cd /app && cat > zz_repro3_test.go <<'EOF'
package tengo_test

import (
	"testing"

	"github.com/d5/tengo/v2"
)

func TestGoCallCompositeReturn(t *testing.T) {
	c := runScript(t, `
mk := func(x) {
	f1 := func(y) { return x + y }
	f2 := func(y) { return x * y }
	return [f1, f2]
}
`)
	fn, _ := c.Get("mk").Object().(*tengo.CompiledFunction)
	ret, err := fn.Call(&tengo.Int{Value: 10})
	if err != nil { t.Fatal(err) }
	arr, ok := ret.(*tengo.Array)
	if !ok { t.Fatalf("type %T", ret) }
	if len(arr.Value) != 2 { t.Fatalf("len %d", len(arr.Value)) }
	f1 := arr.Value[0].(*tengo.CompiledFunction)
	f2 := arr.Value[1].(*tengo.CompiledFunction)
	r1, _ := f1.Call(&tengo.Int{Value: 5})
	if r1.String() != "15" { t.Fatalf("f1 %s", r1) }
	r2, _ := f2.Call(&tengo.Int{Value: 5})
	if r2.String() != "50" { t.Fatalf("f2 %s", r2) }
}

func TestGoCallNestedTransferIsolation(t *testing.T) {
	src := `
g := 5
mk := func(x) {
	n := 0
	inc := func() { n++; return g + n + x }
	return [inc, { "inc": inc }]
}
data := mk(100)
`
	c1 := runScript(t, src)
	src2 := `
out := 1
`
	c2 := runScript(t, src2)
	if err := c2.Set("data", c1.Get("data").Object()); err != nil { t.Fatal(err) }
	if err := c2.Set("g", 50); err != nil { t.Fatal(err) }

	arrObj := c2.Get("data").Object()
	arr, ok := arrObj.(*tengo.Array)
	if !ok { t.Fatalf("type %T", arrObj) }
	incArr := arr.Value[0].(*tengo.CompiledFunction)
	r, err := incArr.Call()
	if err != nil { t.Fatal(err) }
	if r.String() != "151" { t.Fatalf("arr inc got %s (want 50+1+100)", r) }

	m, ok := arr.Value[1].(*tengo.Map)
	if !ok { t.Fatalf("map type %T", arr.Value[1]) }
	incMap := m.Value["inc"].(*tengo.CompiledFunction)
	r2, err := incMap.Call()
	if err != nil { t.Fatal(err) }
	if r2.String() != "152" { t.Fatalf("map inc got %s", r2) }
}

func TestGoCallSourceModuleExport(t *testing.T) {
	src := `
mod := import("mymod")
f := mod.add
g := 10
`
	modsrc := `
x := 1
add := func(a, b) { return a + b + x }
export { "add": add }
`
	s := tengo.NewScript([]byte(src))
	mods := tengo.NewModuleMap()
	mods.AddSourceModule("mymod", []byte(modsrc))
	s.SetImports(mods)
	c, err := s.Run()
	if err != nil { t.Fatal(err) }
	fn, ok := c.Get("f").Object().(*tengo.CompiledFunction)
	if !ok { t.Fatalf("type %T", c.Get("f").Object()) }
	ret, err := fn.Call(&tengo.Int{Value: 20}, &tengo.Int{Value: 21})
	if err != nil { t.Fatal(err) }
	if ret.String() != "42" { t.Fatalf("got %s", ret) }
}

func TestGoCallImportInside(t *testing.T) {
	src := `
math := import("math")
use := func(x) { return math.abs(x) }
`
	s := tengo.NewScript([]byte(src))
	s.SetImports(stdlibmod())
	c, err := s.Run()
	if err != nil { t.Fatal(err) }
	fn, _ := c.Get("use").Object().(*tengo.CompiledFunction)
	ret, err := fn.Call(&tengo.Int{Value: -42})
	if err != nil { t.Fatal(err) }
	if ret.String() != "42" { t.Fatalf("got %s", ret) }
}

func TestGoCallGlobalMutation(t *testing.T) {
	src := `
g := 5
bump := func() { g += 10; return g }
`
	c := runScript(t, src)
	fn, _ := c.Get("bump").Object().(*tengo.CompiledFunction)
	r1, err := fn.Call()
	if err != nil { t.Fatal(err) }
	if r1.String() != "15" { t.Fatalf("r1 %s", r1) }
	r2, _ := fn.Call()
	if r2.String() != "25" { t.Fatalf("r2 %s", r2) }
	if got := c.Get("g").Int(); got != 15 { t.Fatalf("g %d", got) }
}

func TestGoCallWrongArgs(t *testing.T) {
	c := runScript(t, `add := func(a, b) { return a + b }`)
	fn, _ := c.Get("add").Object().(*tengo.CompiledFunction)
	_, err := fn.Call(&tengo.Int{Value: 1})
	if err == nil { t.Fatal("expected error") }
	c2 := runScript(t, `v := func(a, ...rest) { return len(rest) }`)
	fn2, _ := c2.Get("v").Object().(*tengo.CompiledFunction)
	_, err = fn2.Call()
	if err == nil { t.Fatal("expected error for missing required arg") }
}

func TestGoCallClosureSharingWithinInstance(t *testing.T) {
	// two closures capturing the same local must stay shared in-script
	src := `
mk := func() {
	n := 0
	inc := func() { n++; return n }
	get := func() { return n }
	return [inc, get]
}
pair := mk()
inc := pair[0]
get := pair[1]
inc()
inc()
out := get()
`
	c := runScript(t, src)
	if got := c.Get("out").Int(); got != 2 { t.Fatalf("out %d", got) }
	incFn, _ := c.Get("inc").Object().(*tengo.CompiledFunction)
	getFn, _ := c.Get("get").Object().(*tengo.CompiledFunction)
	// Go-side call: inc increments shared n to 3, get sees 3
	if _, err := incFn.Call(); err != nil { t.Fatal(err) }
	r, err := getFn.Call()
	if err != nil { t.Fatal(err) }
	if r.String() != "3" { t.Fatalf("get %s", r) }
}

func TestGoCallCloneNested(t *testing.T) {
	src := `
g := 5
mk := func() {
	n := 0
	return func() { n++; return g + n }
}
f := mk()
f()
data := [f]
`
	c1 := runScript(t, src)
	c2 := c1.Clone()
	if err := c2.Set("g", 100); err != nil { t.Fatal(err) }
	arr2 := c2.Get("data").Object().(*tengo.Array)
	f2 := arr2.Value[0].(*tengo.CompiledFunction)
	r, err := f2.Call()
	if err != nil { t.Fatal(err) }
	if r.String() != "102" { t.Fatalf("clone %s", r) }
}
EOF
python3 - <<'PYEOF'
p='zz_repro3_test.go'
s=open(p).read()
s=s.replace('s.SetImports(stdlibmod())', 's.SetImports(tengo.NewModuleMap().AddBuiltinModule? NO)')
open(p,'w').write(s)
PYEOF
echo "need stdlib import"