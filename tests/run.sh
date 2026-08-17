#!/bin/sh
# Every suite in this directory, one line of result each.
#
# Runnable from anywhere: it locates itself and the repo from $0, never from
# the current directory.
#
#   tests/run.sh              every suite
#   tests/run.sh viz          only suites whose name contains "viz"
#
# Pass and fail are decided by EXIT CODE and nothing else. An earlier runner
# grepped the output for "Traceback" and called that a crash, which marked a
# suite permanently broken because one of its checks deliberately triggers a
# 500 and the route logs that failure with log.exception — a traceback that
# means the test is working. Output is for humans; the exit status is the
# result.
#
# Exits non-zero if any suite failed, so CI or a shell can gate on it.

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO=$(dirname "$HERE")
FILTER=$1

cd "$REPO" || exit 1

pass=0
fail=0
failed=""
started=$(date +%s)

for file in "$HERE"/test_*.py; do
  [ -f "$file" ] || continue
  name=$(basename "$file" .py)
  name=${name#test_}

  if [ -n "$FILTER" ]; then
    case $name in
      *"$FILTER"*) ;;
      *) continue ;;
    esac
  fi

  begin=$(date +%s)
  out=$(timeout 900 python3 -u "$file" 2>&1)
  code=$?
  took=$(( $(date +%s) - begin ))

  # Reported, not decided: the count is read out of the suite's own summary
  # line when it prints one, purely so the line is informative. Whether the
  # suite passed is `code`.
  checks=$(printf '%s' "$out" | sed -n 's/^\([0-9][0-9]*\) checks,.*/\1/p' | tail -1)
  [ -n "$checks" ] || checks="-"

  if [ "$code" -eq 0 ]; then
    pass=$((pass + 1))
    printf '  %-18s ok      %6s checks  %4ds\n' "$name" "$checks" "$took"
  else
    fail=$((fail + 1))
    failed="$failed $name"
    printf '  %-18s FAILED  %6s checks  %4ds  (exit %d)\n' \
      "$name" "$checks" "$took" "$code"
    printf '%s' "$out" | grep -E '[[:space:]]FAIL|Error|Traceback' | head -8 \
      | sed 's/^/        /'
  fi
done

total=$(( $(date +%s) - started ))

echo
if [ "$fail" -eq 0 ] && [ "$pass" -eq 0 ]; then
  echo "no suites matched '$FILTER'"
  exit 1
fi
printf '%d passed, %d failed, %ds total\n' "$pass" "$fail" "$total"
[ "$fail" -eq 0 ] || { printf 'failed:%s\n' "$failed"; exit 1; }
exit 0
