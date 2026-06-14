-- Add coverage_tier to dim_producer (notable / mid / long_tail)
ALTER TABLE dim_producer ADD COLUMN coverage_tier TEXT
  CHECK(coverage_tier IN ('notable', 'mid', 'long_tail'));

-- Step 1: baseline = skeleton
UPDATE dim_producer SET coverage_tier = 'long_tail';

-- Step 2: has cuvées → mid
UPDATE dim_producer
SET coverage_tier = 'mid'
WHERE producer_key IN (
  SELECT DISTINCT producer_key FROM dim_wine
);

-- Step 3: has scraped prices or ratings → notable
UPDATE dim_producer
SET coverage_tier = 'notable'
WHERE producer_key IN (
  SELECT DISTINCT dw.producer_key
  FROM dim_wine dw
  WHERE dw.wine_key IN (SELECT DISTINCT wine_key FROM fact_price)
     OR dw.wine_key IN (SELECT DISTINCT wine_key FROM fact_rating)
);

-- Step 4: prestige override — tier=1 (iconic) is always notable regardless of scraped data
UPDATE dim_producer SET coverage_tier = 'notable' WHERE tier = 1;

-- Step 5: prestige floor — tier=2 (very good) is at least mid, never long_tail
UPDATE dim_producer
SET coverage_tier = 'mid'
WHERE tier = 2 AND coverage_tier = 'long_tail';

-- Step 6: sanitise any tier > 3 (import artefacts) down to 3
UPDATE dim_producer SET tier = 3 WHERE tier > 3;
