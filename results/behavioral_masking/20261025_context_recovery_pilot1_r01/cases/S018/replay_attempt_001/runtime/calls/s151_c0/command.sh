cd /app && git config user.name "Bandit Dev" && git config user.email "dev@example.com" && git commit -m "Add nosec-begin, nosec-end, and nosec-next-line directives

Support suppressing whole regions of code and the next statement with
# nosec-begin/# nosec-end and # nosec-next-line directives. Directives
accept optional selectors with set operators, globs, test names, and the
special all/none tokens. All directives are ignored with --ignore-nosec,
and suppressions are combined so that a blanket suppression dominates." && git log --oneline -3