package kcp

import (
 "io"
 "net"
 "testing"
 "time"
)

func newMuxPair(t *testing.T, c1, c2 net.Conn, cfg1, cfg2 *MuxConfig) (*MuxSession, *MuxSession) {
	t.Helper()
	s1, err := NewMuxSession(c1, cfg1)
	if err != nil {
		t.Fatal(err)
	}
	s2, err := NewMuxSession(c2, cfg2)
	if err != nil {
		t.Fatal(err)
	}
	return s1, s2
}

func acceptWithTimeout(t *testing.T, s *MuxSession) *MuxStream {
	t.Helper()
	type result struct {
		st  *MuxStream
		err error
	}
	ch := make(chan result, 1)
	go func() {
		st, err := s.AcceptStream()
		ch <- result{st, err}
	}()
	select {
	case r := <-ch:
		if r.err != nil {
			t.Fatal(r.err)
		}
		return r.st
	case <-time.After(5 * time.Second):
		t.Fatal("AcceptStream timeout")
		return nil
	}
}

func TestMuxSessionCloseUnblocks(t *testing.T) {
	c1, c2 := net.Pipe()
	defer c1.Close()
	defer c2.Close()

	cfg1 := DefaultMuxConfig()
	cfg1.Side = MuxSideClient
	cfg1.MaxFrameSize = 8192
	cfg1.SendWindow = 512
	cfg1.RecvWindow = 512
	cfg2 := cfg1
	cfg2.Side = MuxSideServer

	s1, s2 := newMuxPair(t, c1, c2, &cfg1, &cfg2)

	// Stream for a blocked reader (no data is ever written to it).
	st1, err := s1.OpenStream(MuxPriorityNormal)
	if err != nil {
		t.Fatal(err)
	}
	_ = st1
	st2 := acceptWithTimeout(t, s2)

	// Stream for a blocked writer.
	w1, err := s1.OpenStream(MuxPriorityNormal)
	if err != nil {
		t.Fatal(err)
	}
	w2 := acceptWithTimeout(t, s2)
	_ = w2

	readDone := make(chan error, 1)
	go func() {
		buf := make([]byte, 16)
		_, err := st2.Read(buf)
		readDone <- err
	}()
	writeDone := make(chan error, 1)
	go func() {
		_, err := w1.Write(make([]byte, 1<<20))
		writeDone <- err
	}()

	time.Sleep(100 * time.Millisecond)
	if err := s2.Close(); err != nil {
		t.Fatal(err)
	}

	select {
	case err := <-readDone:
		if err != io.ErrClosedPipe {
			t.Fatalf("read err = %v, want io.ErrClosedPipe", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("read not unblocked")
	}
	select {
	case err := <-writeDone:
		if err != io.ErrClosedPipe {
			t.Fatalf("write err = %v, want io.ErrClosedPipe", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("write not unblocked")
	}
	if _, err := s1.OpenStream(MuxPriorityNormal); err != io.ErrClosedPipe {
		t.Fatalf("open after close err = %v, want io.ErrClosedPipe", err)
	}
	if _, err := s2.AcceptStream(); err != io.ErrClosedPipe {
		t.Fatalf("accept after close err = %v, want io.ErrClosedPipe", err)
	}
}

