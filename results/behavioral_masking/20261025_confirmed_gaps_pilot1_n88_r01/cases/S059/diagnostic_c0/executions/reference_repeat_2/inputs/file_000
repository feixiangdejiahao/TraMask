package pebble

import (
 "testing"
 "time"
 "github.com/cockroachdb/errors"
 "github.com/cockroachdb/pebble/vfs"
 "github.com/stretchr/testify/require"
)

func openDurabilityTestDB(t *testing.T, el *EventListener) *DB {
	t.Helper()
	opts := &Options{FS: vfs.NewMem()}
	if el != nil {
		opts.EventListener = el
	}
	d, err := Open("", opts)
	require.NoError(t, err)
	t.Cleanup(func() {
		if d.closed.Load() == nil {
			require.NoError(t, d.Close())
		}
	})
	return d
}

func TestWaitForDurabilityWaits(t *testing.T) {
	d := openDurabilityTestDB(t, nil)
	done := make(chan error, 1)
	go func() {
		done <- d.WaitForDurability(100000)
	}()
	// Give the waiter a chance to block.
	time.Sleep(50 * time.Millisecond)
	st := d.DurabilityStats()
	require.Equal(t, int64(1), st.PendingWaiters)

	// A sync commit does not cover seqnum 100000, so the waiter must still be
	// blocked.
	require.NoError(t, d.Set([]byte("a"), []byte("1"), Sync))
	pilot1High, pilot1Err := d.DurableState()
	t.Logf("PILOT1_C0_DURABLE_STATE highest=%d next_sequence=%d error=%v", pilot1High, d.mu.versions.logSeqNum.Load(), pilot1Err)
	select {
	case <-done:
		t.Fatal("waiter unblocked before sequence number was durable")
	case <-time.After(50 * time.Millisecond):
	}
	// Close unblocks the waiter with an error.
	require.NoError(t, d.Close())
	select {
	case err := <-done:
		require.Error(t, err)
		require.True(t, errors.Is(err, ErrClosed))
	case <-time.After(5 * time.Second):
		t.Fatal("waiter not unblocked on close")
	}
}
