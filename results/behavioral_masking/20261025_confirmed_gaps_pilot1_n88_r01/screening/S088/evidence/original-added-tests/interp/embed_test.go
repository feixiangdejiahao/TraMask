package interp_test

import (
	"bytes"
	"io/fs"
	"testing"
	"testing/fstest"

	"github.com/traefik/yaegi/interp"
	"github.com/traefik/yaegi/stdlib"
)

func runEmbed(t *testing.T, fsys fs.FS) (string, error) {
	t.Helper()
	var stdout bytes.Buffer
	i := interp.New(interp.Options{SourcecodeFilesystem: fsys, Stdout: &stdout})
	if err := i.Use(stdlib.Symbols); err != nil {
		t.Fatal(err)
	}
	_, err := i.EvalPath("main.go")
	return stdout.String(), err
}

func TestEmbedString(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import (
	_ "embed"
	"fmt"
)
//go:embed hello.txt
var s string
func main() { fmt.Println(s) }
`)},
		"hello.txt": &fstest.MapFile{Data: []byte("hello world")},
	}
	out, err := runEmbed(t, fsys)
	if err != nil {
		t.Fatal(err)
	}
	if out != "hello world\n" {
		t.Fatalf("got %q", out)
	}
}

func TestEmbedBytes(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import (
	_ "embed"
	"fmt"
)
//go:embed hello.txt
var b []byte
func main() { fmt.Println(string(b)) }
`)},
		"hello.txt": &fstest.MapFile{Data: []byte("hello bytes")},
	}
	out, err := runEmbed(t, fsys)
	if err != nil {
		t.Fatal(err)
	}
	if out != "hello bytes\n" {
		t.Fatalf("got %q", out)
	}
}

func TestEmbedFS(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import (
	"embed"
	"fmt"
	"io/fs"
)
//go:embed data
var content embed.FS
func main() {
	b, err := content.ReadFile("data/a.txt")
	if err != nil { fmt.Println("ERR", err); return }
	fmt.Println(string(b))
	entries, _ := fs.ReadDir(content, "data")
	fmt.Println(len(entries), entries[0].Name())
	var _ fs.FS = content
	var _ fs.ReadFileFS = content
	var _ fs.ReadDirFS = content
}
`)},
		"data/a.txt":     &fstest.MapFile{Data: []byte("A")},
		"data/b.txt":     &fstest.MapFile{Data: []byte("B")},
		"data/sub/c.txt": &fstest.MapFile{Data: []byte("C")},
	}
	out, err := runEmbed(t, fsys)
	if err != nil {
		t.Fatal(err)
	}
	if out != "A\n3 a.txt\n" {
		t.Fatalf("got %q", out)
	}
}

func TestEmbedGrouped(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import (
	_ "embed"
	"fmt"
)
var (
	//go:embed a.txt
	x string
	//go:embed b.txt
	y string
)
func main() { fmt.Println(x, y) }
`)},
		"a.txt": &fstest.MapFile{Data: []byte("A")},
		"b.txt": &fstest.MapFile{Data: []byte("B")},
	}
	out, err := runEmbed(t, fsys)
	if err != nil {
		t.Fatal(err)
	}
	if out != "A B\n" {
		t.Fatalf("got %q", out)
	}
}

func TestEmbedDirAndHidden(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import (
	"embed"
	"fmt"
)
//go:embed all:data
var content embed.FS
func main() {
	entries, _ := content.ReadDir("data")
	fmt.Println(len(entries), entries[0].Name())
	b, err := content.ReadFile("data/.hidden")
	if err == nil { fmt.Println("hidden", string(b)) } else { fmt.Println("hidden ERR") }
}
`)},
		"data/a.txt":   &fstest.MapFile{Data: []byte("A")},
		"data/.hidden": &fstest.MapFile{Data: []byte("H")},
	}
	out, err := runEmbed(t, fsys)
	if err != nil {
		t.Fatal(err)
	}
	if out != "2 .hidden\nhidden H\n" {
		t.Fatalf("got %q", out)
	}
}

func TestEmbedErrors(t *testing.T) {
	tests := []struct {
		name    string
		files   map[string]string
		wantErr string
	}{
		{
			name: "no files",
			files: map[string]string{
				"main.go": `package main
import _ "embed"
//go:embed missing.txt
var s string
func main() {}
`,
			},
			wantErr: "no files",
		},
		{
			name: "multiple files for string",
			files: map[string]string{
				"main.go": `package main
import _ "embed"
//go:embed data
var s string
func main() {}
`,
				"data/a.txt": "A",
				"data/b.txt": "B",
			},
			wantErr: "exactly one file",
		},
		{
			name: "initializer",
			files: map[string]string{
				"main.go": `package main
import _ "embed"
//go:embed a.txt
var s = "x"
func main() {}
`,
				"a.txt": "A",
			},
			wantErr: "initializer",
		},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			fsys := fstest.MapFS{}
			for k, v := range tc.files {
				fsys[k] = &fstest.MapFile{Data: []byte(v)}
			}
			_, err := runEmbed(t, fsys)
			if err == nil || !bytes.Contains([]byte(err.Error()), []byte(tc.wantErr)) {
				t.Fatalf("got err %v, want containing %q", err, tc.wantErr)
			}
		})
	}
}

func TestEmbedNotOverwritten(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import (
	_ "embed"
	"fmt"
)
//go:embed a.txt
var s string
var copy = s
func main() { fmt.Println(s, copy) }
`)},
		"a.txt": &fstest.MapFile{Data: []byte("AA")},
	}
	out, err := runEmbed(t, fsys)
	if err != nil {
		t.Fatal(err)
	}
	if out != "AA AA\n" {
		t.Fatalf("got %q", out)
	}
}

func TestEmbedMultipleLines(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import (
	"embed"
	"fmt"
)
//go:embed a.txt
//go:embed b.txt
var f embed.FS
func main() {
	a, _ := f.ReadFile("a.txt")
	b, _ := f.ReadFile("b.txt")
	fmt.Println(string(a), string(b))
}
`)},
		"a.txt": &fstest.MapFile{Data: []byte("A")},
		"b.txt": &fstest.MapFile{Data: []byte("B")},
	}
	out, err := runEmbed(t, fsys)
	if err != nil {
		t.Fatal(err)
	}
	if out != "A B\n" {
		t.Fatalf("got %q", out)
	}
}

func TestEmbedSubdirSource(t *testing.T) {
	fsys := fstest.MapFS{
		"pkg/main.go": &fstest.MapFile{Data: []byte(`package main
import (
	_ "embed"
	"fmt"
)
//go:embed data.txt
var s string
func main() { fmt.Println(s) }
`)},
		"pkg/data.txt": &fstest.MapFile{Data: []byte("subdir data")},
	}
	var stdout bytes.Buffer
	i := interp.New(interp.Options{SourcecodeFilesystem: fsys, Stdout: &stdout})
	if err := i.Use(stdlib.Symbols); err != nil {
		t.Fatal(err)
	}
	_, err := i.EvalPath("pkg/main.go")
	if err != nil {
		t.Fatal(err)
	}
	if stdout.String() != "subdir data\n" {
		t.Fatalf("got %q", stdout.String())
	}
}

func TestEmbedReadFileCopy(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import (
	"embed"
	"fmt"
)
//go:embed a.txt
var f embed.FS
func main() {
	b1, _ := f.ReadFile("a.txt")
	b2, _ := f.ReadFile("a.txt")
	b1[0] = 'X'
	b3, _ := f.ReadFile("a.txt")
	fmt.Println(string(b2), string(b3))
}
`)},
		"a.txt": &fstest.MapFile{Data: []byte("abc")},
	}
	out, err := runEmbed(t, fsys)
	if err != nil {
		t.Fatal(err)
	}
	if out != "abc abc\n" {
		t.Fatalf("got %q", out)
	}
}

func TestEmbedReadDirFile(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import (
	"embed"
	"fmt"
	"io/fs"
)
//go:embed data
var f embed.FS
func main() {
	d, err := f.Open("data")
	if err != nil { fmt.Println("ERR", err); return }
	rd, ok := d.(fs.ReadDirFile)
	if !ok { fmt.Println("not ReadDirFile"); return }
	entries, err := rd.ReadDir(-1)
	if err != nil { fmt.Println("ERR2", err); return }
	fmt.Println(len(entries), entries[0].Name())
}
`)},
		"data/a.txt": &fstest.MapFile{Data: []byte("A")},
		"data/b.txt": &fstest.MapFile{Data: []byte("B")},
	}
	out, err := runEmbed(t, fsys)
	if err != nil {
		t.Fatal(err)
	}
	if out != "2 a.txt\n" {
		t.Fatalf("got %q", out)
	}
}

func TestEmbedRootReadDir(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import (
	"embed"
	"fmt"
	"io/fs"
)
//go:embed a.txt
var f embed.FS
func main() {
	entries, err := fs.ReadDir(f, ".")
	if err != nil { fmt.Println("ERR", err); return }
	fmt.Println(len(entries), entries[0].Name())
}
`)},
		"a.txt": &fstest.MapFile{Data: []byte("A")},
	}
	out, err := runEmbed(t, fsys)
	if err != nil {
		t.Fatal(err)
	}
	if out != "1 a.txt\n" {
		t.Fatalf("got %q", out)
	}
}

func TestEmbedPatternTopLevelOnly(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import (
	"embed"
	"fmt"
	"io/fs"
)
//go:embed *.txt
var f embed.FS
func main() {
	entries, _ := fs.ReadDir(f, ".")
	fmt.Println(len(entries))
	_, err := f.ReadFile("sub/x.txt")
	if err == nil { fmt.Println("ERR") } else { fmt.Println("not included") }
}
`)},
		"a.txt":     &fstest.MapFile{Data: []byte("A")},
		"sub/x.txt": &fstest.MapFile{Data: []byte("X")},
	}
	out, err := runEmbed(t, fsys)
	if err != nil {
		t.Fatal(err)
	}
	if out != "1\nnot included\n" {
		t.Fatalf("got %q", out)
	}
}

func TestEmbedStringMultipleCompileError(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import _ "embed"
//go:embed data
var s string
func main() {}
`)},
		"data/a.txt": &fstest.MapFile{Data: []byte("A")},
		"data/b.txt": &fstest.MapFile{Data: []byte("B")},
	}
	_, err := runEmbed(t, fsys)
	if err == nil || !bytes.Contains([]byte(err.Error()), []byte("exactly one file")) {
		t.Fatalf("got err %v, want exactly one file", err)
	}
}

func TestEmbedInitFunction(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import (
	_ "embed"
	"fmt"
)
//go:embed a.txt
var s string
func init() { fmt.Println("init", s) }
func main() { fmt.Println("main", s) }
`)},
		"a.txt": &fstest.MapFile{Data: []byte("AA")},
	}
	out, err := runEmbed(t, fsys)
	if err != nil {
		t.Fatal(err)
	}
	if out != "init AA\nmain AA\n" {
		t.Fatalf("got %q", out)
	}
}

func TestEmbedImportedPackage(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import (
	"fmt"
	"./mypkg"
)
func main() { fmt.Println(mypkg.Get()) }
`)},
		"mypkg/mypkg.go": &fstest.MapFile{Data: []byte(`package mypkg
import _ "embed"
//go:embed data.txt
var S string
func Get() string { return S }
`)},
		"mypkg/data.txt": &fstest.MapFile{Data: []byte("from pkg")},
	}
	var stdout bytes.Buffer
	i := interp.New(interp.Options{SourcecodeFilesystem: fsys, GoPath: ".", Stdout: &stdout})
	if err := i.Use(stdlib.Symbols); err != nil {
		t.Fatal(err)
	}
	_, err := i.EvalPath("main.go")
	if err != nil {
		t.Fatal(err)
	}
	if stdout.String() != "from pkg\n" {
		t.Fatalf("got %q", stdout.String())
	}
}

func TestEmbedOverlappingPatterns(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import (
	"embed"
	"fmt"
)
//go:embed data
//go:embed data/a.txt
var f embed.FS
func main() {
	b, _ := f.ReadFile("data/a.txt")
	fmt.Println(string(b))
}
`)},
		"data/a.txt": &fstest.MapFile{Data: []byte("A")},
	}
	out, err := runEmbed(t, fsys)
	if err != nil {
		t.Fatal(err)
	}
	if out != "A\n" {
		t.Fatalf("got %q", out)
	}
}

func TestEmbedEval(t *testing.T) {
	fsys := fstest.MapFS{
		"hello.txt": &fstest.MapFile{Data: []byte("eval data")},
	}
	var stdout bytes.Buffer
	i := interp.New(interp.Options{SourcecodeFilesystem: fsys, Stdout: &stdout})
	if err := i.Use(stdlib.Symbols); err != nil {
		t.Fatal(err)
	}
	_, err := i.Eval(`package main
import (
	_ "embed"
	"fmt"
)
//go:embed hello.txt
var s string
func main() { fmt.Println(s) }
`)
	if err != nil {
		t.Fatal(err)
	}
	if stdout.String() != "eval data\n" {
		t.Fatalf("got %q", stdout.String())
	}
}

func TestEmbedGroupedSingle(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import (
	_ "embed"
	"fmt"
)
//go:embed a.txt
var (
	x string
)
func main() { fmt.Println(x) }
`)},
		"a.txt": &fstest.MapFile{Data: []byte("A")},
	}
	out, err := runEmbed(t, fsys)
	if err != nil {
		t.Fatal(err)
	}
	if out != "A\n" {
		t.Fatalf("got %q", out)
	}
}

func TestEmbedLocalVarError(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import _ "embed"
func main() {
	//go:embed a.txt
	var s string
	_ = s
}
`)},
		"a.txt": &fstest.MapFile{Data: []byte("A")},
	}
	_, err := runEmbed(t, fsys)
	if err == nil || !bytes.Contains([]byte(err.Error()), []byte("local variable")) {
		t.Fatalf("got err %v, want local variable error", err)
	}
}

func TestEmbedGroupMultipleError(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import _ "embed"
//go:embed a.txt
var (
	x string
	y string
)
func main() { _ = x; _ = y }
`)},
		"a.txt": &fstest.MapFile{Data: []byte("A")},
	}
	_, err := runEmbed(t, fsys)
	if err == nil || !bytes.Contains([]byte(err.Error()), []byte("group of variables")) {
		t.Fatalf("got err %v, want group error", err)
	}
}

func TestEmbedQuotedPattern(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import (
	_ "embed"
	"fmt"
)
//go:embed "hello world.txt"
var s string
func main() { fmt.Println(s) }
`)},
		"hello world.txt": &fstest.MapFile{Data: []byte("spaced")},
	}
	out, err := runEmbed(t, fsys)
	if err != nil {
		t.Fatal(err)
	}
	if out != "spaced\n" {
		t.Fatalf("got %q", out)
	}
}

func TestEmbedHiddenExcluded(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import (
	"embed"
	"fmt"
	"io/fs"
)
//go:embed data
var f embed.FS
func main() {
	entries, _ := fs.ReadDir(f, "data")
	fmt.Println(len(entries))
	_, err := f.ReadFile("data/.hidden")
	if err == nil { fmt.Println("hidden included") } else { fmt.Println("hidden excluded") }
}
`)},
		"data/a.txt":   &fstest.MapFile{Data: []byte("A")},
		"data/.hidden": &fstest.MapFile{Data: []byte("H")},
	}
	out, err := runEmbed(t, fsys)
	if err != nil {
		t.Fatal(err)
	}
	if out != "1\nhidden excluded\n" {
		t.Fatalf("got %q", out)
	}
}

func TestEmbedFSZeroValue(t *testing.T) {
	fsys := fstest.MapFS{
		"main.go": &fstest.MapFile{Data: []byte(`package main
import (
	"embed"
	"fmt"
	"io/fs"
)
func main() {
	var f embed.FS
	entries, err := fs.ReadDir(f, ".")
	if err != nil { fmt.Println("ERR", err); return }
	fmt.Println(len(entries))
	_, err = f.ReadFile("x")
	if err == nil { fmt.Println("file exists") } else { fmt.Println("not exist") }
}
`)},
	}
	out, err := runEmbed(t, fsys)
	if err != nil {
		t.Fatal(err)
	}
	if out != "0\nnot exist\n" {
		t.Fatalf("got %q", out)
	}
}
