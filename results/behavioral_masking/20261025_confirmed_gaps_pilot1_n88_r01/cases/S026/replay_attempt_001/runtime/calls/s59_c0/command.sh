cd /app && python3 - <<'PY'
# positive
p='checkers/testdata/brokenDocLink/positive_tests.go'
s=open(p).read()
s=s.replace('''import (
	"strings"
	str "strings"
)

type Stringer struct{}

func (Stringer) String() string { return "" }

var myVar int
''', '''import (
	"strings"
	str "strings"
)

var (
	_ = strings.ToUpper
	_ = str.ToUpper
)

type Stringer struct{}

func (Stringer) String() string { return "" }

var myVar int
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
)

var (
	_ = fmt.Println
	_ = strings.ToUpper
	_ = str.ToUpper
	_ = ToUpper
)
''')
open(p,'w').write(s)
PY
go test ./checkers/ -run 'TestCheckers/brokenDocLink' -count=1 2>&1 | head -80