package tengo_test

import (
	"testing"

	"github.com/d5/tengo/v2"
)

func TestDestructuringArray(t *testing.T) {
	// basic positional binding
	expectRun(t, `out = 0; [a, b] := [1, 2]; out = a + b`, nil, 3)

	// positions beyond the array length bind undefined
	expectRun(t, `out = 0; [a, b, c] := [1]; out = a; out = b; out = c`, nil, tengo.UndefinedValue)

	// empty pattern
	expectRun(t, `[] := [1, 2, 3]; out = 1`, nil, 1)

	// nested array patterns
	expectRun(t, `out = 0; [[a, b], c] := [[1, 2], 3]; out = a + b + c`, nil, 6)

	// rest element
	expectRun(t, `out = 0; [a, ...rest] := [1, 2, 3]; out = len(rest)`, nil, 2)
	expectRun(t, `out = 0; [a, ...rest] := [1, 2, 3]; out = rest[0] + rest[1]`, nil, 5)
	expectRun(t, `out = 0; [...rest] := [1, 2, 3]; out = len(rest)`, nil, 3)
	expectRun(t, `out = 0; [...rest] := []; out = len(rest)`, nil, 0)
	expectRun(t, `out = 0; [a, b, ...rest] := [1]; out = len(rest)`, nil, 0)

	// defaults
	expectRun(t, `out = 0; [a = 5] := []; out = a`, nil, 5)
	expectRun(t, `out = 0; [a = 5] := [2]; out = a`, nil, 2)

	// defaults reference earlier bindings
	expectRun(t, `out = 0; [a, b = a + 1] := [10]; out = b`, nil, 11)
	expectRun(t, `out = 0; [a, b = a + 1] := [10, 20]; out = b`, nil, 20)
}

func TestDestructuringMap(t *testing.T) {
	// renaming
	expectRun(t, `out = 0; {x: a} := {x: 10}; out = a`, nil, 10)

	// shorthand
	expectRun(t, `out = 0; {x} := {x: 10}; out = x`, nil, 10)

	// shorthand with default
	expectRun(t, `out = 0; {x = 5} := {}; out = x`, nil, 5)

	// renaming with default
	expectRun(t, `out = 0; {x: a = 50} := {}; out = a`, nil, 50)
	expectRun(t, `out = 0; {x: a = 50} := {x: 10}; out = a`, nil, 10)

	// absent key binds undefined
	expectRun(t, `out = 0; {x: a, y: b} := {x: 1}; out = b`, nil, tengo.UndefinedValue)

	// empty pattern
	expectRun(t, `{} := {a: 1}; out = 1`, nil, 1)

	// nested map patterns
	expectRun(t, `out = 0; {x: {a}} := {x: {a: 5}}; out = a`, nil, 5)

	// string keys
	expectRun(t, `out = 0; {"x": a} := {x: 42}; out = a`, nil, 42)
}

func TestDestructuringNested(t *testing.T) {
	expectRun(t, `out = 0; [{x: a}, b] := [{x: 1}, 2]; out = a + b`, nil, 3)
	expectRun(t, `out = 0; {x: [a, b]} := {x: [1, 2]}; out = a + b`, nil, 3)
	expectRun(t, `out = 0; [[{y: a}]] := [[{y: 9}]]; out = a`, nil, 9)
}

func TestDestructuringFunctionParams(t *testing.T) {
	expectRun(t, `out = 0; f := func([a, b]) { return a + b }; out = f([1, 2])`, nil, 3)
	expectRun(t, `out = 0; f := func({x: a, y}) { return a + y }; out = f({x: 10, y: 20})`, nil, 30)
	expectRun(t, `out = 0; f := func([[a], b]) { return a + b }; out = f([[5], 3])`, nil, 8)
	expectRun(t, `out = 0; f := func([a = 10]) { return a }; out = f([])`, nil, 10)
	expectRun(t, `out = 0; f := func([a, ...rest]) { return len(rest) }; out = f([1, 2, 3])`, nil, 2)
	expectRun(t, `out = 0; f := func([a, ...rest]) { return len(rest) }; out = f([1])`, nil, 0)
	expectRun(t, `out = 0; f := func([a], ...rest) { return a + len(rest) }; out = f([1], 2, 3)`, nil, 3)
	expectRun(t, `out = 0; f := func([a, b = a + 1]) { return b }; out = f([5])`, nil, 6)
}

func TestDestructuringErrors(t *testing.T) {
	expectCompileError(t, `[a, ...b, c] := [1, 2, 3]`, "rest element must be last")
	expectCompileError(t, `[a, b] = [1, 2]`, "cannot use destructuring with =")
	expectCompileError(t, `{x: a} = {x: 1}`, "cannot use destructuring with =")
	expectCompileError(t, `a := 1; [a, b] := [2, 3]`, "redeclared")
}
