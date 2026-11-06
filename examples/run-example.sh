#!/bin/sh
# Demo: check the clean repo (passes), then the bad repo (fails, on
# purpose), then the repo with no .gitignore (fails, on purpose).
# The failing runs exit 1, which is the expected result — the script
# ends with exit 0 so it can be run as a demo.
cd "$(dirname "$0")/.."
python3 src/gitignore_checker.py examples/clean-repo --tracked examples/clean-repo/tracked.txt
python3 src/gitignore_checker.py examples/bad-repo --tracked examples/bad-repo/tracked.txt || true
python3 src/gitignore_checker.py examples/no-gitignore-repo --tracked examples/no-gitignore-repo/tracked.txt || true
