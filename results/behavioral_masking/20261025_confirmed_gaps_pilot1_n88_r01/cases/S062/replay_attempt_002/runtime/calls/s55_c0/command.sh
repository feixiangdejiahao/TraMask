cd /app && python - <<'PY'
path='pwnlib/tubes/mux.py'
src=open(path).read()
old="""        if not isinstance(underlying, tube):
            raise TypeError('underlying must be a tube, got %r' % type(underlying).__name__)
"""
new="""        import sys, traceback
        if not isinstance(underlying, tube):
            print('DEBUG underlying class:', underlying.__class__)
            print('DEBUG tube class:', tube, tube.__module__)
            print('DEBUG underlying class module:', underlying.__class__.__module__)
            print('DEBUG tube is class?', isinstance(tube, type))
            print('DEBUG isinstance:', isinstance(underlying, tube))
            traceback.print_stack()
            raise TypeError('underlying must be a tube, got %r' % type(underlying).__name__)
"""
src=src.replace(old,new,1)
open(path,'w').write(src)
print('debug added')
PY
timeout 120 python -m doctest pwnlib/tubes/tube.py 2>&1 | grep -A12 "DEBUG" | head -40