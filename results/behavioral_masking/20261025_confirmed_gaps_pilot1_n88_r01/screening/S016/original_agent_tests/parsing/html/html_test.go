package html_test

import (
	"slices"
	"testing"

	"github.com/tomwright/dasel/v3/parsing"
	"github.com/tomwright/dasel/v3/parsing/html"
)

func TestHTMLRegistration(t *testing.T) {
	if !slices.Contains(parsing.RegisteredReaders(), html.HTML) {
		t.Fatalf("expected html reader to be registered")
	}
	if !slices.Contains(parsing.RegisteredWriters(), html.HTML) {
		t.Fatalf("expected html writer to be registered")
	}
}
