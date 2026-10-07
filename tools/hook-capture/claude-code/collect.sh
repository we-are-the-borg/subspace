#!/bin/sh
# Copies every transcript referenced by the captured events, including the
# subagent transcripts next to it, into captures/transcripts/.
here="$(dirname "$0")"
out="$here/captures/transcripts"
mkdir -p "$out"

sed -n 's/.*"transcript_path":"\([^"]*\)".*/\1/p' "$here"/captures/events/*.json | sort -u |
while read -r t; do
  [ -f "$t" ] || { echo "missing: $t" >&2; continue; }
  session=$(basename "$t" .jsonl)
  mkdir -p "$out/$session"
  cp "$t" "$out/$session/"
  sub="$(dirname "$t")/$session/subagents"
  [ -d "$sub" ] && cp -R "$sub" "$out/$session/"
  echo "copied $session"
done
