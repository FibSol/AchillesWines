"""
Dry-run harness for the Tastingbook resolver + extractor.

Read-only: writes NOTHING to the database. It measures, against the *real*
cellar, how many wines resolve to a Tastingbook page and how many of those
carry a James Suckling score — so we can judge whether the source is worth
wiring into the scheduler.

Run:  scraper/.venv/Scripts/python.exe scraper/test_tastingbook_resolver.py [N]
      (N = optional cap on number of cellar wines to test)
"""
import sqlite3
import sys
import time

import httpx

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from achilles_scraper.scrapers.tastingbook import (  # noqa: E402
    slugify_tb, parse_panel, extract_js, resolve_wine_url,
    _USER_AGENT,
)

DB = r"C:\Claude\achilles-wines\data\achilles.db"
SAVED_HTML = r"C:\Claude\achilles-wines\raw\tastingbook_margaux2015.html"


def self_check() -> None:
    print("=== self-check: slugify ===")
    cases = {
        "Château Margaux": "chateau_margaux",
        "Puligny-Montrachet 1er Cru Les Combettes": "pulignymontrachet_1er_cru_les_combettes",
        "Domaine de la Romanée-Conti": "domaine_de_la_romaneeconti",
        "La Tâche": "la_tache",
    }
    for src, want in cases.items():
        got = slugify_tb(src)
        print(f"  {'OK ' if got == want else 'BAD'} {src!r} -> {got!r}" + ("" if got == want else f" (want {want!r})"))

    print("=== self-check: parse_panel on saved Margaux 2015 HTML ===")
    with open(SAVED_HTML, encoding="utf-8") as fh:
        html = fh.read()
    panel = parse_panel(html)
    print(f"  panel size: {len(panel)} critics")
    js = extract_js(panel)
    print(f"  James Suckling: {js.score if js else None}p  (expect 100.0)")
    if js and js.note:
        print(f"  note: {js.note[:80]}...")


def main() -> None:
    cap = int(sys.argv[1]) if len(sys.argv) > 1 else None
    self_check()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    wines = con.execute(
        """
        SELECT DISTINCT w.wine_key, p.producer_name, a.appellation_name,
               w.cuvee_name, w.vintage
        FROM cellar_inventory ci
        JOIN dim_wine w        ON w.wine_key = ci.wine_key
        JOIN dim_producer p    ON p.producer_key = w.producer_key
        JOIN dim_appellation a ON a.appellation_key = w.appellation_key
        WHERE w.vintage IS NOT NULL
        ORDER BY p.producer_name
        """
    ).fetchall()
    if cap:
        wines = wines[:cap]

    print(f"\n=== resolving {len(wines)} cellar wines (read-only) ===")
    headers = {"User-Agent": _USER_AGENT, "Accept-Language": "en;q=0.9,fr;q=0.8"}
    n_resolved = n_js = 0
    misses: list[str] = []

    with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
        for w in wines:
            label = f"{w['producer_name']} | {w['cuvee_name'] or w['appellation_name']} {w['vintage']}"
            matched = resolve_wine_url(client, w["producer_name"], w["appellation_name"],
                                       w["cuvee_name"], w["vintage"])
            js = None
            if matched:
                try:
                    resp = client.get(matched)
                    time.sleep(1.2)
                    js = extract_js(parse_panel(resp.text))
                except Exception:
                    pass

            if matched:
                n_resolved += 1
                if js:
                    n_js += 1
                    print(f"  [JS {js.score:>5.1f}] {label}")
                    print(f"            {matched}")
                else:
                    print(f"  [page  ] {label}  (no JS score)")
                    print(f"            {matched}")
            else:
                misses.append(label)

    total = len(wines)
    print("\n=== summary ===")
    print(f"  cellar wines tested : {total}")
    print(f"  resolved to a page  : {n_resolved}  ({100*n_resolved/total:.0f}%)")
    print(f"  with a JS score     : {n_js}  ({100*n_js/total:.0f}%)")
    print(f"  unresolved          : {len(misses)}")
    if misses:
        print("  --- misses (first 25) ---")
        for m in misses[:25]:
            print(f"    - {m}")


if __name__ == "__main__":
    main()
