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

func hasMethod(typ types.Type, name string) (ok bool) {
	defer func() {
		if r := recover(); r != nil {
			fmt.Println("PANIC:", r)
			ok = false
		}
	}()
	ms := types.NewMethodSet(typ)
	for i := 0; i < ms.Len(); i++ {
		if ms.At(i).Obj().Name() == name {
			return true
		}
	}
	return false
}

func main() {
	src := `package p
type Box[T any] struct { V T }
func (Box[T]) Get() T { var z T; return z }
type TP interface { M() }
`
	fset := token.NewFileSet()
	f, _ := parser.ParseFile(fset, "p.go", src, 0)
	conf := types.Config{Importer: importer.Default()}
	info := &types.Info{Types: map[ast.Expr]types.TypeAndValue{}, Defs: map[*ast.Ident]types.Object{}, Uses: map[*ast.Ident]types.Object{}, Implicits: map[ast.Node]types.Object{}}
	pkg, _ := conf.Check("p", fset, []*ast.File{f}, info)
	for _, name := range []string{"Box", "TP"} {
		tn := pkg.Scope().Lookup(name).(*types.TypeName)
		fmt.Printf("%s methods: Get=%v, M=%v\n", name, hasMethod(tn.Type(), "Get"), hasMethod(tn.Type(), "M"))
	}
}
EOF
go run .