cd /app && python3 - <<'PYEOF'
p='compiled_function_call_test.go'
s=open(p).read()
old='''	fn2 := compiledFn(t, c2, "f")
	ret, err := fn2.Call()
	if err != nil {
		t.Fatal(err)
	}
	if ret.String() != "2" {
		t.Fatalf("got %s, want 2", ret)
	}
}'''
new='''	fn2 := compiledFn(t, c2, "f")
	// the destination script already called f() once, so the rebound
	// closure's capture advanced from 1 to 2
	ret, err := fn2.Call()
	if err != nil {
		t.Fatal(err)
	}
	if ret.String() != "3" {
		t.Fatalf("got %s, want 3", ret)
	}
}'''
assert old in s
s=s.replace(old,new,1)
open(p,'w').write(s)
print("done")
PYEOF
gofmt -w compiled_function_call_test.go && go test -run TestCompiledFunctionCall -v . 2>&1 | tail -30