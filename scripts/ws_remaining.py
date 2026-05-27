"""Used by ws_batch_run.ps1 to check remaining queue depth. Prints a single integer."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from scraper.achilles_scraper.config import config
from scraper.achilles_scraper.db import get_db
from datetime import datetime, timezone
config.ensure_dirs()
conn = get_db(config.db_path)
cutoff = int(datetime.now(timezone.utc).timestamp()) - 30 * 86400
src = conn.execute("SELECT source_key FROM dim_source WHERE source_code='wine_searcher'").fetchone()
if not src:
    print(0)
else:
    n = conn.execute("""
        SELECT COUNT(*) FROM (
          SELECT p.producer_norm, w.cuvee_norm
          FROM dim_wine w
          JOIN dim_producer p USING(producer_key)
          JOIN dim_appellation a USING(appellation_key)
          WHERE p.country_code='FR' AND a.country_code='FR'
            AND (w.vintage IS NULL OR w.vintage >= 2000)
            AND NOT EXISTS (
              SELECT 1 FROM ops_content_hashes
              WHERE url = 'ws_cuvee:' || p.producer_norm || '|' || COALESCE(w.cuvee_norm,'')
                AND source_key = ? AND last_fetched_at >= ?
            )
          GROUP BY p.producer_norm, w.cuvee_norm
        )
    """, (src[0], cutoff)).fetchone()[0]
    print(n)
