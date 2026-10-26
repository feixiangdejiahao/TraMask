cd /app && python3 - <<'PY'
lines = open('checkers/brokenDocLink_checker.go').read().split('\n')
# Find start and end of validDocLinkRef
start = next(i for i,l in enumerate(lines) if l.startswith('func validDocLinkRef('))
end = next(i for i,l in enumerate(lines) if i>start and l.startswith('func validPackageRef('))
new_funcs = '''func validDocLinkText(ref string) bool {
	if ref == "" || strings.ContainsAny(ref, " \\t\\n") {
		return false
	}
	ref = strings.TrimPrefix(ref, "*")
	return ref != ""
}

func validIdentifier(name string) bool {
	return token.IsIdentifier(name)
}
'''.split('\n')
lines[start:end] = new_funcs
open('checkers/brokenDocLink_checker.go','w').write('\n'.join(lines))
PY
gofmt -w checkers/brokenDocLink_checker.go && go build ./... 2>&1 | head -30 && echo BUILD_OK