package git

import (
	"fmt"
	"testing"
)

func TestMergeTextEdge(t *testing.T) {
	cases := []struct {
		name, base, ours, theirs string
	}{
		{"simple conflict", "a\nb\nc\n", "a\nOURS\nc\n", "a\nTHEIRS\nc\n"},
		{"non-overlap", "a\nb\nc\n", "OURS\nb\nc\n", "a\nb\nTHEIRS\n"},
		{"repeated non-overlap", "a\nb\na\nb\n", "a\nx\na\nb\n", "a\nb\na\ny\n"},
		{"repeated overlap", "a\nb\na\nb\n", "a\nx\na\nb\n", "a\ny\na\nb\n"},
		{"no trailing nl conflict", "a\nb", "a\nx", "a\ny"},
		{"insert vs modify", "a\nb\n", "a\nX\nb\n", "a\nb\n"},
		{"delete vs insert", "a\nb\n", "a\n", "a\nX\nb\n"},
		{"both insert same", "a\nb\n", "a\nX\nb\n", "a\nX\nb\n"},
		{"both insert diff", "a\nb\n", "a\nX\nb\n", "a\nY\nb\n"},
		{"empty base both add same", "", "a\n", "a\n"},
		{"empty base both add diff", "", "a\n", "b\n"},
	}
	for _, c := range cases {
		out, conflict := mergeText(c.base, c.ours, c.theirs)
		fmt.Printf("=== %s conflict=%v\n%q\n", c.name, conflict, out)
	}
}
