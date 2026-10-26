cd /app && python3 - <<'PY'
p='checkers/testdata/brokenDocLink/positive_tests.go'
s=open(p).read()
s=s.replace('var myVar int', 'var MyVar int')
s=s.replace('''// NonTypeLocal is an example.
/*! [myVar.Field]: "myVar" is not a type */
func NonTypeLocal() {}
''', '''// NonTypeLocal is an example.
/*! [MyVar.Field]: "MyVar" is not a type */
func NonTypeLocal() {}
''')
open(p,'w').write(s)
PY
go test ./checkers/ -run 'TestCheckers/brokenDocLink' -count=1 2>&1 | head -80