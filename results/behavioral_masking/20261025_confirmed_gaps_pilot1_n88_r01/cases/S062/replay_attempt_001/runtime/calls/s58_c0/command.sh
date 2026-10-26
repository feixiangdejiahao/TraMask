cd /app && python - <<'PY'
path='pwnlib/tubes/mux.py'
src=open(path).read()
old="""        import sys, traceback
        if not isinstance(underlying, tube):
            print('DEBUG underlying class:', underlying.__class__)
            print('DEBUG tube class:', tube, tube.__module__)
            print('DEBUG underlying class module:', underlying.__class__.__module__)
            print('DEBUG tube is class?', isinstance(tube, type))
            print('DEBUG isinstance:', isinstance(underlying, tube))
            traceback.print_stack()
            raise TypeError('underlying must be a tube, got %r' % type(underlying).__name__)
"""
new="""        import sys, traceback
        if not isinstance(underlying, tube):
            with open('/tmp/debug_mux.txt','a') as _f:
                _f.write('underlying class: %r %r\\n' % (underlying.__class__, underlying.__class__.__module__))
                _f.write('tube class: %r %r\\n' % (tube, getattr(tube,'__module__',None)))
                _f.write('tube is class? %r\\n' % isinstance(tube, type))
                _f.write('isinstance: %r\\n' % isinstance(underlying, tube))
                _f.write('id underlying cls: %x id tube: %x\\n' % (id(underlying.__class__), id(tube)))
                traceback.print_stack(file=_f)
            raise TypeError('underlying must be a tube, got %r' % type(underlying).__name__)
"""
src=src.replace(old,new,1)
open(path,'w').write(src)
print('debug to file')
PY
rm -f /tmp/debug_mux.txt
timeout 120 python -m doctest pwnlib/tubes/tube.py >/dev/null 2>&1
cat /tmp/debug_mux.txt 2>/dev/null | head -40