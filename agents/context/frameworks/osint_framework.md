# OSINT Framework Reference

## Purpose
Guide passive intelligence gathering that improves target understanding without intrusive interaction.

## Passive Collection Areas
- Domain and DNS intelligence
- Certificate transparency and subdomain history
- Public code repositories and leaked secrets
- Public documents and metadata
- Breach exposure indicators
- Cloud footprint and bucket enumeration (passive checks)
- Social footprint (employees, roles, technologies)

## Workflow
1. Define target identity set (domains, brands, legal entities, key products).
2. Collect from multiple sources and normalize.
3. Correlate and deduplicate entities.
4. Score confidence and relevance.
5. Output actionable hypotheses for active recon.

## Output Quality Rules
- Every artifact must include source and timestamp.
- Distinguish confirmed facts vs inferred relationships.
- Highlight priority assets for deeper testing.
- Avoid noisy dumps; provide ranked intelligence.

## Execution Guidance
- Default to passive techniques.
- Respect legal boundaries and third-party privacy.
- Use active probing only if explicitly authorized.
