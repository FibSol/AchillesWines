-- Add 14 wine shop + wine press sources discovered 2026-05-22.
-- All gated behind a login → requires_auth=1 so they appear on /admin/auth.
-- Credentials go in .env using the pattern ACHILLES_AUTH_<SOURCE_CODE>_USERNAME / _PASSWORD.
-- The actual scraper for each is still to be implemented (see NEXT.md Sprint 5).

INSERT OR IGNORE INTO `dim_source`
  (`source_code`, `source_name`, `source_tier`, `cadence`, `country_code`,
   `base_url`, `license_class`, `enabled`, `requires_auth`, `notes`)
VALUES
  -- ============================== Wine shops ==============================
  ('wine_searcher',          'Wine-Searcher',         'B_retailer_major', 'monthly',  NULL,
   'https://www.wine-searcher.com',         'public_check_terms', 1, 1,
   'Global aggregator; auth required for prices beyond preview.'),
  ('cavissima_be',           'Cavissima (BE)',        'B_retailer_major', 'monthly',  'BE',
   'https://www.cavissima.be',              'public_check_terms', 1, 1,
   'Belgian variant of cavissima — separate inventory + pricing from FR.'),
  ('ventealapropriete',      'Vente à la Propriété',  'B_retailer_major', 'monthly',  'FR',
   'https://www.ventealapropriete.com',     'public_check_terms', 1, 1,
   'Flash sales platform — prices may swing fast.'),
  ('hachette_vins_shop',     'Hachette Vins (shop)',  'B_retailer_major', 'monthly',  'FR',
   'https://www.hachette-vins.shop',        'public_check_terms', 1, 1,
   'E-commerce arm of the Hachette wine guide.'),
  ('comptoir_des_millesimes','Comptoir des Millésimes','B_retailer_major','monthly',  'FR',
   'https://www.comptoirdesmillesimes.com', 'public_check_terms', 1, 1, NULL),
  ('topwijnen_be',           'Topwijnen (BE)',        'B_retailer_major', 'monthly',  'BE',
   'https://www.topwijnen.be',              'public_check_terms', 1, 1, NULL),
  ('millesima_be',           'Millesima (BE)',        'B_retailer_major', 'monthly',  'BE',
   'https://www.millesima.be',              'public_check_terms', 1, 1,
   'Belgian variant of millesima — separate stock + EUR/BE shipping.'),
  ('vinsbrunin',             'Vins Brunin',           'B_retailer_major', 'monthly',  'FR',
   'https://www.vinsbrunin.com',            'public_check_terms', 1, 1, NULL),
  ('wijnendeclerck_be',      'Wijnen De Clerck (BE)', 'B_retailer_major', 'monthly',  'BE',
   'https://webshop.wijnendeclerck.be',     'public_check_terms', 1, 1, NULL),
  ('belgiumwinewatchers',    'Belgium Wine Watchers', 'B_retailer_major', 'monthly',  'BE',
   'https://www.belgiumwinewatchers.com',   'public_check_terms', 1, 1, NULL),

  -- ============================== Wine press ==============================
  ('magazines_fr',           'Magazines.fr (aggregateur)','E_press_critic','monthly','FR',
   'https://www.magazines.fr',              'public_check_terms', 1, 1,
   'Aggregator giving access to multiple subscription magazines.'),
  ('figaro_vin',             'Le Figaro — Avis Vins', 'E_press_critic',  'monthly',  'FR',
   'https://avis-vin.lefigaro.fr',          'public_check_terms', 1, 1, NULL),
  ('terredevins',            'Terre de Vins',         'E_press_critic',  'monthly',  'FR',
   'https://www.terredevins.com',           'public_check_terms', 1, 1, NULL),
  ('hachette_vins',          'Hachette Vins (guide)', 'E_press_critic',  'monthly',  'FR',
   'https://www.hachette-vins.com',         'public_check_terms', 1, 1,
   'Hachette wine guide ratings/reviews.');
