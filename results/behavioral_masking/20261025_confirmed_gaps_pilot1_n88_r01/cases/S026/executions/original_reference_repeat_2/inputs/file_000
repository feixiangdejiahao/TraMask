package checker_test

import (
	"fmt"
	. "sort"
	"strings"
	. "strings"
	str "strings"

	"github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg"
)

var (
	_ = fmt.Println
	_ = strings.ToUpper
	_ = str.ToUpper
	_ = ToUpper
	_ = IntSlice(nil)
	_ = examplepkg.StructType{}
)

// [MyType] is a valid local symbol reference.
func ValidLocal() {}

// [MyType] is a type, [MyType.Y] is a field and [MyType.N] is a method.
func ValidMembers() {}

// [Embedded.X], [Embedded.M] and [PtrEmbed.X] are promoted members.
func ValidEmbedded() {}

// [fmt.Println], [strings.Builder], [strings.Builder.Reset],
// [strings.Reader.Read], [strings.Reader.Len] and [str.ToUpper] are valid.
func ValidQualified() {}

// [ToUpper] is available via the dot import.
func ValidDotImport() {}

// Go builtins are not flagged: [int], [string], [len], [error], [any].
func ValidBuiltins() {}

// Standard library package links are valid even without an import:
// [math] and [math.Sin].
func ValidStdlibRefs() {}

// Content with spaces or non-identifier characters is not a link:
// [foo bar], [foo-bar], [fmt.println], [Foo.Bar Baz].
func ValidNonLinks() {}

// [github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg.StructType]
// and [github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg.StructType.A]
// are valid package path references.
func ValidPathRefs() {}

// [checker_test.MyType] and [checker_test] are valid self package references.
func ValidSelfRefs() {}

// [*MyType] and [*MyType.Y] are valid pointer style links.
func ValidPointerRefs() {}

// [IntSlice.Sort] is a valid method reference on a dot-imported type.
func ValidDotTypeMethod() {}

// [Box.Put] is a valid pointer-receiver method on a generic type.
func ValidGenericMethod() {}

// [AliasType.Y] and [AliasType.N] are valid members of a type alias.
func ValidAlias() {}

// [MyType] is a valid reference in a type declaration comment.
type DocumentedType struct{}

type (
	// [MyType] is a valid reference in a type group comment.
	DocumentedGroupType struct{}
)

type WithFieldDocs struct {
	// [MyType] is a valid reference in a field comment.
	Field int
}
