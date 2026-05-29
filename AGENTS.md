# Repository Editing Rules

This project contains Traditional Chinese UI text and data-field labels.
Encoding safety is part of correctness.

## Hard Rules

- Do not write source files with PowerShell redirection (`>` / `>>`), `Out-File`, `Set-Content`, or `Get-Content | Set-Content`.
- Do not use shell scripts or Python scripts to rewrite source files for ordinary edits.
- Use `apply_patch` for manual edits.
- Read/search commands are fine, but they must not rewrite files.
- If a whole-file restore is needed, pause and explain the exact file and source before doing it.
- After editing Python files, run `python -m py_compile` on the touched files.

## Why

PowerShell on Windows can silently write text as UTF-16 or otherwise re-encode
UTF-8 files. In this repo that can corrupt Chinese strings and break Streamlit
pages even when the logical code change is small.
