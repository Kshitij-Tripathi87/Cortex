# Validation examples

Small synthetic files that show what import preview reports. They are not
part of the demo dataset and are not imported by the seed.

`equipment_with_issues.csv`, previewed as `equipment` in a workspace that has
a project `DC-EXAMPLE` and no project `DC-NOT-IMPORTED`:

| Row | What it shows | Result |
|---|---|---|
| 2 | A valid row with a value in an unmapped column | Valid; warning `UNKNOWN_SOURCE_COLUMN` |
| 3 | `03/04/26` as a date | Invalid: `INVALID_DATE` (3 April or 4 March is not guessed) |
| 4 | A project that was not imported | Invalid: `REFERENCE_NOT_FOUND` |
| 5 | No required-on-site date | Valid; warning `REQUIRED_ON_SITE_DATE_NOT_RECORDED` |
| 6 | The same row again | Valid, will be skipped; warning `DUPLICATE_ROW` |
| 7 | `Reactor` as a category | Invalid: `INVALID_ENUM` |
