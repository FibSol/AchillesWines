/**
 * Achilles's Wines — Canonical schema
 * Owner: Hector (Solution Architect) · Validated by: Cassandra (Data Steward)
 *
 * Conventions:
 *  - All natural keys are TEXT and normalized (see docs/NOMENCLATURE.md).
 *  - wine_key is sha1(producer_norm|cuvee_norm|vintage_or_NV|appellation_norm|bottle_ml)[:16]
 *  - All fact rows carry: source_key, source_url, content_hash, batch_id (provenance).
 *  - All money is local + EUR + USD (FX captured at record_date).
 *  - Closed enums enforced by CHECK constraints (not enum types — SQLite limitation).
 */

import { sql } from "drizzle-orm";
import {
  sqliteTable,
  text,
  integer,
  real,
  primaryKey,
  index,
  uniqueIndex,
  check,
} from "drizzle-orm/sqlite-core";

/* ============================================================================
 * DIMENSION TABLES
 * ========================================================================== */

/** Sources we ingest from (tier A/B/C/D/E/F). */
export const dimSource = sqliteTable(
  "dim_source",
  {
    sourceKey: integer("source_key").primaryKey({ autoIncrement: true }),
    sourceCode: text("source_code").notNull().unique(),
    sourceName: text("source_name").notNull(),
    sourceTier: text("source_tier", {
      enum: [
        "A_official",
        "B_retailer_major",
        "C_retailer_minor",
        "D_user_aggregate",
        "E_press_critic",
        "F_vintage_authority",
      ],
    }).notNull(),
    countryCode: text("country_code"),
    baseUrl: text("base_url"),
    licenseClass: text("license_class").notNull().default("public_check_terms"),
    cadence: text("cadence", {
      enum: ["one_shot", "weekly", "monthly", "annual", "on_demand"],
    }).notNull(),
    enabled: integer("enabled", { mode: "boolean" }).notNull().default(true),
    /** True when scraping this source requires authenticated session
     * (form login). Credentials come from ACHILLES_AUTH_<source>_USERNAME /
     * _PASSWORD env vars — see scraper/achilles_scraper/auth.py and ADR-010.
     */
    requiresAuth: integer("requires_auth", { mode: "boolean" }).notNull().default(false),
    lastSuccessAt: integer("last_success_at", { mode: "timestamp" }),
    notes: text("notes"),
    /** Optimal --limit value as determined by `achilles-scraper benchmark`. */
    recommendedBatchSize: integer("recommended_batch_size"),
    /** Unix timestamp of the last benchmark run. */
    lastBenchmarkAt: integer("last_benchmark_at"),
    /** Success rate (0–1) at the recommended batch size from last benchmark. */
    benchmarkSuccessRate: real("benchmark_success_rate"),
    /** Human-readable notes from the last benchmark (JSON summary). */
    benchmarkNotes: text("benchmark_notes"),
    /** When 1, EmailNewsletterScraper will retry 0-offer emails via Claude Haiku
     * (LLM fallback parser). Opt-in only — keeps API costs predictable.
     * Requires ANTHROPIC_API_KEY in env; gracefully skipped if absent.
     */
    useLlmFallback: integer("use_llm_fallback").notNull().default(0),
  },
  (t) => ({
    tierIdx: index("idx_source_tier").on(t.sourceTier),
  })
);

/** Geographic hierarchy: country → region → subregion → appellation. */
export const dimAppellation = sqliteTable(
  "dim_appellation",
  {
    appellationKey: integer("appellation_key").primaryKey({ autoIncrement: true }),
    countryCode: text("country_code").notNull(),
    region: text("region").notNull(),
    subregion: text("subregion"),
    appellationName: text("appellation_name").notNull(),
    appellationNorm: text("appellation_norm").notNull(),
    level: text("level", {
      enum: ["regional", "village", "premier_cru", "grand_cru", "iconic"],
    }).notNull(),
    inaoCode: text("inao_code"),
    /** Optional GeoJSON polygon for map overlays. */
    geoPolygon: text("geo_polygon"),
    /** Lat/lon centroid for marker fallback. */
    latitude: real("latitude"),
    longitude: real("longitude"),
  },
  (t) => ({
    normIdx: uniqueIndex("idx_appellation_norm").on(t.countryCode, t.appellationNorm),
    regionIdx: index("idx_appellation_region").on(t.countryCode, t.region),
  })
);

/** Producers — domaines, châteaux, maisons, bodegas, casas. */
export const dimProducer = sqliteTable(
  "dim_producer",
  {
    producerKey: integer("producer_key").primaryKey({ autoIncrement: true }),
    producerName: text("producer_name").notNull(),
    producerNorm: text("producer_norm").notNull(),
    countryCode: text("country_code").notNull(),
    region: text("region"),
    subregion: text("subregion"),
    /** JSON array of appellation_norm strings the producer is authorized to make. */
    allowedAppellations: text("allowed_appellations", { mode: "json" })
      .$type<string[]>()
      .notNull()
      .default(sql`'[]'`),
    /** JSON array of name aliases for fuzzy matching. */
    aliases: text("aliases", { mode: "json" })
      .$type<string[]>()
      .notNull()
      .default(sql`'[]'`),
    website: text("website"),
    latitude: real("latitude"),
    longitude: real("longitude"),
    tier: integer("tier"),
    status: text("status", {
      enum: ["active", "pending_review", "deprecated"],
    }).notNull().default("active"),
    firstSeenAt: integer("first_seen_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
    lastSeenAt: integer("last_seen_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
    notes: text("notes"),
    coverageTier: text("coverage_tier", {
      enum: ["notable", "mid", "long_tail"],
    }),
  },
  (t) => ({
    normIdx: uniqueIndex("idx_producer_norm").on(t.producerNorm, t.countryCode),
    countryRegionIdx: index("idx_producer_country_region").on(t.countryCode, t.region),
    statusIdx: index("idx_producer_status").on(t.status),
  })
);

/** Grape varieties (cépages). */
export const dimVariety = sqliteTable(
  "dim_variety",
  {
    varietyKey: integer("variety_key").primaryKey({ autoIncrement: true }),
    varietyName: text("variety_name").notNull(),
    varietyNorm: text("variety_norm").notNull().unique(),
    colorFamily: text("color_family", {
      enum: ["red", "white", "rosé", "other"],
    }).notNull(),
  }
);

/**
 * Canonical wine identity.
 * wine_key = sha1(producer_norm|cuvee_norm|vintage_or_NV|appellation_norm|bottle_ml)[:16]
 */
export const dimWine = sqliteTable(
  "dim_wine",
  {
    wineKey: text("wine_key").primaryKey(),
    producerKey: integer("producer_key")
      .notNull()
      .references(() => dimProducer.producerKey),
    appellationKey: integer("appellation_key")
      .notNull()
      .references(() => dimAppellation.appellationKey),
    cuveeName: text("cuvee_name").notNull(),
    cuveeNorm: text("cuvee_norm").notNull(),
    color: text("color", {
      enum: ["red", "white", "rosé", "sparkling", "sweet", "fortified", "orange"],
    }).notNull(),
    vintage: integer("vintage"),
    isNonVintage: integer("is_non_vintage", { mode: "boolean" })
      .notNull()
      .default(false),
    bottleMl: integer("bottle_ml").notNull().default(750),
    alcoholPct: real("alcohol_pct"),
    classification: text("classification"),
    canonicalName: text("canonical_name").notNull(),
    firstSeenAt: integer("first_seen_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
    lastSeenAt: integer("last_seen_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
  },
  (t) => ({
    producerIdx: index("idx_wine_producer").on(t.producerKey),
    appellationIdx: index("idx_wine_appellation").on(t.appellationKey),
    vintageIdx: index("idx_wine_vintage").on(t.vintage),
    colorIdx: index("idx_wine_color").on(t.color),
    vintageCheck: check(
      "chk_wine_vintage_or_nv",
      sql`(${t.isNonVintage} = 1 AND ${t.vintage} IS NULL) OR (${t.isNonVintage} = 0 AND ${t.vintage} IS NOT NULL)`,
    ),
  })
);

/** Many-to-many: wine ↔ variety with % composition. */
export const bridgeWineVariety = sqliteTable(
  "bridge_wine_variety",
  {
    wineKey: text("wine_key")
      .notNull()
      .references(() => dimWine.wineKey),
    varietyKey: integer("variety_key")
      .notNull()
      .references(() => dimVariety.varietyKey),
    sharePct: real("share_pct"),
    sourceConfidence: real("source_confidence"),
  },
  (t) => ({
    pk: primaryKey({ columns: [t.wineKey, t.varietyKey] }),
  })
);

/* ============================================================================
 * FACT TABLES
 * ========================================================================== */

/** Observed prices (retail, auction, release). */
export const factPrice = sqliteTable(
  "fact_price",
  {
    priceEventKey: integer("price_event_key").primaryKey({ autoIncrement: true }),
    wineKey: text("wine_key")
      .notNull()
      .references(() => dimWine.wineKey),
    sourceKey: integer("source_key")
      .notNull()
      .references(() => dimSource.sourceKey),
    retailer: text("retailer"),
    recordedAt: integer("recorded_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
    priceKind: text("price_kind", {
      enum: ["retail_in_stock", "retail_oos", "release", "auction_hammer", "secondary"],
    }).notNull(),
    currencyCode: text("currency_code").notNull().default("EUR"),
    amountLocal: real("amount_local").notNull(),
    fxToEur: real("fx_to_eur"),
    amountEur: real("amount_eur"),
    inStock: integer("in_stock", { mode: "boolean" }),
    promoFlag: integer("promo_flag", { mode: "boolean" })
      .notNull()
      .default(false),
    /** % discount vs previous observed price for same (wine_key, retailer). */
    promoDeltaPct: real("promo_delta_pct"),
    sourceUrl: text("source_url"),
    contentHash: text("content_hash"),
    batchId: text("batch_id").notNull(),
  },
  (t) => ({
    wineIdx: index("idx_price_wine").on(t.wineKey),
    recordedIdx: index("idx_price_recorded").on(t.recordedAt),
    wineRetailerIdx: index("idx_price_wine_retailer").on(t.wineKey, t.retailer),
    promoIdx: index("idx_price_promo").on(t.promoFlag, t.recordedAt),
    amountCheck: check("chk_price_positive", sql`${t.amountLocal} > 0`),
  })
);

/** Ratings from critics and aggregated user sources. */
export const factRating = sqliteTable(
  "fact_rating",
  {
    ratingEventKey: integer("rating_event_key").primaryKey({ autoIncrement: true }),
    wineKey: text("wine_key")
      .notNull()
      .references(() => dimWine.wineKey),
    sourceKey: integer("source_key")
      .notNull()
      .references(() => dimSource.sourceKey),
    criticCode: text("critic_code", {
      enum: ["WA", "Vinous", "BH", "JMIB", "RVF", "Decanter", "JS", "JG", "JD", "WS", "Hachette", "CT", "XW", "WE", "VI", "SM"],
    }).notNull(),
    reviewerType: text("reviewer_type", {
      enum: ["critic", "user_aggregate"],
    }).notNull(),
    score: real("score").notNull(),
    scale: text("scale", {
      enum: ["/100", "/20", "/5", "stars"],
    }).notNull(),
    /** Score normalized to /100 for cross-source comparison. */
    scoreNormalized100: real("score_normalized_100").notNull(),
    ratingCount: integer("rating_count"),
    recordedAt: integer("recorded_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
    sourceUrl: text("source_url"),
    contentHash: text("content_hash"),
    batchId: text("batch_id").notNull(),
  },
  (t) => ({
    wineIdx: index("idx_rating_wine").on(t.wineKey),
    criticIdx: index("idx_rating_critic").on(t.criticCode),
    wineCriticIdx: index("idx_rating_wine_critic").on(t.wineKey, t.criticCode),
    scoreCheck: check(
      "chk_rating_normalized_range",
      sql`${t.scoreNormalized100} BETWEEN 0 AND 100`,
    ),
  })
);

/** Vintage ratings by region/subregion/color (annual). */
export const factVintageRating = sqliteTable(
  "fact_vintage_rating",
  {
    vintageRatingKey: integer("vintage_rating_key").primaryKey({ autoIncrement: true }),
    countryCode: text("country_code").notNull(),
    region: text("region").notNull(),
    subregion: text("subregion"),
    color: text("color", {
      enum: ["red", "white", "rosé", "sparkling", "sweet", "fortified", "all"],
    }).notNull(),
    vintage: integer("vintage").notNull(),
    sourceKey: integer("source_key")
      .notNull()
      .references(() => dimSource.sourceKey),
    score: real("score").notNull(),
    scale: text("scale", { enum: ["/100", "/20", "/5"] }).notNull(),
    scoreNormalized100: real("score_normalized_100").notNull(),
    characterNotes: text("character_notes"),
    sourceUrl: text("source_url"),
    recordedAt: integer("recorded_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
  },
  (t) => ({
    regionVintageIdx: index("idx_vintage_region").on(t.countryCode, t.region, t.vintage),
    uniqIdx: uniqueIndex("idx_vintage_unique").on(
      t.countryCode,
      t.region,
      t.subregion,
      t.color,
      t.vintage,
      t.sourceKey,
    ),
  })
);

/* ============================================================================
 * MARKET & SUPPLY REFERENCE (official statistical sources)
 * ========================================================================== */

/**
 * WERC Global Wine Markets megafile — selected metrics in narrow EAV format.
 * Covers vine area ('000 ha) and wine production (KL) from 1835 to 2024.
 * Source: https://economics.adelaide.edu.au/wine-economics/databases
 */
export const factWercStats = sqliteTable(
  "fact_werc_stats",
  {
    statId: integer("stat_id").primaryKey({ autoIncrement: true }),
    sourceKey: integer("source_key")
      .notNull()
      .references(() => dimSource.sourceKey),
    countryCode: text("country_code").notNull(),
    year: integer("year").notNull(),
    /** e.g. 'vine_area_kha' | 'wine_production_kl' */
    metric: text("metric").notNull(),
    value: real("value").notNull(),
    unit: text("unit").notNull(),
    batchId: text("batch_id").notNull(),
    createdAt: integer("created_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
  },
  (t) => ({
    uniqueRow: uniqueIndex("idx_werc_unique").on(t.countryCode, t.year, t.metric),
    countryYearIdx: index("idx_werc_country_year").on(t.countryCode, t.year),
    metricIdx: index("idx_werc_metric").on(t.metric),
  })
);

/** EU bulk wine market prices — EC Agri-food API (weekly, €/HL per category). */
export const factMarketIndex = sqliteTable(
  "fact_market_index",
  {
    marketIndexId: integer("market_index_id").primaryKey({ autoIncrement: true }),
    sourceKey: integer("source_key")
      .notNull()
      .references(() => dimSource.sourceKey),
    countryCode: text("country_code").notNull(),
    wineCategory: text("wine_category").notNull(),
    priceEurHl: real("price_eur_hl").notNull(),
    weekBeginDate: text("week_begin_date").notNull(),
    weekEndDate: text("week_end_date").notNull(),
    batchId: text("batch_id").notNull(),
    createdAt: integer("created_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
  },
  (t) => ({
    countryDateIdx: index("idx_market_country_date").on(t.countryCode, t.weekBeginDate),
    categoryIdx: index("idx_market_category").on(t.wineCategory),
    uniqueRow: uniqueIndex("idx_market_unique").on(
      t.sourceKey, t.countryCode, t.wineCategory, t.weekBeginDate,
    ),
  })
);

/** Annual grape harvest volumes — Eurostat tag00121 (1 000 tonnes by country). */
export const factHarvestVolume = sqliteTable(
  "fact_harvest_volume",
  {
    harvestId: integer("harvest_id").primaryKey({ autoIncrement: true }),
    sourceKey: integer("source_key")
      .notNull()
      .references(() => dimSource.sourceKey),
    countryCode: text("country_code").notNull(),
    year: integer("year").notNull(),
    cropType: text("crop_type", {
      enum: ["all_grapes", "wine_grapes", "table_grapes", "raisin_grapes"],
    }).notNull(),
    volume1000Tonnes: real("volume_1000_tonnes").notNull(),
    batchId: text("batch_id").notNull(),
    createdAt: integer("created_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
  },
  (t) => ({
    countryYearIdx: index("idx_harvest_country_year").on(t.countryCode, t.year),
    uniqueRow: uniqueIndex("idx_harvest_unique").on(
      t.sourceKey, t.countryCode, t.year, t.cropType,
    ),
  })
);

/* ============================================================================
 * CELLAR (personal storage)
 * ========================================================================== */

/** 20 numbered storage locations, capacity 200 each. */
export const cellarLocations = sqliteTable(
  "cellar_locations",
  {
    locationId: integer("location_id").primaryKey(),
    name: text("name").notNull(),
    capacity: integer("capacity").notNull().default(200),
    description: text("description"),
    temperatureZone: text("temperature_zone", {
      enum: ["cellar", "fridge", "kitchen", "other"],
    }).notNull().default("cellar"),
  }
);

/** Bottles in cellar, aggregated by (wine_key, location). */
export const cellarInventory = sqliteTable(
  "cellar_inventory",
  {
    inventoryId: integer("inventory_id").primaryKey({ autoIncrement: true }),
    wineKey: text("wine_key")
      .notNull()
      .references(() => dimWine.wineKey),
    locationId: integer("location_id")
      .notNull()
      .references(() => cellarLocations.locationId),
    qty: integer("qty").notNull(),
    purchasePriceEur: real("purchase_price_eur"),
    purchaseDate: integer("purchase_date", { mode: "timestamp" }),
    purchaseSource: text("purchase_source"),
    notes: text("notes"),
    addedAt: integer("added_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
  },
  (t) => ({
    wineLocationIdx: uniqueIndex("idx_inventory_wine_location").on(t.wineKey, t.locationId),
    locationIdx: index("idx_inventory_location").on(t.locationId),
    qtyCheck: check("chk_inventory_qty_positive", sql`${t.qty} >= 0`),
  })
);

/** Consumption log (drank a bottle). */
export const cellarConsumption = sqliteTable(
  "cellar_consumption",
  {
    consumptionId: integer("consumption_id").primaryKey({ autoIncrement: true }),
    wineKey: text("wine_key")
      .notNull()
      .references(() => dimWine.wineKey),
    locationId: integer("location_id").references(() => cellarLocations.locationId),
    consumedAt: integer("consumed_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
    qty: integer("qty").notNull().default(1),
    personalScore: integer("personal_score"),
    occasion: text("occasion"),
    tastingNote: text("tasting_note"),
  },
  (t) => ({
    consumedIdx: index("idx_consumption_date").on(t.consumedAt),
    wineIdx: index("idx_consumption_wine").on(t.wineKey),
    scoreCheck: check(
      "chk_consumption_score_range",
      sql`${t.personalScore} IS NULL OR (${t.personalScore} BETWEEN 0 AND 100)`,
    ),
  })
);

/* ============================================================================
 * OPS — anti-hallucination & batch tracking
 * ========================================================================== */

/** Dead-letter queue: records that failed validation. */
export const opsDeadLetter = sqliteTable(
  "ops_dead_letter",
  {
    dlqId: integer("dlq_id").primaryKey({ autoIncrement: true }),
    sourceKey: integer("source_key").references(() => dimSource.sourceKey),
    batchId: text("batch_id").notNull(),
    errorClass: text("error_class", {
      enum: [
        "parse_error",
        "schema_drift",
        "auth_error",
        "validation_error",
        "region_gate",
        "critic_enum",
        "multi_source_rule",
        "reconcile_error",
        "fx_missing",
        "network_error",
        "unresolved_dim",
        "unmatched_wine",
        "scraper_not_applicable",
        "source_dead",
      ],
    }).notNull(),
    errorMessage: text("error_message").notNull(),
    sourceRecordId: text("source_record_id"),
    rawRecord: text("raw_record", { mode: "json" }),
    rawObjectPath: text("raw_object_path"),
    createdAt: integer("created_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
    resolvedAt: integer("resolved_at", { mode: "timestamp" }),
    resolvedBy: text("resolved_by"),
    resolution: text("resolution", {
      enum: [
        "pending",
        "approved_manual",
        "blacklisted",
        "fixed_upstream",
        "ignored",
        "archived",
        "unresolvable",
        "auto_resolved",
        "invalid_data",
        "not_applicable",
        "insufficient_data",
        "section_header",
      ],
    }).notNull().default("pending"),
  },
  (t) => ({
    sourceIdx: index("idx_dlq_source").on(t.sourceKey),
    classIdx: index("idx_dlq_class").on(t.errorClass),
    resolutionIdx: index("idx_dlq_resolution").on(t.resolution, t.createdAt),
  })
);

/** Content-hash cache to avoid re-parsing unchanged pages. */
export const opsContentHashes = sqliteTable(
  "ops_content_hashes",
  {
    url: text("url").primaryKey(),
    sourceKey: integer("source_key").references(() => dimSource.sourceKey),
    lastHash: text("last_hash").notNull(),
    lastEtag: text("last_etag"),
    lastModifiedHttp: text("last_modified_http"),
    lastFetchedAt: integer("last_fetched_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
    lastChangedAt: integer("last_changed_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
    fetchCount: integer("fetch_count").notNull().default(1),
  }
);

/** Batch ingestion log: one row per scraper run. */
export const opsBatchLog = sqliteTable(
  "ops_batch_log",
  {
    batchId: text("batch_id").primaryKey(),
    sourceKey: integer("source_key").references(() => dimSource.sourceKey),
    startedAt: integer("started_at", { mode: "timestamp" }).notNull(),
    finishedAt: integer("finished_at", { mode: "timestamp" }),
    status: text("status", {
      enum: ["running", "success", "partial", "failed"],
    }).notNull().default("running"),
    rowsFetched: integer("rows_fetched").notNull().default(0),
    rowsInserted: integer("rows_inserted").notNull().default(0),
    rowsUpdated: integer("rows_updated").notNull().default(0),
    rowsDlq: integer("rows_dlq").notNull().default(0),
    rowsSkippedUnchanged: integer("rows_skipped_unchanged").notNull().default(0),
    notes: text("notes"),
  },
  (t) => ({
    sourceIdx: index("idx_batch_source").on(t.sourceKey, t.startedAt),
  })
);

/**
 * Staging area for price candidates that don't yet pass the tri-source rule.
 * Promoted to fact_price when ≥2 sources concord ±15%.
 */
export const stagingPriceCandidates = sqliteTable(
  "staging_price_candidates",
  {
    candidateId: integer("candidate_id").primaryKey({ autoIncrement: true }),
    wineKey: text("wine_key")
      .notNull()
      .references(() => dimWine.wineKey),
    sourceKey: integer("source_key")
      .notNull()
      .references(() => dimSource.sourceKey),
    retailer: text("retailer"),
    recordedAt: integer("recorded_at", { mode: "timestamp" }).notNull(),
    currencyCode: text("currency_code").notNull().default("EUR"),
    amountLocal: real("amount_local").notNull(),
    amountEur: real("amount_eur"),
    sourceUrl: text("source_url"),
    contentHash: text("content_hash"),
    batchId: text("batch_id").notNull(),
    needsReview: integer("needs_review", { mode: "boolean" })
      .notNull()
      .default(true),
    promotedToFactPriceKey: integer("promoted_to_fact_price_key"),
    promotedAt: integer("promoted_at", { mode: "timestamp" }),
  },
  (t) => ({
    wineIdx: index("idx_staging_price_wine").on(t.wineKey),
    reviewIdx: index("idx_staging_price_review").on(t.needsReview, t.recordedAt),
    // Prevent duplicate inserts: same product from same source with same content hash
    // Note: partial index (WHERE content_hash IS NOT NULL) is applied at DB level via migration
    dedupeIdx: uniqueIndex("uix_staging_wine_source_hash").on(
      t.wineKey, t.sourceKey, t.contentHash
    ),
  })
);

/**
 * Staging area for rating candidates that don't yet have ≥2 distinct
 * source_key values for their wine_key.  Mirrors fact_rating columns plus
 * needs_review and promotion tracking fields (analogous to
 * staging_price_candidates).  Promoted to fact_rating by promote_ratings().
 */
export const stagingRatingCandidates = sqliteTable(
  "staging_rating_candidates",
  {
    candidateId: integer("candidate_id").primaryKey({ autoIncrement: true }),
    wineKey: text("wine_key")
      .notNull()
      .references(() => dimWine.wineKey),
    sourceKey: integer("source_key")
      .notNull()
      .references(() => dimSource.sourceKey),
    criticCode: text("critic_code", {
      enum: ["WA", "Vinous", "BH", "JMIB", "RVF", "Decanter", "JS", "JG", "JD", "WS", "Hachette", "CT", "XW", "WE", "VI", "SM"],
    }).notNull(),
    reviewerType: text("reviewer_type", {
      enum: ["critic", "user_aggregate"],
    }).notNull(),
    score: real("score").notNull(),
    scale: text("scale", {
      enum: ["/100", "/20", "/5", "stars"],
    }).notNull(),
    /** Score normalized to /100 for cross-source comparison. */
    scoreNormalized100: real("score_normalized_100").notNull(),
    ratingCount: integer("rating_count"),
    recordedAt: integer("recorded_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
    sourceUrl: text("source_url"),
    contentHash: text("content_hash"),
    batchId: text("batch_id").notNull(),
    /** Set to 1 until the wine_key has ≥2 distinct source_key values. */
    needsReview: integer("needs_review", { mode: "boolean" })
      .notNull()
      .default(true),
    promotedToFactRatingKey: integer("promoted_to_fact_rating_key"),
    promotedAt: integer("promoted_at", { mode: "timestamp" }),
  },
  (t) => ({
    wineIdx: index("idx_staging_rating_wine").on(t.wineKey),
    reviewIdx: index("idx_staging_rating_review").on(t.needsReview, t.recordedAt),
    dedupeIdx: uniqueIndex("uix_staging_rating_wine_source_hash").on(
      t.wineKey, t.sourceKey, t.contentHash
    ),
    scoreCheck: check(
      "chk_staging_rating_normalized",
      sql`${t.scoreNormalized100} BETWEEN 0 AND 100`,
    ),
  })
);

/** Per-source cron schedules configured from the admin UI. */
export const opsScraperSchedule = sqliteTable(
  "ops_scraper_schedule",
  {
    /** Must match dim_source.source_code */
    sourceCode: text("source_code").primaryKey(),
    /** Standard 5-field cron expression (UTC). NULL = manual only. */
    cronExpr: text("cron_expr"),
    updatedAt: integer("updated_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
  }
);

/** Job queue for UI-triggered scrapers (ADR-006). */
export const opsJobQueue = sqliteTable(
  "ops_job_queue",
  {
    jobId: text("job_id").primaryKey(),
    sourceKey: integer("source_key").references(() => dimSource.sourceKey),
    requestedBy: text("requested_by").notNull().default("ui"),
    requestedAt: integer("requested_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
    status: text("status", {
      enum: ["queued", "running", "done", "failed", "cancelled"],
    })
      .notNull()
      .default("queued"),
    startedAt: integer("started_at", { mode: "timestamp" }),
    finishedAt: integer("finished_at", { mode: "timestamp" }),
    rowsFetched: integer("rows_fetched").notNull().default(0),
    rowsInserted: integer("rows_inserted").notNull().default(0),
    rowsDlq: integer("rows_dlq").notNull().default(0),
    errorMessage: text("error_message"),
    batchId: text("batch_id"),
    params: text("params", { mode: "json" }).$type<Record<string, unknown>>(),
  },
  (t) => ({
    statusIdx: index("idx_job_status").on(t.status, t.requestedAt),
    sourceIdx: index("idx_job_source").on(t.sourceKey),
  })
);

/** Auth session cache — stored JWT bearer tokens and cookie jars (#22, ADR-010 extension). */
export const opsAuthSessions = sqliteTable(
  "ops_auth_sessions",
  {
    sessionKey: integer("session_key").primaryKey({ autoIncrement: true }),
    /** Must match dim_source.source_code (or the _auth_source_code for shared-cred scrapers). */
    sourceCode: text("source_code").notNull().unique(),
    tokenType: text("token_type", {
      enum: ["cookie_jar", "jwt_bearer"],
    }).notNull(),
    /** JSON dict {name: value} — populated for cookie_jar sessions. */
    cookieJar: text("cookie_jar"),
    /** Raw JWT bearer token — populated for jwt_bearer sessions. */
    authToken: text("auth_token"),
    /** JSON dict of extra headers to inject (e.g. Authorization). */
    extraHeaders: text("extra_headers"),
    createdAt: integer("created_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
    /** Unix timestamp after which the session must not be used. NULL = use DEFAULT_SESSION_TTL_SECONDS. */
    expiresAt: integer("expires_at", { mode: "timestamp" }),
    lastUsedAt: integer("last_used_at", { mode: "timestamp" })
      .notNull()
      .default(sql`(unixepoch())`),
  },
  (t) => ({
    sourceIdx: index("idx_auth_session_source").on(t.sourceCode),
  })
);

/* ============================================================================
 * SIMILARITY
 * ========================================================================== */

/**
 * Pre-computed cosine similarity scores between wine feature vectors.
 * Populated by `achilles-scraper compute-similarity`.
 * Top-K=20 most similar wines per wine_key.
 */
export const wineSimilarity = sqliteTable(
  "wine_similarity",
  {
    wineKey: text("wine_key")
      .notNull()
      .references(() => dimWine.wineKey),
    similarWineKey: text("similar_wine_key")
      .notNull()
      .references(() => dimWine.wineKey),
    score: real("score").notNull(),
    computedAt: text("computed_at")
      .notNull()
      .default(sql`(datetime('now'))`),
  },
  (t) => ({
    pk: primaryKey({ columns: [t.wineKey, t.similarWineKey] }),
    scoreIdx: index("idx_wine_similarity_key").on(t.wineKey, t.score),
  })
);

/* ============================================================================
 * Exports
 * ========================================================================== */

export type Source = typeof dimSource.$inferSelect;
export type Producer = typeof dimProducer.$inferSelect;
export type Appellation = typeof dimAppellation.$inferSelect;
export type Wine = typeof dimWine.$inferSelect;
export type Price = typeof factPrice.$inferSelect;
export type Rating = typeof factRating.$inferSelect;
export type VintageRating = typeof factVintageRating.$inferSelect;
export type CellarLocation = typeof cellarLocations.$inferSelect;
export type CellarInventory = typeof cellarInventory.$inferSelect;
export type CellarConsumption = typeof cellarConsumption.$inferSelect;
export type DeadLetter = typeof opsDeadLetter.$inferSelect;
export type WineSimilarity = typeof wineSimilarity.$inferSelect;
export type JobQueue = typeof opsJobQueue.$inferSelect;
export type ScraperSchedule = typeof opsScraperSchedule.$inferSelect;
export type StagingRatingCandidate = typeof stagingRatingCandidates.$inferSelect;
export type MarketIndex = typeof factMarketIndex.$inferSelect;
export type HarvestVolume = typeof factHarvestVolume.$inferSelect;
export type WercStat = typeof factWercStats.$inferSelect;
