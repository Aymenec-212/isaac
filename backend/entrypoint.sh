#!/bin/sh
# Migrations run explicitly before the server accepts traffic (skill 29).
set -e
echo "running migrations..."
alembic upgrade head
echo "seeding pilot organization..."
python -m mosaique.app.seed
exec "$@"
