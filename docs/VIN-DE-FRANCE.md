# Vin de France — model & data conventions

Source: https://www.vindefrance.com/vin-de-france (the producer-collective official site)

## What VdF is

> "Vin de France: the national origin designation dedicated to varietal wines" (created in 2009, replacing the earlier *Vin de Table*).

It is one of three French wine categories defined by the 2009 EU OCM reform:

| Tier | What it certifies |
|---|---|
| **AOP** *(Appellation d'Origine Protégée)* | Wine of **terroir** — specific delimited area + strict varietal & vinification rules |
| **IGP** *(Indication Géographique Protégée)* | Wine of **territory** — broader regional area + looser rules |
| **VDF** *(Vin de France)* | Wine of **national** origin only — varietal-led, no geographic claim |

## What that means for the schema

**VdF is a SINGLE national designation. It is NOT regional.**

A Bordeaux producer can make a VdF (often to escape AOC restrictions on cépage, yield, or aging), but that wine is **legally** a "Vin de France", not a "Bordeaux Vin de France". The producer's region is a fact about the producer (where their winery sits), independent of the wine's appellation.

What is allowed on a VdF label:
> "A name, a known origin (France), the varietal(s) and the vintage."

What is **not** allowed:
- A regional name (Bordeaux, Bourgogne, …)
- A specific AOC (Pauillac, Chablis, …)
- A vineyard or climat name

What VdF producers explicitly **can** do:
> "Blend the same varietal from different regions or local varietals with more well-known French varietals."

A single VdF wine can use grapes from multiple French regions — the regional information is meaningless at the wine level.

## Implication for `dim_appellation` / `dim_wine`

The current schema is correct:

- `dim_appellation` has **exactly one** row `Vin de France` (FR, regional level by convention; the "regional" label here just means top-level — see `docs/FR-REGIONS.md` for the proposed `appellation_tier` split).
- A `dim_wine` row links to that single key via `appellation_key` when the wine is a VdF.
- The producer's region (`dim_producer.region`) is independent — telling you only where the winery is, not the wine's geographic claim.

**Do NOT create per-region VdF rows** (no "Vin de France — Bordeaux", "Vin de France — Bourgogne"). They have no legal basis and would split a single legal designation into ghost variants.

## Auditing VdF rows

The previous audit category `appellation_vin_de_france_with_known_region` was too broad — it flagged **every** VdF wine whose producer has a known region as suspicious. That's wrong: many of those wines are legitimate declassified cuvées (e.g. a Bordeaux producer experimenting with an unauthorized cépage).

Refined criterion (now in `scripts/audit-naming.mjs` and `scripts/emit-manual-review-csv.mjs`):

> Only flag a VdF row as suspect if the producer makes **other** wines under a **real AOC**. Producers that have only VdF wines in our DB are probably genuine VdF specialists and should not be flagged.

The smart-resolve pass already auto-fixes the high-confidence sub-set (producer has another AOC accounting for ≥50% of their wines). What remains:

| Bucket | Action |
|---|---|
| Producer makes only VdF wines | **Not an error.** Remove from manual-review CSV. |
| Producer has mixed AOCs, no single one ≥50% | Keep in CSV — needs eyes-on (could be a wide-portfolio producer or a mislabeled wine) |
| Producer has one dominant AOC ≥50% | Already auto-resolved by `smart-resolve-manual-residue.mjs` |

## UI implication (future)

When listing VdF wines, the filter should be by **producer's region** (a UI concern), never by introducing a fake "Vin de France — Bordeaux" appellation. The DB stays clean; the UI does the join.

## Note on the website used

vindefrance.com is the producer-collective informational site, not an INAO-authoritative cahier-des-charges. For the legal definition see [INAO — décret n° 2009-1352](https://www.legifrance.gouv.fr/loda/id/JORFTEXT000021163029/) and the EU OCM regulation (Reg. (EC) No 1234/2007 → Reg. (EU) No 1308/2013, art. 119). Both confirm the single-national-designation status.
