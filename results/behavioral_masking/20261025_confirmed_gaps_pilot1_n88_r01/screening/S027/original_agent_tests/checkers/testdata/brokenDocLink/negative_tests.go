package checker_test

import (
	"fmt"
	"math"
	"net/http"
	"strings"
)

var (
	_ = fmt.Println
	_ = math.Pi
	_ = http.MethodGet
	_ = strings.Builder{}
)

// Foo is a documented type.
type Foo struct {
	// Field is documented.
	Field int
}

// Method is documented.
func (Foo) Method() {}

// ValidLocal references [Foo] and [Foo.Method] and [Foo.Field].
type ValidLocal struct{}

// Inner is embedded in Outer.
type Inner struct{ EmbeddedField int }

// Method on Inner.
func (Inner) EmbeddedMethod() {}

// Outer embeds Inner.
type Outer struct{ Inner }

// ValidEmbedded references [Outer.EmbeddedField] and [Outer.EmbeddedMethod].
type ValidEmbedded struct{}

// ValidQualified references [fmt.Println], [fmt.Stringer], [math.Sin] and [math.Pi].
type ValidQualified struct{}

// ValidQualifiedMember references [strings.Builder], [strings.Builder.Reset] and [strings.Builder.WriteString].
type ValidQualifiedMember struct{}

// ValidPackageOnly references [fmt], [math], [net/http] and [net/http.Handler].
type ValidPackageOnly struct{}

// Builtins references [int], [error], [len], [nil], [true], [string], [any].
type Builtins struct{}

// NotLinks references [foo bar], [Foo-Bar], [pkg Foo] and [Foo.Bar Baz].
type NotLinks struct{}
