"""Learn executable lexical edits from pairs of existing literal values.

Strings are token sequences, not protocol records or embedded-language ASTs.
Unchanged word/number positions are holes; punctuation remains literal. An edit
is a proposal only: neither syntactic matching nor a numeric offset establishes
oracle preservation. No project, library, key code, or defect-specific rule is
used here.
"""
from __future__ import annotations

from dataclasses import dataclass
import difflib
import hashlib
import json
import re

TOKEN = re.compile(r"[0-9]+|[^\W\d]+|\s+|[^\w\s]", re.UNICODE)


def tokens(text: str) -> tuple[str, ...]:
    pieces = tuple(TOKEN.findall(text))
    if "".join(pieces) != text:
        # Underscores and unusual numeric categories are still literal tokens.
        pieces = tuple(re.findall(r"[0-9]+|[^\W\d]+|\s+|.", text, re.DOTALL))
    if "".join(pieces) != text:
        raise ValueError("Tokenizer did not preserve source")
    return pieces


def token_sort(value: str) -> str:
    if re.fullmatch(r"[0-9]+", value):
        return "decimal"
    if value.isidentifier():
        return "word"
    return "literal"


@dataclass(frozen=True)
class LiteralEdit:
    before: tuple[str, ...]
    after: tuple[str, ...]
    # (tag, original start/end, donor start/end), including unchanged runs.
    alignment: tuple[tuple[str, int, int, int, int], ...]
    mode: str = "literal"

    @property
    def changed_positions(self) -> frozenset[int]:
        return frozenset(i for tag, a, b, _, _ in self.alignment if tag != "equal" for i in range(a, b))

    @property
    def edit_size(self) -> int:
        return sum(max(b - a, d - c) for tag, a, b, c, d in self.alignment if tag != "equal")

    def pattern(self) -> tuple:
        changed = self.changed_positions
        # Repeated unchanged tokens share the same metavariable. This preserves
        # a demonstrated correlation rather than inventing independent holes.
        holes: dict[tuple[str, str], int] = {}
        ans = []
        for i, token in enumerate(self.before):
            sort = token_sort(token)
            numeric_edit = self.mode == "offset" and i in changed and sort == "decimal"
            if (i not in changed and sort != "literal") or numeric_edit:
                key = (sort, token)
                index = holes.setdefault(key, len(holes))
                ans.append(("hole", sort, index))
            else:
                ans.append(("literal", token))
        return tuple(ans)

    @property
    def fingerprint(self) -> str:
        operations = []
        for tag, a, b, c, d in self.alignment:
            if tag == "equal":
                operations.append(("copy", a, b))
            elif self.mode == "offset" and tag == "replace" and b - a == d - c == 1:
                operations.append(("offset", a, int(self.after[c]) - int(self.before[a])))
            else:
                operations.append((tag, a, b, self.after[c:d]))
        value = (self.pattern(), tuple(operations))
        return hashlib.sha256(repr(value).encode()).hexdigest()[:20]

    def apply(self, value: str) -> str | None:
        current = tokens(value)
        pattern = self.pattern()
        if len(current) != len(pattern):
            return None
        bindings = {}
        for expected, token in zip(pattern, current):
            if expected[0] == "literal":
                if token != expected[1]:
                    return None
            else:
                _, sort, identifier = expected
                if token_sort(token) != sort:
                    return None
                if identifier in bindings and bindings[identifier] != token:
                    return None
                bindings[identifier] = token
        out = []
        for tag, a, b, c, d in self.alignment:
            if tag == "equal":
                out.extend(current[a:b])
            elif self.mode == "offset" and tag == "replace" and b - a == d - c == 1:
                replacement = int(current[a]) + int(self.after[c]) - int(self.before[a])
                if replacement < 0:
                    return None
                out.append(str(replacement))
            elif tag != "delete":
                out.extend(self.after[c:d])
        result = "".join(out)
        return result if result != value else None

    def as_dict(self) -> dict:
        return {"before": list(self.before), "after": list(self.after),
                "alignment": [list(x) for x in self.alignment], "mode": self.mode,
                "fingerprint": self.fingerprint, "edit_size": self.edit_size}

    @classmethod
    def from_dict(cls, data: dict) -> "LiteralEdit":
        return cls(tuple(data["before"]), tuple(data["after"]),
                   tuple(tuple(x) for x in data["alignment"]), data["mode"])


def learn_literal_edits(before: str, after: str, *, max_tokens: int = 256,
                        max_changed_tokens: int = 12, max_regions: int = 2) -> list[LiteralEdit]:
    a, b = tokens(before), tokens(after)
    if not a or not b or a == b or max(len(a), len(b)) > max_tokens:
        return []
    alignment = tuple(difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes())
    changed = [x for x in alignment if x[0] != "equal"]
    if len(changed) > max_regions:
        return []
    size = sum(max(j - i, l - k) for _, i, j, k, l in changed)
    unchanged = sum(j - i for tag, i, j, _, _ in alignment if tag == "equal")
    if size > max_changed_tokens or unchanged < 2:
        return []
    edit = LiteralEdit(a, b, alignment)
    result = [edit]
    if all(tag == "replace" and j - i == l - k == 1
           and token_sort(a[i]) == token_sort(b[k]) == "decimal"
           for tag, i, j, k, l in changed):
        offset = LiteralEdit(a, b, alignment, "offset")
        # Integer arithmetic canonicalizes leading zeroes. Keep a numeric rule
        # only when it reproduces the demonstrated source spelling; the exact
        # literal edit remains available for formatted numeric fragments.
        if offset.apply(before) == after:
            result.append(offset)
    assert all(rule.apply(before) == after for rule in result)
    return result


def encode_literal(value: str, language: str, original: str = "") -> str:
    """Only language literal syntax, with no assumptions about the string's API."""
    if language == "python":
        return repr(value)
    if language == "go" and original.startswith("`") and "`" not in value:
        return "`" + value + "`"
    if language in {"go", "typescript"}:
        return json.dumps(value, ensure_ascii=False)
    raise ValueError("Unsupported language")
