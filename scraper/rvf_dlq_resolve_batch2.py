"""
rvf_dlq_resolve_batch2.py — Second batch of online-verified RVF DLQ corrections.

Groups:
  1.  CLOS DU CALVAIRE / CdP  → producer=Clos du Calvaire (key=40322), cuvee=Clos du Calvaire
  2.  CH. DE VAUDIEU / CdP    → producer=Chateau de Vaudieu (key=8332), cuvee=Chateau de Vaudieu
  3.  CLOS DE LA ROLLETTE/ROILETTE / Fleurie → producer=Clos de la Roilette (key=177)
  4.  CH. DE RHODES / Gaillac → producer=Chateau de Rhodes (key=7205)
  5.  DOMAINE SAUMAIZE-MICHELIN / Pouilly-Fuisse → producer key=125, cuvee=Pouilly-Fuisse
  6.  DOMAINE CARRETTE / Pouilly-Fuisse / Macon → producer key=2013
  7.  DOMAINE GAYRARD / Gaillac → create new producer
  8.  DOMAINE DE BRIN / Gaillac / Vin de France → create new producer
  9.  Prieure de St-Jean de Bebian / Languedoc → producer key=6986
  10. DOMAINE PEYRE ROSE / Languedoc → producer key=628, cuvee=Clos des Cistes (flagship)

Usage:
    python rvf_dlq_resolve_batch2.py [--dry-run]
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
BATCH_ID = f"rvfmag-batch2-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower().strip()


def score_to_100(score_raw: float) -> float:
    if score_raw > 20:
        return round(score_raw, 1)
    return round((score_raw / 20.0) * 100.0, 1)


def make_wine_key(conn, producer_key: int, cuvee_norm: str, vintage) -> str | None:
    row = conn.execute("SELECT producer_norm FROM dim_producer WHERE producer_key=?", (producer_key,)).fetchone()
    if not row:
        return None
    producer_norm = row[0]
    vintage_str = str(vintage) if vintage else "NV"
    raw = f"{producer_norm}|{cuvee_norm}|{vintage_str}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def get_or_create_producer(conn, name: str, region: str, dry_run: bool) -> int | None:
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
        (int(datetime.now().timestamp()), "rvf_dlq_resolve_batch2.py", dlq_id),
    )


HEADER_CUVEES_NORM = {
    norm(x) for x in [
        "Bourgogne", "Vin de France", "Languedoc", "Macon", "Macon et Macon-villages",
        "Chateauneuf-du-Pape", "Sancerre", "Pouilly-Fume", "Cotes du Rhone",
        "Cotes du Roussillon", "Arbois-Pupillin Rouge", "Madiran",
        "Pouilly-Fuisse", "Pouilly-Loche", "Chianti Classico", "Grand cru Clos",
        "Alsace", "Pomerol", "Saint-Emilion Grand Cru",
        "Margaux", "Saint-Julien", "Pessac-Leognan", "Sauternes", "Savoie",
        "Vallee de la Loire",
    ]
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    source_key = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code=?", (SOURCE_CODE,)
    ).fetchone()[0]

    # Pre-verified producer keys
    CALVAIRE_KEY = 40322       # Clos du Calvaire (CdP)
    VAUDIEU_KEY = 8332         # Chateau de Vaudieu (CdP)
    ROILETTE_KEY = 177         # Clos de la Roilette (Fleurie)
    RHODES_KEY = 7205          # Chateau de Rhodes (Gaillac)
    SAUMAIZE_KEY = 125         # Domaine Saumaize-Michelin
    CARRETTE_KEY = 2013        # Domaine Carrette
    BEBIAN_KEY = 6986          # Prieure de Saint-Jean de Bebian
    PEYRE_ROSE_KEY = 628       # Domaine Peyre-Rose

    # Appellation keys
    CDP_KEY = 221              # Chateauneuf-du-Pape
    FLEURIE_KEY = 206          # Fleurie
    GAILLAC_KEY = 847          # Gaillac
    LANGUEDOC_KEY = 357        # Coteaux du Languedoc
    POUILLY_FUISSE_KEY = 150   # Pouilly-Fuisse
    MACON_KEY = None           # will look up

    # Macon appellation
    macon_row = conn.execute(
        "SELECT appellation_key FROM dim_appellation WHERE appellation_norm LIKE '%macon%' AND appellation_norm NOT LIKE '%villages%' ORDER BY appellation_key LIMIT 1"
    ).fetchone()
    MACON_KEY = macon_row[0] if macon_row else POUILLY_FUISSE_KEY

    # Load unresolved DLQ
    rows = conn.execute(
        "SELECT dlq_id, raw_record FROM ops_dead_letter "
        "WHERE source_key = 52 AND error_class = 'unmatched_wine' "
        "AND (resolution IS NULL OR resolution = 'pending')"
    ).fetchall()
    print(f"Total unresolved rvf_magazine DLQ rows: {len(rows)}")

    # Create missing producers
    gayrard_key = get_or_create_producer(conn, "Domaine Gayrard", "Sud-Ouest", args.dry_run)
    brin_key = get_or_create_producer(conn, "Domaine de Brin", "Sud-Ouest", args.dry_run)
    if not args.dry_run:
        conn.commit()  # flush new producers so wine_key computation works

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
        app_n = norm(appellation_raw)
        wine_key = None

        # G1: Clos du Calvaire / Chateauneuf-du-Pape (cuvee was section header)
        if ("calvaire" in p_n) and c_n in HEADER_CUVEES_NORM:
            wine_key = ensure_dim_wine(conn, CALVAIRE_KEY, CDP_KEY,
                                       "Clos du Calvaire", "clos du calvaire",
                                       vintage, "red", args.dry_run)
            if wine_key:
                print(f"  [G1 Calvaire/CdP] dlq={dlq_id} v={vintage} score={score}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                resolved += 1
            continue

        # G2: Chateau de Vaudieu / Chateauneuf-du-Pape
        if "vaudieu" in p_n and c_n in HEADER_CUVEES_NORM:
            wine_key = ensure_dim_wine(conn, VAUDIEU_KEY, CDP_KEY,
                                       "Chateau de Vaudieu", "chateau de vaudieu",
                                       vintage, "red", args.dry_run)
            if wine_key:
                print(f"  [G2 Vaudieu/CdP] dlq={dlq_id} v={vintage} score={score}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                resolved += 1
            continue

        # G3: Clos de la Rollette/Roilette / Fleurie (cuvee==producer, OCR typo)
        if ("rollette" in p_n or "roilette" in p_n) and ("rollette" in c_n or "roilette" in c_n or p_n == c_n):
            wine_key = ensure_dim_wine(conn, ROILETTE_KEY, FLEURIE_KEY,
                                       "Fleurie Clos de la Roilette", "fleurie clos de la roilette",
                                       vintage, "red", args.dry_run)
            if wine_key:
                print(f"  [G3 Roilette] dlq={dlq_id} v={vintage} score={score}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                resolved += 1
            continue

        # G4: Chateau de Rhodes / Gaillac
        if "rhodes" in p_n and ("rhodes" in c_n or p_n == c_n):
            wine_key = ensure_dim_wine(conn, RHODES_KEY, GAILLAC_KEY,
                                       "Chateau de Rhodes", "chateau de rhodes",
                                       vintage, "red", args.dry_run)
            if wine_key:
                print(f"  [G4 Rhodes/Gaillac] dlq={dlq_id} v={vintage} score={score}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                resolved += 1
            continue

        # G5: Domaine Saumaize-Michelin / Pouilly-Fuisse (cuvee was section header "Pouilly-Fuisse")
        if "saumaize" in p_n and ("fuiss" in c_n or c_n in HEADER_CUVEES_NORM):
            wine_key = ensure_dim_wine(conn, SAUMAIZE_KEY, POUILLY_FUISSE_KEY,
                                       "Pouilly-Fuisse", "pouilly-fuisse",
                                       vintage, "white", args.dry_run)
            if wine_key:
                print(f"  [G5 Saumaize/PF] dlq={dlq_id} v={vintage} score={score}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                resolved += 1
            continue

        # G6: Domaine Carrette / Pouilly-Fuisse or Macon (header cuvee)
        if "carrette" in p_n and ("fuiss" in c_n or "macon" in c_n or c_n in HEADER_CUVEES_NORM):
            app_key = POUILLY_FUISSE_KEY if "fuiss" in c_n else MACON_KEY
            wine_key = ensure_dim_wine(conn, CARRETTE_KEY, app_key,
                                       "Pouilly-Fuisse", "pouilly-fuisse",
                                       vintage, "white", args.dry_run)
            if wine_key:
                print(f"  [G6 Carrette] dlq={dlq_id} v={vintage} score={score}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                resolved += 1
            continue

        # G7: Domaine Gayrard / Gaillac (cuvee==producer)
        if "gayrard" in p_n and ("gayrard" in c_n or "gaillac" in c_n or p_n == c_n):
            pk = gayrard_key if gayrard_key != -1 else None
            if pk:
                wine_key = ensure_dim_wine(conn, pk, GAILLAC_KEY,
                                           "Domaine Gayrard", "domaine gayrard",
                                           vintage, "red", args.dry_run)
                if wine_key:
                    print(f"  [G7 Gayrard] dlq={dlq_id} v={vintage} score={score}")
                    resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                    resolved += 1
            continue

        # G8: Domaine de Brin / Gaillac or Vin de France
        if "de brin" in p_n and ("brin" in c_n or "gaillac" in c_n or "vin de france" in c_n or p_n == c_n):
            pk = brin_key if brin_key != -1 else None
            app_key = GAILLAC_KEY if "gaillac" in app_n else 530  # 530 = Corse (fallback VdF)
            # Use Gaillac for Domaine de Brin (their main appellation)
            app_key = GAILLAC_KEY
            if pk:
                wine_key = ensure_dim_wine(conn, pk, app_key,
                                           "Domaine de Brin", "domaine de brin",
                                           vintage, "red", args.dry_run)
                if wine_key:
                    print(f"  [G8 Brin] dlq={dlq_id} v={vintage} score={score}")
                    resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                    resolved += 1
            continue

        # G9: Prieure de Saint-Jean de Bebian / Languedoc
        if "bebian" in p_n:
            wine_key = ensure_dim_wine(conn, BEBIAN_KEY, LANGUEDOC_KEY,
                                       "Prieure de Saint-Jean de Bebian", "prieure de saint-jean de bebian",
                                       vintage, "red", args.dry_run)
            if wine_key:
                print(f"  [G9 Bebian] dlq={dlq_id} v={vintage} score={score}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                resolved += 1
            continue

        # G10: Domaine Peyre Rose / Languedoc (cuvee is section header "Cotes de Languedoc")
        if ("peyre" in p_n and "rose" in p_n):
            wine_key = ensure_dim_wine(conn, PEYRE_ROSE_KEY, LANGUEDOC_KEY,
                                       "Clos des Cistes", "clos des cistes",
                                       vintage, "red", args.dry_run)
            if wine_key:
                print(f"  [G10 PeyreRose] dlq={dlq_id} v={vintage} score={score}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
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
        print("(dry run -- nothing written)")
    else:
        print(f"Batch ID : {BATCH_ID}")


if __name__ == "__main__":
    main()
