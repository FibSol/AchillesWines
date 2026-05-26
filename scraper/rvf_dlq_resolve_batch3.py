"""
rvf_dlq_resolve_batch3.py — Third batch of online-verified RVF DLQ corrections.

Groups:
  1. Chateau Les Vignals / Gaillac  → new producer (Cestayrols, Tarn), cuvee=Les Vignals
  2. Domaine du Barry / Gaillac     → new producer (Campagnac, Tarn) – distinct from CDR Barry
  3. Domaine de Brousse / IGP Cotes du Tarn → new producer (Cahuzac-sur-Vere, Tarn)

Unresolvable (marked 'unresolvable'):
  - DOMAINE GAILLARDE  — not a real producer (no listing in any Gaillac directory)
  - Chateau Annabel    — "Annabel" is a branded cuvee of Ch. Puybarbe, not a standalone estate
  - Domaine des Arnelins — not a real producer (no listing anywhere)

Usage:
    python rvf_dlq_resolve_batch3.py [--dry-run]
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
BATCH_ID = f"rvfmag-batch3-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"

GAILLAC_KEY = 847
COTES_DU_TARN_KEY = 842


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower().strip()


def score_to_100(score_raw: float) -> float:
    if score_raw > 20:
        return round(score_raw, 1)
    return round((score_raw / 20.0) * 100.0, 1)


def make_wine_key(conn, producer_key: int, cuvee_norm: str, vintage) -> str | None:
    row = conn.execute(
        "SELECT producer_norm FROM dim_producer WHERE producer_key=?", (producer_key,)
    ).fetchone()
    if not row:
        return None
    producer_norm = row[0]
    vintage_str = str(vintage) if vintage else "NV"
    return hashlib.sha256(f"{producer_norm}|{cuvee_norm}|{vintage_str}".encode()).hexdigest()[:16]


def get_or_create_producer(conn, name: str, region: str, dry_run: bool) -> int:
    name_norm = norm(name)
    row = conn.execute(
        "SELECT producer_key FROM dim_producer WHERE producer_norm=?", (name_norm,)
    ).fetchone()
    if row:
        return row[0]
    if dry_run:
        print(f"    DRY new producer: {name!r} ({region})")
        return -1
    conn.execute(
        "INSERT INTO dim_producer (producer_name, producer_norm, country_code, region, status) VALUES (?,?,'FR',?,'active')",
        (name, name_norm, region),
    )
    pk = conn.execute(
        "SELECT producer_key FROM dim_producer WHERE producer_norm=? ORDER BY producer_key DESC LIMIT 1",
        (name_norm,),
    ).fetchone()[0]
    print(f"    CREATED producer: key={pk} {name!r}")
    return pk


def ensure_dim_wine(conn, producer_key, appellation_key, cuvee_name, cuvee_norm,
                    vintage, color, dry_run) -> str | None:
    wine_key = make_wine_key(conn, producer_key, cuvee_norm, vintage)
    if not wine_key:
        return None
    existing = conn.execute("SELECT wine_key FROM dim_wine WHERE wine_key=?", (wine_key,)).fetchone()
    if existing:
        return wine_key
    if dry_run:
        print(f"    DRY new wine: {wine_key} | p={producer_key} cuvee={cuvee_name!r} v={vintage} [{color}]")
        return wine_key
    conn.execute(
        """INSERT OR IGNORE INTO dim_wine
           (wine_key, producer_key, appellation_key,
            cuvee_name, cuvee_norm, color, vintage, is_non_vintage,
            bottle_ml, canonical_name)
           VALUES (?,?,?,?,?,?,?,?,750,?)""",
        (wine_key, producer_key, appellation_key,
         cuvee_name, cuvee_norm, color, vintage if vintage else None, 1 if not vintage else 0,
         f"{cuvee_name} {vintage}" if vintage else cuvee_name),
    )
    print(f"    CREATED wine: {wine_key} | {cuvee_name!r} v{vintage}")
    return wine_key


def resolve_dlq_row(conn, dlq_id: int, wine_key: str, score_raw: float, source_key: int, dry_run: bool):
    score_20 = score_raw if score_raw <= 20 else round(score_raw / 5.0, 2)
    norm_score = score_to_100(score_raw)
    content_hash = hashlib.sha256(
        json.dumps({"wine_key": wine_key, "critic": CRITIC_CODE,
                    "score": score_20, "source": SOURCE_CODE}, sort_keys=True).encode()
    ).hexdigest()
    if dry_run:
        print(f"    DRY fact_rating: wine={wine_key} score={score_20}/20 ({norm_score}/100)")
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
        (int(datetime.now().timestamp()), "rvf_dlq_resolve_batch3.py", dlq_id),
    )


def mark_unresolvable(conn, dlq_id: int, reason: str, dry_run: bool):
    if dry_run:
        print(f"    DRY unresolvable dlq={dlq_id}: {reason}")
        return
    conn.execute(
        "UPDATE ops_dead_letter SET resolution='unresolvable', resolved_at=?, resolved_by=?, error_message=? WHERE dlq_id=?",
        (int(datetime.now().timestamp()), "rvf_dlq_resolve_batch3.py", reason, dlq_id),
    )


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

    # G1: Chateau Les Vignals (Gaillac, Tarn) — biodynamic estate in Cestayrols
    vignals_key = get_or_create_producer(conn, "Chateau Les Vignals", "Gaillac", args.dry_run)

    # G2: Domaine du Barry (Gaillac, Tarn) — Campagnac, Maroulle family — NOT Cotes du Rhone Barry
    barry_gaillac_key = get_or_create_producer(conn, "Domaine du Barry", "Gaillac", args.dry_run)

    # G3: Domaine de Brousse (Gaillac/Tarn, Cahuzac-sur-Vere) — organic, Boissel family
    brousse_key = get_or_create_producer(conn, "Domaine de Brousse", "Gaillac", args.dry_run)

    resolved = 0
    unresolvable = 0
    skipped = 0

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

        # Only handle cuvee == producer records
        if p_n != c_n:
            skipped += 1
            continue

        # ── GROUP 1: Chateau Les Vignals / Gaillac ──────────────────────────
        if "vignals" in p_n:
            cuvee_name = "Les Vignals"
            cuvee_norm_val = norm(cuvee_name)
            pk = vignals_key if vignals_key != -1 else None
            if pk:
                wine_key = ensure_dim_wine(conn, pk, GAILLAC_KEY, cuvee_name, cuvee_norm_val, vintage, "red", args.dry_run)
                if wine_key:
                    print(f"  [G1 Vignals] dlq={dlq_id} v={vintage} score={score}")
                    resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                    resolved += 1
            continue

        # ── GROUP 2: Domaine du Barry / Gaillac ─────────────────────────────
        if p_n == "domaine du barry":
            cuvee_name = "Domaine du Barry"
            cuvee_norm_val = norm(cuvee_name)
            pk = barry_gaillac_key if barry_gaillac_key != -1 else None
            if pk:
                wine_key = ensure_dim_wine(conn, pk, GAILLAC_KEY, cuvee_name, cuvee_norm_val, vintage, "red", args.dry_run)
                if wine_key:
                    print(f"  [G2 Barry Gaillac] dlq={dlq_id} v={vintage} score={score}")
                    resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                    resolved += 1
            continue

        # ── GROUP 3: Domaine de Brousse / IGP Cotes du Tarn ─────────────────
        if "brousse" in p_n:
            cuvee_name = "Domaine de Brousse"
            cuvee_norm_val = norm(cuvee_name)
            pk = brousse_key if brousse_key != -1 else None
            if pk:
                wine_key = ensure_dim_wine(conn, pk, COTES_DU_TARN_KEY, cuvee_name, cuvee_norm_val, vintage, "red", args.dry_run)
                if wine_key:
                    print(f"  [G3 Brousse] dlq={dlq_id} v={vintage} score={score}")
                    resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                    resolved += 1
            continue

        # ── UNRESOLVABLE: Domaine Gaillarde (not a real producer) ────────────
        if "gaillarde" in p_n:
            mark_unresolvable(conn, dlq_id, "Domaine Gaillarde: not found in any Gaillac producer registry", args.dry_run)
            unresolvable += 1
            continue

        # ── UNRESOLVABLE: Chateau Annabel (branded cuvee of Ch. Puybarbe) ────
        if "annabel" in p_n:
            mark_unresolvable(conn, dlq_id, "Chateau Annabel: branded cuvee of Chateau Puybarbe, not a standalone estate", args.dry_run)
            unresolvable += 1
            continue

        # ── UNRESOLVABLE: Domaine des Arnelins (not a real producer) ─────────
        if "arnelin" in p_n:
            mark_unresolvable(conn, dlq_id, "Domaine des Arnelins: not found in any wine producer directory", args.dry_run)
            unresolvable += 1
            continue

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
