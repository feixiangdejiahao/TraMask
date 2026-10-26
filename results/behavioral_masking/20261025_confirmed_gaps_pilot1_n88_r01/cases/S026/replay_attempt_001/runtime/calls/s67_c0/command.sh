cd /tmp/cptest && cat > main.go <<'EOF'
package main

import (
	"fmt"
	"go/doc/comment"
)

func main() {
	p := &comment.Parser{
		LookupPackage: func(name string) (string, bool) { return name, true },
		LookupSym: func(_, _ string) bool { return true },
	}
	for _, text := range []string{
		"[Foo[T]]",
		"[map[string]int]",
		"[[]int]",
		"[Foo.Bar]",
		"[pkg.Foo[T]]",
		"[[Foo]]",
		"[Foo].",
		"foo [Bar] baz",
	} {
		d := p.Parse(text)
		fmt.Printf("=== %q ===\n", text)
		for _, b := range d.Content {
			para, _ := b.(*comment.Paragraph)
			for _, t := range para.Text {
				fmt.Printf("  %T %v\n", t, t)
			}
		}
	}
}
EOF
go run .