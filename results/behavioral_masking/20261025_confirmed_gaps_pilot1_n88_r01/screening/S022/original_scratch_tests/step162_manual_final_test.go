package expr_test

import (
	"fmt"
	"testing"

	"github.com/expr-lang/expr"
)

type nilEnv struct{ Foo *int }

func TestFinalComprehensive(t *testing.T) {
	env := map[string]any{"p": (*nilEnv)(nil)}
	cases := []struct {
		input string
		env   any
		want  any
	}{
		{`try(int("abc"), 42)`, nil, 42},
		{`try(2 + 2, 42)`, nil, 4},
		{`try { int("abc") } catch { "caught" }`, nil, "caught"},
		{`try { int("abc") } catch e is "invalid operation" { "type caught" }`, nil, "type caught"},
		{`try { 1 } catch { "caught" } finally { 99 }`, nil, 1},
		{`try { throw("boom") } catch e { e }`, nil, "boom"},
		{`try { [][0] } catch e { errtype(e) }`, nil, "index"},
		{`try { int("abc") } catch e { errtype(e) }`, nil, "conversion"},
		{`try { 1 + "a" } catch e { errtype(e) }`, nil, "type"},
		{`try { p.Foo } catch e { errtype(e) }`, env, "nil"},
		{`try { throw("x") } catch e { errtype(e) }`, nil, "custom"},
		{`errtype(nil)`, nil, "none"},
		{`try(1, 2) + 1`, nil, 2},
		{`try { try { throw("always") } catch { retry() } } catch e { errtype(e) }`, nil, "retry"},
		{`try { try { int("x") } catch e { throw("inner:" + e) } } catch e2 { e2 }`, nil, "inner:invalid operation: int(x)"},
	}
	for _, c := range cases {
		got, err := expr.Eval(c.input, c.env)
		if err != nil {
			t.Errorf("%s: error: %v", c.input, err)
			continue
		}
		if fmt.Sprintf("%v", got) != fmt.Sprintf("%v", c.want) {
			t.Errorf("%s: got %#v want %#v", c.input, got, c.want)
		}
	}

	// retry success
	count := 0
	env2 := map[string]any{"get": func() int { count++; return count }}
	prog, err := expr.Compile(`try { let n = get(); if n < 3 { throw("again") } else { n } } catch e { retry }`, expr.Env(env2), expr.AsAny())
	if err != nil {
		t.Fatalf("compile retry: %v", err)
	}
	out, err := expr.Run(prog, env2)
	if fmt.Sprintf("%v", out) != "3" || count != 3 {
		t.Errorf("retry success: got=%#v count=%d err=%v", out, count, err)
	}
}
