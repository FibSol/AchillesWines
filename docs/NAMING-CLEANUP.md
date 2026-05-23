# Wine naming convention + cleanup pipeline

Reference structure (Wine-Searcher / CellarTracker convention):

| Field | Holds | Examples |
|---|---|---|
| `producer_name` | Legal entity only | `Château Cheval Blanc`, `Domaine Faiveley`, `Maison Joseph Drouhin` |
| `cuvee_name` | Specific bottling / vineyard / second wine; **empty** for grand vins | `Le Petit Cheval`, `Les Clos`, `Pavillon Rouge`; `""` for the Cheval Blanc grand vin |
| `vintage` | Year (integer) or `NULL` (NV) | `2020` |
| `classification` | `1er Grand Cru Classé A`, `Grand Cru`, `Cru Bourgeois`, etc. | separate column, not in the name |
| `color` | `red` / `white` / `rosé` / `sparkling` / `sweet` / `fortified` / `orange` | separate column |
| `bottle_ml` | `750`, `1500`, etc. | separate column |
| `appellation_key` | FK to `dim_appellation` | not in the name |

A producer name should **never** contain: vintage, appellation, classification, bottle size, color descriptor, shop SKU code (CB6, CB12, C6…), or packaging notes (COFFRET, EN ETUI, in houten kist).

A cuvée name should **never** contain: producer name, vintage, classification, appellation in parentheses, "Barrel sample", or generic blend descriptors ("Bordeaux-style Red Blend").

## In-scraper hygiene (preferred)

Wrap every raw `producer_name` / `cuvee_name` with the helpers from `scraper/achilles_scraper/identity.py`:

```python
from achilles_scraper.identity import clean_producer_display, clean_cuvee_display

producer_name = clean_producer_display(raw_producer_name)
cuvee_name    = clean_cuvee_display(raw_cuvee_name, producer_name=producer_name)
```

Both functions:
- Are idempotent.
- Return the input unchanged when it isn't unambiguously polluted (mutilation guard preserves names like `Château Margaux`, `Domaine Peyre-Rose`, `Cheval Blanc`).
- Mirror the JS cleanup scripts under `scripts/`.

## Post-batch cleanup pipeline (safety net)

After every scrape batch (or weekly), run in this order:

```powershell
node scripts/cleanup-producer-names.mjs --apply   # 1. clean producer display + merge duplicates
node scripts/cleanup-cuvee-noise.mjs    --apply   # 2. strip barrel-sample / blend / parens-appellation
node scripts/cleanup-cuvee-names.mjs    --apply   # 3. strip vintage/classification/appellation from cuvée + rebuild canonical_name + extract classification
node scripts/dedupe-wines.mjs           --apply   # 4. collapse exact-match wine duplicates (with appellation-containment guard)
node scripts/merge-vin-de-france-ghosts.mjs --apply  # 5. merge Vin-de-France-fallback rows into their real-appellation twin
```

Each script is dry-run by default. Pass `--filter <substring>` to preview a slice. `--limit N` controls sample size.

## Manual review

For ambiguous rows the auto-fixer refuses (mutilation guard, no real-appellation twin, etc.), regenerate the CSV:

```powershell
node scripts/emit-manual-review-csv.mjs   # writes data/manual-review.csv
```

The CSV is UTF-8 with BOM (Excel-friendly) and includes Wine-Searcher + CellarTracker query URLs per row.

## Why the mutilation guard exists

Several legitimate producer surnames look like noise tokens:

| Producer | Why it must be preserved |
|---|---|
| Château **Margaux** | Margaux is also the appellation, but the producer's surname is Margaux. |
| Domaine **Peyre-Rose** | "Rose" is a family-name suffix, not a color descriptor. |
| Domaine Franck **Balthazar** | "Balthazar" is the surname, not a bottle format. |
| Château **Belles Graves** | "Graves" is part of the proper name, not the appellation. |
| **Cheval Blanc** | "Blanc" is part of the producer's name (= "white horse"), not a color tag. |

The mutilation guard rejects any cleanup that would strip the last meaningful token, or shorten the name below 25% of original length (with allowance for cases that leave at least two meaningful tokens).
