"""
Appellation → grape variety mapping for French AOC/AOP appellations.

Strategy A: appellation-default grape rules.
Each appellation maps to a list of variety dicts:
  {
    "variety_norm": str,       # norm_text() of variety name
    "variety_name": str,       # canonical display name
    "color_family": str,       # red | white | rosé | other
    "is_primary": bool,        # True = legally dominant grape
    "pct_min": int | None,     # typical minimum %
    "pct_max": int | None,     # typical maximum %
  }

Keys are norm_text() of the appellation name (matching dim_appellation.appellation_norm).
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from .identity import norm_text


# ---------------------------------------------------------------------------
# Helper: normalise variety name the same way identity.norm_text does
# ---------------------------------------------------------------------------

def _v(name: str, color: str, primary: bool, pct_min=None, pct_max=None) -> dict:
    return {
        "variety_norm": norm_text(name),
        "variety_name": name,
        "color_family": color,
        "is_primary": primary,
        "pct_min": pct_min,
        "pct_max": pct_max,
    }


# ---------------------------------------------------------------------------
# Comprehensive appellation → variety lookup
# Keys = norm_text(appellation_name)  (matches dim_appellation.appellation_norm)
# ---------------------------------------------------------------------------

APPELLATION_VARIETIES: dict[str, list[dict]] = {

    # ═══════════════════════════════════════════════════════════════════
    # BURGUNDY — Bourgogne
    # ═══════════════════════════════════════════════════════════════════

    # Generic Bourgogne
    "bourgogne": [
        _v("Pinot Noir", "red", True, 85, 100),
        _v("Gamay", "red", False, 0, 15),
    ],
    "bourgogne blanc": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "bourgogne rouge": [
        _v("Pinot Noir", "red", True, 85, 100),
        _v("Gamay", "red", False, 0, 15),
    ],
    "bourgogne aligote": [
        _v("Aligoté", "white", True, 100, 100),
    ],
    "bourgogne passetoutgrain": [
        _v("Gamay", "red", True, 33, 66),
        _v("Pinot Noir", "red", False, 33, 66),
    ],

    # Chablis
    "chablis": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "chablis 1er cru": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "chablis premier cru": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "chablis grand cru": [
        _v("Chardonnay", "white", True, 100, 100),
    ],

    # Côte de Nuits — red village appellations
    "gevrey chambertin": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "gevrey chambertin 1er cru": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "gevrey chambertin premier cru": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "chambolle musigny": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "chambolle musigny 1er cru": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "chambolle musigny premier cru": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "vosne romanee": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "vosne romanee 1er cru": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "vosne romanee premier cru": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "nuits saint georges": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "nuits saint georges 1er cru": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "nuits saint georges premier cru": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "morey saint denis": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "vougeot": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "flagey echezeaux": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],

    # Grand Crus Côte de Nuits
    "chambertin": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "chambertin clos de beze": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "bonnes mares": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "musigny": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "clos de vougeot": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "echezeaux": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "grands echezeaux": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "romanee conti": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "romanee saint vivant": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "richebourg": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "la tache": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],

    # Côte de Beaune — red
    "pommard": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "pommard 1er cru": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "pommard premier cru": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "volnay": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "volnay 1er cru": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "volnay premier cru": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "beaune": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "beaune 1er cru": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "savigny les beaune": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "aloxe corton": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "corton": [
        _v("Pinot Noir", "red", True, 90, 100),
        _v("Chardonnay", "white", False, 0, 10),
    ],
    "corton charlemagne": [
        _v("Chardonnay", "white", True, 100, 100),
    ],

    # Côte de Beaune — white
    "meursault": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "meursault premier cru": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "meursault 1er cru": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "puligny montrachet": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "puligny montrachet 1er cru": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "puligny montrachet premier cru": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "chassagne montrachet": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "chassagne montrachet 1er cru": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "chassagne montrachet premier cru": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "montrachet": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "batard montrachet": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "chevalier montrachet": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "saint aubin": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "rully": [
        _v("Chardonnay", "white", True, 80, 100),
        _v("Pinot Noir", "red", False, 0, 20),
    ],
    "mercurey": [
        _v("Pinot Noir", "red", True, 85, 100),
        _v("Chardonnay", "white", False, 0, 15),
    ],
    "givry": [
        _v("Pinot Noir", "red", True, 85, 100),
    ],
    "montagny": [
        _v("Chardonnay", "white", True, 100, 100),
    ],

    # Mâconnais
    "macon": [
        _v("Chardonnay", "white", True, 85, 100),
        _v("Gamay", "red", False, 0, 15),
    ],
    "macon villages": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "pouilly fuisse": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "saint veran": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "pouilly vinzelles": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "pouilly loche": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "viré clesse": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "vire clesse": [
        _v("Chardonnay", "white", True, 100, 100),
    ],

    # Crémant de Bourgogne
    "cremant de bourgogne": [
        _v("Pinot Noir", "red", True, 30, 60),
        _v("Chardonnay", "white", False, 30, 60),
        _v("Aligoté", "white", False, 0, 30),
        _v("Gamay", "red", False, 0, 20),
    ],

    # ═══════════════════════════════════════════════════════════════════
    # BORDEAUX
    # ═══════════════════════════════════════════════════════════════════

    "bordeaux": [
        _v("Merlot", "red", True, 50, 80),
        _v("Cabernet Sauvignon", "red", False, 10, 40),
        _v("Cabernet Franc", "red", False, 5, 30),
        _v("Petit Verdot", "red", False, 0, 5),
    ],
    "bordeaux superieur": [
        _v("Merlot", "red", True, 50, 80),
        _v("Cabernet Sauvignon", "red", False, 10, 40),
        _v("Cabernet Franc", "red", False, 5, 30),
    ],
    "bordeaux blanc": [
        _v("Sauvignon Blanc", "white", True, 50, 80),
        _v("Sémillon", "white", False, 10, 40),
        _v("Muscadelle", "white", False, 0, 10),
    ],
    "medoc": [
        _v("Cabernet Sauvignon", "red", True, 40, 65),
        _v("Merlot", "red", False, 25, 40),
        _v("Cabernet Franc", "red", False, 0, 20),
        _v("Petit Verdot", "red", False, 0, 5),
    ],
    "haut medoc": [
        _v("Cabernet Sauvignon", "red", True, 40, 65),
        _v("Merlot", "red", False, 25, 40),
        _v("Cabernet Franc", "red", False, 0, 20),
        _v("Petit Verdot", "red", False, 0, 5),
    ],
    "pauillac": [
        _v("Cabernet Sauvignon", "red", True, 60, 85),
        _v("Merlot", "red", False, 10, 30),
        _v("Cabernet Franc", "red", False, 5, 15),
        _v("Petit Verdot", "red", False, 0, 5),
    ],
    "margaux": [
        _v("Cabernet Sauvignon", "red", True, 55, 80),
        _v("Merlot", "red", False, 15, 35),
        _v("Cabernet Franc", "red", False, 5, 15),
        _v("Petit Verdot", "red", False, 0, 10),
    ],
    "saint julien": [
        _v("Cabernet Sauvignon", "red", True, 55, 75),
        _v("Merlot", "red", False, 20, 35),
        _v("Cabernet Franc", "red", False, 5, 15),
        _v("Petit Verdot", "red", False, 0, 5),
    ],
    "saint estephe": [
        _v("Cabernet Sauvignon", "red", True, 40, 65),
        _v("Merlot", "red", False, 25, 45),
        _v("Cabernet Franc", "red", False, 5, 20),
        _v("Petit Verdot", "red", False, 0, 5),
    ],
    "listrac medoc": [
        _v("Merlot", "red", True, 40, 60),
        _v("Cabernet Sauvignon", "red", False, 25, 45),
        _v("Cabernet Franc", "red", False, 5, 15),
    ],
    "moulis en medoc": [
        _v("Cabernet Sauvignon", "red", True, 40, 60),
        _v("Merlot", "red", False, 25, 45),
        _v("Cabernet Franc", "red", False, 5, 15),
    ],
    "moulis": [
        _v("Cabernet Sauvignon", "red", True, 40, 60),
        _v("Merlot", "red", False, 25, 45),
        _v("Cabernet Franc", "red", False, 5, 15),
    ],
    "saint emilion": [
        _v("Merlot", "red", True, 60, 90),
        _v("Cabernet Franc", "red", False, 10, 30),
        _v("Cabernet Sauvignon", "red", False, 0, 10),
    ],
    "saint emilion grand cru": [
        _v("Merlot", "red", True, 60, 90),
        _v("Cabernet Franc", "red", False, 10, 30),
        _v("Cabernet Sauvignon", "red", False, 0, 10),
    ],
    "saint emilion grand cru classe": [
        _v("Merlot", "red", True, 60, 90),
        _v("Cabernet Franc", "red", False, 10, 30),
        _v("Cabernet Sauvignon", "red", False, 0, 10),
    ],
    "pomerol": [
        _v("Merlot", "red", True, 70, 95),
        _v("Cabernet Franc", "red", False, 5, 20),
        _v("Cabernet Sauvignon", "red", False, 0, 10),
    ],
    "lalande de pomerol": [
        _v("Merlot", "red", True, 70, 90),
        _v("Cabernet Franc", "red", False, 5, 20),
        _v("Cabernet Sauvignon", "red", False, 0, 10),
    ],
    "fronsac": [
        _v("Merlot", "red", True, 60, 80),
        _v("Cabernet Franc", "red", False, 10, 30),
        _v("Cabernet Sauvignon", "red", False, 0, 15),
    ],
    "pessac leognan": [
        _v("Cabernet Sauvignon", "red", True, 50, 75),
        _v("Merlot", "red", False, 20, 40),
        _v("Cabernet Franc", "red", False, 0, 15),
    ],
    "pessac leognan rouge": [
        _v("Cabernet Sauvignon", "red", True, 50, 75),
        _v("Merlot", "red", False, 20, 40),
        _v("Cabernet Franc", "red", False, 0, 15),
    ],
    "pessac leognan blanc": [
        _v("Sauvignon Blanc", "white", True, 40, 70),
        _v("Sémillon", "white", False, 25, 55),
        _v("Muscadelle", "white", False, 0, 10),
    ],
    "graves": [
        _v("Merlot", "red", True, 40, 65),
        _v("Cabernet Sauvignon", "red", False, 25, 50),
        _v("Cabernet Franc", "red", False, 0, 15),
    ],
    "graves rouge": [
        _v("Merlot", "red", True, 40, 65),
        _v("Cabernet Sauvignon", "red", False, 25, 50),
        _v("Cabernet Franc", "red", False, 0, 15),
    ],
    "graves blanc": [
        _v("Sauvignon Blanc", "white", True, 40, 70),
        _v("Sémillon", "white", False, 25, 55),
        _v("Muscadelle", "white", False, 0, 10),
    ],
    "entre deux mers": [
        _v("Sauvignon Blanc", "white", True, 50, 80),
        _v("Sémillon", "white", False, 15, 40),
        _v("Muscadelle", "white", False, 0, 10),
    ],
    "sauternes": [
        _v("Sémillon", "white", True, 60, 90),
        _v("Sauvignon Blanc", "white", False, 10, 35),
        _v("Muscadelle", "white", False, 0, 5),
    ],
    "barsac": [
        _v("Sémillon", "white", True, 60, 90),
        _v("Sauvignon Blanc", "white", False, 10, 35),
        _v("Muscadelle", "white", False, 0, 5),
    ],

    # ═══════════════════════════════════════════════════════════════════
    # CHAMPAGNE
    # ═══════════════════════════════════════════════════════════════════

    "champagne": [
        _v("Pinot Noir", "red", True, 25, 55),
        _v("Chardonnay", "white", False, 20, 50),
        _v("Pinot Meunier", "red", False, 15, 40),
        _v("Pinot Blanc", "white", False, 0, 5),
        _v("Arbane", "white", False, 0, 5),
        _v("Petit Meslier", "white", False, 0, 5),
    ],
    "champagne blanc de blancs": [
        _v("Chardonnay", "white", True, 100, 100),
    ],
    "champagne blanc de noirs": [
        _v("Pinot Noir", "red", True, 60, 100),
        _v("Pinot Meunier", "red", False, 0, 40),
    ],
    "champagne rose": [
        _v("Pinot Noir", "red", True, 30, 60),
        _v("Chardonnay", "white", False, 20, 50),
        _v("Pinot Meunier", "red", False, 10, 30),
    ],
    "champagne premier cru": [
        _v("Pinot Noir", "red", True, 25, 55),
        _v("Chardonnay", "white", False, 20, 50),
        _v("Pinot Meunier", "red", False, 15, 40),
    ],
    "champagne grand cru": [
        _v("Pinot Noir", "red", True, 25, 55),
        _v("Chardonnay", "white", False, 20, 50),
        _v("Pinot Meunier", "red", False, 15, 40),
    ],

    # ═══════════════════════════════════════════════════════════════════
    # LOIRE
    # ═══════════════════════════════════════════════════════════════════

    # Sancerre
    "sancerre": [
        _v("Sauvignon Blanc", "white", True, 100, 100),
    ],
    "sancerre blanc": [
        _v("Sauvignon Blanc", "white", True, 100, 100),
    ],
    "sancerre rouge": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],

    # Pouilly-Fumé / Pouilly-sur-Loire
    "pouilly fume": [
        _v("Sauvignon Blanc", "white", True, 100, 100),
    ],
    "pouilly sur loire": [
        _v("Chasselas", "white", True, 100, 100),
    ],

    # Muscadet
    "muscadet": [
        _v("Melon de Bourgogne", "white", True, 100, 100),
    ],
    "muscadet sevre et maine": [
        _v("Melon de Bourgogne", "white", True, 100, 100),
    ],
    "muscadet coteaux de la loire": [
        _v("Melon de Bourgogne", "white", True, 100, 100),
    ],
    "muscadet cotes de grand lieu": [
        _v("Melon de Bourgogne", "white", True, 100, 100),
    ],

    # Vouvray / Montlouis
    "vouvray": [
        _v("Chenin Blanc", "white", True, 100, 100),
    ],
    "montlouis sur loire": [
        _v("Chenin Blanc", "white", True, 100, 100),
    ],
    "savennieres": [
        _v("Chenin Blanc", "white", True, 100, 100),
    ],
    "coteaux du layon": [
        _v("Chenin Blanc", "white", True, 100, 100),
    ],
    "bonnezeaux": [
        _v("Chenin Blanc", "white", True, 100, 100),
    ],
    "quarts de chaume": [
        _v("Chenin Blanc", "white", True, 100, 100),
    ],
    "anjou": [
        _v("Chenin Blanc", "white", True, 60, 80),
        _v("Sauvignon Blanc", "white", False, 0, 20),
        _v("Cabernet Franc", "red", False, 0, 30),
        _v("Cabernet Sauvignon", "red", False, 0, 20),
    ],
    "anjou blanc": [
        _v("Chenin Blanc", "white", True, 80, 100),
    ],
    "anjou rouge": [
        _v("Cabernet Franc", "red", True, 60, 100),
        _v("Cabernet Sauvignon", "red", False, 0, 40),
    ],
    "anjou villages": [
        _v("Cabernet Franc", "red", True, 60, 100),
        _v("Cabernet Sauvignon", "red", False, 0, 40),
    ],
    "saumur": [
        _v("Chenin Blanc", "white", True, 80, 100),
    ],
    "saumur champigny": [
        _v("Cabernet Franc", "red", True, 85, 100),
        _v("Cabernet Sauvignon", "red", False, 0, 15),
    ],

    # Chinon / Bourgueil
    "chinon": [
        _v("Cabernet Franc", "red", True, 90, 100),
        _v("Cabernet Sauvignon", "red", False, 0, 10),
    ],
    "bourgueil": [
        _v("Cabernet Franc", "red", True, 90, 100),
        _v("Cabernet Sauvignon", "red", False, 0, 10),
    ],
    "saint nicolas de bourgueil": [
        _v("Cabernet Franc", "red", True, 100, 100),
    ],

    # Touraine
    "touraine": [
        _v("Sauvignon Blanc", "white", True, 50, 80),
        _v("Gamay", "red", False, 0, 30),
        _v("Cabernet Franc", "red", False, 0, 30),
        _v("Chenin Blanc", "white", False, 0, 20),
    ],

    # Pays Nantais / Muscadet
    "gros plant du pays nantais": [
        _v("Folle Blanche", "white", True, 100, 100),
    ],

    # ═══════════════════════════════════════════════════════════════════
    # RHÔNE
    # ═══════════════════════════════════════════════════════════════════

    # Northern Rhône — reds
    "cote rotie": [
        _v("Syrah", "red", True, 80, 100),
        _v("Viognier", "white", False, 0, 20),
    ],
    "hermitage": [
        _v("Syrah", "red", True, 85, 100),
        _v("Marsanne", "white", False, 0, 15),
        _v("Roussanne", "white", False, 0, 15),
    ],
    "hermitage rouge": [
        _v("Syrah", "red", True, 85, 100),
        _v("Marsanne", "white", False, 0, 15),
        _v("Roussanne", "white", False, 0, 15),
    ],
    "hermitage blanc": [
        _v("Marsanne", "white", True, 85, 100),
        _v("Roussanne", "white", False, 0, 15),
    ],
    "crozes hermitage": [
        _v("Syrah", "red", True, 85, 100),
        _v("Marsanne", "white", False, 0, 15),
        _v("Roussanne", "white", False, 0, 15),
    ],
    "crozes hermitage rouge": [
        _v("Syrah", "red", True, 85, 100),
        _v("Marsanne", "white", False, 0, 15),
        _v("Roussanne", "white", False, 0, 15),
    ],
    "crozes hermitage blanc": [
        _v("Marsanne", "white", True, 80, 100),
        _v("Roussanne", "white", False, 0, 20),
    ],
    "saint joseph": [
        _v("Syrah", "red", True, 90, 100),
        _v("Marsanne", "white", False, 0, 10),
        _v("Roussanne", "white", False, 0, 10),
    ],
    "saint joseph rouge": [
        _v("Syrah", "red", True, 90, 100),
        _v("Marsanne", "white", False, 0, 10),
        _v("Roussanne", "white", False, 0, 10),
    ],
    "saint joseph blanc": [
        _v("Marsanne", "white", True, 80, 100),
        _v("Roussanne", "white", False, 0, 20),
    ],
    "cornas": [
        _v("Syrah", "red", True, 100, 100),
    ],

    # Northern Rhône — whites
    "condrieu": [
        _v("Viognier", "white", True, 100, 100),
    ],
    "chateau grillet": [
        _v("Viognier", "white", True, 100, 100),
    ],
    "saint peray": [
        _v("Marsanne", "white", True, 100, 100),
    ],

    # Southern Rhône
    "chateauneuf du pape": [
        _v("Grenache", "red", True, 50, 80),
        _v("Syrah", "red", False, 5, 20),
        _v("Mourvèdre", "red", False, 5, 20),
        _v("Cinsault", "red", False, 0, 10),
        _v("Counoise", "red", False, 0, 10),
        _v("Grenache Blanc", "white", False, 0, 10),
    ],
    "chateauneuf du pape rouge": [
        _v("Grenache", "red", True, 50, 80),
        _v("Syrah", "red", False, 5, 20),
        _v("Mourvèdre", "red", False, 5, 20),
        _v("Cinsault", "red", False, 0, 10),
        _v("Counoise", "red", False, 0, 10),
    ],
    "chateauneuf du pape blanc": [
        _v("Grenache Blanc", "white", True, 30, 60),
        _v("Roussanne", "white", False, 20, 50),
        _v("Bourboulenc", "white", False, 0, 20),
        _v("Clairette", "white", False, 0, 20),
        _v("Picpoul", "white", False, 0, 10),
    ],
    "gigondas": [
        _v("Grenache", "red", True, 50, 80),
        _v("Syrah", "red", False, 10, 25),
        _v("Mourvèdre", "red", False, 5, 20),
        _v("Cinsault", "red", False, 0, 10),
    ],
    "vacqueyras": [
        _v("Grenache", "red", True, 50, 80),
        _v("Syrah", "red", False, 10, 25),
        _v("Mourvèdre", "red", False, 5, 20),
        _v("Cinsault", "red", False, 0, 10),
    ],
    "cotes du rhone": [
        _v("Grenache", "red", True, 40, 70),
        _v("Syrah", "red", False, 10, 30),
        _v("Mourvèdre", "red", False, 5, 20),
        _v("Cinsault", "red", False, 0, 20),
        _v("Carignan", "red", False, 0, 20),
    ],
    "cotes du rhone villages": [
        _v("Grenache", "red", True, 40, 70),
        _v("Syrah", "red", False, 10, 30),
        _v("Mourvèdre", "red", False, 5, 20),
        _v("Cinsault", "red", False, 0, 20),
    ],
    "beaumes de venise": [
        _v("Grenache", "red", True, 50, 70),
        _v("Syrah", "red", False, 20, 30),
        _v("Mourvèdre", "red", False, 0, 20),
    ],
    "lirac": [
        _v("Grenache", "red", True, 40, 70),
        _v("Syrah", "red", False, 10, 30),
        _v("Mourvèdre", "red", False, 5, 20),
        _v("Cinsault", "red", False, 0, 10),
    ],
    "tavel": [
        _v("Grenache", "rosé", True, 40, 60),
        _v("Cinsault", "rosé", False, 15, 35),
        _v("Syrah", "rosé", False, 0, 15),
    ],
    "ventoux": [
        _v("Grenache", "red", True, 40, 70),
        _v("Syrah", "red", False, 10, 30),
        _v("Mourvèdre", "red", False, 0, 20),
    ],
    "luberon": [
        _v("Grenache", "red", True, 40, 70),
        _v("Syrah", "red", False, 10, 30),
        _v("Mourvèdre", "red", False, 0, 20),
    ],
    "muscat de beaumes de venise": [
        _v("Muscat Blanc à Petits Grains", "white", True, 100, 100),
    ],

    # ═══════════════════════════════════════════════════════════════════
    # ALSACE
    # ═══════════════════════════════════════════════════════════════════

    "alsace": [
        _v("Riesling", "white", True, 20, 35),
        _v("Gewurztraminer", "white", False, 15, 30),
        _v("Pinot Gris", "white", False, 10, 20),
        _v("Pinot Blanc", "white", False, 10, 20),
        _v("Sylvaner", "white", False, 5, 15),
        _v("Muscat Blanc à Petits Grains", "white", False, 2, 8),
        _v("Pinot Noir", "red", False, 5, 15),
    ],
    "alsace riesling": [
        _v("Riesling", "white", True, 100, 100),
    ],
    "alsace riesling grand cru": [
        _v("Riesling", "white", True, 100, 100),
    ],
    "alsace gewurztraminer": [
        _v("Gewurztraminer", "white", True, 100, 100),
    ],
    "alsace gewurztraminer vendanges tardives": [
        _v("Gewurztraminer", "white", True, 100, 100),
    ],
    "alsace pinot gris": [
        _v("Pinot Gris", "white", True, 100, 100),
    ],
    "alsace pinot gris vendanges tardives": [
        _v("Pinot Gris", "white", True, 100, 100),
    ],
    "alsace pinot blanc": [
        _v("Pinot Blanc", "white", True, 100, 100),
    ],
    "alsace sylvaner": [
        _v("Sylvaner", "white", True, 100, 100),
    ],
    "alsace pinot noir": [
        _v("Pinot Noir", "red", True, 100, 100),
    ],
    "alsace grand cru": [
        # Generic Grand Cru — variety depends on individual climat
        _v("Riesling", "white", True, None, None),
        _v("Gewurztraminer", "white", False, None, None),
        _v("Pinot Gris", "white", False, None, None),
        _v("Muscat Blanc à Petits Grains", "white", False, None, None),
    ],
    "alsace vendanges tardives": [
        _v("Riesling", "white", True, None, None),
        _v("Gewurztraminer", "white", False, None, None),
        _v("Pinot Gris", "white", False, None, None),
    ],
    "cremant d alsace": [
        _v("Pinot Blanc", "white", True, 50, 80),
        _v("Auxerrois", "white", False, 0, 30),
        _v("Pinot Gris", "white", False, 0, 20),
        _v("Pinot Noir", "red", False, 0, 20),
        _v("Riesling", "white", False, 0, 20),
        _v("Chardonnay", "white", False, 0, 20),
    ],

    # ═══════════════════════════════════════════════════════════════════
    # BEAUJOLAIS
    # ═══════════════════════════════════════════════════════════════════

    "beaujolais": [
        _v("Gamay", "red", True, 100, 100),
    ],
    "beaujolais villages": [
        _v("Gamay", "red", True, 100, 100),
    ],
    "beaujolais nouveau": [
        _v("Gamay", "red", True, 100, 100),
    ],

    # The 10 Beaujolais Crus
    "morgon": [
        _v("Gamay", "red", True, 100, 100),
    ],
    "fleurie": [
        _v("Gamay", "red", True, 100, 100),
    ],
    "moulin a vent": [
        _v("Gamay", "red", True, 100, 100),
    ],
    "brouilly": [
        _v("Gamay", "red", True, 100, 100),
    ],
    "cote de brouilly": [
        _v("Gamay", "red", True, 100, 100),
    ],
    "julienas": [
        _v("Gamay", "red", True, 100, 100),
    ],
    "chenas": [
        _v("Gamay", "red", True, 100, 100),
    ],
    "chiroubles": [
        _v("Gamay", "red", True, 100, 100),
    ],
    "saint amour": [
        _v("Gamay", "red", True, 100, 100),
    ],
    "regnie": [
        _v("Gamay", "red", True, 100, 100),
    ],

    # ═══════════════════════════════════════════════════════════════════
    # LANGUEDOC-ROUSSILLON
    # ═══════════════════════════════════════════════════════════════════

    "languedoc": [
        _v("Grenache", "red", True, 30, 60),
        _v("Syrah", "red", False, 20, 40),
        _v("Mourvèdre", "red", False, 10, 30),
        _v("Cinsault", "red", False, 0, 20),
        _v("Carignan", "red", False, 0, 20),
    ],
    "coteaux du languedoc": [
        _v("Grenache", "red", True, 30, 60),
        _v("Syrah", "red", False, 20, 40),
        _v("Mourvèdre", "red", False, 10, 30),
        _v("Cinsault", "red", False, 0, 20),
    ],
    "minervois": [
        _v("Grenache", "red", True, 40, 70),
        _v("Syrah", "red", False, 20, 40),
        _v("Mourvèdre", "red", False, 0, 20),
        _v("Carignan", "red", False, 0, 40),
        _v("Cinsault", "red", False, 0, 20),
    ],
    "corbieres": [
        _v("Grenache", "red", True, 30, 60),
        _v("Syrah", "red", False, 20, 40),
        _v("Mourvèdre", "red", False, 10, 30),
        _v("Carignan", "red", False, 0, 40),
        _v("Cinsault", "red", False, 0, 20),
    ],
    "faugeres": [
        _v("Grenache", "red", True, 20, 50),
        _v("Syrah", "red", False, 20, 50),
        _v("Mourvèdre", "red", False, 10, 30),
        _v("Carignan", "red", False, 0, 40),
        _v("Cinsault", "red", False, 0, 20),
    ],
    "saint chinian": [
        _v("Grenache", "red", True, 30, 60),
        _v("Syrah", "red", False, 20, 40),
        _v("Mourvèdre", "red", False, 0, 20),
        _v("Carignan", "red", False, 0, 40),
        _v("Cinsault", "red", False, 0, 20),
    ],
    "pic saint loup": [
        _v("Syrah", "red", True, 50, 70),
        _v("Grenache", "red", False, 20, 40),
        _v("Mourvèdre", "red", False, 10, 30),
    ],
    "coteaux du languedoc pic saint loup": [
        _v("Syrah", "red", True, 50, 70),
        _v("Grenache", "red", False, 20, 40),
        _v("Mourvèdre", "red", False, 10, 30),
    ],
    "pezenas": [
        _v("Grenache", "red", True, 30, 60),
        _v("Syrah", "red", False, 20, 50),
        _v("Mourvèdre", "red", False, 10, 30),
    ],

    # Roussillon
    "cotes du roussillon": [
        _v("Grenache", "red", True, 30, 60),
        _v("Syrah", "red", False, 20, 40),
        _v("Mourvèdre", "red", False, 10, 25),
        _v("Carignan", "red", False, 0, 30),
        _v("Cinsault", "red", False, 0, 20),
    ],
    "cotes du roussillon villages": [
        _v("Grenache", "red", True, 30, 60),
        _v("Syrah", "red", False, 20, 50),
        _v("Mourvèdre", "red", False, 10, 25),
        _v("Carignan", "red", False, 0, 30),
    ],
    "collioure": [
        _v("Grenache", "red", True, 30, 60),
        _v("Syrah", "red", False, 20, 40),
        _v("Mourvèdre", "red", False, 10, 25),
    ],
    "maury": [
        _v("Grenache", "red", True, 75, 100),
        _v("Syrah", "red", False, 0, 15),
        _v("Mourvèdre", "red", False, 0, 15),
    ],
    "banyuls": [
        _v("Grenache", "red", True, 75, 100),
        _v("Carignan", "red", False, 0, 15),
        _v("Syrah", "red", False, 0, 10),
    ],
    "muscat de rivesaltes": [
        _v("Muscat Blanc à Petits Grains", "white", True, 100, 100),
    ],

    # ═══════════════════════════════════════════════════════════════════
    # PROVENCE
    # ═══════════════════════════════════════════════════════════════════

    "cotes de provence": [
        _v("Grenache", "rosé", True, 20, 50),
        _v("Cinsault", "rosé", False, 20, 40),
        _v("Syrah", "rosé", False, 10, 30),
        _v("Mourvèdre", "rosé", False, 5, 20),
        _v("Vermentino", "white", False, 0, 20),
    ],
    "bandol": [
        _v("Mourvèdre", "red", True, 50, 95),
        _v("Grenache", "red", False, 5, 30),
        _v("Cinsault", "red", False, 0, 20),
        _v("Syrah", "red", False, 0, 15),
    ],
    "bandol rouge": [
        _v("Mourvèdre", "red", True, 50, 95),
        _v("Grenache", "red", False, 5, 30),
        _v("Cinsault", "red", False, 0, 20),
    ],
    "bandol blanc": [
        _v("Clairette", "white", True, 50, 100),
        _v("Ugni Blanc", "white", False, 0, 40),
        _v("Bourboulenc", "white", False, 0, 40),
    ],
    "bandol rose": [
        _v("Mourvèdre", "rosé", True, 20, 50),
        _v("Grenache", "rosé", False, 20, 40),
        _v("Cinsault", "rosé", False, 20, 40),
    ],
    "cassis": [
        _v("Marsanne", "white", True, 30, 60),
        _v("Clairette", "white", False, 20, 40),
        _v("Bourboulenc", "white", False, 10, 30),
        _v("Ugni Blanc", "white", False, 0, 20),
    ],
    "coteaux d aix en provence": [
        _v("Grenache", "red", True, 30, 60),
        _v("Syrah", "red", False, 20, 40),
        _v("Cabernet Sauvignon", "red", False, 0, 40),
        _v("Cinsault", "red", False, 0, 20),
    ],
    "les baux de provence": [
        _v("Grenache", "red", True, 30, 60),
        _v("Syrah", "red", False, 20, 40),
        _v("Cabernet Sauvignon", "red", False, 0, 40),
        _v("Mourvèdre", "red", False, 0, 20),
    ],
    "palette": [
        _v("Mourvèdre", "red", True, 30, 60),
        _v("Grenache", "red", False, 20, 40),
        _v("Cinsault", "red", False, 0, 20),
    ],

    # ═══════════════════════════════════════════════════════════════════
    # SUD-OUEST
    # ═══════════════════════════════════════════════════════════════════

    "madiran": [
        _v("Tannat", "red", True, 40, 80),
        _v("Cabernet Franc", "red", False, 10, 40),
        _v("Cabernet Sauvignon", "red", False, 0, 20),
        _v("Fer Servadou", "red", False, 0, 20),
    ],
    "cahors": [
        _v("Malbec", "red", True, 70, 100),
        _v("Merlot", "red", False, 0, 20),
        _v("Tannat", "red", False, 0, 10),
    ],
    "jurancon": [
        _v("Petit Manseng", "white", True, 50, 80),
        _v("Gros Manseng", "white", False, 20, 45),
        _v("Courbu", "white", False, 0, 15),
    ],
    "jurancon sec": [
        _v("Gros Manseng", "white", True, 50, 80),
        _v("Petit Manseng", "white", False, 20, 45),
        _v("Courbu", "white", False, 0, 15),
    ],
    "jurancon doux": [
        _v("Petit Manseng", "white", True, 60, 90),
        _v("Gros Manseng", "white", False, 10, 40),
    ],
    "pacherenc du vic bilh": [
        _v("Gros Manseng", "white", True, 40, 70),
        _v("Petit Manseng", "white", False, 20, 40),
        _v("Courbu", "white", False, 0, 20),
    ],
    "irouleguy": [
        _v("Tannat", "red", True, 50, 80),
        _v("Cabernet Franc", "red", False, 10, 40),
        _v("Cabernet Sauvignon", "red", False, 0, 20),
    ],
    "gaillac": [
        _v("Mauzac", "white", True, 40, 80),
        _v("Len de l'El", "white", False, 0, 40),
        _v("Sauvignon Blanc", "white", False, 0, 20),
        _v("Duras", "red", False, 0, 30),
        _v("Syrah", "red", False, 0, 20),
    ],
    "bergerac": [
        _v("Merlot", "red", True, 50, 75),
        _v("Cabernet Franc", "red", False, 15, 35),
        _v("Cabernet Sauvignon", "red", False, 5, 25),
    ],
    "bergerac rouge": [
        _v("Merlot", "red", True, 50, 75),
        _v("Cabernet Franc", "red", False, 15, 35),
        _v("Cabernet Sauvignon", "red", False, 5, 25),
    ],
    "bergerac sec": [
        _v("Sauvignon Blanc", "white", True, 50, 80),
        _v("Sémillon", "white", False, 15, 40),
        _v("Muscadelle", "white", False, 0, 10),
    ],
    "monbazillac": [
        _v("Sémillon", "white", True, 50, 80),
        _v("Sauvignon Blanc", "white", False, 15, 35),
        _v("Muscadelle", "white", False, 0, 15),
    ],
    "pecharmant": [
        _v("Merlot", "red", True, 40, 60),
        _v("Cabernet Franc", "red", False, 20, 40),
        _v("Cabernet Sauvignon", "red", False, 10, 30),
    ],

    # ═══════════════════════════════════════════════════════════════════
    # JURA / SAVOIE
    # ═══════════════════════════════════════════════════════════════════

    "arbois": [
        _v("Savagnin", "white", True, 30, 60),
        _v("Poulsard", "red", False, 20, 40),
        _v("Trousseau", "red", False, 0, 30),
        _v("Pinot Noir", "red", False, 0, 20),
    ],
    "cotes du jura": [
        _v("Savagnin", "white", True, 30, 60),
        _v("Chardonnay", "white", False, 20, 50),
        _v("Poulsard", "red", False, 0, 30),
        _v("Trousseau", "red", False, 0, 20),
    ],
    "vin jaune": [
        _v("Savagnin", "white", True, 100, 100),
    ],
    "chateau chalon": [
        _v("Savagnin", "white", True, 100, 100),
    ],
    "cremant du jura": [
        _v("Chardonnay", "white", True, 50, 80),
        _v("Pinot Noir", "red", False, 0, 30),
        _v("Poulsard", "red", False, 0, 20),
        _v("Trousseau", "red", False, 0, 10),
    ],
    "bugey": [
        _v("Chardonnay", "white", True, 50, 80),
        _v("Altesse", "white", False, 0, 30),
        _v("Gamay", "red", False, 0, 30),
        _v("Pinot Noir", "red", False, 0, 30),
    ],
    "seyssel": [
        _v("Altesse", "white", True, 100, 100),
    ],
    "roussette de savoie": [
        _v("Altesse", "white", True, 100, 100),
    ],
    "vin de savoie": [
        _v("Jacquère", "white", True, 40, 70),
        _v("Altesse", "white", False, 0, 30),
        _v("Chardonnay", "white", False, 0, 20),
        _v("Mondeuse", "red", False, 0, 30),
    ],

    # ═══════════════════════════════════════════════════════════════════
    # CORSICA
    # ═══════════════════════════════════════════════════════════════════

    "ajaccio": [
        _v("Nielluccio", "red", True, 40, 80),
        _v("Grenache", "red", False, 0, 30),
        _v("Sciaccarello", "red", False, 0, 40),
    ],
    "patrimonio": [
        _v("Nielluccio", "red", True, 75, 100),
        _v("Grenache", "red", False, 0, 15),
    ],

    # ═══════════════════════════════════════════════════════════════════
    # GENERIC / CATCH-ALL
    # ═══════════════════════════════════════════════════════════════════

    "vin de france": [],   # Too generic — no default mapping
    "igp pays d oc": [
        _v("Syrah", "red", True, None, None),
        _v("Grenache", "red", False, None, None),
        _v("Merlot", "red", False, None, None),
        _v("Cabernet Sauvignon", "red", False, None, None),
        _v("Chardonnay", "white", False, None, None),
        _v("Viognier", "white", False, None, None),
    ],
}

# Populate a few aliases for common norm-text variants in the DB
_ALIASES: dict[str, str] = {
    # Alsace variety-named appellations with alternate norms
    "cremant d alsace": "cremant d alsace",
    # Blank de blancs / noirs
    "blanc de blancs": "champagne blanc de blancs",
    "blanc de noirs": "champagne blanc de noirs",
    # Languedoc synonym
    "languedoc": "languedoc",
    # Ensure norm-text variant "chateauneuf du pape" covers accent-stripped form
    "chateauneuf du pape": "chateauneuf du pape",
    # Saint-Émilion Grand Cru alias
    "saint emilion grand cru classe": "saint emilion grand cru classe",
    # Moulin-à-Vent without accent
    "moulin a vent": "moulin a vent",
}


def get_varieties_for_appellation(appellation_norm: str) -> list[dict]:
    """Return variety dicts for a given appellation_norm (norm_text key).

    Returns an empty list if no mapping is found (caller should handle gracefully).
    Looks up both the exact key and a norm_text() re-normalization of the input.
    """
    if not appellation_norm:
        return []
    key = appellation_norm.strip()
    result = APPELLATION_VARIETIES.get(key)
    if result is not None:
        return result
    # Try re-normalizing in case caller passed un-normalized text
    rekey = norm_text(key)
    return APPELLATION_VARIETIES.get(rekey, [])


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def ensure_variety_in_db(
    conn: sqlite3.Connection,
    variety_name: str,
    color_family: str,
) -> Optional[int]:
    """Insert variety into dim_variety if absent. Returns variety_key."""
    variety_norm = norm_text(variety_name)
    if not variety_norm:
        return None
    row = conn.execute(
        "SELECT variety_key FROM dim_variety WHERE variety_norm = ?",
        (variety_norm,),
    ).fetchone()
    if row:
        return row[0]
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO dim_variety (variety_name, variety_norm, color_family) VALUES (?, ?, ?)",
            (variety_name, variety_norm, color_family),
        )
        conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
        row = conn.execute(
            "SELECT variety_key FROM dim_variety WHERE variety_norm = ?",
            (variety_norm,),
        ).fetchone()
        return row[0] if row else None
    except Exception:
        return None


def upsert_bridge_wine_variety(
    conn: sqlite3.Connection,
    wine_key: str,
    variety_key: int,
    share_pct: Optional[float] = None,
    source_confidence: Optional[float] = None,
) -> bool:
    """Idempotent INSERT OR REPLACE into bridge_wine_variety.

    Args:
        conn: SQLite connection.
        wine_key: FK to dim_wine.
        variety_key: FK to dim_variety.
        share_pct: Optional % share (e.g. 80.0 for 80%).
        source_confidence: Optional 0-1 confidence float.

    Returns:
        True on success, False on error.
    """
    if not wine_key or not variety_key:
        return False
    try:
        conn.execute(
            """INSERT INTO bridge_wine_variety (wine_key, variety_key, share_pct, source_confidence)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(wine_key, variety_key) DO UPDATE SET
                 share_pct = excluded.share_pct,
                 source_confidence = excluded.source_confidence""",
            (wine_key, variety_key, share_pct, source_confidence),
        )
        conn.commit()
        return True
    except Exception:
        return False
