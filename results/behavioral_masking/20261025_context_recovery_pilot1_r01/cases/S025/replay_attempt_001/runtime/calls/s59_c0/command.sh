cd /app && python3 - <<'PY'
p='packages/core/src/prompts/autocomplete.ts'
s=open(p).read()
old = """\t#renderIfActive(): void {
\t\tif (this.state !== 'initial') {
\t\t\tthis.render();
\t\t}
\t}"""
new = """\t#renderIfActive(): void {
\t\tif (this.state === 'initial') {
\t\t\treturn;
\t\t}
\t\t// Defer to a microtask so synchronous keypress handling (state transitions,
\t\t// cursor updates) completes before rendering. The base Prompt also renders
\t\t// after each keypress; if the frame is identical this is a no-op.
\t\tqueueMicrotask(() => {
\t\t\tif (this.state !== 'initial') {
\t\t\t\tthis.render();
\t\t\t}
\t\t});
\t}"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
PY
cd /app/packages/core && pnpm build 2>&1 | tail -3