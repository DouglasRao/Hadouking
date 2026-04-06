"""
Markdown report generation (PentestLLM).
"""

import datetime
import os
from typing import List, Dict, Any

class ReportGenerator:
    def __init__(self, agent_name: str, target: str):
        self.agent_name = agent_name
        self.target = target
        self.start_time = datetime.datetime.now()
        self.findings: List[Dict[str, Any]] = []
        self.scope: List[str] = [target]
        self.executive_summary = "Pending analysis..."

    def add_finding(self, title: str, severity: str, description: str, remediation: str = ""):
        """Add a vulnerability finding to the report."""
        self.findings.append({
            "title": title,
            "severity": severity,
            "description": description,
            "remediation": remediation
        })

    def set_executive_summary(self, summary: str):
        """Set the executive summary text."""
        self.executive_summary = summary

    def set_target(self, target: str):
        """Set the target for the report."""
        self.target = target
        if target not in self.scope:
            self.scope.append(target)

    def generate_markdown(self) -> str:
        """Generate the complete Markdown report."""
        report = f"""# Penetration Test Report
**Target:** {self.target}
**Agent:** {self.agent_name}
**Date:** {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}

---

## 1. Executive Summary
{self.executive_summary}

## 2. Scope
The following assets were included in this assessment:
"""
        for item in self.scope:
            report += f"- {item}\n"

        report += """
## 3. Methodology
The assessment was conducted with PentestLLM (LLM-assisted agent), following this methodology:
- **Reconnaissance:** Passive and active information gathering.
- **Vulnerability Scanning:** Automated identification of potential weaknesses.
- **Exploitation (Simulated):** Verification of identified vulnerabilities (where applicable and safe).
- **Reporting:** Documentation of findings and remediation steps.

## 4. Findings Summary
| ID | Title | Severity |
|----|-------|----------|
"""
        for i, finding in enumerate(self.findings, 1):
            report += f"| {i} | {finding['title']} | {finding['severity']} |\n"

        report += "\n## 5. Detailed Findings\n"

        for i, finding in enumerate(self.findings, 1):
            report += f"""
### 5.{i} {finding['title']}
**Severity:** {finding['severity']}

**Description:**
{finding['description']}

**Remediation:**
{finding['remediation']}

---
"""
        return report

    def save_report(self, output_dir: str = ".") -> str:
        """Save the report to a file."""
        filename = f"pentest_report_{self.target.replace('/', '_').replace(':', '_')}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, "w") as f:
            f.write(self.generate_markdown())

        return filepath
