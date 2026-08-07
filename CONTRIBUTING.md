# Contributing

Use the guided GitHub forms for bugs and feature requests. For bugs, download
Home Assistant diagnostics from the TorrServer integration, inspect the redacted
file, and attach it manually. Never post credentials, torrent names, hashes,
paths, links, or media metadata.

Development checks:

```bash
python -m pip install -r requirements_test.txt
python -m pytest
python -m ruff check .
```

Keep the integration read-only toward TorrServer. Add tests and matching English,
Italian, and Russian translations for user-visible changes. Beta work should be
validated on a beta branch before a stable release is created.
