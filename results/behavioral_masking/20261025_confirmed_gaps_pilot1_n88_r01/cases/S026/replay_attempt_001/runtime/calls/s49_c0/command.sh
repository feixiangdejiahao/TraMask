cd /app && python3 - <<'PY'
p='checkers/brokenDocLink_checker.go'
s=open(p).read()

s=s.replace('''func (c *brokenDocLinkChecker) checkDocLink(decl ast.Node, link *comment.DocLink) {
	ref := docLinkText(link)
	if !validDocLinkRef(ref) {
		return
	}

	switch {
	case link.ImportPath == "" && link.Recv == "":
		// [Name] local symbol.
		c.checkLocalSymbol(decl, ref, link.Name)
	case link.ImportPath == "" && link.Recv != "":
		// [Recv.Name] local method or field.
		c.checkLocalMember(decl, ref, link.Recv, link.Name)
	case link.ImportPath != "" && link.Recv == "" && link.Name == "":
		// [pkg] package reference.
		c.checkPackageRef(decl, ref, link.ImportPath)
	case link.ImportPath != "" && link.Recv == "":
		// [pkg.Name] qualified symbol.
		c.checkQualifiedSymbol(decl, ref, link.ImportPath, link.Name)
	case link.ImportPath != "" && link.Recv != "":
		// [pkg.Recv.Name] qualified method or field.
		c.checkQualifiedMember(decl, ref, link.ImportPath, link.Recv, link.Name)
	}
}
''', '''func (c *brokenDocLinkChecker) checkDocLink(decl ast.Node, link *comment.DocLink) {
	ref := docLinkText(link)
	if !validDocLinkText(ref) {
		return
	}

	switch {
	case link.ImportPath == "" && link.Recv == "":
		// [Name] local symbol.
		c.checkLocalSymbol(decl, ref, link.Name)
	case link.ImportPath == "" && link.Recv != "":
		// [Recv.Name] local method or field.
		if !validIdentifier(link.Recv) || !validIdentifier(link.Name) {
			return
		}
		c.checkLocalMember(decl, ref, link.Recv, link.Name)
	case link.ImportPath != "" && link.Recv == "" && link.Name == "":
		// [pkg] package reference.
		if !validPackageRef(link.ImportPath) {
			return
		}
		c.checkPackageRef(decl, ref, link.ImportPath)
	case link.ImportPath != "" && link.Recv == "":
		// [pkg.Name] qualified symbol.
		if !validPackageRef(link.ImportPath) || !validIdentifier(link.Name) {
			return
		}
		c.checkQualifiedSymbol(decl, ref, link.ImportPath, link.Name)
	case link.ImportPath != "" && link.Recv != "":
		// [pkg.Recv.Name] qualified method or field.
		if !validPackageRef(link.ImportPath) || !validIdentifier(link.Recv) || !validIdentifier(link.Name) {
			return
		}
		c.checkQualifiedMember(decl, ref, link.ImportPath, link.Recv, link.Name)
	}
}
''')

s=s.replace('''func validDocLinkRef(ref string) bool {
	if ref == "" || strings.ContainsAny(ref, " \t\\n") {
		return false
	}
	ref = strings.TrimPrefix(ref, "*")
	if ref == "" {
		return false
	}
	if token.IsIdentifier(ref) {
		return true
	}
	// Qualified references: pkg.Name or pkg.Recv.Name.
	// The first component can also be a full import path.
	parts := strings.Split(ref, ".")
	if len(parts) < 2 || len(parts) > 3 {
		return false
	}
	if !validPackageRef(parts[0]) {
		return false
	}
	for _, part := range parts[1:] {
		if !token.IsIdentifier(part) {
			return false
		}
	}
	return true
}
''', '''func validDocLinkText(ref string) bool {
	if ref == "" || strings.ContainsAny(ref, " \\t\\n") {
		return false
	}
	ref = strings.TrimPrefix(ref, "*")
	return ref != ""
}

func validIdentifier(name string) bool {
	return token.IsIdentifier(name)
}
''')

open(p,'w').write(s)
PY
gofmt -w checkers/brokenDocLink_checker.go && go build ./... 2>&1 | head -30