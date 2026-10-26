cd /app && cat > zz_repro5_test.go <<'EOF'
package tengo_test

import (
	"fmt"
	"testing"

	"github.com/d5/tengo/v2"
)

func TestGoCallErrorStack(t *testing.T) {
	src := `
outer := func() {
	return inner()
}
inner := func() {
	return 1 + "x"
}
`
	c := runScript(t, src)
	outer, _ := c.Get("outer").Object().(*tengo.CompiledFunction)
	_, err := outer.Call()
	if err == nil { t.Fatal("expected error") }
	fmt.Println("ERR:\n", err)
}
EOF
go test -run TestGoCallErrorStack -v . 2>&1 | tail -20