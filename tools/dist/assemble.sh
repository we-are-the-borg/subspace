#!/bin/sh
# Writes one adapter's release into its dist working tree
# (we-are-the-borg/subspace-<source>):
#
#   sh tools/dist/assemble.sh <source> <dist tree> [<tag>]
#
# Run from the dev checkout at the release tag; <tag> defaults to
# <source>-<version in the adapter's manifest>. The dist tree is the plugin
# itself, at its root, so a marketplace or directory can install the whole
# repository: it is rebuilt from scratch (everything but .git and SOURCE is
# replaced) from adapters/<source>/ exactly as committed (whatever it holds:
# scripts, schema, hooks, manifest, CHANGELOG, …), the templates in
# tools/dist/<source>/ (README.md and the marketplace file, whose plugin
# source is "./"), and docs/contract.md and docs/model.md. SOURCE gains the
# line "<tag> <dev commit>". It never commits or pushes; the release
# workflow does (.github/workflows/release-please.yml).
set -eu
usage='usage: assemble.sh <source> <dist tree> [<tag>]'
source=${1:?$usage}
dist=${2:?$usage}
dev=$(cd "$(dirname "$0")/../.." && pwd)
[ -d "$dev/adapters/$source" ] || { echo "no adapter adapters/$source" >&2; exit 1; }
[ -d "$dev/tools/dist/$source" ] || { echo "no templates tools/dist/$source" >&2; exit 1; }
version=$(sed -n 's/^[[:space:]]*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$dev/adapters/$source"/.*-plugin/plugin.json)
tag=${3:-$source-$version}
case $tag in "$source-"[0-9]*) ;; *) echo "tag $tag does not belong to $source" >&2; exit 1 ;; esac
mkdir -p "$dist"
dist=$(cd "$dist" && pwd)

# Start from an empty tree, keeping the git metadata and the release log.
find "$dist" -mindepth 1 -maxdepth 1 ! -name .git ! -name SOURCE -exec rm -rf {} +

# Everything as committed at this checkout (no ignored or untracked files),
# so a local dry run matches what the workflow publishes.
git -C "$dev" archive --format=tar "HEAD:adapters/$source" | tar -x -C "$dist"
git -C "$dev" archive --format=tar "HEAD:tools/dist/$source" | tar -x -C "$dist"
git -C "$dev" show HEAD:LICENSE > "$dist/LICENSE"
mkdir -p "$dist/docs"
for d in contract.md model.md; do
  git -C "$dev" show "HEAD:docs/$d" > "$dist/docs/$d"
done

# Relative links in the docs that point at files this repo doesn't ship
# (fixtures, schemas, event docs, …) go to the dev repo at this tag.
blob="https://github.com/we-are-the-borg/subspace/blob/$tag"
for d in contract.md model.md; do
  awk -v docs="$dist/docs" -v blob="$blob" '
    function resolve(t,   n, i, parts, out, k) {
      n = split("docs/" t, parts, "/"); k = 0
      for (i = 1; i <= n; i++) {
        if (parts[i] == "..") k--
        else if (parts[i] != "." && parts[i] != "") out[++k] = parts[i]
      }
      t = out[1]; for (i = 2; i <= k; i++) t = t "/" out[i]
      return t
    }
    {
      line = $0; res = ""
      while (match(line, /\]\([^)]+\)/)) {
        target = substr(line, RSTART + 2, RLENGTH - 3)
        file = target; anchor = ""
        if ((p = index(target, "#")) > 0) { file = substr(target, 1, p - 1); anchor = substr(target, p) }
        # Look each file up once: awk keeps failed opens in its file table.
        if (file != "" && !(file in shipped)) {
          shipped[file] = (getline x < (docs "/" file)) >= 0
          close(docs "/" file)
        }
        if (file != "" && target !~ /^[a-z]+:/ && !shipped[file])
          target = blob "/" resolve(file) anchor
        res = res substr(line, 1, RSTART + 1) target ")"
        line = substr(line, RSTART + RLENGTH)
      }
      print res line
    }' "$dist/docs/$d" > "$dist/docs/$d.tmp"
  mv "$dist/docs/$d.tmp" "$dist/docs/$d"
done

# SOURCE: one line per tag, the dev commit it was built from.
commit=$(git -C "$dev" rev-parse HEAD)
{
  if [ -f "$dist/SOURCE" ]; then
    grep -v "^$tag " "$dist/SOURCE"
  else
    echo "Built from https://github.com/we-are-the-borg/subspace"
  fi
  echo "$tag $commit"
} > "$dist/SOURCE.tmp"
mv "$dist/SOURCE.tmp" "$dist/SOURCE"
