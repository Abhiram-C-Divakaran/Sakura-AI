#!/usr/bin/env bash
# Sakura AI — PostgreSQL Backup Restore Verification Script
# Verifies client/server version compatibility and SHA-256 checksum integrity,
# restores a .dump archive into a temporary database, strictly asserts
# alembic_version head, required core tables, pgvector extension, restored user data,
# and real non-null 1536-dim vector survival + cosine distance execution,
# and always drops the temporary database on exit.
#
# Usage:
#   PGPASSWORD=... [EXPECTED_ALEMBIC_HEAD=...] [REQUIRED_MIN_USERS=1] [EXPECTED_USER_USERNAME=...] \
#     [REQUIRE_CHECKSUM=true] [REQUIRE_PGVECTOR=true] [REQUIRE_RESTORED_VECTOR=true] \
#     ./verify_restore.sh /var/backups/sakura/postgres/sakura_anime_ai_20261126T000000Z.dump

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <path-to-backup.dump>" >&2
  exit 1
fi

DUMP_FILE="$1"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
EXPECTED_ALEMBIC_HEAD="${EXPECTED_ALEMBIC_HEAD:-}"
REQUIRED_MIN_USERS="${REQUIRED_MIN_USERS:-0}"
EXPECTED_USER_USERNAME="${EXPECTED_USER_USERNAME:-}"
REQUIRE_CHECKSUM="${REQUIRE_CHECKSUM:-true}"
REQUIRE_PGVECTOR="${REQUIRE_PGVECTOR:-true}"
REQUIRE_RESTORED_VECTOR="${REQUIRE_RESTORED_VECTOR:-false}"
VERIFY_DB="sakura_restore_verify_$(date -u +%Y%m%d%H%M%S)_$$"

if [[ -z "${PGPASSWORD:-}" ]]; then
  echo "ERROR: PGPASSWORD must be set in environment." >&2
  exit 1
fi

for bin in pg_restore psql sha256sum; do
  if ! command -v "${bin}" >/dev/null 2>&1; then
    echo "ERROR: Required tool '${bin}' not found in PATH." >&2
    exit 1
  fi
done

if [[ ! -f "${DUMP_FILE}" ]]; then
  echo "ERROR: Dump file not found: ${DUMP_FILE}" >&2
  exit 1
fi

if [[ ! -s "${DUMP_FILE}" ]]; then
  echo "ERROR: Dump file is empty: ${DUMP_FILE}" >&2
  exit 1
fi

CLIENT_VER_STR="$(pg_restore --version)"
CLIENT_MAJOR="$(echo "${CLIENT_VER_STR}" | grep -oE '[0-9]+(\.[0-9]+)?' | head -n1 | cut -d. -f1)"
SERVER_VER_NUM="$(psql --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT}" --username="${POSTGRES_USER}" -d postgres -Atc "SHOW server_version_num;")"
SERVER_VER_STR="$(psql --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT}" --username="${POSTGRES_USER}" -d postgres -Atc "SHOW server_version;")"
SERVER_MAJOR="$((SERVER_VER_NUM / 10000))"

echo "[verify] Client: ${CLIENT_VER_STR} (major=${CLIENT_MAJOR}) | Server: PostgreSQL ${SERVER_VER_STR} (major=${SERVER_MAJOR})"
if [[ "${CLIENT_MAJOR}" != "${SERVER_MAJOR}" ]]; then
  echo "ERROR: PostgreSQL client major version (${CLIENT_MAJOR}) does not match server major version (${SERVER_MAJOR})." >&2
  exit 1
fi

# Strict SHA-256 sidecar verification before restoration
if [[ "${REQUIRE_CHECKSUM}" == "true" ]]; then
  if [[ ! -f "${DUMP_FILE}.sha256" ]]; then
    echo "ERROR: Required SHA-256 checksum sidecar missing: ${DUMP_FILE}.sha256" >&2
    exit 1
  fi
  echo "[verify] Checking SHA-256 checksum sidecar..."
  sha256sum -c "${DUMP_FILE}.sha256"
elif [[ -f "${DUMP_FILE}.sha256" ]]; then
  echo "[verify] Checking SHA-256 checksum sidecar..."
  sha256sum -c "${DUMP_FILE}.sha256"
fi

# Validate dump archive catalog before creating verification database
echo "[verify] Validating archive catalog..."
pg_restore --list "${DUMP_FILE}" >/dev/null

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

echo "[verify] Asserting restored Alembic version, core tables, pgvector extension, and data integrity..."

# 1. Assert alembic_version exists and matches expected head when provided
RESTORED_ALEMBIC_COUNT="$(psql --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT}" --username="${POSTGRES_USER}" \
  -d "${VERIFY_DB}" -Atv ON_ERROR_STOP=1 -c "SELECT count(*) FROM alembic_version;")"
if [[ "${RESTORED_ALEMBIC_COUNT}" -lt 1 ]]; then
  echo "ERROR: Restored alembic_version table is empty!" >&2
  exit 1
fi

RESTORED_ALEMBIC_HEAD="$(psql --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT}" --username="${POSTGRES_USER}" \
  -d "${VERIFY_DB}" -Atv ON_ERROR_STOP=1 -c "SELECT version_num FROM alembic_version LIMIT 1;")"
echo "[verify] Restored alembic_version = ${RESTORED_ALEMBIC_HEAD}"

if [[ -n "${EXPECTED_ALEMBIC_HEAD}" && "${RESTORED_ALEMBIC_HEAD}" != "${EXPECTED_ALEMBIC_HEAD}" ]]; then
  echo "ERROR: Restored alembic_version (${RESTORED_ALEMBIC_HEAD}) != expected (${EXPECTED_ALEMBIC_HEAD})." >&2
  exit 1
fi

# 2. Assert all required core tables exist in public schema
REQUIRED_TABLES=(
  "users"
  "conversations"
  "messages"
  "documents"
  "document_chunks"
  "coding_jobs"
  "coding_tasks"
  "coding_task_events"
  "background_tasks"
  "scheduled_tasks"
  "scheduled_task_runs"
  "image_generation_jobs"
  "image_variation_batches"
  "storage_deletion_outbox"
  "user_usage_quotas"
  "user_data_exports"
  "account_audit_events"
)

MISSING_TABLES=()
for tbl in "${REQUIRED_TABLES[@]}"; do
  EXISTS="$(psql --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT}" --username="${POSTGRES_USER}" \
    -d "${VERIFY_DB}" -Atv ON_ERROR_STOP=1 \
    -c "SELECT CASE WHEN to_regclass('public.${tbl}') IS NOT NULL THEN 1 ELSE 0 END;")"
  if [[ "${EXISTS}" != "1" ]]; then
    MISSING_TABLES+=("${tbl}")
  fi
done

if [[ "${#MISSING_TABLES[@]}" -gt 0 ]]; then
  echo "ERROR: Restored database is missing required core tables: ${MISSING_TABLES[*]}" >&2
  exit 1
fi

TABLE_COUNT="$(psql --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT}" --username="${POSTGRES_USER}" \
  -d "${VERIFY_DB}" -Atv ON_ERROR_STOP=1 -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';")"
echo "[verify] Verified ${#REQUIRED_TABLES[@]} required core tables (total public tables: ${TABLE_COUNT})."

# 3. Assert pgvector extension and native vector(1536) column when required
if [[ "${REQUIRE_PGVECTOR}" == "true" ]]; then
  HAS_VECTOR="$(psql --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT}" --username="${POSTGRES_USER}" \
    -d "${VERIFY_DB}" -Atv ON_ERROR_STOP=1 \
    -c "SELECT count(*) FROM pg_extension WHERE extname = 'vector';")"
  if [[ "${HAS_VECTOR}" != "1" ]]; then
    echo "ERROR: Required pgvector extension ('vector') is missing in restored database." >&2
    exit 1
  fi
  EMB_TYPE="$(psql --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT}" --username="${POSTGRES_USER}" \
    -d "${VERIFY_DB}" -Atv ON_ERROR_STOP=1 \
    -c "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a JOIN pg_class c ON a.attrelid = c.oid WHERE c.relname = 'document_chunks' AND a.attname = 'embedding' AND NOT a.attisdropped;")"
  if [[ "${EMB_TYPE}" != "vector(1536)" ]]; then
    echo "ERROR: Expected document_chunks.embedding type 'vector(1536)', found '${EMB_TYPE}'." >&2
    exit 1
  fi
  echo "[verify] Verified pgvector extension and document_chunks.embedding (${EMB_TYPE})."
fi

# 4. Assert real non-null 1536-dim vector survives backup/restore & cosine operator works
if [[ "${REQUIRE_RESTORED_VECTOR}" == "true" ]]; then
  VEC_COUNT="$(psql --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT}" --username="${POSTGRES_USER}" \
    -d "${VERIFY_DB}" -Atv ON_ERROR_STOP=1 \
    -c "SELECT count(*) FROM document_chunks WHERE embedding IS NOT NULL;")"
  if [[ "${VEC_COUNT}" -lt 1 ]]; then
    echo "ERROR: Expected at least 1 restored non-null vector in document_chunks, found ${VEC_COUNT}." >&2
    exit 1
  fi
  VEC_DIMS="$(psql --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT}" --username="${POSTGRES_USER}" \
    -d "${VERIFY_DB}" -Atv ON_ERROR_STOP=1 \
    -c "SELECT vector_dims(embedding) FROM document_chunks WHERE embedding IS NOT NULL LIMIT 1;")"
  if [[ "${VEC_DIMS}" != "1536" ]]; then
    echo "ERROR: Expected restored vector dimension 1536, found '${VEC_DIMS}'." >&2
    exit 1
  fi
  SELF_DIST="$(psql --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT}" --username="${POSTGRES_USER}" \
    -d "${VERIFY_DB}" -Atv ON_ERROR_STOP=1 \
    -c "SELECT ROUND((embedding <=> embedding)::numeric, 6) FROM document_chunks WHERE embedding IS NOT NULL LIMIT 1;")"
  echo "[verify] Verified ${VEC_COUNT} restored non-null vector(1536) row(s); cosine self-distance=${SELF_DIST}."
fi

# 5. Assert restored row data readability and expected probe rows
USER_COUNT="$(psql --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT}" --username="${POSTGRES_USER}" \
  -d "${VERIFY_DB}" -Atv ON_ERROR_STOP=1 -c "SELECT count(*) FROM users;")"
echo "[verify] Restored user_count = ${USER_COUNT}"

if [[ "${REQUIRED_MIN_USERS}" -gt 0 && "${USER_COUNT}" -lt "${REQUIRED_MIN_USERS}" ]]; then
  echo "ERROR: Expected at least ${REQUIRED_MIN_USERS} user row(s) after restore, found ${USER_COUNT}." >&2
  exit 1
fi

if [[ -n "${EXPECTED_USER_USERNAME}" ]]; then
  FOUND_PROBE="$(psql --host="${POSTGRES_HOST}" --port="${POSTGRES_PORT}" --username="${POSTGRES_USER}" \
    -d "${VERIFY_DB}" -Atv ON_ERROR_STOP=1 -v uname="${EXPECTED_USER_USERNAME}" \
    -c "SELECT count(*) FROM users WHERE username = :'uname';")"
  if [[ "${FOUND_PROBE}" -lt 1 ]]; then
    echo "ERROR: Expected restored probe user '${EXPECTED_USER_USERNAME}' was not found in restored DB!" >&2
    exit 1
  fi
  echo "[verify] Verified seeded probe user '${EXPECTED_USER_USERNAME}' survived backup & restore."
fi

echo "[verify] SUCCESS: Backup ${DUMP_FILE} restored and verified cleanly."
