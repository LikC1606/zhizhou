# Check Declared Data Partitions

Use `audit_data_split.py` before expensive fitting when partitions are represented as exact row IDs. It checks metadata consistency without loading features, targets, or model files. Reuse the receipt while split/metadata bytes, check configuration, and checker dependencies match; do not repeat an unchanged check for each model.

## Input and Basic Check

Provide a UTF-8 JSON object with 2-64 non-empty partitions. Each list contains unique, non-empty **string** IDs; `"001"` and `"1"` remain distinct. All declared partitions must be mutually disjoint:

```json
{"train": ["001", "1"], "development": ["a"], "confirmation": ["b"]}
```

```powershell
python <skill-dir>/scripts/audit_data_split.py `
  --splits <splits.json> --output <new-split-audit.json>
```

Optional `--metadata <rows.csv>` checks exact coverage of the union of audited IDs, using `--id-column id` by default. Metadata may include extra named columns but no duplicate/empty column names, duplicate IDs, or malformed rows. Prepare metadata for these audited rows only; omitted or additional IDs reject the check. No metadata means only ID disjointness is checked.

## Group and Forward-Time Boundaries

When patients/users/devices or duplicate clusters must remain separate, add `--metadata <rows.csv> --group-column patient`. Repeat `--group-column` for multiple required boundaries. The tool checks exact non-empty group labels across every partition pair. Derive the correct group identity in the adapter; different labels for the same underlying entity cannot be detected here. Use this option only when the validation protocol requires group isolation; forward prediction for existing entities may intentionally reuse groups.

For a forward-time protocol, declare the event/prediction timestamp, its format, and every partition in chronological order:

```powershell
python <skill-dir>/scripts/audit_data_split.py `
  --splits <splits.json> --metadata <rows.csv> `
  --time-column event_at --time-format iso8601 `
  --available-time-column label_available_at `
  --time-order train development confirmation `
  --minimum-time-gap 86400 --output <new-split-audit.json>
```

Each later partition must start strictly after the previous partition's latest event **and**, when supplied, latest label-availability timestamp, with at least the declared gap. This detects labels that would not be known at the next prediction boundary. Default gap is zero; tied timestamps still reject. Choose the embargo from the task's horizon/overlapping windows before training, rather than adjusting it after seeing scores. Event timestamps alone cannot establish that training targets were available; supply their availability times when relevant.

`number` uses exact finite decimals in metadata units. `iso8601` accepts `YYYY-MM-DDTHH:MM:SS[.ffffff]` with `Z` or a `+/-HH:MM` timezone (a space may replace `T`); it normalizes instants to UTC and uses seconds for the gap. Fractions are limited to six digits to avoid silent truncation. Boundary values in receipts are exact rational numbers (Unix epoch seconds for ISO time), rather than floating-point approximations. Group and time checks can be combined when both are required.

## Evidence and Limits

The new receipt records input/checker hashes, Python version, configuration, partition sizes, each performed check, and at most five overlap examples per check. `passed` means the declared metadata satisfies these checks. `rejected` saves failed checks and returns exit code 2; malformed input/configuration returns code 2 with a structured error on stderr. Existing outputs are never overwritten. Resolve failures before fitting; a changed split invalidates dependent fitted models and predictions.

This checks **one disjoint partitioning**, not a pooled collection of CV training sets. For OOF, audit each fold's train/held-out partition separately, keep its receipt with the fitted-pipeline lineage, and separately verify OOF coverage and the contest's fold aggregation. Do not force purged/rolling CV into one global chronological partitioning.

A receipt does not inspect executed fitting rows, preprocessing, upstream caches, feature availability, label provenance, prior holdout exposure, statistical independence, or contest/resource rules. Match actual fitting code/records to the audited partitions and retain [training provenance](data-model.md#establish-training-and-validation-evidence). It does not establish that confirmation is unseen, choose a candidate, or grant/renew a user trial cap. Check costs count toward diagnostics, while reuse avoids unnecessary repeated work.
