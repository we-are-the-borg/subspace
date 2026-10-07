#!/bin/sh
# Copies the shared sources into every adapter: core/spool.sh to
# adapters/*/scripts/, the shared schema/*.json plus the adapter's own
# schema/<source>/*.json to adapters/*/schema/ (so a schema change only
# releases the adapters it concerns) and the adapter's
# own mapping documents model/<source>.json and, if present,
# model/<source>-session.json to adapters/<source>/model/. A
# plugin only ships its own folder, so each adapter carries copies; never edit
# them.
# CI runs this and fails on any diff.
set -eu
cd "$(dirname "$0")/.."
for a in adapters/*/; do
  mkdir -p "${a}scripts" "${a}schema"
  cp core/spool.sh "${a}scripts/spool.sh"
  chmod 755 "${a}scripts/spool.sh"
  source=${a#adapters/}
  source=${source%/}
  # Replace, so a schema removed from schema/ disappears from the adapter too.
  rm -f "${a}schema/"*.json
  cp schema/*.json "${a}schema/"
  if [ -d "schema/$source" ]; then
    cp "schema/$source/"*.json "${a}schema/"
  fi
  rm -rf "${a}model"
  for m in "model/$source.json" "model/$source-session.json"; do
    [ -f "$m" ] || continue
    mkdir -p "${a}model"
    cp "$m" "${a}model/"
  done
done
