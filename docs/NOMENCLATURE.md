# Nomenclature canonique — Achilles's Wines

## Pourquoi une nomenclature stricte

Le projet précédent a échoué sur le matching d'identité : "Domaine Raveneau" s'est retrouvé attaché à 20+ cuvées Bordeaux parce que les variantes ("D. Raveneau", "Raveneau", "Dom Raveneau") n'étaient pas normalisées et que rien ne vérifiait que les cuvées Bordeaux étaient autorisées pour un domaine de Chablis.

Une nomenclature explicite, déterministe, **partagée entre tous les scrapers** est la première ligne de défense.

---

## 1. Normalisation des chaînes

### `norm_text(s) -> str`

```python
def norm_text(s: str | None) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))  # strip accents
    s = s.lower()
    for ch in [",", ".", "'", '"', "/", "-", "(", ")", "[", "]", "_", "&", "+"]:
        s = s.replace(ch, " ")
    return " ".join(s.split())  # collapse whitespace
```

**Exemples :**
- `"Château Lafite-Rothschild"` → `"chateau lafite rothschild"`
- `"D. Coche-Dury"` → `"d coche dury"` (avant expansion préfixe)
- `"Dom. de la Romanée-Conti"` → `"dom de la romanee conti"` (avant expansion préfixe)

### `expand_producer_prefix(s) -> str`

Expansion fixe des préfixes producteurs (héritage burgundy-manager) :

| Avant | Après |
|---|---|
| `D. <X>` | `Domaine <X>` |
| `Dom. <X>` | `Domaine <X>` |
| `Dom <X>` | `Domaine <X>` |
| `Ch. <X>` | `Château <X>` |
| `Ch <X>` | `Château <X>` |
| `Casa <X>` | `Casa <X>` (no expansion) |
| `Bodega <X>` | `Bodega <X>` (no expansion) |
| `Tenuta <X>` | `Tenuta <X>` (no expansion) |

### `clean_cuvee_tails(s) -> str`

Strip des suffixes parasites héritage burgundy-manager :

- `"1er Cru"` / `"1er CC"` / `"2ème Cru Classé"` / `"5ème Cru Classé"` → strip
- `"Grand Cru Classé"` / `"Grand Cru"` → strip (ou flag séparé)
- `"AOC <appellation>"` / `"AOP <appellation>"` → strip
- `"<year>"` à la fin → strip (le vintage est un champ séparé)
- `"750ml"` / `"75cl"` / `"Magnum"` → strip (bottle_ml est un champ séparé)

---

## 2. Clé canonique du vin : `wine_key`

```python
import hashlib

def compute_wine_key(producer_norm: str,
                     cuvee_norm: str,
                     vintage: int | None,
                     appellation_norm: str,
                     bottle_ml: int = 750) -> str:
    vintage_str = str(vintage) if vintage is not None else "NV"
    parts = [producer_norm, cuvee_norm, vintage_str, appellation_norm, str(bottle_ml)]
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
```

**Propriétés :**
- 16 caractères hex = 64 bits de namespace → 2^64 keys (10^19 ; aucun risque de collision pour < 10^6 wines)
- **Déterministe** : deux scrapers indépendants qui normalisent correctement produisent la même clé.
- **Stable** : ne change jamais pour un vin donné (sauf si la normalisation elle-même change → ce serait une migration).

**Exemple :**
- Input : `("domaine coche dury", "meursault perrieres", 2020, "meursault premier cru", 750)`
- Raw : `"domaine coche dury|meursault perrieres|2020|meursault premier cru|750"`
- SHA1 : `c4f3a8b9d1e2f4a5...`
- `wine_key` : `c4f3a8b9d1e2f4a5`

---

## 3. Identifiants composites secondaires

| Type | Format | Exemple |
|---|---|---|
| `producer_key` | INTEGER autoinc | `1042` |
| `appellation_key` | INTEGER autoinc | `87` |
| `source_key` | INTEGER autoinc | `4` |
| `wine_key` | TEXT(16) | `c4f3a8b9d1e2f4a5` |
| `cellar_location_id` | INTEGER 1-36 | `12` |
| `inventory_id` | INTEGER autoinc | `2401` |

---

## 4. Vocabulaires fermés (enums SQLite via CHECK)

### `color`
`red | white | rosé | sparkling | sweet | fortified | orange`

### `appellation_level`
`regional | village | premier_cru | grand_cru | iconic`

(`iconic` = non-classifiés mais cultes type Tignanello, Sassicaia)

### `critic_code` (Cassandra's enum)
`WA | Vinous | BH | JMIB | RVF | Decanter | JS | JG | JD | WS | Hachette | CT | WE | WAL | WD | GV | Halliday | VI | XW | SM`

(`CT` = CellarTracker community = `reviewer_type = user_aggregate`)

`JG` = John Gilman (View from the Cellar); `JD` = Jeb Dunnuck — these are distinct critics, do not conflate.

**Official critics (primary tier).** Six curated critics display first everywhere; all
others stay ingested as secondary. Display labels/names live in `lib/critics.ts`:

| code | label | name |
|---|---|---|
| `WA` | RP | Parker |
| `Vinous` | VN | Vinous |
| `JD` | JD | Jeb Dunnuck |
| `JMIB` | JM | Jasper Morris |
| `RVF` | LVF | Les Vins de France |
| `Hachette` | Hachette | Guide Hachette |

Critic labels/names are brand proper nouns and are **never translated** (same rule as `canonical_name`).

### `reviewer_type`
`critic | user_aggregate`

### `scale`
`/100 | /20 | /5 | stars`

### `price_kind`
`retail_in_stock | retail_oos | release | auction_hammer | secondary`

### `source_tier`
`A_official | B_retailer_major | C_retailer_minor | D_user_aggregate | E_press_critic`

### `currency_code`
ISO 4217 — `EUR` est la base. `GBP`, `USD`, `CHF` permis avec FX vers EUR au record_date.

### `bottle_ml`
`187 | 375 | 500 | 750 | 1500 | 3000 | 6000 | 12000 | 18000` (DOM, Magnum, Jéroboam, Mathusalem, etc.)

---

## 5. Pays et régions

ISO-3166-1 alpha-2 pour `country_code` (`FR`, `IT`, `ES`, `DE`, `AT`, `PT`, `US`, `AU`, `NZ`, `ZA`, `CL`, `AR`).

`region` et `subregion` suivent la nomenclature de l'autorité locale :
- France : INAO (Bourgogne, Bordeaux, Champagne, Vallée du Rhône, Loire, Alsace, Languedoc-Roussillon, Provence, Sud-Ouest, Beaujolais, Savoie, Jura, Corse)
- Italie : DOC/DOCG (Toscana, Piemonte, Veneto, etc.)
- Espagne : DO/DOCa (Rioja, Ribera del Duero, etc.)

---

## 6. Allowed appellations (le hard region gate)

Chaque `dim_producer` a une colonne `allowed_appellations TEXT` (JSON array).

```json
{
  "producer_name": "Domaine Raveneau",
  "country_code": "FR",
  "region": "Bourgogne",
  "subregion": "Chablis",
  "allowed_appellations": [
    "Chablis",
    "Chablis 1er Cru",
    "Chablis Grand Cru"
  ]
}
```

**Avant d'insérer une row dans `dim_wine`** :
```python
if appellation_canonical not in producer.allowed_appellations:
    dead_letter(
        source=source_code,
        error_class="region_gate",
        error_message=f"Producer '{producer.name}' has appellation '{appellation_canonical}' "
                      f"not in allowed list {producer.allowed_appellations}",
        raw_record=record,
    )
    return  # do NOT insert
```

C'est la barrière qui aurait empêché les bugs Raveneau/Bordeaux et Laroche/Sancerre.

---

## 7. Noms canoniques pour l'UI

L'UI affiche `dim_wine.canonical_name` qui est construit comme :

```
{producer_name} · {cuvee_name} · {vintage_or_NV} · {bottle_ml/750 if ≠ 750}
```

Exemples :
- `Domaine Coche-Dury · Meursault Perrières · 2020`
- `Château Pétrus · Pomerol · 2015 · Magnum`
- `Krug · Grande Cuvée 170ème Édition · NV`

**Les noms canoniques ne sont jamais traduits.** Le multilingue ne concerne que l'UI chrome, les labels de filtres, et les libellés métier.
