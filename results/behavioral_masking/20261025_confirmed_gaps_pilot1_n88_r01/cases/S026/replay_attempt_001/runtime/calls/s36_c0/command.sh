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

func hasMethod(typ types.Type, name string) bool {
	ms := types.NewMethodSet(typ)
	for i := 0; i < ms.Len(); i++ {
		if ms.At(i).Obj().Name() == name {
			return true
		}
	}
	return false
}

func hasField(typ types.Type, name string) bool {
	switch t := typ.(type) {
	case *types.Named:
		return hasField(t.Underlying(), name)
	case *types.Pointer:
		return hasField(t.Elem(), name)
	case *types.Struct:
		for i := 0; i < t.NumFields(); i++ {
			f := t.Field(i)
			if f.Name() == name {
				return true
			}
			if f.Embedded() && hasField(f.Type(), name) {
				return true
			}
		}
	}
	return false
}

func main() {
	src := `package p

type Base struct { X int }
func (Base) M() {}
type Embedded struct { Base }
func (Embedded) N() {}
type T struct { Embedded; Y int }
var v T
`
	fset := token.NewFileSet()
	f, _ := parser.ParseFile(fset, "p.go", src, 0)
	conf := types.Config{Importer: importer.Default()}
	info := &types.Info{Types: map[ast.Expr]types.TypeAndValue{}, Defs: map[*ast.Ident]types.Object{}, Uses: map[*ast.Ident]types.Object{}, Implicits: map[ast.Node]types.Object{}}
	pkg, _ := conf.Check("p", fset, []*ast.File{f}, info)
	tn := pkg.Scope().Lookup("T").(*types.TypeName)
	named := tn.Type().(*types.Named)
	for _, name := range []string{"X", "M", "N", "Y", "Embedded", "Base", "NoSuch"} {
		fmt.Printf("%s: method=%v field=%v\n", name, hasMethod(named, name), hasField(named, name))
	}
	// method set lookup with nil pkg
	ms := types.NewMethodSet(named)
	fmt.Println("lookup M with nil pkg:", ms.Lookup(nil, "M"))
}
EOF
go run .