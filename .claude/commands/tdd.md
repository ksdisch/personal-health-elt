---
description: Test-first loop — write failing tests for a spec, confirm they fail for the right reason, commit them, then write code until they pass WITHOUT modifying the tests. Pass the module + behavior to specify as the argument.
argument-hint: <module path + behavior to specify>
---

Task: $ARGUMENTS

Run the **test-first (TDD)** loop. The value is in writing the tests before the
implementation — be disciplined about the order. (If no task was given above, ask
me what behavior to specify first.)

## 1. Write tests first
- Write tests that capture the expected input/output behavior described above.
- **Do NOT write or modify the implementation yet.** The tests are expected to
  fail (or not compile) because the behavior isn't built — that's correct. Don't
  stub the implementation just to make them pass.

## 2. Confirm they fail for the right reason
- Run the suite. Confirm the new tests fail because the behavior is missing, not
  because the tests are malformed. Show me the failing output briefly.

## 3. Commit the tests
- Commit the failing tests on their own (conventional-commit message). This locks
  the spec in place before any implementation exists.

## 4. Code until green
- Now write the implementation to make the tests pass.
- Iterate: run tests → read failures → adjust **the implementation only**. Do NOT
  edit the tests to fit the code. If a test itself is genuinely wrong, stop and
  tell me — don't silently change it.
- Loop until everything is green.
- Keep the loop cheap: re-run only the relevant test(s), and don't re-read files you
  haven't changed.

## 5. Commit
- Commit the passing implementation. Don't push unless I explicitly say so.

---
**When this loop does NOT apply:** repos that ban tests, or framework-bound code
(Phaser scenes, React components) where there's no clean pass/fail — use the
screenshot or playtest loops instead. Keep TDD for pure, deterministic logic.
In Constellation that means colocated `*.test.ts` run via `npm run test` (Vitest),
e.g. the progression/persistence module — never instantiate Phaser/React in tests.
