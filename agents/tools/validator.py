"""
Tool availability validator for PentestLLM agents.

Validates whether security tools are installed before suggesting commands.
"""

import shutil
import subprocess
from typing import Set, List, Dict
import logging

logger = logging.getLogger(__name__)


class ToolValidator:
    """Validate tool availability before suggesting commands."""

    # Comprehensive list of Kali Linux security tools.
    KALI_TOOLS = {
        # Subdomain Enumeration
        "subfinder", "amass", "assetfinder", "findomain", "chaos",
        "shuffledns", "massdns", "dnsgen", "hakrevdns",
        
        # HTTP Probing & Analysis
        "httpx", "httprobe", "meg", "gowitness",
        
        # Web Crawling
        "gospider", "hakrawler", "katana", "gau", "waybackurls",
        "getJS", "subjs", "linkfinder", "cariddi",
        
        # Fuzzing & Content Discovery
        "ffuf", "feroxbuster", "gobuster", "dirsearch", "wfuzz",
        
        # Port Scanning
        "nmap", "naabu", "masscan", "rustscan",
        
        # Vulnerability Scanning
        "nuclei", "jaeles", "nikto", "wpscan", "sqlmap",
        "xsstrike", "dalfox", "kxss", "airixss", "freq",
        
        # Parameter Discovery
        "arjun", "paramspider", "x8",
        
        # OSINT
        "theHarvester", "whois", "dig", "nslookup", "host",
        "dnsrecon", "dnsenum", "fierce", "sherlock", "socialscan",
        "exiftool", "metagoofil",
        
        # Utilities
        "anew", "qsreplace", "unfurl", "urldedupe", "uro",
        "gf", "gargs", "rush", "jq", "curl", "wget",
        "grep", "awk", "sed", "tr", "sort", "uniq",
        
        # Other Tools
        "whatweb", "wappalyzer", "metabigor", "shodan",
        "cf-check", "filter-resolved", "bhedak", "anti-burl",
        "page-fetch", "html-tool", "tojson", "goop",
        "jsubfinder", "secretfinder", "notify"
    }
    
    def __init__(self):
        """Initialize the validator and inventory available tools."""
        self.available_tools: Set[str] = self._check_tools()
        self.missing_tools: Set[str] = self.KALI_TOOLS - self.available_tools

        if self.missing_tools:
            logger.info(f"Missing {len(self.missing_tools)} tools: {', '.join(sorted(list(self.missing_tools)[:5]))}...")

        logger.info(f"Available tools: {len(self.available_tools)}/{len(self.KALI_TOOLS)}")

    def _check_tools(self) -> Set[str]:
        """Return the set of installed tools."""
        available = set()
        for tool in self.KALI_TOOLS:
            if shutil.which(tool):
                available.add(tool)
        return available

    def is_available(self, tool: str) -> bool:
        """Return whether a specific tool is available."""
        return tool in self.available_tools

    def get_available_tools(self) -> Set[str]:
        """Return a copy of all available tools."""
        return self.available_tools.copy()

    def get_missing_tools(self) -> Set[str]:
        """Return a copy of all missing tools."""
        return self.missing_tools.copy()

    def filter_commands(self, commands: List[str]) -> List[Dict[str, str]]:
        """
        Filter commands based on tool availability.
        
        Returns list of dicts with:
        - command: The command string
        - available: Boolean indicating if all required tools are available
        - missing_tools: List of missing tools (if any)
        """
        filtered = []

        for cmd in commands:
            # Extract the tool name from the first token.
            parts = cmd.strip().split()
            if not parts:
                continue

            tool = parts[0]

            # Check whether the tool is available.
            is_available = self.is_available(tool)

            filtered.append({
                "command": cmd,
                "available": is_available,
                "tool": tool,
                "missing_tools": [] if is_available else [tool],
            })

        return filtered
    
    def get_alternatives(self, tool: str) -> List[str]:
        """Get alternative tools for a given tool"""
        alternatives = {
            "subfinder": ["amass", "assetfinder", "findomain"],
            "amass": ["subfinder", "assetfinder"],
            "ffuf": ["feroxbuster", "gobuster", "wfuzz"],
            "feroxbuster": ["ffuf", "gobuster"],
            "nmap": ["naabu", "masscan", "rustscan"],
            "nuclei": ["jaeles", "nikto"],
            "sqlmap": ["ghauri"],
            "dalfox": ["xsstrike", "kxss"],
        }
        
        return [alt for alt in alternatives.get(tool, []) if self.is_available(alt)]
    
    def suggest_install(self, tool: str) -> str:
        """Suggest installation command for a missing tool"""
        install_commands = {
            "subfinder": "go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest",
            "httpx": "go install -v github.com/projectdiscovery/httpx/cmd/httpx@latest",
            "nuclei": "go install -v github.com/projectdiscovery/nuclei/v2/cmd/nuclei@latest",
            "ffuf": "go install github.com/ffuf/ffuf@latest",
            "katana": "go install github.com/projectdiscovery/katana/cmd/katana@latest",
            "naabu": "go install -v github.com/projectdiscovery/naabu/v2/cmd/naabu@latest",
            "anew": "go install -v github.com/tomnomnom/anew@latest",
            "gau": "go install github.com/lc/gau/v2/cmd/gau@latest",
            "waybackurls": "go install github.com/tomnomnom/waybackurls@latest",
            "qsreplace": "go install github.com/tomnomnom/qsreplace@latest",
            "unfurl": "go install github.com/tomnomnom/unfurl@latest",
            "gf": "go install github.com/tomnomnom/gf@latest",
        }
        
        return install_commands.get(tool, f"# Check tool documentation for installation: {tool}")
    



# Global instance
_validator_instance = None

def get_validator() -> ToolValidator:
    """Get or create global ToolValidator instance"""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = ToolValidator()
    return _validator_instance
