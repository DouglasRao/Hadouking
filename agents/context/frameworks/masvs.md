# OWASP MASVS Reference (Mobile)

## Purpose
Provide a concise baseline for Android/iOS security assessment when mobile scope is authorized.

## Control Families
- MASVS-ARCH: Architecture and threat modeling
- MASVS-STORAGE: Local data storage and secrets
- MASVS-CRYPTO: Cryptographic usage
- MASVS-AUTH: Authentication and session handling
- MASVS-NETWORK: Transport security and certificate handling
- MASVS-PLATFORM: OS interaction and permission boundaries
- MASVS-CODE: Code quality and anti-tamper resilience
- MASVS-RESILIENCE: Reverse engineering and runtime protections

## Android-focused Checks
- Exported components and intent exposure
- Insecure WebView settings
- Hardcoded credentials and API keys
- Root/jailbreak bypass weaknesses
- Certificate pinning implementation flaws

## Execution Guidance
- Combine static review with runtime validation.
- Tie findings to data exposure and exploitability.
- Keep mobile evidence reproducible (APK hash, build, device context).
