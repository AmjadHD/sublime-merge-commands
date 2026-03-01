import sublime
import sublime_plugin

from typing import List, Optional, Set, Dict
import os
os.add_dll_directory(r"C:\Users\Lehdhili\AppData\Roaming\Sublime Text\Lib\python38\python3dll")
import pygit2  # noqa: E402
from .utils.utils import git_root, can_fast_forward, is_branch_fully_merged, is_valid_repo, iter_refs, name_to_path, path_to_name  # noqa: E402


def git_root_setting(view: sublime.View) -> Optional[str]:
    settings = view.settings()
    if "git_root" not in settings:
        settings["git_root"] = git_root(
            sublime.expand_variables("$file_path", view.window().extract_variables())  # type: ignore
        )
    result = settings["git_root"]
    if isinstance(result, str) or result is None:
        return result
    else:
        raise ValueError("git_root setting must be a string or null")


def git_run(view: sublime.View, cmd: List[str]):
    cmd.insert(0, "git")
    if (w := view.window()):
        w.run_command("exec", {"cmd": cmd})


class CheckoutBranchCommand(sublime_plugin.TextCommand):
    def run( # type: ignore
        self, edit, branch: str, create_branch=False, new_name: Optional[str] = None
    ):
        if git_root_setting(self.view):
            if not create_branch or branch.startswith("refs/heads"):
                new_name = None
            cmd = ["checkout"]
            if new_name:
                cmd.append("-b")
                cmd.append(new_name)
            cmd.append(path_to_name(branch))
            git_run(self.view, cmd)

    def is_enabled(self):
        root = git_root_setting(self.view)
        return isinstance(root, str) and is_valid_repo(root)

    def input_description(self):
        return "Checkout"

    def input(self, args):
        if not isinstance(root := git_root_setting(self.view), str):
            return
        if "branch" not in args:
            return BranchInputHandler(
                root,
                args.get("local_refs", True),
                args.get("remote_refs", True),
                args.get("tag_refs", True),
            )
        path = name_to_path(pygit2.Repository(root), args["branch"])
        if path is not None and not path.startswith("refs/heads"):
            args["branch"] = path
            if "create_branch" not in args:
                return CheckoutBranchCreateBranchInputHandler(args["branch"])
            if args["create_branch"] is True and not args.get("new_name"):
                return CheckoutBranchNewNameInputHandler(args["branch"])


def _active_branch_path(repo: pygit2.Repository) -> Optional[str]:
    """Return the full ref path of the current branch, or None if HEAD is detached."""
    if repo.head_is_detached:
        return None
    return repo.head.name  # e.g. "refs/heads/main"


class BranchInputHandler(sublime_plugin.ListInputHandler):
    KIND_LOCAL = (sublime.KindId.COLOR_BLUISH, "L", "Local Branch")
    KIND_REMOTE = (sublime.KindId.COLOR_PURPLISH, "R", "Remote Branch")
    KIND_TAG = (sublime.KindId.COLOR_YELLOWISH, "T", "Tag")

    def __init__(self, root: str, local_refs: bool, remote_refs: bool, tag_refs: bool, include_active_branch=True):
        self.root = root
        self.local_refs = local_refs
        self.remote_refs = remote_refs
        self.tag_refs = tag_refs
        self.include_active_branch = include_active_branch

    def list_items(self):
        repo = pygit2.Repository(self.root)
        active_path = _active_branch_path(repo)

        items: List[sublime.ListInputItem] = []
        i = 0
        if self.local_refs:
            for j, head in enumerate(iter_refs(self.root, "heads")):
                if active_path and head == active_path:
                    i = j
                    if not self.include_active_branch:
                        continue
                items.append(
                    sublime.ListInputItem(
                        path_to_name(head), head, kind=self.KIND_LOCAL
                    )
                )
        if self.remote_refs:
            items.extend(
                sublime.ListInputItem(path_to_name(ref), ref, kind=self.KIND_REMOTE)
                for ref in iter_refs(self.root, "remotes")
                if ref[-4:] != "HEAD"
            )
        if self.tag_refs:
            items.extend(
                sublime.ListInputItem(path_to_name(tag), tag, kind=self.KIND_TAG)
                for tag in iter_refs(self.root, "tags")
            )

        return (items, i)

    def placeholder(self) -> str:
        return "Branch or Tag Name"

    def next_input(self, args):
        if args["branch"].startswith("refs/heads"):
            return None
        if "create_branch" not in args:
            return CheckoutBranchCreateBranchInputHandler(args["branch"])
        if args["create_branch"] is True:
            return CheckoutBranchNewNameInputHandler(args["branch"])


class CheckoutBranchCreateBranchInputHandler(sublime_plugin.ListInputHandler):
    def __init__(self, branch: str):
        self.branch = branch

    def name(self):
        return "create_branch"

    def list_items(self):
        branch = "remote branch" if self.branch.startswith("refs/remotes") else "tag"
        return [
            sublime.ListInputItem("Check out commit on " + branch, False, annotation="(runs git checkout)"),
            sublime.ListInputItem("Create local branch", True, annotation="(runs git checkout -b)"),
        ]

    def next_input(self, args):
        if args["create_branch"] is True and not args.get("new_name"):
            return CheckoutBranchNewNameInputHandler(args["branch"])


class CheckoutBranchNewNameInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, branch: str):
        self.branch = branch
        self.branch_name = path_to_name(branch)

    def name(self):
        return "new_name"

    def initial_text(self):
        if not self.branch.startswith("refs/tags"):
            return self.branch_name.rsplit("/", 1)[-1]
        return ""

    def initial_selection(self):
        return [(0, len(self.branch_name.rsplit("/", 1)[-1]))] if not self.branch.startswith("refs/tags") else []

    def placeholder(self):
        return "New Branch Name"

    def preview(self, text: str):
        return f"Create new branch{' ' if text else ''}{text} based on {self.branch_name}"

    def validate(self, text: str, event = None):
        return len(text) != 0


class CreateBranchCommand(sublime_plugin.TextCommand):
    def run(self, edit, name: str): # type: ignore
        if git_root_setting(self.view) is None:
            return
        git_run(self.view, ["checkout", "-b", name])

    def is_enabled(self):
        return git_root_setting(self.view) is not None

    def input_description(self):
        return "Create Branch"

    def input(self, args):
        if "name" not in args:
            return CreateBranchNameInputHandler()


class CreateBranchNameInputHandler(sublime_plugin.TextInputHandler):
    def name(self):
        return "name"

    def placeholder(self):
        return "Branch Name"

    def validate(self, text: str, event = None):
        return len(text) != 0


class RenameBranchCommand(sublime_plugin.TextCommand):
    def run(self, edit, branch: str, new_name: str): # type: ignore
        if git_root_setting(self.view) is None:
            return
        git_run(self.view, ["branch", "-m", branch, new_name])

    def is_enabled(self):
        root = git_root_setting(self.view)
        return root is not None and is_valid_repo(root)

    def input_description(self):
        return "Rename Branch"

    def input(self, args):
        if not (root := git_root_setting(self.view)):
            return
        if "Branch" not in args:
            return RenameBranchBranchInputHandler(root)
        if "new_name" not in args:
            return RenameBranchNewNameInputHandler(args["branch"])


class RenameBranchBranchInputHandler(sublime_plugin.ListInputHandler):
    def __init__(self, root: str):
        self.root = root

    def name(self):
        return "branch"

    def list_items(self):
        repo = pygit2.Repository(self.root)
        active_path = _active_branch_path(repo)

        items: List[str] = []
        i = 0
        for j, head in enumerate(iter_refs(self.root, "heads")):
            if active_path and head == active_path:
                i = j
            items.append(path_to_name(head))

        return (items, i)

    def placeholder(self):
        return "Branch to Rename"

    def next_input(self, args):
        if "new_name" not in args:
            return RenameBranchNewNameInputHandler(args["branch"])


class RenameBranchNewNameInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, branch: str):
        self.branch = branch

    def name(self):
        return "new_name"

    def initial_text(self):
        return self.branch

    def initial_selection(self):
        return [(0, len(self.branch))]

    def placeholder(self):
        return "New Branch Name"

    def preview(self, text: str):
        return f"Rename {self.branch} to {text}"

    def validate(self, text: str, event = None):
        return len(text) != 0


class DeleteBranchCommand(sublime_plugin.TextCommand):
    def run(self, edit, branch: str, prompt=True, local_refs=True, remote_refs=False, tag_refs=True): # type: ignore
        if isinstance(root := git_root_setting(self.view), str):
            branch_name = path_to_name(branch)
            if (
                prompt
                and sublime.ok_cancel_dialog(
                    f"Delete branch {branch_name}?", "Delete", "Confirm Delete"
                )
                != sublime.DIALOG_YES
            ):
                return
            cmd = ["branch", "-d", branch_name]
            if branch.startswith("refs/remotes/"):
                repo = pygit2.Repository(root)
                if not is_branch_fully_merged(repo, branch):
                    if sublime.ok_cancel_dialog(
                        f"{branch_name} isn't fully merged.\nDo you want to force the deletion?\nThis will also delete the branch on the remote repository.",
                        "Force Delete",
                        "Confirm Force Delete",
                    ) == sublime.DIALOG_YES:
                        cmd = ["push", "--delete", "--", "origin", branch_name]
            git_run(self.view, cmd)

    def is_enabled(self):
        root = git_root_setting(self.view)
        return isinstance(root, str) and is_valid_repo(root)

    # def input_description(self):
    #     return "Delete Branch"

    def input(self, args):
        if not isinstance(root := git_root_setting(self.view), str):
            return
        if "branch" not in args:
            return DeleteBranchBranchInputHandler(
                root,
                args.get("local_refs", True),
                args.get("remote_refs", False),
                args.get("tag_refs", True),
            )


class DeleteBranchBranchInputHandler(BranchInputHandler):
    def next_input(self, args):
        return None


class OptionsInputHandler(sublime_plugin.ListInputHandler):
    options: Dict[str, str]
    excludes: Dict[str, Set[str]]
    terminal: str

    def __init__(self, accumulated: List[str] = []) -> None:
        self.available = [self.terminal, *self.options_after(accumulated)]
        self.accumulated = accumulated
        self.selected: List[str] = accumulated
        self.done = False
        print(f"{self.__class__.__name__}(available: {self.available}, selected: {self.selected}, accumulated: {accumulated})")

    def name(self) -> str:
        return "options"

    def placeholder(self) -> str:
        return "Choose flags"

    def list_items(self):
        return (
            [
                sublime.ListInputItem(item, self.accumulated + [item], annotation=self.options[item])
                for item in self.available
            ],
            0
        )

    def confirm(self, value: List[str], event=None):
        self.done = value[-1] == self.terminal
        self.selected = value

    def options_after(self, selected: List[str]) -> Set[str]:
        result = set(self.options.keys()) - set(selected)
        result.remove(self.terminal)
        for val in selected:
            result -= self.excludes.get(val, set())
        return result

    def next_input(self, args):
        if not self.done:
            return self.__class__(self.selected)
        return self.tail(args)

    def tail(self, args) -> Optional[sublime_plugin.CommandInputHandler]:
        return None


class MergeBranchCommand(sublime_plugin.TextCommand):
    def run(self, _, branch: str, options: List[str]):
        if not isinstance(git_root_setting(self.view), str):
            return

        branch_name = path_to_name(branch)
        if options[-1] == "merge":
            options = options[0:-2]
        cmd = ["merge", branch_name, *options]
        git_run(self.view, cmd)

    def is_enabled(self):
        root = git_root_setting(self.view)
        return isinstance(root, str) and is_valid_repo(root)

    def input_description(self):
        return "Merge Branch"

    def input(self, args):
        if not isinstance(root := git_root_setting(self.view), str):
            return

        if "branch" not in args:
            return MergeBranchBranchInputHandler(root)
        if "options" not in args:
            return MergeBranchOptionsInputHandler()

class MergeBranchBranchInputHandler(BranchInputHandler):
    def __init__(self, root: str):
        super().__init__(root, local_refs=True, remote_refs=True, tag_refs=True, include_active_branch=False)
        repo = pygit2.Repository(self.root)
        # active_branch is the short name (e.g. "main"); fall back to detached HEAD OID
        self.active_branch = str(repo.head.target)[:7] if repo.head_is_detached else repo.head.shorthand

    def placeholder(self) -> str:
        return "Branch Name"

    def preview(self, text: str) -> str:
        branch_name = path_to_name(text)
        return f"Merge {branch_name} into {self.active_branch}"

    def next_input(self, args):
        if "options" not in args:
            return MergeBranchOptionsInputHandler()


class MergeBranchOptionsInputHandler(OptionsInputHandler):
    options = {
        "merge":                        "Select to run command",
        "--no-ff":                      "Always create a merge commit",
        "--no-commit":                  "Stage the merge, but don't commit yet",
        "--squash":                     "Combine merged changes into a single commit",
        "--allow-unrelated-histories":  "Allow merging branches that do not share a common ancestor",
    }
    excludes = {
        "--no-ff":     {"--squash"},
        "--squash":    {"--no-ff", "--no-commit"},
        "--no-commit": {"--squash"},
    }
    terminal = "merge"


class AddRemoteCommand(sublime_plugin.TextCommand):
    def run(self, edit, name: str, url: str): # type: ignore
        if git_root_setting(self.view) is None:
            return
        git_run(self.view, ["remote", "add", name, url])

    def is_enabled(self):
        return git_root_setting(self.view) is not None

    def input_description(self):
        return "Add Remote"

    def input(self, args):
        if "name" not in args:
            return AddRemoteNameInputHandler()
        if "url" not in args:
            return AddRemoteUrlInputHandler()


class AddRemoteNameInputHandler(sublime_plugin.TextInputHandler):
    def name(self):
        return "name"

    def validate(self, text: str, event = None):
        return not any(c in text for c in "./\\:[?^*~")

    def preview(self, text: str):
        return "" if self.validate(text) else "Invalid Remote Name"

    def placeholder(self):
        return 'Remote Name (e.g. "orgin")'

    def next_input(self, args):
        if "url" not in args:
            return AddRemoteUrlInputHandler()


class AddRemoteUrlInputHandler(sublime_plugin.TextInputHandler):
    def name(self):
        return "url"

    def validate(self, text: str, event = None):
        return len(text) != 0

    def placeholder(self):
        return "Remote URL"


class CreateTagCommand(sublime_plugin.TextCommand):
    def run(self, edit, name: str, message: str): # type: ignore
        if git_root_setting(self.view):
            git_run(self.view, ["tag", name, message])

    def is_enabled(self):
        return (root := git_root_setting(self.view)) is not None and is_valid_repo(root)

    def input_description(self):
        return "Create Tag"

    def input(self, args):
        if (root := git_root_setting(self.view)) is None:
            return
        repo = pygit2.Repository(root)
        head_commit = repo.head.peel(pygit2.Commit)
        html = sublime.Html(
            f'<div>Create tag at HEAD commit <i>"{head_commit.message}"</i></div>'
        )
        if "name" not in args:
            return CreateTagNameInputHandler(html)
        if "message" not in args:
            return CreateTagMessageInputHandler(html)


class CreateTagNameInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, html: sublime.Html):
        self.html = html

    def name(self):
        return "name"

    def placeholder(self):
        return "Tag Name"

    def validate(self, text: str, event = None):
        return len(text) != 0

    def preview(self, text: str):
        return self.html

    def next_input(self, args):
        if "message" not in args:
            return CreateTagMessageInputHandler(self.html)


class CreateTagMessageInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, html: sublime.Html):
        self.html = html

    def name(self):
        return "message"

    def placeholder(self):
        return "Tag Message"

    def preview(self, text: str):
        return self.html


class DeleteRemoteCommand(sublime_plugin.TextCommand):
    def run(self, edit, remote: str, prompt=True): # type: ignore
        if git_root_setting(self.view) is None:
            return
        delete = True
        if prompt:
            delete = sublime.ok_cancel_dialog(
                "Delete remote ?", "Delete", "Confirm Delete"
            )
        if delete:
            git_run(self.view, ["remote", "remove", remote])

    def is_enabled(self):
        return (root := git_root_setting(self.view)) is not None and is_valid_repo(root)

    def input_description(self):
        return "Delete Remote"

    def input(self, args):
        if (root := git_root_setting(self.view)) and "remote" not in args:
            return RemoteInputHandler(root)


class RemoteInputHandler(sublime_plugin.ListInputHandler):
    def __init__(self, root: str):
        self.root = root

    def name(self):
        return "remote"

    def list_items(self):
        repo = pygit2.Repository(self.root)
        return list(repo.remotes.names())

    def placeholder(self):
        return "Remote"


class AddSubmoduleCommand(sublime_plugin.TextCommand):
    def run(self, edit, repository_path: str, submodule_name: str): # type: ignore
        if git_root_setting(self.view):
            git_run(
                self.view,
                ["submodule", "add", "--name", submodule_name, "--", repository_path],
            )

    def is_enabled(self):
        return git_root_setting(self.view) is not None

    def input_description(self):
        return "Add Submodule"

    def input(self, args):
        if "repository_path" not in args:
            return AddSubmoduleRepositoryPathInputHandler()
        if "submodule_name" not in args:
            return AddSubmoduleSubmoduleNameInputHandler(args["repository_path"])


class AddSubmoduleRepositoryPathInputHandler(sublime_plugin.TextInputHandler):
    def name(self):
        return "repository_path"

    def placeholder(self):
        return "Repository URL"

    def validate(self, text: str, event = None):
        return len(text) != 0

    def preview(self, text: str):
        return "The URL to the submodule origin repository"

    def next_input(self, args):
        if "submodule_name" not in args:
            return AddSubmoduleSubmoduleNameInputHandler(args["repository_path"])


class AddSubmoduleSubmoduleNameInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, path: str):
        self._initial_text = path.rsplit("/")[-1]

    def name(self):
        return "submodule_name"

    def placeholder(self):
        return "Submodule Name"

    def initial_text(self):
        return self._initial_text

    def initial_selection(self):
        return [(0, len(self._initial_text))]

    def preview(self, text: str):
        return "The name that will be stored in the .gitmodules file"

def stash_subcommand(selected: List[str]) -> str:
    return "push" if any(f in ('--include-untracked', '--keep-index') for f in selected) else "save"

def get_stash_cmd(selected: List[str], text: str) -> List[str]:
    subcommand = stash_subcommand(selected)
    result = ["stash", subcommand, *selected]
    if text:
        if subcommand == "push":
            result += "-m"
        result.append(f'"{text}"' if ' ' in text else text)
    return result


class StashCommand(sublime_plugin.TextCommand):
    def run(self, _, options: List[str], message=""):
        if not isinstance(git_root_setting(self.view), str):
            return

        if options[-1] == "stash":
            options = options[:-2]
        cmd = get_stash_cmd(options, message)
        git_run(self.view, cmd)

    def is_enabled(self):
        root = git_root_setting(self.view)
        return isinstance(root, str) and is_valid_repo(root)

    def input_description(self):
        return "Stash"

    def input(self, args):
        if not isinstance(git_root_setting(self.view), str):
            return

        if "options" not in args:
            return StashOptionsInputHandler()

        if "message" not in args:
            return StashMessageInputHandler(args["options"])


class StashOptionsInputHandler(OptionsInputHandler):
    options = {
        "stash":               "Select to run command",
        "--include-untracked": "Include untracked files in the stash",
        "--keep-index":        "Leave staged changes in the working directory",
        "--staged":            "Stash staged changes only",
    }
    excludes = {
        "--include-untracked": {"--staged"},
        "--staged":            {"--include-untracked"},
        "--keep-index":        set(),
    }
    terminal = "stash"

    def tail(self, args):
        if "message" not in args:
            return StashMessageInputHandler(args["options"])


class StashMessageInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, selected: List[str]) -> None:
        self.selected = selected
        self.subcommand = stash_subcommand(selected)

    def name(self) -> str:
        return "message"

    def preview(self, text: str) -> str:
        return "Runs: git " + ' '.join(get_stash_cmd(self.selected, text))

    def placeholder(self) -> str:
        return "Optional Message"

class PopStashCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        if git_root_setting(self.view):
            git_run(self.view, ["stash", "pop"])


class DropStashesCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        if git_root_setting(self.view):
            git_run(self.view, ["stash", "drop"])


class ClearStashesCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        if git_root_setting(self.view) is None:
            return
        msg = "This will permanently erase all stashes.\n\nAre you sure you want to continue ?"
        if sublime.ok_cancel_dialog(msg, "Clear All Stashes", "Confirm Clear Stashes"):
            git_run(self.view, ["stash", "clear"])


class StageAllCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        if git_root_setting(self.view):
            git_run(self.view, ["add", "-A"])


class StageAllModifiedCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        if git_root_setting(self.view):
            git_run(self.view, ["add", "-u"])


class UnstageAllCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        if git_root_setting(self.view):
            git_run(self.view, ["reset"])


class FetchCommand(sublime_plugin.TextCommand):
    fetch_modes = {
        "fetch":              "Fetch from a remote",
        "fetch --prune":      "Fetch and delete stale remote-tracking refs",
        "fetch --tags":       "Fetch all tags from a remote",
        "fetch --all":        "Fetch from all remotes",
        "fetch --all --prune":"Fetch from all remotes and delete stale remote-tracking refs",
        "fetch --all --tags": "Fetch all tags from all remotes",
    }

    def run(self, _, mode: str, remote: str = ""):  # type: ignore
        if not isinstance(git_root_setting(self.view), str):
            return
        cmd = mode.split()
        if remote:
            cmd.append(remote)
        git_run(self.view, cmd)

    def is_enabled(self):
        root = git_root_setting(self.view)
        return isinstance(root, str) and is_valid_repo(root)

    def input_description(self):
        return "Fetch"

    def input(self, args):
        if not isinstance(root := git_root_setting(self.view), str):
            return
        if "mode" not in args:
            return FetchModeInputHandler(root)
        if "remote" not in args and "--all" not in args["mode"]:
            return RemoteInputHandler(root)


class FetchModeInputHandler(sublime_plugin.ListInputHandler):
    def __init__(self, root: str) -> None:
        self.root = root

    def name(self) -> str:
        return "mode"

    def placeholder(self) -> str:
        return "Fetch Mode"

    def list_items(self):
        return [
            sublime.ListInputItem(mode, mode, annotation=annotation)
            for mode, annotation in FetchCommand.fetch_modes.items()
        ]

    def next_input(self, args):
        if "remote" not in args and "--all" not in args["mode"]:
            return RemoteInputHandler(self.root)

class RebaseBranchCommand(sublime_plugin.TextCommand):
    def run(self, _, branch: str):  # type: ignore
        if not isinstance(git_root_setting(self.view), str):
            return
        git_run(self.view, ["rebase", path_to_name(branch)])

    def is_enabled(self):
        root = git_root_setting(self.view)
        return isinstance(root, str) and is_valid_repo(root)

    def input_description(self):
        return "Rebase Branch"

    def input(self, args):
        if not isinstance(root := git_root_setting(self.view), str):
            return
        if "branch" not in args:
            return RebaseBranchBranchInputHandler(root)


class RebaseBranchBranchInputHandler(BranchInputHandler):
    def __init__(self, root: str):
        super().__init__(root, local_refs=True, remote_refs=True, tag_refs=False)
        repo = pygit2.Repository(root)
        self.current = repo.head.shorthand if not repo.head_is_detached else str(repo.head.target)[:7]

    def placeholder(self) -> str:
        return "Branch Name"

    def preview(self, text: str) -> str:
        return f"Rebase {self.current} onto {path_to_name(text)}"

    def next_input(self, args):
        return None

def is_upstream(root: str, remote: str, branch: str) -> bool:
    tracking_ref = f"refs/remotes/{remote}/{branch}"
    return tracking_ref not in pygit2.Repository(root).references

class PushCommand(sublime_plugin.TextCommand):
    def run(self, _, branch: str, remote: str, mode: str, prompt=True):  # type: ignore
        if not isinstance(root := git_root_setting(self.view), str):
            return
        repo = pygit2.Repository(root)
        branch_name = path_to_name(branch)
        tracking_ref = f"refs/remotes/{remote}/{branch_name}"
        no_tracking_ref = tracking_ref not in repo.references
        if prompt and (no_tracking_ref or can_fast_forward(repo, tracking_ref)):
            if sublime.ok_cancel_dialog(
                f"Push {branch_name} to {remote}?", "Push", "Confirm Push"
            ) != sublime.DIALOG_YES:
                return
        cmd = mode.split() + [remote, branch]
        git_run(self.view, cmd)

    def is_enabled(self):
        root = git_root_setting(self.view)
        return isinstance(root, str) and is_valid_repo(root)

    def input_description(self):
        return "Push"

    def input(self, args):
        if not isinstance(root := git_root_setting(self.view), str):
            return
        if "branch" not in args:
            return PushBranchInputHandler(root)
        if "remote" not in args:
            return PushRemoteInputHandler(root)
        if "mode" not in args:
            return PushModeInputHandler(is_upstream(root, args["remote"], args["branch"]))


class PushBranchInputHandler(BranchInputHandler):
    def __init__(self, root: str) -> None:
        super().__init__(root, local_refs=True, remote_refs=False, tag_refs=False)

    def name(self) -> str:
        return "branch"

    def placeholder(self) -> str:
        return "Source Branch"

    def next_input(self, args):
        if "remote" not in args:
            return PushRemoteInputHandler(self.root)
        if "mode" not in args:
            return PushModeInputHandler(is_upstream(self.root, args["remote"], args["branch"]))


class PushRemoteInputHandler(RemoteInputHandler):
    def next_input(self, args):
        if "mode" not in args:
            return PushModeInputHandler(is_upstream(self.root, args["remote"], args["branch"]))


class PushModeInputHandler(sublime_plugin.ListInputHandler):
    push_modes = {
        "push":                   "Push to remote",
        "push --force-with-lease":"Push, fail if remote has changes you don't have",
        "push --force":           "Force push, overwriting remote history",
        "push --no-verify":       "Push, skipping pre-push hooks",
    }

    def __init__(self, is_upstream: bool) -> None:
        self.modes = self.push_modes
        if is_upstream:
            self.modes["push --set-upstream"] = "Push and set upstream tracking"

    def name(self) -> str:
        return "mode"

    def placeholder(self) -> str:
        return "Push Mode"

    def list_items(self):
        return [
            sublime.ListInputItem(mode, mode, annotation=annotation)
            for mode, annotation in self.modes.items()
        ]
