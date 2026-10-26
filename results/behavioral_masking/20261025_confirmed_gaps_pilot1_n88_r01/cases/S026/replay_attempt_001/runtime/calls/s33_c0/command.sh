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
	pkg, err := conf.Check("p", fset, []*ast.File{f}, info)
	fmt.Println("err:", err, "pkg:", pkg)
	for _, spec := range f.Imports {
		fmt.Printf("--- import spec path=%v name=%v\n", spec.Path.Value, spec.Name)
		if spec.Name != nil {
			obj := info.ObjectOf(spec.Name)
			fmt.Printf("  ObjectOf(name): %T %v\n", obj, obj)
			if pn, ok := obj.(*types.PkgName); ok {
				fmt.Printf("  PkgName.Name=%q Imported=%v\n", pn.Name(), pn.Imported().Path())
			}
		}
		imp := info.Implicits[spec]
		fmt.Printf("  Implicits: %T %v\n", imp, imp)
		if pn, ok := imp.(*types.PkgName); ok {
			fmt.Printf("  PkgName.Name=%q Imported=%v\n", pn.Name(), pn.Imported().Path())
		}
	}
}
EOF
go run .