package git

import (
	"io"
	"strings"
	"testing"
	"time"

	"github.com/go-git/go-billy/v6/memfs"
	"github.com/go-git/go-billy/v6/util"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/go-git/go-git/v6/plumbing"
	"github.com/go-git/go-git/v6/plumbing/format/index"
	"github.com/go-git/go-git/v6/plumbing/object"
	"github.com/go-git/go-git/v6/storage/memory"
)

func mergeTestRepo(t *testing.T, files map[string]string) (*Repository, *Worktree) {
	t.Helper()
	r, err := Init(memory.NewStorage(), WithWorkTree(memfs.New()))
	require.NoError(t, err)
	w, err := r.Worktree()
	require.NoError(t, err)
	for name, content := range files {
		require.NoError(t, util.WriteFile(w.Filesystem, name, []byte(content), 0o644))
		_, err := w.Add(name)
		require.NoError(t, err)
	}
	_, err = w.Commit("initial", &CommitOptions{Author: defaultSignature()})
	require.NoError(t, err)
	return r, w
}

func mergeTestSignature() *object.Signature {
	return &object.Signature{Name: "test", Email: "test@test", When: time.Now()}
}

func mergeWriteCommit(t *testing.T, w *Worktree, files map[string]string, msg string) plumbing.Hash {
	t.Helper()
	for name, content := range files {
		require.NoError(t, util.WriteFile(w.Filesystem, name, []byte(content), 0o644))
		_, err := w.Add(name)
		require.NoError(t, err)
	}
	h, err := w.Commit(msg, &CommitOptions{Author: mergeTestSignature()})
	require.NoError(t, err)
	return h
}

func TestMergeFastForward(t *testing.T) {
	r, w := mergeTestRepo(t, map[string]string{"a.txt": "a\n"})
	// create a side commit on a branch
	require.NoError(t, w.Filesystem.MkdirAll(".git", 0o755))
	branch := plumbing.NewBranchReferenceName("feature")
	err := w.Checkout(&CheckoutOptions{Branch: branch, Create: true})
	require.NoError(t, err)
	side := mergeWriteCommit(t, w, map[string]string{"b.txt": "b\n"}, "side")
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.Master}))

	err = w.Merge(side, &MergeOptions{})
	require.NoError(t, err)
	head, err := r.Head()
	require.NoError(t, err)
	require.Equal(t, side, head.Hash())
	content, err := util.ReadFile(w.Filesystem, "b.txt")
	require.NoError(t, err)
	assert.Equal(t, "b\n", string(content))
}

func TestMergeThreeWayNoConflict(t *testing.T) {
	r, w := mergeTestRepo(t, map[string]string{"base.txt": "base\n"})
	headHash, err := r.Head()
	require.NoError(t, err)

	require.NoError(t, w.Filesystem.MkdirAll(".git", 0o755))
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.NewBranchReferenceName("feature"), Create: true}))
	mergeWriteCommit(t, w, map[string]string{"theirs.txt": "theirs\n"}, "theirs")
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.Master}))
	mergeWriteCommit(t, w, map[string]string{"ours.txt": "ours\n"}, "ours")

	err = w.Merge(plumbing.NewHash(""), &MergeOptions{})
	require.Error(t, err) // invalid hash

	featureRef, err := r.Reference(plumbing.NewBranchReferenceName("feature"), true)
	require.NoError(t, err)
	err = w.Merge(featureRef.Hash(), &MergeOptions{})
	require.NoError(t, err)

	head, err := r.Head()
	require.NoError(t, err)
	require.NotEqual(t, headHash, head.Hash())
	commit, err := r.CommitObject(head.Hash())
	require.NoError(t, err)
	assert.Equal(t, 2, len(commit.ParentHashes))
	assert.Equal(t, featureRef.Hash(), commit.ParentHashes[1])

	ours, err := util.ReadFile(w.Filesystem, "ours.txt")
	require.NoError(t, err)
	assert.Equal(t, "ours\n", string(ours))
	theirs, err := util.ReadFile(w.Filesystem, "theirs.txt")
	require.NoError(t, err)
	assert.Equal(t, "theirs\n", string(theirs))
}

func TestMergeContentConflict(t *testing.T) {
	r, w := mergeTestRepo(t, map[string]string{"file.txt": "line1\nline2\nline3\n"})
	require.NoError(t, w.Filesystem.MkdirAll(".git", 0o755))
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.NewBranchReferenceName("feature"), Create: true}))
	mergeWriteCommit(t, w, map[string]string{"file.txt": "line1\nTHEIRS\nline3\n"}, "theirs")
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.Master}))
	mergeWriteCommit(t, w, map[string]string{"file.txt": "line1\nOURS\nline3\n"}, "ours")

	featureRef, err := r.Reference(plumbing.NewBranchReferenceName("feature"), true)
	require.NoError(t, err)
	err = w.Merge(featureRef.Hash(), &MergeOptions{})
	require.ErrorIs(t, err, ErrMergeConflicts)

	// MERGE_HEAD written on worktree fs
	mergeHead, err := util.ReadFile(w.Filesystem, ".git/MERGE_HEAD")
	require.NoError(t, err)
	assert.Equal(t, featureRef.Hash().String()+"\n", string(mergeHead))

	// conflict markers written
	content, err := util.ReadFile(w.Filesystem, "file.txt")
	require.NoError(t, err)
	assert.Contains(t, string(content), "<<<<<<< HEAD")
	assert.Contains(t, string(content), "OURS")
	assert.Contains(t, string(content), "=======")
	assert.Contains(t, string(content), "THEIRS")
	assert.Contains(t, string(content), ">>>>>>>")

	// index has stages 1,2,3
	idx, err := r.Storer.Index()
	require.NoError(t, err)
	var stages []index.Stage
	for _, e := range idx.Entries {
		if e.Name == "file.txt" {
			stages = append(stages, e.Stage)
		}
	}
	assert.ElementsMatch(t, []index.Stage{1, 2, 3}, stages)

	// Commit concludes the merge and uses MERGE_HEAD as second parent
	headBefore, err := r.Head()
	require.NoError(t, err)
	_, err = w.Commit("merge", &CommitOptions{Author: mergeTestSignature()})
	require.NoError(t, err)
	// The new head commit's parent should include old head and target.
	headAfter, err := r.Head()
	require.NoError(t, err)
	mergedCommit, err := r.CommitObject(headAfter.Hash())
	require.NoError(t, err)
	assert.Equal(t, []plumbing.Hash{headBefore.Hash(), featureRef.Hash()}, mergedCommit.ParentHashes)

	// MERGE_HEAD removed
	_, err = w.Filesystem.Stat(".git/MERGE_HEAD")
	require.Error(t, err)
}

func TestMergeNonConflictingFilesWithConflict(t *testing.T) {
	r, w := mergeTestRepo(t, map[string]string{
		"conflict.txt": "a\nb\nc\n",
		"same.txt":     "x\n",
	})
	require.NoError(t, w.Filesystem.MkdirAll(".git", 0o755))
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.NewBranchReferenceName("feature"), Create: true}))
	mergeWriteCommit(t, w, map[string]string{
		"conflict.txt": "a\nTHEIRS\nc\n",
		"theirs.txt":   "theirs\n",
	}, "theirs")
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.Master}))
	mergeWriteCommit(t, w, map[string]string{
		"conflict.txt": "a\nOURS\nc\n",
		"ours.txt":     "ours\n",
	}, "ours")

	featureRef, err := r.Reference(plumbing.NewBranchReferenceName("feature"), true)
	require.NoError(t, err)
	err = w.Merge(featureRef.Hash(), &MergeOptions{})
	require.ErrorIs(t, err, ErrMergeConflicts)

	// Non-conflicting files are merged into worktree
	theirs, err := util.ReadFile(w.Filesystem, "theirs.txt")
	require.NoError(t, err)
	assert.Equal(t, "theirs\n", string(theirs))
	ours, err := util.ReadFile(w.Filesystem, "ours.txt")
	require.NoError(t, err)
	assert.Equal(t, "ours\n", string(ours))

	// and staged as single stage-0 entries
	idx, err := r.Storer.Index()
	require.NoError(t, err)
	for _, name := range []string{"theirs.txt", "ours.txt"} {
		count := 0
		for _, e := range idx.Entries {
			if e.Name == name {
				count++
				assert.Equal(t, index.Stage(0), e.Stage)
			}
		}
		assert.Equal(t, 1, count)
	}
}

func TestMergeNonOverlappingChanges(t *testing.T) {
	r, w := mergeTestRepo(t, map[string]string{"file.txt": "line1\nline2\nline3\n"})
	require.NoError(t, w.Filesystem.MkdirAll(".git", 0o755))
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.NewBranchReferenceName("feature"), Create: true}))
	mergeWriteCommit(t, w, map[string]string{"file.txt": "line1\nline2\nTHEIRS\n"}, "theirs")
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.Master}))
	mergeWriteCommit(t, w, map[string]string{"file.txt": "OURS\nline2\nline3\n"}, "ours")

	featureRef, err := r.Reference(plumbing.NewBranchReferenceName("feature"), true)
	require.NoError(t, err)
	err = w.Merge(featureRef.Hash(), &MergeOptions{})
	require.NoError(t, err)
	content, err := util.ReadFile(w.Filesystem, "file.txt")
	require.NoError(t, err)
	assert.Equal(t, "OURS\nline2\nTHEIRS\n", string(content))
}

func TestMergeDeleteModifyConflict(t *testing.T) {
	r, w := mergeTestRepo(t, map[string]string{"file.txt": "base\n"})
	require.NoError(t, w.Filesystem.MkdirAll(".git", 0o755))
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.NewBranchReferenceName("feature"), Create: true}))
	require.NoError(t, w.Filesystem.Remove("file.txt"))
	_, err := w.Remove("file.txt")
	require.NoError(t, err)
	_, err = w.Commit("delete", &CommitOptions{Author: mergeTestSignature()})
	require.NoError(t, err)
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.Master}))
	mergeWriteCommit(t, w, map[string]string{"file.txt": "modified\n"}, "modify")

	featureRef, err := r.Reference(plumbing.NewBranchReferenceName("feature"), true)
	require.NoError(t, err)
	err = w.Merge(featureRef.Hash(), &MergeOptions{})
	require.ErrorIs(t, err, ErrMergeConflicts)

	idx, err := r.Storer.Index()
	require.NoError(t, err)
	var stages []index.Stage
	for _, e := range idx.Entries {
		if e.Name == "file.txt" {
			stages = append(stages, e.Stage)
		}
	}
	// base + ours, no theirs
	assert.ElementsMatch(t, []index.Stage{1, 2}, stages)
}

func TestMergeAddAddConflict(t *testing.T) {
	r, w := mergeTestRepo(t, map[string]string{"base.txt": "base\n"})
	require.NoError(t, w.Filesystem.MkdirAll(".git", 0o755))
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.NewBranchReferenceName("feature"), Create: true}))
	mergeWriteCommit(t, w, map[string]string{"new.txt": "theirs\n"}, "theirs")
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.Master}))
	mergeWriteCommit(t, w, map[string]string{"new.txt": "ours\n"}, "ours")

	featureRef, err := r.Reference(plumbing.NewBranchReferenceName("feature"), true)
	require.NoError(t, err)
	err = w.Merge(featureRef.Hash(), &MergeOptions{})
	require.ErrorIs(t, err, ErrMergeConflicts)

	idx, err := r.Storer.Index()
	require.NoError(t, err)
	var stages []index.Stage
	for _, e := range idx.Entries {
		if e.Name == "new.txt" {
			stages = append(stages, e.Stage)
		}
	}
	assert.ElementsMatch(t, []index.Stage{2, 3}, stages)
}

func TestMergeFileDirConflict(t *testing.T) {
	r, w := mergeTestRepo(t, map[string]string{"base.txt": "base\n"})
	require.NoError(t, w.Filesystem.MkdirAll(".git", 0o755))
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.NewBranchReferenceName("feature"), Create: true}))
	require.NoError(t, w.Filesystem.MkdirAll("dir", 0o755))
	require.NoError(t, util.WriteFile(w.Filesystem, "dir/inner.txt", []byte("theirs\n"), 0o644))
	_, err := w.Add("dir/inner.txt")
	require.NoError(t, err)
	_, err = w.Commit("theirs dir", &CommitOptions{Author: mergeTestSignature()})
	require.NoError(t, err)
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.Master}))
	mergeWriteCommit(t, w, map[string]string{"dir": "ours file\n"}, "ours file")

	featureRef, err := r.Reference(plumbing.NewBranchReferenceName("feature"), true)
	require.NoError(t, err)
	err = w.Merge(featureRef.Hash(), &MergeOptions{})
	require.ErrorIs(t, err, ErrMergeConflicts)
}

func TestMergeDirtyWorktree(t *testing.T) {
	_, w := mergeTestRepo(t, map[string]string{"a.txt": "a\n"})
	require.NoError(t, util.WriteFile(w.Filesystem, "dirty.txt", []byte("dirty\n"), 0o644))
	err := w.Merge(plumbing.NewHash("1111111111111111111111111111111111111111"), &MergeOptions{})
	require.ErrorIs(t, err, ErrUncommittedChanges)
}

func TestMergeWithoutUserConfig(t *testing.T) {
	r, w := mergeTestRepo(t, map[string]string{"base.txt": "base\n"})
	// Remove user config so Commit cannot find an author.
	cfg, err := r.Config()
	require.NoError(t, err)
	cfg.User.Name = ""
	cfg.User.Email = ""
	cfg.Author.Name = ""
	cfg.Author.Email = ""
	cfg.Committer.Name = ""
	cfg.Committer.Email = ""
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
}

func TestMergeAddClearsConflictStages(t *testing.T) {
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

	// resolve by writing a file and re-staging
	require.NoError(t, util.WriteFile(w.Filesystem, "file.txt", []byte("a\nRESOLVED\nc\n"), 0o644))
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

func TestMergeRepeatedLines(t *testing.T) {
	r, w := mergeTestRepo(t, map[string]string{"file.txt": "a\nb\na\nb\n"})
	require.NoError(t, w.Filesystem.MkdirAll(".git", 0o755))
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.NewBranchReferenceName("feature"), Create: true}))
	mergeWriteCommit(t, w, map[string]string{"file.txt": "a\nx\na\nb\n"}, "theirs")
	require.NoError(t, w.Checkout(&CheckoutOptions{Branch: plumbing.Master}))
	mergeWriteCommit(t, w, map[string]string{"file.txt": "a\nb\na\ny\n"}, "ours")

	featureRef, err := r.Reference(plumbing.NewBranchReferenceName("feature"), true)
	require.NoError(t, err)
	err = w.Merge(featureRef.Hash(), &MergeOptions{})
	require.NoError(t, err)
	content, err := util.ReadFile(w.Filesystem, "file.txt")
	require.NoError(t, err)
	assert.Equal(t, "a\nx\na\ny\n", string(content))
}

var _ = io.ReadAll
var _ = strings.TrimSpace
