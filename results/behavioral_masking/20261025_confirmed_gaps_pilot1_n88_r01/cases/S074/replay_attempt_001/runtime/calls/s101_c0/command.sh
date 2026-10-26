cd /app && python3 - <<'PYEOF'
p='objects.go'
s=open(p).read()

old='''// bindContext returns a copy of o bound to ctx. The captured free variables are
// snapshotted at their current values so the copy is independent of the VM stack
// where the closure was created. The function bytecode (instructions, constants
// and imports) is preserved from the function's original context when one is
// available; only globals and the allocation limit are rebound to ctx.
func (o *CompiledFunction) bindContext(ctx *functionContext) *CompiledFunction {
	bytecode := ctx.bytecode
	if o.ctx != nil {
		bytecode = o.ctx.bytecode
	}
	free := make([]*ObjectPtr, len(o.Free))
	for i, p := range o.Free {
		if p != nil && p.Value != nil {
			val := *p.Value
			free[i] = &ObjectPtr{Value: &val}
		}
	}
	return &CompiledFunction{
		Instructions:  append([]byte{}, o.Instructions...),
		NumLocals:     o.NumLocals,
		NumParameters: o.NumParameters,
		VarArgs:       o.VarArgs,
		SourceMap:     o.SourceMap,
		Free:          free,
		ctx: &functionContext{
			bytecode:  bytecode,
			globals:   ctx.globals,
			maxAllocs: ctx.maxAllocs,
		},
	}
}'''
new='''// bindContext returns a copy of o bound to ctx. The captured free variables are
// snapshotted at their current values (recursively rebinding any callable
// values) so the copy is independent of the VM stack where the closure was
// created. The function bytecode (instructions, constants and imports) is
// preserved from the function's original context when one is available; only
// globals and the allocation limit are rebound to ctx.
func (o *CompiledFunction) bindContext(ctx *functionContext) *CompiledFunction {
	return o.bindContextRec(ctx, make(map[Object]Object))
}

func (o *CompiledFunction) bindContextRec(
	ctx *functionContext,
	seen map[Object]Object,
) *CompiledFunction {
	if bound, ok := seen[o]; ok {
		if b, ok := bound.(*CompiledFunction); ok {
			return b
		}
	}
	bytecode := ctx.bytecode
	if o.ctx != nil {
		bytecode = o.ctx.bytecode
	}
	bound := &CompiledFunction{
		Instructions:  append([]byte{}, o.Instructions...),
		NumLocals:     o.NumLocals,
		NumParameters: o.NumParameters,
		VarArgs:       o.VarArgs,
		SourceMap:     o.SourceMap,
		ctx: &functionContext{
			bytecode:  bytecode,
			globals:   ctx.globals,
			maxAllocs: ctx.maxAllocs,
		},
	}
	seen[o] = bound
	free := make([]*ObjectPtr, len(o.Free))
	for i, p := range o.Free {
		if p != nil && p.Value != nil {
			val := bindObjectRec(*p.Value, ctx, seen)
			free[i] = &ObjectPtr{Value: &val}
		}
	}
	bound.Free = free
	return bound
}'''
assert old in s
s=s.replace(old,new)

old='''// bindObject recursively rebinds callable values to ctx. Composite values are
// deep-copied so that the resulting object is isolated from the original.
func bindObject(o Object, ctx *functionContext) Object {
	if o == nil {
		return nil
	}
	switch o := o.(type) {
	case *CompiledFunction:
		return o.bindContext(ctx)
	case *Array:
		val := make([]Object, len(o.Value))
		for i, e := range o.Value {
			val[i] = bindObject(e, ctx)
		}
		return &Array{Value: val}
	case *ImmutableArray:
		val := make([]Object, len(o.Value))
		for i, e := range o.Value {
			val[i] = bindObject(e, ctx)
		}
		return &ImmutableArray{Value: val}
	case *Map:
		val := make(map[string]Object, len(o.Value))
		for k, e := range o.Value {
			val[k] = bindObject(e, ctx)
		}
		return &Map{Value: val}
	case *ImmutableMap:
		val := make(map[string]Object, len(o.Value))
		for k, e := range o.Value {
			val[k] = bindObject(e, ctx)
		}
		return &ImmutableMap{Value: val}
	case *Error:
		val := bindObject(o.Value, ctx)
		return &Error{Value: val}
	default:
		return o
	}
}'''
new='''// bindObject recursively rebinds callable values to ctx. Composite values are
// deep-copied so that the resulting object is isolated from the original.
func bindObject(o Object, ctx *functionContext) Object {
	return bindObjectRec(o, ctx, make(map[Object]Object))
}

func bindObjectRec(
	o Object,
	ctx *functionContext,
	seen map[Object]Object,
) Object {
	if o == nil {
		return nil
	}
	switch o := o.(type) {
	case *CompiledFunction:
		return o.bindContextRec(ctx, seen)
	case *Array:
		if bound, ok := seen[o]; ok {
			return bound
		}
		arr := &Array{Value: make([]Object, len(o.Value))}
		seen[o] = arr
		for i, e := range o.Value {
			arr.Value[i] = bindObjectRec(e, ctx, seen)
		}
		return arr
	case *ImmutableArray:
		if bound, ok := seen[o]; ok {
			return bound
		}
		arr := &ImmutableArray{Value: make([]Object, len(o.Value))}
		seen[o] = arr
		for i, e := range o.Value {
			arr.Value[i] = bindObjectRec(e, ctx, seen)
		}
		return arr
	case *Map:
		if bound, ok := seen[o]; ok {
			return bound
		}
		m := &Map{Value: make(map[string]Object, len(o.Value))}
		seen[o] = m
		for k, e := range o.Value {
			m.Value[k] = bindObjectRec(e, ctx, seen)
		}
		return m
	case *ImmutableMap:
		if bound, ok := seen[o]; ok {
			return bound
		}
		m := &ImmutableMap{Value: make(map[string]Object, len(o.Value))}
		seen[o] = m
		for k, e := range o.Value {
			m.Value[k] = bindObjectRec(e, ctx, seen)
		}
		return m
	case *Error:
		val := bindObjectRec(o.Value, ctx, seen)
		return &Error{Value: val}
	default:
		return o
	}
}'''
assert old in s
s=s.replace(old,new)

open(p,'w').write(s)
print("done")
PYEOF
gofmt -w objects.go && go build ./... && echo OK