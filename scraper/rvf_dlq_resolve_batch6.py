"""
rvf_dlq_resolve_batch6.py — Sixth batch of RVF DLQ corrections.

Groups handled (all cuvee==producer OCR/hyphen-norm mismatches):
  1. VIGNERONS DE BUKY → key=37476 (Vignerons de Buxy, Bourgogne)   [94% score, below threshold]
  2. CHATEAU LAFFEUR   → key=5051  (Chateau Lafleur, Pomerol)        [93% score, double-f OCR]
  3. CHATEAU BELAIR-MONANGE → key=451 (Saint-Emilion)  [64% because hyphen stored as space]
  4. CHATEAU FRANC-BAUDRON  → key=3713 (Fronsac)        [62% hyphen issue]
  5. CHATEAU LA CLOTTE-CAZALIS → key=2667 (Saint-Emilion) [68% hyphen issue]
  6. DOMAINE OURY-SCHREIBER → key=8692 (Ourry-Schreiber, Alsace)     [93% + hyphen]

Unresolvable:
  - Chinese wines: Lady Penguin, United Winery, Gaolang Winery, Spine Wine (Ningxia)
  - Terrasses du Larzac: appellation-as-producer (section header)
  - Charmes-Chambertin: appellation name used as producer (section header)
  - Clos de la Roche Grand Cru: appellation name used as producer

Usage:
    python rvf_dlq_resolve_batch6.py [--dry-run]
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

load_dotenv(Path(__file__).parent.parent / ".env", override=True)
DB_PATH = Path(__file__).parent.parent / os.getenv("DATABASE_URL", "data/achilles.db")

SOURCE_CODE = "rvf_magazine"
CRITIC_CODE = "RVF"
SCALE = "/20"
BATCH_ID = f"rvfmag-batch6-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"

# Producer keys
BUXY_KEY = 37476
LAFLEUR_KEY = 5051
BELAIR_MONANGE_KEY = 451
FRANC_BAUDRON_KEY = 3713
CLOTTE_CAZALIS_KEY = 2667
OURRY_SCHREIBER_KEY = 8692

# Appellation keys
BOURGOGNE_KEY = 230
POMEROL_KEY = 215
SAINT_EMILION_KEY = 214
FRONSAC_KEY = 228
ALSACE_KEY = 376


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower().strip()


def score_to_100(score_raw: float) -> float:
    if score_raw > 20:
        return round(score_raw, 1)
    return round((score_raw / 20.0) * 100.0, 1)


def make_wine_key(conn, producer_key: int, cuvee_norm_val: str, vintage) -> str | None:
    row = conn.execute(
        "SELECT producer_norm FROM dim_producer WHERE producer_key=?", (producer_key,)
    ).fetchone()
    if not row:
        return None
    vintage_str = str(vintage) if vintage else "NV"
    return hashlib.sha256(f"{row[0]}|{cuvee_norm_val}|{vintage_str}".encode()).hexdigest()[:16]


def ensure_dim_wine(conn, producer_key, appellation_key, cuvee_name, cuvee_norm_val,
                    vintage, color, dry_run) -> str | None:
    wine_key = make_wine_key(conn, producer_key, cuvee_norm_val, vintage)
    if not wine_key:
        return None
    if conn.execute("SELECT wine_key FROM dim_wine WHERE wine_key=?", (wine_key,)).fetchone():
        return wine_key
    if dry_run:
        pn = conn.execute("SELECT producer_name FROM dim_producer WHERE producer_key=?", (producer_key,)).fetchone()
        print(f"    DRY new wine: {wine_key} | {pn[0]!r} / {cuvee_name!r} v{vintage} [{color}]")
        return wine_key
    conn.execute(
        """INSERT OR IGNORE INTO dim_wine
           (wine_key, producer_key, appellation_key,
            cuvee_name, cuvee_norm, color, vintage, is_non_vintage,
            bottle_ml, canonical_name)
           VALUES (?,?,?,?,?,?,?,?,750,?)""",
        (wine_key, producer_key, appellation_key,
         cuvee_name, cuvee_norm_val, color,
         vintage if vintage else None, 1 if not vintage else 0,
         f"{cuvee_name} {vintage}" if vintage else cuvee_name),
    )
    print(f"    CREATED wine: {wine_key} | {cuvee_name!r} v{vintage}")
    return wine_key


def resolve_dlq_row(conn, dlq_id, wine_key, score_raw, source_key, dry_run):
    score_20 = score_raw if score_raw <= 20 else round(score_raw / 5.0, 2)
    norm_score = score_to_100(score_raw)
    content_hash = hashlib.sha256(
        json.dumps({"wine_key": wine_key, "critic": CRITIC_CODE,
                    "score": score_20, "source": SOURCE_CODE}, sort_keys=True).encode()
    ).hexdigest()
    if dry_run:
        print(f"    DRY resolve dlq={dlq_id} wine={wine_key} score={score_20}/20")
        return
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
        (int(datetime.now().timestamp()), "rvf_dlq_resolve_batch6.py", dlq_id),
    )


def mark_unresolvable(conn, dlq_id, reason, dry_run):
    if dry_run:
        return
    conn.execute(
        "UPDATE ops_dead_letter SET resolution='unresolvable', resolved_at=?, resolved_by=?, error_message=? WHERE dlq_id=?",
        (int(datetime.now().timestamp()), "rvf_dlq_resolve_batch6.py", reason, dlq_id),
    )


def handle(conn, dlq_id, producer_key, app_key, cuvee_name, vintage, color, score, source_key, label, dry_run):
    wine_key = ensure_dim_wine(conn, producer_key, app_key, cuvee_name, norm(cuvee_name), vintage, color, dry_run)
    if wine_key:
        print(f"  [{label}] dlq={dlq_id} v={vintage} score={score}")
        resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, dry_run)
        return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    source_key = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code=?", (SOURCE_CODE,)
    ).fetchone()[0]

    rows = conn.execute(
        "SELECT dlq_id, raw_record FROM ops_dead_letter "
        "WHERE source_key=52 AND error_class='unmatched_wine' "
        "AND (resolution IS NULL OR resolution='pending')"
    ).fetchall()
    print(f"Unresolved: {len(rows)}")

    resolved = 0
    unresolvable = 0
    skipped = 0

    UNRESOLVABLE = {
        "lady penguin": "Lady Penguin: Ningxia (China) wine, not French",
        "united winery": "United Winery: Ningxia (China) wine, not French",
        "gaolang": "Gaolang Winery: Ningxia (China) wine, not French",
        "spine wine": "Spine Wine: Ningxia (China) wine, not French",
        "terrasses du larzac": "Terrasses du Larzac: appellation used as producer (section header artifact)",
        "charmes-chambertin": "Charmes-Chambertin: appellation used as producer (section header artifact)",
        "charmes chambertin": "Charmes-Chambertin: appellation used as producer (section header artifact)",
        "clos de la roche": "Clos de la Roche Grand Cru: appellation used as producer (section header artifact)",
    }

    for dlq_id, raw in rows:
        try:
            r = json.loads(raw)
        except Exception:
            continue

        producer_raw = (r.get("producer") or "").strip()
        cuvee_raw = (r.get("cuvee") or "").strip()
        vintage = r.get("vintage")
        score = r.get("score")
        if score is None:
            continue

        p_n = norm(producer_raw)
        c_n = norm(cuvee_raw)

        # Check unresolvable
        matched = False
        for kw, reason in UNRESOLVABLE.items():
            if kw in p_n:
                mark_unresolvable(conn, dlq_id, reason, args.dry_run)
                unresolvable += 1
                matched = True
                break
        if matched:
            continue

        if p_n != c_n:
            skipped += 1
            continue

        ok = False

        # G1: Vignerons de Buky (OCR for Buxy)
        if "vignerons de buky" in p_n or ("vignerons" in p_n and "buky" in p_n):
            ok = handle(conn, dlq_id, BUXY_KEY, BOURGOGNE_KEY, "Vignerons de Buxy", vintage, "red", score, source_key, "G1 Buky->Buxy", args.dry_run)

        # G2: Chateau Laffeur (OCR double-f for Lafleur)
        elif "laffeur" in p_n:
            ok = handle(conn, dlq_id, LAFLEUR_KEY, POMEROL_KEY, "Chateau Lafleur", vintage, "red", score, source_key, "G2 Laffeur->Lafleur", args.dry_run)

        # G3: Chateau Belair-Monange
        elif "belair" in p_n and "monange" in p_n:
            ok = handle(conn, dlq_id, BELAIR_MONANGE_KEY, SAINT_EMILION_KEY, "Chateau Belair-Monange", vintage, "red", score, source_key, "G3 BelairMonange", args.dry_run)

        # G4: Chateau Franc-Baudron
        elif "franc" in p_n and "baudron" in p_n:
            ok = handle(conn, dlq_id, FRANC_BAUDRON_KEY, FRONSAC_KEY, "Chateau Franc-Baudron", vintage, "red", score, source_key, "G4 FrancBaudron", args.dry_run)

        # G5: Chateau La Clotte-Cazalis
        elif "clotte" in p_n and "cazalis" in p_n:
            ok = handle(conn, dlq_id, CLOTTE_CAZALIS_KEY, SAINT_EMILION_KEY, "Chateau La Clotte-Cazalis", vintage, "red", score, source_key, "G5 ClotteCazalis", args.dry_run)

        # G6: Domaine Oury-Schreiber (OCR for Ourry-Schreiber)
        elif "oury" in p_n and "schreiber" in p_n:
            ok = handle(conn, dlq_id, OURRY_SCHREIBER_KEY, ALSACE_KEY, "Domaine Ourry-Schreiber", vintage, "white", score, source_key, "G6 Oury->Ourry", args.dry_run)

        if ok:
            resolved += 1
        elif not matched:
            skipped += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    print(f"\n{'='*55}")
    print(f"Resolved       : {resolved}")
    print(f"Unresolvable   : {unresolvable}")
    print(f"Skipped        : {skipped}")
    if args.dry_run:
        print("(dry run -- nothing written)")
    else:
        print(f"Batch ID: {BATCH_ID}")


if __name__ == "__main__":
    main()
