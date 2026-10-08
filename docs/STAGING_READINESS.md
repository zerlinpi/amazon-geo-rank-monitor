# Staging release readiness

Phase 33 provides a repeatable staging verification layer on top of the normal
offline/CI `validate` gate.

## 1. Configure the GitHub staging environment

Create a GitHub Actions environment named `staging`. Restrict who can approve
runs if your repository plan supports environment reviewers.

Set these environment variables:

```text
STAGING_API_URL=https://api-staging.example.com
STAGING_WEB_URL=https://staging.example.com
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_FROM_EMAIL=noreply@example.com
SMTP_STARTTLS=true
RESIDENTIAL_PROXY_SERVER=http://pr.oxylabs.io:7777
```

Set these as environment secrets:

```text
SMTP_USERNAME
SMTP_PASSWORD
STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET
OXYLABS_USERNAME
OXYLABS_PASSWORD
RESIDENTIAL_PROXY_USERNAME
RESIDENTIAL_PROXY_PASSWORD
```

Do not put secrets into repository variables.

## 2. Run the no-transaction staging gate

In **Actions → Staging Readiness → Run workflow**, leave
**paid_provider_probes** disabled.

This proves:

- external HTTPS/TLS reachability of frontend, `/health` and `/ready`;
- production-style cookie/URL/CORS configuration;
- SMTP TLS/authentication and NOOP;
- Stripe API authentication;
- required provider credentials are present.

It does not send email or create a Stripe payment.

## 3. Run controlled provider verification

Before a release that needs full provider evidence, run the workflow again and
explicitly enable **paid_provider_probes**.

Choose a low-impact staging keyword and a five-digit US ZIP.

This performs one managed Amazon Search probe and one Strict browser probe.
Those calls may consume provider credits. The Strict probe verifies exit
geography and Amazon delivery ZIP in the same browser context.

Do not schedule this workflow and do not enable provider probes on ordinary PR
CI.

## 4. Read the evidence

The job uploads `staging-readiness-<run id>` for 30 days. The JSON contains
only check names, pass/fail state and sanitized details. Upstream exception
messages and credential values are deliberately omitted.

A release candidate is ready for human release approval only when:

- the exact source commit has a green required `validate` check;
- the intended staging deployment has a green no-transaction readiness run;
- a full provider run is green when provider geography is release-critical;
- the Phase 32 GitHub main-branch ruleset has been configured and independently
  verified by a repository administrator.

## Local/operator CLI

From an environment configured like staging:

```bash
cd backend
agrm-readiness
agrm-readiness --live
agrm-readiness --live --paid-provider-probes \
  --keyword "walking pad" \
  --postal-code 10001
```

The last command can consume provider credits.

A non-zero exit status means at least one required check failed.
