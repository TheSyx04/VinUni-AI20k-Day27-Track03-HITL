"""Thin wrapper around the `gh` CLI to fetch PR metadata and diffs.

We shell out to `gh` instead of using the REST API directly so students don't
need to manage a PAT — `gh auth login` is enough.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass


PR_URL_RE = re.compile(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)")


@dataclass
class PullRequest:
    url: str
    owner: str
    repo: str
    number: int
    title: str
    author: str
    base_ref: str
    head_ref: str
    head_sha: str
    diff: str
    files_changed: list[str]


def _require_gh() -> None:
    if shutil.which("gh") is None:
        raise RuntimeError("`gh` CLI not found on PATH. Install from https://cli.github.com/")


def parse_pr_url(pr_url: str) -> tuple[str, str, int]:
    m = PR_URL_RE.search(pr_url)
    if not m:
        raise ValueError(f"Not a PR URL: {pr_url}")
    return m.group(1), m.group(2), int(m.group(3))


def fetch_pr(pr_url: str) -> PullRequest:
    """Fetch PR metadata + unified diff via `gh`."""
    _require_gh()
    owner, repo, number = parse_pr_url(pr_url)
    repo_slug = f"{owner}/{repo}"

    meta_raw = subprocess.check_output(
        [
            "gh", "pr", "view", str(number),
            "--repo", repo_slug,
            "--json", "title,author,baseRefName,headRefName,headRefOid,files",
        ],
        text=True,
    )
    meta = json.loads(meta_raw)

    diff = subprocess.check_output(
        ["gh", "pr", "diff", str(number), "--repo", repo_slug],
        text=True,
    )

    return PullRequest(
        url=pr_url,
        owner=owner,
        repo=repo,
        number=number,
        title=meta["title"],
        author=meta["author"]["login"],
        base_ref=meta["baseRefName"],
        head_ref=meta["headRefName"],
        head_sha=meta["headRefOid"],
        diff=diff,
        files_changed=[f["path"] for f in meta.get("files", [])],
    )


def post_review_comment(pr: PullRequest, body: str) -> None:
    """Post a top-level review comment back to the PR (used by stage 5)."""
    _require_gh()
    subprocess.check_call(
        [
            "gh", "pr", "comment", str(pr.number),
            "--repo", f"{pr.owner}/{pr.repo}",
            "--body", body,
        ]
    )
