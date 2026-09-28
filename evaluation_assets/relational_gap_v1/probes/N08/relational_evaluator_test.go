// Manual retrospective evaluator control; excluded from generator inputs.
package pebble

import (
	"testing"
	"time"

	"github.com/cockroachdb/pebble/vfs"
)

func TestRelationalEvaluatorDurability(t *testing.T) {
	db, err := Open("", &Options{FS: vfs.NewMem()})
	if err != nil { t.Fatal(err) }
	defer db.Close()
	batch := db.NewBatch()
	defer batch.Close()
	if err := batch.Set([]byte("key"), []byte("value"), nil); err != nil { t.Fatal(err) }
	if err := db.Apply(batch, Sync); err != nil { t.Fatal(err) }
	seq := batch.SeqNum()
	t.Run("control_written_sequence", func(t *testing.T) {
		select {
		case err := <-db.DurabilityNotify(seq):
			if err != nil { t.Fatal(err) }
		case <-time.After(time.Second):
			t.Fatal("completed sync commit did not notify")
		}
	})
	t.Run("control_far_future", func(t *testing.T) {
		select {
		case err := <-db.DurabilityNotify(seq + 100000):
			t.Fatalf("future sequence notified: %v", err)
		default:
		}
	})
	t.Run("gap_exclusive_boundary", func(t *testing.T) {
		select {
		case err := <-db.DurabilityNotify(seq + 1):
			t.Fatalf("unwritten next sequence notified: seq=%d, error=%v", seq + 1, err)
		default:
		}
	})
}
