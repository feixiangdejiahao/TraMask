package etree

import (
	"strings"
	"testing"
)

func TestDiffRoundTripMany(t *testing.T) {
	cases := []struct{ base, target string }{
		{"<root><a/><a/><a/></root>", "<root><a/><a/></root>"},
		{"<root><a/><a/></root>", "<root><a/><a/><a/></root>"},
		{"<root><a x=\"1\"/><a x=\"2\"/></root>", "<root><a x=\"2\"/><a x=\"1\"/></root>"},
		{"<root><a><b/></a></root>", "<root><a><b/><c/></a></root>"},
		{"<root><a><b/><c/></a></root>", "<root><a><b/></a></root>"},
		{"<root><a>t1<b/>t2</a></root>", "<root><a>t1<b/>t2</a></root>"},
		{"<root><a>old</a></root>", "<root><a></a></root>"},
		{"<root><a></a></root>", "<root><a>new</a></root>"},
		{"<root><ns:a xmlns:ns=\"urn:x\"/></root>", "<root><ns:a xmlns:ns=\"urn:x\" k=\"v\"/></root>"},
		{"<root><a b=\"1\" c=\"2\"/></root>", "<root><a b=\"3\"/></root>"},
	}
	for _, c := range cases {
		base := mustDoc(t, c.base)
		target := mustDoc(t, c.target)
		ops, err := Diff(base, target, DefaultDiffOptions())
		if err != nil {
			t.Fatalf("diff error %s->%s: %v", c.base, c.target, err)
		}
		patch := GeneratePatch(ops)
		patched := base.Copy()
		if err := ApplyPatch(patched, patch); err != nil {
			t.Fatalf("apply error %s->%s: %v patch=%s ops=%+v", c.base, c.target, err, docStr(t, patch), ops)
		}
		if docStr(t, patched) != docStr(t, target) {
			t.Errorf("roundtrip failed %s->%s\ngot %s\nwant %s\nops=%+v\npatch=%s",
				c.base, c.target, docStr(t, patched), docStr(t, target), ops, docStr(t, patch))
		}
	}
}

func TestNilErrors(t *testing.T) {
	if _, err := Diff(nil, NewDocument(), DefaultDiffOptions()); err == nil {
		t.Error("Diff nil should error")
	}
	if _, err := Diff(NewDocument(), nil, DefaultDiffOptions()); err == nil {
		t.Error("Diff nil should error")
	}
	if err := ApplyPatch(nil, NewDocument()); err == nil {
		t.Error("ApplyPatch nil doc should error")
	}
	if err := ApplyPatch(NewDocument(), nil); err == nil {
		t.Error("ApplyPatch nil patch should error")
	}
	if _, err := ReversePatch(nil); err == nil {
		t.Error("ReversePatch nil should error")
	}
	if _, _, err := Merge3Way(nil, NewDocument(), NewDocument(), DefaultMergeOptions()); err == nil {
		t.Error("Merge3Way nil should error")
	}
	if _, _, err := Merge3Way(NewDocument(), nil, NewDocument(), DefaultMergeOptions()); err == nil {
		t.Error("Merge3Way nil should error")
	}
	if _, _, err := Merge3Way(NewDocument(), NewDocument(), nil, DefaultMergeOptions()); err == nil {
		t.Error("Merge3Way nil should error")
	}
}

func TestMergeConflictTypes(t *testing.T) {
	// Modify-delete: ours changes text, theirs removes element.
	base := mustDoc(t, `<root><a>1</a></root>`)
	ours := mustDoc(t, `<root><a>2</a></root>`)
	theirs := mustDoc(t, `<root></root>`)
	_, conflicts, err := Merge3Way(base, ours, theirs, DefaultMergeOptions())
	if err != nil {
		t.Fatal(err)
	}
	if len(conflicts) != 1 {
		t.Fatalf("expected 1 conflict, got %d", len(conflicts))
	}
	if conflicts[0].Type != ConflictModifyDelete {
		t.Errorf("expected modify-delete, got %v", conflicts[0].Type)
	}
	if conflicts[0].Type.String() != "modify-delete" {
		t.Error("ConflictType String wrong")
	}

	// Structural: ours removes parent, theirs adds child under it.
	base = mustDoc(t, `<root><a><b/></a></root>`)
	ours = mustDoc(t, `<root></root>`)
	theirs = mustDoc(t, `<root><a><b/><c/></a></root>`)
	_, conflicts, err = Merge3Way(base, ours, theirs, DefaultMergeOptions())
	if err != nil {
		t.Fatal(err)
	}
	if len(conflicts) != 1 {
		t.Fatalf("expected 1 structural conflict, got %d", len(conflicts))
	}
	if conflicts[0].Type != ConflictStructural {
		t.Errorf("expected structural, got %v", conflicts[0].Type)
	}
}

func TestAutoResolve(t *testing.T) {
	base := mustDoc(t, `<root><a>1</a></root>`)
	ours := mustDoc(t, `<root><a>ours</a></root>`)
	theirs := mustDoc(t, `<root><a>theirs</a></root>`)
	opts := DefaultMergeOptions()
	opts.AutoResolve = true
	opts.DefaultResolution = ResolutionTheirs
	merged, conflicts, err := Merge3Way(base, ours, theirs, opts)
	if err != nil {
		t.Fatal(err)
	}
	if len(conflicts) != 1 || !conflicts[0].Resolved {
		t.Fatalf("expected resolved conflict: %+v", conflicts)
	}
	if conflicts[0].Resolution != "theirs" {
		t.Errorf("resolution wrong: %v", conflicts[0].Resolution)
	}
	if a := merged.Root().SelectElement("a").Text(); a != "theirs" {
		t.Errorf("merged text wrong: %s", a)
	}
}

func TestMergeResolveMethod(t *testing.T) {
	c := &MergeConflict{BaseValue: "base", OursValue: "ours", TheirsValue: "theirs"}
	c.Resolve(ResolutionOurs, nil)
	if !c.Resolved || c.Resolution != "ours" {
		t.Error("ours resolve wrong")
	}
	c = &MergeConflict{BaseValue: "base", OursValue: "ours", TheirsValue: "theirs"}
	c.Resolve(ResolutionCustom, "custom")
	if !c.Resolved || c.Resolution != "custom" {
		t.Error("custom resolve wrong")
	}
}

func TestConflictTypeStrings(t *testing.T) {
	if ConflictBothModified.String() != "both-modified" {
		t.Error("both-modified")
	}
	if ConflictStructural.String() != "structural" {
		t.Error("structural")
	}
}

func TestKeyAttrDifferentTagReplace(t *testing.T) {
	base := mustDoc(t, `<root><a id="1"/></root>`)
	target := mustDoc(t, `<root><b id="1"/></root>`)
	opts := DefaultDiffOptions()
	opts.IdentityMode = IdentityKeyAttribute
	opts.KeyAttributes = map[string]string{"*": "id"}
	ops, err := Diff(base, target, opts)
	if err != nil {
		t.Fatal(err)
	}
	foundReplace := false
	for _, op := range ops {
		if op.Type == OpReplace {
			foundReplace = true
		}
	}
	if !foundReplace {
		t.Errorf("expected replace, ops=%+v", ops)
	}
}

func TestIgnoreOrder(t *testing.T) {
	base := mustDoc(t, `<root><item id="1"/><item id="2"/></root>`)
	target := mustDoc(t, `<root><item id="2"/><item id="1"/></root>`)
	opts := DefaultDiffOptions()
	opts.IdentityMode = IdentityKeyAttribute
	opts.KeyAttributes = map[string]string{"item": "id"}
	opts.IgnoreOrder = true
	ops, _ := Diff(base, target, opts)
	for _, op := range ops {
		if op.Type == OpMove {
			t.Error("should not move when IgnoreOrder")
		}
	}
}

func TestContentHashMode(t *testing.T) {
	base := mustDoc(t, `<root><item><a/></item><item><b/></item></root>`)
	target := mustDoc(t, `<root><item><b/></item><item><a/></item></root>`)
	opts := DefaultDiffOptions()
	opts.IdentityMode = IdentityContentHash
	ops, _ := Diff(base, target, opts)
	// Same content hashes should pair; no removals/adds.
	for _, op := range ops {
		if op.Type == OpRemove || op.Type == OpAdd {
			t.Errorf("unexpected op %+v", op)
		}
	}
}

func TestIgnoreWhitespace(t *testing.T) {
	base := mustDoc(t, `<root>   <a/>   </root>`)
	target := mustDoc(t, `<root><a/></root>`)
	ops, _ := Diff(base, target, DefaultDiffOptions())
	if len(ops) != 0 {
		t.Errorf("whitespace should be ignored, got %+v", ops)
	}
}

func TestIgnoreAttrs(t *testing.T) {
	base := mustDoc(t, `<root><a x="1"/></root>`)
	target := mustDoc(t, `<root><a x="2"/></root>`)
	opts := DefaultDiffOptions()
	opts.IgnoreAttrs = []string{"x"}
	ops, _ := Diff(base, target, opts)
	if len(ops) != 0 {
		t.Errorf("ignored attr diff, got %+v", ops)
	}
}

func TestDocumentMetadataCopy(t *testing.T) {
	d := NewDocument()
	d.CreateElement("root")
	d.Metadata["k"] = "v"
	c := d.Copy()
	if c.Metadata["k"] != "v" {
		t.Error("metadata not copied")
	}
}

func TestOpString(t *testing.T) {
	op := DiffOperation{Type: OpMove, OldPath: "/a[1]", NewPath: "/b[1]"}
	s := op.String()
	if !contains(s, "MOVE") || !contains(s, "/a[1]") || !contains(s, "/b[1]") {
		t.Errorf("move string wrong: %s", s)
	}
	op = DiffOperation{Type: OpUpdateAttr, Path: "/a[1]", AttrName: "x"}
	if !contains(op.String(), "@x") {
		t.Errorf("update-attr string wrong: %s", op.String())
	}
}

func contains(s, sub string) bool {
	return strings.Contains(s, sub)
}

func TestDeepEqualComments(t *testing.T) {
	a := NewElement("a")
	a.CreateComment("c")
	b := NewElement("a")
	if a.DeepEqual(b) {
		t.Error("comment should differ")
	}
	b.CreateComment("c")
	if !a.DeepEqual(b) {
		t.Error("same comment should be equal")
	}
}

func TestReversePatchAttrRemove(t *testing.T) {
	patch := mustDoc(t, `<diff xmlns="urn:ietf:params:xml:ns:patch-ops"><remove sel="/r[1]/@a">old</remove></diff>`)
	rev, err := ReversePatch(patch)
	if err != nil {
		t.Fatal(err)
	}
	op := rev.Root().ChildElements()[0]
	if op.Tag != "add" || op.SelectAttrValue("type", "") != "attribute" || op.SelectAttrValue("name", "") != "a" {
		t.Errorf("attr remove reverse wrong: %s", docStr(t, rev))
	}
}

func TestMergeIndependentAdds(t *testing.T) {
	base := mustDoc(t, `<root><a/></root>`)
	ours := mustDoc(t, `<root><a/><b/></root>`)
	theirs := mustDoc(t, `<root><a/><c/></root>`)
	_, conflicts, err := Merge3Way(base, ours, theirs, DefaultMergeOptions())
	if err != nil {
		t.Fatal(err)
	}
	if len(conflicts) != 0 {
		t.Errorf("independent adds should not conflict: %+v", conflicts)
	}
}

func TestMergeAddVsReplaceConflict(t *testing.T) {
	base := mustDoc(t, `<root><a/></root>`)
	ours := mustDoc(t, `<root><a/><b/></root>`)
	theirs := mustDoc(t, `<root><x/></root>`)
	_, conflicts, err := Merge3Way(base, ours, theirs, DefaultMergeOptions())
	if err != nil {
		t.Fatal(err)
	}
	if len(conflicts) == 0 {
		t.Error("expected conflict for add vs replace")
	}
}

func TestMoveInDiffForReorder(t *testing.T) {
	base := mustDoc(t, `<root><item id="1"/><item id="2"/></root>`)
	target := mustDoc(t, `<root><item id="2"/><item id="1"/></root>`)
	opts := DefaultDiffOptions()
	opts.IdentityMode = IdentityKeyAttribute
	opts.KeyAttributes = map[string]string{"item": "id"}
	ops, _ := Diff(base, target, opts)
	moves := 0
	for _, op := range ops {
		if op.Type == OpMove {
			moves++
		}
	}
	if moves == 0 {
		t.Error("expected move for reorder")
	}
}

func TestRootAddRemoveRoundTrip(t *testing.T) {
	// Root add from empty
	base := NewDocument()
	target := mustDoc(t, `<root><a/></root>`)
	ops, _ := Diff(base, target, DefaultDiffOptions())
	p := GeneratePatch(ops)
	out := NewDocument()
	if err := ApplyPatch(out, p); err != nil {
		t.Fatal(err)
	}
	if docStr(t, out) != docStr(t, target) {
		t.Error("root add failed")
	}

	// Root remove via copy
	base2 := mustDoc(t, `<root><a/></root>`)
	target2 := NewDocument()
	ops2, _ := Diff(base2, target2, DefaultDiffOptions())
	p2 := GeneratePatch(ops2)
	out2 := base2.Copy()
	if err := ApplyPatch(out2, p2); err != nil {
		t.Fatal(err)
	}
	if out2.Root() != nil {
		t.Error("root remove failed")
	}
}
