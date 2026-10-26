cd /app && git add pwnlib/tubes/mux.py pwnlib/tubes/buffer.py pwnlib/tubes/tube.py pwnlib/tubes/__init__.py pwn/toplevel.py && git status --short && git commit -m "Add TubeMultiplexer and MuxChannel for multiplexing tubes

Implement a multiplexer that supports multiple independent, bidirectional
logical channels over a single underlying tube:

- New pwnlib.tubes.mux module with TubeMultiplexer and MuxChannel
- open_channel/accept_channel with handshake, validation and timeouts
- Per-channel flow control with configurable high/low water marks
- Channel close and half-close (shutdown) semantics with EOF propagation
- Underlying tube death propagates EOF to all channels
- Buffer.set_watermarks plus high_water/low_water/over_high_water/
  under_low_water properties
- tube.mux() convenience wrapper" && git log --oneline -2