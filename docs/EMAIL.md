# Newsletter scrapers (email ingestion)

Some wine retailers don't expose stable price pages but do send rich HTML newsletters. Achilles's Wines polls a dedicated IMAP mailbox, parses each newsletter, and feeds the offers through the same `staging_price_candidates` → tri-source-rule → `fact_price` pipeline used by the web scrapers.

See [ADR-011](../DECISIONS.md) for the design rationale.

## Setting up the mailbox

1. **Create a dedicated mailbox.** Don't reuse your personal Gmail — anything Achilles can read, it will `\Seen`-mark. Suggested: `wine-newsletters@<your domain>` or a new throwaway Gmail.
2. **Subscribe** that address to each retailer/critic newsletter you want to track.
3. **Generate an App Password** (Gmail-specific):
   - Enable 2-step verification on the account.
   - Visit https://myaccount.google.com/apppasswords
   - Generate a 16-character app password labeled "Achilles Wines".
4. **Set env vars** in `.env` (or `docker-compose` env):
   ```
   ACHILLES_MAILBOX_HOST=imap.gmail.com
   ACHILLES_MAILBOX_PORT=993
   ACHILLES_MAILBOX_USERNAME=wine-newsletters@yourdomain.com
   ACHILLES_MAILBOX_PASSWORD=xxxx xxxx xxxx xxxx   # the app password
   ACHILLES_MAILBOX_SSL=1
   ACHILLES_MAILBOX_FOLDER=INBOX
   ```

## Architecture

```
┌──────────────────┐  IMAP UNSEEN  ┌─────────────────────────┐
│ Dedicated Gmail  │ ────────────▶│ EmailNewsletterScraper  │
└──────────────────┘                │  (per source_code)      │
                                    └──────────┬──────────────┘
                                               │ generic HTML parse
                                               ▼
                                    ┌─────────────────────────┐
                                    │ staging_price_candidates│
                                    └──────────┬──────────────┘
                                               │ tri-source rule
                                               ▼
                                    ┌─────────────────────────┐
                                    │       fact_price        │
                                    └─────────────────────────┘
```

Each newsletter sender is its own row in `dim_source` (e.g. `millesima_email`, `idealwine_email`). The scraper for that source filters incoming mail by the configured `from:` address, parses the HTML body, and writes one `staging_price_candidates` row per offer.

## Running a poll

From `/admin/jobs`, pick `millesima_email` (or any `*_email` source) and click **🚀 Launch**. The Python sidecar's job runner:

1. Generates a `batch_id` and opens `logs/<batch_id>.log` (live-tailed by the drawer at `/admin/jobs`).
2. Opens the mailbox.
3. `SEARCH UNSEEN FROM "<sender>"` for the source's address.
4. For each message: saves the raw `.eml` to `raw/email/<batch_id>/<uid>.eml`, parses HTML, writes offers to staging.
5. On success, marks the message `\Seen` — it won't be re-polled.
6. On parse failure: writes a DLQ row with `raw_object_path` pointing at the `.eml`, leaves the message **un**read so a future run (with a better parser) can retry.

## Adding a new sender

For a vendor whose layout the generic parser handles well, just:

1. Insert a row in `dim_source` (or write a migration like `0003_email_newsletter_sources.sql`):
   ```sql
   INSERT INTO dim_source (source_code, source_name, source_tier, cadence, country_code, enabled)
   VALUES ('newvendor_email', 'NewVendor newsletter', 'B_retailer_major', 'on_demand', 'FR', 1);
   ```
2. Register a subclass in `scraper/achilles_scraper/scrapers/email_samples.py`:
   ```python
   class NewVendorEmailScraper(EmailNewsletterScraper):
       source_code = "newvendor_email"
       from_email = "news@newvendor.com"
       domain_hints = ("newvendor.com",)
   ```
3. Add it to `cli.py`'s `_load_scrapers()` and `--source` choices.

For a vendor with exotic HTML, override `_parse_html()` and return your own `list[EmailOffer]`.

## How offers are mapped to wine_key

The generic parser pulls `producer – cuvée vintage` from the anchor text. We normalise with the existing `expand_producer_prefix(norm_text(...))` and `clean_cuvee_tails(norm_text(...))` helpers, then `compute_wine_key` produces the same canonical key the web scrapers use. Identical offers from `millesima.fr` (HTML scraper) and `millesima_email` (newsletter scraper) collide on the same `wine_key` and feed the tri-source rule together.

**Appellation** is left empty in the email pipeline — newsletters rarely state the AOC explicitly. The `wine_key` therefore won't match an HTML-scraper key that *did* include the appellation. This is a known limitation; the staging row stays in `needs_review=1` until a human resolves it (or a per-vendor parser does smarter extraction).

## Operational tips

- **Filter early in Gmail**: create a Gmail filter that labels all newsletter senders as `Achilles/newsletters` and skips your inbox. Set `ACHILLES_MAILBOX_FOLDER=Achilles/newsletters` so the poll doesn't touch unrelated mail.
- **Replaying a parse**: after fixing a parser, find the `.eml` in `raw/email/<old_batch>/`, copy it back to the mailbox via IMAP APPEND (unread), and re-run the job.
- **Privacy**: `.eml` files are raw email; treat the `raw/email/` directory like any other personal data and back it up encrypted (see `docs/BACKUP.md`).

## What's not supported (yet)

- OAuth2 (Gmail requires app passwords for IMAP since May 2022 — works fine; OAuth would be heavier).
- LLM-based extraction for arbitrary newsletter layouts (would cost API calls; can be added as a fallback later).
- Attachment parsing (PDFs/CSVs attached to newsletters).
