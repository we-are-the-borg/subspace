#!/bin/sh
# Checks a subspace day folder against contract v1 (the envelope checks
# mirror schema/envelope.v1.json) and the payload
# structure of the fixtures. Usage:
#
#   tools/e2e/check.sh <events/YYYY-MM-DD> [fixture events folder ...]
#
# Without fixture folders, fixtures for the source recorded in the envelopes
# are used.
# Fails on broken envelopes, leftover .tmp files, wrong permissions and
# payloads missing a key every fixture of that event has. Keys no fixture
# has are only reported (new fields are backwards compatible). Also applies
# the installed mapping document ($ROOT/model/<source>.json, contract §12) to
# every event and fails on events it can't classify.
# Test tooling, not the hook script, so jq and python3 are allowed.

set -eu
day=${1:?usage: check.sh <day folder> [fixture events folder ...]}
shift
fixture_args=$#
repo=$(cd "${0%/*}/../.." && pwd)

fail=0
bad() { echo "FAIL $*"; fail=1; }

# Layout and permissions (contract §3, §4)
find "$day" -name '.*.tmp' | while read -r f; do echo "FAIL leftover $f"; done | grep . && fail=1
find "$day" -type d ! -perm 700 | while read -r f; do echo "FAIL mode $f"; done | grep . && fail=1
find "$day" -type f -name '*.json' ! -perm 600 | while read -r f; do echo "FAIL mode $f"; done | grep . && fail=1

# Validate the envelope before using its source to select fixtures. This
# mirrors schema/envelope.v1.json without requiring a JSON Schema runtime.
n=0
source=
for f in "$day"/*.json; do
  [ -e "$f" ] || { bad "no events in $day"; break; }
  n=$((n + 1))
  out=$(jq -r -s '
    if length != 1 then "FAIL not one JSON document"
    else .[0]
    | if (keys != ["payload","pid","source","ts","v"]) then "FAIL envelope keys \(keys)"
    elif .v != 1 then "FAIL v \(.v)"
    elif (.source | type) != "string" or .source == "" then "FAIL source type/value"
    elif (.ts | type) != "number" or .ts < 0 or .ts != (.ts | floor) then "FAIL ts type/value"
    elif (.pid | type) != "number" or .pid < 1 or .pid != (.pid | floor) then "FAIL pid type/value"
    elif (.payload | type) != "object" then "FAIL payload is not an object"
    elif (.payload.hook_event_name | type) != "string" then "FAIL hook_event_name is not a string"
    elif (.payload | has("session_id")) and (.payload.session_id | type) != "string" then "FAIL session_id is not a string"
    elif (.payload | has("transcript_path")) and ((.payload.transcript_path | type) != "string" and (.payload.transcript_path | type) != "null") then "FAIL transcript_path type"
    elif (.payload | has("cwd")) and (.payload.cwd | type) != "string" then "FAIL cwd is not a string"
    elif (.payload | has("agent_id")) and (.payload.agent_id | type) != "string" then "FAIL agent_id is not a string"
    elif (.payload | has("agent_type")) and (.payload.agent_type | type) != "string" then "FAIL agent_type is not a string"
    else empty
    end
    end' "$f" 2>&1) || out="FAIL not one JSON document"
  if [ -n "$out" ]; then
    printf '%s\n' "$out" | sed "s|\$|  (${f##*/})|"
    fail=1
    continue
  fi
  event_source=$(jq -r -s '.[0].source' "$f")
  if [ -z "$source" ]; then
    source=$event_source
  elif [ "$source" != "$event_source" ]; then
    bad "mixed sources $source and $event_source  (${f##*/})"
  fi
done

case $source in claude-code | codex) ;; '') ;; *) bad "unsupported source $source" ;; esac
[ "$fail" -eq 0 ] || { echo "--- $n events"; echo FAILED; exit 1; }

if [ "$fixture_args" -eq 0 ]; then
  set -- "$repo"/fixtures/"$source"/*/*/events
fi
for d; do
  [ -d "$d" ] || bad "fixture folder not found: $d"
done
[ "$fail" -eq 0 ] || { echo "--- $n events"; echo FAILED; exit 1; }

# Per event name: keys every fixture has, and keys any fixture has
known=$(for d; do cat "$d"/*.json; done | jq -e -s '
  group_by(.hook_event_name)
  | map({key: .[0].hook_event_name,
         value: {all: (map(keys) | reduce .[1:][] as $k (.[0]; . - (. - $k))),
                 any: (map(keys) | add | unique)}})
  | from_entries') || { bad "could not read fixtures"; known='{}'; }

for f in "$day"/*.json; do
  out=$(jq -r --argjson known "$known" '
    .payload as $p | $known[$p.hook_event_name] as $k
      | if $k == null then "NEW  \($p.hook_event_name) (no fixture)"
        else (($k.all - ($p | keys))[] | "FAIL \($p.hook_event_name) misses \(.)"),
             ((($p | keys) - $k.any)[] | "NEW  \($p.hook_event_name) has \(.)")
        end
    ' "$f" 2>&1) || out="FAIL could not compare payload"
  [ -z "$out" ] || printf '%s\n' "$out" | sed "s|\$|  (${f##*/})|"
  case $out in *FAIL*) fail=1 ;; esac
done

# Mapping document (contract §12): $ROOT is two levels above the day folder.
mapping=$(cd "$day/../.." && pwd)/model/$source.json
if [ ! -f "$mapping" ]; then
  echo "NOTE no $mapping (release without mapping documents, or no SessionStart since installing)"
else
  [ "$(cat "$mapping")" = "$(cat "$repo/model/$source.json")" ] ||
    echo "NOTE $mapping differs from model/$source.json in this checkout"
  for f in "$day"/*.json; do
    kind=$(jq -c '.payload' "$f" | python3 "$repo/tools/model/apply.py" "$mapping" | jq -r '.kind') ||
      kind="(interpreter failed)"
    case $kind in
      unknown | "(interpreter failed)" | '') bad "mapping gives kind $kind  (${f##*/})" ;;
    esac
  done
fi

echo "--- $n events"
jq -r '.payload.hook_event_name' "$day"/*.json 2>/dev/null | sort | uniq -c
[ "$fail" -eq 0 ] && echo OK || { echo FAILED; exit 1; }
