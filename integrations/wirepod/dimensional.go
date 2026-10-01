// Build using the same Go toolchain as wire-pod, with -buildmode=plugin.
// No robot token is sent to the application and no SDK control is acquired here.
package main

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
    "net/url"
	"os"
	"strings"
	"time"
)

var Utterances = []string{"dimensional"}
var Name = "Dimensional HumanCLI"

type config struct {
	URL       string `json:"url"`
	TokenFile string `json:"token_file"`
}

func forward(text, serial string) error {
	filename := os.Getenv("DIMENSIONAL_VOICE_CONFIG")
	if filename == "" {
		filename = "/data/chipper/dimensional-voice.json"
	}
	raw, err := os.ReadFile(filename)
	if err != nil {
		return err
	}
	var cfg config
	if err = json.Unmarshal(raw, &cfg); err != nil {
		return err
	}
    // Local app service, including its dynamic desktop port. Never follow redirects.
    u, err := url.Parse(cfg.URL)
    if err != nil || u.Scheme != "http" || u.Hostname() != "127.0.0.1" || u.Port() == "" || u.User != nil || u.Path != "" || u.RawQuery != "" || u.Fragment != "" {
        return fmt.Errorf("use the local app's loopback URL")
    }
	secret, err := os.ReadFile(cfg.TokenFile)
	if err != nil {
		return err
	}
	client := &http.Client{Timeout: 4 * time.Second, CheckRedirect: func(req *http.Request, via []*http.Request) error { return http.ErrUseLastResponse }}
	send := func(method, path string, body []byte) ([]byte, error) {
		req, err := http.NewRequest(method, cfg.URL+path, bytes.NewReader(body))
		if err != nil {
			return nil, err
		}
		req.Header.Set("Authorization", "Bearer "+strings.TrimSpace(string(secret)))
		req.Header.Set("X-Go2-Request", "1")
		req.Header.Set("Content-Type", "application/json")
		res, err := client.Do(req)
		if err != nil {
			return nil, err
		}
		defer res.Body.Close()
		if res.StatusCode != 200 {
			return nil, fmt.Errorf("HumanCLI unavailable (%d)", res.StatusCode)
		}
		return io.ReadAll(io.LimitReader(res.Body, 8192))
	}
	raw, err = send("GET", "/api/vector/wirepod/session", nil)
	if err != nil {
		return err
	}
	var session map[string]interface{}
	if err = json.Unmarshal(raw, &session); err != nil {
		return err
	}
	if session["serial"] != serial {
		return fmt.Errorf("the app is connected to a different robot")
	}
	id := make([]byte, 16)
	if _, err = rand.Read(id); err != nil {
		return err
	}
	session["id"], session["text"] = hex.EncodeToString(id), text
	raw, err = json.Marshal(session)
	if err != nil {
		return err
	}
	_, err = send("POST", "/api/vector/wirepod/transcript", raw)
	// Never retry: a lost response may follow an accepted physical command.
	return err
}

func Action(transcribedText, botSerial, guid, target string) (string, string) {
	_ = guid
	_ = target
	// wire-pod matches substrings; only an explicit prefix opts into our agent.
	text := strings.TrimSpace(transcribedText)
	if !strings.HasPrefix(strings.ToLower(text), "dimensional ") {
		return "", ""
	}
	text = strings.TrimSpace(text[len("dimensional "):])
	if text == "" {
		return "intent_imperative_praise", "Tell Dimensional what you want to do."
	}
	if err := forward(text, botSerial); err != nil {
		return "intent_imperative_praise", "Dimensional is unavailable. Check HumanCLI in the app."
	}
	return "intent_imperative_praise", "Sent to Dimensional."
}
