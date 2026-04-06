# OWASP Web Security Methodology

## Goal
Identify and exploit vulnerabilities based on the OWASP Top 10 and Web Security Testing Guide (WSTG).

## Key Vulnerability Classes

### A01:2021-Broken Access Control
*   **Concept**: Users acting outside of their intended permissions.
*   **Testing Strategy**:
    *   Test IDOR (Insecure Direct Object References) by changing IDs in URLs/parameters.
    *   Test Privilege Escalation (Vertical/Horizontal).
    *   Force browsing to restricted pages.

### A03:2021-Injection
*   **Concept**: Untrusted data is sent to an interpreter as part of a command or query.
*   **Testing Strategy**:
    *   **SQL Injection**: Test all inputs with single quotes, boolean conditions, and time delays.
    *   **Command Injection**: Test inputs with shell operators (`;`, `|`, `&&`).
    *   **XSS**: Test inputs for reflection of HTML/JS tags.

### A07:2021-Identification and Authentication Failures
*   **Concept**: Weaknesses in session management or credential handling.
*   **Testing Strategy**:
    *   Brute force / Credential Stuffing protection.
    *   Session fixation and timeout.
    *   Weak password policies.

## Execution Guidance
*   **Validation**: Always verify findings with a Proof of Concept (PoC).
*   **Tools**: Use available tools (e.g., Burp Suite, OWASP ZAP, sqlmap, etc.) to automate detection, but verify manually.
*   **Reporting**: Classify findings by severity and impact.
