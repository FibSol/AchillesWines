# Sources de données — Achilles's Wines

Toutes les sources sont **publiques** ou **opt-in licenciées plus tard**. Aucun scraping de contenu privatif ni de PII utilisateur.

---

## Tier A — Sources d'identité (one-shot + audit annuel)

Pour seed et maintenir `dim_producer`, `dim_appellation`, `dim_geography`.

| Source | URL | Contenu | Cadence |
|---|---|---|---|
| burgundy-manager export | (interne) | 8 700 domaines français + AOC + communes (avec leurs `allowed_appellations` à figer) | One-shot import |
| INAO | https://www.inao.gouv.fr | Liste officielle des AOC françaises | Annuel |
| Vins-de-Bourgogne (BIVB) | https://www.vins-bourgogne.fr | Climats et lieux-dits | Annuel |
| Conseils interprofessionnels (CIVB, CIVC, etc.) | divers | Listes producteurs par région | Annuel |
| Sites officiels des domaines | divers | Cuvées disponibles, AOC produites (gold standard pour `allowed_appellations`) | Annuel |

**Rôle Cassandra** : valider chaque ajout au producer registry. Pas d'auto-discovery.

---

## Tier B — Retailers majeurs (mensuel, prix retail)

Tous ont des fiches produit publiques et exportent un sitemap.xml ou catégorie navigable.

| Source | Pays | URL | Notes |
|---|---|---|---|
| Millesima | FR | https://www.millesima.fr | Sitemap clair, catégories par région |
| iDealwine | FR | https://www.idealwine.com | Catalogue + ventes aux enchères |
| Cavissima | FR | https://www.cavissima.com | Spécialiste investissement vin |
| Lavinia | FR | https://www.lavinia.fr | Réseau physique + online |
| Vinatis | FR | https://www.vinatis.com | Volume, prix moyens, promos fréquentes |
| 1855 | FR | https://www.1855.com | Spécialiste Bordeaux |
| WDC (Wine du Coin?) | BE | https://www.wdc.be | Retailer belge |
| TastingDays | BE | https://www.tastingdays.com | Retailer belge |
| Cinoco | BE | https://www.cinoco.com | Importateur belge |
| Wijnhuis | BE | https://www.wijnhuis.be | Retailer belge (NL) |
| Provini | BE | https://www.provini.be | Spécialiste Italie en Belgique |
| Drinks&Co | ES/BE | https://www.drinksco.com | Multi-marché EU |
| Tannico | IT | https://www.tannico.it | Référence retailer italien |
| Decantalo | ES | https://www.decantalo.com | Spécialiste Espagne |
| Vinissimus | ES | https://www.vinissimus.com | Catalogue ES large |

**Implémentation** :
- Un module Python par retailer dans `scrapers/retailers/`.
- Tous suivent la même interface : `def scrape(since: datetime | None) -> list[ScrapedPrice]`.
- ETag cache + content-hash diff.
- robots.txt respect : Reading `https://<domain>/robots.txt` à chaque session, respect du `Crawl-delay`.

---

## Tier C — Retailers mineurs / spécialisés (opportuniste)

Pour combler les trous quand un vin n'apparaît que sur des sites moins évidents.

| Source | Pays | URL | Notes |
|---|---|---|---|
| Berry Bros. & Rudd | UK | https://www.bbr.com | Vieux millésimes |
| Justerini & Brooks | UK | https://www.justerinis.com | Allocations |
| Hedonism Wines | UK | https://hedonism.co.uk | Catalogue rare |
| K&L Wine Merchants | US | https://www.klwines.com | Reference catalogue US |
| Total Wine | US | https://www.totalwine.com | Volume |
| Drinkable Curio | DE | https://www.weinhandel-deutschland.de | Allemagne |

**Statut** : optionnel, activable site par site.

---

## Tier D — Crowd ratings (one-shot puis annuel)

| Source | URL | Licence | Contenu |
|---|---|---|---|
| X-Wines | https://github.com/rogerioxavier/X-Wines | CC0 | 21M ratings, 100k wines (user-style) |
| Mendeley soMLier | https://data.mendeley.com/datasets/dtbm7n6npz/1 | CC BY 4.0 | 278k Vivino-derived ratings (2021 snapshot) |
| CellarTracker pages publiques | https://www.cellartracker.com | TOS check | Scores agrégés visibles publiquement |

**Statut Cassandra** : `reviewer_type = user_aggregate`, **jamais** mélangé avec les ratings critiques canoniques. Affiché avec un badge "👥 Crowd" distinct.

---

## Tier E — Presse / Critiques (mensuel + Mai)

Articles publics et vintage charts gratuites uniquement. Pas de scraping derrière paywall.

| Source | URL | Contenu public | Notes |
|---|---|---|---|
| Decanter | https://www.decanter.com | Vintage Guide gratuit, articles, "Best of" listes | Gold standard vintage |
| Wine Spectator | https://www.winespectator.com | Vintage chart gratuit | Gratuite, mise à jour annuelle |
| RVF | https://www.larvf.com | Articles libres, classements partiels | Premium pour les détails |
| Robert Parker (Wine Advocate) | https://www.robertparker.com | Vintage chart gratuit | Articles premium |
| Vinous | https://vinous.com | Free previews, vintage reports excerpts | Premium pour le détail |
| Jeb Dunnuck | https://jebdunnuck.com | Some free reports, vintage notes | Recent + recommended |
| James Suckling | https://www.jamessuckling.com | Vintage reports, top-100 lists | Mix free/premium |
| Burghound | https://www.burghound.com | Allen Meadows scores quoted by retailers | Paywall but cited publicly |
| Jasper Morris IB | https://www.insideburgundy.com | Burgundy specialist, partial free | Premium for full |
| Hachette Guide | https://www.hachette-vins.com | Coups de cœur publics + étoiles | Hachette stars |
| Vivino API | https://www.vivino.com | (NON — TOS interdit scraping) | Skip |

**Règle Cassandra** : seuls les **scores numériques** sont stockés. Aucun extrait textuel des notes de dégustation (copyright). L'UI renvoie vers la source originale via lien externe.

---

## Tier F — Données millésimes (annuel Mai)

| Source | Format | URL |
|---|---|---|
| Decanter Vintage Guide | HTML public | https://www.decanter.com/wine/vintage-guide/ |
| Wine Spectator Vintage Charts | HTML public + PDF | https://www.winespectator.com/vintage-charts |
| Robert Parker Vintage Chart | HTML public | https://www.robertparker.com/vintage-chart |
| RVF Guide Vert | livre annuel — manuel | (n/a) |
| Bettane+Desseauve Le Grand Guide | livre annuel — manuel | (n/a) |

**Pour les sources livres** : saisie manuelle annuelle via la page admin (CSV import).

---

## Sources rejetées explicitement

| Source | Raison |
|---|---|
| Vivino API/scraping direct | TOS interdit + auth requise |
| Wine-Searcher API | Coût (~commercial only) |
| Liv-ex APIs | Coût (~10k £/an) — reporté en enrichissement opt-in |
| Tastingbook | TOS unclear, accès limité |
| robertparker.com login content | Paywall, pas de scraping derrière auth |

---

## Conformité

- **robots.txt** : honoré par tous les scrapers. Si un site interdit le crawl, il est exclu.
- **User-Agent** identifiable : `AchillesWines/1.0 (+local; personal use)`.
- **Rate limiting** : crawl-delay du robots.txt respecté, par défaut 2 s entre requêtes par host.
- **Caching agressif** : ETag/Last-Modified honored → 304 = pas de re-download.
- **No PII**: aucun nom d'utilisateur, aucune review textuelle individuelle scrapée. Uniquement scores agrégés numériques publics.
- **Provenance preserved** : chaque row stocke `source_key`, `source_url`, `content_hash`, `batch_id`.

---

## Politique de scraping pour économiser les tokens

1. **ETag/Last-Modified** : la première chose qu'envoie l'extracteur. Réponse 304 = exit early.
2. **Content-hash diff** : avant de parser, on hash le body et on compare à `ops_content_hashes`. Identique = exit early.
3. **Sitemap-driven** : on lit `sitemap.xml` pour ne crawler que les URLs nouvelles ou modifiées (via `<lastmod>`).
4. **Selectolax > BeautifulSoup** : 10× plus rapide, CPU économisé.
5. **Playwright seulement si DOM rendering JS strict** : 90% des retailers sont SSR-friendly.
6. **Pas de LLM dans le hot path** : CSS selectors versionnés par site. LLM uniquement pour la normalisation finale de noms producteur (1 fois par batch, max 100 noms).
7. **Diff incrémental** : on stocke `last_crawled_at` par URL, ne re-fetch que si > 30 jours pour prix retail (sauf hebdo promos detector).
