package termenv

import (
	"bytes"
	"io"
	"testing"
	"text/template"
)

func TestTruncateANSIWrapper(t *testing.T) {
	if got := TruncateANSI("hello", 3, TruncateOptions{}); got != "hel" {
		t.Errorf("TruncateANSI = %q, want %q", got, "hel")
	}
	if got := TruncateANSI("\x1b[31mhello", 3, TruncateOptions{}); got != "\x1b[31mhel\x1b[0m" {
		t.Errorf("TruncateANSI = %q, want %q", got, "\x1b[31mhel\x1b[0m")
	}
}

func TestStripANSIWrapper(t *testing.T) {
	if got := StripANSI("\x1b[31mhello\x1b[0m"); got != "hello" {
		t.Errorf("StripANSI = %q, want %q", got, "hello")
	}
}

func TestANSIWidthWrapper(t *testing.T) {
	if got := ANSIWidth("\x1b[31m世界\x1b[0m"); got != 4 {
		t.Errorf("ANSIWidth = %d, want %d", got, 4)
	}
}

func TestHasANSIWrapper(t *testing.T) {
	if HasANSI("hello") {
		t.Errorf("HasANSI(hello) = true, want false")
	}
	if !HasANSI("\x1b[31mhello") {
		t.Errorf("HasANSI(\\x1b[31mhello) = false, want true")
	}
}

func TestStylePreserveResets(t *testing.T) {
	s := String("hello world").Bold()
	if s.preserveResets {
		t.Errorf("style should not preserve resets by default")
	}
	s = s.PreserveResets()
	if !s.preserveResets {
		t.Errorf("style should preserve resets after PreserveResets()")
	}
}

func TestStyleTruncate(t *testing.T) {
	s := String("hello world").Foreground(ANSIColor(1))
	got := s.Truncate(5, TruncateOptions{})
	want := "\x1b[31mhello\x1b[0m"
	if got != want {
		t.Errorf("Style.Truncate = %q, want %q", got, want)
	}

	// Tail inherits style.
	got = s.Truncate(8, TruncateOptions{Tail: "..."})
	want = "\x1b[31mhello...\x1b[0m"
	if got != want {
		t.Errorf("Style.Truncate with tail = %q, want %q", got, want)
	}
}

func TestStyleTruncateAscii(t *testing.T) {
	s := Ascii.String("hello world").Foreground(ANSIColor(1))
	got := s.Truncate(5, TruncateOptions{Tail: "..."})
	want := "hello"
	if got != want {
		t.Errorf("Ascii Style.Truncate = %q, want %q", got, want)
	}
}

func TestStyleTruncatePreserveResets(t *testing.T) {
	s := String("foo\x1b[0mbar").Foreground(ANSIColor(1)).PreserveResets()
	got := s.Truncate(5, TruncateOptions{})
	want := "\x1b[31mfoo\x1b[0m\x1b[31mba\x1b[0m"
	if got != want {
		t.Errorf("Style.Truncate preserve = %q, want %q", got, want)
	}
}

func TestOutputStringInheritsPreserveResets(t *testing.T) {
	o := NewOutput(io.Discard, WithProfile(ANSI), WithPreserveResets(true))
	s := o.String("hello")
	if !s.preserveResets {
		t.Errorf("Output.String style should inherit preserve-resets default")
	}
}

func TestOutputTruncate(t *testing.T) {
	o := NewOutput(io.Discard, WithProfile(ANSI))
	got := o.Truncate("\x1b[31mhello world", 8, TruncateOptions{Tail: "..."})
	want := "\x1b[31mhello...\x1b[0m"
	if got != want {
		t.Errorf("Output.Truncate = %q, want %q", got, want)
	}
}

func TestOutputTruncatePreserveResetsDefault(t *testing.T) {
	o := NewOutput(io.Discard, WithProfile(ANSI), WithPreserveResets(true))
	got := o.Truncate("\x1b[31mhello\x1b[0mworld", 7, TruncateOptions{})
	want := "\x1b[31mhello\x1b[0m\x1b[31mwo\x1b[0m"
	if got != want {
		t.Errorf("Output.Truncate preserve = %q, want %q", got, want)
	}

	// opts.PreserveResets can force it even without the default.
	o = NewOutput(io.Discard, WithProfile(ANSI))
	got = o.Truncate("\x1b[31mhello\x1b[0mworld", 7, TruncateOptions{PreserveResets: true})
	if got != want {
		t.Errorf("Output.Truncate opts preserve = %q, want %q", got, want)
	}
}

func TestOutputTruncateAscii(t *testing.T) {
	o := NewOutput(io.Discard, WithProfile(Ascii))
	got := o.Truncate("\x1b[31mhello world", 8, TruncateOptions{Tail: "..."})
	want := "hello..."
	if got != want {
		t.Errorf("Ascii Output.Truncate = %q, want %q", got, want)
	}
}

func TestOutputTemplateFuncsTruncate(t *testing.T) {
	o := NewOutput(io.Discard, WithProfile(ANSI), WithPreserveResets(true))
	funcs := o.TemplateFuncs()
	tpl := template.Must(template.New("test").Funcs(funcs).Parse(`{{ Truncate 8 "..." "\x1b[31mhello world" }}|{{ truncate 5 "\x1b[31mhello world" }}`))
	var buf bytes.Buffer
	if err := tpl.Execute(&buf, nil); err != nil {
		t.Fatal(err)
	}
	got := buf.String()
	want := "\x1b[31mhello...\x1b[0m|\x1b[31mhello\x1b[0m"
	if got != want {
		t.Errorf("template truncate = %q, want %q", got, want)
	}
}

func TestTemplateFuncsTruncateAscii(t *testing.T) {
	funcs := TemplateFuncs(Ascii)
	tpl := template.Must(template.New("test").Funcs(funcs).Parse(`{{ Truncate 8 "..." "\x1b[31mhello world" }}|{{ truncate 5 "\x1b[31mhello world" }}`))
	var buf bytes.Buffer
	if err := tpl.Execute(&buf, nil); err != nil {
		t.Fatal(err)
	}
	got := buf.String()
	want := "hello...|hello"
	if got != want {
		t.Errorf("ascii template truncate = %q, want %q", got, want)
	}
}

func TestOutputTemplateFuncsPropagatesDefault(t *testing.T) {
	o := NewOutput(io.Discard, WithProfile(ANSI), WithPreserveResets(true))
	funcs := o.TemplateFuncs()
	tpl := template.Must(template.New("test").Funcs(funcs).Parse(`{{ truncate 7 "\x1b[31mhello\x1b[0mworld" }}`))
	var buf bytes.Buffer
	if err := tpl.Execute(&buf, nil); err != nil {
		t.Fatal(err)
	}
	got := buf.String()
	want := "\x1b[31mhello\x1b[0m\x1b[31mwo\x1b[0m"
	if got != want {
		t.Errorf("template preserve = %q, want %q", got, want)
	}
}

func TestNoTailWhenTextFitsRemaining(t *testing.T) {
	// When the text fits in the space remaining after reserving the tail,
	// the full string is returned without appending the tail.
	if got := TruncateANSI("hello", 10, TruncateOptions{Tail: "..."}); got != "hello" {
		t.Errorf("expected full string without tail, got %q", got)
	}
	if got := TruncateANSI("hello world", 20, TruncateOptions{Tail: "..."}); got != "hello world" {
		t.Errorf("expected full string without tail, got %q", got)
	}
	// The tail always counts toward the width when truncating.
	if got := TruncateANSI("hello", 5, TruncateOptions{Tail: "..."}); got != "he..." {
		t.Errorf("expected he..., got %q", got)
	}
}

func TestTruncateDoesNotSplitCSI(t *testing.T) {
	// An unfinished CSI sequence at the end is passed through whole.
	got := TruncateANSI("\x1b[31", 3, TruncateOptions{})
	if got != "\x1b[31" {
		t.Errorf("unfinished CSI should be passed through unsplit, got %q", got)
	}
	// Complete CSI sequences are preserved whole.
	got = TruncateANSI("\x1b[2Jhello", 3, TruncateOptions{})
	if got != "\x1b[2Jhel" {
		t.Errorf("CSI should be passed through unsplit, got %q", got)
	}
}
