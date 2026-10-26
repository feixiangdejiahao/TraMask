cd /app && cat > zz_repro_test.go <<'EOF'
package tengo_test

import (
	"fmt"
	"testing"

	"github.com/d5/tengo/v2"
)

func TestClosureGlobalRepro(t *testing.T) {
	src := []byte(`
g := 5
make := func() {
	y := 10
	return func() { return g + y }
}
out = make()
`)
	s := tengo.NewScript(src)
	if err := s.Add("g", 100); err != nil { t.Fatal(err) }
	c, err := s.Run()
	if err != nil { t.Fatal(err) }
	v := c.Get("out")
	fn, ok := v.Object().(*tengo.CompiledFunction)
	if !ok { t.Fatalf("not function: %T", v.Object()) }
	fmt.Println("CanCall:", fn.CanCall())
	ret, err := fn.Call()
	fmt.Println("call ret:", ret, "err:", err)
}
EOF
go test -run TestClosureGlobalRepro -v . 2>&1 | tail -30