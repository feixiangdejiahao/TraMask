package main

import (
	"fmt"
	"github.com/beevik/etree"
)

func main() {
	base := etree.NewDocument(); base.ReadFromString(`<root><item id="1"><a/></item><item id="2"><b/></item></root>`)
	target := etree.NewDocument(); target.ReadFromString(`<root><item id="2"><b/><x/></item><item id="1"><a/></item></root>`)
	opts := etree.DefaultDiffOptions()
	opts.IdentityMode = etree.IdentityKeyAttribute
	opts.KeyAttributes = map[string]string{"item": "id"}
	opts.IgnoreOrder = true
	ops, _ := etree.Diff(base, target, opts)
	for _, o := range ops { fmt.Printf("%v path=%q\n", o.Type, o.Path) }
	p := etree.GeneratePatch(ops)
	ps, _ := p.WriteToString(); fmt.Println("patch:", ps)
	patched := base.Copy()
	if err := etree.ApplyPatch(patched, p); err != nil { fmt.Println("err:", err); return }
	got, _ := patched.WriteToString(); want, _ := target.WriteToString()
	fmt.Println("got:", got); fmt.Println("want:", want); fmt.Println("match:", got==want)
}
