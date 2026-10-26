cd /app && python3 - <<'PYEOF'
p='zz_repro3_test.go'
s=open(p).read()
print("before map:", 'if r2.String() != "152"' in s)
print("before g:", 'got != 15' in s)
s=s.replace('if r2.String() != "152" { t.Fatalf("map inc got %s", r2) }', 'if r2.String() != "151" { t.Fatalf("map inc got %s", r2) }')
s=s.replace('if got := c.Get("g").Int(); got != 15 { t.Fatalf("g %d", got) }', 'if got := c.Get("g").Int(); got != 25 { t.Fatalf("g %d", got) }')
open(p,'w').write(s)
print("after map:", 'if r2.String() != "152"' in s)
print("after g:", 'got != 15' in s)
PYEOF
go test -run 'TestGoCall' -v . 2>&1 | tail -60