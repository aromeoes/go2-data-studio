# Go2 setup console

This is the local Go2 product, separate from the marketing repository and the pinned DimOS runtime. Do not modify the pinned framework checkout.

## Physical robot maintenance

A fall was reported during the control-debugging session on 2026-09-21. Cause is unconfirmed. Treat software disconnect, process restart, runtime replacement and electrical shutdown as separate operations.

Before a planned disconnect or restart of a physical robot session:

1. Stop navigation and Teleop.
2. Ask the Go2 to lie down only with the operator present.
3. Wait for the operator to visually confirm the robot is lying down and supported. A successful API response is not sufficient.
4. Save any recording and then close the connection using the guarded dashboard flow.

Never restart a live physical session automatically as part of deploying code without that posture confirmation. Do not issue an automatic lie-down after network loss, or claim it succeeded when the link is unavailable. External power loss, firmware faults, process crashes and emergency stops cannot guarantee a controlled posture.

After a reported fall, leave the console disconnected. Do not reconnect or run motion experiments until the user explicitly asks to resume. Use replay and mocks for regression checks.
