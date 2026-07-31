import asyncio
import datetime
import json
import logging
import os
import shlex
import time

import aiohttp
import memcache
import requests
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import Message
from aiohttp import ClientResponseError
from bs4 import BeautifulSoup
from nats.aio.client import Client as NATS

# ================== CONFIG ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
NATS_SUBJECT = "habr.requests"
NATS_URL = os.getenv("NATS_URL", "nats://nats:4222")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = (
    "nvidia/nemotron-3-nano-30b-a3b:free"  # meta-llama/llama-3.3-70b-instruct:free
)
AI_CACHE_TTL = 60 * 60 * 24 * 7  # 7 days
WEEKLY_NUM_OF_PAGES = 6  # 20 articles per page
BATCH_SIZE = 5
OPENROUTER_REQUEST_TIMEOUT_SEC = 75 # seconds
OPENROUTER_MAX_ATTEMPTS = 2

TELEGRAM_REQUEST_TIMEOUT_SEC = 30
TELEGRAM_SEND_MESSAGE_RETRIES = 3
TELEGRAM_SEND_MESSAGE_RETRY_DELAY = 2
NATS_CONNECT_RETRY_DELAY_SEC = 2

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
    "lunnemone",  #  politics, rewriter
    "Soldier22",  # LLM slop
    "ignatenkosergey",  # LLM slop
    "inkedsymon",  # LLM rewriter
    "strannik96",  # LLM rewriter
    "claudedev",  # LLM slop
    "tripolskypetr",  # trader
    "leonidasthegraet",  # LLM slop
]

STOPWORDS = COMPANY_NAMES + HUBS + AUTHORS

# ================== GLOBALS ==================

# Configure telegram bot
bot = Bot(token=BOT_TOKEN)
mc = memcache.Client(["memcached:11211"])
http_session: aiohttp.ClientSession | None = None


async def send_message_with_retry(
    bot: Bot,
    chat_id: int,
    text: str,
    max_retries: int = TELEGRAM_SEND_MESSAGE_RETRIES,
    retry_delay: float = TELEGRAM_SEND_MESSAGE_RETRY_DELAY,
) -> bool:
    """Send message to Telegram with retry logic for timeout errors."""
    for attempt in range(max_retries):
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            return True
        except (TelegramNetworkError, asyncio.TimeoutError):
            if attempt < max_retries - 1:
                logging.warning(
                    f"Telegram timeout (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s..."
                )
                await asyncio.sleep(retry_delay)
            else:
                logging.error(
                    f"Failed to send message after {max_retries} attempts: timeout/network error"
                )
                return False
        except Exception as e:
            logging.error(f"Error sending message: {e}")
            return False
    return False


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


async def connect_nats_with_retry(max_attempts: int = 0) -> NATS:
    """Connect to NATS with retries. max_attempts=0 means infinite retries."""
    nc = NATS()
    servers = [NATS_URL, "nats://127.0.0.1:4222"]
    attempt = 0

    while True:
        attempt += 1
        try:
            await nc.connect(
                servers=servers,
                allow_reconnect=True,
                reconnect_time_wait=NATS_CONNECT_RETRY_DELAY_SEC,
                max_reconnect_attempts=-1,
            )
            logging.info("Connected to NATS on attempt %d via %s", attempt, servers)
            return nc
        except Exception as e:
            if max_attempts > 0 and attempt >= max_attempts:
                logging.error(
                    "Failed to connect to NATS after %d attempts via %s: %s",
                    attempt,
                    servers,
                    e,
                )
                raise

            logging.warning(
                "NATS connect attempt %d failed via %s: %s. Retrying in %ss.",
                attempt,
                servers,
                e,
                NATS_CONNECT_RETRY_DELAY_SEC,
            )
            await asyncio.sleep(NATS_CONNECT_RETRY_DELAY_SEC)


# ================== TELEGRAM ==================


async def handle_all(msg: Message):
    if msg.from_user is None:
        return

    user_id = msg.from_user.id
    message = msg.text or ""

    print(f"Processing message for user {user_id}")
    print(f"Processing message {message}")

    try:
        nc = await connect_nats_with_retry(max_attempts=3)
    except Exception:
        logging.exception("Unable to connect to NATS in bot handler")
        await msg.answer("⚠️ Сервис временно недоступен. Попробуйте ещё раз позже.")
        return

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
        response = (
            "⏳ Подождите, мы собираем статьи... (это будет долго... возможно) [UTC "
            + str(datetime.datetime.now())
            + "]"
        )
        await nc.publish(NATS_SUBJECT, json.dumps(payload).encode())
    else:
        response = (
            "⏳ Подождите, мы собираем статьи... [UTC "
            + str(datetime.datetime.now())
            + "]"
        )
        await nc.publish(NATS_SUBJECT, json.dumps(payload).encode())

    # Sending the response(s)
    if isinstance(response, list):
        for text in response:
            await msg.answer(text)
    else:
        await msg.answer(response)

    await nc.close()


async def start_bot():
    dp = Dispatcher()
    dp.message.register(handle_all)
    print("Telegram bot is running...")
    await dp.start_polling(bot)


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
    if not texts:
        return [None] * len(texts)

    combined_prompt = (
        "Estimate AI likelihood for each of the following texts separately.\n\n"
    )
    for i, text in enumerate(texts, 1):
        combined_prompt += f'Text {i}:\n"""\n{text}\n"""\n\n'
    combined_prompt += (
        "Use these AI text detection signals when scoring. Treat each match as a signal, "
        "not absolute proof.\n"
        "1. Gerund-participle chains: flag sentences that stack multiple "
        "participles/gerunds in sequence (more than one in one sentence), especially "
        "when they feel mechanical.\n"
        "2. Formulaic constructions: flag phrases like 'serves as a foundation', "
        "'acts as', 'represents' used where plain 'is' would be natural.\n"
        "3. Three-item lists: flag repeated enumerations with exactly three elements; "
        "human text varies list length more often.\n"
        "4. Forced synonym rotation: flag unnatural synonym swaps done only for "
        "variation, such as replacing a stable topic word with near-synonyms without "
        "meaning change.\n"
        "5. Empty lead-ins: flag filler intros such as 'it is important to note', "
        "'it is worth emphasizing', 'it should be considered', 'it cannot be ignored' "
        "when they add no content.\n"
        "6. Promotional adjectives: flag marketing-heavy wording like 'unique', "
        "'stunning', 'leading', 'in the heart of' in neutral or informational contexts.\n"
        "7. English calque patterns: flag direct translation templates like 'plays a "
        "key role', 'in conclusion', 'as of today' when overused.\n"
        "8. Contrast template: flag frequent 'not X, but Y' or 'this is not X, this is "
        "Y' constructions.\n"
        "9. Didactic tone: flag teacher-like directives such as 'let's consider', 'it "
        "is necessary to understand', 'it is critically important'.\n"
        "10. Over-smoothed transitions: flag text that inserts a transition between "
        "nearly every sentence, such as 'moreover', 'in this regard', 'also', creating "
        "artificial flow.\n\n"
        "Return ONLY a JSON array of integers from 0 to 100, each representing the AI "
        "generated article likelihood for the corresponding text based on these signals."
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

    logging.debug(
        "detect_ai_score_batch: sending OpenRouter request (model=%s, texts=%d)",
        OPENROUTER_MODEL,
        len(texts),
    )

    curl_cmd = (
        f"curl -X POST {shlex.quote(url)} "
        f"-H 'Authorization: {headers['Authorization']}' "
        f"-H 'Content-Type: {headers['Content-Type']}' "
        # f"-d {shlex.quote(json.dumps(payload))}"
    )
    print(f"detect_ai_score_batch:\n{curl_cmd}")

    for attempt in range(1, OPENROUTER_MAX_ATTEMPTS + 1):
        started_at = time.monotonic()
        try:
            timeout = aiohttp.ClientTimeout(total=OPENROUTER_REQUEST_TIMEOUT_SEC)
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout,
            ) as r:
                if r.status != 200:
                    error_text = await r.text()
                    raise aiohttp.ClientError(
                        f"OpenRouter status {r.status}: {error_text[:300]}"
                    )

                data = await r.json()
                raw = data["choices"][0]["message"]["content"]
                scores = json.loads(raw)
                scores = [max(0, min(100, int(s))) for s in scores]
                return scores

        except (
            asyncio.TimeoutError,
            aiohttp.ClientError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
            IndexError,
        ) as e:
            elapsed_sec = time.monotonic() - started_at
            if attempt < OPENROUTER_MAX_ATTEMPTS:
                logging.warning(
                    "OpenRouter batch attempt %d/%d failed after %.1fs (%s): %s",
                    attempt,
                    OPENROUTER_MAX_ATTEMPTS,
                    elapsed_sec,
                    type(e).__name__,
                    e,
                )
                continue

            logging.error(
                "OpenRouter batch attempt %d/%d failed after %.1fs (%s): %s",
                attempt,
                OPENROUTER_MAX_ATTEMPTS,
                elapsed_sec,
                type(e).__name__,
                e,
            )
            return [None] * len(texts)

    return [None] * len(texts)


async def message_handler(msg):
    user_id = None
    try:
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
                            loop.run_in_executor(
                                None, fetch_article_text, chunk[i]["link"], 2000
                            )
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

            await send_message_with_retry(bot, user_id, "\n".join(out))

            print("-------------------------")
    except Exception:
        logging.exception("Unhandled exception in message_handler")
        if user_id is not None:
            await send_message_with_retry(
                bot,
                user_id,
                "⚠️ Не удалось обработать запрос полностью. Попробуйте ещё раз позже.",
                max_retries=2,
            )


async def start_worker():
    nc = await connect_nats_with_retry(max_attempts=0)

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
        asyncio.run(start_bot())
    elif args.mode == "worker":
        asyncio.run(start_worker())


if __name__ == "__main__":
    main()
