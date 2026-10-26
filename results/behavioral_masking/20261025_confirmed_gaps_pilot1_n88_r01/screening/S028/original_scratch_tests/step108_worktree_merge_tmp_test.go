package git

import (
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/go-git/go-git/v6/plumbing"
)

func TestMergeDeleteModifyTheirsDeleted(t *testing.T) {
	r, w := mergeTestRepo(t, map[string]string{"file.txt": "base\n"})
	require.NoError(t, w.Filesystem.MkdirAll(".git", 0o755))
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.NewBranchReferenceName("feature"), Create: true}))
	mergeWriteCommit(t, w, map[string]string{"file.txt": "modified\n"}, "modify")
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.Master}))
	require.NoError(t, w.Filesystem.Remove("file.txt"))
	_, err := w.Remove("file.txt")
	require.NoError(t, err)
	_, err = w.Commit("delete", &CommitOptions{Author: mergeTestSignature()})
	require.NoError(t, err)
	featureRef, err := r.Reference(plumbing.NewBranchReferenceName("feature"), true)
	require.NoError(t, err)
	err = w.Merge(featureRef.Hash(), &MergeOptions{})
	t.Logf("merge err: %v", err)
	require.ErrorIs(t, err, ErrMergeConflicts)
}
