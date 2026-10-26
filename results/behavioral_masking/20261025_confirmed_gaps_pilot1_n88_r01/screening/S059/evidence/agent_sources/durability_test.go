// Copyright 2025 The LevelDB-Go and Pebble Authors. All rights reserved. Use
// of this source code is governed by a BSD-style license that can be found in
// the LICENSE file.

package pebble

import (
	"bytes"
	"context"
	"fmt"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/cockroachdb/errors"
	"github.com/cockroachdb/pebble/internal/base"
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

func TestBatchDurableEvent(t *testing.T) {
	infos := make(chan BatchDurableInfo, 10)
	d := openDurabilityTestDB(t, &EventListener{
		BatchDurable: func(info BatchDurableInfo) { infos <- info },
	})

	// Non-sync commit must not trigger BatchDurable.
	require.NoError(t, d.Set([]byte("nosync"), []byte("1"), NoSync))

	b := d.NewBatch()
	require.NoError(t, b.Set([]byte("a"), []byte("1"), nil))
	require.NoError(t, b.Set([]byte("b"), []byte("2"), nil))
	require.NoError(t, d.Apply(b, &WriteOptions{Sync: true, CommitCorrelationID: 42}))
	require.NoError(t, b.Close())

	select {
	case info := <-infos:
		require.Greater(t, info.JobID, 0)
		require.Equal(t, uint64(42), info.CorrelationID)
		require.NoError(t, info.Err)
		require.Greater(t, info.BatchSize, 0)
		require.Equal(t, uint32(2), info.KeyCount)
		require.Greater(t, info.ApplyDuration, time.Duration(0))
		require.Greater(t, info.SyncDuration, time.Duration(0))
		// WaitForJobDurability should succeed for the delivered job ID.
		require.NoError(t, d.WaitForJobDurability(info.JobID))
	case <-time.After(5 * time.Second):
		t.Fatal("timed out waiting for BatchDurable event")
	}

	// Exactly one event for one sync commit.
	select {
	case <-infos:
		t.Fatal("unexpected extra BatchDurable event")
	case <-time.After(50 * time.Millisecond):
	}
}

func TestBatchDurableApplyNoSyncWait(t *testing.T) {
	infos := make(chan BatchDurableInfo, 1)
	d := openDurabilityTestDB(t, &EventListener{
		BatchDurable: func(info BatchDurableInfo) { infos <- info },
	})
	b := d.NewBatch()
	require.NoError(t, b.Set([]byte("a"), []byte("1"), nil))
	require.NoError(t, d.ApplyNoSyncWait(b, Sync))
	// The event should only fire after SyncWait.
	select {
	case <-infos:
		t.Fatal("BatchDurable fired before SyncWait")
	case <-time.After(50 * time.Millisecond):
	}
	require.NoError(t, b.SyncWait())
	select {
	case info := <-infos:
		require.NoError(t, info.Err)
	case <-time.After(5 * time.Second):
		t.Fatal("timed out waiting for BatchDurable event")
	}
	require.NoError(t, b.Close())
}

func TestWaitForDurability(t *testing.T) {
	d := openDurabilityTestDB(t, nil)
	require.NoError(t, d.WaitForDurability(0))
	require.NoError(t, d.WaitForDurabilityBatch(nil))
	require.NoError(t, d.WaitForDurabilityBatch([]base.SeqNum{}))

	b := d.NewBatch()
	require.NoError(t, b.Set([]byte("a"), []byte("1"), nil))
	require.NoError(t, b.Set([]byte("b"), []byte("2"), nil))
	require.NoError(t, d.Apply(b, Sync))
	seqNum := b.SeqNum()
	require.NoError(t, b.Close())

	require.NoError(t, d.WaitForDurability(seqNum))
	require.NoError(t, d.WaitForDurability(seqNum+1))
	require.NoError(t, d.WaitForDurabilityBatch([]base.SeqNum{seqNum, seqNum + 1}))

	high, err := d.DurableState()
	require.NoError(t, err)
	require.GreaterOrEqual(t, high, seqNum+2)
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

func TestWaitForJobDurabilityErrors(t *testing.T) {
	d := openDurabilityTestDB(t, nil)
	err := d.WaitForJobDurability(0)
	require.Error(t, err)
	require.Contains(t, err.Error(), "unknown")

	err = d.WaitForJobDurability(1)
	require.Error(t, err)
	require.Contains(t, err.Error(), "unknown")

	err = d.WaitForJobDurability(123456789)
	require.Error(t, err)
	require.Contains(t, err.Error(), "unknown")
}

func TestWaitForJobDurabilityExpired(t *testing.T) {
	d := openDurabilityTestDB(t, nil)
	// Generate enough sync commits to overflow the job history retention window.
	for i := 0; i < durabilityJobRetention+10; i++ {
		require.NoError(t, d.Set([]byte{byte(i)}, []byte("1"), Sync))
	}
	err := d.WaitForJobDurability(1)
	require.Error(t, err)
	require.Contains(t, err.Error(), "expired")
}

func TestWaitForJobDurability(t *testing.T) {
	var jobID atomic.Int64
	d := openDurabilityTestDB(t, &EventListener{
		BatchDurable: func(info BatchDurableInfo) { jobID.Store(int64(info.JobID)) },
	})
	b := d.NewBatch()
	require.NoError(t, b.Set([]byte("a"), []byte("1"), nil))
	require.NoError(t, d.Apply(b, Sync))
	require.NoError(t, b.Close())
	require.Greater(t, jobID.Load(), int64(0))
	require.NoError(t, d.WaitForJobDurability(int(jobID.Load())))
}

func TestDurabilityNotify(t *testing.T) {
	d := openDurabilityTestDB(t, nil)

	// Already-durable seqnum returns nil immediately.
	select {
	case err := <-d.DurabilityNotify(0):
		require.NoError(t, err)
	case <-time.After(5 * time.Second):
		t.Fatal("timed out")
	}

	// Future seqnum delivers nil once covered by a sync commit.
	ch := d.DurabilityNotify(100)
	b := d.NewBatch()
	require.NoError(t, b.Set([]byte("a"), []byte("1"), nil))
	// Set a high seqnum artificially? Instead use a real batch and wait for its
	// seqnum range.
	require.NoError(t, d.Apply(b, Sync))
	seqNum := b.SeqNum()
	require.NoError(t, b.Close())
	ch2 := d.DurabilityNotify(seqNum)
	select {
	case err := <-ch2:
		require.NoError(t, err)
	case <-time.After(5 * time.Second):
		t.Fatal("timed out waiting for durability notify")
	}
	_ = ch // ch for seqnum 100 will only fire on close
}

func TestDurabilityNotifyBound(t *testing.T) {
	d := openDurabilityTestDB(t, nil)
	chans := make([]<-chan error, 0, maxDurabilityNotifiers+1)
	for i := 0; i < maxDurabilityNotifiers; i++ {
		chans = append(chans, d.DurabilityNotify(1<<30))
	}
	// The next subscription exceeds the bound and gets an immediate error.
	ch := d.DurabilityNotify(1 << 30)
	select {
	case err := <-ch:
		require.Error(t, err)
	case <-time.After(5 * time.Second):
		t.Fatal("expected immediate non-nil error for excess subscriber")
	}
	_ = chans
}

func TestDurabilityStats(t *testing.T) {
	d := openDurabilityTestDB(t, nil)
	st := d.DurabilityStats()
	require.Equal(t, base.SeqNum(0), st.HighestDurableSeqNum)
	require.NoError(t, st.FirstErr)
	require.Equal(t, int64(0), st.PendingWaiters)
	require.Equal(t, uint64(0), st.TotalDurableCommits)
	require.Equal(t, uint64(0), st.TotalFailedCommits)

	require.NoError(t, d.Set([]byte("a"), []byte("1"), Sync))
	st = d.DurabilityStats()
	require.Equal(t, uint64(1), st.TotalDurableCommits)
	require.Equal(t, uint64(0), st.TotalFailedCommits)
	require.Greater(t, st.HighestDurableSeqNum, base.SeqNum(0))
	require.Greater(t, st.CumulativeSyncDuration, time.Duration(0))
}

func TestDisableWALWaitAPIs(t *testing.T) {
	opts := &Options{FS: vfs.NewMem(), DisableWAL: true}
	d, err := Open("", opts)
	require.NoError(t, err)
	defer func() { require.NoError(t, d.Close()) }()

	require.NoError(t, d.WaitForDurability(12345))
	require.NoError(t, d.WaitForDurabilityBatch([]base.SeqNum{1, 2, 3}))
	require.NoError(t, d.WaitForJobDurability(12345))
	select {
	case err := <-d.DurabilityNotify(12345):
		require.NoError(t, err)
	case <-time.After(5 * time.Second):
		t.Fatal("timed out")
	}
}

func TestDurabilityMetrics(t *testing.T) {
	d := openDurabilityTestDB(t, &EventListener{
		BatchDurable: func(info BatchDurableInfo) {},
	})
	require.NoError(t, d.Set([]byte("a"), []byte("1"), Sync))
	m := d.Metrics()
	require.Equal(t, uint64(1), m.DurableCommitCount)
	require.Greater(t, m.DurableCommitDuration, time.Duration(0))

	// Without BatchDurable configured, the metrics stay zero.
	d2 := openDurabilityTestDB(t, nil)
	require.NoError(t, d2.Set([]byte("a"), []byte("1"), Sync))
	m2 := d2.Metrics()
	require.Equal(t, uint64(0), m2.DurableCommitCount)
	require.Equal(t, time.Duration(0), m2.DurableCommitDuration)
}

func TestTeeEventListenerBatchDurable(t *testing.T) {
	var got1, got2 atomic.Int64
	l1 := EventListener{BatchDurable: func(info BatchDurableInfo) { got1.Add(1) }}
	l2 := EventListener{BatchDurable: func(info BatchDurableInfo) { got2.Add(1) }}
	tee := TeeEventListener(l1, l2)
	d := openDurabilityTestDB(t, &tee)
	require.NoError(t, d.Set([]byte("a"), []byte("1"), Sync))
	require.Eventually(t, func() bool { return got1.Load() == 1 && got2.Load() == 1 }, 5*time.Second, 10*time.Millisecond)
}

func TestDurabilityCloseUnblocksNotify(t *testing.T) {
	d := openDurabilityTestDB(t, nil)
	ch := d.DurabilityNotify(1 << 40)
	require.NoError(t, d.Close())
	select {
	case err := <-ch:
		require.Error(t, err)
		require.True(t, errors.Is(err, ErrClosed))
	case <-time.After(5 * time.Second):
		t.Fatal("notify not unblocked on close")
	}
}

func TestDurabilityContextCancellation(t *testing.T) {
	d := openDurabilityTestDB(t, nil)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- d.WaitForDurabilityContext(ctx, 1<<30) }()
	time.Sleep(50 * time.Millisecond)
	cancel()
	select {
	case err := <-done:
		require.Error(t, err)
		require.True(t, errors.Is(err, context.Canceled))
	case <-time.After(5 * time.Second):
		t.Fatal("context cancellation did not unblock waiter")
	}
	// PendingWaiters should return to zero.
	require.Eventually(t, func() bool { return d.DurabilityStats().PendingWaiters == 0 }, 5*time.Second, 10*time.Millisecond)
}

func TestBatchDurableErrMessage(t *testing.T) {
	// Sanity-check that the error messages contain the required substrings.
	require.True(t, strings.Contains(errDurabilityUnknownJob.Error(), "unknown"))
	require.True(t, strings.Contains(errDurabilityExpiredJob.Error(), "expired"))
}

func TestBatchDurableLargeBatch(t *testing.T) {
	infos := make(chan BatchDurableInfo, 1)
	opts := &Options{FS: vfs.NewMem(), MemTableSize: 1 << 16}
	opts.EventListener = &EventListener{BatchDurable: func(info BatchDurableInfo) { infos <- info }}
	d, err := Open("", opts)
	require.NoError(t, err)
	defer func() { require.NoError(t, d.Close()) }()

	b := d.NewBatch()
	val := bytes.Repeat([]byte("v"), 1024)
	for i := 0; i < 64; i++ {
		require.NoError(t, b.Set([]byte(fmt.Sprintf("key%02d", i)), val, nil))
	}
	require.NoError(t, d.Apply(b, Sync))
	require.NoError(t, b.Close())

	select {
	case info := <-infos:
		require.NoError(t, info.Err)
		require.Greater(t, info.BatchSize, 1<<16)
		require.Greater(t, info.ApplyDuration, time.Duration(0))
		require.Greater(t, info.SyncDuration, time.Duration(0))
	case <-time.After(5 * time.Second):
		t.Fatal("timed out waiting for large batch durable event")
	}
}
