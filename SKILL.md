---
name: codex-log-guard
description: Detect and mitigate excessive writes to Codex's logs_2.sqlite database on Windows, macOS, or Linux. Use when checking Codex SQLite/WAL churn, logs_2.sqlite growth, SSD write concerns, GitHub issue openai/codex#28224, or when installing, verifying, automating, or removing the block_log_inserts workaround.
---

# Codex Log Guard

Use the bundled script to detect active Codex diagnostic-log churn and install a reversible SQLite trigger only when thresholds are exceeded.

## Run

Execute from the skill directory:

```bash
python scripts/codex_log_guard.py --json
```

The default check:

1. Resolves `CODEX_HOME`, falling back to `~/.codex`.
2. Confirms `logs_2.sqlite` and the `logs` table exist.
3. Returns immediately when `block_log_inserts` is already installed.
4. Samples aggregate values for 15 seconds without reading log bodies.
5. Treats `MAX(id)` growth of at least 20 or WAL growth of at least 256 KiB as excessive.
6. Installs `block_log_inserts`, checkpoints/truncates WAL, and verifies the trigger.

## Options

- Diagnose without modification: `python scripts/codex_log_guard.py --dry-run --json`
- Install regardless of sampling: `python scripts/codex_log_guard.py --force --json`
- Remove the workaround: `python scripts/codex_log_guard.py --remove --json`
- Adjust detection: use `--sample-seconds`, `--id-threshold`, or `--wal-threshold-bytes`.

## Safety

- Do not delete rows or database files.
- Do not run `VACUUM`; it can cause a large one-time rewrite.
- Do not modify tables other than creating or dropping `block_log_inserts` on `logs`.
- State clearly that blocking inserts disables this diagnostic log table, not Codex conversations, project files, or state databases.
- After an official fix, remove the workaround and re-run in `--dry-run` mode before leaving it disabled.
