#!/usr/bin/env bash
# MedAxis production deployment after the one-time infrastructure migration.
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

echo "MedAxis production deploy"

if [[ ! -f .env ]]; then
    echo ".env not found; copy .env.example and configure production secrets."
    exit 1
fi

docker compose -f "$COMPOSE_FILE" config >/dev/null
docker compose -f "$COMPOSE_FILE" build --no-cache backend
docker compose -f "$COMPOSE_FILE" build --no-cache frontend
docker compose -f "$COMPOSE_FILE" up -d --force-recreate

echo "Running health check..."
for _ in {1..30}; do
    if curl -fsS http://127.0.0.1:8000/health >/dev/null; then
        docker exec medaxis-backend alembic upgrade head
        echo "Deployment successful."
        exit 0
    fi
    sleep 2
done

echo "Health check failed; inspect: docker compose -f $COMPOSE_FILE logs backend"
exit 1
