from typing import Iterator, Optional

import pygit2


def name_to_path(root: str, name: str) -> Optional[str]:
    for ref in iter_refs(root):
        if ref.endswith(name):
            return ref


def path_to_name(path: str) -> str:
    tokens = path.split("/")
    return path if len(tokens) < 3 else "/".join(tokens[2:])


def is_valid_repo(path: str) -> bool:
    try:
        pygit2.Repository(path)
        return True
    except pygit2.GitError:
        return False


def iter_refs(root: str, filter: str = "") -> Iterator[str]:
    repo = pygit2.Repository(root)
    prefix = f"refs/{filter}" if filter else "refs/"
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


def is_branch_fully_merged(repo_path: str, branch_name: str) -> bool:
    repo = pygit2.Repository(repo_path)

    try:
        # Try origin/HEAD first
        origin_head = repo.references["refs/remotes/origin/HEAD"]
        base_commit = repo.get(origin_head.resolve().target)
    except KeyError:
        base_commit = repo.head.peel(pygit2.Commit)

    try:
        branch_ref = repo.references[branch_name]
    except KeyError:
        print(f"Branch '{branch_name}' not found.")
        return False

    branch_commit = repo.get(branch_ref.resolve().target)

    # merge_base returns the OID of the common ancestor; if it equals branch_commit's OID,
    # the branch is fully merged into base.
    try:
        merge_base_oid = repo.merge_base(branch_commit.id, base_commit.id)
    except Exception:
        return False

    return merge_base_oid == branch_commit.id
