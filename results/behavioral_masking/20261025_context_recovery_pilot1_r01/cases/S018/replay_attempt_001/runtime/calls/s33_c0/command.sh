cd /app && python - <<'EOF'
import re
path = 'bandit/core/manager.py'
src = open(path).read()

# Add import
src = src.replace(
    "from bandit.core import metrics\n",
    "from bandit.core import metrics\nfrom bandit.core import nosec\n",
)

# Replace the tokenize block in _parse_file
old = '''            # nosec_lines is a dict of line number -> set of tests to ignore
            #                                         for the line
            nosec_lines = dict()
            try:
                fdata.seek(0)
                tokens = tokenize.tokenize(fdata.readline)

                if not self.ignore_nosec:
                    for toktype, tokval, (lineno, _), _, _ in tokens:
                        if toktype == tokenize.COMMENT:
                            nosec_lines[lineno] = _parse_nosec_comment(tokval)

            except tokenize.TokenError:
                pass
'''
new = '''            # nosec_lines is a dict of line number -> suppression for the line
            nosec_lines = dict()
            if not self.ignore_nosec:
                enabled_tests = self._get_enabled_tests()
                nosec_lines = nosec.build_nosec_lines(data, enabled_tests)
'''
assert old in src, "old block not found"
src = src.replace(old, new)

# Add _get_enabled_tests method to BanditManager before _execute_ast_visitor
marker = "    def _execute_ast_visitor(self, fname, fdata, data, nosec_lines):\n"
method = '''    def _get_enabled_tests(self):
        """Return the set of test IDs currently enabled for this manager."""
        enabled = set()
        for plugin in self.b_ts.plugins:
            if (
                hasattr(plugin.plugin, "_config")
                and plugin.plugin._test_id == "B001"
            ):
                for tests in plugin.plugin._config.values():
                    enabled.update(t["id"] for t in tests)
            else:
                enabled.add(plugin.plugin._test_id)
        return enabled

'''
assert marker in src
src = src.replace(marker, method + marker)

# Remove obsolete _parse_nosec_comment and helpers
old_funcs = '''
def _find_test_id_from_nosec_string(extman, match):
    test_id = extman.check_id(match)
    if test_id:
        return match
    # Finding by short_id didn't work, let's check the test name
    test_id = extman.get_test_id(match)
    if not test_id:
        # Name and short id didn't work:
        LOG.warning(
            "Test in comment: %s is not a test name or id, ignoring", match
        )
    return test_id  # We want to return None or the string here regardless


def _parse_nosec_comment(comment):
    found_no_sec_comment = NOSEC_COMMENT.search(comment)
    if not found_no_sec_comment:
        # there was no nosec comment
        return None

    matches = found_no_sec_comment.groupdict()
    nosec_tests = matches.get("tests", set())

    # empty set indicates that there was a nosec comment without specific
    # test ids or names
    test_ids = set()
    if nosec_tests:
        extman = extension_loader.MANAGER
        # lookup tests by short code or name
        for test in NOSEC_COMMENT_TESTS.finditer(nosec_tests):
            test_match = test.group(1)
            test_id = _find_test_id_from_nosec_string(extman, test_match)
            if test_id:
                test_ids.add(test_id)

    return test_ids
'''
assert old_funcs in src, "old funcs not found"
src = src.replace(old_funcs, "\n")

# Remove obsolete regex constants
src = src.replace('NOSEC_COMMENT = re.compile(r"#\\s*nosec:?\\s*(?P<tests>[^#]+)?#?")\nNOSEC_COMMENT_TESTS = re.compile(r"(?:(B\\d+|[a-z\\d_]+),?)+", re.IGNORECASE)\n', '')

open(path, 'w').write(src)
print("done")
EOF
grep -n 'NOSEC_COMMENT\|_parse_nosec\|_find_test_id\|nosec\.\|_get_enabled_tests' bandit/core/manager.py | head -30