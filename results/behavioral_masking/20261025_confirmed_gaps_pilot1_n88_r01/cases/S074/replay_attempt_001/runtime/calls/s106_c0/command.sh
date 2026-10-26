cd /app && cat >> compiled_function_call_test.go <<'EOF'

func TestCompiledFunctionCallAddTransfer(t *testing.T) {
	src := `
g := 10
mk := func() {
	n := 0
	return func() { n++; return g + n }
}
f := mk()
f()
`
	c1 := runCompiled(t, src)
	fn1 := compiledFn(t, c1, "f")

	// Add a callable value to a fresh script. The function is rebound to the
	// new instance, so it resolves globals against the new instance.
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
	ret, err := fn2.Call()
	if err != nil {
		t.Fatal(err)
	}
	if ret.String() != "11" {
		t.Fatalf("got %s, want 11", ret)
	}
}
EOF
gofmt -w compiled_function_call_test.go && go test -run TestCompiledFunctionCallAddTransfer -v . 2>&1 | tail -20