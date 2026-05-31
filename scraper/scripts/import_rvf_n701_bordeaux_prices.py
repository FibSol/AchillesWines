"""
import_rvf_n701_bordeaux_prices.py
RVF N°701 (June 2026) — Bordeaux primeurs 2025 pages 124-143.

Covers:
  p.124-127  Pomerol + Lalande-de-Pomerol
  p.128-131  Médoc / Moulis / Margaux
  p.132-135  Pauillac + Saint-Estèphe
  p.136-139  Saint-Julien + Pessac-Léognan (rouges)
  p.140-143  Pessac-Léognan (blancs) + Sauternes

Ratings (vintage=2025) → staging_rating_candidates
Prices (vintage=2024 or 2023) → staging_price_candidates
batch_id = 'rvf_n701_bdx_prices'
INSERT OR IGNORE (idempotent)
"""

import sys
import hashlib
import logging
import sqlite3
from pathlib import Path
from time import time

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scraper"))

from achilles_scraper.identity import norm_text, normalize_producer, normalize_cuvee, compute_wine_key

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("import_rvf_n701_bdx_prices")

DB_PATH = PROJECT_ROOT / "data" / "achilles.db"
BATCH_ID = "rvf_n701_bdx_prices"
CRITIC_CODE = "RVF"
SCALE = "/100"
REVIEWER_TYPE = "critic"
COUNTRY_CODE = "FR"


def _r(producer, cuvee, appellation, score, price_2024, price_2023, color="rouge"):
    """Build a wine entry with 2025 score + 2024/2023 reference prices."""
    return {
        "producer": producer,
        "cuvee": cuvee,
        "appellation": appellation,
        "score": score,
        "price_2024": price_2024,
        "price_2023": price_2023,
        "color": color,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DATASET  (read from RVF N°701 pages 124-143)
# score = midpoint of range (e.g. "96-98" → 97.0)
# price = None means N.C. (non communiqué) or not shown
# ─────────────────────────────────────────────────────────────────────────────

WINES = [

    # =========================================================================
    # POMEROL  pp.124-127
    # =========================================================================

    _r("Château Pétrus",              "", "Pomerol",   98.0, 2160.0, 3150.0),
    _r("Château La Conseillante",     "", "Pomerol",   96.5,  168.0,  210.0),
    _r("Château Le Pin",              "", "Pomerol",   96.5, 2780.0, 2950.0),
    _r("Château Trotanoy",            "", "Pomerol",   96.0,  171.0,  230.0),
    _r("Château L'Église-Clinet",     "", "Pomerol",   96.0,   49.0,   57.1),
    _r("Château Hosanna",             "", "Pomerol",   95.0,  166.0,  138.0),
    _r("Château La Fleur-Pétrus",     "", "Pomerol",   95.0,  155.0,  187.0),
    _r("Château La Violette",         "", "Pomerol",   95.0,  134.0,  216.0),
    _r("Château Clinet",              "", "Pomerol",   94.5,  117.0,  117.6),
    # Angélica — Laurent Lythier micro-cuvée à Pomerol
    _r("Angélica",                    "", "Pomerol",   94.0,   55.8,   67.2),
    _r("Château Petit-Village",       "", "Pomerol",   94.0,   63.0,   81.0),
    _r("Château Nénin",               "", "Pomerol",   94.0,   None,   None),
    _r("Château Domaine de l'Église", "", "Pomerol",   94.0,   None,   None),
    _r("Château Le Gay",              "", "Pomerol",   93.5,   37.2,   None),
    _r("Château Gazin",               "", "Pomerol",   93.5,   94.0,   97.4),
    _r("Clos du Clocher",             "", "Pomerol",   92.5,   None,   None),
    # p.126 — more Pomerol
    _r("Château Bourgneuf",           "", "Pomerol",   93.0,   38.0,   55.65),
    _r("Château Le Bon Pasteur",      "", "Pomerol",   92.5,   50.4,   50.4),
    _r("Château Lécuyer",             "", "Pomerol",   92.5,   None,   None),
    _r("Château Feyrit-Clinet",       "", "Pomerol",   91.0,   49.0,   57.1),
    _r("Château Porte Chic",          "", "Pomerol",   90.5,   None,   None),
    _r("Château Fayat",               "", "Pomerol",   90.5,   None,   30.0),
    _r("Château Le Caillou",          "", "Pomerol",   90.5,   None,   None),
    _r("Château Gombaude-Guillot",    "", "Pomerol",   92.5,   None,   None),
    _r("Clos René",                   "", "Pomerol",   92.5,   None,   28.0),
    _r("Château Latour à Pomerol",    "", "Pomerol",   92.5,   None,   None),
    _r("Château Bonalgue",            "", "Pomerol",   92.0,   None,   None),
    _r("Château Cantelauze",          "", "Pomerol",   91.5,   None,   None),
    _r("Château La Fleur du Roy",     "", "Pomerol",   91.5,   None,   None),
    _r("Château La Pointe",           "", "Pomerol",   92.0,   None,   None),
    # p.127 — Pomerol right column + Lalande-de-Pomerol
    _r("Château Mazeyres",            "", "Pomerol",   92.0,   58.8,   45.6),
    _r("Château De Valois",           "", "Pomerol",   92.0,   70.0,   77.3),
    _r("Château Rouget",              "", "Pomerol",   93.5,  117.0,  117.6),
    _r("Château Saint-Pierre",        "", "Pomerol",   93.5,   41.45,  46.7),
    _r("Château Beauregard",          "", "Pomerol",   90.5,   None,   None),
    # Lalande-de-Pomerol
    _r("Château Pavillon Beauregard", "", "Lalande-de-Pomerol", 90.5, None, None),

    # =========================================================================
    # MÉDOC / MOULIS / MARGAUX  pp.128-131
    # =========================================================================

    # p.128 — Vin de France + Haut-Médoc
    _r("Château Lafleur",             "", "Vin de France",   98.0, 1000.0,  840.0),
    _r("Château Lafleur",         "Pensées de Lafleur", "Vin de France", 93.5,  None, None),
    _r("Château Lafleur Gazin",       "", "Vin de France",   92.5,   22.7,   24.0),

    # Haut-Médoc p.129
    _r("Château Cantemerle",          "", "Haut-Médoc",      93.0,   None,   None),
    _r("Château Belgrave",            "", "Haut-Médoc",      92.5,   None,   24.8),
    _r("Château La Lagune",           "", "Haut-Médoc",      92.5,   None,   None),
    _r("Château Sociando-Mallet",     "", "Haut-Médoc",      92.0,   None,   None),
    _r("Château de Camensac",         "", "Haut-Médoc",      88.5,   None,   None),

    # Listrac-Médoc
    _r("Château Fourcas Hosten",      "", "Listrac-Médoc",   92.0,   None,   None),
    _r("Château Cos d'Estournel",     "Les Pagodes de Cos", "Saint-Estèphe", 92.5, None, None),
    _r("Château Pichon Longueville Comtesse", "", "Pauillac", 91.5, 24.5, None),
    _r("Château Fourcas Dupré",       "", "Listrac-Médoc",   91.5,   None,   None),
    _r("Château Siran",               "", "Margaux",         91.5,   None,   None),
    _r("Château d'Issan",             "", "Margaux",         91.5,   None,   None),
    _r("Clos Manou",                  "", "Médoc",           91.5,   None,   None),

    # Margaux p.129 right + p.130
    _r("Château Margaux",             "", "Margaux",         99.0,   None,   None),
    _r("Château Palmer",              "", "Margaux",         96.0,   386.0,  504.0),
    _r("Château Brane-Cantenac",      "", "Margaux",         95.0,   50.4,   62.4),
    _r("Château Rauzan-Ségla",        "", "Margaux",         95.0,   67.2,   84.0),
    _r("Château Lascombes",           "", "Margaux",         95.0,   40.3,   45.6),
    _r("Château Giscours",            "", "Margaux",         94.0,   42.7,   54.0),
    _r("Château Kirwan",              "", "Margaux",         94.5,   33.6,   37.7),
    _r("Château Siran",               "", "Margaux",         94.5,   None,   None),

    # p.130-131
    _r("Château Cantenac Brown",      "", "Margaux",         96.0,   None,   40.6),
    _r("Château d'Issan",             "", "Margaux",         94.0,   30.0,   37.2),
    _r("Château Ferrière",            "", "Margaux",         94.5,   32.0,   None),
    _r("Château Durfort-Vivens",      "", "Margaux",         94.5,   45.25,  53.6),
    _r("Château Siran",               "", "Margaux",         94.5,   None,   None),
    _r("Château Malescot Saint-Exupéry", "", "Margaux",      92.5,   25.9,   28.6),
    _r("Château Prieuré-Lichine",     "", "Margaux",         92.0,   None,   None),
    _r("Château Marquis de Terme",    "", "Margaux",         93.5,   37.2,   38.4),
    _r("Château du Tertre",           "", "Margaux",         93.0,   None,   None),
    _r("Château Dauzac",              "", "Margaux",         91.5,   20.6,   None),
    _r("Château Boyd-Cantenac",       "", "Margaux",         90.5,   None,   None),
    _r("Château Rauzan-Gassies",      "", "Margaux",         91.0,   None,   None),
    _r("Château La Tour de Mons",     "", "Margaux",         91.5,   None,   None),
    _r("Château Poujeaux",            "", "Moulis-en-Médoc",  92.5,   None,   None),
    _r("Château Anthonic",            "", "Moulis-en-Médoc",  92.5,   None,   None),
    _r("Château Branas Grand Poujeaux", "", "Moulis-en-Médoc", 91.5,  None,   None),
    _r("Château Grand Poujeaux",      "", "Moulis-en-Médoc",  91.5,   None,   None),
    _r("Château Mauvesin Barton",     "", "Moulis-en-Médoc",  90.5,   20.16,  23.5),
    _r("Château Tour du Haut-Moulin", "", "Haut-Médoc",      92.5,   None,   None),
    _r("Château Potensac",            "", "Médoc",            92.5,   20.3,   21.0),
    _r("Château Haut Condissas",      "", "Médoc",            90.5,   None,   None),
    _r("Château La Tour de By",       "", "Médoc",            90.0,   20.4,   19.8),
    _r("Château Lestage-Darquier Grand Poujeaux", "", "Moulis-en-Médoc", 91.5, None, None),
    _r("Château Enclos Tourmaline",   "", "Médoc",            91.5,   None,   None),

    # =========================================================================
    # PAUILLAC  pp.132-135
    # =========================================================================

    # p.132
    _r("Château Lafite Rothschild",   "", "Pauillac",   98.0,  402.0,  574.0),
    _r("Château Mouton Rothschild",   "", "Pauillac",   98.0,  268.0,  466.0),
    _r("Château Pichon Longueville Comtesse", "", "Pauillac", 96.5, 124.0, 168.0),
    _r("Château Grand-Puy-Lacoste",   "", "Pauillac",   95.5,   27.6,   32.7),
    _r("Château Grand-Puy Ducasse",   "", "Pauillac",   93.5,   None,   None),
    _r("Château Lynch-Moussas",       "", "Pauillac",   93.5,   None,   None),

    # p.133 — Pauillac + Saint-Estèphe + Saint-Julien start
    _r("Château Pédescaux",           "", "Pauillac",   93.5,  118.8,  159.6),
    _r("Château Meyney",              "", "Pauillac",   94.0,   33.0,   37.0),
    _r("Château Phelan Ségur",        "", "Pauillac",   97.0,   40.3,   43.6),
    _r("Château Montrose",            "", "Pauillac",   97.0,  117.6,  168.0),
    _r("Château Calon Ségur",         "", "Saint-Estèphe", 96.0,  85.7,  109.2),
    _r("Château Cos d'Estournel",     "", "Saint-Estèphe", 96.0, None, None),
    _r("Château Haut-Bages Libéral",  "", "Pauillac",   93.5,   45.0,   50.4),
    _r("Château Lynch-Bages",         "", "Pauillac",   95.5,   68.5,   102.0),
    _r("Château Pichon Baron",        "", "Pauillac",   96.5,  114.25,  146.0),
    _r("Château Batailley",           "", "Pauillac",   95.5,   None,   None),

    # p.134 — Pauillac cont. + Saint-Estèphe + Saint-Julien starts
    _r("Château Haut-Marbuzet",       "", "Saint-Estèphe", 95.0, 34.55, 36.0),
    _r("Château Le Crock",            "", "Saint-Estèphe", 94.5, None,  None),
    _r("Château de Pez",              "", "Saint-Estèphe", 94.5, None,  23.0),
    _r("Château Domeyne",             "", "Saint-Estèphe", 93.5, None,  None),
    _r("Château Ormes de Pez",        "", "Saint-Estèphe", 93.5, 22.7,  23.5),
    _r("Château Haut-Marbuzet",       "", "Saint-Estèphe", 94.5, None,  None),
    _r("Château Capbern",             "", "Saint-Estèphe", 93.0, None,  None),
    _r("Château Cos Labory",          "", "Saint-Estèphe", 95.0, 118.8, 159.6),
    _r("Château Lafon-Rochet",        "", "Saint-Estèphe", 93.0, 24.0,  23.8),
    _r("Château Labegorce",           "", "Margaux",        93.5, 25.9,  28.6),

    # p.135 — Saint-Julien start
    _r("Château Léoville-Las Cases",  "", "Saint-Julien",  98.5,  135.5,  193.6),
    _r("Château Ducru-Beaucaillou",   "", "Saint-Julien",  97.0,  None,   None),

    # =========================================================================
    # SAINT-JULIEN  pp.135-136
    # =========================================================================

    # p.136 — Saint-Julien
    _r("Château Léoville Barton",     "", "Saint-Julien",   96.5,   68.4,   80.4),
    _r("Château Léoville Poyferré",   "", "Saint-Julien",   96.0,   59.0,   89.0),
    _r("Château Beychevelle",         "", "Saint-Julien",   96.0,   81.6,   84.0),
    _r("Château Gruaud Larose",       "", "Saint-Julien",   95.5,   None,   None),
    _r("Château Branaire-Ducru",      "", "Saint-Julien",   94.0,   37.2,   45.3),
    _r("Château Langoa Barton",       "", "Saint-Julien",   93.5,   None,   42.6),
    _r("Château Gloria",              "", "Saint-Julien",   93.5,   None,   None),
    _r("Château Moulin Riche",        "", "Saint-Julien",   92.0,   25.9,   30.0),
    _r("Château Saint-Pierre",        "", "Saint-Julien",   95.5,   44.05,  45.3),
    _r("Château Talbot",              "", "Saint-Julien",   95.5,   45.3,   None),
    _r("Château Clos du Marquis",     "", "Saint-Julien",   94.0,   44.05,  52.7),
    _r("Les Carmes Haut-Brion",       "", "Saint-Julien",   97.0,   26.05,  30.0),

    # =========================================================================
    # PESSAC-LÉOGNAN (ROUGES)  pp.137-141
    # =========================================================================

    # p.137
    _r("Château Haut-Brion",          "", "Pessac-Léognan",  98.5,  336.0,  438.0),
    _r("La Mission Haut-Brion",       "", "Pessac-Léognan",  98.0,  None,   222.0),
    _r("Château Haut-Bailly",         "", "Pessac-Léognan",  96.5,   84.5,  None),
    _r("Domaine de Chevalier",        "", "Pessac-Léognan",  94.0,   44.05,  64.8),
    _r("Château Smith Haut Lafitte",  "", "Pessac-Léognan",  94.0,   None,  None),
    _r("Château Carbonnieux",         "", "Pessac-Léognan",  94.5,   None,  None),
    _r("Château Pape Clément",        "", "Pessac-Léognan",  None,  None,   None),  # no score visible
    _r("Château Les Carmes Haut-Brion", "", "Pessac-Léognan", 97.0,  26.05,  30.0),

    # p.138-139 — Pessac-Léognan rouges cont.
    _r("Château Haut-Brion",          "", "Pessac-Léognan",  96.5,   None,   None),  # Lafleur 2025 notes
    _r("Château Olivier",             "", "Pessac-Léognan",  92.5,   None,   None),
    _r("Château Latour-Martillac",    "", "Pessac-Léognan",  95.5,   None,   None),
    _r("Château Malartic-Lagravière", "", "Pessac-Léognan",  93.5,   31.0,   33.6),
    _r("Château Branaire-Ducru",      "", "Saint-Julien",    95.0,   44.05,  52.7),   # already above but here again
    _r("Château Carbonnieux",         "", "Pessac-Léognan",  93.5,   36.1,   39.5),
    _r("Château Bouscaut",            "", "Pessac-Léognan",  92.5,   25.0,   33.6),
    _r("Château Le Thil",             "", "Pessac-Léognan",  92.5,   None,   None),
    _r("Château Bouscaut",            "", "Pessac-Léognan",  92.5,   25.2,   30.6),

    # p.139 right column
    _r("Château Bouscaut",            "", "Pessac-Léognan",  92.0,   None,   None),
    _r("Château Olivier",             "", "Pessac-Léognan",  92.0,   27.7,   27.0),
    _r("Château Larrivet Haut-Brion", "", "Pessac-Léognan",  93.5,   30.25,  34.2),
    _r("Château La Garde",            "", "Pessac-Léognan",  91.5,   None,   None),
    _r("Château Couhins-Lurton",      "", "Pessac-Léognan",  91.5,   28.08,  28.0),
    _r("Château Couhins",             "", "Pessac-Léognan",  90.5,   None,   25.0),
    _r("Château Fieuzal",             "", "Pessac-Léognan",  91.5,   10.0,   19.0),

    # p.140-141 — Pessac-Léognan rouges cont.
    _r("Château Haut-Brion",          "", "Pessac-Léognan",  96.5,   None,   None),  # dup guard via hash
    _r("Château Smith Haut Lafitte",  "", "Pessac-Léognan",  95.5,  151.0, 151.2),
    _r("Domaine de Chevalier",        "", "Pessac-Léognan",  94.0,   99.0,  110.0),
    _r("Château Latour-Martillac",    "", "Pessac-Léognan",  93.5,   None,   None),
    _r("Château Carbonnieux",         "", "Pessac-Léognan",  93.5,   36.1,   39.5),
    _r("Château Malartic-Lagravière", "", "Pessac-Léognan",  93.5,   54.0,   53.0),
    _r("Château Larrivet Haut-Brion", "", "Pessac-Léognan",  92.5,   31.0,   32.7),
    _r("Château Bouscaut",            "", "Pessac-Léognan",  92.5,   31.0,   33.6),
    _r("Château Fieuzal",             "", "Pessac-Léognan",  91.5,   42.0,   46.8),
    _r("Château Brown",               "", "Pessac-Léognan",  91.5,   27.0,   26.9),
    _r("Château Couhins-Lurton",      "", "Pessac-Léognan",  91.5,   26.05,  None),
    _r("Château La Garde",            "", "Pessac-Léognan",  91.5,   59.0,   58.8),
    _r("Château La Louvière",         "", "Pessac-Léognan",  90.5,   None,   None),

    # =========================================================================
    # PESSAC-LÉOGNAN BLANCS  pp.139-141
    # =========================================================================

    _r("La Mission Haut-Brion",       "", "Pessac-Léognan",  97.5,  606.0,  606.0, "blanc"),
    _r("Château Haut-Brion",          "", "Pessac-Léognan",  96.5,   84.5,  None,  "blanc"),
    _r("Château Haut-Bailly",         "", "Pessac-Léognan",  96.5,   None,  None,  "blanc"),
    _r("Château Smith Haut Lafitte",  "", "Pessac-Léognan",  96.5,   None,  None,  "blanc"),
    _r("Domaine de Chevalier",        "", "Pessac-Léognan",  94.0,   27.7,  34.2,  "blanc"),
    _r("Château Carbonnieux",         "", "Pessac-Léognan",  93.5,   36.1,  39.5,  "blanc"),
    _r("Château Malartic-Lagravière", "", "Pessac-Léognan",  93.5,   54.0,  53.0,  "blanc"),
    _r("Château Larrivet Haut-Brion", "", "Pessac-Léognan",  93.5,   30.25, 34.2,  "blanc"),
    _r("Château Bouscaut",            "", "Pessac-Léognan",  92.5,   25.2,  30.6,  "blanc"),
    _r("Château Olivier",             "", "Pessac-Léognan",  92.0,   27.7,  27.0,  "blanc"),
    _r("Château La Louvière",         "", "Pessac-Léognan",  90.5,   30.0,  31.8,  "blanc"),
    _r("Château Brown",               "", "Pessac-Léognan",  90.5,   23.0,  None,  "blanc"),
    _r("Château Couhins",             "", "Pessac-Léognan",  90.5,   None,  28.0,  "blanc"),
    _r("Domaine de la Solitude",      "", "Pessac-Léognan",  91.5,   19.0,  19.0,  "blanc"),
    _r("Château La Garde",            "", "Pessac-Léognan",  90.5,   None,  None,  "blanc"),

    # =========================================================================
    # SAUTERNES  pp.142-143
    # =========================================================================

    _r("Château Lafaurie-Peyraguey",  "", "Sauternes",   97.5,   None,   None, "blanc"),
    _r("Château Clos Haut-Peyraguey", "", "Sauternes",   95.5,   None,   None, "blanc"),
    _r("Château Raymond-Lafon",       "", "Sauternes",   95.5,   None,  48.7,  "blanc"),
    _r("Château Suduiraut",           "", "Sauternes",   95.5,   55.45, 60.0,  "blanc"),
    _r("Château Caillou",             "", "Sauternes",   95.0,   None,  59.5,  "blanc"),
    _r("Château Sigalas-Rabaud",      "", "Sauternes",   93.5,   None,   None, "blanc"),
    _r("Château Tuyttens",            "", "Sauternes",   93.5,   None,   None, "blanc"),
    _r("Domaine de l'Alliance",       "", "Sauternes",   92.5,   None,   None, "blanc"),
    _r("Château Doisy Daëne",         "", "Sauternes",   93.0,   None,  41.0,  "blanc"),
    _r("Château de Fargues",          "", "Sauternes",   92.5,   None,   None, "blanc"),
    _r("Château Rieussec",            "", "Sauternes",   None,   None,   None, "blanc"),  # not shown
    _r("Château Bastor-Lamontagne",   "", "Sauternes",   92.0,   None,  30.0,  "blanc"),
    _r("Château Broustet",            "", "Sauternes",   92.0,   None,   None, "blanc"),
    _r("Château Liot",                "", "Sauternes",   92.0,   None,   None, "blanc"),
    _r("Château Doisy-Védrines",      "", "Sauternes",   92.0,   None,   None, "blanc"),
    _r("Château Guiraud",             "", "Sauternes",   92.0,   None,   None, "blanc"),
    _r("Château La Clotte-Cazalis",   "", "Sauternes",   92.0,   None,  None,  "blanc"),
    _r("Château Haut-Bergeron",       "", "Sauternes",   91.5,   None,   None, "blanc"),
    _r("Château Rabaud-Promis",       "", "Sauternes",   93.5,   None,   None, "blanc"),
    _r("Château d'Arche",             "", "Sauternes",   91.5,   None,   None, "blanc"),
    _r("Château Siau",                "", "Sauternes",   90.5,   None,   None, "blanc"),
    _r("Château Coutet",              "", "Sauternes",   91.5,   None,   None, "blanc"),
    _r("Château La Tour Blanche",     "", "Sauternes",   91.5,   23.0,  52.0,  "blanc"),
    _r("Château de Myrat",            "", "Sauternes",   91.5,   None,   None, "blanc"),
    _r("Château Roumieu",             "", "Sauternes",   91.5,   None,   None, "blanc"),
    _r("Château Closiot",             "", "Barsac",      95.0,   None,  25.0,  "blanc"),
    _r("Château Climens",             "", "Barsac",      None,   None,   None, "blanc"),  # not in this batch
    _r("Château Raymond-Lafon",       "", "Sauternes",   95.5,   None,  48.7,  "blanc"),  # dup handled by hash
    _r("Château Clos Haut-Peyraguey", "", "Sauternes",   95.5,   None,   None, "blanc"),  # dup handled
    _r("Château Lafaurie-Peyraguey",  "", "Sauternes",   97.5,   82.8,  80.7,  "blanc"),
]

# ─────────────────────────────────────────────────────────────────────────────
# DB HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def lookup_appellation(cur, raw_name: str, fallback_key: int) -> int:
    n = norm_text(raw_name)
    candidates = [n]
    for prefix in ("igp ", "aop ", "aoc "):
        if n.startswith(prefix):
            candidates.append(n[len(prefix):])
    OVERRIDES = {
        "pessac leognan": "pessac leognan",
        "pomerol": "pomerol",
        "lalande de pomerol": "lalande de pomerol",
        "pauillac": "pauillac",
        "saint julien": "saint julien",
        "margaux": "margaux",
        "saint estephe": "saint estephe",
        "sauternes": "sauternes",
        "barsac": "barsac",
        "haut medoc": "haut medoc",
        "medoc": "medoc",
        "moulis en medoc": "moulis en medoc",
        "listrac medoc": "listrac medoc",
        "vin de france": "vin de france",
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
            return row[0]
    log.warning("Appellation not found, fallback: %r", raw_name)
    return fallback_key


def get_or_create_producer(cur, producer_display: str, now: int) -> int:
    p_norm = normalize_producer(producer_display)
    cur.execute("SELECT producer_key FROM dim_producer WHERE producer_norm=? LIMIT 1", (p_norm,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        """INSERT INTO dim_producer
            (producer_name, producer_norm, country_code, coverage_tier,
             allowed_appellations, aliases, status, first_seen_at, last_seen_at)
           VALUES (?, ?, ?, 'notable', '[]', '[]', 'active', ?, ?)""",
        (producer_display, p_norm, COUNTRY_CODE, now, now),
    )
    new_key = cur.lastrowid
    log.info("Created producer: %r (key=%d)", producer_display, new_key)
    return new_key


def get_or_create_wine(cur, producer_key, appellation_key, producer_display,
                       cuvee_display, color, vintage, now) -> str:
    p_norm = normalize_producer(producer_display)
    c_norm = normalize_cuvee(cuvee_display)
    wine_key = compute_wine_key(p_norm, c_norm, vintage)
    cur.execute("SELECT wine_key FROM dim_wine WHERE wine_key=?", (wine_key,))
    if cur.fetchone():
        return wine_key
    canonical = f"{producer_display} {cuvee_display}".strip()
    if vintage:
        canonical = f"{canonical} {vintage}"
    is_nv = 1 if vintage is None else 0
    cur.execute(
        """INSERT OR IGNORE INTO dim_wine
            (wine_key, producer_key, appellation_key, cuvee_name, cuvee_norm,
             color, vintage, is_non_vintage, bottle_ml, canonical_name,
             first_seen_at, last_seen_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 750, ?, ?, ?)""",
        (wine_key, producer_key, appellation_key,
         cuvee_display or "", c_norm, color, vintage, is_nv,
         canonical, now, now),
    )
    return wine_key


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    if not DB_PATH.exists():
        log.error("DB not found: %s", DB_PATH)
        sys.exit(1)

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    now = int(time())

    cur.execute("SELECT source_key FROM dim_source WHERE source_code='rvf' LIMIT 1")
    row = cur.fetchone()
    if not row:
        log.error("No dim_source row with source_code='rvf'")
        sys.exit(1)
    source_key = row[0]
    log.info("RVF source_key=%d", source_key)

    cur.execute("SELECT appellation_key FROM dim_appellation WHERE appellation_norm='france' LIMIT 1")
    row = cur.fetchone()
    fallback_key = row[0] if row else 1

    # Before counts
    cur.execute("SELECT COUNT(*) FROM staging_rating_candidates WHERE batch_id=?", (BATCH_ID,))
    before_ratings = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM staging_price_candidates WHERE batch_id=?", (BATCH_ID,))
    before_prices_all = cur.fetchone()[0]

    new_ratings = 0
    new_prices_2024 = 0
    new_prices_2023 = 0
    skipped = 0

    # Filter out entries with no data at all
    valid_wines = [w for w in WINES if w["score"] is not None or w["price_2024"] is not None or w["price_2023"] is not None]
    log.info("Processing %d wine entries (%d skipped empty)", len(valid_wines), len(WINES) - len(valid_wines))

    for w in valid_wines:
        producer = w["producer"]
        cuvee = w["cuvee"] or ""
        appellation = w["appellation"]
        score = w["score"]
        price_2024 = w["price_2024"]
        price_2023 = w["price_2023"]
        color = w["color"]

        appellation_key = lookup_appellation(cur, appellation, fallback_key)
        producer_key = get_or_create_producer(cur, producer, now)

        # 2025 score → staging_rating_candidates
        if score is not None:
            wine_key = get_or_create_wine(
                cur, producer_key, appellation_key, producer, cuvee, color, 2025, now
            )
            ch = sha1(f"rvf_n701_bdx_{wine_key}_2025_{score}")
            cur.execute(
                """INSERT OR IGNORE INTO staging_rating_candidates
                    (wine_key, source_key, critic_code, reviewer_type, score,
                     scale, score_normalized_100, recorded_at, batch_id,
                     needs_review, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (wine_key, source_key, CRITIC_CODE, REVIEWER_TYPE, score,
                 SCALE, score, now, BATCH_ID, ch),
            )
            if cur.rowcount > 0:
                new_ratings += 1
            else:
                skipped += 1

        # 2024 price → staging_price_candidates
        if price_2024 is not None:
            wine_key_p = get_or_create_wine(
                cur, producer_key, appellation_key, producer, cuvee, color, 2024, now
            )
            ch_p = sha1(f"rvf_n701_bdx_price_{wine_key_p}_2024_{price_2024}")
            cur.execute(
                """INSERT OR IGNORE INTO staging_price_candidates
                    (wine_key, source_key, currency_code, amount_local, amount_eur,
                     recorded_at, batch_id, needs_review, content_hash)
                   VALUES (?, ?, 'EUR', ?, ?, ?, ?, 1, ?)""",
                (wine_key_p, source_key, price_2024, price_2024, now, BATCH_ID, ch_p),
            )
            if cur.rowcount > 0:
                new_prices_2024 += 1
            else:
                skipped += 1

        # 2023 price → staging_price_candidates
        if price_2023 is not None:
            wine_key_p = get_or_create_wine(
                cur, producer_key, appellation_key, producer, cuvee, color, 2023, now
            )
            ch_p = sha1(f"rvf_n701_bdx_price_{wine_key_p}_2023_{price_2023}")
            cur.execute(
                """INSERT OR IGNORE INTO staging_price_candidates
                    (wine_key, source_key, currency_code, amount_local, amount_eur,
                     recorded_at, batch_id, needs_review, content_hash)
                   VALUES (?, ?, 'EUR', ?, ?, ?, ?, 1, ?)""",
                (wine_key_p, source_key, price_2023, price_2023, now, BATCH_ID, ch_p),
            )
            if cur.rowcount > 0:
                new_prices_2023 += 1
            else:
                skipped += 1

    con.commit()

    # After counts
    cur.execute("SELECT COUNT(*) FROM staging_rating_candidates WHERE batch_id=?", (BATCH_ID,))
    after_ratings = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM staging_price_candidates WHERE batch_id=?", (BATCH_ID,))
    after_prices_all = cur.fetchone()[0]

    con.close()

    print()
    print("=" * 65)
    print(f"  RVF N°701 Bordeaux Prices — batch_id='{BATCH_ID}'")
    print("  Pages 124-143 (Pomerol, Médoc, Pauillac, Saint-Julien,")
    print("  Saint-Estèphe, Margaux, Pessac-Léognan, Sauternes)")
    print("=" * 65)
    print(f"  Wine entries processed    : {len(valid_wines)}")
    print(f"  New 2025 scores inserted  : {new_ratings}  (staging_rating_candidates: {before_ratings} -> {after_ratings})")
    print(f"  New 2024 prices inserted  : {new_prices_2024}")
    print(f"  New 2023 prices inserted  : {new_prices_2023}  (staging_price_candidates: {before_prices_all} -> {after_prices_all})")
    print(f"  Skipped (already exist)   : {skipped}")
    print("=" * 65)


if __name__ == "__main__":
    main()
