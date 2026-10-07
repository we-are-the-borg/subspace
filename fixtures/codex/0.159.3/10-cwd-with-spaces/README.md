# Project cwd containing spaces

Session `01a0f73c-f632-7622-a755-51d3ace56468`, captured from `tools/hook-capture/codex/captures/project with spaces` while inheriting the outer project's hook definition.

Every payload preserves the full cwd containing spaces. The first `pwd` turn has a paired tool call and stop. The second turn starts a running sleep and ends with interrupt; no post or stop was captured. Its absence does not prove process termination.

This establishes inherited-hook delivery and cwd preservation on macOS. It does not cover an installed plugin path containing spaces or another operating system.

Source files are the eight raw JSON files in the nested capture tree, from `1790854396-52040-rzrzab.json` through `1790854431-52454-FWAIIC.json`, numbered by captured delivery order.
