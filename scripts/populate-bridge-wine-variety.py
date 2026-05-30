#!/usr/bin/env python3
"""
populate-bridge-wine-variety.py
================================
One-shot script to populate bridge_wine_variety using appellation-default
grape rules (Strategy A from issue #42).

Steps:
1. Seed any missing grape varieties into dim_variety.
2. Iterate all dim_wine rows with a FR appellation.
3. Look up APPELLATION_VARIETIES for each appellation_norm.
4. Upsert into bridge_wine_variety with source_confidence=0.6 (appellation default).

Usage:
    scraper\\.venv\\Scripts\\python.exe scripts/populate-bridge-wine-variety.py
    # or from project root:
    python scripts/populate-bridge-wine-variety.py

Run from project root (C:\\Claude\\achilles-wines).
"""
from __future__ import annotations

import os
import sys

# Make sure the scraper package is importable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRAPER_ROOT = os.path.join(PROJECT_ROOT, "scraper")
if SCRAPER_ROOT not in sys.path:
    sys.path.insert(0, SCRAPER_ROOT)

import sqlite3
from achilles_scraper.varieties import (
    APPELLATION_VARIETIES,
    get_varieties_for_appellation,
    ensure_variety_in_db,
    upsert_bridge_wine_variety,
)

DB_PATH = os.path.join(PROJECT_ROOT, "data", "achilles.db")

# Confidence assigned to appellation-default grape mappings
# (lower than scraper-extracted data; reflects that it's a rule, not observed data)
APPELLATION_DEFAULT_CONFIDENCE = 0.6


def main() -> None:
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # -----------------------------------------------------------------------
    # 1. Before counts
    # -----------------------------------------------------------------------
    before_bridge = conn.execute("SELECT COUNT(*) FROM bridge_wine_variety").fetchone()[0]
    before_variety = conn.execute("SELECT COUNT(*) FROM dim_variety").fetchone()[0]
    print(f"Before: dim_variety={before_variety}  bridge_wine_variety={before_bridge}")

    # -----------------------------------------------------------------------
    # 2. Seed all variety names from APPELLATION_VARIETIES into dim_variety
    # -----------------------------------------------------------------------
    seeded_varieties: dict[str, int] = {}  # variety_norm → variety_key

    for varieties in APPELLATION_VARIETIES.values():
        for v in varieties:
            vn = v["variety_norm"]
            if not vn or vn in seeded_varieties:
                continue
            key = ensure_variety_in_db(conn, v["variety_name"], v["color_family"])
            if key:
                seeded_varieties[vn] = key

    # Also build a lookup for all existing varieties (in case they were already seeded)
    for row in conn.execute("SELECT variety_key, variety_norm FROM dim_variety").fetchall():
        seeded_varieties[row["variety_norm"]] = row["variety_key"]

    after_variety = conn.execute("SELECT COUNT(*) FROM dim_variety").fetchone()[0]
    print(f"Varieties seeded: {after_variety - before_variety} new  (total {after_variety})")

    # -----------------------------------------------------------------------
    # 3. Iterate all dim_wine rows with a known appellation
    # -----------------------------------------------------------------------
    wines = conn.execute(
        """
        SELECT w.wine_key, a.appellation_norm
        FROM dim_wine w
        JOIN dim_appellation a ON w.appellation_key = a.appellation_key
        """
    ).fetchall()

    print(f"Processing {len(wines):,} wines...")

    total_upserted = 0
    total_no_mapping = 0
    total_skipped = 0

    for wine in wines:
        wine_key = wine["wine_key"]
        appellation_norm = wine["appellation_norm"]

        varieties = get_varieties_for_appellation(appellation_norm)
        if not varieties:
            total_no_mapping += 1
            continue

        for v in varieties:
            vn = v["variety_norm"]
            variety_key = seeded_varieties.get(vn)
            if not variety_key:
                total_skipped += 1
                continue

            # Use midpoint of pct range as share_pct if both bounds given
            share_pct = None
            if v["pct_min"] is not None and v["pct_max"] is not None:
                share_pct = (v["pct_min"] + v["pct_max"]) / 2.0

            # Primary varieties get slightly higher confidence
            confidence = APPELLATION_DEFAULT_CONFIDENCE if v["is_primary"] else APPELLATION_DEFAULT_CONFIDENCE * 0.8

            ok = upsert_bridge_wine_variety(
                conn, wine_key, variety_key, share_pct, confidence
            )
            if ok:
                total_upserted += 1
            else:
                total_skipped += 1

    # -----------------------------------------------------------------------
    # 4. After counts
    # -----------------------------------------------------------------------
    after_bridge = conn.execute("SELECT COUNT(*) FROM bridge_wine_variety").fetchone()[0]

    print()
    print("=" * 60)
    print(f"DONE")
    print(f"  Wines processed         : {len(wines):,}")
    print(f"  Wines with no mapping   : {total_no_mapping:,}")
    print(f"  Bridge rows upserted    : {total_upserted:,}")
    print(f"  Rows skipped (no key)   : {total_skipped:,}")
    print()
    print(f"Before: bridge_wine_variety = {before_bridge:,}")
    print(f"After:  bridge_wine_variety = {after_bridge:,}")
    print(f"Net new rows: {after_bridge - before_bridge:,}")
    print("=" * 60)

    conn.close()


if __name__ == "__main__":
    main()
