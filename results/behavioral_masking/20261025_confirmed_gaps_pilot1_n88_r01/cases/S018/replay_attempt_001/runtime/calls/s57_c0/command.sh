cd /app && python - <<'EOF'
path = 'tests/test_rrule.py'
with open(path) as f:
    src = f.read()
old = """@pytest.mark.rrule
@pytest.mark.rrulestr
@pytest.mark.xfail(reason=\"rrulestr loses time zone, gh issue #637\")
@freeze_time(datetime(2018, 3, 6, 5, 36, tzinfo=tz.UTC))
def test_generated_aware_dtstart_rrulestr():"""
new = """@pytest.mark.rrule
@pytest.mark.rrulestr
@freeze_time(datetime(2018, 3, 6, 5, 36, tzinfo=tz.UTC))
def test_generated_aware_dtstart_rrulestr():"""
assert old in src
src = src.replace(old, new, 1)
with open(path, 'w') as f:
    f.write(src)
print("xfail removed")
EOF
cd /app && python -m pytest tests/test_rrule.py -q 2>&1 | tail -5