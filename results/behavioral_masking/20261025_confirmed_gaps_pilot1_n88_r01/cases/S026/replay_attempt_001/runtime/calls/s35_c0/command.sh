cd /tmp/tstest && cat > main.go <<'EOF'
package main

import (
	"fmt"
	"go/ast"
	"go/importer"
	"go/parser"
	"go/token"
	"go/types"
)

func main() {
	src := `package p
import (
	"fmt"
	alias "strings"
	. "sort"
)
var _ = fmt.Sprintf
var _ = alias.ToUpper
var _ = Ints
`
	fset := token.NewFileSet()
	f, _ := parser.ParseFile(fset, "p.go", src, 0)
	conf := types.Config{Importer: importer.Default()}
	info := &types.Info{Types: map[ast.Expr]types.TypeAndValue{}, Defs: map[*ast.Ident]types.Object{}, Uses: map[*ast.Ident]types.Object{}, Implicits: map[ast.Node]types.Object{}, Scopes: map[ast.Node]*types.Scope{}}
	pkg, _ := conf.Check("p", fset, []*ast.File{f}, info)
	fmt.Println("package scope:", pkg.Scope())
	for _, n := range []string{"Ints", "fmt", "alias"} {
		obj := pkg.Scope().Lookup(n)
		fmt.Printf("  pkg.Lookup(%q): %v\n", n, obj)
	}
	fmt.Println("file scope:", info.Scopes[f])
	fs := info.Scopes[f]
	if fs != nil {
		for _, n := range []string{"Ints", "fmt", "alias"} {
			obj := fs.Lookup(n)
			fmt.Printf("  file.Lookup(%q): %v\n", n, obj)
		}
		fmt.Println("  file scope names:")
		for _, name := range fs.Names() {
			obj := fs.Lookup(name)
			fmt.Printf("    %s -> %T %v\n", name, obj, obj)
		}
	}
}
EOF
go run .