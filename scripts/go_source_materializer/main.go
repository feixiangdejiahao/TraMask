// Source-only Go materialization. No test execution or oracle decisions.
package main

import (
	"encoding/json"
	"fmt"
	"go/ast"
	"go/build"
	"go/parser"
	"go/token"
	"io"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

type File struct {
	Path       string   `json:"path"`
	Code       string   `json:"code"`
	Historical bool     `json:"historical"`
	Generated  []string `json:"generated"`
	Keep       []string `json:"keep"`
}
type Request struct {
	Files        []File `json:"files"`
	PruneHistory bool   `json:"prune_history"`
	Repository   string `json:"repository,omitempty"`
	AnalyzeOnly  bool   `json:"analyze_only,omitempty"`
}
type Edit struct {
	Start  int    `json:"start_byte"`
	End    int    `json:"end_byte"`
	Before string `json:"before"`
	After  string `json:"after"`
	Reason string `json:"reason"`
	Name   string `json:"name,omitempty"`
}
type Result struct {
	Path        string   `json:"path"`
	Code        string   `json:"code"`
	Edits       []Edit   `json:"edits"`
	Unsupported []string `json:"unsupported"`
}

func parents(root ast.Node) map[ast.Node]ast.Node {
	result := map[ast.Node]ast.Node{}
	stack := []ast.Node{}
	ast.Inspect(root, func(node ast.Node) bool {
		if node == nil {
			stack = stack[:len(stack)-1]
			return false
		}
		if len(stack) > 0 {
			result[node] = stack[len(stack)-1]
		}
		stack = append(stack, node)
		return true
	})
	return result
}

func readIdentifier(id *ast.Ident, owner ast.Node) bool {
	if id.Name == "_" {
		return false
	}
	switch node := owner.(type) {
	case *ast.AssignStmt:
		for _, item := range node.Lhs {
			if item == id {
				return false
			}
		}
	case *ast.RangeStmt:
		if node.Key == id || node.Value == id {
			return false
		}
	case *ast.ValueSpec:
		for _, item := range node.Names {
			if item == id {
				return false
			}
		}
	case *ast.Field:
		for _, item := range node.Names {
			if item == id {
				return false
			}
		}
	case *ast.SelectorExpr:
		if node.Sel == id {
			return false
		}
	case *ast.BranchStmt, *ast.LabeledStmt, *ast.FuncDecl, *ast.TypeSpec:
		return false
	}
	return true
}

func selected(names []string) map[string]bool {
	result := map[string]bool{}
	for _, name := range names {
		result[name] = true
	}
	return result
}

func structFieldKey(id *ast.Ident, parent map[ast.Node]ast.Node) bool {
	pair, ok := parent[id].(*ast.KeyValueExpr)
	if !ok || pair.Key != id {
		return false
	}
	literal, ok := parent[pair].(*ast.CompositeLit)
	if !ok {
		return false
	}
	var typ ast.Expr = literal.Type
	seen := map[*ast.Object]bool{}
	for {
		switch node := typ.(type) {
		case *ast.StructType:
			return true
		case *ast.Ident:
			if node.Obj == nil || seen[node.Obj] {
				return false
			}
			seen[node.Obj] = true
			declaration, ok := node.Obj.Decl.(*ast.TypeSpec)
			if !ok {
				return false
			}
			typ = declaration.Type
		case *ast.ParenExpr:
			typ = node.X
		default:
			return false
		}
	}
}

func declarationNames(statement ast.Stmt) []*ast.Ident {
	switch node := statement.(type) {
	case *ast.AssignStmt:
		if node.Tok != token.DEFINE {
			return nil
		}
		var names []*ast.Ident
		for _, item := range node.Lhs {
			id, ok := item.(*ast.Ident)
			if ok && id.Obj != nil && id.Obj.Decl == node {
				names = append(names, id)
			}
		}
		return names
	case *ast.DeclStmt:
		decl, ok := node.Decl.(*ast.GenDecl)
		if !ok || decl.Tok != token.VAR {
			return nil
		}
		var names []*ast.Ident
		for _, item := range decl.Specs {
			if spec, ok := item.(*ast.ValueSpec); ok {
				names = append(names, spec.Names...)
			}
		}
		return names
	case *ast.RangeStmt:
		if node.Tok != token.DEFINE {
			return nil
		}
		var names []*ast.Ident
		for _, item := range []ast.Expr{node.Key, node.Value} {
			if id, ok := item.(*ast.Ident); ok {
				names = append(names, id)
			}
		}
		return names
	}
	return nil
}

func unusedBindings(fs *token.FileSet, file *ast.File, input File) ([]Edit, []string) {
	var edits []Edit
	var unsupported []string
	generated := selected(input.Generated)
	for _, declaration := range file.Decls {
		function, ok := declaration.(*ast.FuncDecl)
		if !ok || function.Body == nil || !generated[function.Name.Name] {
			continue
		}
		parent := parents(function)
		reads := map[*ast.Object]bool{}
		ast.Inspect(function.Body, func(node ast.Node) bool {
			if id, ok := node.(*ast.Ident); ok && id.Obj != nil && readIdentifier(id, parent[id]) && !structFieldKey(id, parent) {
				reads[id.Obj] = true
			}
			return true
		})
		ast.Inspect(function.Body, func(node ast.Node) bool {
			statement, ok := node.(ast.Stmt)
			if !ok {
				return true
			}
			names := declarationNames(statement)
			var unused []string
			for _, id := range names {
				if id.Name != "_" && id.Obj != nil && !reads[id.Obj] {
					unused = append(unused, id.Name)
				}
			}
			if len(unused) == 0 {
				return true
			}
			if _, ok := statement.(*ast.RangeStmt); ok {
				unsupported = append(unsupported, function.Name.Name+":range_scope:"+strings.Join(unused, ","))
				return true
			}
			switch parent[statement].(type) {
			case *ast.BlockStmt, *ast.CaseClause, *ast.CommClause:
				position := fs.Position(statement.End()).Offset
				for _, name := range unused {
					edits = append(edits, Edit{Start: position, End: position, After: "; _ = " + name, Reason: "preserve_unread_local_binding_without_repeating_initializer", Name: name})
				}
			default:
				unsupported = append(unsupported, function.Name.Name+":initializer_scope:"+strings.Join(unused, ","))
			}
			return true
		})
	}
	return edits, unsupported
}

func isTestEntry(function *ast.FuncDecl, imports map[string]string) bool {
	if function.Recv != nil || !strings.HasPrefix(function.Name.Name, "Test") || function.Name.Name == "TestMain" || function.Type.Params == nil || len(function.Type.Params.List) != 1 {
		return false
	}
	star, ok := function.Type.Params.List[0].Type.(*ast.StarExpr)
	if !ok {
		return false
	}
	selector, ok := star.X.(*ast.SelectorExpr)
	if !ok || selector.Sel.Name != "T" {
		return false
	}
	name, ok := selector.X.(*ast.Ident)
	return ok && imports[name.Name] == "testing"
}

var packageNames = map[string]string{}
var repositoryRoot, modulePath string

func repositoryPackageName(importPath string) string {
	if repositoryRoot == "" || modulePath == "" || (importPath != modulePath && !strings.HasPrefix(importPath, modulePath+"/")) {
		return ""
	}
	relative := strings.TrimPrefix(strings.TrimPrefix(importPath, modulePath), "/")
	directory := filepath.Join(repositoryRoot, filepath.FromSlash(relative))
	resolved, err := filepath.EvalSymlinks(directory)
	if err != nil || (resolved != repositoryRoot && !strings.HasPrefix(resolved, repositoryRoot+string(filepath.Separator))) {
		return ""
	}
	entries, err := os.ReadDir(resolved)
	if err != nil {
		return ""
	}
	names := map[string]bool{}
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".go") || strings.HasSuffix(entry.Name(), "_test.go") {
			continue
		}
		file, err := parser.ParseFile(token.NewFileSet(), filepath.Join(resolved, entry.Name()), nil, parser.PackageClauseOnly)
		if err == nil {
			names[file.Name.Name] = true
		}
	}
	if len(names) == 1 {
		for name := range names {
			return name
		}
	}
	return ""
}

func configureRepository(repository string) {
	if repository == "" {
		return
	}
	root, err := filepath.EvalSymlinks(repository)
	if err != nil {
		return
	}
	data, err := os.ReadFile(filepath.Join(root, "go.mod"))
	if err != nil {
		return
	}
	for _, line := range strings.Split(string(data), "\n") {
		fields := strings.Fields(line)
		if len(fields) >= 2 && fields[0] == "module" {
			repositoryRoot, modulePath = root, strings.Trim(fields[1], "\"")
			return
		}
	}
}

func importBinding(item *ast.ImportSpec) string {
	if item.Name != nil {
		return item.Name.Name
	}
	value, err := strconv.Unquote(item.Path.Value)
	if err != nil || value == "C" {
		return ""
	}
	if name, found := packageNames[value]; found {
		return name
	}
	// Resolve package declarations from local Go source; never guess that a
	// third-party package has the same name as its final import-path segment.
	name := repositoryPackageName(value)
	if pkg, err := build.Import(value, "", 0); name == "" && err == nil {
		name = pkg.Name
	}
	packageNames[value] = name
	return name
}

func importNames(file *ast.File) map[string]string {
	result := map[string]string{}
	for _, item := range file.Imports {
		value, err := strconv.Unquote(item.Path.Value)
		if err != nil {
			continue
		}
		if name := importBinding(item); name != "" {
			result[name] = value
		}
	}
	return result
}

func prune(file *ast.File, fs *token.FileSet, input File) []Edit {
	if !input.Historical {
		return nil
	}
	imports := importNames(file)
	entries := map[string]*ast.FuncDecl{}
	for _, declaration := range file.Decls {
		if function, ok := declaration.(*ast.FuncDecl); ok && isTestEntry(function, imports) {
			entries[function.Name.Name] = function
		}
	}
	keep := selected(append(input.Keep, input.Generated...))
	parent := parents(file)
	references := func(root ast.Node) {
		ast.Inspect(root, func(node ast.Node) bool {
			id, ok := node.(*ast.Ident)
			if !ok || !readIdentifier(id, parent[id]) {
				return true
			}
			if _, found := entries[id.Name]; !found {
				return true
			}
			if id.Obj == nil || id.Obj.Kind == ast.Fun {
				keep[id.Name] = true
			}
			return true
		})
	}
	// Helpers and global initializers remain; any test entry they reference must
	// remain too. Repeated closure iteration covers test-to-test calls.
	for {
		before := len(keep)
		for _, declaration := range file.Decls {
			function, ok := declaration.(*ast.FuncDecl)
			if ok && entries[function.Name.Name] != nil && !keep[function.Name.Name] {
				continue
			}
			references(declaration)
		}
		if len(keep) == before {
			break
		}
	}
	var edits []Edit
	removed := map[ast.Node]bool{}
	for name, function := range entries {
		if keep[name] {
			continue
		}
		start, end := fs.Position(function.Pos()).Offset, fs.Position(function.End()).Offset
		edits = append(edits, Edit{Start: start, End: end, Before: input.Code[start:end], Reason: "unselected_historical_test_entry", Name: name})
		removed[function] = true
	}
	used := map[string]bool{}
	ast.Inspect(file, func(node ast.Node) bool {
		if removed[node] {
			return false
		}
		if expression, ok := node.(*ast.SelectorExpr); ok {
			if name, ok := expression.X.(*ast.Ident); ok && name.Obj == nil {
				used[name.Name] = true
			}
		}
		return true
	})
	for _, item := range file.Imports {
		name := importBinding(item)
		if name == "" || name == "_" || name == "." || name == "C" || used[name] {
			continue
		}
		if item.Name != nil {
			start, end := fs.Position(item.Name.Pos()).Offset, fs.Position(item.Name.End()).Offset
			edits = append(edits, Edit{Start: start, End: end, Before: input.Code[start:end], After: "_", Reason: "preserve_unused_import_init", Name: name})
		} else {
			start := fs.Position(item.Path.Pos()).Offset
			edits = append(edits, Edit{Start: start, End: start, After: "_ ", Reason: "preserve_unused_import_init", Name: name})
		}
	}
	return edits
}

func historicalClosure(request *Request) error {
	type Context struct {
		File      *ast.File
		Parent    map[ast.Node]ast.Node
		Namespace string
		Entries   map[string]bool
	}
	contexts := []Context{}
	targets, keep := map[string]bool{}, map[string]bool{}
	for _, input := range request.Files {
		file, err := parser.ParseFile(token.NewFileSet(), input.Path, input.Code, 0)
		if err != nil {
			return err
		}
		context := Context{File: file, Parent: parents(file), Namespace: path.Dir(input.Path) + ":" + file.Name.Name + ":", Entries: map[string]bool{}}
		imports := importNames(file)
		for _, declaration := range file.Decls {
			if function, ok := declaration.(*ast.FuncDecl); ok && isTestEntry(function, imports) {
				name := function.Name.Name
				context.Entries[name], targets[context.Namespace+name] = true, true
				if !input.Historical {
					keep[context.Namespace+name] = true
				}
			}
		}
		for _, name := range append(input.Keep, input.Generated...) {
			keep[context.Namespace+name] = true
		}
		contexts = append(contexts, context)
	}
	for {
		before := len(keep)
		for _, context := range contexts {
			for _, declaration := range context.File.Decls {
				if function, ok := declaration.(*ast.FuncDecl); ok && context.Entries[function.Name.Name] && !keep[context.Namespace+function.Name.Name] {
					continue
				}
				ast.Inspect(declaration, func(node ast.Node) bool {
					id, ok := node.(*ast.Ident)
					if ok && readIdentifier(id, context.Parent[id]) && (id.Obj == nil || id.Obj.Kind == ast.Fun) && targets[context.Namespace+id.Name] {
						keep[context.Namespace+id.Name] = true
					}
					return true
				})
			}
		}
		if before == len(keep) {
			break
		}
	}
	for index, context := range contexts {
		for name := range context.Entries {
			if keep[context.Namespace+name] {
				request.Files[index].Keep = append(request.Files[index].Keep, name)
			}
		}
	}
	return nil
}

func process(input File, pruneHistory bool) (Result, error) {
	result := Result{Path: input.Path, Code: input.Code, Edits: []Edit{}, Unsupported: []string{}}
	fs := token.NewFileSet()
	file, err := parser.ParseFile(fs, input.Path, input.Code, parser.ParseComments)
	if err != nil {
		return result, err
	}
	if pruneHistory {
		result.Edits = append(result.Edits, prune(file, fs, input)...)
	}
	edits, unsupported := unusedBindings(fs, file, input)
	result.Edits = append(result.Edits, edits...)
	result.Unsupported = append(result.Unsupported, unsupported...)
	sort.SliceStable(result.Edits, func(i, j int) bool {
		a, b := result.Edits[i], result.Edits[j]
		if a.Start == b.Start {
			return a.End > b.End
		}
		return a.Start > b.Start
	})
	for _, edit := range result.Edits {
		if result.Code[edit.Start:edit.End] != edit.Before {
			return result, fmt.Errorf("edit source mismatch")
		}
		result.Code = result.Code[:edit.Start] + edit.After + result.Code[edit.End:]
	}
	if _, err := parser.ParseFile(token.NewFileSet(), input.Path, result.Code, 0); err != nil {
		return result, err
	}
	return result, nil
}

func main() {
	data, err := io.ReadAll(os.Stdin)
	var request Request
	if err == nil {
		err = json.Unmarshal(data, &request)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	configureRepository(request.Repository)
	if request.AnalyzeOnly {
		analysis := []map[string]interface{}{}
		for _, input := range request.Files {
			fs := token.NewFileSet()
			file, err := parser.ParseFile(fs, input.Path, input.Code, 0)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(2)
			}
			parent := parents(file)
			unresolved := []map[string]interface{}{}
			for _, id := range file.Unresolved {
				include := readIdentifier(id, parent[id])
				switch owner := parent[id].(type) {
				case *ast.AssignStmt:
					if owner.Tok != token.DEFINE {
						include = true
					}
				case *ast.RangeStmt:
					if owner.Tok != token.DEFINE {
						include = true
					}
				}
				if !include || id.Name == "_" || structFieldKey(id, parent) {
					continue
				}
				selector, ok := parent[id].(*ast.SelectorExpr)
				unresolved = append(unresolved, map[string]interface{}{"name": id.Name, "start_byte": fs.Position(id.Pos()).Offset,
					"end_byte": fs.Position(id.End()).Offset, "selector_receiver": ok && selector.X == id})
			}
			globals := []string{}
			for name := range file.Scope.Objects {
				globals = append(globals, name)
			}
			sort.Strings(globals)
			imports := []map[string]string{}
			for _, item := range file.Imports {
				module, _ := strconv.Unquote(item.Path.Value)
				alias := ""
				if item.Name != nil {
					alias = item.Name.Name
				}
				imports = append(imports, map[string]string{"module": module, "name": importBinding(item), "explicit_alias": alias})
			}
			analysis = append(analysis, map[string]interface{}{"path": input.Path, "package": file.Name.Name, "globals": globals,
				"unresolved": unresolved, "imports": imports})
		}
		json.NewEncoder(os.Stdout).Encode(analysis)
		return
	}
	if request.PruneHistory {
		if err := historicalClosure(&request); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(2)
		}
	}
	results := []Result{}
	for _, input := range request.Files {
		result, err := process(input, request.PruneHistory)
		if err != nil {
			fmt.Fprintln(os.Stderr, input.Path+": "+err.Error())
			os.Exit(2)
		}
		results = append(results, result)
	}
	json.NewEncoder(os.Stdout).Encode(results)
}
