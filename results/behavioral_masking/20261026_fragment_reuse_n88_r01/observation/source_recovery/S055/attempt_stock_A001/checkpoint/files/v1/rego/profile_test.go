// Copyright 2024 The OPA Authors.  All rights reserved.
// Use of this source code is governed by an Apache2
// license that can be found in the LICENSE file.

//go:build profile

package rego

import (
	"context"
	"reflect"
	"testing"
)

func TestProfileEvaluation(t *testing.T) {
	ctx := context.Background()
	module := `package authz

allow if {
	input.user == "admin"
}

deny if {
	false
}

multi if {
	false
}

multi if {
	true
}

roles contains x if {
	x := input.roles[_]
}
`
	r := New(
		Module("test.rego", module),
		Input(map[string]any{"user": "admin", "roles": []any{"a", "b", "c"}}),
		EnableRuleProfile(true),
		Query("data.authz"),
	)

	rs, err := r.Eval(ctx)
	if err != nil {
		t.Fatalf("eval: %v", err)
	}
	if len(rs) == 0 {
		t.Fatal("expected results")
	}

	profile := rs[0].Profile
	if profile == nil {
		t.Fatal("expected profile to be set")
	}

	expected := map[string]RuleStat{
		"data.authz.allow": {Evals: 1, Successes: 1},
		"data.authz.deny":  {Evals: 1, Successes: 0},
		"data.authz.multi": {Evals: 2, Successes: 1},
		"data.authz.roles": {Evals: 1, Successes: 1},
	}

	for path, want := range expected {
		stat := profile.Stat(path)
		if stat == nil {
			t.Errorf("missing stat for %s", path)
			continue
		}
		if *stat != want {
			t.Errorf("stat for %s = %v, want %v", path, *stat, want)
		}
	}

	if got := profile.Summary(); got != "profile: 4 rules, 5 evals, 3 successes" {
		t.Errorf("summary = %q", got)
	}

	if got := profile.FailedRules(); !reflect.DeepEqual(got, []string{"data.authz.deny"}) {
		t.Errorf("failed rules = %v", got)
	}

	if got := profile.SucceededRules(); !reflect.DeepEqual(got, []string{"data.authz.allow", "data.authz.multi", "data.authz.roles"}) {
		t.Errorf("succeeded rules = %v", got)
	}

	if got := profile.Packages(); !reflect.DeepEqual(got, []string{"data.authz"}) {
		t.Errorf("packages = %v", got)
	}
}

func TestProfileDisabled(t *testing.T) {
	ctx := context.Background()
	r := New(
		Module("test.rego", `package authz
allow if { true }`),
		Query("data.authz.allow"),
	)

	rs, err := r.Eval(ctx)
	if err != nil {
		t.Fatalf("eval: %v", err)
	}
	if len(rs) == 0 {
		t.Fatal("expected results")
	}
	if rs[0].Profile != nil {
		t.Fatalf("expected nil profile, got %v", rs[0].Profile)
	}
}

func TestProfilePreparedEval(t *testing.T) {
	ctx := context.Background()
	r := New(
		Module("test.rego", `package authz
allow if { input.user == "admin" }`),
		Query("data.authz.allow"),
	)

	pq, err := r.PrepareForEval(ctx)
	if err != nil {
		t.Fatalf("prepare: %v", err)
	}

	rs, err := pq.Eval(ctx, EvalInput(map[string]any{"user": "admin"}), EvalRuleProfile(true))
	if err != nil {
		t.Fatalf("eval: %v", err)
	}
	if len(rs) == 0 {
		t.Fatal("expected results")
	}
	if rs[0].Profile == nil {
		t.Fatal("expected profile to be set")
	}
	if stat := rs[0].Profile.Stat("data.authz.allow"); stat == nil || *stat != (RuleStat{Evals: 1, Successes: 1}) {
		t.Errorf("unexpected allow stat: %v", stat)
	}

	// Per-eval option should override the construction option.
	r2 := New(
		Module("test.rego", `package authz
allow if { true }`),
		EnableRuleProfile(true),
		Query("data.authz.allow"),
	)
	pq2, err := r2.PrepareForEval(ctx)
	if err != nil {
		t.Fatalf("prepare: %v", err)
	}
	rs2, err := pq2.Eval(ctx, EvalRuleProfile(false))
	if err != nil {
		t.Fatalf("eval: %v", err)
	}
	if len(rs2) == 0 {
		t.Fatal("expected results")
	}
	if rs2[0].Profile != nil {
		t.Fatalf("expected nil profile when disabled per-eval, got %v", rs2[0].Profile)
	}
}

func TestProfileMethods(t *testing.T) {
	p := NewEvalProfile()
	p.increment("data.authz.allow", 7, 4)
	p.increment("data.authz.deny", 4, 0)
	p.increment("data.other.thing", 1, 1)

	if got := p.Stat("data.authz.allow").Evals; got != 7 {
		t.Errorf("allow evals = %d", got)
	}
	if p.Stat("nope") != nil {
		t.Errorf("expected nil for untracked rule")
	}
	if got := p.RulePaths(); !reflect.DeepEqual(got, []string{"data.authz.allow", "data.authz.deny", "data.other.thing"}) {
		t.Errorf("rule paths = %v", got)
	}
	if got := p.SuccessRate("data.authz.allow"); got != 4.0/7.0 {
		t.Errorf("success rate = %v", got)
	}
	if got := p.OverallSuccessRate(); got != 5.0/12.0 {
		t.Errorf("overall success rate = %v", got)
	}
	if got := p.HotRules(4); !reflect.DeepEqual(got, []string{"data.authz.allow", "data.authz.deny"}) {
		t.Errorf("hot rules = %v", got)
	}
	if p.HotRules(100) != nil {
		t.Errorf("expected nil hot rules")
	}
	if got := p.FailedRules(); !reflect.DeepEqual(got, []string{"data.authz.deny"}) {
		t.Errorf("failed rules = %v", got)
	}
	if got := p.SucceededRules(); !reflect.DeepEqual(got, []string{"data.authz.allow", "data.other.thing"}) {
		t.Errorf("succeeded rules = %v", got)
	}
	if got := p.Packages(); !reflect.DeepEqual(got, []string{"data.authz", "data.other"}) {
		t.Errorf("packages = %v", got)
	}

	filtered := p.FilterByPackage("data.authz")
	if filtered == nil || len(filtered.RulePaths()) != 2 {
		t.Fatalf("filtered = %v", filtered)
	}
	p.increment("data.authz.allow", 1, 0)
	if got := filtered.Stat("data.authz.allow").Evals; got != 7 {
		t.Errorf("filtered profile not deep-copied: evals = %d", got)
	}

	if !p.ContainsRule("data.authz.deny") || p.ContainsRule("nope") {
		t.Errorf("contains rule returned unexpected result")
	}

	if got := p.Summary(); got != "profile: 3 rules, 13 evals, 5 successes" {
		t.Errorf("summary = %q", got)
	}

	want := "Profile:\n  data.authz.allow: evals=8 successes=4\n  data.authz.deny: evals=4 successes=0\n  data.other.thing: evals=1 successes=1\n"
	if got := p.String(); got != want {
		t.Errorf("string = %q, want %q", got, want)
	}

	other := NewEvalProfile()
	other.increment("data.authz.allow", 8, 4)
	other.increment("data.authz.deny", 4, 0)
	other.increment("data.other.thing", 1, 1)
	if !p.Equal(other) {
		t.Errorf("expected structurally equal profiles")
	}
	other.increment("data.authz.deny", 1, 0)
	if p.Equal(other) {
		t.Errorf("expected structurally different profiles")
	}

	stats := p.PackageStats()
	if stats["data.authz"].Evals != 12 || stats["data.authz"].Successes != 4 {
		t.Errorf("package stats = %v", stats)
	}
	if stats["data.other"].Evals != 1 || stats["data.other"].Successes != 1 {
		t.Errorf("package stats other = %v", stats)
	}
}

func TestProfileNilReceiver(t *testing.T) {
	var p *EvalProfile
	var s *RuleStat
	var d *ProfileDiff

	if p.Stat("x") != nil {
		t.Errorf("nil Stat")
	}
	if p.RulePaths() != nil {
		t.Errorf("nil RulePaths")
	}
	if p.SuccessRate("x") != 0 {
		t.Errorf("nil SuccessRate")
	}
	if p.OverallSuccessRate() != 0 {
		t.Errorf("nil OverallSuccessRate")
	}
	if p.HotRules(1) != nil || p.FailedRules() != nil || p.SucceededRules() != nil || p.Packages() != nil {
		t.Errorf("nil slice-returning method returned non-nil")
	}
	if p.FilterByPackage("x") != nil || p.PackageStats() != nil {
		t.Errorf("nil map-returning method returned non-nil")
	}
	if p.ContainsRule("x") {
		t.Errorf("nil ContainsRule")
	}
	if p.Summary() != "profile: disabled" {
		t.Errorf("nil Summary = %q", p.Summary())
	}
	if p.String() != "<nil>" {
		t.Errorf("nil String = %q", p.String())
	}
	if p.Diff(NewEvalProfile()) != nil {
		t.Errorf("nil Diff should be nil")
	}
	if !p.Equal(nil) {
		t.Errorf("nil Equal nil should be true")
	}
	if p.Equal(NewEvalProfile()) {
		t.Errorf("nil Equal non-nil should be false")
	}
	if s.SuccessRate() != 0 {
		t.Errorf("nil RuleStat SuccessRate")
	}
	if s.String() != "<nil>" {
		t.Errorf("nil RuleStat String = %q", s.String())
	}
	if d.HasChanges() {
		t.Errorf("nil ProfileDiff HasChanges")
	}
}

func TestProfileDiff(t *testing.T) {
	a := NewEvalProfile()
	a.increment("data.a", 2, 1)
	a.increment("data.b", 3, 2)
	a.increment("data.c", 5, 5)

	b := NewEvalProfile()
	b.increment("data.b", 3, 2)
	b.increment("data.c", 6, 5)
	b.increment("data.d", 1, 1)

	diff := a.Diff(b)
	if diff == nil || !diff.HasChanges() {
		t.Fatalf("expected changes, got %v", diff)
	}
	if len(diff.Added) != 1 || diff.Added["data.d"] == nil {
		t.Errorf("added = %v", diff.Added)
	}
	if len(diff.Removed) != 1 || diff.Removed["data.a"] == nil {
		t.Errorf("removed = %v", diff.Removed)
	}
	if len(diff.Changed) != 1 || diff.Changed["data.c"] == nil {
		t.Errorf("changed = %v", diff.Changed)
	}
	if delta := diff.Changed["data.c"]; delta.EvalsDelta != 1 || delta.SuccessesDelta != 0 {
		t.Errorf("changed delta = %+v", delta)
	}

	noDiff := a.Diff(a)
	if noDiff == nil || noDiff.HasChanges() {
		t.Errorf("expected no changes")
	}
	if noDiff.Added != nil || noDiff.Removed != nil || noDiff.Changed != nil {
		t.Errorf("expected nil fields for no changes, got %+v", noDiff)
	}

	// Diff against nil should report all receiver rules as removed.
	removed := a.Diff(nil)
	if removed == nil || !removed.HasChanges() {
		t.Fatalf("expected removed changes, got %v", removed)
	}
	if len(removed.Added) != 0 || len(removed.Changed) != 0 || len(removed.Removed) != 3 {
		t.Errorf("unexpected diff against nil: %+v", removed)
	}
}

func TestProfileMerge(t *testing.T) {
	var nilp *EvalProfile
	if nilp.Merge(nil) != nil {
		t.Errorf("both nil merge should be nil")
	}
	p := NewEvalProfile()
	p.increment("data.a", 1, 0)
	if nilp.Merge(p) != p || p.Merge(nil) != p {
		t.Errorf("merge with nil should return non-nil side")
	}
	q := NewEvalProfile()
	q.increment("data.a", 2, 2)
	q.increment("data.b", 1, 1)
	merged := p.Merge(q)
	if merged.Stat("data.a").Evals != 3 || merged.Stat("data.a").Successes != 2 {
		t.Errorf("merged a = %v", merged.Stat("data.a"))
	}
	if merged.Stat("data.b") == nil {
		t.Errorf("merged b missing")
	}
}
