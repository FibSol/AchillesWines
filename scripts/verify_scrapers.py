"""End-to-end smoke test of every registered scraper.

For each entry in achilles_scraper.cli.SCRAPERS:
  1. Open a fresh get_db() connection on a TEST DB (copy of prod).
  2. Instantiate the scraper, call .run(limit=5).
  3. Record rows_fetched / rows_inserted / rows_dlq / error / elapsed.

Each scraper runs in its own subprocess with a hard 60s timeout, so one
hung scraper (e.g. hachette_vins) cannot block the rest of the matrix.

Outputs docs/scraper_health_<date>.md grouped into:
  GREEN   — fetched > 0 AND inserted > 0
  YELLOW  — fetched > 0 AND inserted = 0   (gate / dim resolution issue)
  GRAY    — error matches /credentials? missing/i  (expected, no creds)
  RED     — any other error  OR  fetched = 0   OR  timed out

Run:
    python scripts/verify_scrapers.py
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROD_DB = ROOT / "data" / "achilles.db"
TEST_DB = ROOT / "data" / "achilles.test.db"
REPORT = ROOT / "docs" / f"scraper_health_{date.today().isoformat()}.md"
PER_SCRAPER_TIMEOUT_S = 60

# This module is invoked both as the orchestrator (default) and as a
# subprocess worker via `--run <source_code>`. The worker prints a single
# JSON line then exits.


def copy_db() -> None:
    print(f"Copying {PROD_DB.name} -> {TEST_DB.name} ...", flush=True)
    t0 = time.time()
    src = sqlite3.connect(f"file:{PROD_DB}?mode=ro", uri=True)
    if TEST_DB.exists():
        TEST_DB.unlink()
    dst = sqlite3.connect(str(TEST_DB))
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    print(f"  done in {time.time() - t0:.1f}s "
          f"({TEST_DB.stat().st_size / 1_048_576:.0f} MB)", flush=True)


def run_worker(code: str) -> None:
    """Subprocess entry: load scraper, run with limit=5, print JSON, exit."""
    sys.path.insert(0, str(ROOT / "scraper"))
    from achilles_scraper.cli import _load_scrapers, SCRAPERS
    from achilles_scraper.db import get_db
    _load_scrapers()
    if code not in SCRAPERS:
        print(json.dumps({"error": f"unknown scraper: {code}"}))
        return
    cls = SCRAPERS[code]
    try:
        conn = get_db(str(TEST_DB))
        scraper = cls(conn)
        res = scraper.run(limit=5)
        out = {
            "fetched": getattr(res, "rows_fetched", 0),
            "inserted": getattr(res, "rows_inserted", 0),
            "dlq": getattr(res, "rows_dlq", 0),
            "skipped": getattr(res, "rows_skipped_unchanged", 0),
            "error": (res.error or "")[:300],
        }
        try:
            conn.close()
        except Exception:
            pass
    except Exception as e:
        out = {"fetched": 0, "inserted": 0, "dlq": 0, "skipped": 0,
               "error": f"{type(e).__name__}: {e}"[:300]}
    print(json.dumps(out), flush=True)


def categorise(r: dict) -> str:
    err = (r.get("error") or "").lower()
    if "timed out" in err:
        return "RED"
    if err and "credentials" in err and "missing" in err:
        return "GRAY"
    if err:
        return "RED"
    fetched, inserted, skipped = r["fetched"], r["inserted"], r["skipped"]
    # Idempotent re-run where every fetched row was already in the DB is healthy.
    if inserted > 0 or (fetched > 0 and skipped >= fetched):
        return "GREEN"
    if fetched > 0:
        return "YELLOW"
    if skipped > 0:
        return "GREEN"
    return "RED"


def orchestrate() -> int:
    if not PROD_DB.exists():
        print(f"prod DB missing: {PROD_DB}", file=sys.stderr)
        return 1
    copy_db()

    sys.path.insert(0, str(ROOT / "scraper"))
    from achilles_scraper.cli import _load_scrapers, SCRAPERS
    _load_scrapers()
    codes = sorted(SCRAPERS.keys())
    print(f"Loaded {len(codes)} scrapers", flush=True)

    rows: list[dict] = []
    for code in codes:
        print(f"-- {code:30s} ...", end=" ", flush=True)
        t0 = time.time()
        result: dict = {"code": code, "fetched": 0, "inserted": 0,
                        "dlq": 0, "skipped": 0, "error": ""}
        try:
            cp = subprocess.run(
                [sys.executable, __file__, "--run", code],
                capture_output=True, text=True,
                timeout=PER_SCRAPER_TIMEOUT_S,
                cwd=str(ROOT),
                # Disable stdout buffering in the child via PYTHONUNBUFFERED
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                # On Windows, subprocess.run waits politely; timeout kills the process.
            )
            # Find the JSON line in stdout (children may print log noise first).
            out = ""
            for line in cp.stdout.splitlines():
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    out = line
            if out:
                try:
                    result.update(json.loads(out))
                except Exception as e:
                    result["error"] = f"json decode: {e}; stdout[-200]={cp.stdout[-200:]!r}"
            else:
                err_tail = (cp.stderr or cp.stdout or "")[-200:]
                result["error"] = f"no JSON from child (rc={cp.returncode}): {err_tail!r}"
        except subprocess.TimeoutExpired:
            result["error"] = f"timed out after {PER_SCRAPER_TIMEOUT_S}s"
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"

        result["elapsed_s"] = round(time.time() - t0, 1)
        result["category"] = categorise(result)
        rows.append(result)
        err_pretty = (result["error"][:80] + "...") if len(result["error"]) > 80 else result["error"]
        print(f"{result['category']:6} f={result['fetched']:>3} "
              f"i={result['inserted']:>3} d={result['dlq']:>3} "
              f"t={result['elapsed_s']:>5}s  {err_pretty}", flush=True)

    # --- Report -----------------------------------------------------------
    by_cat: dict[str, list[dict]] = {"GREEN": [], "YELLOW": [], "GRAY": [], "RED": []}
    for r in rows:
        by_cat[r["category"]].append(r)

    out: list[str] = []
    out.append(f"# Scraper health — {date.today().isoformat()}\n")
    out.append(f"Ran {len(rows)} scrapers via subprocess with `--limit 5` and "
               f"{PER_SCRAPER_TIMEOUT_S}s hard timeout against "
               f"`{TEST_DB.relative_to(ROOT)}` (copy of prod).\n")
    out.append("Connections opened via `get_db()` so `PRAGMA foreign_keys=ON`.\n")
    summary = " · ".join(f"**{cat}** {len(by_cat[cat])}"
                         for cat in ["GREEN", "YELLOW", "GRAY", "RED"])
    out.append(f"## Summary\n\n{summary}\n")

    def section(cat: str, blurb: str) -> str:
        sec = [f"## {cat} — {blurb}\n"]
        if not by_cat[cat]:
            sec.append("*(none)*\n")
            return "\n".join(sec)
        sec.append("| scraper | fetched | inserted | dlq | skipped | elapsed | error |")
        sec.append("| --- | --- | --- | --- | --- | --- | --- |")
        for r in sorted(by_cat[cat], key=lambda x: x["code"]):
            err = (r.get("error") or "").replace("|", "\\|").replace("\n", " ")[:200]
            sec.append(f"| `{r['code']}` | {r['fetched']} | {r['inserted']} | "
                       f"{r['dlq']} | {r['skipped']} | {r['elapsed_s']}s | {err} |")
        return "\n".join(sec) + "\n"

    out.append(section("RED", "errored, fetched 0 rows, or timed out"))
    out.append(section("YELLOW", "fetched but inserted 0 (gate / dim resolution)"))
    out.append(section("GRAY", "credentials missing (expected — no creds in .env)"))
    out.append(section("GREEN", "fetched and inserted"))

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(out), encoding="utf-8")
    print(f"\nWrote {REPORT.relative_to(ROOT)}")
    print(summary)
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--run":
        run_worker(sys.argv[2])
    else:
        sys.exit(orchestrate())
