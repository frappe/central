import subprocess
from pathlib import Path

from fcloud.errors import FcloudError


def get_repository() -> tuple[str, str]:
	"""owner/name and the current branch of the git repository in the working directory."""
	try:
		remote = run_git("remote", "get-url", "origin")
		branch = run_git("rev-parse", "--abbrev-ref", "HEAD")
	except (subprocess.CalledProcessError, FileNotFoundError):
		raise FcloudError("Run this in a git repository with an origin on GitHub, or pass --repository.")
	return to_owner_and_name(remote), branch


def run_git(*arguments: str) -> str:
	return subprocess.run(["git", *arguments], capture_output=True, text=True, check=True).stdout.strip()


def to_owner_and_name(repository: str) -> str:
	"""owner/name from a GitHub URL, an SSH remote, or owner/name itself."""
	return repository.split("github.com", 1)[-1].lstrip(":/").removesuffix("/").removesuffix(".git")


def get_target(repository: str | None, branch: str | None) -> tuple[str, str | None]:
	"""The repository and branch from the options, or from the git repository in the working directory."""
	if repository:
		return to_owner_and_name(repository), branch
	current_repository, current_branch = get_repository()
	return current_repository, branch or current_branch


def has_container_file(directory: Path) -> bool:
	return any((directory / name).exists() for name in ("Dockerfile", "Containerfile"))
