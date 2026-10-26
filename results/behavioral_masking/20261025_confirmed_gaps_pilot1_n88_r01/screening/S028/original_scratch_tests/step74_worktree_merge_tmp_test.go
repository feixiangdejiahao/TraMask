package git

import (
	"fmt"
	"testing"
)

func TestMergeTextTrickyRepeated(t *testing.T) {
	cases := []struct {
		name, base, ours, theirs string
	}{
		{"same middle", "foo\nfoo\nfoo\n", "foo\nbar\nfoo\n", "foo\nbaz\nfoo\n"},
	}
	for _, c := range cases {
		out, conflict := mergeText(c.base, c.ours, c.theirs)
		fmt.Printf("%s: conflict=%v out=%q\n", c.name, conflict, out)
	}
}
