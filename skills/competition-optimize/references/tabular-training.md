# Numeric Tabular Training

Use `scripts/tabular_training.py` for finite numeric features and scalar regression (`rmse`, `mae`) or binary probabilities (`binary_log_loss`, `roc_auc`). This adapter performs actual fitting; the older prediction tools remain useful for already-produced predictions. It does not prepare arbitrary Kaggle datasets, support multiclass/image/text tasks, or submit to a platform.

## Setup and Candidate Interface

Use an isolated optional environment; the rest of the skill remains standard-library based:

```sh
uv venv /absolute/path/to/tabular-env --python /usr/bin/python3
uv pip install --python /absolute/path/to/tabular-env/bin/python \
  -r /absolute/path/to/competition-optimize/scripts/requirements-tabular.txt
```

A candidate is a single Python source file exposing `build_model(seed, task)`. Return a fresh sklearn-compatible estimator or pipeline. Keep learned preprocessing **inside** the returned pipeline. Use installed dependencies; snapshot any additional implementation dependencies before extending this single-file interface. For example:

```python
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge, LogisticRegression

def build_model(seed, task):
    estimator = (LogisticRegression(random_state=seed, max_iter=2000)
                 if task == "binary" else Ridge(alpha=1))
    return make_pipeline(StandardScaler(), estimator)
```

The adapter gives each fit only the declared training features/labels. It records the rows and saved model bytes. Candidate Python and joblib files are trusted executable code: this is not a sandbox or proof that arbitrary code did not read other files. Upstream features, external data permission and prior holdout exposure still require task-specific review.

## Freeze the Fold Protocol Before Comparing Candidates

The training CSV contains unique string IDs, declared numeric feature columns, the target and any split metadata. Binary targets are exactly 0/1; each training fold needs both classes. Column names default to `id`, `target`, `prediction` and may be overridden in the protocol.

```json
{
  "schema_version": 1,
  "task_id": "my-task-v1",
  "task": "regression",
  "metric": "rmse",
  "score_kind": "proxy",
  "features": ["x1", "x2"],
  "split": {"kind": "group", "group_column": "patient"},
  "expected_oof_ids": ["a", "b", "c", "d"],
  "folds": [
    {"id": "0", "seed": 1729, "train_ids": ["c", "d"], "validation_ids": ["a", "b"]},
    {"id": "1", "seed": 1730, "train_ids": ["a", "b"], "validation_ids": ["c", "d"]}
  ]
}
```

This example assumes groups in the two partitions are disjoint. `iid` and `group` require exactly one OOF prediction for every data row. `time` and `group_time` allow a declared warmup set excluded from `expected_oof_ids`; every row must still be used in some train/validation fold. Validation IDs cannot repeat across folds. The metric is pooled over all declared OOF rows, **not** the mean of fold scores. No default fold or seed search is performed.

For temporal protocols, set `time_column`, `time_format` (`number` or timezone-aware `iso8601`), optional `available_time_column`, and optional nonnegative `minimum_time_gap` under `split`. Each validation period must follow both the latest training event and label-availability timestamp by the declared gap. Combine with `group_column` using `group_time` when both restrictions apply. The same checks apply between development data and confirmation/final features; final features need event/group metadata, but not future label-availability timestamps.

## Train, Compare, Freeze, Confirm

Commands use fresh output directories under an existing parent. A failed fit can leave diagnostic files but never a successful manifest; use a new directory for a repaired attempt.

```sh
PY=/absolute/path/to/tabular-env/bin/python
S=/absolute/path/to/competition-optimize/scripts
$PY "$S/tabular_training.py" train --data training.csv --protocol folds.json \
  --candidate candidate.py --output-dir runs/baseline
# Implement a real source/pipeline change, then use the same data/protocol.
$PY "$S/tabular_training.py" train --data training.csv --protocol folds.json \
  --candidate changed.py --output-dir runs/challenger
$PY "$S/compare_prediction_results.py" \
  --baseline runs/baseline/evaluation/result.json \
  --candidate runs/challenger/evaluation/result.json --truth runs/baseline/truth.csv \
  --output runs/development-comparison.json
$PY "$S/tabular_training.py" freeze --run runs/challenger \
  --decision-rule 'Apply the predeclared independent confirmation rule; otherwise retain the baseline' \
  --output-dir runs/frozen
$PY "$S/tabular_training.py" confirm --frozen runs/frozen \
  --data confirmation-features.csv --truth confirmation-truth.csv --output-dir runs/confirmation
$PY "$S/tabular_training.py" predict --frozen runs/frozen --data test-features.csv \
  --sample-submission sample_submission.csv --output-dir runs/final
```

Choose the candidate from development evidence before `freeze`; the example command is not a direction to select the challenger regardless of results. Freeze all finalists and the actual selection/delivery rule before reading confirmation labels. `freeze` copies and seals source, protocol, data, OOF, fitting receipts and model files. Later commands recheck those bytes and recorded Python/package environment before loading the models. The fixed inference recipe is the arithmetic mean of all frozen fold models; it does not retrain on holdout rows or tune blend weights. The tool records the decision rule but does not interpret natural language or automatically promote a candidate.

`confirm` checks ID/group/time separation, predicts with frozen models, then reads the separate confirmation truth file and produces a normal prediction result with `stage=confirmation`. Keep it out of development decisions. `predict` verifies the exact sample ID set, column names and order; it writes predictions in sample order plus a hash receipt. Sample format is exactly the ID and prediction column. Upload remains a separately authorized action.

## Artifacts and Archive Identity

- `candidate.py`, `protocol.json`, `training.csv`: snapshotted implementation and inputs.
- `recipe.json`: stable implementation identity containing the actual candidate source, feature/data identity and environment; it excludes output bytes, elapsed times and fold measurement seeds.
- `models/fold-N.joblib`, `fit.json`: trained models, actual fit rows, seeds, timings, package versions and unchecked scope.
- `oof.csv`, `truth.csv`, `evaluation/result.json`: complete OOF and normal scorer evidence, usable with existing prediction comparison/error tools.
- `manifest.json`: hashes of every run artifact; frozen copies additionally bind the training seal and delivery rule. Paths inside the manifest are relative, so a complete frozen directory can move without rewriting its seal.
- `delivery.json`, `submission.csv`: frozen identity, input/output hashes and validated final row order.

For candidate archiving, the prediction hash identifies output, not implementation. Pass `--configuration RUN/recipe.json` to bind the actual candidate source, feature/data identity and environment. The fold protocol remains independently sealed in the evaluation and training manifest. Do not use elapsed time or fitted model/prediction hashes as implementation identity: repetitions of an unchanged recipe remain measurements of one implementation. Archive the normal result and retain `fit.json`/manifest as its fitting evidence. Confirmation results keep the confirmation role.

`examples/tabular_training_pilot.py` in the repository demonstrates real baseline/challenger OOF fitting, frozen confirmation and final CSV on bundled raw Diabetes data. It is a reproducible integration exercise, not a benchmark of autonomous contest gains.
