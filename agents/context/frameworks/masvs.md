# OWASP MASVS (Mobile App Security Verification Standard)

## Goal
Verify the security of Android applications by analyzing storage, cryptography, and interaction with the platform.

## Key Verification Requirements

### MASVS-STORAGE: Storage
*   **Concept**: Sensitive data must be stored securely.
*   **Testing Strategy**:
    *   Check `SharedPreferences` for cleartext credentials.
    *   Analyze SQLite databases for sensitive info.
    *   Check for hardcoded API keys in `strings.xml` or decompiled code.
    *   **Tools**: adb, jadx, mobsf.

### MASVS-CRYPTO: Cryptography
*   **Concept**: Cryptography must be used correctly.
*   **Testing Strategy**:
    *   Identify weak algorithms (MD5, SHA1, DES).
    *   Check for hardcoded encryption keys.
    *   Verify proper implementation of KeyStore.

### MASVS-PLATFORM: Platform Interaction
*   **Concept**: The app must interact safely with other apps and the OS.
*   **Testing Strategy**:
    *   **Exported Components**: Check `AndroidManifest.xml` for exported Activities, Services, and Broadcast Receivers.
    *   **Intents**: Test for Intent Injection or data leakage via Intents.
    *   **Permissions**: Verify requested permissions are necessary (Least Privilege).

## Execution Guidance
*   **Static Analysis (SAST)**: Use `jadx` or `apktool` to reverse engineer the APK. Search for secrets and logic flaws.
*   **Dynamic Analysis (DAST)**: Use `frida` or `objection` to hook methods and inspect memory at runtime (if applicable).
