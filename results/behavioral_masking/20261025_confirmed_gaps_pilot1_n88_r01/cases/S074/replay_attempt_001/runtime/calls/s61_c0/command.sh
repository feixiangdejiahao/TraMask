cd /app && cat > /tmp/patch_vm2.py <<'PYEOF'
p='vm.go'
s=open(p).read()

# Add bytecode/ctx to frame
old='''// frame represents a function call frame.
type frame struct {
	fn          *CompiledFunction
	freeVars    []*ObjectPtr
	ip          int
	basePointer int
}'''
new='''// frame represents a function call frame.
type frame struct {
	fn          *CompiledFunction
	freeVars    []*ObjectPtr
	ip          int
	basePointer int
	bytecode    *Bytecode
	ctx         *functionContext
}'''
assert old in s
s=s.replace(old,new)

# Add bytecode field to VM
old='''type VM struct {
	constants   []Object
	stack       [StackSize]Object
	sp          int
	globals     []Object
	fileSet     *parser.SourceFileSet
	frames      [MaxFrames]frame
	framesIndex int
	curFrame    *frame
	curInsts    []byte
	ip          int
	aborting    int64
	maxAllocs   int64
	allocs      int64
	err         error
	ctx         *functionContext
	stopOnReturn bool
	returnValue  Object
}'''
new='''type VM struct {
	constants   []Object
	bytecode    *Bytecode
	stack       [StackSize]Object
	sp          int
	globals     []Object
	fileSet     *parser.SourceFileSet
	frames      [MaxFrames]frame
	framesIndex int
	curFrame    *frame
	curInsts    []byte
	ip          int
	aborting    int64
	maxAllocs   int64
	allocs      int64
	err         error
	ctx         *functionContext
	stopOnReturn bool
	returnValue  Object
}'''
assert old in s
s=s.replace(old,new)

# NewVM: set bytecode and frame bytecode/ctx
old='''	v := &VM{
		constants:   bytecode.Constants,
		sp:          0,
		globals:     globals,
		fileSet:     bytecode.FileSet,
		framesIndex: 1,
		ip:          -1,
		maxAllocs:   maxAllocs,
	}
	v.ctx = &functionContext{
		bytecode:  bytecode,
		globals:   v.globals,
		maxAllocs: maxAllocs,
	}
	v.frames[0].fn = bytecode.MainFunction
	v.frames[0].ip = -1
	v.curFrame = &v.frames[0]
	v.curInsts = v.curFrame.fn.Instructions
	return v
}'''
new='''	v := &VM{
		constants:   bytecode.Constants,
		bytecode:    bytecode,
		sp:          0,
		globals:     globals,
		fileSet:     bytecode.FileSet,
		framesIndex: 1,
		ip:          -1,
		maxAllocs:   maxAllocs,
	}
	v.ctx = &functionContext{
		bytecode:  bytecode,
		globals:   v.globals,
		maxAllocs: maxAllocs,
	}
	v.frames[0].fn = bytecode.MainFunction
	v.frames[0].ip = -1
	v.frames[0].bytecode = bytecode
	v.frames[0].ctx = v.ctx
	v.curFrame = &v.frames[0]
	v.curInsts = v.curFrame.fn.Instructions
	return v
}'''
assert old in s
s=s.replace(old,new)

# runFunction: set frame bytecode/ctx from fn.ctx
old='''	v.stopOnReturn = true
	v.returnValue = UndefinedValue
	v.frames[0].fn = fn
	v.frames[0].freeVars = fn.Free
	v.frames[0].ip = -1
	v.frames[0].basePointer = 0
	v.curFrame = &v.frames[0]'''
new='''	v.stopOnReturn = true
	v.returnValue = UndefinedValue
	v.frames[0].fn = fn
	v.frames[0].freeVars = fn.Free
	v.frames[0].ip = -1
	v.frames[0].basePointer = 0
	if fn.ctx != nil {
		v.frames[0].bytecode = fn.ctx.bytecode
		v.frames[0].ctx = fn.ctx
	} else {
		v.frames[0].bytecode = v.bytecode
		v.frames[0].ctx = v.ctx
	}
	v.curFrame = &v.frames[0]'''
assert old in s
s=s.replace(old,new)

# OpConstant use curFrame bytecode constants + curFrame ctx
old='''		case parser.OpConstant:
			v.ip += 2
			cidx := int(v.curInsts[v.ip]) | int(v.curInsts[v.ip-1])<<8

			obj := v.constants[cidx]
			if fn, ok := obj.(*CompiledFunction); ok {
				obj = fn.attachContext(v.ctx)
			}
			v.stack[v.sp] = obj
			v.sp++'''
new='''		case parser.OpConstant:
			v.ip += 2
			cidx := int(v.curInsts[v.ip]) | int(v.curInsts[v.ip-1])<<8

			obj := v.curFrame.bytecode.Constants[cidx]
			if fn, ok := obj.(*CompiledFunction); ok {
				obj = fn.attachContext(v.curFrame.ctx)
			}
			v.stack[v.sp] = obj
			v.sp++'''
assert old in s
s=s.replace(old,new)

# OpCall: set frame bytecode/ctx
old='''				// update call frame
				v.curFrame.ip = v.ip // store current ip before call
				v.curFrame = &(v.frames[v.framesIndex])
				v.curFrame.fn = callee
				v.curFrame.freeVars = callee.Free
				v.curFrame.basePointer = v.sp - numArgs
				v.curInsts = callee.Instructions
				v.ip = -1
				v.framesIndex++
				v.sp = v.sp - numArgs + callee.NumLocals'''
new='''				// update call frame
				v.curFrame.ip = v.ip // store current ip before call
				v.curFrame = &(v.frames[v.framesIndex])
				v.curFrame.fn = callee
				v.curFrame.freeVars = callee.Free
				v.curFrame.basePointer = v.sp - numArgs
				if callee.ctx != nil {
					v.curFrame.bytecode = callee.ctx.bytecode
					v.curFrame.ctx = callee.ctx
				} else {
					v.curFrame.bytecode = v.bytecode
					v.curFrame.ctx = v.ctx
				}
				v.curInsts = callee.Instructions
				v.ip = -1
				v.framesIndex++
				v.sp = v.sp - numArgs + callee.NumLocals'''
assert old in s
s=s.replace(old,new)

# OpClosure: use curFrame bytecode constants and curFrame ctx
old='''			fn, ok := v.constants[constIndex].(*CompiledFunction)
			if !ok {
				v.err = fmt.Errorf("not function: %s", fn.TypeName())
				return
			}'''
new='''			fn, ok := v.curFrame.bytecode.Constants[constIndex].(*CompiledFunction)
			if !ok {
				v.err = fmt.Errorf("not function: %s", fn.TypeName())
				return
			}'''
assert old in s
s=s.replace(old,new)

old='''			cl := &CompiledFunction{
				Instructions:  fn.Instructions,
				NumLocals:     fn.NumLocals,
				NumParameters: fn.NumParameters,
				VarArgs:       fn.VarArgs,
				SourceMap:     fn.SourceMap,
				Free:          free,
				ctx:           v.ctx,
			}'''
new='''			cl := &CompiledFunction{
				Instructions:  fn.Instructions,
				NumLocals:     fn.NumLocals,
				NumParameters: fn.NumParameters,
				VarArgs:       fn.VarArgs,
				SourceMap:     fn.SourceMap,
				Free:          free,
				ctx:           v.curFrame.ctx,
			}'''
assert old in s
s=s.replace(old,new)

open(p,'w').write(s)
print("done")
PYEOF
python3 /tmp/patch_vm2.py && gofmt -w vm.go && go build ./... 2>&1 | head -30