package vm

import (
	"fmt"
	"testing"
)

func TestDefaultArguments(t *testing.T) {
	t.Parallel()

	tests := []Test{
		{Script: `func f(a = 1, b = 2...) {}`, ParseError: fmt.Errorf("invalid default argument declaration")},
	}
	runTests(t, tests, nil, nil)
}
