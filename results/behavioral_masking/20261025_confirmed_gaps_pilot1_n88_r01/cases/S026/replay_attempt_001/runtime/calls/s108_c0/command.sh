cd /app && python3 - <<'PY'
p='checkers/testdata/brokenDocLink/negative_tests.go'
s=open(p).read()
s=s.replace('''// [fmt.Println], [strings.Builder] and [str.ToUpper] are valid qualified refs.
func ValidQualified() {}
''', '''// [fmt.Println], [strings.Builder], [strings.Builder.Reset],
// [strings.Reader.Read], [strings.Reader.Len] and [str.ToUpper] are valid.
func ValidQualified() {}
''')
open(p,'w').write(s)
PY
gofmt -w checkers/testdata/brokenDocLink/negative_tests.go && go test ./checkers/ -run 'TestCheckers/brokenDocLink' -count=1 2>&1 | tail -10