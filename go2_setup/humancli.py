"""Terminal client for the same control authority used by the web console."""

import os
import time
import threading
import requests


def main():
    base = f"http://127.0.0.1:{os.environ.get('GO2_SETUP_PORT', '8780')}/api"
    headers = {"X-Go2-Request": "1"}

    def call(path, data=None):
        r = requests.post(base + path, json=data or {}, headers=headers, timeout=20)
        if not r.ok:
            raise RuntimeError(r.json().get("detail", r.text))
        return r.json()

    result = call("/mode", {"mode": "agent"})
    epoch = result["epoch"]
    done = threading.Event()

    def heartbeat():
        while not done.wait(0.4):
            try:
                if not call("/heartbeat", {"epoch": epoch})["ok"]:
                    done.set()
                    print("\nControl was revoked by another interface. Close and reopen this CLI.")
            except requests.RequestException:
                done.set()

    threading.Thread(target=heartbeat, daemon=True).start()
    print(
        "DimOS HumanCLI. Ask about status, navigation, recordings or maps. Ctrl+C cancels and exits."
    )
    seen = set()
    try:
        while not done.is_set():
            text = input("go2 > ").strip()
            if not text or done.is_set():
                continue
            try:
                call("/agent", {"text": text, "epoch": epoch})
            except RuntimeError as error:
                print(error)
            while not done.is_set():
                state = requests.get(base + "/state", timeout=5).json()
                for index, message in enumerate(state["agent"]["messages"]):
                    marker = (state["agent"]["conversation_id"], index, message["ts"])
                    if marker not in seen and message["role"] != "user":
                        print(f"{message['role']}: {message['text']}")
                    seen.add(marker)
                if not state["agent"]["busy"]:
                    break
                time.sleep(0.3)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        done.set()
        call("/agent/cancel")
        # Only release our own lease, never cancel a new controller's mission.
        call("/release", {"epoch": epoch})


if __name__ == "__main__":
    main()
