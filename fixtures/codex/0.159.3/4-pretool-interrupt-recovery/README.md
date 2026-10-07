# Pre-tool interrupt with recovery

Session `01a0f72f-bc80-7822-bc97-ecba336ba9dc`. The first prompt was interrupted before the model issued any tool call, so its turn has `UserPromptSubmit` and `Interrupt` without pre, post or stop events. A later `pwd` turn in the same session completed with a matching pre/post pair and stop.

This run establishes recovery after a turn-level interrupt. It is not evidence of interrupting a running command.

Source files are the seven raw capture JSON files for this session, from `1790853519-45545-lpH0Z4.json` through `1790853541-45880-zEyXCD.json`, numbered by captured delivery order.
