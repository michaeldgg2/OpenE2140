set -euo pipefail

die() { echo "ERROR: $*" >&2; exit 1; }

# helper to read shell-style var from mod.config
get_var() {
	local file="$1" var="$2"
	awk -F= -v k="$var" '
		$0 ~ "^"k"[[:space:]]*=" {
			v = substr($0, index($0, "=") + 1)
			gsub(/^[ \t]+|[ \t]+$/,"",v)
			if (v ~ /^".*"$/) v = substr(v,2,length(v)-2)
			print v
			exit
		}
	' "$file"
}

REPO_ROOT="${GITHUB_WORKSPACE:-.}"
CONFIG_FILE="$REPO_ROOT/mod.config"
[ -f "$CONFIG_FILE" ] || die "mod.config not found"

ENGINE_VERSION_CURRENT="$(get_var "$CONFIG_FILE" "ENGINE_VERSION")" || true
AUTOMATIC_ENGINE_SOURCE="$(get_var "$CONFIG_FILE" "AUTOMATIC_ENGINE_SOURCE")" || true

[ -n "$ENGINE_VERSION_CURRENT" ] || die "ENGINE_VERSION not found or empty in mod.config"
[ -n "$AUTOMATIC_ENGINE_SOURCE" ] || die "AUTOMATIC_ENGINE_SOURCE not found or empty in mod.config"

echo "Current ENGINE_VERSION: $ENGINE_VERSION_CURRENT"
echo "AUTOMATIC_ENGINE_SOURCE: $AUTOMATIC_ENGINE_SOURCE"

# Extract owner/repo from AUTOMATIC_ENGINE_SOURCE
repo_path="$(echo "$AUTOMATIC_ENGINE_SOURCE" | sed -E 's#https?://github.com/([^/]+/[^/]+).*#\1#')"
owner="${repo_path%%/*}"
repo="${repo_path##*/}"
[ -n "$owner" ] || die "Failed to parse owner from AUTOMATIC_ENGINE_SOURCE"
[ -n "$repo" ] || die "Failed to parse repo from AUTOMATIC_ENGINE_SOURCE"

echo "Engine repo: $owner/$repo (default branch: bleed)"

# Use GitHub API to get latest commit on bleed branch
DEFAULT_BRANCH="bleed"
api="https://api.github.com/repos/$owner/$repo/commits/$DEFAULT_BRANCH"
headers=( -H "Accept: application/vnd.github.v3+json" )
if [ -n "${GITHUB_TOKEN:-}" ]; then
	headers+=( -H "Authorization: token ${GITHUB_TOKEN}" )
fi

commit_json="$(curl -s "${headers[@]}" "$api")"
ENGINE_COMMIT_HASH="$(echo "$commit_json" | jq -r .sha)"
ENGINE_COMMIT_DATE="$(echo "$commit_json" | jq -r '.commit.author.date' | cut -dT -f1)"

if [ -z "$ENGINE_COMMIT_HASH" ] || [ "$ENGINE_COMMIT_HASH" = "null" ]; then
	echo "Failed to get latest commit for $owner/$repo on branch $DEFAULT_BRANCH" >&2
	echo "Response was: $commit_json" >&2
	exit 1
fi

echo "Latest engine commit: $ENGINE_COMMIT_HASH ($ENGINE_COMMIT_DATE)"

# Exit if already up-to-date
if [ "$ENGINE_VERSION_CURRENT" = "$ENGINE_COMMIT_HASH" ]; then
	echo "ENGINE_VERSION already up-to-date. Exiting."
	exit 0
fi

# Update mod.config: replace ENGINE_VERSION line with new hash (no quotes)
tmp_config="$(mktemp)"
awk -v new="$ENGINE_COMMIT_HASH" '
BEGIN{FS=OFS="="}
{
	if ($0 ~ /^ENGINE_VERSION[[:space:]]*=/) {
		print "ENGINE_VERSION=" new
	} else {
		print $0
	}
}
' "$CONFIG_FILE" > "$tmp_config"
mv "$tmp_config" "$CONFIG_FILE"

# Commit to engine-update branch
branch="engine-update"
git checkout -B "$branch"

git add mod.config
commit_msg="Engine update ($ENGINE_COMMIT_DATE)"
git commit -m "$commit_msg" || die "git commit failed"

# Push branch (force if exists) and create PR if newly created
if git ls-remote --heads origin "refs/heads/$branch" | grep -q .; then
	echo "Remote branch $branch exists — force pushing"
	git push --force origin "$branch" || die "git push --force failed"
else
	echo "Pushing new branch $branch"
	git push -u origin "$branch" || die "git push failed"
	if command -v gh >/dev/null 2>&1; then
		gh auth status >/dev/null 2>&1 || gh auth login --with-token < <(printf '%s' "${GITHUB_TOKEN:-}")
		pr_title="$commit_msg"
		pr_body="Automated engine update to commit $ENGINE_COMMIT_HASH"
		gh pr create --title "$pr_title" --body "$pr_body" --base master --head "$branch" || die "gh pr create failed"
	else
		echo "gh CLI not available; skipped creating PR"
	fi
fi
