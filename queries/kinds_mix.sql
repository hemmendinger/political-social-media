-- Overall mix of post kinds (original/quote/reblog/reply) and how many of each are deleted.
SELECT kind, COUNT(*) AS n, SUM(is_deleted) AS deleted
FROM v_posts_et
GROUP BY kind
ORDER BY n DESC;
