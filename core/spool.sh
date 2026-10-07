#!/bin/sh
# Writes one hook event from stdin into $ROOT/events/<UTC date>/ for local
# apps, and deletes day folders past retention. See docs/contract.md.
#
# Usage: spool.sh <source> [session-start], e.g. spool.sh claude-code
# (contract §4). Only the SessionStart hook passes session-start: the payload
# is never parsed, so a nested "hook_event_name" can't fake one.
#
# Source of truth is core/spool.sh; adapters/*/scripts/spool.sh are copies
# written by tools/sync.sh.
#
# Never steers: prints nothing, always exits 0. POSIX sh and standard
# utilities only. Must stay fast enough to run as a synchronous hook.

# Never print or write anything, everything straight into the void
exec > /dev/null 2>&1
# Files and folders are private to the user (0600/0700); other accounts can't read them.
umask 077
# use $SUBSPACE_DIR if set, else $CLAUDE_PLUGIN_DATA if set, else empty string
root=${SUBSPACE_DIR:-${CLAUDE_PLUGIN_DATA:-}}
source=${1:-}
event=${2:-}
# Lowercase letters, digits and dashes, spelled out: ranges like a-z depend
# on the locale and can match uppercase letters.
case $source in '' | *[!abcdefghijklmnopqrstuvwxyz0123456789-]*) source= ;; esac

# Without $ROOT or a valid source there is nothing to write. Drain stdin
# anyway so the agent never writes into a closed pipe.
[ -n "$root" ] && [ -n "$source" ] || { cat > /dev/null; exit 0; }

# UTC civil date from days since 1970-01-01 (Howard Hinnant's
# civil_from_days), because date arithmetic differs between BSD and GNU.
# Sets y, m, d.
civil() {
  z=$(($1 + 719468))
  era=$((z / 146097))
  doe=$((z - era * 146097))
  yoe=$(((doe - doe / 1460 + doe / 36524 - doe / 146096) / 365))
  doy=$((doe - (365 * yoe + yoe / 4 - yoe / 100)))
  mp=$(((5 * doy + 2) / 153))
  d=$((doy - (153 * mp + 2) / 5 + 1))
  m=$((mp < 10 ? mp + 3 : mp - 9))
  y=$((yoe + era * 400 + (m <= 2)))
}

ts=$(date +%s)
days=$((ts / 86400))
civil "$days"
[ "$m" -lt 10 ] && m=0$m
[ "$d" -lt 10 ] && d=0$d
# directory name of the current day, e.g. $ROOT/events/2023-01-31
dir="$root/events/$y-$m-$d"

# Four random bytes as hex. $RANDOM is not POSIX.
# shellcheck disable=SC2046
set -- $(od -An -N4 -tx1 /dev/urandom)
name="$ts-$PPID-$1$2$3$4"

# Envelope around the payload, byte for byte. Written under a dot name and
# renamed, so apps never see a partial file. Empty stdin is dropped.
head="{\"v\":1,\"source\":\"$source\",\"ts\":$ts,\"pid\":$PPID,\"payload\":"
[ -d "$dir" ] || mkdir -p "$dir"
tmp="$dir/.$name.tmp"
if { printf '%s' "$head" && cat && printf '}'; } > "$tmp" &&
  [ "$(wc -c < "$tmp")" -gt $((${#head} + 1)) ] &&
  mv "$tmp" "$dir/$name.json"; then
  # On SessionStart refresh $ROOT/plugin.json with the plugin's version,
  # $ROOT/schema/ with the plugin's schemas and $ROOT/model/ with its mapping
  # document. The version comes from the adapter's one manifest, e.g.
  # .claude-plugin/plugin.json.
  if [ "$event" = session-start ]; then
    version=$(sed -n 's/^[[:space:]]*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
      "${0%/*}"/../.*-plugin/plugin.json)
    [ -n "$version" ] &&
      printf '{"v":1,"version":"%s"}' "$version" > "$root/.plugin.json.$name.tmp" &&
      mv "$root/.plugin.json.$name.tmp" "$root/plugin.json"
    rm -f "$root/.plugin.json.$name.tmp"
    for k in schema model; do
      [ -d "${0%/*}/../$k" ] || continue
      [ -d "$root/$k" ] || mkdir "$root/$k"
      for s in "${0%/*}/../$k"/*.json; do
        t="$root/$k/.${s##*/}.$name.tmp"
        [ -f "$s" ] && cp "$s" "$t" && mv "$t" "$root/$k/${s##*/}"
        rm -f "$t"
      done
    done
  fi
else
  rm -f "$tmp"
fi

# Delete day folders older than retention_days (default 3, 1..30): keep
# today and the retention_days days before it.
# Arithmetic reads leading zeros as octal and aborts on 08, so strip them.
keep=${CLAUDE_PLUGIN_OPTION_RETENTION_DAYS:-3}
keep=${keep%%.*}
case $keep in '' | *[!0-9]*) keep=3 ;; esac
keep=${keep#"${keep%%[!0]*}"}
case $keep in '') keep=1 ;; ??) [ "$keep" -gt 30 ] && keep=30 ;; ???*) keep=30 ;; esac
civil $((days - keep))
oldest=$((y * 10000 + m * 100 + d))
for f in "$root"/events/*/; do
  f=${f%/}
  n=${f##*/}
  case $n in [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;; *) continue ;; esac
  # YYYYMMDD; the 1 prefixes keep leading zeros from reading as octal.
  y=${n%%-*} r=${n#*-}
  [ $(((1$y - 10000) * 10000 + (1${r%-*} - 100) * 100 + 1${r#*-} - 100)) -lt "$oldest" ] && rm -rf "$f"
done
exit 0
