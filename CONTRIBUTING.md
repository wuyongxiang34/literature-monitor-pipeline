# Contributing

Thank you for helping improve Literature Monitor Pipeline.

## Development setup

On Windows 10/11 with Python 3.11 or later:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
.\.venv\Scripts\python.exe run.py profiles validate es_hwb
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Pull requests

1. Keep changes focused and explain the user-visible behavior.
2. Add or update tests for query compilation, profile handling, data-source behavior, or output changes.
3. Run the complete test suite before opening a pull request.
4. Do not commit `.env`, API keys, local profiles, browser data, databases, logs, generated reports, or licensed database exports.
5. Preserve backward compatibility unless the pull request clearly documents a migration.

## Search-rule changes

WoS query behavior must be supported by Clarivate's official search-field, search-rule, or operator documentation. Provider-specific translations must not claim semantics the target API does not support.
