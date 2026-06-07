# fix: allow uppercase hex digits in uuid, uuid3, uuid4, uuid5 validators

## Summary

The `uuid`, `uuid3`, `uuid4`, and `uuid5` validation tags incorrectly rejected valid UUIDs containing uppercase hexadecimal characters. The RFC 4122 variants (`uuid_rfc4122`, `uuid3_rfc4122`, etc.) already used case-insensitive patterns (`[0-9a-fA-F]`), but the non-RFC variants only matched lowercase hex digits (`[0-9a-f]`).

## What changed and why

- **`regexes.go`**: Updated `uUIDRegexString`, `uUID3RegexString`, `uUID4RegexString`, and `uUID5RegexString` to use `[0-9a-fA-F]` (and `[89abAB]` for the variant nibble in UUID4/5) so that uppercase UUIDs are accepted, consistent with the `_rfc4122` counterparts.
- **`doc.go`**: Removed the incorrect documentation notes that stated uppercase UUIDs would not pass and that users should use the `_rfc4122` variants as a workaround.
- **`validator_test.go`**: Added test cases with uppercase UUIDs for `uuid`, `uuid3`, `uuid4`, and `uuid5` to prevent regressions.

## Validation

Existing tests continue to pass. New test cases confirm that uppercase UUIDs (e.g. `"5ADE1109-1E12-4E46-8E41-EF204C423153"`) are now accepted by all four affected validators.

Fixes #1550
