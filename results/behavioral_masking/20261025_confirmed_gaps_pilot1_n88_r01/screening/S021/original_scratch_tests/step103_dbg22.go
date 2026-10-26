package main

import (
	"fmt"
	"github.com/beevik/etree"
)

func main() {
	base := etree.NewDocument(); base.ReadFromString(`<root>text</root>`)
	target := etree.NewDocument(); target.ReadFromString(`<root><child/>text</root>`)
	ops, _ := etree.Diff(base, target, etree.DefaultDiffOptions())
	for _, o := range ops { fmt.Printf("%v path=%q old=%v new=%v\n", o.Type, o.Path, o.OldValue, o.NewValue) }
	p := etree.GeneratePatch(ops)
	ps, _ := p.WriteToString(); fmt.Println("patch:", ps)
	patched := base.Copy()
	if err := etree.ApplyPatch(patched, p); err != nil { fmt.Println("err:", err); return }
	got, _ := patched.WriteToString(); want, _ := target.WriteToString()
	fmt.Println("got:", got); fmt.Println("want:", want); fmt.Println("match:", got==want)
}
