import asyncio
import json
import logging
import os
import shlex

import aiohttp
import memcache
import requests
from aiohttp import ClientResponseError
from bs4 import BeautifulSoup
from nats.aio.client import Client as NATS
from telegram import Bot, Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# ================== CONFIG ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
NATS_SUBJECT = "habr.requests"
NATS_URL = "nats://nats:4222"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = (
    "nvidia/nemotron-3-nano-30b-a3b:free"  # meta-llama/llama-3.3-70b-instruct:free
)
AI_CACHE_TTL = 60 * 60 * 24 * 7  # 7 days
WEEKLY_NUM_OF_PAGES = 6  # 20 articles per page
BATCH_SIZE = 5

# ================== CONST ==================

COMPANY_NAMES = [
    "AstraLinux",
    "FirstVDS",
    "PatientZero",
    "RUVDS",
    "Selectel",
    "Timeweb Cloud",
    "Блог компании 1С-Битрикс",
    "Блог компании 2ГИС",
    "Блог компании ABBYY",
    "Блог компании Acronis",
    "Блог компании Altoros",
    "Блог компании Artezio",
    "Блог компании Beget",
    "Блог компании CloudMTS",
    "Блог компании CROC",
    "Блог компании DataArt",
    "Блог компании DataLine",
    "Блог компании EPAM",
    "Блог компании GeekBrains",
    "Блог компании GridGain",
    "Блог компании Huawei",
    "Блог компании IBS",
    "Блог компании ICL Services",
    "Блог компании Infowatch",
    "Блог компании Jet Infosystems",
    "Блог компании JetBrains",
    "Блог компании JetBrains",
    "Блог компании Kaspersky",
    "Блог компании Luxoft",
    "Блог компании Mail.ru Cloud Solutions",
    "Блог компании Microsoft",
    "Блог компании NIX Solutions",
    "Блог компании Oracle",
    "Блог компании OTUS",
    "Блог компании Parallels",
    "Блог компании Positive Technologies",
    "Блог компании QSOFT",
    "Блог компании Reg.ru",
    "Блог компании RuCore",
    "Блог компании SAP",
    "Блог компании Skillbox",
    "Блог компании SkillFactory",
    "Блог компании Softline",
    "Блог компании Tinkoff Tech",
    "Блог компании UltraVDS",
    "Блог компании VK Tech",
    "Блог компании VK",
    "Блог компании VMware",
    "Блог компании Альфа-Банк",
    "Блог компании ВКонтакте",
    "Блог компании КРОК",
    "Блог компании Лаборатория Касперского",
    "Блог компании Ланит",
    "Блог компании Летай",
    "Блог компании МегаФон",
    "Блог компании Нетология",
    "Блог компании ПИК",
    "Блог компании Ред Софт",
    "Блог компании Ростелеком-Солар",
    "Блог компании Ростелеком",
    "Блог компании СберТех",
    "Блог компании Фоксфорд",
    "Блог компании ЦИАН",
    "Блог компании Цифра",
    "Блог компании Эльбрус",
    "Блог компании Яндекс.Практикум",
    "Блог компании Яндекс",
    "МТС",
]

HUBS = [
    "История IT",
    "Научно-популярное",
    "Читальный зал",
]

AUTHORS = [
    "BMARVIN",
    "Catx2",
    "DmitryShkoliar",
    "its_capitan",
    "ITVDN",
    "OlegSivchenko",
    "pilot_artem",
    "Sivchenko_translate",
    "slava_rumin",
    "SLY_G",
    "timonin",
    "the_annnisss",  # LLM slop
    "AlekseiPodkletnov",
    "xonika9",  # LLM slop
    "double_bobik",  # ad network | SEO garbage
    "cyberscoper",  # LLM
    "ScriptShaper",  # LLM slop
    "Keshah",  # LLM rewriter
    "varanio",  # rewriter
    "DazzleBizzareAdventure",  # rewriter
    "PSDK_XP",  # rewriter
    "MDyuzhev",  # rewriter
    "tripolskypetr",  # senseless bullshit
]

STOPWORDS = COMPANY_NAMES + HUBS + AUTHORS

# ================== GLOBALS ==================

bot = Bot(token=BOT_TOKEN)
mc = memcache.Client(["memcached:11211"])
http_session: aiohttp.ClientSession | None = None


async def get_http_session():
    global http_session
    if http_session is None or http_session.closed:
        http_session = aiohttp.ClientSession(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Referer": "https://habr.com/",
                "Connection": "keep-alive",
            },
            timeout=aiohttp.ClientTimeout(total=120),
        )
    return http_session


# ================== TELEGRAM ==================


async def handle_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message.text

    print(f"Processing message for user {user_id}")
    print(f"Processing message {message}")

    nc = NATS()
    await nc.connect(servers=[NATS_URL])

    payload = {"user_id": user_id, "message": message}

    if "/stop_words" in message:
        response = [
            "Компании:\n" + "\n".join(f"- {w}" for w in COMPANY_NAMES),
            "Хабы:\n" + "\n".join(f"- {w}" for w in HUBS),
            "Авторы:\n" + "\n".join(f"- {w}" for w in AUTHORS),
        ]
    elif "/propose" in message:
        email_link = "yulik_86@mal.ru"
        response = f"Предложить новое стоп-слово! Мы рассмотрим его в ближайшее время.\n\nОтправить подробности на почту: {email_link}"
    elif "/start" in message:
        response = (
            "Читайте Habr еженедельно\n"
            "• Лучшее за неделю /habr:\n"
            "  + Статьи RationalAnswer\n"
            "  + Топ финансовых новостей за неделю\n"
            "• Помечает бесполезные статьи согласно стоп-слов /stop_words\n"
            "• Проверяет на AI текст /habr_ai"
        )
    elif "/habr_ai" in message:
        response = "⏳ Подождите, мы собираем статьи... (это будет долго... возможно)"
        await nc.publish(NATS_SUBJECT, json.dumps(payload).encode())
    else:
        response = "⏳ Подождите, мы собираем статьи..."
        await nc.publish(NATS_SUBJECT, json.dumps(payload).encode())

    # Sending the response(s)
    if isinstance(response, list):
        for text in response:
            await update.message.reply_text(text)
    else:
        await update.message.reply_text(response)

    await nc.close()


def start_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL, handle_all))
    print("Telegram bot is running...")
    app.run_polling()


# ================== SCRAPING ==================


async def fetch_html(url: str, retries=3, delay=5) -> str:
    session = await get_http_session()
    for attempt in range(retries):
        try:
            async with session.get(url) as r:
                r.raise_for_status()
                return await r.text()
        except ClientResponseError as e:
            if e.status == 503:
                logging.warning(f"503 error on {url}, retrying in {delay} seconds...")
                await asyncio.sleep(delay)
            else:
                raise
    logging.error(f"Failed to fetch {url} after {retries} retries due to 503")
    return ""


def extract_article(post):
    def t(sel):
        el = post.select_one(sel)
        return el.text.strip() if el else ""

    def h(sel):
        el = post.select_one(sel)
        return el.get("href", "") if el else ""

    return {
        "topic": t("a.tm-publication-hub__link span"),
        "title": t("a.tm-title__link"),
        "link": h("a.readmore"),
        "snippet": t("div.article-formatted-body"),
        "author": t("a.tm-user-info__username"),
    }


def strike_stopwords(text, stopwords):
    text_l = text.lower()
    for w in stopwords:
        if w.lower() in text_l:
            return f"[🗑️] {text}"
    return text


async def parse_habr_articles():
    articles_raw = []

    # TOP WEEKLY
    html = await fetch_html("https://habr.com/ru/articles/top/weekly/")
    soup = BeautifulSoup(html, "html.parser")

    pages = min(
        max(
            [
                int(a.text)
                for a in soup.select("a.tm-pagination__page")
                if a.text.isdigit()
            ]
            or [1]
        ),
        WEEKLY_NUM_OF_PAGES,
    )

    urls = [
        f"https://habr.com/ru/articles/top/weekly/page{i}/"
        for i in range(1, pages + 1)  # 20 articles per page
    ]
    pages_html = await asyncio.gather(*(fetch_html(u) for u in urls))

    for html in pages_html:
        soup = BeautifulSoup(html, "html.parser")
        for post in soup.select("article.tm-articles-list__item"):
            articles_raw.append(extract_article(post))

    # RationalAnswer WEEKLY
    html = await fetch_html("https://habr.com/ru/users/RationalAnswer/articles/")
    soup = BeautifulSoup(html, "html.parser")
    for post in soup.select("article.tm-articles-list__item")[: (BATCH_SIZE + 1)]:
        articles_raw.append(extract_article(post))

    # finance WEEKLY
    html = await fetch_html("https://habr.com/ru/hubs/finance/articles/top/weekly/")
    soup = BeautifulSoup(html, "html.parser")
    for post in soup.select("article.tm-articles-list__item")[: (BATCH_SIZE * 2 + 1)]:
        articles_raw.append(extract_article(post))

    seen = set()
    articles = []

    for a in articles_raw:
        if not a["title"] or a["title"] in seen:
            continue
        seen.add(a["title"])

        snippet = a["snippet"].replace("Читать дальше →", "").strip()
        snippet = snippet[:300] + "..."

        articles.append(
            {
                "title": f"{strike_stopwords(a['topic'], STOPWORDS)} "
                f"({strike_stopwords(a['author'], STOPWORDS)}): "
                f"{a['title']}",
                "link": "https://habr.com" + a["link"],
                "snippet": snippet,
            }
        )

    return articles


# ================== AI ==================


# used requests as habr bans async some way
def fetch_article_text(url, max_chars=5000):
    try:
        resp = requests.get(url, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        body = soup.select_one(
            "div.article-formatted-body.article-formatted-body_version-2"
        )

        text = body.get_text(" ", strip=True) if body else ""

        print(f"fetch_article_text: {url}")
        print(f"fetch_article_text: {text[:100]}")

        return text[:max_chars]

    except Exception:
        return ""


async def detect_ai_score_batch(texts: list[str]) -> list[int | None]:
    """
    Sends up to ~8 texts per API call, returns list of AI scores or None.
    """
    combined_prompt = (
        "Estimate AI likelihood for each of the following texts separately.\n\n"
    )
    for i, text in enumerate(texts, 1):
        combined_prompt += f'Text {i}:\n"""\n{text}\n"""\n\n'
    combined_prompt += (
        "Return ONLY a JSON array of integers from 0 to 100, "
        "each representing AI generated article likelihood for the corresponding text."
    )

    session = await get_http_session()

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": combined_prompt}],
        "temperature": 0.0,
    }

    curl_cmd = (
        f"curl -X POST {shlex.quote(url)} "
        f"-H 'Authorization: {headers['Authorization']}' "
        f"-H 'Content-Type: {headers['Content-Type']}' "
        # f"-d {shlex.quote(json.dumps(payload))}"
    )
    print(f"detect_ai_score_batch:\n{curl_cmd}")

    async with session.post(url, headers=headers, json=payload) as r:
        if r.status == 200:
            data = await r.json()
            raw = data["choices"][0]["message"]["content"]
            try:
                scores = json.loads(raw)
                scores = [max(0, min(100, int(s))) for s in scores]
                return scores
            except Exception as e:
                logging.error(
                    f"Failed to parse AI batch scores: {e}, raw response: {raw}"
                )
                return [None] * len(texts)

        error_text = await r.text()
        logging.error(
            f"HTTP error from OpenRouter API:\nStatus: {r.status}\nBody: {error_text}"
        )
        return [None] * len(texts)


async def message_handler(msg):
    data = json.loads(msg.data.decode())
    user_id = data.get("user_id")
    message = data.get("message")

    cache_key = "habr_articles_v1"
    articles = mc.get(cache_key)

    if not articles:
        articles = await parse_habr_articles()
        if articles:
            mc.set(cache_key, articles, time=3600)

    if not articles:
        await bot.send_message(chat_id=user_id, text="Не удалось получить статьи.")
        return

    total_articles = len(articles)

    for start in range(0, total_articles, BATCH_SIZE):
        chunk = articles[start : start + BATCH_SIZE]
        out = []

        # ---- AI MODE ----
        if "/habr_ai" in message:
            cached_scores: list[int | None] = []
            texts_to_check: list[str] = []
            indexes_to_check: list[int] = []

            for i, a in enumerate(chunk):
                cached = mc.get(f"ai_score:{a['link']}")
                if cached is not None:
                    cached_scores.append(cached)
                else:
                    cached_scores.append(None)
                    indexes_to_check.append(i)

            print(f"message_handler:cached_scores = {cached_scores}")
            print(f"message_handler:indexes_to_check = {indexes_to_check}")

            if indexes_to_check:
                loop = asyncio.get_running_loop()
                texts = await asyncio.gather(
                    *(
                        loop.run_in_executor(None, fetch_article_text, chunk[i]["link"])
                        for i in indexes_to_check
                    )
                )

                new_scores = await detect_ai_score_batch(texts)

                for idx, score in zip(indexes_to_check, new_scores):
                    if score is not None:
                        mc.set(
                            f"ai_score:{chunk[idx]['link']}",
                            score,
                            time=AI_CACHE_TTL,
                        )
                    cached_scores[idx] = score

            scores = cached_scores

            for a, score in zip(chunk, scores):
                if score is None:
                    score_text = "🩹AI score retrieval error"
                else:
                    if score >= 75:
                        emoji = "🤖"
                    elif score >= 50:
                        emoji = "⚠️"
                    elif score >= 25:
                        emoji = "👀"
                    else:
                        emoji = "👤"
                    score_text = f"AI score: {score}/100 {emoji}"

                out.append(
                    f"{a['title']}\n"
                    f"{score_text}\n"
                    f"{a['link']}\n"
                    f"{a['snippet']}\n"
                    f"------------------"
                )

        # ---- NORMAL MODE ----
        else:
            for a in chunk:
                out.append(
                    f"{a['title']}\n{a['link']}\n{a['snippet']}\n------------------"
                )

        progress = min(start + BATCH_SIZE, total_articles)
        out.append(f"Processed {progress} of {total_articles} articles.")

        await bot.send_message(chat_id=user_id, text="\n".join(out))

        print("-------------------------")


async def start_worker():
    nc = NATS()
    await nc.connect(servers=[NATS_URL])

    await nc.subscribe(NATS_SUBJECT, cb=message_handler)
    print("Worker is listening for messages...")
    while True:
        await asyncio.sleep(1)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Habr Bot")
    parser.add_argument(
        "--mode",
        choices=["bot", "worker"],
        required=True,
        help='Run mode: "bot" for Telegram bot, "worker" for NATS worker',
    )

    args = parser.parse_args()

    if args.mode == "bot":
        start_bot()
    elif args.mode == "worker":
        asyncio.run(start_worker())


if __name__ == "__main__":
    main()
