-- Accounts Trump reblogs (ReTruths) most often.
SELECT reblog_of_acct AS account, COUNT(*) AS n
FROM v_posts_et
WHERE kind = 'reblog' AND reblog_of_acct IS NOT NULL
GROUP BY reblog_of_acct
ORDER BY n DESC, account ASC
LIMIT 10;
