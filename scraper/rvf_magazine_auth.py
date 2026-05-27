"""
Step 1 — RVF magazine scraper: authenticate to magazines.fr, open each issue
in the mozzoviewer, navigate to tasting-note pages and save screenshots.

Usage:
    python rvf_magazine_auth.py [--issues N] [--headless]

Output: scraper/raw/rvf_pages/<issue_id>/<page_N>.png
        scraper/raw/rvf_pages/manifest.json  (issue list + page paths)

Env vars required:
    ACHILLES_AUTH_MAGAZINES_FR_USERNAME
    ACHILLES_AUTH_MAGAZINES_FR_PASSWORD
    ANTHROPIC_API_KEY  (used in step 2, not here)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

load_dotenv(Path(__file__).parent.parent / ".env")

USERNAME = os.environ["ACHILLES_AUTH_MAGAZINES_FR_USERNAME"]
PASSWORD = os.environ["ACHILLES_AUTH_MAGAZINES_FR_PASSWORD"]

LIBRARY_URL = "https://www.magazines.fr/mon-espace-client/ma-bibliotheque-numerique.html"
OUT_DIR = Path(__file__).parent / "raw" / "rvf_pages"
MANIFEST = OUT_DIR / "manifest.json"

# Pages in a mozzoviewer issue that are likely tasting notes.
# RVF structure: cover + editorial + region articles + TASTING NOTES + small ads.
# We screenshot pages 60-160 (wide net) and let the extractor filter.
FIRST_PAGE = 60
LAST_PAGE  = 180
PAGE_STEP  = 1


def login(page) -> None:
    page.goto(LIBRARY_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Dismiss cookie consent if present
    for sel in ["button:has-text('Agree and close')", "button:has-text('Accepter')",
                "button:has-text('Tout accepter')", "#didomi-notice-agree-button",
                "button:has-text('Accepter et fermer')"]:
        try:
            page.click(sel, timeout=2000)
            page.wait_for_timeout(1000)
            break
        except PwTimeout:
            pass

    # magazines.fr has a 2-step form: first choose "Oui / J'ai déjà un compte"
    # then the email+password fields appear.
    for sel in [
        "label:has-text('J')",       # "J'ai déjà un compte" label
        "input[value='oui']",
        "input[id*='oui']",
        "#oui",
        "label:has-text('Oui')",
        "[id*='dejaClient'] label",
    ]:
        try:
            page.click(sel, timeout=2000)
            page.wait_for_timeout(1000)
            break
        except PwTimeout:
            pass

    # Wait for and fill email + password
    page.wait_for_selector("input[type=password]", timeout=10000)
    page.fill("input[type=email], input[name*=email], input[id*=email], input[id*=login]",
              USERNAME, timeout=10000)
    page.fill("input[type=password]", PASSWORD)
    page.click("button[type=submit], input[type=submit]")
    page.wait_for_load_state("networkidle", timeout=15000)
    # Verify we left the login/connexion page
    current = page.url.lower()
    if "connexion" in current or "login" in current:
        # Try once more: maybe we need a different submit
        try:
            page.click("button:has-text('OK'), button:has-text('Connexion'), button:has-text('Valider')",
                       timeout=3000)
            page.wait_for_load_state("networkidle", timeout=10000)
        except PwTimeout:
            pass
    print(f"  Logged in — landed on {page.url}")


def get_issue_links(page) -> list[dict]:
    page.goto(LIBRARY_URL, wait_until="networkidle")
    page.wait_for_timeout(2000)

    issues = []
    cards = page.query_selector_all("a[href*='mozzoviewer'], a[href*='publishingcenter']")
    if not cards:
        # fallback: look for "Lire" buttons that open the viewer
        cards = page.query_selector_all("a:has-text('Lire'), button:has-text('Lire')")

    for el in cards:
        href = el.get_attribute("href") or ""
        title_el = el.query_selector("span, p, div") or el
        title = (title_el.inner_text() or href).strip()[:80]
        m = re.search(r'contentId=(\d+)', href)
        if m:
            issues.append({"content_id": m.group(1), "title": title, "url": href})

    # deduplicate by content_id
    seen = set()
    unique = []
    for i in issues:
        if i["content_id"] not in seen:
            seen.add(i["content_id"])
            unique.append(i)
    return unique


def screenshot_issue(page, issue: dict, max_pages: int) -> list[str]:
    content_id = issue["content_id"]
    issue_dir = OUT_DIR / content_id
    issue_dir.mkdir(parents=True, exist_ok=True)

    viewer_url = issue["url"]
    print(f"  Opening viewer: {viewer_url[:80]}…")

    # Open viewer in same tab (it redirects internally)
    page.goto(viewer_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)

    # The viewer is an iframe-based SPA. Look for page number input or navigation.
    # Strategy: use the viewer's keyboard navigation (right arrow) or direct URL
    # with #page/N fragment.

    base_viewer = viewer_url.split("?")[0].rstrip("/")
    qs = viewer_url.split("?")[1] if "?" in viewer_url else ""

    saved = []
    last_page = min(LAST_PAGE, FIRST_PAGE + max_pages - 1)

    for pg in range(FIRST_PAGE, last_page + 1, PAGE_STEP):
        target = f"{base_viewer}?{qs}#page/{pg}"
        page.goto(target, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(2500)  # allow images to render

        out_path = issue_dir / f"page_{pg:04d}.png"
        page.screenshot(path=str(out_path), full_page=False)
        saved.append(str(out_path))
        print(f"    page {pg:3d} → {out_path.name}")

    return saved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--issues", type=int, default=12, help="Max issues to process")
    parser.add_argument("--max-pages", type=int, default=120, help="Max tasting pages per issue")
    parser.add_argument("--headless", action="store_true", default=False)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        launch_opts = dict(
            headless=args.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        # Prefer installed Chrome for better site compatibility
        try:
            browser = pw.chromium.launch(channel="chrome", **launch_opts)
        except Exception:
            browser = pw.chromium.launch(**launch_opts)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="fr-FR",
            extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9"},
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = ctx.new_page()

        print("=== Step 1: Login ===")
        login(page)

        print("=== Step 2: Collect issue links ===")
        issues = get_issue_links(page)
        if not issues:
            print("ERROR: no issues found. Check login and library page structure.")
            sys.exit(1)
        print(f"  Found {len(issues)} issues")
        for i in issues[:args.issues]:
            print(f"    {i['content_id']} — {i['title']}")

        manifest = {"issues": []}
        for issue in issues[:args.issues]:
            print(f"\n=== Issue {issue['content_id']}: {issue['title']} ===")
            try:
                pages_saved = screenshot_issue(page, issue, args.max_pages)
                manifest["issues"].append({**issue, "pages": pages_saved})
            except Exception as e:
                print(f"  ERROR: {e}")
                manifest["issues"].append({**issue, "pages": [], "error": str(e)})

        MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nManifest written to {MANIFEST}")
        browser.close()


if __name__ == "__main__":
    main()
