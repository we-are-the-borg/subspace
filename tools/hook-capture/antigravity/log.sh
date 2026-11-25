#!/bin/sh
# Capture stdin unchanged. Diagnostic metadata is separate from the payload.
# This hook is silent, always exits 0, and uses POSIX sh and Unix utilities.
{
  umask 077
  dir="$(dirname "$0")/captures/events"
  mkdir -p "$dir" || exit 0
  tmp=$(mktemp "$dir/.$(date +%s)-$$-XXXXXX") || exit 0
  name=${tmp##*/.}

  # Publish the payload first so process diagnostics cannot delay its capture.
  cat > "$tmp" && mv "$tmp" "$dir/$name.json"
  {
    printf 'ts=%s\nppid=%s\npwd=%s\nSHELL=%s\nargv0=%s\n' \
      "$(date +%s)" "$PPID" "$(pwd)" "${SHELL-unset}" "$0"
    printf 'process chain (pid ppid comm args), starting at PPID:\n'
    # One snapshot is faster and more consistent than ps per ancestor. No depth
    # limit: include PID 1, or explain if an ancestor vanished/is inaccessible.
    ps -ww -eo pid=,ppid=,comm=,args= | awk -v pid="$PPID" '
      { parent[$1] = $2; line[$1] = $0 }
      END {
        while (pid > 0 && !seen[pid]++) {
          if (!(pid in line)) {
            printf "  unavailable pid=%s\n", pid
            break
          }
          printf "  %s\n", line[pid]
          if (pid == 1) break
          pid = parent[pid]
        }
      }'
    printf 'env names (no values):\n'
    env | awk -F= '$1 ~ /^(AGY_|ANTIGRAVITY_|GEMINI_|GOOGLE_|PLUGIN_|CLAUDE_)[A-Za-z0-9_]*$/ { print "  " $1 }' | sort
    # Names and values of the allowlisted terminal identifiers only (contract §4).
    printf 'terminal:\n'
    for n in TERM_PROGRAM TERM_PROGRAM_VERSION __CFBundleIdentifier TERM_SESSION_ID \
      ITERM_SESSION_ID WARP_FOCUS_URL WARP_TERMINAL_SESSION_UUID WEZTERM_PANE \
      KITTY_WINDOW_ID KITTY_LISTEN_ON TMUX TMUX_PANE; do
      set='' val=''
      eval "set=\${$n+x} val=\${$n-}"
      [ -z "$set" ] || printf '  %s=%s\n' "$n" "$val"
    done
  } > "$dir/.$name.meta.tmp"
  mv "$dir/.$name.meta.tmp" "$dir/$name.meta"
} > /dev/null 2>&1
exit 0
