"""Unit tests for mailbox config + helpers (no live IMAP)."""
import email
import os
import unittest
from email.message import EmailMessage
from unittest import mock

from achilles_scraper import mailbox


class LoadConfigTests(unittest.TestCase):
    def test_raises_when_required_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(mailbox.MailboxConfigError) as cm:
                mailbox.load_config_from_env()
            msg = str(cm.exception)
            self.assertIn("ACHILLES_MAILBOX_HOST", msg)
            self.assertIn("ACHILLES_MAILBOX_USERNAME", msg)
            self.assertIn("ACHILLES_MAILBOX_PASSWORD", msg)

    def test_loads_with_minimal_env(self):
        with mock.patch.dict(os.environ, {
            "ACHILLES_MAILBOX_HOST": "imap.gmail.com",
            "ACHILLES_MAILBOX_USERNAME": "wine@example.com",
            "ACHILLES_MAILBOX_PASSWORD": "abcd efgh ijkl mnop",
        }, clear=True):
            cfg = mailbox.load_config_from_env()
            self.assertEqual(cfg.host, "imap.gmail.com")
            self.assertEqual(cfg.port, 993)  # default
            self.assertTrue(cfg.use_ssl)     # default
            self.assertEqual(cfg.folder, "INBOX")  # default

    def test_port_must_be_integer(self):
        with mock.patch.dict(os.environ, {
            "ACHILLES_MAILBOX_HOST": "x",
            "ACHILLES_MAILBOX_USERNAME": "y",
            "ACHILLES_MAILBOX_PASSWORD": "z",
            "ACHILLES_MAILBOX_PORT": "abc",
        }, clear=True):
            with self.assertRaises(mailbox.MailboxConfigError):
                mailbox.load_config_from_env()

    def test_ssl_off(self):
        with mock.patch.dict(os.environ, {
            "ACHILLES_MAILBOX_HOST": "x",
            "ACHILLES_MAILBOX_USERNAME": "y",
            "ACHILLES_MAILBOX_PASSWORD": "z",
            "ACHILLES_MAILBOX_SSL": "0",
            "ACHILLES_MAILBOX_PORT": "143",
        }, clear=True):
            cfg = mailbox.load_config_from_env()
            self.assertFalse(cfg.use_ssl)
            self.assertFalse(cfg.starttls)
            self.assertEqual(cfg.port, 143)

    def test_starttls_for_proton_bridge(self):
        with mock.patch.dict(os.environ, {
            "ACHILLES_MAILBOX_HOST": "127.0.0.1",
            "ACHILLES_MAILBOX_PORT": "1143",
            "ACHILLES_MAILBOX_USERNAME": "winenewsmail@proton.me",
            "ACHILLES_MAILBOX_PASSWORD": "bridge-app-password",
            "ACHILLES_MAILBOX_SSL": "0",
            "ACHILLES_MAILBOX_STARTTLS": "1",
        }, clear=True):
            cfg = mailbox.load_config_from_env()
            self.assertFalse(cfg.use_ssl)
            self.assertTrue(cfg.starttls)
            self.assertTrue(cfg.is_local)
            self.assertEqual(cfg.port, 1143)

    def test_ssl_and_starttls_mutually_exclusive(self):
        with mock.patch.dict(os.environ, {
            "ACHILLES_MAILBOX_HOST": "x",
            "ACHILLES_MAILBOX_USERNAME": "y",
            "ACHILLES_MAILBOX_PASSWORD": "z",
            "ACHILLES_MAILBOX_SSL": "1",
            "ACHILLES_MAILBOX_STARTTLS": "1",
        }, clear=True):
            with self.assertRaises(mailbox.MailboxConfigError):
                mailbox.load_config_from_env()


class IsLocalTests(unittest.TestCase):
    def _cfg(self, host: str) -> mailbox.MailboxConfig:
        return mailbox.MailboxConfig(host=host, port=1143, username="u", password="p")

    def test_loopback_v4(self):
        self.assertTrue(self._cfg("127.0.0.1").is_local)

    def test_loopback_v6(self):
        self.assertTrue(self._cfg("::1").is_local)

    def test_localhost_name(self):
        self.assertTrue(self._cfg("localhost").is_local)
        self.assertTrue(self._cfg("bridge.localhost").is_local)

    def test_remote_host(self):
        self.assertFalse(self._cfg("imap.gmail.com").is_local)
        self.assertFalse(self._cfg("10.0.0.5").is_local)

    def test_repr_redacts_password(self):
        cfg = mailbox.MailboxConfig(
            host="x", port=993, username="u", password="topsecret",
        )
        r = repr(cfg)
        self.assertIn("u", r)
        self.assertNotIn("topsecret", r)
        self.assertIn("redacted", r.lower())


class DecodeHeaderTests(unittest.TestCase):
    def test_plain_ascii(self):
        self.assertEqual(mailbox._decode_header("Hello"), "Hello")

    def test_utf8_encoded(self):
        encoded = "=?utf-8?B?5ryi5a2X?="  # 漢字
        self.assertEqual(mailbox._decode_header(encoded), "漢字")

    def test_none_returns_empty(self):
        self.assertEqual(mailbox._decode_header(None), "")


class FromAddrExtractionTests(unittest.TestCase):
    def test_display_name_with_brackets(self):
        msg = EmailMessage()
        msg["From"] = 'Millesima <newsletter@millesima.fr>'
        self.assertEqual(mailbox._extract_from_addr(msg), "newsletter@millesima.fr")

    def test_bare_address(self):
        msg = EmailMessage()
        msg["From"] = "foo@bar.com"
        self.assertEqual(mailbox._extract_from_addr(msg), "foo@bar.com")

    def test_lowercases(self):
        msg = EmailMessage()
        msg["From"] = "FOO@BAR.com"
        self.assertEqual(mailbox._extract_from_addr(msg), "foo@bar.com")


class ExtractHtmlBodyTests(unittest.TestCase):
    def test_returns_html_part(self):
        msg = EmailMessage()
        msg.set_content("plain version")
        msg.add_alternative("<p>html version</p>", subtype="html")
        body = mailbox.extract_html_body(msg)
        self.assertIn("html version", body)

    def test_falls_back_to_plain_wrapped_in_pre(self):
        msg = EmailMessage()
        msg.set_content("just plain")
        body = mailbox.extract_html_body(msg)
        self.assertIn("just plain", body)
        self.assertIn("<pre>", body)

    def test_returns_empty_when_no_body(self):
        msg = email.message_from_string("Subject: x\n\n")
        self.assertEqual(mailbox.extract_html_body(msg), "")


if __name__ == "__main__":
    unittest.main()
