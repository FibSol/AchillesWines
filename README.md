# Achilles's Wines

> Vinothèque pour la maison. Multilingue, multi-source, multi-région.
> Strict data quality, design Dionysus, déploiement Raspberry Pi 5 + Home Assistant.

## 🍷 Vision

Une application personnelle pour gérer une cave familiale, suivre les prix et ratings, identifier les meilleurs rapports qualité-prix, planifier les achats annuels, et proposer des accords mets-vins basés sur ce qu'on a réellement en cave.

**Distinguished from burgundy-manager :**
- Multilingue FR/EN/NL/DE/ES/IT
- Stricte data quality (multi-source obligatoire pour les prix)
- Design Dionysus (jeune et audacieux)
- Pensé pour le déploiement RPi 5 + Home Assistant dès l'architecture
- Producer registry pré-validé pour empêcher les mismatches type Raveneau/Bordeaux

## ⚡ Quick start (en local pendant le POC)

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

## 📋 Documentation

- [**docs/TEAM.md**](docs/TEAM.md) — Les 5 rôles : Helena, Hector, Patroclus, Odysseus, Cassandra
- [**docs/ARCHITECTURE.md**](docs/ARCHITECTURE.md) — Stack, déploiement Docker, flux ETL
- [**docs/NOMENCLATURE.md**](docs/NOMENCLATURE.md) — Normalisation, `wine_key` composite, enums
- [**docs/DATA_SOURCES.md**](docs/DATA_SOURCES.md) — Sources tier A/B/C/D/E/F, conformité, optimisation tokens
- [**DECISIONS.md**](DECISIONS.md) — ADRs (Architecture Decision Records)
- [**PROGRESS.md**](PROGRESS.md) — Log append-only daté
- [**NEXT.md**](NEXT.md) — Backlog priorisé

## 🎨 Design

**Dionysus** — bold contemporain :
- bg `#1A0B2E` aubergine nuit
- primary `#FF5C8A` corail électrique
- surface `#FAF7F5` ivoire
- accent `#6FFFE9` mint (hover only)
- titres : Migra 800 italic, -12 letter-spacing
- body : Geist 400/500/700
- carte : tiles dark + corail markers

## 🌐 Langues

- 🇫🇷 Français (défaut)
- 🇬🇧 English
- 🇳🇱 Nederlands
- 🇩🇪 Deutsch
- 🇪🇸 Español
- 🇮🇹 Italiano

**Règle absolue** : les noms de vins (producer, cuvée, appellation) ne sont JAMAIS traduits.

## 📦 Stack

- **Frontend** : Next.js 15 · TypeScript · Tailwind v4 · shadcn/ui · next-intl · React-Leaflet · Recharts · TanStack Query · next-pwa
- **Backend** : Next.js API + tRPC · Drizzle ORM · SQLite WAL
- **Scraping** : Python 3.12 · httpx · selectolax · Playwright · APScheduler · rapidfuzz · pydantic
- **Déploiement** : Docker Compose addon Home Assistant · nginx reverse proxy · backup quotidien NAS

## 🛡 Anti-hallucination

Le projet précédent (burgundy-manager) a accumulé des bugs de matching (Raveneau attaché à Bordeaux, Laroche à Sancerre). Achilles's Wines impose 6 gates :

1. **Producer registry pré-validé** (seed manuel)
2. **Hard region gate** (`appellation ∈ producer.allowed_appellations` obligatoire)
3. **Tri-source rule** (≥2 sources concordent ±15% pour prix)
4. **Critic enum fermé** (WA, Vinous, BH, JMIB, RVF, Decanter, JS, JG, WS, Hachette)
5. **Content-hash diff** (évite re-parsing)
6. **DLQ visible** à `/quarantaine` avec review manuelle

Voir [docs/ARCHITECTURE.md § Flux ETL](docs/ARCHITECTURE.md) pour le détail.

## 🗺 Roadmap

### MVP (Sprint 1-3) — voir [NEXT.md](NEXT.md)
- [ ] Scaffold + schema + i18n + Dionysus theme
- [ ] Import producer registry (8 700 domaines)
- [ ] Dashboard + Domaines + Cellar + Best Value + Vintages + Map
- [ ] Premier scraper Millesima end-to-end

### Phase 2 — Ingestion ramp-up
- [ ] 10+ retailers EU
- [ ] Vintage ratings (Decanter, Wine Spectator)
- [ ] Critic ratings (sources publiques)
- [ ] Promos detector hebdo

### Phase 3 — Déploiement RPi
- [ ] Dockerization
- [ ] HA addon
- [ ] PWA installable
- [ ] Backup chiffré NAS

### Phase 4 — Innovations
- [ ] Menu pairing avec cuvées de la cave
- [ ] OCR étiquette via Claude Vision
- [ ] Recommandations par similarité (cépages + style)
- [ ] Vintage divergence heatmap

## 📊 Métriques cibles

- **8 700 domaines** importés depuis burgundy-manager
- **10+ retailers** scrapés mensuellement
- **6 langues** support complet
- **36 emplacements × 120 bouteilles** capacité cave (4 320 bouteilles max)
- **SQLite < 500 MB** après 1 an
- **Latence API < 150 ms** typique

## 🤝 Contribution & propriété

Personal/local use only. Pas d'open-source pour l'instant. Successor de `C:\Users\Nicolas\Bourgogne\burgundy-manager` (devenu legacy).
