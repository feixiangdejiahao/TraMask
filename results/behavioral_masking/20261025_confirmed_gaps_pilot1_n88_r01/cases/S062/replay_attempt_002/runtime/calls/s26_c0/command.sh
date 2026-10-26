cd /app && python - <<'PY'
path='pwnlib/tubes/mux.py'
src=open(path).read()
old="""        except Exception as e:
            log.debug('multiplexer reader error: %r', e)
"""
new="""        except Exception as e:
            import traceback; traceback.print_exc()
            log.debug('multiplexer reader error: %r', e)
"""
src=src.replace(old,new,1)
open(path,'w').write(src)
print('ok')
PY
python /tmp/test_mux2.py 2>&1 | grep -A20 "Traceback (most recent call last)" | head -40