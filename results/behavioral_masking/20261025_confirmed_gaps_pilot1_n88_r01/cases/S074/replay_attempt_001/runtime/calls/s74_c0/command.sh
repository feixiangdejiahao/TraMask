cd /app && python3 - <<'PYEOF'
p='objects.go'
s=open(p).read()

# Change bindObject default from o.Copy() to o
old='''	default:
		return o.Copy()
	}
}

// Error represents an error value.'''
new='''	default:
		return o
	}
}

// Error represents an error value.'''
assert old in s
s=s.replace(old,new,1)
open(p,'w').write(s)

p='script.go'
s=open(p).read()

# Set: remove .Copy()
old='''	c.globals[idx] = bindObject(obj.Copy(), c.ctx)
	return nil
}'''
new='''	c.globals[idx] = bindObject(obj, c.ctx)
	return nil
}'''
assert old in s
s=s.replace(old,new,1)

# Clone: use g.Copy() with nil guard and bindObject
old='''	// copy global objects and rebind any callable values to the clone's
	// execution context. Captured free variables are snapshotted at clone
	// time so the clone is fully isolated from the source instance.
	for idx, g := range c.globals {
		if g != nil {
			clone.globals[idx] = bindObject(g, clone.ctx)
		}
	}
	return clone
}'''
new='''	// copy global objects and rebind any callable values to the clone's
	// execution context. Captured free variables are snapshotted at clone
	// time so the clone is fully isolated from the source instance.
	for idx, g := range c.globals {
		if g != nil {
			if cp := g.Copy(); cp != nil {
				clone.globals[idx] = bindObject(cp, clone.ctx)
			}
		}
	}
	return clone
}'''
assert old in s
s=s.replace(old,new,1)
open(p,'w').write(s)
print("done")
PYEOF
gofmt -w objects.go script.go && go test ./... 2>&1 | tail -30