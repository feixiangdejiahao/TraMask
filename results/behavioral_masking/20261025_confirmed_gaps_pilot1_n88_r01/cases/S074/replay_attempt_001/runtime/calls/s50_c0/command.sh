cd /app && cat > /tmp/patch_vm.py <<'PYEOF'
p='vm.go'
s=open(p).read()

# Add fields to VM struct
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
}'''
new='''type VM struct {
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
assert old in s
s=s.replace(old,new)

# Set ctx in NewVM
old='''	v := &VM{
		constants:   bytecode.Constants,
		sp:          0,
		globals:     globals,
		fileSet:     bytecode.FileSet,
		framesIndex: 1,
		ip:          -1,
		maxAllocs:   maxAllocs,
	}
	v.frames[0].fn = bytecode.MainFunction
	v.frames[0].ip = -1
	v.curFrame = &v.frames[0]
	v.curInsts = v.curFrame.fn.Instructions
	return v
}'''
new='''	v := &VM{
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
assert old in s
s=s.replace(old,new)

# Refactor Run error formatting into formatError and add runFunction
old='''// Run starts the execution.
func (v *VM) Run() (err error) {
	// reset VM states
	v.sp = 0
	v.curFrame = &(v.frames[0])
	v.curInsts = v.curFrame.fn.Instructions
	v.framesIndex = 1
	v.ip = -1
	v.allocs = v.maxAllocs + 1

	v.run()
	atomic.StoreInt64(&v.aborting, 0)
	err = v.err
	if err != nil {
		filePos := v.fileSet.Position(
			v.curFrame.fn.SourcePos(v.ip - 1))
		err = fmt.Errorf("Runtime Error: %w\\n\\tat %s",
			err, filePos)
		for v.framesIndex > 1 {
			v.framesIndex--
			v.curFrame = &v.frames[v.framesIndex-1]
			filePos = v.fileSet.Position(
				v.curFrame.fn.SourcePos(v.curFrame.ip - 1))
			err = fmt.Errorf("%w\\n\\tat %s", err, filePos)
		}
		return err
	}
	return nil
}'''
new='''// Run starts the execution.
func (v *VM) Run() (err error) {
	// reset VM states
	v.sp = 0
	v.curFrame = &(v.frames[0])
	v.curInsts = v.curFrame.fn.Instructions
	v.framesIndex = 1
	v.ip = -1
	v.allocs = v.maxAllocs + 1

	v.run()
	atomic.StoreInt64(&v.aborting, 0)
	err = v.err
	if err != nil {
		return v.formatError(err)
	}
	return nil
}

// runFunction runs a single compiled function with the given arguments and
// returns its return value. It is used to support invoking compiled functions
// from Go code (CompiledFunction.Call).
func (v *VM) runFunction(fn *CompiledFunction, args []Object) (
	Object, error) {
	v.stopOnReturn = true
	v.returnValue = UndefinedValue
	v.frames[0].fn = fn
	v.frames[0].freeVars = fn.Free
	v.frames[0].ip = -1
	v.frames[0].basePointer = 0
	v.curFrame = &v.frames[0]
	v.curInsts = fn.Instructions
	v.framesIndex = 1
	v.ip = -1
	v.sp = 0
	for i, arg := range args {
		v.stack[i] = arg
	}
	v.sp = fn.NumLocals
	v.allocs = v.maxAllocs + 1

	v.run()
	atomic.StoreInt64(&v.aborting, 0)
	if v.err != nil {
		return nil, v.formatError(v.err)
	}
	ret := v.returnValue
	if ret == nil {
		ret = UndefinedValue
	}
	return ret, nil
}

// formatError wraps a runtime error with the runtime error message and the
// source position / call stack.
func (v *VM) formatError(err error) error {
	filePos := v.fileSet.Position(
		v.curFrame.fn.SourcePos(v.ip - 1))
	err = fmt.Errorf("Runtime Error: %w\\n\\tat %s",
		err, filePos)
	for v.framesIndex > 1 {
		v.framesIndex--
		v.curFrame = &v.frames[v.framesIndex-1]
		filePos = v.fileSet.Position(
			v.curFrame.fn.SourcePos(v.curFrame.ip - 1))
		err = fmt.Errorf("%w\\n\\tat %s", err, filePos)
	}
	return err
}'''
assert old in s
s=s.replace(old,new)

# Modify OpConstant
old='''		case parser.OpConstant:
			v.ip += 2
			cidx := int(v.curInsts[v.ip]) | int(v.curInsts[v.ip-1])<<8

			v.stack[v.sp] = v.constants[cidx]
			v.sp++'''
new='''		case parser.OpConstant:
			v.ip += 2
			cidx := int(v.curInsts[v.ip]) | int(v.curInsts[v.ip-1])<<8

			obj := v.constants[cidx]
			if fn, ok := obj.(*CompiledFunction); ok {
				obj = fn.attachContext(v.ctx)
			}
			v.stack[v.sp] = obj
			v.sp++'''
assert old in s
s=s.replace(old,new)

# Modify OpClosure
old='''			cl := &CompiledFunction{
				Instructions:  fn.Instructions,
				NumLocals:     fn.NumLocals,
				NumParameters: fn.NumParameters,
				VarArgs:       fn.VarArgs,
				SourceMap:     fn.SourceMap,
				Free:          free,
			}'''
new='''			cl := &CompiledFunction{
				Instructions:  fn.Instructions,
				NumLocals:     fn.NumLocals,
				NumParameters: fn.NumParameters,
				VarArgs:       fn.VarArgs,
				SourceMap:     fn.SourceMap,
				Free:          free,
				ctx:           v.ctx,
			}'''
assert old in s
s=s.replace(old,new)

# Modify OpReturn
old='''		case parser.OpReturn:
			v.ip++
			var retVal Object
			if int(v.curInsts[v.ip]) == 1 {
				retVal = v.stack[v.sp-1]
			} else {
				retVal = UndefinedValue
			}
			//v.sp--
			v.framesIndex--
			v.curFrame = &v.frames[v.framesIndex-1]
			v.curInsts = v.curFrame.fn.Instructions
			v.ip = v.curFrame.ip
			//v.sp = lastFrame.basePointer - 1
			v.sp = v.frames[v.framesIndex].basePointer
			// skip stack overflow check because (newSP) <= (oldSP)
			v.stack[v.sp-1] = retVal
			//v.sp++'''
new='''		case parser.OpReturn:
			v.ip++
			var retVal Object
			if int(v.curInsts[v.ip]) == 1 {
				retVal = v.stack[v.sp-1]
			} else {
				retVal = UndefinedValue
			}
			if v.stopOnReturn && v.framesIndex == 1 {
				v.returnValue = retVal
				v.sp = 0
				return
			}
			//v.sp--
			v.framesIndex--
			v.curFrame = &v.frames[v.framesIndex-1]
			v.curInsts = v.curFrame.fn.Instructions
			v.ip = v.curFrame.ip
			//v.sp = lastFrame.basePointer - 1
			v.sp = v.frames[v.framesIndex].basePointer
			// skip stack overflow check because (newSP) <= (oldSP)
			v.stack[v.sp-1] = retVal
			//v.sp++'''
assert old in s
s=s.replace(old,new)

open(p,'w').write(s)
print("done")
PYEOF
python3 /tmp/patch_vm.py && gofmt -w vm.go && go build ./... 2>&1 | head -30