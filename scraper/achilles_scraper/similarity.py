"""
Wine feature-vector similarity engine.

Architecture:
  - Build a fixed-length numeric feature vector per wine from dim_wine,
    fact_rating, fact_price, bridge_wine_variety, dim_appellation.
  - Cosine similarity between vectors.
  - Pre-compute and persist top-K most similar wines to wine_similarity table.

No external ML dependencies — pure NumPy.
"""

from __future__ import annotations

import math
import sqlite3
import time
from typing import Any

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    _HAS_NUMPY = False

# ---------------------------------------------------------------------------
# Feature encoding constants
# ---------------------------------------------------------------------------

COLOR_ENCODING: dict[str, float] = {
    "red": 0.0,
    "white": 1.0,
    "rosé": 0.5,
    "sparkling": 0.75,
    "sweet": 0.25,
    "fortified": 1.0,
    "orange": 0.875,  # between white and sparkling
}

# Vintage decade bucket
def _vintage_bucket(vintage: int | None, is_nv: bool) -> float:
    if is_nv or vintage is None:
        return 1.0
    if vintage < 2000:
        return 0.0
    if vintage < 2010:
        return 0.25
    if vintage < 2020:
        return 0.5
    return 0.75


# Price log-normalization: clamped over €5–€500
_PRICE_MIN_LOG = math.log(5.0)
_PRICE_MAX_LOG = math.log(500.0)

def _normalize_price(eur: float) -> float:
    clamped = max(5.0, min(500.0, eur))
    return (math.log(clamped) - _PRICE_MIN_LOG) / (_PRICE_MAX_LOG - _PRICE_MIN_LOG)


# ---------------------------------------------------------------------------
# Catalog queries (executed once and cached per call)
# ---------------------------------------------------------------------------

def _get_top_regions(conn: sqlite3.Connection, top_n: int = 20) -> list[str]:
    """Return top-N regions by wine count, in order."""
    rows = conn.execute(
        """
        SELECT da.region, COUNT(*) AS cnt
        FROM dim_wine dw
        JOIN dim_appellation da ON da.appellation_key = dw.appellation_key
        GROUP BY da.region
        ORDER BY cnt DESC
        LIMIT ?
        """,
        (top_n,),
    ).fetchall()
    return [r[0] for r in rows]


def _get_top_varieties(conn: sqlite3.Connection, top_n: int = 50) -> list[int]:
    """Return top-N variety_keys by frequency in bridge_wine_variety."""
    rows = conn.execute(
        """
        SELECT variety_key, COUNT(*) AS cnt
        FROM bridge_wine_variety
        GROUP BY variety_key
        ORDER BY cnt DESC
        LIMIT ?
        """,
        (top_n,),
    ).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Feature vector builder
# ---------------------------------------------------------------------------

def build_feature_vector(
    wine_key: str,
    conn: sqlite3.Connection,
    top_regions: list[str] | None = None,
    top_variety_keys: list[int] | None = None,
) -> "np.ndarray | None":
    """Build a fixed-length numeric feature vector for one wine.

    Returns None if the wine has no price AND no rating data (skip cheaply).

    Vector layout:
      [0]      — color scalar
      [1..20]  — region one-hot (top-20 + "other" = 21 dims)
      [21..71] — variety multi-hot (top-50 + "other" = 51 dims)
      [72]     — avg critic score normalized 0–1
      [73]     — avg price EUR log-normalized 0–1
      [74]     — vintage decade bucket
    Total length: 75
    """
    if not _HAS_NUMPY:
        raise ImportError("numpy is required for similarity computation")

    if top_regions is None:
        top_regions = _get_top_regions(conn)
    if top_variety_keys is None:
        top_variety_keys = _get_top_varieties(conn)

    # Fetch wine dimensions
    wine_row = conn.execute(
        """
        SELECT dw.color, dw.vintage, dw.is_non_vintage,
               da.region
        FROM dim_wine dw
        JOIN dim_appellation da ON da.appellation_key = dw.appellation_key
        WHERE dw.wine_key = ?
        """,
        (wine_key,),
    ).fetchone()
    if wine_row is None:
        return None

    color_str, vintage, is_nv, region = wine_row

    # Require at least one price or rating
    has_price = conn.execute(
        "SELECT 1 FROM fact_price WHERE wine_key = ? LIMIT 1", (wine_key,)
    ).fetchone()
    has_rating = conn.execute(
        "SELECT 1 FROM fact_rating WHERE wine_key = ? LIMIT 1", (wine_key,)
    ).fetchone()
    if not has_price and not has_rating:
        return None

    # Avg critic score (normalized 0–1 over /100)
    rating_row = conn.execute(
        "SELECT AVG(score_normalized_100) FROM fact_rating WHERE wine_key = ?",
        (wine_key,),
    ).fetchone()
    avg_score_raw: float | None = rating_row[0] if rating_row else None
    avg_score = (avg_score_raw / 100.0) if avg_score_raw is not None else 0.5

    # Avg price EUR log-normalized
    price_row = conn.execute(
        "SELECT AVG(amount_eur) FROM fact_price WHERE wine_key = ? AND amount_eur > 0",
        (wine_key,),
    ).fetchone()
    avg_price_raw: float | None = price_row[0] if price_row else None
    avg_price = _normalize_price(avg_price_raw) if avg_price_raw else 0.5

    # Variety keys for this wine
    variety_rows = conn.execute(
        "SELECT variety_key FROM bridge_wine_variety WHERE wine_key = ?",
        (wine_key,),
    ).fetchall()
    wine_variety_keys = {r[0] for r in variety_rows}

    # --- Assemble vector ---
    n_regions = len(top_regions) + 1  # +1 for "other"
    n_varieties = len(top_variety_keys) + 1  # +1 for "other"
    vec = np.zeros(1 + n_regions + n_varieties + 3, dtype=np.float32)

    idx = 0

    # [0] color
    vec[idx] = COLOR_ENCODING.get(color_str or "red", 0.0)
    idx += 1

    # [1..n_regions] region one-hot
    region_found = False
    for i, r in enumerate(top_regions):
        if r == region:
            vec[idx + i] = 1.0
            region_found = True
            break
    if not region_found:
        vec[idx + len(top_regions)] = 1.0  # "other" bucket
    idx += n_regions

    # variety multi-hot
    variety_found_any = False
    for i, vk in enumerate(top_variety_keys):
        if vk in wine_variety_keys:
            vec[idx + i] = 1.0
            variety_found_any = True
    if not variety_found_any and wine_variety_keys:
        # all varieties outside top-50 — mark "other"
        vec[idx + len(top_variety_keys)] = 1.0
    idx += n_varieties

    # [72] avg score
    vec[idx] = avg_score
    idx += 1

    # [73] avg price
    vec[idx] = avg_price
    idx += 1

    # [74] vintage bucket
    vec[idx] = _vintage_bucket(vintage, bool(is_nv))

    return vec


# ---------------------------------------------------------------------------
# Cosine similarity helpers
# ---------------------------------------------------------------------------

def _cosine_similarity_matrix(A: "np.ndarray") -> "np.ndarray":
    """Compute pairwise cosine similarity for rows of A.
    Returns shape (n, n) matrix.
    """
    norms = np.linalg.norm(A, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)  # avoid div-by-zero
    A_norm = A / norms
    return A_norm @ A_norm.T


def cosine_similarity(a: "np.ndarray", b: "np.ndarray") -> float:
    """Cosine similarity between two 1-D vectors."""
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# ---------------------------------------------------------------------------
# Batch computation
# ---------------------------------------------------------------------------

def compute_all_similarities(
    conn: sqlite3.Connection,
    top_k: int = 20,
    batch_size: int = 500,
    progress_callback: Any = None,
) -> int:
    """Compute pairwise cosine similarities for all eligible wines and persist
    top-K per wine to wine_similarity.

    A wine is eligible if it has at least one fact_price OR fact_rating row.

    Args:
        conn: SQLite connection (row_factory = sqlite3.Row).
        top_k: Number of most similar wines to keep per wine.
        batch_size: Number of wines to process per matrix block.
        progress_callback: Optional callable(processed, total, rows_written).

    Returns:
        Total rows written to wine_similarity.
    """
    if not _HAS_NUMPY:
        raise ImportError("numpy is required for similarity computation")

    # Fetch all eligible wine keys
    eligible = conn.execute(
        """
        SELECT DISTINCT dw.wine_key
        FROM dim_wine dw
        WHERE EXISTS (SELECT 1 FROM fact_price fp WHERE fp.wine_key = dw.wine_key)
           OR EXISTS (SELECT 1 FROM fact_rating fr WHERE fr.wine_key = dw.wine_key)
        ORDER BY dw.wine_key
        """
    ).fetchall()
    wine_keys = [r[0] for r in eligible]
    total = len(wine_keys)
    if total == 0:
        return 0

    # Build catalog once
    top_regions = _get_top_regions(conn)
    top_variety_keys = _get_top_varieties(conn)

    # Build vectors for all eligible wines
    vectors: list[np.ndarray] = []
    valid_keys: list[str] = []
    for wk in wine_keys:
        v = build_feature_vector(wk, conn, top_regions, top_variety_keys)
        if v is not None:
            vectors.append(v)
            valid_keys.append(wk)

    n = len(valid_keys)
    if n == 0:
        return 0

    A = np.stack(vectors, axis=0)  # shape (n, vec_dim)

    # Clear existing similarity rows
    conn.execute("DELETE FROM wine_similarity")
    conn.commit()

    rows_written = 0
    processed = 0

    for start in range(0, n, batch_size):
        end = min(start + batch_size, n)
        batch_keys = valid_keys[start:end]
        batch_vecs = A[start:end]  # shape (batch, vec_dim)

        # Cosine similarity: batch × all
        norms_batch = np.linalg.norm(batch_vecs, axis=1, keepdims=True)
        norms_batch = np.where(norms_batch == 0, 1.0, norms_batch)
        norms_all = np.linalg.norm(A, axis=1, keepdims=True)
        norms_all = np.where(norms_all == 0, 1.0, norms_all)

        batch_norm = batch_vecs / norms_batch
        all_norm = A / norms_all

        # (batch, n) similarity matrix
        sim_matrix = batch_norm @ all_norm.T

        insert_rows = []
        now_str = _utc_now()

        for i_local, wk in enumerate(batch_keys):
            global_i = start + i_local
            sim_row = sim_matrix[i_local]  # shape (n,)

            # Zero out self-similarity
            sim_row[global_i] = -1.0

            # Get top-K indices
            top_indices = np.argpartition(sim_row, -min(top_k, n - 1))[-top_k:]
            top_indices = top_indices[np.argsort(sim_row[top_indices])[::-1]]

            for idx in top_indices:
                score = float(sim_row[idx])
                if score <= 0.0:
                    continue
                sim_key = valid_keys[int(idx)]
                insert_rows.append((wk, sim_key, score, now_str))

        if insert_rows:
            conn.executemany(
                "INSERT OR REPLACE INTO wine_similarity "
                "(wine_key, similar_wine_key, score, computed_at) VALUES (?,?,?,?)",
                insert_rows,
            )
            conn.commit()
            rows_written += len(insert_rows)

        processed += len(batch_keys)
        if progress_callback:
            progress_callback(processed, n, rows_written)

    return rows_written


def _utc_now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Read-side: get similar wines for display
# ---------------------------------------------------------------------------

def get_similar_wines(
    wine_key: str,
    conn: sqlite3.Connection,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return up to `limit` similar wines for display, ordered by score DESC.

    Joins with dim_wine, dim_producer, dim_appellation, and aggregates
    fact_price (min price EUR) and fact_rating (avg score).
    """
    rows = conn.execute(
        """
        SELECT
            ws.similar_wine_key AS wine_key,
            ws.score            AS similarity_score,
            dp.producer_name,
            dw.cuvee_name,
            dw.vintage,
            dw.is_non_vintage,
            dw.color,
            da.appellation_name,
            (SELECT AVG(fr.score_normalized_100)
             FROM fact_rating fr
             WHERE fr.wine_key = ws.similar_wine_key)  AS avg_score,
            (SELECT MIN(fp.amount_eur)
             FROM fact_price fp
             WHERE fp.wine_key = ws.similar_wine_key AND fp.amount_eur > 0) AS min_price
        FROM wine_similarity ws
        JOIN dim_wine dw  ON dw.wine_key  = ws.similar_wine_key
        JOIN dim_producer dp ON dp.producer_key = dw.producer_key
        JOIN dim_appellation da ON da.appellation_key = dw.appellation_key
        WHERE ws.wine_key = ?
        ORDER BY ws.score DESC
        LIMIT ?
        """,
        (wine_key, limit),
    ).fetchall()

    result = []
    for r in rows:
        result.append(
            {
                "wine_key": r[0],
                "similarity_score": r[1],
                "producer_name": r[2],
                "cuvee_name": r[3],
                "vintage": r[4],
                "is_non_vintage": bool(r[5]),
                "color": r[6],
                "appellation_name": r[7],
                "avg_score": r[8],
                "min_price": r[9],
            }
        )
    return result
