# Comparison — validator #1550 (uuid rejects uppercase) vs. accepted PR #1551

- **Issue:** https://github.com/go-playground/validator/issues/1550
- **Accepted PR:** https://github.com/go-playground/validator/pull/1551
- **Base commit (pre-fix tree):** `b9258bd2b7bbab41c3d99090cac4a659c5f1a60c`
- **Model:** `claude-sonnet-4-6`

## Root cause (both agree)

The `uuid` regex used the lowercase-only hex class `[0-9a-f]`, so valid UUIDs in
uppercase (e.g. `5ADE1109-1E12-4E46-8E41-EF204C423153`) were rejected.

## Maintainer's accepted fix (PR #1551)

- `regexes.go`: `uUIDRegexString` `[0-9a-f]` → `[0-9a-fA-F]` (the `uuid` tag only).
- `validator_test.go`: one uppercase case added to `TestUUIDValidation`.
- (Plus some gofmt whitespace realignment.)

## Agent's change (`change.patch`)

- `regexes.go`: applied the **same** `[0-9a-f]`→`[0-9a-fA-F]` fix, and extended it
  consistently to `uUID3/uUID4/uUID5RegexString` (and `[89ab]`→`[89abAB]` for the
  variant nibble) so `uuid3/uuid4/uuid5` accept uppercase too.
- `doc.go`: removed the now-incorrect "Uppercase UUID values will not pass" lines
  for uuid/uuid3/uuid4/uuid5.
- `validator_test.go`: added an uppercase case to **all four** UUID test tables
  (`TestUUIDValidation`, `TestUUID3/4/5Validation`).

## Assessment

| Criterion | Result |
|-----------|--------|
| Right file(s) | ✅ `regexes.go` (+ `doc.go`, tests) — matches and extends the PR |
| Relevant change | ✅ Identical core fix; generalized to all UUID variants |
| Conventions | ✅ Same regex style; doc + tests updated in the repo's table-test idiom |
| Validation | ✅ `go build` + `gofmt` clean; `go test ./...` → all 24 packages pass |
| PR summary | ✅ `pr.md` is accurate and grounded in the diff |

**Verdict:** Matches the accepted fix and is *more thorough* — it also covers the
versioned UUID tags and removes the stale doc lines the human PR left behind.
That breadth is a reasonable, defensible scope for the same root cause (a maintainer
might trim it to just `uuid`, but nothing here is wrong or out of scope).
