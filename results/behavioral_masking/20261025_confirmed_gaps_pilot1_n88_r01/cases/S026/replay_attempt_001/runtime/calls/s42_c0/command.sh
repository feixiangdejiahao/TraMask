cd /app && cat > checkers/brokenDocLink_checker.go <<'EOF'
package checkers

import (
	"go/ast"
	"go/doc/comment"
	"go/token"
	"go/types"
	"strconv"
	"strings"
	"unicode"

	"github.com/go-critic/go-critic/checkers/internal/astwalk"
	"github.com/go-critic/go-critic/linter"
)

func init() {
	var info linter.CheckerInfo
	info.Name = "brokenDocLink"
	info.Tags = []string{linter.DiagnosticTag, linter.ExperimentalTag}
	info.Summary = "Detects broken doc comment links"
	info.Before = `
// Foo is a sample function.
// It is documented by [Bar] which does not exist.
func Foo() int`
	info.After = `
// Foo is a sample function.
// It is documented by [Foo] which is defined in this package.
func Foo() int`

	collection.AddChecker(&info, func(ctx *linter.CheckerContext) (linter.FileWalker, error) {
		return astwalk.WalkerForDocLink(&brokenDocLinkChecker{ctx: ctx}), nil
	})
}

type brokenDocLinkChecker struct {
	astwalk.WalkHandler
	ctx *linter.CheckerContext

	file       *ast.File
	imports    map[string]*types.Package
	dotImports []*types.Package
}

func (c *brokenDocLinkChecker) EnterFile(f *ast.File) bool {
	c.file = f
	c.imports = make(map[string]*types.Package)
	c.dotImports = c.dotImports[:0]
	for _, spec := range f.Imports {
		pkg := importedPackage(c.ctx, spec)
		if pkg == nil {
			continue
		}
		if spec.Name != nil && spec.Name.Name == "." {
			c.dotImports = append(c.dotImports, pkg)
			continue
		}
		c.imports[localPackageName(c.ctx, spec)] = pkg
	}
	return true
}

func (c *brokenDocLinkChecker) VisitDocLink(decl ast.Node, doc *ast.CommentGroup) {
	parser := &comment.Parser{
		LookupPackage: func(name string) (string, bool) { return name, true },
		LookupSym:     func(_, _ string) bool { return true },
	}
	parsed := parser.Parse(doc.Text())
	for _, block := range parsed.Content {
		c.visitBlock(decl, block)
	}
}

func (c *brokenDocLinkChecker) visitBlock(decl ast.Node, block comment.Block) {
	switch block := block.(type) {
	case *comment.Paragraph:
		c.visitTexts(decl, block.Text)
	case *comment.Heading:
		c.visitTexts(decl, block.Text)
	case *comment.List:
		for _, item := range block.Items {
			for _, content := range item.Content {
				c.visitBlock(decl, content)
			}
		}
	case *comment.Code:
		// Code blocks do not contain documentation links.
	}
}

func (c *brokenDocLinkChecker) visitTexts(decl ast.Node, texts []comment.Text) {
	for _, text := range texts {
		link, ok := text.(*comment.DocLink)
		if !ok {
			continue
		}
		c.checkDocLink(decl, link)
	}
}

func (c *brokenDocLinkChecker) checkDocLink(decl ast.Node, link *comment.DocLink) {
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

func (c *brokenDocLinkChecker) checkLocalSymbol(decl ast.Node, ref, name string) {
	if c.lookupLocal(name) != nil || types.Universe.Lookup(name) != nil {
		return
	}
	c.warn(decl, ref, `unknown symbol %q in current package`, name)
}

func (c *brokenDocLinkChecker) checkLocalMember(decl ast.Node, ref, recv, name string) {
	obj := c.lookupLocal(recv)
	if obj == nil {
		if types.Universe.Lookup(recv) != nil {
			return
		}
		c.warn(decl, ref, `type %q not found in current package`, recv)
		return
	}
	typeName, ok := obj.(*types.TypeName)
	if !ok {
		c.warn(decl, ref, `%q is not a type`, recv)
		return
	}
	if !hasMember(typeName.Type(), name) {
		c.warn(decl, ref, `type %q has no method or field %q`, recv, name)
	}
}

func (c *brokenDocLinkChecker) checkPackageRef(decl ast.Node, ref, pkgRef string) {
	if types.Universe.Lookup(pkgRef) != nil {
		return
	}
	if c.resolvePackage(pkgRef) == nil {
		c.warn(decl, ref, `package %q is not imported`, pkgRef)
	}
}

func (c *brokenDocLinkChecker) checkQualifiedSymbol(decl ast.Node, ref, pkgRef, name string) {
	pkg := c.resolvePackage(pkgRef)
	if pkg == nil {
		c.warn(decl, ref, `package %q is not imported`, pkgRef)
		return
	}
	if !packageHasSymbol(pkg, c.ctx.Pkg, name) {
		c.warn(decl, ref, `%q not found in package %q`, name, pkgRef)
	}
}

func (c *brokenDocLinkChecker) checkQualifiedMember(decl ast.Node, ref, pkgRef, recv, name string) {
	pkg := c.resolvePackage(pkgRef)
	if pkg == nil {
		c.warn(decl, ref, `package %q is not imported`, pkgRef)
		return
	}
	obj := pkg.Scope().Lookup(recv)
	if obj == nil {
		if pkg == c.ctx.Pkg {
			c.warn(decl, ref, `type %q not found in current package`, recv)
		} else {
			c.warn(decl, ref, `type %q not found in package %q`, recv, pkgRef)
		}
		return
	}
	typeName, ok := obj.(*types.TypeName)
	if !ok {
		c.warn(decl, ref, `%q is not a type`, recv)
		return
	}
	if !hasMember(typeName.Type(), name) {
		c.warn(decl, ref, `type %q has no method or field %q`, recv, name)
	}
}

func (c *brokenDocLinkChecker) warn(decl ast.Node, ref, format string, args ...interface{}) {
	c.ctx.Warn(decl, "[%s]: "+format, append([]interface{}{ref}, args...)...)
}

func (c *brokenDocLinkChecker) lookupLocal(name string) types.Object {
	if obj := c.ctx.Pkg.Scope().Lookup(name); obj != nil {
		return obj
	}
	for _, pkg := range c.dotImports {
		if obj := pkg.Scope().Lookup(name); obj != nil && obj.Exported() {
			return obj
		}
	}
	return nil
}

func (c *brokenDocLinkChecker) resolvePackage(ref string) *types.Package {
	if pkg := c.imports[ref]; pkg != nil {
		return pkg
	}
	for _, spec := range c.file.Imports {
		path, err := strconv.Unquote(spec.Path.Value)
		if err != nil {
			continue
		}
		if path == ref {
			return importedPackage(c.ctx, spec)
		}
	}
	return nil
}

func packageHasSymbol(pkg, currentPkg *types.Package, name string) bool {
	obj := pkg.Scope().Lookup(name)
	if obj == nil {
		return false
	}
	if pkg != currentPkg && !obj.Exported() {
		return false
	}
	return true
}

func hasMember(typ types.Type, name string) bool {
	return hasMethod(typ, name) || hasField(typ, name)
}

func hasMethod(typ types.Type, name string) bool {
	methodSet := types.NewMethodSet(typ)
	for i := 0; i < methodSet.Len(); i++ {
		if methodSet.At(i).Obj().Name() == name {
			return true
		}
	}
	return false
}

func hasField(typ types.Type, name string) bool {
	switch typ := typ.(type) {
	case *types.Named:
		return hasField(typ.Underlying(), name)
	case *types.Pointer:
		return hasField(typ.Elem(), name)
	case *types.Struct:
		for i := 0; i < typ.NumFields(); i++ {
			field := typ.Field(i)
			if field.Name() == name {
				return true
			}
			if field.Embedded() && hasField(field.Type(), name) {
				return true
			}
		}
	}
	return false
}

func docLinkText(link *comment.DocLink) string {
	var sb strings.Builder
	for _, text := range link.Text {
		switch text := text.(type) {
		case comment.Plain:
			sb.WriteString(string(text))
		case comment.Italic:
			sb.WriteString(string(text))
		}
	}
	return sb.String()
}

func validDocLinkRef(ref string) bool {
	if ref == "" || strings.ContainsAny(ref, " \t\n") {
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

func validPackageRef(ref string) bool {
	if token.IsIdentifier(ref) {
		return true
	}
	if !strings.Contains(ref, "/") {
		return false
	}
	for _, r := range ref {
		if unicode.IsLetter(r) || unicode.IsDigit(r) {
			continue
		}
		switch r {
		case '-', '_', '.', '/', '~':
			continue
		}
		return false
	}
	return true
}

func importedPackage(ctx *linter.CheckerContext, spec *ast.ImportSpec) *types.Package {
	var obj types.Object
	if spec.Name != nil {
		obj = ctx.TypesInfo.ObjectOf(spec.Name)
	} else {
		obj = ctx.TypesInfo.Implicits[spec]
	}
	pkgName, ok := obj.(*types.PkgName)
	if !ok {
		return nil
	}
	return pkgName.Imported()
}

func localPackageName(ctx *linter.CheckerContext, spec *ast.ImportSpec) string {
	if spec.Name != nil {
		return spec.Name.Name
	}
	obj := ctx.TypesInfo.Implicits[spec]
	if pkgName, ok := obj.(*types.PkgName); ok {
		return pkgName.Name()
	}
	return ""
}
EOF
gofmt -w checkers/brokenDocLink_checker.go && go build ./... 2>&1 | head -30