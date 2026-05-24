"""
Audit dim_wine for near-duplicate cuvée names within the same producer.

Catches:
  A) Article divergence  : "Le Carillon" vs "Carillon"
  B) Accent differences  : "Angelus" vs "Angelus" (e vs é, a vs â, etc.)
  C) Apostrophe-space    : already fixed, but kept as guard
  D) Ordinal noise       : "Clos #1" vs "Clos No.1"
  E) High edit-distance  : any pair with Levenshtein ≤ 2 (on norms)
  F) One name contains the other (substring)

Output: grouped by producer, sorted by count of suspect pairs.

Usage:
    python scripts/audit-cuvee-similarity.py [--min-count N] [--top N] [--csv path]
"""
import re
import sys
import csv
import unicodedata
import sqlite3
import itertools
from pathlib import Path
from collections import defaultdict

DB_PATH = Path(__file__).parent.parent / "data" / "achilles.db"

# ── CLI args ──────────────────────────────────────────────────────────────────
MIN_COUNT = 1
TOP_N = None
CSV_OUT = None
for i, arg in enumerate(sys.argv[1:]):
    if arg == "--min-count" and i + 1 < len(sys.argv[1:]):
        MIN_COUNT = int(sys.argv[i + 2])
    if arg == "--top" and i + 1 < len(sys.argv[1:]):
        TOP_N = int(sys.argv[i + 2])
    if arg == "--csv" and i + 1 < len(sys.argv[1:]):
        CSV_OUT = sys.argv[i + 2]


# ── Normalization helpers ─────────────────────────────────────────────────────

def strip_accents(s: str) -> str:
    """Remove all combining diacritical marks."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )

_LEADING_ARTICLE = re.compile(
    r"^(le|la|les|l|un|une|de|du|des|the|lo|la|los|las|il|i|gli|le)\s+",
    re.I,
)
_PUNCT = re.compile(r"[^a-z0-9\s]")
_SPACES = re.compile(r"\s+")

def norm(s: str) -> str:
    """Canonical key: lowercase, no accents, no punctuation, strip leading article."""
    if not s:
        return ""
    out = strip_accents(s.lower())
    out = _PUNCT.sub(" ", out)
    out = _SPACES.sub(" ", out).strip()
    out = _LEADING_ARTICLE.sub("", out).strip()
    return out

def norm_no_article(s: str) -> str:
    """Same but always strip leading article."""
    return _LEADING_ARTICLE.sub("", norm(s)).strip()

def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) > len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (0 if ca == cb else 1)))
        prev = curr
    return prev[-1]


# ── Category detection ────────────────────────────────────────────────────────

def categorize(a: str, b: str) -> list[str]:
    cats = []
    na, nb = norm(a), norm(b)
    naa, nab = norm_no_article(a), norm_no_article(b)

    # A: article divergence — norms differ but no-article norms match
    if na != nb and naa == nab and naa:
        cats.append("article")

    # B: accent difference — accent-stripped norms match but originals differ
    sa, sb = strip_accents(a.lower()), strip_accents(b.lower())
    if sa == sb and a.lower() != b.lower():
        cats.append("accent")

    # C: apostrophe-space
    ac = re.sub(r"(^|\s)(d|l|n|j|m|s|c|qu)'\s+([A-Za-z])", r"\1\2'\3", a, flags=re.I)
    bc = re.sub(r"(^|\s)(d|l|n|j|m|s|c|qu)'\s+([A-Za-z])", r"\1\2'\3", b, flags=re.I)
    if ac != a or bc != b:
        if ac.lower() == bc.lower():
            cats.append("apostrophe-space")

    # E: edit distance on norm (only meaningful for names >= 8 chars)
    if not cats and len(na) >= 8 and len(nb) >= 8:
        dist = levenshtein(na, nb)
        max_len = max(len(na), len(nb))
        if dist == 1:
            cats.append("edit-1")
        elif dist == 2 and max_len >= 12:
            cats.append("edit-2")

    # F: substring containment (one norm contains the other)
    if not cats and na and nb and na != nb:
        if na in nb or nb in na:
            shorter, longer = (na, nb) if len(na) < len(nb) else (nb, na)
            if len(shorter) >= 4 and len(longer) / len(shorter) <= 2.5:
                cats.append("substring")

    return cats if cats else []


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT p.producer_key, p.producer_name, w.cuvee_name,
               COUNT(*) as wine_count
        FROM dim_wine w
        JOIN dim_producer p ON w.producer_key = p.producer_key
        WHERE w.cuvee_name IS NOT NULL AND w.cuvee_name != ''
        GROUP BY p.producer_key, p.producer_name, w.cuvee_name
        ORDER BY p.producer_name, w.cuvee_name
    """)
    rows = cur.fetchall()
    conn.close()

    # Group by producer
    by_producer: dict[int, dict] = defaultdict(lambda: {"name": "", "cuvees": {}})
    for pk, pname, cname, cnt in rows:
        by_producer[pk]["name"] = pname
        by_producer[pk]["cuvees"][cname] = cnt

    findings: list[dict] = []

    for pk, info in by_producer.items():
        cuvees = list(info["cuvees"].keys())
        if len(cuvees) < 2:
            continue

        for a, b in itertools.combinations(cuvees, 2):
            cats = categorize(a, b)
            if cats:
                findings.append({
                    "producer_key": pk,
                    "producer_name": info["name"],
                    "cuvee_a": a,
                    "count_a": info["cuvees"][a],
                    "cuvee_b": b,
                    "count_b": info["cuvees"][b],
                    "categories": ", ".join(cats),
                })

    # Sort by category priority then producer
    cat_order = {"accent": 0, "article": 1, "apostrophe-space": 2, "edit-1": 3, "edit-2": 4, "substring": 5}
    findings.sort(key=lambda x: (
        min(cat_order.get(c.strip(), 9) for c in x["categories"].split(",")),
        x["producer_name"],
    ))

    # ── Summary by category ────────────────────────────────────────────────────
    cat_counts: dict[str, int] = defaultdict(int)
    for f in findings:
        for c in f["categories"].split(", "):
            cat_counts[c.strip()] += 1

    print(f"\nTotal suspect pairs found: {len(findings)}")
    print(f"{'Category':<22} {'Pairs':>6}")
    print("-" * 30)
    for cat in ["accent", "article", "apostrophe-space", "edit-1", "edit-2", "substring"]:
        if cat_counts[cat]:
            print(f"  {cat:<20} {cat_counts[cat]:>6}")

    # ── Detail output ─────────────────────────────────────────────────────────
    shown = 0
    prev_producer = None
    limit = TOP_N or len(findings)

    print()
    for f in findings[:limit]:
        if f["producer_name"] != prev_producer:
            print(f"\n{'=' * 70}")
            print(f"  Producer: {f['producer_name']}  (key={f['producer_key']})")
            prev_producer = f["producer_name"]
        tag = f"[{f['categories']}]"
        print(f"    {tag:<22}  {f['cuvee_a']!r:40}  vs  {f['cuvee_b']!r}")
        shown += 1

    if TOP_N and len(findings) > TOP_N:
        print(f"\n  ... {len(findings) - TOP_N} more pairs not shown (use --top N to see more)")

    # ── CSV export ────────────────────────────────────────────────────────────
    if CSV_OUT:
        with open(CSV_OUT, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(findings[0].keys()) if findings else [])
            writer.writeheader()
            writer.writerows(findings)
        print(f"\nCSV written to: {CSV_OUT}")


if __name__ == "__main__":
    main()
