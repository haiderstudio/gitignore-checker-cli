"""Tests for gitignore_checker — standard library unittest only."""

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import gitignore_checker  # noqa: E402


def write(tmp, name, text, encoding="utf-8"):
    path = Path(tmp) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)
    return path


def run_cli(*args, cwd=None):
    argv = [sys.executable, str(SRC / "gitignore_checker.py"), *args]
    return subprocess.run(
        argv, capture_output=True, text=True, cwd=cwd or ROOT
    )


def make_repo(tmp, gitignore, files, tracked):
    """Build a small repo folder: .gitignore text, files on disk
    (name -> text), and a tracked list. Returns the repo path."""
    repo = Path(tmp) / "repo"
    repo.mkdir()
    if gitignore is not None:
        (repo / ".gitignore").write_text(gitignore)
    for name, text in files.items():
        write(repo, name, text)
    tracked_path = repo / "tracked.txt"
    tracked_path.write_text("\n".join(tracked) + "\n")
    return repo


class TestPattern(unittest.TestCase):
    def matches(self, raw, path, is_dir=False):
        return gitignore_checker.Pattern(1, raw).matches(path, is_dir)

    def test_star_matches_any_depth(self):
        self.assertTrue(self.matches("*.log", "a.log"))
        self.assertTrue(self.matches("*.log", "src/a.log"))
        self.assertFalse(self.matches("*.log", "a.txt"))
        self.assertFalse(self.matches("*.log", "a.log.txt"))

    def test_question_mark(self):
        self.assertTrue(self.matches("?.txt", "a.txt"))
        self.assertFalse(self.matches("?.txt", "ab.txt"))

    def test_character_class(self):
        self.assertTrue(self.matches("[abc].txt", "a.txt"))
        self.assertTrue(self.matches("[abc].txt", "c.txt"))
        self.assertFalse(self.matches("[abc].txt", "d.txt"))
        self.assertTrue(self.matches("[!abc].txt", "d.txt"))

    def test_double_star_any_depth(self):
        self.assertTrue(self.matches("**/foo", "foo"))
        self.assertTrue(self.matches("**/foo", "a/foo"))
        self.assertTrue(self.matches("**/foo", "a/b/foo"))
        self.assertFalse(self.matches("**/foo", "a/foobar"))

    def test_double_star_middle(self):
        self.assertTrue(self.matches("a/**/b", "a/b"))
        self.assertTrue(self.matches("a/**/b", "a/x/b"))
        self.assertTrue(self.matches("a/**/b", "a/x/y/b"))
        self.assertFalse(self.matches("a/**/b", "x/a/b"))

    def test_double_star_end(self):
        self.assertTrue(self.matches("docs/**", "docs/a.txt"))
        self.assertTrue(self.matches("docs/**", "docs/a/b.txt"))
        self.assertFalse(self.matches("docs/**", "other/a.txt"))

    def test_anchored_leading_slash(self):
        self.assertTrue(self.matches("/root.txt", "root.txt"))
        self.assertFalse(self.matches("/root.txt", "sub/root.txt"))

    def test_anchored_with_slash(self):
        self.assertTrue(self.matches("docs/*.txt", "docs/a.txt"))
        self.assertFalse(self.matches("docs/*.txt", "docs/sub/a.txt"))
        self.assertFalse(self.matches("docs/*.txt", "x/docs/a.txt"))

    def test_dir_pattern_matches_inside(self):
        self.assertTrue(self.matches("build/", "build/out.o", True))
        self.assertTrue(self.matches("build/", "build/out.o", False))
        self.assertTrue(self.matches("build/", "src/build/out.o"))
        self.assertFalse(self.matches("build/", "rebuild/out.o"))

    def test_dir_pattern_ignores_dir_itself(self):
        self.assertTrue(self.matches("build/", "build", True))
        self.assertFalse(self.matches("build/", "build", False))

    def test_dir_pattern_does_not_match_plain_file(self):
        # A file named "logs" is not a folder, so "logs/" does not
        # ignore it.
        self.assertFalse(self.matches("logs/", "logs", False))

    def test_star_star_alone(self):
        self.assertTrue(self.matches("**", "anything/at/all.txt"))

    def test_escaped_hash(self):
        self.assertTrue(self.matches("\\#file", "#file"))
        self.assertFalse(self.matches("\\#file", "file"))


class TestParseGitignore(unittest.TestCase):
    def test_comments_and_blanks_skipped(self):
        patterns = gitignore_checker.parse_gitignore(
            "# a comment\n\n*.log\n"
        )
        self.assertEqual([p.raw for p in patterns], ["*.log"])
        self.assertEqual(patterns[0].lineno, 3)

    def test_trailing_space_ignored(self):
        patterns = gitignore_checker.parse_gitignore("*.log \n")
        self.assertEqual(patterns[0].raw, "*.log")

    def test_negation_flag(self):
        patterns = gitignore_checker.parse_gitignore("*.log\n!keep.log\n")
        self.assertFalse(patterns[0].negated)
        self.assertTrue(patterns[1].negated)


class TestIsIgnored(unittest.TestCase):
    def test_last_match_wins(self):
        patterns = gitignore_checker.parse_gitignore(
            "*.log\n!keep.log\n"
        )
        self.assertFalse(gitignore_checker.is_ignored(patterns, "keep.log"))
        self.assertTrue(gitignore_checker.is_ignored(patterns, "a.log"))

    def test_negation_then_reignore(self):
        patterns = gitignore_checker.parse_gitignore(
            "*.log\n!keep.log\nkeep.log\n"
        )
        self.assertTrue(gitignore_checker.is_ignored(patterns, "keep.log"))

    def test_no_match(self):
        patterns = gitignore_checker.parse_gitignore("*.log\n")
        self.assertFalse(gitignore_checker.is_ignored(patterns, "a.py"))


class TestCheckRepo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def check(self, gitignore, files, tracked, allow_unused=False):
        repo = make_repo(self.tmp.name, gitignore, files, tracked)
        return gitignore_checker.check_repo(
            repo, repo / ".gitignore", tracked, allow_unused
        )

    def test_clean_repo(self):
        checked, problems = self.check(
            "*.log\nbuild/\n",
            {"app.py": "x\n", "notes.log": "x\n",
             "build/output.txt": "x\n"},
            ["app.py"],
        )
        self.assertEqual((checked, problems), (1, []))

    def test_tracked_ignored_file(self):
        checked, problems = self.check(
            "*.log\nsecrets.txt\n",
            {"app.py": "x\n"},
            ["app.py", "secrets.txt", "app.log"],
        )
        self.assertEqual(checked, 3)
        self.assertEqual(len(problems), 2)
        self.assertIn(
            "secrets.txt: tracked but ignored by .gitignore line 2: "
            "secrets.txt",
            problems,
        )
        self.assertIn(
            "app.log: tracked but ignored by .gitignore line 1: *.log",
            problems,
        )

    def test_unused_pattern(self):
        checked, problems = self.check(
            "*.log\n*.tmp\n",
            {"app.py": "x\n", "notes.log": "x\n"},
            ["app.py"],
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("pattern '*.tmp' matches nothing", problems[0])
        self.assertIn(":2:", problems[0])

    def test_allow_unused_silences_it(self):
        checked, problems = self.check(
            "*.log\n*.tmp\n",
            {"app.py": "x\n", "notes.log": "x\n"},
            ["app.py"],
            allow_unused=True,
        )
        self.assertEqual(problems, [])

    def test_pattern_used_by_disk_file_only(self):
        # A pattern matching an untracked file on disk is used, not
        # dead weight.
        checked, problems = self.check(
            "*.log\n",
            {"app.py": "x\n", "notes.log": "x\n"},
            ["app.py"],
        )
        self.assertEqual(problems, [])

    def test_negated_pattern_never_unused(self):
        checked, problems = self.check(
            "*.log\n!keep.log\n",
            {"app.py": "x\n", "notes.log": "x\n"},
            ["app.py"],
        )
        self.assertEqual(problems, [])

    def test_negated_tracked_file_is_clean(self):
        checked, problems = self.check(
            "*.log\n!keep.log\n",
            {"app.py": "x\n", "keep.log": "x\n", "notes.log": "x\n"},
            ["app.py", "keep.log"],
        )
        self.assertEqual(problems, [])

    def test_non_utf8_gitignore(self):
        repo = Path(self.tmp.name) / "repo"
        repo.mkdir()
        (repo / ".gitignore").write_bytes(b"\xff\xfe bad\n")
        checked, problems = gitignore_checker.check_repo(
            repo, repo / ".gitignore", ["app.py"], False
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("not valid UTF-8", problems[0])

    def test_missing_gitignore_file(self):
        repo = Path(self.tmp.name) / "repo"
        repo.mkdir()
        checked, problems = gitignore_checker.check_repo(
            repo, repo / ".gitignore", ["app.py"], False
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("No such file", problems[0])


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def repo(self, gitignore, files, tracked):
        return make_repo(self.tmp.name, gitignore, files, tracked)

    def test_clean_exit_zero(self):
        repo = self.repo(
            "*.log\nbuild/\n",
            {"app.py": "x\n", "notes.log": "x\n",
             "build/output.txt": "x\n"},
            ["app.py"],
        )
        result = run_cli(str(repo), "--tracked", str(repo / "tracked.txt"))
        self.assertEqual(result.returncode, 0)
        self.assertIn(
            "OK — 1 tracked file(s) checked, .gitignore matches.",
            result.stdout,
        )

    def test_bad_exit_one(self):
        repo = self.repo(
            "*.log\nsecrets.txt\n*.tmp\n",
            {"app.py": "x\n"},
            ["app.py", "secrets.txt", "app.log"],
        )
        result = run_cli(str(repo), "--tracked", str(repo / "tracked.txt"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL secrets.txt:", result.stdout)
        self.assertIn("FAIL app.log:", result.stdout)
        self.assertIn("matches nothing", result.stdout)
        self.assertIn(
            "Checked 3 tracked file(s), 3 problem(s).", result.stdout
        )

    def test_allow_unused_flag(self):
        repo = self.repo(
            "*.log\nsecrets.txt\n*.tmp\n",
            {"app.py": "x\n"},
            ["app.py", "secrets.txt", "app.log"],
        )
        result = run_cli(
            str(repo),
            "--tracked", str(repo / "tracked.txt"),
            "--allow-unused",
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("matches nothing", result.stdout)
        self.assertIn(
            "Checked 3 tracked file(s), 2 problem(s).", result.stdout
        )

    def test_missing_gitignore(self):
        repo = Path(self.tmp.name) / "repo"
        repo.mkdir()
        write(repo, "app.py", "x\n")
        write(repo, "tracked.txt", "app.py\n")
        result = run_cli(
            str(repo), "--tracked", str(repo / "tracked.txt")
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("no .gitignore file", result.stdout)
        self.assertIn(
            "Checked 1 tracked file(s), 1 problem(s).", result.stdout
        )

    def test_missing_folder(self):
        result = run_cli(str(Path(self.tmp.name) / "nope"))
        self.assertEqual(result.returncode, 2)

    def test_missing_tracked_list(self):
        repo = self.repo("*.log\n", {"app.py": "x\n"}, ["app.py"])
        result = run_cli(str(repo), "--tracked", str(repo / "nope.txt"))
        self.assertEqual(result.returncode, 2)

    def test_not_a_git_repo_without_tracked(self):
        repo = self.repo("*.log\n", {"app.py": "x\n"}, ["app.py"])
        result = run_cli(str(repo))
        self.assertEqual(result.returncode, 2)
        self.assertIn("--tracked", result.stderr)

    def test_bad_flag(self):
        result = run_cli("--nope")
        self.assertEqual(result.returncode, 2)

    def test_version(self):
        result = run_cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn("1.0.0", result.stdout)

    def test_json_output(self):
        repo = self.repo(
            "*.log\nsecrets.txt\n",
            {"app.py": "x\n", "notes.log": "x\n"},
            ["app.py", "secrets.txt"],
        )
        result = run_cli(
            str(repo), "--tracked", str(repo / "tracked.txt"), "--json"
        )
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["tracked"], 2)
        self.assertEqual(len(payload["problems"]), 1)
        self.assertIn("secrets.txt", payload["problems"][0])
        self.assertEqual(
            payload["summary"], {"checked": 2, "problems": 1}
        )
        self.assertIn("1 problem(s)", result.stderr)

    def test_json_clean(self):
        repo = self.repo(
            "*.log\n",
            {"app.py": "x\n", "notes.log": "x\n"},
            ["app.py"],
        )
        result = run_cli(
            str(repo), "--tracked", str(repo / "tracked.txt"), "--json"
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["problems"], [])

    def test_input_files_unchanged(self):
        repo = self.repo(
            "*.log\nsecrets.txt\n",
            {"app.py": "x\n"},
            ["app.py", "secrets.txt"],
        )
        before = (repo / ".gitignore").read_bytes()
        run_cli(str(repo), "--tracked", str(repo / "tracked.txt"))
        self.assertEqual((repo / ".gitignore").read_bytes(), before)

    def test_git_mode(self):
        import shutil

        if shutil.which("git") is None:
            self.skipTest("git is not installed")
        repo = Path(self.tmp.name) / "gitrepo"
        repo.mkdir()
        (repo / ".gitignore").write_text("*.log\nsecrets.txt\n")
        (repo / "app.py").write_text("x\n")
        (repo / "secrets.txt").write_text("x\n")
        # Untracked on disk, so "*.log" counts as used.
        (repo / "notes.log").write_text("x\n")
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        subprocess.run(["git", "init", "-q"], cwd=repo, env=env,
                       check=True)
        subprocess.run(["git", "add", "."], cwd=repo, env=env,
                       check=True)
        # An ignored file only becomes tracked if it was added
        # before the pattern existed, or forced in — that is the
        # mistake this tool catches.
        subprocess.run(["git", "add", "-f", "secrets.txt"], cwd=repo,
                       env=env, check=True)
        result = run_cli(str(repo))
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL secrets.txt:", result.stdout)
        self.assertIn(
            "Checked 3 tracked file(s), 1 problem(s).", result.stdout
        )


class TestExamples(unittest.TestCase):
    def test_sample_output_matches_fresh_run(self):
        result = subprocess.run(
            ["sh", "examples/run-example.sh"],
            capture_output=True, text=True, cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0)
        expected = (ROOT / "examples" / "sample-output.txt").read_text()
        self.assertEqual(result.stdout, expected)

    def test_readme_quotes_match_real_runs(self):
        readme = (ROOT / "README.md").read_text()
        clean = run_cli(
            "examples/clean-repo",
            "--tracked", "examples/clean-repo/tracked.txt",
        )
        self.assertEqual(clean.returncode, 0)
        for line in clean.stdout.strip().splitlines():
            self.assertIn(line, readme)
        bad = run_cli(
            "examples/bad-repo",
            "--tracked", "examples/bad-repo/tracked.txt",
        )
        self.assertEqual(bad.returncode, 1)
        for line in bad.stdout.strip().splitlines():
            self.assertIn(line, readme)
        missing = run_cli(
            "examples/no-gitignore-repo",
            "--tracked", "examples/no-gitignore-repo/tracked.txt",
        )
        self.assertEqual(missing.returncode, 1)
        for line in missing.stdout.strip().splitlines():
            self.assertIn(line, readme)


class TestHygiene(unittest.TestCase):
    def test_stdlib_only(self):
        allowed = {
            "argparse", "json", "os", "re", "subprocess", "sys",
            "pathlib",
        }
        test_allowed = allowed | {
            "ast", "shutil", "tempfile", "unittest", "gitignore_checker",
        }
        for path, names in [
            (SRC / "gitignore_checker.py", allowed),
            (HERE / "test_gitignore_checker.py", test_allowed),
        ]:
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertIn(alias.name.split(".")[0], names)
                elif isinstance(node, ast.ImportFrom):
                    self.assertIn(node.module.split(".")[0], names)

    def test_no_placeholder_or_secrets(self):
        banned = ["TODO", "FIXME", "coming soon", "lorem",
                  "API_KEY", "api_key", "password="]
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if HERE in path.parents:
                continue  # the test file's own word lists
            if path.suffix == ".pyc":
                continue
            text = path.read_text(errors="ignore")
            for word in banned:
                self.assertNotIn(
                    word, text, f"{word} found in {path}"
                )

    def test_no_absolute_paths(self):
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if HERE in path.parents:
                continue  # the test file's own word lists
            if path.suffix in {".pyc", ".log"}:
                continue
            text = path.read_text(errors="ignore")
            self.assertNotIn("/home/", text, f"absolute path in {path}")
            self.assertNotIn("/tmp/", text, f"absolute path in {path}")

    def test_gitignore_has_env_first(self):
        lines = (ROOT / ".gitignore").read_text().splitlines()
        self.assertEqual(lines[0], ".env")

    def test_fake_git_hooks_todo_does_not_break_scan(self):
        # The Day 21 lesson: a scan that walks .git hits GitHub's own
        # sample hooks containing "TODO". Our scans exclude .git.
        with tempfile.TemporaryDirectory() as tmp:
            hooks = Path(tmp) / ".git" / "hooks"
            hooks.mkdir(parents=True)
            (hooks / "sendemail-validate.sample").write_text(
                "# TODO: fix this\n"
            )
            found = []
            for path in Path(tmp).rglob("*"):
                if not path.is_file():
                    continue
                if ".git" in path.parts or "__pycache__" in path.parts:
                    continue
                if "TODO" in path.read_text(errors="ignore"):
                    found.append(path)
            self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
