"""
Tests for scraper/achilles_scraper/similarity.py

Covers:
 - build_feature_vector returns correct-length vector
 - Color encoding (red vs white → different vectors)
 - Cosine similarity of identical vectors = 1.0
 - Cosine similarity of orthogonal vectors = 0.0
 - Similarity is symmetric: sim(A,B) == sim(B,A)
 - compute_all_similarities writes rows to wine_similarity
 - get_similar_wines returns results sorted by score DESC
 - Feature vector for wine with no ratings/prices is None (skip gracefully)
 - _vintage_bucket edge cases
 - _normalize_price clamping
 - Batch computation writes expected number of rows
 - compute_all_similarities is idempotent (re-run clears old rows)
"""

from __future__ import annotations

import math
import sqlite3
from typing import Generator

import numpy as np
import pytest

from achilles_scraper.similarity import (
    COLOR_ENCODING,
    _normalize_price,
    _vintage_bucket,
    build_feature_vector,
    compute_all_similarities,
    cosine_similarity,
    get_similar_wines,
)

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_db() -> sqlite3.Connection:
    """In-memory SQLite with minimal Achilles schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE dim_appellation (
            appellation_key INTEGER PRIMARY KEY,
            country_code TEXT NOT NULL,
            region TEXT NOT NULL,
            subregion TEXT,
            appellation_name TEXT NOT NULL,
            appellation_norm TEXT NOT NULL,
            level TEXT NOT NULL DEFAULT 'regional'
        );

        CREATE TABLE dim_producer (
            producer_key INTEGER PRIMARY KEY,
            producer_name TEXT NOT NULL,
            producer_norm TEXT NOT NULL,
            country_code TEXT NOT NULL
        );

        CREATE TABLE dim_variety (
            variety_key INTEGER PRIMARY KEY,
            variety_name TEXT NOT NULL,
            variety_norm TEXT NOT NULL,
            color_family TEXT NOT NULL
        );

        CREATE TABLE dim_wine (
            wine_key TEXT PRIMARY KEY,
            producer_key INTEGER NOT NULL,
            appellation_key INTEGER NOT NULL,
            cuvee_name TEXT NOT NULL,
            cuvee_norm TEXT NOT NULL,
            color TEXT NOT NULL,
            vintage INTEGER,
            is_non_vintage INTEGER NOT NULL DEFAULT 0,
            bottle_ml INTEGER NOT NULL DEFAULT 750,
            canonical_name TEXT NOT NULL
        );

        CREATE TABLE bridge_wine_variety (
            wine_key TEXT NOT NULL,
            variety_key INTEGER NOT NULL,
            share_pct REAL,
            source_confidence REAL,
            PRIMARY KEY (wine_key, variety_key)
        );

        CREATE TABLE dim_source (
            source_key INTEGER PRIMARY KEY,
            source_code TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_tier TEXT NOT NULL,
            cadence TEXT NOT NULL,
            license_class TEXT NOT NULL DEFAULT 'public_check_terms'
        );

        CREATE TABLE fact_price (
            price_event_key INTEGER PRIMARY KEY AUTOINCREMENT,
            wine_key TEXT NOT NULL,
            source_key INTEGER NOT NULL,
            recorded_at INTEGER NOT NULL DEFAULT (unixepoch()),
            price_kind TEXT NOT NULL DEFAULT 'retail_in_stock',
            currency_code TEXT NOT NULL DEFAULT 'EUR',
            amount_local REAL NOT NULL,
            amount_eur REAL,
            batch_id TEXT NOT NULL DEFAULT 'test'
        );

        CREATE TABLE fact_rating (
            rating_event_key INTEGER PRIMARY KEY AUTOINCREMENT,
            wine_key TEXT NOT NULL,
            source_key INTEGER NOT NULL,
            critic_code TEXT NOT NULL,
            reviewer_type TEXT NOT NULL DEFAULT 'critic',
            score REAL NOT NULL,
            scale TEXT NOT NULL DEFAULT '/100',
            score_normalized_100 REAL NOT NULL,
            recorded_at INTEGER NOT NULL DEFAULT (unixepoch()),
            batch_id TEXT NOT NULL DEFAULT 'test'
        );

        CREATE TABLE wine_similarity (
            wine_key TEXT NOT NULL,
            similar_wine_key TEXT NOT NULL,
            score REAL NOT NULL,
            computed_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (wine_key, similar_wine_key)
        );
        """
    )
    # Seed base rows
    conn.execute(
        "INSERT INTO dim_appellation VALUES (1,'FR','Burgundy',NULL,'Gevrey-Chambertin','gevrey_chambertin','grand_cru')"
    )
    conn.execute(
        "INSERT INTO dim_appellation VALUES (2,'FR','Bordeaux',NULL,'Pauillac','pauillac','regional')"
    )
    conn.execute(
        "INSERT INTO dim_producer VALUES (1,'Test Producer','test_producer','FR')"
    )
    conn.execute(
        "INSERT INTO dim_source VALUES (1,'test','Test Source','E_press_critic','one_shot','public_check_terms')"
    )
    conn.execute(
        "INSERT INTO dim_variety VALUES (1,'Pinot Noir','pinot_noir','red')"
    )
    conn.execute(
        "INSERT INTO dim_variety VALUES (2,'Cabernet Sauvignon','cabernet_sauvignon','red')"
    )
    conn.commit()
    return conn


def _insert_wine(
    conn: sqlite3.Connection,
    wine_key: str,
    color: str = "red",
    vintage: int | None = 2018,
    is_nv: int = 0,
    appellation_key: int = 1,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO dim_wine VALUES (?,1,?,?,?,?,?,?,750,?)",
        (wine_key, appellation_key, f"Cuvée {wine_key}", wine_key, color,
         vintage, is_nv, f"Canonical {wine_key}"),
    )
    conn.commit()


def _add_price(conn: sqlite3.Connection, wine_key: str, amount_eur: float = 50.0) -> None:
    conn.execute(
        "INSERT INTO fact_price (wine_key, source_key, amount_local, amount_eur) VALUES (?,1,?,?)",
        (wine_key, amount_eur, amount_eur),
    )
    conn.commit()


def _add_rating(conn: sqlite3.Connection, wine_key: str, score: float = 90.0) -> None:
    conn.execute(
        "INSERT INTO fact_rating (wine_key, source_key, critic_code, score, score_normalized_100) VALUES (?,1,'WA',?,?)",
        (wine_key, score, score),
    )
    conn.commit()


# ── Unit tests ─────────────────────────────────────────────────────────────


class TestVintageBucket:
    def test_pre_2000(self):
        assert _vintage_bucket(1999, False) == 0.0

    def test_2000s(self):
        assert _vintage_bucket(2005, False) == 0.25

    def test_2010s(self):
        assert _vintage_bucket(2015, False) == 0.5

    def test_2020s(self):
        assert _vintage_bucket(2021, False) == 0.75

    def test_non_vintage(self):
        assert _vintage_bucket(None, True) == 1.0

    def test_none_vintage(self):
        assert _vintage_bucket(None, False) == 1.0


class TestNormalizePrice:
    def test_mid_range(self):
        v = _normalize_price(50.0)
        assert 0.0 < v < 1.0

    def test_clamp_low(self):
        assert _normalize_price(1.0) == _normalize_price(5.0)

    def test_clamp_high(self):
        assert _normalize_price(1000.0) == _normalize_price(500.0)

    def test_bounds(self):
        assert _normalize_price(5.0) == pytest.approx(0.0, abs=1e-6)
        assert _normalize_price(500.0) == pytest.approx(1.0, abs=1e-6)


class TestCosineSimilarity:
    def test_identical_vectors(self):
        a = np.array([1.0, 0.0, 1.0, 0.0])
        assert cosine_similarity(a, a) == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors(self):
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])
        assert cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-6)

    def test_symmetry(self):
        a = np.array([0.3, 0.7, 0.1, 0.9])
        b = np.array([0.5, 0.2, 0.8, 0.4])
        assert cosine_similarity(a, b) == pytest.approx(cosine_similarity(b, a), abs=1e-6)

    def test_zero_vector(self):
        a = np.zeros(4)
        b = np.array([1.0, 0.0, 0.0, 0.0])
        assert cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-6)


class TestBuildFeatureVector:
    def test_returns_none_for_no_data(self):
        conn = _make_db()
        _insert_wine(conn, "no_data", color="red")
        result = build_feature_vector("no_data", conn)
        assert result is None

    def test_returns_ndarray_with_price(self):
        conn = _make_db()
        _insert_wine(conn, "w_price", color="red")
        _add_price(conn, "w_price", 50.0)
        vec = build_feature_vector("w_price", conn)
        assert vec is not None
        assert isinstance(vec, np.ndarray)

    def test_correct_length(self):
        conn = _make_db()
        _insert_wine(conn, "w_len", color="red")
        _add_price(conn, "w_len", 50.0)
        # Provide explicit catalogs so the length is deterministic
        top_regions = [f"Region{i}" for i in range(20)]
        top_variety_keys = list(range(1, 51))
        vec = build_feature_vector("w_len", conn, top_regions, top_variety_keys)
        # 1 (color) + 21 (top-20 regions + other) + 51 (top-50 varieties + other) + 3 (score, price, vintage)
        assert vec is not None
        assert len(vec) == 76

    def test_color_red_vs_white(self):
        conn = _make_db()
        _insert_wine(conn, "w_red", color="red")
        _add_price(conn, "w_red", 50.0)
        _insert_wine(conn, "w_white", color="white")
        _add_price(conn, "w_white", 50.0)

        top_regions = ["Burgundy", "Bordeaux"]
        top_varieties: list[int] = []

        vec_red = build_feature_vector("w_red", conn, top_regions, top_varieties)
        vec_white = build_feature_vector("w_white", conn, top_regions, top_varieties)
        assert vec_red is not None and vec_white is not None
        # Color dimension differs
        assert vec_red[0] != vec_white[0]
        assert vec_red[0] == COLOR_ENCODING["red"]
        assert vec_white[0] == COLOR_ENCODING["white"]

    def test_returns_none_for_unknown_wine(self):
        conn = _make_db()
        result = build_feature_vector("nonexistent_key", conn)
        assert result is None

    def test_variety_multihot(self):
        conn = _make_db()
        _insert_wine(conn, "w_variety", color="red")
        _add_price(conn, "w_variety", 50.0)
        conn.execute(
            "INSERT INTO bridge_wine_variety VALUES ('w_variety',1,100.0,1.0)"
        )
        conn.commit()

        top_regions: list[str] = []
        top_variety_keys = [1, 2]  # variety_key 1 = Pinot Noir

        vec = build_feature_vector("w_variety", conn, top_regions, top_variety_keys)
        assert vec is not None
        # [0] = color, [1..1] = region "other" (no top_regions), then variety multi-hot starts at [2]
        n_regions = 1  # 0 top_regions + 1 "other"
        variety_start = 1 + n_regions
        # variety_key=1 is at index 0 in top_variety_keys
        assert vec[variety_start] == 1.0       # Pinot Noir present
        assert vec[variety_start + 1] == 0.0  # Cabernet Sauvignon absent


class TestComputeAllSimilarities:
    def test_writes_rows(self):
        conn = _make_db()
        # Insert 3 wines with data
        for i in range(1, 4):
            wk = f"wine_{i:03d}"
            _insert_wine(conn, wk, color="red")
            _add_price(conn, wk, 40.0 + i * 10)
            _add_rating(conn, wk, 85.0 + i * 2)

        rows_written = compute_all_similarities(conn, top_k=2, batch_size=10)
        assert rows_written > 0

        count = conn.execute("SELECT COUNT(*) FROM wine_similarity").fetchone()[0]
        assert count == rows_written

    def test_idempotent(self):
        conn = _make_db()
        for i in range(1, 4):
            wk = f"wine_idem_{i}"
            _insert_wine(conn, wk, color="red")
            _add_price(conn, wk, 50.0)
            _add_rating(conn, wk, 88.0)

        rows_first = compute_all_similarities(conn, top_k=2, batch_size=10)
        rows_second = compute_all_similarities(conn, top_k=2, batch_size=10)
        # Second run should produce same row count (old rows cleared)
        count = conn.execute("SELECT COUNT(*) FROM wine_similarity").fetchone()[0]
        assert count == rows_second

    def test_skips_wines_with_no_data(self):
        conn = _make_db()
        # Wine with data
        _insert_wine(conn, "with_data", color="red")
        _add_price(conn, "with_data", 50.0)
        # Wine without data
        _insert_wine(conn, "no_data", color="white")

        compute_all_similarities(conn, top_k=5, batch_size=10)
        # no_data wine should NOT appear in wine_similarity as the source
        count = conn.execute(
            "SELECT COUNT(*) FROM wine_similarity WHERE wine_key='no_data'"
        ).fetchone()[0]
        assert count == 0


class TestGetSimilarWines:
    def test_returns_sorted_by_score_desc(self):
        conn = _make_db()
        for i in range(1, 5):
            wk = f"sim_wine_{i}"
            _insert_wine(conn, wk, color="red")
            _add_price(conn, wk, 30.0 + i * 10)
            _add_rating(conn, wk, 80.0 + i * 2)

        compute_all_similarities(conn, top_k=3, batch_size=10)

        results = get_similar_wines("sim_wine_1", conn, limit=5)
        # Verify sorted descending
        scores = [r["similarity_score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_returns_empty_for_unknown_key(self):
        conn = _make_db()
        results = get_similar_wines("nonexistent", conn, limit=5)
        assert results == []

    def test_result_keys(self):
        conn = _make_db()
        for i in range(1, 4):
            wk = f"keys_wine_{i}"
            _insert_wine(conn, wk, color="red")
            _add_price(conn, wk, 50.0)
            _add_rating(conn, wk, 90.0)

        compute_all_similarities(conn, top_k=2, batch_size=10)
        results = get_similar_wines("keys_wine_1", conn, limit=2)
        if results:
            expected_keys = {
                "wine_key", "similarity_score", "producer_name", "cuvee_name",
                "vintage", "is_non_vintage", "color", "appellation_name",
                "avg_score", "min_price",
            }
            assert set(results[0].keys()) == expected_keys
