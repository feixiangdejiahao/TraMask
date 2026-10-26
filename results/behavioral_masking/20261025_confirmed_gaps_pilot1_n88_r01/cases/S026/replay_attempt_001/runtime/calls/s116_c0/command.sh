cd /app && go build -o /tmp/gocritic ./cmd/go-critic && cd /tmp/checkertest && cat > main.go <<'EOF'
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
// [foo bar], [fmt.println], [IntSlice.Sort], [T.X], [T.M], [int], [strings.Builder.Reset]
func Doc() {}
EOF
/tmp/gocritic check -enable=brokenDocLink ./main.go 2>&1 | head -20