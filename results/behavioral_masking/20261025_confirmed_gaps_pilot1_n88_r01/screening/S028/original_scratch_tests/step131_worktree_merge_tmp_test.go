package git

import (
	"fmt"
	"testing"
)

func TestMergeTextDeleteDifferent(t *testing.T) {
	out, conflict := mergeText("a\nb\nc\n", "a\nc\n", "a\nb\n")
	fmt.Printf("conflict=%v out=%q\n", conflict, out)
}
