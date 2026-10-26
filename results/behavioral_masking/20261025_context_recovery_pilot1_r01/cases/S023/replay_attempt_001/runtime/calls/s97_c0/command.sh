cd /app && python - <<'EOF'
path='docs/cattrs.rst'
s=open(path).read()
old='''cattrs.errors module
--------------------

.. automodule:: cattrs.errors
   :members:
   :undoc-members:
   :show-inheritance:
'''
new='''cattrs.errors module
--------------------

.. automodule:: cattrs.errors
   :members:
   :undoc-members:
   :show-inheritance:

cattrs.partial module
---------------------

.. automodule:: cattrs.partial
   :members:
   :undoc-members:
   :show-inheritance:
'''
assert old in s
open(path,'w').write(s.replace(old,new))
print("docs cattrs.rst updated")
EOF
cd /app && git status --short