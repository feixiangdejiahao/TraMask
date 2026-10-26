cd /app && python3 - <<'PYEOF'
p='compiled_function_call_test.go'
s=open(p).read()
old=s[s.index('func TestCompiledFunctionCallAddTransfer'):s.index('func TestCompiledFunctionCallNestedClosureIsolation')]
new='''func TestCompiledFunctionCallAddTransfer(t *testing.T) {
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
	ret, err := fn2.Call()
	if err != nil {
		t.Fatal(err)
	}
	if ret.String() != "2" {
		t.Fatalf("got %s, want 2", ret)
	}
}

'''
s=s.replace(old,new)
open(p,'w').write(s)
print("done")
PYEOF
gofmt -w compiled_function_call_test.go && go test -run TestCompiledFunctionCallAddTransfer -v . 2>&1 | tail -10