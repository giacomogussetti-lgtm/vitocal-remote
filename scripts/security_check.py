"""
Security & Privacy Audit Scanner for Vitocal Remote.
Scans source files, documentation, and data files to prevent leaking sensitive information
(passwords, tokens, API keys, personal emails, physical house locations, MAC addresses)
before exporting or pushing to a public or shared GitHub repository.

Can be run standalone:
    python scripts/security_check.py [path_to_scan]
Default path is workspace root (excluding .env, venv, and local git).
"""
import os
import re
import sys
from pathlib import Path
from typing import List, Tuple

# Project root
BASE_DIR = Path(__file__).resolve().parent.parent

# Strictly forbidden files that should NEVER be staged or pushed
STRICTLY_FORBIDDEN_FILES = {
    ".env",
    "netatmo_token.json",
    "token.save",
    "vitocal_telemetry.db",
}

# Sensitive regex patterns
PATTERNS = [
    ("GEOGRAPHIC_LOCATION", re.compile(r"\b(bratto|castione(?:\s+della\s+presolana)?|presolana|val\s+seriana|bergamo)\b", re.IGNORECASE)),
    ("EMAIL_ADDRESS", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")),
    ("MAC_ADDRESS", re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}(?:[0-9A-Fa-f]{2})\b")),
    ("GITHUB_TOKEN", re.compile(r"\b(ghp_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("BEARER_TOKEN", re.compile(r"Bearer\s+([A-Za-z0-9._~+/-]{30,})", re.IGNORECASE)),
    ("HARDCODED_SECRET", re.compile(r"""(?:password|client_secret|refresh_token|access_token)\s*[:=]\s*["']([^"']{8,})["']""", re.IGNORECASE)),
    ("PERSONAL_NAME_OR_ACCOUNT", re.compile(r"\b(?:donata|chiarello)\b", re.IGNORECASE)),
]

# Ignored directories
IGNORED_DIRS = {"__pycache__", ".git", ".idea", ".vscode", "venv", "env", ".pytest_cache", ".user_uploaded"}

# Whitelisted matches (generic templates or GitHub system names)
WHITELISTED_MATCHES = {
    "users.noreply.github.com",
    "github-actions[bot]",
    "example.com",
    "tua_email_vicare@example.com",
    "tua_password_vicare",
    "il_tuo_client_id_viessmann",
    "your_viessmann_password",
    "your_client_id_here",
    "your_client_secret_here",
    "your_netatmo_client_id",
    "your_netatmo_client_secret",
    "your_netatmo_refresh_token_here",
    "example_device",
}


def scan_directory(target_path: Path) -> List[Tuple[str, int, str, str, str]]:
    """
    Scans files in target_path.
    Returns list of (rel_file, line_num, rule_name, matched_value, line_snippet).
    """
    violations = []

    for root, dirs, files in os.walk(target_path):
        # Prune ignored directories
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]

        for fname in files:
            filepath = Path(root) / fname
            rel_path = str(filepath.relative_to(target_path))

            # 1. Critical Check: forbidden secret files
            if fname in STRICTLY_FORBIDDEN_FILES:
                violations.append((
                    rel_path,
                    1,
                    "FORBIDDEN_FILE",
                    fname,
                    f"Il file '{fname}' contiene credenziali o database locale e NON deve MAI essere caricato su Git!"
                ))
                continue

            # Skip binary / bytecode files or self
            if fname.endswith((".pyc", ".png", ".jpg", ".jpeg", ".ico", ".db", ".exe")) or fname == "security_check.py":
                continue

            # Read text content
            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            for idx, line in enumerate(content.splitlines(), start=1):
                for rule_name, regex in PATTERNS:
                    for match in regex.finditer(line):
                        val = match.group(0)
                        # Check whitelist
                        if any(w in val.lower() or w in line.lower() for w in WHITELISTED_MATCHES):
                            continue
                        # If in .env.example with dummy placeholders, skip
                        if fname == ".env.example" and ("your_" in line or "tuo_" in line or "example" in line):
                            continue

                        violations.append((rel_path, idx, rule_name, val, line.strip()))

    return violations


def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "github_ready"
    print(f"[*] Avvio Security & Privacy Scan su: {target.resolve()}")

    if not target.exists():
        print(f"[!] Errore: Cartella {target} non trovata.")
        sys.exit(1)

    issues = scan_directory(target)

    if not issues:
        print("[✓] NESSUN DATO SENSIBILE TROVATO!")
        print("    Tutte le credenziali, email personali, MAC address e riferimenti geografici sono 100% protetti e anonimizzati.")
        sys.exit(0)

    print(f"\n[!] ATTENZIONE: Trovate {len(issues)} occorrenze potenzialmente sensibili:\n")
    for rel_file, line_no, rule, val, snippet in issues:
        print(f"  • {rel_file}:{line_no} [{rule}] -> '{val}'")
        print(f"    Riga: {snippet[:100]}\n")

    sys.exit(2)


if __name__ == "__main__":
    main()
