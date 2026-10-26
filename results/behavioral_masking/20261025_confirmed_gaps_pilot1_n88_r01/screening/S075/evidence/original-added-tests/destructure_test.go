package tengo_test

import (
	"strings"
	"testing"

	"github.com/d5/tengo/v2"
	"github.com/d5/tengo/v2/parser"
)

func TestDestructuringArray(t *testing.T) {
	expectRun(t, `[a, b] := [1, 2]; out = [a, b]`, nil, ARR{1, 2})
	expectRun(t, `[a, b] := [1]; out = [a, b]`, nil,
		ARR{1, tengo.UndefinedValue})
	expectRun(t, `[a, b = 50] := [1]; out = [a, b]`, nil, ARR{1, 50})
	expectRun(t, `[a, b = 50] := [1, 2]; out = [a, b]`, nil, ARR{1, 2})
	expectRun(t, `[a, ...rest] := [1, 2, 3]; out = [a, rest]`, nil,
		ARR{1, ARR{2, 3}})
	expectRun(t, `[a, ...rest] := [1]; out = [a, rest]`, nil,
		ARR{1, ARR{}})
	expectRun(t, `[] := [1, 2]; out = 1`, nil, 1)
	expectRun(t, `[a, [b, c]] := [1, [2, 3]]; out = [a, b, c]`, nil,
		ARR{1, 2, 3})
}

func TestDestructuringMap(t *testing.T) {
	expectRun(t, `{x: a} := {x: 1}; out = a`, nil, 1)
	expectRun(t, `{x} := {x: 1}; out = x`, nil, 1)
	expectRun(t, `{x: a = 50} := {}; out = a`, nil, 50)
	expectRun(t, `{x: a = 50} := {x: 2}; out = a`, nil, 2)
	expectRun(t, `{x = 50} := {}; out = x`, nil, 50)
	expectRun(t, `{x: [a, b]} := {x: [1, 2]}; out = [a, b]`, nil,
		ARR{1, 2})
	expectRun(t, `{} := {x: 1}; out = 1`, nil, 1)
	expectRun(t, `{"x": a} := {"x": 3}; out = a`, nil, 3)
}

func TestDestructuringDefaultsLazy(t *testing.T) {
	// default expression should only be evaluated when the value is missing.
	expectRun(t,
		`f := func() { return 100 }; [a = f()] := [1]; out = a`,
		nil, 1)
	expectRun(t,
		`f := func() { return 100 }; [a = f()] := []; out = a`,
		nil, 100)
	// defaults may reference bindings established earlier
	expectRun(t,
		`[a, b = a + 1] := [1]; out = [a, b]`, nil, ARR{1, 2})
}

func TestDestructuringFunctionParams(t *testing.T) {
	expectRun(t,
		`f := func([a, b]) { return a + b }; out = f([1, 2])`, nil, 3)
	expectRun(t,
		`f := func({x: a}) { return a }; out = f({x: 10})`, nil, 10)
	expectRun(t,
		`f := func([a, b = 5]) { return a + b }; out = f([1])`, nil, 6)
	expectRun(t,
		`f := func([a, ...rest]) { return rest }; out = f([1, 2, 3])`,
		nil, ARR{2, 3})
	expectRun(t,
		`f := func(a = 10) { return a }; out = f(undefined)`, nil, 10)
	expectRun(t,
		`f := func([a], ...rest) { return [a, rest] }; out = f([1], 2, 3)`,
		nil, ARR{1, ARR{2, 3}})
}

func TestDestructuringErrors(t *testing.T) {
	expectCompileError(t, `[a, b] = [1, 2]`,
		"cannot use destructuring with =")
	expectCompileError(t, `{x} = {x: 1}`,
		"cannot use destructuring with =")

	// rest element must be last
	fileSet := parser.NewFileSet()
	file := fileSet.AddFile("test", -1, len(`[a, ...rest, b] := [1, 2, 3]`))
	p := parser.NewParser(file, []byte(`[a, ...rest, b] := [1, 2, 3]`), nil)
	_, err := p.ParseFile()
	if err == nil || !strings.Contains(err.Error(), "rest element must be last") {
		t.Fatalf("expected rest error, got %v", err)
	}

	// rest is not supported in map patterns
	fileSet = parser.NewFileSet()
	file = fileSet.AddFile("test", -1, len(`{...rest} := {a: 1}`))
	p = parser.NewParser(file, []byte(`{...rest} := {a: 1}`), nil)
	_, err = p.ParseFile()
	if err == nil {
		t.Fatal("expected parse error for map rest")
	}
}
