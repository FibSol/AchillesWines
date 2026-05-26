"""
LLM fallback parser (ADR-011 extension).

When the heuristic email parser extracts 0 offers, and the source has
`use_llm_fallback=1`, this module retries using Claude claude-haiku-4-5 to extract
structured wine offer data from the newsletter plain text.

Cost estimate: ~$0.0025 per email (Haiku input+output at current rates).
Prompt caching is used on the system prompt to reduce repeat costs.

Usage:
    from achilles_scraper.llm_parser import parse_with_llm
    offers = parse_with_llm(html, source_code="millesima_email")
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

from .email_parser import EmailOffer

logger = logging.getLogger(__name__)

# Maximum characters of plain text sent to the LLM (newsletters can be huge).
MAX_TEXT_CHARS = 4000

# Haiku model — cheapest, fast enough for newsletter parsing.
HAIKU_MODEL = "claude-haiku-4-5"

# System prompt — stable across calls so prompt caching applies.
_SYSTEM_PROMPT = """You are a wine offer extractor. Given plain text from a wine newsletter, extract all wine offers mentioned.

Return a JSON array only — no prose, no markdown fences. Each element must have:
  - "producer": string — producer / domaine name (e.g. "Domaine Leflaive")
  - "cuvee": string — cuvée / wine name without the vintage (e.g. "Puligny-Montrachet 1er Cru Les Pucelles")
  - "vintage": integer or null — harvest year (e.g. 2018) or null for non-vintage
  - "price_eur": number — price in euros as a float (e.g. 49.90)
  - "bottle_ml": integer — bottle size in ml, default 750 if not stated
  - "source_url": string or null — product page URL if present in the text

Rules:
- Only include offers where both producer and cuvée are clearly identifiable.
- If price is ambiguous or missing, omit that offer.
- Do not invent or hallucinate data not present in the text.
- If no offers are found, return an empty array: []
- Respond with ONLY the JSON array, nothing else."""


def _strip_html(html: str) -> str:
    """Strip HTML tags and return plain text, truncated to MAX_TEXT_CHARS."""
    try:
        from selectolax.parser import HTMLParser
        tree = HTMLParser(html)
        text = tree.text(separator=" ", strip=True)
    except Exception:
        # Fallback: crude regex tag strip
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_TEXT_CHARS]


def _parse_llm_response(response_text: str, source_code: str) -> list[EmailOffer]:
    """Parse Claude's JSON response into EmailOffer objects. Returns [] on any error."""
    raw = response_text.strip()
    # Strip markdown code fences if the model added them despite instructions.
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("[llm_parser] %s: JSON decode error: %s", source_code, exc)
        return []

    if not isinstance(data, list):
        logger.warning("[llm_parser] %s: expected list, got %s", source_code, type(data).__name__)
        return []

    offers: list[EmailOffer] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            producer = str(item.get("producer") or "").strip()
            cuvee = str(item.get("cuvee") or "").strip()
            if not producer or not cuvee:
                continue

            raw_price = item.get("price_eur")
            if raw_price is None:
                continue
            price_eur = float(raw_price)
            if price_eur <= 0:
                continue

            raw_vintage = item.get("vintage")
            vintage: Optional[int] = None
            if raw_vintage is not None:
                try:
                    v = int(raw_vintage)
                    if 1950 <= v <= 2099:
                        vintage = v
                except (ValueError, TypeError):
                    pass

            raw_ml = item.get("bottle_ml")
            bottle_ml = 750
            if raw_ml is not None:
                try:
                    bottle_ml = int(raw_ml)
                except (ValueError, TypeError):
                    bottle_ml = 750

            source_url = item.get("source_url") or None
            if source_url:
                source_url = str(source_url).strip() or None

            offers.append(EmailOffer(
                producer_name=producer,
                cuvee_name=cuvee,
                vintage=vintage,
                bottle_ml=bottle_ml,
                price_eur=price_eur,
                source_url=source_url,
                raw_anchor_text=f"[llm] {producer} {cuvee}",
            ))
        except (KeyError, ValueError, TypeError) as exc:
            logger.debug("[llm_parser] %s: skipping malformed item %r: %s", source_code, item, exc)
            continue

    return offers


def parse_with_llm(html: str, source_code: str) -> list[EmailOffer]:
    """
    Use Claude claude-haiku-4-5 to extract wine offers from newsletter HTML.

    Returns [] if:
    - ANTHROPIC_API_KEY is not set in the environment
    - anthropic package is not installed
    - Any API error occurs
    - The LLM response is malformed

    Prompt caching is applied to the system prompt to reduce costs on repeated
    calls for the same source.

    Cost estimate: ~$0.0025 per call at Haiku rates.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.debug("[llm_parser] %s: ANTHROPIC_API_KEY not set — skipping LLM fallback", source_code)
        return []

    try:
        from anthropic import Anthropic
    except ImportError:
        logger.warning("[llm_parser] %s: anthropic package not installed — skipping LLM fallback", source_code)
        return []

    plain_text = _strip_html(html)
    if not plain_text.strip():
        logger.debug("[llm_parser] %s: empty plain text after stripping HTML", source_code)
        return []

    logger.info(
        "[llm_parser] %s: sending %d chars to %s (est. cost ~$0.0025)",
        source_code,
        len(plain_text),
        HAIKU_MODEL,
    )

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Extract all wine offers from this newsletter text "
                        f"(source: {source_code}):\n\n{plain_text}"
                    ),
                }
            ],
        )
    except Exception as exc:
        logger.warning("[llm_parser] %s: API call failed: %s", source_code, exc)
        return []

    response_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            response_text = block.text
            break

    if not response_text:
        logger.warning("[llm_parser] %s: empty response from LLM", source_code)
        return []

    offers = _parse_llm_response(response_text, source_code)
    logger.info("[llm_parser] %s: extracted %d offer(s) via LLM fallback", source_code, len(offers))
    return offers
