"""
IMAP mailbox client (ADR-011).

A thin wrapper around stdlib `imaplib` + `email.message` for fetching
newsletter emails from a dedicated mailbox. Used by EmailNewsletterScraper.

Connection config from env vars (env-only, never persisted):

    ACHILLES_MAILBOX_HOST       e.g. imap.gmail.com
    ACHILLES_MAILBOX_PORT       e.g. 993
    ACHILLES_MAILBOX_USERNAME   e.g. wine-newsletters@gmail.com
    ACHILLES_MAILBOX_PASSWORD   Gmail app password (16 chars, no spaces)
    ACHILLES_MAILBOX_SSL        "1" / "0" (default 1)
    ACHILLES_MAILBOX_FOLDER     default "INBOX"
"""
from __future__ import annotations

import email
import imaplib
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from email.message import Message
from typing import Iterator, Optional


class MailboxError(Exception):
    pass


class MailboxConfigError(MailboxError):
    """Required ACHILLES_MAILBOX_* env vars are missing or malformed."""


@dataclass(frozen=True)
class MailboxConfig:
    host: str
    port: int
    username: str
    password: str
    use_ssl: bool = True
    starttls: bool = False
    folder: str = "INBOX"

    def __repr__(self) -> str:  # don't leak the password
        return (
            f"MailboxConfig(host={self.host!r}, port={self.port}, "
            f"username={self.username!r}, password=<redacted>, "
            f"use_ssl={self.use_ssl}, starttls={self.starttls}, "
            f"folder={self.folder!r})"
        )

    @property
    def is_local(self) -> bool:
        """True iff host is a loopback address — used to allow self-signed
        certs from Proton Mail Bridge (and similar local proxies) without
        weakening security for real remote hosts.
        """
        return self.host in ("127.0.0.1", "::1", "localhost") or self.host.endswith(".localhost")


def load_config_from_env() -> MailboxConfig:
    host = os.getenv("ACHILLES_MAILBOX_HOST", "").strip()
    user = os.getenv("ACHILLES_MAILBOX_USERNAME", "").strip()
    pw = os.getenv("ACHILLES_MAILBOX_PASSWORD", "")
    if not host or not user or not pw:
        missing = [
            n for n, v in (
                ("ACHILLES_MAILBOX_HOST", host),
                ("ACHILLES_MAILBOX_USERNAME", user),
                ("ACHILLES_MAILBOX_PASSWORD", pw),
            ) if not v
        ]
        raise MailboxConfigError(f"missing env var(s): {', '.join(missing)}")

    port_raw = os.getenv("ACHILLES_MAILBOX_PORT", "993").strip()
    try:
        port = int(port_raw)
    except ValueError as e:
        raise MailboxConfigError(f"ACHILLES_MAILBOX_PORT not an integer: {port_raw!r}") from e

    ssl_raw = os.getenv("ACHILLES_MAILBOX_SSL", "1").strip().lower()
    use_ssl = ssl_raw not in ("0", "false", "no", "")

    starttls_raw = os.getenv("ACHILLES_MAILBOX_STARTTLS", "0").strip().lower()
    starttls = starttls_raw in ("1", "true", "yes")

    # use_ssl and starttls are mutually exclusive (implicit TLS vs upgrade).
    if use_ssl and starttls:
        raise MailboxConfigError(
            "ACHILLES_MAILBOX_SSL and ACHILLES_MAILBOX_STARTTLS are mutually exclusive"
        )

    folder = os.getenv("ACHILLES_MAILBOX_FOLDER", "INBOX").strip() or "INBOX"

    return MailboxConfig(
        host=host, port=port, username=user, password=pw,
        use_ssl=use_ssl, starttls=starttls, folder=folder,
    )


@dataclass(frozen=True)
class FetchedMessage:
    uid: bytes
    message_id: str
    subject: str
    from_addr: str
    raw: bytes
    parsed: Message = field(repr=False)


def _imap_class(use_ssl: bool):
    return imaplib.IMAP4_SSL if use_ssl else imaplib.IMAP4


def _build_starttls_context(allow_self_signed: bool):
    """SSL context for STARTTLS. Loopback hosts (Proton Mail Bridge etc.)
    use a self-signed cert by design — we relax verification only there.
    """
    import ssl
    ctx = ssl.create_default_context()
    if allow_self_signed:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _decode_header(value: Optional[str]) -> str:
    if not value:
        return ""
    parts = email.header.decode_header(value)
    out = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            try:
                out.append(chunk.decode(enc or "utf-8", errors="replace"))
            except (LookupError, TypeError):
                out.append(chunk.decode("utf-8", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out).strip()


def _extract_from_addr(msg: Message) -> str:
    raw = _decode_header(msg.get("From", ""))
    # "Display Name <addr@host>" → addr@host
    if "<" in raw and ">" in raw:
        return raw.split("<", 1)[1].split(">", 1)[0].strip().lower()
    return raw.strip().lower()


@contextmanager
def open_mailbox(cfg: Optional[MailboxConfig] = None) -> Iterator["Mailbox"]:
    """Context manager: connect → login → SELECT folder → yield → logout.

    Supports three transport modes:
      - implicit TLS (use_ssl=True)  — Gmail, classic IMAPS port 993
      - STARTTLS    (starttls=True)  — Proton Mail Bridge (1143), some
        corporate IMAP servers (143/STARTTLS)
      - plain       (both False)     — dev only
    """
    cfg = cfg or load_config_from_env()
    cls = _imap_class(cfg.use_ssl)
    conn = cls(cfg.host, cfg.port)
    try:
        if cfg.starttls:
            ctx = _build_starttls_context(allow_self_signed=cfg.is_local)
            typ, _ = conn.starttls(ssl_context=ctx)
            if typ != "OK":
                raise MailboxError(f"STARTTLS upgrade failed: {typ}")
        typ, _ = conn.login(cfg.username, cfg.password)
        if typ != "OK":
            raise MailboxError(f"login failed: {typ}")
        typ, _ = conn.select(cfg.folder, readonly=False)
        if typ != "OK":
            raise MailboxError(f"folder {cfg.folder!r} not selectable: {typ}")
        yield Mailbox(conn=conn, cfg=cfg)
    finally:
        try:
            conn.logout()
        except Exception:
            pass


@dataclass
class Mailbox:
    """Thin wrapper around an active imaplib connection."""

    conn: imaplib.IMAP4
    cfg: MailboxConfig

    def search_unseen(self, from_addr: Optional[str] = None) -> list[bytes]:
        """Return UIDs of UNSEEN messages, optionally filtered by `From:` header."""
        criteria = ["UNSEEN"]
        if from_addr:
            criteria += ["FROM", f'"{from_addr}"']
        typ, data = self.conn.uid("SEARCH", None, *criteria)
        if typ != "OK":
            raise MailboxError(f"SEARCH failed: {typ}")
        if not data or not data[0]:
            return []
        return data[0].split()

    def fetch(self, uid: bytes) -> FetchedMessage:
        """Fetch the full RFC822 source for a UID."""
        typ, data = self.conn.uid("FETCH", uid, "(RFC822)")
        if typ != "OK" or not data or data[0] is None:
            raise MailboxError(f"FETCH {uid!r} failed: {typ}")
        # imaplib returns a list of (header, body) tuples or bare bytes
        raw = b""
        for chunk in data:
            if isinstance(chunk, tuple) and len(chunk) > 1:
                raw = chunk[1]
                break
        if not raw:
            raise MailboxError(f"FETCH {uid!r}: empty body")
        msg = email.message_from_bytes(raw)
        return FetchedMessage(
            uid=uid,
            message_id=_decode_header(msg.get("Message-ID", "")),
            subject=_decode_header(msg.get("Subject", "")),
            from_addr=_extract_from_addr(msg),
            raw=raw,
            parsed=msg,
        )

    def mark_seen(self, uid: bytes) -> None:
        """Flag a UID as \\Seen so we don't reprocess it next batch."""
        typ, _ = self.conn.uid("STORE", uid, "+FLAGS", "(\\Seen)")
        if typ != "OK":
            raise MailboxError(f"STORE \\Seen on {uid!r} failed: {typ}")

    def delete(self, uid: bytes) -> None:
        """Mark a UID as \\Deleted and expunge it from the mailbox."""
        typ, _ = self.conn.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
        if typ != "OK":
            raise MailboxError(f"STORE \\Deleted on {uid!r} failed: {typ}")
        self.conn.expunge()


def extract_html_body(msg: Message) -> str:
    """Return the first text/html part of a multipart message, decoded.
    Falls back to text/plain (wrapped in <pre>) if no HTML part exists.
    """
    html = None
    plain = None
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/html" and html is None:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    html = payload.decode(charset, errors="replace")
            elif ctype == "text/plain" and plain is None:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    plain = payload.decode(charset, errors="replace")
    else:
        ctype = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if ctype == "text/html":
                html = text
            else:
                plain = text

    if html:
        return html
    if plain:
        # Best-effort: render plain text in a pre so the parser regex still works.
        return f"<pre>{plain}</pre>"
    return ""
