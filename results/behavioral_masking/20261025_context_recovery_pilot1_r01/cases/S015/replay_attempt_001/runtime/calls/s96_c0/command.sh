cd /app && git config user.email "bandit-dev@example.com" && git config user.name "Bandit Dev" && git commit -m "Add incremental analysis caching to Bandit

Implement an on-disk cache for Bandit's --incremental mode. Unchanged
files (and files whose imported dependencies have not changed) return
cached results instead of being rescanned. Dependency invalidation is
cycle-safe for circular imports.

New CLI options: --incremental/--no-incremental, --cache-dir,
--cache-size-limit, --clear-cache, --cache-summary, --force-rescan,
--warm-cache, --export-cache, --import-cache, --list-cached-files,
--prune-cache, and --cache-stats.

Config file support via incremental_analysis.enabled,
incremental_analysis.cache_directory, and
incremental_analysis.cache_expiry_days. Analysis options, profile name
and content, and config content are part of the cache key. JSON output
now includes cache_info and metrics include cache_hits/cache_misses.
Cache integrity is validated on load and corrupted entries are
discarded." && git log --oneline -3