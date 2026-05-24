"""
Parse the similarity JSON and produce a human-readable summary split by:
  1. Article issues (Le/La/Les vs bare name) — classified by language
  2. Edit-1 real duplicates — filter out numbered-series noise
  3. Edit-2 worth reviewing
Outputs to scripts/cuvee-findings-classified.txt
"""
import re
import json
from pathlib import Path

DATA = Path(__file__).parent / "cuvee-similarity-report.json"
OUT  = Path(__file__).parent / "cuvee-findings-classified.txt"

findings = json.loads(DATA.read_text(encoding="utf-8"))

# ── Helpers ───────────────────────────────────────────────────────────────────
_HAS_DIGIT = re.compile(r"\d")
_ONLY_NUM_DIFF = re.compile(r"^\d+$")  # token is purely numeric

def only_digit_differs(a: str, b: str) -> bool:
    """Returns True if the ONLY changed character(s) between a and b are digits."""
    ta = a.lower().split()
    tb = b.lower().split()
    if len(ta) != len(tb):
        return False
    diffs = [(i, w1, w2) for i, (w1, w2) in enumerate(zip(ta, tb)) if w1 != w2]
    if not diffs:
        return False
    return all(_HAS_DIGIT.search(w1) and _HAS_DIGIT.search(w2) for _, w1, w2 in diffs)

def singular_plural(a: str, b: str) -> bool:
    a2 = a.lower().replace("vineyards", "vineyard").replace("vines", "vine")
    b2 = b.lower().replace("vineyards", "vineyard").replace("vines", "vine")
    return a2 == b2

# ── Classify ──────────────────────────────────────────────────────────────────
article_fr:    list[dict] = []
article_en:    list[dict] = []
article_other: list[dict] = []
gender_clash:  list[dict] = []

edit1_real:    list[dict] = []
edit1_numbers: list[dict] = []
edit1_plural:  list[dict] = []

edit2_real:    list[dict] = []

_FR_ARTICLE = re.compile(r"^(le|la|les|l')\s+", re.I)
_EN_ARTICLE = re.compile(r"^(the)\s+", re.I)
_LA_RE = re.compile(r"^la\s+", re.I)
_LE_RE = re.compile(r"^le\s+", re.I)

for f in findings:
    cats = f["categories"]
    a, b = f["cuvee_a"], f["cuvee_b"]

    if "article" in cats:
        # Detect gender clash (La vs Le on same root)
        da = _LA_RE.match(a) or _LE_RE.match(a)
        db = _LA_RE.match(b) or _LE_RE.match(b)
        if da and db:
            gender_clash.append(f)
        elif _FR_ARTICLE.match(a) or _FR_ARTICLE.match(b):
            article_fr.append(f)
        elif _EN_ARTICLE.match(a) or _EN_ARTICLE.match(b):
            article_en.append(f)
        else:
            article_other.append(f)

    elif "edit-1" in cats:
        if only_digit_differs(a, b):
            edit1_numbers.append(f)
        elif singular_plural(a, b):
            edit1_plural.append(f)
        else:
            edit1_real.append(f)

    elif "edit-2" in cats:
        if not only_digit_differs(a, b):
            edit2_real.append(f)


# ── Output ────────────────────────────────────────────────────────────────────
lines: list[str] = []

def section(title: str, items: list[dict], show_max: int = 200) -> None:
    lines.append(f"\n{'=' * 72}")
    lines.append(f"  {title}  ({len(items)} pairs)")
    lines.append('=' * 72)
    for f in items[:show_max]:
        lines.append(f"  [{f['producer_name']}]")
        lines.append(f"      A: {f['cuvee_a']!r}")
        lines.append(f"      B: {f['cuvee_b']!r}")
    if len(items) > show_max:
        lines.append(f"  ... {len(items) - show_max} more")


lines.append("CUVEE SIMILARITY FINDINGS — CLASSIFIED")
lines.append(f"Total pairs scanned: {len(findings)}\n")
lines.append("SUMMARY")
lines.append(f"  French article divergence (Le/La/Les):  {len(article_fr)}")
lines.append(f"  English article divergence (The):       {len(article_en)}")
lines.append(f"  Gender clash (Le vs La on same root):   {len(gender_clash)}")
lines.append(f"  Other article:                          {len(article_other)}")
lines.append(f"  Edit-1 real spelling/accent typos:      {len(edit1_real)}")
lines.append(f"  Edit-1 singular/plural only:            {len(edit1_plural)}")
lines.append(f"  Edit-1 numbered series (skip):          {len(edit1_numbers)}")
lines.append(f"  Edit-2 real typos:                      {len(edit2_real)}")

section("FRENCH ARTICLE DIVERGENCE — fix by keeping the 'with article' form as canonical", article_fr)
section("ENGLISH ARTICLE DIVERGENCE — review needed", article_en)
section("GENDER CLASH (Le vs La) — review needed", gender_clash)
section("OTHER ARTICLE — review", article_other)
section("EDIT-1 REAL TYPOS / SPELLING / ACCENT — fix candidates", edit1_real)
section("EDIT-1 SINGULAR/PLURAL — probably same wine", edit1_plural)
section("EDIT-2 REAL TYPOS", edit2_real, show_max=60)

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"Written to {OUT}")
print(f"\nSummary:")
print(f"  French article divergence: {len(article_fr)}")
print(f"  English article divergence: {len(article_en)}")
print(f"  Gender clash (Le vs La):   {len(gender_clash)}")
print(f"  Other article:             {len(article_other)}")
print(f"  Edit-1 real typos:         {len(edit1_real)}")
print(f"  Edit-1 singular/plural:    {len(edit1_plural)}")
print(f"  Edit-1 numbered series:    {len(edit1_numbers)}")
print(f"  Edit-2 real typos:         {len(edit2_real)}")
