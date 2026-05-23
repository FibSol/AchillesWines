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
- **Status:** superseded by ADR-012
- **Decision:** Palette aubergine nuit (#1A0B2E) + corail électrique (#FF5C8A) + ivoire (#FAF7F5) + mint (#6FFFE9 hover only). Typographies Migra (titres 800 italic, -12 letter-spacing) + Geist (body). Dark mode par défaut.
- **Alternatives considered:**
  - Athena : dark luxe sommellerie (magenta vin + or champagne, Fraunces + Inter).
  - Apollo : éditorial chaud lumineux (bordeaux + safran, Cormorant + DM Sans).
- **Reasoning:** Le brief demande "jeune et dynamique pour le monde du vin", explicitement pas VCF ni Raketman. Dionysus est le plus contrastant des trois et le mieux aligné sur l'identité Achilles (mythologie + audace).

## ADR-012 — Design Athena (dark luxe sommellerie) remplace Dionysus
- **Date:** 2026-05-23
- **Status:** accepted
- **Decision:** Palette Athena : noir profond `#0F0E17` (bg) · magenta vin `#A53860` (primaire) · crème `#F7F4EA` (fg) · or champagne `#E5B25D` (accent secondaire). Typos : Fraunces (titres, italic, variable, via next/font) + Inter (body, via next/font). Vibe : Le Wine Mag édition nuit × Vivino premium. Supersède ADR-002 (Dionysus).
- **Alternatives considered:**
  - Conserver Dionysus (aubergine/coral/mint) — rejeté : créait des maux de tête visuels selon retour utilisateur.
  - Apollo (bordeaux/safran, Cormorant + DM Sans) — non réévalué.
- **Reasoning:** L'utilisateur a prescrit la palette exacte. Athena était une option dès ADR-002 (déjà documentée comme alternative). La combinaison magenta vin + or champagne est un classique sommellerie (accord couleur/or intentionnel, pas accidentel). Les deux accents servent des rôles distincts : magenta = interactif (boutons, bordures, états actifs), champagne = décoratif/données (valeurs stat cards, badges, le "A." du footer). next/font garantit le chargement réel des fontes (l'ancienne implémentation utilisait des fallbacks CSS sans téléchargement).

## ADR-014 — CellarTracker en tant que critic-aggregation hub (pas scraping global)
- **Date:** 2026-05-23
- **Status:** accepted
- **Decision:** On consomme CellarTracker via son endpoint partenaire officiel `xlquery.asp` (source_code `cellartracker_xlquery`), pas par scraping des 6 M pages `wine.asp?iWine=N`. Pour chaque vin présent dans la cellule CT de l'utilisateur, on récupère en une requête les 30+ scores critiques pré-agrégés (WA, WS, AG/Vinous, JR, BH, DR, JS, JM, JH, WAL, WD, JG, GV, CT community avg, etc.).
- **Alternatives considered:**
  - (a) Scraper `wine.asp?iWine=N` de 1 à ~6 M — bloqué par Kasada (429 + JS challenge). Solver services chiffrés à 60-300 k€ pour le sweep complet. Rejeté.
  - (b) Playwright + stealth opportuniste sur quelques centaines de vins — possible mais lent (~3-5 s/page), banissement de compte probable, et ne donne *pas* les scores critiques agrégés que CT a déjà compilés.
  - (c) Scraper chaque critique séparément (Vinous, JR, Decanter, Burghound…) — duplique le travail que CT fait gratuitement, multiplie les abonnements payants requis.
- **Reasoning:** CellarTracker se positionne comme un *hub d'agrégation critique* via sa page Partner Integrations (`getcontent.asp`). Les utilisateurs lient leurs abonnements (Vinous, Jancis Robinson, Decanter, Burghound, Halliday, Jeb Dunnuck, Inside Burgundy, Suckling, Wine Align, Wine Doctor…) une fois, et CT canalise les reviews dans leur vue cellule. `xlquery.asp` expose ces données agrégées en TSV/CSV/XML, sans Kasada. C'est l'usage prévu — pas un contournement.
- **Implications produit:**
  - Le flow utilisateur Achilles devient : ajouter un vin → ajouter aussi à CT (manuel UI, scan barcode mobile CT, ou bulk-add futur) → notre scraper pull les scores agrégés pour ce vin → écriture dans `fact_rating` avec le `critic_code` approprié.
  - Couverture critique élargie *sans* écrire 15 scrapers individuels (un seul scraper xlquery suffit pour exposer la donnée de tous les critiques liés par l'utilisateur).
  - Architecture-mirror à envisager pour Achilles : exposer nous-mêmes une page "Partner Integrations" où l'utilisateur lie ses comptes externes (Vinous OAuth, etc.) plutôt que de scraper. Différé en backlog, pas dans ce sprint.

## ADR-013 — Couverture France : skeleton-first, 60 % strict plutôt que 80 % bruité
- **Date:** 2026-05-23
- **Status:** accepted
- **Decision:** Cible **60 % des producteurs français notables** avec données vérifiées, plutôt que 80 % en acceptant des données mono-source. Pipeline en 3 couches :
  1. **Squelette (autoritaire, gratuit)** — INAO appellation registry complet + listes officielles des syndicats viticoles (CIVB Bordeaux, BIVB Bourgogne, Inter-Rhône, InterLoire, CIVC Champagne, CIVA Alsace, etc.) → `dim_producer` étendu sans prix ni rating.
  2. **Cuvées + fourchettes de prix** — élargir les scrapers existants (iDealwine, Wine-Searcher, Vinatis, Millesima, Lavinia, Cavissima) + agrégat min/max par `wine_key`. Promotion à `fact_price` uniquement si **≥2 sources concordent à ±15 %** (ADR-003 inchangé).
  3. **Ratings critiques** — RVF, Decanter, Bettane+Desseauve, James Suckling, Hachette ; promotion à `fact_rating` uniquement si **≥2 sources critiques** valident (nouveau gate). Vivino utilisé en tiebreaker seulement, jamais en source unique.
- **KPI** : `coverage_score = (producers_with_≥1_cuvée + cuvées_with_≥2_source_price + wines_with_≥2_source_rating) / (3 × producers_total)` — cible **≥ 60 %**.
- **Alternatives considered:**
  - (a) 80 % coverage, sources uniques tolérées. Rejeté — répète l'erreur burgundy-manager (cf. [feedback_burgundy_prices_data_quality.md](../../../Users/Nicolas/.claude/projects/C--Claude/memory/feedback_burgundy_prices_data_quality.md)).
  - (b) Vivino comme source primaire pour atteindre 80 %. Rejeté — crowd data introduit le bruit que les gates ADR-003 doivent justement bloquer.
  - (c) LWIN/Liv-ex abonnement pour couverture exhaustive. Rejeté (coût, cf. ADR-005).
- **Reasoning:** L'utilisateur a explicitement choisi "slower, stricter, 60 % is good enough" après reality-check. Le squelette INAO + syndicats est gratuit, autoritaire, et donne 100 % des producteurs déclarés sans pollution. Les couches 2 et 3 héritent du gate multi-source existant (ADR-003) au lieu de l'assouplir. Mieux vaut 60 % de données fiables qu'un 80 % qu'il faudrait re-nettoyer.

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

## ADR-011 — Email newsletter ingestion : IMAP dédié + parser HTML générique + .eml replay
- **Date:** 2026-05-22
- **Status:** accepted
- **Decision:**
  - **Protocol** : IMAP via stdlib `imaplib` + `email.message`. Pas de POP3 (destructif), pas d'OAuth (Gmail accepte les App Passwords pour IMAP depuis 2022).
  - **Mailbox** : un seul compte Gmail dédié. Credentials en env vars `ACHILLES_MAILBOX_HOST/PORT/USERNAME/PASSWORD/SSL/FOLDER`. Jamais en DB. Le `MailboxConfig.__repr__` redacte le password.
  - **Modèle** : un row `dim_source` par expéditeur (e.g. `millesima_email`, `idealwine_email`). Le scraper pour ce source filtre `SEARCH UNSEEN FROM "<addr>"`. Mailbox creds partagées entre tous les `*_email` sources — pas en ACHILLES_AUTH_* (ADR-010 ne s'applique pas ici, c'est un mailbox, pas une auth de site).
  - **Parser** : `EmailNewsletterScraper(BaseScraper)` base avec hook `_parse_html()`. Default = heuristique générique (selectolax) qui extrait anchors `[href]` qui pointent vers un produit + prix le plus proche en montant dans le DOM avec `text(separator=" ")` pour éviter de coller les textes voisins. Subclasses peuvent override pour des layouts exotiques.
  - **Lifecycle** : .eml sauvé dans `raw/email/<batch_id>/<uid>.eml` AVANT toute écriture DB → on a un artéfact pour replay même si le crash arrive après. Succès → message marqué `\Seen` (option choisie par l'utilisateur). Échec parse → DLQ avec `raw_object_path` → message reste UNSEEN pour qu'un parser amélioré puisse retenter plus tard.
  - **wine_key** : appellation laissée vide dans la pipeline email (les newsletters ne nomment pas l'AOC explicitement). Conséquence : ne collide pas avec le `wine_key` du scraper HTML correspondant. Trade-off accepté pour V1 ; le row staging reste `needs_review=1` jusqu'à résolution manuelle.
- **Alternatives considered:**
  - (a) Webhook inbound (Postmark, SendGrid Inbound Parse) : push au lieu de poll. Élégant mais ajoute un service externe payant et une URL publique à exposer depuis le RPi — overkill.
  - (b) LLM (Claude/OpenAI) pour extraire les offres sans parser HTML : marche sur n'importe quelle disposition mais coûte ~$0.01 par newsletter et introduit une dépendance réseau. Reporté en fallback ; peut être ajouté plus tard via `_parse_html()` override.
  - (c) Stocker mailbox creds dans `dim_source` plutôt qu'env vars. Rejeté : partage de creds entre N sources `*_email`, et secrets en DB violent le principe d'ADR-010.
  - (d) Supprimer le message après parse au lieu de `\Seen`. Rejeté par l'utilisateur (réversibilité utile, inspection dans Gmail UI).
  - (e) Pas de `.eml` sauvé. Rejeté : le replay-without-refetch est essentiel quand on améliore un parser.
- **Reasoning:** Un mailbox IMAP dédié transforme tous les retailers en un seul protocole (IMAP) et déplace la complexité de "scraper N sites avec N anti-bots" vers "parser N layouts HTML d'emails dans un seul flux". Le scraper Python existant a déjà selectolax + httpx + DLQ + ops_content_hashes — on réutilise 100% de l'infrastructure. La sauvegarde du .eml en premier garantit qu'un crash ne perde jamais l'input. `\Seen` est doublement utile : (1) idempotence du poll, (2) inspectabilité dans Gmail UI.

## ADR-010 — Authentification scrapers : env-vars only + form login + re-login chaque batch
- **Date:** 2026-05-22
- **Status:** accepted
- **Decision:**
  - **Stockage des credentials** : env vars exclusivement, pattern `ACHILLES_AUTH_<SOURCE>_USERNAME` / `_PASSWORD`. Jamais en base, jamais en log. `Credentials.__repr__` redacte le password.
  - **Flow** : form login (username + password) uniquement pour le V1. Pas d'OAuth, pas de cookies pasted-from-browser, pas de captcha-bypass.
  - **Session** : pas de cache. Chaque batch se reconnecte. Quand ça devient un problème (rate-limiting target, latence), on ajoutera une table `ops_auth_sessions(source_key, cookie_jar JSON, expires_at, …)`.
  - **Drapeau de découverte** : nouvelle colonne `dim_source.requires_auth` (boolean default false). `/admin/auth` liste les sources avec ce flag = 1, montre la présence des env vars et offre un bouton "Test login" qui enqueue un job avec `params.test_auth=true`.
  - **Erreurs** : `AuthMissingError` (env vars absentes) et `AuthError` (login rejeté ou rompu) dans `scraper/achilles_scraper/auth.py`. Le JobRunner les capture et marque le job `failed` avec le message d'erreur. DLQ `errorClass="auth_error"` (déjà dans l'enum) pour les 401 ligne-par-ligne pendant un scrape.
- **Alternatives considered:**
  - (a) Cache de session en DB. Plus performant et plus poli vis-à-vis du target. Reporté — re-login coûte ~1 s, on a une marge.
  - (b) Cookies pastés depuis le browser (workaround captcha/2FA). Utile mais le UX est mauvais (cookie expire → silently 403 → DLQ). À reconsidérer si Decanter Premium ou WS Pro entrent en jeu.
  - (c) Tokens API uniquement. Trop limité — Wine-Searcher est payant et la plupart des cibles n'exposent pas d'API.
  - (d) Vault / OS keyring. Over-engineering pour un déploiement maison mono-utilisateur.
- **Reasoning:** Env vars + form-login couvre le 80% des sources qu'on vise (iDealwine, Lavinia, Vinatis, RVF, peut-être Decanter free-tier). Re-login par batch garde la code-surface minimale et rend chaque run idempotent. La table `requires_auth` est un boolean simple — pas de structure d'auth en DB tant qu'on n'a pas un besoin clair. `/admin/auth` réutilise complètement la pipeline existante : c'est juste un job avec un flag.

## ADR-009 — Backups : SQLite online-backup → GPG symmetric → NAS, retention 7d + 4w
- **Date:** 2026-05-22
- **Status:** accepted
- **Decision:**
  - Snapshot via l'API `sqlite3 .backup` (équivalent C `sqlite3_backup_step`) — fonctionne sous WAL avec lecteurs/écrivains concurrents, sans verrou exclusif.
  - Chiffrement GPG **symétrique AES-256** avec passphrase via `ACHILLES_GPG_PASSPHRASE` (env), pas de clé asymétrique à gérer.
  - Verification round-trip : on déchiffre dans /dev/null après le chiffrement et on fail si ça ne décode pas (un backup unreadable est pire que pas de backup).
  - Rétention : 7 daily + 4 weekly (le dimanche est suffixé `-weekly`). Pruning par filename glob, immune au temps système / timezone.
  - Pas de cron embarqué — `scripts/backup.sh` est idempotent et conçu pour être déclenché par : (a) cron host RPi, (b) HA shell_command via docker exec, (c) systemd timer.
  - Script de restore companion `scripts/restore.sh` avec `PRAGMA integrity_check` avant l'install + refuse l'overwrite sans `--force`.
- **Alternatives considered:**
  - (a) `cp data/achilles.db backup.db` — race condition garantie avec WAL et lecteur/écrivain concurrent.
  - (b) `pg_dump`-style SQL export — perd les blobs SQLite-specific (FTS shadow tables, triggers) et 10× plus lent.
  - (c) GPG asymétrique avec clé GitHub-stored — plus paranoïaque mais complique le restore depuis un host neuf.
  - (d) Litestream streaming replication vers S3 — over-engineering pour 50 MB de DB et un usage maison.
- **Reasoning:** L'API online-backup est le seul mécanisme officiellement WAL-safe. GPG symétrique a une surface d'erreur minimale (passphrase = 1 secret à gérer). La vérification round-trip a déjà sauvé un projet précédent où la corruption GPG était silencieuse. Le suffixe `-weekly` rend la rétention prédictible et auditable au `ls`.

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
