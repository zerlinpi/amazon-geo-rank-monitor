# Windows desktop executable and Authenticode release requirements

## What is supported today

**Current repository:** FastAPI + worker/scheduler + PostgreSQL/Redis + Fantastic Admin web UI. Supported deployment is server-side Docker Compose and access through an HTTPS browser. The repository does **not** presently contain a Windows desktop shell, `.exe` build, installer, Authenticode signing credential or signed release artifact.

A browser-installed PWA/shortcut is **not** equivalent to a signed Windows `.exe`, and bundling an API Python entrypoint with PyInstaller alone does not package PostgreSQL, Redis, the web frontend, secure secrets, reverse proxy or operational data safely. Do not publish such a binary as a complete/offline product.

## Choose a supported packaging architecture first

| Option | Description | Windows .exe? | Data / network |
|---|---|---|---|
| Existing Web SaaS | HTTPS frontend hosted on a server; Chrome/Edge browser on Windows | No | Server stores data; requires network |
| Desktop client to SaaS (proposed) | Separate signed Windows shell using WebView2/Tauri, authenticated against HTTPS API | Yes, after implementation | Server stores data; requires network |
| Fully offline desktop (separate large project) | Bundled local API, a compatible local database, local job runner, managed upgrades and offline limitations | Yes, after redesign | Strict/Managed Amazon collection still needs network/provider credentials |

**Recommendation for minimum risk:** preserve the existing server deployment; if a native Windows binary is a confirmed product requirement, plan a **separate desktop client**. Prefer the OS WebView2 runtime instead of shipping an additional Chromium copy when functional and security requirements permit. Do not silently wrap an arbitrary remote URL with unrestricted native API access. A desktop app should allowlist the authorized HTTPS domain, enforce a tight content security policy, and avoid persisting session/API/provider secrets in a plaintext local file.

## Signing prerequisites

A working Windows code-signing release requires all of:

1. A separately implemented, tested desktop executable/installer and reproducible Windows CI build.
2. A legitimate code-signing certificate in the publisher's legal identity, with a securely managed private key (Windows certificate store, hardware token, cloud signing service or protected CI identity).
3. Windows SDK **SignTool** and an approved RFC 3161 timestamp service.
4. Signature verification, publisher validation, malware scanning, Windows 10/11 installer/uninstaller tests, upgrade/rollback tests and test signing of **every distributed executable**.
5. Restricted release environment and reviewed PR/commit; no certificate private key, PFX password, access tokens or signing outputs containing secrets committed into this repository.

Self-signed certificates may be useful for internal testing but do not provide public publisher trust. Authenticode cryptographic validity does **not** guarantee Windows SmartScreen reputation or that an unsigned bundled dependency will be trusted.

## Example Windows signing and verification

This is an **operator example for an already built `.exe`**, not a build recipe or evidence that one exists. Install the Windows SDK and make `signtool.exe` available. Configure a certificate in the Windows signing certificate store or use the provider-approved cloud signing flow. From a restricted Windows release session:

```powershell
# Replace paths and thumbprint with real, authorized values.
$exe = "C:\release\AmazonGeoRankMonitor-Setup.exe"
$thumbprint = "<CODE_SIGNING_CERT_THUMBPRINT>"

if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "Installer not built" }
& signtool.exe sign /sha1 $thumbprint /fd SHA256 /tr "http://timestamp.digicert.com" /td SHA256 $exe
if ($LASTEXITCODE -ne 0) { throw "Code signing failed" }

& signtool.exe verify /pa /all /v $exe
if ($LASTEXITCODE -ne 0) { throw "Signature verification failed" }

$sig = Get-AuthenticodeSignature -LiteralPath $exe
if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Thumbprint -ne $thumbprint) {
    throw "Unexpected signature or publisher certificate"
}
Get-FileHash -LiteralPath $exe -Algorithm SHA256
```

This example assumes `/sha1` can locate the authorized code-signing certificate and associated private key in the signing environment; hardware/cloud signing workflows may use a different provider command. For release, verify certificate issuer, EKU (code signing), validity/revocation policy and expected publisher subject through your signing service and deployment QA. Timestamp outages must fail the release gate rather than silently produce an untimestamped artifact. Follow Windows SDK documentation for the supported SignTool version.

## Proposed Windows desktop acceptance tests

- Launch, resize/minimize/maximize, high-DPI 100%/125%/150%, multi-monitor, sleep/resume, network loss/reconnect and clean shutdown.
- Windows 10/11 x64; Windows 11 ARM64 only if officially supported by the selected runtime.
- First install, upgrade, uninstall, shortcut, installation without admin where supported and installer cancellation.
- Browser renderer main-thread latency, memory baseline, animation jank, accessibility and reduced-motion behavior.
- User login, expired session, MFA/SSO, CSRF, deep links, blocked arbitrary navigation and enforced HTTPS/TLS.
- Server unavailable: show explicit retry state, never crash or expose local credentials.
- Installer and `exe` cryptographic signature/publisher checks, checksum artifact, Windows Defender scan and protected CI release approvals.
- Cold start and 8-hour soak under realistic data/network conditions with Windows Error Reporting collection and crash diagnostics.
- PR validates desktop tests separately; **do not reuse green SaaS CI as proof the Windows binary is stable**.

## Release gate

Until a tested desktop entrypoint, Windows-specific CI, installer packaging, signing identity and verification jobs exist, status must remain **Windows signed .exe: NOT IMPLEMENTED / NOT RELEASED**.

Continue production deployment via [DEPLOYMENT.md](DEPLOYMENT.md). For existing service operation see [Chinese user guide](USER_GUIDE.zh-CN.md) and [stability runbook](PERFORMANCE_STABILITY.md).
