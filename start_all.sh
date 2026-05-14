#!/bin/bash
set -e

# Start Postgres (audit + checkpointer store) and wait until it is ready.

echo "Starting Postgres via docker compose..."
docker compose up -d postgres

echo "Waiting for Postgres to accept connections..."
until docker compose exec -T postgres pg_isready -U hitl -d hitl_audit >/dev/null 2>&1; do
  sleep 1
done

echo ""
echo "Postgres is ready:    postgresql://hitl:hitl@localhost:1505/hitl_audit"
echo ""
echo "Next steps:"
echo "  uv sync                                    # install deps"
echo "  cp .env.example .env && \$EDITOR .env       # add OPENROUTER_API_KEY"
echo "  gh auth login                              # so the agent can fetch PRs"
echo "  uv run python exercises/exercise_4_audit.py \\"
echo "        --pr https://github.com/VinUni-AI20k/PR-Demo/pull/2"
echo ""
echo "Stop with: docker compose down"
