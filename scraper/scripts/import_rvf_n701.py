"""
import_rvf_n701.py — Import RVF N°701 (June 2026) ratings + prices into Achilles staging tables.

Rules:
- Ratings  → staging_rating_candidates  (needs_review=1, critic_code='RVF', scale='/100')
- Prices   → staging_price_candidates   (source_key from dim_source WHERE source_code='rvf')
- NEVER insert directly into fact_price / fact_rating
- Uses norm_text() + compute_wine_key() from scraper/achilles_scraper/identity.py
- INSERT OR IGNORE for dim_producer / dim_appellation / dim_wine (idempotent)
- Range scores: midpoint; "98-100" cap at 100.0
- Vintage = 2025 for all Bordeaux primeurs
- Appellation fallback: dim_appellation WHERE appellation_norm='france' if not found
"""

import sys
import json
import hashlib
import logging
import sqlite3
from pathlib import Path
from time import time

# ── path bootstrap ──────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scraper"))

from achilles_scraper.identity import norm_text, normalize_producer, normalize_cuvee, compute_wine_key

# ── logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(message)s",
)
log = logging.getLogger("import_rvf_n701")

# ── constants ────────────────────────────────────────────────────────────────
DB_PATH = PROJECT_ROOT / "data" / "achilles.db"
BATCH_ID = "rvf_n701_import"
CRITIC_CODE = "RVF"
SCALE = "/100"
REVIEWER_TYPE = "critic"
COUNTRY_CODE = "FR"

# ── helpers ──────────────────────────────────────────────────────────────────

def midpoint_score(score_str) -> float:
    """Parse 'X' or 'X-Y' into a midpoint float, capped at 100."""
    s = str(score_str).strip()
    if "-" in s:
        parts = s.split("-")
        lo, hi = float(parts[0].strip()), float(parts[1].strip())
        mid = (lo + hi) / 2.0
    else:
        mid = float(s)
    return min(mid, 100.0)


def content_hash(wine_key: str, score: float, price) -> str:
    raw = f"rvf_n701_{wine_key}_{score}_{price}"
    return hashlib.sha1(raw.encode()).hexdigest()


def lookup_appellation(cur, raw_name: str, fallback_key: int, missing_log: list) -> int:
    """
    Try a cascade of norm-text lookups against dim_appellation.
    Returns (appellation_key, used_fallback:bool).
    """
    candidates = []

    # 1. direct norm
    n = norm_text(raw_name)
    candidates.append(n)

    # 2. strip "IGP " / "AOP " / "AOC " prefix
    for prefix in ("igp ", "aop ", "aoc "):
        if n.startswith(prefix):
            candidates.append(n[len(prefix):])

    # 3. known manual overrides
    OVERRIDES = {
        "saint emilion grand cru": "saint emilion grand cru",
        "vin de france": "vin de france",
        "moulis en medoc": "moulis en medoc",
        "corse sartene": "vin de corse sartene",
        "corse ajaccio": "ajaccio",
    }
    for c in list(candidates):
        if c in OVERRIDES:
            candidates.append(OVERRIDES[c])

    for candidate in candidates:
        cur.execute(
            "SELECT appellation_key FROM dim_appellation WHERE appellation_norm=? LIMIT 1",
            (candidate,),
        )
        row = cur.fetchone()
        if row:
            return row[0], False

    # fallback
    missing_log.append(raw_name)
    log.warning("Appellation not found, using France fallback: %r  (norm tried: %r)", raw_name, candidates[0])
    return fallback_key, True


def get_or_create_producer(cur, producer_display: str, now: int) -> int:
    """Return producer_key, creating if missing."""
    p_norm = normalize_producer(producer_display)
    cur.execute("SELECT producer_key FROM dim_producer WHERE producer_norm=? LIMIT 1", (p_norm,))
    row = cur.fetchone()
    if row:
        return row[0], False

    # Insert new producer
    cur.execute(
        """
        INSERT INTO dim_producer
            (producer_name, producer_norm, country_code, coverage_tier,
             allowed_appellations, aliases, status, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, 'notable', '[]', '[]', 'active', ?, ?)
        """,
        (producer_display, p_norm, COUNTRY_CODE, now, now),
    )
    new_key = cur.lastrowid
    log.info("Created producer: %r  (key=%d)", producer_display, new_key)
    return new_key, True


def get_or_create_wine(
    cur,
    producer_key: int,
    appellation_key: int,
    producer_display: str,
    cuvee_display: str,
    color: str,
    vintage,
    now: int,
) -> str:
    """Return wine_key, creating dim_wine row if missing."""
    p_norm = normalize_producer(producer_display)
    c_norm = normalize_cuvee(cuvee_display)
    wine_key = compute_wine_key(p_norm, c_norm, vintage)
    canonical = f"{producer_display} {cuvee_display}".strip()
    if vintage:
        canonical = f"{canonical} {vintage}"

    cur.execute("SELECT wine_key FROM dim_wine WHERE wine_key=?", (wine_key,))
    if cur.fetchone():
        return wine_key, False

    is_nv = 1 if vintage is None else 0
    cur.execute(
        """
        INSERT OR IGNORE INTO dim_wine
            (wine_key, producer_key, appellation_key, cuvee_name, cuvee_norm,
             color, vintage, is_non_vintage, bottle_ml, canonical_name,
             first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 750, ?, ?, ?)
        """,
        (
            wine_key, producer_key, appellation_key,
            cuvee_display if cuvee_display else "",
            c_norm,
            color,
            vintage,
            is_nv,
            canonical,
            now, now,
        ),
    )
    return wine_key, True


def insert_rating(cur, wine_key, source_key, score, raw_record, now):
    ch = content_hash(wine_key, score, None)
    cur.execute(
        """
        INSERT OR IGNORE INTO staging_rating_candidates
            (wine_key, source_key, critic_code, reviewer_type, score,
             scale, score_normalized_100, recorded_at, batch_id,
             needs_review, content_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (
            wine_key, source_key, CRITIC_CODE, REVIEWER_TYPE, score,
            SCALE, score, now, BATCH_ID, ch,
        ),
    )
    return cur.rowcount


def insert_price(cur, wine_key, source_key, price_eur, now):
    ch = content_hash(wine_key, 0, price_eur)
    cur.execute(
        """
        INSERT OR IGNORE INTO staging_price_candidates
            (wine_key, source_key, currency_code, amount_local, amount_eur,
             recorded_at, batch_id, needs_review, content_hash)
        VALUES (?, ?, 'EUR', ?, ?, ?, ?, 1, ?)
        """,
        (wine_key, source_key, price_eur, price_eur, now, BATCH_ID, ch),
    )
    return cur.rowcount


# ── WINE DATA ─────────────────────────────────────────────────────────────────
# Format: (producer, cuvee, appellation, score_or_range, price_eur_or_None, vintage, color)

BORDEAUX_VINTAGE = 2025
BORDEAUX_NOTE = "Bordeaux primeur en-fût, avril 2025"

WINES = []

# ── Saint-Émilion Grand Cru ──────────────────────────────────────────────────
for row in [
    ("Château Pavie Macquin",           "", "Saint-Émilion Grand Cru", "93-96", 50.40),
    ("Château Beau-Séjour Bécot",       "", "Saint-Émilion Grand Cru", "94-95", 52.90),
    ("Château Valandraud",              "", "Saint-Émilion Grand Cru", "93-95", 108.0),
    ("Château Canon",                   "", "Saint-Émilion Grand Cru", "92-95", 40.0),
    ("Château Fonroque",                "", "Saint-Émilion Grand Cru", "92-95", 27.25),
    ("Château Grand Corbin-Despagne",   "", "Saint-Émilion Grand Cru", "92-95", 30.20),
    ("Château L'If",                    "", "Saint-Émilion Grand Cru", "93-94", 78.0),
    ("Château Dassault",                "", "Saint-Émilion Grand Cru", "93-94", 96.0),
    ("Château Fleur Cardinale",         "", "Saint-Émilion Grand Cru", "92-94", 42.30),
    ("Château Côte de Baleau",          "", "Saint-Émilion Grand Cru", "92-94", 16.80),
    ("Château Saint Georges Côte Pavie","", "Saint-Émilion Grand Cru", "92-94", 26.05),
    ("Château Pavie",                   "", "Saint-Émilion Grand Cru", "92-94", 58.80),
    ("Château Berliquet",               "", "Saint-Émilion Grand Cru", "92-94", 36.25),
    ("Château Mangot",                  "", "Saint-Émilion Grand Cru", "92-94", 45.90),
    ("Château Rocheyron",               "", "Saint-Émilion Grand Cru", "92-94", None),
    ("Château Joanin Bécot",            "", "Saint-Émilion Grand Cru", "92-93", 18.60),
    ("Château Laroque",                 "", "Saint-Émilion Grand Cru", "92-93", 23.90),
    ("Château La Marzelle",             "", "Saint-Émilion Grand Cru", "92-93", 46.30),
    ("Château Boutisse",                "", "Saint-Émilion Grand Cru", "92-93", None),
    ("Château Sanctus",                 "", "Saint-Émilion Grand Cru", "92-93", None),
]:
    WINES.append((*row, BORDEAUX_VINTAGE, "rouge"))

# ── Pomerol ──────────────────────────────────────────────────────────────────
for row in [
    ("Château Pétrus",                      "", "Pomerol",       "97-99",  2160.0),
    ("Château La Conseillante",             "", "Pomerol",       "96-97",  166.0),
    ("Le Pin",                              "", "Pomerol",       "96-97",  2280.0),
    ("Château L'Église-Clinet",             "", "Pomerol",       "95-97",  None),
    ("Château Trotanoy",                    "", "Pomerol",       "95-97",  171.0),
    ("Château Hosanna",                     "", "Pomerol",       "94-96",  134.0),
    ("Château La Fleur-Pétrus",             "", "Pomerol",       "94-96",  155.0),
    ("Château La Violette",                 "", "Pomerol",       "94-96",  63.0),
    ("Château L'Évangile",                  "", "Pomerol",       "93-96",  252.0),
    ("Château Clinet",                      "", "Pomerol",       "93-96",  117.0),
    ("Château Nénin",                       "", "Pomerol",       "93-96",  55.80),
    ("Château Gazin",                       "", "Pomerol",       "93-95",  84.0),
    ("Château Petit-Village",               "", "Pomerol",       "93-95",  None),
    ("Château du Domaine de l'Église",      "", "Pomerol",       "93-95",  None),
    ("Château Lafleur",                     "", "Vin de France", "97-99",  1000.0),
]:
    WINES.append((*row, BORDEAUX_VINTAGE, "rouge"))

# ── Pauillac ─────────────────────────────────────────────────────────────────
for row in [
    ("Château Lafite Rothschild",                       "", "Pauillac", "97-98", 258.0),
    ("Château Mouton Rothschild",                       "", "Pauillac", "97-98", 258.0),
    ("Château Pichon Longueville Comtesse de Lalande",  "", "Pauillac", "96-98", 126.0),
    ("Château Pichon Baron",                            "", "Pauillac", "96-97", 114.0),
    ("Château Pontet-Canet",                            "", "Pauillac", "96-97", 38.0),
    ("Château Lynch-Bages",                             "", "Pauillac", "95-97", 66.50),
    ("Château Grand-Puy-Lacoste",                       "", "Pauillac", "95-96", None),
    ("Château Clerc Milon",                             "", "Pauillac", "95-96", 84.0),
    ("Château Batailley",                               "", "Pauillac", "95-96", None),
    ("Château d'Armailhac",                             "", "Pauillac", "94-95", 39.0),
    ("Château Duhart-Milon",                            "", "Pauillac", "94-95", 64.0),
]:
    WINES.append((*row, BORDEAUX_VINTAGE, "rouge"))

# ── Saint-Julien ─────────────────────────────────────────────────────────────
for row in [
    ("Château Ducru-Beaucaillou",  "", "Saint-Julien", "97-98", 126.0),
    ("Château Léoville Barton",    "", "Saint-Julien", "96-98", 68.40),
    ("Château Léoville Poyferré",  "", "Saint-Julien", "96-97", 67.20),
    ("Château Beychevelle",        "", "Saint-Julien", "96-97", 81.60),
    ("Château Talbot",             "", "Saint-Julien", "95-96", 45.35),
    ("Château Branaire-Ducru",     "", "Saint-Julien", "94-96", 37.20),
    ("Château Langoa Barton",      "", "Saint-Julien", "93-95", 28.55),
]:
    WINES.append((*row, BORDEAUX_VINTAGE, "rouge"))

# ── Margaux ───────────────────────────────────────────────────────────────────
for row in [
    ("Château Margaux", "", "Margaux", "98-100", None),
    ("Château Palmer",  "", "Margaux", "96-97",  None),
]:
    WINES.append((*row, BORDEAUX_VINTAGE, "rouge"))

# ── Pessac-Léognan ───────────────────────────────────────────────────────────
for row in [
    ("Château Haut-Brion",         "", "Pessac-Léognan", "98-99",   366.0),
    ("Château La Mission Haut-Brion","", "Pessac-Léognan", "97-100", None),
    ("Château Haut-Bailly",        "", "Pessac-Léognan", "96-97",   84.50),
    ("Château Smith Haut Lafitte", "", "Pessac-Léognan", "95-96",   151.0),
    ("Domaine de Chevalier",       "", "Pessac-Léognan", "94-95",   99.0),
    ("Château Malartic-Lagravière","", "Pessac-Léognan", "93-94",   54.0),
    ("Château Olivier",            "", "Pessac-Léognan", "92-94",   31.0),
    ("Château La Solitude",        "", "Pessac-Léognan", "91-92",   19.0),
]:
    WINES.append((*row, BORDEAUX_VINTAGE, "rouge"))

# ── Haut-Médoc / Moulis ──────────────────────────────────────────────────────
for row in [
    ("Château Cantemerle",                      "",                "Haut-Médoc",       "92-94", 22.70,  BORDEAUX_VINTAGE, "rouge"),
    ("Château Sociando-Mallet",                 "",                "Haut-Médoc",       "92-94", 26.05,  BORDEAUX_VINTAGE, "rouge"),
    ("Château La Lagune",                       "",                "Haut-Médoc",       "91-93", 28.50,  BORDEAUX_VINTAGE, "rouge"),
    ("Château Lestage-Darquier Grand Poujeaux", "Grand Poujeaux",  "Moulis-en-Médoc",  "93-94", 20.40,  BORDEAUX_VINTAGE, "rouge"),
]:
    WINES.append(row)

# ── Châteauneuf-du-Pape blancs ───────────────────────────────────────────────
for row in [
    ("Château Rayas",               "Blanc",               "Châteauneuf-du-Pape", 98.5,  136.0, 2023, "blanc"),
    ("Domaine de Marcoux",          "Blanc",               "Châteauneuf-du-Pape", 98.0,  50.0,  2023, "blanc"),
    ("Famille Isabel Ferrando",     "Vieilles Clairettes", "Vin de France",       98.0,  300.0, 2023, "blanc"),
    ("Clos des Papes",              "Blanc",               "Châteauneuf-du-Pape", 96.5,  62.0,  2024, "blanc"),
    ("Domaine du Vieux Télégraphe", "Blanc",               "Châteauneuf-du-Pape", 96.0,  78.0,  2023, "blanc"),
]:
    WINES.append(row)

# ── Languedoc blancs ─────────────────────────────────────────────────────────
for row in [
    ("Domaine les Aurelles",        "La Roussane",                 "Vin de France",               96.0, 170.0, 2020, "blanc"),
    ("Domaine d'Aupilhac",          "Orv",                         "Languedoc",                   95.0, 129.0, 2024, "blanc"),
    ("Domaine Alain Chabanon",      "Trélans",                     "IGP Saint-Guilhem-le-Désert", 94.0, 32.0,  2022, "blanc"),
    ("Domaine Le Conte des Floris", "Lune Blanche",                "Languedoc",                   94.0, 45.0,  2022, "blanc"),
    ("Domaine du Pas de l'Escalette","Mas Rousseau",               "IGP Pays d'Hérault",          94.0, 34.0,  2023, "blanc"),
    ("Mas Jullien",                 "Blanc de Raisins Blancs",     "IGP Pays d'Hérault",          94.0, 43.0,  2023, "blanc"),
    ("Roc d'Anglade",               "Blanc",                       "IGP Gard",                    94.0, 47.0,  2023, "blanc"),
    ("Domaine de Montcalmès",       "Blanc",                       "Languedoc",                   93.0, 32.0,  2022, "blanc"),
    ("Clos Saint Sébastien",        "Inspiration Minérale",        "Collioure",                   92.0, 34.0,  2023, "blanc"),
    ("Coume del Mas",               "Folio Edition Spéciale",      "Collioure",                   92.0, 32.0,  2023, "blanc"),
    ("Mas Amiel",                   "Altaïr",                      "Côtes du Roussillon",         92.0, 29.0,  2024, "blanc"),
]:
    WINES.append(row)

# ── Provence/Rhône blancs ────────────────────────────────────────────────────
for row in [
    ("Domaine Milan",     "Grand Blanc", "Vin de France", 92.0, 35.0, 2019, "blanc"),
    ("Domaine du Paternel","Blanc",      "Cassis",        92.0, 20.0, 2020, "blanc"),
    ("Domaine Ray-Jane",  "Insulée",     "IGP Var",       92.0, 30.0, 2023, "blanc"),
]:
    WINES.append(row)

# ── Rosés 2025 ────────────────────────────────────────────────────────────────
for row in [
    ("Domaine du Pas de l'Escalette", "Rosé",                 "IGP Pays d'Hérault",  92.0, 8.0,   2025, "rosé"),
    ("Tour de Corent",                "Rosé",                 "Côtes d'Auvergne",    92.0, 7.60,  2025, "rosé"),
    ("Domaine Fontchêne",             "Léon",                 "IGP Alpilles",        92.0, 16.0,  2025, "rosé"),
    ("Domaine Alône",                 "Almo",                 "Vin de France",       92.0, 16.0,  2025, "rosé"),
    ("Domaine Py",                    "Antoine",              "Corbières",           92.0, 13.0,  2025, "rosé"),
    ("Domaine Pradeaux",              "Rosé",                 "Vin de France",       92.0, 15.0,  2025, "rosé"),
    ("Myrko Tépus",                   "Dal Solera",           "Vin de France",       92.0, 17.0,  2025, "rosé"),
    ("Château de Caille",             "Rosé",                 "Côtes de Provence",   92.0, 23.90, 2025, "rosé"),
    ("Clos Mirages",                  "Rosé",                 "Côtes de Provence",   92.0, 13.90, 2025, "rosé"),
    ("Mas de Cadenet",                "Rosé",                 "Côtes de Provence",   90.0, 10.0,  2025, "rosé"),
    ("Christophe Avi",                "M'Avi en Rosé",        "Vin de France",       90.0, 8.50,  2025, "rosé"),
    ("Château de Beaupré",            "Façon Phanette",       "Vin de France",       89.0, 9.0,   2025, "rosé"),
    ("Les Chemins de l'Arkose",       "Corent Gamay",         "Côtes d'Auvergne",   92.0, 13.0,  2024, "rosé"),
    ("Castellu d'Alba",               "Rosé",                 "Corse",               92.0, 20.0,  2025, "rosé"),
    ("Castellu di Baricci",           "Rosé",                 "Corse Sartenè",       92.0, 18.0,  2025, "rosé"),
    ("Sant Armettu",                  "Myrtus",               "IGP Île de Beauté",   92.0, 19.0,  2025, "rosé"),
    ("Domaine Comte Peraldi",         "Rosé",                 "Corse Ajaccio",       92.0, 17.50, 2025, "rosé"),
    ("Clos Canereccia",               "Cuvée des Pierres",    "Corse",               91.0, 12.95, 2025, "rosé"),
]:
    WINES.append(row)

# ── Crémants / Bulles ─────────────────────────────────────────────────────────
for row in [
    ("Dominique Gruhier", "Grande Cuvée Pinot Noir d'Édouard Extra Brut", "Crémant de Bourgogne", 93.0,  22.50, 2018, "blanc"),
    ("Bruno Dangin",      "Prestige de Nançois",                          "Crémant de Bourgogne", 92.5,  23.0,  2021, "blanc"),
    ("Domaine Léon Boesch","Soixante-Douze Vendanges",                    "Crémant d'Alsace",     92.5,  17.50, 2023, "blanc"),
    ("Albert Mann",       "Extra-Brut",                                   "Crémant d'Alsace",     91.5,  23.50, 2022, "blanc"),
    ("Camille Braun",     "La Colline",                                   "Crémant d'Alsace",     91.0,  14.0,  2022, "blanc"),
    ("Mélanie Pfister",   "Extra-Brut de Blanc",                          "Crémant d'Alsace",     88.5,  13.0,  2023, "blanc"),
    ("Domaine Gresser",   "Brut",                                         "Crémant d'Alsace",     88.0,  14.0,  None, "blanc"),
]:
    WINES.append(row)

# ── Appellation name normalisation overrides ──────────────────────────────────
# Map raw appellation strings to the norm we want to look up in dim_appellation.
# This is a pre-processing step so we don't have to special-case inside the loop.
APP_NORM_OVERRIDES = {
    "Saint-Émilion Grand Cru":        "saint emilion grand cru",
    "Pomerol":                         "pomerol",
    "Pauillac":                        "pauillac",
    "Saint-Julien":                    "saint julien",
    "Margaux":                         "margaux",
    "Pessac-Léognan":                  "pessac leognan",
    "Haut-Médoc":                      "haut medoc",
    "Moulis-en-Médoc":                 "moulis en medoc",
    "Châteauneuf-du-Pape":            "chateauneuf du pape",
    "Languedoc":                       "languedoc",
    "IGP Saint-Guilhem-le-Désert":    "igp saint guilhem le desert",
    "IGP Pays d'Hérault":             "igp pays d herault",
    "IGP Gard":                        "igp gard",
    "IGP Var":                         "igp var",
    "IGP Alpilles":                    "igp alpilles",
    "IGP Île de Beauté":              "igp ile de beaute",
    "Collioure":                       "collioure",
    "Côtes du Roussillon":            "cotes du roussillon",
    "Cassis":                          "cassis",
    "Côtes de Provence":              "cotes de provence",
    "Côtes d'Auvergne":              "cotes d auvergne",
    "Corse":                           "corse",
    "Corse Sartenè":                  "vin de corse sartene",
    "Corse Ajaccio":                  "ajaccio",
    "Corbières":                       "corbieres",
    "Crémant de Bourgogne":           "cremant de bourgogne",
    "Crémant d'Alsace":              "cremant d alsace",
    "Vin de France":                   "vin de france",
}

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Look up RVF source_key
    cur.execute("SELECT source_key FROM dim_source WHERE source_code='rvf' LIMIT 1")
    row = cur.fetchone()
    if not row:
        log.error("RVF source not found in dim_source. Aborting.")
        sys.exit(1)
    rvf_source_key = row[0]
    log.info("RVF source_key = %d", rvf_source_key)

    # Look up France fallback appellation_key
    cur.execute("SELECT appellation_key FROM dim_appellation WHERE appellation_norm='france' LIMIT 1")
    row = cur.fetchone()
    if not row:
        log.error("France fallback appellation not found. Aborting.")
        sys.exit(1)
    fallback_app_key = row[0]
    log.info("France fallback appellation_key = %d", fallback_app_key)

    now = int(time())
    missing_appellations = []
    stats = {
        "producers_found": 0,
        "producers_created": 0,
        "wines_found": 0,
        "wines_created": 0,
        "ratings_inserted": 0,
        "prices_inserted": 0,
        "appellation_fallbacks": 0,
    }

    # Pre-build appellation cache from dim_appellation
    cur.execute("SELECT appellation_key, appellation_norm FROM dim_appellation")
    app_cache = {r[1]: r[0] for r in cur.fetchall()}

    def fast_lookup_app(raw_name: str) -> tuple[int, bool]:
        """Fast cached appellation lookup."""
        # Try override first
        override_norm = APP_NORM_OVERRIDES.get(raw_name)
        if override_norm and override_norm in app_cache:
            return app_cache[override_norm], False

        # Try norm_text directly
        n = norm_text(raw_name)
        if n in app_cache:
            return app_cache[n], False

        # Strip IGP/AOP/AOC prefix
        for prefix in ("igp ", "aop ", "aoc "):
            if n.startswith(prefix):
                stripped = n[len(prefix):]
                if stripped in app_cache:
                    return app_cache[stripped], False

        # Fallback
        missing_appellations.append(raw_name)
        log.warning("Appellation fallback (France) for: %r", raw_name)
        return fallback_app_key, True

    try:
        for entry in WINES:
            producer_display, cuvee_display, appellation_raw, score_raw, price_raw, vintage, color = entry

            score = midpoint_score(score_raw)

            # Appellation
            app_key, used_fallback = fast_lookup_app(appellation_raw)
            if used_fallback:
                stats["appellation_fallbacks"] += 1

            # Producer
            producer_key, created = get_or_create_producer(cur, producer_display, now)
            if created:
                stats["producers_created"] += 1
            else:
                stats["producers_found"] += 1

            # Wine
            wine_key, created = get_or_create_wine(
                cur, producer_key, app_key,
                producer_display, cuvee_display,
                color, vintage, now,
            )
            if created:
                stats["wines_created"] += 1
            else:
                stats["wines_found"] += 1

            # Rating
            n = insert_rating(cur, wine_key, rvf_source_key, score, None, now)
            stats["ratings_inserted"] += n

            # Price
            if price_raw is not None:
                n = insert_price(cur, wine_key, rvf_source_key, float(price_raw), now)
                stats["prices_inserted"] += n

        conn.commit()
        log.info("Commit OK")
    except Exception:
        conn.rollback()
        log.exception("Import failed — rolled back")
        sys.exit(1)
    finally:
        conn.close()

    # ── summary ───────────────────────────────────────────────────────────────
    total_wines = len(WINES)
    fallback_pct = 100 * stats["appellation_fallbacks"] / max(total_wines, 1)

    print()
    print("=" * 60)
    print("  RVF N°701 Import Summary")
    print("=" * 60)
    print(f"  Total wine entries processed : {total_wines}")
    print(f"  Producers found in DB        : {stats['producers_found']}")
    print(f"  Producers created (new)      : {stats['producers_created']}")
    print(f"  Wines found in DB            : {stats['wines_found']}")
    print(f"  Wines created (new)          : {stats['wines_created']}")
    print(f"  Ratings inserted             : {stats['ratings_inserted']}")
    print(f"  Prices inserted              : {stats['prices_inserted']}")
    print(f"  Appellation fallbacks        : {stats['appellation_fallbacks']} ({fallback_pct:.1f}%)")
    if missing_appellations:
        print(f"  Missing appellations        : {sorted(set(missing_appellations))}")
    if fallback_pct > 40:
        print("  WARNING: Appellation fallback rate exceeds 40%!")
    print("=" * 60)
    print("  batch_id:", BATCH_ID)
    print("  source_key (RVF):", rvf_source_key)
    print("=" * 60)


if __name__ == "__main__":
    main()
