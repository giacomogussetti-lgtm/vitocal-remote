"""
Utility script to prepare a clean, sanitized export folder for GitHub.
Copies only safe project files, strips bytecode (__pycache__), and
runs the security & privacy audit before finishing.
"""
import os
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

TARGET_DIR = BASE_DIR / "github_ready"

ITEMS_TO_COPY = [
    ".github",
    "api",
    "data/cloud_telemetry.jsonl",
    "data/archive",
    "models",
    "scripts",
    "storage",
    "ui",
    "web",
    ".env.example",
    ".gitignore",
    "AGENTS.md",
    "app.py",
    "avvia_gestionale.bat",
    "avvia_app_mobile.bat",
    "sblocca_firewall_mobile.bat",
    "config.py",
    "PROJECT_STATUS.md",
    "README.md",
    "requirements.txt",
    "requirements_cloud.txt",
    "test_bench.py",
    "web_server.py",
]


def prepare_export():
    print(f"[*] Preparazione cartella pulita per GitHub: {TARGET_DIR}")

    if TARGET_DIR.exists():
        for child in TARGET_DIR.iterdir():
            try:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            except Exception as e:
                print(f"[!] Warning cleaning {child.name}: {e}")
    else:
        TARGET_DIR.mkdir(parents=True, exist_ok=True)

    for rel_item in ITEMS_TO_COPY:
        src = BASE_DIR / rel_item
        dst = TARGET_DIR / rel_item
        if not src.exists():
            print(f"[-] Salto (non trovato): {rel_item}")
            continue

        if src.is_dir():
            shutil.copytree(
                src,
                dst,
                ignore=shutil.ignore_patterns(
                    "__pycache__",
                    "*.pyc",
                    "*.db",
                    "token.save",
                    "netatmo_token.json",
                    ".env*",
                ),
            )
            print(f"[+] Cartella copiata: {rel_item}")
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            print(f"[+] File copiato: {rel_item}")

    # Remove any forbidden files that might have been copied inadvertently
    from scripts.security_check import STRICTLY_FORBIDDEN_FILES
    for root, dirs, files in os.walk(TARGET_DIR):
        for f in files:
            if f in STRICTLY_FORBIDDEN_FILES:
                forbidden_path = Path(root) / f
                forbidden_path.unlink(missing_ok=True)
                print(f"[!] Rimosso file proibito da export: {f}")

    print("\n[*] Esecuzione Security & Privacy Audit automatico...")
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    from scripts.security_check import scan_directory

    issues = scan_directory(TARGET_DIR)
    if issues:
        print(f"\n[!] ERRORE: Trovati {len(issues)} dati sensibili in github_ready!")
        for rel_file, line_no, rule, val, snippet in issues:
            print(f"  • {rel_file}:{line_no} [{rule}] -> '{val}'")
            print(f"    {snippet[:90]}")
        sys.exit(1)
    else:
        print("[✓] AUDIT SUPERATO AL 100%! La cartella 'github_ready' è pulita, priva di segreti e pronta per GitHub.")


if __name__ == "__main__":
    prepare_export()
