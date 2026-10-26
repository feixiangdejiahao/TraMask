// Copyright The Prometheus Authors
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package promql

import (
	"slices"
	"testing"
)

func TestCompareLabelValues(t *testing.T) {
	tests := []struct {
		name string
		a, b string
		want int
	}{
		{"equal", "foo", "foo", 0},
		{"empty untyped", "", "a", -1},
		{"leading whitespace first", " 1", "+Inf", -1},
		{"leading whitespace natural", " 10", " 2", 1},
		{"posInf before finite", "+Inf", "1", -1},
		{"finite before negInf", "1", "-Inf", -1},
		{"posInf before negInf", "+Inf", "-Inf", -1},
		{"numeric natural", "2", "10", -1},
		{"numeric scientific", "1e2", "50", 1},
		{"numeric plus sign", "+2", "3", -1},
		{"numeric equal tie-break", "1.0", "1.00", -1},
		{"bare exponent untyped", "1e", "1", 1}, // untyped after numeric
		{"nan untyped", "NaN", "1", 1},          // untyped after numeric
		{"duration", "1h", "90m", -1},
		{"duration scientific", "1e3s", "15m", 1},
		{"duration negative", "-1h", "1h", -1},
		{"bytes", "1KiB", "1KB", 1},
		{"bytes scientific", "1e3B", "1KiB", -1},
		{"semver", "1.2.3", "1.11.3", -1},
		{"semver v prefix tie-break", "1.2.3", "v1.2.3", -1},
		{"semver release after prerelease", "1.2.3", "1.2.3-rc1", 1},
		{"invalid semver untyped", "1.2.3.4.5", "1.2.3", 1},
		{"ipv4 before ipv6", "192.168.1.1", "::1", -1},
		{"ipv4 mapped is ipv6", "192.168.1.1", "::ffff:192.168.1.1", -1},
		{"cidr smaller prefix first", "10.0.0.0/8", "10.0.0.0/16", -1},
		{"cidr network bytes", "10.0.0.0/16", "11.0.0.0/16", -1},
		{"timestamp", "2020-01-01T00:00:00Z", "2021-01-01T00:00:00Z", -1},
		{"timestamp date", "2020-01-01", "2020-01-02", -1},
		{"typed before untyped", "1", "foo", -1},
		{"bare exponent vs valid exponent", "1e", "1e1", 1},
		{"nan natural order", "NaN", "nan", -1},
		{"numeric equal scientific tie-break", "1e3", "1000", -1},
		{"duration equal tie-break", "1.5e2m", "150m", -1},
		{"bytes equal tie-break", "1KiB", "1024B", -1},
		{"ipv4 mapped vs ipv6", "::ffff:192.168.1.1", "::ffff:192.168.1.2", -1},
		{"cidr ipv6 smaller prefix first", "2001:db8::/32", "2001:db8::/64", -1},
		{"timestamp equal instant tie-break", "2020-01-01T00:00:00+00:00", "2020-01-01T00:00:00Z", -1},
		{"tab leading whitespace", "\t1", "0", -1},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := CompareLabelValues(tt.a, tt.b)
			if got < 0 && tt.want < 0 {
				return
			}
			if got > 0 && tt.want > 0 {
				return
			}
			if got == 0 && tt.want == 0 {
				return
			}
			t.Fatalf("CompareLabelValues(%q, %q) = %d, want sign %d", tt.a, tt.b, got, tt.want)
		})
	}
}

func TestCompareLabelValuesOrder(t *testing.T) {
	// Verify a complete ordering across all domains.
	want := []string{
		" 2",
		" 10",
		"+Inf",
		"infinity",
		"-1e3",
		"1",
		"1.0",
		"2",
		"1e3",
		"-Inf",
		"-infinity",
		"-2h",
		"1h",
		"1.5e2m",
		"-1MiB",
		"1KB",
		"1KiB",
		"1MiB",
		"1.2.3",
		"1.11.3",
		"v2.0.0",
		"192.168.1.1",
		"::1",
		"10.0.0.0/8",
		"10.0.0.0/16",
		"2020-01-01T00:00:00Z",
		"2021-01-01T00:00:00Z",
		"",
		"1e",
		"NaN",
		"bar",
		"foo",
	}

	got := append([]string(nil), want...)
	slices.SortFunc(got, CompareLabelValues)
	if !slices.Equal(got, want) {
		t.Fatalf("sorted order mismatch:\n got: %v\nwant: %v", got, want)
	}
}

func TestCompareLabelValuesRequirements(t *testing.T) {
	tests := []struct {
		name string
		vals []string
	}{
		{
			name: "class order",
			vals: []string{
				"+Inf", "Inf", "infinity",
				"-1e3", "0", "1", "1.5", "2e10",
				"-Inf", "-infinity",
				"-1h", "1h", "1.5e2m", "1d",
				"-1MiB", "1KB", "1KiB", "1.5e3MiB",
				"1.2.3", "1.11.3", "v2.0.0",
				"10.0.0.1", "192.168.1.1", "::1", "2001:db8::1",
				"10.0.0.0/8", "10.0.0.0/16", "2001:db8::/32",
				"2020-01-01T00:00:00Z", "2020-06-01T00:00:00Z", "2021-01-01T00:00:00Z",
				"", "1e", "NaN", "bar", "foo",
			},
		},
		{
			name: "leading whitespace",
			vals: []string{" 1.2.3", " 1h", " 2", " 10"},
		},
		{
			name: "duration scientific and signed",
			vals: []string{"-1e3h", "-2h", "-1h", "0s", "1h", "1.5h", "1e3h", "1e4h"},
		},
		{
			name: "bytes scientific and signed",
			vals: []string{"-1e3MiB", "-1MiB", "0B", "1KB", "1KiB", "1e6B", "1e3KiB"},
		},
		{
			name: "semver prerelease",
			vals: []string{"1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"},
		},
		{
			name: "cidr equal network different prefix",
			vals: []string{"192.168.0.0/8", "192.168.0.0/16", "192.168.0.0/24", "192.168.0.0/32"},
		},
		{
			name: "ipv4 before ipv6 and mapped",
			vals: []string{"0.0.0.0", "192.168.1.1", "255.255.255.255", "::", "::1", "::ffff:192.168.1.1", "2001:db8::1"},
		},
		{
			name: "timestamp formats",
			vals: []string{"2020-01-01", "2020-01-01 00:00:00", "2020-01-01T00:00:00Z", "2020-01-01T01:00:00+01:00", "2020-06-01", "2021-01-01T00:00:00.123Z"},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// The values in tt.vals are already in expected sorted order; verify.
			for i := 1; i < len(tt.vals); i++ {
				if CompareLabelValues(tt.vals[i-1], tt.vals[i]) >= 0 {
					t.Fatalf("expected %q < %q", tt.vals[i-1], tt.vals[i])
				}
			}
		})
	}
}

func TestCompareLabelValuesIsTotalOrder(t *testing.T) {
	values := []string{
		" 1", " 10", " 2",
		"+Inf", "-Inf", "1", "-1", "1e3", "1e", "NaN", "",
		"1h", "1.5e2m", "-2h",
		"1KiB", "1KB", "-1MiB",
		"1.2.3", "v1.2.3", "1.2.3-rc1",
		"192.168.1.1", "::1", "::ffff:192.168.1.1",
		"10.0.0.0/8", "10.0.0.0/16",
		"2020-01-01T00:00:00Z", "2021-01-01T00:00:00Z",
		"foo", "bar",
	}
	for _, a := range values {
		for _, b := range values {
			ab := CompareLabelValues(a, b)
			ba := CompareLabelValues(b, a)
			if a == b {
				if ab != 0 || ba != 0 {
					t.Fatalf("CompareLabelValues(%q, %q) = %d, %d; want 0,0", a, b, ab, ba)
				}
				continue
			}
			if ab == 0 || ba == 0 {
				t.Fatalf("CompareLabelValues(%q, %q) = %d, %d; want nonzero", a, b, ab, ba)
			}
			if ab != -ba {
				t.Fatalf("CompareLabelValues(%q, %q) = %d, reverse = %d; not antisymmetric", a, b, ab, ba)
			}

		}
	}
}

func TestNaturalCompareLeadingZeroTie(t *testing.T) {
	if got := CompareLabelValues("a1", "a01"); got == 0 {
		t.Fatal("CompareLabelValues(a1, a01) returned 0; want nonzero total order")
	}
	if got := CompareLabelValues("a01", "a1"); got == 0 {
		t.Fatal("CompareLabelValues(a01, a1) returned 0; want nonzero total order")
	}
	// Shorter representation sorts first.
	if CompareLabelValues("a1", "a01") >= 0 {
		t.Fatal("expected a1 < a01")
	}
}
