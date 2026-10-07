#!/bin/sh
# Captures one hook event into captures/events/: <name>.json holds the raw
# payload, <name>.meta the parent process chain and exported CLAUDE_* names.
# Like the real plugin it prints nothing and always exits 0.
{
  dir="$(dirname "$0")/captures/events"
  mkdir -p "$dir"
  name="$(date +%s)-$$"

  {
    printf 'ts=%s\nppid=%s\nCLAUDE_PID=%s\n' "$(date +%s)" "$PPID" "${CLAUDE_PID-unset}"
    printf 'process chain (pid ppid comm):\n'
    pid=$PPID
    for _ in 1 2 3 4; do
      line=$(ps -o pid=,ppid=,comm= -p "$pid") || break
      printf '  %s\n' "$line"
      pid=$(printf '%s' "$line" | awk '{print $2}')
    done
    printf 'env:\n'
    env | sed -n 's/^\(CLAUDE[A-Z0-9_]*\)=.*/  \1/p' | sort
  } > "$dir/$name.meta"

  cat > "$dir/.$name.tmp" && mv "$dir/.$name.tmp" "$dir/$name.json"
} > /dev/null 2>&1
exit 0
