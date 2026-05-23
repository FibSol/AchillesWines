import sqlite3, json
conn = sqlite3.connect('../data/achilles.db')

batch = 'millesima-20260523-102655-70956883'

# Get full unresolved_dim payloads
print('=== UNRESOLVED_DIM full payloads ===')
samples = conn.execute("""
    SELECT raw_record FROM ops_dead_letter
    WHERE source_key = (SELECT source_key FROM dim_source WHERE source_code='millesima')
    AND batch_id = ?
    AND error_class = 'unresolved_dim'
    LIMIT 5
""", (batch,)).fetchall()
for s in samples:
    try:
        d = json.loads(s[0])
        print(json.dumps(d, indent=2, ensure_ascii=False)[:300])
        print('---')
    except Exception:
        print(s[0][:200])

# Check if Drappier is in dim_producer
print('\n=== dim_producer check ===')
rows = conn.execute("""
    SELECT producer_key, producer_name, producer_norm, country_code, status
    FROM dim_producer
    WHERE producer_norm LIKE '%drappier%' OR producer_norm LIKE '%ayala%' OR producer_norm LIKE '%paillard%'
    LIMIT 10
""").fetchall()
for r in rows:
    print(f'  key={r[0]} name={r[1]} norm={r[2]} cc={r[3]} status={r[4]}')
