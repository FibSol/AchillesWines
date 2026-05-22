import json
import time


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
