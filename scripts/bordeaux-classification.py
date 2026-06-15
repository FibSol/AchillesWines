"""
Bordeaux Grand Cru classification — reference parser + matcher.

Parses the classed-growth lists from a saved lalandemoreau page into a clean
{château → classification} reference table, then matches them against
dim_producer.  DRY-RUN by default (writes nothing); pass --apply to write
dim_wine.classification for the GRAND VIN of each matched producer.

Scope note: this is Bordeaux-only reference data for the broader catalogue
(dim_wine.classification is ~3% filled).  It is NOT a cellar enrichment — the
cellar is ~5% Bordeaux.  Single-source (a retailer's transcription), so the
match step is conservative and reviewable.

    python scripts/bordeaux-classification.py            # dry run + write reference JSON
    python scripts/bordeaux-classification.py --apply    # also write classifications
"""
import argparse
import difflib
import json
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

from selectolax.parser import HTMLParser

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "raw" / "lalandemoreau_grandscrus.html"
REF_OUT = ROOT / "reference" / "bordeaux_classification.json"
DB = ROOT / "data" / "achilles.db"

MATCH_THRESHOLD = 0.90  # conservative — Bordeaux names collide (e.g. Lagrange)
_ORDINALS = {
    "premier": "Premier", "premiers": "Premier",
    "deuxieme": "Deuxième", "deuxiemes": "Deuxième",
    "troisieme": "Troisième", "troisiemes": "Troisième",
    "quatrieme": "Quatrième", "quatriemes": "Quatrième",
    "cinquieme": "Cinquième", "cinquiemes": "Cinquième",
}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def classify_header(text: str, system: str | None) -> tuple[str | None, str | None]:
    """(classification, new_system) for a section header, or (None, system)."""
    t = _strip_accents(text).lower().strip()
    if not t:
        return None, system
    # System context from h3/h2.
    if "garage" in t or "artisans" in t or "differents classements" in t or "qu'est-ce" in t:
        return None, None
    if "saint-emilion" in t or "saint emilion" in t or "emilion" in t:
        system = "stemilion"
    elif "sauternes" in t or "barsac" in t:
        system = "sauternes"
    elif "pessac" in t or "graves" in t:
        system = "graves"
    elif "1855" in t and "bourgeois" not in t:
        system = "medoc1855"

    ordinal = next((v for k, v in _ORDINALS.items() if re.search(rf"\b{k}\b", t)), None)

    if "bourgeois" in t:
        return "Cru Bourgeois", system
    if "1855" in t and ordinal:
        return f"1855 {ordinal} Cru Classé (Médoc)", "medoc1855"
    if system == "stemilion":
        if "classes a" in t or "classe a" in t:
            return "Saint-Émilion Premier Grand Cru Classé A", system
        if "classes b" in t or "classe b" in t:
            return "Saint-Émilion Premier Grand Cru Classé B", system
        if "grands crus classes" in t or "grand cru classe" in t:
            return "Saint-Émilion Grand Cru Classé", system
    if system == "sauternes":
        if "superieur" in t:
            return "Sauternes Premier Cru Supérieur", system
        if "deuxieme" in t:
            return "Sauternes Deuxième Cru Classé", system
        if "premier" in t:
            return "Sauternes Premier Cru Classé", system
    return None, system


def _looks_like_chateau(text: str) -> bool:
    t = text.strip()
    if not t or t.startswith("-") or t.endswith(":"):
        return False
    if len(t) > 60:
        return False
    alpha = [c for c in t if c.isalpha()]
    if len(alpha) < 3:
        return False
    upper_ratio = sum(c.isupper() for c in alpha) / len(alpha)
    return upper_ratio >= 0.5


def parse_reference(html: str) -> list[dict]:
    tree = HTMLParser(html)
    body = tree.css_first("body") or tree.root
    rows: list[dict] = []
    classification: str | None = None
    system: str | None = None
    # NB: traverse() yields nodes in true document order; css("h..,p") does NOT
    # (it groups by selector), which would mis-assign every château to the last
    # section header.
    for node in body.traverse(include_text=False):
        if node.tag in ("h2", "h3", "h4"):
            htext = node.text(strip=True)
            if htext:  # ignore empty <h4></h4> spacers — don't reset classification
                classification, system = classify_header(htext, system)
        elif node.tag == "p" and classification:
            text = node.text(strip=True)
            if _looks_like_chateau(text):
                rows.append({"chateau": text.strip(), "classification": classification})
    # de-dup (some pages repeat names)
    seen, out = set(), []
    for r in rows:
        key = (r["chateau"].lower(), r["classification"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


# Communes/appellations some lists append to the château name ("BATAILLEY PAUILLAC").
_COMMUNE_TAIL = re.compile(
    r"\b("
    r"cantenac margaux|pessac leognan|haut medoc|saint laurent|st laurent|"
    r"saint julien|st julien|saint estephe|st estephe|saint emilion|st emilion|"
    r"pauillac|margaux|cantenac|labarde|ludon|arsac|pessac|leognan|sauternes|"
    r"barsac|medoc|moulis|listrac|bommes|preignac|fargues|soussans"
    r")\b",
)


def norm_name(name: str) -> str:
    n = _strip_accents(name).lower()
    n = re.sub(r"\b(chateau|ch|domaine|maison)\b\.?", " ", n)
    n = re.sub(r"\(.*?\)", " ", n)  # drop parentheticals e.g. "(margaux)", "(duffau...)"
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    # Strip a trailing commune/appellation token (only when something remains).
    m = _COMMUNE_TAIL.search(n)
    if m and m.start() > 0:
        n = n[: m.start()].strip()
    return re.sub(r"\s+", " ", n).strip()


def match_to_producers(ref: list[dict], con: sqlite3.Connection) -> dict:
    producers = con.execute(
        "SELECT producer_key, producer_name, region, subregion FROM dim_producer"
    ).fetchall()
    by_norm: dict[str, list] = {}
    for pk, name, region, sub in producers:
        by_norm.setdefault(norm_name(name), []).append((pk, name, region, sub))
    all_norms = list(by_norm.keys())

    matched, unmatched = [], []
    for r in ref:
        target = norm_name(r["chateau"])
        cands = by_norm.get(target)
        if not cands:
            close = difflib.get_close_matches(target, all_norms, n=1, cutoff=MATCH_THRESHOLD)
            cands = by_norm.get(close[0]) if close else None
        if cands:
            pk, name, region, sub = cands[0]
            matched.append({**r, "producer_key": pk, "producer_name": name,
                            "region": region, "subregion": sub,
                            "ambiguous": len(cands) > 1,
                            "candidate_keys": [c[0] for c in cands],
                            "candidates": [f"{c[1]} ({c[2]}/{c[3]})" for c in cands]})
        else:
            unmatched.append(r)
    return {"matched": matched, "unmatched": unmatched}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write dim_wine.classification")
    args = ap.parse_args()

    ref = parse_reference(HTML.read_text(encoding="utf-8"))
    REF_OUT.parent.mkdir(exist_ok=True)
    REF_OUT.write_text(json.dumps(ref, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Parsed {len(ref)} classed châteaux → {REF_OUT}")
    by_class: dict[str, int] = {}
    for r in ref:
        by_class[r["classification"]] = by_class.get(r["classification"], 0) + 1
    for cls, n in sorted(by_class.items()):
        print(f"   {n:>3}  {cls}")

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True) if not args.apply else sqlite3.connect(DB)
    res = match_to_producers(ref, con)
    m, u = res["matched"], res["unmatched"]
    print(f"\nMatched {len(m)}/{len(ref)} châteaux to dim_producer "
          f"({100*len(m)/len(ref):.0f}%); {len(u)} unmatched.")
    print("--- sample matches ---")
    for r in m[:20]:
        flag = " [AMBIGUOUS]" if r["ambiguous"] else ""
        print(f"   {r['chateau']:<28} → {r['producer_name']} ({r['region']}/{r['subregion']}) "
              f":: {r['classification']}{flag}")
    if u:
        print("--- unmatched (first 20) ---")
        for r in u[:20]:
            print(f"   {r['chateau']}  ({r['classification']})")

    if not args.apply:
        print("\nDRY RUN — no DB writes. Re-run with --apply once matches look right.")
        return

    # Apply UNAMBIGUOUS matches only; defer ambiguous ones to a review file so a
    # genuine name collision (e.g. the two "Lagrange") never gets mislabelled.
    unamb = [r for r in m if not r["ambiguous"]]
    amb = [r for r in m if r["ambiguous"]]
    review = ROOT / "reference" / "bordeaux_classification_review.json"
    review.write_text(json.dumps(amb, ensure_ascii=False, indent=2), encoding="utf-8")

    cur = con.cursor()
    updated = 0
    for r in unamb:
        for wine_key, cuvee_norm in cur.execute(
            "SELECT wine_key, cuvee_norm FROM dim_wine WHERE producer_key = ?",
            (r["producer_key"],),
        ).fetchall():
            if not (cuvee_norm or "").strip():  # grand vin only
                cur.execute(
                    "UPDATE dim_wine SET classification = ? WHERE wine_key = ? "
                    "AND (classification IS NULL OR classification = '')",
                    (r["classification"], wine_key),
                )
                updated += cur.rowcount
    con.commit()
    print(f"\nAPPLIED — set classification on {updated} grand-vin rows "
          f"from {len(unamb)} unambiguous châteaux.")
    print(f"DEFERRED {len(amb)} ambiguous châteaux → {review} (resolve manually).")


if __name__ == "__main__":
    main()
