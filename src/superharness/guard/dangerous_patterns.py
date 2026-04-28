"""Dangerous command detection patterns (cherry-picked from hermes-agent).

25 regex patterns detect shell commands that could damage the system.
Source: hermes-agent/tools/approval.py lines 24-52.
"""
import re

# (compiled_regex, human_label)
DANGEROUS_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Filesystem destruction
    (re.compile(r"rm\s+-rf\s+/", re.IGNORECASE), "rm -rf on root"),
    (re.compile(r"rm\s+-rf\s+~", re.IGNORECASE), "rm -rf on home"),
    (re.compile(r"rm\s+-rf\s+\*", re.IGNORECASE), "rm -rf wildcard"),
    (re.compile(r"find\s+.*-exec\s+rm", re.IGNORECASE), "find -exec rm"),
    (re.compile(r"find\s+.*-delete", re.IGNORECASE), "find -delete"),
    (re.compile(r"xargs\s+rm", re.IGNORECASE), "xargs rm"),
    # Device overwrite
    (re.compile(r"dd\s+if=.*of=/dev/", re.IGNORECASE), "dd to block device"),
    (re.compile(r"mkfs\.", re.IGNORECASE), "mkfs format"),
    (re.compile(r">\s*/dev/sd", re.IGNORECASE), "redirect to block device"),
    # Fork bombs
    (re.compile(r":\(\)\s*\{.*:\|:.*\}", re.IGNORECASE), "fork bomb"),
    (re.compile(r"perl\s+-e.*fork", re.IGNORECASE), "perl fork bomb"),
    # Process destruction
    (re.compile(r"kill\s+-9\s+-1", re.IGNORECASE), "kill -9 -1 (all processes)"),
    (re.compile(r"killall\s+-9", re.IGNORECASE), "killall -9"),
    # Pipe to shell
    (re.compile(r"curl.*\|.*(?:ba)?sh", re.IGNORECASE), "curl piped to shell"),
    (re.compile(r"wget.*\|.*(?:ba)?sh", re.IGNORECASE), "wget piped to shell"),
    # Permission escalation
    (re.compile(r"chmod\s+777\s+/", re.IGNORECASE), "chmod 777 on root path"),
    (re.compile(r"chown\s+-R\s+root", re.IGNORECASE), "chown -R root"),
    # Service disruption
    (re.compile(r"systemctl\s+stop\s+(sshd|iptables|firewalld)", re.IGNORECASE), "stop critical service"),
    # SQL destruction
    (re.compile(r"\bDROP\s+(TABLE|DATABASE)\b", re.IGNORECASE), "SQL DROP TABLE/DATABASE"),
    (re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE), "SQL TRUNCATE TABLE"),
    # Config overwrite
    (re.compile(r"tee\s+/etc/", re.IGNORECASE), "tee to /etc"),
    # Variables obscured
    (re.compile(r"\$\{.*:-\}\s*rm\s+-rf", re.IGNORECASE), "obscured variable rm -rf"),
    (re.compile(r"\$\{.*#\*\}.*rm\s+-rf", re.IGNORECASE), "substring removal rm -rf"),
    # Cron/Reboot
    (re.compile(r"shutdown\s+-[rh]", re.IGNORECASE), "shutdown command"),
    (re.compile(r"reboot", re.IGNORECASE), "reboot command"),
]
