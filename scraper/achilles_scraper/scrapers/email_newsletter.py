"""
EmailNewsletterScraper — ADR-011 base class for sources that come from email.

Each subclass declares the From: address it cares about. The scraper:

  1. Opens the dedicated mailbox (env vars).
  2. Searches UNSEEN messages matching the From filter.
  3. For each, saves the .eml to raw/email/<batch_id>/<uid>.eml, extracts the
     HTML body, runs parse_newsletter_html → list[EmailOffer].
  4. Writes offers to staging_price_candidates.
  5. Marks the message \\Seen on success. Failed parses go to DLQ with
     raw_object_path pointing at the saved .eml.

Subclasses can override `_parse_html()` for vendor-specific selectors.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..mailbox import (
    FetchedMessage,
    MailboxConfigError,
    MailboxError,
    extract_html_body,
    load_config_from_env,
    open_mailbox,
)
from ..email_parser import EmailOffer, parse_newsletter_html
from ..identity import (
    compute_wine_key,
    expand_producer_prefix,
    norm_text,
    clean_cuvee_tails,
)
from ..dlq import write_dlq
from ..llm_parser import parse_with_llm
from .base import BaseScraper, ScrapeResult


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_RAW_DIR = PROJECT_ROOT / "raw" / "email"


class EmailNewsletterScraper(BaseScraper):
    """Subclass and set `source_code` + `from_email` + `domain_hints`."""

    # Required overrides:
    source_code: str = ""
    from_email: str = ""

    # Optional: substrings used to recognise product links inside the email.
    domain_hints: tuple[str, ...] = ()

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    # -- DB helpers -----------------------------------------------------------

    def _source_key(self) -> Optional[int]:
        row = self.conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = ?",
            (self.source_code,),
        ).fetchone()
        return row["source_key"] if row else None

    def _insert_candidate(
        self,
        source_key: int,
        batch_id: str,
        offer: EmailOffer,
        content_hash: str,
    ) -> None:
        producer_norm = expand_producer_prefix(norm_text(offer.producer_name))
        cuvee_norm = clean_cuvee_tails(norm_text(offer.cuvee_name))
        wine_key = compute_wine_key(
            producer_norm=producer_norm,
            cuvee_norm=cuvee_norm,
            vintage=offer.vintage,
            appellation_norm="",  # newsletters rarely state the AOC cleanly; left empty.
            bottle_ml=offer.bottle_ml,
        )
        now = int(time.time())
        self.conn.execute(
            """
            INSERT INTO staging_price_candidates
              (wine_key, source_key, retailer, recorded_at, currency_code,
               amount_local, amount_eur, source_url, content_hash, batch_id,
               needs_review)
            VALUES (?, ?, ?, ?, 'EUR', ?, ?, ?, ?, ?, 1)
            """,
            (
                wine_key,
                source_key,
                self.source_code,
                now,
                offer.price_eur,
                offer.price_eur,
                offer.source_url,
                content_hash,
                batch_id,
            ),
        )

    # -- LLM fallback ---------------------------------------------------------

    def _use_llm_fallback(self) -> bool:
        """Return True when this source has use_llm_fallback=1 in dim_source."""
        row = self.conn.execute(
            "SELECT use_llm_fallback FROM dim_source WHERE source_code = ?",
            (self.source_code,),
        ).fetchone()
        if row is None:
            return False
        return bool(row["use_llm_fallback"])

    # -- Parsing override hook ------------------------------------------------

    def _parse_html(self, html: str) -> list[EmailOffer]:
        """Default: generic heuristic. Subclasses override for site-specific selectors."""
        return parse_newsletter_html(html, source_domain_hints=self.domain_hints)

    # -- BaseScraper.run ------------------------------------------------------

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not self.from_email:
            return ScrapeResult(error=f"{self.source_code}: from_email not configured")

        batch_id = self.batch_id or (
            f"{self.source_code}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        )
        result = ScrapeResult(batch_id=batch_id)

        source_key = self._source_key()
        if source_key is None:
            return ScrapeResult(
                error=f"unknown source_code in dim_source: {self.source_code}",
                batch_id=batch_id,
            )

        try:
            cfg = load_config_from_env()
        except MailboxConfigError as e:
            result.error = f"mailbox config: {e}"
            return result

        raw_dir = DEFAULT_RAW_DIR / batch_id
        raw_dir.mkdir(parents=True, exist_ok=True)

        try:
            with open_mailbox(cfg) as mb:
                uids = mb.search_unseen(from_addr=self.from_email)
                if limit is not None:
                    uids = uids[:limit]
                print(f"[{self.source_code}] found {len(uids)} unseen message(s) from {self.from_email}")

                for uid in uids:
                    try:
                        msg = mb.fetch(uid)
                        eml_path = raw_dir / f"{uid.decode('ascii', errors='replace')}.eml"
                        eml_path.write_bytes(msg.raw)
                        result.rows_fetched += 1

                        html = extract_html_body(msg.parsed)
                        if not html.strip():
                            self._dlq(
                                batch_id, msg, eml_path,
                                error_class="parse_error",
                                error_message="empty html/text body",
                            )
                            result.rows_dlq += 1
                            continue

                        offers = self._parse_html(html)
                        if not offers and self._use_llm_fallback():
                            offers = parse_with_llm(html, self.source_code)
                            if offers:
                                print(f"  → LLM fallback extracted {len(offers)} offer(s)")
                        print(
                            f"  uid={uid.decode('ascii', errors='replace')} "
                            f"subject={msg.subject[:60]!r} → {len(offers)} offer(s)"
                        )

                        if not offers:
                            self._dlq(
                                batch_id, msg, eml_path,
                                error_class="parse_error",
                                error_message="no offers extracted",
                            )
                            result.rows_dlq += 1
                            # Don't mark \Seen — let the user inspect / a smarter parser try again.
                            continue

                        # Per-message hash so duplicate newsletters don't repopulate staging.
                        msg_hash = msg.message_id or f"uid:{uid.decode('ascii', errors='replace')}"
                        inserted_this_msg = 0
                        for offer in offers:
                            try:
                                self._insert_candidate(source_key, batch_id, offer, msg_hash)
                                result.rows_inserted += 1
                                inserted_this_msg += 1
                            except sqlite3.Error as e:
                                self._dlq(
                                    batch_id, msg, eml_path,
                                    error_class="schema_drift",
                                    error_message=f"insert failed for {offer.producer_name}: {e}",
                                )
                                result.rows_dlq += 1
                        self.conn.commit()

                        # Mark \Seen (not deleted) once at least one offer was persisted.
                        # Per ADR-011: emails are NEVER deleted — \Seen flags them so the
                        # next run skips them, but they remain visible and recoverable in
                        # the Gmail UI. If all inserts failed, leave UNSEEN for retry.
                        if inserted_this_msg > 0:
                            mb.mark_seen(uid)
                    except MailboxError as e:
                        print(f"  uid={uid!r} mailbox error: {e}")
                        result.rows_dlq += 1
                    except Exception as e:
                        print(f"  uid={uid!r} unexpected error: {e}")
                        result.rows_dlq += 1
        except MailboxError as e:
            result.error = f"mailbox: {e}"
            return result

        return result

    # -- DLQ helper -----------------------------------------------------------

    def _dlq(
        self,
        batch_id: str,
        msg: FetchedMessage,
        eml_path: Path,
        *,
        error_class: str,
        error_message: str,
    ) -> None:
        source_key = self._source_key()
        write_dlq(
            self.conn,
            source_key=source_key,
            batch_id=batch_id,
            error_class=error_class,
            error_message=error_message,
            source_record_id=msg.message_id or msg.uid.decode("ascii", errors="replace"),
            raw_record=json.dumps({
                "from": msg.from_addr,
                "subject": msg.subject,
                "message_id": msg.message_id,
            }),
            raw_object_path=str(eml_path),
        )
