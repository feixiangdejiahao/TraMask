package expr_test

import (
	"fmt"
	"testing"

	"github.com/expr-lang/expr"
)

func TestManualNestedFinally(t *testing.T) {
	cases := []struct {
		input string
		want  any
	}{
		{`try { try { int("x") } catch e { throw("y") } } finally { 3 }`, "error:y"},
		{`try { try { int("x") } catch e { throw("y") } } catch e2 { e2 } finally { 3 }`, "y"},
		{`try { try { int("x") } finally { 3 } } catch e2 { e2 }`, "invalid operation: int(x)"},
		{`try { try { int("x") } catch e { "caught" } finally { 3 } } catch e2 { "outer:" + e2 }`, "caught"},
	}
	for _, c := range cases {
		got, err := expr.Eval(c.input, nil)
		if c.want == "" {
			continue
		}
		if c.want == "error:y" {
			if err == nil || !containsStr(err.Error(), "y") {
				t.Errorf("%s: got=%#v err=%v", c.input, got, err)
			}
			continue
		}
		if err != nil {
			t.Errorf("%s: error: %v", c.input, err)
			continue
		}
		if fmt.Sprintf("%v", got) != fmt.Sprintf("%v", c.want) {
			t.Errorf("%s: got %#v want %#v", c.input, got, c.want)
		}
	}
}

func containsStr(s, sub string) bool {
	return len(s) >= len(sub) && (func() bool {
		for i := 0; i+len(sub) <= len(s); i++ {
			if s[i:i+len(sub)] == sub {
				return true
			}
		}
		return false
	})()
}
