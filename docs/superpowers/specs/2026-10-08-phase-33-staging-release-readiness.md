# Phase 33 — Staging Release Readiness

## Goal

Close the release-evidence gap left by Phase 32 without adding a new business
subsystem or automatically creating a release tag.

Phase 32 proves the product offline and in deterministic CI. Phase 33 adds a
repeatable, secret-safe staging verification path for the external integrations
that cannot be proven by offline CI:

- deployed HTTPS frontend/API surfaces;
- SMTP authentication;
- Stripe API authentication;
- Oxylabs managed Amazon Search;
- Strict residential-proxy + browser geography verification.

## Safety model

The new `agrm-readiness` command never prints configured secrets, usernames or
upstream exception messages.

Failures are reported only as the check name and exception class, for example:

```json
{"name":"stripe_live","status":"fail","detail":"failed (AuthenticationError)"}
```

This output is safe to retain as CI evidence.

## Check levels

### Configuration checks

Every invocation validates release-oriented configuration:

- secure session cookies;
- HTTPS public web, SSO callback and Stripe return URLs;
- HTTPS-only CORS origins;
- SMTP host/from address;
- Stripe API + webhook credentials;
- managed provider credentials;
- strict residential proxy credentials.

These checks make no network requests.

### Non-transactional live checks

`agrm-readiness --live` adds:

- SMTP connect/EHLO, optional STARTTLS, optional login and NOOP;
- Stripe Balance retrieval to prove API authentication.

It does not send email, create Checkout sessions, charge cards or create rank
jobs.

Each live check is bounded to 30 seconds.

### Explicit paid provider checks

`--paid-provider-probes` is opt-in and may consume provider credits.

It performs exactly one controlled managed probe and one Strict browser probe
using the supplied keyword and five-digit US ZIP. The Strict probe must verify
the proxy geography and Amazon Deliver-to ZIP in the same browser context,
preserving the existing strict-verification contract.

Each paid provider check is bounded to 180 seconds.

## GitHub Actions

`.github/workflows/staging-readiness.yml` is manual-only
(`workflow_dispatch`) and uses the protected `staging` environment.

The workflow first verifies the deployed surfaces externally:

- `STAGING_API_URL/health`;
- `STAGING_API_URL/ready`;
- `STAGING_WEB_URL/`.

Requests require HTTPS and TLS 1.2 or newer.

It then runs `agrm-readiness --live`. Paid provider probes run only when the
operator explicitly selects the workflow input.

The sanitized JSON report is uploaded as a 30-day workflow artifact.

## Required staging environment

Repository/environment variables:

- `STAGING_API_URL`;
- `STAGING_WEB_URL`;
- `SMTP_HOST`;
- `SMTP_PORT` (default 587);
- `SMTP_FROM_EMAIL`;
- `SMTP_STARTTLS` (default true);
- optional `RESIDENTIAL_PROXY_SERVER`.

Environment secrets:

- `SMTP_USERNAME`;
- `SMTP_PASSWORD`;
- `STRIPE_SECRET_KEY`;
- `STRIPE_WEBHOOK_SECRET`;
- `OXYLABS_USERNAME`;
- `OXYLABS_PASSWORD`;
- `RESIDENTIAL_PROXY_USERNAME`;
- `RESIDENTIAL_PROXY_PASSWORD`.

The workflow intentionally fails when mandatory release configuration is
missing.

## Release rule

Phase 33 does not automatically publish `v1.0.0`.

A release should require both:

1. the normal exact-commit `validate` check; and
2. a successful manual Staging Readiness run against the intended release
   deployment.

For full provider evidence, the operator must explicitly enable paid provider
probes. A run without that option proves deployment, SMTP and Stripe readiness
but does not prove paid Amazon geography behavior.

## Non-goals

- no automatic production deployment;
- no automatic tag/release creation;
- no email delivery to a real recipient;
- no Stripe payment creation;
- no background polling of third-party credentials;
- no relaxation of Phase 32 security or tenant boundaries.
