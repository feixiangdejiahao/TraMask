cd /app && python3 - <<'PY'
p='checkers/testdata/brokenDocLink/negative_tests.go'
s=open(p).read()
s=s.replace('''	"fmt"
	"strings"
	. "strings"
	str "strings"
''', '''	"fmt"
	"strings"
	. "sort"
	. "strings"
	str "strings"
''')
open(p,'w').write(s)
PY
gofmt -w checkers/testdata/brokenDocLink/negative_tests.go && sed -n '1,12p' checkers/testdata/brokenDocLink/negative_tests.go && go test ./checkers/ -run 'TestCheckers/brokenDocLink' -count=1 2>&1 | head -60