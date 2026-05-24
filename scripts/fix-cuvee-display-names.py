"""
Patch existing dim_wine rows for known display-name issues:
  1. Apostrophe-space:  "d' Angélus" → "d'Angélus"
  2. Collapsed article: normalise cuveeNorm for dedup (re-check "Le X" vs "X")
     — only updates cuvee_norm if different; wine_key is left unchanged because
       changing it would orphan fact rows.  A separate dedupe pass is needed.

Run from the project root:
    python scripts/fix-cuvee-display-names.py [--dry-run]
"""
import re
import sys
import sqlite3
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv
DB_PATH = Path(__file__).parent.parent / "data" / "achilles.db"

# Same apostrophe-space fix as clean_cuvee_display
# Only French elision particles — avoids mangling possessives ("Founders' Reserve")
# or Italian abbreviations ("Ca' di Mori").
_ELISION_SPACE_RE = re.compile(r"(^|\s)(d|l|n|j|m|s|c|qu)'\s+([A-Za-zÀ-ÿ])", re.I)


def fix_apostrophe_space(s: str) -> str:
    return _ELISION_SPACE_RE.sub(r"\1\2'\3", s)


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT wine_key, cuvee_name, canonical_name FROM dim_wine")
    rows = cur.fetchall()

    cuvee_updates: list[tuple[str, str, str]] = []
    canonical_updates: list[tuple[str, str, str]] = []

    for wine_key, cuvee_name, canonical_name in rows:
        new_cuvee = fix_apostrophe_space(cuvee_name) if cuvee_name else cuvee_name
        new_canonical = fix_apostrophe_space(canonical_name) if canonical_name else canonical_name
        if new_cuvee != cuvee_name:
            cuvee_updates.append((new_cuvee, wine_key, cuvee_name))
        if new_canonical != canonical_name:
            canonical_updates.append((new_canonical, wine_key, canonical_name))

    print(f"dim_wine rows scanned: {len(rows)}")
    print(f"cuvee_name fixes:      {len(cuvee_updates)}")
    print(f"canonical_name fixes:  {len(canonical_updates)}")

    if cuvee_updates:
        print("\nSample cuvee_name fixes (first 10):")
        for new, key, old in cuvee_updates[:10]:
            print(f"  {old!r}  ->  {new!r}  [{key}]")

    if not DRY_RUN:
        for new_cuvee, wine_key, _ in cuvee_updates:
            cur.execute(
                "UPDATE dim_wine SET cuvee_name = ? WHERE wine_key = ?",
                (new_cuvee, wine_key),
            )
        for new_canonical, wine_key, _ in canonical_updates:
            cur.execute(
                "UPDATE dim_wine SET canonical_name = ? WHERE wine_key = ?",
                (new_canonical, wine_key),
            )
        conn.commit()
        print(f"\nApplied {len(cuvee_updates)} cuvee_name + {len(canonical_updates)} canonical_name updates.")
    else:
        print("\n[dry-run] No changes written.")

    conn.close()


if __name__ == "__main__":
    main()
