mkdir -p /tmp/cptest && cd /tmp/cptest && cat > main.go <<'EOF'
package main

import (
	"fmt"
	"go/doc/comment"
)

func walkTexts(ts []comment.Text, depth int) {
	for _, t := range ts {
		switch v := t.(type) {
		case comment.Plain:
			fmt.Printf("%*sPlain: %q\n", depth, "", string(v))
		case comment.Italic:
			fmt.Printf("%*sItalic: %q\n", depth, "", string(v))
		case *comment.Link:
			fmt.Printf("%*sLink: text=%q url=%q auto=%v\n", depth, "", v.Text, v.URL, v.Auto)
		case *comment.DocLink:
			fmt.Printf("%*sDocLink: imp=%q recv=%q name=%q text=%v\n", depth, "", v.ImportPath, v.Recv, v.Name, v.Text)
		}
	}
}

func walkBlocks(bs []comment.Block, depth int) {
	for _, b := range bs {
		switch v := b.(type) {
		case *comment.Paragraph:
			fmt.Printf("%*sParagraph:\n", depth, "")
			walkTexts(v.Text, depth+2)
		case *comment.List:
			fmt.Printf("%*sList:\n", depth, "")
			for _, item := range v.Items {
				fmt.Printf("%*sItem:\n", depth+2, "")
				walkBlocks(item.Content, depth+4)
			}
		case *comment.Heading:
			fmt.Printf("%*sHeading: %q\n", depth, "", v.Text)
		case *comment.Code:
			fmt.Printf("%*sCode: %q\n", depth, "", v.Text)
		}
	}
}

func parse(text string, lookupSym bool, lookupPkg bool) {
	p := &comment.Parser{
		LookupSym: func(recv, name string) bool { return lookupSym },
		LookupPackage: func(name string) (string, bool) {
			if lookupPkg {
				return name, true
			}
			return "", false
		},
	}
	d := p.Parse(text)
	fmt.Printf("=== %q ===\n", text)
	walkBlocks(d.Content, 0)
	fmt.Println()
}

func main() {
	parse("[Foo]", true, true)
	parse("[Foo.Bar]", true, true)
	parse("[pkg.Foo]", true, true)
	parse("[pkg.Recv.Method]", true, true)
	parse("[Recv.Method]", true, true)
	parse("[math]", true, true)
	parse("[foo bar]", true, true)
	parse("[foo-bar]", true, true)
	parse("[Foo.Bar Baz]", true, true)
	parse("[*Foo]", true, true)
	parse("map[ast.Expr]TypeAndValue", true, true)
	parse("pre [Foo] post", true, true)
	parse("pre[Foo]post", true, true)
	parse("[T]", false, false)
	parse("[pkg.T]", false, false)
	parse("[T.M]", false, false)
}
EOF
cat > go.mod <<'EOF'
module cptest

go 1.25
EOF
go run .