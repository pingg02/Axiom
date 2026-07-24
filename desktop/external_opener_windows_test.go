//go:build windows

package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestWindowsExternalOpenerIconUsesShellIcon(t *testing.T) {
	explorer := filepath.Join(os.Getenv("WINDIR"), "explorer.exe")
	if info, err := os.Stat(explorer); err != nil || info.IsDir() {
		t.Skip("Windows Explorer executable is unavailable")
	}
	got := platformExternalOpenerIconDataURL(externalOpenerSpec{IconSource: explorer})
	if !strings.HasPrefix(got, "data:image/png;base64,") {
		t.Fatalf("native Explorer icon = %q, want PNG data URL", got)
	}
}
