package evaluator

import (
 "testing"
 "github.com/abs-lang/abs/object"
)

func TestFragmentS001Original(t *testing.T) {
	tests := []struct {
		input    string
		expected interface{}
	}{
		{`s="hello"; s[0]="H"; s`, "Hello"},
		{`s="hello"; s[1:3]="EY"; s`, "hEYlo"},
		{`s="hello"; s[2:5:2]="A"; s`, "heAlA"},
		{`s="hello"; s[1:4]="X"; s`, "hXXXo"},
		{`s="héllo"; s[1]="É"; s`, "hÉllo"},
		{`s="héllo"; s[1:3]="X"; s`, "hXXlo"},
		{`s="hello"; s[3:1]="x"`, "range assignment size mismatch: target=0 value=1"},
		{`s="hello"; s[1:3]=5`, "range assignment expects STRING value, got NUMBER"},
		{`s="hello"; s[0]="too long"`, "index assignment expects single-character STRING value, got 8 characters"},
		{`s="hello"; s[1:3]="abcdef"`, "range assignment size mismatch: target=2 value=6"},
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
