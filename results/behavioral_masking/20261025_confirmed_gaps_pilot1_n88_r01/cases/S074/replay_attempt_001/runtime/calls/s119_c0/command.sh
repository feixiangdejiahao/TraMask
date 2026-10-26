cd /app && cat > zz_variadic_test.go <<'EOF'
package tengo_test

import (
	"testing"

	"github.com/d5/tengo/v2"
)

func TestEdgeVariadicNoFixed(t *testing.T) {
	c := runCompiled(t, `
cnt := func(...args) { return len(args) }
`)
	fn := compiledFn(t, c, "cnt")
	r, err := fn.Call(&tengo.Int{Value: 1}, &tengo.Int{Value: 2})
	if err != nil { t.Fatal(err) }
	if r.String() != "2" { t.Fatalf("got %s", r) }
	r2, err := fn.Call()
	if err != nil { t.Fatal(err) }
	if r2.String() != "0" { t.Fatalf("got %s", r2) }
}
EOF
go test -run TestEdgeVariadicNoFixed -v . 2>&1 | tail -10 && rm zz_variadic_test.go