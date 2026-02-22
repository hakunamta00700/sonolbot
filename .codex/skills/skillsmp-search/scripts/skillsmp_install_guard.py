#!/usr/bin/env python3
"""
Guarded pre-install checks for SkillsMP skills.
Generates a security report from a quarantined folder and enforces approval.
"""

import argparse
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_MIN_STARS = int(os.getenv("SKILLSMP_MIN_STARS", "10"))
DEFAULT_MIN_AGE_DAYS = int(os.getenv("SKILLSMP_MIN_AGE_DAYS", "30"))
DEFAULT_QUARANTINE_ROOT = os.getenv("SKILLSMP_QUARANTINE_ROOT", "./quarantine")

TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml", ".md", ".txt",
    ".sh", ".bash", ".ps1", ".bat", ".cmd", ".rb", ".php", ".go", ".rs",
    ".java", ".kt", ".cs", ".cpp", ".c", ".h", ".hpp", ".swift",
}

SUSPICIOUS_EXTENSIONS = {
    ".exe", ".dll", ".so", ".dylib", ".jar", ".class", ".msi", ".apk",
    ".bin", ".ps1", ".bat", ".cmd", ".sh",
}

NETWORK_PATTERNS = [
    r"\brequests\b",
    r"\burllib\b",
    r"\bhttpx\b",
    r"\bsocket\b",
    r"\bfetch\s*\(",
    r"\baxios\b",
    r"\bhttp\.client\b",
    r"\bnet/http\b",
    r"\bWebClient\b",
    r"\bcurl\b",
    r"\bwget\b",
]

EXEC_PATTERNS = [
    r"\bos\.system\b",
    r"\bsubprocess\b",
    r"\bchild_process\b",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bpowershell\b",
    r"\bbash\b",
    r"\bsh\b",
    r"\bcmd\.exe\b",
]


def parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        # Handle milliseconds
        if ts > 1_000_000_000_000:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    value = str(value).strip()
    try:
        # Try full ISO format first
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass
    if value.isdigit():
        ts = float(value)
        if ts > 1_000_000_000_000:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    # Try date only
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def is_within(path: str, root: str) -> bool:
    path_abs = os.path.abspath(path)
    root_abs = os.path.abspath(root)
    return path_abs == root_abs or path_abs.startswith(root_abs + os.sep)


def is_text_file(path: str, max_bytes: int = 4096) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(max_bytes)
        if b"\x00" in chunk:
            return False
        return True
    except OSError:
        return False


def is_executable(path: str) -> bool:
    try:
        st = os.stat(path)
    except OSError:
        return False
    if os.name == "nt":
        return os.path.splitext(path)[1].lower() in {".exe", ".bat", ".cmd", ".ps1"}
    return bool(st.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def scan_directory(quarantine_dir: str, quarantine_root: str) -> Dict[str, Any]:
    findings: Dict[str, Any] = {
        "symlinks_outside": [],
        "executables": [],
        "suspicious_extensions": [],
        "network_indicators": [],
        "exec_indicators": [],
        "files_scanned": 0,
    }

    for root, _, files in os.walk(quarantine_dir):
        for name in files:
            path = os.path.join(root, name)
            rel_path = os.path.relpath(path, quarantine_dir)

            if os.path.islink(path):
                target = os.path.realpath(path)
                if not is_within(target, quarantine_root):
                    findings["symlinks_outside"].append({
                        "path": rel_path,
                        "target": target,
                    })

            ext = os.path.splitext(path)[1].lower()
            if ext in SUSPICIOUS_EXTENSIONS:
                findings["suspicious_extensions"].append(rel_path)

            if is_executable(path):
                findings["executables"].append(rel_path)

            if ext in TEXT_EXTENSIONS and is_text_file(path):
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                except OSError:
                    continue

                for pattern in NETWORK_PATTERNS:
                    if re.search(pattern, content):
                        findings["network_indicators"].append({
                            "path": rel_path,
                            "pattern": pattern,
                        })

                for pattern in EXEC_PATTERNS:
                    if re.search(pattern, content):
                        findings["exec_indicators"].append({
                            "path": rel_path,
                            "pattern": pattern,
                        })

            findings["files_scanned"] += 1

    return findings


def load_metadata(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def extract_skill_from_list(data: Dict[str, Any], skill_name: Optional[str]) -> Dict[str, Any]:
    candidates = []

    for key in ("skills", "data", "resolved"):
        if isinstance(data.get(key), list):
            candidates = data.get(key)
            break

    if not candidates and isinstance(data.get("data"), dict):
        for key in ("skills", "data", "resolved"):
            if isinstance(data["data"].get(key), list):
                candidates = data["data"].get(key)
                break

    if not candidates:
        return {}

    def as_skill(item):
        if not isinstance(item, dict):
            return None
        if "skill" in item and isinstance(item.get("skill"), dict):
            return item.get("skill")
        return item

    if skill_name:
        for item in candidates:
            skill = as_skill(item)
            if isinstance(skill, dict) and (
                skill.get("name") == skill_name or skill.get("id") == skill_name
            ):
                return skill
        return {}

    if len(candidates) == 1:
        skill = as_skill(candidates[0])
        if isinstance(skill, dict):
            return skill
    return {}


def extract_metadata(args: argparse.Namespace) -> Dict[str, Any]:
    data = load_metadata(args.metadata_json)

    skill_data = data
    if data:
        skill_data = extract_skill_from_list(data, args.skill_name) or data

    name = args.skill_name or skill_data.get("name") or skill_data.get("skillName")
    stars = args.stars
    if stars is None:
        stars = skill_data.get("stars")

    created_at = args.created_at
    if not created_at:
        created_at = (
            skill_data.get("createdAt")
            or skill_data.get("created_at")
            or skill_data.get("updatedAt")
            or skill_data.get("updated_at")
        )

    return {
        "name": name,
        "stars": stars,
        "created_at": created_at,
    }


def policy_check(stars: Optional[int], created_at: Optional[str], min_stars: int, min_age_days: int) -> Tuple[bool, List[str]]:
    violations: List[str] = []
    if stars is None:
        violations.append("stars unknown")
    elif stars < min_stars:
        violations.append(f"stars below minimum ({stars} < {min_stars})")

    created_dt = parse_date(created_at) if created_at else None
    if created_dt is None:
        violations.append("created_at unknown")
    else:
        age_days = (datetime.now(timezone.utc) - created_dt).days
        if age_days < min_age_days:
            violations.append(f"skill too new ({age_days} < {min_age_days} days)")

    return (len(violations) == 0), violations


def write_report(report_path: str, report: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)


def write_approval(approval_path: str, user_note: str) -> None:
    os.makedirs(os.path.dirname(approval_path), exist_ok=True)
    with open(approval_path, "w", encoding="utf-8") as f:
        f.write(user_note)


def main() -> int:
    parser = argparse.ArgumentParser(description="SkillsMP install guard (quarantine + approval)")
    parser.add_argument("--skill-name", help="Skill name")
    parser.add_argument("--stars", type=int, help="Star count")
    parser.add_argument("--created-at", help="Creation date (ISO or YYYY-MM-DD)")
    parser.add_argument("--metadata-json", help="Path to metadata JSON")
    parser.add_argument("--quarantine-dir", required=True, help="Path to quarantined skill folder")
    parser.add_argument("--quarantine-root", default=DEFAULT_QUARANTINE_ROOT, help="Root quarantine folder")
    parser.add_argument("--report-out", help="Security report output path (JSON)")
    parser.add_argument("--approval-out", help="Approval record output path")
    parser.add_argument("--min-stars", type=int, default=DEFAULT_MIN_STARS, help="Minimum stars required")
    parser.add_argument("--min-age-days", type=int, default=DEFAULT_MIN_AGE_DAYS, help="Minimum age in days")
    parser.add_argument("--approve", action="store_true", help="Skip prompt and approve")
    parser.add_argument("--non-interactive", action="store_true", help="Fail if approval is required")

    args = parser.parse_args()

    quarantine_dir = os.path.abspath(args.quarantine_dir)
    quarantine_root = os.path.abspath(args.quarantine_root)
    if not os.path.isdir(quarantine_dir):
        print("❌ Quarantine directory does not exist.")
        return 4
    if not is_within(quarantine_dir, quarantine_root):
        print("❌ Quarantine directory is outside the quarantine root.")
        return 4

    metadata = extract_metadata(args)
    stars = metadata.get("stars")
    created_at = metadata.get("created_at")

    ok_policy, violations = policy_check(stars, created_at, args.min_stars, args.min_age_days)

    findings = scan_directory(quarantine_dir, quarantine_root)

    report_path = args.report_out or os.path.join(quarantine_dir, "security_report.json")
    approval_path = args.approval_out or os.path.join(quarantine_dir, "approval.txt")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "skill": metadata,
        "policy": {
            "min_stars": args.min_stars,
            "min_age_days": args.min_age_days,
            "passed": ok_policy,
            "violations": violations,
        },
        "quarantine": {
            "dir": quarantine_dir,
            "root": quarantine_root,
        },
        "findings": findings,
    }

    write_report(report_path, report)

    print("Security report written:", report_path)
    print("Policy check:", "PASS" if ok_policy else "FAIL")
    if violations:
        for v in violations:
            print(" -", v)

    if not ok_policy:
        print("❌ Installation blocked by policy.")
        return 2

    # Approval gate
    if args.approve:
        write_approval(approval_path, f"Approved at {datetime.now(timezone.utc).isoformat()}\n")
        print("✅ Approved (flag). Approval record:", approval_path)
        return 0

    if args.non_interactive or not sys.stdin.isatty():
        print("❌ Approval required. Re-run with --approve or use interactive mode.")
        return 3

    print("Approval required. Type APPROVE to continue:")
    try:
        user_input = input("> ").strip()
    except EOFError:
        user_input = ""

    if user_input == "APPROVE":
        write_approval(approval_path, f"Approved at {datetime.now(timezone.utc).isoformat()}\n")
        print("✅ Approved (interactive). Approval record:", approval_path)
        return 0

    print("❌ Not approved.")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
