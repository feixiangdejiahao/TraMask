cd /app && cat > zz_edge_test.go <<'EOF'
package tengo_test

import (
	"testing"

	"github.com/d5/tengo/v2"
)

func TestEdgeNestedClosureCapture(t *testing.T) {
	src := `
mk := func() {
	n := 0
	inc := func() { n++; return n }
	outer := func() { return inc() }
	return outer
}
f := mk()
f()
`
	c1 := runCompiled(t, src)
	f1 := compiledFn(t, c1, "f")
	c2 := runCompiled(t, src)
	if err := c2.Set("f", f1); err != nil { t.Fatal(err) }
	f2 := compiledFn(t, c2, "f")

	// after f() once, n=1. transferring should snapshot n=1.
	// calling f2 should make n=2 and return 2; calling f1 should make its n=2 and return 2.
	r2, err := f2.Call()
	if err != nil { t.Fatal(err) }
	t.Log("f2:", r2.String())
	r1, err := f1.Call()
	if err != nil { t.Fatal(err) }
	t.Log("f1:", r1.String())
}
EOF
go test -run TestEdgeNestedClosureCapture -v . 2>&1 | tail -20