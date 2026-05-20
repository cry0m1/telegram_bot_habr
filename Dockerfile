FROM python:3.14-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN pip install --no-cache-dir --upgrade uv

COPY requirements.txt .

RUN uv pip install --system -r requirements.txt

COPY habr_tg_bot.py .

ENTRYPOINT ["python", "/app/habr_tg_bot.py"]
CMD ["--mode", "bot"]

