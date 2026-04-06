# OSSTMM (Open Source Security Testing Methodology Manual)

## Goal
Conduct a scientific and measurable security test of the network and infrastructure.

## Key Channels

### Network Security
*   **Goal**: Assess the security of network devices, ports, and protocols.
*   **Testing Strategy**:
    *   **Port Scanning**: Identify all open ports and running services (TCP/UDP).
    *   **Service Enumeration**: Grab banners, identify versions.
    *   **Vulnerability Scanning**: Check for known CVEs in services.
    *   **Tools**: nmap, masscan, nessus (if available).

### Access Control
*   **Goal**: Verify that access controls are effective.
*   **Testing Strategy**:
    *   Test for default credentials on network devices (routers, switches).
    *   Attempt to bypass segmentation (VLAN hopping).
    *   Test for weak authentication protocols (Telnet, FTP, HTTP Basic).

### Trust Verification
*   **Goal**: Verify trust relationships between systems.
*   **Testing Strategy**:
    *   Check for excessive trust (e.g., unrestricted NFS exports).
    *   Analyze man-in-the-middle possibilities (ARP spoofing).

## Red Team Specifics (Adversary Simulation)
*   **Initial Access**: Phishing, exploiting public-facing apps.
*   **Persistence**: Creating scheduled tasks, adding users, web shells.
*   **Lateral Movement**: Pass-the-Hash, SSH key pivoting.
*   **C2**: Establishing Command and Control channels.

## Execution Guidance
*   **Rules of Engagement**: Strictly follow the defined scope and timing.
*   **Stealth**: For Red Team, prioritize stealth over speed. Use slow scan rates.
