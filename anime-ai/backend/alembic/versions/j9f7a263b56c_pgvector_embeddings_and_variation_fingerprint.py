"""pgvector_embeddings_and_variation_fingerprint

Revision ID: j9f7a263b56c
Revises: i8e6f152a45b
Create Date: 2026-11-27 17:30:00.000000

PostgreSQL Contract Fix:
1. Installs the pgvector extension (`CREATE EXTENSION IF NOT EXISTS vector`) on PostgreSQL.
2. Validates all existing non-null `document_chunks.embedding` JSON rows before conversion:
   every non-null row must be a JSON array of exactly 1536 finite numeric values; any malformed
   or incompatible historical value aborts the migration with actionable diagnostics (including
   offending chunk IDs) rather than silently dropping or corrupting data.
3. Converts `document_chunks.embedding` from JSON to native `vector(1536)` preserving all valid
   embeddings and all NULL values.
4. Remains dialect-aware so SQLite continues using JSON without errors.
5. Adds `request_fingerprint` to `image_variation_batches` for strict idempotency payload matching.

Downgrade Policy:
- On PostgreSQL, converts `document_chunks.embedding` back to JSON preserving all existing vectors
  and NULLs. Intentionally leaves the `vector` extension installed so downgrade cannot break other
  schemas or active sessions depending on the extension.
"""
import math
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'j9f7a263b56c'
down_revision: Union[str, Sequence[str], None] = 'i8e6f152a45b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXPECTED_EMBEDDING_DIM = 1536


def _validate_existing_json_embeddings(bind) -> None:
    """
    Validates every non-null historical `document_chunks.embedding` JSON row before converting
    to PostgreSQL `vector(1536)`. Raises an actionable RuntimeError listing offending row IDs
    and exact validation errors if any row is malformed or has the wrong dimension.
    """
    rows = bind.execute(
        sa.text("SELECT id, embedding FROM document_chunks WHERE embedding IS NOT NULL")
    ).fetchall()

    invalid_rows = []
    for row_id, raw_val in rows:
        if not isinstance(raw_val, list):
            invalid_rows.append(
                f"id={row_id}: expected JSON array of {EXPECTED_EMBEDDING_DIM} numbers, got {type(raw_val).__name__}"
            )
            continue
        if len(raw_val) != EXPECTED_EMBEDDING_DIM:
            invalid_rows.append(
                f"id={row_id}: expected dimension {EXPECTED_EMBEDDING_DIM}, got {len(raw_val)}"
            )
            continue
        bad_elem = None
        for idx, item in enumerate(raw_val):
            # Reject booleans (isinstance(True, int) is True in Python), strings, nulls, NaN/Inf
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                bad_elem = f"index {idx} has non-numeric type {type(item).__name__}"
                break
            if not math.isfinite(float(item)):
                bad_elem = f"index {idx} has non-finite float value {item!r}"
                break
        if bad_elem is not None:
            invalid_rows.append(f"id={row_id}: {bad_elem}")

        if len(invalid_rows) >= 10:
            break

    if invalid_rows:
        details = "; ".join(invalid_rows)
        raise RuntimeError(
            "Cannot convert document_chunks.embedding to vector(1536): "
            f"detected malformed or dimension-mismatched historical embedding row(s): {details}. "
            "Fix or nullify the invalid historical embeddings before re-running alembic upgrade."
        )


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    dialect = bind.dialect.name

    # 1. PostgreSQL pgvector extension + native vector(1536) column conversion
    if dialect == 'postgresql':
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

        if insp.has_table('document_chunks'):
            col_meta = bind.execute(
                sa.text(
                    """
                    SELECT
                        c_info.udt_name,
                        format_type(a.atttypid, a.atttypmod) AS formatted_type
                    FROM information_schema.columns c_info
                    JOIN pg_class cls
                      ON cls.relname = c_info.table_name
                    JOIN pg_namespace ns
                      ON ns.oid = cls.relnamespace AND ns.nspname = c_info.table_schema
                    JOIN pg_attribute a
                      ON a.attrelid = cls.oid AND a.attname = c_info.column_name AND NOT a.attisdropped
                    WHERE c_info.table_schema = current_schema()
                      AND c_info.table_name = 'document_chunks'
                      AND c_info.column_name = 'embedding'
                    """
                )
            ).fetchone()

            if col_meta is not None:
                udt_name, formatted_type = col_meta[0], (col_meta[1] or "").strip().lower()
                if formatted_type == 'vector(1536)':
                    pass  # Already exact native vector(1536) contract
                elif udt_name == 'vector':
                    # Existing vector column with wrong/unconstrained typmod: validate dims before altering!
                    bad_vecs = bind.execute(
                        sa.text(
                            "SELECT id, vector_dims(embedding) FROM document_chunks "
                            "WHERE embedding IS NOT NULL AND vector_dims(embedding) != 1536 LIMIT 10"
                        )
                    ).fetchall()
                    if bad_vecs:
                        details = "; ".join(f"id={r[0]}: dims={r[1]}" for r in bad_vecs)
                        raise RuntimeError(
                            f"Cannot alter document_chunks.embedding from '{formatted_type}' to vector(1536): "
                            f"incompatible existing vector dimensions: {details}."
                        )
                    op.execute(
                        sa.text(
                            "ALTER TABLE document_chunks "
                            "ALTER COLUMN embedding TYPE vector(1536)"
                        )
                    )
                elif udt_name in ('json', 'jsonb'):
                    _validate_existing_json_embeddings(bind)
                    op.execute(
                        sa.text(
                            """
                            ALTER TABLE document_chunks
                            ALTER COLUMN embedding TYPE vector(1536)
                            USING (
                                CASE
                                    WHEN embedding IS NULL THEN NULL
                                    ELSE regexp_replace(embedding::jsonb::text, '\\s+', '', 'g')::vector(1536)
                                END
                            )
                            """
                        )
                    )
                else:
                    raise RuntimeError(
                        f"Unsupported existing column type '{formatted_type}' (udt={udt_name}) on "
                        "document_chunks.embedding; expected json, jsonb, or vector(1536)."
                    )

    # 2. Add request_fingerprint to image_variation_batches (all dialects)
    if insp.has_table('image_variation_batches'):
        existing_cols = {c['name'] for c in insp.get_columns('image_variation_batches')}
        existing_indexes = {idx['name'] for idx in insp.get_indexes('image_variation_batches')}
        if 'request_fingerprint' not in existing_cols:
            with op.batch_alter_table('image_variation_batches') as batch_op:
                batch_op.add_column(sa.Column('request_fingerprint', sa.String(length=128), nullable=True))
        if 'ix_image_variation_batches_request_fingerprint' not in existing_indexes:
            op.create_index(
                'ix_image_variation_batches_request_fingerprint',
                'image_variation_batches',
                ['request_fingerprint'],
                unique=False,
            )


    # 3. Ensure generated_images.parent_image_id self-referential FK matches ORM
    if insp.has_table('generated_images'):
        existing_fks = {
            (tuple(fk['constrained_columns']), fk['referred_table'], tuple(fk['referred_columns']))
            for fk in insp.get_foreign_keys('generated_images')
        }
        if (('parent_image_id',), 'generated_images', ('id',)) not in existing_fks:
            with op.batch_alter_table('generated_images') as batch_op:
                batch_op.create_foreign_key(
                    'fk_generated_images_parent_image_id',
                    'generated_images',
                    ['parent_image_id'],
                    ['id'],
                    ondelete='SET NULL',
                )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    dialect = bind.dialect.name

    # 0. Drop generated_images.parent_image_id self-referential FK if present
    if insp.has_table('generated_images'):
        fk_names = {fk.get('name') for fk in insp.get_foreign_keys('generated_images')}
        if 'fk_generated_images_parent_image_id' in fk_names:
            with op.batch_alter_table('generated_images') as batch_op:
                batch_op.drop_constraint('fk_generated_images_parent_image_id', type_='foreignkey')

    # 1. Remove request_fingerprint from image_variation_batches
    if insp.has_table('image_variation_batches'):
        existing_cols = {c['name'] for c in insp.get_columns('image_variation_batches')}
        existing_indexes = {idx['name'] for idx in insp.get_indexes('image_variation_batches')}
        if 'ix_image_variation_batches_request_fingerprint' in existing_indexes:
            op.drop_index('ix_image_variation_batches_request_fingerprint', table_name='image_variation_batches')
        if 'request_fingerprint' in existing_cols:
            with op.batch_alter_table('image_variation_batches') as batch_op:
                batch_op.drop_column('request_fingerprint')

    # 2. Convert PostgreSQL vector(1536) back to JSON preserving all existing values and NULLs
    if dialect == 'postgresql' and insp.has_table('document_chunks'):
        col_meta = bind.execute(
            sa.text(
                """
                SELECT data_type, udt_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'document_chunks'
                  AND column_name = 'embedding'
                """
            )
        ).fetchone()
        if col_meta is not None and col_meta[1] == 'vector':
            op.execute(
                sa.text(
                    """
                    ALTER TABLE document_chunks
                    ALTER COLUMN embedding TYPE json
                    USING (
                        CASE
                            WHEN embedding IS NULL THEN NULL
                            ELSE (embedding::text)::json
                        END
                    )
                    """
                )
            )
