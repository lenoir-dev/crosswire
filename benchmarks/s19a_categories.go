// Independent, pinned go/types diagnostic codes and positions for S19a.
// Never imports crosswire; consumes offline `go list -e -deps -export -json`.
package main

import (
	"encoding/json"
	"go/ast"
	"go/importer"
	"go/parser"
	"go/token"
	"go/types"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
)

type Package struct {
	ImportPath, Dir, Name, Export, GoVersion string
	GoFiles, Imports []string
	Module *struct { GoVersion string }
}

type Diagnostic struct {
	Package string `json:"package"`
	Path string `json:"path"`
	Line int `json:"line"`
	Column int `json:"column"`
	StartLine int `json:"start_line"`
	StartColumn int `json:"start_column"`
	EndLine int `json:"end_line"`
	EndColumn int `json:"end_column"`
	Code int64 `json:"code"`
	Syntax string `json:"syntax"`
	Symbol string `json:"symbol,omitempty"`
	ImportPath string `json:"import_path,omitempty"`
	Message string `json:"message"`
}

func main() {
	root, err := filepath.Abs(os.Args[1]); if err != nil { panic(err) }
	decoder := json.NewDecoder(os.Stdin)
	var packages []Package
	exports := map[string]string{}
	for {
		var p Package
		err := decoder.Decode(&p)
		if err == io.EOF { break }; if err != nil { panic(err) }
		packages = append(packages, p)
		if p.Export != "" { exports[p.ImportPath] = p.Export }
	}
	var diagnostics []Diagnostic
	for _, p := range packages {
		if p.Dir != root && !strings.HasPrefix(p.Dir, root+string(os.PathSeparator)) { continue }
		fset := token.NewFileSet()
		var files []*ast.File
		for _, name := range p.GoFiles {
			if strings.HasSuffix(name, "_test.go") { continue }
			file, err := parser.ParseFile(fset, filepath.Join(p.Dir,name), nil, 0)
			if err != nil { continue }; files = append(files, file)
		}
		if len(files)==0 { continue }
		lookup := func(path string) (io.ReadCloser, error) { return os.Open(exports[path]) }
		config := types.Config{Importer: importer.ForCompiler(fset, "gc", lookup),
			Sizes: types.SizesFor("gc", os.Getenv("GOARCH"))}
		if p.Module != nil && p.Module.GoVersion != "" { config.GoVersion = "go"+p.Module.GoVersion }
		config.Error = func(err error) {
			e, ok := err.(types.Error); if !ok { return }
			position := fset.Position(e.Pos)
			path, _ := filepath.Rel(root, position.Filename)
			code := reflect.ValueOf(e).FieldByName("go116code").Int()
			d := Diagnostic{Package:p.ImportPath, Path:filepath.ToSlash(path), Line:position.Line,
				Column:position.Column, Code:code, Syntax:"other", Message:e.Msg}
			// Category is the pinned checker code plus syntax at its position,
			// never an English-message regex. Messages are retained only for audit.
			best := token.Pos(1<<30)
			for _, f := range files {
				imports := map[string]string{}
				for _, imp := range f.Imports {
					path, _ := strconv.Unquote(imp.Path.Value)
					name := ""; if imp.Name != nil { name=imp.Name.Name }
					if name=="" { for _, candidate:=range packages { if candidate.ImportPath==path {name=candidate.Name;break} } }
					imports[name]=path
				}
				ast.Inspect(f, func(n ast.Node) bool {
					if n==nil || e.Pos<n.Pos() || e.Pos>=n.End() {return true}
					span:=n.End()-n.Pos(); if span>best {return true}
					oldBest:=best
					switch node:=n.(type) {
					case *ast.ImportSpec:
						best=span; d.Syntax="import";d.ImportPath,_=strconv.Unquote(node.Path.Value)
					case *ast.SelectorExpr:
						if head,ok:=node.X.(*ast.Ident);ok && imports[head.Name]!="" {
							best=span;d.Syntax="package-selector";d.Symbol=node.Sel.Name;d.ImportPath=imports[head.Name]
						}
					case *ast.CallExpr:
						best=span;d.Syntax="call"
						if name,ok:=node.Fun.(*ast.Ident);ok {d.Syntax="bare-call";d.Symbol=name.Name}
					case *ast.AssignStmt:
						best=span;d.Syntax="assignment";if len(node.Lhs)>1 && len(node.Rhs)==1 {if _,ok:=node.Rhs[0].(*ast.CallExpr);ok {d.Syntax="multi-assignment-call"}}
					}
					if best!=oldBest {
						start,end:=fset.Position(n.Pos()),fset.Position(n.End())
						d.StartLine=start.Line;d.StartColumn=start.Column;d.EndLine=end.Line;d.EndColumn=end.Column
					}
					// WrongAssignCount=17 in the pinned codes table; preserve the
					// syntactic multi-assignment even when its RHS call is smaller.
					if code==17 && d.Syntax=="multi-assignment-call" {return false}
					return true
				})
			}
			diagnostics=append(diagnostics,d)
		}
		_, _ = config.Check(p.ImportPath, fset, files, nil)
	}
	if diagnostics==nil {diagnostics=[]Diagnostic{}}
	if err:=json.NewEncoder(os.Stdout).Encode(diagnostics);err!=nil {panic(err)}
}
