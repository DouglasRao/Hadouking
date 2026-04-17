# MITRE ATT&CK Reference for Adversary Emulation

## Purpose
Map pentest and red-team activities to ATT&CK tactics and techniques so findings can be understood in an attacker-behavior context.

## High-Value Tactics for Pentest Workflows
- Reconnaissance (TA0043)
- Resource Development (TA0042)
- Initial Access (TA0001)
- Execution (TA0002)
- Persistence (TA0003)
- Privilege Escalation (TA0004)
- Defense Evasion (TA0005)
- Credential Access (TA0006)
- Discovery (TA0007)
- Lateral Movement (TA0008)
- Collection (TA0009)
- Exfiltration (TA0010)
- Command and Control (TA0011)

## Example Technique Anchors
- T1595 Active Scanning
- T1190 Exploit Public-Facing Application
- T1059 Command and Scripting Interpreter
- T1110 Brute Force
- T1552 Unsecured Credentials
- T1021 Remote Services
- T1041 Exfiltration Over C2 Channel

## How to Use in Reports
- Attach ATT&CK tactic/technique IDs to each confirmed finding.
- Describe realistic attacker objective enabled by the weakness.
- Prioritize mitigations that break complete attack chains.

## Execution Guidance
- Use ATT&CK as a classification layer, not a substitute for validation.
- Keep PoCs focused on impact, not tool novelty.
