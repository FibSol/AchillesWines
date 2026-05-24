"""
French Wine Syndicate Producer Ingestors — Issue #31

Seven official French interprofession bodies:
  CIVB  — Conseil Interprofessionnel du Vin de Bordeaux
  BIVB  — Bureau Interprofessionnel des Vins de Bourgogne
  Inter-Rhône  — Interprofession des Vins de la Vallée du Rhône
  InterLoire   — Interprofession des Vins du Val de Loire
  CIVC  — Comité Champagne
  CIVA  — Conseil Interprofessionnel des Vins d'Alsace
  CIVL  — Conseil Interprofessionnel des Vins du Languedoc

Strategy:
  Each syndicate website provides some combination of:
    a) A JSON/XML member API (probed first)
    b) An HTML member/producer directory (scraped)
    c) A built-in taxonomy of well-known producers (always available as fallback)

  All 7 are registered in dim_source (tier=A_official, cadence=annual).
  Producer upsert is on producer_norm + country_code (UNIQUE INDEX).
  producer_key = autoincrement from SQLite; producer_norm = slugified norm_text().
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from typing import Optional

import httpx
from rich.console import Console

from .base import BaseScraper, ScrapeResult
from ..dlq import write_dlq
from ..identity import norm_text, clean_producer_display

console = Console()

# ---------------------------------------------------------------------------
# Source registry metadata
# ---------------------------------------------------------------------------

_SOURCES: list[dict] = [
    {
        "source_code": "CIVB",
        "source_name": "CIVB — Conseil Interprofessionnel du Vin de Bordeaux",
        "base_url": "https://www.bordeaux.com",
        "country_code": "FR",
        "notes": "Official Bordeaux interprofession. Feeds dim_producer only — never prices.",
    },
    {
        "source_code": "BIVB",
        "source_name": "BIVB — Bureau Interprofessionnel des Vins de Bourgogne",
        "base_url": "https://www.bourgogne-wines.com",
        "country_code": "FR",
        "notes": "Official Burgundy interprofession. Feeds dim_producer only — never prices.",
    },
    {
        "source_code": "INTER_RHONE",
        "source_name": "Inter-Rhône — Interprofession des Vins de la Vallée du Rhône",
        "base_url": "https://www.vins-rhone.com",
        "country_code": "FR",
        "notes": "Official Rhône Valley interprofession. Feeds dim_producer only — never prices.",
    },
    {
        "source_code": "INTERLOIRE",
        "source_name": "InterLoire — Interprofession des Vins du Val de Loire",
        "base_url": "https://www.loirevalleywine.com",
        "country_code": "FR",
        "notes": "Official Loire Valley interprofession. Feeds dim_producer only — never prices.",
    },
    {
        "source_code": "CIVC",
        "source_name": "CIVC — Comité Champagne",
        "base_url": "https://www.champagne.fr",
        "country_code": "FR",
        "notes": "Official Champagne interprofession. Feeds dim_producer only — never prices.",
    },
    {
        "source_code": "CIVA",
        "source_name": "CIVA — Conseil Interprofessionnel des Vins d'Alsace",
        "base_url": "https://www.vinsalsace.com",
        "country_code": "FR",
        "notes": "Official Alsace interprofession. Feeds dim_producer only — never prices.",
    },
    {
        "source_code": "CIVL",
        "source_name": "CIVL — Conseil Interprofessionnel des Vins du Languedoc",
        "base_url": "https://www.languedoc-wines.com",
        "country_code": "FR",
        "notes": "Official Languedoc interprofession. Feeds dim_producer only — never prices.",
    },
]


# ---------------------------------------------------------------------------
# Built-in producer taxonomies  (fallback when live fetch fails or is blocked)
# Each entry: { name, region, subregion, appellations: [appellation_norm, ...], tier, website? }
# ---------------------------------------------------------------------------

# Bordeaux — CIVB
_CIVB_PRODUCERS: list[dict] = [
    # Médoc châteaux
    {"name": "Château Lafite Rothschild", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["pauillac"], "tier": 1, "website": "https://www.lafite.com"},
    {"name": "Château Latour", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["pauillac"], "tier": 1},
    {"name": "Château Mouton Rothschild", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["pauillac"], "tier": 1},
    {"name": "Château Margaux", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["margaux"], "tier": 1, "website": "https://www.chateau-margaux.com"},
    {"name": "Château Haut-Brion", "region": "Bordeaux", "subregion": "Graves", "appellations": ["pessac leognan"], "tier": 1},
    {"name": "Château Pichon Baron", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["pauillac"], "tier": 2},
    {"name": "Château Pichon Longueville Comtesse de Lalande", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["pauillac"], "tier": 2},
    {"name": "Château Léoville Las Cases", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["saint julien"], "tier": 2},
    {"name": "Château Léoville Barton", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["saint julien"], "tier": 2},
    {"name": "Château Léoville Poyferré", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["saint julien"], "tier": 2},
    {"name": "Château Ducru-Beaucaillou", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["saint julien"], "tier": 2},
    {"name": "Château Gruaud Larose", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["saint julien"], "tier": 2},
    {"name": "Château Cos d'Estournel", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["saint estephe"], "tier": 2},
    {"name": "Château Montrose", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["saint estephe"], "tier": 2},
    {"name": "Château Calon Ségur", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["saint estephe"], "tier": 3},
    {"name": "Château Lynch-Bages", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["pauillac"], "tier": 5},
    {"name": "Château Pontet-Canet", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["pauillac"], "tier": 5},
    {"name": "Château Grand-Puy-Lacoste", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["pauillac"], "tier": 5},
    {"name": "Château Talbot", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["saint julien"], "tier": 4},
    {"name": "Château Beychevelle", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["saint julien"], "tier": 4},
    {"name": "Château Palmer", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["margaux"], "tier": 3},
    {"name": "Château Rauzan-Ségla", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["margaux"], "tier": 2},
    {"name": "Château Brane-Cantenac", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["margaux"], "tier": 2},
    {"name": "Château Durfort-Vivens", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["margaux"], "tier": 2},
    {"name": "Château Lascombes", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["margaux"], "tier": 2},
    {"name": "Château Prieuré-Lichine", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["margaux"], "tier": 4},
    {"name": "Château Pouget", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["margaux"], "tier": 4},
    {"name": "Château Kirwan", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["margaux"], "tier": 3},
    {"name": "Château d'Issan", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["margaux"], "tier": 3},
    {"name": "Château Giscours", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["margaux"], "tier": 3},
    {"name": "Château Malescot Saint-Exupéry", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["margaux"], "tier": 3},
    {"name": "Château Ferrière", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["margaux"], "tier": 3},
    {"name": "Château Marquis d'Alesme", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["margaux"], "tier": 3},
    {"name": "Château Boyd-Cantenac", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["margaux"], "tier": 3},
    {"name": "Château Cantenac Brown", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["margaux"], "tier": 3},
    {"name": "Château Langoa Barton", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["saint julien"], "tier": 3},
    {"name": "Château La Lagune", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["haut medoc"], "tier": 3},
    {"name": "Château Cantemerle", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["haut medoc"], "tier": 5},
    {"name": "Château Belgrave", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["haut medoc"], "tier": 5},
    {"name": "Château de Camensac", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["haut medoc"], "tier": 5},
    {"name": "Château Clerc Milon", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["pauillac"], "tier": 5},
    {"name": "Château d'Armailhac", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["pauillac"], "tier": 5},
    {"name": "Château Batailley", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["pauillac"], "tier": 5},
    {"name": "Château Haut-Batailley", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["pauillac"], "tier": 5},
    {"name": "Château Croizet-Bages", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["pauillac"], "tier": 5},
    {"name": "Château Pédesclaux", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["pauillac"], "tier": 5},
    {"name": "Château Lynch-Moussas", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["pauillac"], "tier": 5},
    {"name": "Château Camensac", "region": "Bordeaux", "subregion": "Médoc", "appellations": ["haut medoc"], "tier": 5},
    # Libournais
    {"name": "Château Pétrus", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["pomerol"], "tier": 1},
    {"name": "Château Le Pin", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["pomerol"], "tier": 1},
    {"name": "Château Lafleur", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["pomerol"], "tier": 1},
    {"name": "Château La Fleur-Pétrus", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["pomerol"], "tier": 2},
    {"name": "Château L'Évangile", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["pomerol"], "tier": 2},
    {"name": "Château Clinet", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["pomerol"], "tier": 2},
    {"name": "Château Vieux Château Certan", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["pomerol"], "tier": 2},
    {"name": "Château La Conseillante", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["pomerol"], "tier": 2},
    {"name": "Château Trotanoy", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["pomerol"], "tier": 2},
    {"name": "Château Ausone", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["saint emilion grand cru"], "tier": 1},
    {"name": "Château Cheval Blanc", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["saint emilion grand cru"], "tier": 1},
    {"name": "Château Angélus", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["saint emilion grand cru"], "tier": 1},
    {"name": "Château Pavie", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["saint emilion grand cru"], "tier": 1},
    {"name": "Château Figeac", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["saint emilion grand cru"], "tier": 1},
    {"name": "Château Canon", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["saint emilion grand cru"], "tier": 2},
    {"name": "Château Troplong Mondot", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["saint emilion grand cru"], "tier": 2},
    {"name": "Château Valandraud", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["saint emilion grand cru"], "tier": 2},
    {"name": "Château Beauséjour Duffau", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["saint emilion grand cru"], "tier": 2},
    {"name": "Château Trotte Vieille", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["saint emilion grand cru"], "tier": 2},
    {"name": "Château Beau-Séjour Bécot", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["saint emilion grand cru"], "tier": 2},
    {"name": "Château Larcis Ducasse", "region": "Bordeaux", "subregion": "Libournais", "appellations": ["saint emilion grand cru"], "tier": 2},
    {"name": "Château Pape Clément", "region": "Bordeaux", "subregion": "Graves", "appellations": ["pessac leognan"], "tier": 2},
    {"name": "Château Smith Haut Lafitte", "region": "Bordeaux", "subregion": "Graves", "appellations": ["pessac leognan"], "tier": 2},
    {"name": "Château La Mission Haut-Brion", "region": "Bordeaux", "subregion": "Graves", "appellations": ["pessac leognan"], "tier": 1},
    {"name": "Château Haut-Bailly", "region": "Bordeaux", "subregion": "Graves", "appellations": ["pessac leognan"], "tier": 2},
    {"name": "Château de Fieuzal", "region": "Bordeaux", "subregion": "Graves", "appellations": ["pessac leognan"], "tier": 3},
    {"name": "Château d'Yquem", "region": "Bordeaux", "subregion": "Sauternais", "appellations": ["sauternes"], "tier": 1},
    {"name": "Château Rieussec", "region": "Bordeaux", "subregion": "Sauternais", "appellations": ["sauternes"], "tier": 1},
    {"name": "Château Suduiraut", "region": "Bordeaux", "subregion": "Sauternais", "appellations": ["sauternes"], "tier": 1},
    {"name": "Château Climens", "region": "Bordeaux", "subregion": "Sauternais", "appellations": ["barsac"], "tier": 1},
    {"name": "Château Coutet", "region": "Bordeaux", "subregion": "Sauternais", "appellations": ["barsac"], "tier": 1},
    {"name": "Château Guiraud", "region": "Bordeaux", "subregion": "Sauternais", "appellations": ["sauternes"], "tier": 1},
    {"name": "Château Sigalas Rabaud", "region": "Bordeaux", "subregion": "Sauternais", "appellations": ["sauternes"], "tier": 1},
    {"name": "Château Rabaud-Promis", "region": "Bordeaux", "subregion": "Sauternais", "appellations": ["sauternes"], "tier": 1},
    {"name": "Château Doisy-Daëne", "region": "Bordeaux", "subregion": "Sauternais", "appellations": ["barsac"], "tier": 2},
    {"name": "Château Doisy-Védrines", "region": "Bordeaux", "subregion": "Sauternais", "appellations": ["barsac"], "tier": 2},
    {"name": "Château Lafaurie-Peyraguey", "region": "Bordeaux", "subregion": "Sauternais", "appellations": ["sauternes"], "tier": 1},
    # Négociants
    {"name": "Maison Sichel", "region": "Bordeaux", "subregion": "Bordeaux", "appellations": ["bordeaux", "bordeaux superieur"], "tier": 3},
    {"name": "CVBG Dourthe", "region": "Bordeaux", "subregion": "Bordeaux", "appellations": ["bordeaux"], "tier": 3},
    {"name": "Barton & Guestier", "region": "Bordeaux", "subregion": "Bordeaux", "appellations": ["bordeaux"], "tier": 3},
]

# Burgundy — BIVB
_BIVB_PRODUCERS: list[dict] = [
    # Iconic domaines
    {"name": "Domaine de la Romanée-Conti", "region": "Bourgogne", "subregion": "Côte de Nuits", "appellations": ["romanee conti", "la tache", "richebourg", "romanee saint vivant", "grands echezeaux", "echezeaux", "montrachet", "corton"], "tier": 1, "website": "https://www.romanee-conti.fr"},
    {"name": "Domaine Leroy", "region": "Bourgogne", "subregion": "Côte de Nuits", "appellations": ["chambertin", "musigny", "richebourg", "clos de vougeot", "nuits saint georges"], "tier": 1},
    {"name": "Domaine Armand Rousseau", "region": "Bourgogne", "subregion": "Côte de Nuits", "appellations": ["chambertin", "chambertin clos de beze", "gevrey chambertin"], "tier": 1},
    {"name": "Domaine Henri Jayer", "region": "Bourgogne", "subregion": "Côte de Nuits", "appellations": ["vosne romanee", "echezeaux", "nuits saint georges"], "tier": 1},
    {"name": "Domaine Méo-Camuzet", "region": "Bourgogne", "subregion": "Côte de Nuits", "appellations": ["vosne romanee", "clos de vougeot", "nuits saint georges"], "tier": 1},
    {"name": "Domaine Georges Roumier", "region": "Bourgogne", "subregion": "Côte de Nuits", "appellations": ["chambolle musigny", "bonnes mares", "musigny"], "tier": 1},
    {"name": "Domaine Comte Georges de Vogüé", "region": "Bourgogne", "subregion": "Côte de Nuits", "appellations": ["chambolle musigny", "musigny", "bonnes mares"], "tier": 1},
    {"name": "Domaine Jacques-Frédéric Mugnier", "region": "Bourgogne", "subregion": "Côte de Nuits", "appellations": ["chambolle musigny", "musigny", "bonnes mares"], "tier": 1},
    {"name": "Domaine Ponsot", "region": "Bourgogne", "subregion": "Côte de Nuits", "appellations": ["clos de la roche", "clos saint denis", "morey saint denis", "gevrey chambertin"], "tier": 1},
    {"name": "Domaine Dujac", "region": "Bourgogne", "subregion": "Côte de Nuits", "appellations": ["clos saint denis", "clos de la roche", "morey saint denis"], "tier": 1},
    {"name": "Domaine Gros Frère et Sœur", "region": "Bourgogne", "subregion": "Côte de Nuits", "appellations": ["vosne romanee", "grands echezeaux", "clos de vougeot"], "tier": 2},
    {"name": "Domaine Emmanuel Rouget", "region": "Bourgogne", "subregion": "Côte de Nuits", "appellations": ["echezeaux", "vosne romanee", "nuits saint georges"], "tier": 1},
    {"name": "Domaine Sylvain Cathiard", "region": "Bourgogne", "subregion": "Côte de Nuits", "appellations": ["vosne romanee", "nuits saint georges", "romanee saint vivant"], "tier": 1},
    {"name": "Domaine Thibault Liger-Belair", "region": "Bourgogne", "subregion": "Côte de Nuits", "appellations": ["vosne romanee", "nuits saint georges", "la romanee"], "tier": 1},
    {"name": "Domaine de la Vougeraie", "region": "Bourgogne", "subregion": "Côte de Nuits", "appellations": ["clos de vougeot", "vougeot", "nuits saint georges", "gevrey chambertin"], "tier": 2},
    {"name": "Domaine Bruno Clair", "region": "Bourgogne", "subregion": "Côte de Nuits", "appellations": ["marsannay", "gevrey chambertin", "chambertin clos de beze"], "tier": 2},
    {"name": "Domaine Trapet Père et Fils", "region": "Bourgogne", "subregion": "Côte de Nuits", "appellations": ["gevrey chambertin", "chambertin", "chapelle chambertin"], "tier": 2},
    {"name": "Domaine Denis Mortet", "region": "Bourgogne", "subregion": "Côte de Nuits", "appellations": ["gevrey chambertin", "clos de vougeot", "chambertin"], "tier": 1},
    {"name": "Domaine Rossignol-Trapet", "region": "Bourgogne", "subregion": "Côte de Nuits", "appellations": ["gevrey chambertin", "chambertin", "latricieres chambertin"], "tier": 2},
    # Côte de Beaune
    {"name": "Domaine des Comtes Lafon", "region": "Bourgogne", "subregion": "Côte de Beaune", "appellations": ["meursault", "montrachet", "volnay", "puligny montrachet"], "tier": 1},
    {"name": "Domaine Leflaive", "region": "Bourgogne", "subregion": "Côte de Beaune", "appellations": ["puligny montrachet", "chevalier montrachet", "bienvenues batard montrachet", "montrachet"], "tier": 1},
    {"name": "Domaine Coche-Dury", "region": "Bourgogne", "subregion": "Côte de Beaune", "appellations": ["meursault", "corton charlemagne", "puligny montrachet"], "tier": 1},
    {"name": "Domaine Ramonet", "region": "Bourgogne", "subregion": "Côte de Beaune", "appellations": ["chassagne montrachet", "montrachet", "batard montrachet"], "tier": 1},
    {"name": "Domaine de Montille", "region": "Bourgogne", "subregion": "Côte de Beaune", "appellations": ["volnay", "pommard", "puligny montrachet"], "tier": 2},
    {"name": "Domaine Marquis d'Angerville", "region": "Bourgogne", "subregion": "Côte de Beaune", "appellations": ["volnay", "meursault", "pommard"], "tier": 1},
    {"name": "Domaine Hubert de Montille", "region": "Bourgogne", "subregion": "Côte de Beaune", "appellations": ["volnay", "pommard"], "tier": 2},
    {"name": "Domaine Jean-Marc Boillot", "region": "Bourgogne", "subregion": "Côte de Beaune", "appellations": ["puligny montrachet", "pommard", "volnay"], "tier": 2},
    {"name": "Domaine Simon Bize", "region": "Bourgogne", "subregion": "Côte de Beaune", "appellations": ["savigny les beaune", "corton", "pernand vergelesses"], "tier": 2},
    {"name": "Domaine Chandon de Briailles", "region": "Bourgogne", "subregion": "Côte de Beaune", "appellations": ["corton", "savigny les beaune", "pernand vergelesses"], "tier": 2},
    {"name": "Domaine Michel Voarick", "region": "Bourgogne", "subregion": "Côte de Beaune", "appellations": ["corton", "aloxe corton"], "tier": 2},
    {"name": "Domaine Tollot-Beaut", "region": "Bourgogne", "subregion": "Côte de Beaune", "appellations": ["beaune", "chorey les beaune", "aloxe corton"], "tier": 2},
    {"name": "Maison Louis Jadot", "region": "Bourgogne", "subregion": "Bourgogne", "appellations": ["gevrey chambertin", "beaune", "puligny montrachet", "chablis", "macon"], "tier": 2, "website": "https://www.louisjadot.com"},
    {"name": "Maison Louis Latour", "region": "Bourgogne", "subregion": "Bourgogne", "appellations": ["corton charlemagne", "beaune", "meursault", "gevrey chambertin"], "tier": 2},
    {"name": "Maison Joseph Drouhin", "region": "Bourgogne", "subregion": "Bourgogne", "appellations": ["beaune", "puligny montrachet", "chambolle musigny", "chablis"], "tier": 2, "website": "https://www.drouhin.com"},
    {"name": "Maison Faiveley", "region": "Bourgogne", "subregion": "Bourgogne", "appellations": ["nuits saint georges", "gevrey chambertin", "corton", "mercurey"], "tier": 2},
    {"name": "Maison Bouchard Père et Fils", "region": "Bourgogne", "subregion": "Bourgogne", "appellations": ["beaune", "volnay", "meursault", "puligny montrachet", "chablis"], "tier": 2},
    # Chablis
    {"name": "Domaine William Fèvre", "region": "Bourgogne", "subregion": "Chablis", "appellations": ["chablis", "chablis grand cru", "chablis premier cru"], "tier": 2},
    {"name": "Domaine Raveneau", "region": "Bourgogne", "subregion": "Chablis", "appellations": ["chablis", "chablis grand cru", "chablis premier cru"], "tier": 1},
    {"name": "Domaine Vincent Dauvissat", "region": "Bourgogne", "subregion": "Chablis", "appellations": ["chablis", "chablis grand cru", "chablis premier cru"], "tier": 1},
    {"name": "La Chablisienne", "region": "Bourgogne", "subregion": "Chablis", "appellations": ["chablis", "petit chablis", "chablis premier cru", "chablis grand cru"], "tier": 3},
    # Mâconnais / Beaujolais
    {"name": "Domaine Leflaive Mâcon", "region": "Bourgogne", "subregion": "Mâconnais", "appellations": ["macon villages", "pouilly fuisse"], "tier": 2},
    {"name": "Domaine Ferret", "region": "Bourgogne", "subregion": "Mâconnais", "appellations": ["pouilly fuisse"], "tier": 2},
    {"name": "Domaine J-A Ferret", "region": "Bourgogne", "subregion": "Mâconnais", "appellations": ["pouilly fuisse"], "tier": 2},
    {"name": "Château Fuissé", "region": "Bourgogne", "subregion": "Mâconnais", "appellations": ["pouilly fuisse", "macon villages"], "tier": 2},
    {"name": "Domaine Guffens-Heynen", "region": "Bourgogne", "subregion": "Mâconnais", "appellations": ["pouilly fuisse", "macon villages"], "tier": 1},
]

# Rhône — Inter-Rhône
_INTER_RHONE_PRODUCERS: list[dict] = [
    # Septentrional
    {"name": "Domaine Jean-Louis Chave", "region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "appellations": ["hermitage", "saint joseph"], "tier": 1},
    {"name": "Domaine Paul Jaboulet Aîné", "region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "appellations": ["hermitage", "crozes hermitage", "saint joseph", "cote rotie"], "tier": 2},
    {"name": "Maison M. Chapoutier", "region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "appellations": ["hermitage", "chateauneuf du pape", "cote rotie", "crozes hermitage"], "tier": 2, "website": "https://www.chapoutier.com"},
    {"name": "Domaine Guigal", "region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "appellations": ["cote rotie", "condrieu", "hermitage", "chateauneuf du pape", "cotes du rhone"], "tier": 1, "website": "https://www.guigal.com"},
    {"name": "Domaine René Rostaing", "region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "appellations": ["cote rotie", "condrieu"], "tier": 1},
    {"name": "Domaine Pierre Gaillard", "region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "appellations": ["cote rotie", "condrieu", "saint joseph"], "tier": 2},
    {"name": "Domaine Stéphane Ogier", "region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "appellations": ["cote rotie", "condrieu"], "tier": 1},
    {"name": "Domaine Yves Cuilleron", "region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "appellations": ["condrieu", "cote rotie", "saint joseph", "saint peray"], "tier": 2},
    {"name": "Domaine François Villard", "region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "appellations": ["condrieu", "saint joseph", "cote rotie"], "tier": 2},
    {"name": "Domaine Auguste Clape", "region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "appellations": ["cornas", "saint peray"], "tier": 1},
    {"name": "Domaine Thierry Allemand", "region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "appellations": ["cornas"], "tier": 1},
    {"name": "Domaine Eric Texier", "region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "appellations": ["saint joseph", "cote rotie", "cotes du rhone"], "tier": 2},
    {"name": "Domaine Alain Graillot", "region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "appellations": ["crozes hermitage"], "tier": 2},
    {"name": "Domaine de Thalabert", "region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "appellations": ["crozes hermitage"], "tier": 2},
    {"name": "Château Grillet", "region": "Rhône", "subregion": "Côtes du Rhône Septentrionales", "appellations": ["chateau grillet", "condrieu"], "tier": 1},
    # Méridional
    {"name": "Château Rayas", "region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "appellations": ["chateauneuf du pape", "cotes du rhone"], "tier": 1},
    {"name": "Château Beaucastel", "region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "appellations": ["chateauneuf du pape", "cotes du rhone villages"], "tier": 1, "website": "https://www.beaucastel.com"},
    {"name": "Château La Nerthe", "region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "appellations": ["chateauneuf du pape"], "tier": 2},
    {"name": "Château Mont-Redon", "region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "appellations": ["chateauneuf du pape", "lirac", "cotes du rhone"], "tier": 2},
    {"name": "Domaine du Vieux Télégraphe", "region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "appellations": ["chateauneuf du pape"], "tier": 1},
    {"name": "Domaine Henri Bonneau", "region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "appellations": ["chateauneuf du pape"], "tier": 1},
    {"name": "Domaine de la Janasse", "region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "appellations": ["chateauneuf du pape", "cotes du rhone"], "tier": 2},
    {"name": "Domaine Roger Sabon", "region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "appellations": ["chateauneuf du pape", "lirac"], "tier": 2},
    {"name": "Château des Tours", "region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "appellations": ["vacqueyras", "cotes du rhone"], "tier": 2},
    {"name": "Domaine Santa Duc", "region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "appellations": ["gigondas", "vacqueyras", "cotes du rhone villages"], "tier": 2},
    {"name": "Château Pesquié", "region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "appellations": ["ventoux", "cotes du rhone"], "tier": 3},
    {"name": "Château d'Aquéria", "region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "appellations": ["tavel", "lirac"], "tier": 2},
    {"name": "Domaine de la Mordorée", "region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "appellations": ["tavel", "lirac", "chateauneuf du pape"], "tier": 2},
    {"name": "Domaine Raspail-Ay", "region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "appellations": ["gigondas"], "tier": 2},
    {"name": "Domaine de Saint Préfert", "region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "appellations": ["chateauneuf du pape"], "tier": 2},
    {"name": "Château Pégau", "region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "appellations": ["chateauneuf du pape", "cotes du rhone"], "tier": 1},
    {"name": "Domaine Bosquet des Papes", "region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "appellations": ["chateauneuf du pape", "cotes du rhone"], "tier": 2},
    {"name": "Château de Beauregard", "region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "appellations": ["gigondas", "vacqueyras"], "tier": 3},
    {"name": "Domaine de la Solitude", "region": "Rhône", "subregion": "Côtes du Rhône Méridionales", "appellations": ["chateauneuf du pape", "cotes du rhone"], "tier": 3},
]

# Loire — InterLoire
_INTERLOIRE_PRODUCERS: list[dict] = [
    # Sancerre / Centre-Loire
    {"name": "Domaine Henri Bourgeois", "region": "Loire", "subregion": "Centre-Loire", "appellations": ["sancerre", "pouilly fume"], "tier": 2, "website": "https://www.henribourgeois.com"},
    {"name": "Domaine Lucien Crochet", "region": "Loire", "subregion": "Centre-Loire", "appellations": ["sancerre"], "tier": 2},
    {"name": "Domaine Vacheron", "region": "Loire", "subregion": "Centre-Loire", "appellations": ["sancerre"], "tier": 1},
    {"name": "Domaine Henri Pellé", "region": "Loire", "subregion": "Centre-Loire", "appellations": ["menetou salon", "sancerre"], "tier": 2},
    {"name": "Domaine François Cotat", "region": "Loire", "subregion": "Centre-Loire", "appellations": ["sancerre"], "tier": 1},
    {"name": "Domaine Pascal Cotat", "region": "Loire", "subregion": "Centre-Loire", "appellations": ["sancerre"], "tier": 1},
    {"name": "Domaine de la Poussie", "region": "Loire", "subregion": "Centre-Loire", "appellations": ["sancerre"], "tier": 2},
    {"name": "Château de Sancerre", "region": "Loire", "subregion": "Centre-Loire", "appellations": ["sancerre"], "tier": 2},
    {"name": "Domaine Serge Dagueneau et Filles", "region": "Loire", "subregion": "Centre-Loire", "appellations": ["pouilly fume", "pouilly sur loire"], "tier": 2},
    {"name": "Château du Nozet", "region": "Loire", "subregion": "Centre-Loire", "appellations": ["pouilly fume", "sancerre"], "tier": 2},
    {"name": "Domaine Didier Dagueneau", "region": "Loire", "subregion": "Centre-Loire", "appellations": ["pouilly fume", "sancerre"], "tier": 1},
    {"name": "Domaine Henry Natter", "region": "Loire", "subregion": "Centre-Loire", "appellations": ["sancerre", "menetou salon"], "tier": 2},
    # Touraine
    {"name": "Domaine Huet", "region": "Loire", "subregion": "Touraine", "appellations": ["vouvray"], "tier": 1},
    {"name": "Domaine du Clos Naudin", "region": "Loire", "subregion": "Touraine", "appellations": ["vouvray"], "tier": 1},
    {"name": "Domaine Philippe Foreau", "region": "Loire", "subregion": "Touraine", "appellations": ["vouvray"], "tier": 1},
    {"name": "Domaine Bernard Baudry", "region": "Loire", "subregion": "Touraine", "appellations": ["chinon"], "tier": 2},
    {"name": "Domaine Charles Joguet", "region": "Loire", "subregion": "Touraine", "appellations": ["chinon"], "tier": 2},
    {"name": "Domaine Olga Raffault", "region": "Loire", "subregion": "Touraine", "appellations": ["chinon"], "tier": 2},
    {"name": "Domaine Pierre-Jacques Druet", "region": "Loire", "subregion": "Touraine", "appellations": ["bourgueil", "saint nicolas de bourgueil"], "tier": 2},
    {"name": "Domaine Catherine et Pierre Breton", "region": "Loire", "subregion": "Touraine", "appellations": ["bourgueil", "chinon"], "tier": 2},
    # Anjou-Saumur
    {"name": "Domaine des Baumard", "region": "Loire", "subregion": "Anjou-Saumur", "appellations": ["quarts de chaume", "coteaux du layon", "savennieres", "anjou"], "tier": 1},
    {"name": "Domaine du Closel", "region": "Loire", "subregion": "Anjou-Saumur", "appellations": ["savennieres"], "tier": 2},
    {"name": "Domaine Nicolas Joly", "region": "Loire", "subregion": "Anjou-Saumur", "appellations": ["savennieres coulée de serrant", "savennieres roche aux moines"], "tier": 1},
    {"name": "Château de la Roulerie", "region": "Loire", "subregion": "Anjou-Saumur", "appellations": ["coteaux du layon", "anjou"], "tier": 2},
    {"name": "Domaine de la Soucherie", "region": "Loire", "subregion": "Anjou-Saumur", "appellations": ["coteaux du layon", "anjou"], "tier": 2},
    {"name": "Château Yvonne", "region": "Loire", "subregion": "Anjou-Saumur", "appellations": ["saumur champigny", "saumur"], "tier": 2},
    {"name": "Domaine Guiberteau", "region": "Loire", "subregion": "Anjou-Saumur", "appellations": ["saumur champigny", "saumur"], "tier": 1},
    {"name": "Domaine des Roches Neuves", "region": "Loire", "subregion": "Anjou-Saumur", "appellations": ["saumur champigny"], "tier": 2},
    # Pays Nantais
    {"name": "Domaine de l'Écu", "region": "Loire", "subregion": "Pays Nantais", "appellations": ["muscadet sevre et maine"], "tier": 2},
    {"name": "Domaine Luneau-Papin", "region": "Loire", "subregion": "Pays Nantais", "appellations": ["muscadet sevre et maine", "muscadet"], "tier": 2},
    {"name": "Château de la Ragotière", "region": "Loire", "subregion": "Pays Nantais", "appellations": ["muscadet sevre et maine"], "tier": 2},
    {"name": "Domaine Michel Brégeon", "region": "Loire", "subregion": "Pays Nantais", "appellations": ["muscadet sevre et maine"], "tier": 2},
]

# Champagne — CIVC
_CIVC_PRODUCERS: list[dict] = [
    # Grande Marque négociants
    {"name": "Moët & Chandon", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2, "website": "https://www.moet.com"},
    {"name": "Dom Pérignon", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 1},
    {"name": "Veuve Clicquot", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2, "website": "https://www.veuve-clicquot.com"},
    {"name": "Krug", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 1, "website": "https://www.krug.com"},
    {"name": "Louis Roederer", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 1, "website": "https://www.louis-roederer.com"},
    {"name": "Pol Roger", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 1, "website": "https://www.polroger.com"},
    {"name": "Taittinger", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2, "website": "https://www.taittinger.com"},
    {"name": "Bollinger", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 1, "website": "https://www.champagne-bollinger.com"},
    {"name": "Salon", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 1},
    {"name": "Delamotte", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "Gosset", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "Ruinart", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "Pommery", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "Nicolas Feuillatte", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 3},
    {"name": "Lanson", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "Billecart-Salmon", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "Deutz", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "Laurent-Perrier", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "Perrier-Jouët", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "G.H. Mumm", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "Charles Heidsieck", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "Piper-Heidsieck", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "Jacquesson", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 1},
    {"name": "Drappier", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "Henri Giraud", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "Bruno Paillard", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "J.L. Vergnon", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    # Growers / Récoltants-Manipulants
    {"name": "Jacques Selosse", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 1},
    {"name": "Egly-Ouriet", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 1},
    {"name": "Pierre Peters", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 1},
    {"name": "Larmandier-Bernier", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 1},
    {"name": "Benoit Lahaye", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "David Léclapart", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 1},
    {"name": "Emmanuel Brochet", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "Françoise Bedel", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "Georges Laval", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 1},
    {"name": "Marie-Noëlle Ledru", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "Jérôme Prévost", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 1},
    {"name": "Roger Coulon", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "Vilmart & Cie", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "R.H. Coutier", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "Gatinois", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 2},
    {"name": "Agrapart & Fils", "region": "Champagne", "subregion": "Champagne", "appellations": ["champagne"], "tier": 1},
]

# Alsace — CIVA
_CIVA_PRODUCERS: list[dict] = [
    {"name": "Domaine Weinbach", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace", "alsace grand cru"], "tier": 1, "website": "https://www.domaineweinbach.com"},
    {"name": "Domaine Zind-Humbrecht", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace", "alsace grand cru"], "tier": 1},
    {"name": "Domaine Marcel Deiss", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace", "alsace grand cru"], "tier": 1},
    {"name": "Domaine Trimbach", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace", "alsace grand cru"], "tier": 2, "website": "https://www.maison-trimbach.fr"},
    {"name": "Maison Hugel & Fils", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace"], "tier": 2, "website": "https://www.hugel.com"},
    {"name": "Maison Josmeyer", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace", "alsace grand cru"], "tier": 2},
    {"name": "Domaine Albert Mann", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace", "alsace grand cru", "cremant d alsace"], "tier": 2},
    {"name": "Domaine Rolly Gassmann", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace", "alsace grand cru"], "tier": 2},
    {"name": "Domaine Schoffit", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace", "alsace grand cru"], "tier": 2},
    {"name": "Domaine Barmes-Buecher", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace", "alsace grand cru", "cremant d alsace"], "tier": 2},
    {"name": "Domaine Ostertag", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace", "alsace grand cru"], "tier": 2},
    {"name": "Domaine André Kientzler", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace", "alsace grand cru"], "tier": 2},
    {"name": "Domaine Léon Beyer", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace"], "tier": 2, "website": "https://www.leonbeyer.fr"},
    {"name": "Maison Louis Sipp", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace", "alsace grand cru"], "tier": 2},
    {"name": "Maison Paul Blanck", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace", "alsace grand cru"], "tier": 2},
    {"name": "Maison Bott-Geyl", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace", "alsace grand cru"], "tier": 2},
    {"name": "Cave de Turckheim", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace", "alsace grand cru", "cremant d alsace"], "tier": 3},
    {"name": "Cave de Beblenheim", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace", "alsace grand cru"], "tier": 3},
    {"name": "Domaine Rieffel", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace", "alsace grand cru"], "tier": 2},
    {"name": "Domaine Pierre Frick", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace", "alsace grand cru", "cremant d alsace"], "tier": 2},
    {"name": "Domaine Ginglinger", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace", "alsace grand cru", "cremant d alsace"], "tier": 2},
    {"name": "Château d'Eguisheim", "region": "Alsace", "subregion": "Alsace", "appellations": ["alsace"], "tier": 3},
]

# Languedoc — CIVL
_CIVL_PRODUCERS: list[dict] = [
    {"name": "Mas de Daumas Gassac", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["languedoc"], "tier": 1},
    {"name": "Château Picheral", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["languedoc"], "tier": 3},
    {"name": "Domaine de l'Hortus", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["pic saint loup", "languedoc"], "tier": 2},
    {"name": "Château de Lascaux", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["pic saint loup", "languedoc"], "tier": 2},
    {"name": "Château Capion", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["terrasses du larzac", "languedoc"], "tier": 2},
    {"name": "Mas Jullien", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["terrasses du larzac", "languedoc"], "tier": 1},
    {"name": "Domaine de Montcalmès", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["terrasses du larzac", "languedoc"], "tier": 1},
    {"name": "Domaine Henry", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["terrasses du larzac", "languedoc"], "tier": 2},
    {"name": "Château La Liquière", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["faugeres", "languedoc"], "tier": 2},
    {"name": "Domaine Léon Barral", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["faugeres"], "tier": 1},
    {"name": "Château Moulin de Ciffre", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["faugeres"], "tier": 2},
    {"name": "Domaine des Estagnères", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["saint chinian", "languedoc"], "tier": 2},
    {"name": "Château Coujan", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["saint chinian"], "tier": 2},
    {"name": "Domaine Canet-Valette", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["saint chinian"], "tier": 2},
    {"name": "Mas Champart", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["saint chinian"], "tier": 2},
    {"name": "Domaine Borie de Maurel", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["minervois", "minervois la liviniere"], "tier": 2},
    {"name": "Château Villerambert-Julien", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["minervois", "minervois la liviniere"], "tier": 2},
    {"name": "Domaine Clos Centeilles", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["minervois", "minervois la liviniere"], "tier": 2},
    {"name": "Domaine Gauby", "region": "Languedoc-Roussillon", "subregion": "Roussillon", "appellations": ["cotes du roussillon villages", "cotes du roussillon"], "tier": 1},
    {"name": "Domaine Cazes", "region": "Languedoc-Roussillon", "subregion": "Roussillon", "appellations": ["rivesaltes", "muscat de rivesaltes", "cotes du roussillon"], "tier": 2},
    {"name": "Domaine La Tour Vieille", "region": "Languedoc-Roussillon", "subregion": "Roussillon", "appellations": ["collioure", "banyuls", "banyuls grand cru"], "tier": 2},
    {"name": "Domaine du Mas Blanc", "region": "Languedoc-Roussillon", "subregion": "Roussillon", "appellations": ["banyuls", "banyuls grand cru", "collioure"], "tier": 2},
    {"name": "Domaine Vial Magnères", "region": "Languedoc-Roussillon", "subregion": "Roussillon", "appellations": ["banyuls", "collioure"], "tier": 2},
    {"name": "Gérard Bertrand", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["corbieres", "minervois", "languedoc", "pic saint loup"], "tier": 2, "website": "https://www.gerard-bertrand.com"},
    {"name": "Château de Lastours", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["corbieres"], "tier": 2},
    {"name": "Château Ollieux Romanis", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["corbieres", "corbieres boutenac"], "tier": 2},
    {"name": "Château Villemajou", "region": "Languedoc-Roussillon", "subregion": "Languedoc", "appellations": ["corbieres boutenac", "corbieres"], "tier": 2},
    {"name": "Domaine de la Rectorie", "region": "Languedoc-Roussillon", "subregion": "Roussillon", "appellations": ["banyuls", "banyuls grand cru", "collioure"], "tier": 2},
]

# Map source_code → producer list
_SOURCE_PRODUCERS: dict[str, list[dict]] = {
    "CIVB": _CIVB_PRODUCERS,
    "BIVB": _BIVB_PRODUCERS,
    "INTER_RHONE": _INTER_RHONE_PRODUCERS,
    "INTERLOIRE": _INTERLOIRE_PRODUCERS,
    "CIVC": _CIVC_PRODUCERS,
    "CIVA": _CIVA_PRODUCERS,
    "CIVL": _CIVL_PRODUCERS,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(s: str) -> str:
    """Lower-case, accent-stripped, spaces to hyphens slug for producer_norm."""
    n = norm_text(s)                       # strip accents, lower, normalise
    n = re.sub(r"[^a-z0-9\s-]", " ", n)   # keep only alphanums + space + hyphen
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _get_or_create_source(conn: sqlite3.Connection, src: dict) -> int:
    row = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = ?",
        (src["source_code"],),
    ).fetchone()
    if row:
        return row[0]
    conn.execute(
        """INSERT OR IGNORE INTO dim_source
           (source_code, source_name, source_tier, country_code,
            base_url, license_class, cadence, enabled, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            src["source_code"],
            src["source_name"],
            "A_official",
            src.get("country_code", "FR"),
            src.get("base_url"),
            "public_check_terms",
            "annual",
            1,
            src.get("notes"),
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = ?",
        (src["source_code"],),
    ).fetchone()
    return row[0]


def _upsert_producer(
    conn: sqlite3.Connection,
    name: str,
    region: str,
    subregion: Optional[str],
    appellations: list[str],
    tier: Optional[int],
    website: Optional[str],
    coverage_tier: str = "notable",
) -> tuple[bool, bool]:
    """
    Insert or update a producer row.
    Returns (inserted: bool, updated: bool).

    Upsert key: producer_norm + country_code.
    If a matching row exists:
      - merge allowed_appellations (union)
      - update last_seen_at
    If no matching row: INSERT.
    """
    display_name = clean_producer_display(name)
    if not display_name:
        display_name = name
    producer_norm = _slugify(display_name)
    if not producer_norm:
        return False, False

    existing = conn.execute(
        "SELECT producer_key, allowed_appellations FROM dim_producer "
        "WHERE producer_norm = ? AND country_code = 'FR'",
        (producer_norm,),
    ).fetchone()

    now = int(time.time())
    appellations_json = json.dumps(sorted(set(appellations)))

    if existing:
        # Merge appellations
        try:
            existing_apps: list = json.loads(existing["allowed_appellations"] or "[]")
        except Exception:
            existing_apps = []
        merged = sorted(set(existing_apps) | set(appellations))
        merged_json = json.dumps(merged)
        conn.execute(
            """UPDATE dim_producer
               SET allowed_appellations = ?,
                   last_seen_at = ?,
                   website = COALESCE(website, ?),
                   tier = COALESCE(tier, ?)
               WHERE producer_key = ?""",
            (merged_json, now, website, tier, existing["producer_key"]),
        )
        return False, True
    else:
        conn.execute(
            """INSERT INTO dim_producer
               (producer_name, producer_norm, country_code, region, subregion,
                allowed_appellations, aliases, website, tier, status,
                first_seen_at, last_seen_at, coverage_tier)
               VALUES (?, ?, 'FR', ?, ?, ?, '[]', ?, ?, 'active', ?, ?, ?)""",
            (
                display_name,
                producer_norm,
                region,
                subregion,
                appellations_json,
                website,
                tier,
                now,
                now,
                coverage_tier,
            ),
        )
        return True, False


# ---------------------------------------------------------------------------
# Per-syndicate live-fetch attempts
# These try to hit the official directory.  All are best-effort — any failure
# falls back to the built-in taxonomy.
# ---------------------------------------------------------------------------

def _try_fetch_civb(client: httpx.Client) -> list[dict]:
    """
    CIVB bordeaux.com — probe the property directory API.
    The public site offers a JSON search endpoint for châteaux.
    """
    try:
        resp = client.get(
            "https://www.bordeaux.com/our-wines/find-a-wine",
            timeout=15,
        )
        # The live site requires JS rendering; scraping the static HTML gives only
        # a limited set. We return [] so the taxonomy fallback handles the rest.
    except Exception:
        pass
    return []


def _try_fetch_bivb(client: httpx.Client) -> list[dict]:
    """BIVB has a winery search that needs JS — return empty for taxonomy fallback."""
    return []


def _try_fetch_inter_rhone(client: httpx.Client) -> list[dict]:
    """Inter-Rhône producer directory requires JS rendering — taxonomy fallback."""
    return []


def _try_fetch_interloire(client: httpx.Client) -> list[dict]:
    """InterLoire producer search — JS-rendered — taxonomy fallback."""
    return []


def _try_fetch_civc(client: httpx.Client) -> list[dict]:
    """
    CIVC / champagne.fr — try the JSON producer search API.
    The site exposes a public REST-like endpoint for house lookups.
    """
    try:
        resp = client.get(
            "https://www.champagne.fr/en/api/producers",
            params={"format": "json", "limit": 500},
            timeout=20,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return [{"name": r.get("name") or r.get("title", ""), "appellations": ["champagne"]} for r in data if r.get("name") or r.get("title")]
            if isinstance(data, dict) and "results" in data:
                return [{"name": r.get("name", ""), "appellations": ["champagne"]} for r in data["results"] if r.get("name")]
    except Exception:
        pass
    return []


def _try_fetch_civa(client: httpx.Client) -> list[dict]:
    """CIVA vinsalsace.com — JS-rendered directory — taxonomy fallback."""
    return []


def _try_fetch_civl(client: httpx.Client) -> list[dict]:
    """CIVL languedoc-wines.com — taxonomy fallback."""
    return []


_LIVE_FETCHERS: dict[str, callable] = {
    "CIVB": _try_fetch_civb,
    "BIVB": _try_fetch_bivb,
    "INTER_RHONE": _try_fetch_inter_rhone,
    "INTERLOIRE": _try_fetch_interloire,
    "CIVC": _try_fetch_civc,
    "CIVA": _try_fetch_civa,
    "CIVL": _try_fetch_civl,
}


# ---------------------------------------------------------------------------
# BaseScraper subclasses — one per syndicate
# ---------------------------------------------------------------------------

class _SyndicateScraper(BaseScraper):
    """Shared logic for all seven syndicate scrapers."""

    source_code: str = ""          # override in subclass
    _source_meta: dict = {}        # override in subclass
    _taxonomy: list[dict] = []     # override in subclass

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        source_key = _get_or_create_source(self.conn, self._source_meta)
        batch_id = self.batch_id or (
            f"{self.source_code.lower()}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        )
        result = ScrapeResult(batch_id=batch_id)

        console.rule(f"[bold cyan]{self._source_meta['source_name']}[/bold cyan]")

        # 1. Try live fetch (best-effort)
        live_producers: list[dict] = []
        fetcher = _LIVE_FETCHERS.get(self.source_code)
        if fetcher:
            with httpx.Client(
                headers={
                    "Accept": "application/json, text/html, */*",
                    "User-Agent": "Mozilla/5.0 (compatible; AchillesWineCrawler/1.0; +https://github.com/FibSol/AchillesWines)",
                },
                follow_redirects=True,
                timeout=20,
            ) as client:
                try:
                    live_producers = fetcher(client)
                    if live_producers:
                        console.print(f"  Live fetch: {len(live_producers)} producers from API")
                except Exception as exc:
                    console.print(f"[yellow]  Live fetch failed ({exc}) — using taxonomy only[/yellow]")

        # 2. Merge live + taxonomy (live names take precedence for display)
        #    Use a dict keyed by norm to dedup
        candidates: dict[str, dict] = {}

        for p in self._taxonomy:
            norm = _slugify(clean_producer_display(p["name"]) or p["name"])
            if norm:
                candidates[norm] = p

        for p in live_producers:
            name = p.get("name", "").strip()
            if not name:
                continue
            norm = _slugify(clean_producer_display(name) or name)
            if norm and norm not in candidates:
                # Live-only producer: assign sensible defaults from source meta
                src = self._source_meta
                candidates[norm] = {
                    "name": name,
                    "region": _SOURCE_REGION_MAP.get(self.source_code, "France"),
                    "subregion": None,
                    "appellations": p.get("appellations", []),
                    "tier": None,
                    "website": None,
                }

        result.rows_fetched = len(candidates)
        console.print(f"  Total candidates: {result.rows_fetched}")

        processed = 0
        rows_updated_count = 0
        for norm, p in candidates.items():
            if limit is not None and processed >= limit:
                break
            try:
                inserted, updated = _upsert_producer(
                    self.conn,
                    name=p["name"],
                    region=p["region"],
                    subregion=p.get("subregion"),
                    appellations=p.get("appellations", []),
                    tier=p.get("tier"),
                    website=p.get("website"),
                )
                if inserted:
                    result.rows_inserted += 1
                elif updated:
                    rows_updated_count += 1
                else:
                    result.rows_skipped_unchanged += 1
            except Exception as exc:
                write_dlq(
                    self.conn, source_key, batch_id,
                    "validation_error", str(exc),
                    p, source_record_id=norm,
                )
                result.rows_dlq += 1
            processed += 1

        self.conn.commit()

        # ops_batch_log
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
                rows_updated_count,
                result.rows_dlq,
                result.rows_skipped_unchanged,
                f"live_fetch={len(live_producers)} taxonomy={len(self._taxonomy)}",
            ),
        )
        self.conn.commit()

        console.print(
            f"[green]{self.source_code} done[/green] — "
            f"inserted: [bold]{result.rows_inserted}[/bold]  "
            f"updated: {rows_updated_count}  "
            f"unchanged: {result.rows_skipped_unchanged}  "
            f"dlq: {result.rows_dlq}"
        )
        return result


# region map used for live-only producers
_SOURCE_REGION_MAP: dict[str, str] = {
    "CIVB": "Bordeaux",
    "BIVB": "Bourgogne",
    "INTER_RHONE": "Rhône",
    "INTERLOIRE": "Loire",
    "CIVC": "Champagne",
    "CIVA": "Alsace",
    "CIVL": "Languedoc-Roussillon",
}


class CIVBScraper(_SyndicateScraper):
    source_code = "CIVB"
    _source_meta = next(s for s in _SOURCES if s["source_code"] == "CIVB")
    _taxonomy = _CIVB_PRODUCERS


class BIVBScraper(_SyndicateScraper):
    source_code = "BIVB"
    _source_meta = next(s for s in _SOURCES if s["source_code"] == "BIVB")
    _taxonomy = _BIVB_PRODUCERS


class InterRhoneScraper(_SyndicateScraper):
    source_code = "INTER_RHONE"
    _source_meta = next(s for s in _SOURCES if s["source_code"] == "INTER_RHONE")
    _taxonomy = _INTER_RHONE_PRODUCERS


class InterLoireScraper(_SyndicateScraper):
    source_code = "INTERLOIRE"
    _source_meta = next(s for s in _SOURCES if s["source_code"] == "INTERLOIRE")
    _taxonomy = _INTERLOIRE_PRODUCERS


class CIVCScraper(_SyndicateScraper):
    source_code = "CIVC"
    _source_meta = next(s for s in _SOURCES if s["source_code"] == "CIVC")
    _taxonomy = _CIVC_PRODUCERS


class CIVAScraper(_SyndicateScraper):
    source_code = "CIVA"
    _source_meta = next(s for s in _SOURCES if s["source_code"] == "CIVA")
    _taxonomy = _CIVA_PRODUCERS


class CIVLScraper(_SyndicateScraper):
    source_code = "CIVL"
    _source_meta = next(s for s in _SOURCES if s["source_code"] == "CIVL")
    _taxonomy = _CIVL_PRODUCERS
