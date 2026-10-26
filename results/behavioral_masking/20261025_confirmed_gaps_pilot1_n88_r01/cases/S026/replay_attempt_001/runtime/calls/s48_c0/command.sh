cd /tmp/cptest && cat > main.go <<'EOF'
package main

import (
	"fmt"
	"go/doc/comment"
)

func dump(d *comment.Doc) {
	for _, b := range d.Content {
		fmt.Printf("block: %T\n", b)
		switch b := b.(type) {
		case *comment.Paragraph:
			for _, t := range b.Text {
				fmt.Printf("  text: %T %v\n", t, t)
			}
		case *comment.List:
			for _, it := range b.Items {
				fmt.Printf("  item:\n")
				for _, c := range it.Content {
					p := c.(*comment.Paragraph)
					for _, t := range p.Text {
						fmt.Printf("    text: %T %v\n", t, t)
					}
				}
			}
		}
	}
}

func main() {
	p := &comment.Parser{
		LookupPackage: func(name string) (string, bool) { return name, true },
		LookupSym: func(_, _ string) bool { return true },
	}
	for _, text := range []string{
		"Foo docs.\n! [Bar]: unknown symbol \"Bar\" in current package\nMore docs.",
		"Foo docs.\n[Bar]: unknown symbol \"Bar\" in current package\n",
		"Foo docs.\n// [Bar]: unknown symbol \"Bar\" in current package\n",
	} {
		fmt.Printf("=== %q ===\n", text)
		dump(p.Parse(text))
		fmt.Println()
	}
}
EOF
go run .