cd /app && python3 - <<'PY'
# positive
p='checkers/testdata/brokenDocLink/positive_tests.go'
s=open(p).read()
s=s.replace('''import (
	"strings"
	str "strings"

	"github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg"
)
''', '''import (
	"strings"
	str "strings"
	. "sort"

	"github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg"
)
''')
s=s.replace('''var (
	_ = strings.ToUpper
	_ = str.ToUpper
	_ = examplepkg.StructType{}
)
''', '''var (
	_ = strings.ToUpper
	_ = str.ToUpper
	_ = IntSlice(nil)
	_ = examplepkg.StructType{}
)
''')
s=s.replace('''// PathTypeNotFound is an example.
/*! [github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg.MissingType.Field]: type "MissingType" not found in package "github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg" */
func PathTypeNotFound() {}
''', '''// PathTypeNotFound is an example.
/*! [github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg.MissingType.Field]: type "MissingType" not found in package "github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg" */
func PathTypeNotFound() {}

// DotTypeMemberMissing is an example.
/*! [IntSlice.Missing]: type "IntSlice" has no method or field "Missing" */
func DotTypeMemberMissing() {}
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

	"github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg"
)
''', '''import (
	"fmt"
	"strings"
	str "strings"
	. "sort"
	. "strings"

	"github.com/go-critic/go-critic/checkers/testdata/_importable/examplepkg"
)
''')
s=s.replace('''var (
	_ = fmt.Println
	_ = strings.ToUpper
	_ = str.ToUpper
	_ = ToUpper
	_ = examplepkg.StructType{}
)
''', '''var (
	_ = fmt.Println
	_ = strings.ToUpper
	_ = str.ToUpper
	_ = ToUpper
	_ = IntSlice(nil)
	_ = examplepkg.StructType{}
)
''')
s=s.replace('''// [*MyType] and [*MyType.Y] are valid pointer style links.
func ValidPointerRefs() {}
''', '''// [*MyType] and [*MyType.Y] are valid pointer style links.
func ValidPointerRefs() {}

// [IntSlice.Sort] is a valid method reference on a dot-imported type.
func ValidDotTypeMethod() {}
''')
open(p,'w').write(s)
PY
gofmt -w checkers/testdata/brokenDocLink/positive_tests.go checkers/testdata/brokenDocLink/negative_tests.go && go test ./checkers/ -run 'TestCheckers/brokenDocLink' -count=1 2>&1 | head -60