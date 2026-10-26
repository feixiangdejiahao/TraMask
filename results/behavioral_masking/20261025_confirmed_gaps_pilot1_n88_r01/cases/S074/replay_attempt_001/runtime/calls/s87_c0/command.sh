cd /app && cat >> zz_repro4_test.go <<'EOF'

func TestGoCallReturnGlobalFunction(t *testing.T) {
	src := `
add := func(a, b) { return a + b }
get := func() { return add }
`
	c := runScript(t, src)
	getFn, _ := c.Get("get").Object().(*tengo.CompiledFunction)
	ret, err := getFn.Call()
	if err != nil { t.Fatal(err) }
	fn, ok := ret.(*tengo.CompiledFunction)
	if !ok { t.Fatalf("type %T", ret) }
	r, err := fn.Call(&tengo.Int{Value: 40}, &tengo.Int{Value: 2})
	if err != nil { t.Fatal(err) }
	if r.String() != "42" { t.Fatalf("got %s", r) }
}

func TestGoCallGetAll(t *testing.T) {
	c := runScript(t, `add := func(a, b) { return a + b }`)
	for _, v := range c.GetAll() {
		if v.Name() == "add" {
			fn, ok := v.Object().(*tengo.CompiledFunction)
			if !ok { t.Fatalf("type %T", v.Object()) }
			r, err := fn.Call(&tengo.Int{Value: 20}, &tengo.Int{Value: 22})
			if err != nil { t.Fatal(err) }
			if r.String() != "42" { t.Fatalf("got %s", r) }
		}
	}
}

func TestGoCallCloneAfterGoCall(t *testing.T) {
	src := `
g := 1
f := func() { g += 1; return g }
`
	c := runScript(t, src)
	fn, _ := c.Get("f").Object().(*tengo.CompiledFunction)
	if _, err := fn.Call(); err != nil { t.Fatal(err) } // g -> 2
	cl := c.Clone()
	if got := cl.Get("g").Int(); got != 2 { t.Fatalf("clone g=%d", got) }
	clFn, _ := cl.Get("f").Object().(*tengo.CompiledFunction)
	r, err := clFn.Call()
	if err != nil { t.Fatal(err) }
	if r.String() != "3" { t.Fatalf("got %s", r) }
	// source unchanged
	if got := c.Get("g").Int(); got != 2 { t.Fatalf("source g=%d", got) }
}
EOF
gofmt -w zz_repro4_test.go && go test -run 'TestGoCall' -v . 2>&1 | tail -40