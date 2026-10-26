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
type MyType struct{ X int }
func (MyType) M() {}
type A = MyType
type B MyType
`
	fset := token.NewFileSet()
	f, _ := parser.ParseFile(fset, "p.go", src, 0)
	conf := types.Config{Importer: importer.Default()}
	info := &types.Info{Types: map[ast.Expr]types.TypeAndValue{}, Defs: map[*ast.Ident]types.Object{}, Uses: map[*ast.Ident]types.Object{}, Implicits: map[ast.Node]types.Object{}}
	pkg, _ := conf.Check("p", fset, []*ast.File{f}, info)
	for _, name := range []string{"A", "B", "MyType"} {
		tn := pkg.Scope().Lookup(name).(*types.TypeName)
		fmt.Printf("%s: Type()=%T %v; IsAlias=%v\n", name, tn.Type(), tn.Type(), tn.IsAlias())
	}
}
EOF
go run .