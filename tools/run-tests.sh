#!/bin/bash
# tools/run-tests.sh - every check in this repository (the same file in every
# repository that uses tools/build.py). Nothing touches the real system: dom0's
# tools are mocked, qubes are entries in a JSON file.
#   - generated scripts match their sources (tools/build.py --check)
#   - shell and Python syntax of every script
#   - tools/tests: every module's dom0 scripts, and the all-in-one, against the mocks
#   - each module's own tests (<module>/tests/run-tests.sh), if it has any
# Some tests need root and an account named 'user'; they are skipped otherwise.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 tools/build.py --check
for f in $(find . -path ./.git -prune -o \( -name '*.sh' -o -name '*.rc' \) -print); do
    case $f in */tests/shell-harness/*|*/node_modules/*) continue ;; esac
    bash -n "$f" || { echo "syntax error: $f" >&2; exit 1; }
done
for f in $(find . -path ./.git -prune -o -path '*/tests' -prune -o -type f -print); do
    case $(head -c 40 "$f" | head -n 1) in
        '#!/usr/bin/python3'*|'#!/usr/bin/env python3'*)
            python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read(), sys.argv[1])" "$f" ;;
    esac
done
(cd tools/tests && python3 -W ignore -m unittest test_modules)
for t in */tests/run-tests.sh; do
    [ -e "$t" ] || continue
    echo "== $t"
    bash "$t"
done
echo "all checks passed"
