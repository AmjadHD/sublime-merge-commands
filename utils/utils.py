from typing import Iterator, Optional

import pygit2


def name_to_path(repo: pygit2.Repository, name: str) -> Optional[str]:
    try:
        return repo.lookup_reference_dwim(name).name
    except pygit2.GitError:
        return None


def path_to_name(ref_path: str) -> str:
    parts = ref_path.split("/", 2)
    return parts[2] if len(parts) == 3 else ref_path


def active_branch_path(repo: pygit2.Repository) -> Optional[str]:
    """Return the full ref path of the current branch, or None if HEAD is detached."""
    if repo.head_is_detached:
        return None
    return repo.head.name  # e.g. "refs/heads/main"


def is_valid_repo(path: str) -> bool:
    try:
        pygit2.Repository(path)
        return True
    except pygit2.GitError:
        return False


def iter_refs(root: str, filter: str = "") -> Iterator[str]:
    repo = pygit2.Repository(root)
    prefix = f"refs/{filter}"
    for ref in repo.references:
        if ref.startswith(prefix):
            yield ref


def git_root(path: str) -> Optional[str]:
    if not path:
        return None
    try:
        return pygit2.discover_repository(path)
    except pygit2.GitError:
        return None


def _is_ancestor(repo: pygit2.Repository, ancestor_oid: pygit2.Oid, descendant_oid: pygit2.Oid) -> bool:
    merge_base = repo.merge_base(ancestor_oid, descendant_oid)
    return merge_base == ancestor_oid


def is_upstream(root: str, remote: str, branch: str) -> bool:
    tracking_ref = f"refs/remotes/{remote}/{branch}"
    return tracking_ref not in pygit2.Repository(root).references


def is_branch_fully_merged(repo: pygit2.Repository, branch: str) -> bool:
    try:
        base_commit = repo.references["refs/remotes/origin/HEAD"].resolve().peel(pygit2.Commit)
    except KeyError:
        base_commit = repo.head.peel(pygit2.Commit)
    branch_commit = repo.references[branch].resolve().peel(pygit2.Commit)
    return _is_ancestor(repo, branch_commit.id, base_commit.id)


def can_fast_forward(repo: pygit2.Repository, branch: str) -> bool:
    head_commit = repo.head.peel(pygit2.Commit)
    branch_commit = repo.references[branch].peel(pygit2.Commit)
    return _is_ancestor(repo, head_commit.id, branch_commit.id)
