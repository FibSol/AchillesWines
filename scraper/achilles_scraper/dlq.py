import json
import time
from typing import Optional


def insert_staging_candidate(
    conn,
    *,
    wine_key: str,
    source_key: int,
    retailer: str,
    recorded_at: int,
    currency_code: str = "EUR",
    amount_local: float,
    amount_eur: Optional[float] = None,
    source_url: Optional[str] = None,
    content_hash: Optional[str] = None,
    batch_id: str,
) -> bool:
    """Insert a staging price candidate, skipping duplicates.

    Uses INSERT OR IGNORE — the UNIQUE INDEX on (wine_key, source_key, content_hash)
    prevents duplicate inserts for the same product/source/hash combination.

    Returns:
        True  — row was inserted (new record)
        False — row was silently ignored (already exists with same hash)
    """
    cur = conn.execute(
        """INSERT OR IGNORE INTO staging_price_candidates
           (wine_key, source_key, retailer, recorded_at, currency_code,
            amount_local, amount_eur, source_url, content_hash, batch_id, needs_review)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        (
            wine_key, source_key, retailer, recorded_at, currency_code,
            amount_local, amount_eur, source_url, content_hash, batch_id,
        ),
    )
    conn.commit()
    return cur.rowcount > 0


def write_dlq(
    conn,
    source_key,
    batch_id,
    error_class,
    error_message,
    raw_record,
    source_record_id=None,
    raw_object_path=None,
):
    """Insert a row into ops_dead_letter for a record that failed a gate.

    Args:
        raw_record: dict or string to JSON-encode for the `raw_record` column.
                    Strings are passed through as-is (already JSON).
        raw_object_path: optional filesystem path to a saved artefact (e.g.
                    `raw/email/<batch_id>/<uid>.eml`) so the operator can
                    replay the parser without re-fetching.
    """
    if isinstance(raw_record, (dict, list)):
        raw_record_value = json.dumps(raw_record)
    else:
        raw_record_value = raw_record

    conn.execute(
        """INSERT INTO ops_dead_letter
           (source_key, batch_id, error_class, error_message, raw_record,
            source_record_id, raw_object_path, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            source_key,
            batch_id,
            error_class,
            error_message,
            raw_record_value,
            source_record_id,
            raw_object_path,
            int(time.time()),
        ),
    )
    conn.commit()
