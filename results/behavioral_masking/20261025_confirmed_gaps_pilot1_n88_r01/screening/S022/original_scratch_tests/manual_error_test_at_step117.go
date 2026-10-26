package expr_test

import (
	"fmt"
	"strings"
	"testing"

	"github.com/expr-lang/expr"
)

type nilEnv struct{ Foo *int }

func TestManualErrorHandling(t *testing.T) {
	env := map[string]any{"p": (*nilEnv)(nil)}
	cases := []struct {
		input string
		env   any
		want  any
	}{
		{`try(int("abc"), 0)`, nil, 0},
		{`try(int("abc"), 42)`, nil, 42},
		{`try(2 + 2, 42)`, nil, 4},
		{`try { int("abc") } catch { "caught" }`, nil, "caught"},
		{`try { int("abc") } catch e { e }`, nil, `invalid operation: int(abc)`},
		{`try { int("abc") } catch e is "invalid operation" { "type caught" }`, nil, "type caught"},
		{`try { int("abc") } catch e is "not present" { "nope" }`, nil, "error"},
		{`try { 1 } catch { "caught" } finally { 99 }`, nil, 1},
		{`try { int("abc") } catch { "caught" } finally { 99 }`, nil, "caught"},
		{`try { 1 } finally { 99 }`, nil, 1},
		{`try { throw("boom") } catch e { e }`, nil, "boom"},
		{`try { throw(123) } catch e { e }`, nil, "123"},
		{`try { [][0] } catch e { errtype(e) }`, nil, "index"},
		{`try { int("abc") } catch e { errtype(e) }`, nil, "conversion"},
		{`try { 1 + "a" } catch e { errtype(e) }`, nil, "type"},
		{`try { p.Foo } catch e { errtype(e) }`, env, "nil"},
		{`try { throw("x") } catch e { errtype(e) }`, nil, "custom"},
		{`errtype(nil)`, nil, "none"},
		{`try { throw("x") } catch { retry() }`, nil, "error"},
	}
	for _, c := range cases {
		got, err := expr.Eval(c.input, c.env)
		if err != nil {
			if c.want == "error" {
				continue
			}
			t.Errorf("%s: unexpected error: %v", c.input, err)
			continue
		}
		if c.want == "error" {
			t.Errorf("%s: expected error, got %#v", c.input, got)
			continue
		}
		if fmt.Sprintf("%v", got) != fmt.Sprintf("%v", c.want) {
			t.Errorf("%s: got %#v, want %#v", c.input, got, c.want)
		}
	}
}

func TestManualRetry(t *testing.T) {
	// retry outside catch (inside try) should be caught by the catch
	got, err := expr.Eval(`try { retry() } catch { "caught" }`, nil)
	if fmt.Sprintf("%v", got) != "caught" || err != nil {
		t.Errorf("retry outside catch: got=%#v err=%v", got, err)
	}

	// retry at top level
	_, err = expr.Eval(`retry()`, nil)
	if err == nil {
		t.Errorf("retry at top level should error")
	}

	// retry exhaustion classified retry
	got, err = expr.Eval(`try { try { throw("always") } catch { retry() } } catch e { errtype(e) }`, nil)
	if fmt.Sprintf("%v", got) != "retry" || err != nil {
		t.Errorf("retry type: got=%#v err=%v", got, err)
	}

	// retry success
	count := 0
	env := map[string]any{"get": func() int { count++; return count }}
	prog, err := expr.Compile(`try { let n = get(); if n < 3 { throw("again") } else { n } } catch e { retry() }`, expr.Env(env), expr.AsAny())
	if err != nil {
		t.Fatalf("compile: %v", err)
	}
	out, err := expr.Run(prog, env)
	if fmt.Sprintf("%v", out) != "3" || count != 3 {
		t.Errorf("retry success: got=%#v count=%d err=%v", out, count, err)
	}

	// finally throw overrides
	_, err = expr.Eval(`try { 1 } finally { throw("cleanup") }`, nil)
	if err == nil || !strings.Contains(err.Error(), "cleanup") {
		t.Errorf("finally throw: err=%v", err)
	}
	_, err = expr.Eval(`try { int("x") } catch { "caught" } finally { throw("cleanup") }`, nil)
	if err == nil || !strings.Contains(err.Error(), "cleanup") {
		t.Errorf("finally throw2: err=%v", err)
	}

	// lazy fallback
	sideEffect := false
	env2 := map[string]any{"boom": func() int { sideEffect = true; return 1 }}
	got, err = expr.Eval(`try(1, boom())`, env2)
	if fmt.Sprintf("%v", got) != "1" || sideEffect {
		t.Errorf("lazy fallback: got=%#v sideEffect=%v err=%v", got, sideEffect, err)
	}
}
