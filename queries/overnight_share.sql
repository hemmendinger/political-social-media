-- Share of posts made overnight (00:00-05:59 ET).
SELECT
    SUM(CASE WHEN et_hour BETWEEN 0 AND 5 THEN 1 ELSE 0 END) AS overnight,
    COUNT(*) AS total,
    CAST(SUM(CASE WHEN et_hour BETWEEN 0 AND 5 THEN 1 ELSE 0 END) AS REAL) / NULLIF(COUNT(*), 0) AS share
FROM v_posts_et;
