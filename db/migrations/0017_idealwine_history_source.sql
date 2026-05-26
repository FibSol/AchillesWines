-- Migration 0017: idealwine_history dim_source row
-- Registers the iDealwine historical auction results scraper (past sold lots).
-- Separate from idealwine_auctions (live/active lots) so hammer prices from
-- the archive do not inflate current market-price estimates.

INSERT OR IGNORE INTO dim_source
    (source_code, source_name, source_tier, country_code, base_url,
     license_class, cadence, enabled, requires_auth, notes)
VALUES
    ('idealwine_history',
     'iDealwine Historical Auction Results',
     'B_retailer',
     'FR',
     'https://www.idealwine.com',
     'public_check_terms',
     'monthly',
     1,
     1,
     'Past auction sold-lot results archive — hammer prices for old vintages (pre-2010). '
     'Separate from idealwine_auctions (live lots). '
     'Shares JWT credentials with idealwine source_code (ACHILLES_AUTH_IDEALWINE_*).');
