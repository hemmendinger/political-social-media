# Test fixtures

Real responses captured on 2026-09-11 (afternoon, America/New_York). Do not edit by hand. When a source changes its
markup, recapture the affected file with the URL below and update the tests that depend on it.

| File | Source URL | Notes |
|---|---|---|
| trumpstruth_listing_page1.html | https://www.trumpstruth.org/?sort=desc&per_page=100&removed=include | 100 cards, 5 `ReTruthed` (self-reposts), quote cards with a nested status, Next Page cursor link |
| trumpstruth_listing_2026-09-09_cursor.html | listing with cursor `2026-09-09 01:30:00`, per_page=25 | 25 cards; 5 `ReTruthed` indicators, all preceding the *same* reused target card (trumpstruth id 41640 / ts_id 117238282851088051, "The Failing New York Magazine..."), not 5 distinct repost cards -- ids 41652/41650/41648/41645 nearby are unrelated plain original cards with no ReTruthed indicator |
| trumpstruth_listing_2022_tail.html | listing with cursor `2022-03-01 00:00:00` | 1 card: the first post (2022-02-14) |
| trumpstruth_home.html | https://www.trumpstruth.org/ | 10 cards, Next Page cursor link |
| trumpstruth_status_41686_original_video.html | /statuses/41686 | original post with video, captions track, details table |
| trumpstruth_status_41678_quote.html | /statuses/41678 | quote post (nested status), image attachment |
| trumpstruth_status_41655_original_retruthed_target.html | /statuses/41655 | an original post that is later ReTruthed by its own author elsewhere (see the `retruthed`/`retruthed_by` cards on the listing fixtures) -- its own status page carries no reblog markup at all, so on its own it parses as a plain original post |
| trumpstruth_status_41641/41644/41646/41649_removed_reblog.html | /statuses/&lt;id&gt; | four removed self-reposts of 2026-09-08; details row `Removed from platform`, deletion banner |
| trumpstruth_search_removed_2026.html | /search?query=&removed=only&sort=date_desc&per_page=100&start_date=2026-01-01&end_date=2026-09-11 | 88 results, `search-result` items with `status__deleted-badge` |
| trumpstruth_search_removed_2026-09-07_to_11.html | same with per_page=25, 2026-09-07..11 | 4 results |
| trumpstruth_search_query_trump.html | /search?query=Trump&sort=date_desc&per_page=10&removed=include | 10 results with a result-count line |
| trumpstruth_stats.html | https://www.trumpstruth.org/stats | totals by kind, coverage dates |
| trumpstruth_feed.xml | https://www.trumpstruth.org/feed | RSS, 100 items, `truth:originalId` |
| trumpstruth_feed_dated_2025-12-01.xml | /feed?start_date=2025-12-01&end_date=2025-12-01 | 10 items (the feed caps dated queries at 10) |
| api_statuses_2026-09-04_to_09-11.json | https://truthsocial.com/api/v1/accounts/107780257626128497/statuses?limit=20&exclude_replies=false (+max_id pages) | 180 statuses: originals, quotes, reblogs (incl. one of MichaelCohen212), cards, media, account block |
| api_status_404.json | https://truthsocial.com/api/v1/statuses/117238345561593751 | body of the 404 for a deleted post |
| cnn_archive_sample.json | https://ix.cnn.io/data/truth-social/truth_archive.json | 420 rows: newest 400, the deleted self-repost 117238345561593751, oldest 20 |
