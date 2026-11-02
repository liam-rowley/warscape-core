# F1: Fixture first job

Model: Sonnet. Budget about 50 tool calls; at the cap, stop.

## Kill criteria
- It breaks twice: stop.

## Finish
Write `jobs/F1/report.md`. Then `wsc reg set jobs F1 status=review report=jobs/F1/report.md`.
