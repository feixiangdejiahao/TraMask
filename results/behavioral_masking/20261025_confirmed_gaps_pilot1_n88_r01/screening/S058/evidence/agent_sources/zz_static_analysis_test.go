//go:build analyze

package participle_test

import (
	"strings"
	"testing"

	"github.com/alecthomas/assert/v2"

	"github.com/alecthomas/participle/v2"
)

func mustZZAnalyze[G any](t *testing.T, options ...participle.Option) *participle.AnalysisReport {
	t.Helper()
	p, err := participle.Build[G](options...)
	assert.NoError(t, err)
	report, err := p.Analyze()
	assert.NoError(t, err)
	return report
}

func TestZZStaticAnalyzeFirstFirst(t *testing.T) {
	type Grammar struct {
		A string `@Ident | @Ident`
	}
	report := mustZZAnalyze[Grammar](t)
	assert.True(t, report.HasType(participle.ConflictFirstFirst), report.String())
	assert.True(t, report.HasType(participle.ConflictUnreachable), report.String())
	assert.Equal(t, 1, report.ConflictCount(participle.ConflictFirstFirst))
	assert.Equal(t, 1, report.ConflictCount(participle.ConflictUnreachable))
	ff := report.FilterByType(participle.ConflictFirstFirst)
	assert.Equal(t, 1, len(ff.Warnings()))
	assert.Equal(t, 0, len(ff.Errors()))
	assert.Equal(t, "warning", participle.SeverityWarning.String())
	assert.Equal(t, "first/first", participle.ConflictFirstFirst.String())
}

func TestZZStaticAnalyzeNoConflictLiteralsAndTypes(t *testing.T) {
	type Grammar struct {
		A string `"if" | "while"`
	}
	assert.True(t, mustZZAnalyze[Grammar](t).IsClean())

	type Grammar2 struct {
		A string `"keyword" | @Ident`
	}
	assert.True(t, mustZZAnalyze[Grammar2](t).IsClean(), mustZZAnalyze[Grammar2](t).String())
}

func TestZZStaticAnalyzeFirstFollow(t *testing.T) {
	type Grammar struct {
		A string `@Ident? @Ident`
	}
	report := mustZZAnalyze[Grammar](t)
	assert.True(t, report.HasType(participle.ConflictFirstFollow), report.String())
	assert.Equal(t, 1, report.ConflictCount(participle.ConflictFirstFollow))
	assert.Equal(t, "first/follow", participle.ConflictFirstFollow.String())

	type Grammar2 struct {
		A string `@Ident* @Ident`
	}
	assert.True(t, mustZZAnalyze[Grammar2](t).HasType(participle.ConflictFirstFollow))

	type Grammar3 struct {
		A string `@Ident+ @Ident`
	}
	assert.True(t, mustZZAnalyze[Grammar3](t).HasType(participle.ConflictFirstFollow))

	type Grammar4 struct {
		A string `@Ident+`
	}
	assert.True(t, mustZZAnalyze[Grammar4](t).IsClean(), mustZZAnalyze[Grammar4](t).String())
}

func TestZZStaticAnalyzeEpsilonThroughEmbedding(t *testing.T) {
	type Inner struct {
		A string `@Ident?`
	}
	type Outer struct {
		Inner Inner  `@@`
		B     string `@Ident`
	}
	report := mustZZAnalyze[Outer](t)
	assert.True(t, report.HasType(participle.ConflictFirstFollow), report.String())
	if len(report.Conflicts) > 0 {
		c := report.Conflicts[0]
		assert.Equal(t, "Inner", c.Location.TypeName)
	}
}

func TestZZStaticAnalyzeLookaheadSuppression(t *testing.T) {
	type Grammar struct {
		A string `(?= @Ident | @Ident) @Ident`
	}
	assert.True(t, mustZZAnalyze[Grammar](t).IsClean(), mustZZAnalyze[Grammar](t).String())
}

func TestZZStaticAnalyzeNegationNoConflicts(t *testing.T) {
	type Grammar struct {
		A string `!(@Ident | @Ident)`
	}
	assert.True(t, mustZZAnalyze[Grammar](t).IsClean(), mustZZAnalyze[Grammar](t).String())
}

func TestZZStaticAnalyzeReportMethods(t *testing.T) {
	type Grammar struct {
		A string `@Ident | @Ident`
		B string `@Ident? @Ident`
	}
	report := mustZZAnalyze[Grammar](t)
	assert.False(t, report.IsClean())
	assert.Equal(t, "error", participle.SeverityError.String())
	assert.Equal(t, "unreachable", participle.ConflictUnreachable.String())

	summary := report.Summary()
	assert.True(t, strings.Contains(summary, "conflict(s)"), summary)
	assert.True(t, strings.Contains(summary, "first/first"), summary)
	assert.True(t, strings.Contains(summary, "first/follow"), summary)
	assert.True(t, strings.Contains(summary, "unreachable"), summary)

	filtered := report.FilterByType(participle.ConflictFirstFollow)
	assert.Equal(t, 1, len(filtered.Conflicts))
	assert.True(t, filtered.HasType(participle.ConflictFirstFollow))

	merged := report.Merge(report)
	assert.Equal(t, len(report.Conflicts), len(merged.Conflicts))
	deduped := report.Dedup()
	assert.Equal(t, len(report.Conflicts), len(deduped.Conflicts))
}

func TestZZStaticAnalyzeSuppressConflictType(t *testing.T) {
	type Grammar struct {
		A string `@Ident | @Ident`
	}
	p, err := participle.Build[Grammar]()
	assert.NoError(t, err)
	report, err := p.AnalyzeWithOptions(participle.SuppressConflictType(participle.ConflictFirstFirst))
	assert.NoError(t, err)
	assert.False(t, report.HasType(participle.ConflictFirstFirst))
	assert.True(t, report.HasType(participle.ConflictUnreachable))
}

func TestZZStaticStrictModeConflicts(t *testing.T) {
	type Grammar struct {
		A string `@Ident | @Ident`
	}
	_, err := participle.Build[Grammar](participle.StrictMode())
	assert.Error(t, err)
	assert.True(t, strings.Contains(err.Error(), "conflict"), err.Error())

	type Clean struct {
		A string `"if" | "while"`
	}
	_, err = participle.Build[Clean](participle.StrictMode())
	assert.NoError(t, err)
}

func TestZZStaticConflictStringNonEmptyFields(t *testing.T) {
	type Grammar struct {
		A string `@Ident | @Ident`
	}
	report := mustZZAnalyze[Grammar](t)
	for _, c := range report.Conflicts {
		assert.True(t, c.Message != "")
		assert.True(t, len(c.GrammarSnippet) >= 4, c.GrammarSnippet)
		assert.True(t, c.Example != "")
		assert.True(t, strings.Contains(c.Suggestion, " "), c.Suggestion)
		assert.True(t, strings.Contains(c.String(), c.Type.String()))
		assert.True(t, strings.Contains(c.String(), c.Location.String()))
	}
}

func TestZZStaticAnalyzeFirstFollowLiteral(t *testing.T) {
	type Grammar struct {
		A string `"a"? "a"`
	}
	report := mustZZAnalyze[Grammar](t)
	assert.True(t, report.HasType(participle.ConflictFirstFollow), report.String())
	if len(report.Conflicts) > 0 {
		c := report.Conflicts[0]
		assert.True(t, len(c.GrammarSnippet) >= 4, c.GrammarSnippet)
		assert.True(t, c.Example != "", "example must be non-empty")
		assert.True(t, c.Suggestion != "", "suggestion must be non-empty")
	}
}

func TestZZStaticAnalyzeRecursiveGrammar(t *testing.T) {
	type Expr struct {
		Left  int    `@Int`
		Op    string `(@("+" | "-"))?`
		Right *Expr  `@@?`
	}
	// Must not hang or panic; recursion through @@ must be handled.
	report := mustZZAnalyze[Expr](t)
	_ = report
}

type ZZAnalyzeUnion interface{ analyzeUnion() }

type ZZAnalyzeUnionA struct {
	A string `@Ident`
}

func (ZZAnalyzeUnionA) analyzeUnion() {}

type ZZAnalyzeUnionB struct {
	B string `@Ident`
}

func (ZZAnalyzeUnionB) analyzeUnion() {}

func TestZZAnalyzeUnionMembers(t *testing.T) {
	type Grammar struct {
		U ZZAnalyzeUnion `@@`
	}
	p, err := participle.Build[Grammar](participle.Union[ZZAnalyzeUnion](ZZAnalyzeUnionA{}, ZZAnalyzeUnionB{}))
	assert.NoError(t, err)
	report, err := p.Analyze()
	assert.NoError(t, err)
	_ = report
}

func TestZZStaticAnalyzeSummary(t *testing.T) {
	type Clean struct {
		A string `"if" | "while"`
	}
	report := mustZZAnalyze[Clean](t)
	assert.Equal(t, "no conflicts detected", report.Summary())
	assert.True(t, report.String() != "")
	assert.Equal(t, 0, report.ConflictCount(participle.ConflictFirstFirst))
	assert.Equal(t, 0, report.ConflictCount(participle.ConflictFirstFollow))
	assert.Equal(t, 0, report.ConflictCount(participle.ConflictUnreachable))

	type Dirty struct {
		A string `@Ident | @Ident`
	}
	report = mustZZAnalyze[Dirty](t)
	assert.Equal(t, "2 conflict(s): 1 first/first, 0 first/follow, 1 unreachable", report.Summary())
}

func TestZZStaticStrictModeIndependentOfSuppress(t *testing.T) {
	type Grammar struct {
		A string `@Ident? @Ident`
	}
	_, err := participle.Build[Grammar](participle.StrictMode(), participle.UseLookahead(3))
	assert.Error(t, err)
	assert.True(t, strings.Contains(err.Error(), "conflict"), err.Error())
}
