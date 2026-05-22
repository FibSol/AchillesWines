import sqlite3
import time
from dataclasses import dataclass

@dataclass
class PromotionResult:
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
        if len(items) < 2:
            result.pending += len(items)
            continue
        sorted_items = sorted(items, key=lambda x: x["amount_eur"] or 0)
        median = sorted_items[len(sorted_items) // 2]["amount_eur"] or 0
        if median == 0:
            result.pending += len(items)
            continue
        concordant = [c for c in items if abs((c["amount_eur"] or 0) - median) / median <= TOLERANCE]
        if len(concordant) >= 2:
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
