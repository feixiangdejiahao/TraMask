package tengo_test

import (
	"strings"
	"testing"

	"github.com/d5/tengo/v2"
	"github.com/d5/tengo/v2/stdlib"
)

func runCompiled(t *testing.T, src string) *tengo.Compiled {
	t.Helper()
	c, err := tengo.NewScript([]byte(src)).Run()
	if err != nil {
		t.Fatalf("run: %v", err)
	}
	return c
}

func compiledFn(
	t *testing.T,
	c *tengo.Compiled,
	name string,
) *tengo.CompiledFunction {
	t.Helper()
	fn, ok := c.Get(name).Object().(*tengo.CompiledFunction)
	if !ok {
		t.Fatalf("variable %q is %T, not *CompiledFunction", name,
			c.Get(name).Object())
	}
	return fn
}

func TestCompiledFunctionCallBasic(t *testing.T) {
	c := runCompiled(t, `
add := func(a, b) { return a + b }
out := add(1, 2)
`)
	ret, err := compiledFn(t, c, "add").Call(
		&tengo.Int{Value: 40}, &tengo.Int{Value: 2})
	if err != nil {
		t.Fatal(err)
	}
	if got := ret.String(); got != "42" {
		t.Fatalf("got %s, want 42", got)
	}
}

func TestCompiledFunctionCallRecursion(t *testing.T) {
	c := runCompiled(t, `
fact := func(n) {
	if n <= 1 { return 1 }
	return n * fact(n-1)
}
`)
	ret, err := compiledFn(t, c, "fact").Call(&tengo.Int{Value: 10})
	if err != nil {
		t.Fatal(err)
	}
	if got := ret.String(); got != "3628800" {
		t.Fatalf("got %s, want 3628800", got)
	}
}

func TestCompiledFunctionCallVariadic(t *testing.T) {
	c := runCompiled(t, `
sum := func(a, ...args) {
	s := a
	for _, x in args { s += x }
	return s
}
`)
	ret, err := compiledFn(t, c, "sum").Call(
		&tengo.Int{Value: 1}, &tengo.Int{Value: 2}, &tengo.Int{Value: 3})
	if err != nil {
		t.Fatal(err)
	}
	if got := ret.String(); got != "6" {
		t.Fatalf("got %s, want 6", got)
	}

	// too few arguments
	_, err = compiledFn(t, c, "sum").Call()
	if err == nil {
		t.Fatal("expected argument-count error")
	}
}

func TestCompiledFunctionCallClosure(t *testing.T) {
	c := runCompiled(t, `
g := 5
make := func() {
	y := 10
	return func() { return g + y }
}
f := make()
`)
	ret, err := compiledFn(t, c, "f").Call()
	if err != nil {
		t.Fatal(err)
	}
	if got := ret.String(); got != "15" {
		t.Fatalf("got %s, want 15", got)
	}
}

func TestCompiledFunctionCallReturnedClosure(t *testing.T) {
	c := runCompiled(t, `
make := func(x) {
	return func(y) { return x + y }
}
f := make(10)
`)
	ret, err := compiledFn(t, c, "make").Call(&tengo.Int{Value: 10})
	if err != nil {
		t.Fatal(err)
	}
	inner, ok := ret.(*tengo.CompiledFunction)
	if !ok {
		t.Fatalf("returned value is %T, not *CompiledFunction", ret)
	}
	r, err := inner.Call(&tengo.Int{Value: 32})
	if err != nil {
		t.Fatal(err)
	}
	if got := r.String(); got != "42" {
		t.Fatalf("got %s, want 42", got)
	}
}

func TestCompiledFunctionCallReturnedComposite(t *testing.T) {
	c := runCompiled(t, `
mk := func(x) {
	inc := func(y) { return x + y }
	mul := func(y) { return x * y }
	return [inc, { "mul": mul }]
}
`)
	ret, err := compiledFn(t, c, "mk").Call(&tengo.Int{Value: 10})
	if err != nil {
		t.Fatal(err)
	}
	arr, ok := ret.(*tengo.Array)
	if !ok {
		t.Fatalf("returned value is %T, want *Array", ret)
	}
	inc := arr.Value[0].(*tengo.CompiledFunction)
	if r, _ := inc.Call(&tengo.Int{Value: 5}); r.String() != "15" {
		t.Fatalf("inc returned %s", r)
	}
	m, ok := arr.Value[1].(*tengo.Map)
	if !ok {
		t.Fatalf("map is %T", arr.Value[1])
	}
	mul := m.Value["mul"].(*tengo.CompiledFunction)
	if r, _ := mul.Call(&tengo.Int{Value: 5}); r.String() != "50" {
		t.Fatalf("mul returned %s", r)
	}
}

func TestCompiledFunctionCallFromGoCallback(t *testing.T) {
	apply := func(args ...tengo.Object) (tengo.Object, error) {
		fn := args[0].(*tengo.CompiledFunction)
		return fn.Call(args[1])
	}
	s := tengo.NewScript([]byte(`
double := func(x) { return x * 2 }
gcall := import("gcall")
out := gcall.apply(double, 21)
`))
	mods := tengo.NewModuleMap()
	mods.AddBuiltinModule("gcall", map[string]tengo.Object{
		"apply": &tengo.UserFunction{Name: "apply", Value: apply},
	})
	s.SetImports(mods)
	c, err := s.Run()
	if err != nil {
		t.Fatal(err)
	}
	if got := c.Get("out").Int(); got != 42 {
		t.Fatalf("got %d, want 42", got)
	}
}

func TestCompiledFunctionCallSourceModuleExport(t *testing.T) {
	s := tengo.NewScript([]byte(`
mod := import("mymod")
f := mod.add
`))
	mods := tengo.NewModuleMap()
	mods.AddSourceModule("mymod", []byte(`
x := 1
add := func(a, b) { return a + b + x }
export { "add": add }
`))
	s.SetImports(mods)
	c, err := s.Run()
	if err != nil {
		t.Fatal(err)
	}
	ret, err := compiledFn(t, c, "f").Call(
		&tengo.Int{Value: 20}, &tengo.Int{Value: 21})
	if err != nil {
		t.Fatal(err)
	}
	if got := ret.String(); got != "42" {
		t.Fatalf("got %s, want 42", got)
	}
}

func TestCompiledFunctionCallImport(t *testing.T) {
	s := tengo.NewScript([]byte(`
math := import("math")
use := func(x) { return math.abs(x) }
`))
	s.SetImports(stdlib.GetModuleMap("math"))
	c, err := s.Run()
	if err != nil {
		t.Fatal(err)
	}
	ret, err := compiledFn(t, c, "use").Call(&tengo.Int{Value: -42})
	if err != nil {
		t.Fatal(err)
	}
	if got := ret.String(); got != "42" {
		t.Fatalf("got %s, want 42", got)
	}
}

func TestCompiledFunctionCallGlobalMutation(t *testing.T) {
	c := runCompiled(t, `
g := 5
bump := func() { g += 10; return g }
`)
	fn := compiledFn(t, c, "bump")
	r1, err := fn.Call()
	if err != nil {
		t.Fatal(err)
	}
	if r1.String() != "15" {
		t.Fatalf("first call returned %s", r1)
	}
	r2, err := fn.Call()
	if err != nil {
		t.Fatal(err)
	}
	if r2.String() != "25" {
		t.Fatalf("second call returned %s", r2)
	}
	if got := c.Get("g").Int(); got != 25 {
		t.Fatalf("global g = %d, want 25", got)
	}
}

func TestCompiledFunctionCallErrorFormat(t *testing.T) {
	c := runCompiled(t, `
inner := func() { return 1 + "x" }
outer := func() { return inner() }
`)
	_, err := compiledFn(t, c, "outer").Call()
	if err == nil {
		t.Fatal("expected runtime error")
	}
	msg := err.Error()
	if !strings.Contains(msg, "Runtime Error: invalid operation: int + string") {
		t.Fatalf("unexpected error: %v", err)
	}
	if strings.Count(msg, "at (main):") != 2 {
		t.Fatalf("unexpected stack trace: %v", err)
	}
}

func TestCompiledFunctionCallMaxAllocs(t *testing.T) {
	s := tengo.NewScript([]byte(`
mk := func() {
	x := 0
	x++
	return x
}
`))
	s.SetMaxAllocs(0)
	c, err := s.Run()
	if err != nil {
		t.Fatal(err)
	}
	_, err = compiledFn(t, c, "mk").Call()
	if err == nil {
		t.Fatal("expected allocation limit error")
	}
	if !strings.Contains(err.Error(), "object allocation limit exceeded") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestCompiledFunctionCallCloneIsolation(t *testing.T) {
	c1 := runCompiled(t, `
g := 5
mk := func() {
	n := 0
	return func() { n++; return g + n }
}
f := mk()
f()
`)
	clone := c1.Clone()
	if err := clone.Set("g", 100); err != nil {
		t.Fatal(err)
	}
	f1 := compiledFn(t, c1, "f")
	f2 := compiledFn(t, clone, "f")

	// source: g=5, n=1 -> 7
	r1, err := f1.Call()
	if err != nil {
		t.Fatal(err)
	}
	if r1.String() != "7" {
		t.Fatalf("source returned %s", r1)
	}

	// clone: g=100, n snapshot=1 -> 102
	r2, err := f2.Call()
	if err != nil {
		t.Fatal(err)
	}
	if r2.String() != "102" {
		t.Fatalf("clone returned %s", r2)
	}

	// each instance keeps its own globals and captures
	if got := c1.Get("g").Int(); got != 5 {
		t.Fatalf("source g=%d", got)
	}
	if got := clone.Get("g").Int(); got != 100 {
		t.Fatalf("clone g=%d", got)
	}
}

func TestCompiledFunctionCallTransferIsolation(t *testing.T) {
	src := `
g := 10
mk := func() {
	n := 0
	return func() { n++; return g + n }
}
f := mk()
f()
f()
`
	c1 := runCompiled(t, src)
	fn1 := compiledFn(t, c1, "f")

	// destination compiled from the same source so global indexes match
	c2 := runCompiled(t, src)
	if err := c2.Set("f", fn1); err != nil {
		t.Fatal(err)
	}
	if err := c2.Set("g", 100); err != nil {
		t.Fatal(err)
	}

	// transferred closure sees captures at transfer time (n=2) and
	// resolves globals against the destination (g=100) -> 103
	fn2 := compiledFn(t, c2, "f")
	r2, err := fn2.Call()
	if err != nil {
		t.Fatal(err)
	}
	if r2.String() != "103" {
		t.Fatalf("destination returned %s", r2)
	}

	// source is unaffected: n=2 -> 3, g=10 -> 13
	r1, err := fn1.Call()
	if err != nil {
		t.Fatal(err)
	}
	if r1.String() != "13" {
		t.Fatalf("source returned %s", r1)
	}
	if got := c2.Get("g").Int(); got != 100 {
		t.Fatalf("destination g=%d", got)
	}
	if got := c1.Get("g").Int(); got != 10 {
		t.Fatalf("source g=%d", got)
	}
}

func TestCompiledFunctionCallNestedTransferIsolation(t *testing.T) {
	src := `
g := 5
mk := func(x) {
	n := 0
	inc := func() { n++; return g + n + x }
	return [inc, { "inc": inc }]
}
data := mk(100)
`
	c1 := runCompiled(t, src)
	c2 := runCompiled(t, src)
	if err := c2.Set("data", c1.Get("data").Object()); err != nil {
		t.Fatal(err)
	}
	if err := c2.Set("g", 50); err != nil {
		t.Fatal(err)
	}

	arr := c2.Get("data").Object().(*tengo.Array)
	incArr := arr.Value[0].(*tengo.CompiledFunction)
	r, err := incArr.Call()
	if err != nil {
		t.Fatal(err)
	}
	if r.String() != "151" {
		t.Fatalf("array closure returned %s", r)
	}

	m := arr.Value[1].(*tengo.Map)
	incMap := m.Value["inc"].(*tengo.CompiledFunction)
	r2, err := incMap.Call()
	if err != nil {
		t.Fatal(err)
	}
	// both references resolve to the same rebound closure, so the capture
	// is shared (n was already 1)
	if r2.String() != "152" {
		t.Fatalf("map closure returned %s", r2)
	}
}

func TestCompiledFunctionCallClosureSharing(t *testing.T) {
	c := runCompiled(t, `
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
`)
	if got := c.Get("out").Int(); got != 2 {
		t.Fatalf("in-script shared capture out=%d", got)
	}
	c = c.Clone()
	incFn := compiledFn(t, c, "inc")
	getFn := compiledFn(t, c, "get")
	if _, err := incFn.Call(); err != nil {
		t.Fatal(err)
	}
	r, err := getFn.Call()
	if err != nil {
		t.Fatal(err)
	}
	// Go-side calls still share the same capture
	if r.String() != "3" {
		t.Fatalf("shared capture returned %s", r)
	}
}

func TestCompiledFunctionCallWrongArgs(t *testing.T) {
	c := runCompiled(t, `add := func(a, b) { return a + b }`)
	_, err := compiledFn(t, c, "add").Call(&tengo.Int{Value: 1})
	if err == nil {
		t.Fatal("expected error for wrong number of arguments")
	}
}

func TestCompiledFunctionCallAddTransfer(t *testing.T) {
	src := `
mk := func() {
	n := 0
	return func() { n++; return n }
}
f := mk()
f()
`
	c1 := runCompiled(t, src)
	fn1 := compiledFn(t, c1, "f")

	// Add a callable value to a fresh script. The closure is rebound to the
	// new instance and its captured free variable is snapshotted at the
	// current value (1).
	s := tengo.NewScript([]byte(`
out := f()
`))
	if err := s.Add("f", fn1); err != nil {
		t.Fatal(err)
	}
	c2, err := s.Run()
	if err != nil {
		t.Fatal(err)
	}
	fn2 := compiledFn(t, c2, "f")
	// the destination script already called f() once, so the rebound
	// closure's capture advanced from 1 to 2
	ret, err := fn2.Call()
	if err != nil {
		t.Fatal(err)
	}
	if ret.String() != "3" {
		t.Fatalf("got %s, want 3", ret)
	}
}

func TestCompiledFunctionCallNestedClosureIsolation(t *testing.T) {
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
	if err := c2.Set("f", f1); err != nil {
		t.Fatal(err)
	}
	f2 := compiledFn(t, c2, "f")

	// both instances start with n=1 (snapshotted for the destination) and
	// each increment their own copy
	r2, err := f2.Call()
	if err != nil {
		t.Fatal(err)
	}
	if r2.String() != "2" {
		t.Fatalf("destination returned %s", r2)
	}
	r1, err := f1.Call()
	if err != nil {
		t.Fatal(err)
	}
	if r1.String() != "2" {
		t.Fatalf("source returned %s", r1)
	}
}

func TestCompiledFunctionCallRecursiveClosureTransfer(t *testing.T) {
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
	if err := c2.Set("f", f1); err != nil {
		t.Fatal(err)
	}
	f2 := compiledFn(t, c2, "f")
	ret, err := f2.Call(&tengo.Int{Value: 5})
	if err != nil {
		t.Fatal(err)
	}
	if ret.String() != "120" {
		t.Fatalf("got %s, want 120", ret)
	}
}
