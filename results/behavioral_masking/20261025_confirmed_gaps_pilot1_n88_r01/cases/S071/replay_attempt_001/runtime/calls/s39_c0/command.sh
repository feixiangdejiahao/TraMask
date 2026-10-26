cd /app && python3 - <<'PYEOF'
path = 'src/error-stack.ts'
with open(path) as f:
    src = f.read()

old = """function applyMaxStackLines(
  frames: string[],
  maxStackLines: number | undefined
): string[] {
  if (maxStackLines === undefined) {
    return frames;
  }

  // maxStackLines counts the header line, which is kept separately.
  const maxFrames = Math.max(0, maxStackLines - 1);
  return frames.slice(0, maxFrames);
}
"""
new = """function applyMaxStackLines(
  frames: string[],
  maxStackLines: number | undefined
): string[] {
  if (maxStackLines === undefined) {
    return frames;
  }

  // maxStackLines counts the header line, which is kept separately.
  const maxFrames = Math.max(0, maxStackLines - 1);
  return frames.slice(0, maxFrames);
}

function splitStack(stack: string, normalizeNewlines: boolean): string[] {
  const normalized = normalizeNewlines ? normalizeStackNewlines(stack) : stack;
  const lines = normalized.split('\\n');

  // Drop trailing empty lines so a trailing CRLF/CR/LF does not create an
  // artificial empty frame.
  while (lines.length > 1 && lines[lines.length - 1] === '') {
    lines.pop();
  }

  return lines;
}
"""
assert old in src
src = src.replace(old, new)

old2 = """  const normalized = options.normalizeNewlines
    ? normalizeStackNewlines(stack)
    : stack;
  const lines = normalized.split('\\n');
  const header = lines[0] ?? '';
  let frames = lines.slice(1);

  if (options.trimLeadingWhitespace) {
    frames = frames.map(trimLeadingWhitespace);
  }

  if (options.redactPaths !== 'none') {
    frames = frames.map((frame) => redactPath(frame, options.redactPaths));
  }

  frames = applyMaxStackLines(frames, options.maxStackLines);

  frames = stripInternalFrames(frames, options.stripInternalFrames);

  return [header, ...frames].join('\\n');"""
new2 = """  const lines = splitStack(stack, options.normalizeNewlines);
  const header = lines[0] ?? '';
  let frames = lines.slice(1);

  if (options.trimLeadingWhitespace) {
    frames = frames.map(trimLeadingWhitespace);
  }

  if (options.redactPaths !== 'none') {
    frames = frames.map((frame) => redactPath(frame, options.redactPaths));
  }

  frames = applyMaxStackLines(frames, options.maxStackLines);

  frames = stripInternalFrames(frames, options.stripInternalFrames);

  return [header, ...frames].join('\\n');"""
assert old2 in src
src = src.replace(old2, new2)

old3 = """  const normalized = options.normalizeNewlines
    ? normalizeStackNewlines(stack)
    : stack;
  const lines = normalized.split('\\n');
  const header = lines[0] ?? '';
  let frames = lines.slice(1);

  if (options.trimLeadingWhitespace) {
    frames = frames.map(trimLeadingWhitespace);
  }

  frames = stripInternalFrames(frames, options.stripInternalFrames);

  if (options.redactPaths !== 'none') {
    frames = frames.map((frame) => redactPath(frame, options.redactPaths));
  }

  frames = applyMaxStackLines(frames, options.maxStackLines);

  return [{ raw: header }, ...frames.map((frame) => ({ raw: frame }))];"""
new3 = """  const lines = splitStack(stack, options.normalizeNewlines);
  const header = lines[0] ?? '';
  let frames = lines.slice(1);

  if (options.trimLeadingWhitespace) {
    frames = frames.map(trimLeadingWhitespace);
  }

  frames = stripInternalFrames(frames, options.stripInternalFrames);

  if (options.redactPaths !== 'none') {
    frames = frames.map((frame) => redactPath(frame, options.redactPaths));
  }

  frames = applyMaxStackLines(frames, options.maxStackLines);

  return [{ raw: header }, ...frames.map((frame) => ({ raw: frame }))];"""
assert old3 in src
src = src.replace(old3, new3)

with open(path, 'w') as f:
    f.write(src)
print('patched')
PYEOF
npx vitest run src/error-stack.test.ts 2>&1 | tail -20