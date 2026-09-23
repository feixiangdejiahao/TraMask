def preserves(field, op, expected, source, followup):
    sm = source["modifiers"] - 1
    fm = followup["modifiers"] - 1
    same_key = source["key"] == followup["key"]
    same_alt = source["alternate"] == followup["alternate"]
    same_text = source["text"] == followup["text"]
    same_mod = sm == fm

    # Event type is independent of key encoding, text, and modifier bits.
    phases = {"1": "press", "2": "repeat", "3": "release"}
    if field == "phase":
        value = phases[followup["phase"]]
        if op == "eq":
            return value == expected
        if op == "one_of":
            return value in expected
        return False
    if field in ("is_press", "is_repeat", "is_release"):
        types = {"is_press": "1", "is_repeat": "2", "is_release": "3"}
        value = followup["phase"] == types[field]
        if op == "eq":
            return value == expected
        if op == "one_of":
            return value in expected
        return False

    # Convenience properties project individual protocol modifier bits.
    bits = {
        "shift": 1, "alt": 2, "ctrl": 4, "super": 8,
        "hyper": 16, "meta": 32, "caps_lock": 64, "num_lock": 128,
    }
    if field in ("shift", "alt", "ctrl", "super", "hyper", "meta"):
        value = bool(fm & bits[field])
        if op == "eq":
            return value == expected
        if op == "one_of":
            return value in expected
        return False
    if field == "modifiers":
        if same_mod:
            return True
        # Membership need not preserve the complete sorted tuple.
        if op == "contains" and expected in bits:
            return bool(fm & bits[expected])
        return False

    sa = source["alternate"]
    fa = followup["alternate"]
    ss = None
    fs = None
    sl = None
    fl = None
    if len(sa) > 0:
        ss = int(sa[0])
    if len(fa) > 0:
        fs = int(fa[0])
    if len(sa) > 1:
        sl = int(sa[1])
    if len(fa) > 1:
        fl = int(fa[1])

    # Alternate metadata names the reported alternate, not the active text.
    if field == "shifted_key":
        return ss == fs
    if field == "base_layout_key":
        return sl == fl

    sc = None
    fc = None
    if source["key"].endswith("u") and source["key"][:-1].isdigit():
        sc = int(source["key"][:-1])
    if followup["key"].endswith("u") and followup["key"][:-1].isdigit():
        fc = int(followup["key"][:-1])

    sp = ""
    fp = ""
    if sc is not None and 0 < sc <= 1114111:
        sp = chr(sc)
    if fc is not None and 0 < fc <= 1114111:
        fp = chr(fc)
    sprint = bool(sp) and sp.isprintable()
    fprint = bool(fp) and fp.isprintable()

    # Press/repeat/release changes do not change a Key's other stored data.
    if field in ("key", "character", "base_key", "aliases", "is_printable"):
        if same_key and same_alt and same_text and same_mod:
            return True

    if field == "base_key":
        # Associated text and alternates must not replace stable primary metadata.
        if same_key and ((sm & 1) == (fm & 1)):
            return True
        if same_key and (not sprint or not sp.isupper()):
            return True
        # Shifted alphabetic primary codes retain the unshifted base name.
        if fprint and (fp.islower() or fp.isupper()):
            value = fp
            if fm & 1:
                value = fp.lower()
            if len(value) == 1:
                if op == "eq":
                    return value == expected
                if op == "one_of":
                    return value in expected
        return False

    # Code zero explicitly denotes text without a known physical key.
    if field in ("key", "character") and fc == 0 and followup["text"]:
        if sc == 0 and same_text:
            return True
        if len(followup["text"]) == 1:
            value = chr(int(followup["text"][0]))
            if op == "eq":
                return value == expected
            if op == "one_of":
                return value in expected
        return False

    if field == "character":
        # Non-shift printable shortcuts retain character=None, including when
        # text reporting or alternate metadata is also enabled.
        if fprint and (fm & 62):
            if op == "eq":
                return expected is None
            if op == "one_of":
                return None in expected
            return False

        # For unmodified/shift-only text events, reported text is the character.
        if not (fm & 62) and followup["text"]:
            if same_text and not (sm & 62) and source["text"]:
                return True
            if len(followup["text"]) == 1:
                value = chr(int(followup["text"][0]))
                if op == "eq":
                    return value == expected
                if op == "one_of":
                    return value in expected
            return False

        if fprint and not (fm & 254):
            value = fp
            known = True
            if fm & 1:
                if fs is not None:
                    value = chr(fs)
                    known = value.isprintable()
                elif not fp.isupper():
                    # A shift mapping cannot in general be guessed from a code.
                    known = False
            if known:
                if op == "eq":
                    return value == expected
                if op == "one_of":
                    return value in expected
        if same_key and same_mod and same_text and ss == fs:
            return True
        return False

    if field == "key":
        # Shortcut names are stable under associated-text and alternate reports.
        if fprint and (fm & 62):
            if same_key and same_mod:
                return True

        # Shift-only printable keys permit either the literal shifted character
        # or the modifier-qualified base name; membership must cover BOTH.
        if fprint and fm == 1 and op == "one_of":
            shifted = None
            if fs is not None and chr(fs).isprintable():
                shifted = chr(fs)
            elif fp.isupper():
                shifted = fp
            base = fp.lower()
            if shifted is not None and len(base) == 1 and base.islower():
                text_agrees = not followup["text"]
                if len(followup["text"]) == 1:
                    text_agrees = chr(int(followup["text"][0])) == shifted
                if text_agrees:
                    return shifted in expected and ("shift+" + base) in expected

        if same_key and same_mod and same_text and ss == fs:
            return True
        return False

    if field == "aliases":
        # A shifted alternate contributes an alias with Shift consumed.
        # Preserving this member does not require preserving all other aliases.
        if op == "contains" and fs is not None and (fm & 1):
            name = chr(fs)
            known = name.islower() or name.isupper()
            # The issue explicitly requires Textual's punctuation name here.
            if name == "+":
                name = "plus"
                known = True
            if known and not (fm & 192):
                prefix = ""
                if fm & 2:
                    prefix = prefix + "alt+"
                if fm & 4:
                    prefix = prefix + "ctrl+"
                if fm & 16:
                    prefix = prefix + "hyper+"
                if fm & 32:
                    prefix = prefix + "meta+"
                if fm & 8:
                    prefix = prefix + "super+"
                return expected == prefix + name
        return False

    return False
