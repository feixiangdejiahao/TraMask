package vm

import (
 "fmt"
 "testing"
)

func TestFragmentS002Combined(t *testing.T) {
	t.Parallel()

	tests := []Test{
		{Script: `func f(a = 1, b = 2) { return a + b }; f()`, RunOutput: int64(3)},
		{Script: `func f(a = 1, b = 2) { return a + b }; f(10)`, RunOutput: int64(12)},
		{Script: `func f(a = 1, b = 2) { return a + b }; f(10, 20)`, RunOutput: int64(30)},
		{Script: `x = 100; func f(a = x, b = a + 1) { return a + b }; f()`, RunOutput: int64(201)},
		{Script: `func f(a, b = a) { return b }; f(5)`, RunOutput: int64(5)},
		{Script: `func f(a = 1, b = 2) { return a }; f(10, 20, 30)`, RunError: fmt.Errorf("function wants 2 arguments but received 3")},
		{Script: `func f(a) { return a }; f()`, RunError: fmt.Errorf("function wants 1 arguments but received 0")},
		{Script: `func f(a = 1) { return a }; f(nil)`, RunOutput: nil},

		// Variadic parameter may follow defaulted fixed parameters.
		{Script: `func f(a = 1, b = 2, rest...) { return [a, b, rest] }; f()`, RunOutput: []interface{}{int64(1), int64(2), []interface{}{}}},
		{Script: `func f(a = 1, b = 2, rest...) { return [a, b, rest] }; f(9, 8)`, RunOutput: []interface{}{int64(9), int64(8), []interface{}{}}},
		{Script: `func f(a = 1, b = 2, rest...) { return [a, b, rest] }; f(9, 8, 7, 6)`, RunOutput: []interface{}{int64(9), int64(8), []interface{}{int64(7), int64(6)}}},

		// Default expressions are evaluated at call time, left to right.
		{Script: `count = 0; func f(a = count++) { return a }; f(100); count`, RunOutput: int64(0)},
		{Script: `count = 0; func f(a = count++) { return a }; f(); count`, RunOutput: int64(1)},

		// Anonymous and nested functions.
		{Script: `f = func(a = 5) { return a }; f()`, RunOutput: int64(5)},
		{Script: `func outer(f = func(x = 3) { return x }) { return f() }; outer()`, RunOutput: int64(3)},

		// Complex default expressions.
		{Script: `func f(m = {"a": 1, "b": 2}) { return m.a }; f()`, RunOutput: int64(1)},
		{Script: `func f(a = [1, 2, 3], i = 1) { return a[i] }; f()`, RunOutput: int64(2)},

		// Multi-line default expressions must not shift positions of later functions.
		{Script: "func f(a = [1,\n2]) { return a[1] }\nfunc g(b = 5) { return b }; g()", RunOutput: int64(5)},
		{Script: "func f(a = [1,\n2]) { return a[1] }\nfunc g(b = 5) { return b }; f()", RunOutput: int64(2)},

		// Invalid declarations.
		{Script: `func f(a = 1, b) {}`, ParseError: fmt.Errorf("invalid default argument declaration")},
		{Script: `func f(a = 1, b = 2, c) {}`, ParseError: fmt.Errorf("invalid default argument declaration")},
		{Script: `func f(a = 1, b... = 2) {}`, ParseError: fmt.Errorf("invalid default argument declaration")},
		{Script: `func f(a = 1, b = 2, c...) { return c }; f()`, RunOutput: []interface{}{}},
	}
	runTests(t, tests, nil, nil)
}
