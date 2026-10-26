cd /app && cat >> compiled_function_call_test.go <<'EOF'

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
EOF
gofmt -w compiled_function_call_test.go && rm -f zz_edge_test.go zz_edge2_test.go && go test ./... 2>&1 | tail -12