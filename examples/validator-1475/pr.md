# Fix e164 regex to reject phone numbers with country code starting with 0

## Summary

The `e164` validator incorrectly accepted phone numbers whose country code started with `0` (e.g. `+0123456789`). Per the E.164 specification, country codes must begin with a digit in the range `1–9`.

## What changed and why

**`regexes.go`**: Updated `e164RegexString` from `^\+[1-9]?[0-9]{7,14}$` to `^\+[1-9][0-9]{6,14}$`.

- The old pattern made the leading `[1-9]` optional (`?`), so `+0…` would pass as long as the total digit count was within range.
- The new pattern requires the first digit after `+` to be `[1-9]` (non-optional) and adjusts the subsequent digit count to `{6,14}`, keeping the overall valid length at 7–15 digits (including the `+` sign) in line with the E.164 standard.

**`validator_test.go`**: Added `TestE164Validation` covering empty strings, missing `+`, numbers starting with `+0`, valid international numbers, and boundary length cases.

## Validation

The new test suite exercises both previously-broken cases (e.g. `+0123456789` now correctly fails) and known-good numbers (e.g. `+1123456789`, `+441234567890`). All tests pass with the updated regex.

Fixes #1475
