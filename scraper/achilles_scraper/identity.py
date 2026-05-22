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

def clean_cuvee_tails(normalized: str) -> str:
    out = normalized
    for pattern in _CUVEE_TAIL_STRIPS:
        out = pattern.sub(" ", out)
    return re.sub(r"\s+", " ", out).strip()

def normalize_producer(name: str) -> str:
    return expand_producer_prefix(norm_text(name))

def normalize_cuvee(name: str) -> str:
    return clean_cuvee_tails(norm_text(name))

def compute_wine_key(producer_norm: str, cuvee_norm: str, vintage, appellation_norm: str, bottle_ml: int = 750) -> str:
    v = "NV" if vintage is None else str(vintage)
    raw = f"{producer_norm}|{cuvee_norm}|{v}|{appellation_norm}|{bottle_ml}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]

def normalize_score_to_100(score: float, scale: str) -> float:
    if scale == "/100":
        return score
    elif scale == "/20":
        return (score / 20) * 100
    elif scale in ("/5", "stars"):
        return (score / 5) * 100
    raise ValueError(f"Unknown scale: {scale}")
