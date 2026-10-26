cd /app && python3 - <<'PYEOF'
path = 'sqlite_utils/cli.py'
src = open(path).read()
old = """    except (OperationalError, sqlite3.IntegrityError) as e:
        raise click.ClickException(str(e))


@cli.command(name="enable-safe-import")
"""
new = """    except (OperationalError, sqlite3.IntegrityError) as e:
        raise click.ClickException(str(e))


@cli.command(name="enable-safe-import")
"""
# There are 3 blank lines between. Let's collapse.
import re
src = re.sub(r"(raise click\.ClickException\(str\(e\)\)\n)\n\n\n(@cli\.command\(name=\"enable-safe-import\"\))", r"\1\n\n\2", src)
open(path, 'w').write(src)
print("done")
PYEOF
grep -n "enable-safe-import" sqlite_utils/cli.py | head -3 && sed -n '1536,1543p' sqlite_utils/cli.py