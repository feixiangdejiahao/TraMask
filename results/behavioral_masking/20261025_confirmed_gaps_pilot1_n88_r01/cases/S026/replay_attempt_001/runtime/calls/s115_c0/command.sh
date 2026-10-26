cd /app && python3 - <<'PY'
p='checkers/brokenDocLink_checker.go'
s=open(p).read()
s=s.replace('''func hasMethod(typ types.Type, name string) bool {
	methodSet := types.NewMethodSet(typ)
	for i := 0; i < methodSet.Len(); i++ {
		if methodSet.At(i).Obj().Name() == name {
			return true
		}
	}
	return false
}
''', '''func hasMethod(typ types.Type, name string) bool {
	// Directly declared methods, including methods with a pointer receiver.
	if named, ok := typ.(*types.Named); ok {
		for i := 0; i < named.NumMethods(); i++ {
			if named.Method(i).Name() == name {
				return true
			}
		}
	}
	// Promoted methods, both through the value and the pointer method sets.
	if methodInSet(types.NewMethodSet(typ), name) {
		return true
	}
	if _, isPtr := typ.(*types.Pointer); !isPtr {
		return methodInSet(types.NewMethodSet(types.NewPointer(typ)), name)
	}
	return false
}

func methodInSet(methodSet *types.MethodSet, name string) bool {
	for i := 0; i < methodSet.Len(); i++ {
		if methodSet.At(i).Obj().Name() == name {
			return true
		}
	}
	return false
}
''')
open(p,'w').write(s)
PY
gofmt -w checkers/brokenDocLink_checker.go && go test ./checkers/ -run 'TestCheckers/brokenDocLink' -count=1 2>&1 | tail -10