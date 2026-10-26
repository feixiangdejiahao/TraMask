cd /app && python - <<'PY'
path = 'bandit/cli/main.py'
src = open(path).read()

old = '''    except (utils.ProfileNotFound, ValueError) as e:
        LOG.error(e)
        sys.exit(2)

    b_mgr = b_manager.BanditManager(
'''
new = '''    except (utils.ProfileNotFound, ValueError) as e:
        LOG.error(e)
        sys.exit(2)

    if cache is not None:
        cache.cache_key = b_cache.cache_key_from_parts(
            profile_name=args.profile,
            profile_include=sorted(profile.get("include") or []),
            profile_exclude=sorted(profile.get("exclude") or []),
            profile_blacklist=profile.get("blacklist") or {},
            cli_tests=args.tests,
            cli_skips=args.skips,
            severity=args.severity,
            confidence=args.confidence,
            ignore_nosec=args.ignore_nosec,
        )

    b_mgr = b_manager.BanditManager(
'''
assert old in src
src = src.replace(old, new, 1)

old2 = '''    # initiate execution of tests within Bandit Manager
    b_mgr.run_tests()
    LOG.debug(b_mgr.b_ma)
    LOG.debug(b_mgr.metrics)

    # trigger output of results by Bandit Manager
'''
new2 = '''    # initiate execution of tests within Bandit Manager
    b_mgr.run_tests(
        cache=cache if incremental_enabled else None,
        force_rescan=args.force_rescan and incremental_enabled,
    )
    LOG.debug(b_mgr.b_ma)
    LOG.debug(b_mgr.metrics)

    if args.warm_cache:
        sys.exit(0)

    # trigger output of results by Bandit Manager
'''
assert old2 in src
src = src.replace(old2, new2, 1)

open(path, 'w').write(src)
PY
python -m py_compile bandit/cli/main.py && echo OK