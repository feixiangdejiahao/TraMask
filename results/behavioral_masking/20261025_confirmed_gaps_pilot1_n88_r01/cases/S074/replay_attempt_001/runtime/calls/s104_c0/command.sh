cd /app && python3 - <<'PYEOF'
p='compiled_function_call_test.go'
s=open(p).read()
old='''	r2, err := incMap.Call()
	if err != nil {
		t.Fatal(err)
	}
	// independently snapshotted capture: also starts at n=0
	if r2.String() != "151" {
		t.Fatalf("map closure returned %s", r2)
	}'''
new='''	r2, err := incMap.Call()
	if err != nil {
		t.Fatal(err)
	}
	// both references in the transferred array/map resolve to the same
	// rebound closure, so the capture is shared (n was already 1)
	if r2.String() != "152" {
		t.Fatalf("map closure returned %s", r2)
	}'''
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("done")
PYEOF
gofmt -w compiled_function_call_test.go && go test -run TestCompiledFunctionCall -v . 2>&1 | tail -45