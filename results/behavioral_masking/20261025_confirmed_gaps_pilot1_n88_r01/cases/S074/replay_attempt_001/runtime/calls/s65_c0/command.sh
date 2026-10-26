cd /app && python3 - <<'PYEOF'
p='vm.go'
s=open(p).read()

# 1. Add bytecode to VM struct
s = s.replace('''type VM struct {
	constants    []Object
	stack''', '''type VM struct {
	constants    []Object
	bytecode     *Bytecode
	stack''', 1)

# 2. Add bytecode to frame struct
s = s.replace('''type frame struct {
	fn          *CompiledFunction
	freeVars    []*ObjectPtr
	ip          int
	basePointer int
}''', '''type frame struct {
	fn          *CompiledFunction
	freeVars    []*ObjectPtr
	ip          int
	basePointer int
	bytecode    *Bytecode
	ctx         *functionContext
}''', 1)

# 3. NewVM set bytecode field and frame bytecode/ctx
s = s.replace('''	v := &VM{
		constants:   bytecode.Constants,
		sp:          0,''', '''	v := &VM{
		constants:   bytecode.Constants,
		bytecode:    bytecode,
		sp:          0,''', 1)

s = s.replace('''	v.frames[0].fn = bytecode.MainFunction
	v.frames[0].ip = -1
	v.curFrame = &v.frames[0]''', '''	v.frames[0].fn = bytecode.MainFunction
	v.frames[0].ip = -1
	v.frames[0].bytecode = bytecode
	v.frames[0].ctx = v.ctx
	v.curFrame = &v.frames[0]''', 1)

# 4. runFunction frame bytecode/ctx
s = s.replace('''	v.frames[0].fn = fn
	v.frames[0].freeVars = fn.Free
	v.frames[0].ip = -1
	v.frames[0].basePointer = 0
	v.curFrame = &v.frames[0]''', '''	v.frames[0].fn = fn
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
	v.curFrame = &v.frames[0]''', 1)

# 5. OpConstant
s = s.replace('''			obj := v.constants[cidx]
			if fn, ok := obj.(*CompiledFunction); ok {
				obj = fn.attachContext(v.ctx)
			}''', '''			obj := v.curFrame.bytecode.Constants[cidx]
			if fn, ok := obj.(*CompiledFunction); ok {
				obj = fn.attachContext(v.curFrame.ctx)
			}''', 1)

# 6. OpCall frame bytecode/ctx
s = s.replace('''				v.curFrame.fn = callee
				v.curFrame.freeVars = callee.Free
				v.curFrame.basePointer = v.sp - numArgs
				v.curInsts = callee.Instructions''', '''				v.curFrame.fn = callee
				v.curFrame.freeVars = callee.Free
				v.curFrame.basePointer = v.sp - numArgs
				if callee.ctx != nil {
					v.curFrame.bytecode = callee.ctx.bytecode
					v.curFrame.ctx = callee.ctx
				} else {
					v.curFrame.bytecode = v.bytecode
					v.curFrame.ctx = v.ctx
				}
				v.curInsts = callee.Instructions''', 1)

# 7. OpClosure use curFrame bytecode
s = s.replace('''			fn, ok := v.constants[constIndex].(*CompiledFunction)''', '''			fn, ok := v.curFrame.bytecode.Constants[constIndex].(*CompiledFunction)''', 1)

# 8. OpClosure ctx
s = s.replace('''				Free:          free,
				ctx:           v.ctx,
			}''', '''				Free:          free,
				ctx:           v.curFrame.ctx,
			}''', 1)

open(p,'w').write(s)
print("done")
PYEOF
gofmt -w vm.go && go build ./... 2>&1 | head -30