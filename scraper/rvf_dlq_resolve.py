"""
rvf_dlq_resolve.py — Resolve unmatched RVF DLQ records by creating missing
dim_producer and dim_wine entries, then the caller should re-run
rvf_magazine_import.py to link ratings.

Usage:
    python rvf_dlq_resolve.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
from pathlib import Path

from dotenv import load_dotenv
from rapidfuzz import fuzz
import sqlite3

sys.path.insert(0, str(Path(__file__).parent))
from achilles_scraper.identity import (
    normalize_producer,
    normalize_cuvee,
    compute_wine_key,
    clean_producer_display,
    clean_cuvee_display,
)

load_dotenv(Path(__file__).parent.parent / ".env", override=True)
DB_PATH = Path(__file__).parent.parent / os.getenv("DATABASE_URL", "data/achilles.db")

# ── Thresholds ────────────────────────────────────────────────────────────────
PRODUCER_MATCH_THRESH = 85
APPELLATION_MATCH_THRESH = 78

# ── Known section-header cuvée names (not real wine names) ───────────────────
def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower().strip()

HEADER_CUVEES = {
    norm(x) for x in [
        "Bourgogne", "Vin de France", "Languedoc", "Mâcon", "Mâcon et Mâcon-villages",
        "Châteauneuf-du-Pape", "Sancerre", "Pouilly-Fumé", "Côtes du Rhône",
        "Côtes du Roussillon", "Mondeuse", "Arbois-Pupillin Rouge", "Madiran",
        "Pouilly-Fuissé", "Pouilly-Loché", "Chianti Classico", "Grand cru Clos",
        "Île de la Réunion", "Alsace", "Pomerol", "Saint-Émilion Grand Cru",
        "Margaux", "Saint-Julien", "Pessac-Léognan", "Sauternes", "Savoie",
        "Vallée de la Loire",
    ]
}

# ── White-wine appellation heuristics (default color is red) ─────────────────
WHITE_APP_KEYWORDS = {
    "blanc", "pouilly", "sancerre", "muscadet", "riesling", "gewurz",
    "pinot gris", "muscat", "alsace", "chablis", "meursault", "puligny",
    "chassagne", "viognier", "roussanne", "marsanne", "vouvray", "montlouis",
    "macon", "fuisse", "fume", "pessac-leognan blanc",
}
SPARKLING_APP_KEYWORDS = {"champagne", "cremant", "prosecco", "cava", "brut"}


def guess_color(appellation: str) -> str:
    an = norm(appellation)
    if any(k in an for k in SPARKLING_APP_KEYWORDS):
        return "sparkling"
    if any(k in an for k in WHITE_APP_KEYWORDS):
        return "white"
    return "red"


def is_bad_score(s) -> bool:
    if s is None:
        return False
    frac = s - int(s)
    return frac >= 0.5 and int(s) > 20


def is_clean(r: dict) -> bool:
    if is_bad_score(r.get("score")):
        return False
    p_n = norm(r.get("producer", ""))
    c_n = norm(r.get("cuvee", ""))
    if p_n == c_n:
        return False
    if c_n in HEADER_CUVEES:
        return False
    if not p_n or not c_n:
        return False
    return True


def find_appellation(db_apps: list[dict], appellation: str) -> dict | None:
    a_norm = normalize_producer(appellation)  # good enough normalisation
    best_score = 0
    best = None
    for a in db_apps:
        s = fuzz.token_sort_ratio(a_norm, a["appellation_norm"])
        if s > best_score:
            best_score = s
            best = a
    if best_score >= APPELLATION_MATCH_THRESH:
        return best
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)

    # ── Load DLQ ─────────────────────────────────────────────────────────────
    rows = conn.execute(
        "SELECT raw_record FROM ops_dead_letter WHERE error_class = 'unmatched_wine'"
    ).fetchall()
    records = [json.loads(r[0]) for r in rows]
    clean = [r for r in records if is_clean(r)]
    print(f"DLQ total: {len(records)}  |  clean after filter: {len(clean)}")

    # ── Load reference tables ─────────────────────────────────────────────────
    db_producers = [
        {"producer_key": r[0], "producer_norm": r[1], "producer_name": r[2],
         "country_code": r[3], "region": r[4]}
        for r in conn.execute(
            "SELECT producer_key, producer_norm, producer_name, country_code, region FROM dim_producer"
        ).fetchall()
    ]
    db_apps = [
        {"appellation_key": r[0], "appellation_norm": r[1],
         "appellation_name": r[2], "country_code": r[3], "region": r[4]}
        for r in conn.execute(
            "SELECT appellation_key, appellation_norm, appellation_name, country_code, region FROM dim_appellation"
        ).fetchall()
    ]
    print(f"dim_producer: {len(db_producers)}  |  dim_appellation: {len(db_apps)}")

    # Get the "Vin de France" fallback appellation
    vdf_app = next(
        (a for a in db_apps if "vin de france" in a["appellation_norm"]), None
    )
    if not vdf_app:
        # Create one if missing (shouldn't happen)
        print("WARNING: no 'Vin de France' appellation found — using first appellation as fallback")
        vdf_app = db_apps[0]

    # ── Process each clean DLQ record ─────────────────────────────────────────
    wines_created = 0
    producers_created = 0
    already_exists = 0
    app_misses = 0

    for r in clean:
        raw_producer = (r.get("producer") or "").strip()
        raw_cuvee = (r.get("cuvee") or "").strip()
        vintage = r.get("vintage")
        appellation_raw = (r.get("appellation") or "Vin de France").strip()

        # Clean display names
        producer_display = clean_producer_display(raw_producer)
        cuvee_display = clean_cuvee_display(raw_cuvee, producer_display)
        if not cuvee_display:
            cuvee_display = raw_cuvee  # fallback to raw if cleaning strips everything

        # Normalise for key computation
        producer_norm = normalize_producer(producer_display)
        cuvee_norm = normalize_cuvee(cuvee_display, strip_words=[producer_norm])

        if not producer_norm or not cuvee_norm:
            continue

        # ── Find or create dim_producer ───────────────────────────────────────
        best_prod = None
        best_score = 0
        for p in db_producers:
            s = fuzz.token_sort_ratio(producer_norm, p["producer_norm"])
            if s > best_score:
                best_score = s
                best_prod = p

        if best_score >= PRODUCER_MATCH_THRESH:
            producer_key = best_prod["producer_key"]
            country_code = best_prod["country_code"]
        else:
            # Create new producer
            # Guess country from appellation
            country_code = "FR"  # default — RVF is >95% French
            region = appellation_raw
            if not args.dry_run:
                conn.execute(
                    """INSERT INTO dim_producer
                       (producer_name, producer_norm, country_code, region, status)
                       VALUES (?,?,?,?,'active')""",
                    (producer_display, producer_norm, country_code, region),
                )
                producer_key = conn.execute(
                    "SELECT producer_key FROM dim_producer WHERE producer_norm=? ORDER BY producer_key DESC LIMIT 1",
                    (producer_norm,),
                ).fetchone()[0]
                # Update in-memory list so subsequent records can match this new producer
                db_producers.append({
                    "producer_key": producer_key,
                    "producer_norm": producer_norm,
                    "producer_name": producer_display,
                    "country_code": country_code,
                    "region": region,
                })
                producers_created += 1
            else:
                producer_key = -1
                producers_created += 1

        # ── Find appellation ──────────────────────────────────────────────────
        app = find_appellation(db_apps, appellation_raw)
        if app:
            appellation_key = app["appellation_key"]
        else:
            app_misses += 1
            appellation_key = vdf_app["appellation_key"]

        # ── Compute wine_key ──────────────────────────────────────────────────
        wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage)

        # ── Check existence ───────────────────────────────────────────────────
        existing = conn.execute(
            "SELECT 1 FROM dim_wine WHERE wine_key=?", (wine_key,)
        ).fetchone()
        if existing:
            already_exists += 1
            continue

        # ── Derive color ──────────────────────────────────────────────────────
        color = guess_color(appellation_raw)

        is_nv = 1 if vintage is None else 0
        canonical_name = f"{producer_display} {cuvee_display}"
        if vintage:
            canonical_name += f" {vintage}"

        if args.dry_run:
            print(f"  DRY new wine: {wine_key} | {producer_display} / {cuvee_display} v{vintage} [{color}]")
            wines_created += 1
            continue

        conn.execute(
            """INSERT OR IGNORE INTO dim_wine
               (wine_key, producer_key, appellation_key,
                cuvee_name, cuvee_norm, color, vintage, is_non_vintage,
                bottle_ml, canonical_name)
               VALUES (?,?,?,?,?,?,?,?,750,?)""",
            (wine_key, producer_key, appellation_key,
             cuvee_display, cuvee_norm, color, vintage if not is_nv else None, is_nv,
             canonical_name),
        )
        if conn.total_changes:
            wines_created += 1

    if not args.dry_run:
        conn.commit()

    conn.close()

    print(f"\n{'='*55}")
    print(f"Producers created : {producers_created}")
    print(f"Appellation misses: {app_misses} (used Vin de France fallback)")
    print(f"Wines created     : {wines_created}")
    print(f"Already existed   : {already_exists}")
    if args.dry_run:
        print("(dry run — nothing written)")
    else:
        print("\nNow re-run: python rvf_magazine_import.py")


if __name__ == "__main__":
    main()
