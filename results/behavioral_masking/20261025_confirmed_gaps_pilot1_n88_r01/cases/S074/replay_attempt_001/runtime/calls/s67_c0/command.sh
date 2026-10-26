cd /app && python3 - <<'PYEOF'
p='zz_repro2_test.go'
s=open(p).read()

# Fix clone test expectations
s=s.replace('''	// mutate clone global g
	if err := c2.Set("g", 100); err != nil { t.Fatal(err) }
	// f2 should use clone's g=100, n snapshot=1 -> 101
	ret2, err := f2.Call()
	if err != nil { t.Fatal(err) }
	if ret2.String() != "101" { t.Fatalf("clone got %s", ret2) }
	// f1 should use c1's g=5, n=1 -> 6
	ret1, err := f1.Call()
	if err != nil { t.Fatal(err) }
	if ret1.String() != "6" { t.Fatalf("source got %s", ret1) }''', '''	// mutate clone global g
	if err := c2.Set("g", 100); err != nil { t.Fatal(err) }
	// f2 should use clone's g=100, n snapshot=1 then increment -> 102
	ret2, err := f2.Call()
	if err != nil { t.Fatal(err) }
	if ret2.String() != "102" { t.Fatalf("clone got %s", ret2) }
	// f1 should use c1's g=5, n=1 then increment -> 7
	ret1, err := f1.Call()
	if err != nil { t.Fatal(err) }
	if ret1.String() != "7" { t.Fatalf("source got %s", ret1) }''')

# Rewrite transfer test to same-source layout
old = s[s.index('func TestGoCallTransferIsolation'):s.index('func TestGoCallCloneIsolation')]
new = '''func TestGoCallTransferIsolation(t *testing.T) {
	src := `
g := 10
mk := func() {
	n := 0
	return func() { n++; return g + n }
}
f := mk()
f()
f()
`
	c1 := runScript(t, src)
	fn1, _ := c1.Get("f").Object().(*tengo.CompiledFunction)

	// c2 compiled from the same source so global indexes match
	c2 := runScript(t, src)
	if err := c2.Set("f", fn1); err != nil { t.Fatal(err) }
	if err := c2.Set("g", 100); err != nil { t.Fatal(err) }

	// transferred closure snapshots n=2; calling it increments to 3 and
	// uses c2's g=100 -> 103
	fn2, _ := c2.Get("f").Object().(*tengo.CompiledFunction)
	ret2, err := fn2.Call()
	if err != nil { t.Fatal(err) }
	if ret2.String() != "103" { t.Fatalf("c2 got %s", ret2) }

	// source instance is unaffected: n=2 -> 3, g=10 -> 13
	ret1, err := fn1.Call()
	if err != nil { t.Fatal(err) }
	if ret1.String() != "13" { t.Fatalf("c1 got %s", ret1) }

	// c2's globals were not mutated by c1's call and vice versa
	if got := c2.Get("g").Int(); got != 100 { t.Fatalf("c2 g=%d", got) }
	if got := c1.Get("g").Int(); got != 10 { t.Fatalf("c1 g=%d", got) }
}

'''
s = s.replace(old, new)
open(p,'w').write(s)
print("done")
PYEOF
gofmt -w zz_repro2_test.go && go test -run 'TestGoCall' -v . 2>&1 | tail -60