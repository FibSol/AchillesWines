# REGISTER_IN_CLI = True
"""
Tastingbook.com critic-panel scraper — James Suckling ratings.

Why this exists
---------------
The sibling ``james_suckling`` scraper targets jamessuckling.com directly, but
that site is a client-side Next.js SPA behind a paywall (scores render only for
logged-in subscribers) — it self-disables with ``scraper_not_applicable``.

Tastingbook.com, by contrast, server-side-renders a multi-critic panel per wine
using schema.org microdata, and **James Suckling's score is shown publicly**.
We resolve each cellar wine to its Tastingbook page, parse the panel, and import
**only the James Suckling score** (critic_code = 'JS').

Important coverage caveats (be honest about these):
  * Tastingbook's panel is fed from press releases + a competition jury
    ("BWW Finalist") + importers. Coverage skews to famous/marketed wines;
    small growers are often absent → expect a low hit-rate on a grower-heavy
    cellar. Misses are written to the DLQ as ``unmatched_wine`` (not errors).
  * The other panellists ("Wine Importer", "BWW Finalist", amateurs) do NOT map
    cleanly onto our critic_code enum, so we deliberately import JS only.
    ``parse_panel`` still returns the full panel for inspection/debugging.

URL grammar (verified against several wines)::

    /wine/{producer_slug}/{wine_slug}_{vintage}

    slug rule: lowercase → strip accents → DELETE hyphens & apostrophes
               (Puligny-Montrachet → pulignymontrachet,
                Romanée-Conti      → romaneeconti)
               → any other non-alphanumeric run → single underscore
    wine_slug: slugify(appellation + cuvée); for Bordeaux châteaux the wine name
               equals the producer name, so wine_slug == producer_slug.

source_code = 'tastingbook'  (tier D_user_aggregate)
critic_code = 'JS'           (/100 scale)
"""
import difflib
import hashlib
import logging
import re
import time
import unicodedata
import uuid
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

try:
    import httpx
    from selectolax.parser import HTMLParser
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

from .base import BaseScraper, ScrapeResult
from ..identity import compute_wine_key, normalize_producer, normalize_cuvee
from ..dlq import write_dlq

_logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_BASE = "https://tastingbook.com"

CRITIC_CODE = "JS"
# Tastingbook global author id for James Suckling (stable across all wines).
_JS_AUTHOR_ID = "7668"
# Politeness delay between wine-page fetches (seconds).
_REQUEST_DELAY = 1.2


# ---------------------------------------------------------------------------
# Slug construction
# ---------------------------------------------------------------------------

def slugify_tb(s: str) -> str:
    """Tastingbook slug rule: lowercase, strip accents, delete hyphens and
    apostrophes (joining adjacent chars), then collapse every other run of
    non-alphanumerics into a single underscore.

    >>> slugify_tb("Château Margaux")
    'chateau_margaux'
    >>> slugify_tb("Puligny-Montrachet 1er Cru Les Combettes")
    'pulignymontrachet_1er_cru_les_combettes'
    >>> slugify_tb("Domaine de la Romanée-Conti")
    'domaine_de_la_romaneeconti'
    """
    if not s:
        return ""
    out = unicodedata.normalize("NFKD", str(s))
    out = "".join(c for c in out if not unicodedata.combining(c))
    out = out.lower()
    out = out.replace("’", "").replace("'", "")  # drop apostrophes
    out = out.replace("-", "")                    # delete hyphens (join)
    out = re.sub(r"[^a-z0-9]+", "_", out)         # everything else → underscore
    return out.strip("_")


def _wine_slug_candidates(appellation: str, cuvee: str, producer: str) -> list[str]:
    """Ordered, de-duplicated wine-slug candidates for the second path segment.

    Tastingbook's wine name is usually ``appellation + cuvée``; for Bordeaux it
    is the château (== producer). We try the most specific forms first.
    """
    cuvee = (cuvee or "").strip()
    appellation = (appellation or "").strip()
    producer = (producer or "").strip()

    raw: list[str] = []
    # 1. appellation + cuvée — only when the cuvée doesn't already carry the
    #    appellation (our cuvée strings often do, e.g. "Puligny-Montrachet 1er
    #    Cru …"), which would otherwise double the slug.
    if (
        appellation and cuvee
        and cuvee.lower() not in appellation.lower()
        and not cuvee.lower().startswith(appellation.lower())
    ):
        raw.append(f"{appellation} {cuvee}")
    # 2. cuvée alone (already often carries the appellation prefix in our data)
    if cuvee:
        raw.append(cuvee)
    # 3. appellation alone (village/regional wines with no distinct cuvée)
    if appellation:
        raw.append(appellation)
    # 4. producer (Bordeaux château case: wine name == producer)
    if producer:
        raw.append(producer)

    seen: set[str] = set()
    out: list[str] = []
    for r in raw:
        slug = slugify_tb(r)
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def candidate_urls(
    producer: str,
    appellation: str,
    cuvee: str,
    vintage: Optional[int],
) -> list[str]:
    """Build ordered candidate Tastingbook wine-page URLs for one wine.

    Returns [] when there is no vintage (Tastingbook keys pages by vintage and
    we have no reliable NV slug convention) or no producer.
    """
    if vintage is None:
        return []
    p_slug = slugify_tb(producer)
    if not p_slug:
        return []
    urls: list[str] = []
    for w_slug in _wine_slug_candidates(appellation, cuvee, producer):
        urls.append(f"{_BASE}/wine/{p_slug}/{w_slug}_{vintage}")
    return urls


# ---------------------------------------------------------------------------
# Producer-page discovery (the robust resolver)
# ---------------------------------------------------------------------------
#
# Guessing the wine slug is brittle. Instead we resolve the producer's canonical
# /p/{slug} page and read its real /wine/ links. This also fixes French-domaine
# slug quirks ("&" → "et", a "Domaine"/"Château" prefix that our data omits).

def producer_slug_candidates(producer: str) -> list[str]:
    """Ordered, de-duplicated /p/ producer-slug candidates."""
    if not producer:
        return []
    base = producer.replace("&", " et ").replace("+", " et ")
    low = slugify_tb(base)
    variants: list[str] = [low]
    has_prefix = re.match(r"^(domaine|chateau|château|maison|clos)\b", base.strip(), re.I)
    if not has_prefix:
        variants.append(slugify_tb("domaine " + base))
        variants.append(slugify_tb("chateau " + base))
    else:
        # also try without the leading structural word
        variants.append(slugify_tb(re.sub(r"^(domaine|chateau|château|maison)\s+", "", base, flags=re.I)))
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def parse_producer_wine_links(html: str) -> list[tuple[str, str, Optional[int]]]:
    """Return (path, wine_slug, vintage) for every /wine/ link on a producer page."""
    out: list[tuple[str, str, Optional[int]]] = []
    seen: set[str] = set()
    for m in re.finditer(r'href="(/wine/[^"/]+/([^"/?]+))(?:\?[^"]*)?"', html):
        path, wine_slug = m.group(1), m.group(2)
        if path in seen:
            continue
        seen.add(path)
        vm = re.search(r"_((?:19|20)\d{2})$", wine_slug)
        vintage = int(vm.group(1)) if vm else None
        out.append((path, wine_slug, vintage))
    return out


def _best_wine_match(
    links: list[tuple[str, str, Optional[int]]],
    cuvee: str,
    appellation: str,
    vintage: int,
) -> Optional[str]:
    """Pick the best wine path for the target vintage by slug similarity."""
    same_vintage = [(p, s) for (p, s, v) in links if v == vintage]
    if not same_vintage:
        return None
    if len(same_vintage) == 1:
        return same_vintage[0][0]
    target = slugify_tb(f"{appellation} {cuvee}") if cuvee else slugify_tb(appellation)
    target = re.sub(r"_(?:19|20)\d{2}$", "", target)

    def score(slug: str) -> float:
        s = re.sub(r"_(?:19|20)\d{2}$", "", slug)
        return difflib.SequenceMatcher(None, target, s).ratio()

    best_path, best = None, 0.0
    for path, slug in same_vintage:
        r = score(slug)
        if r > best:
            best, best_path = r, path
    return best_path if best >= 0.5 else None


def resolve_wine_url(
    client: "httpx.Client",
    producer: str,
    appellation: str,
    cuvee: str,
    vintage: Optional[int],
    *,
    delay: float = _REQUEST_DELAY,
) -> Optional[str]:
    """Resolve a cellar wine to a real Tastingbook wine-page URL, or None.

    Strategy: producer-page discovery first (robust), then fall back to direct
    slug construction (cheap, covers the Bordeaux producer==wine case).
    """
    if vintage is None or not producer:
        return None

    # 1. Producer-page discovery. Tastingbook returns a generic shell (with
    #    ~1000 unrelated sidebar links) for unknown /p/ slugs, so we identify the
    #    real producer page by its *own* wine links — those whose producer path
    #    segment equals the /p/ slug.
    for p_slug in producer_slug_candidates(producer):
        try:
            resp = client.get(f"{_BASE}/p/{p_slug}")
        except Exception:
            continue
        time.sleep(delay)
        own = [
            (path, slug, v)
            for (path, slug, v) in parse_producer_wine_links(resp.text)
            if path.split("/")[2] == p_slug
        ]
        if not own:
            continue  # soft-404 / wrong producer slug
        match = _best_wine_match(own, cuvee, appellation, vintage)
        if match:
            return f"{_BASE}{match}"
        # Real producer page, but this vintage/cuvée isn't covered — stop.
        return None

    # 2. Direct slug construction fallback.
    for url in candidate_urls(producer, appellation, cuvee, vintage):
        try:
            resp = client.get(url)
        except Exception:
            continue
        time.sleep(delay)
        if is_real_wine_page(HTMLParser(resp.text)):
            return url
    return None


# ---------------------------------------------------------------------------
# Page parsing (schema.org microdata)
# ---------------------------------------------------------------------------

@dataclass
class CriticRating:
    author: str
    author_id: Optional[str]
    score: float
    note: Optional[str] = None


def _parse_score(content: str) -> Optional[float]:
    """'100,0' / '99,0' (European decimal comma) → float."""
    if not content:
        return None
    try:
        return float(content.strip().replace(",", "."))
    except ValueError:
        return None


def is_real_wine_page(tree: "HTMLParser") -> bool:
    """Tastingbook returns HTTP 200 for unknown wines (a generic SPA shell).
    A genuine wine page carries schema.org review microdata and the
    ``#vintage-tasting`` article. Use those as the discriminator.
    """
    if tree.css_first("article#vintage-tasting") is not None:
        return True
    return tree.css_first("[itemprop='review']") is not None


def parse_panel(html: str) -> list[CriticRating]:
    """Extract the full critic panel from a Tastingbook wine page.

    Each review (both the compact 'Latest tasting notes' list and the longer
    'Written Notes') is wrapped in its own ``[itemprop='review']`` container
    holding an ``[itemprop='author']`` and an ``[itemprop='ratingValue']`` meta,
    so we pair them per-container (order-independent).
    """
    tree = HTMLParser(html)
    out: list[CriticRating] = []
    for block in tree.css("[itemprop='review']"):
        author_el = block.css_first("[itemprop='author']")
        rating_el = block.css_first("[itemprop='ratingValue']")
        if author_el is None or rating_el is None:
            continue
        score = _parse_score(rating_el.attributes.get("content", "") or "")
        if score is None:
            continue
        author = (author_el.text() or "").strip()
        href = author_el.attributes.get("href", "") or ""
        m = re.search(r"/user/show/id/(\d+)", href)
        author_id = m.group(1) if m else None
        desc_el = block.css_first("[itemprop='description']")
        note = (desc_el.text() or "").strip() if desc_el is not None else None
        out.append(CriticRating(author=author, author_id=author_id, score=score, note=note))
    return out


def extract_js(panel: list[CriticRating]) -> Optional[CriticRating]:
    """Return a single James Suckling rating from the panel, or None.

    Matches on the stable Tastingbook author id (7668) first, then falls back
    to a name match. If several JS entries exist (summary + written note echo
    the same score), prefer the one carrying a tasting note, else the highest.
    """
    js = [
        r for r in panel
        if r.author_id == _JS_AUTHOR_ID or "james suckling" in r.author.lower()
    ]
    if not js:
        return None
    with_note = [r for r in js if r.note]
    if with_note:
        return max(with_note, key=lambda r: r.score)
    return max(js, key=lambda r: r.score)


def _normalize_score_to_100(score: float) -> Optional[float]:
    return score if 0 <= score <= 100 else None


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class TastingbookScraper(BaseScraper):
    source_code = "tastingbook"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def _cellar_wines(self) -> list[sqlite3.Row]:
        """Distinct wines currently in the cellar (the import target set)."""
        return self.conn.execute(
            """
            SELECT DISTINCT w.wine_key, p.producer_name, a.appellation_name,
                   w.cuvee_name, w.vintage
            FROM cellar_inventory ci
            JOIN dim_wine w        ON w.wine_key = ci.wine_key
            JOIN dim_producer p    ON p.producer_key = w.producer_key
            JOIN dim_appellation a ON a.appellation_key = w.appellation_key
            WHERE w.vintage IS NOT NULL
            """
        ).fetchall()

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependencies: httpx or selectolax not installed")

        batch_id = self.batch_id or f"tastingbook-{datetime.utcnow():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
        result = ScrapeResult(batch_id=batch_id)

        source_row = self.conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = ?", (self.source_code,)
        ).fetchone()
        if not source_row:
            return ScrapeResult(
                error=(
                    "source_code 'tastingbook' not registered in dim_source. "
                    "Run scripts/register-tastingbook-source.mjs (or re-seed) first."
                )
            )
        source_key = source_row[0]

        self.conn.row_factory = sqlite3.Row
        wines = self._cellar_wines()
        if limit is not None:
            wines = wines[:limit]

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Accept-Language": "en;q=0.9,fr;q=0.8",
        }

        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            for w in wines:
                result.rows_fetched += 1
                wine_key = w["wine_key"]
                matched_url = resolve_wine_url(
                    client, w["producer_name"], w["appellation_name"],
                    w["cuvee_name"], w["vintage"],
                )
                if matched_url is None:
                    result.rows_dlq += 1
                    write_dlq(self.conn, source_key, batch_id, "unmatched_wine",
                              "No Tastingbook page resolved (producer/vintage not covered)",
                              {"wine_key": wine_key, "producer": w["producer_name"],
                               "vintage": w["vintage"]})
                    continue

                try:
                    resp = self._fetch(lambda u=matched_url: client.get(u))
                    time.sleep(_REQUEST_DELAY)
                except Exception as exc:
                    result.rows_dlq += 1
                    write_dlq(self.conn, source_key, batch_id, "network_error",
                              str(exc), {"url": matched_url})
                    continue
                js = extract_js(parse_panel(resp.text))

                if js is None:
                    # Page exists but James Suckling did not rate this wine.
                    result.rows_dlq += 1
                    write_dlq(self.conn, source_key, batch_id, "insufficient_data",
                              "Tastingbook page found but no James Suckling score",
                              {"wine_key": wine_key, "url": matched_url})
                    continue

                score_norm = _normalize_score_to_100(js.score)
                if score_norm is None or not (50 <= js.score <= 100):
                    result.rows_dlq += 1
                    write_dlq(self.conn, source_key, batch_id, "validation_error",
                              f"JS score {js.score} out of plausible range",
                              {"wine_key": wine_key, "url": matched_url})
                    continue

                content_hash = hashlib.sha256(
                    f"{wine_key}:{CRITIC_CODE}:{js.score}".encode()
                ).hexdigest()
                try:
                    self.conn.execute(
                        """
                        INSERT OR IGNORE INTO fact_rating
                        (wine_key, source_key, critic_code, reviewer_type, score, scale,
                         score_normalized_100, source_url, content_hash, batch_id)
                        VALUES (?, ?, ?, 'critic', ?, '/100', ?, ?, ?, ?)
                        """,
                        (wine_key, source_key, CRITIC_CODE, js.score, score_norm,
                         matched_url, content_hash, batch_id),
                    )
                    self.conn.commit()
                    result.rows_inserted += 1
                except Exception as exc:
                    result.rows_dlq += 1
                    write_dlq(self.conn, source_key, batch_id, "validation_error",
                              str(exc), {"wine_key": wine_key, "score": js.score})

        return result
