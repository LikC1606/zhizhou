# Move Archived Evidence Without Rewriting Identity

Use this when moving a completed archive and its source/result files to another location. Export only the artifact roots you explicitly select. The exporter does not discover every reference or certify scientific conclusions.

```sh
S=/absolute/path/to/competition-optimize/scripts
/usr/bin/python3 "$S/evidence_bundle.py" export \
  --archive /old/run/candidates.jsonl \
  --artifact /old/run/candidates \
  --artifact /old/run/evaluations \
  --output /new/evidence-bundle
/usr/bin/python3 "$S/evidence_bundle.py" verify --bundle /new/evidence-bundle
```

The new directory contains the original archive bytes, copied artifacts and a manifest mapping each original absolute path to a relative stored location with its content hash. Directory inventory and file bytes are checked. Original JSONL, proposal targets, review/learning seals and path-bearing identities remain unchanged. The bundle directory can itself move intact.

`verify` checks the exported bytes and mapping. It does not prove that all references have been exported. Unmapped references fail explicitly during a query, even if an original file still happens to exist; no filesystem search or silent fallback fills the gap. Export missing artifacts into a new complete bundle instead of editing the archive or manifest to guess identities.

## Query a Moved Bundle

The explicit resolver plugs into `EvidenceSnapshot`; the existing archive CLI still operates on ordinary local paths. For example:

```sh
PYTHONPATH="$S" /usr/bin/python3 - /new/evidence-bundle <<'PY'
import json
import pathlib
import sys
from candidate_archive import parse_records
from evidence_files import ArtifactResolver
from evidence_queries import BriefQuery, EvidenceSnapshot

resolver = ArtifactResolver(pathlib.Path(sys.argv[1]))
records = parse_records(resolver.archive_path.read_bytes(), str(resolver.archive_original_path))
evidence = EvidenceSnapshot(resolver.archive_original_path, records, resolver=resolver)
print(json.dumps(evidence.brief(BriefQuery()), ensure_ascii=False, indent=2))
# Exact proposal chain, when needed:
# print(evidence.trace(proposal_id="proposal-id"))
PY
```

A query checks the original archived hashes against the explicitly resolved bytes. The returned identities continue to name the original locations; use `resolver.resolve_path(pathlib.Path(original_path))` to open their relocated copies. Create a fresh resolver/evidence view for each operation, preserving the existing rule against cross-operation file verification caches.

This is an evidence reader/exporter, not a campaign migration command. It does not move live processes, rewrite sealed requests, reassign locks, change model selection or promote confirmation evidence into development.
