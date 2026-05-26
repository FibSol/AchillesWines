"""
Step 2 — RVF magazine extractor: feed saved page screenshots to Claude Vision,
extract wine tasting notes, write to raw/rvf_pages/ratings.json.

Usage:
    python rvf_magazine_extract.py [--batch-size N]

Input:  scraper/raw/rvf_pages/manifest.json + .png files
Output: scraper/raw/rvf_pages/ratings.json

Then import into Achilles DB:
    python rvf_magazine_import.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

MANIFEST  = Path(__file__).parent / "raw" / "rvf_pages" / "manifest.json"
OUT_FILE  = Path(__file__).parent / "raw" / "rvf_pages" / "ratings.json"

MODEL = "claude-haiku-4-5-20251001"

SYSTEM = """You are a wine data extraction assistant.
You receive a photograph of a page from La Revue du Vin de France (RVF), a French wine magazine.
Your task: extract all wine tasting notes visible on the page.

For each wine found, return a JSON object with:
  - producer: str       (domaine / château name, as printed)
  - cuvee: str          (wine name / cuvée, as printed)
  - vintage: int|null   (4-digit year, null if NV or not shown)
  - appellation: str    (AOC/AOP or region, as printed)
  - score: float|null   (numeric score on /20 scale, null if not visible)
  - note: str           (tasting note text, first sentence only, truncated at 200 chars)
  - page_is_ratings: bool  (true if this page is clearly a tasting notes / degustation page)

If the page is not a tasting-notes page (e.g. it's an article, advert, or editorial),
return: {"page_is_ratings": false, "wines": []}

Return only valid JSON — no markdown, no explanation. Format:
{"page_is_ratings": true|false, "wines": [...]}
"""


def encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def extract_page(client: anthropic.Anthropic, img_path: str) -> dict:
    b64 = encode_image(img_path)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": b64},
                    },
                    {"type": "text", "text": "Extract all wine tasting notes from this page."},
                ],
            }
        ],
    )
    raw = msg.content[0].text.strip()
    # strip accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)


def main():
    if not MANIFEST.exists():
        print(f"ERROR: manifest not found at {MANIFEST}")
        print("Run rvf_magazine_auth.py first.")
        sys.exit(1)

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in .env")
        sys.exit(1)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    client = anthropic.Anthropic(api_key=api_key)

    all_ratings: list[dict] = []
    total_pages = sum(len(i.get("pages", [])) for i in manifest["issues"])
    processed = 0
    skipped_non_ratings = 0

    for issue in manifest["issues"]:
        content_id = issue["content_id"]
        title = issue.get("title", content_id)
        pages = issue.get("pages", [])
        print(f"\n=== {title} ({len(pages)} pages) ===")

        for img_path in pages:
            if not Path(img_path).exists():
                print(f"  SKIP (file missing): {img_path}")
                continue

            print(f"  {Path(img_path).name} … ", end="", flush=True)
            try:
                result = extract_page(client, img_path)
                is_ratings = result.get("page_is_ratings", False)
                wines = result.get("wines", [])

                if not is_ratings:
                    skipped_non_ratings += 1
                    print("not a ratings page")
                else:
                    for w in wines:
                        w["source_issue"] = content_id
                        w["source_page"] = Path(img_path).name
                        w["source_title"] = title
                    all_ratings.extend(wines)
                    print(f"{len(wines)} wines")

                processed += 1
                time.sleep(0.3)  # gentle rate limit

            except json.JSONDecodeError as e:
                print(f"JSON parse error: {e}")
            except anthropic.RateLimitError:
                print("rate limit — sleeping 30s")
                time.sleep(30)
            except Exception as e:
                print(f"ERROR: {e}")

    OUT_FILE.write_text(
        json.dumps({"ratings": all_ratings, "total": len(all_ratings)}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"\n{'='*50}")
    print(f"Pages processed : {processed}/{total_pages}")
    print(f"Non-rating pages: {skipped_non_ratings}")
    print(f"Wines extracted : {len(all_ratings)}")
    print(f"Output          : {OUT_FILE}")


if __name__ == "__main__":
    main()
