cd /app && cat > /tmp/test_mux_validation.py <<'PYEOF'
import socket, time, threading
from pwnlib.tubes.listen import listen
from pwnlib.tubes.remote import remote
from pwnlib.tubes.tube import tube
from pwnlib.tubes.buffer import Buffer
from pwnlib.tubes.mux import TubeMultiplexer, MuxChannel

# Buffer watermarks
b = Buffer()
print("initial high/low", b.high_water, b.low_water, b.over_high_water, b.under_low_water)
b.set_watermarks(high=10, low=5)
b.add(b'abcdef')
print("size6 over_high", b.over_high_water, "under_low", b.under_low_water)
b.add(b'ghij')
print("size10 over_high", b.over_high_water, "under_low", b.under_low_water)
b.add(b'k')
print("size11 over_high", b.over_high_water)
b.get(6)
print("size5 under_low", b.under_low_water, "over_high", b.over_high_water)
b.get()
print("size0 under_low", b.under_low_water)
try:
    b.set_watermarks(high=10, low=20)
    print("ERROR no ValueError")
except ValueError:
    print("set_watermarks ValueError ok")

# Constructor validation
l = listen(0); r = remote('localhost', l.lport); srv = l.wait_for_connection()
try:
    TubeMultiplexer("not a tube")
    print("ERROR TypeError")
except TypeError:
    print("TypeError ok")
for bad in [0, -1, 65536, 1.5, "x", True]:
    try:
        TubeMultiplexer(r, max_channels=bad)
        print("ERROR ValueError for", bad)
    except ValueError:
        print("ValueError ok for max_channels", bad)
    except Exception as e:
        print("wrong exc", bad, type(e).__name__, e)
try:
    TubeMultiplexer(r, high_water_mark=10, low_water_mark=20)
    print("ERROR ValueError water")
except ValueError:
    print("water ValueError ok")

m = TubeMultiplexer(r)
print("mux on tube?", isinstance(r.mux(), TubeMultiplexer))
print("properties", m.high_water_mark, m.low_water_mark, m.max_channels, isinstance(m.channels, dict))
m.close()

# MuxChannel subclass
print("MuxChannel subclass of tube:", issubclass(MuxChannel, tube))
r.close(); l.close()
PYEOF
timeout 20 python /tmp/test_mux_validation.py