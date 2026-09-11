-- Most-linked domains in link-preview cards.
SELECT card_domain AS domain, COUNT(*) AS n
FROM v_posts_et
WHERE card_domain IS NOT NULL AND card_domain != ''
GROUP BY card_domain
ORDER BY n DESC, domain ASC
LIMIT 10;
