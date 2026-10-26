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
type Box[T any] struct{}
func F[T any]() { var x T; _ = x }
`
	fset := token.NewFileSet()
	f, _ := parser.ParseFile(fset, "p.go", src, 0)
	conf := types.Config{Importer: importer.Default()}
	info := &types.Info{Types: map[ast.Expr]types.TypeAndValue{}, Defs: map[*ast.Ident]types.Object{}, Uses: map[*ast.Ident]types.Object{}, Implicits: map[ast.Node]types.Object{}, Selections: map[*ast.SelectorExpr]*types.Selection{}}
	pkg, _ := conf.Check("p", fset, []*ast.File{f}, info)
	fn := pkg.Scope().Lookup("F").(*types.Func)
	sig := fn.Type().(*types.Signature)
	tp := sig.TypeParams().At(0)
	fmt.Println("tp:", tp)
	func() {
		defer func() { fmt.Println("panic:", recover()) }()
		ms := types.NewMethodSet(tp)
		fmt.Println("methodset len:", ms.Len())
		pt := types.NewPointer(tp)
		fmt.Println("ptr:", pt)
		ms2 := types.NewMethodSet(pt)
		fmt.Println("ptr methodset len:", ms2.Len())
	}()
}
EOF
go run .