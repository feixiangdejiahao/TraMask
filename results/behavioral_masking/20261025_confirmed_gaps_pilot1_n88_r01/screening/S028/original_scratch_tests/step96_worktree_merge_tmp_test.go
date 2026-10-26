package git

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/go-git/go-git/v6/plumbing"
)

func TestMergeCommitAllAfterConflict(t *testing.T) {
	r, w := mergeTestRepo(t, map[string]string{"file.txt": "a\nb\nc\n"})
	require.NoError(t, w.Filesystem.MkdirAll(".git", 0o755))
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.NewBranchReferenceName("feature"), Create: true}))
	mergeWriteCommit(t, w, map[string]string{"file.txt": "a\nTHEIRS\nc\n"}, "theirs")
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.Master}))
	mergeWriteCommit(t, w, map[string]string{"file.txt": "a\nOURS\nc\n"}, "ours")
	featureRef, err := r.Reference(plumbing.NewBranchReferenceName("feature"), true)
	require.NoError(t, err)
	err = w.Merge(featureRef.Hash(), &MergeOptions{})
	require.ErrorIs(t, err, ErrMergeConflicts)

	headBefore, err := r.Head()
	require.NoError(t, err)
	_, err = w.Commit("merge", &CommitOptions{Author: mergeTestSignature(), All: true})
	require.NoError(t, err)
	headAfter, err := r.Head()
	require.NoError(t, err)
	commit, err := r.CommitObject(headAfter.Hash())
	require.NoError(t, err)
	assert.Equal(t, []plumbing.Hash{headBefore.Hash(), featureRef.Hash()}, commit.ParentHashes)
}
