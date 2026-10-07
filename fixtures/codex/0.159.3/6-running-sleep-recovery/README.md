# Running sleep interrupt with recovery and late post

Session `01a0f735-3b55-7ca0-848e-6d8a30065041`. A shell call started `sleep 30`, returned a running-process session ID, and was confirmed running before the wait turn was interrupted.

The next `pwd` turn completed with its pre/post pair and stop. Only afterward did the original sleep call deliver its matching `PostToolUse`, about 30 seconds after its pre event. There is no stop for the interrupted turn. Consumers must accept a post for an interrupted turn after another turn has stopped.

The empty hook response contains no exit code. The timing is consistent with normal sleep completion, but the payloads do not prove its exit status or that interruption terminated anything.

Source files are the nine raw capture JSON files for this session, from `1790853881-47977-fQ20xE.json` through `1790853914-48405-GKrwGd.json`, numbered by captured delivery order. `009-PostToolUse.json` is deliberately the late post for `003-PreToolUse.json`.
