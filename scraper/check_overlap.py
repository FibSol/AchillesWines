import sqlite3
conn = sqlite3.connect('../data/achilles.db')

# Overall overlap: 2+ sources
all_overlap = conn.execute('''
    SELECT COUNT(*) FROM (
        SELECT wine_key FROM staging_price_candidates
        WHERE needs_review=1 AND promoted_at IS NULL
        GROUP BY wine_key HAVING COUNT(DISTINCT source_key) >= 2
    )
''').fetchone()[0]
print(f'Total 2+ source overlap: {all_overlap}')

# topwijnen_be vs wijnhuis overlap
tw_wh = conn.execute('''
    SELECT COUNT(*) FROM (
        SELECT wine_key FROM staging_price_candidates
        WHERE source_key IN (
            SELECT source_key FROM dim_source WHERE source_code IN ('topwijnen_be','wijnhuis')
        ) AND needs_review=1 AND promoted_at IS NULL
        GROUP BY wine_key HAVING COUNT(DISTINCT source_key) >= 2
    )
''').fetchone()[0]
print(f'topwijnen_be+wijnhuis overlap: {tw_wh}')

# topwijnen_be vs any French source
tw_fr = conn.execute('''
    SELECT COUNT(*) FROM (
        SELECT wine_key FROM staging_price_candidates
        WHERE source_key IN (
            SELECT source_key FROM dim_source WHERE source_code IN ('topwijnen_be','millesima','cavissima','vinatis','cinoco')
        ) AND needs_review=1 AND promoted_at IS NULL
        GROUP BY wine_key HAVING COUNT(DISTINCT source_key) >= 2
    )
''').fetchone()[0]
print(f'topwijnen_be+French sources overlap: {tw_fr}')

# Sample topwijnen_be wine_keys that also appear in wijnhuis
sample = conn.execute('''
    SELECT DISTINCT w.canonical_name, spc.wine_key
    FROM staging_price_candidates spc
    JOIN dim_wine w ON w.wine_key = spc.wine_key
    WHERE spc.wine_key IN (
        SELECT wine_key FROM staging_price_candidates
        WHERE source_key = (SELECT source_key FROM dim_source WHERE source_code='topwijnen_be')
    ) AND spc.wine_key IN (
        SELECT wine_key FROM staging_price_candidates
        WHERE source_key = (SELECT source_key FROM dim_source WHERE source_code='wijnhuis')
    )
    LIMIT 10
''').fetchall()
print()
print('Sample topwijnen_be + wijnhuis overlap:')
for s in sample:
    print(f'  {s[0][:60]}')
