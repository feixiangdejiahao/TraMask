cd /app && cat > checkers/testdata/brokenDocLink/types.go <<'EOF'
package checker_test

type Base struct{ X int }

func (Base) M() {}

type Embedded struct{ Base }

type PtrEmbed struct{ *Base }

type MyType struct {
	Embedded
	Y int
}

func (MyType) N() {}

type Box[T any] struct{}

func (b *Box[T]) Put(x T) {}

type AliasType = MyType
EOF
python3 - <<'PY'
# remove shared types from negative
p='checkers/testdata/brokenDocLink/negative_tests.go'
s=open(p).read()
s=s.replace('''type Base struct{ X int }

func (Base) M() {}

type Embedded struct{ Base }

type PtrEmbed struct{ *Base }

type MyType struct {
	Embedded
	Y int
}

func (MyType) N() {}

type Box[T any] struct{}

func (b *Box[T]) Put(x T) {}

type AliasType = MyType

''', '')
open(p,'w').write(s)
PY
gofmt -w checkers/testdata/brokenDocLink/types.go checkers/testdata/brokenDocLink/negative_tests.go && go test ./checkers/ -run 'TestCheckers/brokenDocLink' -count=1 2>&1 | tail -10