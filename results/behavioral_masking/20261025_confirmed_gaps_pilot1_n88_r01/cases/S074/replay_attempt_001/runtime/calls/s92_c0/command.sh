cd /app && python3 - <<'PYEOF'
p='vm.go'
s=open(p).read()

# Remove unused constants field from VM
s=s.replace('''type VM struct {
	constants    []Object
	bytecode     *Bytecode''', '''type VM struct {
	bytecode     *Bytecode''', 1)
s=s.replace('''	v := &VM{
		constants:   bytecode.Constants,
		bytecode:    bytecode,''', '''	v := &VM{
		bytecode:    bytecode,''', 1)

# Reset stopOnReturn in Run
s=s.replace('''func (v *VM) Run() (err error) {
	// reset VM states
	v.sp = 0''', '''func (v *VM) Run() (err error) {
	// reset VM states
	v.sp = 0
	v.stopOnReturn = false
	v.returnValue = UndefinedValue''', 1)

# Reset err in runFunction
s=s.replace('''func (v *VM) runFunction(fn *CompiledFunction, args []Object) (
	Object, error) {
	v.stopOnReturn = true''', '''func (v *VM) runFunction(fn *CompiledFunction, args []Object) (
	Object, error) {
	v.err = nil
	v.stopOnReturn = true''', 1)

open(p,'w').write(s)

p='objects.go'
s=open(p).read()
# bindContext nil p guard
s=s.replace('''	for i, p := range o.Free {
		if p != nil {
			val := *p.Value
			free[i] = &ObjectPtr{Value: &val}
		}
	}''', '''	for i, p := range o.Free {
		if p != nil && p.Value != nil {
			val := *p.Value
			free[i] = &ObjectPtr{Value: &val}
		}
	}''', 1)
# bindObject nil guard
s=s.replace('''func bindObject(o Object, ctx *functionContext) Object {
	switch o := o.(type) {''', '''func bindObject(o Object, ctx *functionContext) Object {
	if o == nil {
		return nil
	}
	switch o := o.(type) {''', 1)
# Error nil guard
s=s.replace('''	case *Error:
		return &Error{Value: bindObject(o.Value, ctx)}''', '''	case *Error:
		val := bindObject(o.Value, ctx)
		return &Error{Value: val}''', 1)
open(p,'w').write(s)
print("done")
PYEOF
gofmt -w vm.go objects.go && go build ./... && go test ./... 2>&1 | tail -15