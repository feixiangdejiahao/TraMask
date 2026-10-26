cd /app && python - <<'PY'
path='pwnlib/tubes/mux.py'
src=open(path).read()
# Remove debug block
old='''        import sys, traceback
        if not isinstance(underlying, tube):
            with open('/tmp/debug_mux.txt','a') as _f:
                _f.write('underlying class: %r %r\\n' % (underlying.__class__, underlying.__class__.__module__))
                _f.write('tube class: %r %r\\n' % (tube, getattr(tube,'__module__',None)))
                _f.write('tube is class? %r\\n' % isinstance(tube, type))
                _f.write('isinstance: %r\\n' % isinstance(underlying, tube))
                _f.write('id underlying cls: %x id tube: %x\\n' % (id(underlying.__class__), id(tube)))
                traceback.print_stack(file=_f)
            raise TypeError('underlying must be a tube, got %r' % type(underlying).__name__)
'''
new='''        if not isinstance(underlying, tube):
            raise TypeError('underlying must be a tube, got %r' % type(underlying).__name__)
'''
assert old in src
src=src.replace(old,new,1)
open(path,'w').write(src)

path='pwnlib/tubes/tube.py'
src=open(path).read()
old='''            >>> from pwnlib.tubes.mux import TubeMultiplexer
            >>> t = tube()
            >>> isinstance(t.mux(), TubeMultiplexer)
            True
'''
new='''            >>> from pwnlib.tubes.mux import TubeMultiplexer
            >>> from pwnlib.tubes.tube import tube as _tube
            >>> t = _tube()
            >>> isinstance(t.mux(), TubeMultiplexer)
            True
'''
assert old in src
src=src.replace(old,new,1)
open(path,'w').write(src)
print('patched')
PY
python -m py_compile pwnlib/tubes/mux.py && python -m py_compile pwnlib/tubes/tube.py
timeout 120 python -m doctest pwnlib/tubes/tube.py 2>&1 | grep -E "tube.tube.mux|items had failures" | head