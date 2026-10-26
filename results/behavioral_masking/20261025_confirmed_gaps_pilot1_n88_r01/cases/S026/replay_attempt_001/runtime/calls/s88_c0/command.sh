cd /app && python3 - <<'PY'
# negative test: add pointer embedding
p='checkers/testdata/brokenDocLink/negative_tests.go'
s=open(p).read()
s=s.replace('''type Embedded struct{ Base }
''', '''type Embedded struct{ Base }

type PtrEmbed struct{ *Base }
''')
s=s.replace('''// [Embedded.X] and [Embedded.M] are promoted members.
func ValidEmbedded() {}
''', '''// [Embedded.X], [Embedded.M] and [PtrEmbed.X] are promoted members.
func ValidEmbedded() {}
''')
open(p,'w').write(s)

# checker: add \r to whitespace
p='checkers/brokenDocLink_checker.go'
s=open(p).read()
s=s.replace('''	if ref == "" || strings.ContainsAny(ref, " \\t\\n") {
''', '''	if ref == "" || strings.ContainsAny(ref, " \\t\\n\\r") {
''')
open(p,'w').write(s)
PY
gofmt -w checkers/brokenDocLink_checker.go checkers/testdata/brokenDocLink/negative_tests.go && go test ./checkers/ -run 'TestCheckers/brokenDocLink' -count=1 2>&1 | tail -10