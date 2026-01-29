# telegram_bot_habr

```sh
cd telegram_bot_habr
podman build -t habr_bot_worker:$(date +%s) -t habr_bot_worker:latest .

podman pod rm -f habr-pod 2>/dev/null || true

podman pod create --name habr-pod -p 127.0.0.1:4222:4222
podman run -d --rm --pod habr-pod --name nats docker.io/library/nats
podman run -d --rm --pod habr-pod --name memcached docker.io/library/memcached
podman run -d --rm --pod habr-pod --name habr_bot_bot habr_bot_worker:latest --mode bot
podman run -d --rm --pod habr-pod --name habr_bot_worker habr_bot_worker:latest --mode worker

podman pod logs -f habr-pod
```
