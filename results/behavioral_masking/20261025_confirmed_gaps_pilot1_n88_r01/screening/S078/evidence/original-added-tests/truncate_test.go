package termenv

import (
	"bytes"
	"testing"
	"text/template"
)

func TestANSIWrappers(t *testing.T) {
	if StripANSI("\x1b[31mHello\x1b[0m") != "Hello" {
		t.Error("StripANSI failed")
	}
	if ANSIWidth("\x1b[31mHello\x1b[0m") != 5 {
		t.Error("ANSIWidth failed")
	}
	if !HasANSI("\x1b[31m") {
		t.Error("HasANSI failed")
	}
	if HasANSI("hello") {
		t.Error("HasANSI should be false")
	}
	if TruncateANSI("hello world", 8, TruncateOptions{Tail: "..."}) != "hello..." {
		t.Error("TruncateANSI failed")
	}
}

func TestStyleTruncate(t *testing.T) {
	s := String("hello world").Bold()
	got := s.Truncate(8, TruncateOptions{Tail: "..."})
	want := "\x1b[1mhello...\x1b[0m"
	if got != want {
		t.Errorf("got %q, want %q", got, want)
	}

	// Ascii: plain text without tail
	ascii := Ascii.String("hello world")
	got = ascii.Truncate(8, TruncateOptions{Tail: "..."})
	if got != "hello wo" {
		t.Errorf("Ascii Style.Truncate: got %q, want %q", got, "hello wo")
	}
}

func TestStylePreserveResets(t *testing.T) {
	s := String("hello\x1b[0m world").Bold().PreserveResets()
	got := s.Truncate(10, TruncateOptions{})
	want := "\x1b[1mhello\x1b[0m\x1b[1m worl\x1b[0m"
	if got != want {
		t.Errorf("got %q, want %q", got, want)
	}
}

func TestOutputStringAndTruncate(t *testing.T) {
	o := NewOutput(nil, WithProfile(ANSI), WithPreserveResets(true))
	s := o.String("hello\x1b[0m world").Bold()
	// Style created by Output should inherit preserve-resets
	got := s.Truncate(10, TruncateOptions{})
	if got != "\x1b[1mhello\x1b[0m\x1b[1m worl\x1b[0m" {
		t.Errorf("got %q", got)
	}

	// Output.Truncate with default preserve-resets
	got = o.Truncate("\x1b[1mhello\x1b[0m world", 10, TruncateOptions{})
	if got != "\x1b[1mhello\x1b[0m\x1b[1m worl\x1b[0m" {
		t.Errorf("Output.Truncate got %q", got)
	}

	// Ascii Output.Truncate returns text with tail, no ANSI
	asciiOut := NewOutput(nil, WithProfile(Ascii))
	got = asciiOut.Truncate("\x1b[31mhello world\x1b[0m", 8, TruncateOptions{Tail: "..."})
	if got != "hello..." {
		t.Errorf("Ascii Output.Truncate: got %q, want %q", got, "hello...")
	}
}

func TestTemplateTruncateFuncs(t *testing.T) {
	o := NewOutput(nil, WithProfile(ANSI))
	tpl, err := template.New("test").Funcs(o.TemplateFuncs()).Parse(`{{ Truncate 8 "..." "hello world" }}|{{ truncate 5 "hello world" }}`)
	if err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	if err := tpl.Execute(&buf, nil); err != nil {
		t.Fatal(err)
	}
	if buf.String() != "hello...|hello" {
		t.Errorf("got %q", buf.String())
	}
}

func TestTemplatePreserveResetsPropagation(t *testing.T) {
	o := NewOutput(nil, WithProfile(ANSI), WithPreserveResets(true))
	tpl, err := template.New("test").Funcs(o.TemplateFuncs()).Parse(`{{ Truncate 10 "..." (Bold "hello\x1b[0m world") }}`)
	if err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	if err := tpl.Execute(&buf, nil); err != nil {
		t.Fatal(err)
	}
	want := "\x1b[1mhello\x1b[0m\x1b[1m w...\x1b[0m"
	if buf.String() != want {
		t.Errorf("got %q, want %q", buf.String(), want)
	}

	// Without the output default, the reset is not re-opened.
	o2 := NewOutput(nil, WithProfile(ANSI))
	tpl2, err := template.New("test").Funcs(o2.TemplateFuncs()).Parse(`{{ Truncate 10 "..." (Bold "hello\x1b[0m world") }}`)
	if err != nil {
		t.Fatal(err)
	}
	buf.Reset()
	if err := tpl2.Execute(&buf, nil); err != nil {
		t.Fatal(err)
	}
	want2 := "\x1b[1mhello\x1b[0m w..."
	if buf.String() != want2 {
		t.Errorf("got %q, want %q", buf.String(), want2)
	}
}
