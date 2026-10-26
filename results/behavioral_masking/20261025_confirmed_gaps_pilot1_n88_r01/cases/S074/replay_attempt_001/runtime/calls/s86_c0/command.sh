cd /app && cat > zz_repro4_test.go <<'EOF'
package tengo_test

import (
	"strings"
	"testing"

	"github.com/d5/tengo/v2"
)

func TestGoCallDeepRecursion(t *testing.T) {
	src := `
fib := func(n) {
	if n < 2 { return n }
	return fib(n-1) + fib(n-2)
}
`
	c := runScript(t, src)
	fn, _ := c.Get("fib").Object().(*tengo.CompiledFunction)
	ret, err := fn.Call(&tengo.Int{Value: 20})
	if err != nil { t.Fatal(err) }
	if ret.String() != "6765" { t.Fatalf("got %s", ret) }
}

func TestGoCallMaxAllocs(t *testing.T) {
	s := tengo.NewScript([]byte(`
mk := func() {
	x := 0
	x++
	return x
}
`))
	s.SetMaxAllocs(0) // only 0 allocations allowed
	c, err := s.Run()
	if err != nil { t.Fatal(err) }
	fn, _ := c.Get("mk").Object().(*tengo.CompiledFunction)
	_, err = fn.Call()
	if err == nil { t.Fatal("expected alloc limit error") }
	if !strings.Contains(err.Error(), "object allocation limit exceeded") {
		t.Fatalf("err: %v", err)
	}
}

func TestGoCallReturnMapWithClosures(t *testing.T) {
	src := `
mk := func(x) {
	inc := func(y) { return x + y }
	return { "inc": inc, "x": x }
}
`
	c := runScript(t, src)
	fn, _ := c.Get("mk").Object().(*tengo.CompiledFunction)
	ret, err := fn.Call(&tengo.Int{Value: 40})
	if err != nil { t.Fatal(err) }
	m, ok := ret.(*tengo.Map)
	if !ok { t.Fatalf("type %T", ret) }
	inc := m.Value["inc"].(*tengo.CompiledFunction)
	r, err := inc.Call(&tengo.Int{Value: 2})
	if err != nil { t.Fatal(err) }
	if r.String() != "42" { t.Fatalf("got %s", r) }
}

func TestGoCallRunAfter(t *testing.T) {
	src := `
g := 1
bump := func() { g += 1 }
`
	c := runScript(t, src)
	fn, _ := c.Get("bump").Object().(*tengo.CompiledFunction)
	if _, err := fn.Call(); err != nil { t.Fatal(err) }
	if got := c.Get("g").Int(); got != 2 { t.Fatalf("g=%d", got) }
	// re-run the script (resets g to 1)
	if err := c.Run(); err != nil { t.Fatal(err) }
	if got := c.Get("g").Int(); got != 1 { t.Fatalf("after rerun g=%d", got) }
}
EOF
go test -run 'TestGoCall' -v . 2>&1 | tail -60