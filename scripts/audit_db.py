"""Read-only DB health audit for data/achilles.db.

Counts, orphan checks, duplicate sweeps, source-coverage matrix, DLQ histogram,
critic-code conformance. Touches no rows. Writes a Markdown report to
docs/reliability_audit_<YYYY-MM-DD>.md.

Run:
    python scripts/audit_db.py
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "achilles.db"
REPORT = ROOT / "docs" / f"reliability_audit_{date.today().isoformat()}.md"

# Critic codes accepted in fact_rating per ADR-013 + scrapers/james_suckling.py
VALID_CRITIC_CODES = {"WA", "Vinous", "BH", "JMIB", "RVF", "Decanter", "JS",
                      "JG", "WS", "Hachette", "CT", "WE", "WAL", "WD", "GV",
                      "Halliday"}


def q(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[tuple]:
    return conn.execute(sql, params).fetchall()


def scalar(conn, sql, params=()) -> int | str | None:
    row = q(conn, sql, params)
    if not row:
        return None
    return row[0][0]


def md_table(headers: list[str], rows: list[tuple]) -> str:
    if not rows:
        return "*(no rows)*\n"
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(v) if v is not None else "" for v in r) + " |")
    return "\n".join(out) + "\n"


def table_exists(conn, name: str) -> bool:
    return scalar(conn,
                  "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
                  (name,)) is not None


def main() -> int:
    if not DB_PATH.exists():
        print(f"DB not found at {DB_PATH}", file=sys.stderr)
        return 1
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    sections: list[str] = []

    sections.append(f"# Reliability audit — {date.today().isoformat()}\n")
    sections.append(f"Source DB: `{DB_PATH.relative_to(ROOT)}`  "
                    f"({DB_PATH.stat().st_size / 1_048_576:.0f} MB)\n")

    # --- 1. Row counts -----------------------------------------------------
    sections.append("## 1. Row counts\n")
    rc_tables = [
        "dim_source", "dim_producer", "dim_appellation", "dim_variety", "dim_wine",
        "bridge_wine_variety", "fact_price", "fact_rating", "fact_vintage_rating",
        "cellar_locations", "cellar_inventory", "cellar_consumption",
        "ops_dead_letter", "ops_content_hashes", "ops_batch_log",
        "ops_job_queue", "staging_price_candidates",
        # Newer tables that may or may not exist:
        "fact_market_index", "fact_harvest_volume", "fact_werc_stats",
    ]
    counts = []
    for t in rc_tables:
        if table_exists(conn, t):
            n = scalar(conn, f"SELECT COUNT(*) FROM {t}")
            counts.append((t, f"{n:,}"))
        else:
            counts.append((t, "*(missing)*"))
    sections.append(md_table(["table", "rows"], counts))

    # --- 2. Source coverage ------------------------------------------------
    sections.append("## 2. Source coverage\n")
    sections.append("Rows produced per source across fact tables.\n")
    src_rows = q(conn, """
        SELECT s.source_code,
               s.source_tier,
               s.requires_auth,
               s.enabled,
               COALESCE((SELECT COUNT(*) FROM fact_price  fp WHERE fp.source_key = s.source_key), 0)  AS prices,
               COALESCE((SELECT COUNT(*) FROM fact_rating fr WHERE fr.source_key = s.source_key), 0)  AS ratings,
               COALESCE((SELECT COUNT(*) FROM staging_price_candidates sp WHERE sp.source_key = s.source_key), 0) AS staging,
               COALESCE((SELECT COUNT(*) FROM ops_dead_letter dl WHERE dl.source_key = s.source_key), 0) AS dlq,
               COALESCE((SELECT MAX(finished_at) FROM ops_batch_log bl WHERE bl.source_key = s.source_key), '') AS last_run
        FROM dim_source s
        ORDER BY (prices + ratings + staging) DESC, s.source_code
    """)
    sections.append(md_table(
        ["source_code", "tier", "auth", "enabled", "fact_price", "fact_rating",
         "staging", "DLQ", "last_run_at"], src_rows))

    # --- 3. Dim integrity --------------------------------------------------
    sections.append("## 3. Dim integrity\n")
    integ = []
    integ.append(("dim_producer total",
                  scalar(conn, "SELECT COUNT(*) FROM dim_producer")))
    integ.append(("dim_producer status=pending_review",
                  scalar(conn, "SELECT COUNT(*) FROM dim_producer WHERE status='pending_review'")))
    integ.append(("dim_producer status=deprecated",
                  scalar(conn, "SELECT COUNT(*) FROM dim_producer WHERE status='deprecated'")))
    integ.append(("dim_appellation total",
                  scalar(conn, "SELECT COUNT(*) FROM dim_appellation")))
    integ.append(("dim_appellation with lat/lng",
                  scalar(conn, "SELECT COUNT(*) FROM dim_appellation WHERE latitude IS NOT NULL")))
    integ.append(("dim_wine total",
                  scalar(conn, "SELECT COUNT(*) FROM dim_wine")))
    integ.append(("dim_wine NV (is_non_vintage=1)",
                  scalar(conn, "SELECT COUNT(*) FROM dim_wine WHERE is_non_vintage=1")))
    integ.append(("dim_wine with vintage",
                  scalar(conn, "SELECT COUNT(*) FROM dim_wine WHERE is_non_vintage=0 AND vintage IS NOT NULL")))
    sections.append(md_table(["metric", "value"],
                             [(k, f"{v:,}" if isinstance(v, int) else v) for k, v in integ]))

    # Orphan facts (foreign-key style — schema enforces these so should be 0)
    sections.append("### Orphan facts (FK violations would show > 0)\n")
    orphans = [
        ("fact_price → dim_wine",
         scalar(conn, "SELECT COUNT(*) FROM fact_price fp LEFT JOIN dim_wine w ON fp.wine_key = w.wine_key WHERE w.wine_key IS NULL")),
        ("fact_rating → dim_wine",
         scalar(conn, "SELECT COUNT(*) FROM fact_rating fr LEFT JOIN dim_wine w ON fr.wine_key = w.wine_key WHERE w.wine_key IS NULL")),
        ("staging_price_candidates → dim_wine",
         scalar(conn, "SELECT COUNT(*) FROM staging_price_candidates sp LEFT JOIN dim_wine w ON sp.wine_key = w.wine_key WHERE w.wine_key IS NULL")),
        ("dim_wine → dim_producer",
         scalar(conn, "SELECT COUNT(*) FROM dim_wine w LEFT JOIN dim_producer p ON w.producer_key = p.producer_key WHERE p.producer_key IS NULL")),
        ("dim_wine → dim_appellation",
         scalar(conn, "SELECT COUNT(*) FROM dim_wine w LEFT JOIN dim_appellation a ON w.appellation_key = a.appellation_key WHERE a.appellation_key IS NULL")),
    ]
    sections.append(md_table(["relation", "orphan_count"],
                             [(k, f"{v:,}") for k, v in orphans]))

    # Duplicate (producer_norm, country) — uniqueIndex says this should be 0
    dups_prod = q(conn, """
        SELECT producer_norm, country_code, COUNT(*) AS n
        FROM dim_producer
        GROUP BY producer_norm, country_code
        HAVING n > 1
        ORDER BY n DESC LIMIT 25
    """)
    sections.append("### Duplicate dim_producer (producer_norm, country_code)\n")
    sections.append(md_table(["producer_norm", "country_code", "duplicate_count"], dups_prod))

    # Duplicate (country_code, appellation_norm) — should be 0 per uniqueIndex
    dups_app = q(conn, """
        SELECT appellation_norm, country_code, COUNT(*) AS n
        FROM dim_appellation
        GROUP BY appellation_norm, country_code
        HAVING n > 1
        ORDER BY n DESC LIMIT 25
    """)
    sections.append("### Duplicate dim_appellation (country_code, appellation_norm)\n")
    sections.append(md_table(["appellation_norm", "country_code", "duplicate_count"], dups_app))

    # --- 4. fact_rating critic-code conformance ---------------------------
    sections.append("## 4. fact_rating critic-code conformance\n")
    sections.append(f"Closed enum per ADR-013 / scrapers: `{sorted(VALID_CRITIC_CODES)}`\n")
    critic_dist = q(conn, """
        SELECT critic_code, reviewer_type, COUNT(*) AS n
        FROM fact_rating
        GROUP BY critic_code, reviewer_type
        ORDER BY n DESC
    """)
    flagged = [(c, rt, n, "❌ not in enum") if c not in VALID_CRITIC_CODES else (c, rt, n, "✓")
               for c, rt, n in critic_dist]
    sections.append(md_table(["critic_code", "reviewer_type", "rows", "in_enum?"], flagged))

    # --- 5. DLQ histogram --------------------------------------------------
    sections.append("## 5. ops_dead_letter histogram\n")
    dlq_total = scalar(conn, "SELECT COUNT(*) FROM ops_dead_letter")
    sections.append(f"Total DLQ rows: **{dlq_total:,}**\n")
    if dlq_total:
        dlq_by_reason = q(conn, """
            SELECT error_class, COUNT(*) AS n
            FROM ops_dead_letter
            GROUP BY error_class
            ORDER BY n DESC
        """)
        sections.append("### By error_class\n")
        sections.append(md_table(["error_class", "rows"], dlq_by_reason))

        dlq_by_source = q(conn, """
            SELECT s.source_code, dl.error_class, COUNT(*) AS n
            FROM ops_dead_letter dl
            LEFT JOIN dim_source s ON s.source_key = dl.source_key
            GROUP BY s.source_code, dl.error_class
            ORDER BY n DESC
            LIMIT 30
        """)
        sections.append("### Top 30 (source, error_class) cells\n")
        sections.append(md_table(["source_code", "error_class", "rows"], dlq_by_source))

    # --- 6. Batch log sanity ----------------------------------------------
    sections.append("## 6. ops_batch_log — recent batches\n")
    batch_recent = q(conn, """
        SELECT bl.batch_id, COALESCE(s.source_code, '?'),
               bl.rows_fetched, bl.rows_inserted, bl.rows_dlq, bl.status,
               datetime(bl.started_at, 'unixepoch') AS started,
               CASE WHEN bl.finished_at IS NULL THEN ''
                    ELSE datetime(bl.finished_at, 'unixepoch') END AS finished,
               COALESCE(bl.notes, '')
        FROM ops_batch_log bl
        LEFT JOIN dim_source s ON s.source_key = bl.source_key
        ORDER BY bl.finished_at DESC NULLS LAST
        LIMIT 20
    """)
    sections.append(md_table(
        ["batch_id", "source", "fetched", "inserted", "dlq", "status",
         "started", "finished", "notes"],
        batch_recent))

    # Batches that fetched > 0 but inserted 0 — suspicious
    bad_batches = q(conn, """
        SELECT s.source_code, COUNT(*) AS bad_batches,
               SUM(bl.rows_fetched) AS fetched_total,
               SUM(bl.rows_dlq) AS dlq_total
        FROM ops_batch_log bl
        JOIN dim_source s USING (source_key)
        WHERE bl.rows_fetched > 0 AND bl.rows_inserted = 0
        GROUP BY s.source_code
        ORDER BY bad_batches DESC
        LIMIT 30
    """)
    sections.append("### Batches with rows_fetched > 0 AND rows_inserted = 0\n")
    sections.append("Strong signal of a broken gate, mismatched dim, or parsing-but-failing-validation.\n")
    sections.append(md_table(["source_code", "bad_batches", "fetched_total", "dlq_total"], bad_batches))

    # --- 7. Cellar sanity (quick) ------------------------------------------
    sections.append("## 7. Cellar sanity\n")
    cellar = [
        ("cellar_locations", scalar(conn, "SELECT COUNT(*) FROM cellar_locations")),
        ("cellar_inventory rows", scalar(conn, "SELECT COUNT(*) FROM cellar_inventory")),
        ("cellar_inventory distinct wines", scalar(conn,
            "SELECT COUNT(DISTINCT wine_key) FROM cellar_inventory")),
        ("cellar_inventory orphan (no dim_wine)", scalar(conn, """
            SELECT COUNT(*) FROM cellar_inventory ci
            LEFT JOIN dim_wine w ON ci.wine_key = w.wine_key
            WHERE w.wine_key IS NULL""")),
        ("cellar_consumption rows", scalar(conn, "SELECT COUNT(*) FROM cellar_consumption")),
    ]
    sections.append(md_table(["metric", "value"],
                             [(k, f"{v:,}") for k, v in cellar]))

    conn.close()

    report = "\n".join(sections)
    REPORT.write_text(report, encoding="utf-8")
    print(f"Wrote {REPORT.relative_to(ROOT)} ({len(report):,} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
