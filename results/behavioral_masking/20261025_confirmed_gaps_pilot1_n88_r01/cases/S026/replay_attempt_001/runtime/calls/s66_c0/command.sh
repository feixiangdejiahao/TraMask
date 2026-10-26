cd /app && python3 - <<'PY'
# positive
p='checkers/testdata/brokenDocLink/positive_tests.go'
s=open(p).read()
s=s.replace('''import (
	"strings"
	str "strings"
)
''', '''import (
	"strings"
	str "strings"

	"github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg"
)
''')
s=s.replace('''var (
	_ = strings.ToUpper
	_ = str.ToUpper
)
''', '''var (
	_ = strings.ToUpper
	_ = str.ToUpper
	_ = examplepkg.StructType{}
)
''')
s=s.replace('''// PackageOnlyNotImported is an example.
/*! [missingpkg]: package "missingpkg" is not imported */
func PackageOnlyNotImported() {}
''', '''// PackageOnlyNotImported is an example.
/*! [missingpkg]: package "missingpkg" is not imported */
func PackageOnlyNotImported() {}

// PathQualifiedMissing is an example.
/*! [github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg.Missing]: "Missing" not found in package "github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg" */
func PathQualifiedMissing() {}

// PathTypeNotFound is an example.
/*! [github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg.MissingType.Field]: type "MissingType" not found in package "github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg" */
func PathTypeNotFound() {}
''')
open(p,'w').write(s)

# negative
p='checkers/testdata/brokenDocLink/negative_tests.go'
s=open(p).read()
s=s.replace('''import (
	"fmt"
	"strings"
	str "strings"
	. "strings"
)
''', '''import (
	"fmt"
	"strings"
	str "strings"
	. "strings"

	"github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg"
)
''')
s=s.replace('''var (
	_ = fmt.Println
	_ = strings.ToUpper
	_ = str.ToUpper
	_ = ToUpper
)
''', '''var (
	_ = fmt.Println
	_ = strings.ToUpper
	_ = str.ToUpper
	_ = ToUpper
	_ = examplepkg.StructType{}
)
''')
s=s.replace('''// Content with spaces or non-identifier characters is not a link:
// [foo bar], [foo-bar], [fmt.println], [Foo.Bar Baz].
func ValidNonLinks() {}
''', '''// Content with spaces or non-identifier characters is not a link:
// [foo bar], [foo-bar], [fmt.println], [Foo.Bar Baz].
func ValidNonLinks() {}

// [github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg.StructType]
// and [github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg.StructType.A]
// are valid package path references.
func ValidPathRefs() {}

// [*MyType] and [*MyType.Y] are valid pointer style links.
func ValidPointerRefs() {}

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
''')
open(p,'w').write(s)
PY
gofmt -w checkers/testdata/brokenDocLink/positive_tests.go checkers/testdata/brokenDocLink/negative_tests.go && go test ./checkers/ -run 'TestCheckers/brokenDocLink' -count=1 2>&1 | head -80