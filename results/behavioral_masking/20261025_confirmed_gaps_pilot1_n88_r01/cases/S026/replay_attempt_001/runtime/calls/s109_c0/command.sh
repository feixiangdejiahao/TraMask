cd /tmp/tstest && cat > main.go <<'EOF'
package main

import (
	"fmt"
	"go/importer"
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

func main() {
	imp := importer.Default()
	pkg, err := imp.Import("strings")
	fmt.Println("err:", err)
	if err != nil { return }
	fmt.Println("scope names containing Builder:", pkg.Scope().Lookup("Builder"))
	obj := pkg.Scope().Lookup("Builder")
	tn := obj.(*types.TypeName)
	fmt.Printf("Builder type: %v, methods: Get=%v Reset=%v WriteString=%v\n", tn.Type(), hasMethod(tn.Type(), "Get"), hasMethod(tn.Type(), "Reset"), hasMethod(tn.Type(), "WriteString"))
	reader := pkg.Scope().Lookup("Reader").(*types.TypeName)
	fmt.Printf("Reader methods: Read=%v Len=%v\n", hasMethod(reader.Type(), "Read"), hasMethod(reader.Type(), "Len"))
	// Also check pointer method set
	fmt.Printf("Builder ptr methods: Reset=%v\n", hasMethod(types.NewPointer(tn.Type()), "Reset"))
}
EOF
go run .