"""Lexical shell analysis for historical test discovery; commands stay unchanged."""
import ast
from io import StringIO
from pathlib import Path
import posixpath
import re
import shlex


_SCRIPT_EXTENSIONS = ('.py', '.js', '.cjs', '.mjs', '.ts', '.tsx', '.go', '.rs', '.sh')
_ASSIGNMENT = re.compile(r'[A-Za-z_][A-Za-z_0-9]*=')


def resolve_path(value, cwd="/app"):
    if not value or any(c in value for c in ("\0", "$", "`")):
        return None
    value = value.split("::", 1)[0]
    path = posixpath.normpath(value if value.startswith("/") else posixpath.join(cwd, value))
    return path if path in {"/app", "/tmp"} or path.startswith(("/app/", "/tmp/")) else None


def heredocs(command):
    rows, position = [], 0
    while position < len(command):
        newline = command.find("\n", position)
        if newline < 0:
            break
        header = command[position:newline]
        quote, escaped, offset = None, False, 0
        found = None
        while offset < len(header):
            char = header[offset]
            if escaped:
                escaped = False
            elif char == "\\" and quote != "'":
                escaped = True
            elif quote:
                if char == quote:
                    quote = None
            elif char in "'\"":
                quote = char
            elif header.startswith("<<", offset) and not header.startswith("<<<", offset):
                found = re.match(r"<<(?P<tabs>-?)\s*(?P<quote>['\"]?)(?P<delimiter>[A-Za-z_][A-Za-z_0-9]*)(?P=quote)", header[offset:])
                if found:
                    break
            offset += 1
        if not found:
            position = newline + 1
            continue
        cursor, closing = newline + 1, None
        while cursor < len(command):
            end = command.find("\n", cursor)
            end = len(command) if end < 0 else end
            line = command[cursor:end]
            if (line.lstrip("\t") if found["tabs"] else line) == found["delimiter"]:
                closing = (cursor, end + (end < len(command)))
                break
            cursor = end + 1
        body_end, end = closing if closing else (len(command), len(command))
        rows.append({"header_start": position, "header_end": newline, "body_start": newline + 1,
                     "body_end": body_end, "end": end, "body": command[newline + 1:body_end],
                     "terminated": closing is not None, "delimiter": found["delimiter"],
                     "quoted": bool(found["quote"]), "strip_tabs": bool(found["tabs"])})
        position = end
    return rows


def segments(command, heredocs):
    endings = {row["header_end"]: row for row in heredocs}
    rows, start, index, quote, escaped, depth = [], 0, 0, None, False, 0
    def add(end):
        nonlocal start
        left, right = start, end
        while left < right and command[left].isspace():
            left += 1
        while right > left and command[right - 1].isspace():
            right -= 1
        if left < right:
            rows.append({"start": left, "end": right, "text": command[left:right]})
    while index < len(command):
        if index in endings and quote is None:
            end = endings[index]["end"]
            add(end)
            start, index = end, end
            continue
        char = command[index]
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif not depth and (char in ";\n" or command[index:index + 2] in {"&&", "||"}):
            add(index)
            index += 1 if command[index:index + 2] in {"&&", "||"} else 0
            start = index + 1
        index += 1
    add(len(command))
    return rows


def shell_tokens(text, *, header_only=True):
    return [token for token, _ in shell_words(text, header_only=header_only)]


def shell_words(text, *, header_only=True):
    text = text.split('\n', 1)[0] if header_only else text
    stream = StringIO(text)
    lexer = shlex.shlex(stream,
                        posix=True, punctuation_chars=";&|<>")
    lexer.whitespace_split = True
    words = []
    while True:
        start = stream.tell()
        token = lexer.get_token()
        if token is None:
            return words
        words.append((token, text[start:stream.tell()]))


def _argument_needs_shell(raw):
    quote, index = None, 0
    while index < len(raw):
        char = raw[index]
        if char == '\\' and quote != "'":
            if quote == '"' and index + 1 < len(raw) and raw[index + 1] in '$`\n':
                return True
            index += 2
            continue
        if quote == "'":
            if char == "'":
                quote = None
        elif char in '$`':
            return True
        elif quote == '"' and char == '"':
            quote = None
        elif quote is None and char in "'\"":
            quote = char
        index += 1
    return False


def _heredoc_needs_shell(text):
    return bool(re.search(r'[$`]|\\[\\\n]', text))


def _inline_argument(tokens, options):
    for index, token in enumerate(tokens):
        for option in options:
            if token == option:
                return index, option, index + 1, None
            if len(option) == 2 and token.startswith(option) and len(token) > 2:
                return index, option, index, token[len(option):]
    return None


def python_writes(body, cwd):
    """Literal Path/open writes only; never evaluate or execute subject code."""
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return []
    rows, handles = [], {}
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    def literal_write(node, content):
        current = parents.get(node)
        while current is not None:
            if isinstance(current, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try,
                                    ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                return None
            current = parents.get(current)
        return content
    def opened(node):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open"
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            mode = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else None
            if isinstance(mode, str) and any(flag in mode for flag in "wax"):
                return resolve_path(node.args[0].value, cwd), mode
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            for item in node.items:
                info = opened(item.context_expr)
                if info and isinstance(item.optional_vars, ast.Name):
                    handles[item.optional_vars.id] = info
    for node in ast.walk(tree):
        if (not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute)
                or node.func.attr not in {"write_text", "write_bytes", "write"} or not node.args):
            continue
        owner = node.func.value
        if node.func.attr == "write":
            info = handles.get(owner.id) if isinstance(owner, ast.Name) else opened(owner)
            if info and info[0]:
                content = node.args[0].value if isinstance(node.args[0], ast.Constant) and "a" not in info[1] else None
                rows.append((info[0], literal_write(node, content if isinstance(content, str) else None)))
            continue
        if not isinstance(owner, ast.Call) or not owner.args:
            continue
        name = owner.func.id if isinstance(owner.func, ast.Name) else owner.func.attr if isinstance(owner.func, ast.Attribute) else None
        if name != "Path" or not isinstance(owner.args[0], ast.Constant) or not isinstance(owner.args[0].value, str):
            continue
        path = resolve_path(owner.args[0].value, cwd)
        if path:
            content = node.args[0].value if isinstance(node.args[0], ast.Constant) else None
            if isinstance(content, bytes):
                try:
                    content = content.decode("utf-8")
                except UnicodeDecodeError:
                    content = None
            rows.append((path, literal_write(node, content if isinstance(content, str) else None)))
    # Multiple writes/append operations are not a complete-file byte oracle.
    return [(path, content if sum(other == path for other, _ in rows) == 1 else None)
            for path, content in rows]


def source_writes(tokens, heredoc, cwd, words):
    rows = []
    for index, operator in enumerate(tokens[:-1]):
        if operator not in {">", ">>"}:
            continue
        token = tokens[index + 1]
        path = resolve_path(token, cwd)
        if not path:
            continue
        # Numeric stream destinations and /dev/null are not source material.
        if token.isdigit() or token.startswith("&"):
            continue
        content = heredoc["body"] if heredoc and tokens and posixpath.basename(tokens[0]) == "cat" and operator == ">" else None
        if content is not None and heredoc["strip_tabs"]:
            content = "".join(line.lstrip("\t") for line in content.splitlines(keepends=True))
        if content is not None and not heredoc["quoted"] and _heredoc_needs_shell(content):
            content = None
        rows.append((path, content))
    if tokens and posixpath.basename(tokens[0]) == "tee":
        rows += [(path, heredoc["body"] if heredoc and "-a" not in tokens
                  and (heredoc['quoted'] or not _heredoc_needs_shell(heredoc['body'])) else None)
                 for token in tokens[1:] if not token.startswith("-") and (path := resolve_path(token, cwd))]
    if tokens and posixpath.basename(tokens[0]) in {"sed", "perl"} and any(token.startswith("-i") for token in tokens):
        rows += [(path, None) for token in tokens[1:] if token.endswith(_SCRIPT_EXTENSIONS)
                 and (path := resolve_path(token, cwd))]
    if tokens and posixpath.basename(tokens[0]) in {"cp", "mv"}:
        arguments = [token for token in tokens[1:] if not token.startswith("-")]
        if len(arguments) == 2 and arguments[-1].endswith(_SCRIPT_EXTENSIONS):
            path = resolve_path(arguments[-1], cwd)
            if path:
                rows.append((path, None))
    if heredoc and tokens and posixpath.basename(tokens[0]) == "apply_patch":
        for match in re.finditer(r"^\*\*\* (?:Add|Update) File: (.+)$", heredoc["body"], re.M):
            path = resolve_path(match[1], cwd)
            if path:
                rows.append((path, None))
    if tokens and re.fullmatch(r"python(?:[23](?:\.\d+)?)?", posixpath.basename(tokens[0])):
        redirection=next((i for i,t in enumerate(tokens) if t in {'<<','<<-'}),len(tokens))
        entry,_,_=interpreter_entry(tokens[:redirection])
        argument = _inline_argument(tokens, ('-c',))
        body = heredoc['body'] if heredoc and entry=='stdin' else None
        if entry=='command' and argument and argument[2] < len(tokens) and not heredoc:
            _, _, index, attached = argument
            body = tokens[index] if attached is None else attached
        if body is not None:
            writes = python_writes(body, cwd)
            needs_shell = (not heredoc['quoted'] and _heredoc_needs_shell(body) if heredoc
                           else _argument_needs_shell(words[argument[2]][1]))
            if needs_shell:
                writes = [(path, None) for path, _ in writes]
            rows += writes
    return rows


def unwrap(tokens):
    tokens = list(tokens)
    while tokens and _ASSIGNMENT.match(tokens[0]):
        tokens.pop(0)
    if tokens and Path(tokens[0]).name in {"env", "command", "nohup"}:
        tokens.pop(0)
        while tokens and (tokens[0].startswith("-") or _ASSIGNMENT.match(tokens[0])):
            tokens.pop(0)
    if tokens and Path(tokens[0]).name == "timeout":
        tokens.pop(0)
        while tokens and tokens[0].startswith("-"):
            option = tokens.pop(0)
            if option in {"-s", "--signal", "-k", "--kill-after"} and tokens:
                tokens.pop(0)
        if tokens:
            tokens.pop(0)  # Duration, not a claim about runtime control flow.
    if len(tokens) >= 3 and Path(tokens[0]).name in {"uv", "poetry", "pipenv"} and tokens[1] == "run":
        tokens = tokens[2:]
    if tokens and Path(tokens[0]).name in {"npx", "bunx"}:
        tokens = tokens[1:]
        while tokens and tokens[0].startswith("-"):
            tokens.pop(0)
    return tokens


def interpreter_entry(argv):
    """Decode the source selector of an actual Python/Node interpreter argv."""
    python=bool(re.fullmatch(r'python(?:[23](?:\.\d+)?)?',Path(argv[0]).name))
    commands=('-c',) if python else ('-e','--eval','-p','--print')
    values={'-W','-X','--check-hash-based-pycs'} if python else {
        '-r','--require','--import','--loader','--experimental-loader','--input-type','--conditions','-C',
        '--compiler-options','-O','--project','-P'}
    i=1
    while i<len(argv):
        token=argv[i]
        options=(*commands,'-m') if python else commands
        for option in options:
            if token==option:
                value=argv[i+1] if i+1<len(argv) else None
                return ('module' if option=='-m' else 'command'),value,argv[i+2:]
            if (len(option)==2 and token.startswith(option) and len(token)>2) or token.startswith(option+'='):
                value=token[len(option)+1:] if len(option)>2 and token.startswith(option+'=') else token[len(option):]
                return ('module' if option=='-m' else 'command'),value,argv[i+1:]
        if token=='--':
            i+=1
            if i==len(argv):break
            token=argv[i]
        if token=='-':return 'stdin',None,argv[i+1:]
        if not token.startswith('-'):return 'file',token,argv[i+1:]
        i+=2 if token in values else 1
    return 'stdin',None,[]


def inline_sources(command):
    """Locate literal Python/JS/TS script text in shell invocations.

    Indices address decoded script text, not byte offsets in the quoted shell
    command. Shell syntax failures remain recorded material for later work.
    """
    sources, issues = [], []
    docs = heredocs(command)
    for segment in segments(command, docs):
        doc = next((d for d in docs if segment['start'] <= d['header_end'] < segment['end']), None)
        try:
            words = shell_words(segment['text'], header_only=doc is not None)
            tokens = unwrap([word for word, _ in words])
        except ValueError as error:
            issues.append({'kind': 'shell_lexing', 'message': str(error),
                           'start': len(command[:segment['start']].encode()),
                           'end': len(command[:segment['end']].encode())})
            continue
        if not tokens:
            continue
        executable = Path(tokens[0]).name
        if re.fullmatch(r'python(?:[23](?:\.\d+)?)?', executable):
            suffix, options = '.py', ('-c',)
        elif executable in {'node', 'nodejs'}:
            suffix, options = '.js', ('-e', '--eval')
        elif executable in {'tsx', 'ts-node'}:
            suffix, options = '.ts', ('-e', '--eval')
        else:
            continue
        argument = _inline_argument(tokens, options)
        # A module/script may consume stdin as data; a heredoc alone does not
        # make that data interpreter source.
        redirection = next((i for i, token in enumerate(tokens) if token in {'<<', '<<-'}), len(tokens))
        argv = tokens[1:redirection]
        entry,_,_=interpreter_entry(tokens[:redirection])
        stdin_script = entry=='stdin'
        if entry not in {'command','stdin'}:
            continue
        if argument is not None:
            _, option, offset, attached = argument
            if offset == len(tokens):
                issues.append({'kind': 'inline_argument_missing', 'message': option})
                continue
            text = tokens[offset] if attached is None else attached
            raw_argument = words[len(words) - len(tokens) + offset][1]
            needs_shell = _argument_needs_shell(raw_argument)
        elif doc is not None and stdin_script:
            text = doc['body']
            if doc['strip_tabs']:
                text = ''.join(line.lstrip('\t') for line in text.splitlines(keepends=True))
            needs_shell = not doc['quoted'] and _heredoc_needs_shell(text)
        else:
            continue
        if needs_shell:
            issues.append({'kind': 'inline_shell_expansion',
                           'message': 'Executed source depends on shell expansion.',
                           'start': len(command[:segment['start']].encode()),
                           'end': len(command[:segment['end']].encode())})
            continue
        sources.append({'path': '<inline>' + suffix, 'text': text})
    return {'sources': sources, 'issues': issues}


def invocation_signal(tokens):
    tokens = unwrap(tokens)
    if not tokens:
        return None
    executable, args = Path(tokens[0]).name, tokens[1:]
    kind = None
    # Package managers can invoke installed binaries as well as named scripts.
    # Restrict this wrapper handling to the leading invocation arguments.
    if executable in {"npm", "pnpm", "yarn"}:
        nested = list(args)
        while nested and nested[0].startswith("-"):
            option = nested.pop(0)
            if option in {"--filter", "-F", "--dir", "-C", "--cwd", "--workspace", "-w"} and nested:
                nested.pop(0)
        if nested and nested[0] in {"exec", "dlx", "run"}:
            nested.pop(0)
        if nested and nested[0] in {"pytest", "jest", "vitest", "mocha", "ava", "tap", "tsc", "mypy", "pyright"}:
            signal = invocation_signal(nested)
            return {**signal, "invocation_wrapper": executable, "wrapper_argv": tokens}
    if executable in {"pytest", "py.test", "nosetests", "tox", "nox", "jest", "vitest", "mocha", "ava", "tap", "ctest", "rspec", "phpunit"}:
        kind = "test_runner"
    elif executable in {"go", "cargo", "deno", "dotnet", "bun"} and "test" in args:
        kind = "test_runner"
    elif executable in {"npm", "pnpm", "yarn"} and any(re.fullmatch(r"(?:test|tests|spec)(?::[\w-]+)*", arg) for arg in args):
        kind = "test_script"
    elif executable in {"make", "gmake", "mvn", "mvnw", "gradle", "gradlew", "rake"} and any(re.search(r"(?:^|[:_-])(test|check|spec)s?(?:$|[:_-])", arg) for arg in args):
        kind = "validation_build_target"
    elif executable in {"tsc", "mypy", "pyright"} or executable == "cargo" and "check" in args:
        kind = "static_validation"
    elif re.fullmatch(r"python(?:[23](?:\.\d+)?)?", executable):
        if any(args[index:index + 2] in (["-m", "pytest"], ["-m", "unittest"]) for index in range(len(args))):
            kind = "test_runner"
        elif _inline_argument(args, ('-c',)) is not None or "-" in args or any(arg.startswith("<<") for arg in args):
            kind = "inline_executable_script"
        elif any(arg.endswith(".py") for arg in args):
            kind = "script_invocation"
    elif executable in {"node", "nodejs", "tsx", "ts-node", "ruby", "perl", "php", "bash", "sh", "zsh"}:
        if "--test" in args:
            kind = "test_runner"
        elif _inline_argument(args, ('-e', '-c', '--eval')) is not None or any(
                arg == '-' or arg.startswith('<<') for arg in args):
            kind = "inline_executable_script"
        elif any(re.search(r"\.(?:[cm]?js|tsx?|rb|pl|php|sh)$", arg) for arg in args):
            kind = "script_invocation"
    elif tokens[0].startswith(("./", "/")) and re.search(r"(?:test|spec|\.(?:py|sh|[cm]?js|tsx?)$)", executable, re.I):
        kind = "executable_file_candidate"
    return {"kind": kind, "executable": executable, "lexical_tokens": tokens} if kind else None
