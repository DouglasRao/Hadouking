"""
Dynamic methodology context loader for PentestLLM.

Loads high-level methodology frameworks (OWASP, PTES, MITRE) based on agent type and task keywords.
"""

import os
import re
from typing import List, Dict, Optional, Set
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class ContextLoader:
    """Dynamically load methodology context based on agent type and task."""

    def __init__(self, context_dir: str = None):
        """
        Initialize context loader.
        
        Args:
            context_dir: Path to context directory (default: agents/context)
        """
        if context_dir is None:
            # Resolve the directory relative to this file.
            current_dir = Path(__file__).parent
            context_dir = current_dir

        self.context_dir = Path(context_dir)
        self.cache: Dict[str, str] = {}

        # Verify the directory exists.
        if not self.context_dir.exists():
            logger.warning(f"Context directory not found: {self.context_dir}")

    def load_context(self, category: str, name: str) -> Optional[str]:
        """
        Load a specific context file on-demand.
        
        Args:
            category: Category folder (frameworks, etc.)
            name: Name of file (without .md extension)
        
        Returns:
            Context content or None if not found
        """
        # Build the target path.
        path = self.context_dir / category / f"{name}.md"
        path_str = str(path)

        # Check the cache first.
        if path_str in self.cache:
            return self.cache[path_str]

        # Load from disk.
        if not path.exists():
            logger.warning(f"Context file not found: {path}")
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            # Cache the content for later reuse.
            self.cache[path_str] = content
            return content

        except Exception as e:
            logger.error(f"Error loading context {path}: {e}")
            return None

    def get_relevant_context(
        self,
        agent_type: str,
        task_keywords: List[str]
    ) -> List[str]:
        """
        Select relevant methodology frameworks based on keywords.
        
        Args:
            agent_type: Type of agent
            task_keywords: Keywords extracted from task
        
        Returns:
            List of context contents
        """
        relevant_contexts = []

        # Default frameworks per agent.
        agent_defaults = {
            "bug_bounty_agent": [("frameworks", "owasp")],
            "recon_agent": [("frameworks", "ptes")],
            "pentest_agent": [("frameworks", "ptes"), ("frameworks", "mitre")],
            "osint_agent": [("frameworks", "osint_framework")],
            "redteam_agent": [("frameworks", "osstmm"), ("frameworks", "mitre")],
            "network_security_analyzer_agent": [("frameworks", "osstmm")],
            "android_sast_agent": [("frameworks", "masvs")],
        }
        
        # Keyword-to-framework mapping.
        keyword_map = {
            # OWASP-related
            "xss": ("frameworks", "owasp"),
            "sql": ("frameworks", "owasp"),
            "injection": ("frameworks", "owasp"),
            "idor": ("frameworks", "owasp"),
            "auth": ("frameworks", "owasp"),
            "web": ("frameworks", "owasp"),
            
            # PTES/recon-related
            "recon": ("frameworks", "ptes"),
            "scan": ("frameworks", "ptes"),
            "discovery": ("frameworks", "ptes"),
            "intel": ("frameworks", "ptes"),
            
            # MITRE-related
            "lateral": ("frameworks", "mitre"),
            "privilege": ("frameworks", "mitre"),
            
            # Android / MASVS
            "android": ("frameworks", "masvs"),
            "apk": ("frameworks", "masvs"),
            "mobile": ("frameworks", "masvs"),
            "sast": ("frameworks", "masvs"),
            
            # Network / OSSTMM
            "network": ("frameworks", "osstmm"),
            "port": ("frameworks", "osstmm"),
            "infrastructure": ("frameworks", "osstmm"),
            
            # OSINT
            "osint": ("frameworks", "osint_framework"),
            "email": ("frameworks", "osint_framework"),
            "whois": ("frameworks", "osint_framework"),
        }
        
        # 1. Load defaults for agent
        defaults = agent_defaults.get(agent_type, [])
        for cat, name in defaults:
            content = self.load_context(cat, name)
            if content:
                relevant_contexts.append(content)
                
        # 2. Load specific frameworks based on keywords
        # Avoid duplicates
        loaded_names = {name for _, name in defaults}
        
        for keyword in task_keywords:
            if keyword in keyword_map:
                cat, name = keyword_map[keyword]
                if name not in loaded_names:
                    content = self.load_context(cat, name)
                    if content:
                        relevant_contexts.append(content)
                        loaded_names.add(name)
        
        return relevant_contexts
    
    def extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text"""
        # Simplified keyword extraction
        keywords = {
            "xss", "sql", "injection", "recon", "scan", "osint",
            "auth", "web", "network", "discovery", "intel"
        }
        
        found = []
        text_lower = text.lower()
        for k in keywords:
            if k in text_lower:
                found.append(k)
        return found


# Global instance
_loader_instance = None

def get_loader() -> ContextLoader:
    """Get or create global ContextLoader instance"""
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = ContextLoader()
    return _loader_instance
