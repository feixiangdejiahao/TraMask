package expr_test

import (
	"fmt"
	"testing"

	"github.com/expr-lang/expr"
)

func TestManualBareRetry(t *testing.T) {
	count := 0
	env := map[string]any{"get": func() int { count++; return count }}
	prog, err := expr.Compile(`try { let n = get(); if n < 3 { throw("again") } else { n } } catch e { retry }`, expr.Env(env), expr.AsAny())
	if err != nil {
		t.Fatalf("compile: %v", err)
	}
	out, err := expr.Run(prog, env)
	fmt.Printf("bare retry: out=%#v count=%d err=%v\n", out, count, err)
}
