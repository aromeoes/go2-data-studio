package main

import (
	"encoding/json"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestPrefixDoesNotInterceptNativeRequests(t *testing.T) {
	intent, text := Action("what is dimensional", "robot", "private-robot-token", "target")
	if intent != "" || text != "" {
		t.Fatal("intercepted native request")
	}
}
func TestTranscriptAndCredentialBoundary(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	token := filepath.Join(dir, "token")
	os.WriteFile(token, []byte("voice-token"), 0600)
	cfg := filepath.Join(dir, "config")
	os.WriteFile(cfg, []byte(`{"url":"http://`+listener.Addr().String()+`","token_file":"`+token+`"}`), 0600)
	t.Setenv("DIMENSIONAL_VOICE_CONFIG", cfg)
	calls := 0
	mux := http.NewServeMux()
	mux.HandleFunc("/api/vector/wirepod/session", func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer voice-token" {
			t.Error("wrong voice credential")
		}
		w.Write([]byte(`{"serial":"robot","epoch":4,"robot_id":"saved","conversation_id":"chat","issued":1}`))
	})
	mux.HandleFunc("/api/vector/wirepod/transcript", func(w http.ResponseWriter, r *http.Request) {
		calls++
		var body map[string]interface{}
		json.NewDecoder(r.Body).Decode(&body)
		if body["text"] != "look up" || body["serial"] != "robot" || body["id"] == "" {
			t.Error("wrong transcript")
		}
		raw, _ := json.Marshal(body)
		if strings.Contains(string(raw), "private-robot-token") {
			t.Error("robot token leaked")
		}
		w.WriteHeader(409) // Must never retry an ambiguous/failed submission.
	})
	server := &http.Server{Handler: mux}
	go server.Serve(listener)
	defer server.Close()
	Action("dimensional look up", "robot", "private-robot-token", "192.168.1.71")
	if calls != 1 {
		t.Fatalf("expected exactly one submission, got %d", calls)
	}
}
