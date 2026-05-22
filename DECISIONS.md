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

## ADR-005 — wine_key = sha1 composite hash, pas LWIN
- **Date:** 2026-05-21
- **Status:** accepted
- **Decision:** `wine_key = sha1(producer_norm | cuvee_norm | vintage_or_NV | appellation_norm | bottle_ml)[:16]` (16 chars hex). Déterministe, deux scrapers indépendants produisent la même clé. LWIN reste un enrichissement opt-in si abonnement Liv-ex un jour.
- **Alternatives considered:**
  - LWIN comme PK (coût ~10k £/an).
  - UUID v4 random + lookup composite (perd la déterministicité).
  - Serial BIGINT + composite UNIQUE index.
- **Reasoning:** Le coût LWIN est prohibitif pour un usage maison. La clé déterministe via hash garantit la dedup naturelle sans coordinateur central, et le tronquage à 16 chars donne 64 bits de namespace (largement assez pour 10⁶ wines). Un préfixe d'évolution `lwin11:` peut être ajouté plus tard si LWIN entre en jeu.
