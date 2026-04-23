# PTES Reference for Hadouking

## Purpose
Use PTES (Penetration Testing Execution Standard) as the default backbone for end-to-end offensive security engagements.

## PTES Phases
1. Pre-engagement Interactions
2. Intelligence Gathering
3. Threat Modeling
4. Vulnerability Analysis
5. Exploitation
6. Post-Exploitation
7. Reporting

## Phase Checklist

### 1) Pre-engagement Interactions
- Confirm explicit authorization, legal scope, and permitted techniques.
- Define target inventory (domains, CIDRs, applications, APIs, repos, cloud assets).
- Define constraints (time window, rate limits, excluded assets, data handling).
- Define severity model and evidence expectations.

### 2) Intelligence Gathering
- Passive recon first: DNS, WHOIS, CT logs, ASN, historical URLs, exposed metadata.
- Active recon second: host discovery, service discovery, endpoint discovery.
- Build an asset graph: subdomains, IPs, services, technologies, auth surfaces.
- Track confidence for each discovered artifact.

### 3) Threat Modeling
- Identify trust boundaries and data flows.
- Prioritize attack paths by exposure + business impact.
- Map entry points to likely attacker goals.
- Define test hypotheses before heavy scanning.

### 4) Vulnerability Analysis
- Enumerate misconfigurations, known CVEs, weak auth, and logic flaws.
- Combine automated scanning with manual verification.
- Validate exploitability and remove false positives early.
- Keep findings tied to exact asset + endpoint.

### 5) Exploitation
- Execute safe PoCs only within allowed scope.
- Prove impact with minimal disruption.
- Prefer deterministic and reproducible payloads.
- Stop escalation if authorization boundaries are reached.

### 6) Post-Exploitation
- Demonstrate realistic impact (access level, blast radius, persistence risk).
- Collect only minimal evidence necessary.
- Avoid destructive actions unless explicitly authorized.
- Map pivot opportunities but do not exceed scope.

### 7) Reporting
- Deliver executive summary + technical details.
- Include: evidence, reproduction steps, impact, remediation.
- Group findings by attack path and business risk.
- Provide prioritized remediation roadmap.

## Role Mapping for Subagents
- `recon_passive`: phase 2 passive data collection.
- `recon_active`: phase 2 active discovery and service enumeration.
- `vuln_scanner`: phase 4 automated detection.
- `code_review`: phase 3-4 source-assisted analysis.
- `exploit_validation`: phase 5 impact validation.
- `reporting`: phase 7 consolidation.
- `pentest_brain`: orchestrates priorities and dependencies across all phases.

## Execution Guidance
- Preserve chain-of-custody for evidence.
- Prefer fast, low-noise checks before aggressive scans.
- Every action must map to scope and a clear hypothesis.
