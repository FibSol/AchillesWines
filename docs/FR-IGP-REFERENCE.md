# French IGP (Vin de Pays) — canonical reference

Source: **FranceAgriMer / Confédération Française des Vins de Pays — *Carte des IGP*** (2022 edition, derived from official CFVDP + INAO data).
Mirror: École Muscadelle PDF — extracted text in `data/inao-refs/liste_igp_muscadelle.txt`.

Cross-checked against:
- INAO October 2024 PDF — *Les vignobles sous AOP en France* (`CAR_AOP-Viti_2024.pdf`)
- INAO December 2024 PDF — *Les vignobles sous IGP en France* (`CAR_IGP-Viti_2024.pdf`)
- INAO 2012 reference list — *Les appellations d'origine Vins, Cidres et Eaux-de-Vie* (`inao_liste_aoc_vins.pdf` in `data/inao-refs/`)

**75 IGPs total** as of 2022, organised into 3 tiers:

## 1. IGP Régionales (6)

These cover wide multi-département zones:

| # | IGP | Sub-zones (dénominations complémentaires) |
|---|---|---|
| 01 | Atlantique | — |
| 02 | Comté Tolosan | Bigorre · Cantal · Coteaux et Terrasses de Montauban |
| 03 | Comtés Rhodaniens | — |
| 04 | Méditerranée | Comté de Grignan · Coteaux de Montélimar |
| 05 | Pays d'Oc | — |
| 06 | Val de Loire | Allier · Cher · Indre · Indre-et-Loire · Loir-et-Cher · Loire-Atlantique · Loiret · Maine-et-Loire · Marches de Bretagne · Nièvre · Pays de Retz · Sarthe · Vendée · Vienne |

## 2. IGP Départementales (28)

One per département where named (numbers 07–34):

Alpes-de-Haute-Provence · Alpes-Maritimes · Ardèche (Coteaux de l'Ardèche) · Ariège (Coteaux de la Lèze · Coteaux de Plantaurel) · Aude (Coteaux de la Cabrerisse · Coteaux de Miramont · Côtes de Lastours · Côtes de Prouilhe · Hauterive · La Côte Révée · Pays de Cucugnan · Val de Cesse · Val de Dagne) · Aveyron · Bouches-du-Rhône (Terre de Camargue) · Calvados (Grisy) · Coteaux de l'Ain (Pays de Gex · Revermont · Val de Saône · Valmorey) · Côtes Catalanes (Pyrénées-Orientales) · Côtes du Lot (Rocamadour) · Drôme (Comté de Grignan · Coteaux de Montélimar) · Franche-Comté (Buffard · Coteaux de Champlitte · Doubs · Gy · Haute-Saône · Hugier · Motey-Bésuche · Offlanges · Vuillafans) · Gard · Gers · Haute-Marne · Hautes-Alpes · Haute-Vienne · Île de Beauté · Isère (Balmes Dauphinoises · Coteaux du Grésivaudan) · Landes (Coteaux de Chalosse · Côtes de l'Adour · Sables de l'océan · Sables fauves) · Pays de l'Hérault (15+ sub-zones) · Puy de Dôme · Saône et Loire · Var (Argens · Coteaux du Verdon · Sainte-Baume) · Vaucluse (Aigues · Principauté d'Orange) · Vins de la Corrèze · Yonne

## 3. IGP de petites zones (41)

Numbered 35–75 in the official map:

Agenais · Alpilles · Cévennes · Charentais (Charente · Charente-Maritime · Île de Ré · Île d'Oléron · Saint-Sornin) · Cité de Carcassonne · Collines Rhodaniennes · Côte Vermeille · Coteaux de Coiffy · Coteaux de Glanes · Coteaux de l'Auxois · Coteaux de Narbonne · Coteaux de Peyriac (Hauts de Badens) · Coteaux de Tannay · Coteaux d'Enserune · Coteaux des Baronnies · Coteaux du Cher et de l'Arnon · Coteaux du Libron (Les Coteaux de Béziers) · Coteaux du Pont du Gard · Côtes de Gascogne (Côtes du Condomois) · Côtes de la Charité · Côtes de Meuse · Côtes de Thau (Cap d'Agde) · Côtes de Thongue · Côtes du Tarn (Cabanes · Cunac) · Duché d'Uzès · Haute Vallée de l'Aude · Haute Vallée de l'Orb · Lavilledieu · Cathare · Maures · Mont Caume · Périgord (Dordogne · Vin de Domme) · Sable de Camargue · Sainte Marie La Blanche · Saint-Guilhem-Le-Désert (Val de Montferrand · Cité d'Aniane) · Thézac-Perricard · Urfé (Ambierle · Trelins) · Vallée du Paradis · Vallée du Torgan · Vicomté d'Aumelas (Vallée dorée) · Vins des Allobroges

## Database alignment

The 2009 EU OCM reform renamed every "Vin de Pays" to an IGP — they are the same legal designation. Until this pass, `dim_appellation` held both forms as separate rows, causing massive duplication (e.g. `Pays d'Oc` 190 wines + `Vin de Pays d'Oc` 214 wines + `IGP Pays d'Oc` 8 wines = 412 wines split across 3 keys for the same IGP).

The `scripts/merge-igp-vdp-duplicates.mjs` pass collapsed **27 alias rows into 16 canonical IGP rows**, re-pointing **958 wines** to the correct `IGP <Name>` key. Sample (full output in commit message):

- `Pays d'Oc` + `Vin de Pays d'Oc` → `IGP Pays d'Oc` (404 wines)
- `Méditerranée` + `Vin de Pays de la Méditerranée` + `Vin de Pays des Portes de Méditerranée` → `IGP Méditerranée` (63 wines)
- `Val de Loire` + `Vin de Pays du Val de Loire` + `Vin de Pays du Jardin de la France` + `Pays de Loire` → `IGP Val de Loire` (66 wines)
- `Gard` + `Vin de Pays du Gard` + `IGP Pays du Gard` → `IGP Gard` (72 wines)
- `Côtes Catalanes` + `Vin de Pays des Côtes Catalanes` → `IGP Côtes Catalanes` (62 wines)
- `Côtes de Gascogne` → `IGP Côtes de Gascogne` (179 wines)

The remaining `Vin de Pays X` rows that didn't have a script-mapped IGP twin are mostly small (< 5 wines) and stayed untouched — they're listed in the manual-review CSV.

## Note on the broken ONIVINS PDFs

The three PDFs referenced at the bottom of https://onivins.fr/regions-viticoles-france/ (*Localisation du vignoble français*, *Localisation des vignobles d'AOC*, *Localisation des vignobles de vins de pays*) all return a *Page Not Found* HTML stub as of 2026-05 — the documents are no longer hosted. The sources used instead, in order of authority:

1. **INAO Liste-AOC-vins.pdf** (2012) — text-searchable, complete AOC + eau-de-vie list
2. **FranceAgriMer Carte des IGP** (2022, via École Muscadelle mirror) — 75-IGP list with sub-zones
3. **INAO 2024 vineyard maps** (`CAR_AOP-Viti_2024.pdf` / `CAR_IGP-Viti_2024.pdf`) — current geographic distribution, image-only PDFs (not text-searchable but visually authoritative)
