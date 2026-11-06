# gitignore-checker-cli

Check .gitignore matches the files a repo tracks, fail CI on a mismatch.

[![CI](https://github.com/haiderstudio/gitignore-checker-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/gitignore-checker-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`gitignore_checker` reads a repo's `.gitignore` and its tracked
files, and checks that the two agree:

- every tracked file must NOT match an ignore pattern. A `.env`,
  a `secrets.txt`, or a `__pycache__` folder that got committed by
  mistake is reported with the file name and the `.gitignore`
  line that ignores it.
- every ignore pattern must match at least one tracked file or one
  file on disk. A pattern that matches nothing is dead weight and
  is reported with its line number. `--allow-unused` silences that
  check — use it if you keep patterns for files that do not exist
  yet.
- a repo with no `.gitignore` file at all is reported as a
  problem, not skipped silently.

It exits 1 on any problem, so it can fail a CI run before a secret
or a junk file ships in a commit, and 0 when the `.gitignore`
matches.

- Tracked files come from `git ls-files` by default. `--tracked
  FILE` reads them from a plain list instead, one path per line —
  handy for a repo that is not a git checkout, or for testing.
- `--gitignore FILE` reads a different ignore file than
  `<repo>/.gitignore`.
- `--json` prints the result as JSON instead of plain text, for
  scripts. The summary line goes to standard error, so standard
  output stays clean JSON.
- Ignore patterns follow the git rules: `*` matches anything
  except `/`, `?` matches one character, `**` matches across
  folders, `[...]` is a character class, a trailing `/` means
  folders only, a pattern with a `/` in it is anchored to the repo
  root, and `!` negates a pattern. The last matching pattern wins,
  so `!keep.log` after `*.log` keeps that one file tracked.

## What it does NOT do

- It does not rewrite `.gitignore` and it never untracks a file.
  A tracked-but-ignored file is reported, not removed.
- It does not check that a repo HAS the patterns it needs — it
  checks the patterns that are there against what is tracked.
  Checking `.gitignore` content against a fixed template is the
  job of
  [repo-hygiene-checker-cli](https://github.com/haiderstudio/repo-hygiene-checker-cli).
- It reads only the `.gitignore` at the repo root. Nested
  `.gitignore` files, `.git/info/exclude`, and the global gitignore
  are not read.
- It does not model git's rule that a file cannot be re-included
  if its parent folder is excluded — `!build/keep.txt` after
  `build/` counts as not ignored here (last match wins), while git
  itself would still ignore it.
- It does not fetch anything from the network. Every input is a
  local folder or file.

## Who it is for

Anyone who keeps a `.gitignore` and wants a quick, scriptable
check that it matches reality: a developer adding a CI step that
fails the build when a secret or a build folder slips into git, or
anyone tidying a repo before a first push. If the ignore file
matches, you get a plain OK line; if it does not, the report says
exactly which file and which line broke.

## How this differs from similar tools

`.gitignore` checkers already exist, but none of them is this
exact tool. The exact name `gitignore-checker-cli` matches 0
repositories on GitHub. The unquoted search `gitignore checker`
returns 19 results. The top ones are libraries that answer "is
this path ignored?": thehanimo/py-gitignore (10 stars, Python) is
a gitignore parser and checker library, inmarelibero/gitignore-checker
(5 stars, PHP) is a library to check if a given path is ignored
by git, and kvn-dtrx/gitignore-checker (0 stars) is a
reimplementation of git's ignoring mechanism. None of them audits
a repo's tracked files against its own `.gitignore`. The closest
overlap is kriskimmerle/gitignore-check (0 stars, Python), a
"smart .gitignore validator" that auto-detects the project type,
finds missing patterns, and spots tracked files that should be
ignored — broader than this slice, because it also judges which
patterns a project ought to have. This tool does a narrower job:
a Python standard-library-only CLI that checks the tracked files
against the ignore file that is already there, reports unused
patterns and a missing `.gitignore`, and exits 1 on a mismatch
for CI — no install beyond Python, no project-type guessing, no
network.

## Install

Python standard library only — no packages to download. You need
Python 3.8 or newer. Clone the repo and run it in place:

```
git clone https://github.com/haiderstudio/gitignore-checker-cli.git
cd gitignore-checker-cli
python3 src/gitignore_checker.py examples/clean-repo --tracked examples/clean-repo/tracked.txt
```

```
OK — 2 tracked file(s) checked, .gitignore matches.
```

## Usage

Check a git repo (tracked files come from `git ls-files`):

```
python3 src/gitignore_checker.py .
```

```
FAIL secrets.txt: tracked but ignored by .gitignore line 2: secrets.txt
Checked 3 tracked file(s), 1 problem(s).
```

Check a folder with a tracked list instead of git:

```
python3 src/gitignore_checker.py examples/bad-repo --tracked examples/bad-repo/tracked.txt
```

```
FAIL secrets.txt: tracked but ignored by .gitignore line 2: secrets.txt
FAIL app.log: tracked but ignored by .gitignore line 1: *.log
FAIL examples/bad-repo/.gitignore:3: pattern '*.tmp' matches nothing
Checked 3 tracked file(s), 3 problem(s).
```

Keep patterns for files that do not exist yet:

```
python3 src/gitignore_checker.py examples/bad-repo --tracked examples/bad-repo/tracked.txt --allow-unused
```

```
FAIL secrets.txt: tracked but ignored by .gitignore line 2: secrets.txt
FAIL app.log: tracked but ignored by .gitignore line 1: *.log
Checked 3 tracked file(s), 2 problem(s).
```

A repo with no `.gitignore` at all:

```
python3 src/gitignore_checker.py examples/no-gitignore-repo --tracked examples/no-gitignore-repo/tracked.txt
```

```
FAIL examples/no-gitignore-repo: no .gitignore file
Checked 2 tracked file(s), 1 problem(s).
```

Machine-readable output with `--json` (the summary goes to
standard error, so standard output is clean JSON):

```
python3 src/gitignore_checker.py examples/clean-repo --tracked examples/clean-repo/tracked.txt --json
```

```
{
  "repo": "examples/clean-repo",
  "tracked": 2,
  "problems": [],
  "summary": {
    "checked": 2,
    "problems": 0
  }
}
```

Exit codes: 0 when the `.gitignore` matches, 1 when any file has
a problem, 2 for a usage problem (a missing folder, a bad flag, a
repo that is not a git checkout and no `--tracked` list given).

## Examples

### 1. A tracked file that should be ignored

`examples/bad-repo` has a `.gitignore` with `*.log` on line 1 and
`secrets.txt` on line 2, but both files are tracked:

```
python3 src/gitignore_checker.py examples/bad-repo --tracked examples/bad-repo/tracked.txt
```

```
FAIL secrets.txt: tracked but ignored by .gitignore line 2: secrets.txt
FAIL app.log: tracked but ignored by .gitignore line 1: *.log
FAIL examples/bad-repo/.gitignore:3: pattern '*.tmp' matches nothing
Checked 3 tracked file(s), 3 problem(s).
```

### 2. A clean repo

`examples/clean-repo` ignores `*.log` and `build/`, and tracks
only `app.py` and `README.md`:

```
python3 src/gitignore_checker.py examples/clean-repo --tracked examples/clean-repo/tracked.txt
```

```
OK — 2 tracked file(s) checked, .gitignore matches.
```

### 3. The bundled examples, all at once

```
sh examples/run-example.sh
```

The script checks the clean repo (passes), then the bad repo
(fails, on purpose), then the repo with no `.gitignore` (fails,
on purpose). Its full output is in `examples/sample-output.txt`.
The failing runs exit 1, which is the expected result — the
script ends with exit 0 so it can be run as a demo.

## How it is tested

48 tests, standard library `unittest` only, no packages to install:

```
python3 tests/test_gitignore_checker.py
```

The tests cover: pattern matching (`*`, `?`, `[...]`, `**` at
the start, middle, and end, anchored and unanchored patterns,
folder-only patterns, negation, last-match-wins, comments and
blank lines), the repo check (clean repos, tracked-but-ignored
files, unused patterns, `--allow-unused`, patterns used by a file
on disk only, negated tracked files, non-UTF-8 ignore files),
the CLI (exit 0/1/2, `--json` output, `--version`, missing
folders, a missing tracked list, a folder that is not a git
checkout, input files left unchanged, a real git repo built with
`git init` and `git add -f`), the bundled examples (sample output
compared byte-for-byte against a fresh run, and the README-quoted
outputs checked against it), and hygiene checks (no placeholder
text, no absolute paths, stdlib imports only, `.env` first in
`.gitignore`).

## Contributing

Small, focused improvements are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. The idea of
checking `.gitignore` files is not new — the similar tools named
above (thehanimo/py-gitignore, inmarelibero/gitignore-checker,
kvn-dtrx/gitignore-checker, kriskimmerle/gitignore-check) are
listed in "How this differs" — but every line of code here is
original, and the tool builds on nothing but Python's standard
library.
