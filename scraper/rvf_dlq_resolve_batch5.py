"""
rvf_dlq_resolve_batch5.py — Fifth batch of online-verified RVF DLQ corrections.

Groups handled (cuvee==producer, name mismatch vs dim_producer):
  1.  Camille Cayran (CDR)     → key=2170 (Maison Camille Cayran)
  2.  Vigneron de 4 Chemins   → key=7056 (Les Vignerons des Quatre Chemins)
  3.  Vignerons d'Ajaccio     → create new producer
  4.  Fabien Duveau (Sancerre/Saumur) → key=3341 (Domaine Fabien Duveau)
  5.  Christophe Avi (Bergerac/Buzet) → create new producer
  6.  Domaine de Bonneril     → key=1607 (OCR error for Bonnefil)
  7.  Leo de Prades           → key=5396 (Chateau Leo de Prades)
  8.  Turtac (Bordeaux)       → key=51202 (OCR error for Tutiac)
  9.  Cave des Demoiselles    → key=32044 (Cellier des Demoiselles)
  10. Cave de Castelmaure     → key=31470
  11. Cave de Saint-Chinian   → key=7536 (Cave des Vignerons de Saint-Chinian)
  12. Domaine de Joyeuse      → key=4697 (Cave Anne de Joyeuse)
  13. Vignobles de Montesquieu → key=6199 (Montesquieu)
  14. La Romaine (Gigondas)   → key=7358 (Cave La Romaine)
  15. Terres Secretes         → key=8028 (Vignerons des Terres Secretes)
  16. Vignerons d'Ige         → key=8466
  17. Huton-Beaunoy (OCR)     → key=36039 (Nuiton-Beaunoy)

Unresolvable:
  - Domaine de Rocqueville, Princesse des Braves, Compagnie Andeye,
    Domaine Arnaud Simon, Chateau Abreuvoir Imperial, Helicon,
    Domaine Plenium, Domaine Vallee Moray, Marie Thibault, Marielle Michot,
    Domaine Achilles (not Achillee), Domaine Seres (Alsace), Comte des Corneilles

Usage:
    python rvf_dlq_resolve_batch5.py [--dry-run]
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
BATCH_ID = f"rvfmag-batch5-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"

# Producer keys (verified)
CAMILLE_CAYRAN_KEY = 2170
QUATRE_CHEMINS_KEY = 7056
FABIEN_DUVEAU_KEY = 3341
BONNEFIL_KEY = 1607       # used for BONNERIL (OCR variant)
LEO_PRADES_KEY = 5396
TUTIAC_KEY = 51202        # used for TURTAC (OCR variant)
CELLIER_DEMOISELLES_KEY = 32044
CAVE_CASTELMAURE_KEY = 31470
VIGNERONS_CHINIAN_KEY = 7536
ANNE_DE_JOYEUSE_KEY = 4697
MONTESQUIEU_KEY = 6199
CAVE_ROMAINE_KEY = 7358
TERRES_SECRETES_KEY = 8028
VIGNERONS_IGE_KEY = 8466
NUITON_BEAUNOY_KEY = 36039

# Appellation keys
CAIRANNE_KEY = 297
LAUDUN_KEY = 1078
AJACCIO_KEY = 951
SAUMUR_CHAMP_KEY = 368
BUZET_KEY = 1103
GAILLAC_KEY = 847
SAINT_ESTEPHE_KEY = 211
BORDEAUX_KEY = 224
CORBIERES_KEY = 309
SAINT_CHINIAN_KEY = 513
LANGUEDOC_KEY = 357
PIC_SAINT_LOUP_KEY = 257
GIGONDAS_KEY = 244
SAINT_VERAN_KEY = 196
MACON_KEY = 817
BOURGOGNE_KEY = 230
CDR_KEY = 242             # Cotes du Rhone
VDF_KEY = 305             # Vin de France fallback


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


def ensure_dim_wine(conn, producer_key, appellation_key, cuvee_name, cuvee_norm_val,
                    vintage, color, dry_run) -> str | None:
    wine_key = make_wine_key(conn, producer_key, cuvee_norm_val, vintage)
    if not wine_key:
        return None
    if conn.execute("SELECT wine_key FROM dim_wine WHERE wine_key=?", (wine_key,)).fetchone():
        return wine_key
    if dry_run:
        prod_name = conn.execute("SELECT producer_name FROM dim_producer WHERE producer_key=?", (producer_key,)).fetchone()
        pname = prod_name[0] if prod_name else f"pk={producer_key}"
        print(f"    DRY new wine: {wine_key} | {pname!r} / {cuvee_name!r} v{vintage} [{color}]")
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
        (int(datetime.now().timestamp()), "rvf_dlq_resolve_batch5.py", dlq_id),
    )


def mark_unresolvable(conn, dlq_id: int, reason: str, dry_run: bool):
    if dry_run:
        return
    conn.execute(
        "UPDATE ops_dead_letter SET resolution='unresolvable', resolved_at=?, resolved_by=?, error_message=? WHERE dlq_id=?",
        (int(datetime.now().timestamp()), "rvf_dlq_resolve_batch5.py", reason, dlq_id),
    )


def handle(conn, dlq_id, producer_key, appellation_key, cuvee_name, vintage, color, score, source_key, label, dry_run):
    """Create wine + resolve DLQ row, return True on success."""
    if producer_key == -1:
        return False
    wine_key = ensure_dim_wine(conn, producer_key, appellation_key, cuvee_name, norm(cuvee_name), vintage, color, dry_run)
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

    # Pre-create new producers
    ajaccio_key = get_or_create_producer(conn, "Les Vignerons d'Ajaccio", "Corse", args.dry_run)
    christophe_avi_key = get_or_create_producer(conn, "Domaine Christophe Avi", "Buzet", args.dry_run)

    rows = conn.execute(
        "SELECT dlq_id, raw_record FROM ops_dead_letter "
        "WHERE source_key=52 AND error_class='unmatched_wine' "
        "AND (resolution IS NULL OR resolution='pending')"
    ).fetchall()
    print(f"Unresolved: {len(rows)}")

    resolved = 0
    unresolvable = 0
    skipped = 0

    UNRESOLVABLE_KEYWORDS = {
        "rocqueville": "Domaine de Rocqueville: unconfirmed (possible OCR for Rocheville)",
        "princesse des braves": "Princesse des Braves: not a real producer",
        "andeye": "Compagnie Andeye: not a real producer",
        "arnaud simon": "Domaine Arnaud Simon: unconfirmed producer",
        "abreuvoir": "Chateau Abreuvoir Imperial: not a real producer",
        "helicon": "Helicon: not found in dim_producer",
        "plenium": "Domaine Plenium: not found in dim_producer",
        "vallee moray": "Domaine Vallee Moray: not found in dim_producer",
        "marie thibault": "Marie Thibault: not found in dim_producer",
        "marielle michot": "Marielle Michot: not found in dim_producer",
        "corneilles": "Comte des Corneilles: not found in dim_producer",
        "helene notea": "Domaine Helena Notea: not found in dim_producer",
        "domaine achilles": "Domaine Achilles: not Achillee, not found in dim_producer",
        "seres, les origines": "Domaine Seres Les Origines: not found in dim_producer",
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
        app_raw = (r.get("appellation") or "").strip()

        # Check unresolvable keywords
        matched_unres = False
        for kw, reason in UNRESOLVABLE_KEYWORDS.items():
            if kw in p_n:
                mark_unresolvable(conn, dlq_id, reason, args.dry_run)
                unresolvable += 1
                matched_unres = True
                break
        if matched_unres:
            continue

        ok = False

        # ── CUVEE == PRODUCER GROUPS ─────────────────────────────────────────

        if p_n == c_n:
            # G1: Camille Cayran (Cotes du Rhone / Cairanne)
            if "cayran" in p_n:
                ok = handle(conn, dlq_id, CAMILLE_CAYRAN_KEY, CAIRANNE_KEY, "Camille Cayran", vintage, "red", score, source_key, "G1 Cayran", args.dry_run)

            # G2: Vigneron de 4 Chemins / Laudun
            elif "4 chemin" in p_n or "quatre chemin" in p_n:
                ok = handle(conn, dlq_id, QUATRE_CHEMINS_KEY, LAUDUN_KEY, "Les Vignerons des Quatre Chemins", vintage, "red", score, source_key, "G2 4Chemins", args.dry_run)

            # G3: Les Vignerons d'Ajaccio
            elif "vignerons d ajaccio" in p_n or "vignerons d'ajaccio" in p_n:
                pk = ajaccio_key if ajaccio_key != -1 else None
                if pk:
                    ok = handle(conn, dlq_id, pk, AJACCIO_KEY, "Les Vignerons d'Ajaccio", vintage, "red", score, source_key, "G3 Ajaccio", args.dry_run)

            # G4: Fabien Duveau (DLQ says Sancerre, actually Saumur-Champigny)
            elif "duveau" in p_n and "fabien" in p_n:
                ok = handle(conn, dlq_id, FABIEN_DUVEAU_KEY, SAUMUR_CHAMP_KEY, "Domaine Fabien Duveau", vintage, "red", score, source_key, "G4 Duveau", args.dry_run)

            # G5: Christophe Avi (DLQ says Bergerac, actually Buzet/Brulhois)
            elif "christophe avi" in p_n:
                pk = christophe_avi_key if christophe_avi_key != -1 else None
                if pk:
                    ok = handle(conn, dlq_id, pk, BUZET_KEY, "Domaine Christophe Avi", vintage, "red", score, source_key, "G5 ChrisAvi", args.dry_run)

            # G6: Domaine de Bonneril (OCR error for Bonnefil)
            elif "bonneril" in p_n:
                ok = handle(conn, dlq_id, BONNEFIL_KEY, GAILLAC_KEY, "Domaine de Bonnefil", vintage, "red", score, source_key, "G6 Bonneril->Bonnefil", args.dry_run)

            # G7: Leo de Prades (Saint-Estephe)
            elif "prades" in p_n and ("leo" in p_n or "léo" in producer_raw.lower()):
                ok = handle(conn, dlq_id, LEO_PRADES_KEY, SAINT_ESTEPHE_KEY, "Chateau Leo de Prades", vintage, "red", score, source_key, "G7 LeoPrades", args.dry_run)

            # G8: Turtac (OCR for Tutiac/Vignerons de Tutiac)
            elif "turtac" in p_n:
                ok = handle(conn, dlq_id, TUTIAC_KEY, BORDEAUX_KEY, "Les Vignerons de Tutiac", vintage, "red", score, source_key, "G8 Turtac->Tutiac", args.dry_run)

            # G9: Cave des Demoiselles (= Cellier des Demoiselles, Corbieres)
            elif "demoiselles" in p_n and "cave" in p_n:
                ok = handle(conn, dlq_id, CELLIER_DEMOISELLES_KEY, CORBIERES_KEY, "Cellier des Demoiselles", vintage, "red", score, source_key, "G9 Demoiselles", args.dry_run)

            # G10: Cave de Castelmaure (Corbieres)
            elif "castelmaure" in p_n:
                ok = handle(conn, dlq_id, CAVE_CASTELMAURE_KEY, CORBIERES_KEY, "Cave de Castelmaure", vintage, "red", score, source_key, "G10 Castelmaure", args.dry_run)

            # G11: Cave de Saint-Chinian (= Cave des Vignerons de Saint-Chinian)
            elif "saint-chinian" in p_n or "saint chinian" in p_n:
                ok = handle(conn, dlq_id, VIGNERONS_CHINIAN_KEY, SAINT_CHINIAN_KEY, "Cave de Saint-Chinian", vintage, "red", score, source_key, "G11 StChinian", args.dry_run)

            # G12: Domaine de Joyeuse (= Cave Anne de Joyeuse, Languedoc/Limoux)
            elif "joyeuse" in p_n:
                ok = handle(conn, dlq_id, ANNE_DE_JOYEUSE_KEY, LANGUEDOC_KEY, "Cave Anne de Joyeuse", vintage, "red", score, source_key, "G12 Joyeuse", args.dry_run)

            # G13: Vignobles de Montesquieu (Pic-Saint-Loup)
            elif "montesquieu" in p_n:
                ok = handle(conn, dlq_id, MONTESQUIEU_KEY, PIC_SAINT_LOUP_KEY, "Montesquieu", vintage, "red", score, source_key, "G13 Montesquieu", args.dry_run)

            # G14: La Romaine (Gigondas) — cooperate Cave La Romaine Vaison
            elif p_n in ("la romaine", "cave la romaine"):
                ok = handle(conn, dlq_id, CAVE_ROMAINE_KEY, GIGONDAS_KEY, "Cave La Romaine", vintage, "red", score, source_key, "G14 LaRomaine", args.dry_run)

            # G15: Terres Secretes (Saint-Veran)
            elif "terres secret" in p_n:
                ok = handle(conn, dlq_id, TERRES_SECRETES_KEY, SAINT_VERAN_KEY, "Vignerons des Terres Secretes", vintage, "white", score, source_key, "G15 TerresSecr", args.dry_run)

            # G16: Vignerons d'Ige (Macon)
            elif "d ige" in p_n or "d'ige" in p_n:
                ok = handle(conn, dlq_id, VIGNERONS_IGE_KEY, MACON_KEY, "Les Vignerons d'Ige", vintage, "white", score, source_key, "G16 Ige", args.dry_run)

            # G17: Huton-Beaunoy (OCR for Nuiton-Beaunoy, Nuits-Saint-Georges area)
            elif "huton" in p_n and "beaunoy" in p_n:
                ok = handle(conn, dlq_id, NUITON_BEAUNOY_KEY, BOURGOGNE_KEY, "Nuiton-Beaunoy", vintage, "red", score, source_key, "G17 Huton->Nuiton", args.dry_run)

        # ── HEADER-CUVEE GROUPS (producer != cuvee) ──────────────────────────
        else:
            # H1: HELION / HELICON with cuvee=Vin de France — not in DB, skip
            # H2: DOMAINE PLENIUM with cuvee=Languedoc — not in DB, skip
            # H3: DOMAINE VALLEE MORAY — not in DB, skip
            # H4: MARIE THIBAULT — not in DB, skip
            # H5: MARIELLE MICHOT (Sancerre) — not in DB, skip
            # These are already handled by unresolvable keyword check above if applicable
            pass

        if ok:
            resolved += 1
        elif not matched_unres:
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
