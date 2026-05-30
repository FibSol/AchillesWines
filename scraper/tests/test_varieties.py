"""
Tests for scraper/achilles_scraper/varieties.py — issue #42.

Covers:
- get_varieties_for_appellation returns correct grapes for key appellations
- Unknown appellation returns empty list (no crash)
- upsert_bridge_wine_variety is idempotent (two identical inserts = 1 row)
- Bridge rows have correct is_primary flag reflected through share_pct/confidence
- ensure_variety_in_db creates and deduplicates variety rows
- All APPELLATION_VARIETIES entries are valid dicts with required keys
"""
from __future__ import annotations

import sqlite3
import pytest

# The module under test
from achilles_scraper.varieties import (
    APPELLATION_VARIETIES,
    get_varieties_for_appellation,
    ensure_variety_in_db,
    upsert_bridge_wine_variety,
)
from achilles_scraper.identity import norm_text


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mem_db() -> sqlite3.Connection:
    """In-memory SQLite DB with the minimal tables needed by the variety module."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE dim_variety (
            variety_key  INTEGER PRIMARY KEY AUTOINCREMENT,
            variety_name TEXT NOT NULL,
            variety_norm TEXT NOT NULL UNIQUE,
            color_family TEXT NOT NULL
        );
        CREATE TABLE dim_wine (
            wine_key TEXT PRIMARY KEY,
            producer_key INTEGER NOT NULL DEFAULT 1,
            appellation_key INTEGER NOT NULL DEFAULT 1,
            cuvee_name TEXT NOT NULL,
            cuvee_norm TEXT NOT NULL,
            color TEXT NOT NULL,
            vintage INTEGER,
            is_non_vintage INTEGER NOT NULL DEFAULT 0,
            bottle_ml INTEGER NOT NULL DEFAULT 750,
            canonical_name TEXT NOT NULL
        );
        CREATE TABLE bridge_wine_variety (
            wine_key     TEXT NOT NULL,
            variety_key  INTEGER NOT NULL,
            share_pct    REAL,
            source_confidence REAL,
            PRIMARY KEY (wine_key, variety_key)
        );
        -- Insert a dummy wine so FK constraints are satisfied
        INSERT INTO dim_wine (wine_key, cuvee_name, cuvee_norm, color, vintage, is_non_vintage, canonical_name)
        VALUES ('test_wine_key', 'Test Cuvée', 'test cuvee', 'red', 2020, 0, 'Test Cuvée 2020');
        """
    )
    return conn


# ---------------------------------------------------------------------------
# 1. get_varieties_for_appellation — correct grapes returned
# ---------------------------------------------------------------------------

class TestGetVarietiesForAppellation:
    def test_meursault_is_chardonnay(self):
        """Meursault → 100% Chardonnay (white Burgundy)."""
        varieties = get_varieties_for_appellation("meursault")
        assert len(varieties) >= 1
        norms = [v["variety_norm"] for v in varieties]
        assert "chardonnay" in norms, f"Expected chardonnay in {norms}"
        # Primary grape is Chardonnay
        primary = [v for v in varieties if v["is_primary"]]
        assert len(primary) == 1
        assert primary[0]["variety_norm"] == "chardonnay"

    def test_gevrey_chambertin_is_pinot_noir(self):
        """Gevrey-Chambertin → 100% Pinot Noir (red Burgundy)."""
        varieties = get_varieties_for_appellation("gevrey chambertin")
        norms = [v["variety_norm"] for v in varieties]
        assert "pinot noir" in norms
        primary = [v for v in varieties if v["is_primary"]]
        assert primary[0]["variety_norm"] == "pinot noir"

    def test_chateauneuf_du_pape_grenache_primary(self):
        """Châteauneuf-du-Pape → Grenache primary with Syrah, Mourvèdre secondary."""
        varieties = get_varieties_for_appellation("chateauneuf du pape")
        norms = [v["variety_norm"] for v in varieties]
        assert "grenache" in norms
        assert len(varieties) >= 3  # multiple grapes
        primary = [v for v in varieties if v["is_primary"]]
        assert primary[0]["variety_norm"] == "grenache"
        # Syrah and Mourvèdre are secondary
        secondary = [v for v in varieties if not v["is_primary"]]
        secondary_norms = [v["variety_norm"] for v in secondary]
        assert "syrah" in secondary_norms

    def test_champagne_three_main_grapes(self):
        """Champagne → blend of Pinot Noir, Chardonnay, Pinot Meunier."""
        varieties = get_varieties_for_appellation("champagne")
        norms = [v["variety_norm"] for v in varieties]
        assert "pinot noir" in norms
        assert "chardonnay" in norms
        assert "pinot meunier" in norms
        assert len(varieties) >= 3

    def test_bordeaux_rouge_merlot_cabernet(self):
        """Bordeaux → Merlot primary, Cabernet Sauvignon secondary."""
        varieties = get_varieties_for_appellation("bordeaux")
        norms = [v["variety_norm"] for v in varieties]
        assert "merlot" in norms
        assert "cabernet sauvignon" in norms
        primary = [v for v in varieties if v["is_primary"]]
        assert primary[0]["variety_norm"] == "merlot"

    def test_pauillac_cabernet_sauvignon_primary(self):
        """Pauillac → Cabernet Sauvignon primary."""
        varieties = get_varieties_for_appellation("pauillac")
        primary = [v for v in varieties if v["is_primary"]]
        assert primary[0]["variety_norm"] == "cabernet sauvignon"

    def test_sancerre_sauvignon_blanc(self):
        """Sancerre blanc → Sauvignon Blanc 100%."""
        varieties = get_varieties_for_appellation("sancerre")
        norms = [v["variety_norm"] for v in varieties]
        assert "sauvignon blanc" in norms

    def test_beaujolais_gamay(self):
        """Beaujolais → Gamay 100%."""
        varieties = get_varieties_for_appellation("beaujolais")
        norms = [v["variety_norm"] for v in varieties]
        assert "gamay" in norms
        primary = [v for v in varieties if v["is_primary"]]
        assert primary[0]["variety_norm"] == "gamay"

    def test_morgon_gamay(self):
        """Morgon (Beaujolais cru) → Gamay 100%."""
        varieties = get_varieties_for_appellation("morgon")
        norms = [v["variety_norm"] for v in varieties]
        assert "gamay" in norms

    def test_alsace_riesling_is_riesling(self):
        """Alsace Riesling appellation → Riesling 100%."""
        varieties = get_varieties_for_appellation("alsace riesling")
        assert len(varieties) == 1
        assert varieties[0]["variety_norm"] == "riesling"
        assert varieties[0]["is_primary"] is True

    def test_chablis_chardonnay(self):
        """Chablis → Chardonnay 100%."""
        varieties = get_varieties_for_appellation("chablis")
        assert len(varieties) == 1
        assert varieties[0]["variety_norm"] == "chardonnay"

    def test_madiran_tannat(self):
        """Madiran → Tannat primary."""
        varieties = get_varieties_for_appellation("madiran")
        primary = [v for v in varieties if v["is_primary"]]
        assert primary[0]["variety_norm"] == "tannat"

    def test_cahors_malbec(self):
        """Cahors → Malbec primary (minimum 70%)."""
        varieties = get_varieties_for_appellation("cahors")
        primary = [v for v in varieties if v["is_primary"]]
        assert primary[0]["variety_norm"] == "malbec"
        assert primary[0]["pct_min"] >= 70

    def test_bandol_mourvedre_primary(self):
        """Bandol rouge → Mourvèdre primary (minimum 50%)."""
        varieties = get_varieties_for_appellation("bandol")
        primary = [v for v in varieties if v["is_primary"]]
        assert primary[0]["variety_norm"] == norm_text("Mourvèdre")
        assert primary[0]["pct_min"] >= 50

    def test_cote_rotie_syrah_viognier(self):
        """Côte-Rôtie → Syrah primary with optional Viognier (white co-ferment)."""
        varieties = get_varieties_for_appellation("cote rotie")
        norms = [v["variety_norm"] for v in varieties]
        assert "syrah" in norms
        assert "viognier" in norms

    def test_condrieu_viognier_only(self):
        """Condrieu → Viognier 100%."""
        varieties = get_varieties_for_appellation("condrieu")
        assert len(varieties) == 1
        assert varieties[0]["variety_norm"] == "viognier"

    def test_sauternes_semillon_primary(self):
        """Sauternes → Sémillon primary."""
        varieties = get_varieties_for_appellation("sauternes")
        primary = [v for v in varieties if v["is_primary"]]
        assert primary[0]["variety_norm"] == norm_text("Sémillon")

    def test_champagne_blanc_de_blancs_chardonnay_only(self):
        """Champagne Blanc de Blancs → Chardonnay only."""
        varieties = get_varieties_for_appellation("champagne blanc de blancs")
        assert len(varieties) == 1
        assert varieties[0]["variety_norm"] == "chardonnay"

    def test_vouvray_chenin_blanc(self):
        """Vouvray → Chenin Blanc 100%."""
        varieties = get_varieties_for_appellation("vouvray")
        assert len(varieties) == 1
        assert varieties[0]["variety_norm"] == "chenin blanc"


# ---------------------------------------------------------------------------
# 2. Unknown appellation → empty list, no crash
# ---------------------------------------------------------------------------

class TestUnknownAppellation:
    def test_unknown_returns_empty(self):
        result = get_varieties_for_appellation("xyzzy not a real appellation")
        assert result == []

    def test_empty_string_returns_empty(self):
        result = get_varieties_for_appellation("")
        assert result == []

    def test_none_like_empty_does_not_crash(self):
        # norm_text handles None-ish by treating as empty string
        result = get_varieties_for_appellation("   ")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 3. upsert_bridge_wine_variety — idempotency
# ---------------------------------------------------------------------------

class TestUpsertBridgeWineVariety:
    def test_insert_creates_row(self, mem_db):
        vk = ensure_variety_in_db(mem_db, "Pinot Noir", "red")
        assert vk is not None
        ok = upsert_bridge_wine_variety(mem_db, "test_wine_key", vk, 80.0, 0.6)
        assert ok is True
        count = mem_db.execute("SELECT COUNT(*) FROM bridge_wine_variety").fetchone()[0]
        assert count == 1

    def test_double_insert_is_idempotent(self, mem_db):
        vk = ensure_variety_in_db(mem_db, "Chardonnay", "white")
        upsert_bridge_wine_variety(mem_db, "test_wine_key", vk, 90.0, 0.7)
        upsert_bridge_wine_variety(mem_db, "test_wine_key", vk, 90.0, 0.7)
        count = mem_db.execute("SELECT COUNT(*) FROM bridge_wine_variety").fetchone()[0]
        assert count == 1  # still only one row

    def test_upsert_updates_existing(self, mem_db):
        """Second upsert with new values should update, not duplicate."""
        vk = ensure_variety_in_db(mem_db, "Merlot", "red")
        upsert_bridge_wine_variety(mem_db, "test_wine_key", vk, 60.0, 0.5)
        upsert_bridge_wine_variety(mem_db, "test_wine_key", vk, 70.0, 0.6)
        count = mem_db.execute("SELECT COUNT(*) FROM bridge_wine_variety").fetchone()[0]
        assert count == 1
        row = mem_db.execute(
            "SELECT share_pct, source_confidence FROM bridge_wine_variety WHERE wine_key = ?",
            ("test_wine_key",),
        ).fetchone()
        assert row[0] == pytest.approx(70.0)
        assert row[1] == pytest.approx(0.6)

    def test_multiple_varieties_for_same_wine(self, mem_db):
        """A blend wine can have multiple variety rows."""
        vk1 = ensure_variety_in_db(mem_db, "Cabernet Sauvignon", "red")
        vk2 = ensure_variety_in_db(mem_db, "Cabernet Franc", "red")
        upsert_bridge_wine_variety(mem_db, "test_wine_key", vk1, 70.0, 0.6)
        upsert_bridge_wine_variety(mem_db, "test_wine_key", vk2, 30.0, 0.5)
        count = mem_db.execute("SELECT COUNT(*) FROM bridge_wine_variety").fetchone()[0]
        assert count == 2

    def test_invalid_empty_wine_key_returns_false(self, mem_db):
        vk = ensure_variety_in_db(mem_db, "Grenache", "red")
        result = upsert_bridge_wine_variety(mem_db, "", vk, None, None)
        assert result is False

    def test_none_variety_key_returns_false(self, mem_db):
        result = upsert_bridge_wine_variety(mem_db, "test_wine_key", None, None, None)
        assert result is False


# ---------------------------------------------------------------------------
# 4. Bridge row is_primary reflected via confidence
# ---------------------------------------------------------------------------

class TestIsPrimaryFlagConfidence:
    def test_primary_variety_higher_confidence(self, mem_db):
        """Primary varieties should get higher confidence than secondary ones."""
        vk_primary = ensure_variety_in_db(mem_db, "Pinot Noir", "red")
        vk_secondary = ensure_variety_in_db(mem_db, "Gamay", "red")

        # Simulate what the population script does
        upsert_bridge_wine_variety(mem_db, "test_wine_key", vk_primary, 90.0, 0.60)
        upsert_bridge_wine_variety(mem_db, "test_wine_key", vk_secondary, 10.0, 0.48)

        rows = mem_db.execute(
            "SELECT variety_key, source_confidence FROM bridge_wine_variety ORDER BY source_confidence DESC"
        ).fetchall()
        assert rows[0][0] == vk_primary
        assert rows[0][1] > rows[1][1]


# ---------------------------------------------------------------------------
# 5. ensure_variety_in_db
# ---------------------------------------------------------------------------

class TestEnsureVarietyInDb:
    def test_creates_new_variety(self, mem_db):
        vk = ensure_variety_in_db(mem_db, "Sauvignon Blanc", "white")
        assert vk is not None
        row = mem_db.execute(
            "SELECT variety_name, variety_norm, color_family FROM dim_variety WHERE variety_key = ?", (vk,)
        ).fetchone()
        assert row[0] == "Sauvignon Blanc"
        assert row[1] == "sauvignon blanc"
        assert row[2] == "white"

    def test_idempotent_returns_same_key(self, mem_db):
        vk1 = ensure_variety_in_db(mem_db, "Syrah", "red")
        vk2 = ensure_variety_in_db(mem_db, "Syrah", "red")
        assert vk1 == vk2
        count = mem_db.execute("SELECT COUNT(*) FROM dim_variety WHERE variety_norm='syrah'").fetchone()[0]
        assert count == 1

    def test_empty_name_returns_none(self, mem_db):
        result = ensure_variety_in_db(mem_db, "", "red")
        assert result is None


# ---------------------------------------------------------------------------
# 6. APPELLATION_VARIETIES structural integrity
# ---------------------------------------------------------------------------

class TestAppellationVarietiesStructure:
    def test_all_entries_are_lists(self):
        for key, varieties in APPELLATION_VARIETIES.items():
            assert isinstance(varieties, list), f"Key {key!r} should map to a list"

    def test_all_variety_dicts_have_required_keys(self):
        required = {"variety_norm", "variety_name", "color_family", "is_primary", "pct_min", "pct_max"}
        for key, varieties in APPELLATION_VARIETIES.items():
            for v in varieties:
                missing = required - set(v.keys())
                assert not missing, f"Appellation {key!r} variety dict missing keys: {missing}"

    def test_variety_norms_are_lowercase(self):
        for key, varieties in APPELLATION_VARIETIES.items():
            for v in varieties:
                assert v["variety_norm"] == v["variety_norm"].lower(), (
                    f"Appellation {key!r}: variety_norm {v['variety_norm']!r} is not lowercase"
                )

    def test_is_primary_is_bool(self):
        for key, varieties in APPELLATION_VARIETIES.items():
            for v in varieties:
                assert isinstance(v["is_primary"], bool), (
                    f"Appellation {key!r}: is_primary should be bool, got {type(v['is_primary'])}"
                )

    def test_color_family_valid_values(self):
        valid = {"red", "white", "rosé", "other"}
        for key, varieties in APPELLATION_VARIETIES.items():
            for v in varieties:
                assert v["color_family"] in valid, (
                    f"Appellation {key!r}: invalid color_family {v['color_family']!r}"
                )

    def test_pct_range_valid(self):
        for key, varieties in APPELLATION_VARIETIES.items():
            for v in varieties:
                lo = v["pct_min"]
                hi = v["pct_max"]
                if lo is not None and hi is not None:
                    assert 0 <= lo <= 100, f"Appellation {key!r}: pct_min={lo} out of range"
                    assert 0 <= hi <= 100, f"Appellation {key!r}: pct_max={hi} out of range"
                    assert lo <= hi, f"Appellation {key!r}: pct_min > pct_max"

    def test_at_least_one_primary_per_non_empty_appellation(self):
        """Every non-empty appellation entry must have at least one primary variety."""
        for key, varieties in APPELLATION_VARIETIES.items():
            if not varieties:
                continue
            has_primary = any(v["is_primary"] for v in varieties)
            assert has_primary, f"Appellation {key!r} has no primary variety"

    def test_minimum_appellation_coverage(self):
        """Verify all required appellations from the issue are covered."""
        required_appellations = [
            # Burgundy
            "meursault", "puligny montrachet", "chassagne montrachet",
            "chablis", "gevrey chambertin", "chambolle musigny", "vosne romanee",
            "nuits saint georges", "pommard", "volnay", "bourgogne", "cremant de bourgogne", "macon",
            # Bordeaux
            "pauillac", "margaux", "saint julien", "saint estephe",
            "saint emilion", "pomerol", "pessac leognan", "pessac leognan rouge",
            "pessac leognan blanc", "sauternes", "barsac", "graves",
            "medoc", "haut medoc", "entre deux mers",
            # Champagne
            "champagne", "champagne blanc de blancs", "champagne blanc de noirs",
            # Loire
            "sancerre", "pouilly fume", "muscadet", "vouvray",
            "chinon", "bourgueil", "anjou",
            # Rhône
            "chateauneuf du pape", "cote rotie", "hermitage",
            "crozes hermitage", "saint joseph", "gigondas", "vacqueyras",
            "condrieu", "cotes du rhone",
            # Alsace
            "alsace riesling", "alsace gewurztraminer", "alsace pinot gris",
            "alsace sylvaner", "cremant d alsace", "alsace grand cru",
            # Beaujolais
            "beaujolais", "beaujolais villages",
            "morgon", "fleurie", "moulin a vent", "brouilly", "cote de brouilly",
            "julienas", "chenas", "chiroubles", "saint amour", "regnie",
            # Languedoc
            "minervois", "corbieres", "faugeres", "saint chinian", "pic saint loup",
            # Roussillon
            "cotes du roussillon",
            # Provence
            "cotes de provence", "bandol", "cassis",
            # Sud-Ouest
            "madiran", "cahors", "jurancon", "gaillac", "bergerac",
        ]
        missing = [a for a in required_appellations if a not in APPELLATION_VARIETIES]
        assert not missing, f"Missing appellation coverage for: {missing}"
