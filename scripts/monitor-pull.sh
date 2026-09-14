#!/usr/bin/env bash
# ==============================================================================
# monitor-pull.sh - Passive Pull & Adoption Monitor for agi-memory
# Queries GitHub traffic, referrers, PyPI downloads, and stargazers in 2 seconds.
# ==============================================================================

set -eo pipefail

REPO="kdbhalala/agi-memory"
BOLD="\033[1m"
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
NC="\033[0m"

echo -e "${BOLD}${BLUE}=== agi-memory Passive Adoption Pulse ===${NC}\n"

# 1. GitHub 14-Day Traffic
if command -v gh >/dev/null 2>&1; then
    echo -e "${BOLD}[1/4] GitHub 14-Day Traffic & Clones:${NC}"
    CLONES_JSON=$(gh api "repos/$REPO/traffic/clones" 2>/dev/null || echo "{}")
    VIEWS_JSON=$(gh api "repos/$REPO/traffic/views" 2>/dev/null || echo "{}")

    TOTAL_CLONES=$(echo "$CLONES_JSON" | jq -r '.count // "N/A"')
    UNIQUE_CLONERS=$(echo "$CLONES_JSON" | jq -r '.uniques // "N/A"')
    TOTAL_VIEWS=$(echo "$VIEWS_JSON" | jq -r '.count // "N/A"')
    UNIQUE_VISITORS=$(echo "$VIEWS_JSON" | jq -r '.uniques // "N/A"')

    echo -e "  • ${GREEN}Clones (Installs/Pulls):${NC} $TOTAL_CLONES total (${BOLD}$UNIQUE_CLONERS unique machines${NC})"
    echo -e "  • ${GREEN}Views (Repo Visits):${NC}     $TOTAL_VIEWS total (${BOLD}$UNIQUE_VISITORS unique visitors${NC})"

    # 2. Top Referrers
    echo -e "\n${BOLD}[2/4] Top Referral Sources (Last 14 Days):${NC}"
    REFERRERS=$(gh api "repos/$REPO/traffic/popular/referrers" 2>/dev/null || echo "[]")
    echo "$REFERRERS" | jq -r '.[] | "  - \(.referrer): \(.count) views (\(.uniques) unique)"' 2>/dev/null || echo "  (none recorded)"

    # 3. GitHub Engagement
    echo -e "\n${BOLD}[3/4] GitHub Community Engagement:${NC}"
    gh repo view "$REPO" --json stargazerCount,forkCount --jq '"  • Stars: \(.stargazerCount) | Forks: \(.forkCount)"' 2>/dev/null || echo "  (unavailable)"
else
    echo -e "${YELLOW}Notice: 'gh' CLI not found. Install gh to query GitHub traffic.${NC}"
fi

# 4. PyPI Stats
echo -e "\n${BOLD}[4/4] PyPI Downloads:${NC}"
python3 -c "
import urllib.request, json
try:
    req = urllib.request.Request('https://pypistats.org/api/packages/agi-memory/recent', headers={'User-Agent': 'agi-memory-monitor'})
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode('utf-8'))['data']
        print(f'  • Past Day:   {data.get(\"last_day\", 0)}')
        print(f'  • Past Week:  {data.get(\"last_week\", 0)}')
        print(f'  • Past Month: {data.get(\"last_month\", 0)}')
except Exception as e:
    print('  • (PyPI API rate limited or temporarily unreachable - check https://pepy.tech/project/agi-memory)')
"

echo -e "\n${BOLD}Local SQLite Memory State:${NC}"
PYTHONPATH=src python3 -m agi_memory.mcp_server stats
