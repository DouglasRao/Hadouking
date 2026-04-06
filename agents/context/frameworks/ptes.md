# PTES: Intelligence Gathering & Modeling

## Phase 1: Intelligence Gathering (Recon)
*   **Goal**: Collect as much information as possible about the target to identify attack vectors.
*   **Passive Recon**:
    *   Gather info without interacting directly (WHOIS, DNS records, Search Engines, Social Media).
    *   Tools: theHarvester, subfinder (passive mode), Shodan.
*   **Active Recon**:
    *   Interact with the target to map infrastructure (Port scanning, DNS brute forcing, Crawling).
    *   Tools: nmap, amass, gobuster, ffuf.

## Phase 2: Threat Modeling
*   **Goal**: Identify the most effective attack method based on gathered intel.
*   **Strategy**:
    *   Analyze technologies (Wappalyzer, whatweb).
    *   Identify potential entry points (Login pages, APIs, File uploads).
    *   Map out the application logic.

## Phase 3: Vulnerability Analysis
*   **Goal**: Discover flaws that can be exploited.
*   **Strategy**:
    *   Automated Scanning (nuclei, nikto).
    *   Manual Fuzzing (Burp Intruder, ffuf).
    *   Logic testing.

## Execution Guidance
*   **Stealth**: Be aware of noise levels. Passive recon is silent; active recon is noisy.
*   **Scope**: Strictly adhere to the defined scope. Do not scan out-of-scope assets.
