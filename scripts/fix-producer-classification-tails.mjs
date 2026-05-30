#!/usr/bin/env node
/**
 * Fix 392 dim_producer entries where the producer name contains
 * a full wine description (e.g. "Chambertin Grand Cru - Armand Rousseau").
 *
 * Patterns handled:
 *   A: "Appellation [1er/GC] [cuvée] - ProducerName"  (324 entries)
 *   B: "ProducerName : AppellationDescription"          (45 entries)
 *   C: "ALLCAPS APPELLATION JADOT/CARILLON etc."         (3 entries)
 *   D: Special cases (Saint-Emilion GCC flip, Egly-Ouriet, Producer+App prefix)
 *
 * For each fake producer:
 *   1. Extract the real producer name + raw cuvée description
 *   2. Find or create the real producer in dim_producer
 *   3. Update dim_wine: set producer_key, update cuvee_name (cleaned)
 *   4. Delete the orphaned fake dim_producer row
 *
 * Defaults to DRY-RUN. Pass --apply to mutate.
 */
import fs from 'fs';
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');
const db = new Database(DB_PATH, APPLY ? undefined : { readonly: true });
if (APPLY) db.pragma('foreign_keys = OFF');

function normText(s) {
  return (s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[,.'"/\-()\[\]_&+]/g, ' ').replace(/\s+/g, ' ').trim();
}

// ── Producer lookup helpers ───────────────────────────────────────────────────

// Hardcoded overrides: (lower-case fragment in extracted producer name) → producer_key
// NOTE: keys are fed through normText() during lookup, so you can use
// raw names here — dots, dashes, accents, & etc. are all normalized.
const PRODUCER_OVERRIDES_RAW = [
  // Louis Jadot variants
  ['louis jadot', 77], ['jadot', 77],
  // Louis Latour variants
  ['louis latour', 337], ['domaine louis latour', 337],
  // William Fèvre variants (no accent, various spellings)
  ['william fevre', 6], ['william fèvre', 6], ['domaine william fevre', 6],
  // Ponsot
  ['domaine ponsot', 28], ['ponsot', 28],
  // Coche-Dury
  ['domaine coche-dury', 1], ['domaine coche dury', 1], ['coche-dury', 1], ['coche dury', 1],
  // D.E. Defaix (Daniel-Étienne Defaix)
  ['d.e defaix', 283], ['d.e. defaix', 283], ['daniel-etienne defaix', 283],
  // Larmandier-Bernier (fallback — already found by normalized lookup mostly)
  ['larmandier-bernier', 44405], ['larmandier bernier', 44405],
  // Comtes Lafon
  ['domaine des comtes lafon', 37082], ['comtes lafon', 65], ['comtes lafon', 37082],
  // JM Boillot
  ['jm boillot', 58288], ['j.m. boillot', 58288], ['j.m boillot', 58288], ['jean-marie boillot', 58288],
  // Jean Charles Rion → not in DB, will be created
  // Laurent Tribut
  ['laurent tribu', 58567], ['laurent tribut', 58567], ['domaine tribut', 99],
  // Faiveley
  ['domaine faiveley', 22], ['faiveley', 22],
  // Ramonet
  ['domaine ramonet', 71], ['ramonet', 71],
  // Rapet
  ['domaine rapet', 237], ['domaine rapet père et fils', 237], ['rapet', 237],
  // Albert Bichot
  ['maison albert bichot', 336], ['albert bichot', 336],
  // Bouchard Père & Fils
  ['bouchard père & fils', 33603], ['domaine bouchard père & fils', 33603],
  ['bouchard pere & fils', 33603], ['bouchard pere et fils', 33603],
  ['maison bouchard père et fils', 58130], ['maison bouchard pere et fils', 58130],
  // Jean Chartron
  ['domaine jean chartron', 144], ['jean chartron', 144],
  // Olivier Leflaive
  ['domaine olivier leflaive', 58890], ['olivier leflaive', 58890], ['maison olivier leflaive', 58890],
  // J.-A. Ferret
  ['domaine j.-a. ferret', 3539], ['j.-a. ferret', 3539], ['j.a. ferret', 3539],
  // Egly-Ouriet
  ['champagne egly-ouriet', 498], ['egly-ouriet', 498], ['egly ouriet', 498],
  // Drappier
  ['champagne drappier', 521], ['drappier', 521],
  // Bruno Paillard
  ['champagne bruno paillard', 31415], ['bruno paillard', 31415],
  // Chanson
  ['maison chanson père et fils', 343], ['chanson père et fils', 343], ['chanson', 343],
  // Philipponnat
  ['philipponnat', 46242],
  // Geoffroy / René Geoffroy
  ['geoffroy', 36334], ['rene geoffroy', 3900], ['rené geoffroy', 3900],
  // Louis Michel
  ['domaine louis michel & fils', 9], ['louis michel', 9],
  // Armand Rousseau
  ['domaine armand rousseau', 16], ['armand rousseau', 16],
  // Château de la Tour
  ['château de la tour', 8120], ['chateau de la tour', 8120],
  // Louis Carillon (for ALLCAPS CARILLON suffix)
  ['domaine louis carillon', 57588],
  // d'Ardhuy
  ["domaine d'ardhuy", 703], ['domaine ardhuy', 703], ["d'ardhuy", 703],
  // Henri Gouges
  ['domaine henri gouges', 51], ['henri gouges', 51],
  // Jean-Baptiste Adam
  ['jean-baptiste adam', 878],
  // Françoise André
  ['domaine françoise andré', 45323], ['domaine françoise andre', 45323], ['françoise andré', 45323],
  // Gustave Lorentz
  ['gustave lorentz', 5579],
  // Grivot
  ['domaine jean grivot', 43], ['jean grivot', 43], ['grivot', 43],
  // Perrot-Minot
  ['domaine perrot-minot', 301], ['perrot-minot', 301],
  // Michel Gros
  ['domaine michel gros', 141], ['michel gros', 141],
  // Long-Depaquit (via Albert Bichot ownership)
  ['domaine long-depaquit', 93], ['long-depaquit', 93],
  // Maison André Bergère
  ['maison andré bergère', 58079],
  // Au pied du Mont Chauve
  ['au pied du mont chauve', 689],
  // Clusel-Roch
  ['domaine clusel-roch', 593], ['clusel-roch', 593],
  // Billecart-Salmon
  ['billecart-salmon', 43412],
  // Duval-Leroy
  ['duval-leroy', 3340],
  // Domaine de la Vougeraie
  ['domaine de la vougeraie', 108],
  // Billaud-Simon (dashes stripped by normText)
  ['billaud simon', 282], ['domaine billaud simon', 282],
  // Jean-Paul et Benoît Droin
  ['jean paul et benoit droin', 287], ['jean paul benoit droin', 287],
  ['domaine jean paul et benoit droin', 287],
  // Marc Colin
  ['marc colin et ses fils', 119], ['marc colin et fils', 119], ['domaine marc colin', 119],
  // Michel Sarrazin & Fils
  ['michel sarrazin et fils', 34843], ['michel sarrazin fils', 34843],
  // Jean-Marc Pillot
  ['jean marc pillot', 147], ['jean-marc pillot', 147], ['domaine jean marc pillot', 147],
  // Mongeard-Mugneret
  ['mongeard mugneret', 304], ['domaine mongeard mugneret', 304],
  // Blain-Gagnard
  ['blain gagnard', 40353], ['domaine blain gagnard', 40353],
  // Jean-Michel Gaunoux
  ['jean michel gaunoux', 32213], ['jean-michel gaunoux', 32213],
  // Thomas Pico = Domaine Pattes Loup
  ['thomas pico', 10],
  // Méo-Camuzet (accent + dash stripped)
  ['meo camuzet', 40], ['domaine meo camuzet', 40],
  // Bouchard (normalized — & and accents stripped)
  ['bouchard pere fils', 33603], ['domaine bouchard pere fils', 33603],
  ['maison bouchard pere et fils', 58130],
  // D.E. Defaix (dots stripped)
  ['d e defaix', 283], ['domaine d e defaix', 283], ['daniel etienne defaix', 283],
  // J.-A. Ferret (dashes stripped)
  ['j a ferret', 3539], ['domaine j a ferret', 3539],
  // Larmandier (fallback)
  ['larmandier bernier', 44405],
];

// Build map with normalized keys for reliable lookup
const PRODUCER_OVERRIDES = new Map(
  PRODUCER_OVERRIDES_RAW.map(([k, v]) => [normText(k), v])
);

function lookupProducer(name) {
  const lower = normText(name);
  // 1. Hardcoded override
  if (PRODUCER_OVERRIDES.has(lower)) return PRODUCER_OVERRIDES.get(lower);
  // Try partial match in overrides (if extracted name is longer than map key)
  for (const [k, v] of PRODUCER_OVERRIDES) {
    if (lower === k || lower.endsWith(' ' + k) || lower.startsWith(k + ' ')) return v;
  }
  // 2. Exact case-insensitive match in DB
  const exact = db.prepare(`
    SELECT producer_key FROM dim_producer
    WHERE LOWER(producer_name) = LOWER(?)
    AND producer_name NOT LIKE '%1er Cru%' AND producer_name NOT LIKE '%Grand Cru%'
    AND producer_name NOT LIKE '% - %' AND producer_name NOT LIKE '%:%'
    LIMIT 1
  `).get(name);
  if (exact) return exact.producer_key;
  // 3. Accent-stripped normalized match
  const normName = normText(name).replace(/\s+/g, ' ');
  const all = db.prepare(`
    SELECT producer_key, producer_name FROM dim_producer
    WHERE producer_name NOT LIKE '%1er Cru%' AND producer_name NOT LIKE '%Grand Cru%'
    AND producer_name NOT LIKE '% - %' AND producer_name NOT LIKE '%:%'
  `).all();
  const match = all.find(r => normText(r.producer_name) === normName);
  if (match) return match.producer_key;
  // 4. Strip common prefixes and try again
  const stripped = name.replace(/^(Domaine|Château|Maison|Champagne|Domaine de la?|Domaine du)\s+/i, '').trim();
  if (stripped !== name) {
    const strippedNorm = normText(stripped);
    const m2 = all.find(r => normText(r.producer_name) === strippedNorm ||
      normText(r.producer_name).endsWith(' ' + strippedNorm));
    if (m2) return m2.producer_key;
    // LIKE search with stripped name
    const like = db.prepare(`
      SELECT producer_key FROM dim_producer
      WHERE LOWER(producer_name) LIKE LOWER(?)
      AND producer_name NOT LIKE '%1er Cru%' AND producer_name NOT LIKE '%Grand Cru%'
      AND producer_name NOT LIKE '% - %' AND producer_name NOT LIKE '%:%'
      ORDER BY LENGTH(producer_name) ASC LIMIT 1
    `).get(`%${stripped}%`);
    if (like) return like.producer_key;
  }
  // 5. LIKE on the full name (last resort)
  const likeAll = db.prepare(`
    SELECT producer_key FROM dim_producer
    WHERE LOWER(producer_name) LIKE LOWER(?)
    AND producer_name NOT LIKE '%1er Cru%' AND producer_name NOT LIKE '%Grand Cru%'
    AND producer_name NOT LIKE '% - %' AND producer_name NOT LIKE '%:%'
    ORDER BY LENGTH(producer_name) ASC LIMIT 1
  `).get(`%${name}%`);
  return likeAll ? likeAll.producer_key : null;
}

// Classification terms to strip from extracted cuvée text
const CLASS_RE = /\b(1er\s+[Cc]ru|premier\s+grand?\s+cru|grand\s+cru|cru\s+class[ée]|cru\s+bourgeois|classé)\b/gi;
// Appellation prefix stripping: given cuvée text + wine appellation, strip leading appellation
function cleanCuvee(text, appellationName) {
  let out = text.trim();
  // Strip leading appellation name (exact + normalized variant)
  if (appellationName) {
    const esc = appellationName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    out = out.replace(new RegExp(`^\\s*${esc}\\s*`, 'i'), '');
    // Also try norm variant (strip accents from both sides)
    const normApp = normText(appellationName).replace(/\s+/g, '\\s+');
    out = out.replace(new RegExp(`^\\s*${normApp}\\s*`, 'i'), '');
    // Strip first word of appellation (e.g. "Chablis" from "Chablis 1er cru")
    const firstWord = appellationName.split(/[\s\-]+/)[0];
    if (firstWord && firstWord.length >= 4) {
      const esc2 = firstWord.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      out = out.replace(new RegExp(`^\\s*${esc2}\\s+`, 'i'), '');
    }
  }
  // Strip leading classification terms
  out = out.replace(/^\s*(1er\s+[Cc]ru|premier\s+(grand\s+)?cru|grand\s+cru|cru\s+class[ée])\s*/i, '');
  // Strip trailing classification + style terms
  out = out.replace(/\s*(,\s*|\s+[-–]\s+)?(1er\s+[Cc]ru|grand\s+cru|cru\s+class[ée])\s*$/i, '');
  out = out.replace(/\s*(extra[- ]brut|brut\s+nature?|brut|blanc\s+de\s+blancs?|blanc\s+de\s+noirs?)\s*$/i, '');
  out = out.replace(/\s*[-–]\s*$/,'');
  // Strip leading/trailing separators
  out = out.replace(/^\s*[-–,;:]+\s*/, '').replace(/\s*[-–,;:]+\s*$/, '');
  return out.trim();
}

// ── Parse patterns ────────────────────────────────────────────────────────────

// Pattern C: ALLCAPS suffix map
const ALLCAPS_SUFFIX_MAP = {
  'JADOT':   77,   // Maison Louis Jadot
  'CARILLON': 57588, // Domaine Louis Carillon
  'BACHELET': 41,  // Domaine Denis Bachelet
  'FAIVELEY': 22,  // Domaine Faiveley
};

function classify(producerName) {
  // Pattern B: "Producer : Description"
  const colonIdx = producerName.indexOf(' : ');
  if (colonIdx > 0) {
    return {
      pattern: 'B',
      realProducer: producerName.slice(0, colonIdx).trim(),
      rawCuvee: producerName.slice(colonIdx + 3).trim(),
    };
  }
  // Pattern A: either "Description - Producer" OR "Producer - Description"
  const dashIdx = producerName.lastIndexOf(' - ');
  if (dashIdx > 0) {
    const after = producerName.slice(dashIdx + 3).trim();
    const before = producerName.slice(0, dashIdx).trim();

    // Packaging/format suffixes that indicate the after-part is NOT a producer
    const isPackagingSuffix = after.match(/^(rouge|blanc|rosé|rose|brut|sec|doux|etui|owc|coffret|kist|wijnpakket|mag\b)/i);
    if (isPackagingSuffix) {
      // Fall through to Pattern D
    } else {
      // Detect reversed format: "Producer - AppellationGC" (after contains classification)
      const afterHasClassification = /\b(grand\s+cru|1er\s+cru|premier\s+cru|grand\s+premier|cru\s+class[eé])\b/i.test(after);
      const afterHasAppellation = /\b(champagne|chablis|bourgogne|beaune|pommard|volnay|gevrey|vosne|nuits|meursault|corton|montrachet|chambolle|morey|santenay|aloxe|puligny|chassagne|pernand|alsace|sancerre|pouilly|hermitage|crozes|saint[- ]joseph|bordeaux)\b/i.test(after);

      if (afterHasClassification && !after.match(/^\d/) && before.length >= 4) {
        // REVERSED: "Producer - AppellationClassification" → producer is BEFORE dash
        return { pattern: 'A', realProducer: before, rawCuvee: after };
      }

      const looksLikeProducer = after.length >= 3 && !after.match(/^\d/);
      if (looksLikeProducer) {
        return { pattern: 'A', realProducer: after, rawCuvee: before };
      }
    }
  }

  return { pattern: 'D', realProducer: null, rawCuvee: producerName };
}

// ── CSV loading ───────────────────────────────────────────────────────────────

const text = fs.readFileSync('C:/Claude/achilles-wines/data/manual-review.csv', 'utf8').replace(/^﻿/, '');
const lines = text.split('\n').filter(l => l.trim());

function parseCSV(lines) {
  const header = lines[0].split(',').map(h => h.trim());
  const rows = [];
  for (const line of lines.slice(1)) {
    const cols = [];
    let i = 0;
    while (i < line.length) {
      if (line[i] === '"') {
        i++; let field = '';
        while (i < line.length) {
          if (line[i] === '"' && line[i + 1] === '"') { field += '"'; i += 2; }
          else if (line[i] === '"') { i++; break; }
          else field += line[i++];
        }
        cols.push(field); if (line[i] === ',') i++;
      } else {
        let j = i; while (j < line.length && line[j] !== ',') j++;
        cols.push(line.slice(i, j)); i = j + 1;
      }
    }
    rows.push(Object.fromEntries(header.map((h, idx) => [h, (cols[idx] || '').trim()])));
  }
  return rows;
}

const pct = parseCSV(lines).filter(r => r.category === 'producer_classification_tail');

const fetchProducer = db.prepare('SELECT producer_key, producer_name FROM dim_producer WHERE producer_key=?');
const fetchWines = db.prepare(`
  SELECT w.wine_key, w.cuvee_name, w.vintage, a.appellation_name, a.appellation_key
  FROM dim_wine w
  JOIN dim_appellation a ON a.appellation_key = w.appellation_key
  WHERE w.producer_key = ?
`);
const findProducerByName = db.prepare(`
  SELECT producer_key, producer_name FROM dim_producer WHERE LOWER(producer_name) LIKE LOWER(?) LIMIT 1
`);

// ── Hardcoded exceptions (producer_key → {realProducerKey, cuvee}) ────────────
// For entries where the automated classify() logic can't produce the right result
const HARDCODED = new Map([
  // ALLCAPS JADOT entries
  [32005, { realPk: 77, cuvee: 'Les Chaumes' }],       // VOSNE-ROMANEE 1er CRU LES CHAUMES JADOT
  [33354, { realPk: 77, cuvee: 'Cazetiers' }],          // GEVREY-CHAMBERTIN 1ER CRU CAZETIERS JADOT
  [33550, { realPk: 77, cuvee: 'Embazées' }],           // CHASSAGNE-MONTRACHET 1er Cru EMBAZEES JADOT 2022C6
  // Pommery "- Etui" (packaging suffix drops to D_unknown)
  // pk for Champagne Pommery in DB — let lookup resolve
]);

// ── Build the plan ────────────────────────────────────────────────────────────

const PLAN = [];
const SKIP = [];
const patternCounts = { A: 0, B: 0, C: 0, D_special: 0, D_prefix: 0, D_skip: 0 };

// Producers to create (name → key — filled during dry-run preview)
const PRODUCERS_TO_CREATE = new Map();

for (const r of pct) {
  const fakePk = Number(r.key);
  const prodRow = fetchProducer.get(fakePk);
  if (!prodRow) { SKIP.push({ key: fakePk, reason: 'producer not found' }); continue; }
  const wines = fetchWines.all(fakePk);

  // Check hardcoded exceptions first
  if (HARDCODED.has(fakePk)) {
    const hc = HARDCODED.get(fakePk);
    patternCounts['C']++;
    PLAN.push({ type: 'producer_fix', fakePk, fakeName: prodRow.producer_name,
      pattern: 'C', realProducer: `pk=${hc.realPk}`, realPk: hc.realPk,
      rawCuvee: hc.cuvee, cleanedCuvee: hc.cuvee, wines });
    PLAN.push({ type: 'delete_producer', fakePk });
    continue;
  }

  const cls = classify(prodRow.producer_name);

  // ── Pattern D special cases ────────────────────────────────────────────────
  if (cls.pattern === 'D') {
    const name = prodRow.producer_name;

    // "Saint-Emilion Grand Cru" (pk=40221): flip producer←→cuvée for each wine
    if (fakePk === 40221) {
      patternCounts.D_special++;
      for (const w of wines) {
        const chateauName = w.cuvee_name?.trim();
        if (!chateauName) continue;
        const realPk = lookupProducer(chateauName) ||
          findProducerByName.get(`%${chateauName.replace(/^Château\s*/i, '')}%`)?.producer_key;
        PLAN.push({
          type: 'wine_update',
          wineKey: w.wine_key,
          newProducerKey: realPk || `CREATE:${chateauName}`,
          newCuvee: '',
          newCuveeNorm: '',
          fakePk,
          note: `FLIP: "${chateauName}" becomes producer`,
        });
      }
      PLAN.push({ type: 'delete_producer', fakePk });
      continue;
    }

    // Egly-Ouriet entries (5 fake producers)
    if (name.toLowerCase().includes('egly-ouriet') || name.toLowerCase().includes('egly ouriet')) {
      patternCounts.D_special++;
      const cuveeRaw = name.replace(/^Champagne\s+/i, '').replace(/Egly[- ]Ouriet\s*/gi, '').trim();
      const cuvee = cleanCuvee(cuveeRaw, wines[0]?.appellation_name || '');
      for (const w of wines) {
        PLAN.push({ type: 'wine_update', wineKey: w.wine_key, newProducerKey: 498, newCuvee: cuvee, newCuveeNorm: normText(cuvee), fakePk });
      }
      PLAN.push({ type: 'delete_producer', fakePk });
      continue;
    }

    // "Producer AppellationClassification" prefix format
    // These start with a known producer name followed by appellation+classification
    // Detect by looking for known producer names at the start
    const knownPrefixes = [
      { re: /^Justin Girardin\s+/i, producerName: 'Justin Girardin', pk: null },
      { re: /^Domaine Rapet\s+/i, producerName: 'Domaine Rapet Père et Fils', pk: 237 },
      { re: /^Domaine Bouchard Père & Fils\s+/i, producerName: 'Domaine Bouchard Père & Fils', pk: 33603 },
      { re: /^Domaine Bouchard Père et Fils\s+/i, producerName: 'Maison Bouchard Père et Fils', pk: 58130 },
      { re: /^Domaine Françoise André\s+/i, producerName: 'Domaine Françoise André', pk: 45323 },
      { re: /^Domaine D'Ardhuy\s+/i, producerName: "Domaine d'Ardhuy", pk: 703 },
      { re: /^Domaine D Ardhuy\s+/i, producerName: "Domaine d'Ardhuy", pk: 703 },
      { re: /^Domaine Henri Gouges\s+/i, producerName: 'Domaine Henri Gouges', pk: 51 },
      { re: /^Jean-Baptiste Adam\s+/i, producerName: 'Jean-Baptiste Adam', pk: 878 },
      { re: /^Jean Chartron\s+/i, producerName: 'Domaine Jean Chartron', pk: 144 },
      { re: /^Olivier Leflaive\s+/i, producerName: 'Domaine Olivier Leflaive', pk: 58890 },
      { re: /^Domaine Bouthenet-Clerc\s+/i, producerName: 'Domaine Bouthenet-Clerc', pk: null },
      { re: /^Domaine Jean-Baptiste Adam\s+/i, producerName: 'Jean-Baptiste Adam', pk: 878 },
      // Champagne Egly-Ouriet with 1er Cru (no dash)
      { re: /^Champagne Egly-Ouriet\s+/i, producerName: 'Champagne Egly-Ouriet', pk: 498 },
      { re: /^Champagne Pommery\s+/i, producerName: 'Champagne Pommery', pk: null },
    ];

    let handled = false;
    for (const pref of knownPrefixes) {
      if (pref.re.test(name)) {
        patternCounts.D_prefix++;
        const restAfterProducer = name.replace(pref.re, '').trim();
        const cuvee = cleanCuvee(restAfterProducer, wines[0]?.appellation_name || '');
        const pk = pref.pk || lookupProducer(pref.producerName);
        for (const w of wines) {
          PLAN.push({ type: 'wine_update', wineKey: w.wine_key, newProducerKey: pk || `CREATE:${pref.producerName}`, newCuvee: cuvee, newCuveeNorm: normText(cuvee), fakePk });
        }
        PLAN.push({ type: 'delete_producer', fakePk });
        handled = true;
        break;
      }
    }
    if (!handled) {
      patternCounts.D_skip++;
      SKIP.push({ key: fakePk, name: name, reason: 'Pattern D: unhandled', wines: wines.length });
    }
    continue;
  }

  // ── Patterns A, B, C ──────────────────────────────────────────────────────
  patternCounts[cls.pattern]++;
  const realPk = cls.realProducerKey || lookupProducer(cls.realProducer);

  const appName = wines[0]?.appellation_name || '';
  const rawCuvee = cls.rawCuvee;
  const cleanedCuvee = cleanCuvee(rawCuvee, appName);

  PLAN.push({
    type: 'producer_fix',
    fakePk,
    fakeName: prodRow.producer_name,
    pattern: cls.pattern,
    realProducer: cls.realProducer,
    realPk: realPk || `CREATE:${cls.realProducer}`,
    rawCuvee,
    cleanedCuvee,
    wines,
  });
}

// ── Preview ───────────────────────────────────────────────────────────────────
const producerFixes = PLAN.filter(p => p.type === 'producer_fix');
const wineUpdates = PLAN.filter(p => p.type === 'wine_update');
const deleteProducers = PLAN.filter(p => p.type === 'delete_producer');

console.log('=== Pattern counts ===');
Object.entries(patternCounts).forEach(([k, v]) => console.log(`  ${k}: ${v}`));
console.log(`  Skipped: ${SKIP.length}`);
console.log();
console.log(`  Producer-fix entries: ${producerFixes.length}`);
console.log(`  Wine-update entries: ${wineUpdates.length}`);
console.log(`  Producers to delete: ${deleteProducers.length}`);

// Count "CREATE:" cases
const createCases = PLAN.filter(p =>
  (typeof p.realPk === 'string' && p.realPk.startsWith('CREATE:')) ||
  (p.newProducerKey && typeof p.newProducerKey === 'string' && p.newProducerKey.startsWith('CREATE:'))
);
console.log(`  Cases needing new producer: ${createCases.length}`);

// Show sample of each pattern
console.log('\n--- Sample A (5) ---');
producerFixes.filter(p=>p.pattern==='A').slice(0,5).forEach(p => {
  const found = typeof p.realPk === 'number' ? `pk=${p.realPk}` : p.realPk;
  console.log(`  [pk=${p.fakePk}] "${p.fakeName}"`);
  console.log(`    → producer: "${p.realProducer}" (${found})`);
  console.log(`    → cuvée: "${p.cleanedCuvee}" (from: "${p.rawCuvee}")`);
  console.log(`    wines: ${p.wines.map(w=>`"${w.cuvee_name||''}" ${w.vintage??'NV'}`).join(', ')}`);
});
console.log('\n--- Sample B (5) ---');
producerFixes.filter(p=>p.pattern==='B').slice(0,5).forEach(p => {
  const found = typeof p.realPk === 'number' ? `pk=${p.realPk}` : p.realPk;
  console.log(`  [pk=${p.fakePk}] "${p.fakeName}"`);
  console.log(`    → producer: "${p.realProducer}" (${found})`);
  console.log(`    → cuvée: "${p.cleanedCuvee}"`);
  console.log(`    wines: ${p.wines.map(w=>`"${w.cuvee_name||''}" ${w.vintage??'NV'} (${w.appellation_name})`).join(', ')}`);
});
console.log('\n--- Pattern C (all) ---');
producerFixes.filter(p=>p.pattern==='C').forEach(p => {
  console.log(`  [pk=${p.fakePk}] "${p.fakeName}" → pk=${p.realPk} | cuvée: "${p.cleanedCuvee}"`);
  console.log(`    wines: ${p.wines.map(w=>`"${w.cuvee_name||''}" ${w.vintage??'NV'} (${w.appellation_name})`).join(', ')}`);
});
console.log('\n--- CREATE cases ---');
createCases.slice(0,10).forEach(p => {
  const name = p.realPk || p.newProducerKey;
  console.log(`  ${name}`);
});
console.log('\n--- SKIP cases ---');
SKIP.forEach(s => console.log(`  [pk=${s.key}] "${s.name || '?'}" — ${s.reason} (${s.wines ?? '?'} wines)`));

if (!APPLY) {
  console.log('\n(Dry-run — re-run with --apply to mutate.)');
  db.close();
  process.exit(0);
}

// ── Apply ─────────────────────────────────────────────────────────────────────

const insertProducer = db.prepare(`
  INSERT INTO dim_producer (producer_name, producer_norm, country_code, allowed_appellations, aliases)
  VALUES (?, ?, 'FR', '[]', '[]')
`);
const updateWine = db.prepare(`
  UPDATE dim_wine SET producer_key=?, cuvee_name=?, cuvee_norm=?, canonical_name=?
  WHERE wine_key=?
`);
const updateWineProducerOnly = db.prepare(`UPDATE dim_wine SET producer_key=? WHERE wine_key=?`);
const deleteFakeProducer = db.prepare(`DELETE FROM dim_producer WHERE producer_key=?`);
const getWineForUpdate = db.prepare(`
  SELECT w.wine_key, w.cuvee_name, w.vintage, p.producer_name
  FROM dim_wine w JOIN dim_producer p ON p.producer_key=w.producer_key
  WHERE w.wine_key=?
`);

// Cache newly created producer keys
const createdProducers = new Map();

function resolveOrCreate(realPkOrCreate) {
  if (typeof realPkOrCreate === 'number') return realPkOrCreate;
  const createName = realPkOrCreate.replace('CREATE:', '');
  if (createdProducers.has(createName)) return createdProducers.get(createName);
  const newPk = insertProducer.run(createName, normText(createName)).lastInsertRowid;
  createdProducers.set(createName, newPk);
  console.log(`  Created producer [pk=${newPk}] "${createName}"`);
  return newPk;
}

const tx = db.transaction(() => {
  let winesUpdated = 0;
  let producersDeleted = 0;

  // Process producer-fix entries (A, B, C patterns)
  for (const fix of producerFixes) {
    const realPk = resolveOrCreate(fix.realPk);
    for (const w of fix.wines) {
      const existing = getWineForUpdate.get(w.wine_key);
      if (!existing) continue;
      const newCuvee = fix.cleanedCuvee;
      const newNorm = normText(newCuvee);
      const canon = [existing.producer_name /* updated next via FK */, newCuvee, w.vintage]
        .filter(Boolean).join(' ');
      // Get producer name for canonical
      const prow = fetchProducer.get(realPk);
      const canonFinal = [prow?.producer_name || '', newCuvee, w.vintage]
        .filter(x => x !== null && x !== undefined && x !== '').join(' ').trim();
      updateWine.run(realPk, newCuvee, newNorm, canonFinal, w.wine_key);
      winesUpdated++;
    }
    deleteFakeProducer.run(fix.fakePk);
    producersDeleted++;
  }

  // Process D-pattern wine updates
  const deletedFakePks = new Set(producerFixes.map(f => f.fakePk));
  for (const upd of wineUpdates) {
    const realPk = resolveOrCreate(upd.newProducerKey);
    const existing = getWineForUpdate.get(upd.wineKey);
    if (!existing) continue;
    const prow = fetchProducer.get(realPk);
    const newCuvee = upd.newCuvee;
    const newNorm = upd.newCuveeNorm;
    const canon = [prow?.producer_name || '', newCuvee, existing.vintage]
      .filter(x => x !== null && x !== undefined && x !== '').join(' ').trim();
    updateWine.run(realPk, newCuvee, newNorm, canon, upd.wineKey);
    winesUpdated++;
  }
  for (const del of deleteProducers) {
    if (!deletedFakePks.has(del.fakePk)) {
      deleteFakeProducer.run(del.fakePk);
      producersDeleted++;
    }
  }

  console.log(`\nUpdated ${winesUpdated} wines.`);
  console.log(`Deleted ${producersDeleted} fake producers.`);
  console.log(`Created ${createdProducers.size} new producers.`);
});

tx();

// Run orphan producer cleanup
const orphans = db.prepare(`
  DELETE FROM dim_producer WHERE producer_key IN (
    SELECT p.producer_key FROM dim_producer p
    WHERE NOT EXISTS (SELECT 1 FROM dim_wine w WHERE w.producer_key=p.producer_key)
      AND p.producer_key NOT IN (SELECT producer_key FROM dim_wine GROUP BY producer_key)
  )
`).run();
console.log(`Removed ${orphans.changes} orphaned producers.`);
console.log('\nDone. Run the cleanup pipeline next.');
db.close();
