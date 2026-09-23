def preserves(field, op, expected, source, followup):
    sm = source["modifiers"] - 1
    fm = followup["modifiers"] - 1
    same_key = source["key"] == followup["key"]
    same_text = source["text"] == followup["text"]
    same_alt = source["alternate"] == followup["alternate"]

    sa = source["alternate"]
    fa = followup["alternate"]
    same_shifted = (
        (not sa and not fa)
        or (bool(sa) and bool(fa) and int(sa[0]) == int(fa[0]))
    )
    same_layout = (
        (len(sa) < 2 and len(fa) < 2)
        or (len(sa) == 2 and len(fa) == 2 and int(sa[1]) == int(fa[1]))
    )

    # Phase is an independent protocol subfield, including on non-u trailers.
    if field == "phase":
        value = ("press", "repeat", "release")[int(followup["phase"]) - 1]
    elif field == "is_press":
        value = int(followup["phase"]) == 1
    elif field == "is_repeat":
        value = int(followup["phase"]) == 2
    elif field == "is_release":
        value = int(followup["phase"]) == 3
    elif field == "phases":
        value = [("press", "repeat", "release")[int(followup["phase"]) - 1]]
    elif field in ("shift", "alt", "ctrl", "super", "hyper", "meta"):
        # Convenience properties report their own wire bit, not other bits.
        bit = {
            "shift": 1, "alt": 2, "ctrl": 4,
            "super": 8, "hyper": 16, "meta": 32,
        }[field]
        value = bool(fm & bit)
    elif field == "modifiers":
        # Exact stored modifiers survive key, text, alternate, and phase changes.
        if sm == fm:
            return True
        if op == "contains" and expected in (
            "shift", "alt", "ctrl", "super", "hyper", "meta"
        ):
            bit = {
                "shift": 1, "alt": 2, "ctrl": 4,
                "super": 8, "hyper": 16, "meta": 32,
            }[expected]
            return bool(fm & bit)
        # The supplied contracts do not specify lock-bit public spellings.
        if fm & 192:
            return False
        names = (
            (["shift"] if fm & 1 else [])
            + (["alt"] if fm & 2 else [])
            + (["ctrl"] if fm & 4 else [])
            + (["super"] if fm & 8 else [])
            + (["hyper"] if fm & 16 else [])
            + (["meta"] if fm & 32 else [])
        )
        value = tuple(sorted(names))
    elif field == "shifted_key":
        # Alternate metadata is independent of text, modifiers, and phase.
        return same_shifted
    elif field == "base_layout_key":
        return same_layout
    else:
        # Changing only event type cannot change a Key's identity or metadata.
        if (
            same_key and same_text and same_alt and sm == fm
            and field in ("key", "character", "base_key", "aliases", "is_printable")
        ):
            return True

        su = source["key"].endswith("u")
        fu = followup["key"].endswith("u")
        sn = int(source["key"][:-1])
        fn = int(followup["key"][:-1])
        szero = su and sn == 0
        fzero = fu and fn == 0
        sc = chr(sn) if su and 0 <= sn <= 1114111 else ""
        fc = chr(fn) if fu and 0 <= fn <= 1114111 else ""
        sp = bool(sc) and sc.isprintable()
        fp = bool(fc) and fc.isprintable()
        sshortcut = sp and bool(sm & 62)
        fshortcut = fp and bool(fm & 62)

        if field == "base_key":
            # Text reporting and alternate layout information do not replace
            # the underlying known key's stable base metadata.
            if same_key and not szero:
                if sm == fm:
                    return True
                if not sp or not sc.isupper():
                    return True
                # Uppercase shifted encodings still have the lowercase base.
                return bool(sm & 1) and bool(fm & 1)
            if (
                sp and fp and sm & 1 and fm & 1
                and sc.lower() == fc.lower()
            ):
                return True
            return False

        if field == "aliases":
            if (
                same_key and sm == fm and same_alt
                and (same_text or (sshortcut and fshortcut))
            ):
                return True
            # A shifted alias drops Shift but retains the other shortcut
            # modifiers. Its membership need not preserve the entire list.
            if (
                op == "contains"
                and bool(sa) and bool(fa) and same_shifted
                and sm & 1 and fm & 1
                and (sm & 254) == (fm & 254)
            ):
                shifted = chr(int(fa[0]))
                if shifted == "+":
                    shifted = "plus"
                elif not (
                    shifted.islower() or shifted.isupper() or shifted.isdigit()
                ):
                    return False
                if fm & 192:
                    return False
                prefix = (
                    ("alt+" if fm & 2 else "")
                    + ("ctrl+" if fm & 4 else "")
                    + ("super+" if fm & 8 else "")
                    + ("hyper+" if fm & 16 else "")
                    + ("meta+" if fm & 32 else "")
                )
                return expected == prefix + shifted
            return False

        if field == "matched":
            # Release is delivered, but must not run a binding.
            if int(followup["phase"]) != 3:
                return False
            value = False

        elif field in ("key", "character"):
            # Code zero uses associated text as both outputs, even with
            # modifiers; the issue imposes no unmodified-only restriction.
            if szero and fzero and same_text:
                return True
            if fzero:
                if len(followup["text"]) != 1:
                    return False
                value = chr(int(followup["text"][0]))

            elif field == "key" and fshortcut:
                # Non-shift modified printable shortcuts retain stable names,
                # including when associated text or alternates are supplied.
                if sm != fm or not sshortcut:
                    return False
                if same_key:
                    return True
                return bool(fm & 1) and sc.lower() == fc.lower()

            elif field == "character" and fshortcut:
                # Associated text must not turn a modified shortcut into text.
                value = None

            elif field == "character" and followup["text"]:
                if same_text and not sshortcut:
                    return True
                if len(followup["text"]) != 1:
                    return False
                value = chr(int(followup["text"][0]))

            elif fp and not (fm & 254):
                produced = fc
                if fm & 1 and fa:
                    produced = chr(int(fa[0]))
                elif fm & 1 and fc.islower():
                    # No supplied contract specifies arbitrary inferred
                    # layout-dependent shifted forms without an alternate.
                    return False
                if not produced.isprintable():
                    return False

                if field == "character":
                    value = produced
                elif fm & 1:
                    # The shift-only contract permits either public spelling.
                    # Preserve membership only when both remain acceptable.
                    if op != "one_of":
                        return False
                    if not (fc.islower() or fc.isupper() or fc.isdigit()):
                        return False
                    if followup["text"]:
                        if len(followup["text"]) != 1:
                            return False
                        if chr(int(followup["text"][0])) != produced:
                            return False
                    return (
                        produced in expected
                        and "shift+" + fc.lower() in expected
                    )
                else:
                    if followup["text"]:
                        return False
                    if not (fc.islower() or fc.isupper() or fc.isdigit()):
                        return False
                    value = fc
            else:
                return False
        else:
            return False

    if op == "eq":
        return value == expected
    if op == "one_of":
        return value in expected
    if op == "contains":
        if isinstance_placeholder := False:
            return False
        if value is None or value is True or value is False:
            return False
        return expected in value
    return False
