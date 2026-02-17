#!/usr/bin/env python3

import os
import re
import shlex
import shutil
import json
import subprocess
import sys
import tempfile
from typing import Optional, List, Tuple
from dataclasses import dataclass

@dataclass
class CommitInfo:
	sha: str
	short_sha: str
	message_title: str
	html_url: str
	author_name: str
	date: str


@dataclass
class PullRequestInfo:
	number: int
	title: str
	html_url: str
	author: str


def run(cmd: List[str], capture_output: bool = False) -> subprocess.CompletedProcess:
	return subprocess.run(cmd, capture_output=capture_output, text=True, check=True)


def get_var(file_path: str, var: str) -> Optional[str]:
	pattern = re.compile(rf'^\s*{re.escape(var)}\s*=\s*(.*)')
	with open(file_path, "r", encoding="utf-8") as f:
		for line in f:
			m = pattern.match(line)
			if m:
				val = m.group(1).strip()
				# remove trailing comments
				val = re.split(r'\s+#', val, 1)[0].strip()
				# strip matching surrounding quotes
				if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
					val = val[1:-1]
				return val
	return None


def parse_github_repo(url: str) -> Tuple[str, str]:
	# Accepts URLs like https://github.com/owner/repo(.git)? or git@github.com:owner/repo.git
	m = re.match(r"(?:https?://github\.com/|git@github\.com:)([^/ :]+/[^/ :]+)(?:\.git)?", url)
	if not m:
		raise ValueError("Failed to parse owner/repo from URL")
	owner_repo = m.group(1).rstrip(".git")
	owner, repo = owner_repo.split("/", 1)
	return owner, repo


def write_tmp_and_replace(path: str, new_contents: str) -> None:
	# Ensure exactly one trailing newline
	if not new_contents.endswith("\n"):
		new_contents += "\n"

	fd, tmp_path = tempfile.mkstemp()
	os.close(fd)
	with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
		f.write(new_contents)

	shutil.move(tmp_path, path)


def github_api_get(url: str, gh_token: str = "") -> dict:
	"""Call GitHub API via curl and return parsed JSON (fail-fast on errors)."""
	cmd = ["curl", "-sk", "-H", "Accept: application/vnd.github.v3+json"]
	if gh_token:
		cmd += ["-H", f"Authorization: token {gh_token}"]
	cmd += [url]
	
	print(url)

	# run and capture output
	proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
	if proc.returncode != 0:
		raise RuntimeError(f"curl failed ({proc.returncode}): {proc.stdout.strip()}")
	if proc.stdout.strip() == "":
		raise RuntimeError("Empty response from GitHub API")

	try:
		return json.loads(proc.stdout)
	except json.JSONDecodeError as e:
		raise RuntimeError(f"Failed to parse JSON from GitHub API: {e}") from e


def get_commits_between(owner: str, repo: str, from_sha: str, to_sha: str, gh_token: str = "") -> List[CommitInfo]:
	"""
	Use GitHub API to list commits between from_sha (exclusive) and to_sha (inclusive).
	Returns commits ordered newest->oldest as CommitInfo objects.
	"""
	# GitHub compare API: /repos/{owner}/{repo}/compare/{base}...{head}
	compare_api = f"https://api.github.com/repos/{owner}/{repo}/compare/{from_sha}...{to_sha}"
	data = github_api_get(compare_api, gh_token)
	if "commits" not in data:
		raise RuntimeError(f"Compare API error: {data.get('message', 'no commits field')}")

	# Parse commits, but fail-fast on unexpected/missing structure
	commits = []
	try:
		for raw_commit in data["commits"]:
			sha = raw_commit["sha"]
			short = sha[:7]
			commit_obj = raw_commit["commit"]
			msg = commit_obj["message"].splitlines()[0]
			author_obj = commit_obj["author"]
			date = author_obj["date"]
			author = author_obj.get("name", "")
			html_url = raw_commit.get("html_url") or f"https://github.com/{owner}/{repo}/commit/{sha}"
			commits.append(CommitInfo(
				sha=sha,
				short_sha=short,
				message_title=msg,
				html_url=html_url,
				author_name=author,
				date=date,
			))
	except (KeyError, TypeError) as e:
		raise RuntimeError(f"Unexpected compare API response structure: {e}") from e

	return commits


def commit_prs(owner: str, repo: str, sha: str, gh_token: str = "") -> List[PullRequestInfo]:
	"""Return list of PullRequestInfo for a given commit SHA using the commit->pulls endpoint."""
	url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}/pulls"
	raw = github_api_get(url, gh_token)
	prs: List[PullRequestInfo] = []
	try:
		for item in raw:
			prs.append(PullRequestInfo(
				number=int(item["number"]),
				title=item["title"].strip(),
				html_url=item["html_url"],
				author=item["user"]["login"]
			))
	except (KeyError, TypeError) as e:
		raise RuntimeError(f"Unexpected commits API response structure: {e}") from e
	return prs


def aggregate_prs_for_commits(owner: str, repo: str, commits: List[CommitInfo], gh_token: str = "") -> List[PullRequestInfo]:
	"""Return deduplicated list of PRs related to the provided commits (preserve numeric order)."""
	seen = {}
	result: List[PullRequestInfo] = []
	for c in commits:
		try:
			prs = commit_prs(owner, repo, c.sha, gh_token)
		except subprocess.CalledProcessError:
			continue
		for pr in prs:
			if pr.number not in seen:
				seen[pr.number] = True
				result.append(pr)
	return result


def format_pr_body(current_sha: str, latest_sha: str, commits: List[CommitInfo], prs: List[PullRequestInfo], owner: str, repo: str) -> str:
	"""
	Build PR body including compare link, concise commits, and a concise PR list.
	"""
	compare_url = f"https://github.com/{owner}/{repo}/compare/{current_sha}...{latest_sha}"
	lines = []
	lines.append(f"Automated engine update to commit {latest_sha}")
	lines.append("")
	lines.append(f"Compare changes: {compare_url}")
	lines.append("")
	if commits:
		lines.append("Commits included:")
		for c in commits:
			lines.append(f"- [{c.short_sha}: {c.message_title}]({c.html_url})")
	else:
		lines.append("No intermediate commits found.")

	lines.append("")

	if prs:
		lines.append("Related pull requests:")
		for p in prs:
			lines.append(f"- [#{p.number}: {p.title}]({p.html_url}) ({p.author})")
	else:
		lines.append("No related pull requests found.")
	
	return "\n".join(lines)


def try_get_remote_owner_repo() -> Tuple[str, str]:
	# Prefer GITHUB_REPOSITORY if available
	env_repo = os.environ.get("GITHUB_REPOSITORY")
	if env_repo and "/" in env_repo:
		return tuple(env_repo.split("/", 1))
	# Fallback to git remote
	try:
		out = run(["git", "remote", "get-url", "origin"], capture_output=True).stdout.strip()
	except subprocess.CalledProcessError as e:
		raise RuntimeError("Failed to get git remote URL and GITHUB_REPOSITORY not set") from e
	return parse_github_repo(out)


def download_file_from_github(owner: str, repo: str, file_path: str, gh_token: str = "") -> Optional[str]:
	# Try raw content from default branch 'master' first, then 'main'
	for branch in ("master", "main"):
		url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{file_path}"
		cmd = ["curl", "-s", "-f"]
		if gh_token:
			# use Authorization header if token provided
			cmd += ["-H", f"Authorization: token {gh_token}"]
		cmd += [url]
		proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
		if proc.returncode == 0 and proc.stdout.strip() != "":
			return proc.stdout
	# not found
	return None


def local_branch_exists(branch: str) -> bool:
	try:
		run(["git", "rev-parse", "--verify", branch], capture_output=True)
		return True
	except subprocess.CalledProcessError:
		return False


def main() -> None:
	repo_root = os.environ.get("GITHUB_WORKSPACE", ".")
	gh_token = os.environ.get("GITHUB_TOKEN", "")
	config_file = os.path.join(repo_root, "mod.config")
	if not os.path.isdir(repo_root):
		raise FileNotFoundError("Repository root not found")

	# Change to repo root early so git commands operate in right dir
	os.chdir(repo_root)

	branch = "engine-update"
	had_checked_out_branch = False

	# If local engine-update branch exists, check it out BEFORE reading mod.config
	if local_branch_exists(branch):
		print(f"Local branch '{branch}' exists - checking out")
		run(["git", "checkout", branch])
		had_checked_out_branch = True
	else:
		print(f"Local branch '{branch}' does not exist")

	# Ensure we have latest engine commit hash from engine repo first
	# We need engine_source to determine owner/repo for engine. That comes from mod.config,
	# but we should read mod.config after possibly checking out existing branch.
	# If mod.config is not present locally (e.g., not checked out), we'll try to download it from GitHub.
	if not os.path.isfile(config_file):
		print("mod.config not present locally - will attempt to download from GitHub")
		owner_repo = None
		try:
			owner_repo = try_get_remote_owner_repo()
		except Exception:
			# If we couldn't determine owner/repo, fall back to error
			raise RuntimeError("Failed to determine repository owner/repo to download mod.config")

		remote_owner, remote_repo = owner_repo
		downloaded = download_file_from_github(remote_owner, remote_repo, "mod.config", gh_token)
		if downloaded is None:
			raise FileNotFoundError("mod.config not present locally and could not be downloaded from GitHub")

		# write to a temp file path so get_var can read it via a file path
		tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mod.config")
		os.close(tmp_fd)
		with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
			f.write(downloaded if downloaded.endswith("\n") else downloaded + "\n")
		config_source_path = tmp_path
	else:
		config_source_path = config_file

	# Read AUTOMATIC_ENGINE_SOURCE from the chosen mod.config
	engine_source = get_var(config_source_path, "AUTOMATIC_ENGINE_SOURCE") or ""
	if not engine_source:
		# If we had downloaded mod.config from repo, try to parse engine_source from local file instead (fallback)
		if config_source_path != config_file and os.path.isfile(config_file):
			engine_source = get_var(config_file, "AUTOMATIC_ENGINE_SOURCE") or ""
		if not engine_source:
			raise ValueError("AUTOMATIC_ENGINE_SOURCE not found or empty in mod.config")

	owner, repo = parse_github_repo(engine_source)
	print(f"Engine repo: {owner}/{repo} (default branch: bleed)")

	# Retrieve latest commit in the engine repo by calling GitHub API
	default_branch = "bleed"
	commit_data = github_api_get(f"https://api.github.com/repos/{owner}/{repo}/commits/{default_branch}", gh_token)

	engine_commit_hash = None
	engine_commit_date = None
	try:
		engine_commit_hash = commit_data["sha"]
		engine_commit_date = commit_data["commit"]["author"]["date"][:10]  # YYYY-MM-DD
	except (KeyError, TypeError):
		pass

	if not engine_commit_hash or not engine_commit_date:
		print(f"Failed to get latest commit for {owner}/{repo} on branch {default_branch}", file=sys.stderr)
		print("Response was:", file=sys.stderr)
		print(json.dumps(commit_data, indent=2), file=sys.stderr)
		raise RuntimeError("Failed to obtain engine commit")

	print(f"Latest engine commit: {engine_commit_hash} ({engine_commit_date})")

	# Determine current_engine_version from the checked out branch mod.config if that branch existed,
	# otherwise from local mod.config (if present) or downloaded mod.config we saved to tmp.
	current_engine_version = None

	# If we checked out engine-update branch earlier, read its mod.config in repo root (it should now be present)
	if had_checked_out_branch and os.path.isfile(config_file):
		current_engine_version = get_var(config_file, "ENGINE_VERSION") or ""
		print(f"Detected ENGINE_VERSION from checked-out '{branch}' branch: {current_engine_version}")
	else:
		# If we have local mod.config file, read it
		if os.path.isfile(config_file):
			current_engine_version = get_var(config_file, "ENGINE_VERSION") or ""
			print(f"Detected ENGINE_VERSION from local mod.config: {current_engine_version}")
		else:
			# fallback to the downloaded config we saved earlier (if any)
			if config_source_path != config_file and os.path.isfile(config_source_path):
				current_engine_version = get_var(config_source_path, "ENGINE_VERSION") or ""
				print(f"Detected ENGINE_VERSION from downloaded mod.config: {current_engine_version}")

	# If we still don't have current_engine_version, that's an error
	if not current_engine_version:
		raise ValueError("ENGINE_VERSION not found or empty in mod.config")

	# If engine-update branch exists and its mod.config already uses the latest engine commit, skip modifying files
	if had_checked_out_branch:
		if current_engine_version == engine_commit_hash:
			print(f"'{branch}' already contains ENGINE_VERSION set to latest engine commit. No changes needed.")
			return
		else:
			print(f"'{branch}' ENGINE_VERSION is {current_engine_version}, latest is {engine_commit_hash} - will update")

	# If branch did not exist locally, but the repository's mod.config from GitHub already points at latest engine commit,
	# we can skip creating/updating mod.config locally and only ensure branch/PR existence.
	if not had_checked_out_branch:
		# If we downloaded mod.config from GitHub earlier, current_engine_version is already set from it.
		# Otherwise it's from local file. Check equality and skip if already up-to-date.
		if current_engine_version == engine_commit_hash:
			print("Repository's mod.config already points to latest engine commit. No changes needed.")
			return
		else:
			print(f"Repository ENGINE_VERSION is {current_engine_version}, latest is {engine_commit_hash} - will update")

	# At this point we must update mod.config locally (either on checked-out branch or on default branch)
	# Make sure we're on repository root branch (if not on engine-update, create/reset it)
	if not had_checked_out_branch:
		# create/reset branch locally from current HEAD
		run(["git", "checkout", "-B", branch])
	else:
		# we already checked out branch earlier, ensure we're on it
		run(["git", "checkout", branch])

	# Ensure config_file exists now (if we earlier downloaded a temp file, copy it over)
	if not os.path.isfile(config_file):
		# If we had a downloaded config file path, copy it into place
		if 'config_source_path' in locals() and config_source_path != config_file and os.path.isfile(config_source_path):
			shutil.copyfile(config_source_path, config_file)
		else:
			raise FileNotFoundError("mod.config not found to update")

	# Update mod.config by replacing ENGINE_VERSION line
	print("Updating ENGINE_VERSION in mod.config")
	with open(config_file, "r", encoding="utf-8") as f:
		lines = f.readlines()

	new_lines = []
	replaced = False
	for line in lines:
		if re.match(r"^ENGINE_VERSION\s*=", line):
			new_lines.append(f'ENGINE_VERSION="{engine_commit_hash}"')
			replaced = True
		else:
			new_lines.append(line.rstrip("\n"))
	if not replaced:
		raise RuntimeError("ENGINE_VERSION line not found in mod.config to replace")

	write_tmp_and_replace(config_file, "\n".join(new_lines))

	# Stage, commit and push
	print(f"Committing mod.config and pushing to branch {branch}")
	run(["git", "add", "mod.config"])
	commit_msg = f"Engine update ({engine_commit_date})"
	# Try commit; if nothing to commit, skip
	try:
		run(["git", "commit", "-m", commit_msg])
	except subprocess.CalledProcessError:
		print("No changes to commit (mod.config already up-to-date locally).")

	# Force-push
	run(["git", "push", "--force", "origin", branch])

	# Find open PR for this branch using gh
	print(f"Looking for existing PR for branch {branch}")
	try:
		proc = run(
			["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number", "--jq", ".[0].number"],
			capture_output=True,
		)
		pr_number = proc.stdout.strip()
	except subprocess.CalledProcessError:
		pr_number = ""

	print("Retrieving data for PR body:")

	# Retrieve new commits
	# Determine the 'current' engine version for the PR body: use previous detected current_engine_version
	print(f"... commits between {current_engine_version} and {engine_commit_hash}")
	commits = get_commits_between(owner, repo, current_engine_version, engine_commit_hash, gh_token)

	# Retrieve related PRs for those commits
	print(f"... related PRs for these commits")
	prs = aggregate_prs_for_commits(owner, repo, commits, gh_token)

	# Create new or update existing PR
	pr_title = commit_msg
	pr_body = format_pr_body(current_engine_version, engine_commit_hash, commits, prs, owner, repo)

	if pr_number:
		print(f"Updating existing PR: #{pr_number}")
		run(["gh", "pr", "edit", pr_number, "--title", pr_title, "--body", pr_body])
	else:
		print("Creating new PR")
		pr_number = run(["gh", "pr", "create", "--title", pr_title, "--body", pr_body, "--base", "master", "--head", branch], capture_output=True).stdout.strip()
		print(f"New PR: {pr_number}")


if __name__ == "__main__":
	main()
