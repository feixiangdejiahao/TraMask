package main

import (
	_ "embed"
	"fmt"
)

//go:embed embeddata.txt
var content string

func main() {
	fmt.Println(content)
}

// Output:
// embedded via real fs
