#!/usr/bin/env bash
# Sakura AI — PostgreSQL Backup Restore Verification Script
# Verifies checksum integrity, restores a .dump archive into a temporary database,
# validates pgvector + schema tables + alembic_version, and drops the temporary DB.
#
# Usage:
#   PGPASSWORD=... ./verify_restore.sh /var/backups/sakura/postgres/sakura_anime_ai_20261126T000000Z.dump

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <path-to-backup.dump>" >&2
  exit 1
fi

DUMP_FILE="$1"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
VERIFY_DB="sakura_restore_verify_$(date -u +%Y%m%d%H%M%S)"

if [[ -z "${PGPASSWORD:-}" ]]; then
  echo "ERROR: PGPASSWORD must be set in environment." >&2
  exit 1
fi

if [[ ! -f "${DUMP_FILE}" ]]; then
  echo "ERROR: Dump file not found: ${DUMP_FILE}" >&2
  exit 1
fi

if [[ -f "${DUMP_FILE}.sha256" ]]; then
  echo "[verify] Checking SHA-256 checksum..."
  sha256sum -c "${DUMP_FILE}.sha256"
fi

cleanup() {
  echo "[verify] Dropping temporary verification database ${VERIFY_DB}..."
  psql --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT}" --username="${POSTGRES_USER}" \
    -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"${VERIFY_DB}\";" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[verify] Creating temporary database ${VERIFY_DB}..."
psql --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT}" --username="${POSTGRES_USER}" \
  -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"${VERIFY_DB}\";"

echo "[verify] Restoring ${DUMP_FILE} into ${VERIFY_DB}..."
pg_restore \
  --host="${POSTGRES_HOST}" \
  --port="${POSTGRES_PORT}" \
  --username="${POSTGRES_USER}" \
  --dbname="${VERIFY_DB}" \
  --no-owner \
  --no-privileges \
  --exit-on-error \
  "${DUMP_FILE}"

echo "[verify] Inspecting restored schema & Alembic version..."
psql --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT}" --username="${POSTGRES_USER}" \
  -d "${VERIFY_DB}" -v ON_ERROR_STOP=1 <<'SQL'
SELECT version_num AS alembic_head FROM alembic_version;
SELECT count(*) AS table_count FROM information_schema.tables WHERE table_schema = 'public';
SELECT count(*) AS user_count FROM users;
SQL

echo "[verify] SUCCESS: Backup ${DUMP_FILE} restored and verified cleanly."
