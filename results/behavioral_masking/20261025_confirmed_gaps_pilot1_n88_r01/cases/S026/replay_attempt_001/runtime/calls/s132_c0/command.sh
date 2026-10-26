cd /app && python3 - <<'PY'
# negative
p='checkers/testdata/brokenDocLink/negative_tests.go'
s=open(p).read()
s=s.replace('''type Box[T any] struct{}

func (b *Box[T]) Put(x T) {}
''', '''type Box[T any] struct{}

func (b *Box[T]) Put(x T) {}

type AliasType = MyType
''')
s=s.replace('''// [Box.Put] is a valid pointer-receiver method on a generic type.
func ValidGenericMethod() {}
''', '''// [Box.Put] is a valid pointer-receiver method on a generic type.
func ValidGenericMethod() {}

// [AliasType.Y] and [AliasType.N] are valid members of a type alias.
func ValidAlias() {}
''')
open(p,'w').write(s)

# positive
p='checkers/testdata/brokenDocLink/positive_tests.go'
s=open(p).read()
s=s.replace('''// GenericMemberMissing is an example.
/*! [Box.Missing]: type "Box" has no method or field "Missing" */
func GenericMemberMissing() {}
''', '''// GenericMemberMissing is an example.
/*! [Box.Missing]: type "Box" has no method or field "Missing" */
func GenericMemberMissing() {}

// AliasMemberMissing is an example.
/*! [AliasType.Missing]: type "AliasType" has no method or field "Missing" */
func AliasMemberMissing() {}
''')
open(p,'w').write(s)
PY
gofmt -w checkers/testdata/brokenDocLink/positive_tests.go checkers/testdata/brokenDocLink/negative_tests.go && go test ./checkers/ -run 'TestCheckers/brokenDocLink' -count=1 2>&1 | tail -10