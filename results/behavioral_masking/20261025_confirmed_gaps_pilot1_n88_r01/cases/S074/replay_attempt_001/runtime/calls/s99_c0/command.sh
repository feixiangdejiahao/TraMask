cd /app && cat > zz_edge2_test.go <<'EOF'
package tengo_test

import (
	"testing"
)

func TestEdgeRecursiveClosureTransfer(t *testing.T) {
	src := `
mk := func() {
	f := func(n) {
		if n <= 1 { return 1 }
		return n * f(n-1)
	}
	return f
}
f := mk()
`
	c1 := runCompiled(t, src)
	f1 := compiledFn(t, c1, "f")
	c2 := runCompiled(t, src)
	if err := c2.Set("f", f1); err != nil { t.Fatal(err) }
	f2 := compiledFn(t, c2, "f")
	r, err := f2.Call(&tengo.Int{Value: 5})
	if err != nil { t.Fatal(err) }
	t.Log("f2:", r.String())
}
EOF
# fix import: it imports testing only; no tengo needed
go test -run TestEdgeRecursiveClosureTransfer -v . 2>&1 | tail -20