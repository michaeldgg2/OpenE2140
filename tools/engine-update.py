#!/usr/bin/env python3

import os
import re
import shlex
import shutil
import json
import subprocess
import sys
import tempfile
from typing import Optional


def run(cmd: list[str], capture_output: bool = False) -> subprocess.CompletedProcess:
	return subprocess.run(cmd, capture_output=capture_output, text=True, check=True)


def get_var(file_path: str, var: str) -> Optional[str]:
	pattern = re.compile(rf"^{re.escape(var)}\s*=(.*)$")
	with open(file_path, "r", encoding="utf-8") as f:
		for line in f:
			m = pattern.match(line)
			if m:
				val = m.group(1).strip()
				if val.startswith('"') and val.endswith('"'):
					val = val[1:-1]
				return val
	return None


def parse_github_repo(url: str) -> tuple[str, str]:
	m = re.match(r"https?://github\.com/([^/]+/[^/]+)", url)
	if not m:
		raise ValueError("Failed to parse owner/repo from engine_source")
	owner, repo = m.group(1).split("/", 1)
	return owner, repo


def curl_get(url: str, headers: list[str]) -> str:
	cmd = ["curl", "-s"]
	for h in headers:
		cmd += ["-H", h]
	cmd.append(url)
	proc = run(cmd, capture_output=True)
	return proc.stdout


def write_tmp_and_replace(original: str, new_contents: str) -> None:
	fd, tmp_path = tempfile.mkstemp()
	os.close(fd)
	with open(tmp_path, "w", encoding="utf-8") as f:
		f.write(new_contents)
	shutil.move(tmp_path, original)


def main() -> None:
	repo_root = os.environ.get("GITHUB_WORKSPACE", ".")
	config_file = os.path.join(repo_root, "mod.config")
	if not os.path.isfile(config_file):
		raise FileNotFoundError("mod.config not found")

	current_engine_version = get_var(config_file, "ENGINE_VERSION") or ""
	engine_source = get_var(config_file, "AUTOMATIC_ENGINE_SOURCE") or ""

	if not current_engine_version:
		raise ValueError("ENGINE_VERSION not found or empty in mod.config")
	if not engine_source:
		raise ValueError("engine_source not found or empty in mod.config")

	print(f"Current ENGINE_VERSION: {current_engine_version}")
	print(f"AUTOMATIC_ENGINE_SOURCE: {engine_source}")

	owner, repo = parse_github_repo(engine_source)
	print(f"Engine repo: {owner}/{repo} (default branch: bleed)")

	# Retrieve latest commit in the engine repo by calling GitHub API
	default_branch = "bleed"
	api = f"https://api.github.com/repos/{owner}/{repo}/commits/{default_branch}"

	headers = ["Accept: application/vnd.github.v3+json"]
	gh_token = os.environ.get("GITHUB_TOKEN", "")
	if gh_token:
		headers.append(f"Authorization: token {gh_token}")

	commit_json = curl_get(api, headers)
	try:
		commit_data = json.loads(commit_json)
	except json.JSONDecodeError as e:
		raise RuntimeError(f"Failed to parse JSON from GitHub API: {e}")

	# Extract latest engine commit details
	engine_commit_hash = None
	engine_commit_date = None
	try:
		engine_commit_hash = commit_data["sha"]
		engine_commit_date = commit_data["commit"]["author"]["date"][:10]  # YYYY-MM-DD
	except:
		pass

	if not engine_commit_hash or not engine_commit_date:
		print(f"Failed to get latest commit for {owner}/{repo} on branch {default_branch}", file=sys.stderr)
		print("Response was:", file=sys.stderr)
		print(commit_json, file=sys.stderr)
		raise RuntimeError("Failed to obtain engine commit")

	print(f"Latest engine commit: {engine_commit_hash} ({engine_commit_date})")

	if current_engine_version == engine_commit_hash:
		print("ENGINE_VERSION already up-to-date. Exiting.")
		return

	# Update mod.config by replacing ENGINE_VERSION line
	with open(config_file, "r", encoding="utf-8") as f:
		lines = f.readlines()

	new_lines = []
	replaced = False
	for line in lines:
		if re.match(r"^ENGINE_VERSION\s*=", line):
			new_lines.append(f"ENGINE_VERSION={engine_commit_hash}\n")
			replaced = True
		else:
			new_lines.append(line)
	if not replaced:
		raise RuntimeError("ENGINE_VERSION line not found in mod.config to replace")

	write_tmp_and_replace(config_file, "".join(new_lines))

	os.chdir(repo_root)

	# Create or reset branch locally
	branch = "engine-update"
	run(["git", "checkout", "-B", branch])

	# Stage and commit (git commit will fail if no changes; let it raise)
	run(["git", "add", "mod.config"])
	commit_msg = f"Engine update ({engine_commit_date})"
	run(["git", "commit", "-m", commit_msg])

	# Force-push
	run(["git", "push", "--force", "origin", branch])

	# Find open PR for this branch using gh
	try:
		pr_number = run(
			["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number", "--jq", ".[0].number"],
			capture_output=True,
		).stdout.strip()
	except subprocess.CalledProcessError:
		pr_number = ""

	# Create new or update existing PR
	pr_title = commit_msg
	pr_body = f"Automated engine update to commit {engine_commit_hash}"

	if pr_number:
		print(f"Open PR exists: #{pr_number}")
		run(["gh", "pr", "edit", pr_number, "--title", pr_title, "--body", pr_body])
	else:
		print("Creating new PR")
		pr_number = run(["gh", "pr", "create", "--title", pr_title, "--body", pr_body, "--base", "master", "--head", branch]).stdout.strip()
		print(f"New PR: {pr_number}")


if __name__ == "__main__":
	main()
