package html_test

import (
	"testing"

	"github.com/tomwright/dasel/v3/model"
	"github.com/tomwright/dasel/v3/parsing"
	"github.com/tomwright/dasel/v3/parsing/html"
)

func write(t *testing.T, v *model.Value, compact bool) string {
	t.Helper()
	options := parsing.DefaultWriterOptions()
	if compact {
		options = parsing.WriterOptions{Compact: true}
	}
	w, err := html.HTML.NewWriter(options)
	if err != nil {
		t.Fatalf("unexpected error: %s", err)
	}
	out, err := w.Write(v)
	if err != nil {
		t.Fatalf("unexpected error: %s", err)
	}
	return string(out)
}

func newMap() *model.Value {
	return model.NewMapValue()
}

func TestWriter_RendersElementMaps(t *testing.T) {
	t.Run("simple document", func(t *testing.T) {
		v := newMap()
		head := newMap()
		_ = head.SetMapKey("title", model.NewStringValue("T"))
		body := newMap()
		_ = body.SetMapKey("p", model.NewStringValue("Hello"))
		_ = v.SetMapKey("head", head)
		_ = v.SetMapKey("body", body)

		got := write(t, v, false)
		expected := `<head>
  <title>T</title>
</head>
<body>
  <p>Hello</p>
</body>
`
		if got != expected {
			t.Fatalf("expected:\n%s\ngot:\n%s", expected, got)
		}
	})

	t.Run("attributes and text", func(t *testing.T) {
		v := newMap()
		div := newMap()
		_ = div.SetMapKey("-class", model.NewStringValue("a"))
		_ = div.SetMapKey("#text", model.NewStringValue("Hello"))
		_ = div.SetMapKey("b", model.NewStringValue("world"))
		_ = v.SetMapKey("div", div)

		got := write(t, v, false)
		expected := `<div class="a">
  Hello
  <b>world</b>
</div>
`
		if got != expected {
			t.Fatalf("expected:\n%s\ngot:\n%s", expected, got)
		}
	})

	t.Run("slices render repeated elements", func(t *testing.T) {
		v := newMap()
		ul := newMap()
		li := model.NewSliceValue()
		_ = li.Append(model.NewStringValue("one"))
		_ = li.Append(model.NewStringValue("two"))
		_ = ul.SetMapKey("li", li)
		_ = v.SetMapKey("ul", ul)

		got := write(t, v, false)
		expected := `<ul>
  <li>one</li>
  <li>two</li>
</ul>
`
		if got != expected {
			t.Fatalf("expected:\n%s\ngot:\n%s", expected, got)
		}
	})

	t.Run("void elements are self closing", func(t *testing.T) {
		v := newMap()
		body := newMap()
		_ = body.SetMapKey("br", model.NewStringValue(""))
		img := newMap()
		_ = img.SetMapKey("-src", model.NewStringValue("x.png"))
		_ = body.SetMapKey("img", img)
		_ = v.SetMapKey("body", body)

		got := write(t, v, false)
		expected := `<body>
  <br/>
  <img src="x.png"/>
</body>
`
		if got != expected {
			t.Fatalf("expected:\n%s\ngot:\n%s", expected, got)
		}
	})
}

func TestWriter_EscapesWithNamedEntities(t *testing.T) {
	v := newMap()
	p := newMap()
	_ = p.SetMapKey("#text", model.NewStringValue(`<tag> & "quote" 'apos'`))
	_ = v.SetMapKey("p", p)

	got := write(t, v, true)
	expected := `<p>&lt;tag&gt; &amp; &quot;quote&quot; &apos;apos&apos;</p>`
	if got != expected {
		t.Fatalf("expected:\n%s\ngot:\n%s", expected, got)
	}

	// Attribute escaping.
	v = newMap()
	a := newMap()
	_ = a.SetMapKey("-title", model.NewStringValue(`a "b" & c`))
	_ = v.SetMapKey("a", a)
	got = write(t, v, true)
	expected = `<a title="a &quot;b&quot; &amp; c"></a>`
	if got != expected {
		t.Fatalf("expected:\n%s\ngot:\n%s", expected, got)
	}
}

func TestWriter_RawTextElementsNotEscaped(t *testing.T) {
	v := newMap()
	body := newMap()
	_ = body.SetMapKey("script", model.NewStringValue(`if (a < b) x = "&amp;"`))
	_ = body.SetMapKey("style", model.NewStringValue(`a > b { color: red; }`))
	_ = v.SetMapKey("body", body)

	got := write(t, v, true)
	expected := `<body><script>if (a < b) x = "&amp;"</script><style>a > b { color: red; }</style></body>`
	if got != expected {
		t.Fatalf("expected:\n%s\ngot:\n%s", expected, got)
	}
}

func TestWriter_CompactModeViaExtFlag(t *testing.T) {
	v := newMap()
	body := newMap()
	_ = body.SetMapKey("p", model.NewStringValue("Hi"))
	_ = v.SetMapKey("body", body)

	options := parsing.WriterOptions{Ext: map[string]string{"html-compact": "true"}}
	w, err := html.HTML.NewWriter(options)
	if err != nil {
		t.Fatal(err)
	}
	out, err := w.Write(v)
	if err != nil {
		t.Fatal(err)
	}
	expected := `<body><p>Hi</p></body>`
	if string(out) != expected {
		t.Fatalf("expected:\n%s\ngot:\n%s", expected, string(out))
	}
}

func TestWriter_CompactMode(t *testing.T) {
	v := newMap()
	head := newMap()
	_ = head.SetMapKey("title", model.NewStringValue("T"))
	body := newMap()
	_ = body.SetMapKey("p", model.NewStringValue("Hi"))
	_ = v.SetMapKey("head", head)
	_ = v.SetMapKey("body", body)

	got := write(t, v, true)
	expected := `<head><title>T</title></head><body><p>Hi</p></body>`
	if got != expected {
		t.Fatalf("expected:\n%s\ngot:\n%s", expected, got)
	}
}

func TestWriter_RoundTrip(t *testing.T) {
	r, err := html.HTML.NewReader(parsing.DefaultReaderOptions())
	if err != nil {
		t.Fatal(err)
	}
	w, err := html.HTML.NewWriter(parsing.DefaultWriterOptions())
	if err != nil {
		t.Fatal(err)
	}

	in := `<html><head><title>T</title></head><body><div class="a">Hello <b>world</b></div><ul><li>one<li>two</ul><br><img src="x.png"><script>if (a < b) x = "&amp;"</script></body></html>`
	read, err := r.Read([]byte(in))
	if err != nil {
		t.Fatal(err)
	}
	out, err := w.Write(read)
	if err != nil {
		t.Fatal(err)
	}

	// Re-read the output and ensure it matches the original model.
	readAgain, err := r.Read(out)
	if err != nil {
		t.Fatal(err)
	}
	equal, err := read.Equal(readAgain)
	if err != nil {
		t.Fatal(err)
	}
	eqBool, err := equal.BoolValue()
	if err != nil {
		t.Fatal(err)
	}
	if !eqBool {
		t.Fatalf("round trip mismatch:\nfirst:\n%s\nsecond:\n%s", read, readAgain)
	}
}
