# telegram_bot_habr

## EN

Read Habr weekly

- Best of the week /habr:
  RationalAnswer Articles
  Top financial news for the week
- Marks useless articles according to stop words /stop_words
- Checks the text /habr_ai for AI

## RU

Читайте Habr еженедельно

- Лучшее за неделю /habr:
  Статьи RationalAnswer
  Топ финансовых новостей за неделю
- Помечает бесполезные статьи согласно стоп-слов /stop_words
- Проверяет на AI текст /habr_ai

```sh
cd telegram_bot_habr

mv .envrc.template .envrc
# edit .envrc
# export variables from .envrc

podman build -t habr_bot_worker:$(date +%s) -t habr_bot_worker:latest .

podman pod rm -f habr-pod 2>/dev/null || true

podman pod create --name habr-pod -p 127.0.0.1:4222:4222
podman run -d --rm --pod habr-pod --name nats docker.io/library/nats
podman run -d --rm --pod habr-pod --name memcached docker.io/library/memcached
podman run -d --rm --pod habr-pod --name habr_bot_bot habr_bot_worker:latest --mode bot # sends jobs via NATS to worker
podman run -d --rm --pod habr-pod --name habr_bot_worker habr_bot_worker:latest --mode worker

podman pod logs -f habr-pod
```
