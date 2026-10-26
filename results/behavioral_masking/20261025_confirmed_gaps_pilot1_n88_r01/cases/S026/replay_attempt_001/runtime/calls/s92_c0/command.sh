cd /tmp/cptest && cat > main.go <<'EOF'
package main

import (
	"fmt"
	"go/doc/comment"
)

func main() {
	for _, n := range []string{"math", "fmt", "strings", "missingpkg", "math.Sin", "example.com/foo"} {
		p, ok := comment.DefaultLookupPackage(n)
		fmt.Printf("%q -> %q %v\n", n, p, ok)
	}
}
EOF
go run .