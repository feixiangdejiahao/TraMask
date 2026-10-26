cd /app && python3 - <<'PY'
p='checkers/brokenDocLink_checker.go'
s=open(p).read()
s=s.replace('''func (c *brokenDocLinkChecker) checkPackageRef(decl ast.Node, ref, pkgRef string) {
	if types.Universe.Lookup(pkgRef) != nil {
		return
	}
	if c.resolvePackage(pkgRef) == nil {
		c.warn(decl, ref, `package %q is not imported`, pkgRef)
	}
}
''', '''func (c *brokenDocLinkChecker) checkPackageRef(decl ast.Node, ref, pkgRef string) {
	if types.Universe.Lookup(pkgRef) != nil || isStdlibPackage(pkgRef) {
		return
	}
	if c.resolvePackage(pkgRef) == nil {
		c.warn(decl, ref, `package %q is not imported`, pkgRef)
	}
}
''')
s=s.replace('''func (c *brokenDocLinkChecker) checkQualifiedSymbol(decl ast.Node, ref, pkgRef, name string) {
	pkg := c.resolvePackage(pkgRef)
	if pkg == nil {
		c.warn(decl, ref, `package %q is not imported`, pkgRef)
		return
	}
	if !packageHasSymbol(pkg, c.ctx.Pkg, name) {
		c.warn(decl, ref, `%q not found in package %q`, name, pkgRef)
	}
}
''', '''func (c *brokenDocLinkChecker) checkQualifiedSymbol(decl ast.Node, ref, pkgRef, name string) {
	pkg := c.resolvePackage(pkgRef)
	if pkg == nil {
		if isStdlibPackage(pkgRef) {
			return
		}
		c.warn(decl, ref, `package %q is not imported`, pkgRef)
		return
	}
	if !packageHasSymbol(pkg, c.ctx.Pkg, name) {
		c.warn(decl, ref, `%q not found in package %q`, name, pkgRef)
	}
}
''')
s=s.replace('''func (c *brokenDocLinkChecker) checkQualifiedMember(decl ast.Node, ref, pkgRef, recv, name string) {
	pkg := c.resolvePackage(pkgRef)
	if pkg == nil {
		c.warn(decl, ref, `package %q is not imported`, pkgRef)
		return
	}
''', '''func (c *brokenDocLinkChecker) checkQualifiedMember(decl ast.Node, ref, pkgRef, recv, name string) {
	pkg := c.resolvePackage(pkgRef)
	if pkg == nil {
		if isStdlibPackage(pkgRef) {
			return
		}
		c.warn(decl, ref, `package %q is not imported`, pkgRef)
		return
	}
''')
s=s.replace('''func validPackageRef(ref string) bool {
''', '''func isStdlibPackage(ref string) bool {
	_, ok := comment.DefaultLookupPackage(ref)
	return ok
}

func validPackageRef(ref string) bool {
''')
open(p,'w').write(s)
PY
gofmt -w checkers/brokenDocLink_checker.go && go build ./... && go test ./checkers/ -run 'TestCheckers/brokenDocLink' -count=1 2>&1 | tail -10