cd /app && mkdir -p checkers/testdata/brokenDocLink && cat > checkers/testdata/brokenDocLink/positive_tests.go <<'EOF'
package checker_test

import (
	"strings"
	str "strings"
)

type Stringer struct{}

func (Stringer) String() string { return "" }

var myVar int

// LocalSymbol is an example.
/*! [MissingSymbol]: unknown symbol "MissingSymbol" in current package */
func LocalSymbol() {}

// QualifiedSymbol is an example.
/*! [strings.Missing]: "Missing" not found in package "strings" */
func QualifiedSymbol() {}

// RenamedImport is an example.
/*! [str.Missing]: "Missing" not found in package "str" */
func RenamedImport() {}

// LocalTypeMissing is an example.
/*! [MissingType.Field]: type "MissingType" not found in current package */
func LocalTypeMissing() {}

// QualifiedTypeMissing is an example.
/*! [strings.MissingType.Field]: type "MissingType" not found in package "strings" */
func QualifiedTypeMissing() {}

// LocalMemberMissing is an example.
/*! [Stringer.Missing]: type "Stringer" has no method or field "Missing" */
func LocalMemberMissing() {}

// QualifiedMemberMissing is an example.
/*! [strings.Builder.Missing]: type "Builder" has no method or field "Missing" */
func QualifiedMemberMissing() {}

// NonTypeLocal is an example.
/*! [myVar.Field]: "myVar" is not a type */
func NonTypeLocal() {}

// NonTypeQualified is an example.
/*! [strings.ToUpper.Field]: "ToUpper" is not a type */
func NonTypeQualified() {}

// PackageNotImported is an example.
/*! [missingpkg.Foo]: package "missingpkg" is not imported */
func PackageNotImported() {}

// PackageOnlyNotImported is an example.
/*! [missingpkg]: package "missingpkg" is not imported */
func PackageOnlyNotImported() {}
EOF
cat > checkers/testdata/brokenDocLink/negative_tests.go <<'EOF'
package checker_test

import (
	"fmt"
	"strings"
	str "strings"
	. "strings"
)

type Base struct{ X int }

func (Base) M() {}

type Embedded struct{ Base }

type MyType struct {
	Embedded
	Y int
}

func (MyType) N() {}

// Valid local symbol references.
/*! This is not a link. */
func ValidLocal() {}

// [MyType] is a type, [MyType.Y] is a field and [MyType.N] is a method.
func ValidMembers() {}

// [Embedded.X] and [Embedded.M] are promoted members.
func ValidEmbedded() {}

// [fmt.Println], [strings.Builder] and [str.ToUpper] are valid qualified refs.
func ValidQualified() {}

// [ToUpper] is available via the dot import.
func ValidDotImport() {}

// Go builtins are not flagged: [int], [string], [len], [error], [any].
func ValidBuiltins() {}

// Content with spaces or non-identifier characters is not a link:
// [foo bar], [foo-bar], [fmt.println], [Foo.Bar Baz].
func ValidNonLinks() {}
EOF
echo created && ls -la checkers/testdata/brokenDocLink/