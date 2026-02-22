---
name: skillsmp-search
description: Search and discover AI skills from the SkillsMP marketplace using keyword search or AI-powered semantic search. Use this skill when users want to find specific skills, explore available capabilities, or search for solutions to particular problems using natural language queries.
---

# SkillsMP Search

## Overview

Provide programmatic access to the SkillsMP skills marketplace through REST API integration. This skill enables both keyword-based and AI semantic search capabilities to discover community-built AI skills. Use keyword search for exact terms and filtering, or AI search for natural language queries and semantic matching.

## Setup

Before using this skill, set the SkillsMP API key as an environment variable (persistent).

**Windows (Command Prompt):**
```cmd
setx SKILLSMP_API_KEY "your_api_key_here"
```
Note: `setx` writes to the user environment; open a new terminal to pick up changes.

**Windows (PowerShell):** add to your profile (e.g. `notepad $PROFILE`):
```powershell
$env:SKILLSMP_API_KEY='your_api_key_here'
```

**Linux/Mac:** add to your shell startup file (e.g. `~/.bashrc`, `~/.zshrc`, or `~/.profile`):
```bash
export SKILLSMP_API_KEY='your_api_key_here'
```

To obtain an API key, visit https://skillsmp.com/docs/api and click "Generate API Key".

**If the API key is not set:**
- Ask the user to provide a valid `SKILLSMP_API_KEY` before running any search.

## When to Use This Skill

Invoke this skill when users:
- Ask to search for specific skills or capabilities (e.g., "Find a web scraping skill")
- Want to discover skills related to a topic (e.g., "What skills are available for automation?")
- Need to explore the SkillsMP marketplace programmatically
- Request natural language skill discovery (e.g., "How can I build a chatbot?")
- Want to find popular or recent skills in a specific domain

## Core Capabilities

### 1. Keyword Search

Execute precise keyword-based searches with pagination and sorting options.

**Use Cases:**
- Finding skills by exact name or keyword
- Filtering results by popularity (stars) or recency
- Browsing paginated results for comprehensive discovery

**Example Invocation:**
```bash
python scripts/skillsmp_search.py keyword "web scraper" 1 20 stars
```

**Parameters:**
- Query: Search term (required)
- Page: Page number (default: 1)
- Limit: Results per page (default: 20, max: 100)
- Sort: 'stars' for popularity or 'recent' for newest

### 2. AI Semantic Search

Execute natural language queries using Cloudflare AI-powered semantic search.

**Use Cases:**
- Natural language skill discovery
- Finding skills by use case or problem description
- Semantic matching beyond exact keywords

**Example Invocation:**
```bash
python scripts/skillsmp_search.py ai "How to create a web scraper for e-commerce sites"
```

**Parameters:**
- Query: Natural language question or description (required)

## Workflow Decision Tree

```
User requests skill search
    │
    ├─ Exact keyword or skill name known?
    │   └─ YES → Use keyword search
    │       ├─ Need popular results? → Sort by 'stars'
    │       └─ Need latest results? → Sort by 'recent'
    │
    └─ Natural language query or use case?
        └─ YES → Use AI semantic search
```

## Using the Search Script

The `scripts/skillsmp_search.py` script provides command-line access to both search methods.

**Optional Flags:**
- `--timeout <seconds>`: Request timeout (default: 15)
- `--json`: Print raw JSON response
- `--json-out <path>`: Write raw JSON response to a file
- `--resolve-ai`: Resolve AI file results to full skill metadata
- `--resolve-ai-limit <n>`: Max AI items to resolve (default: 5)

### Keyword Search Examples

**Basic Search:**
```bash
python scripts/skillsmp_search.py keyword "automation"
```

**Sorted by Popularity:**
```bash
python scripts/skillsmp_search.py keyword "SEO" 1 20 stars
```

**Sorted by Recency:**
```bash
python scripts/skillsmp_search.py keyword "data analysis" 1 20 recent
```

**Paginated Results:**
```bash
# Get page 2 with 50 results per page
python scripts/skillsmp_search.py keyword "web development" 2 50
```

### AI Search Examples

**Problem-Based Search:**
```bash
python scripts/skillsmp_search.py ai "How to extract data from PDFs"
```

**Use Case Search:**
```bash
python scripts/skillsmp_search.py ai "I need to automate email responses"
```

**Feature Discovery:**
```bash
python scripts/skillsmp_search.py ai "Skills for image processing and computer vision"
```

**Save Raw JSON for Audit:**
```bash
python scripts/skillsmp_search.py keyword "automation" 1 20 stars --json-out ./quarantine/automation_search.json
```

**Note on AI results:**
- AI search may return file-level results (`file_id`, `filename`, `score`) without full skill metadata.
- Use `--resolve-ai` to fetch full skill metadata via keyword search.

**AI Search with Resolution:**
```bash
python scripts/skillsmp_search.py ai "web scraper" --resolve-ai --resolve-ai-limit 10
```

## Secure Installation (Required)

Before installing any skill discovered via SkillsMP search, run the guard script to generate a security report and enforce approval.

**Guard Script:**
```bash
python scripts/skillsmp_install_guard.py \
  --skill-name "skill-name" \
  --stars 42 \
  --created-at 2024-11-01 \
  --quarantine-dir ./quarantine/skill-name
```

**Recommended Flow (with metadata JSON):**
```bash
python scripts/skillsmp_search.py keyword "automation" 1 20 stars --json-out ./quarantine/automation_search.json
python scripts/skillsmp_install_guard.py \
  --skill-name "skill-name" \
  --metadata-json ./quarantine/automation_search.json \
  --quarantine-dir ./quarantine/skill-name
```

**What it enforces:**
- Quarantine-only review (the skill must be inside the quarantine root)
- Security report is generated before any approval
- New or low-star skills are blocked
- Explicit user approval is required (interactive or `--approve`)

**Metadata note:**
- If `createdAt` is missing, the guard will use `updatedAt` (epoch seconds) when present.

**Policy defaults (can be overridden via env vars):**
- `SKILLSMP_MIN_STARS` (default: 10)
- `SKILLSMP_MIN_AGE_DAYS` (default: 30)
- `SKILLSMP_QUARANTINE_ROOT` (default: `./quarantine`)

## Integration with Workflow

### Direct Script Execution

Execute the search script directly when users request skill searches. The script handles authentication, API communication, error handling, and formatted output.

### Programmatic Integration

For Python-based workflows, import and use the functions directly:

```python
from scripts.skillsmp_search import keyword_search, ai_search

# Keyword search
results = keyword_search("automation", page=1, limit=20, sort_by="stars")

# AI search
results = ai_search("How to build a recommendation system")
```

### Error Handling

The script handles common errors automatically:
- Missing API key
- Invalid parameters
- Network failures

**Note:** No automatic retries are implemented. Use `--timeout` to avoid hanging requests.

Check the `success` field in responses:
```python
if not results.get("success", True):
    error = results.get("error", {})
    print(f"Error: {error.get('message')}")
```

## API Reference

For detailed API documentation, including authentication, endpoints, response formats, and error codes, refer to `references/api_reference.md`.

Key points:
- Base URL: `https://skillsmp.com/api/v1`
- Authentication: Bearer token (pre-configured in script)
- Rate limits: Standard API rate limiting applies
- Maximum results per page: 100

## Best Practices

1. **Choose the Right Search Method:**
   - Use keyword search when users provide specific terms
   - Use AI search for natural language questions or use cases
   - Default to AI search when query intent is unclear

2. **Security & Installation Guardrails (skillsmp search):**
   - 특정 스킬 설치 시, 먼저 위험성 없는 격리 폴더에서 사전에 보안 검토하여 결과 보고할 것
   - 특정 스킬 설치 시, 1번의 보안 결과 보고와 더불어 사용자의 승인을 반드시 받을 것
   - 신규 스킬 또는 스타 점수가 낮은 스킬은 설치하지 말고 사용자에게 알려 보안에 주의할 것

3. **Result Presentation:**
   - Show skill name, description, and relevance/popularity
   - Include URLs for users to explore further
   - Limit initial results to 20 for readability

4. **Pagination:**
   - Start with page 1 and default limit (20)
   - Increase limit only when users request more results
   - Use pagination for large result sets

5. **Sorting Strategy:**
   - Use 'stars' sort for general queries (shows popular, vetted skills)
   - Use 'recent' sort when users want latest capabilities
   - AI search automatically ranks by relevance

## Resources

### scripts/skillsmp_search.py
Python script providing both keyword and AI search functionality with formatted output and error handling. Can be executed directly from command line or imported as a module.

### references/api_reference.md
Comprehensive API documentation including endpoints, authentication, request/response formats, error codes, and usage examples.
