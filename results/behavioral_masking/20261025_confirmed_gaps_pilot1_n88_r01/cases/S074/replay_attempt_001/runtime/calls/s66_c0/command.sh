cd /app && python3 - <<'PYEOF'
p='zz_repro2_test.go'
s=open(p).read()
s=s.replace('sum := func(a, args...) {', 'sum := func(a, ...args) {')
s=s.replace('''func TestGoCallCallbackArg(t *testing.T) {
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
}''', '''func TestGoCallCallbackArg(t *testing.T) {
	// Go builtin calls a script function passed as argument
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
	if err != nil { t.Fatal(err) }
	if got := c.Get("out").Int(); got != 42 { t.Fatalf("out=%d", got) }
}''')
# rewrite transfer isolation test to call via Go
s=s.replace('''func TestGoCallTransferIsolation(t *testing.T) {
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
}''', '''func TestGoCallTransferIsolation(t *testing.T) {
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
	c1 := runScript(t, src1)
	fn, _ := c1.Get("f").Object().(*tengo.CompiledFunction)

	// transfer to c2 via Add + Compile
	s2src := `out := f()`
	s2 := tengo.NewScript([]byte(s2src))
	if err := s2.Add("f", fn); err != nil { t.Fatal(err) }
	c2, err := s2.Run()
	if err != nil { t.Fatal(err) }

	// c1's f still has n=2, g=10 -> 12
	ret1, err := fn.Call()
	if err != nil { t.Fatal(err) }
	if ret1.String() != "12" { t.Fatalf("c1 got %s", ret1) }

	// c2's f (snapshot n=2, resolves g against c2). c2's script
	// doesn't define g, so set it now.
	if err := c2.Set("g", 100); err != nil { t.Fatal(err) }
	f2, _ := c2.Get("f").Object().(*tengo.CompiledFunction)
	ret2, err := f2.Call()
	if err != nil { t.Fatal(err) }
	if ret2.String() != "102" { t.Fatalf("c2 got %s", ret2) }

	// after calling f2, c2's g should be 100 (not modified) and c1 unchanged
	if got := c2.Get("g").Int(); got != 100 { t.Fatalf("c2 g=%d", got) }
	if got := c1.Get("g").Int(); got != 10 { t.Fatalf("c1 g=%d", got) }
}''')
open(p,'w').write(s)
print("done")
PYEOF
go test -run 'TestGoCall' -v . 2>&1 | tail -60