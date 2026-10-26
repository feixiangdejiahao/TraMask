cd /app && python3 - <<'PY'
p='checkers/testdata/brokenDocLink/negative_tests.go'
s=open(p).read()
s=s.replace('''// [github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg.StructType]
// and [github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg.StructType.A]
// are valid package path references.
func ValidPathRefs() {}
''', '''// [github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg.StructType]
// and [github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg.StructType.A]
// are valid package path references.
func ValidPathRefs() {}

// [checker_test.MyType] and [checker_test] are valid self package references.
func ValidSelfRefs() {}
''')
open(p,'w').write(s)
PY
gofmt -w checkers/testdata/brokenDocLink/negative_tests.go && go test ./checkers/ -run 'TestCheckers/brokenDocLink' -count=1 2>&1 | tail -10