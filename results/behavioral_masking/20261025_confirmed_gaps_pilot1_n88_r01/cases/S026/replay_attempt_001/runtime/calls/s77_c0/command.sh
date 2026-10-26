mkdir -p /tmp/checkertest && cd /tmp/checkertest && cat > go.mod <<'EOF'
module checkertest

go 1.25

require github.com/go-critic/go-critic v0.0.0
replace github.com/go-critic/go-critic => /app
EOF
cat > main.go <<'EOF'
package main

import "strings"

// Foo is documented by [Missing] and [strings.Missing].
func Foo() {}
EOF
cd /app && go build -o /tmp/gocritic ./cmd/go-critic && cd /tmp/checkertest && /tmp/gocritic check -enable=brokenDocLink ./... 2>&1 | head -20