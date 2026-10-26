package trafficpolicy

import (
	"testing"
	"time"

	envoyroutev3 "github.com/envoyproxy/go-control-plane/envoy/config/route/v3"
	envoy_type_matcher_v3 "github.com/envoyproxy/go-control-plane/envoy/type/matcher/v3"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/durationpb"

	"github.com/kgateway-dev/kgateway/v2/api/v1alpha1/kgateway"
	"github.com/kgateway-dev/kgateway/v2/pkg/pluginsdk/ir"
	"github.com/kgateway-dev/kgateway/v2/pkg/pluginsdk/policy"
)

func TestConstructConsistentHash(t *testing.T) {
	t.Run("nil config", func(t *testing.T) {
		out := &trafficPolicySpecIr{}
		require.NoError(t, constructConsistentHash(kgateway.TrafficPolicySpec{}, out))
		assert.Nil(t, out.consistentHash)
	})

	t.Run("empty config", func(t *testing.T) {
		out := &trafficPolicySpecIr{}
		require.NoError(t, constructConsistentHash(kgateway.TrafficPolicySpec{
			ConsistentHash: &kgateway.ConsistentHashConfig{},
		}, out))
		require.NotNil(t, out.consistentHash)
		assert.False(t, out.consistentHash.disable)
		assert.Empty(t, out.consistentHash.headers)
		assert.Empty(t, out.consistentHash.cookies)
		assert.Nil(t, out.consistentHash.sourceIp)
	})

	t.Run("full config", func(t *testing.T) {
		terminal := true
		out := &trafficPolicySpecIr{}
		require.NoError(t, constructConsistentHash(kgateway.TrafficPolicySpec{
			ConsistentHash: &kgateway.ConsistentHashConfig{
				Headers: []kgateway.ConsistentHashHeader{
					{
						HeaderName: "x-user",
						RegexRewrite: &kgateway.ConsistentHashRegexRewrite{
							Pattern:      "^(.*)-suffix$",
							Substitution: "$1",
						},
						Terminal: &terminal,
					},
				},
				Cookies: []kgateway.ConsistentHashCookie{
					{
						Name:     "session",
						TTL:      strPtr("1h30m"),
						Path:     strPtr("/"),
						Terminal: &terminal,
					},
				},
				QueryParameters: []kgateway.ConsistentHashQueryParameter{{Name: "user_id"}},
				FilterState:     []kgateway.ConsistentHashFilterState{{Key: "state_key"}},
				SourceIp:        &kgateway.ConsistentHashSourceIp{Terminal: &terminal},
			},
		}, out))
		require.NotNil(t, out.consistentHash)
		require.Len(t, out.consistentHash.headers, 1)
		assert.Equal(t, "x-user", out.consistentHash.headers[0].headerName)
		require.NotNil(t, out.consistentHash.headers[0].regexRewrite)
		assert.Equal(t, "^(.*)-suffix$", out.consistentHash.headers[0].regexRewrite.GetPattern().GetRegex())
		require.Len(t, out.consistentHash.cookies, 1)
		require.NotNil(t, out.consistentHash.cookies[0].ttl)
		assert.Equal(t, 90*time.Minute, *out.consistentHash.cookies[0].ttl)
		require.Len(t, out.consistentHash.queryParameters, 1)
		require.Len(t, out.consistentHash.filterState, 1)
		require.NotNil(t, out.consistentHash.sourceIp)
	})

	t.Run("integer seconds ttl", func(t *testing.T) {
		out := &trafficPolicySpecIr{}
		require.NoError(t, constructConsistentHash(kgateway.TrafficPolicySpec{
			ConsistentHash: &kgateway.ConsistentHashConfig{
				Cookies: []kgateway.ConsistentHashCookie{{Name: "session", TTL: strPtr("3600")}},
			},
		}, out))
		require.NotNil(t, out.consistentHash.cookies[0].ttl)
		assert.Equal(t, time.Hour, *out.consistentHash.cookies[0].ttl)
	})

	t.Run("invalid ttl", func(t *testing.T) {
		out := &trafficPolicySpecIr{}
		err := constructConsistentHash(kgateway.TrafficPolicySpec{
			ConsistentHash: &kgateway.ConsistentHashConfig{
				Cookies: []kgateway.ConsistentHashCookie{{Name: "session", TTL: strPtr("not-a-duration")}},
			},
		}, out)
		require.Error(t, err)
	})

	t.Run("disable", func(t *testing.T) {
		out := &trafficPolicySpecIr{}
		require.NoError(t, constructConsistentHash(kgateway.TrafficPolicySpec{
			ConsistentHash: &kgateway.ConsistentHashConfig{
				Disable: true,
				Headers: []kgateway.ConsistentHashHeader{{HeaderName: "x-user"}},
			},
		}, out))
		require.NotNil(t, out.consistentHash)
		assert.True(t, out.consistentHash.disable)
		assert.Empty(t, out.consistentHash.headers)
	})

	t.Run("deduplicates headers case-insensitively preserving first casing", func(t *testing.T) {
		out := &trafficPolicySpecIr{}
		require.NoError(t, constructConsistentHash(kgateway.TrafficPolicySpec{
			ConsistentHash: &kgateway.ConsistentHashConfig{
				Headers: []kgateway.ConsistentHashHeader{
					{HeaderName: "X-User"},
					{HeaderName: "x-user"},
				},
			},
		}, out))
		require.Len(t, out.consistentHash.headers, 1)
		assert.Equal(t, "X-User", out.consistentHash.headers[0].headerName)
	})
}

func TestBuildHashPolicies(t *testing.T) {
	t.Run("empty config defaults to sourceIp", func(t *testing.T) {
		policies := buildHashPolicies(&consistentHashIR{})
		require.Len(t, policies, 1)
		assert.True(t, policies[0].GetConnectionProperties().GetSourceIp())
		assert.False(t, policies[0].GetTerminal())
	})

	t.Run("disable produces no policies", func(t *testing.T) {
		assert.Nil(t, buildHashPolicies(&consistentHashIR{disable: true}))
	})

	t.Run("canonical order", func(t *testing.T) {
		ch := &consistentHashIR{
			sourceIp:        &consistentHashSourceIpIR{},
			headers:         []*consistentHashHeaderIR{{headerName: "x-user"}},
			cookies:         []*consistentHashCookieIR{{name: "session"}},
			queryParameters: []*consistentHashQueryParameterIR{{name: "user_id"}},
			filterState:     []*consistentHashFilterStateIR{{key: "state_key"}},
		}
		policies := buildHashPolicies(ch)
		require.Len(t, policies, 5)
		assert.NotNil(t, policies[0].GetHeader())
		assert.NotNil(t, policies[1].GetCookie())
		assert.NotNil(t, policies[2].GetQueryParameter())
		assert.NotNil(t, policies[3].GetFilterState())
		assert.NotNil(t, policies[4].GetConnectionProperties())
	})

	t.Run("regex rewrite and cookie attributes", func(t *testing.T) {
		ch := &consistentHashIR{
			headers: []*consistentHashHeaderIR{{
				headerName: "x-user",
				regexRewrite: &envoy_type_matcher_v3.RegexMatchAndSubstitute{
					Pattern:      &envoy_type_matcher_v3.RegexMatcher{Regex: "^(.*)-suffix$"},
					Substitution: "$1",
				},
				terminal: true,
			}},
			cookies: []*consistentHashCookieIR{{
				name: "session",
				ttl:  durationPtr(time.Hour),
				path: "/",
				attributes: []consistentHashCookieAttributeIR{
					{name: "SameSite", value: "Strict"},
					{name: "Secure"},
				},
			}},
		}
		policies := buildHashPolicies(ch)
		require.Len(t, policies, 2)
		header := policies[0].GetHeader()
		require.NotNil(t, header)
		assert.Equal(t, "^(.*)-suffix$", header.GetRegexRewrite().GetPattern().GetRegex())
		assert.True(t, policies[0].GetTerminal())
		cookie := policies[1].GetCookie()
		require.NotNil(t, cookie)
		assert.Equal(t, durationpb.New(time.Hour), cookie.GetTtl())
		assert.Equal(t, "/", cookie.GetPath())
		require.Len(t, cookie.GetAttributes(), 2)
		assert.Equal(t, "SameSite", cookie.GetAttributes()[0].GetName())
		assert.Equal(t, "Strict", cookie.GetAttributes()[0].GetValue())
		assert.Equal(t, "Secure", cookie.GetAttributes()[1].GetName())
	})
}

func TestApplyConsistentHash(t *testing.T) {
	t.Run("nil config does nothing", func(t *testing.T) {
		route := &envoyroutev3.Route{Action: &envoyroutev3.Route_Route{Route: &envoyroutev3.RouteAction{}}}
		applyConsistentHash(nil, route)
		assert.Empty(t, route.GetRoute().GetHashPolicy())
	})

	t.Run("applies hash policies", func(t *testing.T) {
		route := &envoyroutev3.Route{Action: &envoyroutev3.Route_Route{Route: &envoyroutev3.RouteAction{}}}
		applyConsistentHash(&consistentHashIR{headers: []*consistentHashHeaderIR{{headerName: "x-user"}}}, route)
		require.Len(t, route.GetRoute().GetHashPolicy(), 1)
		assert.Equal(t, "x-user", route.GetRoute().GetHashPolicy()[0].GetHeader().GetHeaderName())
	})

	t.Run("disable clears existing hash policies", func(t *testing.T) {
		route := &envoyroutev3.Route{
			Action: &envoyroutev3.Route_Route{
				Route: &envoyroutev3.RouteAction{
					HashPolicy: []*envoyroutev3.RouteAction_HashPolicy{{
						PolicySpecifier: &envoyroutev3.RouteAction_HashPolicy_Header_{
							Header: &envoyroutev3.RouteAction_HashPolicy_Header{HeaderName: "x-user"},
						},
					}},
				},
			},
		}
		applyConsistentHash(&consistentHashIR{disable: true}, route)
		assert.Empty(t, route.GetRoute().GetHashPolicy())
	})
}

func TestMergeConsistentHash(t *testing.T) {
	ref := &ir.AttachedPolicyRef{Name: "p2"}

	t.Run("deep merge unions arrays with higher priority first", func(t *testing.T) {
		p1 := &TrafficPolicy{spec: trafficPolicySpecIr{consistentHash: &consistentHashIR{
			headers:  []*consistentHashHeaderIR{{headerName: "x-user"}},
			sourceIp: &consistentHashSourceIpIR{terminal: true},
		}}}
		p2 := &TrafficPolicy{spec: trafficPolicySpecIr{consistentHash: &consistentHashIR{
			headers: []*consistentHashHeaderIR{{headerName: "x-user"}, {headerName: "X-Account"}},
			cookies: []*consistentHashCookieIR{{name: "session"}},
		}}}
		origins := ir.MergeOrigins{}
		mergeConsistentHash(p1, p2, ref, nil, policy.MergeOptions{Strategy: policy.AugmentedDeepMerge}, origins, TrafficPolicyMergeOpts{})
		require.NotNil(t, p1.spec.consistentHash)
		assert.Equal(t, []string{"x-user", "X-Account"}, headersNames(p1.spec.consistentHash.headers))
		require.Len(t, p1.spec.consistentHash.cookies, 1)
		// sourceIp retains higher-priority value even when lower priority leaves it unset.
		require.NotNil(t, p1.spec.consistentHash.sourceIp)
		assert.True(t, p1.spec.consistentHash.sourceIp.terminal)
		_, ok := origins["consistentHash"]
		assert.True(t, ok)
	})

	t.Run("overridable deep merge prefers p2", func(t *testing.T) {
		p1 := &TrafficPolicy{spec: trafficPolicySpecIr{consistentHash: &consistentHashIR{
			headers: []*consistentHashHeaderIR{{headerName: "x-user"}},
		}}}
		p2 := &TrafficPolicy{spec: trafficPolicySpecIr{consistentHash: &consistentHashIR{
			headers: []*consistentHashHeaderIR{{headerName: "X-Account"}},
		}}}
		origins := ir.MergeOrigins{}
		mergeConsistentHash(p1, p2, ref, nil, policy.MergeOptions{Strategy: policy.OverridableDeepMerge}, origins, TrafficPolicyMergeOpts{})
		require.NotNil(t, p1.spec.consistentHash)
		assert.Equal(t, []string{"X-Account", "x-user"}, headersNames(p1.spec.consistentHash.headers))
	})

	t.Run("shallow merge prefers p1", func(t *testing.T) {
		p1 := &TrafficPolicy{spec: trafficPolicySpecIr{consistentHash: &consistentHashIR{
			headers: []*consistentHashHeaderIR{{headerName: "x-user"}},
		}}}
		p2 := &TrafficPolicy{spec: trafficPolicySpecIr{consistentHash: &consistentHashIR{
			headers: []*consistentHashHeaderIR{{headerName: "x-account"}},
		}}}
		origins := ir.MergeOrigins{}
		mergeConsistentHash(p1, p2, ref, nil, policy.MergeOptions{Strategy: policy.AugmentedShallowMerge}, origins, TrafficPolicyMergeOpts{})
		assert.Equal(t, []string{"x-user"}, headersNames(p1.spec.consistentHash.headers))
	})

	t.Run("higher priority disable suppresses lower priority", func(t *testing.T) {
		p1 := &TrafficPolicy{spec: trafficPolicySpecIr{consistentHash: &consistentHashIR{disable: true}}}
		p2 := &TrafficPolicy{spec: trafficPolicySpecIr{consistentHash: &consistentHashIR{
			headers: []*consistentHashHeaderIR{{headerName: "x-user"}},
		}}}
		origins := ir.MergeOrigins{}
		mergeConsistentHash(p1, p2, ref, nil, policy.MergeOptions{Strategy: policy.AugmentedDeepMerge}, origins, TrafficPolicyMergeOpts{})
		require.NotNil(t, p1.spec.consistentHash)
		assert.True(t, p1.spec.consistentHash.disable)
		assert.Empty(t, p1.spec.consistentHash.headers)
		assert.Empty(t, origins["consistentHash"])
	})

	t.Run("merge settings deep merge", func(t *testing.T) {
		p1 := &TrafficPolicy{spec: trafficPolicySpecIr{consistentHash: &consistentHashIR{
			headers: []*consistentHashHeaderIR{{headerName: "x-user"}},
		}}}
		p2 := &TrafficPolicy{spec: trafficPolicySpecIr{consistentHash: &consistentHashIR{
			headers: []*consistentHashHeaderIR{{headerName: "x-account"}},
		}}}
		origins := ir.MergeOrigins{}
		mergeConsistentHash(p1, p2, ref, nil, policy.MergeOptions{Strategy: policy.AugmentedShallowMerge}, origins, TrafficPolicyMergeOpts{ConsistentHash: "DeepMerge"})
		assert.Equal(t, []string{"x-user", "x-account"}, headersNames(p1.spec.consistentHash.headers))
	})
}

func headersNames(headers []*consistentHashHeaderIR) []string {
	out := make([]string, 0, len(headers))
	for _, h := range headers {
		out = append(out, h.headerName)
	}
	return out
}

func strPtr(s string) *string { return &s }

func durationPtr(d time.Duration) *time.Duration { return &d }

func TestMergePoliciesConsistentHashDeepMerge(t *testing.T) {
	p1 := &TrafficPolicy{spec: trafficPolicySpecIr{consistentHash: &consistentHashIR{
		headers: []*consistentHashHeaderIR{{headerName: "x-user"}},
	}}}
	p2 := &TrafficPolicy{spec: trafficPolicySpecIr{consistentHash: &consistentHashIR{
		headers: []*consistentHashHeaderIR{{headerName: "x-account"}},
		cookies: []*consistentHashCookieIR{{name: "session"}},
	}}}

	policies := []ir.PolicyAtt{
		{PolicyIr: p1, PolicyRef: &ir.AttachedPolicyRef{Name: "p1"}},
		{PolicyIr: p2, PolicyRef: &ir.AttachedPolicyRef{Name: "p2"}},
	}

	merged := policy.MergePolicies(policies, mergeTrafficPolicies, `{"trafficPolicy":{"consistentHash":"DeepMerge"}}`)
	require.NotNil(t, merged.PolicyIr)
	mergedPolicy, ok := merged.PolicyIr.(*TrafficPolicy)
	require.True(t, ok)
	require.NotNil(t, mergedPolicy.spec.consistentHash)
	assert.Equal(t, []string{"x-user", "x-account"}, headersNames(mergedPolicy.spec.consistentHash.headers))
	require.Len(t, mergedPolicy.spec.consistentHash.cookies, 1)
	assert.Contains(t, merged.MergeOrigins["consistentHash"], policies[1].PolicyRef.ID())
}

func TestConsistentHashIREquals(t *testing.T) {
	a := &consistentHashIR{
		disable:  false,
		headers:  []*consistentHashHeaderIR{{headerName: "x-user", terminal: true}},
		cookies:  []*consistentHashCookieIR{{name: "session", ttl: durationPtr(time.Hour)}},
		sourceIp: &consistentHashSourceIpIR{terminal: true},
	}
	b := &consistentHashIR{
		disable:  false,
		headers:  []*consistentHashHeaderIR{{headerName: "x-user", terminal: true}},
		cookies:  []*consistentHashCookieIR{{name: "session", ttl: durationPtr(time.Hour)}},
		sourceIp: &consistentHashSourceIpIR{terminal: true},
	}
	assert.True(t, a.Equals(b))

	b.headers[0].terminal = false
	assert.False(t, a.Equals(b))
	assert.False(t, a.Equals(nil))
}

func TestConsistentHashIRValidate(t *testing.T) {
	valid := &consistentHashIR{
		headers: []*consistentHashHeaderIR{{
			headerName: "x-user",
			regexRewrite: &envoy_type_matcher_v3.RegexMatchAndSubstitute{
				Pattern: &envoy_type_matcher_v3.RegexMatcher{Regex: "^foo(.*)$"},
			},
		}},
	}
	require.NoError(t, valid.Validate())

	invalid := &consistentHashIR{
		headers: []*consistentHashHeaderIR{{
			headerName: "x-user",
			regexRewrite: &envoy_type_matcher_v3.RegexMatchAndSubstitute{
				Pattern: &envoy_type_matcher_v3.RegexMatcher{Regex: "[invalid("},
			},
		}},
	}
	require.Error(t, invalid.Validate())
	assert.Contains(t, invalid.Validate().Error(), "invalid regex pattern")
}

func TestMergeConsistentHashSourceIpRetainsHigherPriorityEvenWhenUnset(t *testing.T) {
	p1 := &TrafficPolicy{spec: trafficPolicySpecIr{consistentHash: &consistentHashIR{
		headers: []*consistentHashHeaderIR{{headerName: "x-user"}},
	}}}
	p2 := &TrafficPolicy{spec: trafficPolicySpecIr{consistentHash: &consistentHashIR{
		sourceIp: &consistentHashSourceIpIR{terminal: true},
	}}}
	mergeConsistentHash(p1, p2, &ir.AttachedPolicyRef{Name: "p2"}, nil, policy.MergeOptions{Strategy: policy.AugmentedDeepMerge}, ir.MergeOrigins{}, TrafficPolicyMergeOpts{})
	require.NotNil(t, p1.spec.consistentHash)
	assert.Nil(t, p1.spec.consistentHash.sourceIp)
}
