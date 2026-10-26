cd /app && python3 - <<'PY'
p='checkers/brokenDocLink_checker.go'
s=open(p).read()
s=s.replace('''func (c *brokenDocLinkChecker) resolvePackage(ref string) *types.Package {
	if pkg := c.imports[ref]; pkg != nil {
		return pkg
	}
''', '''func (c *brokenDocLinkChecker) resolvePackage(ref string) *types.Package {
	if ref == c.ctx.Pkg.Name() {
		return c.ctx.Pkg
	}
	if pkg := c.imports[ref]; pkg != nil {
		return pkg
	}
''')
open(p,'w').write(s)
PY
gofmt -w checkers/brokenDocLink_checker.go && go test ./checkers/ -run 'TestCheckers/brokenDocLink' -count=1 2>&1 | tail -10