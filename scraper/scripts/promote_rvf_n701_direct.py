"""
promote_rvf_n701_direct.py
--------------------------
Directly promote all RVF N°701 staging rows into fact_rating and fact_price,
bypassing the tri-source promoter.

User explicitly accepted single-source data risk (ADR-003 exception).
"""

import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parents[2] / "data" / "achilles.db"


def promote_ratings(conn: sqlite3.Connection) -> int:
    """Promote staging_rating_candidates → fact_rating for rvf_n701 batch.
    Returns number of rows inserted."""
    cur = conn.cursor()

    # Insert DISTINCT on content_hash to handle any cross-batch duplicates
    cur.execute("""
        INSERT OR IGNORE INTO fact_rating (
            wine_key,
            source_key,
            critic_code,
            reviewer_type,
            score,
            scale,
            score_normalized_100,
            rating_count,
            recorded_at,
            source_url,
            content_hash,
            batch_id
        )
        SELECT DISTINCT
            wine_key,
            source_key,
            critic_code,
            reviewer_type,
            score,
            scale,
            score_normalized_100,
            rating_count,
            recorded_at,
            source_url,
            content_hash,
            batch_id
        FROM staging_rating_candidates
        WHERE batch_id LIKE 'rvf_n701%'
          AND promoted_to_fact_rating_key IS NULL
    """)
    rows_inserted = cur.rowcount

    # Back-fill the staging promoted_to_fact_rating_key + promoted_at
    cur.execute("""
        UPDATE staging_rating_candidates
        SET
            promoted_to_fact_rating_key = (
                SELECT rating_event_key
                FROM fact_rating
                WHERE fact_rating.content_hash = staging_rating_candidates.content_hash
                LIMIT 1
            ),
            promoted_at = :now
        WHERE batch_id LIKE 'rvf_n701%'
          AND promoted_to_fact_rating_key IS NULL
    """, {"now": int(time.time())})

    conn.commit()
    return rows_inserted


def promote_prices(conn: sqlite3.Connection) -> int:
    """Promote staging_price_candidates → fact_price for rvf_n701 batch.
    Returns number of rows inserted."""
    cur = conn.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO fact_price (
            wine_key,
            source_key,
            retailer,
            recorded_at,
            price_kind,
            currency_code,
            amount_local,
            amount_eur,
            source_url,
            content_hash,
            batch_id
        )
        SELECT DISTINCT
            wine_key,
            source_key,
            retailer,
            recorded_at,
            'listed',
            currency_code,
            amount_local,
            amount_eur,
            source_url,
            content_hash,
            batch_id
        FROM staging_price_candidates
        WHERE batch_id LIKE 'rvf_n701%'
          AND promoted_to_fact_price_key IS NULL
    """)
    rows_inserted = cur.rowcount

    cur.execute("""
        UPDATE staging_price_candidates
        SET
            promoted_to_fact_price_key = (
                SELECT price_event_key
                FROM fact_price
                WHERE fact_price.content_hash = staging_price_candidates.content_hash
                LIMIT 1
            ),
            promoted_at = :now
        WHERE batch_id LIKE 'rvf_n701%'
          AND promoted_to_fact_price_key IS NULL
    """, {"now": int(time.time())})

    conn.commit()
    return rows_inserted


def print_sanity_check(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM fact_rating WHERE batch_id LIKE 'rvf_n701%'")
    print(f"fact_rating rows (rvf_n701*): {cur.fetchone()[0]}")

    cur.execute("SELECT COUNT(*) FROM fact_price WHERE batch_id LIKE 'rvf_n701%'")
    print(f"fact_price rows  (rvf_n701*): {cur.fetchone()[0]}")

    print()
    print("Top 5 scores:")
    cur.execute("""
        SELECT
            p.producer_name,
            w.vintage,
            w.cuvee_name,
            r.score_normalized_100
        FROM fact_rating r
        JOIN dim_wine w     ON w.wine_key     = r.wine_key
        JOIN dim_producer p ON p.producer_key = w.producer_key
        WHERE r.batch_id LIKE 'rvf_n701%'
        ORDER BY r.score_normalized_100 DESC
        LIMIT 5
    """)
    rows = cur.fetchall()
    for i, (producer, vintage, cuvee, score) in enumerate(rows, 1):
        print(f"  {i}. {producer} {vintage} {cuvee} — {score}/100")


def main() -> None:
    print(f"DB: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))

    # Pre-flight counts
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM staging_rating_candidates WHERE batch_id LIKE 'rvf_n701%' AND promoted_to_fact_rating_key IS NULL")
    pending_ratings = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM staging_price_candidates WHERE batch_id LIKE 'rvf_n701%' AND promoted_to_fact_price_key IS NULL")
    pending_prices = cur.fetchone()[0]
    print(f"Pending rating candidates: {pending_ratings}")
    print(f"Pending price  candidates: {pending_prices}")
    print()

    ratings_added = promote_ratings(conn)
    prices_added = promote_prices(conn)

    # Count staging rows now marked promoted
    cur.execute("SELECT COUNT(*) FROM staging_rating_candidates WHERE batch_id LIKE 'rvf_n701%' AND promoted_to_fact_rating_key IS NOT NULL")
    staged_ratings_marked = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM staging_price_candidates WHERE batch_id LIKE 'rvf_n701%' AND promoted_to_fact_price_key IS NOT NULL")
    staged_prices_marked = cur.fetchone()[0]

    print(f"fact_rating rows added:        {ratings_added}")
    print(f"fact_price  rows added:        {prices_added}")
    print(f"staging rows marked promoted:  {staged_ratings_marked + staged_prices_marked}  "
          f"(ratings={staged_ratings_marked}, prices={staged_prices_marked})")
    print()

    print_sanity_check(conn)
    conn.close()


if __name__ == "__main__":
    main()
