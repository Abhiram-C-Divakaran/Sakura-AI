#!/usr/bin/env bash
# Sakura AI — PostgreSQL Logical Backup Script
# Creates a compressed custom-format pg_dump with SHA-256 checksum,
# client/server major-version compatibility verification, and retention pruning.
#
# Required env vars:
#   POSTGRES_HOST (default: localhost)
#   POSTGRES_PORT (default: 5432)
#   POSTGRES_USER (default: postgres)
#   POSTGRES_DB   (default: anime_ai)
#   PGPASSWORD    (required; never pass passwords on CLI args)
#   BACKUP_DIR    (default: /var/backups/sakura/postgres)
#   RETENTION_DAYS (default: 14)

set -euo pipefail

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-anime_ai}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/sakura/postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

if [[ -z "${PGPASSWORD:-}" ]]; then
  echo "ERROR: PGPASSWORD must be set in environment." >&2
  exit 1
fi

for bin in pg_dump psql sha256sum; do
  if ! command -v "${bin}" >/dev/null 2>&1; then
    echo "ERROR: Required tool '${bin}' not found in PATH." >&2
    exit 1
  fi
done

CLIENT_VER_STR="$(pg_dump --version)"
CLIENT_MAJOR="$(echo "${CLIENT_VER_STR}" | grep -oE '[0-9]+(\.[0-9]+)?' | head -n1 | cut -d. -f1)"
SERVER_VER_NUM="$(psql --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT}" --username="${POSTGRES_USER}" -d "${POSTGRES_DB}" -Atc "SHOW server_version_num;")"
SERVER_VER_STR="$(psql --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT}" --username="${POSTGRES_USER}" -d "${POSTGRES_DB}" -Atc "SHOW server_version;")"
SERVER_MAJOR="$((SERVER_VER_NUM / 10000))"

echo "[backup] Client: ${CLIENT_VER_STR} (major=${CLIENT_MAJOR}) | Server: PostgreSQL ${SERVER_VER_STR} (major=${SERVER_MAJOR})"
if [[ "${CLIENT_MAJOR}" != "${SERVER_MAJOR}" ]]; then
  echo "ERROR: PostgreSQL client major version (${CLIENT_MAJOR}) does not match server major version (${SERVER_MAJOR})." >&2
  echo "ERROR: Use a matching PostgreSQL ${SERVER_MAJOR} client (e.g., official postgres:${SERVER_MAJOR} container) to avoid incompatible dump directives." >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="${BACKUP_DIR}/sakura_${POSTGRES_DB}_${TIMESTAMP}.dump"

echo "[backup] Starting pg_dump for ${POSTGRES_DB} -> ${OUT_FILE}"
pg_dump \
  --host="${POSTGRES_HOST}" \
  --port="${POSTGRES_PORT}" \
  --username="${POSTGRES_USER}" \
  --format=custom \
  --compress=9 \
  --no-owner \
  --no-privileges \
  --file="${OUT_FILE}" \
  "${POSTGRES_DB}"

if [[ ! -s "${OUT_FILE}" ]]; then
  echo "ERROR: Backup file is empty: ${OUT_FILE}" >&2
  exit 1
fi

sha256sum "${OUT_FILE}" > "${OUT_FILE}.sha256"
echo "[backup] Backup complete ($(du -h "${OUT_FILE}" | cut -f1)). Checksum written to ${OUT_FILE}.sha256"

# Prune backups older than RETENTION_DAYS
find "${BACKUP_DIR}" -type f \( -name "sakura_${POSTGRES_DB}_*.dump" -o -name "sakura_${POSTGRES_DB}_*.dump.sha256" \) -mtime "+${RETENTION_DAYS}" -delete
echo "[backup] Retention pruning complete (kept last ${RETENTION_DAYS} days)."
