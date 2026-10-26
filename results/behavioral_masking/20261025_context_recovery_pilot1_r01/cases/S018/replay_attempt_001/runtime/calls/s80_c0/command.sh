cd /app && python - <<'EOF'
path = 'doc/source/config.rst'
src = open(path).read()
anchor = '''.. code-block:: python

  assert yaml.load("{}") == []  # nosec assert_used

-----------------
Scanning Behavior
-----------------
'''
new = '''.. code-block:: python

  assert yaml.load("{}") == []  # nosec assert_used

Selectors may also use set operations and glob patterns to select which tests
are suppressed.  ``|``, ``&``, ``-`` and ``!`` are union, intersection,
difference and negation (relative to the enabled test set).  Spaces and commas
are also treated as union.  Parentheses can be used for grouping.  The special
token ``all`` suppresses every test and ``none`` makes the directive have no
effect.

For example, this suppresses B602 and B607, but leaves all other tests active:

.. code-block:: python

  self.process = subprocess.Popen('/bin/ls *', shell=True)  # nosec B602 | B607

This suppresses every B6xx test:

.. code-block:: python

  self.process = subprocess.Popen('/bin/ls *', shell=True)  # nosec B6*

Whole regions of code can be suppressed with ``# nosec-begin`` and
``# nosec-end``:

.. code-block:: python

  # nosec-begin
  self.process = subprocess.Popen('/bin/ls *', shell=True)
  self.process = subprocess.Popen('/bin/ls *', shell=True)
  # nosec-end

The directive line itself is not suppressed; the region starts on the line
after ``# nosec-begin`` and ends before the line containing ``# nosec-end``.
An indented region that is not explicitly ended is automatically ended when a
later line has smaller indentation; otherwise it runs to the end of the file.
A region may be given a selector, for example ``# nosec-begin B602`` only
suppresses the selected tests.  If a multi-line statement has any suppressed
line, findings for the whole statement are suppressed even if a
``# nosec-end`` appears later within the same statement.

The next statement can be suppressed with ``# nosec-next-line``:

.. code-block:: python

  # nosec-next-line B602
  self.process = subprocess.Popen('/bin/ls *', shell=True)

When locating the target statement, blank lines, comment-only lines, and lines
containing only grouping tokens (``(``, ``)``, ``[``, ``]``, ``{``, ``}``),
semicolons, or ellipsis literals (``...``) are skipped.  All directive
keywords are matched case-insensitively and are ignored when Bandit is run
with ``--ignore-nosec``.

-----------------
Scanning Behavior
-----------------
'''
assert anchor in src
src = src.replace(anchor, new)
open(path, 'w').write(src)
print("docs updated")
EOF