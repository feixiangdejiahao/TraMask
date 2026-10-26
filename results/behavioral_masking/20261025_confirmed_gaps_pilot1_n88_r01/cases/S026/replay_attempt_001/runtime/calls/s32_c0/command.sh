mkdir -p /tmp/tstest && cd /tmp/tstest && cat > main.go <<'EOF'
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

import "fmt"

type Base struct { X int }
func (Base) M() {}
type Embedded struct { Base }
func (Embedded) N() {}
type T struct { Embedded; Y int }
var v T
func F() { fmt.Println(v.X, v.M, v.Embedded, v.Base) }
`
	fset := token.NewFileSet()
	f, _ := parser.ParseFile(fset, "p.go", src, 0)
	conf := types.Config{Importer: importer.Default()}
	info := &types.Info{Types: map[ast.Expr]types.TypeAndValue{}, Defs: map[*ast.Ident]types.Object{}, Uses: map[*ast.Ident]types.Object{}}
	pkg, _ := conf.Check("p", fset, []*ast.File{f}, info)

	// builtins
	for _, n := range []string{"int", "string", "len", "Error", "error", "any", "comparable", "byte", "rune", "nil", "true"} {
		fmt.Printf("Universe.Lookup(%q) = %v\n", n, types.Universe.Lookup(n))
	}

	// find T
	obj := pkg.Scope().Lookup("T")
	tn := obj.(*types.TypeName)
	named := tn.Type().(*types.Named)
	fmt.Println("T methods:")
	ms := types.NewMethodSet(named)
	for i := 0; i < ms.Len(); i++ {
		fmt.Println("  ", ms.At(i).Obj().Name(), ms.At(i).Obj().Parent())
	}

	fmt.Println("T struct:")
	for _, u := range []types.Type{named, types.NewPointer(named)} {
		fmt.Printf("underlying of %T: %v\n", u, u.Underlying())
		st := u.Underlying().(*types.Struct)
		for i := 0; i < st.NumFields(); i++ {
			fld := st.Field(i)
			fmt.Printf("  field %s embedded=%v type=%v\n", fld.Name(), fld.Embedded(), fld.Type())
		}
	}
}
EOF
cat > go.mod <<'EOF'
module tstest

go 1.25
EOF
go run .