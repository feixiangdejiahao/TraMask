package ansi

import (
	"reflect"
	"testing"
)

func TestTokenize(t *testing.T) {
	tests := []struct {
		name string
		arg  string
		want []Token
	}{
		{
			name: "empty",
			arg:  "",
			want: []Token{},
		},
		{
			name: "text",
			arg:  "hello",
			want: []Token{{Type: TokenText, Raw: "hello", Text: "hello"}},
		},
		{
			name: "sgr",
			arg:  "\x1b[31mhello",
			want: []Token{
				{Type: TokenSGR, Raw: "\x1b[31m"},
				{Type: TokenText, Raw: "hello", Text: "hello"},
			},
		},
		{
			name: "reset",
			arg:  "\x1b[0mhello",
			want: []Token{
				{Type: TokenReset, Raw: "\x1b[0m"},
				{Type: TokenText, Raw: "hello", Text: "hello"},
			},
		},
		{
			name: "reset short",
			arg:  "\x1b[mhello",
			want: []Token{
				{Type: TokenReset, Raw: "\x1b[m"},
				{Type: TokenText, Raw: "hello", Text: "hello"},
			},
		},
		{
			name: "hyperlink",
			arg:  "\x1b]8;;https://example.com\x1b\\hello\x1b]8;;\x1b\\",
			want: []Token{
				{Type: TokenHyperlinkOpen, Raw: "\x1b]8;;https://example.com\x1b\\", Text: "https://example.com"},
				{Type: TokenText, Raw: "hello", Text: "hello"},
				{Type: TokenHyperlinkClose, Raw: "\x1b]8;;\x1b\\"},
			},
		},
		{
			name: "hyperlink bel",
			arg:  "\x1b]8;;https://example.com\x07hello\x1b]8;;\x07",
			want: []Token{
				{Type: TokenHyperlinkOpen, Raw: "\x1b]8;;https://example.com\x07", Text: "https://example.com"},
				{Type: TokenText, Raw: "hello", Text: "hello"},
				{Type: TokenHyperlinkClose, Raw: "\x1b]8;;\x07"},
			},
		},
		{
			name: "non-sgr csi",
			arg:  "\x1b[2Jhello",
			want: []Token{
				{Type: TokenText, Raw: "\x1b[2J"},
				{Type: TokenText, Raw: "hello", Text: "hello"},
			},
		},
		{
			name: "double escape",
			arg:  "\x1b\x1b[31mhello",
			want: []Token{
				{Type: TokenText, Raw: "\x1b"},
				{Type: TokenSGR, Raw: "\x1b[31m"},
				{Type: TokenText, Raw: "hello", Text: "hello"},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := Tokenize(tt.arg)
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("Tokenize(%q) = %#v, want %#v", tt.arg, got, tt.want)
			}
		})
	}
}

func TestStripANSI(t *testing.T) {
	tests := []struct {
		arg  string
		want string
	}{
		{"", ""},
		{"hello", "hello"},
		{"\x1b[31mhello\x1b[0m", "hello"},
		{"\x1b[2Jhello", "hello"},
		{"\x1b]8;;https://example.com\x1b\\hello\x1b]8;;\x1b\\", "hello"},
	}
	for _, tt := range tests {
		if got := StripANSI(tt.arg); got != tt.want {
			t.Errorf("StripANSI(%q) = %q, want %q", tt.arg, got, tt.want)
		}
	}
}

func TestANSIWidth(t *testing.T) {
	tests := []struct {
		arg  string
		want int
	}{
		{"", 0},
		{"hello", 5},
		{"\x1b[31mhello\x1b[0m", 5},
		{"世界", 4},
		{"a\u200bb", 2},
	}
	for _, tt := range tests {
		if got := ANSIWidth(tt.arg); got != tt.want {
			t.Errorf("ANSIWidth(%q) = %d, want %d", tt.arg, got, tt.want)
		}
	}
}

func TestHasANSI(t *testing.T) {
	tests := []struct {
		arg  string
		want bool
	}{
		{"", false},
		{"hello", false},
		{"\x1b[31mhello", true},
		{"\x1b[2Jhello", true},
		{"\x1b]8;;url\x1b\\hello\x1b]8;;\x1b\\", true},
	}
	for _, tt := range tests {
		if got := HasANSI(tt.arg); got != tt.want {
			t.Errorf("HasANSI(%q) = %v, want %v", tt.arg, got, tt.want)
		}
	}
}

func TestTruncateANSI(t *testing.T) {
	tests := []struct {
		name string
		arg  string
		w    int
		opts TruncateOptions
		want string
	}{
		{
			name: "empty",
			arg:  "",
			w:    5,
			want: "",
		},
		{
			name: "simple",
			arg:  "hello",
			w:    3,
			want: "hel",
		},
		{
			name: "fits",
			arg:  "hello",
			w:    5,
			want: "hello",
		},
		{
			name: "tail reserves width",
			arg:  "hello",
			w:    5,
			opts: TruncateOptions{Tail: "..."},
			want: "he...",
		},
		{
			name: "tail no truncate when text fits remaining",
			arg:  "hello",
			w:    10,
			opts: TruncateOptions{Tail: "..."},
			want: "hello",
		},
		{
			name: "tail",
			arg:  "hello world",
			w:    8,
			opts: TruncateOptions{Tail: "..."},
			want: "hello...",
		},
		{
			name: "tail too long",
			arg:  "hello",
			w:    2,
			opts: TruncateOptions{Tail: "..."},
			want: "...",
		},
		{
			name: "styled",
			arg:  "\x1b[31mhello",
			w:    3,
			want: "\x1b[31mhel\x1b[0m",
		},
		{
			name: "styled tail",
			arg:  "\x1b[31mhello world",
			w:    8,
			opts: TruncateOptions{Tail: "..."},
			want: "\x1b[31mhello...\x1b[0m",
		},
		{
			name: "wide runes",
			arg:  "世界hello",
			w:    5,
			want: "世界h",
		},
		{
			name: "zero width space",
			arg:  "a\u200bbbbb",
			w:    3,
			want: "a\u200bbb",
		},
		{
			name: "hyperlink close",
			arg:  "\x1b]8;;https://example.com\x1b\\hello world\x1b]8;;\x1b\\",
			w:    5,
			want: "\x1b]8;;https://example.com\x1b\\hello\x1b]8;;\x1b\\",
		},
		{
			name: "preserve resets",
			arg:  "\x1b[31mhello\x1b[0mworld",
			w:    7,
			opts: TruncateOptions{PreserveResets: true},
			want: "\x1b[31mhello\x1b[0m\x1b[31mwo\x1b[0m",
		},
		{
			name: "no preserve resets",
			arg:  "\x1b[31mhello\x1b[0mworld",
			w:    7,
			want: "\x1b[31mhello\x1b[0mwo",
		},
		{
			name: "reset esc m",
			arg:  "\x1b[1mhello\x1b[mworld",
			w:    7,
			opts: TruncateOptions{PreserveResets: true},
			want: "\x1b[1mhello\x1b[m\x1b[1mwo\x1b[0m",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := TruncateANSI(tt.arg, tt.w, tt.opts)
			if got != tt.want {
				t.Errorf("TruncateANSI(%q, %d, %+v) = %q, want %q", tt.arg, tt.w, tt.opts, got, tt.want)
			}
		})
	}
}

func TestTruncateANSIHyperlinkClose(t *testing.T) {
	s := "\x1b]8;;https://example.com\x1b\\hello world\x1b]8;;\x1b\\"
	got := TruncateANSI(s, 5, TruncateOptions{})
	want := "\x1b]8;;https://example.com\x1b\\hello\x1b]8;;\x1b\\"
	if got != want {
		t.Errorf("hyperlink truncate = %q, want %q", got, want)
	}

	// Truncating exactly at the end of the link text keeps the close intact.
	got = TruncateANSI(s, 11, TruncateOptions{})
	want = s
	if got != want {
		t.Errorf("hyperlink exact fit = %q, want %q", got, want)
	}
}

func TestTruncateANSIMultipleResets(t *testing.T) {
	s := "\x1b[1mfoo\x1b[0mbar\x1b[31mbaz\x1b[0mqux"
	got := TruncateANSI(s, 8, TruncateOptions{PreserveResets: true})
	want := "\x1b[1mfoo\x1b[0m\x1b[1mbar\x1b[31mba\x1b[0m"
	if got != want {
		t.Errorf("multiple resets = %q, want %q", got, want)
	}
}

func TestTruncateANSIGrapheme(t *testing.T) {
	// Family emoji is a single grapheme cluster (width 2).
	s := "👨‍👩‍👧‍👦hello"
	got := TruncateANSI(s, 3, TruncateOptions{})
	if got != "👨‍👩‍👧‍👦h" {
		t.Errorf("grapheme truncate = %q, want family+h", got)
	}
}
