# Security Policy

This tool runs locally, collects no data, sends nothing anywhere, and needs no API key or secret. It only reads the repo folder, the .gitignore file, and the tracked list you name, and it never changes a file, never untracks anything, and never deletes a comment. It writes nothing except the report on standard output (and usage errors on standard error).

If you find a case where the tool changes a file, or reports a count that does not match the real files, please open an issue describing the exact commands and input. Do not include any real secret in the report.
