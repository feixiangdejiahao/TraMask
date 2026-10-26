package main

import (
	"fmt"
	"github.com/beevik/etree"
)

func main() {
	base := etree.NewDocument(); base.ReadFromString(`<root><a>1</a><b>2</b></root>`)
	ours := etree.NewDocument(); ours.ReadFromString(`<root><a>1</a><b>2</b><c/></root>`)
	theirs := etree.NewDocument(); theirs.ReadFromString(`<root><a>9</a><b>2</b></root>`)
	merged, conflicts, err := etree.Merge3Way(base, ours, theirs, etree.DefaultMergeOptions())
	fmt.Println("err:", err)
	fmt.Println("conflicts:", len(conflicts), conflicts)
	if merged != nil {
		s, _ := merged.WriteToString()
		fmt.Println("merged:", s)
		fmt.Println("meta:", merged.Metadata)
	}
}
