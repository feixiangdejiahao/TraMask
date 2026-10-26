package expr_test

import (
	"fmt"
	"testing"

	"github.com/expr-lang/expr"
)

func TestManualEdge(t *testing.T) {
	cases := []struct {
		input string
		want  any
	}{
		// nested catch: inner catch handler throws, outer catches
		{`try { try { int("x") } catch e { throw("inner:" + e) } } catch e2 { e2 }`, "inner:invalid operation: int(x)"},
		// error in finally propagates to outer catch
		{`try { try { 1 } finally { throw("cleanup") } } catch e { e }`, "cleanup"},
		// finally runs on uncaught inner error, outer catches original
		{`try { try { int("x") } finally { 99 } } catch e { e }`, "invalid operation: int(x)"},
		// retry exhaustion caught by outer catch and errtype
		{`try { try { throw("always") } catch { retry() } } catch e { errtype(e) }`, "retry"},
		// catch pattern non-match then finally then propagate
		{`try { try { int("x") } catch e is "nomatch" { "nope" } finally { 42 } } catch e2 { e2 }`, "invalid operation: int(x)"},
		// success with finally returning different type
		{`try { 1 } finally { "cleanup" }`, 1},
		// catch returns value, finally cleanup
		{`try { int("x") } catch { 42 } finally { "cleanup" }`, 42},
		// error inside predicate loop, caught and retried
		{`try { [1,2,3] |> map(#) |> len() } catch { 0 }`, 3},
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
