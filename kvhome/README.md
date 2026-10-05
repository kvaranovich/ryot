# Community media profile

Baseline: upstream v10.5.0, commit 8cb503e5c86d7afe44b207850206bfa0870653bc.
The main branch follows upstream. Local changes live on codex/kvh-38 until reviewed; release images use upstream-version + kv revision, initially v10.5.0-kv.1.

kvhome/Dockerfile wraps the digest-pinned official Community image and disables telemetry. It does not contain backend or frontend code changes. Personal Note will be a separate change built from fork sources; never claim that a wrapper incorporates source patches.

Use supported user preferences to enable Books, Movies, Shows and Video Games; disable fitness, analytics, calendar, genres, people and groups. Keep collections. Do not remove Pro checks or enable paid features.

Upgrade by fetching upstream and choosing a stable tag; apply only reviewed local commits, verify the build and database backup/restore, then publish a new kv revision. Do not move a deployed image tag. Automated upstream integration is separate work.
