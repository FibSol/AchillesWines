# Achilles's Wines — Architecture Decision Records

> Lightweight ADRs. One per cross-cutting decision worth remembering.

## ADR-001 — Fork burgundy-manager au lieu d'évoluer en place
- **Date:** 2026-05-21
- **Status:** accepted
- **Decision:** Nouveau projet à `C:\Claude\achilles-wines`. On importe le producer registry (~8 700 domaines), les AOC et communes depuis burgundy-manager. Les pipelines ratings/prix sont reconstruits from scratch sur fondations data-quality-first.
- **Alternatives considered:**
  - (a) Renommer burgundy-manager in-place et migrer le schéma.
  - (b) Coexistence parallèle sans réutilisation.
- **Reasoning:** Le rebuild permet d'enforcer les data-quality gates (multi-source, hard region gate, critic enum fermé) dès le schéma. Retrofiter et migrer les données sales aurait propagé les bugs (Raveneau/Bordeaux, Laroche/Sancerre). L'import sélectif du registry préserve les 8 700 domaines durement gagnés.

## ADR-002 — Design Dionysus (bold contemporain) plutôt que Athena/Apollo
- **Date:** 2026-05-21
- **Status:** accepted
- **Decision:** Palette aubergine nuit (#1A0B2E) + corail électrique (#FF5C8A) + ivoire (#FAF7F5) + mint (#6FFFE9 hover only). Typographies Migra (titres 800 italic, -12 letter-spacing) + Geist (body). Dark mode par défaut.
- **Alternatives considered:**
  - Athena : dark luxe sommellerie (magenta vin + or champagne, Fraunces + Inter).
  - Apollo : éditorial chaud lumineux (bordeaux + safran, Cormorant + DM Sans).
- **Reasoning:** Le brief demande "jeune et dynamique pour le monde du vin", explicitement pas VCF ni Raketman. Dionysus est le plus contrastant des trois et le mieux aligné sur l'identité Achilles (mythologie + audace).

## ADR-003 — Stratégie data strict multi-source obligatoire
- **Date:** 2026-05-21
- **Status:** accepted
- **Decision:**
  - Prix : ≥2 sources concordent à ±15 % pour entrer en `fact_price`, sinon `staging` avec `needs_review = true`.
  - Ratings critiques : enum fermé (`WA, Vinous, BH, JMIB, RVF, Decanter, JS, JG, WS, Hachette`). Hors enum → DLQ.
  - Identité : hard region gate (`appellation ∈ producer.allowed_appellations`).
- **Alternatives considered:**
  - Inclusif avec flags de confiance (tout entre, badge visible).
  - Hybride (strict identité+ratings, permissif prix).
- **Reasoning:** Le projet précédent a échoué sur la qualité (Raveneau/Bordeaux, Laroche/Sancerre, critiques hors enum perdues). Cassandra impose le strict mode : coverage plus faible mais zéro pollution. Manuel review queue (`/quarantaine`) reste le seul chemin pour les cas borderline.

## ADR-004 — Déploiement Docker Compose addon Home Assistant
- **Date:** 2026-05-21
- **Status:** accepted
- **Decision:** Containers séparés pour `web` (Next.js standalone), `scraper` (Python sidecar), `nginx` (reverse proxy + cache static). Volumes pour `data/` (SQLite WAL) et `raw/` (HTML snapshots). Backup quotidien zip vers NAS.
- **Alternatives considered:**
  - Installation native HAOS supervised (systemd services).
  - Décider plus tard (focus POC d'abord).
- **Reasoning:** Containerisation = isolation crash, mise à jour facile, HAOS gère backup et monitoring via add-on standard. Trade-off CPU/RAM acceptable sur RPi 5 (8 GB).

## ADR-006 — Trigger scrapers depuis l'UI via job-queue SQLite
- **Date:** 2026-05-21
- **Status:** accepted
- **Decision:** Nouvelle table `ops_job_queue` (job_id, source_key, requested_by, requested_at, status [queued|running|done|failed|cancelled], started_at, finished_at, rows_*, error_message, batch_id, params JSON). L'UI INSERT un job avec status=queued, le sidecar Python poll toutes les 5 s, claim le job (UPDATE…WHERE status=queued LIMIT 1 atomique), exécute, met à jour le status. La page `/admin/jobs` affiche queue + history + bouton "Launch now" par source.
- **Alternatives considered:**
  - (a) HTTP endpoint FastAPI/uvicorn sur le sidecar Python → port supplémentaire à exposer, plus de surface réseau, complique Docker Compose.
  - (b) File-based flag dans `triggers/<source>.now` → fragile, pas de visibilité historique, race conditions.
  - (c) Job queue externe (Redis, BullMQ) → over-engineering pour un RPi mono-utilisateur.
- **Reasoning:** SQLite est déjà le bus de données partagé entre web et scraper containers. Une table `ops_job_queue` donne : (1) persistence à travers redémarrages, (2) state visible directement dans `/admin/jobs` sans appel cross-container, (3) atomicité native via UPDATE…RETURNING, (4) zéro dépendance supplémentaire. Polling 5 s est largement acceptable vu la cadence mensuelle des jobs réels.

## ADR-008 — docker-compose orchestration : 3 services + named volumes
- **Date:** 2026-05-22
- **Status:** accepted
- **Decision:**
  - 3 services dans `docker-compose.yml` : `web` (Next.js), `scraper` (sidecar Python), `nginx` (reverse proxy alpine).
  - 3 volumes nommés : `achilles-data` (SQLite WAL partagé sur `/data`), `achilles-logs` (logs nginx + scraper batch logs sur `/app/logs`), `achilles-raw` (HTML snapshots du scraper).
  - Le port host est exposé **uniquement** par nginx (variable `ACHILLES_HTTP_PORT`, défaut 8080). `web` et `scraper` ne sont pas exposés en host — ils communiquent par le réseau bridge `achilles`.
  - `scraper` et `nginx` dépendent du healthcheck de `web` (`depends_on: condition: service_healthy`).
  - Logging json-file rotation `10m × 3` par service.
- **Alternatives considered:**
  - (a) Network `host` au lieu de bridge — plus simple mais expose les ports internes sur le LAN et casse la résolution DNS Docker.
  - (b) Traefik au lieu de nginx — plus puissant (TLS auto, dashboard) mais overkill pour un déploiement mono-host sans WAN.
  - (c) Volume bind `./data:/data` au lieu de named volume. Rejeté : permission chmod compliquée sur RPi (root vs achilles uid 1001).
- **Reasoning:** Les named volumes survivent à `docker compose down`, et Docker gère le owner/permission automatiquement (chown au boot du container). nginx unique point d'entrée HTTP : on peut ajouter TLS plus tard (HA add-on ingress ou Caddy) sans toucher au compose. Les healthcheck en `condition: service_healthy` garantissent que `scraper` ne tente pas de polling avant que le schéma DB soit prêt (web démarre les migrations).

## ADR-007 — Dockerfiles : Next.js standalone (web) + Python wheel cache (scraper)
- **Date:** 2026-05-22
- **Status:** accepted
- **Decision:** Deux Dockerfiles distincts (un par container ADR-004).
  - **Web** (`Dockerfile` à la racine) : 3 stages `deps → builder → runner` sur `node:20-bookworm-slim`. `deps` installe `python3/make/g++` pour le compile natif de `better-sqlite3`. `builder` produit `.next/standalone` via `next.config.ts` (output:"standalone"). `runner` copie uniquement `standalone/`, `static/`, `public/`, `db/` (migrations) — pas de `node_modules` complet. Tini en PID 1, user non-root `achilles:1001`, EXPOSE 3000, HEALTHCHECK via fetch sur `/`.
  - **Scraper** (`scraper/Dockerfile`) : 2 stages `builder → runner` sur `python:3.12-slim-bookworm`. Le builder produit les wheels (`pip wheel --wheel-dir /wheels .`), le runner les installe sans toolchain. Tini, user non-root, HEALTHCHECK via `sqlite3 SELECT 1` sur le DB partagé.
  - **CI** : nouveau job `docker-build` (Buildx + GHA cache) construit les deux images sur chaque push. Job `docker-lint` (hadolint) sur les deux Dockerfiles.
- **Alternatives considered:**
  - (a) Image unique multi-process (web + scraper dans le même container, supervisord). Rejeté par ADR-004 (isolation crash).
  - (b) Alpine base. Rejeté : musl pose des problèmes connus avec `better-sqlite3` et selectolax (Cython).
  - (c) Distroless final stage. Tentant mais pas de shell pour le HEALTHCHECK et debug RPi compliqué.
- **Reasoning:** `node:20-bookworm-slim` + multi-stage `standalone` donne une image runner ~150 MB sans toolchain de compilation. Le wheel-cache du scraper évite de réinstaller `selectolax`/`httpx[http2]` à chaque déploiement (compilation lente sur arm64). Tini en PID 1 est essentiel pour le `docker stop` propre (sinon SIGTERM ne se propage pas à `node server.js`). Le HEALTHCHECK Node utilise `fetch()` natif (Node ≥ 18) — pas de `curl` à installer.

## ADR-005 — wine_key = sha1 composite hash, pas LWIN
- **Date:** 2026-05-21
- **Status:** accepted
- **Decision:** `wine_key = sha1(producer_norm | cuvee_norm | vintage_or_NV | appellation_norm | bottle_ml)[:16]` (16 chars hex). Déterministe, deux scrapers indépendants produisent la même clé. LWIN reste un enrichissement opt-in si abonnement Liv-ex un jour.
- **Alternatives considered:**
  - LWIN comme PK (coût ~10k £/an).
  - UUID v4 random + lookup composite (perd la déterministicité).
  - Serial BIGINT + composite UNIQUE index.
- **Reasoning:** Le coût LWIN est prohibitif pour un usage maison. La clé déterministe via hash garantit la dedup naturelle sans coordinateur central, et le tronquage à 16 chars donne 64 bits de namespace (largement assez pour 10⁶ wines). Un préfixe d'évolution `lwin11:` peut être ajouté plus tard si LWIN entre en jeu.
