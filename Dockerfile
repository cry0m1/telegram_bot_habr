FROM python:3.14-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENV PATH="/app/.venv/bin:${PATH}"

RUN python -m pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project

COPY habr_tg_bot.py .

ENTRYPOINT ["python", "/app/habr_tg_bot.py"]
CMD ["--mode", "bot"]
