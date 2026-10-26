package git

import (
	"fmt"
	"testing"
)

func TestMergeTextNoTrailingNL(t *testing.T) {
	// base no trailing newline, ours modifies first line, theirs appends line
	out, conflict := mergeText("a\nb", "X\nb", "a\nb\nc")
	fmt.Printf("conflict=%v out=%q\n", conflict, out)
}
