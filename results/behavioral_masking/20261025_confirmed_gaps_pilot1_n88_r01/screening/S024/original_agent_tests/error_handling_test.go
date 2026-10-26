package expr_test

import (
	"fmt"
	"testing"

	"github.com/expr-lang/expr"
	"github.com/expr-lang/expr/internal/testify/require"
)

type errorTestS struct {
	Foo int
}

func evalErr(t *testing.T, input string, env any) (any, error) {
	t.Helper()
	return expr.Eval(input, env)
}

func TestTryFunctionForm(t *testing.T) {
	env := map[string]any{
		"a": []int{1, 2, 3},
	}

	out, err := evalErr(t, `try(1 + 2, 99)`, env)
	require.NoError(t, err)
	require.Equal(t, 3, out)

	out, err = evalErr(t, `try(a[10], 99)`, env)
	require.NoError(t, err)
	require.Equal(t, 99, out)

	// The fallback is lazy: it must not be evaluated on success.
	out, err = evalErr(t, `try(1, throw("must not run"))`, env)
	require.NoError(t, err)
	require.Equal(t, 1, out)

	// An error thrown by the fallback propagates.
	_, err = evalErr(t, `try(a[10], throw("fallback"))`, env)
	require.Error(t, err)
	require.Contains(t, err.Error(), "fallback")
}

func TestTryArity(t *testing.T) {
	_, err := expr.Compile(`try(1)`)
	require.Error(t, err)

	_, err = expr.Compile(`try(1, 2, 3)`)
	require.Error(t, err)
	require.Contains(t, err.Error(), "exactly two arguments")
}

func TestTryBlockForm(t *testing.T) {
	env := map[string]any{
		"a": []int{1, 2, 3},
	}

	out, err := evalErr(t, `try { 1 + 2 } catch { 99 }`, env)
	require.NoError(t, err)
	require.Equal(t, 3, out)

	out, err = evalErr(t, `try { a[10] } catch { 99 }`, env)
	require.NoError(t, err)
	require.Equal(t, 99, out)

	out, err = evalErr(t, `try { a[10] } catch err { errtype(err) }`, env)
	require.NoError(t, err)
	require.Equal(t, "index", out)
}

func TestTrySubstringFilter(t *testing.T) {
	env := map[string]any{
		"a": []int{1, 2, 3},
	}

	out, err := evalErr(t, `try { a[10] } catch e is "out of range" { errtype(e) }`, env)
	require.NoError(t, err)
	require.Equal(t, "index", out)

	// Non-matching filter propagates the error.
	_, err = evalErr(t, `try { a[10] } catch e is "not this" { 42 }`, env)
	require.Error(t, err)
	require.Contains(t, err.Error(), "out of range")
}

func TestThrow(t *testing.T) {
	out, err := evalErr(t, `try { throw("boom") } catch e { errtype(e) }`, nil)
	require.NoError(t, err)
	require.Equal(t, "custom", out)

	_, err = evalErr(t, `throw("boom")`, nil)
	require.Error(t, err)
	require.Contains(t, err.Error(), "boom")

	// throw requires exactly one argument.
	_, err = expr.Compile(`throw()`)
	require.Error(t, err)
	_, err = expr.Compile(`throw(1, 2)`)
	require.Error(t, err)
}

func TestErrType(t *testing.T) {
	env := map[string]any{
		"a": []int{1, 2, 3},
		"s": (*errorTestS)(nil),
		"x": "hello",
	}

	tests := []struct {
		input string
		want  string
	}{
		{`try { a[10] } catch e { errtype(e) }`, "index"},
		{`try { int("x") } catch e { errtype(e) }`, "conversion"},
		{`try { 1 + x } catch e { errtype(e) }`, "type"},
		{`try { s.Foo } catch e { errtype(e) }`, "nil"},
		{`try { throw("boom") } catch e { errtype(e) }`, "custom"},
		{`errtype(nil)`, "none"},
	}

	for _, tt := range tests {
		out, err := evalErr(t, tt.input, env)
		require.NoError(t, err)
		require.Equal(t, tt.want, out, tt.input)
	}
}

func TestFinally(t *testing.T) {
	env := map[string]any{
		"a": []int{1, 2, 3},
		"log": func(s string) any {
			fmt.Println("cleanup:", s)
			return s
		},
	}

	out, err := evalErr(t, `try { 1 + 2 } catch { 0 } finally { log("fin") }`, env)
	require.NoError(t, err)
	require.Equal(t, 3, out)

	out, err = evalErr(t, `try { a[10] } catch { 7 } finally { log("fin") }`, env)
	require.NoError(t, err)
	require.Equal(t, 7, out)

	// If the finally body throws, that error overrides the prior result.
	_, err = evalErr(t, `try { a[10] } catch { 7 } finally { throw("cleanup failed") }`, env)
	require.Error(t, err)
	require.Contains(t, err.Error(), "cleanup failed")
}

func TestRetry(t *testing.T) {
	count := 0
	env := map[string]any{
		"fail": func() any {
			count++
			if count < 3 {
				panic("not yet")
			}
			return count
		},
	}

	out, err := evalErr(t, `try { fail() } catch e { retry() }`, env)
	require.NoError(t, err)
	require.Equal(t, 3, out)
	require.Equal(t, 3, count)
}

func TestRetryExhaustion(t *testing.T) {
	env := map[string]any{
		"fail": func() any { panic("always") },
	}

	_, err := evalErr(t, `try { fail() } catch e { retry() }`, env)
	require.Error(t, err)
	require.Contains(t, err.Error(), "retry limit exceeded")

	out, err := evalErr(t, `try { try { fail() } catch e { retry() } } catch e2 { errtype(e2) }`, env)
	require.NoError(t, err)
	require.Equal(t, "retry", out)
}

func TestRetryOutsideCatch(t *testing.T) {
	_, err := evalErr(t, `retry()`, nil)
	require.Error(t, err)
	require.Contains(t, err.Error(), "outside a catch")
}

func TestFinallyRunsOnAllPaths(t *testing.T) {
	var cleanup []string
	env := map[string]any{
		"a": []int{1, 2, 3},
		"cleanup": func(s string) any {
			cleanup = append(cleanup, s)
			return s
		},
	}

	// Finally runs after a successful try.
	cleanup = nil
	_, err := evalErr(t, `try { 1 } catch { 0 } finally { cleanup("success") }`, env)
	require.NoError(t, err)
	require.Equal(t, []string{"success"}, cleanup)

	// Finally runs after the catch handler throws.
	cleanup = nil
	_, err = evalErr(t, `try { a[10] } catch { throw("catch") } finally { cleanup("catch-throw") }`, env)
	require.Error(t, err)
	require.Contains(t, err.Error(), "catch")
	require.Equal(t, []string{"catch-throw"}, cleanup)

	// Finally runs when the catch filter does not match.
	cleanup = nil
	_, err = evalErr(t, `try { a[10] } catch e is "nomatch" { 0 } finally { cleanup("nomatch") }`, env)
	require.Error(t, err)
	require.Equal(t, []string{"nomatch"}, cleanup)
}

func TestErrTypeRetryExhaustion(t *testing.T) {
	env := map[string]any{
		"fail": func() any { panic("always") },
	}
	out, err := evalErr(t, `try { try { fail() } catch e { retry() } } catch e2 { errtype(e2) }`, env)
	require.NoError(t, err)
	require.Equal(t, "retry", out)
}

func TestNestedTry(t *testing.T) {
	env := map[string]any{
		"a": []int{1, 2, 3},
	}

	out, err := evalErr(t, `try { try { a[10] } catch e is "no match" { 0 } } catch e { errtype(e) }`, env)
	require.NoError(t, err)
	require.Equal(t, "index", out)
}

func TestTryInExpression(t *testing.T) {
	env := map[string]any{
		"a": []int{1, 2, 3},
	}

	out, err := evalErr(t, `1 + try(a[10], 41)`, env)
	require.NoError(t, err)
	require.Equal(t, 42, out)

	out, err = evalErr(t, `try(a[10], 1) == 1`, env)
	require.NoError(t, err)
	require.Equal(t, true, out)

	out, err = evalErr(t, `filter(a, try(int("1"), 0) == 1)`, env)
	require.NoError(t, err)
	require.Equal(t, []any{1, 2, 3}, out)
}

func TestTryScopeRestore(t *testing.T) {
	env := map[string]any{
		"a": []int{1, 2, 3},
	}

	out, err := evalErr(t, `try { count(a, int("x") == 1) } catch e { "caught" }`, env)
	require.NoError(t, err)
	require.Equal(t, "caught", out)
}
