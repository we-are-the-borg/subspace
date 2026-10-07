# Pre-tool interrupt with immediate exit

Session `01a0f731-55df-7840-a9c2-0ae0d1fc69ad`. The prompt was interrupted before any tool call and delivered `Interrupt` without stop. The user then shut down the CLI, requiring two Ctrl-C presses.

The key sequence is user-reported UI evidence, not a timestamped payload fact. `SessionEnd` was deliberately not subscribed, so its absence does not independently prove exit or delivery failure.

Source files are the three raw capture JSON files for this session, from `1790853604-46463-AX4T1o.json` through `1790853605-46561-zQarhl.json`, numbered by captured delivery order.
