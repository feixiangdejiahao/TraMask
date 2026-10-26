cd /app && python3 - <<'PY'
p='packages/prompts/src/autocomplete.ts'
lines=open(p).read().split('\n')
# find start/end line
start=None
end=None
for i,l in enumerate(lines):
    if '// No matches message' in l and start is None:
        start=i
    if start is not None and l.strip() == ');' and i>start:
        # ensure this is the headings push closing by checking nearby
        if any('...validationError' in x for x in lines[max(0,i-6):i]):
            end=i
            break
print("start,end", start, end)
if start is not None and end is not None:
    print('\n'.join(f"{j}:{lines[j]}" for j in range(start,end+1)))
PY