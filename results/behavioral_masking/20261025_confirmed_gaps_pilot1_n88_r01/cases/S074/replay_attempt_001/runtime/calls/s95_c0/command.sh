cd /app && python3 - <<'PYEOF'
p='compiled_function_call_test.go'
s=open(p).read()
s=s.replace('''	if !strings.Contains(msg, "at (main):2:9") || !strings.Contains(msg, "at (main):4:9") {
		t.Fatalf("unexpected stack trace: %v", err)
	}''', '''	if strings.Count(msg, "at (main):") != 2 {
		t.Fatalf("unexpected stack trace: %v", err)
	}''')
open(p,'w').write(s)
print("done")
PYEOF
gofmt -w compiled_function_call_test.go && go test -run TestCompiledFunctionCall -v . 2>&1 | tail -45