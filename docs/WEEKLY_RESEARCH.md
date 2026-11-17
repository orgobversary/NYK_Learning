# Weekly Private Research Operation

The weekly job refreshes private research artifacts and the authenticated preview. It
does not publish the Bucket, dataset, Space, or real rows publicly. The job exits without
creating a release when the validated team and passing inputs are unchanged.

## Current operational status

The schedule is installed but **suspended**. On 2026-11-17, both the local runtime and a
manual Hugging Face Job exhausted three 45-second attempts against the NBA Stats
participant endpoint before any passing rows were normalized. Team ingestion and exact
coverage validation succeeded in both environments. Keep the schedule suspended until
the passing source succeeds or a separately authorized export is imported and validated;
do not replace the missing observed network with synthetic edges in a real preview.

## Infrastructure

- Bucket: `obversarystudios/nyk-world-research` (private, US)
- Space: `obversarystudios/nyk_world` (private)
- Schedule: Monday at `11:00 UTC`
- Hardware: `cpu-basic`; timeout 45 minutes; two attempts; concurrency disabled
- Script: `scripts/weekly_research.py` at a pinned Git revision
- Installed schedule ID: `obversarystudios/6afcbf87884144d2f44f81bd` (suspended)

The job mounts the private Bucket at `/research`, bootstraps the cloned project with
`uv pip`, and receives `HF_TOKEN` as a scoped write secret. Never place the token in a
command argument, repository file, manifest, or Space variable.

## Promotion gates

The job must complete source retrieval, exact season coverage, passing schema checks,
closed-manifest validation, chronological modeling, story generation, payload validation,
and private Space upload before atomically changing `registry/latest-research.json` and
`registry/latest-preview.json`. A failed job leaves both pointers unchanged.

Run a manual Job first, repeat it to prove the no-change path, and test rollback to the
previous Space commit before enabling the schedule. Public visibility remains a separate
explicit review.

## Scheduling

Pin the raw script URL to a reviewed 40-character Git commit and export a scoped write
token as `HF_TOKEN` in the invoking shell. Never paste the token into the command:

```bash
hf jobs scheduled uv run "0 11 * * 1" \
  https://raw.githubusercontent.com/orgobversary/NYK_Learning/<commit>/scripts/weekly_research.py \
  --name nyk-world-weekly-research --flavor cpu-basic --timeout 45m --attempts 2 \
  --no-concurrency --python 3.13 \
  --volume hf://buckets/obversarystudios/nyk-world-research:/research:rw \
  --secrets HF_TOKEN --env NYK_REPO_REF=<reviewed-branch-or-tag>
```

Inspect the returned schedule ID with `hf jobs scheduled inspect <id>` and run it once
with `hf jobs scheduled trigger <id>`. After a successful run, invoke it again and confirm
the log reports that inputs are unchanged. Use `hf jobs scheduled suspend <id>` before
source migrations or incident response.

## Rollback

Bucket releases are immutable, so rollback means moving `registry/latest-research.json`
and `registry/latest-preview.json` back to a previously verified release and restoring
the corresponding private Space commit. Do not delete the failed release while
investigating it. Validate the restored Space in an authenticated browser before
resuming the schedule.
