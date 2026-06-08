# Security

Achilles's Wines is a **single-user home application** (Raspberry Pi, behind Home
Assistant). The security model is therefore: **network-level access control first**
(HA ingress login / VPN), with lightweight app-level defenses as backup. It is not
a public multi-tenant SaaS and intentionally does not ship user accounts / RBAC.

> Audited 2026-06-08. This document records the posture, what was hardened, and the
> operator actions that remain (secret rotation, at-rest encryption).

---

## Deployment postures

### Home Assistant add-on (primary, recommended)
- Served via **HA ingress** (`ingress: true` in `addon/config.yaml` / `ha-addon/config.yaml`).
  HA authenticates every request upstream and renders the app in an **iframe**.
- Because of the iframe, the app deliberately sends **no `X-Frame-Options` / `frame-ancestors`**
  and **no HSTS** (TLS is HA's job). Do not add them at the app layer.
- Leave `ACHILLES_ACCESS_TOKEN` **unset** — HA already provides login. The middleware
  gate also auto-trusts requests carrying HA ingress headers.
- HA add-ons run as **root** by design (Supervisor-managed, isolated). That is expected;
  the standalone images (`Dockerfile`, `scraper/Dockerfile`) run non-root.

### Standalone docker-compose (secondary)
- The host port now binds to **`127.0.0.1` by default** (`ACHILLES_BIND_ADDR`), so it is
  **not** LAN-exposed out of the box. Only set `ACHILLES_BIND_ADDR=0.0.0.0` when fronted by
  a VPN (Tailscale/WireGuard) or an authenticating reverse proxy.
- If exposed directly, **enable the access gate** (below). There is no TLS in the bundled
  nginx — terminate TLS at a proxy.

---

## App-level access gate (opt-in)

`middleware.ts` enforces a shared-secret gate **only when `ACHILLES_ACCESS_TOKEN` is set**.
When unset it is a complete no-op (the HA case). When set, it covers **both pages and
`/api/*`**:

- Browser: visit `…/?token=<value>` once → sets an `httpOnly` cookie for 30 days.
- API clients: send `Authorization: Bearer <value>`.
- Requests arriving through HA ingress are trusted automatically.

Use a long random value. This is a single shared secret appropriate for one user — not
a substitute for HA/VPN auth on an internet-exposed host.

---

## Hardening applied (2026-06-08)

| Area | Change |
|---|---|
| Access control | Opt-in shared-secret gate in `middleware.ts` covering pages **and** API (the matcher previously excluded `/api`). No-op unless `ACHILLES_ACCESS_TOKEN` is set; HA-ingress-aware. |
| Security headers | `next.config.ts` now sends CSP, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` (camera allowed for OCR), `X-DNS-Prefetch-Control`. Intentionally **no** frame-blocking / HSTS (HA iframe + HA TLS). CSP is permissive (allows inline/eval + `https:` + CartoDB tiles) to avoid breakage — tighten with nonces later. |
| Cost / DoS | `/api/cellar/ocr` now rate-limited (40/h global, 20/h per IP) and validates the image media type against an allowlist (415 otherwise). |
| Input validation | `/api/jobs`: `params` constrained to scalars; `status` filter guarded against an enum. `/api/cellar/import` + `/api/producers/import`: 5 MB CSV size cap. |
| SSRF | `FRANKFURTER_API_BASE` (scraper FX) is now validated — only `https://*.frankfurter.app` is honored; anything else falls back to the default. |
| Network default | docker-compose host port binds to `127.0.0.1` by default. |
| Auditability | `lib/audit.ts` appends sensitive mutations to `logs/audit.log` (best-effort, never throws). Wired into job creation and DLQ resolution. |

## Verified already-safe (no change needed)
- **No SQL injection** — Drizzle parameterized throughout; raw `sql\`\`` only for column refs/aggregates.
- **No command injection** — `subprocess` uses `shell=False` + arg lists; no `eval`/`exec`.
- **No path traversal** — job-logs route guards `batchId` via `safeJoinLogsDir()` containment.
- **Secrets** — nothing hardcoded; `__repr__` redaction on `Credentials`/`MailboxConfig`; DLQ
  `raw_record` does not capture credentials; **`.env` is gitignored and was never committed**;
  `.env.example` is placeholder-only.
- **Backups** — GPG AES-256 (ADR-009).

---

## ⚠️ Operator action items (cannot be done in code)

1. **Rotate the secrets in your local `.env`.** Per `NEXT.md` these were exposed in chat on
   2026-05-22 and never rotated. Rotate and replace:
   - Anthropic API key, Firecrawl API key, Kaggle key
   - Mailbox app-password (Gmail/Proton bridge)
   - The shared wine-shop login (and ideally give each shop a **unique** credential rather than
     one reused email/password pair)
   - Any personal site logins stored there
   `.env` is not in git, but treat anything pasted into chat as compromised.

2. **Encrypt data at rest.** The live SQLite DB (`data/achilles.db`) holds cellar data and any
   cached session tokens and is **not** encrypted (only backups are). Simplest on a Pi: enable
   **full-disk encryption (LUKS)** on the data partition. (SQLCipher is an app-level alternative
   but invasive — deferred.)

3. **Keep `ACHILLES_ACCESS_TOKEN` unset on HA**; set it only for a standalone/LAN deployment.

4. **Tighten CSP later** (optional): move to nonce-based `script-src` to drop `'unsafe-inline'`.

---

## Quick checklist
- [ ] Rotate `.env` secrets (item 1)
- [ ] Enable LUKS / disk encryption on the Pi (item 2)
- [ ] Confirm the add-on is reached only via HA ingress (not a raw forwarded port)
- [ ] (Standalone only) set `ACHILLES_ACCESS_TOKEN` + keep bind on loopback/VPN
