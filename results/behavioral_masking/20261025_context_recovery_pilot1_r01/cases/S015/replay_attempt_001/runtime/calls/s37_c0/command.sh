cd /app && python - <<'PY'
path = 'bandit/cli/main.py'
src = open(path).read()

old = '''    try:
        b_conf = b_config.BanditConfig(config_file=args.config_file)
    except utils.ConfigError as e:
        LOG.error(e)
        sys.exit(2)

    if not args.targets:
        parser.print_usage()
        sys.exit(2)
'''
new = '''    try:
        b_conf = b_config.BanditConfig(config_file=args.config_file)
    except utils.ConfigError as e:
        LOG.error(e)
        sys.exit(2)

    # Resolve incremental analysis settings from the CLI and config file.
    incremental_enabled = args.incremental
    if incremental_enabled is None:
        incremental_enabled = bool(
            b_conf.get_option("incremental_analysis.enabled") or False
        )
    cache_dir = (
        args.cache_dir
        or b_conf.get_option("incremental_analysis.cache_directory")
        or ".bandit_cache"
    )
    expiry_days = b_conf.get_option(
        "incremental_analysis.cache_expiry_days"
    )
    if expiry_days is None:
        expiry_days = 30
    else:
        expiry_days = int(expiry_days)
    cache_size_limit = args.cache_size_limit

    if args.warm_cache:
        incremental_enabled = True

    if args.force_rescan and not incremental_enabled:
        LOG.warning("--force-rescan has no effect without --incremental")

    cache_action = (
        args.clear_cache
        or args.cache_summary
        or args.list_cached_files
        or args.prune_cache is not None
        or args.cache_stats
        or args.export_cache is not None
        or args.import_cache is not None
    )

    if not args.targets and not cache_action:
        parser.print_usage()
        sys.exit(2)

    if args.clear_cache:
        b_cache.clear_cache_dir(cache_dir)
        sys.exit(0)

    cache = None
    if (
        args.cache_summary
        or args.list_cached_files
        or args.prune_cache is not None
        or args.cache_stats
        or args.export_cache is not None
        or args.import_cache is not None
        or incremental_enabled
    ):
        cache = b_cache.BanditCache(
            cache_dir,
            cache_key=None,
            expiry_days=expiry_days,
            size_limit=cache_size_limit,
        )

    if args.cache_summary:
        print(f"Cached files: {len(cache.entries)}")
        sys.exit(0)

    if args.list_cached_files:
        for cached_path in cache.list_files():
            print(cached_path)
        sys.exit(0)

    if args.prune_cache is not None:
        cache.prune(args.prune_cache)
        sys.exit(0)

    if args.cache_stats:
        for key, value in cache.stats().items():
            print(f"{key}: {value}")
        sys.exit(0)

    if args.export_cache is not None:
        with open(args.export_cache, "w", encoding="utf-8") as f:
            cache.export(f)
        sys.exit(0)

    if args.import_cache is not None:
        cache.import_cache(args.import_cache)
        sys.exit(0)
'''
assert old in src
src = src.replace(old, new, 1)
open(path, 'w').write(src)
PY
python -m py_compile bandit/cli/main.py && echo OK