-- Media item counts by type, plus how many posts carry no media at all.
SELECT type, COUNT(*) AS n
FROM media
GROUP BY type
UNION ALL
SELECT 'no_media_posts' AS type, COUNT(*) AS n
FROM v_posts_et
WHERE media_count = 0;
