-- Post counts by Eastern-time hour of day (0-23), across all data.
SELECT et_hour, COUNT(*) AS n
FROM v_posts_et
GROUP BY et_hour
ORDER BY et_hour;
