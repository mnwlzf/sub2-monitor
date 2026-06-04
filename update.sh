#!/bin/sh
set -eu

APP_NAME="${APP_NAME:-sub-monitor}"
SERVICE_NAME="${SERVICE_NAME:-sub-monitor}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:18080/api/health}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-60}"

log() {
  printf '[%s] %s\n' "$APP_NAME" "$*"
}

error() {
  printf '[%s] ERROR: %s\n' "$APP_NAME" "$*" >&2
}

find_compose() {
  if docker compose version >/dev/null 2>&1; then
    printf 'docker compose'
    return 0
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    printf 'docker-compose'
    return 0
  fi

  error "docker compose or docker-compose is required."
  return 1
}

wait_for_health() {
  if ! command -v curl >/dev/null 2>&1; then
    log "curl is not installed; skipping local health check."
    return 0
  fi

  log "Waiting for health check: $HEALTH_URL"
  start_time="$(date +%s)"

  while :; do
    if curl -fsS --connect-timeout 2 --max-time 5 "$HEALTH_URL" >/dev/null 2>&1; then
      log "Health check passed."
      return 0
    fi

    now="$(date +%s)"
    elapsed=$((now - start_time))
    if [ "$elapsed" -ge "$HEALTH_TIMEOUT_SECONDS" ]; then
      log "Health check did not pass within ${HEALTH_TIMEOUT_SECONDS}s."
      log "Recent logs:"
      # shellcheck disable=SC2086
      $COMPOSE_CMD logs --tail=80 "$SERVICE_NAME" || true
      return 1
    fi

    sleep 2
  done
}

COMPOSE_CMD="$(find_compose)"

log "Pulling latest image..."
# shellcheck disable=SC2086
$COMPOSE_CMD pull "$SERVICE_NAME"

log "Starting service..."
# shellcheck disable=SC2086
$COMPOSE_CMD up -d "$SERVICE_NAME"

log "Current status:"
# shellcheck disable=SC2086
$COMPOSE_CMD ps "$SERVICE_NAME"

wait_for_health
