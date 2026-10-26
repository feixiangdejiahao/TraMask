cd /app && python3 - <<'PY'
p='checkers/testdata/brokenDocLink/negative_tests.go'
s=open(p).read()
s=s.replace('''// Go builtins are not flagged: [int], [string], [len], [error], [any].
func ValidBuiltins() {}
''', '''// Go builtins are not flagged: [int], [string], [len], [error], [any].
func ValidBuiltins() {}

// Standard library package links are valid even without an import:
// [math] and [math.Sin].
func ValidStdlibRefs() {}
''')
open(p,'w').write(s)
PY
gofmt -w checkers/testdata/brokenDocLink/negative_tests.go && go test ./checkers/ -run 'TestCheckers/brokenDocLink' -count=1 2>&1 | tail -10