package html_test

import (
	"testing"

	"github.com/tomwright/dasel/v3/model"
	"github.com/tomwright/dasel/v3/parsing"
	"github.com/tomwright/dasel/v3/parsing/html"
)

func writeHTML(t *testing.T, value *model.Value, compact bool) string {
	t.Helper()
	opts := parsing.DefaultWriterOptions()
	opts.Compact = compact
	w, err := html.HTML.NewWriter(opts)
	if err != nil {
		t.Fatalf("unexpected error creating writer: %s", err)
	}
	out, err := w.Write(value)
	if err != nil {
		t.Fatalf("unexpected error writing HTML: %s", err)
	}
	return string(out)
}

func TestHtmlWriter_Write(t *testing.T) {
	t.Run("renders element map directly", func(t *testing.T) {
		body := model.NewMapValue()
		div := model.NewMapValue()
		_ = div.SetMapKey("-class", model.NewStringValue("box"))
		_ = div.SetMapKey("p", model.NewStringValue("hi"))
		_ = body.SetMapKey("div", div)
		root := model.NewMapValue()
		_ = root.SetMapKey("body", body)

		got := writeHTML(t, root, false)
		expected := `<body>
  <div class="box">
    <p>hi</p>
  </div>
</body>
`
		if got != expected {
			t.Fatalf("Expected:\n%s\nGot:\n%s", expected, got)
		}
	})

	t.Run("void elements are self-closing", func(t *testing.T) {
		body := model.NewMapValue()
		_ = body.SetMapKey("br", model.NewStringValue(""))
		input := model.NewMapValue()
		_ = input.SetMapKey("-disabled", model.NewStringValue(""))
		_ = body.SetMapKey("input", input)
		root := model.NewMapValue()
		_ = root.SetMapKey("body", body)

		got := writeHTML(t, root, false)
		expected := `<body>
  <br/>
  <input disabled=""/>
</body>
`
		if got != expected {
			t.Fatalf("Expected:\n%s\nGot:\n%s", expected, got)
		}
	})

	t.Run("escapes text and attributes", func(t *testing.T) {
		div := model.NewMapValue()
		_ = div.SetMapKey("-title", model.NewStringValue(`a "quoted" & b`))
		_ = div.SetMapKey("#text", model.NewStringValue("a & b < c"))
		root := model.NewMapValue()
		_ = root.SetMapKey("div", div)

		got := writeHTML(t, root, false)
		expected := `<div title="a &quot;quoted&quot; &amp; b">a &amp; b &lt; c</div>
`
		if got != expected {
			t.Fatalf("Expected:\n%s\nGot:\n%s", expected, got)
		}
	})

	t.Run("raw text is not escaped", func(t *testing.T) {
		root := model.NewMapValue()
		_ = root.SetMapKey("script", model.NewStringValue(`if (a < b && c > d) { x = "&amp;"; }`))
		got := writeHTML(t, root, false)
		expected := `<script>if (a < b && c > d) { x = "&amp;"; }</script>
`
		if got != expected {
			t.Fatalf("Expected:\n%s\nGot:\n%s", expected, got)
		}
	})

	t.Run("compact mode", func(t *testing.T) {
		body := model.NewMapValue()
		div := model.NewMapValue()
		_ = div.SetMapKey("p", model.NewStringValue("hi"))
		_ = body.SetMapKey("div", div)
		_ = body.SetMapKey("br", model.NewStringValue(""))
		root := model.NewMapValue()
		_ = root.SetMapKey("body", body)

		got := writeHTML(t, root, true)
		expected := `<body><div><p>hi</p></div><br/></body>
`
		if got != expected {
			t.Fatalf("Expected:\n%s\nGot:\n%s", expected, got)
		}
	})

	t.Run("writes structured node", func(t *testing.T) {
		title := model.NewMapValue()
		_ = title.SetMapKey("tag", model.NewStringValue("title"))
		_ = title.SetMapKey("attrs", model.NewMapValue())
		_ = title.SetMapKey("text", model.NewStringValue("T"))
		_ = title.SetMapKey("children", model.NewSliceValue())

		head := model.NewMapValue()
		_ = head.SetMapKey("tag", model.NewStringValue("head"))
		_ = head.SetMapKey("attrs", model.NewMapValue())
		_ = head.SetMapKey("text", model.NewStringValue(""))
		titleChildren := model.NewSliceValue()
		_ = titleChildren.Append(title)
		_ = head.SetMapKey("children", titleChildren)

		p := model.NewMapValue()
		_ = p.SetMapKey("tag", model.NewStringValue("p"))
		attrs := model.NewMapValue()
		_ = attrs.SetMapKey("class", model.NewStringValue("x"))
		_ = p.SetMapKey("attrs", attrs)
		_ = p.SetMapKey("text", model.NewStringValue("Hi"))
		_ = p.SetMapKey("children", model.NewSliceValue())

		body := model.NewMapValue()
		_ = body.SetMapKey("tag", model.NewStringValue("body"))
		_ = body.SetMapKey("attrs", model.NewMapValue())
		_ = body.SetMapKey("text", model.NewStringValue(""))
		bodyChildren := model.NewSliceValue()
		_ = bodyChildren.Append(p)
		_ = body.SetMapKey("children", bodyChildren)

		root := model.NewMapValue()
		_ = root.SetMapKey("tag", model.NewStringValue("html"))
		rootAttrs := model.NewMapValue()
		_ = rootAttrs.SetMapKey("lang", model.NewStringValue("en"))
		_ = root.SetMapKey("attrs", rootAttrs)
		_ = root.SetMapKey("text", model.NewStringValue(""))
		rootChildren := model.NewSliceValue()
		_ = rootChildren.Append(head)
		_ = rootChildren.Append(body)
		_ = root.SetMapKey("children", rootChildren)

		got := writeHTML(t, root, false)
		expected := `<html lang="en">
  <head>
    <title>T</title>
  </head>
  <body>
    <p class="x">Hi</p>
  </body>
</html>
`
		if got != expected {
			t.Fatalf("Expected:\n%s\nGot:\n%s", expected, got)
		}
	})
}
