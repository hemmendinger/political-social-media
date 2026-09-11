-- Longest gaps between consecutive posts, largest first.
WITH ordered AS (
    SELECT
        created_at_et,
        created_at_utc,
        LAG(created_at_utc) OVER (ORDER BY created_at_utc) AS prev_created_at_utc,
        LAG(created_at_et) OVER (ORDER BY created_at_utc) AS prev_created_at_et
    FROM v_posts_et
)
SELECT
    prev_created_at_et AS from_et,
    created_at_et AS to_et,
    (julianday(created_at_utc) - julianday(prev_created_at_utc)) * 1440.0 AS gap_min
FROM ordered
WHERE prev_created_at_utc IS NOT NULL
ORDER BY gap_min DESC
LIMIT 20;
