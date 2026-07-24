package main

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"testing"

	"golang.org/x/mod/modfile"
)

const (
	webview2ModulePath = "github.com/wailsapp/go-webview2"
	webview2PatchPath  = "./third_party/go-webview2"
)

func TestWebView2MixedDPIPatchWiring(t *testing.T) {
	modData, err := os.ReadFile("go.mod")
	if err != nil {
		t.Fatal(err)
	}
	mod, err := modfile.Parse("go.mod", modData, nil)
	if err != nil {
		t.Fatal(err)
	}
	replaced := false
	for _, directive := range mod.Replace {
		if directive.Old.Path == webview2ModulePath && directive.New.Path == webview2PatchPath {
			replaced = true
			break
		}
	}
	if !replaced {
		t.Fatalf("%s must be replaced by %s", webview2ModulePath, webview2PatchPath)
	}

	patchFile := filepath.Join("third_party", "go-webview2", "pkg", "edge", "chromium.go")
	parsed, err := parser.ParseFile(token.NewFileSet(), patchFile, nil, 0)
	if err != nil {
		t.Fatal(err)
	}

	policyEnabled := false
	policyApplied := false
	ast.Inspect(parsed, func(node ast.Node) bool {
		switch value := node.(type) {
		case *ast.ValueSpec:
			if len(value.Names) == 1 && value.Names[0].Name == "shouldDetectMonitorScaleChanges" && len(value.Values) == 1 {
				ident, ok := value.Values[0].(*ast.Ident)
				policyEnabled = ok && ident.Name == "true"
			}
		case *ast.CallExpr:
			selector, ok := value.Fun.(*ast.SelectorExpr)
			if !ok || selector.Sel.Name != "PutShouldDetectMonitorScaleChanges" || len(value.Args) != 1 {
				break
			}
			ident, ok := value.Args[0].(*ast.Ident)
			policyApplied = ok && ident.Name == "shouldDetectMonitorScaleChanges"
		}
		return true
	})
	if !policyEnabled || !policyApplied {
		t.Fatal("patched WebView2 must enable and apply automatic monitor-scale detection")
	}
}
