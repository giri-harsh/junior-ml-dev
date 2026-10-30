# Autopilot report - run 8 (E2B backend + live demo)

## Outcome: NOT RUN - no credentials
The run-8 brief asked me to append `E2B_API_KEY` and `HF_TOKEN` to `.env`, but the lines contained
the placeholders `<paste e2b key>` and `<paste hf token>`, not keys. `.env` (gitignored, verified
with `git check-ignore .env`) has neither name. I did not write placeholders into `.env` and did not
invent tokens (decision 139).

## E2B results + latency
None. Part A skipped. Resume: add `E2B_API_KEY=<key>` to `.env`, then run part A of the brief.

## Space
None created (no `HF_TOKEN`). Visibility, verification, cold start and run latency: not measured.
Resume: add `HF_TOKEN=<write token>` (and `DEMO_PRIVATE=1` if wanted), then run part B.

## Files uploaded / secret scan
0 files uploaded. Nothing was sent anywhere; Groq/Gemini keys were never touched.

## Decisions
139: run 8 skipped for missing keys; docs say "not run".

## Skipped
Parts A and B in full. Part C: docs updated (NEEDS_HARSH items 1-2, KNOWN_GAPS E2B row unchanged);
RESUME_BULLETS has no E2B or demo claim.

## NEEDS_HARSH
E2B key, HF token (+ DEMO_PRIVATE choice), real MinIO, cloud-deploy account.

## Git
See the run-7 report; the run-8 docs are in the same push. No `r8-done` tag (nothing delivered).

## Estimated PRD complete
Unchanged at about 91%; the demo and E2B are the missing pieces.
