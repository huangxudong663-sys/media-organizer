# Phase 1-4 changes

This branch implements a staged refactor of the original media_organizer script to improve batch performance, robustness, and add optional AI-assisted filename classification.

Summary of major changes by phase:

Phase 1
- Replaced interactive-only stdin prompts with an argparse-based CLI while retaining interactive fallback.
- Added logging support and a --dry-run mode that exports CSV preview instead of moving files.
- Added a switch to allow (or not) automatic dependency installation at runtime.

Phase 2
- Added support for exiftool bulk metadata extraction (if available) to speed up processing of large datasets.
- Added ffprobe concurrency limiting when per-file video metadata extraction is used.
- Implemented deep_merge for reading user config to avoid accidental removal of default nested keys.

Phase 3
- Added optional --dedupe to compare files by content hash (xxhash preferred) and skip true duplicates.
- UTF-8 Unicode normalization applied more broadly to filenames and path comparisons.
- Operation metadata saved to logs (config checksum, root path, git short sha if available).

Phase 4
- Optional AI classification support (OpenAI/Anthropic) to label filenames which rules don't match.
- AI batching, timeout, retry and strict JSON-only extraction + validation; raw AI responses saved only if explicitly enabled.
- Unit tests and documentation updates.

Notes
- AI is disabled by default and must be enabled in the configuration or via CLI override.
- Automatic pip installs are disabled by default. Use --auto-install-deps to allow the script to install missing Python packages at runtime.

Testing & Usage
- See README.md for usage, large dataset recommendations, and privacy notes.
