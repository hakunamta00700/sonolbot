#!/usr/bin/env python3
"""
SkillsMP API Search Script
Provides keyword and AI semantic search capabilities for SkillsMP skills marketplace.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Iterable, Tuple

import requests

API_BASE_URL = "https://skillsmp.com/api/v1"
API_KEY = os.getenv("SKILLSMP_API_KEY", "")
DEFAULT_TIMEOUT = float(os.getenv("SKILLSMP_TIMEOUT", "15"))


def keyword_search(
    query: str,
    page: int = 1,
    limit: int = 20,
    sort_by: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """
    Search skills using keywords.

    Args:
        query: Search query string
        page: Page number (default: 1)
        limit: Items per page (default: 20, max: 100)
        sort_by: Sort method ('stars' or 'recent')

    Returns:
        API response as dictionary
    """
    url = f"{API_BASE_URL}/skills/search"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    params = {
        "q": query,
        "page": page,
        "limit": limit
    }

    if sort_by:
        params["sortBy"] = sort_by

    try:
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": {
                "code": "REQUEST_FAILED",
                "message": str(e)
            }
        }


def ai_search(query: str, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """
    AI semantic search powered by Cloudflare AI.

    Args:
        query: Natural language search query

    Returns:
        API response as dictionary
    """
    url = f"{API_BASE_URL}/skills/ai-search"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    params = {"q": query}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": {
                "code": "REQUEST_FAILED",
                "message": str(e)
            }
        }


def derive_skill_id_from_filename(filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    name = filename.replace("\\", "/")
    if "/" in name:
        name = name.split("/")[-1]
    if name.endswith(".md"):
        name = name[:-3]
    return name or None


def derive_url_from_filename(filename: Optional[str]) -> Optional[str]:
    skill_id = derive_skill_id_from_filename(filename)
    if not skill_id:
        return None
    return f"https://skillsmp.com/skills/{skill_id}"


def extract_ai_items(data: Dict[str, Any]) -> Iterable[Any]:
    data_block = data.get("data", {})
    if isinstance(data_block, dict):
        if isinstance(data_block.get("data"), list):
            return data_block.get("data")
        if isinstance(data_block.get("skills"), list):
            return data_block.get("skills")
    if isinstance(data.get("skills"), list):
        return data.get("skills")
    if isinstance(data.get("data"), list):
        return data.get("data")
    return []


def extract_keyword_skills(data: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    data_block = data.get("data", {})
    if isinstance(data_block, dict) and isinstance(data_block.get("skills"), list):
        return data_block.get("skills")
    if isinstance(data.get("skills"), list):
        return data.get("skills")
    if isinstance(data.get("data"), list):
        return data.get("data")
    return []


def pick_best_skill(skills: Iterable[Dict[str, Any]], derived_id: str) -> Optional[Dict[str, Any]]:
    for skill in skills:
        if not isinstance(skill, dict):
            continue
        if skill.get("id") == derived_id:
            return skill
        url = skill.get("skillUrl") or skill.get("url")
        if url and url.rstrip("/").endswith("/" + derived_id):
            return skill
    skills_list = [s for s in skills if isinstance(s, dict)]
    if len(skills_list) == 1:
        return skills_list[0]
    return None


def resolve_ai_results(data: Dict[str, Any], timeout: float, limit: int) -> Dict[str, Any]:
    items = list(extract_ai_items(data))
    if not items:
        return data

    resolved_meta = []
    cache: Dict[str, Optional[Dict[str, Any]]] = {}
    attempts = 0

    for item in items:
        if not isinstance(item, dict):
            resolved_meta.append({"status": "invalid_item"})
            continue

        if "skill" in item and isinstance(item.get("skill"), dict):
            resolved_meta.append({
                "status": "already_resolved",
                "skill_id": item["skill"].get("id"),
                "skillUrl": item["skill"].get("skillUrl") or item["skill"].get("url"),
            })
            continue

        filename = item.get("filename")
        derived_id = derive_skill_id_from_filename(filename)
        meta_entry = {
            "file_id": item.get("file_id"),
            "filename": filename,
            "derived_id": derived_id,
            "matched": False,
        }

        if not derived_id:
            meta_entry["status"] = "no_filename"
            resolved_meta.append(meta_entry)
            continue

        if limit is not None and attempts >= limit:
            meta_entry["status"] = "skipped_limit"
            resolved_meta.append(meta_entry)
            continue

        if derived_id in cache:
            skill = cache[derived_id]
        else:
            attempts += 1
            search_result = keyword_search(derived_id, page=1, limit=5, sort_by="stars", timeout=timeout)
            skills = extract_keyword_skills(search_result)
            skill = pick_best_skill(skills, derived_id)
            cache[derived_id] = skill

        if skill:
            item["skill"] = skill
            item["resolved"] = True
            meta_entry["matched"] = True
            meta_entry["skill_id"] = skill.get("id")
            meta_entry["skillUrl"] = skill.get("skillUrl") or skill.get("url")
        else:
            meta_entry["status"] = "not_found"

        resolved_meta.append(meta_entry)

    data["resolved"] = resolved_meta
    return data


def format_results(data: Dict[str, Any], search_type: str) -> str:
    """
    Format API response for display.

    Args:
        data: API response dictionary
        search_type: Type of search ('keyword' or 'ai')

    Returns:
        Formatted string output
    """
    if not data.get("success", True):
        error = data.get("error", {})
        return f"❌ Error ({error.get('code', 'UNKNOWN')}): {error.get('message', 'Unknown error')}"

    output = [f"\n{'='*60}"]
    output.append(f"Search Type: {search_type.upper()}")
    output.append(f"{'='*60}\n")

    def extract_list(data_obj: Dict[str, Any], keys: Tuple[str, ...]) -> Iterable[Any]:
        for key in keys:
            if key in data_obj and isinstance(data_obj[key], list):
                return data_obj[key]
        return []

    def normalize_skill(item: Any) -> Tuple[Dict[str, Any], Optional[float]]:
        if isinstance(item, dict) and "skill" in item:
            skill = item.get("skill", {}) or {}
            score = item.get("score")
            if score is None:
                score = item.get("relevance")
            return skill, score
        if isinstance(item, dict):
            score = item.get("score")
            if score is None:
                score = item.get("relevance")
            return item, score
        return {}, None

    def maybe_created(skill: Dict[str, Any]) -> Optional[str]:
        return skill.get("createdAt") or skill.get("created_at") or skill.get("updatedAt") or skill.get("updated_at")

    def format_timestamp(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            ts = float(value)
        else:
            try:
                ts = float(str(value))
            except (TypeError, ValueError):
                return str(value)
        # Handle milliseconds
        if ts > 1_000_000_000_000:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None

    if search_type == "ai":
        results = list(extract_ai_items(data))
        if not results:
            return "\n".join(output) + "No results found."

        for idx, item in enumerate(results, 1):
            skill, score = normalize_skill(item)
            file_id = item.get("file_id") if isinstance(item, dict) else None
            filename = item.get("filename") if isinstance(item, dict) else None
            resolved_flag = item.get("resolved") if isinstance(item, dict) else None

            display_name = skill.get("name") or skill.get("filename") or "Unnamed Skill"
            output.append(f"{idx}. {display_name}")
            output.append(f"   Description: {skill.get('description', 'No description')}")
            output.append(f"   Author: {skill.get('author', 'Unknown')}")
            output.append(f"   Stars: {skill.get('stars', 0)}")
            if score is not None:
                try:
                    score_val = float(score)
                except (TypeError, ValueError):
                    score_val = None
                if score_val is not None:
                    output.append(f"   Relevance Score: {score_val:.3f}")
            if resolved_flag:
                output.append("   Resolved: yes")
            if file_id:
                output.append(f"   File ID: {file_id}")
            if filename:
                output.append(f"   Filename: {filename}")
            created_at = maybe_created(skill)
            if created_at:
                created_fmt = format_timestamp(created_at) or str(created_at)
                output.append(f"   Updated: {created_fmt}")
            url = skill.get("skillUrl") or skill.get("url")
            if not url and filename:
                url = derive_url_from_filename(filename)
                if url:
                    output.append(f"   URL (derived): {url}")
                else:
                    output.append("   URL: ")
            else:
                output.append(f"   URL: {url or ''}")
            output.append("")
    else:
        skills = []
        data_block = data.get("data", {})
        if isinstance(data_block, dict):
            skills = extract_list(data_block, ("skills",))
        if not skills:
            skills = extract_list(data, ("skills", "data"))
        if not skills:
            return "\n".join(output) + "No results found."

        # Add pagination info
        pagination = {}
        if isinstance(data_block, dict):
            pagination = data_block.get("pagination", {})
        if not pagination:
            pagination = data.get("pagination", {})
        if pagination:
            output.append(
                f"Page {pagination.get('page', 1)} of {pagination.get('totalPages', 1)} "
                f"(Total: {pagination.get('total', 0)} skills)\n"
            )

        for idx, skill in enumerate(skills, 1):
            output.append(f"{idx}. {skill.get('name', 'Unnamed Skill')}")
            output.append(f"   Description: {skill.get('description', 'No description')}")
            output.append(f"   Author: {skill.get('author', 'Unknown')}")
            output.append(f"   Stars: {skill.get('stars', 0)}")
            created_at = maybe_created(skill)
            if created_at:
                created_fmt = format_timestamp(created_at) or str(created_at)
                output.append(f"   Updated: {created_fmt}")
            output.append(f"   URL: {skill.get('skillUrl', skill.get('url', ''))}")
            output.append("")

    return "\n".join(output)


def main():
    """Main CLI interface."""
    # Check if API key is set
    if not API_KEY:
        print("❌ Error: SKILLSMP_API_KEY environment variable is not set.")
        print("\nPlease set your API key:")
        print("  export SKILLSMP_API_KEY='your_api_key_here'")
        print("\nOr on Windows:")
        print("  set SKILLSMP_API_KEY=your_api_key_here")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="SkillsMP search CLI")
    parser.add_argument("--json", action="store_true", help="Print raw JSON response")
    parser.add_argument("--json-out", help="Write raw JSON response to file")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Request timeout (seconds)")
    parser.add_argument(
        "--resolve-ai",
        action="store_true",
        help="Resolve AI file results to full skill metadata using keyword search",
    )
    parser.add_argument(
        "--resolve-ai-limit",
        type=int,
        default=5,
        help="Max AI items to resolve (default: 5)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    keyword_parser = subparsers.add_parser("keyword", help="Keyword search")
    keyword_parser.add_argument("query", help="Search query")
    keyword_parser.add_argument("page", nargs="?", type=int, default=1, help="Page number")
    keyword_parser.add_argument("limit", nargs="?", type=int, default=20, help="Items per page")
    keyword_parser.add_argument("sortBy", nargs="?", default=None, help="Sort method (stars/recent)")

    ai_parser = subparsers.add_parser("ai", help="AI semantic search")
    ai_parser.add_argument("query", help="Search query")

    def reorder_global_args(argv):
        global_flags = {"--json", "--resolve-ai"}
        global_opts = {"--json-out", "--timeout", "--resolve-ai-limit"}
        global_args = []
        rest = []
        i = 0
        while i < len(argv):
            arg = argv[i]
            if arg in global_flags:
                global_args.append(arg)
                i += 1
                continue
            if any(arg.startswith(opt + "=") for opt in global_opts):
                global_args.append(arg)
                i += 1
                continue
            if arg in global_opts:
                if i + 1 < len(argv):
                    global_args.extend([arg, argv[i + 1]])
                    i += 2
                else:
                    global_args.append(arg)
                    i += 1
                continue
            rest.append(arg)
            i += 1
        return global_args + rest

    args = parser.parse_args(reorder_global_args(sys.argv[1:]))

    if args.command == "keyword":
        result = keyword_search(
            args.query,
            page=args.page,
            limit=args.limit,
            sort_by=args.sortBy,
            timeout=args.timeout,
        )
        print(format_results(result, "keyword"))
    else:
        # ai
        result = ai_search(args.query, timeout=args.timeout)
        if args.resolve_ai:
            result = resolve_ai_results(result, timeout=args.timeout, limit=args.resolve_ai_limit)
        print(format_results(result, "ai"))

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

    if args.json:
        print("\n" + "="*60)
        print("RAW JSON RESPONSE:")
        print("="*60)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
