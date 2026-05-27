"""
Reset CT scraping state after the bad login-redirect run:
1. Reset cursor to 550 (last good iWine)
2. Delete cookie cache (force fresh Playwright login)
3. Purge the 1390 junk DLQ rows from login-redirect pages
"""
import sqlite3, json
from pathlib import Path

# 1. Reset cursor
cursor_path = Path('data/cellartracker_cursor.txt')
old_cursor = cursor_path.read_text().strip() if cursor_path.exists() else 'missing'
cursor_path.write_text('550', encoding='utf-8')
print(f'Cursor reset: {old_cursor} -> 550')

# 2. Invalidate cookie cache
cookie_cache = Path('data/ct_cookies.json')
if cookie_cache.exists():
    cookie_cache.unlink()
    print('Cookie cache deleted -> next run will re-login via Playwright')
else:
    print('Cookie cache already missing')

# 3. Purge junk DLQ rows (parse_error "missing producer or designation" with pairs={})
conn = sqlite3.connect('../data/achilles.db')
# Find source_key for cellartracker
sk = conn.execute("SELECT source_key FROM dim_source WHERE source_code='cellartracker'").fetchone()
if sk:
    sk = sk[0]
    # Count before
    before = conn.execute("SELECT COUNT(*) FROM ops_dead_letter WHERE source_key=?", (sk,)).fetchone()[0]
    # Delete rows where raw_record contains "pairs": {} (login redirect noise)
    # These are all the rows from the bad run where pairs was empty
    rows = conn.execute(
        "SELECT dlq_id, raw_record FROM ops_dead_letter WHERE source_key=? AND error_class='parse_error'",
        (sk,)
    ).fetchall()
    purge_ids = []
    for dlq_id, raw in rows:
        try:
            d = json.loads(raw) if raw else {}
            if d.get('pairs') == {} or d.get('pairs') is None:
                purge_ids.append(dlq_id)
        except:
            pass
    if purge_ids:
        conn.executemany("DELETE FROM ops_dead_letter WHERE dlq_id=?", [(i,) for i in purge_ids])
        conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM ops_dead_letter WHERE source_key=?", (sk,)).fetchone()[0]
    print(f'DLQ rows: {before} -> {after} (purged {before - after} junk login-redirect entries)')
else:
    print('cellartracker source_key not found')

conn.close()
print('\nDone. Next scraper run will start from iWine 551 with a fresh Playwright session.')
