"""
rvf_dlq_resolve_batch1.py — Resolve the first confirmed batch of RVF DLQ
unmatched_wine records using online-verified producer/cuvée corrections.

Groups handled:
  1. Clos Sainte Hune / Alsace  → producer=Trimbach (key=573), cuvée=Riesling Clos Sainte Hune
  2. Château Dauzac / Margaux   → cuvée==producer, valid for Bordeaux châteaux
  3. Pierre Overnoy / Arbois-Pupillin Rouge → cuvée was a section-header, maps to existing Poulsard wine
  4. Bailly Lapierre / Crémant de Bourgogne → cooperative NV Crémant
  5. Clos Capitoro / Ajaccio   → fix OCR spelling (Capigtoro→Capitoro)
  6. Domaine Vico / Ajaccio    → appellation correction: Ajaccio→Corse
  7. Château Lafleur / Pomerol → cuvée==producer
  8. Château Saint-Pierre / Saint-Julien → cuvée==producer

Usage:
    python rvf_dlq_resolve_batch1.py [--dry-run]
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
BATCH_ID = f"rvfmag-batch1-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower().strip()


def score_to_100(score_raw: float) -> float:
    """RVF /20 scale → /100."""
    if score_raw > 20:
        return round(score_raw, 1)  # already /100
    return round((score_raw / 20.0) * 100.0, 1)


def make_wine_key(producer_norm: str, cuvee_norm: str, vintage) -> str:
    vintage_str = str(vintage) if vintage else "NV"
    raw = f"{producer_norm}|{cuvee_norm}|{vintage_str}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def ensure_dim_wine(conn, producer_key, appellation_key, cuvee_name, cuvee_norm,
                    vintage, color, dry_run) -> str | None:
    """Insert into dim_wine if missing. Return wine_key."""
    # Lookup producer_norm for key computation
    row = conn.execute("SELECT producer_norm FROM dim_producer WHERE producer_key=?", (producer_key,)).fetchone()
    if not row:
        print(f"    ERROR: producer_key {producer_key} not found")
        return None
    producer_norm = row[0]

    wine_key = make_wine_key(producer_norm, cuvee_norm, vintage)
    existing = conn.execute("SELECT wine_key FROM dim_wine WHERE wine_key=?", (wine_key,)).fetchone()
    if existing:
        return wine_key

    canonical = f"{cuvee_name}"
    if vintage:
        canonical += f" {vintage}"

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
         canonical),
    )
    print(f"    CREATED wine: {wine_key} | {cuvee_name!r} v{vintage}")
    return wine_key


def resolve_dlq_row(conn, dlq_id: int, wine_key: str, score_raw: float, dry_run: bool):
    """Write a fact_rating row and mark DLQ as resolved."""
    score_20 = score_raw if score_raw <= 20 else round(score_raw / 5.0, 2)
    norm_score = score_to_100(score_raw)
    content_hash = hashlib.sha256(
        json.dumps({"wine_key": wine_key, "critic": CRITIC_CODE,
                    "score": score_20, "source": SOURCE_CODE}, sort_keys=True).encode()
    ).hexdigest()

    source_key = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code=?", (SOURCE_CODE,)
    ).fetchone()[0]

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
        (int(datetime.now().timestamp()), "rvf_dlq_resolve_batch1.py", dlq_id),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)

    # Producer keys (verified online)
    TRIMBACH_KEY = 573      # Maison Trimbach, Alsace
    DAUZAC_KEY = 3052       # Château Dauzac, Bordeaux
    OVERNOY_KEY = 667       # Domaine Pierre Overnoy (Houillon), Jura
    BAILLY_KEY = 419        # Bailly-Lapierre, Crémant de Bourgogne
    CAPITORO_KEY = 2517     # Clos Capitoro, Corse
    VICO_KEY = 8397         # Domaine Vico, Corse
    LAFLEUR_KEY = 5051      # Château Lafleur, Bordeaux
    STPIERRE_KEY = 765      # Château Saint-Pierre, Bordeaux

    # Appellation keys (verified from DB)
    ALSACE_KEY = 376
    MARGAUX_KEY = 212
    ARBOIS_PUPILLIN_KEY = 485
    CREMANT_BOURG_KEY = 316
    AJACCIO_KEY = 951
    CORSE_KEY = 530
    POMEROL_KEY = 215
    SAINT_JULIEN_KEY = 216

    # Load DLQ records for source_key=52 (rvf_magazine)
    rows = conn.execute(
        "SELECT dlq_id, raw_record FROM ops_dead_letter "
        "WHERE source_key = 52 AND error_class = 'unmatched_wine' "
        "AND (resolution IS NULL OR resolution = 'pending')"
    ).fetchall()
    print(f"Total unresolved rvf_magazine DLQ rows: {len(rows)}")

    resolved = 0
    skipped = 0

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

        wine_key = None

        # ── GROUP 1: Clos Sainte Hune → Trimbach ─────────────────────────────
        if p_n == "clos sainte hune" and c_n == "clos sainte hune":
            cuvee_name = "Riesling Clos Sainte Hune"
            cuvee_norm = norm(cuvee_name)
            wine_key = ensure_dim_wine(
                conn, TRIMBACH_KEY, ALSACE_KEY,
                cuvee_name, cuvee_norm, vintage, "white", args.dry_run
            )
            if wine_key:
                print(f"  [G1 Trimbach/CSH] dlq={dlq_id} v={vintage} score={score}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, args.dry_run)
                resolved += 1
            continue

        # ── GROUP 2: Château Dauzac (cuvée == producer) ──────────────────────
        if p_n in ("chateau dauzac", "ch. dauzac", "château dauzac") and c_n in ("chateau dauzac", "ch. dauzac", "château dauzac"):
            cuvee_name = "Château Dauzac"
            cuvee_norm = norm(cuvee_name)
            wine_key = ensure_dim_wine(
                conn, DAUZAC_KEY, MARGAUX_KEY,
                cuvee_name, cuvee_norm, vintage, "red", args.dry_run
            )
            if wine_key:
                print(f"  [G2 Dauzac] dlq={dlq_id} v={vintage} score={score}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, args.dry_run)
                resolved += 1
            continue

        # ── GROUP 3: Pierre Overnoy / Arbois-Pupillin Rouge ──────────────────
        # "Arbois-Pupillin Rouge" is a section-header for Overnoy's Poulsard
        if "overnoy" in p_n and c_n in ("arbois-pupillin rouge", "arbois pupillin rouge", "arbois-pupillin"):
            # Map to the existing Poulsard (Ploussard) wine — look it up
            existing = conn.execute(
                "SELECT wine_key FROM dim_wine WHERE producer_key=? AND cuvee_norm LIKE '%ploussard%' OR (producer_key=? AND cuvee_norm LIKE '%poulsard%') LIMIT 1",
                (OVERNOY_KEY, OVERNOY_KEY)
            ).fetchone()
            if existing:
                wine_key = existing[0]
                print(f"  [G3 Overnoy] dlq={dlq_id} v={vintage} score={score} -> existing {wine_key}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, args.dry_run)
                resolved += 1
            else:
                # Create the Poulsard wine
                cuvee_name = "Poulsard Arbois-Pupillin"
                cuvee_norm = norm(cuvee_name)
                wine_key = ensure_dim_wine(
                    conn, OVERNOY_KEY, ARBOIS_PUPILLIN_KEY,
                    cuvee_name, cuvee_norm, vintage, "red", args.dry_run
                )
                if wine_key:
                    print(f"  [G3 Overnoy-new] dlq={dlq_id} v={vintage} score={score}")
                    resolve_dlq_row(conn, dlq_id, wine_key, score, args.dry_run)
                    resolved += 1
            continue

        # ── GROUP 4: Bailly Lapierre / Crémant de Bourgogne ─────────────────
        if ("bailly" in p_n and "lapierre" in p_n) and c_n in ("bailly lapierre", "bailly-lapierre"):
            cuvee_name = "Réserve Brut"
            cuvee_norm = norm(cuvee_name)
            wine_key = ensure_dim_wine(
                conn, BAILLY_KEY, CREMANT_BOURG_KEY,
                cuvee_name, cuvee_norm, vintage, "sparkling", args.dry_run
            )
            if wine_key:
                print(f"  [G4 Bailly] dlq={dlq_id} v={vintage} score={score}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, args.dry_run)
                resolved += 1
            continue

        # ── GROUP 5: Clos Capigtoro → Clos Capitoro ──────────────────────────
        if "capigtoro" in p_n or "capitoro" in p_n:
            cuvee_name = "Clos Capitoro"
            cuvee_norm = norm(cuvee_name)
            wine_key = ensure_dim_wine(
                conn, CAPITORO_KEY, AJACCIO_KEY,
                cuvee_name, cuvee_norm, vintage, "red", args.dry_run
            )
            if wine_key:
                print(f"  [G5 Capitoro] dlq={dlq_id} v={vintage} score={score}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, args.dry_run)
                resolved += 1
            continue

        # ── GROUP 6: Domaine Vico / Ajaccio → Vin de Corse ───────────────────
        if "vico" in p_n and c_n in ("domaine vico", "vico"):
            cuvee_name = "Domaine Vico"
            cuvee_norm = norm(cuvee_name)
            wine_key = ensure_dim_wine(
                conn, VICO_KEY, CORSE_KEY,  # Corse (not Ajaccio)
                cuvee_name, cuvee_norm, vintage, "red", args.dry_run
            )
            if wine_key:
                print(f"  [G6 Vico] dlq={dlq_id} v={vintage} score={score}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, args.dry_run)
                resolved += 1
            continue

        # ── GROUP 7: Château Lafleur / Pomerol ───────────────────────────────
        if c_n in ("chateau lafleur", "ch. lafleur", "château lafleur") and p_n in ("chateau lafleur", "ch. lafleur", "château lafleur"):
            cuvee_name = "Château Lafleur"
            cuvee_norm = norm(cuvee_name)
            wine_key = ensure_dim_wine(
                conn, LAFLEUR_KEY, POMEROL_KEY,
                cuvee_name, cuvee_norm, vintage, "red", args.dry_run
            )
            if wine_key:
                print(f"  [G7 Lafleur] dlq={dlq_id} v={vintage} score={score}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, args.dry_run)
                resolved += 1
            continue

        # ── GROUP 8: Château Saint-Pierre / Saint-Julien ─────────────────────
        if "saint-pierre" in c_n and "saint-pierre" in p_n and "julien" in norm(appellation_raw):
            cuvee_name = "Château Saint-Pierre"
            cuvee_norm = norm(cuvee_name)
            wine_key = ensure_dim_wine(
                conn, STPIERRE_KEY, SAINT_JULIEN_KEY,
                cuvee_name, cuvee_norm, vintage, "red", args.dry_run
            )
            if wine_key:
                print(f"  [G8 St-Pierre] dlq={dlq_id} v={vintage} score={score}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, args.dry_run)
                resolved += 1
            continue

        skipped += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    print(f"\n{'='*55}")
    print(f"Resolved : {resolved}")
    print(f"Skipped  : {skipped}")
    if args.dry_run:
        print("(dry run — nothing written)")
    else:
        print(f"Batch ID : {BATCH_ID}")


if __name__ == "__main__":
    main()
