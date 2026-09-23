def preserves(field, op, expected, source, followup):
    sm = source["modifiers"] - 1
    fm = followup["modifiers"] - 1
    sk = source["key"]
    fk = followup["key"]
    sa = source["alternate"]
    fa = followup["alternate"]
    st = source["text"]
    ft = followup["text"]

    # Event types apply across the producer's u, tilde, and letter encodings.
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
        return (op == "eq" and value == expected) or (
            op == "one_of" and value in expected
        )

    # Convenience properties report individual held modifier bits.
    bits = {"shift": 1, "alt": 2, "ctrl": 4,
            "super": 8, "hyper": 16, "meta": 32}
    if field in bits:
        value = bool(fm & bits[field])
        return (op == "eq" and value == expected) or (
            op == "one_of" and value in expected
        )

    if field == "modifiers":
        if sm == fm:
            return True
        # Membership survives unrelated modifier additions/removals.
        if op == "contains" and expected in bits:
            return bool(fm & bits[expected])
        # The supplied contracts do not specify public lock-modifier spelling.
        if fm & 192:
            return False
        value = ()
        if fm & 1:
            value = value + ("shift",)
        if fm & 2:
            value = value + ("alt",)
        if fm & 4:
            value = value + ("ctrl",)
        if fm & 8:
            value = value + ("super",)
        if fm & 16:
            value = value + ("hyper",)
        if fm & 32:
            value = value + ("meta",)
        value = tuple(sorted(value))
        return (op == "eq" and value == expected) or (
            op == "one_of" and value in expected
        ) or (op == "contains" and expected in value)

    same_key = sk == fk
    if sk[-1] == fk[-1]:
        same_key = int(sk[:-1]) == int(fk[:-1])

    same_shifted = len(sa) == 0 and len(fa) == 0
    if len(sa) > 0 and len(fa) > 0:
        same_shifted = int(sa[0]) == int(fa[0])

    # Reported alternate metadata is independent of phase, text, and modifiers.
    if field in ("shifted_key", "base_layout_key"):
        index = 0
        if field == "base_layout_key":
            index = 1
        if len(sa) > index and len(fa) > index:
            if int(sa[index]) == int(fa[index]):
                return True
        if len(sa) <= index and len(fa) <= index:
            return True
        if len(fa) <= index:
            value = None
        else:
            value = chr(int(fa[index]))
            # Names explicitly established by the issue and existing contracts.
            names = {" ": "space", "+": "plus", "=": "equals_sign"}
            if value in names:
                value = names[value]
            elif not (
                "a" <= value <= "z"
                or "A" <= value <= "Z"
                or "0" <= value <= "9"
            ):
                return False
        return (op == "eq" and value == expected) or (
            op == "one_of" and value in expected
        )

    sc = None
    fc = None
    if sk.endswith("u") and 0 < int(sk[:-1]) <= 1114111:
        sc = chr(int(sk[:-1]))
    if fk.endswith("u") and 0 < int(fk[:-1]) <= 1114111:
        fc = chr(int(fk[:-1]))
    sp = sc is not None and sc.isprintable()
    fp = fc is not None and fc.isprintable()
    szero = sk.endswith("u") and int(sk[:-1]) == 0
    fzero = fk.endswith("u") and int(fk[:-1]) == 0

    if field == "base_key":
        # Stable unmodified identity must survive text reporting and event type.
        if same_key:
            return not fzero or st == ft
        # Shifted and primary letter encodings describe the same base letter.
        if sp and fp and sc.lower() == fc.lower():
            if ("a" <= sc <= "z" or sm & 1) and (
                "a" <= fc <= "z" or fm & 1
            ):
                return True
        return False

    if field not in ("key", "character", "aliases"):
        return False

    # Phase changes do not change other public key projections.
    if same_key and sa == fa and sm == fm and st == ft:
        return True

    if field in ("key", "character") and fzero:
        # Code zero uses its associated text even when modifiers are reported.
        if szero and st == ft:
            return True
        if len(ft) == 1:
            value = chr(int(ft[0]))
            return (op == "eq" and value == expected) or (
                op == "one_of" and value in expected
            )
        return False

    if field == "aliases" and op == "contains" and len(fa) > 0:
        shifted = chr(int(fa[0]))
        names = {" ": "space", "+": "plus", "=": "equals_sign"}
        known = True
        if shifted in names:
            shifted = names[shifted]
        elif not (
            "a" <= shifted <= "z"
            or "A" <= shifted <= "Z"
            or "0" <= shifted <= "9"
        ):
            known = False
        if known and not fm & 192:
            # A shifted alternate already encodes shift: ctrl+plus must match
            # the shifted form, not require an additional literal shift.
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
            if expected == prefix + shifted:
                return True

    if field == "character":
        # Non-shift modified printable shortcuts have no character; this is
        # not restricted to press events or to packets without associated text.
        if fp and fm & 62:
            return (op == "eq" and expected is None) or (
                op == "one_of" and None in expected
            )
        if same_key and sm == fm and st == ft:
            if not fm & 1 or same_shifted:
                return True

        # Associated text can determine printable output. With no text, the
        # primary/shifted character gives a value-dependent preservation rule.
        if fp and not ft and fm in (0, 1):
            value = fc
            known = fm == 0
            if fm == 1:
                if fa:
                    value = chr(int(fa[0]))
                    known = value.isprintable()
                elif "a" <= fc <= "z" or "A" <= fc <= "Z":
                    value = fc.upper()
                    known = True
            if known:
                # In particular, shift applied to an encoded uppercase letter
                # preserves that character rather than destroying it.
                return (op == "eq" and value == expected) or (
                    op == "one_of" and value in expected
                )
        return False

    if field == "key":
        if same_key and sm == fm and st == ft:
            if same_shifted or not fm & 1:
                return True

        # Modified printable shortcuts retain their base-based public names.
        if sp and fp and sm == fm and fm & 62:
            if same_key:
                return True
            if sc.lower() == fc.lower():
                if ("a" <= sc <= "z" or sm & 1) and (
                    "a" <= fc <= "z" or fm & 1
                ):
                    return True

        if fp and not ft and fm == 1 and op == "one_of":
            # The issue permits either shifted output or a shift+base name.
            # Membership must cover both; equality to only one is insufficient.
            if "a" <= fc <= "z" or "A" <= fc <= "Z":
                shifted = fc.upper()
                if fa:
                    shifted = chr(int(fa[0]))
                if "a" <= shifted <= "z" or "A" <= shifted <= "Z":
                    return shifted in expected and "shift+" + fc.lower() in expected
        return False

    # Full alias equality needs all alias-producing metadata unchanged.
    if field == "aliases":
        if same_key and sm == fm and sa == fa and not fzero:
            if st == ft or fp and fm & 62:
                return True
    return False
