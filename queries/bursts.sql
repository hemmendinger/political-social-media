-- Posts that landed within 10 minutes of the previous post (candidate burst members), using
-- LAG() to compute the gap from the prior post in time order.
WITH ordered AS (
    SELECT
        ts_id, created_at_et, kind, created_at_utc,
        LAG(created_at_utc) OVER (ORDER BY created_at_utc) AS prev_created_at_utc
    FROM v_posts_et
)
SELECT
    ts_id,
    created_at_et,
    kind,
    (julianday(created_at_utc) - julianday(prev_created_at_utc)) * 1440.0 AS gap_min
FROM ordered
WHERE prev_created_at_utc IS NOT NULL
  AND (julianday(created_at_utc) - julianday(prev_created_at_utc)) * 1440.0 <= 10
ORDER BY created_at_utc;
