// Manual retrospective evaluator control; excluded from generator inputs.
package git

import "testing"

func TestRelationalEvaluatorMerge(t *testing.T) {
	base := "a\nb\nc\nd\ne\n"
	t.Run("control_identical_interval", func(t *testing.T) {
		_, conflict := mergeText(base, "a\nB_OURS\nc\nd\ne\n", "a\nB_THEIRS\nc\nd\ne\n")
		if !conflict { t.Fatal("same-line edits must conflict") }
	})
	t.Run("control_disjoint", func(t *testing.T) {
		_, conflict := mergeText(base, "A_OURS\nb\nc\nd\ne\n", "a\nb\nc\nD_THEIRS\ne\n")
		if conflict { t.Fatal("disjoint edits must merge") }
	})
	t.Run("gap_partial_overlap", func(t *testing.T) {
		got, conflict := mergeText(base, "a\nB_OURS\nC_OURS\nd\ne\n", "a\nb\nC_THEIRS\nD_THEIRS\ne\n")
		if !conflict { t.Fatalf("partial overlap silently merged: %q", got) }
	})
}
