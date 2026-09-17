# Uninstall email verification

Flattens the Postmark-derived email settings to a console backend
with verification off, and drops the transactional-mail dependency.
Accounts, sign-in, sign-up, and password reset all stay — this is
the narrow strip; allauth itself is not on the menu.

## Remove

1. `clx/settings.py`: replace the `POSTMARK_SERVER_TOKEN` /
   `DEFAULT_FROM_EMAIL` reads and the `if POSTMARK_SERVER_TOKEN:`
   block with:

   ```python
   EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
   ACCOUNT_EMAIL_VERIFICATION = "none"
   ```

2. `pyproject.toml`: the `django-anymail[postmark]` dependency.
3. `clx/app/template_overrides/account/verification_sent.html`,
   `email_confirm.html`, and `email.html`.
4. `clx/app/signals.py`: in `create_dev_user`, drop the
   `EmailAddress` creation and its allauth import — with
   verification off nothing reads it.
5. `README.md`: the `POSTMARK_SERVER_TOKEN` and
   `DEFAULT_FROM_EMAIL` rows of the secrets table (if the infra
   guide has not already removed the whole section).
6. Grep the tests for `verification`, `postmark`, and
   `EmailAddress` and prune what surfaces.

Run the verify suite.
