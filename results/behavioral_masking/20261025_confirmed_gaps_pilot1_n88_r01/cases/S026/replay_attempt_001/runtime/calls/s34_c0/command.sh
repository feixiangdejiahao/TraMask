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
	info := &types.Info{Types: map[ast.Expr]types.TypeAndValue{}, Defs: map[*ast.Ident]types.Object{}, Uses: map[*ast.Ident]types.Object{}, Implicits: map[ast.Node]types.Object{}}
	pkg, _ := conf.Check("p", fset, []*ast.File{f}, info)
	fmt.Println("pkg scope:")
	for _, n := range []string{"Ints", "fmt", "alias", "Sprintf", "ToUpper"} {
		obj := pkg.Scope().Lookup(n)
		fmt.Printf("  Lookup(%q): %T %v\n", n, obj, obj)
	}
	// Check if pkg scope includes dot imported sort.Ints
	obj := pkg.Scope().Lookup("Ints")
	if obj != nil {
		fmt.Println("  Ints parent:", obj.Parent())
	}
}
EOF
go run .