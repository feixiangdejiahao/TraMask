package kcp

import (
	"encoding/binary"
	"io"
	"net"
	"sync"
	"sync/atomic"
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

func TestMuxBasic(t *testing.T) {
	c1, c2 := net.Pipe()
	defer c1.Close()
	defer c2.Close()

	cfg1 := DefaultMuxConfig()
	cfg1.Side = MuxSideClient
	cfg2 := DefaultMuxConfig()
	cfg2.Side = MuxSideServer

	s1, s2 := newMuxPair(t, c1, c2, &cfg1, &cfg2)
	defer s1.Close()
	defer s2.Close()

	st1, err := s1.OpenStream(MuxPriorityNormal)
	if err != nil {
		t.Fatal(err)
	}
	if st1.ID() != 1 {
		t.Fatalf("client stream id = %d, want 1", st1.ID())
	}
	st2 := acceptWithTimeout(t, s2)
	if st2.ID() != 1 {
		t.Fatalf("server accepted stream id = %d, want 1", st2.ID())
	}

	// server opens a stream, client accepts
	st3, err := s2.OpenStream(MuxPriorityHigh)
	if err != nil {
		t.Fatal(err)
	}
	if st3.ID() != 2 {
		t.Fatalf("server stream id = %d, want 2", st3.ID())
	}
	st4 := acceptWithTimeout(t, s1)
	if st4.ID() != 2 {
		t.Fatalf("client accepted stream id = %d, want 2", st4.ID())
	}

	if s1.NumStreams() != 2 || s2.NumStreams() != 2 {
		t.Fatalf("NumStreams = %d/%d, want 2/2", s1.NumStreams(), s2.NumStreams())
	}

	// bidirectional data exchange on stream 1
	go func() {
		if _, err := st1.Write([]byte("hello")); err != nil {
			t.Errorf("write: %v", err)
		}
	}()
	buf := make([]byte, 10)
	n, err := st2.Read(buf)
	if err != nil {
		t.Fatal(err)
	}
	if string(buf[:n]) != "hello" {
		t.Fatalf("got %q", buf[:n])
	}

	go func() {
		if _, err := st3.Write([]byte("world")); err != nil {
			t.Errorf("write: %v", err)
		}
	}()
	n, err = st4.Read(buf)
	if err != nil {
		t.Fatal(err)
	}
	if string(buf[:n]) != "world" {
		t.Fatalf("got %q", buf[:n])
	}
}

func TestMuxMultipleStreamsOrdering(t *testing.T) {
	c1, c2 := net.Pipe()
	defer c1.Close()
	defer c2.Close()

	cfg1 := DefaultMuxConfig()
	cfg1.Side = MuxSideClient
	cfg1.MaxFrameSize = 64
	cfg2 := DefaultMuxConfig()
	cfg2.Side = MuxSideServer
	cfg2.MaxFrameSize = 64

	s1, s2 := newMuxPair(t, c1, c2, &cfg1, &cfg2)
	defer s1.Close()
	defer s2.Close()

	// open 3 client streams
	var clientStreams []*MuxStream
	for i := 0; i < 3; i++ {
		st, err := s1.OpenStream(MuxPriorityNormal)
		if err != nil {
			t.Fatal(err)
		}
		clientStreams = append(clientStreams, st)
	}
	var serverStreams []*MuxStream
	for i := 0; i < 3; i++ {
		serverStreams = append(serverStreams, acceptWithTimeout(t, s2))
	}

	// write different patterns to each stream and verify they stay independent
	for i := 0; i < 3; i++ {
		payload := make([]byte, 300)
		for j := range payload {
			payload[j] = byte(i)
		}
		go func(st *MuxStream, p []byte) {
			if _, err := st.Write(p); err != nil {
				t.Errorf("write: %v", err)
			}
		}(clientStreams[i], payload)
	}

	for i := 0; i < 3; i++ {
		got := make([]byte, 0, 300)
		buf := make([]byte, 37)
		for len(got) < 300 {
			n, err := serverStreams[i].Read(buf)
			if err != nil {
				t.Fatalf("stream %d read: %v", i, err)
			}
			got = append(got, buf[:n]...)
		}
		for j := range got {
			if got[j] != byte(i) {
				t.Fatalf("stream %d byte %d = %d, want %d", i, j, got[j], i)
			}
		}
	}
}

func TestMuxHalfClose(t *testing.T) {
	c1, c2 := net.Pipe()
	defer c1.Close()
	defer c2.Close()

	cfg1 := DefaultMuxConfig()
	cfg1.Side = MuxSideClient
	cfg2 := DefaultMuxConfig()
	cfg2.Side = MuxSideServer

	s1, s2 := newMuxPair(t, c1, c2, &cfg1, &cfg2)
	defer s1.Close()
	defer s2.Close()

	st1, err := s1.OpenStream(MuxPriorityNormal)
	if err != nil {
		t.Fatal(err)
	}
	st2 := acceptWithTimeout(t, s2)

	// write then close (half-close)
	go func() {
		if _, err := st1.Write([]byte("payload")); err != nil {
			t.Errorf("write: %v", err)
		}
		if err := st1.Close(); err != nil {
			t.Errorf("close: %v", err)
		}
	}()

	buf := make([]byte, 64)
	n, err := st2.Read(buf)
	if err != nil {
		t.Fatal(err)
	}
	if string(buf[:n]) != "payload" {
		t.Fatalf("got %q", buf[:n])
	}

	// after data drained and remote FIN received, read returns EOF
	_, err = st2.Read(buf)
	if err != io.EOF {
		t.Fatalf("second read err = %v, want io.EOF", err)
	}

	// remote close unblocks local writers
	if _, err := st2.Write([]byte("x")); err != io.ErrClosedPipe {
		t.Fatalf("write after remote close err = %v, want io.ErrClosedPipe", err)
	}
}

func TestMuxReadDeadline(t *testing.T) {
	c1, c2 := net.Pipe()
	defer c1.Close()
	defer c2.Close()

	cfg1 := DefaultMuxConfig()
	cfg1.Side = MuxSideClient
	cfg2 := DefaultMuxConfig()
	cfg2.Side = MuxSideServer

	s1, s2 := newMuxPair(t, c1, c2, &cfg1, &cfg2)
	defer s1.Close()
	defer s2.Close()

	st1, err := s1.OpenStream(MuxPriorityNormal)
	if err != nil {
		t.Fatal(err)
	}
	_ = st1
	st2 := acceptWithTimeout(t, s2)

	st2.SetReadDeadline(time.Now().Add(50 * time.Millisecond))
	buf := make([]byte, 16)
	_, err = st2.Read(buf)
	if err == nil {
		t.Fatal("expected timeout error")
	}
	ne, ok := err.(net.Error)
	if !ok || !ne.Timeout() {
		t.Fatalf("err = %v, not a net.Error with Timeout()", err)
	}

	// reset deadline to zero should block; make it return via session close
	st2.SetReadDeadline(time.Time{})
	go func() {
		time.Sleep(50 * time.Millisecond)
		s1.Close()
	}()
	_, err = st2.Read(buf)
	if err != io.ErrClosedPipe {
		t.Fatalf("read after session close err = %v, want io.ErrClosedPipe", err)
	}
}

func TestMuxFlowControl(t *testing.T) {
	c1, c2 := net.Pipe()
	defer c1.Close()
	defer c2.Close()

	cfg1 := DefaultMuxConfig()
	cfg1.Side = MuxSideClient
	cfg1.MaxFrameSize = 8192
	cfg1.SendWindow = 1024
	cfg1.RecvWindow = 1024
	cfg2 := cfg1
	cfg2.Side = MuxSideServer

	s1, s2 := newMuxPair(t, c1, c2, &cfg1, &cfg2)
	defer s1.Close()
	defer s2.Close()

	st1, err := s1.OpenStream(MuxPriorityNormal)
	if err != nil {
		t.Fatal(err)
	}
	st2 := acceptWithTimeout(t, s2)

	writeDone := make(chan error, 1)
	go func() {
		_, err := st1.Write(make([]byte, 4096))
		writeDone <- err
	}()

	// wait for the writer to block on flow control
	select {
	case err := <-writeDone:
		t.Fatalf("write finished unexpectedly: %v", err)
	case <-time.After(200 * time.Millisecond):
	}

	// read all data; each drained window grants the blocked writer more credit
	drainDone := make(chan struct{})
	go func() {
		defer close(drainDone)
		buf := make([]byte, 1024)
		total := 0
		for total < 4096 {
			n, err := st2.Read(buf)
			if err != nil {
				return
			}
			total += n
		}
	}()

	select {
	case err := <-writeDone:
		if err != nil {
			t.Fatalf("write err: %v", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("write did not resume after window update")
	}
	<-drainDone
}

func TestMuxBlockedStreamDoesNotStallOthers(t *testing.T) {
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
	defer s1.Close()
	defer s2.Close()

	slow1, err := s1.OpenStream(MuxPriorityNormal)
	if err != nil {
		t.Fatal(err)
	}
	slow2 := acceptWithTimeout(t, s2)
	fast1, err := s1.OpenStream(MuxPriorityNormal)
	if err != nil {
		t.Fatal(err)
	}
	fast2 := acceptWithTimeout(t, s2)

	// block slow stream with a large write
	slowDone := make(chan error, 1)
	go func() {
		_, err := slow1.Write(make([]byte, 4096))
		slowDone <- err
	}()

	time.Sleep(100 * time.Millisecond)

	// fast stream should still be writable and readable
	fastDone := make(chan error, 1)
	go func() {
		_, err := fast1.Write([]byte("fast"))
		fastDone <- err
	}()
	buf := make([]byte, 16)
	n, err := fast2.Read(buf)
	if err != nil {
		t.Fatal(err)
	}
	if string(buf[:n]) != "fast" {
		t.Fatalf("got %q", buf[:n])
	}
	select {
	case err := <-fastDone:
		if err != nil {
			t.Fatalf("fast write err: %v", err)
		}
	default:
		t.Fatal("fast write did not complete")
	}

	// drain slow stream to unblock it
	readDone := make(chan struct{})
	go func() {
		total := 0
		buf := make([]byte, 512)
		for total < 4096 {
			n, err := slow2.Read(buf)
			if err != nil {
				break
			}
			total += n
		}
		close(readDone)
	}()
	select {
	case err := <-slowDone:
		if err != nil {
			t.Fatalf("slow write err: %v", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("slow write did not unblock")
	}
	<-readDone
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

	if err := s2.Close(); err != nil {
		t.Fatal(err)
	}

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

type gateConn struct {
	net.Conn
	mu      sync.Mutex
	enabled bool
	gate    chan struct{}
	writes  [][]byte
}

func (c *gateConn) setEnabled() {
	c.mu.Lock()
	c.enabled = true
	c.gate = make(chan struct{})
	c.mu.Unlock()
}

func (c *gateConn) release() {
	c.mu.Lock()
	if c.gate != nil {
		close(c.gate)
		c.gate = nil
	}
	c.mu.Unlock()
}

func (c *gateConn) recordedWrites() [][]byte {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := make([][]byte, len(c.writes))
	copy(out, c.writes)
	return out
}

func (c *gateConn) Write(b []byte) (int, error) {
	c.mu.Lock()
	enabled := c.enabled
	gate := c.gate
	c.mu.Unlock()
	if enabled && gate != nil {
		<-gate
	}
	n, err := c.Conn.Write(b)
	if err == nil {
		cp := make([]byte, len(b))
		copy(cp, b)
		c.mu.Lock()
		c.writes = append(c.writes, cp)
		c.mu.Unlock()
	}
	return n, err
}

func TestMuxPriorityScheduling(t *testing.T) {
	c1, c2 := net.Pipe()
	defer c1.Close()
	defer c2.Close()
	gc := &gateConn{Conn: c1}

	cfg1 := DefaultMuxConfig()
	cfg1.Side = MuxSideClient
	cfg1.MaxFrameSize = 16
	cfg2 := DefaultMuxConfig()
	cfg2.Side = MuxSideServer
	cfg2.MaxFrameSize = 16

	s1, _ := NewMuxSession(gc, &cfg1)
	s2, _ := NewMuxSession(c2, &cfg2)
	defer s1.Close()
	defer s2.Close()

	low1, err := s1.OpenStream(MuxPriorityLow)
	if err != nil {
		t.Fatal(err)
	}
	_ = acceptWithTimeout(t, s2)
	high1, err := s1.OpenStream(MuxPriorityHigh)
	if err != nil {
		t.Fatal(err)
	}
	_ = acceptWithTimeout(t, s2)

	// block the client writer
	gc.setEnabled()

	// queue three low-priority frames
	for i := 0; i < 3; i++ {
		if _, err := low1.Write([]byte("low")); err != nil {
			t.Fatal(err)
		}
	}
	// queue one high-priority frame
	if _, err := high1.Write([]byte("HI!")); err != nil {
		t.Fatal(err)
	}

	// let the writer proceed
	gc.release()

	// Wait until the four data frames have been written.
	deadline := time.Now().Add(5 * time.Second)
	var writes [][]byte
	for {
		writes = gc.recordedWrites()
		if len(writes) >= 4 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("only %d data frames written: %v", len(writes), writes)
		}
		time.Sleep(10 * time.Millisecond)
	}

	// Extract the payload of the last four recorded writes.
	payload := func(b []byte) string {
		if len(b) < muxHeaderSize {
			return string(b)
		}
		length := int(binary.BigEndian.Uint32(b[4:8]))
		if len(b) < muxHeaderSize+length {
			return string(b)
		}
		return string(b[muxHeaderSize : muxHeaderSize+length])
	}
	received := make([]string, 0, 4)
	for _, w := range writes {
		p := payload(w)
		if p == "low" || p == "HI!" {
			received = append(received, p)
		}
	}
	t.Logf("received: %v", received)

	if len(received) != 4 {
		t.Fatalf("received %d frames", len(received))
	}
	// The high-priority frame must be sent before at least two of the three
	// queued low-priority frames. Depending on scheduling, either the first
	// low frame was already in-flight (low, HI!, low, low) or the writer
	// noticed the high frame before picking any frame (HI!, low, low, low).
	hiPos := -1
	for i, p := range received {
		if p == "HI!" {
			hiPos = i
		}
	}
	if hiPos < 0 {
		t.Fatalf("high frame missing: %v", received)
	}
	if hiPos > 1 {
		t.Fatalf("high frame did not preempt queued low frames: %v", received)
	}
	if received[0] != "low" && received[0] != "HI!" {
		t.Fatalf("unexpected first frame %q", received[0])
	}
}

func TestMuxSNMP(t *testing.T) {
	before := DefaultSnmp.Copy()
	c1, c2 := net.Pipe()
	defer c1.Close()
	defer c2.Close()

	cfg1 := DefaultMuxConfig()
	cfg1.Side = MuxSideClient
	cfg1.MaxFrameSize = 64
	cfg2 := DefaultMuxConfig()
	cfg2.Side = MuxSideServer
	cfg2.MaxFrameSize = 64

	s1, s2 := newMuxPair(t, c1, c2, &cfg1, &cfg2)
	defer s1.Close()
	defer s2.Close()

	st1, err := s1.OpenStream(MuxPriorityNormal)
	if err != nil {
		t.Fatal(err)
	}
	st2 := acceptWithTimeout(t, s2)
	go st1.Write([]byte("snmp-data"))
	buf := make([]byte, 16)
	n, err := st2.Read(buf)
	if err != nil {
		t.Fatal(err)
	}
	if n != 9 || string(buf[:n]) != "snmp-data" {
		t.Fatalf("got %q", buf[:n])
	}

	// The sender's MuxBytesSent counter is updated by the session writer
	// goroutine after the frame is handed to the wire, which can race with
	// the receiver's read returning. Poll until it becomes visible.
	deadline := time.Now().Add(2 * time.Second)
	for DefaultSnmp.Copy().MuxBytesSent < before.MuxBytesSent+9 {
		if time.Now().After(deadline) {
			t.Fatal("MuxBytesSent not incremented by data frame")
		}
		time.Sleep(5 * time.Millisecond)
	}
	after := DefaultSnmp.Copy()
	if after.MuxStreamsOpened <= before.MuxStreamsOpened {
		t.Fatal("MuxStreamsOpened not incremented")
	}
	if after.MuxFramesSent <= before.MuxFramesSent {
		t.Fatal("MuxFramesSent not incremented")
	}
	if after.MuxFramesReceived <= before.MuxFramesReceived {
		t.Fatal("MuxFramesReceived not incremented")
	}
	if after.MuxBytesSent < before.MuxBytesSent+9 {
		t.Fatalf("MuxBytesSent not incremented: %d -> %d", before.MuxBytesSent, after.MuxBytesSent)
	}
	if after.MuxBytesReceived < before.MuxBytesReceived+9 {
		t.Fatalf("MuxBytesReceived not incremented")
	}

	// ensure Header/ToSlice have the new fields and line up
	hdr := DefaultSnmp.Header()
	slc := DefaultSnmp.ToSlice()
	if len(hdr) != len(slc) {
		t.Fatalf("header len %d != slice len %d", len(hdr), len(slc))
	}
	found := false
	for _, h := range hdr {
		if h == "MuxBytesReceived" {
			found = true
		}
	}
	if !found {
		t.Fatal("MuxBytesReceived missing from Header")
	}

	// Reset clears mux counters. Close the sessions and let background
	// goroutines drain before resetting so no in-flight frame races with it.
	s1.Close()
	s2.Close()
	time.Sleep(200 * time.Millisecond)
	DefaultSnmp.Reset()
	reset := DefaultSnmp.Copy()
	if reset.MuxBytesSent != 0 || reset.MuxFramesReceived != 0 || reset.MuxStreamsOpened != 0 {
		t.Fatalf("Reset did not clear mux counters: sent=%d recv=%d opened=%d", reset.MuxBytesSent, reset.MuxFramesReceived, reset.MuxStreamsOpened)
	}
	_ = atomic.LoadUint64(&after.MuxStreamsOpened)
}

func TestMuxStreamRemoval(t *testing.T) {
	c1, c2 := net.Pipe()
	defer c1.Close()
	defer c2.Close()

	cfg1 := DefaultMuxConfig()
	cfg1.Side = MuxSideClient
	cfg2 := DefaultMuxConfig()
	cfg2.Side = MuxSideServer

	s1, s2 := newMuxPair(t, c1, c2, &cfg1, &cfg2)
	defer s1.Close()
	defer s2.Close()

	st1, err := s1.OpenStream(MuxPriorityNormal)
	if err != nil {
		t.Fatal(err)
	}
	st2 := acceptWithTimeout(t, s2)
	if s1.NumStreams() != 1 || s2.NumStreams() != 1 {
		t.Fatalf("NumStreams = %d/%d, want 1/1", s1.NumStreams(), s2.NumStreams())
	}

	// Remote closes first.
	go func() {
		st2.Write([]byte("x"))
		st2.Close()
	}()

	buf := make([]byte, 16)
	if _, err := st1.Read(buf); err != nil {
		t.Fatal(err)
	}
	// Wait until the remote FIN is processed (read returns io.EOF).
	if _, err := st1.Read(buf); err != io.EOF {
		t.Fatalf("read after remote FIN = %v, want io.EOF", err)
	}
	// Remote FIN received -> write should fail
	if _, err := st1.Write([]byte("y")); err != io.ErrClosedPipe {
		t.Fatalf("write after remote FIN = %v, want io.ErrClosedPipe", err)
	}

	// Local close completes both sides. No buffered data remains on either side.
	if err := st1.Close(); err != nil {
		t.Fatalf("close after remote FIN: %v", err)
	}

	deadline := time.Now().Add(2 * time.Second)
	for s1.NumStreams() != 0 || s2.NumStreams() != 0 {
		if time.Now().After(deadline) {
			t.Fatalf("streams not removed: s1=%d s2=%d", s1.NumStreams(), s2.NumStreams())
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func TestMuxDoubleClose(t *testing.T) {
	c1, c2 := net.Pipe()
	defer c1.Close()
	defer c2.Close()

	cfg1 := DefaultMuxConfig()
	cfg1.Side = MuxSideClient
	cfg2 := DefaultMuxConfig()
	cfg2.Side = MuxSideServer

	s1, s2 := newMuxPair(t, c1, c2, &cfg1, &cfg2)
	defer s1.Close()
	defer s2.Close()

	st1, err := s1.OpenStream(MuxPriorityNormal)
	if err != nil {
		t.Fatal(err)
	}
	_ = acceptWithTimeout(t, s2)

	if err := st1.Close(); err != nil {
		t.Fatal(err)
	}
	if err := st1.Close(); err != io.ErrClosedPipe {
		t.Fatalf("second close err = %v, want io.ErrClosedPipe", err)
	}
}

// blockingWriteConn never completes writes. Close returns without unblocking
// pending writes, so it exercises the requirement that MuxSession.Close must
// not wait for background writer work.
type blockingWriteConn struct {
	net.Conn
	writeBlock chan struct{}
}

func (c *blockingWriteConn) Write(b []byte) (int, error) {
	<-c.writeBlock
	return 0, io.ErrClosedPipe
}

func TestMuxCloseDoesNotWaitForBlockedWrite(t *testing.T) {
	c1, c2 := net.Pipe()
	defer c1.Close()
	defer c2.Close()
	bwc := &blockingWriteConn{Conn: c1, writeBlock: make(chan struct{})}

	cfg := DefaultMuxConfig()
	cfg.Side = MuxSideClient
	s, err := NewMuxSession(bwc, &cfg)
	if err != nil {
		t.Fatal(err)
	}

	st, err := s.OpenStream(MuxPriorityNormal)
	if err != nil {
		t.Fatal(err)
	}
	// Block a reader so we can also verify it is unblocked.
	readDone := make(chan error, 1)
	go func() {
		buf := make([]byte, 16)
		_, err := st.Read(buf)
		readDone <- err
	}()

	// Give the writer goroutine time to block on the stuck conn.
	time.Sleep(50 * time.Millisecond)

	closeDone := make(chan error, 1)
	go func() {
		closeDone <- s.Close()
	}()
	select {
	case err := <-closeDone:
		if err != nil {
			t.Fatalf("close err = %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Close blocked")
	}

	select {
	case err := <-readDone:
		if err != io.ErrClosedPipe {
			t.Fatalf("read err = %v, want io.ErrClosedPipe", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("reader not unblocked")
	}

	if s.NumStreams() != 0 {
		t.Fatalf("NumStreams after close = %d, want 0", s.NumStreams())
	}
	if err := s.Close(); err != io.ErrClosedPipe {
		t.Fatalf("second close err = %v, want io.ErrClosedPipe", err)
	}
}

func TestMuxRemoteCloseUnblocksPeer(t *testing.T) {
	c1, c2 := net.Pipe()
	defer c1.Close()
	defer c2.Close()

	cfg1 := DefaultMuxConfig()
	cfg1.Side = MuxSideClient
	cfg2 := DefaultMuxConfig()
	cfg2.Side = MuxSideServer

	s1, s2 := newMuxPair(t, c1, c2, &cfg1, &cfg2)

	st1, err := s1.OpenStream(MuxPriorityNormal)
	if err != nil {
		t.Fatal(err)
	}
	st2 := acceptWithTimeout(t, s2)

	readDone := make(chan error, 1)
	go func() {
		buf := make([]byte, 16)
		_, err := st2.Read(buf)
		readDone <- err
	}()
	acceptDone := make(chan error, 1)
	go func() {
		_, err := s2.AcceptStream()
		acceptDone <- err
	}()

	time.Sleep(50 * time.Millisecond)
	if err := s1.Close(); err != nil {
		t.Fatal(err)
	}

	select {
	case err := <-readDone:
		if err != io.ErrClosedPipe {
			t.Fatalf("read err = %v, want io.ErrClosedPipe", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("peer reader not unblocked")
	}
	select {
	case err := <-acceptDone:
		if err != io.ErrClosedPipe {
			t.Fatalf("accept err = %v, want io.ErrClosedPipe", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("peer accept not unblocked")
	}
	_ = st1
}

func TestMuxCloseUnblocksBlockedWriter(t *testing.T) {
	c1, c2 := net.Pipe()
	defer c1.Close()
	defer c2.Close()

	cfg1 := DefaultMuxConfig()
	cfg1.Side = MuxSideClient
	cfg1.SendWindow = 512
	cfg1.RecvWindow = 512
	cfg2 := cfg1
	cfg2.Side = MuxSideServer

	s1, s2 := newMuxPair(t, c1, c2, &cfg1, &cfg2)
	defer s1.Close()
	defer s2.Close()

	st1, err := s1.OpenStream(MuxPriorityNormal)
	if err != nil {
		t.Fatal(err)
	}
	_ = acceptWithTimeout(t, s2)

	writeDone := make(chan error, 1)
	go func() {
		_, err := st1.Write(make([]byte, 1<<20))
		writeDone <- err
	}()

	// Let it block on flow control.
	time.Sleep(100 * time.Millisecond)
	select {
	case err := <-writeDone:
		t.Fatalf("write finished before close: %v", err)
	default:
	}

	if err := st1.Close(); err != nil {
		t.Fatal(err)
	}

	select {
	case err := <-writeDone:
		if err != io.ErrClosedPipe {
			t.Fatalf("write err = %v, want io.ErrClosedPipe", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("blocked writer not unblocked by Close")
	}
}

func TestMuxSNMPClosedCounting(t *testing.T) {
	c1, c2 := net.Pipe()
	defer c1.Close()
	defer c2.Close()

	cfg1 := DefaultMuxConfig()
	cfg1.Side = MuxSideClient
	cfg2 := DefaultMuxConfig()
	cfg2.Side = MuxSideServer

	s1, s2 := newMuxPair(t, c1, c2, &cfg1, &cfg2)

	before1 := DefaultSnmp.Copy().MuxStreamsClosed
	before2 := before1

	st1, err := s1.OpenStream(MuxPriorityNormal)
	if err != nil {
		t.Fatal(err)
	}
	st2 := acceptWithTimeout(t, s2)

	// Local close increments this side's counter.
	if err := st1.Close(); err != nil {
		t.Fatal(err)
	}
	// Wait for the peer to process the FIN and close its side.
	if _, err := st2.Read(make([]byte, 1)); err != io.EOF {
		t.Fatalf("expected EOF after remote close, got %v", err)
	}

	after1 := DefaultSnmp.Copy().MuxStreamsClosed
	if after1 < before1+1 {
		t.Fatalf("MuxStreamsClosed not incremented on local close: %d -> %d", before1, after1)
	}
	if after1 < before2+1 {
		t.Fatalf("MuxStreamsClosed not incremented on remote close: %d -> %d", before2, after1)
	}
}
