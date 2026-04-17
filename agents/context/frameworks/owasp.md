# OWASP Web Security Testing Guide (WSTG) Reference

## Purpose
Use this as the web and API testing backbone, especially for authenticated business workflows and OWASP Top 10 coverage.

## Core Test Domains (WSTG-aligned)

### Information Gathering (WSTG-INFO)
- Enumerate endpoints, parameters, headers, and exposed technologies.
- Identify hidden routes, admin panels, debug interfaces, and metadata leaks.

### Configuration and Deployment Management (WSTG-CONF)
- Test default credentials, verbose errors, unsafe HTTP methods, and insecure headers.
- Validate TLS posture, CSP, HSTS, CORS, and cache behavior.

### Identity Management (WSTG-IDNT)
- Verify user enumeration and account lifecycle weaknesses.
- Test registration, account recovery, and invitation flows.

### Authentication (WSTG-AUTHN)
- Validate MFA flows, session binding, brute-force resistance, lockout behavior.
- Check credential stuffing protections and password policy enforcement.

### Authorization (WSTG-AUTHZ)
- Test horizontal and vertical privilege escalation.
- Validate object-level access control (IDOR/BOLA).

### Session Management (WSTG-SESS)
- Verify session fixation, timeout, renewal, and invalidation.
- Check cookie flags (`HttpOnly`, `Secure`, `SameSite`) and token leakage.

### Input Validation (WSTG-INPV)
- Test XSS, SQLi, command injection, path traversal, SSRF, template injection.
- Validate input normalization and canonicalization issues.

### Error Handling and Logging (WSTG-ERRH)
- Check stack traces, debug outputs, and sensitive data exposure.
- Validate audit trail integrity and security event visibility.

### Cryptography (WSTG-CRYP)
- Validate token signing, key handling, and insecure algorithm usage.
- Check transport and data-at-rest assumptions.

### Business Logic (WSTG-BUSL)
- Test workflow abuse, race conditions, quota bypass, and state confusion.
- Focus on impact-driven attack scenarios.

### Client-side Testing (WSTG-CLNT)
- Audit client-side secrets, source maps, and dangerous JS sinks.
- Validate CSP bypass opportunities and DOM XSS vectors.

## OWASP API Security Alignment
- API1 BOLA
- API2 Broken Authentication
- API3 Broken Object Property Level Authorization
- API4 Unrestricted Resource Consumption
- API5 Broken Function Level Authorization
- API6 Unrestricted Access to Sensitive Business Flows
- API7 SSRF
- API8 Security Misconfiguration
- API9 Improper Inventory Management
- API10 Unsafe Consumption of APIs

## Execution Guidance
- Always validate findings with reproducible requests.
- Combine automated discovery with manual exploitability checks.
- Classify severity by exploitability + business impact.
