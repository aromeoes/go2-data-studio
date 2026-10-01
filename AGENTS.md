# Go2 setup console

This is the local Go2 product, separate from the marketing repository and the pinned DimOS runtime. Do not modify the pinned framework checkout.

## Physical robot maintenance

A fall was reported during the control-debugging session on 2026-09-21. Cause is unconfirmed. Treat software disconnect, process restart, runtime replacement and electrical shutdown as separate operations.

Before a planned disconnect or restart of a physical robot session:

1. Stop navigation and Teleop.
2. Save any recording and close the connection through the dashboard.
3. Reconnect with movement idle; never resume a mission automatically.

The user explicitly removed posture validation on 2026-09-28. Do not require a posture checkbox, a posture-confirmation button, or a visual posture report before configuring sessions or disconnecting. Do not automatically issue posture commands as part of those operations. Software disconnect, runtime restart and electrical shutdown remain separate operations.

After a reported fall, leave the console disconnected. Do not reconnect or run motion experiments until the user explicitly asks to resume. Use replay and mocks for regression checks.
