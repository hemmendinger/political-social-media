-- Posts per ET calendar day, split by kind, plus how many of that day's posts were later found deleted.
SELECT
    et_date,
    SUM(CASE WHEN kind = 'original' THEN 1 ELSE 0 END) AS original,
    SUM(CASE WHEN kind = 'quote' THEN 1 ELSE 0 END) AS quote,
    SUM(CASE WHEN kind = 'reblog' THEN 1 ELSE 0 END) AS reblog,
    SUM(CASE WHEN kind = 'reply' THEN 1 ELSE 0 END) AS reply,
    COUNT(*) AS total,
    SUM(is_deleted) AS deleted
FROM v_posts_et
GROUP BY et_date
ORDER BY et_date;
