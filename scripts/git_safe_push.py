"""
Race-free Git commit & push helper for concurrent GitHub Actions workflows
(telemetry_logger.yml and apply_command.yml).

Prevents merge conflicts when a scheduled telemetry run and an on-demand PWA
command modify data/cloud_telemetry.jsonl or data/autopilot_state.json at the
same second.
"""
import argparse
import gzip
import json
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("git_safe_push")


def _run_git(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    res = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed ({res.returncode}): {res.stderr.strip() or res.stdout.strip()}")
    return res


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts))
        return dt
    except Exception:
        return None


def _parse_json_safe(raw: str | bytes | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def merge_jsonl_lines(
    remote_text: str,
    local_text: str,
    exclude_timestamps: Optional[set[str]] = None,
) -> str:
    """
    Merges two JSONL telemetry buffers by deduplicating on `timestamp_utc`
    (preserving exact JSON lines and sorting chronologically).
    When the same timestamp appears in both, local replaces remote unless excluded.
    """
    excluded = exclude_timestamps or set()
    by_key: dict[str, tuple[str, str]] = {}
    fallback_seq = 0

    for src_text in (remote_text, local_text):
        if not src_text:
            continue
        for raw_ln in src_text.splitlines():
            ln = raw_ln.strip()
            if not ln:
                continue
            ts = ""
            try:
                rec = json.loads(ln)
                if isinstance(rec, dict):
                    ts = str(rec.get("timestamp_utc") or "")
            except Exception:
                ts = ""
            if ts and ts in excluded:
                continue
            if ts:
                by_key[f"ts:{ts}"] = (ts, ln)
            else:
                fallback_seq += 1
                by_key[f"raw:{fallback_seq}"] = (f"zzzz:{fallback_seq:08d}", ln)

    ordered = sorted(by_key.values(), key=lambda pair: pair[0])
    if not ordered:
        return ""
    return "\n".join(ln for _, ln in ordered) + "\n"


def merge_gzip_jsonl_bytes(remote_bytes: bytes | None, local_bytes: bytes | None) -> bytes:
    """Merges two gzip-compressed JSONL archive files without duplicating samples."""
    remote_txt = gzip.decompress(remote_bytes).decode("utf-8", errors="replace") if remote_bytes else ""
    local_txt = gzip.decompress(local_bytes).decode("utf-8", errors="replace") if local_bytes else ""
    merged_txt = merge_jsonl_lines(remote_txt, local_txt)
    return gzip.compress(merged_txt.encode("utf-8"))


def _extract_timestamps(jsonl_text: str) -> set[str]:
    out: set[str] = set()
    for raw_ln in jsonl_text.splitlines():
        ln = raw_ln.strip()
        if not ln:
            continue
        try:
            rec = json.loads(ln)
            ts = rec.get("timestamp_utc") if isinstance(rec, dict) else None
            if ts:
                out.add(str(ts))
        except Exception:
            pass
    return out


def should_preserve_remote_state(
    remote_cfg: dict[str, Any],
    local_cfg: dict[str, Any],
    remote_state: dict[str, Any],
    local_state: dict[str, Any],
) -> bool:
    """
    In telemetry mode, returns True if a concurrent command modified autopilot_config
    or wrote a newer last_action_utc on remote, so telemetry won't clobber it.
    """
    if remote_cfg and local_cfg and remote_cfg.get("enabled") != local_cfg.get("enabled"):
        return True
    rem_act = _parse_iso(remote_state.get("last_action_utc"))
    loc_act = _parse_iso(local_state.get("last_action_utc"))
    if rem_act is not None and (loc_act is None or rem_act > loc_act):
        return True
    return False


def _snapshot_local_state(file_args: list[str]) -> dict[str, Any]:
    snap: dict[str, Any] = {
        "files": {},       # rel_path -> bytes
        "archives": {},    # rel_path -> bytes
        "cfg": {},
        "state": {},
    }
    for rel in file_args:
        p = Path(rel)
        if not p.exists():
            continue
        if p.is_dir():
            for gz in sorted(p.glob("*.jsonl.gz")):
                snap["archives"][gz.as_posix()] = gz.read_bytes()
        else:
            snap["files"][p.as_posix()] = p.read_bytes()

    cfg_path = Path("data/autopilot_config.json")
    if cfg_path.exists():
        snap["cfg"] = _parse_json_safe(cfg_path.read_bytes())
    st_path = Path("data/autopilot_state.json")
    if st_path.exists():
        snap["state"] = _parse_json_safe(st_path.read_bytes())
    return snap


def _apply_merged_snapshot(mode: str, file_args: list[str], snap: dict[str, Any]) -> list[str]:
    """Applies local snapshot onto the freshly reset remote tree and returns paths to stage."""
    paths_to_stage: list[str] = []
    local_files: dict[str, bytes] = snap["files"]
    local_archives: dict[str, bytes] = snap["archives"]
    archived_timestamps: set[str] = set()

    # 1. Merge archive files first so we know any timestamps that were rotated out of hot JSONL
    if any(Path(f).as_posix() == "data/archive" for f in file_args) or local_archives:
        archive_dir = Path("data/archive")
        if local_archives:
            archive_dir.mkdir(parents=True, exist_ok=True)
        for rel_gz, loc_bytes in local_archives.items():
            gz_path = Path(rel_gz)
            rem_bytes = gz_path.read_bytes() if gz_path.exists() else None
            if rem_bytes == loc_bytes:
                continue
            merged_gz = merge_gzip_jsonl_bytes(rem_bytes, loc_bytes)
            gz_path.write_bytes(merged_gz)
            archived_timestamps |= _extract_timestamps(gzip.decompress(merged_gz).decode("utf-8", errors="replace"))
            paths_to_stage.append(rel_gz)

    # 2. Merge data/cloud_telemetry.jsonl cleanly across concurrent runs
    jsonl_rel = "data/cloud_telemetry.jsonl"
    if jsonl_rel in local_files:
        jsonl_path = Path(jsonl_rel)
        rem_text = jsonl_path.read_text(encoding="utf-8", errors="replace") if jsonl_path.exists() else ""
        loc_text = local_files[jsonl_rel].decode("utf-8", errors="replace")
        merged_text = merge_jsonl_lines(rem_text, loc_text, exclude_timestamps=archived_timestamps or None)
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        jsonl_path.write_text(merged_text, encoding="utf-8")
        paths_to_stage.append(jsonl_rel)

    # 3. Mode-specific handling for config / command receipt / autopilot state / models / weather
    if mode == "command":
        for rel in (
            "data/last_command.json",
            "data/autopilot_config.json",
            "data/autopilot_state.json",
            "data/thermal_model.json",
            "data/weather_forecast.json",
        ):
            if rel in local_files:
                p = Path(rel)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(local_files[rel])
                paths_to_stage.append(rel)
    else:
        # Telemetry mode NEVER overwrites autopilot_config.json or last_command.json
        for rel in ("data/thermal_model.json", "data/weather_forecast.json"):
            if rel in local_files:
                p = Path(rel)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(local_files[rel])
                paths_to_stage.append(rel)

        st_rel = "data/autopilot_state.json"
        if st_rel in local_files:
            st_path = Path(st_rel)
            cfg_path = Path("data/autopilot_config.json")
            rem_cfg = _parse_json_safe(cfg_path.read_bytes()) if cfg_path.exists() else {}
            rem_state = _parse_json_safe(st_path.read_bytes()) if st_path.exists() else {}
            if should_preserve_remote_state(rem_cfg, snap["cfg"], rem_state, snap["state"]):
                logger.info("Stato remoto più recente o comando concorrente rilevato: preservo data/autopilot_state.json remoto.")
            else:
                st_path.parent.mkdir(parents=True, exist_ok=True)
                st_path.write_bytes(local_files[st_rel])
                paths_to_stage.append(st_rel)

    # Deduplicate preserving order
    return list(dict.fromkeys(paths_to_stage))


def safe_commit_and_push(
    mode: str,
    message: str,
    file_args: list[str],
    max_attempts: int = 4,
) -> bool:
    snap = _snapshot_local_state(file_args)
    if not snap["files"] and not snap["archives"]:
        logger.info("Nessun file locale rilevato da inviare.")
        return True

    for attempt in range(1, max_attempts + 1):
        logger.info("Tentativo push sicuro #%d/%d (mode=%s)...", attempt, max_attempts, mode)
        _run_git(["fetch", "origin", "main"])
        _run_git(["reset", "--hard", "FETCH_HEAD"])

        to_stage = _apply_merged_snapshot(mode, file_args, snap)
        existing_stage = [p for p in to_stage if Path(p).exists()]
        if existing_stage:
            _run_git(["add", "--", *existing_stage])

        diff_res = _run_git(["diff", "--staged", "--quiet"], check=False)
        if diff_res.returncode == 0:
            logger.info("Nessuna modifica netta da inviare.")
            return True

        _run_git(["commit", "-m", message])
        push_res = _run_git(["push", "origin", "HEAD:main"], check=False)
        if push_res.returncode == 0:
            logger.info("Push completato con successo al tentativo #%d.", attempt)
            return True

        logger.warning(
            "Push rifiutato (probabile push concorrente su main), nuovo sync tra 2s: %s",
            push_res.stderr.strip() or push_res.stdout.strip(),
        )
        time.sleep(2.0)

    logger.error("Impossibile completare git push dopo %d tentativi.", max_attempts)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe conflict-free Git commit & push for Vitocal Actions")
    parser.add_argument("--mode", choices=["command", "telemetry"], required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--files", nargs="+", required=True)
    args = parser.parse_args()

    ok = safe_commit_and_push(mode=args.mode, message=args.message, file_args=args.files)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
