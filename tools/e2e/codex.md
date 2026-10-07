# Codex installed-plugin verification

Procedure for Codex CLI 0.159.3 on macOS. The user starts every interactive or
headless session. The staging helper only copies the adapter into a disposable
local marketplace; it never launches Codex or edits personal configuration.
Test commands below were checked against this version's CLI help. The results
(data roots, trust after updates, data kept on uninstall) are in contract §2 and
§11. Fetching published release tags and other platforms are outside this local
test.

## 1. Stage and install without a published release

Run from the subspace repository. Keep this terminal for the later steps:

```sh
SUBSPACE_E2E_REPO="$PWD"
SUBSPACE_E2E_WORK=$(mktemp -d /tmp/subspace-codex-e2e.XXXXXX)
python3 tools/e2e/codex-stage.py "$SUBSPACE_E2E_WORK/marketplace baseline"
mkdir "$SUBSPACE_E2E_WORK/project"
git -C "$SUBSPACE_E2E_WORK/project" init -q
codex --version
codex plugin list --json
```

The marketplace and installed-cache paths deliberately contain spaces. The
plugin/marketplace identity remains `subspace@subspace`. If that plugin or a
marketplace named `subspace` is already installed in the selected Codex home,
preserve it and use the isolated custom-home step first; do not replace an
existing install solely for this test. Also note any existing data directory,
so new events can be distinguished from historical data. `SUBSPACE_DIR` must be
unset when checking Codex's own data-root selection.

For the **default home** test, use a shell with `CODEX_HOME` and `SUBSPACE_DIR`
unset (check with `printenv CODEX_HOME SUBSPACE_DIR`):

```sh
codex plugin marketplace add "$SUBSPACE_E2E_WORK/marketplace baseline" --json
codex plugin add subspace@subspace --json
codex plugin list --marketplace subspace --json
codex --no-daemon -C "$SUBSPACE_E2E_WORK/project"
```

Trust the disposable project if requested. Open `/hooks`, review the installed
subspace definitions and trust all eleven hooks. Do not bypass trust. Send:

> Run `pwd` and then `sh -c 'exit 7'`, each exactly once. Report both exit codes.

Wait for the turn to complete, then send a second short prompt (`Reply with
e2e-ready.`) and exit normally. Record hook errors/warnings if any. Verify the
CLI entry is installed/enabled and the marker is version `0.0.0`:

```sh
cat "$HOME/.codex/plugins/data/subspace-subspace/plugin.json"
SUBSPACE_E2E_DAY=$(date -u +%Y-%m-%d)
sh "$SUBSPACE_E2E_REPO/tools/e2e/check.sh" \
  "$HOME/.codex/plugins/data/subspace-subspace/events/$SUBSPACE_E2E_DAY"
```

Check new events have `source: codex`, the disposable project's cwd, matching
pre/post tool IDs, the actual script parent PID, and unchanged raw tool input.
The checker validates schema/layout/permissions and fixture keys, not a rollout
exit code. Read the referenced rollout to confirm the failed call and accept an
empty shell `tool_response`. Confirm schema and marker files exist and match the
installed adapter. No `SessionEnd` is expected; teardown can lose final events.

## 2. Custom Codex home

Use a per-command environment prefix, keeping the shell's existing `CODEX_HOME`
unchanged. The custom home deliberately contains spaces:

```sh
mkdir "$SUBSPACE_E2E_WORK/codex home"
CODEX_HOME="$SUBSPACE_E2E_WORK/codex home" codex login
CODEX_HOME="$SUBSPACE_E2E_WORK/codex home" codex plugin marketplace add \
  "$SUBSPACE_E2E_WORK/marketplace baseline" --json
CODEX_HOME="$SUBSPACE_E2E_WORK/codex home" codex plugin add subspace@subspace --json
CODEX_HOME="$SUBSPACE_E2E_WORK/codex home" codex --no-daemon \
  -C "$SUBSPACE_E2E_WORK/project"
```

Trust the project and installed hooks in this home. Send this prompt:

> Run `pwd` and then `sh -c 'exit 7'`, each exactly once. Report both exit codes.

Wait for the turn to complete, then send:

> Reply with e2e-ready.

Wait for that turn to complete and exit normally. Login is only needed to start
a real agent; do not copy credentials into the repository. If login uses shared
OS credentials, record that separately.

```sh
cat "$SUBSPACE_E2E_WORK/codex home/plugins/data/subspace-subspace/plugin.json"
sh "$SUBSPACE_E2E_REPO/tools/e2e/check.sh" \
  "$SUBSPACE_E2E_WORK/codex home/plugins/data/subspace-subspace/events/$(date -u +%Y-%m-%d)"
```

Confirm these sessions only wrote under the custom plugin data root, with no
new event for their session IDs in the default root. Also run a user-started
`codex exec` ephemeral session after trust, to verify installed-plugin null paths:

```sh
CODEX_HOME="$SUBSPACE_E2E_WORK/codex home" codex exec \
  'Run pwd exactly once and report the directory.' \
  -C "$SUBSPACE_E2E_WORK/project" --ephemeral --sandbox read-only --json
```

Check delivered ephemeral events have `transcript_path: null` and pass the same
checker. Missing async terminal events must be recorded rather than hidden by
repeating until a desired result appears.

## 3. Upgrade and hook trust (custom home)

The following versions exist only in disposable copies. Repository manifests
and release tags are managed by release-please and are never bumped manually.

```sh
python3 "$SUBSPACE_E2E_REPO/tools/e2e/codex-stage.py" \
  "$SUBSPACE_E2E_WORK/marketplace version only" --revision version-only
CODEX_HOME="$SUBSPACE_E2E_WORK/codex home" codex plugin marketplace remove subspace
CODEX_HOME="$SUBSPACE_E2E_WORK/codex home" codex plugin marketplace add \
  "$SUBSPACE_E2E_WORK/marketplace version only"
CODEX_HOME="$SUBSPACE_E2E_WORK/codex home" codex plugin add subspace@subspace
CODEX_HOME="$SUBSPACE_E2E_WORK/codex home" codex --no-daemon \
  -C "$SUBSPACE_E2E_WORK/project"
```

Inspect `/hooks` **before** trusting anything again. Record whether unchanged
definitions retain trust. Send `Reply with e2e-ready.`, wait for the turn to
complete and exit normally. In the terminal, verify marker version `0.0.1`:

```sh
cat "$SUBSPACE_E2E_WORK/codex home/plugins/data/subspace-subspace/plugin.json"
```

Then repeat with a changed hook definition:

```sh
python3 "$SUBSPACE_E2E_REPO/tools/e2e/codex-stage.py" \
  "$SUBSPACE_E2E_WORK/marketplace changed hook" --revision changed-hook
CODEX_HOME="$SUBSPACE_E2E_WORK/codex home" codex plugin marketplace remove subspace
CODEX_HOME="$SUBSPACE_E2E_WORK/codex home" codex plugin marketplace add \
  "$SUBSPACE_E2E_WORK/marketplace changed hook"
CODEX_HOME="$SUBSPACE_E2E_WORK/codex home" codex plugin add subspace@subspace
CODEX_HOME="$SUBSPACE_E2E_WORK/codex home" codex --no-daemon \
  -C "$SUBSPACE_E2E_WORK/project"
```

Only `SessionStart` has a changed definition (a harmless trailing command
space). Inspect `/hooks` before re-trust; record which hooks are skipped and
which retain trust. Review/trust the changed definition, exit and start a fresh
session so a new `SessionStart` can arrive. Send `Reply with e2e-ready.`, wait
for the turn to complete, exit,
verify marker version `0.0.2`, and run the checker again. This tests changed
definitions separately from a version-only upgrade; it is not a published
release or remote tag-fetch test.

## 4. Uninstall

After all sessions using each test install have exited:

```sh
CODEX_HOME="$SUBSPACE_E2E_WORK/codex home" codex plugin remove subspace@subspace --json
CODEX_HOME="$SUBSPACE_E2E_WORK/codex home" codex plugin list --marketplace subspace --json
test -f "$SUBSPACE_E2E_WORK/codex home/plugins/data/subspace-subspace/plugin.json"
test ! -e "$SUBSPACE_E2E_WORK/codex home/plugins/cache/subspace/subspace"
CODEX_HOME="$SUBSPACE_E2E_WORK/codex home" codex plugin marketplace remove subspace
```

Record that the installed entry/cache disappear while marker/events/schema
remain. For the default-home test install, with `CODEX_HOME` unset and after
its sessions have exited:

```sh
codex plugin remove subspace@subspace --json
codex plugin list --marketplace subspace --json
test -f "$HOME/.codex/plugins/data/subspace-subspace/plugin.json"
test ! -e "$HOME/.codex/plugins/cache/subspace/subspace"
```

Remove the default-home test marketplace only if this procedure added it:

```sh
codex plugin marketplace remove subspace
```

Persistent data is expected; purge it only if desired after reviewing the
resolved root. Keep both data roots and the disposable test home until results
have been reviewed. None of these checks prove Linux/WSL/native Windows support.
