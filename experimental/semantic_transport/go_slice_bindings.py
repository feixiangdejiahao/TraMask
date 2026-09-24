"""Keep Go prefixes compilable when a later use was removed by slicing.

Blank assignments to newly bound locals preserve each initializer and its
evaluation order. They do not evaluate methods, replace expected values, or
execute the subject. Only declarations in ordinary statement lists are handled.
"""
from anchor_retrieval.syntax import Source, child, walk


def normalize_body(body):
    prefix = 'package slice\nfunc generated() '
    source = Source('slice.go', prefix + body, 'go')
    if source.root.has_error:
        return body
    edits = []
    for statement in walk(source.root):
        if statement.parent is None or statement.parent.type != 'statement_list':
            continue
        names = []
        if statement.type == 'short_var_declaration':
            left = child(statement, 'left')
            if left is not None:
                names = [source.text(n) for n in left.named_children if n.type == 'identifier']
        elif statement.type == 'var_declaration':
            for spec in walk(statement):
                if spec.type == 'var_spec':
                    names.extend(source.text(n) for n in spec.children_by_field_name('name'))
        names = list(dict.fromkeys(n for n in names if n != '_'))
        if not names:
            continue
        following = statement.next_named_sibling
        pending = list(names)
        at = statement.end_byte
        # Re-running the normalization does not accumulate blank uses.
        while pending and following is not None:
            left, right = child(following, 'left'), child(following, 'right')
            if (following.type == 'assignment_statement' and left is not None and right is not None
                    and source.text(left) == '_' and source.text(right) == pending[0]):
                pending.pop(0)
                at = following.end_byte
                following = following.next_named_sibling
            else:
                break
        if pending:
            edits.append((at, '; ' + '; '.join('_ = ' + n for n in pending)))
    raw = source.data
    for at, text in sorted(edits, reverse=True):
        raw = raw[:at] + text.encode() + raw[at:]
    return raw[len(prefix.encode()):].decode()
