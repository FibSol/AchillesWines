# Bordeaux structure — DB validation

Source: *Guide pédagogique — Vins de Bordeaux* (École du Vin de Bordeaux / CERPET, 2013, C. Charpentier) — [PDF](https://www.hotellerie-restauration.ac-versailles.fr/IMG/pdf/guide_pdagogique_octobre_2013._vins_de_bordeaux._c_charpentier.pdf). Cross-checked against the current `data/achilles.db`.

## What the DB gets right

The column-level structure already matches the official model:

| Concept | Column | Status |
|---|---|---|
| Producer (legal entity) | `dim_producer.producer_name` | ✓ |
| Specific bottling / vineyard | `dim_wine.cuvee_name` | ✓ |
| Vintage | `dim_wine.vintage` | ✓ |
| Classification (rank within an official classement) | `dim_wine.classification` | ✓ |
| Appellation | `dim_appellation` (FK) | ✓ |
| Color | `dim_wine.color` | ✓ |
| Bottle format | `dim_wine.bottle_ml` | ✓ |

The user's original screenshot example is correctly modelled after the cleanup pass:
- `producer = "Château Cheval Blanc"` · `cuvée = ""` · `vintage = 2020`
- `appellation = "Saint-Émilion Grand Cru"` · `classification = "1er Grand Cru Classé A"`

This is the exact structure shown on page 50 of the guide: producers listed under `Château … , Appellation` with the classification (Premiers Grands Crus Classés A/B, Grands Crus Classés) as a separate header.

## Issues found

### 1. Appellation duplicates (mechanical)

The same legal AOC is represented under multiple `appellation_name` strings:

| Canonical | Duplicate variants in DB |
|---|---|
| Listrac-Médoc | "Listrac", "Listrac-Médoc" |
| Moulis-en-Médoc | "Moulis", "Moulis En Medoc" |
| Puisseguin Saint-Émilion | "Puisseguin St Emilion", "Puisseguin-Saint-Emilion" |
| Francs Côtes de Bordeaux | "Bordeaux Côtes de Francs", "Côtes de Bordeaux Francs", "Francs Côtes de Bordeaux" |
| Cadillac Côtes de Bordeaux | "Premieres Côtes de Bordeaux" (historical name; merged into Cadillac CdB in 2009) |

Auto-fix: merge each variant set into a single canonical row, re-point all `dim_wine.appellation_key` references.

### 2. "Saint-Émilion Grand Cru Classé" is **not** an appellation

The official structure (guide p. 34):

> « Il s'agit en effet d'une appellation d'origine et non pas d'un classement […]. Tout vin produit dans l'aire géographique de l'appellation Saint-Émilion peut revendiquer les deux AOC Saint-Émilion et Saint-Émilion Grand Cru mais […] seuls les vins de l'appellation Saint-Émilion Grand Cru peuvent bénéficier des mentions "Grand Cru Classé" ou "Premier Grand Cru Classé" à la suite du classement officiel. »

So:
- **Appellations** (legal AOCs): `Saint-Émilion`, `Saint-Émilion Grand Cru`
- **Classifications** (within the AOC Saint-Émilion Grand Cru): `Grand Cru Classé`, `Premier Grand Cru Classé B`, `Premier Grand Cru Classé A`

The DB has a row `Saint-Emilion Grand Cru Classé` in `dim_appellation` (35 wines linked) — this is wrong. Those 35 wines should be re-pointed to `Saint-Émilion Grand Cru`, and the classification populated from the official 2012 list.

### 3. `dim_appellation.level` is incomplete and inconsistent

Schema enum: `regional, village, premier_cru, grand_cru, iconic`.

Issues:
- Bordeaux **commune-level** appellations (Pauillac, Margaux, Saint-Julien, Saint-Estèphe, Pessac-Léognan, Sauternes, Barsac, Listrac-Médoc, Moulis-en-Médoc) are all currently marked `regional` instead of `village`.
- "Saint-Émilion Grand Cru" is currently `regional` but it's a stricter-rules appellation tier inside the same geography as Saint-Émilion — neither `regional` nor `village` cleanly describes it.
- The enum mixes appellation hierarchy (régionale / sous-régionale / communale) with classification (premier_cru / grand_cru), which the guide explicitly says are different concepts.

Recommendation: in a future ADR, split the enum into:
- `appellation_tier`: `regional` (Bordeaux/Bordeaux Sup.) · `subregional` (Médoc, Haut-Médoc, Graves, Entre-Deux-Mers, Côtes de Bordeaux) · `communal` (Margaux, Pauillac, Saint-Julien, Saint-Estèphe, Pessac-Léognan, Sauternes, Barsac, Saint-Émilion, Pomerol, Moulis-en-Médoc, Listrac-Médoc) · `communal_stricter` (Saint-Émilion Grand Cru, Bordeaux Supérieur, Graves Supérieures)
- Keep `classification` separate (already in `dim_wine.classification`).

For now I'm not modifying the schema — just upgrading `level` values where the canonical mapping is unambiguous.

### 4. Classification values are sparse

Distinct values present (with counts):

| Classification | n | Origin |
|---|--:|---|
| `Grand Cru` | 2,339 | Mostly Burgundy (correct: it IS a classification in Burgundy) |
| `1er Cru` | 2,017 | Mostly Burgundy Premier Cru |
| `Cru Bourgeois` | 24 | Médoc |
| `1er Grand Cru Classé B` | 22 | Saint-Émilion |
| `1er Grand Cru Classé A` | 8 | Saint-Émilion |
| `Cru Bourgeois Supérieur` | 7 | Médoc |
| `Cru Bourgeois Exceptionnel` | 3 | Médoc |

Missing — the 1855 ranks for the Médoc:
- `1er Cru Classé` (5 producers: Lafite, Latour, Margaux, Mouton, Haut-Brion)
- `2e Cru Classé` (14 producers)
- `3e Cru Classé` (14)
- `4e Cru Classé` (10)
- `5e Cru Classé` (18)

Missing — the 1855 Sauternes ranks:
- `Premier Cru Supérieur` (Yquem only)
- `1er Cru` Sauternes (10 châteaux — distinct from Burgundy 1er Cru, which is unfortunate ambiguity in the schema)
- `2e Cru` Sauternes (13 châteaux)

Missing — the Graves 1959 classification:
- `Cru Classé de Graves` (16 châteaux, no hierarchy)

Missing — Saint-Émilion `Grand Cru Classé` rank (~64 châteaux as of 2012 revision).

Recommendation: ship a curated reference table (`scripts/seed-bordeaux-classifications.mjs`) that updates `dim_wine.classification` for known châteaux. The classification list is small and stable (~150 châteaux across all four classements).

## Canonical reference (from the guide)

### Médoc / Sauternes 1855 — full hierarchy
*(See guide pp. 47–48; revised 1973 to promote Mouton Rothschild)*

Reds (61 châteaux):
- **Premiers Crus** (5): Haut-Brion, Lafite Rothschild, Latour, Margaux, Mouton Rothschild
- **Deuxièmes Crus** (14): Brane-Cantenac, Cos d'Estournel, Ducru-Beaucaillou, Durfort-Vivens, Gruaud-Larose, Lascombes, Léoville Barton, Léoville Las Cases, Léoville Poyferré, Montrose, Pichon Longueville Comtesse de Lalande, Pichon-Longueville (Baron), Rauzan-Gassies, Rauzan-Ségla
- **Troisièmes Crus** (14): Boyd-Cantenac, Calon Ségur, Cantenac Brown, d'Issan, Desmirail, Ferrière, Giscours, Kirwan, La Lagune, Lagrange (Saint-Julien), Langoa Barton, Malescot Saint-Exupéry, Marquis d'Alesme Becker, Palmer
- **Quatrièmes Crus** (10): Beychevelle, Branaire-Ducru, Duhart-Milon, La Tour Carnet, Lafon-Rochet, Marquis de Terme, Pouget, Prieuré-Lichine, Saint-Pierre, Talbot
- **Cinquièmes Crus** (18): Batailley, Belgrave, Camensac, Cantemerle, Clerc Milon, Cos Labory, Croizet-Bages, d'Armailhac, Dauzac, du Tertre, Grand-Puy Ducasse, Grand-Puy-Lacoste, Haut-Bages Libéral, Haut-Batailley, Lynch-Bages, Lynch-Moussas, Pédesclaux, Pontet-Canet

Whites / Sauternes (27 châteaux):
- **Premier Cru Supérieur** (1): Yquem
- **Premiers Crus** (11): Climens, Clos Haut-Peyraguey, Coutet, de Rayne-Vigneau, Guiraud, La Tour Blanche, Lafaurie-Peyraguey, Rabaud-Promis, Rieussec, Sigalas-Rabaud, Suduiraut
- **Seconds Crus** (15): Broustet, Caillou, d'Arche, de Malle, de Myrat, Doisy Daëne, Doisy-Dubroca, Doisy-Védrines, Filhot, Lamothe, Lamothe-Guignard, Nairac, Romer, Romer du Hayot, Suau

### Graves 1953/1959 — single rank "Cru Classé", all in Pessac-Léognan
16 châteaux: Bouscaut, Carbonnieux, Domaine de Chevalier, Couhins, Couhins-Lurton, de Fieuzal, Haut-Bailly, Haut-Brion, Latour-Martillac, Laville Haut-Brion, Malartic-Lagravière, La Mission Haut-Brion, Olivier, Pape Clément, Smith-Haut-Lafitte, La Tour Haut-Brion.

### Saint-Émilion 2012 — Premiers Grands Crus Classés
- **A** (4 in 2012; reduced to 2 in 2022 reform): Ausone, Cheval Blanc, *plus 2012–2022: Angelus, Pavie*
- **B**: Beauséjour, Beau-Séjour-Bécot, Bélair-Monange, Canon, Canon La Gaffelière, Clos Fourtet, La Gaffelière, La Mondotte, Larcis Ducasse, Figeac, Pavie Macquin, Troplong Mondot, Trotte Vieille, Valandraud

### Cru Bourgeois (2009 reform, 3-tier from 2018)
Tiers: `Cru Bourgeois Exceptionnel` → `Cru Bourgeois Supérieur` → `Cru Bourgeois`. Eligible AOCs: Médoc, Haut-Médoc, Margaux, Moulis-en-Médoc, Listrac-Médoc, Saint-Julien, Pauillac, Saint-Estèphe. Annual list at [crus-bourgeois.com](https://www.crus-bourgeois.com).

### Cru Artisan (2006)
44 small Médoc estates. List at [crus-artisans.com](https://www.crus-artisans.com).

### Pomerol
**No official classification**. Petrus, Le Pin, Vieux Château Certan, La Conseillante etc. carry no formal rank — they trade on reputation alone.

## Bordeaux AOCs — full list (60 AOCs in 6 families)

| Family | AOCs |
|---|---|
| Vins blancs secs | Bordeaux Blanc, Entre-Deux-Mers, Graves (blanc), Pessac-Léognan (blanc) |
| Bordeaux & Bordeaux Supérieur | Bordeaux (rouge/blanc/rosé/clairet), Bordeaux Supérieur, Crémant de Bordeaux |
| Côtes de Bordeaux | Blaye Côtes de Bordeaux, Cadillac Côtes de Bordeaux, Castillon Côtes de Bordeaux, Francs Côtes de Bordeaux, Côtes de Bourg, Côtes de Bordeaux Saint-Macaire |
| Saint-Émilion · Pomerol · Fronsac | Saint-Émilion, Saint-Émilion Grand Cru, Montagne-Saint-Émilion, Saint-Georges-Saint-Émilion, Puisseguin-Saint-Émilion, Lussac-Saint-Émilion, Pomerol, Lalande-de-Pomerol, Fronsac, Canon-Fronsac |
| Médoc & Graves | Médoc, Haut-Médoc, Margaux, Pauillac, Saint-Julien, Saint-Estèphe, Moulis-en-Médoc, Listrac-Médoc, Graves, Pessac-Léognan |
| Sweet Bordeaux | Sauternes, Barsac, Cérons, Cadillac, Loupiac, Sainte-Croix-du-Mont, Graves Supérieures, Bordeaux Supérieur Moelleux |
