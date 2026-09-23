def preserves(field, op, expected, source, followup):
    sm = source["modifiers"] - 1
    fm = followup["modifiers"] - 1
    same_key = source["key"] == followup["key"]
    same_alt = source["alternate"] == followup["alternate"]
    same_text = source["text"] == followup["text"]
    same_mods = sm == fm
    szero = source["key"].endswith("u") and int(source["key"].split("u")[0]) == 0
    fzero = followup["key"].endswith("u") and int(followup["key"].split("u")[0]) == 0

    # Event types apply to every supported trailer, not only Unicode keys.
    if field in ("phase", "is_press", "is_repeat", "is_release"):
        phase = {"1": "press", "2": "repeat", "3": "release"}[followup["phase"]]
        if field == "phase":
            value = phase
        else:
            value = phase == field.split("is_")[1]
        if op == "eq":
            return value == expected
        if op == "one_of":
            return value in expected
        return False

    # Convenience flags are projections of individual protocol modifier bits.
    bits = {"shift": 1, "alt": 2, "ctrl": 4, "super": 8, "hyper": 16, "meta": 32}
    if field in bits:
        value = bool(fm & bits[field])
        if op == "eq":
            return value == expected
        if op == "one_of":
            return value in expected
        return False

    if field == "modifiers":
        if same_mods:
            return True
        if op == "contains" and expected in bits:
            return bool(fm & bits[expected])
        # The API specifies a sorted tuple. Avoid guessing lock-bit spellings.
        if fm & 192:
            return False
        value = ()
        if fm & 2:
            value = value + ("alt",)
        if fm & 4:
            value = value + ("ctrl",)
        if fm & 16:
            value = value + ("hyper",)
        if fm & 32:
            value = value + ("meta",)
        if fm & 1:
            value = value + ("shift",)
        if fm & 8:
            value = value + ("super",)
        if op == "eq":
            return value == expected
        if op == "one_of":
            return value in expected
        return False

    # Alternate metadata records the supplied Unicode keys independently of
    # phase, text reporting, the primary key, and active modifiers.
    if field in ("shifted_key", "base_layout_key"):
        index = 0
        if field == "base_layout_key":
            index = 1
        shas = len(source["alternate"]) > index
        fhas = len(followup["alternate"]) > index
        if not shas and not fhas:
            return True
        if shas and fhas:
            if int(source["alternate"][index]) == int(followup["alternate"][index]):
                return True
        if not fhas:
            if op == "eq":
                return expected == None
            if op == "one_of":
                return None in expected
        return False

    # Text-reporting events retain their stable base metadata. Code zero is
    # different: its only key identity is its associated text.
    if field == "base_key":
        if same_key:
            return not fzero or same_text
        return szero and fzero and same_text

    # Phase is orthogonal to all the remaining keyboard projections.
    if same_key and same_alt and same_text and same_mods:
        return field in ("key", "character", "aliases", "is_printable")

    # Unknown-key text is both the public key and character, even with modifiers.
    if szero and fzero and same_text and len(followup["text"]) > 0:
        if field in ("key", "character", "is_printable"):
            return True

    sc = None
    fc = None
    if source["key"].endswith("u"):
        code = int(source["key"].split("u")[0])
        if 0 < code <= 1114111:
            sc = chr(code)
    if followup["key"].endswith("u"):
        code = int(followup["key"].split("u")[0])
        if 0 < code <= 1114111:
            fc = chr(code)
    sprint = sc != None and sc.isprintable()
    fprint = fc != None and fc.isprintable()

    if field in ("character", "is_printable"):
        # Non-shift modified printable shortcuts produce no character; text
        # reporting does not turn those shortcuts into ordinary text keys.
        if not fzero and fprint and fm & 62:
            value = None
            if field == "is_printable":
                value = False
            if op == "eq":
                return value == expected
            if op == "one_of":
                return value in expected
            return False

        if same_key and same_mods and same_text:
            # Shifted alternates can change the produced character only when
            # shift is actually applied.
            if not fm & 1:
                return True
            if len(source["alternate"]) > 0 and len(followup["alternate"]) > 0:
                return int(source["alternate"][0]) == int(followup["alternate"][0])

        # Applying shift to an already uppercase Unicode letter is absorbed.
        # This does not assert idempotence for arbitrary punctuation mappings.
        if same_key and same_alt and same_text and len(followup["text"]) == 0:
            if (sm ^ fm) == 1 and not (sm | fm) & 254:
                if fprint and fc.isupper() and fc.upper() == fc:
                    if len(followup["alternate"]) == 0:
                        return True
                    return int(followup["alternate"][0]) == ord(fc)
        return False

    if field == "key":
        if same_key and same_mods and not fzero:
            # Modified shortcut names use stable primary-key identity.
            if fprint and fm & 62:
                return True
            if same_text and not fm & 1:
                return True
            if same_text and same_alt:
                return True
        return False

    if field == "aliases":
        if op != "contains":
            return False

        # Adding alternate metadata must not remove existing primary aliases.
        if same_key and same_mods and same_text:
            if len(source["alternate"]) == 0:
                return True
            if len(followup["alternate"]) >= len(source["alternate"]):
                first_same = int(source["alternate"][0]) == int(followup["alternate"][0])
                if first_same and len(source["alternate"]) == 1:
                    return True
                if first_same and int(source["alternate"][1]) == int(followup["alternate"][1]):
                    return True

        # A shifted-alternate shortcut remains a member even if other aliases
        # change. Shift is absorbed by the explicitly supplied shifted key.
        if len(followup["alternate"]) > 0 and not fm & 192:
            code = int(followup["alternate"][0])
            if not 0 < code <= 1114111:
                return False
            name = chr(code)
            # Textual spellings explicitly established by the supplied contract.
            names = {"+": "plus", "=": "equals_sign", " ": "space"}
            if name in names:
                name = names[name]
            elif not name.isprintable() or not (name.islower() or name.isupper()):
                return False

            prefix = ""
            if fm & 2:
                prefix = prefix + "alt+"
            if fm & 4:
                prefix = prefix + "ctrl+"
            if fm & 16:
                prefix = prefix + "hyper+"
            if fm & 32:
                prefix = prefix + "meta+"
            unshifted_prefix = prefix
            if fm & 1:
                prefix = prefix + "shift+"
            if fm & 8:
                prefix = prefix + "super+"
                unshifted_prefix = unshifted_prefix + "super+"
            return expected == prefix + name or expected == unshifted_prefix + name
        return False

    return False
