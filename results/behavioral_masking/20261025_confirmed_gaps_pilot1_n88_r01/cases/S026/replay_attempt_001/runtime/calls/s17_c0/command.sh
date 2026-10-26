cd /tmp/cptest && cat > main.go <<'EOF'
package main

import (
	"fmt"
	"go/doc/comment"
)

func main() {
	for _, text := range []string{"[math]", "[Foo]", "[fmt]", "[io.Reader]", "[Foo.Bar]", "[Recv.Method]", "[pkg.Recv.Method]", "[foo bar]", "[foo-bar]", "[Foo.Bar Baz]"} {
		p := &comment.Parser{
			LookupSym: func(recv, name string) bool { fmt.Printf("  LookupSym(%q, %q) -> true\n", recv, name); return true },
			LookupPackage: func(name string) (string, bool) { fmt.Printf("  LookupPackage(%q) -> true\n", name); return name, true },
		}
		d := p.Parse(text)
		fmt.Printf("=== %q ===\n", text)
		for _, b := range d.Content {
			para := b.(*comment.Paragraph)
			for _, t := range para.Text {
				if dl, ok := t.(*comment.DocLink); ok {
					fmt.Printf("  DocLink imp=%q recv=%q name=%q\n", dl.ImportPath, dl.Recv, dl.Name)
				} else {
					fmt.Printf("  %T %v\n", t, t)
				}
			}
		}
		fmt.Println()
	}
}
EOF
go run .