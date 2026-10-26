cd /app && python - <<'EOF'
# utils.py
path = 'bandit/core/utils.py'
src = open(path).read()
old = '''def get_nosec(nosec_lines, context):
    for lineno in context["linerange"]:
        nosec = nosec_lines.get(lineno, None)
        if nosec is not None:
            return nosec
    return None
'''
new = '''def get_nosec(nosec_lines, context):
    """Get the suppression applicable to a context, if any.

    All suppressions applying to any line in the context's line range are
    combined.  A blanket suppression dominates any specific ones.

    :param nosec_lines: mapping of line number to Suppression
    :param context: context dict with a ``linerange``
    :return: a Suppression, or None if no suppression applies
    """
    from bandit.core import nosec

    suppressions = []
    for lineno in context["linerange"]:
        suppression = nosec_lines.get(lineno, None)
        if suppression is not None:
            suppressions.append(suppression)
    return nosec.combine_suppressions(suppressions)
'''
assert old in src
src = src.replace(old, new)
open(path, 'w').write(src)

# tester.py
path = 'bandit/core/tester.py'
src = open(path).read()
src = src.replace(
    "from bandit.core import constants\n",
    "from bandit.core import constants\nfrom bandit.core import nosec as b_nosec\n",
)
old = '''                    nosec_tests_to_skip = self._get_nosecs_from_contexts(
                        temp_context, test_result=result
                    )
'''
new = '''                    nosec_suppression = self._get_nosecs_from_contexts(
                        temp_context, test_result=result
                    )
'''
assert old in src
src = src.replace(old, new)

old = '''                    # don't skip the test if there was no nosec comment
                    if nosec_tests_to_skip is not None:
                        # If the set is empty then it means that nosec was
                        # used without test number -> update nosecs counter.
                        # If the test id is in the set of tests to skip,
                        # log and increment the skip by test count.
                        if not nosec_tests_to_skip:
                            LOG.debug("skipped, nosec without test number")
                            self.metrics.note_nosec()
                            continue
                        if result.test_id in nosec_tests_to_skip:
                            LOG.debug(
                                f"skipped, nosec for test {result.test_id}"
                            )
                            self.metrics.note_skipped_test()
                            continue
'''
new = '''                    # don't skip the test if there was no nosec comment
                    if nosec_suppression is not None:
                        # A blanket suppression means nosec was used without
                        # test number -> update nosecs counter.  Otherwise,
                        # if the test id is in the set of tests to skip, log
                        # and increment the skip by test count.
                        if nosec_suppression.is_blanket:
                            LOG.debug("skipped, nosec without test number")
                            self.metrics.note_nosec()
                            continue
                        if result.test_id in nosec_suppression.tests:
                            LOG.debug(
                                f"skipped, nosec for test {result.test_id}"
                            )
                            self.metrics.note_skipped_test()
                            continue
'''
assert old in src
src = src.replace(old, new)

old = '''                    nosec_tests_to_skip = self._get_nosecs_from_contexts(
                        temp_context
                    )
                    if (
                        nosec_tests_to_skip
                        and test._test_id in nosec_tests_to_skip
                    ):
'''
new = '''                    nosec_suppression = self._get_nosecs_from_contexts(
                        temp_context
                    )
                    if (
                        nosec_suppression is not None
                        and nosec_suppression.is_specific
                        and test._test_id in nosec_suppression.tests
                    ):
'''
assert old in src
src = src.replace(old, new)

old = '''    def _get_nosecs_from_contexts(self, context, test_result=None):
        """Use context and optional test result to get set of tests to skip.
        :param context: temp context
        :param test_result: optional test result
        :return: set of tests to skip for the line based on contexts
        """
        nosec_tests_to_skip = set()
        base_tests = (
            self.nosec_lines.get(test_result.lineno, None)
            if test_result
            else None
        )
        context_tests = utils.get_nosec(self.nosec_lines, context)

        # if both are none there were no comments
        # this is explicitly different from being empty.
        # empty set indicates blanket nosec comment without
        # individual test names or ids
        if base_tests is None and context_tests is None:
            nosec_tests_to_skip = None

        # combine tests from current line and context line
        if base_tests is not None:
            nosec_tests_to_skip.update(base_tests)
        if context_tests is not None:
            nosec_tests_to_skip.update(context_tests)

        return nosec_tests_to_skip
'''
new = '''    def _get_nosecs_from_contexts(self, context, test_result=None):
        """Use context and optional test result to get the suppression.

        :param context: temp context
        :param test_result: optional test result
        :return: Suppression for the finding, or None if no suppression
                 applies
        """
        suppressions = []
        if test_result:
            base = self.nosec_lines.get(test_result.lineno, None)
            if base is not None:
                suppressions.append(base)
        context_suppression = utils.get_nosec(self.nosec_lines, context)
        if context_suppression is not None:
            suppressions.append(context_suppression)
        return b_nosec.combine_suppressions(suppressions)
'''
assert old in src
src = src.replace(old, new)
open(path, 'w').write(src)
print("done")
EOF
python -c "import bandit.core.manager, bandit.core.tester, bandit.core.utils; print('imports ok')"