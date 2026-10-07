#!/bin/sh
# Tests for spool.sh as shipped in adapters/claude-code/ (a copy of core/spool.sh). POSIX sh, no dependencies.
#   sh tests/spool.test.sh              run with /bin/sh
#   SPOOL_SH=dash sh tests/spool.test.sh   run the script under another shell
set -u

here=$(cd "$(dirname "$0")" && pwd)
spool="$here/../adapters/claude-code/scripts/spool.sh"
manifest="$here/../adapters/claude-code/.claude-plugin/plugin.json"
schemas="$here/../adapters/claude-code/schema"
models="$here/../adapters/claude-code/model"
run_sh=${SPOOL_SH:-sh}
# Don't inherit a real plugin environment (e.g. when run from Claude Code).
unset SUBSPACE_DIR CLAUDE_PLUGIN_DATA CLAUDE_PLUGIN_OPTION_RETENTION_DAYS

tmp=$(mktemp -d)
trap 'chmod -R u+w "$tmp" 2>/dev/null; rm -rf "$tmp"' EXIT

pass=0
fail=0
current=
no() { printf 'FAIL [%s] %s\n' "$current" "$*"; fail=$((fail + 1)); }
check() { if eval "$1"; then :; else no "$2"; fi; }

# Fresh $ROOT per test.
setup() {
  current=$1
  root="$tmp/$1"
  mkdir -p "$root"
}

# Runs spool.sh on $root with stdin from $1 (a file), source $src (default
# claude-code) and, if $opt is set, it as retention_days. Fails the test on output or a nonzero exit.
spool() {
  (
    [ -n "${opt+x}" ] && export CLAUDE_PLUGIN_OPTION_RETENTION_DAYS="$opt"
    SUBSPACE_DIR=$root exec "$run_sh" "$spool" "${src-claude-code}" ${event:+"$event"}
  ) < "$1" > "$tmp/out" 2>&1
  code=$?
  [ "$code" -eq 0 ] || no "exit code $code"
  [ -s "$tmp/out" ] && no "printed: $(cat "$tmp/out")"
  return 0
}
payload() { printf '%s' "$1" > "$tmp/payload"; spool "$tmp/payload"; }

# UTC date $1 days ago, via the platform's date (tests may use BSD or GNU).
days_ago() {
  s=$(( $(date +%s) - $1 * 86400 ))
  date -u -r "$s" +%Y-%m-%d 2>/dev/null || date -u -d "@$s" +%Y-%m-%d
}
today=$(days_ago 0)

events() { find "$root/events" -type f 2>/dev/null; }
count() { events | wc -l | tr -d ' '; }
done_test() { pass=$((pass + 1)); }

# --- tests -------------------------------------------------------------------

setup envelope
payload '{"hook_event_name":"Stop"}'
check '[ "$(count)" = 1 ]' "expected 1 file, got $(count)"
f=$(events)
check '[ "$(dirname "$f")" = "$root/events/$today" ]' "not in today's folder: $f"
check 'basename "$f" | grep -Eq "^[0-9]+-[0-9]+-[0-9a-f]+\.json$"' "bad name: $f"
check 'grep -Eq "^\{\"v\":1,\"source\":\"claude-code\",\"ts\":[0-9]+,\"pid\":[0-9]+,\"payload\":\{\"hook_event_name\":\"Stop\"\}\}$" "$f"' \
  "bad envelope: $(cat "$f")"
ts=$(sed 's/.*"ts":\([0-9]*\).*/\1/' "$f")
check '[ $(( $(date +%s) - ts )) -le 5 ]' "ts $ts is not now"
check 'basename "$f" | grep -q "^$ts-"' "name doesn't start with ts"
check '[ "$(ls -A "$root")" = events ]' "wrote outside events/: $(ls -A "$root")"
done_test

setup permissions
payload '{"hook_event_name":"Stop"}'
f=$(events)
check 'ls -ld "$root/events" | grep -q "^drwx------"' "events/ not 0700"
check 'ls -ld "$root/events/$today" | grep -q "^drwx------"' "day folder not 0700"
check 'ls -l "$f" | grep -q "^-rw-------"' "event file not 0600"
done_test

setup empty-stdin
: > "$tmp/empty"
spool "$tmp/empty"
check '[ "$(count)" = 0 ]' "empty stdin was written"
done_test

setup byte-for-byte
# Quotes, backslashes, escapes, tabs, Unicode, CRLF, newlines and a trailing
# newline; plus a large payload.
printf '{"s":"a\\"b\\\\c\\n","u":"äöü ✓ 日本 🚀","t":"\t","x":"%%s $HOME `id`"}\r\n{\n  "second": "line"\n}\n' > "$tmp/special"
awk 'BEGIN { printf "{\"big\":\""; for (i = 0; i < 200000; i++) printf "0123456789"; printf "\"}" }' > "$tmp/big"
for p in special big; do
  before=$(count)
  spool "$tmp/$p"
  f=$(ls -t "$root/events/$today"/*.json | head -n 1)
  check '[ "$(count)" = $((before + 1)) ]' "$p: not written"
  # Rebuild the expected file from its own envelope head and compare bytes.
  { head -n 1 "$f" | sed 's/"payload":.*/"payload":/' | tr -d '\n'; cat "$tmp/$p"; printf '}'; } > "$tmp/expected"
  check 'cmp -s "$f" "$tmp/expected"' "$p: payload changed"
done
done_test

setup retention-default
for d in 0 1 2 3 4 10 400; do mkdir -p "$root/events/$(days_ago $d)"; done
mkdir -p "$root/events/not-a-date" "$root/events/.hidden" "$root/events/0999-09-09"
payload '{"hook_event_name":"Stop"}'
for d in 0 1 2 3; do
  check '[ -d "$root/events/$(days_ago $d)" ]' "deleted $d days ago"
done
for d in 4 10 400; do
  check '[ ! -e "$root/events/$(days_ago $d)" ]' "kept $d days ago"
done
check '[ ! -e "$root/events/0999-09-09" ]' "kept 0999-09-09"
check '[ -d "$root/events/not-a-date" ] && [ -d "$root/events/.hidden" ]' "deleted a folder that is not a day"
done_test

retention() {
  setup "retention-${1:-empty}"
    for d in 0 1 2 5 6 7 30 31 32; do mkdir -p "$root/events/$(days_ago $d)"; done
  opt=$1
  payload '{"hook_event_name":"Stop"}'
  unset opt
  for d in 0 1 2 5 6 7 30 31 32; do
    if [ "$d" -le "$2" ]; then
      check '[ -d "$root/events/$(days_ago $d)" ]' "retention $1: deleted $d days ago"
    else
      check '[ ! -e "$root/events/$(days_ago $d)" ]' "retention $1: kept $d days ago"
    fi
  done
  done_test
}
# option value -> newest day that is kept
retention 1 1
retention 6 6
retention 6.0 6
retention 30 30
retention 0 1
retention 99 30
retention 08 8
retention 0030 30
retention 99999999999999999999 30
retention abc 3
retention '' 3

setup session-start
event=session-start
version=$(sed -n 's/^ *"version": *"\([^"]*\)".*/\1/p' "$manifest")
payload '{"session_id":"x","hook_event_name":"SessionStart","source":"startup"}'
check '[ "$(cat "$root/plugin.json" 2>/dev/null)" = "{\"v\":1,\"version\":\"$version\"}" ]' \
  "bad plugin.json: $(cat "$root/plugin.json" 2>/dev/null)"
check 'ls -l "$root/plugin.json" | grep -q "^-rw-------"' "plugin.json not 0600"
check '[ -z "$(find "$root" -maxdepth 1 -name ".*.tmp")" ]' "left a .tmp file"
check '[ "$(count)" = 1 ]' "SessionStart event not written"
check 'cmp -s "$root/schema/envelope.v1.json" "$schemas/envelope.v1.json"' "schema not copied"
check 'ls -ld "$root/schema" | grep -q "^drwx------"' "schema/ not 0700"
check 'ls -l "$root/schema/envelope.v1.json" | grep -q "^-rw-------"' "schema not 0600"
check '[ -z "$(find "$root/schema" -name ".*.tmp")" ]' "left a .tmp file in schema/"
check 'cmp -s "$root/schema/mapping.v1.json" "$schemas/mapping.v1.json"' "mapping schema not copied"
check 'cmp -s "$root/model/claude-code.json" "$models/claude-code.json"' "mapping document not copied"
check 'cmp -s "$root/model/claude-code-session.json" "$models/claude-code-session.json"' "session-status mapping not copied"
check 'ls -ld "$root/model" | grep -q "^drwx------"' "model/ not 0700"
check 'ls -l "$root/model/claude-code.json" | grep -q "^-rw-------"' "mapping document not 0600"
check '[ -z "$(find "$root/model" -name ".*.tmp")" ]' "left a .tmp file in model/"
echo stale > "$root/plugin.json"
echo stale > "$root/schema/envelope.v1.json"
echo stale > "$root/model/claude-code.json"
payload '{"session_id":"x", "hook_event_name" : "SessionStart", "source":"compact"}'
check 'grep -q "\"version\"" "$root/plugin.json"' "plugin.json not refreshed"
check 'cmp -s "$root/schema/envelope.v1.json" "$schemas/envelope.v1.json"' "schema not refreshed"
check 'cmp -s "$root/model/claude-code.json" "$models/claude-code.json"' "mapping document not refreshed"
unset event
done_test

setup other-events-leave-plugin-json
echo untouched > "$root/plugin.json"
payload '{"hook_event_name":"Stop"}'
payload '{"hook_event_name":"PreToolUse","tool_input":{"command":"echo \"hook_event_name\":\"SessionStart\""}}'
payload '{"hook_event_name":"Stop","tool_response":{"hook_event_name":"SessionStart"}}'
payload '{"hook_event_name":"SessionStart","source":"startup"}'
event=other
payload '{"hook_event_name":"SessionStart"}'
unset event
check '[ "$(cat "$root/plugin.json")" = untouched ]' "plugin.json touched by another event"
check '[ ! -e "$root/schema" ]' "schema/ written by another event"
check '[ ! -e "$root/model" ]' "model/ written by another event"
done_test

setup missing-root
root="$tmp/does/not/exist"
payload '{"hook_event_name":"Stop"}'
check '[ "$(count)" = 1 ]' "missing \$ROOT not created"
check 'ls -ld "$root" | grep -q "^drwx------"' "\$ROOT not 0700"
current=unset-root
: > "$tmp/out"
(cd "$tmp" && unset SUBSPACE_DIR CLAUDE_PLUGIN_DATA; printf '{}' | "$run_sh" "$spool" claude-code > "$tmp/out" 2>&1) \
  || no "exit code $?"
check '[ ! -s "$tmp/out" ] && [ ! -e "$tmp/events" ] && [ ! -e /events ]' "misbehaved without \$ROOT"
done_test

setup plugin-data-fallback
printf '{}' | (unset SUBSPACE_DIR; CLAUDE_PLUGIN_DATA=$root "$run_sh" "$spool" claude-code) > "$tmp/out" 2>&1 || no "exit code $?"
check '[ "$(count)" = 1 ] && [ ! -s "$tmp/out" ]' "CLAUDE_PLUGIN_DATA not used"
done_test

setup source
src=codex
payload '{"hook_event_name":"Stop"}'
check 'grep -q "^{\"v\":1,\"source\":\"codex\"," "$(events)"' "source not taken from the argument: $(cat "$(events)")"
for src in '' 'Claude' 'a b' 'x"y' '../x'; do
  payload '{"hook_event_name":"Stop"}'
done
unset src
spool_noarg() { (SUBSPACE_DIR=$root exec "$run_sh" "$spool") < "$tmp/payload" > "$tmp/out" 2>&1 || no "exit code $?"; }
spool_noarg
check '[ ! -s "$tmp/out" ]' "printed without source"
check '[ "$(count)" = 1 ]' "wrote with a missing or invalid source: $(count) files"
done_test

setup read-only-root
chmod 500 "$root"
payload '{"hook_event_name":"Stop"}'
chmod 700 "$root"
mkdir -p "$root/events"
chmod 500 "$root/events"
payload '{"hook_event_name":"SessionStart"}'
chmod 700 "$root/events"
check '[ "$(count)" = 0 ]' "wrote into a read-only \$ROOT"
done_test

setup parallel
n=200
i=0
while [ $i -lt $n ]; do
  printf '{"n":%s}' "$i" | SUBSPACE_DIR=$root "$run_sh" "$spool" claude-code >> "$tmp/out-parallel" 2>&1 &
  i=$((i + 1))
done
wait
check '[ ! -s "$tmp/out-parallel" ]' "printed during parallel runs"
check '[ "$(count)" = $n ]' "expected $n files, got $(count)"
seen=$(sed -n 's/.*"payload":{"n":\([0-9]*\)}}$/\1/p' "$root/events/$today"/*.json | sort -u | wc -l | tr -d ' ')
check '[ "$seen" = $n ]' "expected $n distinct payloads, got $seen"
bad=$(grep -Lx '{"v":1,"source":"claude-code","ts":[0-9]*,"pid":[0-9]*,"payload":{"n":[0-9]*}}' "$root/events/$today"/*.json)
check '[ -z "$bad" ]' "broken files: $bad"
done_test

setup speed
for d in 0 1 2 3; do mkdir -p "$root/events/$(days_ago $d)"; done
cp "$here/../fixtures/claude-code/2.1.285/1-headless-parallel-subagents/events/019-PostToolBatch.json" "$tmp/fixture"
runs=100
# Seconds for $runs invocations.
measure() {
  SUBSPACE_DIR=$root env time -p "$run_sh" -c 'i=0; while [ $i -lt '"$runs"' ]; do "$0" "$1" claude-code < "$2"; i=$((i + 1)); done' \
    "$run_sh" "$spool" "$tmp/fixture" 2>&1 >/dev/null | awk '/^real/ { print $2 }'
}
t=$(measure)
[ -n "$t" ] || no "could not measure (is time(1) installed?)"
ms=$(awk -v t="${t:-999}" -v n=$runs 'BEGIN { printf "%.1f", t * 1000 / n }')
printf 'speed: %s ms per event\n' "$ms"
# Limit from #6. Locally ~20 ms, on Linux ~5-10 ms; GitHub's macOS runners are
# slow at forking (~35 ms), so the limit is the requirement itself.
check 'awk -v m="$ms" "BEGIN { exit !(m < 50) }"' "too slow: $ms ms per event"
done_test

setup executable
check '[ -x "$spool" ]' "spool.sh is not executable"
check 'head -n 1 "$spool" | grep -qx "#!/bin/sh"' "spool.sh has no #!/bin/sh"
done_test

# -----------------------------------------------------------------------------
if [ $fail -eq 0 ]; then
  printf 'ok: %s tests (%s)\n' "$pass" "$run_sh"
else
  printf '%s failure(s) in %s tests (%s)\n' "$fail" "$pass" "$run_sh"
  exit 1
fi
