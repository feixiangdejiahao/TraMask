package evaluator

import (
 "testing"
 "github.com/abs-lang/abs/object"
)

func TestFragmentS001ReadControl(t *testing.T) {
	tests := []struct {
		input    string
		expected interface{}
	}{
		{`"1234567890"[1:8:2]`, "2468"},
		{`"1234567890"[8:1:-2]`, "9753"},
		{`"1234567890"[::-1]`, "0987654321"},
		{`"1234567890"[::2]`, "13579"},
		{`"1234567890"[4::-1]`, "54321"},
		{`"1234567890"[:5:2]`, "135"},
		{`"1234567890"[:]`, "1234567890"},
		{`"aé€"[1]`, "é"},
		{`"aé€"[-1]`, "€"},
		{`"aé€"[1:]`, "é€"},
		{`"aé€"[:-1]`, "aé"},
		{`"aé€"[::2]`, "a€"},
		{`"aé€"[::-1]`, "€éa"},
		{`"abc"[1:2:"x"]`, `index ranges can only be numerical: got "x" (type STRING)`},
	}

	for _, tt := range tests {
		evaluated := testEval(tt.input)
		switch expected := tt.expected.(type) {
		case string:
			if s, ok := evaluated.(*object.String); ok {
				if s.Value != expected {
					t.Errorf("result is not the right string for %q. got=%q, want=%q", tt.input, s.Value, expected)
				}
				continue
			}
			if errObj, ok := evaluated.(*object.Error); ok {
				logErrorWithPosition(t, errObj.Message, expected)
				continue
			}
			t.Errorf("object is not the right result for %q. got=%T (%+v)", tt.input, evaluated, evaluated)
		}
	}
}
