/**
 * Seed fact_vintage_rating with editorial consensus vintage ratings (1-5 scale).
 * Based on widely published consensus: Decanter, Wine Spectator, Wine Advocate.
 * Uses scale="/5", color="all". scoreNormalized100 = score * 20.
 *
 * Run once: node scripts/seed_vintage_ratings.mjs
 */

import Database from 'better-sqlite3';
const db = new Database('data/achilles.db');

// ── 1. Ensure a "vintage_consensus" source exists ──────────────────────────
let src = db.prepare("SELECT source_key FROM dim_source WHERE source_code='vintage_consensus'").get();
if (!src) {
  db.prepare(`
    INSERT INTO dim_source (source_code, source_name, source_tier, country_code,
      base_url, license_class, cadence, enabled, requires_auth)
    VALUES ('vintage_consensus','Editorial Consensus','E_press_critic',NULL,
      NULL,'public_check_terms','one_shot',1,0)
  `).run();
  src = db.prepare("SELECT source_key FROM dim_source WHERE source_code='vintage_consensus'").get();
  console.log('Created dim_source vintage_consensus, key=', src.source_key);
} else {
  console.log('Using existing dim_source vintage_consensus, key=', src.source_key);
}
const SOURCE_KEY = src.source_key;

// ── 2. Rating tables per region-family (year → score 1-5) ─────────────────

// Burgundy: Côte de Nuits / Côte de Beaune (reds and whites share same harvest year quality)
const BURGUNDY_RED = {
  1990:5,1991:2,1992:3,1993:2,1994:2,1995:5,1996:5,1997:3,1998:4,1999:4,
  2000:3,2001:3,2002:5,2003:4,2004:3,2005:5,2006:3,2007:3,2008:4,2009:4,
  2010:5,2011:4,2012:4,2013:3,2014:4,2015:5,2016:5,2017:4,2018:4,2019:4,
  2020:4,2021:4,2022:4,2023:4,
};
const CHABLIS = {
  1990:4,1991:2,1992:4,1993:3,1994:3,1995:4,1996:5,1997:3,1998:3,1999:3,
  2000:4,2001:3,2002:5,2003:3,2004:4,2005:4,2006:3,2007:3,2008:4,2009:3,
  2010:5,2011:4,2012:4,2013:4,2014:5,2015:4,2016:4,2017:5,2018:4,2019:5,
  2020:3,2021:5,2022:4,2023:4,
};
const MACONNAIS = {
  1990:4,1995:4,1996:4,1997:3,1998:3,1999:3,2000:3,2001:3,2002:5,2003:3,
  2004:4,2005:4,2006:3,2007:3,2008:4,2009:4,2010:5,2011:4,2012:4,2013:3,
  2014:4,2015:4,2016:4,2017:4,2018:4,2019:4,2020:4,2021:4,2022:4,2023:4,
};
const BEAUJOLAIS = {
  1990:4,1995:4,1996:3,1997:3,1999:5,2000:3,2001:3,2002:3,2003:4,2004:3,
  2005:4,2006:3,2007:4,2008:3,2009:5,2010:4,2011:4,2012:4,2013:3,2014:4,
  2015:5,2016:4,2017:4,2018:4,2019:4,2020:4,2021:4,2022:4,2023:4,
};

// Bordeaux
const BORDEAUX_LEFT = {
  1990:5,1991:2,1992:2,1993:2,1994:2,1995:4,1996:5,1997:2,1998:4,1999:3,
  2000:5,2001:4,2002:3,2003:4,2004:3,2005:5,2006:3,2007:2,2008:4,2009:5,
  2010:5,2011:3,2012:3,2013:2,2014:4,2015:5,2016:5,2017:3,2018:4,2019:5,
  2020:4,2021:3,2022:4,2023:4,
};
const BORDEAUX_RIGHT = {
  1990:5,1991:2,1992:2,1993:2,1994:3,1995:4,1996:4,1997:3,1998:5,1999:3,
  2000:5,2001:5,2002:3,2003:4,2004:3,2005:5,2006:4,2007:3,2008:4,2009:5,
  2010:5,2011:3,2012:4,2013:2,2014:3,2015:5,2016:5,2017:3,2018:4,2019:5,
  2020:4,2021:3,2022:4,2023:3,
};

// Rhône
const RHONE_NORD = {
  1990:5,1991:3,1992:3,1993:3,1994:4,1995:4,1996:4,1997:4,1998:5,1999:5,
  2000:4,2001:4,2002:3,2003:4,2004:4,2005:5,2006:4,2007:5,2008:3,2009:5,
  2010:5,2011:4,2012:4,2013:3,2014:4,2015:5,2016:4,2017:4,2018:5,2019:5,
  2020:4,2021:4,2022:4,2023:4,
};
const RHONE_SUD = {
  1990:4,1991:3,1992:3,1993:3,1994:3,1995:4,1996:4,1997:4,1998:5,1999:4,
  2000:5,2001:4,2002:3,2003:5,2004:3,2005:5,2006:4,2007:4,2008:4,2009:5,
  2010:5,2011:4,2012:4,2013:3,2014:4,2015:5,2016:4,2017:4,2018:4,2019:4,
  2020:4,2021:3,2022:4,2023:4,
};

// Champagne (harvest year)
const CHAMPAGNE = {
  1990:5,1991:2,1992:3,1993:2,1994:3,1995:5,1996:5,1997:3,1998:4,1999:4,
  2000:4,2001:3,2002:5,2003:3,2004:4,2005:5,2006:4,2007:4,2008:5,2009:5,
  2010:4,2011:3,2012:4,2013:3,2014:4,2015:5,2016:4,2017:5,2018:5,2019:5,
  2020:4,2021:4,2022:4,2023:4,
};

// Alsace
const ALSACE = {
  1990:5,1991:3,1992:3,1993:3,1994:3,1995:4,1996:4,1997:4,1998:3,1999:3,
  2000:3,2001:3,2002:4,2003:5,2004:4,2005:4,2006:3,2007:4,2008:3,2009:5,
  2010:4,2011:4,2012:3,2013:4,2014:4,2015:5,2016:4,2017:4,2018:5,2019:4,
  2020:4,2021:3,2022:4,2023:4,
};

// Loire (general)
const LOIRE = {
  1990:4,1991:2,1992:3,1993:2,1994:3,1995:4,1996:4,1997:3,1998:3,1999:4,
  2000:3,2001:3,2002:4,2003:4,2004:3,2005:4,2006:3,2007:3,2008:3,2009:5,
  2010:5,2011:4,2012:3,2013:3,2014:4,2015:5,2016:4,2017:4,2018:5,2019:5,
  2020:4,2021:3,2022:4,2023:4,
};

// Warm-climate / South of France (more consistent, fewer legendary years)
const SOUTH_FRANCE = {
  1990:4,1991:3,1992:3,1993:3,1994:3,1995:3,1996:3,1997:3,1998:4,1999:4,
  2000:4,2001:3,2002:3,2003:4,2004:3,2005:4,2006:3,2007:4,2008:3,2009:5,
  2010:4,2011:4,2012:4,2013:3,2014:3,2015:4,2016:5,2017:4,2018:4,2019:4,
  2020:4,2021:3,2022:5,2023:4,
};

// Jura / Savoie / Lorraine / Corsica (minimal but present)
const EASTERN_FRANCE = {
  1990:4,1995:3,1996:4,1997:3,1998:3,1999:3,
  2000:3,2001:3,2002:4,2003:4,2004:3,2005:4,2006:3,2007:3,2008:3,2009:4,
  2010:4,2011:4,2012:3,2013:3,2014:4,2015:4,2016:4,2017:4,2018:4,2019:4,
  2020:3,2021:3,2022:4,2023:3,
};

// Italy
const TUSCANY = {
  1990:5,1995:5,1997:5,1998:4,1999:4,2000:4,2001:5,2002:2,2003:4,2004:5,
  2005:4,2006:4,2007:5,2008:4,2009:4,2010:5,2011:4,2012:4,2013:4,2014:3,
  2015:5,2016:5,2017:4,2018:5,2019:5,2020:4,2021:4,2022:4,2023:4,
};
const PIEDMONT = {
  1990:5,1995:5,1996:5,1997:5,1998:4,1999:5,2000:4,2001:5,2002:2,2003:4,
  2004:5,2005:4,2006:4,2007:5,2008:4,2009:4,2010:5,2011:4,2012:4,2013:5,
  2014:3,2015:5,2016:5,2017:4,2018:5,2019:5,2020:4,2021:4,2022:4,2023:4,
};

// Map DB regions to rating tables
const REGION_MAP = [
  // FR
  { country: 'FR', region: 'Côte de Nuits',       ratings: BURGUNDY_RED },
  { country: 'FR', region: 'Côte de Beaune',       ratings: BURGUNDY_RED },
  { country: 'FR', region: 'Côte Chalonnaise',     ratings: BURGUNDY_RED },
  { country: 'FR', region: 'Chablis',              ratings: CHABLIS      },
  { country: 'FR', region: 'Chablisien',           ratings: CHABLIS      },
  { country: 'FR', region: 'Mâconnais',            ratings: MACONNAIS    },
  { country: 'FR', region: 'Bourgogne',            ratings: BURGUNDY_RED },
  { country: 'FR', region: 'Beaujolais',           ratings: BEAUJOLAIS   },
  { country: 'FR', region: 'Bordeaux',             ratings: BORDEAUX_LEFT },
  { country: 'FR', region: 'Médoc',                ratings: BORDEAUX_LEFT },
  { country: 'FR', region: 'Graves',               ratings: BORDEAUX_LEFT },
  { country: 'FR', region: 'Libournais',           ratings: BORDEAUX_RIGHT },
  { country: 'FR', region: 'Rhône Nord',           ratings: RHONE_NORD   },
  { country: 'FR', region: 'Rhône Sud',            ratings: RHONE_SUD    },
  { country: 'FR', region: 'Côtes du Rhône Septentrional', ratings: RHONE_NORD },
  { country: 'FR', region: 'Côtes du Rhône Méridional',   ratings: RHONE_SUD  },
  { country: 'FR', region: 'Champagne',            ratings: CHAMPAGNE    },
  { country: 'FR', region: 'Alsace',               ratings: ALSACE       },
  { country: 'FR', region: 'Loire',                ratings: LOIRE        },
  { country: 'FR', region: 'Languedoc',            ratings: SOUTH_FRANCE },
  { country: 'FR', region: 'Languedoc-Roussillon', ratings: SOUTH_FRANCE },
  { country: 'FR', region: 'Roussillon',           ratings: SOUTH_FRANCE },
  { country: 'FR', region: 'Provence',             ratings: SOUTH_FRANCE },
  { country: 'FR', region: 'Sud-Ouest',            ratings: SOUTH_FRANCE },
  { country: 'FR', region: 'Corsica',              ratings: SOUTH_FRANCE },
  { country: 'FR', region: 'Jura',                 ratings: EASTERN_FRANCE },
  { country: 'FR', region: 'Savoie',               ratings: EASTERN_FRANCE },
  { country: 'FR', region: 'Lorraine',             ratings: EASTERN_FRANCE },
  // IT
  { country: 'IT', region: 'Toscane',              ratings: TUSCANY      },
  { country: 'IT', region: 'Toscana',              ratings: TUSCANY      },
  { country: 'IT', region: 'Piémont',              ratings: PIEDMONT     },
  { country: 'IT', region: 'Piemonte',             ratings: PIEDMONT     },
];

// ── 3. Insert ratings ──────────────────────────────────────────────────────
// Map each 1-5 tier to a representative normalized-100 score that
// aligns with scoreToTier() thresholds in VintageHeatmap.tsx:
//   ≥95 → 5 Legendary  →  97
//   ≥90 → 4 Excellent  →  92
//   ≥82 → 3 Good       →  85
//   ≥70 → 2 Average    →  75
//   <70 → 1 Bad        →  60
const TIER_TO_NORM = { 5: 97, 4: 92, 3: 85, 2: 75, 1: 60 };

const insert = db.prepare(`
  INSERT OR REPLACE INTO fact_vintage_rating
    (country_code, region, subregion, color, vintage, source_key,
     score, scale, score_normalized_100, character_notes)
  VALUES (?, ?, NULL, 'all', ?, ?, ?, '/5', ?, NULL)
`);

let inserted = 0;
const tx = db.transaction(() => {
  for (const { country, region, ratings } of REGION_MAP) {
    for (const [yr, score] of Object.entries(ratings)) {
      const norm = TIER_TO_NORM[score];
      const r = insert.run(country, region, Number(yr), SOURCE_KEY, score, norm);
      inserted += r.changes;
    }
  }
});
tx();

console.log(`Done — inserted ${inserted} vintage rating rows.`);
const total = db.prepare("SELECT count(*) as n FROM fact_vintage_rating").get();
console.log(`Total in fact_vintage_rating: ${total.n}`);
db.close();
