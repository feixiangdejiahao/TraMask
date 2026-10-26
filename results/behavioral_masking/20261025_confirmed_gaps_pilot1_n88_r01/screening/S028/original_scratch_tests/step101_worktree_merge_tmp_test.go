package git

import (
	"testing"
	"time"

	"github.com/go-git/go-billy/v6/util"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/go-git/go-git/v6/plumbing"
	"github.com/go-git/go-git/v6/plumbing/object"
)

func TestMergeOSFS(t *testing.T) {
	dir := t.TempDir()
	r, err := PlainInit(dir, false)
	require.NoError(t, err)
	w, err := r.Worktree()
	require.NoError(t, err)
	sig := &object.Signature{Name: "t", Email: "t@t", When: time.Now()}
	require.NoError(t, util.WriteFile(w.Filesystem, "f.txt", []byte("a\nb\nc\n"), 0o644))
	_, err = w.Add("f.txt")
	require.NoError(t, err)
	_, err = w.Commit("init", &CommitOptions{Author: sig})
	require.NoError(t, err)
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.NewBranchReferenceName("feat"), Create: true}))
	require.NoError(t, util.WriteFile(w.Filesystem, "f.txt", []byte("a\nTHEIRS\nc\n"), 0o644))
	_, err = w.Add("f.txt")
	require.NoError(t, err)
	_, err = w.Commit("theirs", &CommitOptions{Author: sig})
	require.NoError(t, err)
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.Master}))
	require.NoError(t, util.WriteFile(w.Filesystem, "f.txt", []byte("a\nOURS\nc\n"), 0o644))
	_, err = w.Add("f.txt")
	require.NoError(t, err)
	_, err = w.Commit("ours", &CommitOptions{Author: sig})
	require.NoError(t, err)
	ref, err := r.Reference(plumbing.NewBranchReferenceName("feat"), true)
	require.NoError(t, err)
	err = w.Merge(ref.Hash(), &MergeOptions{})
	require.ErrorIs(t, err, ErrMergeConflicts)
	content, err := util.ReadFile(w.Filesystem, ".git/MERGE_HEAD")
	require.NoError(t, err)
	assert.Equal(t, ref.Hash().String()+"\n", string(content))
	content, err = util.ReadFile(w.Filesystem, "f.txt")
	require.NoError(t, err)
	assert.Contains(t, string(content), "<<<<<<< HEAD")
}
