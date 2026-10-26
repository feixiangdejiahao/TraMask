package git

import (
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/go-git/go-git/v6/plumbing"
)

func TestMergeConflictHeadUnchanged(t *testing.T) {
	r, w := mergeTestRepo(t, map[string]string{"file.txt": "a\nb\nc\n"})
	require.NoError(t, w.Filesystem.MkdirAll(".git", 0o755))
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.NewBranchReferenceName("feature"), Create: true}))
	mergeWriteCommit(t, w, map[string]string{"file.txt": "a\nTHEIRS\nc\n"}, "theirs")
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.Master}))
	mergeWriteCommit(t, w, map[string]string{"file.txt": "a\nOURS\nc\n"}, "ours")
	headBefore, err := r.Head()
	require.NoError(t, err)
	featureRef, err := r.Reference(plumbing.NewBranchReferenceName("feature"), true)
	require.NoError(t, err)
	err = w.Merge(featureRef.Hash(), &MergeOptions{})
	require.ErrorIs(t, err, ErrMergeConflicts)
	headAfter, err := r.Head()
	require.NoError(t, err)
	require.Equal(t, headBefore.Hash(), headAfter.Hash())
}
