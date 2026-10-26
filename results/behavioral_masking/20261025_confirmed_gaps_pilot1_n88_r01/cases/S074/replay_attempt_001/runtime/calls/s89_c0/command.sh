cd /app && python3 - <<'PYEOF'
p='zz_repro5_test.go'
s=open(p).read()
s=s.replace('''	inner := func() {
	return 1 + "x"
}
outer := func() {
	return inner()
}''', '''	inner := func() {
	return 1 + "x"
}
outer := func() {
	return inner()
}''')
# actually just swap order
s=s.replace('''outer := func() {
	return inner()
}
inner := func() {
	return 1 + "x"
}''', '''inner := func() {
	return 1 + "x"
}
outer := func() {
	return inner()
}''')
open(p,'w').write(s)
PYEOF
go test -run TestGoCallErrorStack -v . 2>&1 | tail -20