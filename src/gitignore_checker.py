"""Check a repo's .gitignore matches the files it tracks.

Reads a repo's .gitignore and its tracked files (from `git ls-files`,
or from a plain list with `--tracked FILE`) and checks two things:

- every tracked file must NOT match an ignore pattern — a tracked
  `.env` or `__pycache__` file is a mistake that ships secrets or junk;
- every ignore pattern must match at least one tracked file or one
  file on disk — a pattern that matches nothing is dead weight
  (silence that check with `--allow-unused`).

Every problem names the file and the .gitignore line; exits 1 on
any problem, so it can fail a CI run, and 0 when the .gitignore
matches. Report-only: it never rewrites .gitignore and never
untracks a file. Standard library only — no packages to install.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

VERSION = "1.0.0"


class Pattern:
    """One .gitignore line, translated into a match rule."""

    def __init__(self, lineno, raw):
        self.lineno = lineno
        self.raw = raw
        body = raw[1:] if raw.startswith("!") else raw
        self.negated = raw.startswith("!")
        self.dir_only = body.endswith("/")
        if self.dir_only:
            body = body[:-1]
        self.regex, self.anchored = _translate(body)

    def matches(self, rel_path, is_dir=False):
        """True if this pattern matches a path relative to the repo
        root. `is_dir` says whether the path itself is a folder;
        every parent folder in the path is a folder by definition."""
        parts = rel_path.split("/")
        targets = [(rel_path, is_dir)]
        for index in range(1, len(parts)):
            targets.append(("/".join(parts[:index]), True))
        for target, target_is_dir in targets:
            if self.dir_only and not target_is_dir:
                continue
            if self.anchored:
                if re.fullmatch(self.regex, target):
                    return True
            else:
                name = target.rsplit("/", 1)[-1]
                if re.fullmatch(self.regex, name):
                    return True
        return False


def _translate(pattern):
    """Translate a gitignore glob into (regex, anchored).

    `*` matches anything except `/`, `?` one character except `/`,
    `**` matches across folders, `[...]` is a character class, and a
    backslash escapes the next character. A pattern with a `/` in it
    (or a leading `/`) is anchored to the repo root; one without
    matches the file or folder name at any depth.
    """
    anchored = pattern.startswith("/")
    if anchored:
        pattern = pattern[1:]
    if "/" in pattern:
        anchored = True
    out = []
    index = 0
    size = len(pattern)
    while index < size:
        char = pattern[index]
        if char == "*":
            if index + 1 < size and pattern[index + 1] == "*":
                if index + 2 < size and pattern[index + 2] == "/":
                    out.append("(?:.*/)?")
                    index += 3
                else:
                    out.append(".*")
                    index += 2
            else:
                out.append("[^/]*")
                index += 1
        elif char == "?":
            out.append("[^/]")
            index += 1
        elif char == "[":
            end = index + 1
            if end < size and pattern[end] in "!^":
                end += 1
            if end < size and pattern[end] == "]":
                end += 1
            while end < size and pattern[end] != "]":
                end += 1
            if end >= size:
                out.append("\\[")
                index += 1
            else:
                stuff = pattern[index + 1:end]
                if stuff.startswith("!"):
                    stuff = "^" + stuff[1:]
                out.append("[" + stuff + "]")
                index = end + 1
        elif char == "\\" and index + 1 < size:
            out.append(re.escape(pattern[index + 1]))
            index += 2
        else:
            out.append(re.escape(char))
            index += 1
    return "".join(out), anchored


def parse_gitignore(text):
    """Turn .gitignore text into a list of Patterns.

    Blank lines and `#` comments are skipped; a trailing space is
    ignored unless it is escaped with a backslash.
    """
    patterns = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.endswith(" ") and not line.endswith("\\ "):
            line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        patterns.append(Pattern(lineno, line))
    return patterns


def is_ignored(patterns, rel_path):
    """True if the last pattern matching a path is not a negation."""
    ignored = False
    for pattern in patterns:
        if pattern.matches(rel_path):
            ignored = not pattern.negated
    return ignored


def last_matching(patterns, rel_path):
    """The last pattern that matches a path, or None."""
    found = None
    for pattern in patterns:
        if pattern.matches(rel_path):
            found = pattern
    return found


def tracked_via_git(repo):
    """Tracked files from `git ls-files`, or (None, error)."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return None, str(exc)
    if result.returncode != 0:
        return None, result.stderr.strip() or "git ls-files failed"
    return [line for line in result.stdout.splitlines() if line], None


def walk_tree(repo):
    """Every file and folder under a repo, as (rel path, is_dir).

    `.git` is never walked.
    """
    found = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [name for name in dirs if name != ".git"]
        for name in sorted(dirs):
            rel = Path(root, name).relative_to(repo).as_posix()
            found.append((rel, True))
        for name in sorted(files):
            rel = Path(root, name).relative_to(repo).as_posix()
            found.append((rel, False))
    return found


def check_repo(repo, gitignore_path, tracked, allow_unused):
    """Check one repo. Returns (tracked count, problem strings)."""
    problems = []
    try:
        text = gitignore_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return len(tracked), [f"{gitignore_path}: file is not valid UTF-8"]
    except OSError as exc:
        return len(tracked), [
            f"{gitignore_path}: {exc.strerror or exc}"
        ]
    patterns = parse_gitignore(text)
    for path in tracked:
        if is_ignored(patterns, path):
            pattern = last_matching(patterns, path)
            problems.append(
                f"{path}: tracked but ignored by .gitignore "
                f"line {pattern.lineno}: {pattern.raw}"
            )
    if not allow_unused:
        on_disk = walk_tree(repo)
        for pattern in patterns:
            if pattern.negated:
                continue
            used = any(
                pattern.matches(path) for path in tracked
            ) or any(
                pattern.matches(path, is_dir)
                for path, is_dir in on_disk
            )
            if not used:
                problems.append(
                    f"{gitignore_path}:{pattern.lineno}: pattern "
                    f"{pattern.raw!r} matches nothing"
                )
    return len(tracked), problems


def run(argv=None):
    """Run the checker. Returns an exit code: 0 clean, 1 problems,
    2 usage error."""
    parser = argparse.ArgumentParser(
        prog="gitignore_checker",
        description="Check .gitignore matches the files a repo tracks.",
    )
    parser.add_argument(
        "repo",
        nargs="?",
        default=".",
        help="repo folder to check (default: the current folder)",
    )
    parser.add_argument(
        "--gitignore",
        default=None,
        metavar="FILE",
        help=".gitignore to read (default: <repo>/.gitignore)",
    )
    parser.add_argument(
        "--tracked",
        default=None,
        metavar="FILE",
        help="file listing tracked paths, one per line "
        "(default: read them with git ls-files)",
    )
    parser.add_argument(
        "--allow-unused",
        action="store_true",
        help="do not fail on patterns that match nothing",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the result as JSON instead of plain text",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {VERSION}"
    )
    args = parser.parse_args(argv)
    repo = Path(args.repo)
    if not repo.is_dir():
        parser.error(f"{args.repo}: no such folder")
    gitignore_path = (
        Path(args.gitignore) if args.gitignore else repo / ".gitignore"
    )
    if args.tracked:
        try:
            tracked = [
                line.strip()
                for line in Path(args.tracked).read_text(
                    encoding="utf-8"
                ).splitlines()
                if line.strip()
            ]
        except OSError as exc:
            parser.error(
                f"cannot read tracked list {args.tracked}: "
                f"{exc.strerror or exc}"
            )
        except UnicodeDecodeError:
            parser.error(f"{args.tracked}: file is not valid UTF-8")
    else:
        tracked, error = tracked_via_git(repo)
        if tracked is None:
            parser.error(
                f"could not list tracked files ({error}) — "
                "not a git repo? pass --tracked FILE"
            )
    if not gitignore_path.is_file():
        problems = [f"{repo}: no .gitignore file"]
        checked = len(tracked)
    else:
        checked, problems = check_repo(
            repo, gitignore_path, tracked, args.allow_unused
        )
    if args.json:
        payload = {
            "repo": str(repo),
            "tracked": checked,
            "problems": problems,
            "summary": {
                "checked": checked,
                "problems": len(problems),
            },
        }
        print(json.dumps(payload, indent=2))
        print(
            f"Checked {checked} tracked file(s), "
            f"{len(problems)} problem(s).",
            file=sys.stderr,
        )
    else:
        for problem in problems:
            print(f"FAIL {problem}")
        if problems:
            print(
                f"Checked {checked} tracked file(s), "
                f"{len(problems)} problem(s)."
            )
        else:
            print(
                f"OK — {checked} tracked file(s) checked, "
                ".gitignore matches."
            )
    return 1 if problems else 0


def main(argv=None):
    try:
        return run(argv)
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
