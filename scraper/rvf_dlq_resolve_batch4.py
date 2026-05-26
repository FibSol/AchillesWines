"""
rvf_dlq_resolve_batch4.py — Fourth batch of RVF DLQ corrections.

Handles two categories:
A) Header-cuvee records where the producer exists in dim_producer but
   fuzzy matching fails because:
   - DLQ name is missing the 'Domaine'/'Chateau' prefix, OR
   - Stored producer_norm has hyphens replaced with spaces (import bug)

   Manually verified producer keys:
   - OLIVIER PITHON          → key=647  (Domaine Olivier Pithon, Roussillon)
   - ROLAND VAN HECKE        → key=58937 (Domaine Roland Van Hecke, Bourgogne)
   - CHATEAU PRIEURE-LICHINE → key=6989  (Chateau Prieure-Lichine, Margaux)
   - DOMAINE TINEL-BLONDELET → key=48080 (Pouilly-Fume)
   - DOMAINE LOUIS-BENJAMIN DAGUENEAU → key=58174 (Pouilly-Fume)
   - LA CAVE DU VIEL ARMAND  → key=8402  (Cave Vinicole du Vieil Armand, Alsace)
   - LE DOMAINE D EDOUARD    → key=3360  (Domaine d'Edouard, Sancerre)
   - DOMAINE CHEVEAU ET GILLES → key=416 (Domaine Cheveau, Pouilly-Fuisse)
   - DOMAINE HELENA NOTEA    → key=310   (Domaine Michel Noellat? — skip, uncertain)

B) Savoie Mondeuse cluster: 8 producers all with cuvee='Mondeuse' and no
   prior match. Create one wine per producer for each vintage.

C) Misc unresolvable:
   - Grand Arome de la Baie du Galion: rhum, not wine
   - CHATEAU LION (Ningxia): non-French producer
   - WINE ART LAND (Ningxia): non-French producer
   - Pierre Ferrand 1840: cognac, not wine
   - DOMAINE VENDOME cuvee='2023': vintage-as-cuvee (bad extraction)
   - Monay-Saint-Denis: OCR noise for Morey-Saint-Denis (unresolvable without correct wine)

Usage:
    python rvf_dlq_resolve_batch4.py [--dry-run]
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
BATCH_ID = f"rvfmag-batch4-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"

# Appellation keys
ROUSSILLON_KEY = None   # filled at runtime
MARGAUX_KEY = 212
POUILLY_FUME_KEY = None  # filled at runtime
ALSACE_KEY = 376
SANCERRE_KEY = None      # filled at runtime
POUILLY_FUISSE_KEY = 150
BOURGOGNE_KEY = None     # filled at runtime
SAVOIE_KEY = None        # filled at runtime
VDF_KEY = 305            # Vin de France fallback


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


def ensure_dim_wine(conn, producer_key, appellation_key, cuvee_name, cuvee_norm_val,
                    vintage, color, dry_run) -> str | None:
    wine_key = make_wine_key(conn, producer_key, cuvee_norm_val, vintage)
    if not wine_key:
        return None
    if conn.execute("SELECT wine_key FROM dim_wine WHERE wine_key=?", (wine_key,)).fetchone():
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
         cuvee_name, cuvee_norm_val, color,
         vintage if vintage else None, 1 if not vintage else 0,
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
        print(f"    DRY resolve dlq={dlq_id} wine={wine_key} score={score_20}/20 ({norm_score}/100)")
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
        (int(datetime.now().timestamp()), "rvf_dlq_resolve_batch4.py", dlq_id),
    )


def mark_unresolvable(conn, dlq_id: int, reason: str, dry_run: bool):
    if dry_run:
        print(f"    DRY unresolvable dlq={dlq_id}: {reason}")
        return
    conn.execute(
        "UPDATE ops_dead_letter SET resolution='unresolvable', resolved_at=?, resolved_by=?, error_message=? WHERE dlq_id=?",
        (int(datetime.now().timestamp()), "rvf_dlq_resolve_batch4.py", reason, dlq_id),
    )


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


def main():
    global ROUSSILLON_KEY, POUILLY_FUME_KEY, SANCERRE_KEY, BOURGOGNE_KEY, SAVOIE_KEY

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    source_key = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code=?", (SOURCE_CODE,)
    ).fetchone()[0]

    # Lookup appellation keys at runtime
    ROUSSILLON_KEY = conn.execute(
        "SELECT appellation_key FROM dim_appellation WHERE appellation_norm LIKE '%roussillon%' AND appellation_norm NOT LIKE '%banyuls%' LIMIT 1"
    ).fetchone()[0]
    POUILLY_FUME_KEY = conn.execute(
        "SELECT appellation_key FROM dim_appellation WHERE appellation_norm LIKE '%pouilly%fum%' LIMIT 1"
    ).fetchone()[0]
    SANCERRE_KEY = conn.execute(
        "SELECT appellation_key FROM dim_appellation WHERE appellation_norm LIKE '%sancerre%' LIMIT 1"
    ).fetchone()[0]
    BOURGOGNE_KEY = conn.execute(
        "SELECT appellation_key FROM dim_appellation WHERE appellation_name='Bourgogne' LIMIT 1"
    ).fetchone()[0]
    savoie_row = conn.execute(
        "SELECT appellation_key FROM dim_appellation WHERE appellation_norm LIKE '%savoie%' LIMIT 1"
    ).fetchone()
    SAVOIE_KEY = savoie_row[0] if savoie_row else VDF_KEY

    print(f"App keys: Roussillon={ROUSSILLON_KEY} PouillyFume={POUILLY_FUME_KEY} Sancerre={SANCERRE_KEY} Bourgogne={BOURGOGNE_KEY} Savoie={SAVOIE_KEY}")

    rows = conn.execute(
        "SELECT dlq_id, raw_record FROM ops_dead_letter "
        "WHERE source_key=52 AND error_class='unmatched_wine' "
        "AND (resolution IS NULL OR resolution='pending')"
    ).fetchall()
    print(f"Unresolved: {len(rows)}")

    # ── Pre-create Savoie producers ──────────────────────────────────────────
    # These need to be created then referenced below
    savoie_producers = {
        "domaine chevallier bernard": ("Domaine Chevallier Bernard", "Savoie"),
        "jean-francois et anne-sophie quenard": ("Jean-Francois et Anne-Sophie Quenard", "Savoie"),
        "domaine bellusiere": ("Domaine Bellusiere", "Savoie"),
        "domaine des anges": ("Domaine des Anges", "Savoie"),
        "domaine grosset": ("Domaine Grosset", "Savoie"),
        "domaine labbe": ("Domaine Labbe", "Savoie"),
        "domaine marc portaz": ("Domaine Marc Portaz", "Savoie"),
        "andre et michel avenard": ("Andre et Michel Avenard", "Savoie"),
    }
    savoie_keys = {}
    for norm_name, (display_name, region) in savoie_producers.items():
        pk = get_or_create_producer(conn, display_name, region, args.dry_run)
        savoie_keys[norm_name] = pk

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

        # ── UNRESOLVABLE: rum, cognac, non-French ───────────────────────────
        if "galion" in p_n and "arôme" in producer_raw.lower() or "arome" in p_n and "galion" in p_n:
            mark_unresolvable(conn, dlq_id, "Grand Arome de la Baie du Galion: rhum, not wine", args.dry_run)
            unresolvable += 1
            continue
        if "chateau lion" in p_n and "ningxia" in (r.get("appellation") or "").lower():
            mark_unresolvable(conn, dlq_id, "Chateau Lion Ningxia: non-French producer", args.dry_run)
            unresolvable += 1
            continue
        if "wine art land" in p_n:
            mark_unresolvable(conn, dlq_id, "Wine Art Land: non-French producer (China)", args.dry_run)
            unresolvable += 1
            continue
        if "pierre ferrand" in p_n and "1840" in c_n:
            mark_unresolvable(conn, dlq_id, "Pierre Ferrand 1840: cognac, not wine", args.dry_run)
            unresolvable += 1
            continue
        if "domaine vendome" in p_n and c_n.isdigit():
            mark_unresolvable(conn, dlq_id, "Domaine Vendome: vintage year extracted as cuvee (bad parse)", args.dry_run)
            unresolvable += 1
            continue
        if "monay" in p_n and "saint-denis" in p_n:
            mark_unresolvable(conn, dlq_id, "Monay-Saint-Denis: OCR noise for Morey-Saint-Denis, no wine_key derivable", args.dry_run)
            unresolvable += 1
            continue

        # ── GROUP A: Header-cuvee with known producer keys ───────────────────

        # A1: Olivier Pithon (Cotes du Roussillon)
        if c_n in ("cotes du roussillon", "cotes du roussillon villages") and "pithon" in p_n:
            wine_key = ensure_dim_wine(conn, 647, ROUSSILLON_KEY, "Cotes du Roussillon", norm("Cotes du Roussillon"), vintage, "red", args.dry_run)
            if wine_key:
                print(f"  [A1 Pithon] dlq={dlq_id} v={vintage}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                resolved += 1
            continue

        # A2: Roland Van Hecke (Bourgogne)
        if c_n == "bourgogne" and "van hecke" in p_n:
            wine_key = ensure_dim_wine(conn, 58937, BOURGOGNE_KEY, "Bourgogne", norm("Bourgogne"), vintage, "red", args.dry_run)
            if wine_key:
                print(f"  [A2 Van Hecke] dlq={dlq_id} v={vintage}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                resolved += 1
            continue

        # A3: Chateau Prieure-Lichine (Margaux) — cuvee=='margaux' header
        if c_n == "margaux" and ("prieure" in p_n or "prieuré" in p_n.lower()):
            wine_key = ensure_dim_wine(conn, 6989, MARGAUX_KEY, "Margaux", norm("Margaux"), vintage, "red", args.dry_run)
            if wine_key:
                print(f"  [A3 Prieure-Lichine] dlq={dlq_id} v={vintage}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                resolved += 1
            continue

        # A4: Domaine Tinel-Blondelet (Pouilly-Fume)
        if c_n in ("pouilly-fume", "pouilly fume") and "tinel" in p_n:
            wine_key = ensure_dim_wine(conn, 48080, POUILLY_FUME_KEY, "Pouilly-Fume", norm("Pouilly-Fume"), vintage, "white", args.dry_run)
            if wine_key:
                print(f"  [A4 Tinel-Blondelet] dlq={dlq_id} v={vintage}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                resolved += 1
            continue

        # A5: Domaine Louis-Benjamin Dagueneau (Pouilly-Fume)
        if c_n in ("pouilly-fume", "pouilly fume") and "dagueneau" in p_n:
            wine_key = ensure_dim_wine(conn, 58174, POUILLY_FUME_KEY, "Pouilly-Fume", norm("Pouilly-Fume"), vintage, "white", args.dry_run)
            if wine_key:
                print(f"  [A5 Dagueneau LB] dlq={dlq_id} v={vintage}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                resolved += 1
            continue

        # A6: La Cave du Viel Armand (Alsace)
        if c_n == "alsace" and ("armand" in p_n or "viel" in p_n):
            wine_key = ensure_dim_wine(conn, 8402, ALSACE_KEY, "Alsace", norm("Alsace"), vintage, "white", args.dry_run)
            if wine_key:
                print(f"  [A6 Cave Viel Armand] dlq={dlq_id} v={vintage}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                resolved += 1
            continue

        # A7: Le Domaine d'Edouard (Sancerre)
        if c_n == "sancerre" and "edouard" in p_n:
            wine_key = ensure_dim_wine(conn, 3360, SANCERRE_KEY, "Sancerre", norm("Sancerre"), vintage, "white", args.dry_run)
            if wine_key:
                print(f"  [A7 Domaine d'Edouard] dlq={dlq_id} v={vintage}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                resolved += 1
            continue

        # A8: Domaine Cheveau et Gilles (Pouilly-Fuisse)
        if c_n in ("pouilly-fuisse", "pouilly fuisse") and "cheveau" in p_n:
            wine_key = ensure_dim_wine(conn, 416, POUILLY_FUISSE_KEY, "Pouilly-Fuisse", norm("Pouilly-Fuisse"), vintage, "white", args.dry_run)
            if wine_key:
                print(f"  [A8 Cheveau] dlq={dlq_id} v={vintage}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                resolved += 1
            continue

        # A9: Leah Angles (Cotes du Roussillon)
        if c_n in ("cotes du roussillon",) and "leah" in p_n and "angles" in p_n:
            mark_unresolvable(conn, dlq_id, "Leah Angles: producer not found in dim_producer, not a known Roussillon estate", args.dry_run)
            unresolvable += 1
            continue

        # A10: Clos Saint Patrice (Chateauneuf-du-Pape)
        if c_n == "chateauneuf-du-pape" and "saint patrice" in p_n:
            mark_unresolvable(conn, dlq_id, "Clos Saint Patrice: not found in dim_producer", args.dry_run)
            unresolvable += 1
            continue

        # A11: La Sousto (Chateauneuf-du-Pape)
        if c_n == "chateauneuf-du-pape" and "sousto" in p_n:
            mark_unresolvable(conn, dlq_id, "La Sousto: not found in dim_producer", args.dry_run)
            unresolvable += 1
            continue

        # ── GROUP B: Savoie Mondeuse cluster ────────────────────────────────
        if c_n == "mondeuse" and p_n in savoie_keys:
            pk = savoie_keys[p_n]
            if pk == -1:
                skipped += 1
                continue
            savoie_app = conn.execute(
                "SELECT appellation_key FROM dim_appellation WHERE appellation_norm='savoie' LIMIT 1"
            ).fetchone()
            app_key = savoie_app[0] if savoie_app else VDF_KEY
            wine_key = ensure_dim_wine(conn, pk, app_key, "Mondeuse", norm("Mondeuse"), vintage, "red", args.dry_run)
            if wine_key:
                print(f"  [B Savoie] dlq={dlq_id} prod={producer_raw!r} v={vintage}")
                resolve_dlq_row(conn, dlq_id, wine_key, score, source_key, args.dry_run)
                resolved += 1
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
