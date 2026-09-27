#!/usr/bin/env bash
# One-time migration from the MedicareAI infrastructure identifiers to MedAxis.
# The script preserves the old installation until the new stack passes health checks.
set -euo pipefail

if [[ "${MEDAXIS_MIGRATION_APPROVED:-0}" != "1" ]]; then
    echo "Set MEDAXIS_MIGRATION_APPROVED=1 to authorize the production migration."
    exit 1
fi

PROJECT_DIR="${PROJECT_DIR:-/opt/MedAxis}"
OLD_PROJECT_DIR="${OLD_PROJECT_DIR:-/opt/MediCareAI-Agent}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/medaxis}"
MARKER="${MARKER:-$BACKUP_DIR/migration-complete}"
OLD_DB_CONTAINER="${OLD_DB_CONTAINER:-medicareai-postgres}"
OLD_REDIS_CONTAINER="${OLD_REDIS_CONTAINER:-medicareai-redis}"
OLD_VALKEY_CONTAINER="${OLD_VALKEY_CONTAINER:-medicareai-valkey}"
OLD_DB_NAME="${OLD_DB_NAME:-medicareai}"

cd "$PROJECT_DIR"
if [[ ! -f .env ]]; then
    echo "Missing $PROJECT_DIR/.env"
    exit 1
fi

set -a
. ./.env
set +a

DB_USER="${DB_USER:-postgres}"
DB_NAME="${DB_NAME:-medaxis}"
NEW_DB_CONTAINER="${NEW_DB_CONTAINER:-medaxis-postgres}"
NEW_REDIS_VOLUME="${NEW_REDIS_VOLUME:-medaxis_redis_data}"
NEW_VALKEY_VOLUME="${NEW_VALKEY_VOLUME:-medaxis_valkey_data}"

if [[ -f "$MARKER" ]]; then
    echo "Migration already completed: $MARKER"
    exit 0
fi

for command in docker curl; do
    command -v "$command" >/dev/null || { echo "Required command not found: $command"; exit 1; }
done

docker compose -f "$COMPOSE_FILE" config >/dev/null
if [[ "${MEDAXIS_MIGRATION_DRY_RUN:-0}" == "1" ]]; then
    echo "MedAxis migration dry run passed: compose configuration is valid."
    echo "The real run will back up PostgreSQL, copy cache volumes, migrate uploads, and recreate containers."
    exit 0
fi

mkdir -p "$BACKUP_DIR"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DB_BACKUP="$BACKUP_DIR/${OLD_DB_NAME}-${TIMESTAMP}.dump"

if ! docker inspect "$OLD_DB_CONTAINER" >/dev/null 2>&1; then
    echo "Old database container not found: $OLD_DB_CONTAINER"
    exit 1
fi

if [[ "$(docker inspect -f '{{.State.Running}}' "$OLD_DB_CONTAINER" 2>/dev/null || true)" != "true" ]]; then
    echo "Old database container is not running: $OLD_DB_CONTAINER"
    exit 1
fi

volume_for() {
    local container="$1"
    local destination="$2"
    docker inspect -f "{{range .Mounts}}{{if eq .Destination \"$destination\"}}{{.Name}}{{end}}{{end}}" "$container" 2>/dev/null || true
}

copy_volume() {
    local old_volume="$1"
    local new_volume="$2"
    [[ -n "$old_volume" ]] || return 0
    docker volume create "$new_volume" >/dev/null
    docker run --rm -v "$old_volume:/from:ro" -v "$new_volume:/to" alpine:3.20 sh -c 'cp -a /from/. /to/'
}

if docker inspect "$OLD_REDIS_CONTAINER" >/dev/null 2>&1; then
    docker exec "$OLD_REDIS_CONTAINER" redis-cli SAVE >/dev/null || true
    OLD_REDIS_VOLUME="$(volume_for "$OLD_REDIS_CONTAINER" /data)"
else
    OLD_REDIS_VOLUME=""
fi
if docker inspect "$OLD_VALKEY_CONTAINER" >/dev/null 2>&1; then
    docker exec "$OLD_VALKEY_CONTAINER" valkey-cli SAVE >/dev/null || true
    OLD_VALKEY_VOLUME="$(volume_for "$OLD_VALKEY_CONTAINER" /data)"
else
    OLD_VALKEY_VOLUME=""
fi

# Keep uploaded medical documents available under the new checkout path.
if [[ -d "$OLD_PROJECT_DIR/backend/uploads" ]]; then
    mkdir -p "$PROJECT_DIR/backend/uploads"
    cp -a "$OLD_PROJECT_DIR/backend/uploads/." "$PROJECT_DIR/backend/uploads/"
fi

# Stop only the old application containers. Volumes remain untouched for rollback.
for container in "$OLD_DB_CONTAINER" "$OLD_REDIS_CONTAINER" "$OLD_VALKEY_CONTAINER" medicareai-backend medicareai-celery medicareai-celery-beat medicareai-frontend medicareai-searxng; do
    if docker inspect "$container" >/dev/null 2>&1; then
        docker stop "$container" >/dev/null || true
    fi
done

copy_volume "$OLD_REDIS_VOLUME" "$NEW_REDIS_VOLUME"
copy_volume "$OLD_VALKEY_VOLUME" "$NEW_VALKEY_VOLUME"

echo "Starting the new database and cache services..."
docker compose -f "$COMPOSE_FILE" up -d postgres redis valkey
for _ in {1..60}; do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$NEW_DB_CONTAINER" 2>/dev/null || true)"
    [[ "$status" == "healthy" ]] && break
    sleep 2
done
status="$(docker inspect -f '{{.State.Health.Status}}' "$NEW_DB_CONTAINER" 2>/dev/null || true)"
[[ "$status" == "healthy" ]] || { echo "New PostgreSQL did not become healthy."; exit 1; }

echo "Restoring PostgreSQL data into $DB_NAME..."
docker cp "$DB_BACKUP" "$NEW_DB_CONTAINER:/tmp/medaxis-restore.dump"
docker exec "$NEW_DB_CONTAINER" pg_restore -U "$DB_USER" -d "$DB_NAME" --clean --if-exists --no-owner /tmp/medaxis-restore.dump
docker exec "$NEW_DB_CONTAINER" rm -f /tmp/medaxis-restore.dump

echo "Starting the complete MedAxis stack..."
docker compose -f "$COMPOSE_FILE" up -d --force-recreate
for _ in {1..60}; do
    if curl -fsS http://127.0.0.1:8000/health >/dev/null; then
        break
    fi
    sleep 2
done
curl -fsS http://127.0.0.1:8000/health >/dev/null

docker exec medaxis-backend alembic upgrade head

if command -v nginx >/dev/null && [[ -f /etc/letsencrypt/live/medaxis.online/fullchain.pem ]]; then
    nginx -t
    systemctl reload nginx
else
    echo "Nginx reload skipped: provision /etc/letsencrypt/live/medaxis.online first."
fi

printf 'completed_at=%s\nbackup=%s\n' "$TIMESTAMP" "$DB_BACKUP" > "$MARKER"
echo "MedAxis migration completed. Keep the old volumes and backup until rollback is no longer required."
