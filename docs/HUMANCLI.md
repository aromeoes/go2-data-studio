# HumanCLI in Go2 Data Studio

The web chat and terminal client now submit turns to the pinned DimOS `McpClient` agent. Natural-language instructions are interpreted by the selected tool-capable model, rather than routed through the original fixed-phrase parser. The custom dashboard and Web SDK remain in place; the upstream terminal UI is not embedded in the page.

## Model configuration

Open HumanCLI and expand **Agent model**. Choose OpenAI, Anthropic, Google Gemini or Ollama, enter a model ID, and provide the relevant credential. OpenAI-compatible HTTPS endpoints and local Ollama endpoints are supported. Model IDs do not include the provider prefix. Models must support tool calling; camera questions additionally require image support.

The bundled runtime currently has OpenAI and Ollama integrations. Anthropic and Google require their corresponding LangChain packages in that same Python environment. The dashboard reports a missing package instead of pretending the provider is ready. Optional dependency groups are declared in `pyproject.toml`.

Configuration precedence is process environment, application `.env`, saved `humancli.json`, and defaults. `.env.example` documents `HUMANCLI_PROVIDER`, `HUMANCLI_MODEL`, `HUMANCLI_BASE_URL`, `HUMANCLI_VISION` and provider-specific keys. Environment overrides are read at application startup; the UI identifies environment-managed settings.

Existing OpenAI credentials and vision preference in `vision.json` remain usable for the default OpenAI endpoint. New settings are atomically saved in `humancli.json` with owner-only permissions. Public state never includes the API key. Changing provider or endpoint does not silently forward an old credential or enable images for the new destination.

Conversation text and requested tool results are sent to the selected model. Camera images are only retrieved when the camera tool is requested, vision has been enabled, and the image is fresh. No more than one image is retrieved per turn. Old images are removed from model history after the turn. OpenAI requests set `store=false`; other providers use their own retention policies. No provider is contacted merely by opening the dashboard or saving settings.

## Tools

The information tooltip is generated from the same registry used to build the agent's MCP tool definitions:

| Tool | Behavior |
| :--- | :--- |
| `robot_status` | Battery, connection, navigation explanations, sensor freshness and recording state |
| `move_relative` | One relative navigation goal, 0.2 to 5 meters, in known free space |
| `start_exploration` | Start frontier exploration while retaining the HumanCLI control lease |
| `stop_navigation` | Close the navigation velocity gate and cancel exploration and planner goals |
| `camera_view` | One requested recent image, when vision is enabled |
| `list_recordings` | Space and segment IDs, names and generated-map status |
| `start_recording` | Record in the selected space or an explicitly identified space |
| `save_recording` | Save the current session and return its segment IDs |
| `generate_map` | Queue a versioned map for a saved segment after navigation is paused |

Examples: “Why did you stop?”, “Walk one meter backward”, “Start recording and explore this space”, “Stop, save this recording and generate its map”. Tool results report requested/accepted/queued operations; they do not claim the robot has reached a destination or that a map is finished.

Exact stop commands bypass the model and do not require credentials. This is a software navigation pause, not an electrical emergency stop. The dashboard Stop control remains available. Arbitrary shell, file deletion, motor shutdown, posture changes, cloud upload, multi-segment merging and semantic room navigation are not exposed as agent tools.

## Integration and cancellation

`agent_worker.py` subclasses the official DimOS `McpClient`. It uses its tool conversion and conversation-processing loop, with LangChain provider initialization and LangGraph tool execution. The adaptation points are pinned upstream internals; review them when upgrading DimOS. Source reference: https://github.com/dimensionalOS/dimos/blob/c1c3cdc9d2ee54ca72259465688395699d7d99a2/dimos/agents/mcp/mcp_client.py

Each turn runs in a separate process. Private JSON-lines IPC supplies MCP tool definitions and forwards tool calls to the supervisor's guarded services. RPC registration is disabled in this worker, so no additional robot bus or public MCP server is started. The selected model credential travels over stdin, not command-line arguments. Robot and Cloud credentials are excluded from the child environment.

The API acknowledges a submitted turn immediately. The existing SDK state stream then carries tool activity, replies and busy state. The browser continues its control heartbeat independently. Turns have a two-minute deadline, model-call timeouts, bounded tool count, bounded model output and graph recursion. Tool IPC is serialized even when a model emits multiple calls.

Each tool validates the conversation, robot process, connection, control mode and epoch. Switching modes, losing control, resetting the conversation, cancelling the response or closing the app prevents subsequent tool execution. A movement attempt with an unknown transport outcome cannot be retried within the same turn. Cancel response stops further reasoning and tool calls; it does not undo already accepted actions. Use Stop to halt movement.

Navigation pause blocks late planner velocity messages while keeping chat's lease available. A new navigation request must pass the current epoch check before reopening that gate. Existing sensor watchdogs remain active. No new motion starts after the browser loses its lease.

Conversation history resets on connection changes, explicit New conversation or 30 minutes of inactivity. Oversized model context is reset at a turn boundary without splitting tool-call/result pairs. Replies are requested in English.

## Validation and activation

Validation: 100 backend tests and 14 frontend tests pass; Ruff and the production build pass. The provider form was inspected in an isolated browser preview.

Tests exercise the actual DimOS MCP client and LangGraph loop with a deterministic model in an isolated subprocess: tool dispatch, image follow-up, cancellation and provider-error redaction. Additional tests cover credentials, typed arguments, stale authority, the recording/exploration/map workflow and the navigation gate. No live provider request or physical robot motion is used in those tests.

This update remains prepared separately from the running physical dashboard. Follow the stop, save and disconnect sequence in AGENTS.md before activating it. Hardware behavior and the selected provider/model should be checked after activation with the operator present.
