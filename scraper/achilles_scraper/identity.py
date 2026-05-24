import re
import unicodedata
import hashlib

def norm_text(s) -> str:
    if not s:
        return ""
    out = unicodedata.normalize("NFKD", str(s))
    out = "".join(c for c in out if not unicodedata.combining(c))
    out = out.lower()
    out = re.sub(r"[,.'\"\/\-()\[\]_&+]", " ", out)
    return re.sub(r"\s+", " ", out).strip()

_PREFIX_MAP = [
    (re.compile(r"^d\s+"), "domaine "),
    (re.compile(r"^dom\s+"), "domaine "),
    (re.compile(r"^ch\s+"), "chateau "),
]

def expand_producer_prefix(normalized: str) -> str:
    for pattern, replacement in _PREFIX_MAP:
        if pattern.match(normalized):
            return pattern.sub(replacement, normalized, count=1)
    return normalized

_CUVEE_TAIL_STRIPS = [
    re.compile(r"\b1\s*er\s+(grand\s+)?cru(\s+classe)?\b", re.I),
    re.compile(r"\b[2-5](\s*e|eme|ème)\s+cru(\s+classe)?\b", re.I),
    re.compile(r"\bgrand\s+cru(\s+classe)?\b", re.I),
    re.compile(r"\baoc?\s+[a-z\- ]+$", re.I),
    re.compile(r"\b(19|20)\d{2}\b"),
    re.compile(r"\b\d+\s*ml\b", re.I),
    re.compile(r"\b\d+\s*cl\b", re.I),
    re.compile(r"\b(magnum|jeroboam|mathusalem|salmanazar|balthazar|nabuchodonosor)\b", re.I),
]

_VINTAGE_RE = re.compile(r"\b(19|20)\d{2}\b")

def clean_cuvee_tails(normalized: str) -> str:
    out = normalized
    for pattern in _CUVEE_TAIL_STRIPS:
        out = pattern.sub(" ", out)
    return re.sub(r"\s+", " ", out).strip()

def normalize_producer(name: str) -> str:
    """Normalize a producer/estate name.

    Strips vintage years (e.g. "Château Lynch-Bages 2010" → "chateau lynch bages")
    so that per-vintage dim_producer artifacts from the BM import don't pollute
    the wine_key — all scrapers should anchor on the estate name alone.
    """
    n = norm_text(name)
    n = _VINTAGE_RE.sub(" ", n)
    return expand_producer_prefix(re.sub(r"\s+", " ", n).strip())

def normalize_cuvee(name: str, *, strip_words: "list[str] | None" = None) -> str:
    """Normalize a cuvée name.

    ``strip_words`` is an optional list of normalized tokens (e.g. a producer norm
    or an appellation norm) to remove before normalization.  Pass them to avoid
    the producer name or appellation leaking into the cuvée component of the
    wine_key and causing cross-scraper divergence.
    """
    base = norm_text(name)
    if strip_words:
        for word in strip_words:
            if word:
                base = re.sub(r"\b" + re.escape(word) + r"\b", " ", base)
        base = re.sub(r"\s+", " ", base).strip()
    return clean_cuvee_tails(base)

def compute_wine_key(
    producer_norm: str,
    cuvee_norm: str,
    vintage: "int | None",
    appellation_norm: str = "",   # kept for backward compat but NOT hashed
    bottle_ml: int = 750,
) -> str:
    """Compute a deterministic 16-char hex wine identity key.

    appellation_norm is intentionally excluded from the hash: different scrapers
    have wildly different appellation extraction quality (API attribute vs title
    heuristic vs fallback "vin de france"), which would produce unique hashes for
    the same physical wine.  appellation still lives in dim_wine; it just doesn't
    contribute to the deduplication key.
    """
    v = "NV" if vintage is None else str(vintage)
    raw = f"{producer_norm}|{cuvee_norm}|{v}|{bottle_ml}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]

# ---------------------------------------------------------------------------
# Display-name cleanup (operates on raw strings, not norms).
# These rules mirror scripts/cleanup-producer-names.mjs and
# scripts/cleanup-cuvee-noise.mjs — keep them in sync.
# ---------------------------------------------------------------------------

_PRODUCER_SHOP_CODE_RES = [
    re.compile(r"\s*\(CB\d{1,2}\)", re.I),
    re.compile(r"\s*\(C\d{1,2}\)", re.I),
    re.compile(r"\s+CB\d{1,2}\b", re.I),
    re.compile(r"\s+C\d{1,2}\b(?![A-Za-z])", re.I),
]
_PRODUCER_SIZE_RES = [
    re.compile(r"\s+\d+\s*(ml|cl|l)\b", re.I),
    re.compile(r"\s+-?\s*magnum\b", re.I),
    re.compile(r"\s+-?\s*jeroboam\b", re.I),
    re.compile(r"\s+-?\s*demi[- ]bouteille\b", re.I),
    re.compile(r"\s+-?\s*half[- ]bottle\b", re.I),
]
_PRODUCER_PACKAGING_RE = re.compile(
    r"\s*\b(in\s+houten\s+kist|original\s+wooden\s+case|owc|caisse\s+bois|coffret(\s+(or|argent))?|en\s+coffret|en\s+etui|\+\s*coffret.*)$",
    re.I,
)
_PRODUCER_CLASSIFICATION_TAILS = [
    re.compile(r"\s*,\s*(1\s*er|premier)\s+grand\s+cru\s+class[ée](\s+[AB])?\s*$", re.I),
    re.compile(r"\s+-\s+(1\s*er|premier)\s+grand\s+cru\s+class[ée](\s+[AB])?\s*$", re.I),
    re.compile(r"\s*,\s*grand\s+cru\s+class[ée]\s*$", re.I),
    re.compile(r"\s+-\s+grand\s+cru\s+class[ée]\s*$", re.I),
    re.compile(r"\s*,\s*1\s*er\s+cru(\s+class[ée])?\s*$", re.I),
    re.compile(r"\s+-\s+1\s*er\s+cru(\s+class[ée])?\s*$", re.I),
    re.compile(r"\s*,\s*grand\s+cru\s*$", re.I),
    re.compile(r"\s+-\s+grand\s+cru\s*$", re.I),
    re.compile(r"\s*,\s*cru\s+bourgeois(\s+sup[ée]rieur|\s+exceptionnel)?\s*$", re.I),
]
_APP_WORDS = (
    r"saint[- ]?[eé]milion(?:\s+grand\s+cru(?:\s+class[ée])?)?|"
    r"pessac[- ]?l[ée]ognan|saint[- ]?julien|saint[- ]?est[èe]phe|"
    r"pauillac|margaux|haut[- ]?m[ée]doc|m[ée]doc|graves|sauternes|barsac|"
    r"pomerol|fronsac|listrac|moulis|"
    r"chablis(?:\s+grand\s+cru|\s+1\s*er\s+cru)?|"
    r"gevrey[- ]?chambertin|vosne[- ]?roman[ée]e|pommard|meursault|"
    r"puligny[- ]?montrachet|chassagne[- ]?montrachet|"
    r"sancerre|chinon|vouvray|c[ôo]tes?[- ]du[- ]rh[ôo]ne|ch[âa]teauneuf[- ]du[- ]pape|"
    r"brunello\s+di\s+montalcino|barolo|barbaresco"
)
_PRODUCER_APP_TAIL_RE = re.compile(
    rf"(\s*,\s*|\s+-\s+|\s+\(\s*)(?:{_APP_WORDS})\s*\)?\s*$", re.I,
)
_PRODUCER_APP_TAIL_UPPER_RE = re.compile(
    r"\s+(ST[- ]?EMILION|ST[- ]?ESTEPHE|ST[- ]?JULIEN|PAUILLAC|MARGAUX|PESSAC|GRAVES|SAUTERNES|MEDOC|HAUT[- ]?MEDOC|MOULIS|LISTRAC|FRONSAC|POMEROL|BARSAC|CHABLIS)\s*$",
    re.I,
)
_PRODUCER_COLOR_SUFFIX_RE = re.compile(
    r"\s+(?:-|–|,)\s+(rouge|blanc|rose|rosé|red|white)\s*$", re.I,
)
_PRODUCER_COLON_VINTAGE_RE = re.compile(r"\s*:\s*vintage\s*$", re.I)
_ALL_CAPS_RE = re.compile(r"^[^a-z]{6,}$")
_VINTAGE_TEST_RE = re.compile(r"\b(19|20)\d{2}\b")
_STRUCT_TOKENS = {
    "CH", "CHATEAU", "CHÂTEAU", "DOMAINE", "MAISON", "BODEGA", "A",
    "DE", "DU", "LA", "LE", "LES", "DOM", "&", "ET",
}

def _is_producer_polluted(name: str) -> bool:
    if _VINTAGE_TEST_RE.search(name):
        return True
    if _ALL_CAPS_RE.match(name):
        return True
    if re.search(r"\(\s*CB?\d", name):
        return True
    if re.search(r"\d+\s*(CL|ML|L)\b", name, re.I) and re.search(r"\s", name):
        return True
    if re.search(r"\b(coffret|owc|houten kist|en coffret|en etui)\b", name, re.I):
        return True
    if re.search(r",\s*(saint[- ]?[eé]milion|pessac[- ]?l[ée]ognan|pauillac|margaux|grand\s+cru|1\s*er\s+cru|cru\s+bourgeois)", name, re.I):
        return True
    if _PRODUCER_COLOR_SUFFIX_RE.search(name):
        return True
    return False

def _is_mutilated(orig: str, cleaned: str) -> bool:
    if not cleaned or len(cleaned) < 4:
        return True
    tokens = [t for t in cleaned.split() if len(t) > 1]
    if not tokens:
        return True
    if tokens[-1].upper() in _STRUCT_TOKENS:
        return True
    meaningful = [t for t in cleaned.split() if len(t) >= 3 and t.upper() not in _STRUCT_TOKENS and not t[0].isdigit()]
    if len(meaningful) >= 2:
        return False
    if len(cleaned) / len(orig) < 0.25:
        return True
    return False

def clean_producer_display(name: str) -> str:
    """Strip vintage / shop SKU / bottle size / packaging / classification & appellation
    tails / color suffix from a producer display name.

    Returns ``name`` unchanged when:
      • the name is not unambiguously polluted, or
      • the cleanup would mutilate the name (kill a real surname like Margaux).

    This mirrors the JS scripts/cleanup-producer-names.mjs rules — keep in sync.
    """
    if not name or not _is_producer_polluted(name):
        return name
    out = name
    for r in _PRODUCER_SHOP_CODE_RES:    out = r.sub(" ", out)
    for r in _PRODUCER_SIZE_RES:         out = r.sub(" ", out)
    out = _PRODUCER_PACKAGING_RE.sub(" ", out)
    out = _VINTAGE_TEST_RE.sub(" ", out)
    for r in _PRODUCER_CLASSIFICATION_TAILS: out = r.sub("", out)
    out = _PRODUCER_APP_TAIL_RE.sub("", out)
    if _ALL_CAPS_RE.match(name):
        out = _PRODUCER_APP_TAIL_UPPER_RE.sub("", out)
        # Strip trailing color word only after a year / shop code / separator.
        out = re.sub(
            r"(?:\d{4}|\(?C\d{1,2}\)?|[,\-])\s+(ROUGE|BLANC|ROSE|ROSÉ|RED|WHITE)\b",
            lambda m: re.sub(r"\s+(ROUGE|BLANC|ROSE|ROSÉ|RED|WHITE)\b", "", m.group(0), flags=re.I),
            out, flags=re.I,
        )
        out = re.sub(r"\s+(C\d{1,2}|A\s*VIS|RY\s+D'?ARGENT)\b\.?", " ", out)
    out = _PRODUCER_COLOR_SUFFIX_RE.sub("", out)
    out = _PRODUCER_COLON_VINTAGE_RE.sub("", out)
    out = re.sub(r"\s*[-–—|]\s*[-–—|]\s*", " - ", out)
    out = re.sub(r"\(\s*\)", " ", out)
    out = re.sub(r"\s+,", ",", out)
    out = re.sub(r"^\s*[,\-–—:]+\s*", "", out)
    out = re.sub(r"\s*[,\-–—:]+\s*$", "", out)
    out = re.sub(r"\s+", " ", out).strip()
    if _is_mutilated(name, out):
        return name
    return out

# ---- cuvée display cleanup ----

_BARREL_SAMPLE_RE = re.compile(r"\bbarrel\s+sample\b", re.I)
_PARENS_APPELLATION_RE = re.compile(rf"\s*\(\s*(?:{_APP_WORDS})\s*\)", re.I)
_GENERIC_BLEND_RE = re.compile(
    r"\b(bordeaux[- ]style\s+red\s+blend|red\s+blend|white\s+blend|rh[ôo]ne[- ]style\s+(red|white)\s+blend)\b",
    re.I,
)

def clean_cuvee_display(name: str, producer_name: str | None = None) -> str:
    """Strip CellarTracker/scraper noise from a cuvée display name:
      • "Barrel sample" (anywhere)
      • parenthesised appellations like "(Saint-Émilion)"
      • generic blend pseudo-cuvées ("Bordeaux-style Red Blend", "Red Blend", "White Blend")
      • a leading copy of the producer name (some scrapers prepend it).
      • apostrophe-space: "d' Angélus" → "d'Angélus", "l' Église" → "l'Église"

    Returns "" when nothing meaningful is left (signals grand-vin).
    """
    if not name:
        return ""
    out = name
    out = _BARREL_SAMPLE_RE.sub(" ", out)
    out = _PARENS_APPELLATION_RE.sub(" ", out)
    out = _GENERIC_BLEND_RE.sub(" ", out)
    if producer_name:
        esc = re.escape(producer_name)
        out = re.sub(rf"^\s*{esc}\s+", "", out, flags=re.I)
    # Fix elision apostrophe-space for French particles: "d' X" → "d'X", "l' X" → "l'X"
    # Requires the particle to follow a space or start-of-string so mid-word apostrophes
    # ("C'D'C' Rosso", "Ca' di Mori") are not touched.
    out = re.sub(r"(^|\s)(d|l|n|j|m|s|c|qu)'\s+([A-Za-zÀ-ÿ])", r"\1\2'\3", out, flags=re.I)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s*[-–—|]\s*[-–—|]\s*", " - ", out)
    out = re.sub(r"^\s*[,\-–—:]+\s*", "", out)
    out = re.sub(r"\s*[,\-–—:]+\s*$", "", out)
    return out.strip()


def normalize_score_to_100(score: float, scale: str) -> float:
    if scale == "/100":
        return score
    elif scale == "/20":
        return (score / 20) * 100
    elif scale in ("/5", "stars"):
        return (score / 5) * 100
    raise ValueError(f"Unknown scale: {scale}")
