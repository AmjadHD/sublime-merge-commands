import sublime
import sublime_plugin

from typing import List, Optional, Set, Dict
import time
import os
os.add_dll_directory("C:\\MyDLLs") # python3.dll is not shipped with sublime text.
import pygit2  # noqa: E402
from .utils.utils import git_root, is_upstream, active_branch_path, can_fast_forward, is_branch_fully_merged, is_valid_repo, iter_refs, name_to_path, path_to_name  # noqa: E402


class MyGitCommand(sublime_plugin.TextCommand):
    def is_enabled(self):
        root = self.git_root_setting()
        return root is not None and is_valid_repo(root)

    def git_run(self, cmd: List[str]):
        cmd.insert(0, "git")
        if (w := self.view.window()):
            w.run_command("exec", {"cmd": cmd})

    def git_root_setting(self) -> Optional[str]:
        _GIT_ROOT_TTL = 60.0
        settings = self.view.settings()
        now = time.monotonic()

        if "git_root" not in settings or now - settings.get("git_root_ts", 0) > _GIT_ROOT_TTL:  # type: ignore
            settings["git_root"] = git_root(
                self.view.window().extract_variables().get("file_path", "")  # type: ignore
            )
            settings["git_root_ts"] = now

        result = settings["git_root"]
        if isinstance(result, str) or result is None:
            return result
        else:
            raise ValueError("git_root setting must be a string or null")


class BranchInputHandler(sublime_plugin.ListInputHandler):
    KIND_LOCAL = (sublime.KindId.COLOR_BLUISH, "L", "Local Branch")
    KIND_REMOTE = (sublime.KindId.COLOR_PURPLISH, "R", "Remote Branch")
    KIND_TAG = (sublime.KindId.COLOR_YELLOWISH, "T", "Tag")

    def __init__(self, root: str, local_refs=False, remote_refs=False, tag_refs=False, include_active_branch=True):
        self.root = root
        self.local_refs = local_refs
        self.remote_refs = remote_refs
        self.tag_refs = tag_refs
        self.include_active_branch = include_active_branch

    def name(self) -> str:
        return "branch"

    def get_kind(self, kind):
        if self.local_refs + self.remote_refs + self.tag_refs == 1:
            return sublime.KIND_AMBIGUOUS
        else:
            return kind

    def list_items(self):
        repo = pygit2.Repository(self.root)
        active_path = active_branch_path(repo)

        items: List[sublime.ListInputItem] = []
        i = 0
        if self.local_refs:
            kind = self.get_kind(self.KIND_LOCAL)
            for j, head in enumerate(iter_refs(self.root, "heads")):
                if active_path and head == active_path:
                    if self.include_active_branch:
                        i = j
                    else:
                        continue
                items.append(
                    sublime.ListInputItem(path_to_name(head), head, kind=kind)
                )
        if self.remote_refs:
            kind = self.get_kind(self.KIND_REMOTE)
            items.extend(
                sublime.ListInputItem(path_to_name(ref), ref, kind=kind)
                for ref in iter_refs(self.root, "remotes")
                if ref[-4:] != "HEAD"
            )
        if self.tag_refs:
            kind = self.get_kind(self.KIND_TAG)
            items.extend(
                sublime.ListInputItem(path_to_name(tag), tag, kind=kind)
                for tag in iter_refs(self.root, "tags")
            )

        return (items, i)

    def placeholder(self) -> str:
        return "Branch or Tag Name"


class CheckoutBranchCommand(MyGitCommand):
    def run( # type: ignore
        self, edit, branch: str, create_branch=False, new_name: Optional[str] = None
    ):
        if not create_branch or branch.startswith("refs/heads"):
            new_name = None
        cmd = ["checkout"]
        if new_name:
            cmd.append("-b")
            cmd.append(new_name)
        cmd.append(path_to_name(branch))
        self.git_run(cmd)

    def input_description(self):
        return "Checkout"

    def input(self, args):
        if not (root := self.git_root_setting()):
            return
        if "branch" not in args:
            return CheckoutBranchBranchInputHandler(
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


class CheckoutBranchBranchInputHandler(BranchInputHandler):
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
        source = "remote branch" if self.branch.startswith("refs/remotes") else "tag"
        return [
            sublime.ListInputItem("Check out commit on " + source, False, annotation="(runs git checkout)"),
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


class CreateBranchCommand(MyGitCommand):
    def run(self, edit, name: str): # type: ignore
        self.git_run(["checkout", "-b", name])

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


class RenameBranchCommand(MyGitCommand):
    def run(self, edit, branch: str, new_name: str): # type: ignore
        shorthand = path_to_name(branch) if branch.startswith("refs/") else branch
        self.git_run(["branch", "-m", shorthand, new_name])

    def input_description(self):
        return "Rename Branch"

    def input(self, args):
        if not (root := self.git_root_setting()):
            return
        if "Branch" not in args:
            return RenameBranchBranchInputHandler(root, local_refs=True)
        if "new_name" not in args:
            return RenameBranchNewNameInputHandler(args["branch"])


class RenameBranchBranchInputHandler(BranchInputHandler):
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


class DeleteBranchCommand(MyGitCommand):
    def run(self, edit, branch: str, prompt=True): # type: ignore
        if not (root := self.git_root_setting()):
            return
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
                    branch_name + " isn't fully merged.\n\
                    Do you want to force the deletion?\n\
                    This will also delete the branch on the remote repository.",
                    "Force Delete",
                    "Confirm Force Delete",
                ) == sublime.DIALOG_YES:
                    cmd = ["push", "--delete", "--", "origin", branch_name]
        self.git_run(cmd)

    def input_description(self):
        return "Delete Branch"

    def input(self, args):
        if not (root := self.git_root_setting()):
            return
        if "branch" not in args:
            return BranchInputHandler(
                root,
                args.get("local_refs", True),
                args.get("remote_refs", False),
                args.get("tag_refs", True),
            )


class OptionsInputHandler(sublime_plugin.ListInputHandler):
    options: Dict[str, str]
    excludes: Dict[str, Set[str]]
    terminal: str

    def __init__(self, accumulated: List[str] = []) -> None:
        self.available = [self.terminal, *self.options_after(accumulated)]
        self.accumulated = accumulated
        self.selected: List[str] = accumulated
        self.done = False

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


class MergeBranchCommand(MyGitCommand):
    def run(self, _, branch: str, options: List[str]):
        branch_name = path_to_name(branch)
        if options[-1] == "merge":
            options = options[0:-2]
        cmd = ["merge", branch_name, *options]
        self.git_run(cmd)

    def is_enabled(self):
        root = self.git_root_setting()
        return root is not None and is_valid_repo(root) and not pygit2.Repository(root).head_is_detached

    def input_description(self):
        return "Merge Branch"

    def input(self, args):
        if not (root := self.git_root_setting()):
            return

        if "branch" not in args:
            return MergeBranchBranchInputHandler(root)
        if "options" not in args:
            return MergeBranchOptionsInputHandler()

class MergeBranchBranchInputHandler(BranchInputHandler):
    def __init__(self, root: str):
        super().__init__(root, local_refs=True, remote_refs=True, include_active_branch=False)
        repo = pygit2.Repository(self.root)
        # active_branch is the short name (e.g. "main"); fall back to detached HEAD OID
        self.active_branch_name = repo.head.shorthand

    def placeholder(self) -> str:
        return "Branch Name"

    def preview(self, text: str) -> str:
        branch_name = path_to_name(text)
        return f"Merge {branch_name} into {self.active_branch_name}"

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


class AddRemoteCommand(MyGitCommand):
    def run(self, edit, name: str, url: str): # type: ignore
        self.git_run(["remote", "add", name, url])

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
        return not any(c in text for c in " ./\\:[?^*~")

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


class CreateTagCommand(MyGitCommand):
    def run(self, edit, name: str, message: str): # type: ignore
        self.git_run(["tag", name, message])

    def input_description(self):
        return "Create Tag"

    def input(self, args):
        if not (root := self.git_root_setting()):
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


class DeleteRemoteCommand(MyGitCommand):
    def run(self, edit, remote: str, prompt=True): # type: ignore
        delete = True
        if prompt:
            delete = sublime.ok_cancel_dialog(
                "Delete remote ?", "Delete", "Confirm Delete"
            )
        if delete:
            self.git_run(["remote", "remove", remote])

    def input_description(self):
        return "Delete Remote"

    def input(self, args):
        if (root := self.git_root_setting()) and "remote" not in args:
            return RemoteInputHandler(root)


class RemoteInputHandler(sublime_plugin.ListInputHandler):
    def __init__(self, root: str):
        self.root = root

    def name(self):
        return "remote"

    def list_items(self): # type: ignore
        repo = pygit2.Repository(self.root)
        return list(repo.remotes.names())

    def placeholder(self):
        return "Remote"


class RenameRemoteCommand(MyGitCommand):
    def run(self, _, remote: str, new_name: str):  # type: ignore
        self.git_run(["remote", "rename", remote, new_name])

    def input_description(self):
        return "Rename Remote"

    def input(self, args):
        if not (root := self.git_root_setting()):
            return
        if "remote" not in args:
            return RenameRemoteRemoteInputHandler(root)
        if "new_name" not in args:
            return RenameRemoteNewNameInputHandler()


class RenameRemoteRemoteInputHandler(RemoteInputHandler):
    def next_input(self, args):
        if "new_name" not in args:
            return RenameRemoteNewNameInputHandler()


class RenameRemoteNewNameInputHandler(sublime_plugin.TextInputHandler):
    def name(self) -> str:
        return "new_name"

    def placeholder(self) -> str:
        return 'New Remote Name (e.g., "origin")'

    def validate(self, text: str, event=None) -> bool:
        return not any(c in text for c in " ./\\:[?^*~")


class AddSubmoduleCommand(MyGitCommand):
    def run(self, edit, repository_path: str, submodule_name: str): # type: ignore
        self.git_run(
            ["submodule", "add", "--name", submodule_name, "--", repository_path],
        )

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


def get_stash_cmd(selected: List[str], text: str) -> List[str]:
    subcommand = "push" if '--include-untracked' in selected or '--keep-index' in selected else "save"
    result = ["stash", subcommand, *selected]
    if text:
        if subcommand == "push":
            result += "-m"
        result.append(f'"{text}"' if ' ' in text else text)
    return result


class StashCommand(MyGitCommand):
    def run(self, _, options: List[str], message=""):
        if options[-1] == "stash":
            options = options[:-2]
        cmd = get_stash_cmd(options, message)
        self.git_run(cmd)

    def input_description(self):
        return "Stash"

    def input(self, args):
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
    }
    terminal = "stash"

    def tail(self, args):
        if "message" not in args:
            return StashMessageInputHandler(args["options"])


class StashMessageInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, selected: List[str]) -> None:
        self.selected = selected

    def name(self) -> str:
        return "message"

    def preview(self, text: str) -> str:
        return "Runs: git " + ' '.join(get_stash_cmd(self.selected, text))

    def placeholder(self) -> str:
        return "Optional Message"


class PopStashCommand(MyGitCommand):
    def run(self, edit):
        self.git_run(["stash", "pop"])


class DropStashesCommand(MyGitCommand):
    def run(self, edit):
        self.git_run(["stash", "drop"])


class ClearStashesCommand(MyGitCommand):
    def run(self, edit):
        msg = "This will permanently erase all stashes.\n\nAre you sure you want to continue ?"
        if sublime.ok_cancel_dialog(msg, "Clear All Stashes", "Confirm Clear Stashes"):
            self.git_run(["stash", "clear"])


class StageAllCommand(MyGitCommand):
    def run(self, edit):
        self.git_run(["add", "-A"])


class StageAllModifiedCommand(MyGitCommand):
    def run(self, edit):
        self.git_run(["add", "-u"])


class UnstageAllCommand(MyGitCommand):
    def run(self, edit):
        self.git_run(["reset"])


class FetchCommand(MyGitCommand):
    def run(self, _, mode: str, remote: str = ""):  # type: ignore
        cmd = mode.split()
        if remote:
            cmd.append(remote)
        self.git_run(cmd)

    def input_description(self):
        return "Fetch"

    def input(self, args):
        if not (root := self.git_root_setting()):
            return
        if "mode" not in args:
            return FetchModeInputHandler(root)
        if "remote" not in args and "--all" not in args["mode"]:
            return RemoteInputHandler(root)


class FetchModeInputHandler(sublime_plugin.ListInputHandler):
    modes = {
        "fetch":              "Fetch from a remote",
        "fetch --prune":      "Fetch and delete stale remote-tracking refs",
        "fetch --tags":       "Fetch all tags from a remote",
        "fetch --all":        "Fetch from all remotes",
        "fetch --all --prune":"Fetch from all remotes and delete stale remote-tracking refs",
        "fetch --all --tags": "Fetch all tags from all remotes",
    }

    def __init__(self, root: str) -> None:
        self.root = root

    def name(self) -> str:
        return "mode"

    def placeholder(self) -> str:
        return "Fetch Options"

    def list_items(self):
        return [
            sublime.ListInputItem(mode, mode, annotation=annotation)
            for mode, annotation in self.modes.items()
        ]

    def next_input(self, args):
        if "remote" not in args and "--all" not in args["mode"]:
            return RemoteInputHandler(self.root)


class PullCommand(MyGitCommand):
    def run(self, _, mode: str, remote: str = ""):  # type: ignore
        cmd = mode.split()
        if remote:
            cmd.append(remote)
        self.git_run(cmd)

    def input_description(self):
        return "Pull"

    def input(self, args):
        if not (root := self.git_root_setting()):
            return
        if "mode" not in args:
            return PullModeInputHandler(root)
        if "remote" not in args and "--all" not in args["mode"] and "pull" not in args["mode"]:
            return RemoteInputHandler(root)


class PullModeInputHandler(FetchModeInputHandler):
    modes = {
        "pull":                      "Pull from tracking remote",
        "pull --ff-only":            "Pull, fail if a merge commit would be created",
        "pull --rebase":             "Rebase local commits on top of fetched changes",
        "pull --rebase --autostash": "Rebase, automatically stashing and restoring local changes",
        **FetchModeInputHandler.modes,
    }

    def placeholder(self) -> str:
        return "Pull Options"

    def next_input(self, args):
        if "remote" not in args and "--all" not in args["mode"] and "pull" not in args["mode"]:
            return RemoteInputHandler(self.root)


class RebaseBranchCommand(MyGitCommand):
    def run(self, _, branch: str):  # type: ignore
        self.git_run(["rebase", path_to_name(branch)])

    def input_description(self):
        return "Rebase Branch"

    def input(self, args):
        if not (root := self.git_root_setting()):
            return
        if "branch" not in args:
            return RebaseBranchBranchInputHandler(root)


class RebaseBranchBranchInputHandler(BranchInputHandler):
    def __init__(self, root: str):
        super().__init__(root, local_refs=True, remote_refs=True)
        repo = pygit2.Repository(root)
        self.current = repo.head.shorthand if not repo.head_is_detached else str(repo.head.target)[:7]

    def placeholder(self) -> str:
        return "Branch Name"

    def preview(self, text: str) -> str:
        return f"Rebase {self.current} onto {path_to_name(text)}"

    def next_input(self, args):
        return None


class PushCommand(MyGitCommand):
    def run(self, _, branch: str, remote: str, mode: str, prompt=True):  # type: ignore
        if not (root := self.git_root_setting()):
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
        self.git_run(cmd)

    def input_description(self):
        return "Push"

    def input(self, args):
        if not (root := self.git_root_setting()):
            return
        if "branch" not in args:
            return PushBranchInputHandler(root, local_refs=True)
        if "remote" not in args:
            return PushRemoteInputHandler(root)
        if "mode" not in args:
            return PushModeInputHandler(is_upstream(root, args["remote"], args["branch"]))


class PushBranchInputHandler(BranchInputHandler):
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


class DeleteTagCommand(MyGitCommand):
    def run(self, edit, ref: str, prompt=True):  # type: ignore
        tag_name = path_to_name(ref)
        if prompt and sublime.ok_cancel_dialog(
            f"Delete tag {tag_name}?", "Delete", "Confirm Delete"
            ) != sublime.DIALOG_YES:
            return
        self.git_run(["tag", "-d", tag_name])

    def input_description(self) -> str:
        return "Delete Tag"

    def input(self, args):
        if not (root := self.git_root_setting()):
            return
        if "ref" not in args:
            return DeleteTagRefInputHandler(root, tag_refs=True)


class DeleteTagRefInputHandler(BranchInputHandler):
    def name(self):
        return "ref"

    def placeholder(self) -> str:
        return "Tag Name"


class DeleteTagOnRemoteCommand(MyGitCommand):
    def run(self, edit, ref: str, remote: str, prompt=True):  # type: ignore
        tag_name = path_to_name(ref)
        if prompt and sublime.ok_cancel_dialog(
            f"Delete tag {tag_name} on {remote}?", "Delete", "Confirm Delete"
        ) != sublime.DIALOG_YES:
            return
        self.git_run(["push", remote, "--delete", tag_name])

    def input_description(self) -> str:
        return "Delete Tag on Remote"

    def input(self, args):
        if not (root := self.git_root_setting()):
            return
        if "ref" not in args:
            return DeleteTagOnRemoteRefInputHandler(root, tag_refs=True)
        if "remote" not in args:
            return RemoteInputHandler(root)


class DeleteTagOnRemoteRefInputHandler(DeleteTagRefInputHandler):
    def next_input(self, args):
        if "remote" not in args:
            return RemoteInputHandler(self.root)


class PushTagCommand(MyGitCommand):
    def run(self, edit, ref: str, remote: str):  # type: ignore
        self.git_run(["push", remote, path_to_name(ref)])

    def input_description(self) -> str:
        return "Push Tag"

    def input(self, args):
        if not (root := self.git_root_setting()):
            return
        if "ref" not in args:
            return DeleteTagOnRemoteRefInputHandler(root, tag_refs=True)
        if "remote" not in args:
            return RemoteInputHandler(root)


class ApplyPatchCommand(MyGitCommand):
    def run(self, edit):
        def on_select(path: Optional[str]):
            if path is not None:
                self.git_run(["apply", path])

        sublime.open_dialog(
            on_select,
            file_types=[("Patch Files", ["patch", "diff"])],
        )


class SetUpstreamCommand(MyGitCommand):
    def run(self, edit, branch: str, upstream: str):  # type: ignore
        self.git_run(["branch", "--set-upstream-to", path_to_name(upstream), path_to_name(branch)])

    def input_description(self) -> str:
        return "Set Branch Upstream"

    def input(self, args):
        if not (root := self.git_root_setting()):
            return
        if "branch" not in args:
            return SetUpstreamBranchInputHandler(root, local_refs=True)
        if "upstream" not in args:
            return SetUpstreamUpstreamInputHandler(root, remote_refs=True)


class SetUpstreamBranchInputHandler(BranchInputHandler):
    def next_input(self, args):
        if "upstream" not in args:
            return SetUpstreamUpstreamInputHandler(self.root, remote_refs=True)


class SetUpstreamUpstreamInputHandler(BranchInputHandler):
    def name(self) -> str:
        return "upstream"


class UnsetUpstreamCommand(MyGitCommand):
    def run(self, edit, branch: str):  # type: ignore
        self.git_run(["branch", "--unset-upstream", path_to_name(branch)])

    def input_description(self) -> str:
        return "Unset Branch Upstream"

    def input(self, args):
        if not (root := self.git_root_setting()):
            return
        if "branch" not in args:
            return BranchInputHandler(root, local_refs=True)

# ── GitFlow ───────────────────────────────────────────────────────────────────

_GITFLOW_INIT_FIELDS = {
    "master":             ("Master Branch", "gitflow.branch.master", "master"),
    "develop":            ("Development Branch", "gitflow.branch.develop", "develop"),
    "feature_prefix":     ("Feature Branch Prefix", "gitflow.prefix.feature", "feature/"),
    "bugfix_prefix":      ("Bugfix Branch Prefix", "gitflow.prefix.bugfix", "bugfix/"),
    "release_prefix":     ("Release Branch Prefix", "gitflow.prefix.release", "release/"),
    "hotfix_prefix":      ("Hotfix Branch Prefix", "gitflow.prefix.hotfix", "hotfix/"),
    "support_prefix":     ("Support Branch Prefix", "gitflow.prefix.support", "support/"),
    "version_tag_prefix": ("Version Tag Prefix", "gitflow.prefix.versiontag", ""),
    "hooks_path":         ("Git Hooks Path", "gitflow.path.hooks", ".git/hooks"),
}

def _gitflow_is_initialized(root: str) -> bool:
    try:
        return "gitflow.branch.master" in pygit2.Repository(root).config
    except pygit2.GitError:
        return False


def _gitflow_current_configs(root: str) -> Dict[str, str]:
    try:
        repo_config = pygit2.Repository(root).config
        return {
            key: repo_config[config_key] if config_key in repo_config else default
            for key, (_, config_key, default) in _GITFLOW_INIT_FIELDS.items()
        }
    except pygit2.GitError:
        return {key: default for key, (_, _, default) in _GITFLOW_INIT_FIELDS.items()}


class GitflowConfigCommandBase(MyGitCommand):
    def _apply_configs(self, configs: dict):
        for key, (_, config_key, _) in _GITFLOW_INIT_FIELDS.items():
            self.git_run(["config", config_key, configs[key]])

    def input(self, args):
        if not (root := self.git_root_setting()):
            return
        if isinstance(args.get("configs"), dict):
            configs = args.get("configs")
        else:
            configs = _gitflow_current_configs(root)
        return GitflowConfigsInputHandler(configs, self.name())


class InitGitflowCommand(GitflowConfigCommandBase):
    def run(self, edit, configs):  # type: ignore
        if not isinstance(configs, dict):
            return
        self._apply_configs(configs)
        self.git_run(["checkout", "-b", configs["master"], f"origin/{configs['master']}"])
        self.git_run(["checkout", "-b", configs["develop"], configs["master"]])

    def is_enabled(self):
        if not (root := self.git_root_setting()):
            return False
        return not _gitflow_is_initialized(root)

    def input_description(self):
        return "Initialize Git Flow"


class EditGitflowConfigCommand(GitflowConfigCommandBase):
    def run(self, edit, configs):  # type: ignore
        if not isinstance(configs, dict):
            return
        self._apply_configs(configs)

    def is_enabled(self):
        if not (root := self.git_root_setting()):
            return False
        return _gitflow_is_initialized(root)

    def input_description(self):
        return "Configure Git Flow"


class GitflowConfigsInputHandler(sublime_plugin.ListInputHandler):
    def __init__(self, configs: Dict[str, str], command_name: str):
        self.configs = configs
        self.command_name = command_name

    def name(self):
        return "configs"

    def placeholder(self):
        return "Edit Git Flow Configuration"

    def list_items(self):
        return [
            sublime.ListInputItem(
                "Initialize" if "init" in self.command_name else "Update",
                self.configs,
                annotation="Runs git config commands",
            ),
            *(
                sublime.ListInputItem(
                    label,
                    key,
                    annotation=self.configs[key],
                )
                for key, (label, _, _) in _GITFLOW_INIT_FIELDS.items()
            ),
        ]

    def next_input(self, args):
        if isinstance(args["configs"], dict):
            return None
        return GitflowEditValueInputHandler(args["configs"], self.configs, self.command_name)


class GitflowEditValueInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, key: str, configs: Dict[str, str], command_name: str):
        self.key = key
        self.configs = configs
        self.command_name = command_name

    def name(self):
        return "configs"

    def placeholder(self):
        return _GITFLOW_INIT_FIELDS[self.key][0]

    def initial_text(self):
        return self.configs[self.key]

    def initial_selection(self):
        return [(0, len(self.configs[self.key]))]

    def preview(self, text: str):
        return f"Set {_GITFLOW_INIT_FIELDS[self.key][0]} to: {text}"

    def validate(self, text: str, event=None):
        return len(text) != 0 or self.key == "version_tag_prefix"

    def confirm(self, value: str, event=None):
        updated = {**self.configs, self.key: value}
        sublime.set_timeout(lambda: sublime.active_window().run_command(
            "show_overlay",
            {
                "overlay": "command_palette",
                "command": self.command_name,
                "args": {"configs": updated},
            }
        ))


class GitflowStartNameInputHandler(sublime_plugin.TextInputHandler):
    def name(self):
        return "name"

    def placeholder(self):
        return "Branch Name"

    def validate(self, text: str, event=None):
        return len(text) != 0


class GitflowStartCommand(MyGitCommand):
    flow_type: str

    def run(self, edit, name: str):  # type: ignore
        self.git_run(["flow", self.flow_type, "start", name])

    def input_description(self):
        return f"Gitflow: Start {self.flow_type.capitalize()}"

    def input(self, args):
        if "name" not in args:
            return GitflowStartNameInputHandler()


class GitflowSimpleCommand(MyGitCommand):
    flow_type: str
    flow_action: str

    def run(self, edit):  # type: ignore
        self.git_run(["flow", self.flow_type, self.flow_action])


# start

class GitflowStartBugfixCommand(GitflowStartCommand):
    flow_type = "bugfix"

class GitflowStartFeatureCommand(GitflowStartCommand):
    flow_type = "feature"

class GitflowStartHotfixCommand(GitflowStartCommand):
    flow_type = "hotfix"

class GitflowStartReleaseCommand(GitflowStartCommand):
    flow_type = "release"

class GitflowStartSupportCommand(GitflowStartCommand):
    flow_type = "support"

# finish

class GitflowFinishBugfixCommand(GitflowSimpleCommand):
    flow_type = "bugfix"
    flow_action = "finish"

class GitflowFinishFeatureCommand(GitflowSimpleCommand):
    flow_type = "feature"
    flow_action = "finish"

class GitflowFinishHotfixCommand(GitflowSimpleCommand):
    flow_type = "hotfix"
    flow_action = "finish"

class GitflowFinishReleaseCommand(GitflowSimpleCommand):
    flow_type = "release"
    flow_action = "finish"

# publish

class GitflowPublishBugfixCommand(GitflowSimpleCommand):
    flow_type = "bugfix"
    flow_action = "publish"

class GitflowPublishFeatureCommand(GitflowSimpleCommand):
    flow_type = "feature"
    flow_action = "publish"

class GitflowPublishHotfixCommand(GitflowSimpleCommand):
    flow_type = "hotfix"
    flow_action = "publish"

class GitflowPublishReleaseCommand(GitflowSimpleCommand):
    flow_type = "release"
    flow_action = "publish"

# rebase

class GitflowRebaseBugfixCommand(GitflowSimpleCommand):
    flow_type = "bugfix"
    flow_action = "rebase"

class GitflowRebaseFeatureCommand(GitflowSimpleCommand):
    flow_type = "feature"
    flow_action = "rebase"

class GitflowRebaseHotfixCommand(GitflowSimpleCommand):
    flow_type = "hotfix"
    flow_action = "rebase"

class GitflowRebaseReleaseCommand(GitflowSimpleCommand):
    flow_type = "release"
    flow_action = "rebase"

class GitflowRebaseSupportCommand(GitflowSimpleCommand):
    flow_type = "support"
    flow_action = "rebase"
