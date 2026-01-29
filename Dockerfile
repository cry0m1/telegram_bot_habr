FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY habr_tg_bot.py .

ENTRYPOINT ["python", "/app/habr_tg_bot.py"]
CMD ["--mode", "bot"]
