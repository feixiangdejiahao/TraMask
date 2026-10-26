package html_test

import (
	"testing"

	"github.com/tomwright/dasel/v3/model"
	"github.com/tomwright/dasel/v3/parsing"
	"github.com/tomwright/dasel/v3/parsing/html"
)

func read(t *testing.T, in string, structured bool) *model.Value {
	t.Helper()
	options := parsing.DefaultReaderOptions()
	if structured {
		options.Ext["html-mode"] = "structured"
	}
	r, err := html.HTML.NewReader(options)
	if err != nil {
		t.Fatalf("unexpected error: %s", err)
	}
	v, err := r.Read([]byte(in))
	if err != nil {
		t.Fatalf("unexpected error: %s", err)
	}
	return v
}

func mustGetMapKey(t *testing.T, v *model.Value, key string) *model.Value {
	t.Helper()
	got, err := v.GetMapKey(key)
	if err != nil {
		t.Fatalf("error getting key %q: %s", key, err)
	}
	return got
}

func mustString(t *testing.T, v *model.Value) string {
	t.Helper()
	s, err := v.StringValue()
	if err != nil {
		t.Fatalf("error getting string value: %s", err)
	}
	return s
}

func TestReader_NormalizesHeadAndBody(t *testing.T) {
	t.Run("full document", func(t *testing.T) {
		v := read(t, `<html><head><title>T</title></head><body><p>Hi</p></body></html>`, false)
		head := mustGetMapKey(t, v, "head")
		body := mustGetMapKey(t, v, "body")
		if _, err := head.GetMapKey("title"); err != nil {
			t.Fatalf("expected title in head: %s", err)
		}
		if _, err := body.GetMapKey("p"); err != nil {
			t.Fatalf("expected p in body: %s", err)
		}
	})

	t.Run("no html wrapper", func(t *testing.T) {
		v := read(t, `<p>Hi</p>`, false)
		head := mustGetMapKey(t, v, "head")
		body := mustGetMapKey(t, v, "body")
		if head.Type() != model.TypeString {
			t.Fatalf("expected empty head to be a string, got %s", head.Type())
		}
		if _, err := body.GetMapKey("p"); err != nil {
			t.Fatalf("expected p in body: %s", err)
		}
	})

	t.Run("orphan content goes into body", func(t *testing.T) {
		v := read(t, `<html><head><title>T</title></head><p>orphan</p></html>`, false)
		body := mustGetMapKey(t, v, "body")
		if _, err := body.GetMapKey("p"); err != nil {
			t.Fatalf("expected orphan p in body: %s", err)
		}
	})

	t.Run("head and body created when missing", func(t *testing.T) {
		v := read(t, `<div>hello</div>`, false)
		for _, key := range []string{"head", "body"} {
			if _, err := v.GetMapKey(key); err != nil {
				t.Fatalf("expected %s key: %s", key, err)
			}
		}
	})
}

func TestReader_ElementConversion(t *testing.T) {
	t.Run("attributes use dash prefix", func(t *testing.T) {
		v := read(t, `<div class="a" id="b">text</div>`, false)
		div := mustGetMapKey(t, mustGetMapKey(t, v, "body"), "div")
		if got := mustString(t, mustGetMapKey(t, div, "-class")); got != "a" {
			t.Fatalf("expected -class=a, got %q", got)
		}
		if got := mustString(t, mustGetMapKey(t, div, "-id")); got != "b" {
			t.Fatalf("expected -id=b, got %q", got)
		}
		if got := mustString(t, mustGetMapKey(t, div, "#text")); got != "text" {
			t.Fatalf("expected #text=text, got %q", got)
		}
	})

	t.Run("text-only element simplifies to string", func(t *testing.T) {
		v := read(t, `<p>hello</p>`, false)
		p := mustGetMapKey(t, mustGetMapKey(t, v, "body"), "p")
		if p.Type() != model.TypeString {
			t.Fatalf("expected string, got %s", p.Type())
		}
		if got := mustString(t, p); got != "hello" {
			t.Fatalf("expected hello, got %q", got)
		}
	})

	t.Run("same tag siblings group into slice", func(t *testing.T) {
		v := read(t, `<p>one</p><p>two</p>`, false)
		p := mustGetMapKey(t, mustGetMapKey(t, v, "body"), "p")
		if p.Type() != model.TypeSlice {
			t.Fatalf("expected slice, got %s", p.Type())
		}
		if n, err := p.SliceLen(); err != nil || n != 2 {
			t.Fatalf("expected 2 items, got %d (%v)", n, err)
		}
	})

	t.Run("void element without attributes is empty string", func(t *testing.T) {
		v := read(t, `<br><hr>`, false)
		body := mustGetMapKey(t, v, "body")
		if got := mustString(t, mustGetMapKey(t, body, "br")); got != "" {
			t.Fatalf("expected empty br, got %q", got)
		}
		if got := mustString(t, mustGetMapKey(t, body, "hr")); got != "" {
			t.Fatalf("expected empty hr, got %q", got)
		}
	})

	t.Run("void element with attributes becomes map", func(t *testing.T) {
		v := read(t, `<img src="x.png" alt="">`, false)
		img := mustGetMapKey(t, mustGetMapKey(t, v, "body"), "img")
		if img.Type() != model.TypeMap {
			t.Fatalf("expected map, got %s", img.Type())
		}
		if got := mustString(t, mustGetMapKey(t, img, "-src")); got != "x.png" {
			t.Fatalf("expected x.png, got %q", got)
		}
		if got := mustString(t, mustGetMapKey(t, img, "-alt")); got != "" {
			t.Fatalf("expected empty alt, got %q", got)
		}
	})

	t.Run("boolean attributes are empty strings", func(t *testing.T) {
		v := read(t, `<input type="checkbox" checked disabled>`, false)
		input := mustGetMapKey(t, mustGetMapKey(t, v, "body"), "input")
		if got := mustString(t, mustGetMapKey(t, input, "-checked")); got != "" {
			t.Fatalf("expected empty checked, got %q", got)
		}
		if got := mustString(t, mustGetMapKey(t, input, "-disabled")); got != "" {
			t.Fatalf("expected empty disabled, got %q", got)
		}
	})

	t.Run("whitespace is trimmed", func(t *testing.T) {
		v := read(t, `<p>  hello  </p>`, false)
		p := mustGetMapKey(t, mustGetMapKey(t, v, "body"), "p")
		if got := mustString(t, p); got != "hello" {
			t.Fatalf("expected hello, got %q", got)
		}
	})
}

func TestReader_DoesNotExposeHTMLWrapper(t *testing.T) {
	v := read(t, `<html lang="en"><head></head><body><p>Hi</p></body></html>`, false)
	keys, err := v.MapKeys()
	if err != nil {
		t.Fatal(err)
	}
	for _, key := range keys {
		if key != "head" && key != "body" {
			t.Fatalf("unexpected top-level key %q", key)
		}
	}

	// Structured mode keeps the html attrs.
	sv := read(t, `<html lang="en"><head></head><body></body></html>`, true)
	attrs := mustGetMapKey(t, sv, "attrs")
	if got := mustString(t, mustGetMapKey(t, attrs, "lang")); got != "en" {
		t.Fatalf("expected lang in structured attrs, got %q", got)
	}
}

func TestReader_LowercasesNames(t *testing.T) {
	v := read(t, `<DIV CLASS="X">text</DIV>`, false)
	body := mustGetMapKey(t, v, "body")
	if _, err := body.GetMapKey("DIV"); err == nil {
		t.Fatalf("did not expect uppercase key DIV")
	}
	div := mustGetMapKey(t, body, "div")
	if _, err := div.GetMapKey("-class"); err != nil {
		t.Fatalf("expected lowercase attr: %s", err)
	}
}

func TestReader_ImplicitClosing(t *testing.T) {
	t.Run("p closes p", func(t *testing.T) {
		v := read(t, `<p>one<p>two`, false)
		p := mustGetMapKey(t, mustGetMapKey(t, v, "body"), "p")
		if p.Type() != model.TypeSlice {
			t.Fatalf("expected slice, got %s", p.Type())
		}
	})

	t.Run("li closes li", func(t *testing.T) {
		v := read(t, `<ul><li>one<li>two</ul>`, false)
		li := mustGetMapKey(t, mustGetMapKey(t, mustGetMapKey(t, v, "body"), "ul"), "li")
		if li.Type() != model.TypeSlice {
			t.Fatalf("expected slice, got %s", li.Type())
		}
	})

	t.Run("td and tr close same type", func(t *testing.T) {
		v := read(t, `<table><tr><td>a<td>b<tr><td>c<td>d</table>`, false)
		table := mustGetMapKey(t, mustGetMapKey(t, v, "body"), "table")
		tr := mustGetMapKey(t, table, "tr")
		if tr.Type() != model.TypeSlice {
			t.Fatalf("expected tr slice, got %s", tr.Type())
		}
	})

	t.Run("option closes option", func(t *testing.T) {
		v := read(t, `<select><option>a<option>b</select>`, false)
		option := mustGetMapKey(t, mustGetMapKey(t, mustGetMapKey(t, v, "body"), "select"), "option")
		if option.Type() != model.TypeSlice {
			t.Fatalf("expected slice, got %s", option.Type())
		}
	})

	t.Run("dt and dd close each other", func(t *testing.T) {
		v := read(t, `<dl><dt>a<dd>b<dt>c<dd>d</dl>`, false)
		dl := mustGetMapKey(t, mustGetMapKey(t, v, "body"), "dl")
		dt := mustGetMapKey(t, dl, "dt")
		dd := mustGetMapKey(t, dl, "dd")
		if n, _ := dt.SliceLen(); n != 2 {
			t.Fatalf("expected 2 dt, got %d", n)
		}
		if n, _ := dd.SliceLen(); n != 2 {
			t.Fatalf("expected 2 dd, got %d", n)
		}
	})

	t.Run("block level elements close p", func(t *testing.T) {
		for _, tag := range []string{"div", "ul", "ol", "table", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"} {
			v := read(t, `<p>one<`+tag+`>two</`+tag+`>`, false)
			body := mustGetMapKey(t, v, "body")
			p := mustGetMapKey(t, body, "p")
			if got := mustString(t, p); got != "one" {
				t.Fatalf("%s: expected p=one, got %q", tag, got)
			}
			if _, err := body.GetMapKey(tag); err != nil {
				t.Fatalf("%s: expected sibling %s, got error: %s", tag, tag, err)
			}
		}
	})
}

func TestReader_CommentsAndDoctypeIgnored(t *testing.T) {
	v := read(t, `<!-- comment --><!DOCTYPE html><p>hello</p>`, false)
	body := mustGetMapKey(t, v, "body")
	if _, err := body.GetMapKey("p"); err != nil {
		t.Fatalf("expected p in body: %s", err)
	}
	// Comment text should not appear.
	keys, err := v.MapKeys()
	if err != nil {
		t.Fatal(err)
	}
	if len(keys) != 2 {
		t.Fatalf("expected only head/body keys, got %v", keys)
	}
}

func TestReader_EntityDecoding(t *testing.T) {
	v := read(t, `<p>&amp; &lt; &gt; &quot; &#65; &#x42; &copy;</p>`, false)
	p := mustGetMapKey(t, mustGetMapKey(t, v, "body"), "p")
	if got := mustString(t, p); got != "& < > \" A B ©" {
		t.Fatalf("unexpected decoded text: %q", got)
	}

	v = read(t, `<a href="?a=1&amp;b=2">link</a>`, false)
	a := mustGetMapKey(t, mustGetMapKey(t, v, "body"), "a")
	if got := mustString(t, mustGetMapKey(t, a, "-href")); got != "?a=1&b=2" {
		t.Fatalf("unexpected decoded attr: %q", got)
	}
}

func TestReader_RawTextElements(t *testing.T) {
	v := read(t, `<script>if (a < b && c > d) { x = "&amp;"; }</script>`, false)
	script := mustGetMapKey(t, mustGetMapKey(t, v, "body"), "script")
	if got := mustString(t, script); got != `if (a < b && c > d) { x = "&amp;"; }` {
		t.Fatalf("raw script content not preserved: %q", got)
	}

	v = read(t, `<style>a > b { color: red; }</style>`, false)
	style := mustGetMapKey(t, mustGetMapKey(t, v, "body"), "style")
	if got := mustString(t, style); got != `a > b { color: red; }` {
		t.Fatalf("raw style content not preserved: %q", got)
	}
}

func TestReader_StructuredMode(t *testing.T) {
	v := read(t, `<html lang="en"><head><title>T</title></head><body><p class="x">Hi</p></body></html>`, true)

	if got := mustString(t, mustGetMapKey(t, v, "tag")); got != "html" {
		t.Fatalf("expected tag html, got %q", got)
	}
	attrs := mustGetMapKey(t, v, "attrs")
	if got := mustString(t, mustGetMapKey(t, attrs, "lang")); got != "en" {
		t.Fatalf("expected lang attr, got %q", got)
	}
	children := mustGetMapKey(t, v, "children")
	if n, _ := children.SliceLen(); n != 2 {
		t.Fatalf("expected 2 children, got %d", n)
	}
	head, err := children.GetSliceIndex(0)
	if err != nil {
		t.Fatal(err)
	}
	if got := mustString(t, mustGetMapKey(t, head, "tag")); got != "head" {
		t.Fatalf("expected first child head, got %q", got)
	}
}
