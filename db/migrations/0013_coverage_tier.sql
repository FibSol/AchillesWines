-- Add coverage_tier to dim_producer (notable / mid / long_tail)
ALTER TABLE dim_producer ADD COLUMN coverage_tier TEXT
  CHECK(coverage_tier IN ('notable', 'mid', 'long_tail'));

-- Populate: notable = has fact data; mid = has cuvées only; long_tail = skeleton
UPDATE dim_producer
SET coverage_tier = 'long_tail';

UPDATE dim_producer
SET coverage_tier = 'mid'
WHERE producer_key IN (
  SELECT DISTINCT producer_key FROM dim_wine
);

UPDATE dim_producer
SET coverage_tier = 'notable'
WHERE producer_key IN (
  SELECT DISTINCT dw.producer_key
  FROM dim_wine dw
  WHERE dw.wine_key IN (SELECT DISTINCT wine_key FROM fact_price)
     OR dw.wine_key IN (SELECT DISTINCT wine_key FROM fact_rating)
);
