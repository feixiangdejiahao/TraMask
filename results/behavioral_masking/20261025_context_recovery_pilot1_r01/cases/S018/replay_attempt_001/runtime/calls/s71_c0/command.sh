cd /app && python - <<'EOF'
path = 'bandit/core/nosec.py'
src = open(path).read()
old = '''def _all_test_ids():
    extman = extension_loader.MANAGER
    return (
        set(extman.plugins_by_id)
        | set(extman.blacklist_by_id)
        | set(extman.builtin)
    )


def _resolve_token(token, enabled_tests):
    """Resolve a single selector token to a set of test IDs."""
    lowered = token.lower()
    if lowered == "all":
        return set(enabled_tests)
    if lowered == "none":
        return set()

    extman = extension_loader.MANAGER
    if "*" in token:
        matched = {
            test_id
            for test_id in _all_test_ids()
            if fnmatch.fnmatchcase(test_id, token)
        }
        if not matched:
            LOG.warning(
                "Test in comment: %s is not a test id pattern, ignoring",
                token,
            )
        return matched

    if extman.check_id(token):
        return {token}
    test_id = extman.get_test_id(token)
    if test_id:
        return {test_id}
    LOG.warning(
        "Test in comment: %s is not a test name or id, ignoring", token
    )
    return set()
'''
new = '''def _resolve_token(token, enabled_tests):
    """Resolve a single selector token to a set of enabled test IDs."""
    enabled_tests = set(enabled_tests)
    lowered = token.lower()
    if lowered == "all":
        return set(enabled_tests)
    if lowered == "none":
        return set()

    extman = extension_loader.MANAGER
    if "*" in token:
        matched = {
            test_id
            for test_id in enabled_tests
            if fnmatch.fnmatchcase(test_id, token)
        }
        if not matched:
            LOG.warning(
                "Test in comment: %s is not a test id pattern, ignoring",
                token,
            )
        return matched

    if extman.check_id(token):
        return {token} & enabled_tests
    test_id = extman.get_test_id(token)
    if test_id:
        return {test_id} & enabled_tests
    LOG.warning(
        "Test in comment: %s is not a test name or id, ignoring", token
    )
    return set()
'''
assert old in src
src = src.replace(old, new)
open(path, 'w').write(src)
print("updated")
EOF
python -m testtools.run tests.unit.core.test_nosec 2>&1 | tail -10