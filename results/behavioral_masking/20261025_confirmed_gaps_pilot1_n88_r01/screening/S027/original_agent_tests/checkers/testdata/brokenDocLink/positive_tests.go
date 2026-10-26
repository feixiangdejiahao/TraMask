package checker_test

// MissingLocal references [Missing].
/*! [Missing]: unknown symbol "Missing" in current package */
type MissingLocal struct{}

// NoSuchTypeMember references [NoSuchType.Method].
/*! [NoSuchType.Method]: type "NoSuchType" not found in current package */
type NoSuchTypeMember struct{}

// NotTypeMember references [NotType.Method].
/*! [NotType.Method]: "NotType" is not a type */
const NotType = 1

// LocalMemberMissing references [LocalT.Missing].
/*! [LocalT.Missing]: type "LocalT" has no method or field "Missing" */
type LocalT struct{}

// PackageNotImported references [strings.Builder].
/*! [strings.Builder]: package "strings" is not imported */
type PackageNotImported struct{}

// PackageOnlyNotImported references [strings].
/*! [strings]: package "strings" is not imported */
type PackageOnlyNotImported struct{}

// FullPathNotImported references [net/http.Handler].
/*! [net/http.Handler]: package "net/http" is not imported */
type FullPathNotImported struct{}

// AliasNotImported references [somealias.Foo].
/*! [somealias.Foo]: package "somealias" is not imported */
type AliasNotImported struct{}

// MultipleMissing references [MissingOne] and [MissingTwo].
/*! [MissingOne]: unknown symbol "MissingOne" in current package */
/*! [MissingTwo]: unknown symbol "MissingTwo" in current package */
type MultipleMissing struct{}

// FuncDoc references [MissingFunc].
/*! [MissingFunc]: unknown symbol "MissingFunc" in current package */
func FuncDoc() {}

var (
	// VarDoc references [MissingVar].
	/*! [MissingVar]: unknown symbol "MissingVar" in current package */
	VarDoc = 1
)

type FieldDoc struct {
	// FieldDocField references [MissingField].
	/*! [MissingField]: unknown symbol "MissingField" in current package */
	Field int
}
