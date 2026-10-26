cd /app && git add objects.go script.go vm.go compiled_function_call_test.go && git commit -m "Implement Go-side calls for compiled functions and closures

CompiledFunction.Call now executes script-defined functions and closures
from Go with the same globals, imports, closure captures, variadic
behavior, recursion and runtime error formatting as in-VM calls. Callable
values are bound to the execution context of the compiled instance they
came from, and transferring values between instances (Set, Clone, Add)
rebinds globals to the destination while snapshotting closure captures so
state stays isolated. Rebinding is applied recursively to every callable
reachable inside arrays, maps and closure captures." && git log --oneline -3