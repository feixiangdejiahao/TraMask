cd /app && cat > /tmp/repro_test.go <<'EOF'
package tengo_test

import (
	"fmt"
	"testing"

	"github.com/d5/tengo/v2"
)

func TestClosureGlobal(t *testing.T) {
	src := []byte(`
x := 5
make := func() {
	y := 10
	return func() { return x + y }
}
out = make()
`)
	s := tengo.NewScript(src)
	if err := s.Add("x", 100); err != nil { t.Fatal(err) }
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
mkdir -p /tmp/repro && cp /tmp/repro_test.go /tmp/repro/ && cd /app && go test -run TestClosureGlobal -v . 2>&1 | tail -30