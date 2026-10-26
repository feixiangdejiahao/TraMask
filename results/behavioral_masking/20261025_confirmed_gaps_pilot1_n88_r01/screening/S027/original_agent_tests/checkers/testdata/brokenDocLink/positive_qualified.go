package checker_test

import (
	"fmt"
	mymath "math"
)

var (
	_ = fmt.Println
	_ = mymath.Pi
)

// QualifiedSymbolMissing references [fmt.Nope].
/*! [fmt.Nope]: "Nope" not found in package "fmt" */
type QualifiedSymbolMissing struct{}

// QualifiedTypeMissing references [fmt.NoSuchType.Method].
/*! [fmt.NoSuchType.Method]: type "NoSuchType" not found in package "fmt" */
type QualifiedTypeMissing struct{}

// QualifiedNotType references [fmt.Println.Method].
/*! [fmt.Println.Method]: "Println" is not a type */
type QualifiedNotType struct{}

// QualifiedMemberMissing references [fmt.Stringer.Missing].
/*! [fmt.Stringer.Missing]: type "Stringer" has no method or field "Missing" */
type QualifiedMemberMissing struct{}

// RenamedSymbolMissing references [mymath.Nope].
/*! [mymath.Nope]: "Nope" not found in package "mymath" */
type RenamedSymbolMissing struct{}

// RenamedTypeMissing references [mymath.NoType.Method].
/*! [mymath.NoType.Method]: type "NoType" not found in package "mymath" */
type RenamedTypeMissing struct{}
