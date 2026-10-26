cd /app && python - <<'PY'
path = 'bandit/cli/main.py'
src = open(path).read()
old = '''        cache.cache_key = b_cache.cache_key_from_parts(
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
'''
new = '''        cache.cache_key = b_cache.cache_key_from_parts(
            config_data=b_conf.config,
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
'''
assert old in src
src = src.replace(old, new, 1)
open(path, 'w').write(src)
PY
python -m py_compile bandit/cli/main.py && echo OK