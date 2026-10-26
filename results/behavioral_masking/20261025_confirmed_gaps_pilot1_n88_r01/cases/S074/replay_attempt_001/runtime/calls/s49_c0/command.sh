cd /app && cat > /tmp/patch_objects.py <<'PYEOF'
import re
p='objects.go'
s=open(p).read()

old='''// CompiledFunction represents a compiled function.
type CompiledFunction struct {
	ObjectImpl
	Instructions  []byte
	NumLocals     int // number of local variables (including function parameters)
	NumParameters int
	VarArgs       bool
	SourceMap     map[int]parser.Pos
	Free          []*ObjectPtr
}'''

new='''// functionContext stores the execution context (bytecode, globals and
// allocation limit) needed to invoke a CompiledFunction from Go code outside
// of a running VM.
type functionContext struct {
	bytecode  *Bytecode
	globals   []Object
	maxAllocs int64
}

// CompiledFunction represents a compiled function.
type CompiledFunction struct {
	ObjectImpl
	Instructions  []byte
	NumLocals     int // number of local variables (including function parameters)
	NumParameters int
	VarArgs       bool
	SourceMap     map[int]parser.Pos
	Free          []*ObjectPtr
	ctx           *functionContext
}'''

assert old in s
s=s.replace(old,new)

old='''// Copy returns a copy of the type.
func (o *CompiledFunction) Copy() Object {
	return &CompiledFunction{
		Instructions:  append([]byte{}, o.Instructions...),
		NumLocals:     o.NumLocals,
		NumParameters: o.NumParameters,
		VarArgs:       o.VarArgs,
		Free:          append([]*ObjectPtr{}, o.Free...), // DO NOT Copy() of elements; these are variable pointers
	}
}'''

new='''// Copy returns a copy of the type.
func (o *CompiledFunction) Copy() Object {
	return &CompiledFunction{
		Instructions:  append([]byte{}, o.Instructions...),
		NumLocals:     o.NumLocals,
		NumParameters: o.NumParameters,
		VarArgs:       o.VarArgs,
		SourceMap:     o.SourceMap,
		Free:          append([]*ObjectPtr{}, o.Free...), // DO NOT Copy() of elements; these are variable pointers
		ctx:           o.ctx,
	}
}

// attachContext returns a copy of o with the given execution context attached.
// Unlike bindContext, attachContext keeps the original free-variable pointers,
// so closures continue to share their captured variables during VM execution.
func (o *CompiledFunction) attachContext(ctx *functionContext) *CompiledFunction {
	if o.ctx == ctx {
		return o
	}
	return &CompiledFunction{
		Instructions:  o.Instructions,
		NumLocals:     o.NumLocals,
		NumParameters: o.NumParameters,
		VarArgs:       o.VarArgs,
		SourceMap:     o.SourceMap,
		Free:          o.Free,
		ctx:           ctx,
	}
}

// bindContext returns a copy of o bound to ctx. The captured free variables are
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
		if p != nil {
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

assert old in s
s=s.replace(old,new)

old='''// CanCall returns whether the Object can be Called.
func (o *CompiledFunction) CanCall() bool {
	return true
}

// Error represents an error value.'''

new='''// CanCall returns whether the Object can be Called.
func (o *CompiledFunction) CanCall() bool {
	return true
}

// Call invokes the compiled function from Go code. The function executes with
// the same globals, imports, closure captures, variadic behavior and error
// formatting as it would inside the VM.
func (o *CompiledFunction) Call(args ...Object) (Object, error) {
	if o.ctx == nil {
		return nil, fmt.Errorf("not callable: %s", o.TypeName())
	}

	if o.VarArgs {
		realArgs := o.NumParameters - 1
		if len(args) < realArgs {
			return nil, fmt.Errorf(
				"wrong number of arguments: want>=%d, got=%d",
				realArgs, len(args))
		}
		varArgs := make([]Object, len(args)-realArgs)
		copy(varArgs, args[realArgs:])
		args = append(args[:realArgs], &Array{Value: varArgs})
	} else if len(args) != o.NumParameters {
		return nil, fmt.Errorf(
			"wrong number of arguments: want=%d, got=%d",
			o.NumParameters, len(args))
	}

	v := NewVM(o.ctx.bytecode, o.ctx.globals, o.ctx.maxAllocs)
	ret, err := v.runFunction(o, args)
	if err != nil {
		return nil, err
	}

	// bind the result (and any callable values reachable from it) to the
	// same execution context so it remains callable from Go.
	return bindObject(ret, o.ctx), nil
}

// bindObject recursively rebinds callable values to ctx. Composite values are
// deep-copied so that the resulting object is isolated from the original.
func bindObject(o Object, ctx *functionContext) Object {
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
		return &Error{Value: bindObject(o.Value, ctx)}
	default:
		return o.Copy()
	}
}

// Error represents an error value.'''

assert old in s
s=s.replace(old,new)

open(p,'w').write(s)
print("done")
PYEOF
python3 /tmp/patch_objects.py && gofmt -w objects.go && sed -n '565,750p' objects.go