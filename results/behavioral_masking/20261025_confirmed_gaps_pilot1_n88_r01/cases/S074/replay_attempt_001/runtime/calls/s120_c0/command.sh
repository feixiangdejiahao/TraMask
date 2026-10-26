cd /app && cat > zz_undef_test.go <<'EOF'
package tengo_test

import (
	"testing"

	"github.com/d5/tengo/v2"
)

func TestEdgeUndefinedReturn(t *testing.T) {
	c := runCompiled(t, `f := func() { }`)
	fn := compiledFn(t, c, "f")
	r, err := fn.Call()
	if err != nil { t.Fatal(err) }
	if r != tengo.UndefinedValue { t.Fatalf("got %T %v", r, r) }
}
EOF
go test -run TestEdgeUndefinedReturn -v . 2>&1 | tail -8 && rm zz_undef_test.go