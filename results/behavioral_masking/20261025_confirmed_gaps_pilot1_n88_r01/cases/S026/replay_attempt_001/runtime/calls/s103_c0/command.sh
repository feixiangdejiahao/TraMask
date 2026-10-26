cd /tmp/checkertest && cat > main.go <<'EOF'
package main

import (
	"strings"
	str "strings"
	. "sort"
)

type Base struct{ X int }
func (Base) M() {}
type T struct{ Base }
func (T) N() {}

var NotType int

// [Missing], [str.Missing], [T.Missing], [NotType.X], [missingpkg.Foo]
// [foo bar], [fmt.println], [IntSlice.Sort], [T.X], [T.M], [int]
func Doc() {}
EOF
cd /app && /tmp/gocritic check -enable=brokenDocLink /tmp/checkertest/main.go 2>&1 | head -20