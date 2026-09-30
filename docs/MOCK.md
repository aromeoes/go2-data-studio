# Mock mode

Mock mode runs the real application UI against a simulated backend, robot and
DimOS Cloud, all inside the browser. Use it to rehearse and design flows without
a Go2, the Python backend, a DimOS runtime or an account.

```sh
cd web
npm ci
npm run mock
```

This opens `http://127.0.0.1:8797/mock.html`. The normal entry (`index.html`) and
the production build never load the mock; `web/src/mock/` is only reachable
through `mock.html`.

## What is simulated

| Area | Behavior |
| :--- | :--- |
| Saved robots | A Go2 and a Vector. Add, edit and availability checks work. |
| Connect | Connecting, then online, with the chosen delay. An unreachable robot keeps retrying with the real error text. |
| Session setup | Both presets and Customize. Starting a session rebuilds the runtime, as the real app does. |
| Camera | A first-person view of a simulated room, drawn from the robot pose. |
| Map | Occupancy grid that fills in as the robot observes the room. |
| Teleop | Keyboard, touch pad and a physical gamepad move the simulated robot. Walls block it. |
| Explore | The robot drives to unobserved areas until none remain. |
| HumanCLI | Scripted replies. Tagging, named navigation, patrol, relative moves and speech change robot state. |
| Recording | Sessions and segments with growing sizes. A dropped connection interrupts the segment. |
| Maps | Queued, running, then ready or failed. |
| DimOS Cloud | Signed in or out, device sign-in code, named uploads with pause, failure and resume. |
| Unitree actions | The real 40 entries from the pinned DimOS registry. Sending one is acknowledged. |

Vector connects and drives, but its skills are not simulated. Voice transcription,
file downloads and Rerun are not simulated.

## Controls

The **MOCK MODE** chip in the bottom right corner opens the controls.

* **Scenario:** device state at launch (returning user or first run), cloud
  account, which robots answer on the network, connect time, session start time,
  and whether a HumanCLI model is configured. The scenario is remembered in the
  browser. Data created while using the app is lost on reload.
* **Trigger now:** drop the connection, freeze sensors (control stops after 10
  seconds, as in the app), set the battery level, fail the next upload or map,
  approve or expire a cloud sign-in, reset everything.
* **Deck size window:** opens the app in a 1280 by 800 window.

The backend is also available in the browser console as `mock`, for example
`mock.dropConnection()` or `mock.snapshot()`.

## Limits

Timings, sizes, battery and map quality are fixtures, not measurements. The mock
follows the API as of this commit; when an endpoint or state field changes in
`go2_setup/api.py`, update `web/src/mock/backend.ts` to match. Passing a flow in
mock mode says nothing about physical robot behavior.

## Files

* `web/mock.html`, `web/src/mock/entry.ts`: entry point.
* `web/src/mock/backend.ts`: simulated backend and robot runtime.
* `web/src/mock/world.ts`: room, LiDAR reveal, routes and camera view.
* `web/src/mock/install.ts`: replaces `fetch` for `/api` and the SDK object.
* `web/src/mock/Panel.tsx`: controls.
* `web/src/mock/fixtures.ts`, `generated.ts`: seed data and catalogs.
* `web/src/mock/backend.test.ts`: flow tests.
