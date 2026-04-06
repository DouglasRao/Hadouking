# OSINT Framework

## Goal
Gather intelligence from open sources to map the target's digital footprint without direct interaction.

## Categories

### Domain Intelligence
*   **Goal**: Map the infrastructure associated with the domain.
*   **Strategy**:
    *   **Registrar Info**: WHOIS data (registrant, dates).
    *   **DNS Records**: A, MX, TXT, NS records.
    *   **Subdomains**: Passive enumeration (Certificate Transparency, Search Engines).

### Email & User Intelligence
*   **Goal**: Identify people and contact points.
*   **Strategy**:
    *   **Breach Data**: Check if emails have been compromised (HaveIBeenPwned).
    *   **Social Media**: LinkedIn (employees), Twitter, GitHub.
    *   **Pattern Analysis**: Identify email naming conventions (e.g., first.last@company.com).

### Cloud & Infrastructure
*   **Goal**: Identify cloud assets.
*   **Strategy**:
    *   **Buckets**: AWS S3, Azure Blobs, Google Cloud Storage.
    *   **CDN**: Identify Content Delivery Networks (Cloudflare, Akamai).

## Execution Guidance
*   **Passive Only**: Do not send packets to the target's infrastructure if strictly OSINT.
*   **Correlation**: Connect the dots. An email found on GitHub might lead to a login portal.
*   **Tools**: theHarvester, spiderfoot, maltego (conceptually), Google Dorks.
