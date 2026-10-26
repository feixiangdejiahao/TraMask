// Copyright 2024 The OPA Authors.  All rights reserved.
// Use of this source code is governed by an Apache2
// license that can be found in the LICENSE file.

//go:build profile

package rego_test

import (
	"context"
	"testing"

	"github.com/open-policy-agent/opa/rego"
)

func TestProfilePublicAPI(t *testing.T) {
	ctx := context.Background()
	r := rego.New(
		rego.Module("test.rego", `package authz
allow { input.user == "admin" }`),
		rego.Input(map[string]any{"user": "admin"}),
		rego.EnableRuleProfile(true),
		rego.Query("data.authz.allow"),
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
		t.Fatal("expected profile")
	}
	if profile.Summary() != "profile: 1 rules, 1 evals, 1 successes" {
		t.Errorf("summary = %q", profile.Summary())
	}
	if !profile.ContainsRule("data.authz.allow") {
		t.Errorf("allow missing from profile")
	}
	if stat := profile.Stat("data.authz.allow"); stat == nil || stat.SuccessRate() != 1 {
		t.Errorf("unexpected stat: %v", stat)
	}

	pq, err := r.PrepareForEval(ctx)
	if err != nil {
		t.Fatalf("prepare: %v", err)
	}
	rs2, err := pq.Eval(ctx, rego.EvalRuleProfile(true))
	if err != nil {
		t.Fatalf("prepared eval: %v", err)
	}
	if len(rs2) == 0 || rs2[0].Profile == nil {
		t.Fatalf("expected profile on prepared eval")
	}

	// Externally constructed profiles should support the documented methods.
	p := &rego.EvalProfile{Rules: map[string]*rego.RuleStat{
		"data.authz.allow": {Evals: 2, Successes: 1},
	}}
	if !p.ContainsRule("data.authz.allow") {
		t.Errorf("externally constructed profile missing rule")
	}
	if p.SuccessRate("data.authz.allow") != 0.5 {
		t.Errorf("success rate = %v", p.SuccessRate("data.authz.allow"))
	}
	if p.Summary() != "profile: 1 rules, 2 evals, 1 successes" {
		t.Errorf("summary = %q", p.Summary())
	}
}
