def preserves(field, op, expected, source, followup):
    sm = source["modifiers"] - 1
    fm = followup["modifiers"] - 1
    same_key = source["key"] == followup["key"]
    same_text = source["text"] == followup["text"]
    sa = source["alternate"]
    fa = followup["alternate"]
    ss = int(sa[0]) if len(sa) else None
    fs = int(fa[0]) if len(fa) else None
    sb = int(sa[1]) if len(sa) > 1 else None
    fb = int(fa[1]) if len(fa) > 1 else None

    # Event types apply across u, tilde, and letter encodings.
    if field in ("phase", "is_press", "is_repeat", "is_release"):
        phase = int(followup["phase"])
        if field == "phase":
            value = {1: "press", 2: "repeat", 3: "release"}[phase]
        elif field == "is_press":
            value = phase == 1
        elif field == "is_repeat":
            value = phase == 2
        else:
            value = phase == 3
        if op == "eq":
            return value == expected
        if op == "one_of":
            return value in expected
        return False

    # Convenience properties report independent wire bits, not public-key spelling.
    bits = {"shift": 1, "alt": 2, "ctrl": 4,
            "super": 8, "hyper": 16, "meta": 32}
    if field in bits:
        value = bool(fm & bits[field])
        if op == "eq":
            return value == expected
        if op == "one_of":
            return value in expected
        return False

    if field == "modifiers":
        if sm == fm:
            return True
        # Membership needs only the named modifier, not the whole tuple.
        if op == "contains" and expected in bits:
            return bool(fm & bits[expected])
        return False

    # Reported alternate metadata is independent of phase, text, and modifiers.
    if field == "shifted_key":
        return ss == fs
    if field == "base_layout_key":
        return sb == fb

    szero = source["key"].endswith("u") and int(source["key"][:-1]) == 0
    fzero = followup["key"].endswith("u") and int(followup["key"][:-1]) == 0

    sc = None
    fc = None
    if source["key"].endswith("u"):
        code = int(source["key"][:-1])
        # Kitty reserves this private-use range for functional keys.
        if 0 <= code <= 1114111 and not 57344 <= code <= 63743:
            char = chr(code)
            if char.isprintable():
                sc = char
    if followup["key"].endswith("u"):
        code = int(followup["key"][:-1])
        if 0 <= code <= 1114111 and not 57344 <= code <= 63743:
            char = chr(code)
            if char.isprintable():
                fc = char

    if field == "base_key":
        # Text-reporting events retain stable unmodified key metadata.
        if same_key and (not fzero or same_text):
            return True
        # The uppercase modified-printable contract uses the lowercase base.
        return (
            sc is not None and fc is not None
            and sc.lower() == fc.lower()
            and len(sc.lower()) == 1
        )

    if field in ("key", "character"):
        # Code zero uses associated text for both projections, even with modifiers.
        if szero and fzero and same_text and len(followup["text"]) > 0:
            return True
        if fzero:
            if len(followup["text"]) == 1:
                value = chr(int(followup["text"][0]))
                if op == "eq":
                    return value == expected
                if op == "one_of":
                    return value in expected
            return False

        # Phase and the base-layout report do not change these projections.
        if same_key and sm == fm and same_text and ss == fs:
            return True

    if field == "character":
        # Non-shift modified printable shortcuts have no character.
        if fc is not None and fm & 62:
            if op == "eq":
                return expected is None
            if op == "one_of":
                return None in expected
            return False

        # Without associated text or lock-state ambiguity, printable shift
        # semantics use the reported alternate, or the uppercase character.
        if fc is not None and not followup["text"] and not fm & 254:
            value = fc
            if fm & 1:
                if fs is not None:
                    if not 0 <= fs <= 1114111:
                        return False
                    value = chr(fs)
                    if not value.isprintable():
                        return False
                else:
                    value = fc.upper()
            if op == "eq":
                return value == expected
            if op == "one_of":
                return value in expected
        return False

    if field == "key":
        # Modified shortcuts retain their mod+base spelling; uppercase wire
        # characters and shifted alternates do not replace that base.
        if sm == fm and fm & 62 and sc is not None and fc is not None:
            return sc.lower() == fc.lower() and len(fc.lower()) == 1

        # Shift-only public spelling is deliberately a choice in the contract.
        # Membership must cover both spellings, rather than pick one oracle.
        if (
            op == "one_of" and fc is not None and fm == 1
            and not followup["text"] and fc.lower().islower()
            and len(fc.lower()) == 1
        ):
            shifted = fc.upper()
            if fs is not None:
                if not 0 <= fs <= 1114111:
                    return False
                shifted = chr(fs)
            return shifted in expected and ("shift+" + fc.lower()) in expected
        return False

    if field == "aliases":
        if same_key and sm == fm and ss == fs and sb == fb and same_text:
            return True
        if op != "contains" or fs is None or not 0 <= fs <= 1114111:
            return False

        # Shifted aliases use Textual names. Shift is already represented by
        # the alternate itself, so adding shift can preserve this membership.
        shifted = chr(fs)
        if shifted == "+":
            shifted = "plus"
        elif shifted == "=":
            shifted = "equals_sign"
        elif shifted == " ":
            shifted = "space"
        elif not shifted.isprintable() or not (
            shifted.islower() or shifted.isupper() or shifted.isdigit()
        ):
            return False

        parts = expected.split("+")
        if parts[-1] != shifted or "shift" in parts[:-1]:
            return False
        if fm & 192:
            return False
        names = ()
        if fm & 2:
            names = names + ("alt",)
        if fm & 4:
            names = names + ("ctrl",)
        if fm & 8:
            names = names + ("super",)
        if fm & 16:
            names = names + ("hyper",)
        if fm & 32:
            names = names + ("meta",)
        return (
            bool(fm & 62)
            and tuple(sorted(parts[:-1])) == tuple(sorted(names))
        )

    return False
