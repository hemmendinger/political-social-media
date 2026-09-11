-- Deleted posts with lifetime (creation to confirmed-gone) and bounds window, newest first.
SELECT
    ts_id,
    created_at_et,
    kind,
    deleted_source,
    lifetime_min,
    deletion_window_min,
    substr(content_text, 1, 120) AS snippet
FROM v_deletions
ORDER BY created_at_utc DESC;
