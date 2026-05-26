"""
Tests for achilles_scraper.llm_parser (ADR-011 LLM fallback parser).

All tests use mocks — no real Anthropic API calls are made.
"""
from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from achilles_scraper.email_parser import EmailOffer
from achilles_scraper.llm_parser import (
    MAX_TEXT_CHARS,
    _parse_llm_response,
    _strip_html,
    parse_with_llm,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_anthropic_response(text: str) -> MagicMock:
    """Build a mock Anthropic messages.create() return value."""
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


VALID_LLM_JSON = json.dumps([
    {
        "producer": "Domaine Leflaive",
        "cuvee": "Puligny-Montrachet 1er Cru Les Pucelles",
        "vintage": 2018,
        "price_eur": 149.90,
        "bottle_ml": 750,
        "source_url": "https://example.com/wine/123",
    },
    {
        "producer": "Chateau Margaux",
        "cuvee": "Grand Vin",
        "vintage": 2015,
        "price_eur": 599.00,
        "bottle_ml": 750,
        "source_url": None,
    },
])


# ---------------------------------------------------------------------------
# 1. Returns [] when ANTHROPIC_API_KEY is not set
# ---------------------------------------------------------------------------

def test_returns_empty_when_no_api_key():
    """parse_with_llm must return [] when ANTHROPIC_API_KEY is absent from env."""
    env_without_key = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    with patch.dict(os.environ, env_without_key, clear=True):
        result = parse_with_llm("<p>Some newsletter</p>", "millesima_email")
    assert result == []


# ---------------------------------------------------------------------------
# 2. Parses a well-formed LLM JSON response
# ---------------------------------------------------------------------------

def test_parses_well_formed_response():
    """_parse_llm_response should produce correctly-typed EmailOffer objects."""
    offers = _parse_llm_response(VALID_LLM_JSON, "millesima_email")
    assert len(offers) == 2

    first = offers[0]
    assert isinstance(first, EmailOffer)
    assert first.producer_name == "Domaine Leflaive"
    assert first.cuvee_name == "Puligny-Montrachet 1er Cru Les Pucelles"
    assert first.vintage == 2018
    assert first.price_eur == 149.90
    assert first.bottle_ml == 750
    assert first.source_url == "https://example.com/wine/123"

    second = offers[1]
    assert second.producer_name == "Chateau Margaux"
    assert second.vintage == 2015
    assert second.source_url is None


# ---------------------------------------------------------------------------
# 3. Malformed JSON returns [] safely
# ---------------------------------------------------------------------------

def test_malformed_json_returns_empty():
    """_parse_llm_response should return [] for invalid JSON without raising."""
    assert _parse_llm_response("not valid json {{", "test_source") == []
    assert _parse_llm_response("", "test_source") == []
    assert _parse_llm_response("{}", "test_source") == []


# ---------------------------------------------------------------------------
# 4. Text truncation at MAX_TEXT_CHARS
# ---------------------------------------------------------------------------

def test_text_truncation():
    """_strip_html must truncate plain text to MAX_TEXT_CHARS characters."""
    long_html = "<p>" + "A" * (MAX_TEXT_CHARS + 500) + "</p>"
    result = _strip_html(long_html)
    assert len(result) <= MAX_TEXT_CHARS


def test_text_truncation_preserves_content():
    """Truncation should keep the first MAX_TEXT_CHARS chars, not the tail."""
    prefix = "Important wine offer: "
    filler = "X" * (MAX_TEXT_CHARS + 1000)
    html = f"<p>{prefix}{filler}</p>"
    result = _strip_html(html)
    assert result.startswith(prefix.strip())
    assert len(result) <= MAX_TEXT_CHARS


# ---------------------------------------------------------------------------
# 5. Valid parsed offer has correct types
# ---------------------------------------------------------------------------

def test_offer_types():
    """Parsed offers must have correct Python types for each field."""
    offers = _parse_llm_response(VALID_LLM_JSON, "test_source")
    assert len(offers) >= 1
    for offer in offers:
        assert isinstance(offer.producer_name, str)
        assert isinstance(offer.cuvee_name, str)
        assert offer.vintage is None or isinstance(offer.vintage, int)
        assert isinstance(offer.price_eur, float)
        assert isinstance(offer.bottle_ml, int)
        assert offer.source_url is None or isinstance(offer.source_url, str)


# ---------------------------------------------------------------------------
# 6. parse_with_llm calls the API and returns offers on success
# ---------------------------------------------------------------------------

def test_parse_with_llm_calls_api_and_returns_offers():
    """parse_with_llm should call Anthropic API and return parsed offers."""
    html = "<p>Domaine Leflaive – Puligny-Montrachet 1er Cru 2018 – 149,90 €</p>"
    mock_response = _make_anthropic_response(VALID_LLM_JSON)

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    MockAnthropic = MagicMock(return_value=mock_client)

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
        with patch.dict("sys.modules", {"anthropic": MagicMock(Anthropic=MockAnthropic)}):
            offers = parse_with_llm(html, "millesima_email")

    assert len(offers) == 2
    assert offers[0].producer_name == "Domaine Leflaive"
    mock_client.messages.create.assert_called_once()


# ---------------------------------------------------------------------------
# 7. API error returns [] gracefully
# ---------------------------------------------------------------------------

def test_api_error_returns_empty():
    """parse_with_llm must return [] (not raise) if the API call throws."""
    html = "<p>Some newsletter content</p>"

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("API rate limit exceeded")
    MockAnthropic = MagicMock(return_value=mock_client)

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
        with patch.dict("sys.modules", {"anthropic": MagicMock(Anthropic=MockAnthropic)}):
            result = parse_with_llm(html, "idealwine_email")

    assert result == []


# ---------------------------------------------------------------------------
# 8. Items without producer or cuvee are skipped
# ---------------------------------------------------------------------------

def test_items_missing_producer_or_cuvee_skipped():
    """_parse_llm_response should skip items where producer or cuvee is empty."""
    bad_items = json.dumps([
        {"producer": "", "cuvee": "Some wine", "price_eur": 25.0},
        {"producer": "Domaine X", "cuvee": "", "price_eur": 25.0},
        {"producer": "Domaine Y", "cuvee": "Good wine", "price_eur": 30.0},
    ])
    offers = _parse_llm_response(bad_items, "test_source")
    assert len(offers) == 1
    assert offers[0].producer_name == "Domaine Y"


# ---------------------------------------------------------------------------
# 9. Items with non-positive price are skipped
# ---------------------------------------------------------------------------

def test_non_positive_price_skipped():
    """_parse_llm_response should drop items with price_eur <= 0."""
    data = json.dumps([
        {"producer": "Dom A", "cuvee": "Wine A", "vintage": 2020, "price_eur": 0},
        {"producer": "Dom B", "cuvee": "Wine B", "vintage": 2019, "price_eur": -5.0},
        {"producer": "Dom C", "cuvee": "Wine C", "vintage": 2018, "price_eur": 45.0},
    ])
    offers = _parse_llm_response(data, "test_source")
    assert len(offers) == 1
    assert offers[0].producer_name == "Dom C"


# ---------------------------------------------------------------------------
# 10. Markdown code fences are stripped before JSON parse
# ---------------------------------------------------------------------------

def test_markdown_fences_stripped():
    """_parse_llm_response should handle LLM responses wrapped in ```json ... ```."""
    fenced = "```json\n" + VALID_LLM_JSON + "\n```"
    offers = _parse_llm_response(fenced, "test_source")
    assert len(offers) == 2


# ---------------------------------------------------------------------------
# 11. Vintage out of range is set to None
# ---------------------------------------------------------------------------

def test_vintage_out_of_range_is_none():
    """Vintages outside 1950–2099 should be normalised to None."""
    data = json.dumps([
        {"producer": "Dom A", "cuvee": "Wine A", "vintage": 1800, "price_eur": 30.0},
    ])
    offers = _parse_llm_response(data, "test_source")
    assert len(offers) == 1
    assert offers[0].vintage is None


# ---------------------------------------------------------------------------
# 12. Default bottle size is 750 when absent
# ---------------------------------------------------------------------------

def test_default_bottle_ml():
    """Offers without bottle_ml should default to 750."""
    data = json.dumps([
        {"producer": "Dom A", "cuvee": "Wine A", "vintage": 2020, "price_eur": 30.0},
    ])
    offers = _parse_llm_response(data, "test_source")
    assert len(offers) == 1
    assert offers[0].bottle_ml == 750
