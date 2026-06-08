# media-organizer — README (feature/organizer-refactor)

This repository contains a photo/video organizer script that classifies media files by EXIF, filename rules, optional AI, and collects unclassified files for manual review.

Phase 2 features (in-progress):
- exiftool bulk metadata reading (if available) for high performance on large datasets
- ffprobe concurrency limiting
- configuration deep merge to avoid overwriting default nested keys
- optional dateutil for better datetime parsing

Quick start

1. Clone the repo and checkout the feature branch:
   git clone https://github.com/huangxudong663-sys/media-organizer.git
   cd media-organizer
   git fetch origin
   git checkout feature/organizer-refactor

2. Install Python dependencies (recommended to use virtualenv):
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   # Optional dependencies for better performance/parsing
   pip install -r requirements-optional.txt

3. Install system tools (highly recommended for large datasets):
   - exiftool (https://exiftool.org/) — used for bulk metadata extraction
   - ffmpeg/ffprobe — used for video metadata when exiftool not available

4. Run a dry-run on a sample directory to preview CSV:
   python3 media_organizer.py --root /path/to/media --dry-run --preview -vv

Notes for running on 2-3TB dataset
- Run exiftool-based bulk metadata extraction: the script will automatically use exiftool if installed when the --use-exiftool flag is provided (or auto-detected).
- Break work into top-level subdirectory jobs and run multiple workers, each limited in concurrency. Example strategy:
  - Each worker: python3 media_organizer.py --root /media/partX --dry-run --use-exiftool --ffprobe-workers 4
- Use --dry-run and inspect the generated CSV before doing real moves.
- Preserve backups or run on copies when testing.

Privacy and AI
- AI classification (optional) sends only filenames to the AI provider, NOT file contents. AI is disabled by default.
- If you enable AI, set API keys via environment variables (e.g., OPENAI_API_KEY or ANTHROPIC_API_KEY).

Pull Request & Review
- Changes are made on branch feature/organizer-refactor. A PR will be opened when the feature work is complete; reviewers will be assigned.

