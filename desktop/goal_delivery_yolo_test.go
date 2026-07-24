package main

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"reasonix/internal/agent"
	"reasonix/internal/boot"
	"reasonix/internal/config"
	"reasonix/internal/control"
	"reasonix/internal/event"
	"reasonix/internal/evidence"
	"reasonix/internal/store"
)

func newGoalDeliveryYoloTestApp(t *testing.T, goalStatus string) (*App, *WorkspaceTab, control.SessionAPI, string) {
	t.Helper()
	isolateDesktopUserDirs(t)
	setDesktopTestCredential(t, "GOAL_DELIVERY_KEY", "sk-test")
	cfg := config.Default()
	cfg.DefaultModel = "test/model"
	cfg.Desktop.ProviderAccess = []string{"test"}
	cfg.Providers = []config.ProviderEntry{{
		Name: "test", Kind: "openai", BaseURL: "https://example.invalid/v1", Model: "model", APIKeyEnv: "GOAL_DELIVERY_KEY",
	}}
	if err := cfg.SaveTo(config.UserConfigPath()); err != nil {
		t.Fatalf("save config: %v", err)
	}

	dir := config.SessionDir()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatalf("mkdir session dir: %v", err)
	}
	path := filepath.Join(dir, "goal-delivery-yolo.jsonl")
	writeHistoryTestSession(t, path, "continue the delivery")
	checkpoint := evidence.DeliveryCheckpoint{
		ScopeID:             "goal-test-scope",
		CriteriaEstablished: true,
		WorkObserved:        true,
		MutationObserved:    true,
		PendingMutation:     true,
	}
	state := map[string]any{
		"goal":               "ship the combined mode",
		"status":             goalStatus,
		"scopeID":            checkpoint.ScopeID,
		"deliveryCheckpoint": checkpoint,
	}
	data, err := json.Marshal(state)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(store.SessionGoalState(path), data, 0o600); err != nil {
		t.Fatalf("write Goal sidecar: %v", err)
	}

	loaded, err := agent.LoadSession(path)
	if err != nil {
		t.Fatalf("load session: %v", err)
	}
	exec := agent.New(nil, nil, loaded, agent.Options{}, event.Discard)
	oldCtrl := control.New(control.Options{Executor: exec, SessionDir: dir, SessionPath: path, Label: "test/model", Sink: event.Discard})
	oldCtrl.Resume(loaded, path)

	app := NewApp()
	app.ctx = context.Background()
	app.readyHook = func() {}
	tab := &WorkspaceTab{
		ID: "tab_goal_delivery_yolo", Scope: "global", Ready: true,
		SessionPath: path, model: "test/model", tokenMode: boot.TokenModeFull,
		mode: "yolo", toolApprovalMode: control.ToolApprovalYolo,
		goal: "stale tab goal", Ctrl: oldCtrl,
		disabledMCP: map[string]ServerView{},
	}
	tab.sink = &tabEventSink{tabID: tab.ID, app: app}
	app.tabs = map[string]*WorkspaceTab{tab.ID: tab}
	app.tabOrder = []string{tab.ID}
	app.activeTabID = tab.ID
	if err := tab.ensureSessionLease(path); err != nil {
		t.Fatalf("ensure session lease: %v", err)
	}
	t.Cleanup(func() {
		if ctrl := app.controllerForTab(tab); ctrl != nil {
			ctrl.Close()
		}
		tab.releaseSessionLease()
	})
	return app, tab, oldCtrl, path
}

func TestGoalDeliveryYoloTokenSwitchPreservesBlockedGoalCheckpoint(t *testing.T) {
	app, tab, oldCtrl, path := newGoalDeliveryYoloTestApp(t, control.GoalStatusBlocked)
	if err := app.SetTokenModeForTab(tab.ID, boot.TokenModeDelivery); err != nil {
		t.Fatalf("SetTokenModeForTab: %v", err)
	}
	ctrl := app.controllerForTab(tab)
	if ctrl == nil || ctrl == oldCtrl {
		t.Fatal("token-mode switch did not install a replacement controller")
	}
	if ctrl.GoalStatus() != control.GoalStatusBlocked || ctrl.Goal() != "ship the combined mode" {
		t.Fatalf("rebuilt Goal = (%q, %q), want blocked Goal", ctrl.Goal(), ctrl.GoalStatus())
	}
	if ctrl.ToolApprovalMode() != control.ToolApprovalYolo {
		t.Fatalf("tool approval = %q, want yolo", ctrl.ToolApprovalMode())
	}
	if currentTabTokenMode(tab) != boot.TokenModeDelivery {
		t.Fatalf("token mode = %q, want delivery", currentTabTokenMode(tab))
	}
	var persisted struct {
		DeliveryCheckpoint evidence.DeliveryCheckpoint `json:"deliveryCheckpoint"`
	}
	data, err := os.ReadFile(store.SessionGoalState(path))
	if err != nil {
		t.Fatalf("read Goal sidecar: %v", err)
	}
	if err := json.Unmarshal(data, &persisted); err != nil {
		t.Fatalf("decode Goal sidecar: %v", err)
	}
	if persisted.DeliveryCheckpoint.ScopeID != "goal-test-scope" || !persisted.DeliveryCheckpoint.PendingMutation {
		t.Fatalf("persisted checkpoint = %+v", persisted.DeliveryCheckpoint)
	}
	if !app.ResumeGoalForTab(tab.ID) || ctrl.GoalStatus() != control.GoalStatusRunning {
		t.Fatal("blocked Goal did not resume after controller rebuild")
	}
}

func TestGoalDeliveryYoloTokenSwitchDoesNotReviveCompletedGoal(t *testing.T) {
	app, tab, _, _ := newGoalDeliveryYoloTestApp(t, control.GoalStatusComplete)
	if err := app.SetTokenModeForTab(tab.ID, boot.TokenModeDelivery); err != nil {
		t.Fatalf("SetTokenModeForTab: %v", err)
	}
	ctrl := app.controllerForTab(tab)
	if ctrl.GoalStatus() == control.GoalStatusRunning {
		t.Fatalf("completed Goal was revived: goal=%q status=%q", ctrl.Goal(), ctrl.GoalStatus())
	}
	if app.ResumeGoalForTab(tab.ID) {
		t.Fatal("completed Goal should not be resumable")
	}
}

func TestGoalAndCollaborationResyncBeforeSendPreserveRunningDeliveryScope(t *testing.T) {
	app, tab, ctrl, path := newGoalDeliveryYoloTestApp(t, control.GoalStatusRunning)
	tab.goal = ctrl.Goal()
	app.SetCollaborationModeForTab(tab.ID, "goal")
	app.SetGoalForTab(tab.ID, ctrl.Goal())

	var persisted struct {
		ScopeID string `json:"scopeID"`
	}
	data, err := os.ReadFile(store.SessionGoalState(path))
	if err != nil {
		t.Fatalf("read Goal sidecar: %v", err)
	}
	if err := json.Unmarshal(data, &persisted); err != nil {
		t.Fatalf("decode Goal sidecar: %v", err)
	}
	if persisted.ScopeID != "goal-test-scope" {
		t.Fatalf("Goal resync replaced delivery scope: got %q", persisted.ScopeID)
	}
}

func TestTokenModeSwitchWaitsForForegroundTurnAdmission(t *testing.T) {
	app, tab, _, _ := newGoalDeliveryYoloTestApp(t, control.GoalStatusBlocked)
	tab.turnStartMu.Lock()
	done := make(chan error, 1)
	go func() { done <- app.SetTokenModeForTab(tab.ID, boot.TokenModeDelivery) }()
	select {
	case err := <-done:
		t.Fatalf("token-mode switch crossed the turn-admission gate: %v", err)
	case <-time.After(50 * time.Millisecond):
	}
	tab.turnStartMu.Unlock()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("SetTokenModeForTab after admission release: %v", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("token-mode switch did not finish after turn admission released")
	}
}
