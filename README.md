# Achilles's Wines

> Vinothèque pour la maison. Multilingue, multi-source, multi-région.
> Strict data quality, design Athena, déploiement Raspberry Pi 5 + Home Assistant.

## Vision

Une application personnelle pour gérer une cave familiale, suivre les prix et ratings, identifier les meilleurs rapports qualité-prix, planifier les achats annuels, et proposer des accords mets-vins basés sur ce qu'on a réellement en cave.

**Distinguished from burgundy-manager :**
- Multilingue FR/EN/NL/DE/ES/IT
- Stricte data quality (multi-source obligatoire pour les prix et les ratings)
- Design Athena (dark luxe sommellerie)
- Pensé pour le déploiement RPi 5 + Home Assistant dès l'architecture
- Producer registry pré-validé pour empêcher les mismatches type Raveneau/Bordeaux
- 37 scrapers actifs (retail FR/BE, presse critique, vintage charts, crowd reviews, données officielles)

## Quick start (en local pendant le POC)

```powershell
cd C:\Claude\achilles-wines
npm install
npm run db:migrate
npm run db:seed
npm run dev
# Open http://localhost:3000
```

Le scraper sidecar Python :
```powershell
cd C:\Claude\achilles-wines\scraper
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
python -m achilles_scraper.cli --help
```

## Documentation

### Projet & architecture
- [**docs/TEAM.md**](docs/TEAM.md) — Les 5 rôles : Helena, Hector, Patroclus, Odysseus, Cassandra
- [**docs/ARCHITECTURE.md**](docs/ARCHITECTURE.md) — Stack, déploiement Docker, flux ETL
- [**DECISIONS.md**](DECISIONS.md) — ADRs (Architecture Decision Records)
- [**PROGRESS.md**](PROGRESS.md) — Log append-only daté
- [**NEXT.md**](NEXT.md) — Backlog priorisé

### Données & qualité
- [**docs/NOMENCLATURE.md**](docs/NOMENCLATURE.md) — Normalisation, `wine_key` composite, enums canoniques
- [**docs/DATA_SOURCES.md**](docs/DATA_SOURCES.md) — Sources tier A/B/C/D/E/F, conformité robots.txt, token economy
- [**docs/NAMING-CLEANUP.md**](docs/NAMING-CLEANUP.md) — Pipeline post-batch : cleanup-producer → cleanup-cuvee → dedupe → merge-VdF

### Connaissance vin (base de référence)
- [**docs/FR-REGIONS.md**](docs/FR-REGIONS.md) — 15 régions viticoles officielles ONIVINS + sous-régions
- [**docs/FR-IGP-REFERENCE.md**](docs/FR-IGP-REFERENCE.md) — 75 IGP / Vin de Pays (FranceAgriMer 2022, INAO 2024)
- [**docs/VIN-DE-FRANCE.md**](docs/VIN-DE-FRANCE.md) — Modèle Vin de France (désignation nationale, pas régionale)
- [**docs/BORDEAUX-VALIDATION.md**](docs/BORDEAUX-VALIDATION.md) — Structure officielle Bordeaux + règles de validation DB

### Infrastructure
- [**docs/BACKUP.md**](docs/BACKUP.md) — SQLite online-backup → GPG AES-256 → NAS, rétention 7j + 4 semaines
- [**docs/AUTH.md**](docs/AUTH.md) — Système d'authentification scrapers (env vars, test_login, ADR-010)
- [**docs/EMAIL.md**](docs/EMAIL.md) — Ingestion newsletters par IMAP (parser HTML générique, .eml replay, ADR-011)
- [**docs/INSTALL_HAOS.md**](docs/INSTALL_HAOS.md) — Guide installation Home Assistant OS sur RPi 5

## Design

**Athena** — dark luxe sommellerie moderne :
- bg `#0F0E17` noir profond
- primary `#A53860` magenta vin
- surface `#F7F4EA` crème
- accent `#E5B25D` or champagne (décoratif/données)
- titres : Fraunces italic variable (via next/font)
- body : Inter 400/500/700 (via next/font)
- carte : dark tiles CartoDB + markers magenta

## Langues

- Français (défaut)
- English
- Nederlands
- Deutsch
- Español
- Italiano

**Règle absolue** : les noms de vins (producer, cuvée, appellation) ne sont JAMAIS traduits.

## Stack

- **Frontend** : Next.js 16.2.6 · TypeScript strict · Tailwind v4 · next-intl 4 · React-Leaflet · Recharts · next-pwa
- **Backend** : Next.js API routes · Drizzle ORM 0.45 · better-sqlite3 12.10 (WAL)
- **Scraping** : Python 3.12 · httpx · selectolax · APScheduler · rapidfuzz · pydantic · rich · click
- **Déploiement** : Docker Compose addon Home Assistant · nginx reverse proxy · GPG backup quotidien NAS

## Anti-hallucination

Le projet précédent (burgundy-manager) a accumulé des bugs de matching (Raveneau attaché à Bordeaux, Laroche à Sancerre). Achilles's Wines impose 6 gates :

1. **Producer registry pré-validé** (seed manuel + syndicats officiels CIVB/BIVB/CIVC/etc.)
2. **Hard region gate** (`appellation ∈ producer.allowed_appellations` obligatoire)
3. **Tri-source rule prix** (≥2 sources concordent ±15% pour entrer dans `fact_price`)
4. **Critic enum fermé** (WA, Vinous, BH, JMIB, RVF, Decanter, JS, JG, WS, Hachette, CT, XW, WE)
5. **Content-hash diff** (évite re-parsing via ETag/MD5)
6. **DLQ visible** à `/quarantaine` avec review manuelle

Voir [docs/ARCHITECTURE.md § Flux ETL](docs/ARCHITECTURE.md) pour le détail.

## Roadmap

### Sprint 1-3 (fondations) — TERMINÉ
- [x] Scaffold Next.js 16 + Drizzle schema 16 tables + i18n 6 langues + thème Athena
- [x] Import producer registry (~8 700 domaines depuis burgundy-manager)
- [x] Dashboard + Domaines/[id] + Cellar + Best Value + Vintages + Map + Menu
- [x] Premier scraper Millesima end-to-end + DLQ + job queue UI

### Sprint 4-9 (UI core + ingestion) — TERMINÉ
- [x] Page Best Value : scoring `(rating^2)/log(price)` + scatter
- [x] Page Vintages : heatmap région × année + drill-down
- [x] Page Domaine/[id] : charts prix et ratings, drinking window
- [x] Cellar drag-and-drop + CSV import/export + ConfidenceBadge
- [x] Menu pairing : composer multi-service + algo keyword-based
- [x] Email newsletter ingestion IMAP + .eml replay (ADR-011)
- [x] Authentification scrapers env-vars + test_login UI (ADR-010)

### Sprint 10-13 (robustesse + couverture) — TERMINÉ
- [x] 37 scrapers actifs (retail FR/BE, presse, vintage, crowd, officiel)
- [x] Identity fix : wine_key déterministe cross-sources (1 752 wine_keys multi-source)
- [x] Promoteur batch : staging → fact_price via tri-source ±15%
- [x] Dockerfiles multi-stage + docker-compose + nginx (ADR-007/008)
- [x] Backup SQLite GPG-AES256 → NAS + restore (ADR-009)
- [x] INAO AOC registry 315 entrées → 915 dim_appellation rows
- [x] WineEnthusiast 129 971 reviews (Kaggle, critic_code=WE)
- [x] Staging dedup UNIQUE index + purge 56 460 doublons

### Sprint 14 — Couverture France 60 % strict (en cours)
- [x] INAO appellation registry complet (820 → 915 dim_appellation rows) — [#30](https://github.com/FibSol/AchillesWines/issues/30)
- [ ] Producer registry expansion : CIVB + BIVB + Inter-Rhône + InterLoire + CIVC + CIVA — [#31](https://github.com/FibSol/AchillesWines/issues/31)
- [ ] Colonne `coverage_tier` (notable/mid/long_tail) + dashboard `/admin/coverage` — [#32](https://github.com/FibSol/AchillesWines/issues/32) [#36](https://github.com/FibSol/AchillesWines/issues/36)
- [ ] Promoter fact_rating : gate ≥2 sources critiques — [#33](https://github.com/FibSol/AchillesWines/issues/33)
- [ ] Wine-Searcher scraper (prix multi-shop) — [#34](https://github.com/FibSol/AchillesWines/issues/34)
- [ ] Purge fact_price mono-source — [#38](https://github.com/FibSol/AchillesWines/issues/38)

### Phase backlog (P3)
- [ ] OCR étiquette via Claude Vision (photo → ajout cellar) — [#24](https://github.com/FibSol/AchillesWines/issues/24)
- [ ] PWA push notifications promos — [#25](https://github.com/FibSol/AchillesWines/issues/25)
- [ ] Recommandations par similarité vectorielle — [#26](https://github.com/FibSol/AchillesWines/issues/26)
- [ ] Vintage divergence heatmap (sources × année) — [#27](https://github.com/FibSol/AchillesWines/issues/27)
- [ ] X-Wines + soMLier crowd reviews import — [#28](https://github.com/FibSol/AchillesWines/issues/28)

## Métriques (2026-05-23)

| KPI | Valeur actuelle |
|-----|----------------|
| Producteurs (dim_producer) | ~8 700 domaines |
| Appellations (dim_appellation) | 915 AOC/IGP |
| Cuvées (dim_wine) | ~3 650 |
| Prix validés (fact_price) | 2 355 rows |
| Ratings critiques (fact_rating) | 130 021 rows (WE 129 971 + hachette) |
| Scrapers actifs | 37 |
| Langues | 6 (FR/EN/NL/DE/ES/IT) |
| Cave max | 36 emplacements × 120 bouteilles = 4 320 max |
| Latence API cible | < 150 ms |
| DB size cible | < 500 MB/an |

## Contribution & propriété

Personal/local use only. Pas d'open-source pour l'instant. Successor de `C:\Users\Nicolas\Bourgogne\burgundy-manager` (devenu legacy).
