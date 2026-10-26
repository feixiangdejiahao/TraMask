cd /app && python3 - <<'PY'
# negative: add generic type
p='checkers/testdata/brokenDocLink/negative_tests.go'
s=open(p).read()
s=s.replace('''func (MyType) N() {}
''', '''func (MyType) N() {}

type Box[T any] struct{}

func (b *Box[T]) Put(x T) {}
''')
s=s.replace('''// [IntSlice.Sort] is a valid method reference on a dot-imported type.
func ValidDotTypeMethod() {}
''', '''// [IntSlice.Sort] is a valid method reference on a dot-imported type.
func ValidDotTypeMethod() {}

// [Box.Put] is a valid pointer-receiver method on a generic type.
func ValidGenericMethod() {}
''')
open(p,'w').write(s)

# positive: add broken generic member
p='checkers/testdata/brokenDocLink/positive_tests.go'
s=open(p).read()
s=s.replace('''// DotTypeMemberMissing is an example.
/*! [IntSlice.Missing]: type "IntSlice" has no method or field "Missing" */
func DotTypeMemberMissing() {}
''', '''// DotTypeMemberMissing is an example.
/*! [IntSlice.Missing]: type "IntSlice" has no method or field "Missing" */
func DotTypeMemberMissing() {}

// GenericMemberMissing is an example.
/*! [Box.Missing]: type "Box" has no method or field "Missing" */
func GenericMemberMissing() {}
''')
open(p,'w').write(s)
PY
gofmt -w checkers/testdata/brokenDocLink/positive_tests.go checkers/testdata/brokenDocLink/negative_tests.go && go test ./checkers/ -run 'TestCheckers/brokenDocLink' -count=1 2>&1 | tail -10