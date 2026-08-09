# `.crm-migrate-v2`

The v2 workflow migration: **applied to the live CRM on 9 August 2026.** `WORKFLOWS.md` now
describes boards that actually exist.

👉 **[RUNBOOK.md](./RUNBOOK.md)** — read this before touching anything. What ran, run order, the two
gates, the **six** bugs (three caught by dry runs, three that only surfaced on `--apply`), what
rollback cannot recover, and what is still not scripted.

Team-facing version: [`../MIGRATION.md`](../MIGRATION.md).

Every script is dry-run by default and a no-op on re-run, so running one bare is a safe way to see
whether the CRM still matches the spec:

```sh
python3 05_verify.py            # read-only: is every record on a v2 stage?
python3 07_relabel_stages.py    # do the boards' labels and column order still match the spec?
```

`_snapshot.py` hashes the schema plus every record's stage. It **no longer matches** the
`c382bb69…` pre-migration baseline, and that is expected. It is still useful for one thing: hash
before and after a *dry* run, and the two must be identical.

Rollback state lives in `manifests/` and is **gitignored, not disposable** — those files are the
only way to reverse `01`–`04` and `07`. Nothing can reverse `06`.
