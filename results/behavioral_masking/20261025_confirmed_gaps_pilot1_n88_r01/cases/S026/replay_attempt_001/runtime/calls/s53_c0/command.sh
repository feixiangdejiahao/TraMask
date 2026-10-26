cd /tmp/cptest && cat > main.go <<'EOF'
package main

import (
	"fmt"
	"go/parser"
	"go/token"
)

func main() {
	src := `package p

// LocalSymbol is an example.
/*! [MissingSymbol]: unknown symbol "MissingSymbol" in current package */
func LocalSymbol() {}
`
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, "p.go", src, parser.ParseComments)
	if err != nil { panic(err) }
	decl := f.Decls[0].(*ast.FuncDecl)
	fmt.Printf("Doc: %q\n", decl.Doc.Text())
	for _, c := range decl.Doc.List {
		fmt.Printf("  comment: %q\n", c.Text)
	}
}
EOF
cat > go.mod <<'EOF'
module cptest

go 1.25
EOF
go run . 2>&1 | head