from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv
from github import Auth, Github, GithubException, InputGitAuthor

from constants import MASADER_GH_REPO, VALID_PUNCT_NAMES

_APP_DIR = Path(__file__).resolve().parent


class GithubPushError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass
class PushResult:
    status: str
    branch: str
    pull_request_url: str | None = None
    message: str | None = None


@dataclass
class GithubUserValidation:
    ok: bool
    error: str | None = None
    status_code: int = 400


def validate_github_username(username: str) -> GithubUserValidation:
    username = username.strip()
    if not username:
        return GithubUserValidation(ok=False, error="GitHub username is required.")

    token, _, _ = load_github_credentials()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.get(
            f"https://api.github.com/users/{username}",
            headers=headers,
            timeout=10,
        )
    except requests.RequestException as exc:
        return GithubUserValidation(
            ok=False,
            error=f"Could not reach GitHub to verify username: {exc}",
            status_code=502,
        )

    if response.status_code == 200:
        return GithubUserValidation(ok=True)

    if response.status_code == 404:
        return GithubUserValidation(
            ok=False,
            error="GitHub user not found. Please enter a valid GitHub username.",
            status_code=404,
        )

    if response.status_code == 403:
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining == "0":
            reset = response.headers.get("X-RateLimit-Reset", "unknown")
            return GithubUserValidation(
                ok=False,
                error=(
                    "GitHub API rate limit exceeded while verifying username. "
                    f"Try again after rate-limit reset (epoch {reset})."
                ),
                status_code=503,
            )
        return GithubUserValidation(
            ok=False,
            error="GitHub API denied the username lookup request.",
            status_code=403,
        )

    return GithubUserValidation(
        ok=False,
        error=f"Could not verify GitHub username (HTTP {response.status_code}).",
        status_code=502,
    )


def load_github_credentials() -> tuple[str, str, str]:
    load_dotenv(_APP_DIR / ".env", override=True)
    return (
        (os.getenv("GITHUB_TOKEN") or "").strip(),
        (os.getenv("GIT_USER_NAME") or "").strip(),
        (os.getenv("GIT_USER_EMAIL") or "").strip(),
    )


def github_credentials_ok() -> tuple[str, str, str]:
    token, user_name, user_email = load_github_credentials()
    if not token:
        raise GithubPushError(
            "GITHUB_TOKEN is not set. Add it to `.env` in the project root.",
            status_code=500,
        )
    if not user_name or not user_email:
        raise GithubPushError(
            "GIT_USER_NAME and GIT_USER_EMAIL must be set in `.env`.",
            status_code=500,
        )
    return token, user_name, user_email


def normalize_dataset_name(name: str) -> str:
    data_name = name.lower().strip()
    for symbol in VALID_PUNCT_NAMES:
        data_name = data_name.replace(symbol, "_")
    return data_name


def unwrap_metadata(payload: dict) -> dict:
    if "metadata" in payload and "Name" not in payload:
        nested = payload["metadata"]
        if isinstance(nested, dict):
            return nested
    return payload


def raw_github_json_url(repo_name: str, branch_name: str, file_path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo_name}/{branch_name}/{file_path}"


def form_edit_url(raw_json_url: str) -> str | None:
    base = (os.getenv("FORM_BASE_URL") or "").strip().rstrip("/")
    if not base:
        return None
    params = urlencode({"annotation_type": "load", "json_url": raw_json_url})
    return f"{base}?{params}"


def build_pr_body(
    github_username: str,
    dataset_name: str,
    *,
    repo_name: str,
    branch_name: str,
    file_path: str,
) -> str:
    raw_url = raw_github_json_url(repo_name, branch_name, file_path)
    edit_url = form_edit_url(raw_url)

    body = (
        f"This is a pull request by @{github_username} to add "
        f"{dataset_name} to the catalogue.\n\n"
    )
    if edit_url:
        body += (
            f'<a href="{edit_url}" target="_blank" rel="noopener noreferrer">'
            "Edit this submission in the Masader Form</a>\n\n"
        )
    body += f"Metadata JSON: [`{file_path}`]({raw_url})"
    return body


def remote_branch_exists(repo, branch_name: str) -> bool:
    try:
        repo.get_git_ref(f"heads/{branch_name}")
        return True
    except GithubException:
        return False


def find_open_pr_for_branch(gh_repo, branch_name: str):
    owner = gh_repo.owner.login
    for pr in gh_repo.get_pulls(head=f"{owner}:{branch_name}", state="open"):
        return pr
    return None


def push_metadata_to_github(
    metadata: dict,
    github_username: str,
    *,
    repo_name: str = MASADER_GH_REPO,
) -> PushResult:
    """Create/update the dataset JSON and open (or refresh) a PR entirely via the
    GitHub REST API.

    This intentionally avoids cloning the (large) ``ARBML/masader`` repository:
    cloning inside a resource-constrained container is slow and blocks the
    request long enough to trip the platform's proxy timeout ("upstream error")
    and trigger a restart. The Git Data / Contents API touches only the single
    file we care about, so a submit stays fast and cheap.
    """
    metadata = unwrap_metadata(metadata)
    dataset_name = (metadata.get("Name") or "").strip()
    if not dataset_name:
        raise GithubPushError("metadata must include a non-empty 'Name' field.")

    github_username = github_username.strip()
    if not github_username:
        raise GithubPushError("github_username is required.")

    github_token, git_user_name, git_user_email = github_credentials_ok()
    data_name = normalize_dataset_name(dataset_name)
    branch_name = f"add-{data_name}"
    file_path = f"datasets/{data_name}.json"
    pr_title = f"Adding {dataset_name} to the catalogue"
    pr_body = build_pr_body(
        github_username,
        dataset_name,
        repo_name=repo_name,
        branch_name=branch_name,
        file_path=file_path,
    )

    try:
        g = Github(auth=Auth.Token(github_token))
        repo = g.get_repo(repo_name)
        default_branch = repo.default_branch
    except GithubException as exc:
        if exc.status == 401:
            raise GithubPushError(
                "GitHub authentication failed (401). Check GITHUB_TOKEN in `.env`.",
                status_code=401,
            ) from exc
        message = exc.data.get("message", str(exc)) if exc.data else str(exc)
        raise GithubPushError(
            f"GitHub API error ({exc.status}): {message}",
            status_code=502,
        ) from exc

    branch_exists_on_remote = remote_branch_exists(repo, branch_name)
    open_pr = (
        find_open_pr_for_branch(repo, branch_name) if branch_exists_on_remote else None
    )

    # Create the working branch off the default branch head when it doesn't exist.
    if not branch_exists_on_remote:
        try:
            base_sha = repo.get_branch(default_branch).commit.sha
            repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_sha)
        except GithubException as exc:
            message = exc.data.get("message", str(exc)) if exc.data else str(exc)
            raise GithubPushError(
                f"Could not create branch `{branch_name}`: {message}",
                status_code=502,
            ) from exc

    new_content = json.dumps(metadata, indent=4)

    # Look up the existing file on the branch (if any) to decide create vs update
    # and to short-circuit when nothing changed.
    existing_file = None
    try:
        existing_file = repo.get_contents(file_path, ref=branch_name)
    except GithubException as exc:
        if exc.status != 404:
            message = exc.data.get("message", str(exc)) if exc.data else str(exc)
            raise GithubPushError(
                f"Could not read `{file_path}`: {message}",
                status_code=502,
            ) from exc

    if existing_file is not None:
        current_content = existing_file.decoded_content.decode("utf-8")
        if current_content == new_content:
            return PushResult(
                status="unchanged",
                branch=branch_name,
                pull_request_url=open_pr.html_url if open_pr else None,
                message="No changes made to the dataset.",
            )

    author = InputGitAuthor(git_user_name, git_user_email)
    commit_message = (
        f"Updating {file_path}" if existing_file is not None else f"Creating {file_path}"
    )

    try:
        if existing_file is not None:
            repo.update_file(
                file_path,
                commit_message,
                new_content,
                existing_file.sha,
                branch=branch_name,
                author=author,
                committer=author,
            )
        else:
            repo.create_file(
                file_path,
                commit_message,
                new_content,
                branch=branch_name,
                author=author,
                committer=author,
            )
    except GithubException as exc:
        message = exc.data.get("message", str(exc)) if exc.data else str(exc)
        raise GithubPushError(
            f"Failed to commit `{file_path}`: {message}",
            status_code=502,
        ) from exc

    if open_pr:
        open_pr.edit(body=pr_body)
        return PushResult(
            status="updated",
            branch=branch_name,
            pull_request_url=open_pr.html_url,
        )

    try:
        pr = repo.create_pull(
            title=pr_title,
            body=pr_body,
            head=branch_name,
            base=default_branch,
        )
    except GithubException as exc:
        message = exc.data.get("message", str(exc)) if exc.data else str(exc)
        raise GithubPushError(
            f"Could not create pull request: {message}",
            status_code=502,
        ) from exc

    return PushResult(
        status="created",
        branch=branch_name,
        pull_request_url=pr.html_url,
    )
