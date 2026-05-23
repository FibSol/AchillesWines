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

def normalize_score_to_100(score: float, scale: str) -> float:
    if scale == "/100":
        return score
    elif scale == "/20":
        return (score / 20) * 100
    elif scale in ("/5", "stars"):
        return (score / 5) * 100
    raise ValueError(f"Unknown scale: {scale}")
