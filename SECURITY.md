# Security

Report suspected vulnerabilities privately to the repository owner through GitHub
private vulnerability reporting when enabled; do not place secrets or exploit data
in public issues. State the affected commit, reproduction, scope and impact with
redacted examples. No response SLA is currently promised.

Production requires HTTPS, secure HttpOnly session cookies, CSRF protection for
mutations, exact CORS origins, tenant-scoped access and least-privilege API keys.
Keep DB/Redis private, rotate compromised credentials immediately and retain audit
records. Review membership roles, API scopes, invitations, SSO/SCIM provisioning and
worker permissions periodically. Never share `.env`, database backups, proxy URLs,
Stripe/webhook keys, MFA/recovery codes or session/CSRF tokens in logs or PRs.

`validate` blocks on dependency audits and redacted Gitleaks scans of fetched git
history plus the current tracked tree. Python packages are locked; cryptography
50.0.1 fixes the audited advisories and is covered by the existing MFA/OIDC/encryption
suite. Frontend uses pinned Fantastic Admin plus `upstream-security.patch`, which
updates vulnerable transitive dependencies without replacing frameworks. The audit
fails on any High/Critical finding. Low/Moderate findings require named scope and
follow-up in docs/hardening/PHASE32.md; audit exceptions must never silently cover
new advisory IDs. Audit databases change, so rerun checks for every release.

Console email emits only configuration status; it never prints message bodies or
reset/invitation tokens. SMTP and webhook error records expose error categories,
not secret URLs or SDK exception bodies. Unexpected API errors return generic JSON
with a request ID. Do not enable request-body/header logging at reverse proxies.

If a real secret is found: revoke/rotate at its provider, invalidate affected sessions
or keys, determine exposure and notify the owner privately. Removing a file is not
revocation. Do not rewrite repository history without an explicit incident plan;
retain the redacted detection and remediation evidence.

The offline CI fixtures cannot prove real provider geography, SMTP delivery, payment
settlement, SSO identity-provider policy or production proxy configuration. Validate
these in a controlled staging environment before production traffic, within approved
budgets. No release is declared solely because fixture tests are green.
