
# Add essential paths
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Log script start
echo "$(date) - Starting habr pod" >> /tmp/habr-pod-debug.log

# Wait for user runtime directory to be available
while [ ! -d "/run/user/1000" ]; do
    sleep 1
done

# Ensure directory exists
mkdir -p /run/user/1000/containers

# Add environment variables Podman needs
export XDG_RUNTIME_DIR=/run/user/1000
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus

/usr/bin/podman pod exists habr-pod || /usr/bin/podman pod create --name habr-pod -p 127.0.0.1:4222:4222
/usr/bin/podman start nats || /usr/bin/podman run -d --rm --pod habr-pod --name nats docker.io/library/nats
/usr/bin/podman start memcached || /usr/bin/podman run -d --rm --pod habr-pod --name memcached docker.io/library/memcached
/usr/bin/podman start habr_bot_bot || /usr/bin/podman run -d --rm --pod habr-pod --name habr_bot_bot habr_bot_worker:latest --mode bot
/usr/bin/podman start habr_bot_worker || /usr/bin/podman run -d --rm --pod habr-pod --name habr_bot_worker habr_bot_worker:latest --mode worker
