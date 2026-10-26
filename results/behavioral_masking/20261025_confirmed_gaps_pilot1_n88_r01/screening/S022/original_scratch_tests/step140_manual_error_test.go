package expr_test

import (
	"fmt"
	"testing"

	"github.com/expr-lang/expr"
)

func TestManualMisc(t *testing.T) {
	cases := []struct {
		input string
		want  any
	}{
		{`let x = try(int("a"), 42); x`, 42},
		{`let x = try { int("a") } catch { 7 }; x + 1`, 8},
		{`try(int("a"), 1) == 1`, true},
		{`if try(int("a"), 0) == 0 { "ok" } else { "bad" }`, "ok"},
		{`{a: try(int("x"), 1)}.a`, 1},
	}
	for _, c := range cases {
		got, err := expr.Eval(c.input, nil)
		if err != nil {
			t.Errorf("%s: error: %v", c.input, err)
			continue
		}
		if fmt.Sprintf("%v", got) != fmt.Sprintf("%v", c.want) {
			t.Errorf("%s: got %#v want %#v", c.input, got, c.want)
		}
	}
}
