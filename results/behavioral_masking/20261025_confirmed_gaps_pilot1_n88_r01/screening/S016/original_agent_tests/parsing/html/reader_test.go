package html_test

import (
	"testing"

	"github.com/tomwright/dasel/v3/parsing"
	"github.com/tomwright/dasel/v3/parsing/html"
	"github.com/tomwright/dasel/v3/parsing/json"
)

func readAsJSON(t *testing.T, input string, structured bool) string {
	t.Helper()
	opts := parsing.DefaultReaderOptions()
	if structured {
		opts.Ext = map[string]string{"html-mode": "structured"}
	}
	r, err := html.HTML.NewReader(opts)
	if err != nil {
		t.Fatalf("unexpected error creating reader: %s", err)
	}
	w, err := json.JSON.NewWriter(parsing.DefaultWriterOptions())
	if err != nil {
		t.Fatalf("unexpected error creating json writer: %s", err)
	}
	value, err := r.Read([]byte(input))
	if err != nil {
		t.Fatalf("unexpected error reading HTML: %s", err)
	}
	out, err := w.Write(value)
	if err != nil {
		t.Fatalf("unexpected error writing JSON: %s", err)
	}
	return string(out)
}

func assertJSON(t *testing.T, input, expected string) {
	t.Helper()
	got := readAsJSON(t, input, false)
	if got != expected {
		t.Fatalf("Expected JSON:\n%s\nGot:\n%s", expected, got)
	}
}

func TestHtmlReader_Read(t *testing.T) {
	t.Run("full document", func(t *testing.T) {
		assertJSON(t,
			`<html><head><title>Test</title></head><body><p>Hello</p></body></html>`,
			`{
    "head": {
        "title": "Test"
    },
    "body": {
        "p": "Hello"
    }
}
`)
	})

	t.Run("normalizes missing head and body", func(t *testing.T) {
		assertJSON(t,
			`<p>Hello</p>`,
			`{
    "head": "",
    "body": {
        "p": "Hello"
    }
}
`)
	})

	t.Run("orphan content goes into body", func(t *testing.T) {
		assertJSON(t,
			`some text`,
			`{
    "head": "",
    "body": "some text"
}
`)
	})

	t.Run("lowercases tags and attributes", func(t *testing.T) {
		assertJSON(t,
			`<DIV CLASS="X" ID="Y">TEXT</DIV>`,
			`{
    "head": "",
    "body": {
        "div": {
            "-class": "X",
            "-id": "Y",
            "#text": "TEXT"
        }
    }
}
`)
	})

	t.Run("same tag siblings become a slice", func(t *testing.T) {
		assertJSON(t,
			`<div><p>one</p><p>two</p></div>`,
			`{
    "head": "",
    "body": {
        "div": {
            "p": [
                "one",
                "two"
            ]
        }
    }
}
`)
	})

	t.Run("implicitly closes p on block elements", func(t *testing.T) {
		assertJSON(t,
			`<p>one<div>two</div>three</p>`,
			`{
    "head": "",
    "body": {
        "#text": "three",
        "p": "one",
        "div": "two"
    }
}
`)
	})

	t.Run("implicitly closes li", func(t *testing.T) {
		assertJSON(t,
			`<ul><li>one<li>two</ul>`,
			`{
    "head": "",
    "body": {
        "ul": {
            "li": [
                "one",
                "two"
            ]
        }
    }
}
`)
	})

	t.Run("implicitly closes td and tr", func(t *testing.T) {
		assertJSON(t,
			`<table><tr><td>a<td>b<tr><td>c</table>`,
			`{
    "head": "",
    "body": {
        "table": {
            "tr": [
                {
                    "td": [
                        "a",
                        "b"
                    ]
                },
                {
                    "td": "c"
                }
            ]
        }
    }
}
`)
	})

	t.Run("dt and dd close each other", func(t *testing.T) {
		assertJSON(t,
			`<dl><dt>a<dd>b</dl>`,
			`{
    "head": "",
    "body": {
        "dl": {
            "dt": "a",
            "dd": "b"
        }
    }
}
`)
	})

	t.Run("decodes entities", func(t *testing.T) {
		assertJSON(t,
			`<p>a &amp; b &#65; &#x42; &lt;x&gt;</p>`,
			`{
    "head": "",
    "body": {
        "p": "a \u0026 b A B \u003cx\u003e"
    }
}
`)
	})

	t.Run("decodes entities in attributes", func(t *testing.T) {
		assertJSON(t,
			`<a href="?a=1&amp;b=2">x</a>`,
			`{
    "head": "",
    "body": {
        "a": {
            "-href": "?a=1\u0026b=2",
            "#text": "x"
        }
    }
}
`)
	})

	t.Run("void elements and boolean attributes", func(t *testing.T) {
		assertJSON(t,
			`<input disabled checked="yes"><br>`,
			`{
    "head": "",
    "body": {
        "input": {
            "-disabled": "",
            "-checked": "yes"
        },
        "br": ""
    }
}
`)
	})

	t.Run("raw text elements preserve content verbatim", func(t *testing.T) {
		assertJSON(t,
			`<script>if (a < b && c > d) { x = "&amp;"; }</script>`,
			`{
    "head": {
        "script": "if (a \u003c b \u0026\u0026 c \u003e d) { x = \"\u0026amp;\"; }"
    }
}
`)
	})

	t.Run("comments and doctype ignored", func(t *testing.T) {
		assertJSON(t,
			`<!-- comment --><!DOCTYPE html><html><head><title>x</title></head><body><div>y</div></body></html>`,
			`{
    "head": {
        "title": "x"
    },
    "body": {
        "div": "y"
    }
}
`)
	})

	t.Run("whitespace is trimmed", func(t *testing.T) {
		assertJSON(t,
			`<p>  hello  </p>`,
			`{
    "head": "",
    "body": {
        "p": "hello"
    }
}
`)
	})
}

func TestHtmlReader_StructuredMode(t *testing.T) {
	got := readAsJSON(t,
		`<html lang="en"><head><title>T</title></head><body><p class="x">Hi</p></body></html>`,
		true,
	)
	expected := `{
    "tag": "html",
    "attrs": {
        "lang": "en"
    },
    "text": "",
    "children": [
        {
            "tag": "head",
            "attrs": {},
            "text": "",
            "children": [
                {
                    "tag": "title",
                    "attrs": {},
                    "text": "T",
                    "children": []
                }
            ]
        },
        {
            "tag": "body",
            "attrs": {},
            "text": "",
            "children": [
                {
                    "tag": "p",
                    "attrs": {
                        "class": "x"
                    },
                    "text": "Hi",
                    "children": []
                }
            ]
        }
    ]
}
`
	if got != expected {
		t.Fatalf("Expected JSON:\n%s\nGot:\n%s", expected, got)
	}
}
