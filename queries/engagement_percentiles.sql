-- Approximate median and p90 favourites per post kind, from the latest engagement snapshot per
-- post (v_engagement_latest), using NTILE(100) as a percentile bucket (window functions, SQLite 3.37+).
WITH latest AS (
    SELECT p.kind, e.favourites
    FROM v_engagement_latest e
    JOIN v_posts_et p ON p.ts_id = e.ts_id
    WHERE e.favourites IS NOT NULL
),
ranked AS (
    SELECT kind, favourites, NTILE(100) OVER (PARTITION BY kind ORDER BY favourites) AS pct
    FROM latest
)
SELECT
    kind,
    COUNT(*) AS n,
    MIN(CASE WHEN pct >= 50 THEN favourites END) AS favourites_p50,
    MIN(CASE WHEN pct >= 90 THEN favourites END) AS favourites_p90
FROM ranked
GROUP BY kind;
