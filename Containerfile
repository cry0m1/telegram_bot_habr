FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENV PATH="/app/.venv/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project

COPY habr_tg_bot.py .

ENTRYPOINT ["python", "habr_tg_bot.py"]
CMD ["--mode", "bot"]
