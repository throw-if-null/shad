#!/usr/bin/env bash
# Checks that shad matches the Coral release that CORAL.md `targets`:
#
# - CORAL-CONTRACT.md is byte-identical to the contract that the release's own
#   generator writes. Coral's generator reads the rule documents of the
#   checkout it runs from (coral scripts/generate-contract.mjs), so the check
#   runs the generator of the tagged release, never of a branch.
# - AGENTS.md loads every Coral document from that release tag.
#
# The check reads and compares. It changes no file in this repository.
# CORAL_URL overrides the Coral repository location, for a local mirror.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
coral_url=${CORAL_URL:-https://github.com/throw-if-null/coral.git}

fail() {
	echo "coral-contract: $*" >&2
	exit 1
}

mapfile -t targets < <(sed -n 's/^targets: "\([^"]*\)"$/\1/p' "$repo/CORAL.md")
[[ ${#targets[@]} -eq 1 ]] || fail "CORAL.md must hold exactly one 'targets: \"<version>\"' line"
version=${targets[0]}
tag="v$version"

# Each Coral reference in AGENTS.md names the release tag, so an upgrade
# that changes CORAL.md and not AGENTS.md fails here.
if grep -n 'coral\.appsandtools\.work' "$repo/AGENTS.md"; then
	fail "AGENTS.md references the live Coral site; load from raw.githubusercontent.com/throw-if-null/coral/$tag/"
fi
if grep -no 'throw-if-null/coral/[^/]*/' "$repo/AGENTS.md" | grep -v "/coral/$tag/$"; then
	fail "AGENTS.md references a Coral revision other than $tag"
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# ls-remote exits 2 when the remote has no matching ref.
status=0
git ls-remote --exit-code --tags "$coral_url" "refs/tags/$tag" >/dev/null || status=$?
case $status in
0) ;;
2) fail "Coral release tag $tag does not exist at $coral_url; CORAL.md targets $version" ;;
*) fail "cannot read the tags of $coral_url (git ls-remote exit $status)" ;;
esac

git -C "$work" init -q coral
git -C "$work/coral" fetch -q --depth 1 "$coral_url" "refs/tags/$tag:refs/tags/$tag"
git -C "$work/coral" -c advice.detachedHead=false checkout -q "refs/tags/$tag"

released=$(<"$work/coral/VERSION")
[[ $released == "$version" ]] || fail "Coral $tag holds VERSION $released, not $version"

node_wanted=$(<"$work/coral/.node-version")
node_running=$(node --version)
node_running=${node_running#v}
[[ ${node_running%%.*} == "${node_wanted%%.*}" ]] ||
	fail "Coral $tag requires Node $node_wanted; this is Node $node_running"

(cd "$work/coral" && npm ci --ignore-scripts --no-audit --no-fund --loglevel=error)
node "$work/coral/scripts/generate-contract.mjs" --project "$repo" --stdout >"$work/contract.md"

if ! diff -u --label "CORAL-CONTRACT.md (committed)" --label "CORAL-CONTRACT.md (Coral $tag)" \
	"$repo/CORAL-CONTRACT.md" "$work/contract.md"; then
	fail "CORAL-CONTRACT.md differs from the contract Coral $tag generates; regenerate it from a $tag checkout"
fi
echo "coral-contract: CORAL-CONTRACT.md matches Coral $tag"
