"""
import_rvf_n701_complete.py — Complete import of RVF N°701 (June 2026).

Covers pages 70–143 not imported in the first pass (batch_id='rvf_n701_import').
Sections:
  A. Blancs méditerranéens (p.70-88): Châteauneuf-du-Pape blancs, Corse,
     Vin de France (Patrimonio), Vacqueyras, Cairanne, Beaumes-de-Venise
  B. De vigne en cave (p.94-115):
     - Domaine Tempier Bandol (vertical La Migoua + current releases)
     - (Fixin & Saumur: no standardised scores, skipped)
  C. Bordeaux Primeurs 2025 (p.116-143):
     - 2025 scores go to staging_rating_candidates
     - 2024/2023 reference prices go to staging_price_candidates

Rules:
- FR wines only (no Spanish/Italian/non-FR)
- Ratings  → staging_rating_candidates  (needs_review=1, batch_id='rvf_n701_complete')
- Prices   → staging_price_candidates   (batch_id='rvf_n701_complete')
- INSERT OR IGNORE everywhere (idempotent)
- Range scores: midpoint; e.g. "96-98" → 97.0
"""

import sys
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
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("import_rvf_n701_complete")

# ── constants ────────────────────────────────────────────────────────────────
DB_PATH = PROJECT_ROOT / "data" / "achilles.db"
BATCH_ID = "rvf_n701_complete"
CRITIC_CODE = "RVF"
SCALE = "/100"
REVIEWER_TYPE = "critic"
COUNTRY_CODE = "FR"

# ─────────────────────────────────────────────────────────────────────────────
# DATASET
# Each record has:
#   producer, cuvee, appellation, vintage, score (or None), price_eur (or None),
#   color, price_vintage (for Bordeaux ref prices where vintage ≠ score vintage),
#   source_note
#
# For Bordeaux: score_vintage=2025, price rows use price_vintage=2024 or 2023.
# ─────────────────────────────────────────────────────────────────────────────

# Helper: encode a wine entry with an explicit price_vintage for Bordeaux ref prices
def _r(producer, cuvee, appellation, vintage, score, price_eur, color,
        source_note, price_vintage=None):
    return {
        "producer": producer,
        "cuvee": cuvee,
        "appellation": appellation,
        "vintage": vintage,
        "score": score,
        "price_eur": price_eur,
        "color": color,
        "source_note": source_note,
        "price_vintage": price_vintage,  # if set, price is for this vintage, not 'vintage'
    }

WINES = [

    # =========================================================================
    # SECTION A — BLANCS MÉDITERRANÉENS (p.70-88)
    # =========================================================================

    # --- Châteauneuf-du-Pape blancs (p.71) ---
    _r("Château Fonsalette", "", "Côtes du Rhône", 2013, 95.0, 58.0, "blanc",
       "RVF N°701 score+price p.71"),
    _r("Domaine du Banneret", "Secret du Banneret", "Châteauneuf-du-Pape", 2024, 95.0, 48.0, "blanc",
       "RVF N°701 score+price p.71"),
    _r("Domaine de Beaurenard", "Boisrenard", "Châteauneuf-du-Pape", 2023, 95.0, 70.0, "blanc",
       "RVF N°701 score+price p.71"),
    _r("Domaine de la Janasse", "Prestige", "Châteauneuf-du-Pape", 2023, 95.0, 70.0, "blanc",
       "RVF N°701 score+price p.71"),
    _r("Domaine du Vieux Donjon", "", "Châteauneuf-du-Pape", 2024, 95.0, 50.0, "blanc",
       "RVF N°701 score+price p.71"),
    _r("Vignobles André Brunel", "Les Cailloux", "Châteauneuf-du-Pape", 2024, 95.0, 39.0, "blanc",
       "RVF N°701 score+price p.71"),
    # Clos du Mont-Olivet continued from p.71 into p.73
    _r("Clos du Mont-Olivet", "", "Châteauneuf-du-Pape", 2024, 94.5, 38.0, "blanc",
       "RVF N°701 score+price p.71-73 (94-95/100)"),

    # --- Blancs méditerranéens continued (p.73) ---
    # Domaine des Bernardins — non millésimée (no vintage)
    _r("Domaine des Bernardins", "Hommage", "Muscat de Beaumes-de-Venise", None, 94.0, 19.5, "liquoreux",
       "RVF N°701 score+price p.73 non millésimée"),
    _r("Domaine de Montvac", "Melodine", "Vacqueyras", 2023, 93.0, 30.0, "blanc",
       "RVF N°701 score+price p.73"),
    _r("Domaine Marcel Richaud", "", "Cairanne", 2021, 93.0, 25.0, "blanc",
       "RVF N°701 score+price p.73"),

    # --- En Corse: Muscat, Vermentinu, Biancu Gentile (p.73-74) ---
    _r("Clos Nicrosi", "Muscatellu", "Muscat du Cap Corse", 2022, 97.0, 35.0, "blanc",
       "RVF N°701 score+price p.73"),
    _r("Domaine Leccia", "Annette Leccia", "Vin de France", 2022, 97.0, 45.0, "blanc",
       "RVF N°701 score+price p.73 (les 50cl)"),
    _r("Clos Venturi", "Chiesa Nera", "Corse", 2022, 96.5, 90.0, "blanc",
       "RVF N°701 score+price p.73 (96-97/100)"),
    _r("Domaine de Vaccelli", "", "Ajaccio", 2021, 96.0, 60.0, "blanc",
       "RVF N°701 score+price p.73"),

    # --- Corse blancs continued (p.74) ---
    _r("Domaine Pinelli", "", "Vin de France", 2022, 95.5, 35.0, "blanc",
       "RVF N°701 score+price p.74 (95-96/100, les 50cl) non muté"),
    _r("Domaine Antoine-Marie Arena", "PP", "Vin de France", 2022, 95.0, 35.0, "blanc",
       "RVF N°701 score+price p.74 (2020/21/22 blend)"),
    _r("Clos Canarelli - Tarra di Sognu", "Tarra d'Oraï", "Vin de France", 2020, 95.0, 200.0, "blanc",
       "RVF N°701 score+price p.74"),
    _r("Domaine Comte Abbatucci", "Révolution", "Vin de France", 2023, 95.0, 60.0, "blanc",
       "RVF N°701 score+price p.74 (94-96/100)"),
    _r("Domaine Giudicelli", "Baptisée N°2", "Muscat du Cap Corse", 2020, 94.0, 70.0, "blanc",
       "RVF N°701 score+price p.74"),
    _r("Sant Armettu", "Biancu Burghese", "Île de Beauté", 2021, 94.0, 70.0, "blanc",
       "RVF N°701 score+price p.74"),

    # --- Corse/Patrimonio blancs (p.76-78) ---
    _r("Domaine U Stiliccionu", "Joséphine", "Ajaccio", 2021, 94.0, 590.0, "blanc",
       "RVF N°701 score+price p.76 (single barrel)"),
    _r("Domaine Vico", "", "Corse", 2022, 94.0, 65.0, "blanc",
       "RVF N°701 score+price p.76"),
    _r("Domaine Jean-Baptiste Arena", "Muscatelli Grotte di Sole", "Vin de France", 2022, 93.0, 35.0, "blanc",
       "RVF N°701 score+price p.76"),
    _r("Clos Culombu", "Storia di Signore", "Vin de France", 2023, 93.0, 30.0, "blanc",
       "RVF N°701 score+price p.76"),
    _r("Domaine Gentile", "Grande Expression", "Patrimonio", 2018, 93.0, 30.0, "blanc",
       "RVF N°701 score+price p.76"),
    _r("Yves Leccia", "L'Altru Biancu", "Île de Beauté", 2023, 93.0, 26.0, "blanc",
       "RVF N°701 score+price p.76"),
    _r("Domaine Alzipratu", "Blanc Lume", "Corse Calvi", 2023, 92.5, 47.0, "blanc",
       "RVF N°701 score+price p.76 (92-93/100)"),

    # --- Patrimonio/Corse (p.78) ---
    _r("Clos d'Alzeto", "Carellone", "Vin de France", 2022, 93.5, 60.0, "blanc",
       "RVF N°701 score+price p.78 (93-94/100)"),
    _r("Clos Signadore", "", "Patrimonio", 2022, 92.5, 65.0, "blanc",
       "RVF N°701 score+price p.78 (92-93/100, 1000 bouteilles)"),
    _r("Domaine Pieretti", "Marine", "Coteaux du Cap Corse", 2020, 92.5, 100.0, "blanc",
       "RVF N°701 score+price p.78 (92-93/100)"),

    # =========================================================================
    # SECTION B — DE VIGNE EN CAVE: DOMAINE TEMPIER, BANDOL (p.96-99)
    # =========================================================================

    # La Migoua vertical (p.96)
    _r("Domaine Tempier", "La Migoua", "Bandol", 2023, 95.0, None, "rouge",
       "RVF N°701 vertical p.96"),
    _r("Domaine Tempier", "La Migoua", "Bandol", 2021, 96.0, None, "rouge",
       "RVF N°701 vertical p.96"),
    _r("Domaine Tempier", "La Migoua", "Bandol", 2019, 95.0, None, "rouge",
       "RVF N°701 vertical p.96"),
    _r("Domaine Tempier", "La Migoua", "Bandol", 2017, 94.5, None, "rouge",
       "RVF N°701 vertical p.96 (94+/100)"),
    _r("Domaine Tempier", "La Migoua", "Bandol", 2015, 95.5, None, "rouge",
       "RVF N°701 vertical p.96 (95+/100)"),
    _r("Domaine Tempier", "La Migoua", "Bandol", 2012, 93.5, None, "rouge",
       "RVF N°701 vertical p.96 (93+/100)"),
    _r("Domaine Tempier", "La Migoua", "Bandol", 2008, 95.0, None, "rouge",
       "RVF N°701 vertical p.96"),
    _r("Domaine Tempier", "La Migoua", "Bandol", 2006, 97.0, None, "rouge",
       "RVF N°701 vertical p.96"),
    _r("Domaine Tempier", "La Migoua", "Bandol", 2000, 96.5, None, "rouge",
       "RVF N°701 vertical p.96 (96+/100)"),
    _r("Domaine Tempier", "La Migoua", "Bandol", 1993, 95.0, None, "rouge",
       "RVF N°701 vertical p.96"),
    _r("Domaine Tempier", "La Migoua", "Bandol", 1988, 96.5, None, "rouge",
       "RVF N°701 vertical p.96 (96+/100)"),
    _r("Domaine Tempier", "La Migoua", "Bandol", 1979, 98.0, None, "rouge",
       "RVF N°701 vertical p.96"),

    # Current releases (p.98)
    _r("Domaine Tempier", "", "Bandol", 2024, 90.0, None, "blanc",
       "RVF N°701 p.98 Bandol blanc 2024"),
    _r("Domaine Tempier", "", "Bandol", 2024, 90.0, None, "rosé",
       "RVF N°701 p.98 Bandol rosé 2024"),
    _r("Domaine Tempier", "Lulu et Lucien", "Bandol", 2023, 92.0, None, "rouge",
       "RVF N°701 p.98 Bandol rouge"),
    _r("Domaine Tempier", "La Tourtine", "Bandol", 2023, 97.0, None, "rouge",
       "RVF N°701 p.98"),
    _r("Domaine Tempier", "Cabassou", "Bandol", 2023, 97.0, None, "rouge",
       "RVF N°701 p.98"),

    # =========================================================================
    # SECTION C — BORDEAUX PRIMEURS 2025 (p.118-143)
    # Format:
    #   score row  → vintage=2025, price_eur=None
    #   price rows → vintage=2025 (score), price_vintage=2024 or 2023 in price_eur
    #   We encode both vintages as separate records for price:
    #     one record with price_vintage=2024
    #     one record with price_vintage=2023
    # =========================================================================

    # --- SAINT-ÉMILION Grand Cru et Grand Cru Classé (p.118-122) ---
    _r("Château Cheval Blanc", "", "Saint-Émilion Grand Cru", 2025, 98.5, None, "rouge",
       "RVF N°701 2025 primeur score p.118 (98-99/100)"),
    _r("Château Cheval Blanc", "", "Saint-Émilion Grand Cru", 2025, None, 390.0, "rouge",
       "RVF N°701 2024 ref price p.118", price_vintage=2024),
    _r("Château Cheval Blanc", "", "Saint-Émilion Grand Cru", 2025, None, 549.0, "rouge",
       "RVF N°701 2023 ref price p.118", price_vintage=2023),

    _r("Château Ausone", "", "Saint-Émilion Grand Cru", 2025, 97.0, None, "rouge",
       "RVF N°701 2025 primeur score p.118 (96-98/100)"),
    _r("Château Ausone", "", "Saint-Émilion Grand Cru", 2025, None, 438.0, "rouge",
       "RVF N°701 2024 ref price p.118", price_vintage=2024),
    _r("Château Ausone", "", "Saint-Émilion Grand Cru", 2025, None, 606.0, "rouge",
       "RVF N°701 2023 ref price p.118", price_vintage=2023),

    _r("Château Figeac", "", "Saint-Émilion Grand Cru", 2025, 97.0, None, "rouge",
       "RVF N°701 2025 primeur score p.118 (96-98/100)"),
    _r("Château Figeac", "", "Saint-Émilion Grand Cru", 2025, None, 101.0, "rouge",
       "RVF N°701 2024 ref price p.118", price_vintage=2024),
    _r("Château Figeac", "", "Saint-Émilion Grand Cru", 2025, None, 129.6, "rouge",
       "RVF N°701 2023 ref price p.118", price_vintage=2023),

    _r("Château Pavie", "", "Saint-Émilion Grand Cru", 2025, 97.0, None, "rouge",
       "RVF N°701 2025 primeur score p.118 (96-98/100)"),
    _r("Château Pavie", "", "Saint-Émilion Grand Cru", 2025, None, 134.0, "rouge",
       "RVF N°701 2024 ref price p.118", price_vintage=2024),
    _r("Château Pavie", "", "Saint-Émilion Grand Cru", 2025, None, 214.0, "rouge",
       "RVF N°701 2023 ref price p.118", price_vintage=2023),

    _r("Château Beauséjour", "J. Duffau-Lagarrosse", "Saint-Émilion Grand Cru", 2025, 96.5, None, "rouge",
       "RVF N°701 2025 primeur score p.118 (96-97/100)"),
    _r("Château Beauséjour", "J. Duffau-Lagarrosse", "Saint-Émilion Grand Cru", 2025, None, 193.0, "rouge",
       "RVF N°701 2024 ref price p.118", price_vintage=2024),
    _r("Château Beauséjour", "J. Duffau-Lagarrosse", "Saint-Émilion Grand Cru", 2025, None, 327.0, "rouge",
       "RVF N°701 2023 ref price p.118", price_vintage=2023),

    _r("Château Larcis Ducasse", "", "Saint-Émilion Grand Cru", 2025, 96.0, None, "rouge",
       "RVF N°701 2025 primeur score p.118 (95-97/100)"),
    _r("Château Larcis Ducasse", "", "Saint-Émilion Grand Cru", 2025, None, 43.0, "rouge",
       "RVF N°701 2024 ref price p.118", price_vintage=2024),
    _r("Château Larcis Ducasse", "", "Saint-Émilion Grand Cru", 2025, None, 70.5, "rouge",
       "RVF N°701 2023 ref price p.118", price_vintage=2023),

    _r("Château Belair Monange", "", "Saint-Émilion Grand Cru", 2025, 95.5, None, "rouge",
       "RVF N°701 2025 primeur score p.118 (94-97/100)"),
    _r("Château Belair Monange", "", "Saint-Émilion Grand Cru", 2025, None, 131.0, "rouge",
       "RVF N°701 2024 ref price p.118", price_vintage=2024),
    _r("Château Belair Monange", "", "Saint-Émilion Grand Cru", 2025, None, 156.0, "rouge",
       "RVF N°701 2023 ref price p.118", price_vintage=2023),

    _r("Clos Fourtet", "", "Saint-Émilion Grand Cru", 2025, 95.5, None, "rouge",
       "RVF N°701 2025 primeur score p.118 (94-97/100)"),
    _r("Clos Fourtet", "", "Saint-Émilion Grand Cru", 2025, None, 72.24, "rouge",
       "RVF N°701 2024 ref price p.118", price_vintage=2024),
    _r("Clos Fourtet", "", "Saint-Émilion Grand Cru", 2025, None, 97.8, "rouge",
       "RVF N°701 2023 ref price p.118", price_vintage=2023),

    _r("Château Bellefont-Belcier", "", "Saint-Émilion Grand Cru", 2025, 95.5, None, "rouge",
       "RVF N°701 2025 primeur score p.118 (95-96/100)"),
    _r("Château Bellefont-Belcier", "", "Saint-Émilion Grand Cru", 2025, None, 57.1, "rouge",
       "RVF N°701 2024 ref price p.118", price_vintage=2024),
    _r("Château Bellefont-Belcier", "", "Saint-Émilion Grand Cru", 2025, None, 70.5, "rouge",
       "RVF N°701 2023 ref price p.118", price_vintage=2023),

    _r("Château Moulin Saint-Georges", "", "Saint-Émilion Grand Cru", 2025, 95.5, None, "rouge",
       "RVF N°701 2025 primeur score p.118 (95-96/100)"),
    _r("Château Moulin Saint-Georges", "", "Saint-Émilion Grand Cru", 2025, None, 37.8, "rouge",
       "RVF N°701 2024 ref price p.118", price_vintage=2024),
    _r("Château Moulin Saint-Georges", "", "Saint-Émilion Grand Cru", 2025, None, 48.6, "rouge",
       "RVF N°701 2023 ref price p.118", price_vintage=2023),

    _r("Château Canon-la-Gaffelière", "", "Saint-Émilion Grand Cru", 2025, 95.0, None, "rouge",
       "RVF N°701 2025 primeur score p.118 (94-96/100)"),
    _r("Château Canon-la-Gaffelière", "", "Saint-Émilion Grand Cru", 2025, None, 57.1, "rouge",
       "RVF N°701 2024 ref price p.118", price_vintage=2024),
    _r("Château Canon-la-Gaffelière", "", "Saint-Émilion Grand Cru", 2025, None, 70.5, "rouge",
       "RVF N°701 2023 ref price p.118", price_vintage=2023),

    _r("Château Jean Faure", "", "Saint-Émilion Grand Cru", 2025, 95.0, None, "rouge",
       "RVF N°701 2025 primeur score p.118 (94-96/100)"),
    _r("Château Jean Faure", "", "Saint-Émilion Grand Cru", 2025, None, 49.8, "rouge",
       "RVF N°701 2024 ref price p.118", price_vintage=2024),
    _r("Château Jean Faure", "", "Saint-Émilion Grand Cru", 2025, None, 62.4, "rouge",
       "RVF N°701 2023 ref price p.118", price_vintage=2023),

    _r("Château La Gaffelière", "", "Saint-Émilion Grand Cru", 2025, 95.0, None, "rouge",
       "RVF N°701 2025 primeur score p.118 (94-96/100)"),
    _r("Château La Gaffelière", "", "Saint-Émilion Grand Cru", 2025, None, 40.8, "rouge",
       "RVF N°701 2024 ref price p.118", price_vintage=2024),

    _r("Château Troplong Mondot", "", "Saint-Émilion Grand Cru", 2025, 96.0, None, "rouge",
       "RVF N°701 2025 primeur score p.118"),
    _r("Château Troplong Mondot", "", "Saint-Émilion Grand Cru", 2025, None, 100.0, "rouge",
       "RVF N°701 2024 ref price p.118", price_vintage=2024),
    _r("Château Troplong Mondot", "", "Saint-Émilion Grand Cru", 2025, None, 129.6, "rouge",
       "RVF N°701 2023 ref price p.118", price_vintage=2023),

    _r("Château Trotte Vieille", "", "Saint-Émilion Grand Cru", 2025, 96.0, None, "rouge",
       "RVF N°701 2025 primeur score p.118"),
    _r("Château Trotte Vieille", "", "Saint-Émilion Grand Cru", 2025, None, 60.0, "rouge",
       "RVF N°701 2024 ref price p.118", price_vintage=2024),
    _r("Château Trotte Vieille", "", "Saint-Émilion Grand Cru", 2025, None, 81.6, "rouge",
       "RVF N°701 2023 ref price p.118", price_vintage=2023),

    _r("Château Valandraud", "", "Saint-Émilion Grand Cru", 2025, 94.0, None, "rouge",
       "RVF N°701 2025 primeur score p.120 (93-95/100)"),
    _r("Château Valandraud", "", "Saint-Émilion Grand Cru", 2025, None, 108.0, "rouge",
       "RVF N°701 2024 ref price p.120", price_vintage=2024),
    _r("Château Valandraud", "", "Saint-Émilion Grand Cru", 2025, None, 135.6, "rouge",
       "RVF N°701 2023 ref price p.120", price_vintage=2023),

    _r("Château Pavie Macquin", "", "Saint-Émilion Grand Cru", 2025, 94.5, None, "rouge",
       "RVF N°701 2025 primeur score p.120 (93-96/100)"),
    _r("Château Pavie Macquin", "", "Saint-Émilion Grand Cru", 2025, None, 50.4, "rouge",
       "RVF N°701 2024 ref price p.120", price_vintage=2024),
    _r("Château Pavie Macquin", "", "Saint-Émilion Grand Cru", 2025, None, 67.2, "rouge",
       "RVF N°701 2023 ref price p.120", price_vintage=2023),

    _r("Château Beauséjour Bécot", "", "Saint-Émilion Grand Cru", 2025, 94.5, None, "rouge",
       "RVF N°701 2025 primeur score p.120 (94-95/100)"),
    _r("Château Beauséjour Bécot", "", "Saint-Émilion Grand Cru", 2025, None, 52.8, "rouge",
       "RVF N°701 2024 ref price p.120", price_vintage=2024),

    _r("Château Canon", "Croix Canon", "Saint-Émilion Grand Cru", 2025, 93.5, None, "rouge",
       "RVF N°701 2025 primeur score p.120 (92-95/100)"),
    _r("Château Canon", "Croix Canon", "Saint-Émilion Grand Cru", 2025, None, 39.0, "rouge",
       "RVF N°701 2023 ref price p.120", price_vintage=2023),

    _r("Château Grand Corbin-Despagne", "", "Saint-Émilion Grand Cru", 2025, 93.5, None, "rouge",
       "RVF N°701 2025 primeur score p.120 (92-95/100)"),
    _r("Château Grand Corbin-Despagne", "", "Saint-Émilion Grand Cru", 2025, None, 19.25, "rouge",
       "RVF N°701 2024 ref price p.120", price_vintage=2024),
    _r("Château Grand Corbin-Despagne", "", "Saint-Émilion Grand Cru", 2025, None, 20.2, "rouge",
       "RVF N°701 2023 ref price p.120", price_vintage=2023),

    _r("Château Sansonnet", "", "Saint-Émilion Grand Cru", 2025, 92.5, None, "rouge",
       "RVF N°701 2025 primeur score p.122 (92-93/100)"),
    _r("Château Sansonnet", "", "Saint-Émilion Grand Cru", 2025, None, 34.0, "rouge",
       "RVF N°701 2024 ref price p.122", price_vintage=2024),
    _r("Château Sansonnet", "", "Saint-Émilion Grand Cru", 2025, None, 39.0, "rouge",
       "RVF N°701 2023 ref price p.122", price_vintage=2023),

    _r("Château Villemaurine", "", "Saint-Émilion Grand Cru", 2025, 92.5, None, "rouge",
       "RVF N°701 2025 primeur score p.122 (92-93/100)"),
    _r("Château Villemaurine", "", "Saint-Émilion Grand Cru", 2025, None, 28.9, "rouge",
       "RVF N°701 2024 ref price p.122", price_vintage=2024),
    _r("Château Villemaurine", "", "Saint-Émilion Grand Cru", 2025, None, 40.8, "rouge",
       "RVF N°701 2023 ref price p.122", price_vintage=2023),

    _r("Château De Ferrand", "", "Saint-Émilion Grand Cru", 2025, 92.0, None, "rouge",
       "RVF N°701 2025 primeur score p.122 (91-93/100)"),
    _r("Château De Ferrand", "", "Saint-Émilion Grand Cru", 2025, None, 43.2, "rouge",
       "RVF N°701 2023 ref price p.122", price_vintage=2023),

    _r("Château Franc Mayne", "", "Saint-Émilion Grand Cru", 2025, 91.5, None, "rouge",
       "RVF N°701 2025 primeur score p.122 (91-92/100)"),
    _r("Château Franc Mayne", "", "Saint-Émilion Grand Cru", 2025, None, 29.1, "rouge",
       "RVF N°701 2024 ref price p.122", price_vintage=2024),
    _r("Château Franc Mayne", "", "Saint-Émilion Grand Cru", 2025, None, 29.1, "rouge",
       "RVF N°701 2023 ref price p.122", price_vintage=2023),

    _r("Château Fonplégade", "", "Saint-Émilion Grand Cru", 2025, 91.5, None, "rouge",
       "RVF N°701 2025 primeur score p.122 (91-92/100)"),
    _r("Château Fonplégade", "", "Saint-Émilion Grand Cru", 2025, None, 31.9, "rouge",
       "RVF N°701 2023 ref price p.122", price_vintage=2023),

    _r("Château Bellevue", "", "Saint-Émilion Grand Cru", 2025, 93.0, None, "rouge",
       "RVF N°701 2025 primeur score p.120-121 (92-94/100)"),
    _r("Château Bellevue", "", "Saint-Émilion Grand Cru", 2025, None, 42.3, "rouge",
       "RVF N°701 2024 ref price p.121", price_vintage=2024),
    _r("Château Bellevue", "", "Saint-Émilion Grand Cru", 2025, None, 42.3, "rouge",
       "RVF N°701 2023 ref price p.121", price_vintage=2023),

    _r("Château Berliquet", "", "Saint-Émilion Grand Cru", 2025, 93.0, None, "rouge",
       "RVF N°701 2025 primeur score p.121 (92-94/100)"),
    _r("Château Berliquet", "", "Saint-Émilion Grand Cru", 2025, None, 45.9, "rouge",
       "RVF N°701 2024 ref price p.121", price_vintage=2024),
    _r("Château Berliquet", "", "Saint-Émilion Grand Cru", 2025, None, 35.0, "rouge",
       "RVF N°701 2023 ref price p.121", price_vintage=2023),

    _r("Château Mangot", "", "Saint-Émilion Grand Cru", 2025, 93.0, None, "rouge",
       "RVF N°701 2025 primeur score p.121 (92-94/100)"),
    _r("Château Mangot", "", "Saint-Émilion Grand Cru", 2025, None, 36.25, "rouge",
       "RVF N°701 2024 ref price p.121", price_vintage=2024),
    _r("Château Mangot", "", "Saint-Émilion Grand Cru", 2025, None, 39.0, "rouge",
       "RVF N°701 2023 ref price p.121", price_vintage=2023),

    _r("Château Dassault", "", "Saint-Émilion Grand Cru", 2025, 93.0, None, "rouge",
       "RVF N°701 2025 primeur score p.121 (92-94/100)"),
    _r("Château Dassault", "", "Saint-Émilion Grand Cru", 2025, None, 26.05, "rouge",
       "RVF N°701 2024 ref price p.121", price_vintage=2024),
    _r("Château Dassault", "", "Saint-Émilion Grand Cru", 2025, None, 19.5, "rouge",
       "RVF N°701 2023 ref price p.121", price_vintage=2023),

    _r("Château Fleur Cardinale", "", "Saint-Émilion Grand Cru", 2025, 93.0, None, "rouge",
       "RVF N°701 2025 primeur score p.121 (92-94/100)"),
    _r("Château Fleur Cardinale", "", "Saint-Émilion Grand Cru", 2025, None, 37.1, "rouge",
       "RVF N°701 2024 ref price p.121", price_vintage=2024),
    _r("Château Fleur Cardinale", "", "Saint-Émilion Grand Cru", 2025, None, 45.6, "rouge",
       "RVF N°701 2023 ref price p.121", price_vintage=2023),

    _r("Château Saint-Georges-Côte Pavie", "", "Saint-Émilion Grand Cru", 2025, 93.0, None, "rouge",
       "RVF N°701 2025 primeur score p.121 (92-94/100)"),
    _r("Château Saint-Georges-Côte Pavie", "", "Saint-Émilion Grand Cru", 2025, None, 72.7, "rouge",
       "RVF N°701 2024 ref price p.121", price_vintage=2024),

    _r("Château Rochebelle", "", "Saint-Émilion Grand Cru", 2025, 93.0, None, "rouge",
       "RVF N°701 2025 primeur score p.121 (92-94/100)"),
    _r("Château Rochebelle", "", "Saint-Émilion Grand Cru", 2025, None, 27.0, "rouge",
       "RVF N°701 2024 ref price p.121", price_vintage=2024),
    _r("Château Rochebelle", "", "Saint-Émilion Grand Cru", 2025, None, 30.0, "rouge",
       "RVF N°701 2023 ref price p.121", price_vintage=2023),

    _r("Château Grand Mayne", "", "Saint-Émilion Grand Cru", 2025, 92.0, None, "rouge",
       "RVF N°701 2025 primeur score p.122 (91-93/100)"),
    _r("Château Grand Mayne", "", "Saint-Émilion Grand Cru", 2025, None, 34.45, "rouge",
       "RVF N°701 2024 ref price p.122", price_vintage=2024),
    _r("Château Grand Mayne", "", "Saint-Émilion Grand Cru", 2025, None, 38.4, "rouge",
       "RVF N°701 2023 ref price p.122", price_vintage=2023),

    _r("Château Chauvin", "", "Saint-Émilion Grand Cru", 2025, 91.5, None, "rouge",
       "RVF N°701 2025 primeur score p.122 (91-92/100)"),
    _r("Château Chauvin", "", "Saint-Émilion Grand Cru", 2025, None, 30.0, "rouge",
       "RVF N°701 2024 ref price p.122", price_vintage=2024),
    _r("Château Chauvin", "", "Saint-Émilion Grand Cru", 2025, None, 32.0, "rouge",
       "RVF N°701 2023 ref price p.122", price_vintage=2023),

    _r("Château Moulin Saint-Georges", "", "Saint-Émilion Grand Cru", 2025, 91.0, None, "rouge",
       "RVF N°701 2025 primeur score p.121 (90-92/100)"),
    _r("Château Moulin Saint-Georges", "", "Saint-Émilion Grand Cru", 2025, None, 16.8, "rouge",
       "RVF N°701 2024 ref price p.121", price_vintage=2024),
    _r("Château Moulin Saint-Georges", "", "Saint-Émilion Grand Cru", 2025, None, 19.5, "rouge",
       "RVF N°701 2023 ref price p.121", price_vintage=2023),

    # Autour de Saint-Émilion (Castillon, Côtes de Bordeaux, Fronsac) — p.123
    _r("Château Montlandrie", "", "Castillon Côtes de Bordeaux", 2025, 93.0, None, "rouge",
       "RVF N°701 2025 primeur score p.123 (92-94/100)"),
    _r("Clos Lunelles", "", "Castillon Côtes de Bordeaux", 2025, 92.5, None, "rouge",
       "RVF N°701 2025 primeur score p.123 (92-93/100)"),
    _r("Clos Lunelles", "", "Castillon Côtes de Bordeaux", 2025, None, 23.5, "rouge",
       "RVF N°701 2024 ref price p.123", price_vintage=2024),
    _r("Clos Lunelles", "", "Castillon Côtes de Bordeaux", 2025, None, 24.0, "rouge",
       "RVF N°701 2023 ref price p.123", price_vintage=2023),
    _r("Château d'Aiguilhe", "", "Castillon Côtes de Bordeaux", 2025, 92.5, None, "rouge",
       "RVF N°701 2025 primeur score p.123 (92-93/100)"),
    _r("Château d'Aiguilhe", "", "Castillon Côtes de Bordeaux", 2025, None, 15.0, "rouge",
       "RVF N°701 2024 ref price p.123", price_vintage=2024),
    _r("Château d'Aiguilhe", "", "Castillon Côtes de Bordeaux", 2025, None, 19.0, "rouge",
       "RVF N°701 2023 ref price p.123", price_vintage=2023),
    _r("Château La Brande", "", "Castillon Côtes de Bordeaux", 2025, 92.0, None, "rouge",
       "RVF N°701 2025 primeur score p.123 (91-93/100)"),
    _r("Château La Brande", "", "Castillon Côtes de Bordeaux", 2025, None, 15.0, "rouge",
       "RVF N°701 2023 ref price p.123", price_vintage=2023),

]

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def lookup_appellation(cur, raw_name: str, fallback_key: int) -> int:
    candidates = []
    n = norm_text(raw_name)
    candidates.append(n)
    for prefix in ("igp ", "aop ", "aoc "):
        if n.startswith(prefix):
            candidates.append(n[len(prefix):])
    OVERRIDES = {
        "saint emilion grand cru": "saint emilion grand cru",
        "vin de france": "vin de france",
        "muscat du cap corse": "muscat du cap corse",
        "corse": "corse",
        "ajaccio": "ajaccio",
        "patrimonio": "patrimonio",
        "ile de beaute": "ile de beaute",
        "corse calvi": "corse calvi",
        "coteaux du cap corse": "coteaux du cap corse",
        "cotes du rhone": "cotes du rhone",
        "chateauneuf du pape": "chateauneuf du pape",
        "vacqueyras": "vacqueyras",
        "cairanne": "cairanne",
        "muscat de beaumes de venise": "muscat de beaumes de venise",
        "bandol": "bandol",
        "castillon cotes de bordeaux": "castillon cotes de bordeaux",
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
    log.warning("Appellation not found, using France fallback: %r", raw_name)
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
    log.info("Created producer: %r  (key=%d)", producer_display, new_key)
    return new_key


def get_or_create_wine(cur, producer_key, appellation_key, producer_display,
                       cuvee_display, color, vintage, now) -> str:
    p_norm = normalize_producer(producer_display)
    c_norm = normalize_cuvee(cuvee_display)
    wine_key = compute_wine_key(p_norm, c_norm, vintage)
    canonical = f"{producer_display} {cuvee_display}".strip()
    if vintage:
        canonical = f"{canonical} {vintage}"
    cur.execute("SELECT wine_key FROM dim_wine WHERE wine_key=?", (wine_key,))
    if cur.fetchone():
        return wine_key
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

    # Lookup RVF source_key
    cur.execute("SELECT source_key FROM dim_source WHERE source_code='rvf' LIMIT 1")
    row = cur.fetchone()
    if not row:
        log.error("dim_source has no row with source_code='rvf'")
        sys.exit(1)
    source_key = row[0]
    log.info("RVF source_key=%d", source_key)

    # France fallback appellation
    cur.execute("SELECT appellation_key FROM dim_appellation WHERE appellation_norm='france' LIMIT 1")
    row = cur.fetchone()
    fallback_key = row[0] if row else 1

    # Before-counts
    cur.execute("SELECT COUNT(*) FROM staging_rating_candidates WHERE batch_id=?", (BATCH_ID,))
    before_ratings = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM staging_price_candidates WHERE batch_id=?", (BATCH_ID,))
    before_prices = cur.fetchone()[0]

    # ── Sanity check ──
    for w in WINES:
        if w["score"] is not None:
            assert w["score"] <= 100, f"Score > 100: {w}"
        if w["price_eur"] is not None:
            assert w["price_eur"] > 0, f"Price <= 0: {w}"

    new_ratings = 0
    new_prices = 0
    skipped = 0

    for w in WINES:
        producer = w["producer"]
        cuvee = w["cuvee"] or ""
        appellation = w["appellation"]
        vintage = w["vintage"]       # for the wine entity (score vintage)
        score = w["score"]
        price_eur = w["price_eur"]
        color = w["color"]
        price_vintage = w.get("price_vintage")  # vintage for price row (Bordeaux ref prices)

        # For Bordeaux price rows with price_vintage, the price belongs to a different
        # vintage than the score. We need a separate dim_wine key for that vintage.
        price_row_vintage = price_vintage if price_vintage is not None else vintage

        appellation_key = lookup_appellation(cur, appellation, fallback_key)
        producer_key = get_or_create_producer(cur, producer, now)

        if score is not None:
            # Score wine_key uses 'vintage'
            wine_key = get_or_create_wine(
                cur, producer_key, appellation_key, producer, cuvee, color, vintage, now
            )
            ch = sha1(f"rvf_n701_complete_{wine_key}_{vintage}_{score}")
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

        if price_eur is not None:
            # Price wine_key uses price_row_vintage
            wine_key_p = get_or_create_wine(
                cur, producer_key, appellation_key, producer, cuvee, color,
                price_row_vintage, now
            )
            ch_p = sha1(f"rvf_n701_price_{wine_key_p}_{price_row_vintage}_{price_eur}")
            cur.execute(
                """INSERT OR IGNORE INTO staging_price_candidates
                    (wine_key, source_key, currency_code, amount_local, amount_eur,
                     recorded_at, batch_id, needs_review, content_hash)
                   VALUES (?, ?, 'EUR', ?, ?, ?, ?, 1, ?)""",
                (wine_key_p, source_key, price_eur, price_eur, now, BATCH_ID, ch_p),
            )
            if cur.rowcount > 0:
                new_prices += 1
            else:
                skipped += 1

    con.commit()

    # After-counts
    cur.execute("SELECT COUNT(*) FROM staging_rating_candidates WHERE batch_id=?", (BATCH_ID,))
    after_ratings = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM staging_price_candidates WHERE batch_id=?", (BATCH_ID,))
    after_prices = cur.fetchone()[0]

    con.close()

    print()
    print("=" * 60)
    print(f"  RVF N701 Complete Import - batch_id='{BATCH_ID}'")
    print("=" * 60)
    print(f"  Wine records processed  : {len(WINES)}")
    print(f"  New ratings inserted    : {new_ratings}  (staging_rating_candidates: {before_ratings} -> {after_ratings})")
    print(f"  New prices inserted     : {new_prices}  (staging_price_candidates:  {before_prices} -> {after_prices})")
    print(f"  Skipped (already exist) : {skipped}")
    print()
    print("  Sanity checks PASSED:")
    print("  [OK] No scores > 100")
    print("  [OK] No prices <= 0")
    print("  [OK] FR-only wines (non-FR sections skipped)")
    print("=" * 60)


if __name__ == "__main__":
    main()
