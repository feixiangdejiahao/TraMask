cd /app && cat > bandit/core/nosec.py <<'PYEOF'
#
# SPDX-License-Identifier: Apache-2.0
import ast
import fnmatch
import io
import logging
import re
import tokenize

from bandit.core import extension_loader

LOG = logging.getLogger(__name__)

# Matches any nosec directive in a comment.  Directives are matched
# case-insensitively.  The selector (everything after the directive keyword,
# up to the next '#') is captured separately.
_DIRECTIVE_PATTERN = re.compile(
    r"#\s*nosec(?P<directive>-(?:begin|end|next-line))?"
    r"(?P<selector>[^#]*)",
    re.IGNORECASE,
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9_*]+")

# A line consisting solely of these characters is skipped when locating the
# target statement of a # nosec-next-line directive.
_NEXT_LINE_SKIP_RE = re.compile(rb"^[\(\)\[\]\{\};.\s]*$")


class Suppression:
    """A resolved nosec suppression.

    A suppression is one of:

    * blanket -- suppress every test
    * specific -- suppress a specific set of tests
    * none -- the directive had no effect (e.g. the selector was ``none``)
    """

    __slots__ = ("_blanket", "_tests")

    def __init__(self, blanket=False, tests=None):
        self._blanket = blanket
        self._tests = tests

    @classmethod
    def blanket(cls):
        return cls(blanket=True, tests=set())

    @classmethod
    def none(cls):
        return cls(blanket=False, tests=None)

    @classmethod
    def specific(cls, tests):
        return cls(blanket=False, tests=set(tests))

    @property
    def is_blanket(self):
        return self._blanket

    @property
    def is_none(self):
        return not self._blanket and self._tests is None

    @property
    def is_specific(self):
        return not self._blanket and bool(self._tests)

    @property
    def tests(self):
        return self._tests

    def __bool__(self):
        return self.is_blanket or self.is_specific

    def __repr__(self):
        if self.is_blanket:
            return "<Suppression: blanket>"
        if self.is_none:
            return "<Suppression: none>"
        return "<Suppression: %r>" % (sorted(self._tests),)


class SelectorError(Exception):
    """Raised when a selector expression cannot be parsed."""


class Directive:
    """A parsed nosec directive from a comment."""

    __slots__ = ("type", "line", "suppression")

    def __init__(self, type_, line, suppression):
        self.type = type_  # "nosec", "begin", "end" or "next_line"
        self.line = line
        self.suppression = suppression


def _all_test_ids():
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


def _tokenize(text):
    tokens = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch in "|&!(),":
            tokens.append(("OP", ch))
            i += 1
        elif ch == "-":
            tokens.append(("OP", "-"))
            i += 1
        else:
            match = _TOKEN_RE.match(text, i)
            if not match:
                raise SelectorError(
                    "Unexpected character in selector: %r" % ch
                )
            tokens.append(("ATOM", match.group(0)))
            i = match.end()
    return tokens


class _SelectorParser:
    """Recursive descent parser for nosec selector expressions."""

    def __init__(self, tokens, enabled_tests):
        self.tokens = tokens
        self.pos = 0
        self.enabled_tests = set(enabled_tests)

    def peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return (None, None)

    def next(self):
        token = self.peek()
        self.pos += 1
        return token

    def parse(self):
        if not self.tokens:
            return set(self.enabled_tests)
        result = self._parse_union()
        if self.pos != len(self.tokens):
            raise SelectorError("Unexpected token after expression")
        return result

    def _parse_union(self):
        left = self._parse_intersection()
        while True:
            kind, value = self.peek()
            if kind == "OP" and value in ("|", ","):
                self.next()
                left |= self._parse_intersection()
            elif kind == "ATOM" or (kind == "OP" and value in ("(", "!")):
                # Adjacent tokens (separated by whitespace) are a union.
                left |= self._parse_intersection()
            else:
                break
        return left

    def _parse_intersection(self):
        left = self._parse_difference()
        while True:
            kind, value = self.peek()
            if kind == "OP" and value == "&":
                self.next()
                left &= self._parse_difference()
            else:
                break
        return left

    def _parse_difference(self):
        left = self._parse_primary()
        while True:
            kind, value = self.peek()
            if kind == "OP" and value == "-":
                self.next()
                left -= self._parse_primary()
            else:
                break
        return left

    def _parse_primary(self):
        kind, value = self.peek()
        if kind == "OP" and value == "!":
            self.next()
            return self.enabled_tests - self._parse_primary()
        if kind == "OP" and value == "(":
            self.next()
            result = self._parse_union()
            kind, value = self.peek()
            if not (kind == "OP" and value == ")"):
                raise SelectorError("Expected closing parenthesis")
            self.next()
            return result
        if kind == "ATOM":
            self.next()
            return _resolve_token(value, self.enabled_tests)
        raise SelectorError("Expected a token")


def _evaluate(tokens, enabled_tests):
    parser = _SelectorParser(tokens, enabled_tests)
    result = parser.parse()
    if result == set(enabled_tests):
        return Suppression.blanket()
    if not result:
        return Suppression.none()
    return Suppression.specific(result)


def _fallback_union(text, enabled_tests):
    """Parse an unparseable selector as a plain union of tokens."""
    result = set()
    for token in re.split(r"[\s,]+", text.strip()):
        if token:
            result.update(_resolve_token(token, enabled_tests))
    if result == set(enabled_tests):
        return Suppression.blanket()
    if not result:
        return Suppression.none()
    return Suppression.specific(result)


def _resolve_selector(text, enabled_tests, directive_type):
    """Resolve a selector string to a Suppression.

    :param text: selector text (without the directive keyword)
    :param enabled_tests: the set of currently enabled test IDs
    :param directive_type: "nosec", "begin" or "next_line"
    """
    if text is None or not text.strip():
        return Suppression.blanket()
    text = text.strip()
    if text.lower() == "all":
        return Suppression.blanket()
    if text.lower() == "none":
        return Suppression.none()

    try:
        suppression = _evaluate(_tokenize(text), enabled_tests)
    except SelectorError:
        suppression = _fallback_union(text, enabled_tests)

    # Backwards compatibility: historically ``# nosec <text>`` suppressed
    # every finding on the line when <text> was not a recognised test name
    # (for example ``# nosec (on the line)``).  Preserve that for plain
    # inline nosec comments whose selector is only unrecognised words, but
    # honour explicit ``none`` and set-operator expressions for the new
    # directives.
    if (
        directive_type == "nosec"
        and suppression.is_none
        and not any(char in text for char in "|&!-")
    ):
        return Suppression.blanket()
    return suppression


def parse_directives(comment, line, enabled_tests):
    """Parse all nosec directives found in a comment.

    :param comment: the full comment text
    :param line: 1-based line number of the comment
    :param enabled_tests: set of enabled test IDs
    :return: list of Directive objects
    """
    directives = []
    for match in _DIRECTIVE_PATTERN.finditer(comment):
        directive = match.group("directive")
        selector_text = match.group("selector").strip()
        if selector_text.startswith(":"):
            selector_text = selector_text[1:].strip()

        if directive == "-end":
            # Extra text after nosec-end is ignored.
            directives.append(Directive("end", line, Suppression.none()))
            continue

        if directive == "-begin":
            type_ = "begin"
        elif directive == "-next-line":
            type_ = "next_line"
        else:
            type_ = "nosec"

        suppression = _resolve_selector(
            selector_text, enabled_tests, type_
        )
        directives.append(Directive(type_, line, suppression))
    return directives


def combine_suppressions(suppressions):
    """Combine a list of suppressions into a single suppression.

    Blanket suppressions dominate specific ones.  Empty/none suppressions
    are ignored.
    """
    specific = set()
    has_blanket = False
    has_specific = False
    for suppression in suppressions:
        if suppression is None or suppression.is_none:
            continue
        if suppression.is_blanket:
            has_blanket = True
        elif suppression.is_specific:
            specific.update(suppression.tests)
            has_specific = True
    if has_blanket:
        return Suppression.blanket()
    if has_specific:
        return Suppression.specific(specific)
    return None


def _leading_whitespace(line):
    return len(line) - len(line.lstrip())


def _is_skippable_line(line):
    """Return True for lines skipped when locating a nosec-next-line target.

    Blank lines, comment-only lines, and lines containing only grouping
    tokens, semicolons, or ellipsis literals are skipped.
    """
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith(b"#"):
        return True
    return bool(_NEXT_LINE_SKIP_RE.fullmatch(stripped))


def _find_statement_at_line(tree, line):
    """Find the innermost statement node that contains the given line."""
    best = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):
            continue
        if not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
            continue
        if node.lineno <= line <= node.end_lineno:
            if best is None or (
                node.lineno > best.lineno
                or (
                    node.lineno == best.lineno
                    and node.end_lineno < best.end_lineno
                )
            ):
                best = node
    return best


def _next_statement_lines(lines, directive_line, tree):
    """Find the line numbers of the statement following a directive.

    :param lines: physical lines of the file (1-based indexing)
    :param directive_line: 1-based line of the directive
    :param tree: parsed AST (or None if parsing failed)
    :return: list of 1-based line numbers, or None
    """
    for index in range(directive_line, len(lines)):
        line_no = index + 1
        if _is_skippable_line(lines[index]):
            continue
        if tree is not None:
            statement = _find_statement_at_line(tree, line_no)
            if statement is not None:
                # If the line is a continuation of a statement that began
                # before the directive, it is not the next statement.
                if statement.lineno < directive_line + 1:
                    continue
                return list(
                    range(statement.lineno, statement.end_lineno + 1)
                )
        return [line_no]
    return None


def build_nosec_lines(data, enabled_tests):
    """Build a mapping of line number to Suppression from a file's source.

    :param data: file contents (bytes)
    :param enabled_tests: set of enabled test IDs
    :return: dict mapping 1-based line numbers to Suppression objects
    """
    lines = data.splitlines()
    directives_by_line = {}

    try:
        fdata = io.BytesIO(data)
        tokens = tokenize.tokenize(fdata.readline)
        for toktype, tokval, (lineno, _), _, _ in tokens:
            if toktype == tokenize.COMMENT:
                directives = parse_directives(tokval, lineno, enabled_tests)
                if directives:
                    directives_by_line.setdefault(lineno, []).extend(
                        directives
                    )
    except (tokenize.TokenError, IndentationError):
        pass

    try:
        tree = ast.parse(data)
    except SyntaxError:
        tree = None

    nosec_lines = {}
    active_regions = []  # stack of (indent, Suppression)

    for lineno in range(1, len(lines) + 1):
        line = lines[lineno - 1]
        stripped = line.strip()
        indent = _leading_whitespace(line)
        is_blank = not stripped

        # An indented region that is not explicitly ended ends when a later
        # line has smaller indentation.
        if not is_blank:
            while active_regions and active_regions[-1][0] > indent:
                active_regions.pop()

        directives = directives_by_line.get(lineno, [])

        # End directives close the most recently started active region
        # before the current line.
        for directive in directives:
            if directive.type == "end":
                if active_regions:
                    active_regions.pop()

        line_suppressions = [
            suppression for _, suppression in active_regions
        ]
        for directive in directives:
            if directive.type == "nosec":
                line_suppressions.append(directive.suppression)
        combined = combine_suppressions(line_suppressions)
        if combined is not None:
            nosec_lines[lineno] = combined

        # Begin directives take effect on the next line, and next-line
        # directives target the following statement.
        for directive in directives:
            if directive.type == "begin":
                active_regions.append((indent, directive.suppression))
            elif directive.type == "next_line":
                target_lines = _next_statement_lines(
                    lines, directive.line, tree
                )
                if target_lines is None:
                    continue
                for target in target_lines:
                    existing = nosec_lines.get(target)
                    new = combine_suppressions(
                        [existing, directive.suppression]
                    )
                    if new is not None:
                        nosec_lines[target] = new

    return nosec_lines
PYEOF
echo "created"; python -c "import bandit.core.nosec as n; print('import ok')"