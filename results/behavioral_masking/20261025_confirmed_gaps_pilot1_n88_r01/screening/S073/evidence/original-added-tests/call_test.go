package tengo_test

import (
	"strings"
	"testing"

	"github.com/d5/tengo/v2"
	"github.com/d5/tengo/v2/require"
)

func callCompiled(t *testing.T, c *tengo.Compiled, name string, args ...tengo.Object) (tengo.Object, error) {
	t.Helper()
	v := c.Get(name)
	require.False(t, v.IsUndefined())
	fn, ok := v.Object().(*tengo.CompiledFunction)
	require.True(t, ok, "expected compiled-function, got %s", v.ValueType())
	return fn.Call(args...)
}

func TestCompiledFunction_Call_Basic(t *testing.T) {
	s := tengo.NewScript([]byte(`add := func(a, b) { return a + b }`))
	c, err := s.Run()
	require.NoError(t, err)

	res, err := callCompiled(t, c, "add",
		&tengo.Int{Value: 40}, &tengo.Int{Value: 2})
	require.NoError(t, err)
	require.Equal(t, int64(42), res.(*tengo.Int).Value)
}

func TestCompiledFunction_Call_NoReturn(t *testing.T) {
	s := tengo.NewScript([]byte(`f := func() { a := 1 }`))
	c, err := s.Run()
	require.NoError(t, err)

	res, err := callCompiled(t, c, "f")
	require.NoError(t, err)
	require.Equal(t, tengo.UndefinedValue, res)
}

func TestCompiledFunction_Call_ClosureState(t *testing.T) {
	s := tengo.NewScript([]byte(`
make := func() {
	n := 0
	return func() { n += 1; return n }
}
c := make()
`))
	c, err := s.Run()
	require.NoError(t, err)

	fn := c.Get("c").Object().(*tengo.CompiledFunction)
	r1, err := fn.Call()
	require.NoError(t, err)
	require.Equal(t, int64(1), r1.(*tengo.Int).Value)

	r2, err := fn.Call()
	require.NoError(t, err)
	require.Equal(t, int64(2), r2.(*tengo.Int).Value)

	r3, err := fn.Call()
	require.NoError(t, err)
	require.Equal(t, int64(3), r3.(*tengo.Int).Value)
}

func TestCompiledFunction_Call_Globals(t *testing.T) {
	s := tengo.NewScript([]byte(`x := 0; f := func() { x += 5; return x }`))
	c, err := s.Run()
	require.NoError(t, err)

	r1, err := callCompiled(t, c, "f")
	require.NoError(t, err)
	require.Equal(t, int64(5), r1.(*tengo.Int).Value)
	require.Equal(t, 5, c.Get("x").Int())

	r2, err := callCompiled(t, c, "f")
	require.NoError(t, err)
	require.Equal(t, int64(10), r2.(*tengo.Int).Value)
	require.Equal(t, 10, c.Get("x").Int())
}

func TestCompiledFunction_Call_Recursion(t *testing.T) {
	s := tengo.NewScript([]byte(`
f := func(n) {
	if n <= 1 { return 1 }
	return n * f(n-1)
}
`))
	c, err := s.Run()
	require.NoError(t, err)

	res, err := callCompiled(t, c, "f", &tengo.Int{Value: 5})
	require.NoError(t, err)
	require.Equal(t, int64(120), res.(*tengo.Int).Value)
}

func TestCompiledFunction_Call_ClosureRecursion(t *testing.T) {
	s := tengo.NewScript([]byte(`
fact := func(n) {
	if n <= 1 { return 1 }
	return n * fact(n-1)
}
`))
	c, err := s.Run()
	require.NoError(t, err)

	res, err := callCompiled(t, c, "fact", &tengo.Int{Value: 6})
	require.NoError(t, err)
	require.Equal(t, int64(720), res.(*tengo.Int).Value)
}

func TestCompiledFunction_Call_Variadic(t *testing.T) {
	s := tengo.NewScript([]byte(`
f := func(a, ...rest) { return len(rest) }
g := func(...all) { return len(all) }
`))
	c, err := s.Run()
	require.NoError(t, err)

	res, err := callCompiled(t, c, "f",
		&tengo.Int{Value: 1}, &tengo.Int{Value: 2}, &tengo.Int{Value: 3})
	require.NoError(t, err)
	require.Equal(t, int64(2), res.(*tengo.Int).Value)

	res, err = callCompiled(t, c, "f", &tengo.Int{Value: 1})
	require.NoError(t, err)
	require.Equal(t, int64(0), res.(*tengo.Int).Value)

	res, err = callCompiled(t, c, "g")
	require.NoError(t, err)
	require.Equal(t, int64(0), res.(*tengo.Int).Value)

	res, err = callCompiled(t, c, "g", &tengo.Int{Value: 1}, &tengo.Int{Value: 2})
	require.NoError(t, err)
	require.Equal(t, int64(2), res.(*tengo.Int).Value)

	_, err = callCompiled(t, c, "f")
	require.Error(t, err)
	require.True(t, strings.Contains(err.Error(), "want>=1"),
		"unexpected error: %v", err)
}

func TestCompiledFunction_Call_ReturnedClosure(t *testing.T) {
	s := tengo.NewScript([]byte(`
make := func(n) {
	return func(x) { return x + n }
}
add5 := make(5)
`))
	c, err := s.Run()
	require.NoError(t, err)

	fn := c.Get("add5").Object().(*tengo.CompiledFunction)
	res, err := fn.Call(&tengo.Int{Value: 3})
	require.NoError(t, err)
	require.Equal(t, int64(8), res.(*tengo.Int).Value)
}

func TestCompiledFunction_Call_CompositeValues(t *testing.T) {
	s := tengo.NewScript([]byte(`
arr := [func(a) { return a + 1 }, func(a) { return a * 2 }]
m := {"add": func(a, b) { return a + b }}
`))
	c, err := s.Run()
	require.NoError(t, err)

	arr := c.Get("arr").Object().(*tengo.Array)
	require.Equal(t, 2, len(arr.Value))
	r1, err := arr.Value[0].(*tengo.CompiledFunction).Call(&tengo.Int{Value: 10})
	require.NoError(t, err)
	require.Equal(t, int64(11), r1.(*tengo.Int).Value)
	r2, err := arr.Value[1].(*tengo.CompiledFunction).Call(&tengo.Int{Value: 10})
	require.NoError(t, err)
	require.Equal(t, int64(20), r2.(*tengo.Int).Value)

	m := c.Get("m").Object().(*tengo.Map)
	rf, ok := m.Value["add"].(*tengo.CompiledFunction)
	require.True(t, ok)
	r3, err := rf.Call(&tengo.Int{Value: 20}, &tengo.Int{Value: 22})
	require.NoError(t, err)
	require.Equal(t, int64(42), r3.(*tengo.Int).Value)
}

func TestCompiledFunction_Call_SourceModuleExport(t *testing.T) {
	mods := tengo.NewModuleMap()
	mods.AddSourceModule("mod", []byte(`
base := 10
export func(x) { return x + base }
`))
	s := tengo.NewScript([]byte(`fn := import("mod")`))
	s.SetImports(mods)
	c, err := s.Run()
	require.NoError(t, err)

	fn := c.Get("fn").Object().(*tengo.CompiledFunction)
	res, err := fn.Call(&tengo.Int{Value: 5})
	require.NoError(t, err)
	require.Equal(t, int64(15), res.(*tengo.Int).Value)
}

func TestCompiledFunction_Call_GoCallbackArgument(t *testing.T) {
	var received *tengo.CompiledFunction
	caller := &tengo.UserFunction{
		Name: "call",
		Value: func(args ...tengo.Object) (tengo.Object, error) {
			received = args[0].(*tengo.CompiledFunction)
			return tengo.UndefinedValue, nil
		},
	}

	s := tengo.NewScript([]byte(`
f := func(a) { return a * 2 }
call(f)
out := f(21)
`))
	s.Add("call", caller)
	c, err := s.Run()
	require.NoError(t, err)
	require.Equal(t, 42, c.Get("out").Int())

	require.NotNil(t, received)
	res, err := received.Call(&tengo.Int{Value: 5})
	require.NoError(t, err)
	require.Equal(t, int64(10), res.(*tengo.Int).Value)
}

func TestCompiledFunction_Call_RuntimeErrorFormatting(t *testing.T) {
	s := tengo.NewScript([]byte(`f := func() { return len() }`))
	c, err := s.Run()
	require.NoError(t, err)

	fn := c.Get("f").Object().(*tengo.CompiledFunction)
	_, err = fn.Call()
	require.Error(t, err)
	require.True(t, strings.Contains(err.Error(),
		"Runtime Error: wrong number of arguments"),
		"unexpected error: %v", err)
	require.True(t, strings.Contains(err.Error(), "at (main):1:22"),
		"unexpected error: %v", err)
}

func TestCompiledFunction_Call_WrongArgs(t *testing.T) {
	s := tengo.NewScript([]byte(`f := func(a, b) { return a + b }`))
	c, err := s.Run()
	require.NoError(t, err)

	_, err = callCompiled(t, c, "f", &tengo.Int{Value: 1})
	require.Error(t, err)
	require.True(t, strings.Contains(err.Error(), "want=2, got=1"),
		"unexpected error: %v", err)
}

func TestCompiled_Clone_Isolation(t *testing.T) {
	s := tengo.NewScript([]byte(`
x := 0
f := func() { x += 1; return x }
f()
`))
	c, err := s.Run()
	require.NoError(t, err)

	fn := c.Get("f").Object().(*tengo.CompiledFunction)
	r0, err := fn.Call()
	require.NoError(t, err)
	require.Equal(t, int64(2), r0.(*tengo.Int).Value)

	clone := c.Clone()
	cloneFn := clone.Get("f").Object().(*tengo.CompiledFunction)

	// clone starts from the copied global value (x = 2)
	r1, err := cloneFn.Call()
	require.NoError(t, err)
	require.Equal(t, int64(3), r1.(*tengo.Int).Value)

	r2, err := cloneFn.Call()
	require.NoError(t, err)
	require.Equal(t, int64(4), r2.(*tengo.Int).Value)

	// original is unaffected by calls through the clone
	r3, err := fn.Call()
	require.NoError(t, err)
	require.Equal(t, int64(3), r3.(*tengo.Int).Value)

	// clone still has its own state
	r4, err := cloneFn.Call()
	require.NoError(t, err)
	require.Equal(t, int64(5), r4.(*tengo.Int).Value)

	require.Equal(t, 3, c.Get("x").Int())
	require.Equal(t, 5, clone.Get("x").Int())
}

func TestCompiled_Clone_ClosureIsolation(t *testing.T) {
	s := tengo.NewScript([]byte(`
make := func() {
	n := 0
	return func() { n += 1; return n }
}
c := make()
c()
`))
	src, err := s.Run()
	require.NoError(t, err)

	srcFn := src.Get("c").Object().(*tengo.CompiledFunction)
	// source captured n is already 1; clone snapshots it at transfer time
	clone := src.Clone()
	cloneFn := clone.Get("c").Object().(*tengo.CompiledFunction)

	r1, err := cloneFn.Call()
	require.NoError(t, err)
	require.Equal(t, int64(2), r1.(*tengo.Int).Value)

	r2, err := cloneFn.Call()
	require.NoError(t, err)
	require.Equal(t, int64(3), r2.(*tengo.Int).Value)

	// source closure is independent
	r3, err := srcFn.Call()
	require.NoError(t, err)
	require.Equal(t, int64(2), r3.(*tengo.Int).Value)
}

func TestCompiled_Set_TransferredClosureSnapshot(t *testing.T) {
	srcScript := tengo.NewScript([]byte(`
make := func() {
	n := 0
	return func() { n += 1; return n }
}
c := make()
c()
c()
`))
	src, err := srcScript.Run()
	require.NoError(t, err)

	// captured n is now 2
	srcFn := src.Get("c").Object().(*tengo.CompiledFunction)

	dstScript := tengo.NewScript([]byte(`g := undefined`))
	dst, err := dstScript.Run()
	require.NoError(t, err)
	require.NoError(t, dst.Set("g", srcFn))

	dstFn := dst.Get("g").Object().(*tengo.CompiledFunction)

	// destination sees captures as of transfer time (n=2)
	r1, err := dstFn.Call()
	require.NoError(t, err)
	require.Equal(t, int64(3), r1.(*tengo.Int).Value)

	r2, err := dstFn.Call()
	require.NoError(t, err)
	require.Equal(t, int64(4), r2.(*tengo.Int).Value)

	// source is not affected by destination calls
	r3, err := srcFn.Call()
	require.NoError(t, err)
	require.Equal(t, int64(3), r3.(*tengo.Int).Value)
}

func TestCompiled_Set_TransferredCompositeRecursiveIsolation(t *testing.T) {
	srcScript := tengo.NewScript([]byte(`
n := 100
f1 := func() { n += 1; return n }
f2 := func() { n += 10; return n }
arr := [f1, f2]
`))
	src, err := srcScript.Run()
	require.NoError(t, err)
	srcArr := src.Get("arr").Object().(*tengo.Array)

	dstScript := tengo.NewScript([]byte(`n := 0; arr := []`))
	dst, err := dstScript.Run()
	require.NoError(t, err)
	require.NoError(t, dst.Set("arr", srcArr))

	dstArr := dst.Get("arr").Object().(*tengo.Array)
	require.Equal(t, 2, len(dstArr.Value))

	dstFn1 := dstArr.Value[0].(*tengo.CompiledFunction)
	dstFn2 := dstArr.Value[1].(*tengo.CompiledFunction)

	r1, err := dstFn1.Call()
	require.NoError(t, err)
	require.Equal(t, int64(1), r1.(*tengo.Int).Value)

	r2, err := dstFn2.Call()
	require.NoError(t, err)
	require.Equal(t, int64(11), r2.(*tengo.Int).Value)

	// source is unaffected
	srcFn1 := srcArr.Value[0].(*tengo.CompiledFunction)
	r3, err := srcFn1.Call()
	require.NoError(t, err)
	require.Equal(t, int64(101), r3.(*tengo.Int).Value)

	// destination globals reflect destination calls
	require.Equal(t, 11, dst.Get("n").Int())
	require.Equal(t, 101, src.Get("n").Int())
}

func TestCompiled_Clone_CompositeRecursiveIsolation(t *testing.T) {
	s := tengo.NewScript([]byte(`
n := 10
f1 := func() { n += 1; return n }
f2 := func() { n += 2; return n }
arr := [f1, f2]
`))
	src, err := s.Run()
	require.NoError(t, err)

	clone := src.Clone()
	cloneArr := clone.Get("arr").Object().(*tengo.Array)
	cloneFn1 := cloneArr.Value[0].(*tengo.CompiledFunction)
	cloneFn2 := cloneArr.Value[1].(*tengo.CompiledFunction)

	// clone starts from the copied global value (n = 10)
	r1, err := cloneFn1.Call()
	require.NoError(t, err)
	require.Equal(t, int64(11), r1.(*tengo.Int).Value)

	r2, err := cloneFn2.Call()
	require.NoError(t, err)
	require.Equal(t, int64(13), r2.(*tengo.Int).Value)

	require.Equal(t, 13, clone.Get("n").Int())
	require.Equal(t, 10, src.Get("n").Int())
}

func TestCompiled_Set_TransferredRecursiveClosure(t *testing.T) {
	srcScript := tengo.NewScript([]byte(`
fact := func(n) {
	if n <= 1 { return 1 }
	return n * fact(n-1)
}
`))
	src, err := srcScript.Run()
	require.NoError(t, err)
	srcFn := src.Get("fact").Object().(*tengo.CompiledFunction)

	dstScript := tengo.NewScript([]byte(`g := undefined`))
	dst, err := dstScript.Run()
	require.NoError(t, err)
	require.NoError(t, dst.Set("g", srcFn))

	dstFn := dst.Get("g").Object().(*tengo.CompiledFunction)
	res, err := dstFn.Call(&tengo.Int{Value: 5})
	require.NoError(t, err)
	require.Equal(t, int64(120), res.(*tengo.Int).Value)
}

func TestCompiledFunction_Call_InsideTransferredToScript(t *testing.T) {
	// A function defined in instance A is set into instance B and then called
	// from B's script. Constants used by A's function must resolve against A's
	// own bytecode, not B's.
	srcScript := tengo.NewScript([]byte(`f := func(x) { return x + 100 }`))
	src, err := srcScript.Run()
	require.NoError(t, err)
	srcFn := src.Get("f").Object().(*tengo.CompiledFunction)

	dstScript := tengo.NewScript([]byte(`out := g(5)`))
	dstScript.Add("g", nil)
	dst, err := dstScript.Compile()
	require.NoError(t, err)
	require.NoError(t, dst.Set("g", srcFn))
	require.NoError(t, dst.Run())

	require.Equal(t, 105, dst.Get("out").Int())
}

func TestCompiledFunction_Call_ReturnedClosureState(t *testing.T) {
	s := tengo.NewScript([]byte(`
make := func(n) {
	m := n
	return func() { m += 1; return m }
}
c := make(10)
`))
	c, err := s.Run()
	require.NoError(t, err)

	outer := c.Get("c").Object().(*tengo.CompiledFunction)
	res, err := outer.Call()
	require.NoError(t, err)
	require.Equal(t, int64(11), res.(*tengo.Int).Value)

	res, err = outer.Call()
	require.NoError(t, err)
	require.Equal(t, int64(12), res.(*tengo.Int).Value)
}

func TestCompiledFunction_Call_GoSideReturnsClosure(t *testing.T) {
	s := tengo.NewScript([]byte(`make := func(n) { return func(x) { return x + n } }`))
	c, err := s.Run()
	require.NoError(t, err)

	makeFn := c.Get("make").Object().(*tengo.CompiledFunction)
	res, err := makeFn.Call(&tengo.Int{Value: 5})
	require.NoError(t, err)

	cl := res.(*tengo.CompiledFunction)
	r1, err := cl.Call(&tengo.Int{Value: 3})
	require.NoError(t, err)
	require.Equal(t, int64(8), r1.(*tengo.Int).Value)
	r2, err := cl.Call(&tengo.Int{Value: 4})
	require.NoError(t, err)
	require.Equal(t, int64(9), r2.(*tengo.Int).Value)
}

func TestCompiledFunction_Call_ImportInsideFunction(t *testing.T) {
	mods := tengo.NewModuleMap()
	mods.AddSourceModule("mod", []byte(`export func(x) { return x * 2 }`))
	s := tengo.NewScript([]byte(`
f := func(x) {
	m := import("mod")
	return m(x)
}
`))
	s.SetImports(mods)
	c, err := s.Run()
	require.NoError(t, err)

	res, err := callCompiled(t, c, "f", &tengo.Int{Value: 21})
	require.NoError(t, err)
	require.Equal(t, int64(42), res.(*tengo.Int).Value)
}

func TestCompiledFunction_Call_NestedErrorTrace(t *testing.T) {
	s := tengo.NewScript([]byte(`
g := func() { return len() }
f := func() { return g() }
`))
	c, err := s.Run()
	require.NoError(t, err)

	fn := c.Get("f").Object().(*tengo.CompiledFunction)
	_, err = fn.Call()
	require.Error(t, err)
	require.True(t, strings.Contains(err.Error(), "Runtime Error:"),
		"unexpected error: %v", err)
	// both frames should be present
	require.True(t, strings.Count(err.Error(), "at (main):") >= 2,
		"unexpected error: %v", err)
}

func TestScript_AddForeignFunction_ThenGoSideCall(t *testing.T) {
	src := tengo.NewScript([]byte(`f := func(a) { return a + 100 }`))
	srcC, err := src.Run()
	require.NoError(t, err)
	srcFn := srcC.Get("f").Object().(*tengo.CompiledFunction)

	dst := tengo.NewScript([]byte(`
out := f(1)
`))
	dst.Add("f", srcFn)
	dstC, err := dst.Run()
	require.NoError(t, err)
	require.Equal(t, 101, dstC.Get("out").Int())

	dstFn := dstC.Get("f").Object().(*tengo.CompiledFunction)
	res, err := dstFn.Call(&tengo.Int{Value: 5})
	require.NoError(t, err)
	require.Equal(t, int64(105), res.(*tengo.Int).Value)

	// source function unaffected
	res2, err := srcFn.Call(&tengo.Int{Value: 1})
	require.NoError(t, err)
	require.Equal(t, int64(101), res2.(*tengo.Int).Value)
}

func TestCompiled_Set_TransferredNestedMap(t *testing.T) {
	srcScript := tengo.NewScript([]byte(`
n := 0
f := func() { n += 1; return n }
m := {"inner": {"arr": [f]}}
`))
	src, err := srcScript.Run()
	require.NoError(t, err)
	srcMap := src.Get("m").Object().(*tengo.Map)

	dstScript := tengo.NewScript([]byte(`n := 0; m := {}`))
	dst, err := dstScript.Run()
	require.NoError(t, err)
	require.NoError(t, dst.Set("m", srcMap))

	dstMap := dst.Get("m").Object().(*tengo.Map)
	inner := dstMap.Value["inner"].(*tengo.Map)
	arr := inner.Value["arr"].(*tengo.Array)
	dstFn := arr.Value[0].(*tengo.CompiledFunction)

	r1, err := dstFn.Call()
	require.NoError(t, err)
	require.Equal(t, int64(1), r1.(*tengo.Int).Value)

	// destination mutated only its own globals
	require.Equal(t, 1, dst.Get("n").Int())
	require.Equal(t, 0, src.Get("n").Int())

	// source is still independent
	srcFn := srcMap.Value["inner"].(*tengo.Map).Value["arr"].(*tengo.Array).Value[0].(*tengo.CompiledFunction)
	r2, err := srcFn.Call()
	require.NoError(t, err)
	require.Equal(t, int64(1), r2.(*tengo.Int).Value)
	require.Equal(t, 1, src.Get("n").Int())
}

func TestCompiledFunction_Call_TailRecursion(t *testing.T) {
	s := tengo.NewScript([]byte(`
f := func(n, acc) {
	if n == 0 { return acc }
	return f(n-1, acc*n)
}
`))
	c, err := s.Run()
	require.NoError(t, err)

	res, err := callCompiled(t, c, "f",
		&tengo.Int{Value: 5}, &tengo.Int{Value: 1})
	require.NoError(t, err)
	require.Equal(t, int64(120), res.(*tengo.Int).Value)
}

func TestCompiledFunction_Call_ReturnsArrayWithClosure(t *testing.T) {
	s := tengo.NewScript([]byte(`
make := func(n) {
	return [func(x) { return x + n }]
}
`))
	c, err := s.Run()
	require.NoError(t, err)

	makeFn := c.Get("make").Object().(*tengo.CompiledFunction)
	res, err := makeFn.Call(&tengo.Int{Value: 7})
	require.NoError(t, err)
	arr := res.(*tengo.Array)
	cl := arr.Value[0].(*tengo.CompiledFunction)

	r, err := cl.Call(&tengo.Int{Value: 35})
	require.NoError(t, err)
	require.Equal(t, int64(42), r.(*tengo.Int).Value)
}

func TestCompiled_Set_GoSideReturnedClosureTransfer(t *testing.T) {
	src := tengo.NewScript([]byte(`make := func(n) { return func() { n += 1; return n } }`))
	srcC, err := src.Run()
	require.NoError(t, err)

	makeFn := srcC.Get("make").Object().(*tengo.CompiledFunction)
	res, err := makeFn.Call(&tengo.Int{Value: 10})
	require.NoError(t, err)
	cl := res.(*tengo.CompiledFunction)

	// cl captured n=10; bump it once via source
	r, err := cl.Call()
	require.NoError(t, err)
	require.Equal(t, int64(11), r.(*tengo.Int).Value)

	dst := tengo.NewScript([]byte(`g := undefined`))
	dstC, err := dst.Run()
	require.NoError(t, err)
	require.NoError(t, dstC.Set("g", cl))

	dstFn := dstC.Get("g").Object().(*tengo.CompiledFunction)
	// destination snapshot is n=11 at transfer time
	r1, err := dstFn.Call()
	require.NoError(t, err)
	require.Equal(t, int64(12), r1.(*tengo.Int).Value)

	// source unaffected
	r2, err := cl.Call()
	require.NoError(t, err)
	require.Equal(t, int64(12), r2.(*tengo.Int).Value)
}

func TestCompiled_Set_DeepCopyIsolation(t *testing.T) {
	src := tengo.NewScript([]byte(`
n := 0
f := func() { n += 1; return n }
arr := [f]
`))
	srcC, err := src.Run()
	require.NoError(t, err)
	srcArr := srcC.Get("arr").Object().(*tengo.Array)

	dst := tengo.NewScript([]byte(`n := 0; arr := []`))
	dstC, err := dst.Run()
	require.NoError(t, err)
	require.NoError(t, dstC.Set("arr", srcArr))

	// mutating source container must not affect destination
	srcArr.Value = append(srcArr.Value, &tengo.Int{Value: 999})
	dstArr := dstC.Get("arr").Object().(*tengo.Array)
	require.Equal(t, 1, len(dstArr.Value))

	dstFn := dstArr.Value[0].(*tengo.CompiledFunction)
	r, err := dstFn.Call()
	require.NoError(t, err)
	require.Equal(t, int64(1), r.(*tengo.Int).Value)
}

func TestCompiled_Clone_RecursiveClosure(t *testing.T) {
	s := tengo.NewScript([]byte(`
fact := func(n) {
	if n <= 1 { return 1 }
	return n * fact(n-1)
}
`))
	src, err := s.Run()
	require.NoError(t, err)

	clone := src.Clone()
	cloneFn := clone.Get("fact").Object().(*tengo.CompiledFunction)
	res, err := cloneFn.Call(&tengo.Int{Value: 5})
	require.NoError(t, err)
	require.Equal(t, int64(120), res.(*tengo.Int).Value)
}

func TestCompiledFunction_Call_SourceModuleMapExport(t *testing.T) {
	mods := tengo.NewModuleMap()
	mods.AddSourceModule("mod", []byte(`
base := 3
m := {"add": func(x) { return x + base }, "mul": func(x) { return x * base }}
export m
`))
	s := tengo.NewScript([]byte(`m := import("mod")`))
	s.SetImports(mods)
	c, err := s.Run()
	require.NoError(t, err)

	m := c.Get("m").Object().(*tengo.ImmutableMap)
	addFn := m.Value["add"].(*tengo.CompiledFunction)
	mulFn := m.Value["mul"].(*tengo.CompiledFunction)

	r1, err := addFn.Call(&tengo.Int{Value: 10})
	require.NoError(t, err)
	require.Equal(t, int64(13), r1.(*tengo.Int).Value)

	r2, err := mulFn.Call(&tengo.Int{Value: 10})
	require.NoError(t, err)
	require.Equal(t, int64(30), r2.(*tengo.Int).Value)
}

func TestCompiledFunction_Call_FunctionArgument(t *testing.T) {
	s := tengo.NewScript([]byte(`
add := func(a, b) { return a + b }
call := func(f, x) { return f(x, 1) }
`))
	c, err := s.Run()
	require.NoError(t, err)

	addFn := c.Get("add").Object().(*tengo.CompiledFunction)
	callFn := c.Get("call").Object().(*tengo.CompiledFunction)
	res, err := callFn.Call(addFn, &tengo.Int{Value: 41})
	require.NoError(t, err)
	require.Equal(t, int64(42), res.(*tengo.Int).Value)
}
