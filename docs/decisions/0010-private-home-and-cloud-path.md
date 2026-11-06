# 0010. A public engine, a private home, and the path to the cloud

Status: accepted for the private home and the blob store · proposed for phases 2 and 3 · 2026-11-06.

## Context

This repository is public. Character bibles, account handles, and real briefs cannot live in it. The operator also wants a design that scales past one machine, with encryption and object storage.

## Decision

**Now, built.**

- Operator data lives in a private directory named by `$KALAINOVA_HOME`: `jobs/`, `kits/`, `streams/`, `store/`, `out/`. Make it a private repository. This repo ignores those paths and holds only the engine, schemas, prompts, and docs.
- Kit bytes are content-addressed. A kit records a hash and a suffix, never a location. `blobstore.py` keeps a local cache and, when `$KALAINOVA_STORE_URI` is set, a durable S3-compatible copy, with SSE-KMS when `$KALAINOVA_KMS_KEY` is set. A fetched object is refused unless its bytes match its hash.
- Credentials never enter a kit, a stream, or a record. Streams hold handles. Each channel posts with its own token, so a post cannot reach another channel.

**Phase 2, proposed: Postgres and workers.** Add this when a second worker runs at once.

- Postgres holds the job queue (`FOR UPDATE SKIP LOCKED`), the cost ledger with atomic reservation, which closes the known gap that parallel calls can overshoot a cap, and indexes for reporting. Kit versions and locks stay immutable content-hashed documents, so history cannot be edited in place.
- Job records and rendered files move to object storage. A stateless worker claims a job, pulls its bundle, renders in one container, and pushes results. Rendering is CPU and ffmpeg, because models are rented over HTTP, so a serverless container job fits and no GPU is needed.
- An approval remains a human act bound to the file hash, now with an authenticated reviewer.

**Phase 3, proposed: the review service.** An authenticated API and review card, with tenant separation if clients ever log in.

**Security baseline for every phase.** Private bucket, no public ACLs, signed URLs only, versioning on, object lock on frozen references. TLS in transit. Encryption at rest with KMS. Secrets in a secret manager, never in the database. Least-privilege roles per worker. Audit log for approvals and kit freezes. Check each model vendor's retention terms, because references leave our control when sent.

## Consequences

Local-only use still works with no configuration. Phases 2 and 3 need a choice of cloud, and nothing in them is built or tested yet. `git` history keeps anything that was already public, so moving data out now does not retract it.
