#!/bin/sh
# Needs: LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LK_REDIS_HOST/PORT/USER/PASSWORD (not REDIS_*,
# which livekit-server reads as flag overrides),
# and a TCP proxy on port 7881 (Railway sets RAILWAY_TCP_PROXY_DOMAIN/PORT).
set -e
: "${RAILWAY_TCP_PROXY_DOMAIN:?add a TCP proxy to this service on port 7881}"
TCP_PORT="${RAILWAY_TCP_PROXY_PORT:?}"
NODE_IP="$(dig +short A "$RAILWAY_TCP_PROXY_DOMAIN" | tail -n1)"
echo "[start] advertising ICE-TCP ${NODE_IP}:${TCP_PORT} (${RAILWAY_TCP_PROXY_DOMAIN})"

cat > /tmp/livekit.yaml <<YAML
port: 7880
rtc:
  tcp_port: ${TCP_PORT}
  port_range_start: 50000
  port_range_end: 50200
  use_external_ip: false
  node_ip: ${NODE_IP}
keys:
  ${LIVEKIT_API_KEY}: ${LIVEKIT_API_SECRET}
redis:
  address: ${LK_REDIS_HOST}:${LK_REDIS_PORT}
  username: ${LK_REDIS_USER:-default}
  password: ${LK_REDIS_PASSWORD}
logging:
  level: info
YAML

# The proxy delivers to 7881; LiveKit listens on (and advertises) the public port.
socat TCP-LISTEN:7881,fork,reuseaddr TCP:127.0.0.1:${TCP_PORT} &
exec livekit-server --config /tmp/livekit.yaml --bind 0.0.0.0
