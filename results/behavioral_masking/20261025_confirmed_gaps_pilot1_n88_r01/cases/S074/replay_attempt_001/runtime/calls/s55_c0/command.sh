cd /app && cat > zz_repro2_test.go <<'EOF'
package tengo_test

import (
	"fmt"
	"testing"

	"github.com/d5/tengo/v2"
)

func runScript(t *testing.T, src string) *tengo.Compiled {
	t.Helper()
	c, err := tengo.NewScript([]byte(src)).Run()
	if err != nil { t.Fatalf("run: %v", err) }
	return c
}

func TestGoCallBasic(t *testing.T) {
	c := runScript(t, `
add := func(a, b) { return a + b }
out := add(1, 2)
`)
	fn, _ := c.Get("add").Object().(*tengo.CompiledFunction)
	ret, err := fn.Call(&tengo.Int{Value: 40}, &tengo.Int{Value: 2})
	if err != nil { t.Fatal(err) }
	if ret.String() != "42" { t.Fatalf("got %s", ret) }
}

func TestGoCallRecursion(t *testing.T) {
	c := runScript(t, `
fact := func(n) {
	if n <= 1 { return 1 }
	return n * fact(n-1)
}
`)
	fn, _ := c.Get("fact").Object().(*tengo.CompiledFunction)
	ret, err := fn.Call(&tengo.Int{Value: 10})
	if err != nil { t.Fatal(err) }
	if ret.String() != "3628800" { t.Fatalf("got %s", ret) }
}

func TestGoCallVariadic(t *testing.T) {
	c := runScript(t, `
sum := func(a, args...) {
	s := a
	for _, x in args { s += x }
	return s
}
`)
	fn, _ := c.Get("sum").Object().(*tengo.CompiledFunction)
	ret, err := fn.Call(&tengo.Int{Value: 1}, &tengo.Int{Value: 2}, &tengo.Int{Value: 3})
	if err != nil { t.Fatal(err) }
	if ret.String() != "6" { t.Fatalf("got %s", ret) }
}

func TestGoCallReturnedClosure(t *testing.T) {
	c := runScript(t, `
make := func(x) {
	return func(y) { return x + y }
}
f := make(10)
`)
	makeFn, _ := c.Get("make").Object().(*tengo.CompiledFunction)
	ret, err := makeFn.Call(&tengo.Int{Value: 10})
	if err != nil { t.Fatal(err) }
	inner, ok := ret.(*tengo.CompiledFunction)
	if !ok { t.Fatalf("ret type %T", ret) }
	ret2, err := inner.Call(&tengo.Int{Value: 32})
	if err != nil { t.Fatal(err) }
	if ret2.String() != "42" { t.Fatalf("got %s", ret2) }
}

func TestGoCallErrorFormat(t *testing.T) {
	c := runScript(t, `
boom := func() { return 1 + "x" }
`)
	fn, _ := c.Get("boom").Object().(*tengo.CompiledFunction)
	_, err := fn.Call()
	if err == nil { t.Fatal("expected error") }
	fmt.Println("ERR:", err)
}

func TestGoCallCallbackArg(t *testing.T) {
	// Go builtin calls a script function passed as argument
	caller := func(args ...tengo.Object) (tengo.Object, error) {
		fn := args[0].(*tengo.CompiledFunction)
		return fn.Call(&tengo.Int{Value: 20})
	}
	s := tengo.NewScript([]byte(`
caller := func(fn) { return fn(5) }
gcall := import("gcall")
out := gcall.f(caller)
`))
	mods := tengo.NewModuleMap()
	mods.AddBuiltinModule("gcall", map[string]tengo.Object{
		"f": &tengo.UserFunction{Name: "f", Value: caller},
	})
	s.SetImports(mods)
	c, err := s.Run()
	if err != nil { t.Fatal(err) }
	// Actually test that script passes a function to Go which calls it.
	_ = c
}

func TestGoCallTransferIsolation(t *testing.T) {
	src1 := `
g := 10
counter := func() {
	n := 0
	return func() { n++; return g + n }
}
f := counter()
f()
f()
`
	s2src := `
out := f()
`
	c1 := runScript(t, src1)
	fn, _ := c1.Get("f").Object().(*tengo.CompiledFunction)

	// transfer to c2
	s2 := tengo.NewScript([]byte(s2src))
	if err := s2.Add("f", fn); err != nil { t.Fatal(err) }
	c2, err := s2.Run()
	if err != nil { t.Fatal(err) }

	// c1's f still has n=2, g=10 -> 12
	ret1, err := fn.Call()
	if err != nil { t.Fatal(err) }
	if ret1.String() != "12" { t.Fatalf("c1 got %s", ret1) }

	// c2's f should snapshot n=2 but resolve g against c2.
	// But c2 script assigns f() to out before we can call it.
	_ = c2
	// Let's instead directly call c2.Get("f")
	// Actually c2's script references f, so f must be defined in c2's globals.
	_ = c2
}

func TestGoCallCloneIsolation(t *testing.T) {
	c1 := runScript(t, `
g := 5
mk := func() {
	n := 0
	return func() { n++; return g + n }
}
f := mk()
f()
`)
	c2 := c1.Clone()
	f1, _ := c1.Get("f").Object().(*tengo.CompiledFunction)
	f2, _ := c2.Get("f").Object().(*tengo.CompiledFunction)
	// mutate clone global g
	if err := c2.Set("g", 100); err != nil { t.Fatal(err) }
	// f2 should use clone's g=100, n snapshot=1 -> 101
	ret2, err := f2.Call()
	if err != nil { t.Fatal(err) }
	if ret2.String() != "101" { t.Fatalf("clone got %s", ret2) }
	// f1 should use c1's g=5, n=1 -> 6
	ret1, err := f1.Call()
	if err != nil { t.Fatal(err) }
	if ret1.String() != "6" { t.Fatalf("source got %s", ret1) }
}
EOF
go test -run 'TestGoCall' -v . 2>&1 | tail -60