# UX flow prototype

A wireframe of the redesigned app: flow, screens and components, without visual
design. It runs on the mock backend (see [MOCK.md](MOCK.md)), so no robot,
Python backend or account is needed.

```sh
cd web
npm ci
npm run flow
```

This opens `http://127.0.0.1:8798/flow.html`. It works with keyboard and mouse on
a Mac and with the controller and touchscreen on a Steam Deck (1280 by 800). The
current app (`index.html`) and mock mode (`mock.html`) are unchanged.

## Flow

1. **Onboarding**, only when nobody is signed in: Log into Dimensional
   (complimentary hosting) or Stay Local.
2. **Log into Dimensional**: QR code, code and link. The screen stays the same;
   when the 15 minute code expires a new one replaces it.
3. **Connect your robot**: scans saved robots. The first one found opens Robot
   found with a 15 second timer (Connect or Cancel; it never connects on its
   own). The list stays available, with Add robot (choose Go2 or Vector, then its
   fields) and Scan again. With no saved robots, Add robot opens directly.
4. **Start Session**: the robot connects in the background with only the
   required modules while the user picks a blueprint. Teleop is recommended and
   fixed; Custom lets you choose modules, adding what they depend on. Modules
   are a compact checklist in two groups, DimOS modules and App modules: real
   module name, icons for what they do, a lock on required ones, and modules the
   robot cannot run disabled with a short reason. Descriptions appear as
   tooltips on hover or controller focus. The robot picture
   becomes the live camera with frame rate and data rate. START adds the
   selected modules to the same connection. Install community module is
   disabled (coming soon).
5. **Session**: camera first, map second, recording bar, and a Teleop / HumanCLI
   panel above the fold; recordings, maps, activity and robot actions below it.
   The menu button opens the sidebar (spaces, DimOS Cloud, local storage).

## Behavior decisions

| Topic | Behavior |
| :--- | :--- |
| Teleop | Always available. W A S D, Q E or the touch pad on a Mac, hold L1 on a Steam Deck. No Enable button. Keyboard control is released after 2.5 seconds without input so other actions can run. |
| HumanCLI | Only in blueprints that include `McpClient`. Autonomous exploration and patrol start from HumanCLI. |
| Taking over | Driving while HumanCLI is moving the robot opens a prompt: Switch to Teleop (stops HumanCLI) or Keep HumanCLI. |
| Movement toggle | Top right of the control panel. Off keeps the robot in place; HumanCLI can still answer. |
| Stop | No header button. Space on the keyboard and B on the controller stop the robot and latch until Release stop. The Movement toggle keeps it in place. |
| End session | Confirms, saves any recording, disconnects and returns to Connect your robot. |
| Spaces | Chosen in the sidebar. A new device starts with "Starting space". The recording bar shows the current space. |
| Failures | Toasts: robot unreachable (back to the robot list), connection lost and recovered, camera or LiDAR data stopping and resuming. |
| Blueprint | Fixed once the session starts. |

## Backend work the real app needs

The mock backend implements these; the Python backend does not yet.

* `POST /api/connect` accepts a `profile` and starts only those modules.
* `POST /api/session/modules` loads the remaining modules into the running
  session without reconnecting, and reports `loading_modules` in the state.
  DimOS supports adding modules to a running coordinator; `go2_setup/runtime.py`
  and the supervisor currently restart the whole runtime instead.
* `POST /api/hold` for the movement toggle.
* `POST /api/cloud/signout`.
* A default "Starting space" when none exists.
* `selected_modules` in the state, and HumanCLI tools limited to the selected
  modules.

## Open items

* Module list, wording and which modules count as required are a first draft
  (`web/src/flow/modules.ts`).
* Robot pictures are placeholders for the pixel-art versions.
* Voice input is not simulated.
* Visual design is not started.
