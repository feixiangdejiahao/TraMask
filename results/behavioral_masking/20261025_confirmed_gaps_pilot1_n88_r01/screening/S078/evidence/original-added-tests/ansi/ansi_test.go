package ansi

import (
	"reflect"
	"testing"
)

func TestTokenize(t *testing.T) {
	tests := []struct {
		in   string
		want []Token
	}{
		{"hello", []Token{{TokenText, "hello", "hello"}}},
		{"\x1b[31mHello\x1b[0m", []Token{
			{TokenSGR, "\x1b[31m", ""},
			{TokenText, "Hello", "Hello"},
			{TokenReset, "\x1b[0m", ""},
		}},
		{"\x1b[m", []Token{{TokenReset, "\x1b[m", ""}}},
		{"\x1b]8;;https://example.com\x1b\\link\x1b]8;;\x1b\\", []Token{
			{TokenHyperlinkOpen, "\x1b]8;;https://example.com\x1b\\", "https://example.com"},
			{TokenText, "link", "link"},
			{TokenHyperlinkClose, "\x1b]8;;\x1b\\", ""},
		}},
		{"\x1b]8;;https://example.com\x07link\x1b]8;;\x07", []Token{
			{TokenHyperlinkOpen, "\x1b]8;;https://example.com\x07", "https://example.com"},
			{TokenText, "link", "link"},
			{TokenHyperlinkClose, "\x1b]8;;\x07", ""},
		}},
		{"a\x1b[2Jb", []Token{
			{TokenText, "a", "a"},
			{TokenText, "\x1b[2J", ""},
			{TokenText, "b", "b"},
		}},
	}

	for i, test := range tests {
		got := Tokenize(test.in)
		if !reflect.DeepEqual(got, test.want) {
			t.Errorf("test %d: got %#v, want %#v", i, got, test.want)
		}
	}
}

func TestStripANSI(t *testing.T) {
	tests := []struct {
		in, want string
	}{
		{"\x1b[31mHello\x1b[0m", "Hello"},
		{"\x1b]8;;https://example.com\x1b\\link\x1b]8;;\x1b\\", "link"},
		{"\x1b]8;;https://example.com\x07link\x1b]8;;\x07", "link"},
		{"plain", "plain"},
		{"\x1b[2J", ""},
	}
	for i, test := range tests {
		if got := StripANSI(test.in); got != test.want {
			t.Errorf("test %d: got %q, want %q", i, got, test.want)
		}
	}
}

func TestANSIWidth(t *testing.T) {
	tests := []struct {
		in   string
		want int
	}{
		{"hello", 5},
		{"\x1b[31mhello\x1b[0m", 5},
		{"你好", 4},
		{"\x1b[31m你好\x1b[0m", 4},
		{"a\u200bb", 2},
	}
	for i, test := range tests {
		if got := ANSIWidth(test.in); got != test.want {
			t.Errorf("test %d: got %d, want %d", i, got, test.want)
		}
	}
}

func TestHasANSI(t *testing.T) {
	if HasANSI("plain") {
		t.Error("expected false")
	}
	if !HasANSI("\x1b[31m") {
		t.Error("expected true")
	}
}

func TestTruncateANSI(t *testing.T) {
	tests := []struct {
		name string
		in   string
		w    int
		opts TruncateOptions
		want string
	}{
		{"simple", "hello world", 5, TruncateOptions{}, "hello"},
		{"tail", "hello world", 8, TruncateOptions{Tail: "..."}, "hello..."},
		{"wide", "你好世界", 4, TruncateOptions{}, "你好"},
		{"styled", "\x1b[31mhello world\x1b[0m", 5, TruncateOptions{}, "\x1b[31mhello\x1b[0m"},
		{"styled tail", "\x1b[31mhello world\x1b[0m", 8, TruncateOptions{Tail: "..."}, "\x1b[31mhello...\x1b[0m"},
		{"preserve resets", "\x1b[31mhello\x1b[0m world", 10, TruncateOptions{PreserveResets: true}, "\x1b[31mhello\x1b[0m\x1b[31m worl\x1b[0m"},
		{"hyperlink", "\x1b]8;;https://example.com\x1b\\click me\x1b]8;;\x1b\\", 5, TruncateOptions{}, "\x1b]8;;https://example.com\x1b\\click\x1b]8;;\x1b\\"},
		{"tail wider than max", "hello", 3, TruncateOptions{Tail: "..."}, "..."},
		{"tail trunc", "hello", 2, TruncateOptions{Tail: "..."}, ".."},
		{"max zero", "hello", 0, TruncateOptions{}, ""},
		{"zero width", "a\u200bb", 1, TruncateOptions{}, "a\u200b"},
		{"exact fit no tail", "hello", 8, TruncateOptions{Tail: "..."}, "hello"},
		{"not truncated no tail", "hello", 10, TruncateOptions{Tail: "..."}, "hello"},
		{"tail counts toward width", "hello", 5, TruncateOptions{Tail: "..."}, "he..."},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got := TruncateANSI(test.in, test.w, test.opts)
			if got != test.want {
				t.Errorf("got %q, want %q", got, test.want)
			}
		})
	}
}

func TestTruncateANSIEdgeCases(t *testing.T) {
	tests := []struct {
		name string
		in   string
		w    int
		opts TruncateOptions
		want string
	}{
		{"reset middle preserve", "\x1b[31mHello\x1b[0m World", 10, TruncateOptions{PreserveResets: true}, "\x1b[31mHello\x1b[0m\x1b[31m Worl\x1b[0m"},
		{"wide tail", "你好", 3, TruncateOptions{Tail: "…"}, "你…"},
		{"rgb zero is reset", "\x1b[38;2;0;0;0mHello", 3, TruncateOptions{}, "\x1b[38;2;0;0;0mHel"},
		{"styled tail narrow", "\x1b[31mHello World\x1b[0m", 7, TruncateOptions{Tail: "..."}, "\x1b[31mHell...\x1b[0m"},
		{"styled tail tiny", "\x1b[31mHello World\x1b[0m", 2, TruncateOptions{Tail: "..."}, "\x1b[31m..\x1b[0m"},
		{"exact with reset", "\x1b[31mHello\x1b[0m", 5, TruncateOptions{}, "\x1b[31mHello\x1b[0m"},
		{"only ansi", "\x1b[31m", 5, TruncateOptions{Tail: "..."}, "\x1b[31m\x1b[0m"},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got := TruncateANSI(test.in, test.w, test.opts)
			if got != test.want {
				t.Errorf("got %q, want %q", got, test.want)
			}
		})
	}
}

func TestTokenizeRoundTrip(t *testing.T) {
	inputs := []string{
		"hello",
		"\x1b[31mHello\x1b[0m",
		"\x1b[38;2;0;0;0mHello\x1b[0m",
		"\x1b]8;;https://example.com\x1b\\link\x1b]8;;\x1b\\",
		"\x1b[2J\x1b[1;1H",
		"a\x1b]0;title\x07b",
		"\x1b",
	}
	for _, in := range inputs {
		var got string
		for _, tok := range Tokenize(in) {
			got += tok.Raw
		}
		if got != in {
			t.Errorf("round trip failed: got %q, want %q", got, in)
		}
	}
}

func TestTruncateANSIPreserveResetsFullFit(t *testing.T) {
	got := TruncateANSI("\x1b[31mHello\x1b[0m", 100, TruncateOptions{PreserveResets: true})
	want := "\x1b[31mHello\x1b[0m\x1b[31m\x1b[0m"
	if got != want {
		t.Errorf("got %q, want %q", got, want)
	}
}
