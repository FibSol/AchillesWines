"""
RVF viewer screenshot tool — uses fresh mozzoviewer URLs (no login needed).
Navigates pages via hash fragment after initial load; saves canvases as PNGs.

Usage:
    python rvf_viewer_screenshot.py --issues issues.json [--first 60] [--last 180] [--wait 1200]

issues.json format:
    [{"content_id": "197897", "title": "N700", "url": "https://mozzoviewer..."}]

Output: scraper/raw/rvf_pages/<content_id>/page_NNNN.png
        scraper/raw/rvf_pages/manifest.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

OUT_DIR = Path(__file__).parent / "raw" / "rvf_pages"


def screenshot_issue(page, issue: dict, first: int, last: int, wait_ms: int) -> list[str]:
    content_id = issue["content_id"]
    viewer_url = issue["url"]
    issue_dir = OUT_DIR / content_id
    issue_dir.mkdir(parents=True, exist_ok=True)

    # Skip pages already done
    existing = {p.name for p in issue_dir.glob("page_*.png")}
    pages_to_do = [p for p in range(first, last + 1)
                   if f"page_{p:04d}.png" not in existing]

    if not pages_to_do:
        print(f"  All pages already exist, skipping.")
        return [str(issue_dir / f"page_{p:04d}.png") for p in range(first, last + 1)]

    print(f"  Loading viewer…")
    page.goto(viewer_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)  # let PDF.js load the PDF

    # Verify viewer loaded (not expired)
    title = page.title()
    if "expir" in page.content().lower() or "401" in title:
        print(f"  ERROR: URL expired! Run again with a fresh URL.")
        return []

    print(f"  Viewer loaded: {title}")

    saved = []
    base = viewer_url.split("#")[0]

    for pg in pages_to_do:
        out_path = issue_dir / f"page_{pg:04d}.png"

        # Navigate via hash (no token re-check after initial load)
        page.evaluate(f"window.location.hash = '#page/{pg}'")
        page.wait_for_timeout(wait_ms)

        # Screenshot just the canvas element if available, else full viewport
        canvas = page.query_selector(f"#canvas{pg}")
        if canvas:
            canvas.screenshot(path=str(out_path))
        else:
            page.screenshot(path=str(out_path), clip={"x": 0, "y": 50, "width": 1280, "height": 870})

        saved.append(str(out_path))
        print(f"    page {pg:3d} > {out_path.name}")

    return saved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--issues", required=True, help="JSON file with issue list")
    parser.add_argument("--first", type=int, default=60)
    parser.add_argument("--last", type=int, default=180)
    parser.add_argument("--wait", type=int, default=1200, help="ms to wait per page")
    parser.add_argument("--headless", action="store_true", default=False)
    args = parser.parse_args()

    issues = json.loads(Path(args.issues).read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest_path = OUT_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"issues": []}
    done_ids = {i["content_id"] for i in manifest["issues"]}

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(
                channel="chrome",
                headless=args.headless,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
        except Exception:
            browser = pw.chromium.launch(
                headless=args.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )

        ctx = browser.new_context(
            viewport={"width": 1280, "height": 920},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = ctx.new_page()

        for issue in issues:
            cid = issue["content_id"]
            print(f"\n=== {issue.get('title', cid)} (contentId={cid}) ===")
            try:
                pages_saved = screenshot_issue(page, issue, args.first, args.last, args.wait)
                entry = {**issue, "pages": pages_saved}
                existing_entry = next((i for i in manifest["issues"] if i["content_id"] == cid), None)
                if existing_entry:
                    existing_entry.update(entry)
                else:
                    manifest["issues"].append(entry)
                manifest_path.write_text(
                    json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                print(f"  Saved {len(pages_saved)} pages")
            except Exception as e:
                print(f"  ERROR: {e}")

        browser.close()

    print(f"\nManifest: {manifest_path}")


if __name__ == "__main__":
    main()
