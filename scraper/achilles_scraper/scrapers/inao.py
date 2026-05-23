"""
INAO French Appellation Ingestor — Phase 0 of French wine spine.

Sources:
  1. INAO REST API:  https://www.inao.gouv.fr/rest/produit  (names + INAO codes)
  2. data.gouv.fr:   GeoJSON geometries (centroids + geo_polygon)
  3. Built-in taxonomy: region / subregion / level for known appellations

Strategy:
  - Existing dim_appellation rows (from burgundy-manager import): PATCH
    inao_code + latitude + longitude + geo_polygon only.
    Region/subregion/level left unchanged — fixing the hierarchy is a
    separate migration task to avoid breaking region_gate.
  - New appellations (not yet in DB): INSERT with full taxonomy.

dim_source:  source_code = 'INAO', tier = A_official, cadence = annual
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Optional

import httpx
from rich.console import Console

from .base import BaseScraper, ScrapeResult
from ..dlq import write_dlq
from ..identity import norm_text

console = Console()

# ---------------------------------------------------------------------------
# INAO / data.gouv.fr endpoints
# ---------------------------------------------------------------------------
_INAO_PRODUIT_URL = "https://www.inao.gouv.fr/rest/produit"
_DATAGOUV_SEARCH_URL = (
    "https://www.data.gouv.fr/api/1/datasets/"
    "?q=aires+g%C3%A9ographiques+inao+vins&page_size=5"
)
# Stable direct download URL for the INAO GeoJSON (wine AOC areas, WGS84)
# This resource ID is from the well-known data.gouv.fr INAO dataset.
_DATAGOUV_GEOJSON_URL = (
    "https://www.data.gouv.fr/fr/datasets/r/"
    "d87c6d4c-35cc-4dd9-b5ef-88e4e1499b31"
)

# ---------------------------------------------------------------------------
# Built-in taxonomy  (appellation_norm → {region, subregion, level, lat, lon})
# Used for new-row inserts AND to classify INAO API results that don't
# already exist in dim_appellation.
# lat/lon values are approximate region centroids — the GeoJSON fetch will
# override with proper polygon-derived centroids where available.
# ---------------------------------------------------------------------------
_TAXONOMY: dict[str, dict] = {
    # ── Bordeaux ────────────────────────────────────────────────────────────
    "bordeaux": {"region": "Bordeaux", "subregion": "Bordeaux", "level": "regional", "lat": 44.8378, "lon": -0.5792},
    "bordeaux superieur": {"region": "Bordeaux", "subregion": "Bordeaux", "level": "regional", "lat": 44.8, "lon": -0.4},
    "cremant de bordeaux": {"region": "Bordeaux", "subregion": "Bordeaux", "level": "regional", "lat": 44.8, "lon": -0.5},
    "cotes de bordeaux": {"region": "Bordeaux", "subregion": "Bordeaux", "level": "regional", "lat": 44.8, "lon": -0.3},
    "blaye cotes de bordeaux": {"region": "Bordeaux", "subregion": "Blaye", "level": "regional", "lat": 45.13, "lon": -0.67},
    "blaye": {"region": "Bordeaux", "subregion": "Blaye", "level": "regional", "lat": 45.13, "lon": -0.67},
    "bourg": {"region": "Bordeaux", "subregion": "Blaye", "level": "regional", "lat": 45.04, "lon": -0.56},
    "cotes de bourg": {"region": "Bordeaux", "subregion": "Blaye", "level": "regional", "lat": 45.04, "lon": -0.56},
    "medoc": {"region": "Bordeaux", "subregion": "Médoc", "level": "regional", "lat": 45.18, "lon": -0.95},
    "haut medoc": {"region": "Bordeaux", "subregion": "Médoc", "level": "regional", "lat": 45.1, "lon": -0.85},
    "pauillac": {"region": "Bordeaux", "subregion": "Médoc", "level": "village", "lat": 45.2, "lon": -0.75},
    "saint julien": {"region": "Bordeaux", "subregion": "Médoc", "level": "village", "lat": 45.17, "lon": -0.77},
    "margaux": {"region": "Bordeaux", "subregion": "Médoc", "level": "village", "lat": 45.04, "lon": -0.67},
    "saint estephe": {"region": "Bordeaux", "subregion": "Médoc", "level": "village", "lat": 45.26, "lon": -0.77},
    "moulis en medoc": {"region": "Bordeaux", "subregion": "Médoc", "level": "village", "lat": 45.08, "lon": -0.78},
    "listrac medoc": {"region": "Bordeaux", "subregion": "Médoc", "level": "village", "lat": 45.11, "lon": -0.81},
    "saint emilion": {"region": "Bordeaux", "subregion": "Libournais", "level": "village", "lat": 44.89, "lon": -0.15},
    "saint emilion grand cru": {"region": "Bordeaux", "subregion": "Libournais", "level": "grand_cru", "lat": 44.89, "lon": -0.15},
    "pomerol": {"region": "Bordeaux", "subregion": "Libournais", "level": "village", "lat": 44.91, "lon": -0.18},
    "lalande de pomerol": {"region": "Bordeaux", "subregion": "Libournais", "level": "village", "lat": 44.95, "lon": -0.18},
    "fronsac": {"region": "Bordeaux", "subregion": "Libournais", "level": "village", "lat": 44.96, "lon": -0.25},
    "canon fronsac": {"region": "Bordeaux", "subregion": "Libournais", "level": "village", "lat": 44.96, "lon": -0.26},
    "lussac saint emilion": {"region": "Bordeaux", "subregion": "Libournais", "level": "village", "lat": 44.97, "lon": -0.11},
    "montagne saint emilion": {"region": "Bordeaux", "subregion": "Libournais", "level": "village", "lat": 44.96, "lon": -0.12},
    "puisseguin saint emilion": {"region": "Bordeaux", "subregion": "Libournais", "level": "village", "lat": 44.93, "lon": -0.08},
    "saint georges saint emilion": {"region": "Bordeaux", "subregion": "Libournais", "level": "village", "lat": 44.95, "lon": -0.13},
    "sauternes": {"region": "Bordeaux", "subregion": "Sauternais", "level": "village", "lat": 44.54, "lon": -0.35},
    "barsac": {"region": "Bordeaux", "subregion": "Sauternais", "level": "village", "lat": 44.59, "lon": -0.33},
    "cerons": {"region": "Bordeaux", "subregion": "Sauternais", "level": "village", "lat": 44.62, "lon": -0.33},
    "loupiac": {"region": "Bordeaux", "subregion": "Sauternais", "level": "village", "lat": 44.60, "lon": -0.29},
    "sainte croix du mont": {"region": "Bordeaux", "subregion": "Sauternais", "level": "village", "lat": 44.60, "lon": -0.28},
    "pessac leognan": {"region": "Bordeaux", "subregion": "Graves", "level": "village", "lat": 44.78, "lon": -0.64},
    "graves": {"region": "Bordeaux", "subregion": "Graves", "level": "regional", "lat": 44.65, "lon": -0.47},
    "graves de vayres": {"region": "Bordeaux", "subregion": "Graves", "level": "regional", "lat": 44.88, "lon": -0.28},
    "entre deux mers": {"region": "Bordeaux", "subregion": "Entre-Deux-Mers", "level": "regional", "lat": 44.75, "lon": -0.3},
    "castillon cotes de bordeaux": {"region": "Bordeaux", "subregion": "Libournais", "level": "regional", "lat": 44.86, "lon": -0.05},
    "francs cotes de bordeaux": {"region": "Bordeaux", "subregion": "Libournais", "level": "regional", "lat": 44.88, "lon": -0.0},
    # ── Bourgogne ───────────────────────────────────────────────────────────
    "bourgogne": {"region": "Bourgogne", "subregion": "Bourgogne", "level": "regional", "lat": 47.05, "lon": 4.85},
    "bourgogne aligote": {"region": "Bourgogne", "subregion": "Bourgogne", "level": "regional", "lat": 47.0, "lon": 4.85},
    "bourgogne passe tout grains": {"region": "Bourgogne", "subregion": "Bourgogne", "level": "regional", "lat": 47.0, "lon": 4.85},
    "cremant de bourgogne": {"region": "Bourgogne", "subregion": "Bourgogne", "level": "regional", "lat": 47.0, "lon": 4.85},
    "coteaux bourguignons": {"region": "Bourgogne", "subregion": "Bourgogne", "level": "regional", "lat": 47.0, "lon": 4.85},
    "macon": {"region": "Bourgogne", "subregion": "Mâconnais", "level": "regional", "lat": 46.3, "lon": 4.83},
    "macon villages": {"region": "Bourgogne", "subregion": "Mâconnais", "level": "regional", "lat": 46.3, "lon": 4.83},
    "pouilly fuisse": {"region": "Bourgogne", "subregion": "Mâconnais", "level": "village", "lat": 46.29, "lon": 4.75},
    "pouilly loche": {"region": "Bourgogne", "subregion": "Mâconnais", "level": "village", "lat": 46.29, "lon": 4.76},
    "pouilly vinzelles": {"region": "Bourgogne", "subregion": "Mâconnais", "level": "village", "lat": 46.29, "lon": 4.75},
    "saint veran": {"region": "Bourgogne", "subregion": "Mâconnais", "level": "village", "lat": 46.26, "lon": 4.72},
    "vire clesse": {"region": "Bourgogne", "subregion": "Mâconnais", "level": "village", "lat": 46.44, "lon": 4.74},
    "saint amour bellevue": {"region": "Bourgogne", "subregion": "Mâconnais", "level": "village", "lat": 46.26, "lon": 4.72},
    "mercurey": {"region": "Bourgogne", "subregion": "Côte Chalonnaise", "level": "village", "lat": 46.73, "lon": 4.73},
    "givry": {"region": "Bourgogne", "subregion": "Côte Chalonnaise", "level": "village", "lat": 46.78, "lon": 4.74},
    "rully": {"region": "Bourgogne", "subregion": "Côte Chalonnaise", "level": "village", "lat": 46.87, "lon": 4.74},
    "montagny": {"region": "Bourgogne", "subregion": "Côte Chalonnaise", "level": "village", "lat": 46.68, "lon": 4.68},
    "bouzeron": {"region": "Bourgogne", "subregion": "Côte Chalonnaise", "level": "village", "lat": 46.9, "lon": 4.74},
    "cote chalonnaise": {"region": "Bourgogne", "subregion": "Côte Chalonnaise", "level": "regional", "lat": 46.8, "lon": 4.72},
    "gevrey chambertin": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "village", "lat": 47.23, "lon": 4.97},
    "chambolle musigny": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "village", "lat": 47.2, "lon": 4.97},
    "vosne romanee": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "village", "lat": 47.18, "lon": 4.95},
    "nuits saint georges": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "village", "lat": 47.14, "lon": 4.94},
    "morey saint denis": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "village", "lat": 47.22, "lon": 4.97},
    "vougeot": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "village", "lat": 47.2, "lon": 4.96},
    "flagey echezeaux": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "village", "lat": 47.18, "lon": 4.95},
    "marsannay": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "village", "lat": 47.27, "lon": 5.0},
    "fixin": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "village", "lat": 47.26, "lon": 4.98},
    "cote de nuits villages": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "regional", "lat": 47.15, "lon": 4.92},
    "hautes cotes de nuits": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "regional", "lat": 47.2, "lon": 4.9},
    "meursault": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "village", "lat": 46.98, "lon": 4.77},
    "puligny montrachet": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "village", "lat": 46.95, "lon": 4.77},
    "chassagne montrachet": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "village", "lat": 46.93, "lon": 4.77},
    "pommard": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "village", "lat": 46.99, "lon": 4.79},
    "volnay": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "village", "lat": 46.97, "lon": 4.78},
    "beaune": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "village", "lat": 47.02, "lon": 4.84},
    "corton": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "grand_cru", "lat": 47.06, "lon": 4.86},
    "aloxe corton": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "village", "lat": 47.07, "lon": 4.87},
    "savigny les beaune": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "village", "lat": 47.07, "lon": 4.82},
    "pernand vergelesses": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "village", "lat": 47.08, "lon": 4.86},
    "santenay": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "village", "lat": 46.9, "lon": 4.72},
    "maranges": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "village", "lat": 46.89, "lon": 4.69},
    "ladoix": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "village", "lat": 47.08, "lon": 4.88},
    "chorey les beaune": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "village", "lat": 47.04, "lon": 4.86},
    "monthelie": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "village", "lat": 46.97, "lon": 4.78},
    "saint aubin": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "village", "lat": 46.93, "lon": 4.75},
    "auxey duresses": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "village", "lat": 46.96, "lon": 4.75},
    "saint romain": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "village", "lat": 46.96, "lon": 4.73},
    "hautes cotes de beaune": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "regional", "lat": 46.95, "lon": 4.7},
    "cote de beaune": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "regional", "lat": 47.0, "lon": 4.82},
    "cote de beaune villages": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "regional", "lat": 47.0, "lon": 4.82},
    "chablis": {"region": "Bourgogne", "subregion": "Chablis", "level": "village", "lat": 47.81, "lon": 3.8},
    "chablis premier cru": {"region": "Bourgogne", "subregion": "Chablis", "level": "premier_cru", "lat": 47.81, "lon": 3.8},
    "chablis grand cru": {"region": "Bourgogne", "subregion": "Chablis", "level": "grand_cru", "lat": 47.81, "lon": 3.8},
    "petit chablis": {"region": "Bourgogne", "subregion": "Chablis", "level": "regional", "lat": 47.82, "lon": 3.79},
    "irancy": {"region": "Bourgogne", "subregion": "Chablis", "level": "village", "lat": 47.72, "lon": 3.67},
    "saint bris": {"region": "Bourgogne", "subregion": "Chablis", "level": "village", "lat": 47.71, "lon": 3.66},
    "vezelay": {"region": "Bourgogne", "subregion": "Chablis", "level": "village", "lat": 47.47, "lon": 3.74},
    "epineuil": {"region": "Bourgogne", "subregion": "Chablis", "level": "village", "lat": 47.9, "lon": 3.98},
    "chitry": {"region": "Bourgogne", "subregion": "Chablis", "level": "village", "lat": 47.77, "lon": 3.66},
    "montrecul": {"region": "Bourgogne", "subregion": "Chablis", "level": "village", "lat": 47.72, "lon": 3.7},
    # Grand Crus — Bourgogne
    "chambertin": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.23, "lon": 4.97},
    "chambertin clos de beze": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.23, "lon": 4.97},
    "chapelle chambertin": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.23, "lon": 4.97},
    "charmes chambertin": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.23, "lon": 4.97},
    "griotte chambertin": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.23, "lon": 4.97},
    "latricieres chambertin": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.23, "lon": 4.97},
    "mazis chambertin": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.23, "lon": 4.97},
    "mazoyeres chambertin": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.23, "lon": 4.97},
    "ruchottes chambertin": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.23, "lon": 4.97},
    "bonnes mares": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.21, "lon": 4.97},
    "musigny": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.2, "lon": 4.97},
    "clos de vougeot": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.2, "lon": 4.96},
    "grands echezeaux": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.18, "lon": 4.95},
    "echezeaux": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.18, "lon": 4.95},
    "richebourg": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.18, "lon": 4.95},
    "romanee saint vivant": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.18, "lon": 4.95},
    "romanee conti": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "iconic", "lat": 47.18, "lon": 4.95},
    "la romanee": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.18, "lon": 4.95},
    "la tache": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.18, "lon": 4.95},
    "la grande rue": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.18, "lon": 4.95},
    "clos saint denis": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.22, "lon": 4.97},
    "clos de la roche": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.22, "lon": 4.97},
    "clos des lambrays": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.22, "lon": 4.97},
    "clos de tart": {"region": "Bourgogne", "subregion": "Côte de Nuits", "level": "grand_cru", "lat": 47.22, "lon": 4.97},
    "montrachet": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "grand_cru", "lat": 46.94, "lon": 4.77},
    "batard montrachet": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "grand_cru", "lat": 46.94, "lon": 4.77},
    "bienvenues batard montrachet": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "grand_cru", "lat": 46.94, "lon": 4.77},
    "chevalier montrachet": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "grand_cru", "lat": 46.95, "lon": 4.77},
    "criots batard montrachet": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "grand_cru", "lat": 46.93, "lon": 4.77},
    "corton charlemagne": {"region": "Bourgogne", "subregion": "Côte de Beaune", "level": "grand_cru", "lat": 47.07, "lon": 4.87},
    # ── Champagne ───────────────────────────────────────────────────────────
    "champagne": {"region": "Champagne", "subregion": "Champagne", "level": "regional", "lat": 49.25, "lon": 4.03},
    "coteaux champenois": {"region": "Champagne", "subregion": "Champagne", "level": "regional", "lat": 49.25, "lon": 4.03},
    "rose des riceys": {"region": "Champagne", "subregion": "Champagne", "level": "village", "lat": 48.0, "lon": 4.37},
    # ── Loire ───────────────────────────────────────────────────────────────
    "muscadet": {"region": "Loire", "subregion": "Pays Nantais", "level": "regional", "lat": 47.18, "lon": -1.45},
    "muscadet sevre et maine": {"region": "Loire", "subregion": "Pays Nantais", "level": "village", "lat": 47.15, "lon": -1.4},
    "muscadet cotes de grand lieu": {"region": "Loire", "subregion": "Pays Nantais", "level": "village", "lat": 47.13, "lon": -1.6},
    "muscadet coteaux de la loire": {"region": "Loire", "subregion": "Pays Nantais", "level": "village", "lat": 47.35, "lon": -1.2},
    "gros plant du pays nantais": {"region": "Loire", "subregion": "Pays Nantais", "level": "regional", "lat": 47.2, "lon": -1.6},
    "coteaux d ancenis": {"region": "Loire", "subregion": "Pays Nantais", "level": "regional", "lat": 47.37, "lon": -1.18},
    "fiefs vendeens": {"region": "Loire", "subregion": "Pays Nantais", "level": "regional", "lat": 46.67, "lon": -1.43},
    "anjou": {"region": "Loire", "subregion": "Anjou-Saumur", "level": "regional", "lat": 47.47, "lon": -0.55},
    "anjou blanc": {"region": "Loire", "subregion": "Anjou-Saumur", "level": "regional", "lat": 47.47, "lon": -0.55},
    "anjou villages": {"region": "Loire", "subregion": "Anjou-Saumur", "level": "regional", "lat": 47.47, "lon": -0.55},
    "anjou villages brissac": {"region": "Loire", "subregion": "Anjou-Saumur", "level": "village", "lat": 47.36, "lon": -0.44},
    "rose d anjou": {"region": "Loire", "subregion": "Anjou-Saumur", "level": "regional", "lat": 47.47, "lon": -0.55},
    "cabernet d anjou": {"region": "Loire", "subregion": "Anjou-Saumur", "level": "regional", "lat": 47.47, "lon": -0.55},
    "savennieres": {"region": "Loire", "subregion": "Anjou-Saumur", "level": "village", "lat": 47.38, "lon": -0.67},
    "savennieres coulée de serrant": {"region": "Loire", "subregion": "Anjou-Saumur", "level": "iconic", "lat": 47.38, "lon": -0.67},
    "savennieres roche aux moines": {"region": "Loire", "subregion": "Anjou-Saumur", "level": "village", "lat": 47.38, "lon": -0.67},
    "coteaux du layon": {"region": "Loire", "subregion": "Anjou-Saumur", "level": "village", "lat": 47.32, "lon": -0.6},
    "quarts de chaume": {"region": "Loire", "subregion": "Anjou-Saumur", "level": "grand_cru", "lat": 47.31, "lon": -0.59},
    "bonnezeaux": {"region": "Loire", "subregion": "Anjou-Saumur", "level": "village", "lat": 47.35, "lon": -0.48},
    "coteaux de l aubance": {"region": "Loire", "subregion": "Anjou-Saumur", "level": "village", "lat": 47.36, "lon": -0.47},
    "saumur": {"region": "Loire", "subregion": "Anjou-Saumur", "level": "village", "lat": 47.26, "lon": -0.07},
    "saumur champigny": {"region": "Loire", "subregion": "Anjou-Saumur", "level": "village", "lat": 47.24, "lon": -0.04},
    "saumur brézé": {"region": "Loire", "subregion": "Anjou-Saumur", "level": "village", "lat": 47.22, "lon": -0.08},
    "coteaux de saumur": {"region": "Loire", "subregion": "Anjou-Saumur", "level": "village", "lat": 47.26, "lon": -0.07},
    "cremant de loire": {"region": "Loire", "subregion": "Anjou-Saumur", "level": "regional", "lat": 47.3, "lon": -0.2},
    "touraine": {"region": "Loire", "subregion": "Touraine", "level": "regional", "lat": 47.39, "lon": 0.69},
    "touraine amboise": {"region": "Loire", "subregion": "Touraine", "level": "village", "lat": 47.41, "lon": 0.98},
    "touraine azay le rideau": {"region": "Loire", "subregion": "Touraine", "level": "village", "lat": 47.26, "lon": 0.47},
    "touraine mesland": {"region": "Loire", "subregion": "Touraine", "level": "village", "lat": 47.49, "lon": 1.18},
    "touraine noble joue": {"region": "Loire", "subregion": "Touraine", "level": "village", "lat": 47.37, "lon": 0.66},
    "vouvray": {"region": "Loire", "subregion": "Touraine", "level": "village", "lat": 47.41, "lon": 0.81},
    "montlouis sur loire": {"region": "Loire", "subregion": "Touraine", "level": "village", "lat": 47.39, "lon": 0.85},
    "chinon": {"region": "Loire", "subregion": "Touraine", "level": "village", "lat": 47.17, "lon": 0.24},
    "bourgueil": {"region": "Loire", "subregion": "Touraine", "level": "village", "lat": 47.28, "lon": 0.17},
    "saint nicolas de bourgueil": {"region": "Loire", "subregion": "Touraine", "level": "village", "lat": 47.28, "lon": 0.13},
    "cheverny": {"region": "Loire", "subregion": "Touraine", "level": "village", "lat": 47.5, "lon": 1.46},
    "cour cheverny": {"region": "Loire", "subregion": "Touraine", "level": "village", "lat": 47.5, "lon": 1.46},
    "valencay": {"region": "Loire", "subregion": "Touraine", "level": "village", "lat": 47.16, "lon": 1.56},
    "sancerre": {"region": "Loire", "subregion": "Centre-Loire", "level": "village", "lat": 47.33, "lon": 2.83},
    "pouilly fume": {"region": "Loire", "subregion": "Centre-Loire", "level": "village", "lat": 47.29, "lon": 2.96},
    "pouilly sur loire": {"region": "Loire", "subregion": "Centre-Loire", "level": "village", "lat": 47.29, "lon": 2.96},
    "menetou salon": {"region": "Loire", "subregion": "Centre-Loire", "level": "village", "lat": 47.23, "lon": 2.49},
    "quincy": {"region": "Loire", "subregion": "Centre-Loire", "level": "village", "lat": 47.1, "lon": 2.08},
    "reuilly": {"region": "Loire", "subregion": "Centre-Loire", "level": "village", "lat": 47.07, "lon": 1.82},
    "chateaumeillant": {"region": "Loire", "subregion": "Centre-Loire", "level": "village", "lat": 46.57, "lon": 2.19},
    "coteaux du giennois": {"region": "Loire", "subregion": "Centre-Loire", "level": "regional", "lat": 47.6, "lon": 2.63},
    "coteaux du loir": {"region": "Loire", "subregion": "Touraine", "level": "regional", "lat": 47.7, "lon": 0.32},
    "jasnieres": {"region": "Loire", "subregion": "Touraine", "level": "village", "lat": 47.79, "lon": 0.31},
    "coteaux du vendômois": {"region": "Loire", "subregion": "Touraine", "level": "regional", "lat": 47.79, "lon": 1.07},
    # ── Rhône ───────────────────────────────────────────────────────────────
    "cotes du rhone": {"region": "Rhône", "subregion": "Côtes du Rhône", "level": "regional", "lat": 44.4, "lon": 4.9},
    "cotes du rhone villages": {"region": "Rhône", "subregion": "Côtes du Rhône", "level": "regional", "lat": 44.3, "lon": 4.95},
    "cote rotie": {"region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "level": "village", "lat": 45.49, "lon": 4.78},
    "condrieu": {"region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "level": "village", "lat": 45.47, "lon": 4.77},
    "chateau grillet": {"region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "level": "iconic", "lat": 45.46, "lon": 4.77},
    "saint joseph": {"region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "level": "village", "lat": 45.15, "lon": 4.77},
    "crozes hermitage": {"region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "level": "village", "lat": 45.09, "lon": 4.85},
    "hermitage": {"region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "level": "village", "lat": 45.08, "lon": 4.84},
    "cornas": {"region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "level": "village", "lat": 44.97, "lon": 4.84},
    "saint peray": {"region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "level": "village", "lat": 44.95, "lon": 4.84},
    "chateauneuf du pape": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "village", "lat": 44.06, "lon": 4.83},
    "gigondas": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "village", "lat": 44.18, "lon": 5.0},
    "vacqueyras": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "village", "lat": 44.16, "lon": 5.0},
    "beaumes de venise": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "village", "lat": 44.12, "lon": 5.03},
    "rasteau": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "village", "lat": 44.22, "lon": 4.97},
    "lirac": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "village", "lat": 43.97, "lon": 4.7},
    "tavel": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "village", "lat": 43.99, "lon": 4.71},
    "muscat de beaumes de venise": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "village", "lat": 44.12, "lon": 5.03},
    "luberon": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "regional", "lat": 43.77, "lon": 5.36},
    "ventoux": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "regional", "lat": 44.07, "lon": 5.27},
    "grignan les adhemar": {"region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "level": "regional", "lat": 44.38, "lon": 4.9},
    "vinsobres": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "village", "lat": 44.32, "lon": 5.02},
    "cairanne": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "village", "lat": 44.23, "lon": 4.94},
    "roaix": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "village", "lat": 44.25, "lon": 5.0},
    "seguret": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "village", "lat": 44.2, "lon": 5.0},
    "sablet": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "village", "lat": 44.19, "lon": 5.0},
    "plan de dieu": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "village", "lat": 44.15, "lon": 4.97},
    "massif d uchaux": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "village", "lat": 44.22, "lon": 4.77},
    "laudun": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "village", "lat": 44.08, "lon": 4.66},
    "saint gervais": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "village", "lat": 44.15, "lon": 4.75},
    "chusclan": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "village", "lat": 44.11, "lon": 4.7},
    "signargues": {"region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "level": "village", "lat": 43.97, "lon": 4.66},
    # ── Alsace ──────────────────────────────────────────────────────────────
    "alsace": {"region": "Alsace", "subregion": "Alsace", "level": "regional", "lat": 48.32, "lon": 7.44},
    "alsace grand cru": {"region": "Alsace", "subregion": "Alsace", "level": "grand_cru", "lat": 48.1, "lon": 7.3},
    "cremant d alsace": {"region": "Alsace", "subregion": "Alsace", "level": "regional", "lat": 48.2, "lon": 7.35},
    "moselle": {"region": "Alsace", "subregion": "Moselle", "level": "regional", "lat": 49.12, "lon": 6.17},
    # ── Languedoc-Roussillon ────────────────────────────────────────────────
    "languedoc": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "regional", "lat": 43.6, "lon": 3.87},
    "faugeres": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "village", "lat": 43.63, "lon": 3.27},
    "saint chinian": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "village", "lat": 43.45, "lon": 2.93},
    "picpoul de pinet": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "village", "lat": 43.41, "lon": 3.56},
    "minervois": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "village", "lat": 43.35, "lon": 2.72},
    "minervois la liviniere": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "village", "lat": 43.37, "lon": 2.7},
    "corbieres": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "village", "lat": 42.97, "lon": 2.7},
    "corbieres boutenac": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "village", "lat": 43.1, "lon": 2.67},
    "fitou": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "village", "lat": 42.87, "lon": 2.95},
    "la clape": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "village", "lat": 43.15, "lon": 3.18},
    "terrasses du larzac": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "village", "lat": 43.72, "lon": 3.5},
    "pic saint loup": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "village", "lat": 43.74, "lon": 3.8},
    "picpoul": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "regional", "lat": 43.41, "lon": 3.56},
    "banyuls": {"region": "Languedoc-Roussillon", "subregion": "Roussillon", "level": "village", "lat": 42.48, "lon": 3.13},
    "banyuls grand cru": {"region": "Languedoc-Roussillon", "subregion": "Roussillon", "level": "grand_cru", "lat": 42.48, "lon": 3.13},
    "rivesaltes": {"region": "Languedoc-Roussillon", "subregion": "Roussillon", "level": "regional", "lat": 42.77, "lon": 2.87},
    "muscat de rivesaltes": {"region": "Languedoc-Roussillon", "subregion": "Roussillon", "level": "regional", "lat": 42.77, "lon": 2.87},
    "maury": {"region": "Languedoc-Roussillon", "subregion": "Roussillon", "level": "village", "lat": 42.81, "lon": 2.67},
    "maury sec": {"region": "Languedoc-Roussillon", "subregion": "Roussillon", "level": "village", "lat": 42.81, "lon": 2.67},
    "cotes du roussillon": {"region": "Languedoc-Roussillon", "subregion": "Roussillon", "level": "regional", "lat": 42.7, "lon": 2.9},
    "cotes du roussillon villages": {"region": "Languedoc-Roussillon", "subregion": "Roussillon", "level": "regional", "lat": 42.72, "lon": 2.75},
    "collioure": {"region": "Languedoc-Roussillon", "subregion": "Roussillon", "level": "village", "lat": 42.52, "lon": 3.08},
    "muscat de lunel": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "village", "lat": 43.68, "lon": 4.13},
    "muscat de mireval": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "village", "lat": 43.49, "lon": 3.82},
    "muscat de frontignan": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "village", "lat": 43.45, "lon": 3.75},
    "muscat de saint jean de minervois": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "village", "lat": 43.42, "lon": 2.8},
    "blanquette de limoux": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "regional", "lat": 43.05, "lon": 2.17},
    "cremant de limoux": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "regional", "lat": 43.05, "lon": 2.17},
    "limoux": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "regional", "lat": 43.05, "lon": 2.17},
    "cabrieres": {"region": "Languedoc-Roussillon", "subregion": "Languedoc", "level": "village", "lat": 43.62, "lon": 3.38},
    # ── Provence ────────────────────────────────────────────────────────────
    "coteaux d aix en provence": {"region": "Provence", "subregion": "Provence", "level": "regional", "lat": 43.53, "lon": 5.43},
    "cotes de provence": {"region": "Provence", "subregion": "Provence", "level": "regional", "lat": 43.5, "lon": 6.2},
    "cotes de provence sainte victoire": {"region": "Provence", "subregion": "Provence", "level": "village", "lat": 43.55, "lon": 5.6},
    "cotes de provence la londe": {"region": "Provence", "subregion": "Provence", "level": "village", "lat": 43.13, "lon": 6.23},
    "cotes de provence pierrefeu": {"region": "Provence", "subregion": "Provence", "level": "village", "lat": 43.2, "lon": 6.15},
    "cotes de provence frejus": {"region": "Provence", "subregion": "Provence", "level": "village", "lat": 43.43, "lon": 6.72},
    "bandol": {"region": "Provence", "subregion": "Provence", "level": "village", "lat": 43.14, "lon": 5.75},
    "cassis": {"region": "Provence", "subregion": "Provence", "level": "village", "lat": 43.21, "lon": 5.54},
    "bellet": {"region": "Provence", "subregion": "Provence", "level": "village", "lat": 43.76, "lon": 7.22},
    "palette": {"region": "Provence", "subregion": "Provence", "level": "village", "lat": 43.54, "lon": 5.51},
    "les baux de provence": {"region": "Provence", "subregion": "Provence", "level": "village", "lat": 43.74, "lon": 4.8},
    "pierrevert": {"region": "Provence", "subregion": "Provence", "level": "regional", "lat": 43.82, "lon": 5.73},
    "coteaux varois en provence": {"region": "Provence", "subregion": "Provence", "level": "regional", "lat": 43.5, "lon": 5.95},
    # ── Beaujolais ──────────────────────────────────────────────────────────
    "beaujolais": {"region": "Beaujolais", "subregion": "Beaujolais", "level": "regional", "lat": 46.15, "lon": 4.72},
    "beaujolais villages": {"region": "Beaujolais", "subregion": "Beaujolais", "level": "regional", "lat": 46.1, "lon": 4.65},
    "moulin a vent": {"region": "Beaujolais", "subregion": "Beaujolais", "level": "village", "lat": 46.22, "lon": 4.68},
    "fleurie": {"region": "Beaujolais", "subregion": "Beaujolais", "level": "village", "lat": 46.19, "lon": 4.7},
    "morgon": {"region": "Beaujolais", "subregion": "Beaujolais", "level": "village", "lat": 46.15, "lon": 4.67},
    "brouilly": {"region": "Beaujolais", "subregion": "Beaujolais", "level": "village", "lat": 46.1, "lon": 4.67},
    "cote de brouilly": {"region": "Beaujolais", "subregion": "Beaujolais", "level": "village", "lat": 46.1, "lon": 4.67},
    "chenas": {"region": "Beaujolais", "subregion": "Beaujolais", "level": "village", "lat": 46.22, "lon": 4.73},
    "chiroubles": {"region": "Beaujolais", "subregion": "Beaujolais", "level": "village", "lat": 46.17, "lon": 4.72},
    "julienas": {"region": "Beaujolais", "subregion": "Beaujolais", "level": "village", "lat": 46.25, "lon": 4.71},
    "regnie": {"region": "Beaujolais", "subregion": "Beaujolais", "level": "village", "lat": 46.14, "lon": 4.7},
    "saint amour": {"region": "Beaujolais", "subregion": "Beaujolais", "level": "village", "lat": 46.27, "lon": 4.7},
    # ── Sud-Ouest ───────────────────────────────────────────────────────────
    "cahors": {"region": "Sud-Ouest", "subregion": "Sud-Ouest", "level": "village", "lat": 44.45, "lon": 1.44},
    "bergerac": {"region": "Sud-Ouest", "subregion": "Bergerac", "level": "regional", "lat": 44.85, "lon": 0.48},
    "monbazillac": {"region": "Sud-Ouest", "subregion": "Bergerac", "level": "village", "lat": 44.78, "lon": 0.49},
    "montravel": {"region": "Sud-Ouest", "subregion": "Bergerac", "level": "village", "lat": 44.84, "lon": 0.05},
    "cotes de bergerac": {"region": "Sud-Ouest", "subregion": "Bergerac", "level": "regional", "lat": 44.85, "lon": 0.48},
    "pecharmant": {"region": "Sud-Ouest", "subregion": "Bergerac", "level": "village", "lat": 44.88, "lon": 0.55},
    "saussignac": {"region": "Sud-Ouest", "subregion": "Bergerac", "level": "village", "lat": 44.79, "lon": 0.39},
    "madiran": {"region": "Sud-Ouest", "subregion": "Gascogne", "level": "village", "lat": 43.62, "lon": -0.07},
    "pacherenc du vic bilh": {"region": "Sud-Ouest", "subregion": "Gascogne", "level": "village", "lat": 43.62, "lon": -0.07},
    "irouleguy": {"region": "Sud-Ouest", "subregion": "Pays Basque", "level": "village", "lat": 43.27, "lon": -1.32},
    "jurancon": {"region": "Sud-Ouest", "subregion": "Béarn", "level": "village", "lat": 43.28, "lon": -0.37},
    "jurancon sec": {"region": "Sud-Ouest", "subregion": "Béarn", "level": "village", "lat": 43.28, "lon": -0.37},
    "bearn": {"region": "Sud-Ouest", "subregion": "Béarn", "level": "regional", "lat": 43.28, "lon": -0.45},
    "gaillac": {"region": "Sud-Ouest", "subregion": "Gaillac", "level": "regional", "lat": 43.9, "lon": 1.9},
    "gaillac premieres cotes": {"region": "Sud-Ouest", "subregion": "Gaillac", "level": "village", "lat": 43.9, "lon": 1.9},
    "fronton": {"region": "Sud-Ouest", "subregion": "Gaillac", "level": "regional", "lat": 43.85, "lon": 1.36},
    "buzet": {"region": "Sud-Ouest", "subregion": "Agenais", "level": "regional", "lat": 44.27, "lon": 0.3},
    "marcillac": {"region": "Sud-Ouest", "subregion": "Aveyron", "level": "village", "lat": 44.47, "lon": 2.47},
    "entraygues le fel": {"region": "Sud-Ouest", "subregion": "Aveyron", "level": "village", "lat": 44.65, "lon": 2.56},
    "estaing": {"region": "Sud-Ouest", "subregion": "Aveyron", "level": "village", "lat": 44.54, "lon": 2.67},
    "lavilledieu": {"region": "Sud-Ouest", "subregion": "Aveyron", "level": "village", "lat": 44.33, "lon": 1.66},
    "brulhois": {"region": "Sud-Ouest", "subregion": "Agenais", "level": "regional", "lat": 44.1, "lon": 0.65},
    "cotes de millau": {"region": "Sud-Ouest", "subregion": "Aveyron", "level": "regional", "lat": 44.1, "lon": 3.07},
    "tursan": {"region": "Sud-Ouest", "subregion": "Gascogne", "level": "regional", "lat": 43.7, "lon": -0.63},
    "cotes du marmandais": {"region": "Sud-Ouest", "subregion": "Agenais", "level": "regional", "lat": 44.5, "lon": 0.15},
    "saint mont": {"region": "Sud-Ouest", "subregion": "Gascogne", "level": "regional", "lat": 43.74, "lon": -0.07},
    "côtes de gascogne": {"region": "Sud-Ouest", "subregion": "Gascogne", "level": "regional", "lat": 43.6, "lon": 0.15},
    # ── Jura ────────────────────────────────────────────────────────────────
    "arbois": {"region": "Jura", "subregion": "Jura", "level": "village", "lat": 46.9, "lon": 5.77},
    "arbois pupillin": {"region": "Jura", "subregion": "Jura", "level": "village", "lat": 46.89, "lon": 5.77},
    "cotes du jura": {"region": "Jura", "subregion": "Jura", "level": "regional", "lat": 46.75, "lon": 5.7},
    "chateau chalon": {"region": "Jura", "subregion": "Jura", "level": "village", "lat": 46.77, "lon": 5.66},
    "etoile": {"region": "Jura", "subregion": "Jura", "level": "village", "lat": 46.78, "lon": 5.65},
    "cremant du jura": {"region": "Jura", "subregion": "Jura", "level": "regional", "lat": 46.75, "lon": 5.7},
    "macvin du jura": {"region": "Jura", "subregion": "Jura", "level": "regional", "lat": 46.75, "lon": 5.7},
    # ── Savoie ──────────────────────────────────────────────────────────────
    "vin de savoie": {"region": "Savoie", "subregion": "Savoie", "level": "regional", "lat": 45.6, "lon": 6.15},
    "roussette de savoie": {"region": "Savoie", "subregion": "Savoie", "level": "regional", "lat": 45.6, "lon": 6.15},
    "cremant de savoie": {"region": "Savoie", "subregion": "Savoie", "level": "regional", "lat": 45.6, "lon": 6.15},
    "seyssel": {"region": "Savoie", "subregion": "Savoie", "level": "village", "lat": 45.95, "lon": 5.83},
    "bugey": {"region": "Savoie", "subregion": "Bugey", "level": "regional", "lat": 45.86, "lon": 5.5},
    "cerdon": {"region": "Savoie", "subregion": "Bugey", "level": "village", "lat": 46.08, "lon": 5.47},
    # ── Corse ───────────────────────────────────────────────────────────────
    "vin de corse": {"region": "Corse", "subregion": "Corse", "level": "regional", "lat": 42.04, "lon": 9.01},
    "ajaccio": {"region": "Corse", "subregion": "Corse", "level": "village", "lat": 41.93, "lon": 8.74},
    "patrimonio": {"region": "Corse", "subregion": "Corse", "level": "village", "lat": 42.66, "lon": 9.37},
    "muscat du cap corse": {"region": "Corse", "subregion": "Corse", "level": "regional", "lat": 43.0, "lon": 9.4},
}


def _compute_centroid(geometry: dict) -> tuple[float | None, float | None]:
    """Average centroid from a GeoJSON Geometry (Polygon or MultiPolygon)."""
    try:
        coords: list = []
        geo_type = geometry.get("type", "")
        if geo_type == "Polygon":
            coords = geometry["coordinates"][0]
        elif geo_type == "MultiPolygon":
            for poly in geometry["coordinates"]:
                coords.extend(poly[0])
        if not coords:
            return None, None
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        return round(sum(lats) / len(lats), 4), round(sum(lons) / len(lons), 4)
    except Exception:
        return None, None


def _get_or_create_source(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = 'INAO'"
    ).fetchone()
    if row:
        return row[0]
    conn.execute(
        """INSERT INTO dim_source
           (source_code, source_name, source_tier, country_code,
            base_url, license_class, cadence, enabled, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "INAO",
            "INAO — Registre national des AOC/AOP/IGP",
            "A_official",
            "FR",
            "https://www.inao.gouv.fr",
            "public_open_data",
            "annual",
            1,
            "Official INAO product registry + data.gouv.fr GeoJSON. Feeds dim_appellation only — never prices.",
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = 'INAO'"
    ).fetchone()
    return row[0]


def _fetch_inao_products(client: httpx.Client) -> list[dict]:
    """
    Fetch wine appellations from the INAO REST API.
    Returns list of dicts with at minimum:
        denomination, type_ig, code_ig
    Falls back to [] on any error (scraper will still run from taxonomy).
    """
    try:
        resp = client.get(
            _INAO_PRODUIT_URL,
            params={"type_produit": "Vins", "format": "json"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("produits", data.get("data", []))
    except Exception as exc:
        console.print(f"[yellow]INAO REST API unavailable ({exc}) — using taxonomy only[/yellow]")
        return []


def _fetch_geojson(client: httpx.Client) -> dict | None:
    """
    Download the INAO wine-AOC GeoJSON from data.gouv.fr.
    Returns parsed GeoJSON FeatureCollection or None on failure.
    """
    for url in [_DATAGOUV_GEOJSON_URL]:
        try:
            resp = client.get(url, timeout=60, follow_redirects=True)
            if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("application/"):
                return resp.json()
        except Exception:
            pass
    console.print("[yellow]data.gouv.fr GeoJSON unavailable — skipping geometry enrichment[/yellow]")
    return None


def _build_geo_index(geojson: dict | None) -> dict[str, dict]:
    """Build appellation_norm → {lat, lon, geo_polygon} from GeoJSON."""
    index: dict[str, dict] = {}
    if not geojson:
        return index
    features = geojson.get("features", [])
    for feat in features:
        props = feat.get("properties", {})
        name = (
            props.get("appellation")
            or props.get("denomination")
            or props.get("nom_ig")
            or props.get("libelle")
            or ""
        )
        if not name:
            continue
        norm = norm_text(name)
        geometry = feat.get("geometry") or {}
        lat, lon = _compute_centroid(geometry)
        index[norm] = {
            "lat": lat,
            "lon": lon,
            "geo_polygon": json.dumps(geometry) if geometry else None,
        }
    return index


class INAOScraper(BaseScraper):
    """
    Ingest French wine appellations from INAO open data into dim_appellation.

    - PATCH existing rows: fill inao_code + lat/lon + geo_polygon.
    - INSERT new appellations from the built-in _TAXONOMY that are not yet
      present in the DB.  INAO API results also contribute new rows.
    """

    source_code = "inao"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        source_key = _get_or_create_source(self.conn)
        batch_id = self.batch_id or (
            f"inao-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        )
        result = ScrapeResult(batch_id=batch_id)

        console.rule("[bold cyan]INAO Appellation Ingestor[/bold cyan]")

        with httpx.Client(
            headers={"Accept": "application/json, */*"},
            follow_redirects=True,
            timeout=30,
        ) as client:
            inao_products = _fetch_inao_products(client)
            console.print(f"  INAO API: {len(inao_products)} wine products")
            geojson = _fetch_geojson(client)
            geo_index = _build_geo_index(geojson)
            console.print(f"  GeoJSON: {len(geo_index)} features indexed")

        # ── Build the master candidate list ──────────────────────────────────
        # Each candidate: {appellation_name, appellation_norm, inao_code,
        #                  region, subregion, level, lat, lon, geo_polygon}
        candidates: dict[str, dict] = {}  # keyed by appellation_norm

        # 1. Built-in taxonomy (always available)
        for norm, meta in _TAXONOMY.items():
            candidates[norm] = {
                "appellation_name": norm.title(),  # pretty-print fallback
                "appellation_norm": norm,
                "inao_code": None,
                "region": meta["region"],
                "subregion": meta.get("subregion"),
                "level": meta["level"],
                "lat": meta.get("lat"),
                "lon": meta.get("lon"),
                "geo_polygon": None,
            }

        # 2. INAO API results — override name and code; keep taxonomy meta
        for prod in inao_products:
            name = prod.get("denomination") or prod.get("nom_ig") or ""
            if not name:
                continue
            norm = norm_text(name)
            code = prod.get("code_ig") or prod.get("code") or None
            if norm not in candidates:
                # Unknown to taxonomy — insert as generic "France" regional
                candidates[norm] = {
                    "appellation_name": name,
                    "appellation_norm": norm,
                    "inao_code": code,
                    "region": "France",
                    "subregion": None,
                    "level": "regional",
                    "lat": None,
                    "lon": None,
                    "geo_polygon": None,
                }
            else:
                candidates[norm]["appellation_name"] = name  # use official spelling
                if code:
                    candidates[norm]["inao_code"] = code

        # 3. GeoJSON geometry enrichment
        for norm, geo in geo_index.items():
            if norm in candidates:
                if geo.get("lat"):
                    candidates[norm]["lat"] = geo["lat"]
                if geo.get("lon"):
                    candidates[norm]["lon"] = geo["lon"]
                if geo.get("geo_polygon"):
                    candidates[norm]["geo_polygon"] = geo["geo_polygon"]

        result.rows_fetched = len(candidates)
        console.print(f"  Total candidates: {result.rows_fetched}")

        # ── Upsert into dim_appellation ──────────────────────────────────────
        processed = 0
        for norm, cand in candidates.items():
            if limit is not None and processed >= limit:
                break

            existing = self.conn.execute(
                "SELECT appellation_key, inao_code, latitude, longitude, geo_polygon "
                "FROM dim_appellation WHERE country_code='FR' AND appellation_norm=?",
                (norm,),
            ).fetchone()

            try:
                if existing:
                    # PATCH: only fill in missing/null fields
                    updates: list[str] = []
                    params: list = []
                    if existing["inao_code"] is None and cand["inao_code"]:
                        updates.append("inao_code = ?")
                        params.append(cand["inao_code"])
                    if existing["latitude"] is None and cand["lat"]:
                        updates.append("latitude = ?")
                        params.append(cand["lat"])
                    if existing["longitude"] is None and cand["lon"]:
                        updates.append("longitude = ?")
                        params.append(cand["lon"])
                    if existing["geo_polygon"] is None and cand["geo_polygon"]:
                        updates.append("geo_polygon = ?")
                        params.append(cand["geo_polygon"])
                    if updates:
                        params.append(existing["appellation_key"])
                        self.conn.execute(
                            f"UPDATE dim_appellation SET {', '.join(updates)} WHERE appellation_key=?",
                            params,
                        )
                        result.rows_inserted += 1  # count as enrichment
                    else:
                        result.rows_skipped_unchanged += 1
                else:
                    # INSERT new appellation
                    self.conn.execute(
                        """INSERT INTO dim_appellation
                           (country_code, region, subregion, appellation_name,
                            appellation_norm, level, inao_code, latitude, longitude,
                            geo_polygon)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            "FR",
                            cand["region"],
                            cand["subregion"],
                            cand["appellation_name"],
                            norm,
                            cand["level"],
                            cand["inao_code"],
                            cand["lat"],
                            cand["lon"],
                            cand["geo_polygon"],
                        ),
                    )
                    result.rows_inserted += 1

            except Exception as exc:
                write_dlq(
                    self.conn, source_key, batch_id,
                    "validation_error", str(exc), cand,
                    source_record_id=norm,
                )
                result.rows_dlq += 1

            processed += 1

        self.conn.commit()

        # ── ops_batch_log ────────────────────────────────────────────────────
        self.conn.execute(
            """INSERT OR REPLACE INTO ops_batch_log
               (batch_id, source_key, started_at, finished_at,
                status, rows_fetched, rows_inserted, rows_updated,
                rows_dlq, rows_skipped_unchanged, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                batch_id, source_key,
                int(time.time()), int(time.time()),
                "success" if result.rows_dlq == 0 else "partial",
                result.rows_fetched,
                result.rows_inserted,
                0,
                result.rows_dlq,
                result.rows_skipped_unchanged,
                f"inao_api_count={len(inao_products)} geojson_features={len(geo_index)}",
            ),
        )
        self.conn.commit()

        console.print(
            f"[green]INAO done[/green] — "
            f"enriched/inserted: [bold]{result.rows_inserted}[/bold]  "
            f"unchanged: {result.rows_skipped_unchanged}  "
            f"dlq: {result.rows_dlq}"
        )
        return result
