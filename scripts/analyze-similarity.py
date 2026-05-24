"""
Analyze cuvee similarity results and write a clean UTF-8 report.
"""
import re
import unicodedata
import itertools
import sqlite3
import json
from pathlib import Path
from collections import defaultdict

DB_PATH = Path(__file__).parent.parent / "data" / "achilles.db"
OUT_PATH = Path(__file__).parent / "cuvee-similarity-report.json"

def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

_LEADING_ARTICLE = re.compile(
    r"^(le|la|les|l|un|une|de|du|des|the|lo|los|las|il|i|gli)\s+",
    re.I,
)
_PUNCT = re.compile(r"[^a-z0-9\s]")
_SPACES = re.compile(r"\s+")

def norm(s):
    if not s:
        return ""
    out = strip_accents(s.lower())
    out = _PUNCT.sub(" ", out)
    return _SPACES.sub(" ", out).strip()

def norm_no_article(s):
    return _LEADING_ARTICLE.sub("", norm(s)).strip()

def levenshtein(a, b):
    if a == b: return 0
    if len(a) > len(b): a, b = b, a
    prev = list(range(len(b) + 1))
    for ca in a:
        curr = [prev[0] + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j+1]+1, curr[j]+1, prev[j]+(0 if ca==cb else 1)))
        prev = curr
    return prev[-1]

def categorize(a, b):
    cats = []
    na, nb = norm(a), norm(b)
    naa, nab = norm_no_article(a), norm_no_article(b)

    # Accent: accent-stripped norms match but originals differ
    sa, sb = strip_accents(a.lower()), strip_accents(b.lower())
    if sa == sb and a.lower() != b.lower():
        cats.append("accent")

    # Article: norms differ only by leading article
    if na != nb and naa and nab and naa == nab:
        cats.append("article")

    # Edit distance (only for names >= 8 chars)
    if not cats and len(na) >= 8 and len(nb) >= 8:
        dist = levenshtein(na, nb)
        if dist == 1:
            cats.append("edit-1")
        elif dist == 2 and max(len(na), len(nb)) >= 12:
            cats.append("edit-2")

    # Substring (skip if already categorized)
    if not cats and na and nb and na != nb:
        if na in nb or nb in na:
            shorter = na if len(na) < len(nb) else nb
            longer  = na if len(na) >= len(nb) else nb
            if len(shorter) >= 5 and len(longer) / len(shorter) <= 2.5:
                cats.append("substring")

    return cats

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("""
    SELECT p.producer_key, p.producer_name, w.cuvee_name, COUNT(*) as cnt
    FROM dim_wine w
    JOIN dim_producer p ON w.producer_key = p.producer_key
    WHERE w.cuvee_name IS NOT NULL AND w.cuvee_name != ''
    GROUP BY p.producer_key, p.producer_name, w.cuvee_name
    ORDER BY p.producer_name, w.cuvee_name
""")
rows = cur.fetchall()
conn.close()

by_producer = defaultdict(lambda: {"name": "", "cuvees": {}})
for pk, pname, cname, cnt in rows:
    by_producer[pk]["name"] = pname
    by_producer[pk]["cuvees"][cname] = cnt

findings = []
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
                "categories": cats,
            })

# Category stats
cat_counts = defaultdict(int)
for f in findings:
    for c in f["categories"]:
        cat_counts[c] += 1

print("Total pairs:", len(findings))
print("By category:")
for cat in ["accent", "article", "edit-1", "edit-2", "substring"]:
    print(f"  {cat:<20} {cat_counts[cat]:>5}")

# Sort: accent > article > edit-1 > edit-2 > substring
CAT_PRIO = {"accent": 0, "article": 1, "edit-1": 2, "edit-2": 3, "substring": 4}
findings.sort(key=lambda x: (
    min(CAT_PRIO.get(c, 9) for c in x["categories"]),
    x["producer_name"],
))

OUT_PATH.write_text(json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nFull report: {OUT_PATH}")

# Print accent + article in full
print("\n=== ACCENT ISSUES ===")
for f in findings:
    if "accent" in f["categories"]:
        print(f"  [{f['producer_name']}]  {f['cuvee_a']!r}  vs  {f['cuvee_b']!r}")

print("\n=== ARTICLE ISSUES (Le/La/Les prefix divergence) ===")
for f in findings:
    if "article" in f["categories"]:
        print(f"  [{f['producer_name']}]  {f['cuvee_a']!r}  vs  {f['cuvee_b']!r}")

print("\n=== EDIT-1 SAMPLE (first 40) ===")
n = 0
for f in findings:
    if "edit-1" in f["categories"]:
        print(f"  [{f['producer_name']}]  {f['cuvee_a']!r}  vs  {f['cuvee_b']!r}")
        n += 1
        if n >= 40:
            break
