cd /app && python - <<'PY'
path = 'bandit/cli/main.py'
src = open(path).read()

old = '''    parser.add_argument(
        "--exit-zero",
        action="store_true",
        dest="exit_zero",
        default=False,
        help="exit with 0, " "even with results found",
    )
    python_ver = sys.version.replace("\\n", "")
'''
new = '''    parser.add_argument(
        "--exit-zero",
        action="store_true",
        dest="exit_zero",
        default=False,
        help="exit with 0, " "even with results found",
    )
    parser.add_argument(
        "--incremental",
        dest="incremental",
        action="store_true",
        default=None,
        help="enable incremental analysis using cached results",
    )
    parser.add_argument(
        "--no-incremental",
        dest="incremental",
        action="store_false",
        help="disable incremental analysis (default)",
    )
    parser.add_argument(
        "--cache-dir",
        dest="cache_dir",
        action="store",
        default=None,
        help="directory to use for the incremental analysis cache",
    )
    parser.add_argument(
        "--cache-size-limit",
        dest="cache_size_limit",
        action="store",
        default=None,
        type=int,
        help="maximum size of the cache file in bytes",
    )
    parser.add_argument(
        "--clear-cache",
        dest="clear_cache",
        action="store_true",
        default=False,
        help="clear the cache directory and exit",
    )
    parser.add_argument(
        "--cache-summary",
        dest="cache_summary",
        action="store_true",
        default=False,
        help="print the number of files in the cache and exit",
    )
    parser.add_argument(
        "--force-rescan",
        dest="force_rescan",
        action="store_true",
        default=False,
        help="bypass cache lookups but still store results "
        "(requires --incremental)",
    )
    parser.add_argument(
        "--warm-cache",
        dest="warm_cache",
        action="store_true",
        default=False,
        help="pre-populate the cache without reporting issues",
    )
    parser.add_argument(
        "--export-cache",
        dest="export_cache",
        action="store",
        default=None,
        metavar="FILE",
        help="export the cache to a JSON file and exit",
    )
    parser.add_argument(
        "--import-cache",
        dest="import_cache",
        action="store",
        default=None,
        metavar="FILE",
        help="import and merge a cache from a JSON file and exit",
    )
    parser.add_argument(
        "--list-cached-files",
        dest="list_cached_files",
        action="store_true",
        default=False,
        help="list files in the cache, one per line, and exit",
    )
    parser.add_argument(
        "--prune-cache",
        dest="prune_cache",
        action="store",
        default=None,
        metavar="DAYS",
        type=int,
        help="remove cached entries older than DAYS days and exit",
    )
    parser.add_argument(
        "--cache-stats",
        dest="cache_stats",
        action="store_true",
        default=False,
        help="print cache statistics and exit",
    )
    python_ver = sys.version.replace("\\n", "")
'''
assert old in src
src = src.replace(old, new, 1)
open(path, 'w').write(src)
PY
python -m py_compile bandit/cli/main.py && echo OK