cd /app && python3 - <<'PY'
p='checkers/testdata/brokenDocLink/negative_tests.go'
s=open(p).read()
s=s.replace('''// Valid local symbol references.
/*! This is not a link. */
func ValidLocal() {}
''', '''// [MyType] is a valid local symbol reference.
func ValidLocal() {}
''')
open(p,'w').write(s)
PY
cat checkers/testdata/brokenDocLink/negative_tests.go