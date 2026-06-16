"""
Shared helper for capturing republished critic scores that retailer scrapers
already receive but currently discard (e.g. Millesima's ``note_js`` attribute).

Scope: James Suckling only for now (critic_code 'JS').  The retailers expose a
wider panel (Neal Martin, Decanter, Le Figaro, …) but mapping those abbreviations
onto our closed critic_code enum is ambiguous, so they are intentionally left
out — extend MILLESIMA_NOTE_FIELDS once a mapping is confirmed.

Writes to fact_rating with source_key = the retailer (a /100 critic score
republished by a tier-B retailer).  Idempotent: one row per
(wine_key, source_key, critic_code); re-runs update the score if it changed.
"""
import hashlib
import re
import sqlite3
from typing import Optional

# Millesima JSON `attributes` field → critic_code.  JS only, by design.
MILLESIMA_NOTE_FIELDS: dict[str, str] = {
    "note_js": "JS",
}


def parse_critic_score(raw: str) -> Optional[float]:
    """Parse a republished critic score string to a /100 float, or None.

    Handles plain ints ('92'), '+' suffixes ('89+'), and ranges ('95-96' →
    takes the lower bound).  Rejects anything outside a plausible 50–100 range.
    """
    if not raw:
        return None
    m = re.search(r"\d{2,3}", str(raw))
    if not m:
        return None
    try:
        score = float(m.group(0))
    except ValueError:
        return None
    return score if 50 <= score <= 100 else None


def upsert_critic_rating(
    conn: sqlite3.Connection,
    *,
    wine_key: str,
    source_key: int,
    critic_code: str,
    score: float,
    source_url: str,
    batch_id: str,
) -> bool:
    """Insert (or update on change) a single critic rating. Returns True if a
    row was inserted or updated, False if it already existed unchanged."""
    score_norm = score  # republished retailer scores are already /100
    content_hash = hashlib.sha256(
        f"{wine_key}:{source_key}:{critic_code}:{score}".encode()
    ).hexdigest()

    existing = conn.execute(
        "SELECT rating_event_key, content_hash FROM fact_rating "
        "WHERE wine_key = ? AND source_key = ? AND critic_code = ?",
        (wine_key, source_key, critic_code),
    ).fetchone()

    if existing:
        if existing[1] == content_hash:
            return False  # unchanged
        conn.execute(
            "UPDATE fact_rating SET score = ?, score_normalized_100 = ?, "
            "scale = '/100', source_url = ?, content_hash = ?, batch_id = ? "
            "WHERE rating_event_key = ?",
            (score, score_norm, source_url, content_hash, batch_id, existing[0]),
        )
        return True

    conn.execute(
        """INSERT INTO fact_rating
           (wine_key, source_key, critic_code, reviewer_type, score, scale,
            score_normalized_100, source_url, content_hash, batch_id)
           VALUES (?, ?, ?, 'critic', ?, '/100', ?, ?, ?, ?)""",
        (wine_key, source_key, critic_code, score, score_norm,
         source_url, content_hash, batch_id),
    )
    return True
