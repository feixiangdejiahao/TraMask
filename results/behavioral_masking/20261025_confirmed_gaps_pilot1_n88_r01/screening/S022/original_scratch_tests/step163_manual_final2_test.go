package expr_test

import (
	"fmt"
	"testing"

	"github.com/expr-lang/expr"
)

func TestFinalCompilePaths(t *testing.T) {
	for _, in := range []string{
		`retry()`,
		`try { int("x") } catch e { errtype(e) }`,
		`try(1, 2)`,
		`try { throw("x") } catch (e) is "x" { e } finally { 1 }`,
	} {
		prog, err := expr.Compile(in, expr.AsAny())
		if err != nil {
			t.Errorf("compile %s: %v", in, err)
			continue
		}
		out, err := expr.Run(prog, nil)
		fmt.Printf("%s => out=%#v err=%v\n", in, out, err)
	}
}
