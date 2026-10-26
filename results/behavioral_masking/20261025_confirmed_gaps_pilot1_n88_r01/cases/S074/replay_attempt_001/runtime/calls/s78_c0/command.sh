cd /app && python3 - <<'PYEOF'
p='zz_repro3_test.go'
s=open(p).read()
s=s.replace('''	c1 := runScript(t, src)
	c2 := runScript(t, `out := 1`)
	if err := c2.Set("data", c1.Get("data").Object()); err != nil { t.Fatal(err) }
	if err := c2.Set("g", 50); err != nil { t.Fatal(err) }''', '''	c1 := runScript(t, src)
	c2 := runScript(t, src) // same layout so global indexes match
	if err := c2.Set("data", c1.Get("data").Object()); err != nil { t.Fatal(err) }
	if err := c2.Set("g", 50); err != nil { t.Fatal(err) }''')
s=s.replace('''	if got := c.Get("g").Int(); got != 15 { t.Fatalf("g %d", got) }''', '''	if got := c.Get("g").Int(); got != 25 { t.Fatalf("g %d", got) }''')
open(p,'w').write(s)
print("done")
PYEOF
go test -run 'TestGoCall' -v . 2>&1 | tail -80