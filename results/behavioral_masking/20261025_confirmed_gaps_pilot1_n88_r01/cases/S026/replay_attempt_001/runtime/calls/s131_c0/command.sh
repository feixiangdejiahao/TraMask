cd /app && python3 - <<'PY'
p='checkers/brokenDocLink_checker.go'
s=open(p).read()
s=s.replace('''func hasMethod(typ types.Type, name string) bool {
	// Directly declared methods, including methods with a pointer receiver.
	if named, ok := typ.(*types.Named); ok {
''', '''func hasMethod(typ types.Type, name string) bool {
	// Unwrap type aliases before inspecting the underlying type.
	typ = types.Unalias(typ)
	// Directly declared methods, including methods with a pointer receiver.
	if named, ok := typ.(*types.Named); ok {
''')
s=s.replace('''func hasField(typ types.Type, name string) bool {
	switch typ := typ.(type) {
''', '''func hasField(typ types.Type, name string) bool {
	switch typ := types.Unalias(typ).(type) {
''')
open(p,'w').write(s)
PY
gofmt -w checkers/brokenDocLink_checker.go && go build ./... && go test ./checkers/ -run 'TestCheckers/brokenDocLink' -count=1 2>&1 | tail -10