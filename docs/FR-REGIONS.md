# French wine regions — canonical reference

Source: ONIVINS — https://onivins.fr/regions-viticoles-france/ (15 régions viticoles).
Cross-checked against the INAO regional structure.

## The 15 official French wine regions

| Canonical name | Sub-regions we keep in `dim_producer.region` |
|---|---|
| Alsace | Alsace |
| Bordeaux | Bordeaux |
| Bourgogne | Chablis · Côte de Nuits · Côte de Beaune · Côte Chalonnaise · Mâconnais · Bourgogne |
| Bugey | *(not in DB yet)* |
| Champagne | Champagne |
| Corse | Corse |
| Jura | Jura |
| Languedoc-Roussillon | Languedoc · Roussillon · Languedoc-Roussillon |
| Lorraine | Lorraine |
| Lyonnais | Beaujolais |
| Provence | Provence |
| Savoie | Savoie |
| Sud-Ouest | Sud-Ouest |
| Vallée de la Loire | Vallée de la Loire |
| Vallée du Rhône | Vallée du Rhône — Nord · Vallée du Rhône — Sud |

## Why we keep sub-regions

Collapsing everything to 15 buckets would destroy useful analytical structure: Chablis vs Côte de Beaune sell at very different prices, Rhône Nord (Syrah) vs Rhône Sud (Grenache assemblage) make different wines, etc. The schema stores the granular sub-region; the 15-region grouping is a derived view.

## Note on the ONIVINS "official documents"

The page https://onivins.fr/regions-viticoles-france/ lists three downloadable PDFs at the bottom (*Localisation du vignoble français*, *Localisation des vignobles d'AOC*, *Localisation des vignobles de vins de pays*). As of 2026-05, those URLs return a "Page Not Found" HTML stub instead of the actual PDFs — the documents are no longer hosted. The 15-region taxonomy is still authoritative from the page itself.

## Note on Languedoc-Roussillon

The DB currently has three labels in use: `Languedoc` (811 producers), `Roussillon` (206), and `Languedoc-Roussillon` (4). The first two are sub-regions within the combined ONIVINS region. The 4 producers labelled with the combined name should be split — tracked separately.
