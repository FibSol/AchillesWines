import sqlite3
import json
import time

def write_dlq(conn, source_key, batch_id, error_class, error_message, raw_record, source_record_id=None):
    conn.execute(
        """INSERT INTO ops_dead_letter
           (source_key, batch_id, error_class, error_message, raw_record, source_record_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (source_key, batch_id, error_class, error_message, json.dumps(raw_record), source_record_id, int(time.time()))
    )
    conn.commit()
