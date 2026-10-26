package git

import (
	"testing"

	"github.com/go-git/go-billy/v6/util"
	"github.com/stretchr/testify/require"

	"github.com/go-git/go-git/v6/plumbing"
)

func TestMergeStagedChangesDirty(t *testing.T) {
	_, w := mergeTestRepo(t, map[string]string{"a.txt": "a\n"})
	require.NoError(t, util.WriteFile(w.Filesystem, "staged.txt", []byte("staged\n"), 0o644))
	_, err := w.Add("staged.txt")
	require.NoError(t, err)
	err = w.Merge(plumbing.NewHash("1111111111111111111111111111111111111111"), &MergeOptions{})
	require.ErrorIs(t, err, ErrUncommittedChanges)
}
