# Uninstall Sentry

Removes error reporting. It is entirely env-gated, so this is the
smallest guide: a settings block, a dependency, and a README row.

## Remove

1. `clx/settings.py`: the `sentry_sdk` import, `SENTRY_DSN`,
   `SENTRY_TRACES_SAMPLE_RATE`, `SENTRY_SCRUBBED_HEADERS`,
   `scrub_sentry_event`, and the `if SENTRY_DSN:` init block.
2. `pyproject.toml`: the `sentry-sdk` dependency.
3. `README.md`: the `SENTRY_DSN` row of the secrets table (if the
   infra guide has not already removed the whole section).
4. Grep the tests for `sentry` and prune what surfaces.

Run the verify suite.
