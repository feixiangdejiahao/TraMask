cd /app && cat > /tmp/patch_script.py <<'PYEOF'
p='script.go'
s=open(p).read()

old='''	return &Compiled{
		globalIndexes: globalIndexes,
		bytecode:      bytecode,
		globals:       globals,
		maxAllocs:     s.maxAllocs,
	}, nil
}'''
new='''	compiled := &Compiled{
		globalIndexes: globalIndexes,
		bytecode:      bytecode,
		globals:       globals,
		maxAllocs:     s.maxAllocs,
	}
	compiled.ctx = &functionContext{
		bytecode:  bytecode,
		globals:   globals,
		maxAllocs: s.maxAllocs,
	}

	// bind any callable values provided by the user to this compiled
	// instance so they execute against this instance's globals.
	for idx, g := range globals {
		if g != nil {
			globals[idx] = bindObject(g, compiled.ctx)
		}
	}
	return compiled, nil
}'''
assert old in s
s=s.replace(old,new)

old='''type Compiled struct {
	globalIndexes map[string]int // global symbol name to index
	bytecode      *Bytecode
	globals       []Object
	maxAllocs     int64
	lock          sync.RWMutex
}'''
new='''type Compiled struct {
	globalIndexes map[string]int // global symbol name to index
	bytecode      *Bytecode
	globals       []Object
	maxAllocs     int64
	ctx           *functionContext
	lock          sync.RWMutex
}'''
assert old in s
s=s.replace(old,new)

old='''	clone := &Compiled{
		globalIndexes: c.globalIndexes,
		bytecode:      c.bytecode,
		globals:       make([]Object, len(c.globals)),
		maxAllocs:     c.maxAllocs,
	}
	// copy global objects
	for idx, g := range c.globals {
		if g != nil {
			clone.globals[idx] = g.Copy()
		}
	}
	return clone
}'''
new='''	clone := &Compiled{
		globalIndexes: c.globalIndexes,
		bytecode:      c.bytecode,
		globals:       make([]Object, len(c.globals)),
		maxAllocs:     c.maxAllocs,
	}
	clone.ctx = &functionContext{
		bytecode:  c.bytecode,
		globals:   clone.globals,
		maxAllocs: c.maxAllocs,
	}
	// copy global objects and rebind any callable values to the clone's
	// execution context. Captured free variables are snapshotted at clone
	// time so the clone is fully isolated from the source instance.
	for idx, g := range c.globals {
		if g != nil {
			clone.globals[idx] = bindObject(g, clone.ctx)
		}
	}
	return clone
}'''
assert old in s
s=s.replace(old,new)

old='''	idx, ok := c.globalIndexes[name]
	if !ok {
		return fmt.Errorf("'%s' is not defined", name)
	}
	c.globals[idx] = obj
	return nil
}'''
new='''	idx, ok := c.globalIndexes[name]
	if !ok {
		return fmt.Errorf("'%s' is not defined", name)
	}
	// bind the value (and any callable values reachable inside arrays/maps)
	// to this compiled instance. Callables are rebound to this instance's
	// globals while their captured free variables are snapshotted, isolating
	// this instance from the value's source instance.
	c.globals[idx] = bindObject(obj.Copy(), c.ctx)
	return nil
}'''
assert old in s
s=s.replace(old,new)

open(p,'w').write(s)
print("done")
PYEOF
python3 /tmp/patch_script.py && gofmt -w script.go && go build ./... 2>&1 | head -30