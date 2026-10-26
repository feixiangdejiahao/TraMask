package git

import (
	"testing"

	"github.com/go-git/go-billy/v6/util"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/go-git/go-git/v6/plumbing"
	"github.com/go-git/go-git/v6/plumbing/format/index"
)

func TestMergeAddResolveToOurs(t *testing.T) {
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

	// write ours content (same as stage 2)
	require.NoError(t, util.WriteFile(w.Filesystem, "file.txt", []byte("a\nOURS\nc\n"), 0o644))
	_, err = w.Add("file.txt")
	require.NoError(t, err)

	idx, err := r.Storer.Index()
	require.NoError(t, err)
	count := 0
	for _, e := range idx.Entries {
		if e.Name == "file.txt" {
			count++
			assert.Equal(t, index.Stage(0), e.Stage)
		}
	}
	assert.Equal(t, 1, count)
}
