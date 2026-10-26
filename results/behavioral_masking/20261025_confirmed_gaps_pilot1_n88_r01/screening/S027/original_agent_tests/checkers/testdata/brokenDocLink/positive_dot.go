package checker_test

import . "strings"

var _ = Builder{}

// DotUnknown references [MissingDot].
/*! [MissingDot]: unknown symbol "MissingDot" in current package */
type DotUnknown struct{}

// DotMemberMissing references [Builder.Missing].
/*! [Builder.Missing]: type "Builder" has no method or field "Missing" */
type DotMemberMissing struct{}

// DotPkgNotImported references [strings.Builder].
/*! [strings.Builder]: package "strings" is not imported */
type DotPkgNotImported struct{}
