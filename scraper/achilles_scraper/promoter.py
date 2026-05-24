import sqlite3
import time
from dataclasses import dataclass, field


@dataclass
class PromotionResult:
    promoted: int = 0
    pending: int = 0


@dataclass
class RatingPromotionResult:
    promoted: int = 0
    pending: int = 0

def run_promotion(conn: sqlite3.Connection, batch_id: str | None = None) -> PromotionResult:
    where = "WHERE needs_review = 1 AND promoted_at IS NULL"
    params: list = []
    if batch_id:
        where += " AND batch_id = ?"
        params.append(batch_id)

    candidates = conn.execute(f"SELECT * FROM staging_price_candidates {where}", params).fetchall()

    by_wine: dict[str, list] = {}
    for c in candidates:
        by_wine.setdefault(c["wine_key"], []).append(c)

    result = PromotionResult()
    TOLERANCE = 0.15

    for wine_key, items in by_wine.items():
        # ADR-003: tri-source rule requires ≥2 *distinct sources* (source_key),
        # not just ≥2 candidate rows. Without this guard, a single retailer
        # whose scraper ran twice would self-promote.
        distinct_sources = {c["source_key"] for c in items}
        if len(distinct_sources) < 2:
            result.pending += len(items)
            continue
        sorted_items = sorted(items, key=lambda x: x["amount_eur"] or 0)
        median = sorted_items[len(sorted_items) // 2]["amount_eur"] or 0
        if median == 0:
            result.pending += len(items)
            continue
        concordant = [c for c in items if abs((c["amount_eur"] or 0) - median) / median <= TOLERANCE]
        # The concordant subset must itself span ≥2 distinct sources.
        if len(concordant) >= 2 and len({c["source_key"] for c in concordant}) >= 2:
            now = int(time.time())
            for c in concordant:
                conn.execute("""INSERT INTO fact_price
                    (wine_key, source_key, retailer, recorded_at, price_kind, currency_code, amount_local, amount_eur, source_url, content_hash, batch_id)
                    VALUES (?, ?, ?, ?, 'retail_in_stock', ?, ?, ?, ?, ?, ?)""",
                    (c["wine_key"], c["source_key"], c["retailer"], c["recorded_at"], c["currency_code"], c["amount_local"], c["amount_eur"], c["source_url"], c["content_hash"], c["batch_id"]))
                pk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.execute("UPDATE staging_price_candidates SET promoted_to_fact_price_key=?, promoted_at=?, needs_review=0 WHERE candidate_id=?", (pk, now, c["candidate_id"]))
            conn.commit()
            result.promoted += len(concordant)
            result.pending += len(items) - len(concordant)
        else:
            result.pending += len(items)

    return result


def promote_ratings(conn: sqlite3.Connection, batch_id: str | None = None) -> RatingPromotionResult:
    """Promote staging rating candidates to fact_rating.

    Gate (ADR-003 analogue for ratings): a wine_key must have ≥2 *distinct*
    source_key values in staging before any of its candidates are promoted.
    A single critic source that ingested twice must NOT self-promote.

    Vivino rows (source_code='vivino') are excluded — they are handled
    separately by promote_vivino_tiebreakers() per ADR-013.

    Mono-source rows: needs_review stays 1, rows stay in staging.
    Multi-source rows: inserted into fact_rating (idempotent upsert via
    content_hash) and marked with promoted_at in staging.
    """
    # Exclude Vivino rows — they follow a different promotion gate (ADR-013).
    # Look up the vivino source_key defensively (test DBs may have no source_code column).
    vivino_sk: int | None = None
    try:
        vivino_row = conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = 'vivino'"
        ).fetchone()
        vivino_sk = vivino_row[0] if vivino_row else None
    except Exception:
        pass

    if vivino_sk is not None:
        where = f"WHERE needs_review = 1 AND promoted_at IS NULL AND source_key != {vivino_sk}"
    else:
        where = "WHERE needs_review = 1 AND promoted_at IS NULL"
    params: list = []
    if batch_id:
        where += " AND batch_id = ?"
        params.append(batch_id)

    candidates = conn.execute(
        f"SELECT * FROM staging_rating_candidates {where}", params
    ).fetchall()

    by_wine: dict[str, list] = {}
    for c in candidates:
        by_wine.setdefault(c["wine_key"], []).append(c)

    result = RatingPromotionResult()

    for wine_key, items in by_wine.items():
        distinct_sources = {c["source_key"] for c in items}
        if len(distinct_sources) < 2:
            # Gate not met — flag needs_review and leave in staging.
            for c in items:
                conn.execute(
                    "UPDATE staging_rating_candidates SET needs_review = 1 WHERE candidate_id = ?",
                    (c["candidate_id"],),
                )
            result.pending += len(items)
            continue

        # ≥2 distinct sources — promote all candidates for this wine_key.
        now = int(time.time())
        for c in items:
            # Idempotent upsert: skip if (wine_key, source_key, content_hash)
            # already exists in fact_rating.
            existing = None
            if c["content_hash"]:
                existing = conn.execute(
                    "SELECT rating_event_key FROM fact_rating "
                    "WHERE wine_key = ? AND source_key = ? AND content_hash = ?",
                    (c["wine_key"], c["source_key"], c["content_hash"]),
                ).fetchone()

            if existing:
                fact_key = existing["rating_event_key"]
            else:
                conn.execute(
                    """INSERT INTO fact_rating
                        (wine_key, source_key, critic_code, reviewer_type, score, scale,
                         score_normalized_100, rating_count, recorded_at, source_url,
                         content_hash, batch_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        c["wine_key"],
                        c["source_key"],
                        c["critic_code"],
                        c["reviewer_type"],
                        c["score"],
                        c["scale"],
                        c["score_normalized_100"],
                        c["rating_count"],
                        c["recorded_at"],
                        c["source_url"],
                        c["content_hash"],
                        c["batch_id"],
                    ),
                )
                fact_key = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            conn.execute(
                "UPDATE staging_rating_candidates "
                "SET promoted_to_fact_rating_key = ?, promoted_at = ?, needs_review = 0 "
                "WHERE candidate_id = ?",
                (fact_key, now, c["candidate_id"]),
            )

        conn.commit()
        result.promoted += len(items)

    return result


def promote_vivino_tiebreakers(conn: sqlite3.Connection) -> RatingPromotionResult:
    """Promote Vivino staging rows when ≥2 pro critic sources already exist in fact_rating.

    Vivino is a tiebreaker — never a sole source (ADR-013).  A Vivino staging
    row is eligible for promotion only when fact_rating already contains ≥2
    distinct non-Vivino source_keys for the same wine_key.
    """
    vivino_row = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = 'vivino'"
    ).fetchone()
    if not vivino_row:
        return RatingPromotionResult()
    vivino_source_key = vivino_row[0]

    candidates = conn.execute(
        "SELECT * FROM staging_rating_candidates "
        "WHERE source_key = ? AND promoted_at IS NULL",
        (vivino_source_key,),
    ).fetchall()

    result = RatingPromotionResult()
    now = int(time.time())

    for c in candidates:
        wine_key = c["wine_key"]
        pro_count = conn.execute(
            "SELECT COUNT(DISTINCT source_key) FROM fact_rating "
            "WHERE wine_key = ? AND source_key != ?",
            (wine_key, vivino_source_key),
        ).fetchone()[0]

        if pro_count < 2:
            result.pending += 1
            continue

        existing = None
        if c["content_hash"]:
            existing = conn.execute(
                "SELECT rating_event_key FROM fact_rating "
                "WHERE wine_key = ? AND source_key = ? AND content_hash = ?",
                (c["wine_key"], c["source_key"], c["content_hash"]),
            ).fetchone()

        if existing:
            fact_key = existing["rating_event_key"]
        else:
            conn.execute(
                """INSERT INTO fact_rating
                    (wine_key, source_key, critic_code, reviewer_type, score, scale,
                     score_normalized_100, rating_count, recorded_at, source_url,
                     content_hash, batch_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    c["wine_key"], c["source_key"], c["critic_code"], c["reviewer_type"],
                    c["score"], c["scale"], c["score_normalized_100"], c["rating_count"],
                    c["recorded_at"], c["source_url"], c["content_hash"], c["batch_id"],
                ),
            )
            fact_key = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        conn.execute(
            "UPDATE staging_rating_candidates "
            "SET promoted_to_fact_rating_key = ?, promoted_at = ?, needs_review = 0 "
            "WHERE candidate_id = ?",
            (fact_key, now, c["candidate_id"]),
        )
        result.promoted += 1

    conn.commit()
    return result
