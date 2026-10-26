package git

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/go-git/go-git/v6/plumbing"
)

func TestMergeUsesConfigAuthor(t *testing.T) {
	r, w := mergeTestRepo(t, map[string]string{"base.txt": "base\n"})
	cfg, err := r.Config()
	require.NoError(t, err)
	cfg.User.Name = "Config User"
	cfg.User.Email = "cfg@example.com"
	require.NoError(t, r.SetConfig(cfg))
	require.NoError(t, w.Filesystem.MkdirAll(".git", 0o755))
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.NewBranchReferenceName("feature"), Create: true}))
	mergeWriteCommit(t, w, map[string]string{"theirs.txt": "theirs\n"}, "theirs")
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.Master}))
	mergeWriteCommit(t, w, map[string]string{"ours.txt": "ours\n"}, "ours")
	featureRef, err := r.Reference(plumbing.NewBranchReferenceName("feature"), true)
	require.NoError(t, err)
	err = w.Merge(featureRef.Hash(), &MergeOptions{})
	require.NoError(t, err)
	head, err := r.Head()
	require.NoError(t, err)
	commit, err := r.CommitObject(head.Hash())
	require.NoError(t, err)
	assert.Equal(t, "Config User", commit.Author.Name)
	assert.Equal(t, "cfg@example.com", commit.Author.Email)
}
