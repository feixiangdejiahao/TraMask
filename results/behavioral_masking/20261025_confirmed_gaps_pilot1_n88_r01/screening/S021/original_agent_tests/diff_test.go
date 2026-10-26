package etree

import (
	"testing"
)

func mustDoc(t *testing.T, s string) *Document {
	t.Helper()
	d := NewDocument()
	if err := d.ReadFromString(s); err != nil {
		t.Fatalf("parse error: %v", err)
	}
	return d
}

func docStr(t *testing.T, d *Document) string {
	t.Helper()
	d.Indent(NoIndent)
	s, err := d.WriteToString()
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func TestDeepEqual(t *testing.T) {
	var nilEl *Element
	if !nilEl.DeepEqual(nil) {
		t.Error("nil vs nil should be equal")
	}
	a := NewElement("a")
	if nilEl.DeepEqual(a) || a.DeepEqual(nil) {
		t.Error("nil vs non-nil should not be equal")
	}
	b := NewElement("a")
	if !a.DeepEqual(b) {
		t.Error("empty same-tag elements should be equal")
	}
	a.CreateAttr("x", "1")
	if a.DeepEqual(b) {
		t.Error("attr difference should be unequal")
	}
	b.CreateAttr("x", "1")
	if !a.DeepEqual(b) {
		t.Error("same attrs should be equal")
	}
	a.CreateElement("child").SetText("hi")
	if a.DeepEqual(b) {
		t.Error("child difference should be unequal")
	}
	b.CreateElement("child").SetText("hi")
	if !a.DeepEqual(b) {
		t.Error("same children should be equal")
	}
	if !ElementsDeepEqual(a, b) {
		t.Error("ElementsDeepEqual should match")
	}
	if !ElementsDeepEqual(nil, nil) {
		t.Error("ElementsDeepEqual nil nil")
	}
	if ElementsDeepEqual(nil, a) {
		t.Error("ElementsDeepEqual nil nonnil")
	}
}

func TestDiffApplyRoundTrip(t *testing.T) {
	cases := []struct{ base, target string }{
		{"<root/>", "<root/>"},
		{"<root/>", "<root><child/></root>"},
		{"<root><child/></root>", "<root/>"},
		{"<root><a/><b/><c/></root>", "<root><a/><c/></root>"},
		{"<root><a>1</a><b>2</b></root>", "<root><a>x</a><b>2</b><c/></root>"},
		{"<root attr=\"1\"/>", "<root attr=\"2\"/>"},
		{"<root/>", "<root attr=\"1\"/>"},
		{"<root attr=\"1\"/>", "<root/>"},
		{"<root><a x=\"1\"><b/></a></root>", "<root><a x=\"2\"><b/><c/></a></root>"},
		{"<a/>", "<b/>"},
		{"<root><a/><b/></root>", "<root><b/><a/></root>"},
	}
	for _, c := range cases {
		base := mustDoc(t, c.base)
		target := mustDoc(t, c.target)
		ops, err := Diff(base, target, DefaultDiffOptions())
		if err != nil {
			t.Fatalf("diff error for %s -> %s: %v", c.base, c.target, err)
		}
		patch := GeneratePatch(ops)
		patched := base.Copy()
		if err := ApplyPatch(patched, patch); err != nil {
			t.Fatalf("apply error for %s -> %s: %v (patch=%s)", c.base, c.target, err, docStr(t, patch))
		}
		got := docStr(t, patched)
		want := docStr(t, target)
		if got != want {
			t.Errorf("roundtrip failed %s -> %s\ngot:  %s\nwant: %s\nops: %+v\npatch: %s",
				c.base, c.target, got, want, ops, docStr(t, patch))
		}
	}
}

func TestGeneratePatchFormat(t *testing.T) {
	base := mustDoc(t, `<root><a>old</a></root>`)
	target := mustDoc(t, `<root><a>new</a><a x="1"/></root>`)
	ops, _ := Diff(base, target, DefaultDiffOptions())
	patch := GeneratePatch(ops)
	s := docStr(t, patch)
	t.Logf("patch: %s", s)
	if patch.Root().SelectAttrValue("xmlns", "") != "urn:ietf:params:xml:ns:patch-ops" {
		t.Error("missing xmlns")
	}
	// Check update text becomes replace with /text()
	found := false
	for _, op := range patch.Root().ChildElements() {
		if op.Tag == "replace" && op.SelectAttrValue("sel", "") == "/root/a[1]/text()" {
			found = true
		}
	}
	if !found {
		t.Error("expected replace sel /root/a[1]/text()")
	}
	// Check attr add on existing element: base <a/> vs target <a x="1"/>
	base2 := mustDoc(t, `<root><a/></root>`)
	target2 := mustDoc(t, `<root><a x="1"/></root>`)
	ops2, _ := Diff(base2, target2, DefaultDiffOptions())
	patch2 := GeneratePatch(ops2)
	t.Logf("patch2: %s", docStr(t, patch2))
	found = false
	for _, op := range patch2.Root().ChildElements() {
		if op.Tag == "add" && op.SelectAttrValue("type", "") == "attribute" && op.SelectAttrValue("name", "") == "x" {
			found = true
		}
	}
	if !found {
		t.Error("expected attr add")
	}
	// Existing attr update should be replace sel path/@attr
	base3 := mustDoc(t, `<root><a x="1"/></root>`)
	target3 := mustDoc(t, `<root><a x="2"/></root>`)
	ops3, _ := Diff(base3, target3, DefaultDiffOptions())
	patch3 := GeneratePatch(ops3)
	t.Logf("patch3: %s", docStr(t, patch3))
	found = false
	for _, op := range patch3.Root().ChildElements() {
		if op.Tag == "replace" && op.SelectAttrValue("sel", "") == "/root/a[1]/@x" {
			found = true
		}
	}
	if !found {
		t.Error("expected attr replace")
	}
}

func TestMerge3Way(t *testing.T) {
	base := mustDoc(t, `<root><a>1</a><b>2</b></root>`)
	ours := mustDoc(t, `<root><a>1</a><b>3</b><c/></root>`)
	theirs := mustDoc(t, `<root><a>1</a><b>4</b></root>`)
	merged, conflicts, err := Merge3Way(base, ours, theirs, DefaultMergeOptions())
	if err != nil {
		t.Fatal(err)
	}
	if len(conflicts) != 1 {
		t.Fatalf("expected 1 conflict, got %d: %+v", len(conflicts), conflicts)
	}
	if merged.Metadata["merge.base"] != "root" || merged.Metadata["merge.ours"] != "root" || merged.Metadata["merge.theirs"] != "root" {
		t.Errorf("metadata wrong: %+v", merged.Metadata)
	}
	t.Logf("conflicts: %+v", conflicts)
}

func TestReversePatch(t *testing.T) {
	patch := mustDoc(t, `<diff xmlns="urn:ietf:params:xml:ns:patch-ops"><add sel="/r[1]"><c/></add><replace sel="/r[1]/text()">x</replace><remove sel="/r[1]/b[1]/text()">old</remove></diff>`)
	rev, err := ReversePatch(patch)
	if err != nil {
		t.Fatal(err)
	}
	s := docStr(t, rev)
	t.Logf("reverse: %s", s)
	ops := rev.Root().ChildElements()
	if len(ops) != 3 {
		t.Fatalf("expected 3 ops, got %d", len(ops))
	}
	// reverse order: remove text, replace, remove(add)
	if ops[0].Tag != "replace" {
		t.Error("first should be replace for text remove")
	}
	if ops[1].Tag != "replace" {
		t.Error("second should be replace")
	}
	if ops[2].Tag != "remove" {
		t.Error("third should be remove")
	}
}

func TestDiffSummary(t *testing.T) {
	ops := []DiffOperation{
		{Type: OpAdd},
		{Type: OpRemove},
		{Type: OpUpdateText},
		{Type: OpUpdateAttr},
		{Type: OpReplace},
		{Type: OpMove},
	}
	s := NewDiffSummary(ops)
	if s.Additions() != 1 || s.Removals() != 1 || s.Modifications() != 3 || s.Moves() != 1 {
		t.Errorf("summary wrong: %+v", s)
	}
	if s.Total() != 6 || !s.HasChanges() {
		t.Errorf("total wrong")
	}
	if s.String() != "1 additions, 1 removals, 3 modifications, 1 moves" {
		t.Errorf("string wrong: %s", s.String())
	}
	if OpAdd.String() != "add" || OpRemove.String() != "remove" || OpReplace.String() != "replace" ||
		OpMove.String() != "move" || OpUpdateAttr.String() != "update-attr" || OpUpdateText.String() != "update-text" {
		t.Error("OpType String wrong")
	}
}

func TestDocumentConvenience(t *testing.T) {
	d := NewDocument()
	d.CreateElement("root")
	d2 := d.Copy()
	ops, err := d.Diff(d2, DefaultDiffOptions())
	if err != nil || len(ops) != 0 {
		t.Error("diff convenience failed")
	}
	if err := d.Patch(NewDocument()); err == nil {
		t.Error("patch on empty doc should error")
	}
}

func TestKeyAttributeDiff(t *testing.T) {
	base := mustDoc(t, `<root><item id="1"><a/></item><item id="2"><b/></item></root>`)
	target := mustDoc(t, `<root><item id="2"><b/><c/></item><item id="1"><a/></item></root>`)
	opts := DefaultDiffOptions()
	opts.IdentityMode = IdentityKeyAttribute
	opts.KeyAttributes = map[string]string{"item": "id"}
	ops, err := Diff(base, target, opts)
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("key diff ops: %+v", ops)
	hasMove := false
	for _, op := range ops {
		if op.Type == OpMove {
			hasMove = true
		}
	}
	if !hasMove {
		t.Error("expected move")
	}
}
