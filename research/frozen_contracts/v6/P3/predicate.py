def preserves(field, op, expected, source, followup):
    if op not in ("eq", "one_of", "contains"):
        return False

    sm = source["modifiers"] - 1
    fm = followup["modifiers"] - 1
    sk = source["key"]
    fk = followup["key"]
    sa = source["alternate"]
    fa = followup["alternate"]
    st = source["text"]
    ft = followup["text"]

    bits = {"shift": 1, "alt": 2, "ctrl": 4,
            "super": 8, "hyper": 16, "meta": 32}
    phases = {"1": "press", "2": "repeat", "3": "release"}

    # Event types apply to every supported trailer, not just Unicode keys.
    if field == "phase":
        value = phases[followup["phase"]]
    elif field in ("is_press", "is_repeat", "is_release"):
        wanted = {"is_press": "1", "is_repeat": "2", "is_release": "3"}
        value = followup["phase"] == wanted[field]
    elif field in bits:
        # Convenience properties project individual modifier bits.
        value = bool(fm & bits[field])
    elif field == "modifiers":
        if sm == fm:
            return True
        if op == "contains" and expected in bits:
            return bool(fm & bits[expected])
        # The issue specifies sorted names; lock-name spelling is unspecified.
        if fm & 192:
            return False
        names = []
        if fm & 1:
            names = names + ["shift"]
        if fm & 2:
            names = names + ["alt"]
        if fm & 4:
            names = names + ["ctrl"]
        if fm & 8:
            names = names + ["super"]
        if fm & 16:
            names = names + ["hyper"]
        if fm & 32:
            names = names + ["meta"]
        value = tuple(sorted(names))
    else:
        value = None

    if field in ("phase", "is_press", "is_repeat", "is_release",
                 "shift", "alt", "ctrl", "super", "hyper", "meta",
                 "modifiers"):
        if op == "eq":
            return value == expected
        if op == "one_of":
            return value in expected
        if field == "modifiers":
            return expected in value
        return False

    if field not in ("key", "character", "base_key", "shifted_key",
                     "base_layout_key", "aliases"):
        return False

    # Phase changes must not disturb other public key projections.
    if sk == fk and sm == fm and sa == fa and st == ft:
        return True

    szero = sk.endswith("u") and int(sk[:-1]) == 0
    fzero = fk.endswith("u") and int(fk[:-1]) == 0

    if field == "base_key":
        # Stable primary metadata survives text, alternates, and modifiers.
        if sk == fk and not fzero:
            return True
        # Unknown-key text supplies the base as well as key and character.
        if szero and fzero and st == ft and len(ft) > 0:
            return True
        if fzero and len(ft) == 1:
            value = chr(int(ft[0]))
            if op == "eq":
                return value == expected
            if op == "one_of":
                return value in expected
        return False

    if field in ("shifted_key", "base_layout_key"):
        index = 0
        if field == "base_layout_key":
            index = 1
        # Alternate metadata describes Unicode keys independently of phase,
        # modifiers, associated text, and the primary key.
        if len(sa) > index and len(fa) > index:
            if int(sa[index]) == int(fa[index]):
                return True
        elif len(sa) <= index and len(fa) <= index:
            return True
        if len(fa) <= index:
            if op == "eq":
                return expected is None
            if op == "one_of":
                return None in expected
        return False

    sc = None
    fc = None
    if sk.endswith("u"):
        number = int(sk[:-1])
        if 0 < number <= 1114111 and not 55296 <= number <= 63743:
            sc = chr(number)
    if fk.endswith("u"):
        number = int(fk[:-1])
        if 0 < number <= 1114111 and not 55296 <= number <= 63743:
            fc = chr(number)
    sp = sc is not None and sc.isprintable()
    fp = fc is not None and fc.isprintable()

    # Textual names, rather than literal punctuation, appear in shortcuts.
    punctuation = {
        " ": "space", "!": "exclamation_mark", '"': "quotation_mark",
        "#": "number_sign", "$": "dollar_sign", "%": "percent_sign",
        "&": "ampersand", "'": "apostrophe", "(": "left_parenthesis",
        ")": "right_parenthesis", "*": "asterisk", "+": "plus",
        ",": "comma", "-": "hyphen_minus", ".": "full_stop",
        "/": "solidus", ":": "colon", ";": "semicolon",
        "<": "less_than_sign", "=": "equals_sign",
        ">": "greater_than_sign", "?": "question_mark",
        "@": "commercial_at", "[": "left_square_bracket",
        "\\": "reverse_solidus", "]": "right_square_bracket",
        "^": "circumflex_accent", "_": "underscore",
        "`": "grave_accent", "{": "left_curly_bracket",
        "|": "vertical_line", "}": "right_curly_bracket", "~": "tilde"
    }

    if field == "aliases":
        if sk == fk and sm == fm and sa == fa:
            # Associated text cannot erase modified shortcut aliases.
            return bool(fm & 62) and not fzero
        if op != "contains" or len(fa) == 0 or fzero:
            return False
        alternate = chr(int(fa[0]))
        name = alternate
        if alternate in punctuation:
            name = punctuation[alternate]
        elif not (alternate.lower() != alternate.upper()
                  or "0" <= alternate <= "9"):
            return False
        parts = expected.split("+")
        # A shifted alternate already embodies shift. Its shortcut must
        # continue matching when shift is explicitly present on the wire.
        prefix = []
        if fm & 2:
            prefix = prefix + ["alt"]
        if fm & 4:
            prefix = prefix + ["ctrl"]
        if fm & 8:
            prefix = prefix + ["super"]
        if fm & 16:
            prefix = prefix + ["hyper"]
        if fm & 32:
            prefix = prefix + ["meta"]
        if fm & 192:
            return False
        return (parts[-1] == name
                and sorted(parts[:-1]) == sorted(prefix))

    # Code zero means text without a known key, including modified events.
    if fzero:
        if szero and st == ft and len(ft) > 0:
            return True
        if len(ft) != 1:
            return False
        value = chr(int(ft[0]))
        if op == "eq":
            return value == expected
        if op == "one_of":
            return value in expected
        return False

    if field == "character":
        # Non-shift modified printable shortcuts have no character, even
        # when associated text or alternate metadata accompanies the key.
        if fp and fm & 62:
            if op == "eq":
                return expected is None
            if op == "one_of":
                return None in expected
            return False
        if sk == fk and sm == fm and st == ft and not (fm & 1):
            return True
        if not fp or fm & 254 or len(ft) > 0:
            return False
        value = fc
        if fm & 1:
            if len(fa) > 0:
                value = chr(int(fa[0]))
            else:
                value = fc.upper()
        # This also covers adding shift to an already shifted character.
        if op == "eq":
            return value == expected
        if op == "one_of":
            return value in expected
        return False

    if field == "key":
        if sk == fk and sm == fm:
            # Alternate metadata and text do not rename modified shortcuts.
            if fp and fm & 62:
                return True
            if st == ft and sa == fa:
                return True
            if st == ft and not (fm & 1):
                return True

        # Shift-printable public spelling is deliberately non-unique.
        # Preserve a membership assertion only if it admits BOTH spellings.
        if not fp or fm & 254 or len(ft) > 0:
            return False
        base = fc
        if fc in punctuation:
            base = punctuation[fc]
        elif not (fc.lower() != fc.upper() or "0" <= fc <= "9"):
            return False
        if not (fm & 1):
            if op == "eq":
                return base == expected
            if op == "one_of":
                return base in expected
            return False
        shifted = fc.upper()
        if len(fa) > 0:
            shifted = chr(int(fa[0]))
        if not shifted.isprintable():
            return False
        named = "shift+" + base
        if op == "one_of":
            return shifted in expected and named in expected
        return False

    return False
