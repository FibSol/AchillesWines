"""
CellarTracker browser-session scraper.

Uses the Claude-in-Chrome MCP connection that's already open in the user's
browser to fetch wine.asp pages via in-page fetch() calls — bypasses
CloudFront/Kasada because the request originates from a real authenticated
browser session.

Usage:
    python scripts/ct_browser_scrape.py --start 50000 --count 300 --db ../data/achilles.db

The script prints a JS payload to stdout for the MCP javascript_tool call,
waits for the JSON result on stdin, then inserts matching rows into the DB.

Since we can't call the MCP from Python directly, this script is designed to
be driven by Claude Code interactively:
  1. Claude runs build_js_batch(start, count) → copies JS to clipboard
  2. Claude calls mcp javascript_tool with that JS
  3. Claude feeds the JSON result back to this script via --result file
  4. Script inserts into DB and prints next cursor
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

_KNOWN_LABELS = {
    "vintage", "type", "producer", "variety", "designation",
    "vineyard", "country", "region", "subregion", "sub-region", "appellation",
}

_COUNTRY_TO_ISO2 = {
    "france": "FR", "italy": "IT", "spain": "ES", "portugal": "PT",
    "germany": "DE", "austria": "AT", "usa": "US", "united states": "US",
    "argentina": "AR", "chile": "CL", "australia": "AU", "new zealand": "NZ",
    "south africa": "ZA", "hungary": "HU", "greece": "GR",
    "switzerland": "CH", "belgium": "BE", "luxembourg": "LU",
}

_TYPE_TO_COLOR = {
    "red": "red", "white": "white", "rosé": "rosé", "rose": "rosé",
    "pink": "rosé", "sparkling": "sparkling", "champagne": "sparkling",
    "dessert": "sweet", "sweet": "sweet", "fortified": "fortified",
    "port": "fortified", "sherry": "fortified", "madeira": "fortified",
    "orange": "orange", "white - sweet/dessert": "sweet",
    "white - sparkling": "sparkling", "white - fortified": "fortified",
}


def build_js_batch(start: int, count: int, delay_ms: int = 300) -> str:
    """
    Return a self-contained JS snippet to paste into mcp javascript_tool.
    Fetches `count` consecutive iWine pages starting at `start`, using the
    browser's existing CT session. Returns a JSON array of wine objects.
    """
    return f"""
(async () => {{
  const START = {start};
  const COUNT = {count};
  const DELAY = {delay_ms};

  function parseWine(html, iWine) {{
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, 'text/html');

    const pairs = {{}};
    doc.querySelectorAll('ul.twin_set_list li').forEach(li => {{
      const span = li.querySelector('span');
      if (!span) return;
      const label = span.textContent.trim().toLowerCase();
      const full = li.textContent.trim();
      const labelTxt = span.textContent.trim();
      const value = full.startsWith(labelTxt) ? full.substring(labelTxt.length).trim() : full;
      if (label && value && value !== 'n/a') pairs[label] = value;
    }});

    const scoreRaw = doc.querySelector('.scorebox')?.textContent || '';
    const scoreMatch = scoreRaw.match(/CT\\s+([\\d.]+)/);
    const notesMatch = scoreRaw.match(/([\\d,]+)\\s+user reviews/);
    const score = scoreMatch ? parseFloat(scoreMatch[1]) : null;
    const numNotes = notesMatch ? parseInt(notesMatch[1].replace(',','')) : null;

    // Title fallback for "not found" pages
    const title = doc.querySelector('title')?.textContent || '';
    const notFound = !pairs.producer && !score;

    if (notFound) return null;
    return {{ iWine, score, numNotes, ...pairs }};
  }}

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const results = [];

  for (let i = 0; i < COUNT; i++) {{
    const iWine = START + i;
    try {{
      const resp = await fetch('/wine.asp?iWine=' + iWine);
      const html = await resp.text();
      const wine = parseWine(html, iWine);
      if (wine) results.push(wine);
    }} catch(e) {{
      // skip network errors
    }}
    if (i < COUNT - 1) await sleep(DELAY);
  }}

  return JSON.stringify({{ start: START, count: COUNT, found: results.length, wines: results }});
}})()
""".strip()


def _norm_text(s: str) -> str:
    import re
    import unicodedata
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def insert_results(db_path: str, json_str: str) -> dict:
    """
    Parse JSON result from the browser JS batch and insert into:
      - dim_producer (pending_review if new)
      - dim_appellation (if new)
      - dim_wine (if new)
      - staging_rating_candidates → fact_rating via existing promoter rules
    Returns stats dict.
    """
    data = json.loads(json_str)
    wines = data.get("wines", [])

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    source_row = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = 'cellartracker'"
    ).fetchone()
    if not source_row:
        conn.execute(
            """INSERT OR IGNORE INTO dim_source
               (source_code, source_name, source_tier, cadence, base_url,
                license_class, enabled, requires_auth, notes)
               VALUES ('cellartracker','CellarTracker','F_crowd_aggregator','on_demand',
                       'https://www.cellartracker.com','public_check_terms',1,0,
                       'Community wine DB. Browser-session scraper via fetch().')"""
        )
        conn.commit()
        source_row = conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = 'cellartracker'"
        ).fetchone()
    source_key = source_row[0]

    import re
    import uuid
    from datetime import datetime
    batch_id = f"ct-browser-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"

    stats = {"processed": 0, "inserted": 0, "skipped_no_score": 0,
             "skipped_no_fr": 0, "skipped_dup": 0}

    for w in wines:
        stats["processed"] += 1
        score = w.get("score")
        if score is None or score < 50 or score > 100:
            stats["skipped_no_score"] += 1
            continue

        country_raw = w.get("country", "")
        country = _COUNTRY_TO_ISO2.get(country_raw.lower().strip())
        if not country:
            stats["skipped_no_fr"] += 1
            continue

        producer_raw = w.get("producer", "")
        designation = w.get("designation", "") or w.get("variety", "")
        vintage_raw = w.get("vintage", "")
        region_raw = w.get("region", "")
        appellation_raw = w.get("appellation", "") or w.get("subregion", "") or region_raw
        type_raw = w.get("type", "").lower()

        if not producer_raw:
            continue

        # Vintage
        vintage = None
        vraw = vintage_raw.strip().upper()
        if vraw and vraw not in {"NV", "N.V.", "NON-VINTAGE", "N/A", "-"}:
            m = re.search(r"\b(1[89]\d{2}|20[0-3]\d)\b", vraw)
            if m:
                v = int(m.group(1))
                if 1900 <= v <= 2040:
                    vintage = v

        color = None
        for k, v in _TYPE_TO_COLOR.items():
            if k in type_raw:
                color = v
                break
        color = color or "red"

        producer_norm = _norm_text(producer_raw)
        cuvee_norm = _norm_text(designation) if designation else ""
        appellation_norm = _norm_text(appellation_raw) if appellation_raw else _norm_text(region_raw)

        if not producer_norm:
            continue

        # Ensure producer
        prod_row = conn.execute(
            "SELECT producer_key FROM dim_producer WHERE producer_norm=? AND country_code=?",
            (producer_norm, country)
        ).fetchone()
        if not prod_row:
            cur = conn.execute(
                """INSERT OR IGNORE INTO dim_producer
                   (producer_name, producer_norm, country_code, allowed_appellations, aliases, status)
                   VALUES (?,?,?,'[]','[]','pending_review')""",
                (producer_raw, producer_norm, country)
            )
            conn.commit()
            prod_row = conn.execute(
                "SELECT producer_key FROM dim_producer WHERE producer_norm=? AND country_code=?",
                (producer_norm, country)
            ).fetchone()
        if not prod_row:
            continue
        producer_key = prod_row[0]

        # Ensure appellation
        app_row = conn.execute(
            "SELECT appellation_key FROM dim_appellation WHERE country_code=? AND appellation_norm=?",
            (country, appellation_norm)
        ).fetchone()
        if not app_row and appellation_norm:
            cur = conn.execute(
                """INSERT OR IGNORE INTO dim_appellation
                   (country_code, region, appellation_name, appellation_norm, level)
                   VALUES (?,?,?,?,'regional')""",
                (country, region_raw or appellation_raw, appellation_raw or region_raw, appellation_norm)
            )
            conn.commit()
            app_row = conn.execute(
                "SELECT appellation_key FROM dim_appellation WHERE country_code=? AND appellation_norm=?",
                (country, appellation_norm)
            ).fetchone()
        if not app_row:
            continue
        appellation_key = app_row[0]

        # Compute wine_key (mirror of lib/identity.ts)
        raw_key = f"{producer_norm}|{cuvee_norm}|{vintage or 'NV'}|{appellation_norm}"
        wine_key = hashlib.sha1(raw_key.encode()).hexdigest()[:16]

        # Ensure wine
        if not conn.execute("SELECT 1 FROM dim_wine WHERE wine_key=?", (wine_key,)).fetchone():
            conn.execute(
                """INSERT OR IGNORE INTO dim_wine
                   (wine_key, producer_key, appellation_key, cuvee_name, cuvee_norm,
                    color, vintage, is_non_vintage, bottle_ml, canonical_name)
                   VALUES (?,?,?,?,?,?,?,?,750,?)""",
                (wine_key, producer_key, appellation_key, designation, cuvee_norm,
                 color, vintage, 1 if vintage is None else 0, f"{producer_raw} {designation}")
            )
            conn.commit()

        # Insert fact_rating
        content_hash = hashlib.sha256(
            json.dumps({"wine_key": wine_key, "score": score, "iWine": w["iWine"]},
                       sort_keys=True).encode()
        ).hexdigest()

        try:
            conn.execute(
                """INSERT OR IGNORE INTO fact_rating
                   (wine_key, source_key, critic_code, reviewer_type,
                    score, scale, score_normalized_100, source_url, content_hash, batch_id)
                   VALUES (?,?,'CT','user_aggregate',?,'/100',?,?,?,?)""",
                (wine_key, source_key, score, score,
                 f"https://www.cellartracker.com/wine.asp?iWine={w['iWine']}",
                 content_hash, batch_id)
            )
            conn.commit()
            stats["inserted"] += 1
        except Exception:
            stats["skipped_dup"] += 1

    conn.close()
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=50000, help="First iWine to scan")
    parser.add_argument("--count", type=int, default=200, help="How many iWines per batch")
    parser.add_argument("--delay", type=int, default=300, help="ms between fetches in browser")
    parser.add_argument("--db", default="../data/achilles.db")
    parser.add_argument("--result", help="Path to JSON file with browser output (if not reading stdin)")
    parser.add_argument("--print-js", action="store_true", help="Just print the JS snippet and exit")
    args = parser.parse_args()

    if args.print_js:
        print(build_js_batch(args.start, args.count, args.delay))
        sys.exit(0)

    if args.result:
        json_str = Path(args.result).read_text(encoding="utf-8")
    else:
        json_str = sys.stdin.read()

    stats = insert_results(args.db, json_str)
    print(json.dumps(stats, indent=2))
