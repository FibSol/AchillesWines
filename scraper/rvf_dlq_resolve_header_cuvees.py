"""
rvf_dlq_resolve_header_cuvees.py — For unresolved DLQ records where the
cuvee was flagged as a section-header (appellation name = cuvee) but the
producer IS identifiable in dim_producer:
  - create dim_wine with cuvee_name = appellation (legitimate for base bottlings)
  - write fact_rating, mark DLQ resolved

Appellation-as-cuvee is VALID for these cases:
  Pouilly-Fuisse / Macon / Bourgogne / Sancerre etc. (base bottling label text)

Usage:
    python rvf_dlq_resolve_header_cuvees.py [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from rapidfuzz import fuzz

load_dotenv(Path(__file__).parent.parent / ".env", override=True)
DB_PATH = Path(__file__).parent.parent / os.getenv("DATABASE_URL", "data/achilles.db")

SOURCE_CODE = "rvf_magazine"
CRITIC_CODE = "RVF"
SCALE = "/20"
BATCH_ID = f"rvfmag-header-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"

PRODUCER_MATCH_THRESH = 85
APPELLATION_MATCH_THRESH = 78


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower().strip()


HEADER_CUVEES = {
    "Bourgogne", "Vin de France", "Languedoc", "Macon", "Macon et Macon-villages",
    "Chateauneuf-du-Pape", "Sancerre", "Pouilly-Fume", "Cotes du Rhone",
    "Cotes du Roussillon", "Arbois-Pupillin Rouge", "Madiran",
    "Pouilly-Fuisse", "Pouilly-Loche", "Chianti Classico", "Grand cru Clos",
    "Alsace", "Pomerol", "Saint-Emilion Grand Cru",
    "Margaux", "Saint-Julien", "Pessac-Leognan", "Sauternes", "Savoie",
    "Vallee de la Loire",
}
HEADER_CUVEES_NORM = {norm(x) for x in HEADER_CUVEES}

# Map header-cuvee norm -> canonical cuvée display + color + appellation hint
HEADER_MAP = {
    "pouilly-fuisse": ("Pouilly-Fuisse", "white", "fuiss"),
    "pouilly fuisse": ("Pouilly-Fuisse", "white", "fuiss"),
    "macon": ("Macon", "white", "macon"),
    "macon et macon-villages": ("Macon-Villages", "white", "macon"),
    "bourgogne": ("Bourgogne", "red", "bourgogne"),
    "sancerre": ("Sancerre", "white", "sancerre"),
    "pouilly-fume": ("Pouilly-Fume", "white", "pouilly-fum"),
    "cotes du rhone": ("Cotes du Rhone", "red", "rhone"),
    "cotes du roussillon": ("Cotes du Roussillon", "red", "roussillon"),
    "languedoc": ("Languedoc", "red", "languedoc"),
    "alsace": ("Alsace", "white", "alsace"),
    "pomerol": ("Pomerol", "red", "pomerol"),
    "margaux": ("Margaux", "red", "margaux"),
    "saint-julien": ("Saint-Julien", "red", "saint-julien"),
    "pessac-leognan": ("Pessac-Leognan", "red", "pessac"),
    "sauternes": ("Sauternes", "sweet", "sauternes"),
    "savoie": ("Savoie", "white", "savoie"),
    "vallee de la loire": ("Vallee de la Loire", "white", "loire"),
    "madiran": ("Madiran", "red", "madiran"),
    "saint-emilion grand cru": ("Saint-Emilion Grand Cru", "red", "saint-emilion"),
}


def score_to_100(score_raw: float) -> float:
    if score_raw > 20:
        return round(score_raw, 1)
    return round((score_raw / 20.0) * 100.0, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    source_key = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code=?", (SOURCE_CODE,)
    ).fetchone()[0]

    # Load all producers and appellations for fuzzy matching
    db_producers = [
        {"pk": r[0], "pnorm": r[1], "pname": r[2]}
        for r in conn.execute("SELECT producer_key, producer_norm, producer_name FROM dim_producer").fetchall()
    ]
    db_apps = [
        {"ak": r[0], "anorm": r[1], "aname": r[2]}
        for r in conn.execute("SELECT appellation_key, appellation_norm, appellation_name FROM dim_appellation").fetchall()
    ]

    rows = conn.execute(
        "SELECT dlq_id, raw_record FROM ops_dead_letter "
        "WHERE source_key = 52 AND error_class = 'unmatched_wine' "
        "AND (resolution IS NULL OR resolution = 'pending')"
    ).fetchall()
    print(f"Unresolved: {len(rows)}")

    resolved = 0
    no_producer = 0
    no_appellation = 0
    not_header = 0

    for dlq_id, raw in rows:
        try:
            r = json.loads(raw)
        except Exception:
            continue

        producer_raw = (r.get("producer") or "").strip()
        cuvee_raw = (r.get("cuvee") or "").strip()
        vintage = r.get("vintage")
        appellation_raw = (r.get("appellation") or "").strip()
        score = r.get("score")
        if score is None:
            continue

        p_n = norm(producer_raw)
        c_n = norm(cuvee_raw)

        if c_n not in HEADER_CUVEES_NORM:
            not_header += 1
            continue

        # Get canonical cuvee display and color
        header_info = HEADER_MAP.get(c_n)
        if header_info:
            cuvee_display, color, app_hint = header_info
        else:
            cuvee_display = cuvee_raw  # fallback
            color = "red"
            app_hint = c_n[:8]

        # Fuzzy match producer
        best_prod = None
        best_ps = 0
        for p in db_producers:
            s = fuzz.token_sort_ratio(p_n, p["pnorm"])
            if s > best_ps:
                best_ps = s
                best_prod = p
        if best_ps < PRODUCER_MATCH_THRESH:
            no_producer += 1
            continue
        producer_key = best_prod["pk"]

        # Find appellation — prefer exact appellation_raw match, fall back to app_hint
        app_match = None
        best_as = 0
        app_norm_raw = norm(appellation_raw)
        for a in db_apps:
            s = fuzz.token_sort_ratio(app_norm_raw, a["anorm"])
            if s > best_as:
                best_as = s
                app_match = a
        if best_as < APPELLATION_MATCH_THRESH:
            # Try with app_hint
            for a in db_apps:
                if app_hint in a["anorm"]:
                    app_match = a
                    break
        if not app_match:
            no_appellation += 1
            continue
        appellation_key = app_match["ak"]

        # Compute wine_key
        prod_row = conn.execute(
            "SELECT producer_norm FROM dim_producer WHERE producer_key=?", (producer_key,)
        ).fetchone()
        if not prod_row:
            no_producer += 1
            continue
        producer_norm = prod_row[0]
        cuvee_norm = norm(cuvee_display)
        vintage_str = str(vintage) if vintage else "NV"
        raw_key = f"{producer_norm}|{cuvee_norm}|{vintage_str}"
        wine_key = hashlib.sha256(raw_key.encode()).hexdigest()[:16]

        # Ensure dim_wine
        existing = conn.execute("SELECT wine_key FROM dim_wine WHERE wine_key=?", (wine_key,)).fetchone()
        if not existing:
            if args.dry_run:
                print(f"  DRY new wine: {wine_key} | {best_prod['pname']!r} / {cuvee_display!r} v{vintage} [{color}]")
            else:
                conn.execute(
                    """INSERT OR IGNORE INTO dim_wine
                       (wine_key, producer_key, appellation_key,
                        cuvee_name, cuvee_norm, color, vintage, is_non_vintage,
                        bottle_ml, canonical_name)
                       VALUES (?,?,?,?,?,?,?,?,750,?)""",
                    (wine_key, producer_key, appellation_key,
                     cuvee_display, cuvee_norm, color,
                     vintage if vintage else None, 1 if not vintage else 0,
                     f"{best_prod['pname']} {cuvee_display}" + (f" {vintage}" if vintage else "")),
                )

        # Write fact_rating and resolve
        score_20 = score if score <= 20 else round(score / 5.0, 2)
        norm_score = score_to_100(score)
        content_hash = hashlib.sha256(
            json.dumps({"wine_key": wine_key, "critic": CRITIC_CODE,
                        "score": score_20, "source": SOURCE_CODE}, sort_keys=True).encode()
        ).hexdigest()

        if args.dry_run:
            if resolved < 10:
                print(f"  DRY resolve dlq={dlq_id} prod={best_prod['pname']!r} cuvee={cuvee_display!r} v={vintage} score={score_20:.1f}/20 (ps={best_ps})")
            resolved += 1
            continue

        conn.execute(
            """INSERT OR IGNORE INTO fact_rating
               (wine_key, source_key, critic_code, reviewer_type,
                score, scale, score_normalized_100,
                source_url, content_hash, batch_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (wine_key, source_key, CRITIC_CODE, "critic",
             score_20, SCALE, norm_score,
             "https://www.larvf.com", content_hash, BATCH_ID),
        )
        conn.execute(
            "UPDATE ops_dead_letter SET resolution='auto_resolved', resolved_at=?, resolved_by=? WHERE dlq_id=?",
            (int(datetime.now().timestamp()), "rvf_dlq_resolve_header_cuvees.py", dlq_id),
        )
        resolved += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    print(f"\n{'='*55}")
    print(f"Resolved          : {resolved}")
    print(f"No producer match : {no_producer}")
    print(f"No appellation    : {no_appellation}")
    print(f"Not header-cuvee  : {not_header}")
    if args.dry_run:
        print("(dry run -- nothing written)")
    else:
        print(f"Batch ID: {BATCH_ID}")


if __name__ == "__main__":
    main()
