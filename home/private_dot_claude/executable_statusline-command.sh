#!/bin/bash

# Force C locale for numeric formatting (decimal point instead of comma)
export LC_NUMERIC=C

# Colors (ANSI escape codes)
RESET=$'\033[0m'
CYAN=$'\033[36m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
MAGENTA=$'\033[35m'
BLUE=$'\033[34m'
RED=$'\033[31m'
DIM=$'\033[2m'

# Icons (Nerd Fonts - p10k style)
ICON_FOLDER=$(printf '\xef\x84\x95')  # U+F115
ICON_GIT=$(printf '\xee\x9c\xa5')     # U+E725

# Read JSON input from stdin
input=$(cat)

# Debug: uncomment to see available fields
# echo "$input" > /tmp/claude-statusline-debug.json

# Extract model name
model=$(echo "$input" | jq -r '.model.display_name')

# Extract current directory and get basename
current_dir=$(echo "$input" | jq -r '.workspace.current_dir')
dir_basename=$(basename "$current_dir")

# Get git branch and status
cd "$current_dir" 2>/dev/null
if git rev-parse --git-dir > /dev/null 2>&1; then
    branch=$(git -c core.fileMode=false -c advice.detachedHead=false branch --show-current 2>/dev/null || echo "detached")
    if [ -z "$branch" ]; then
        branch=$(git -c core.fileMode=false -c advice.detachedHead=false rev-parse --short HEAD 2>/dev/null || echo "unknown")
    fi

    # Check if working tree is clean
    if git -c core.fileMode=false diff --quiet 2>/dev/null && git -c core.fileMode=false diff --cached --quiet 2>/dev/null; then
        git_status="clean"
        git_color="$GREEN"
    else
        git_status="dirty"
        git_color="$RED"
    fi
    git_info="${MAGENTA}${ICON_GIT} ${branch}${RESET} ${git_color}(${git_status})${RESET}"
else
    git_info="${DIM}no git${RESET}"
fi

# Extract context usage percentage
used_pct=$(echo "$input" | jq -r '.context_window.used_percentage // empty')
if [ -n "$used_pct" ] && [ "$used_pct" != "null" ]; then
    context_info=$(printf "%.1f%%" "$used_pct")
else
    context_info="0.0%"
fi

# Extract session cost (correct field: cost.total_cost_usd)
session_cost=$(echo "$input" | jq -r '.cost.total_cost_usd // 0')
cost_info=$(printf "\$%.2f" "$session_cost")

# Extract token counts
total_input=$(echo "$input" | jq -r '.context_window.total_input_tokens // 0')
total_output=$(echo "$input" | jq -r '.context_window.total_output_tokens // 0')

# Format tokens with K suffix if >= 1000
format_tokens() {
    local tokens=$1
    if [ "$tokens" -ge 1000 ]; then
        printf "%.1fK" $(echo "scale=1; $tokens / 1000" | bc)
    else
        printf "%d" "$tokens"
    fi
}

input_formatted=$(format_tokens "$total_input")
output_formatted=$(format_tokens "$total_output")
token_info="${DIM}↑${RESET}${MAGENTA}${input_formatted}${RESET} ${DIM}↓${RESET}${MAGENTA}${output_formatted}${RESET}"

# Build status line with separators
printf "%s%s%s %s|%s %s%s %s%s %s|%s %s %s|%s %sctx:%s %s%s%s %s|%s %s%s%s %s|%s %s" \
    "$CYAN" "$model" "$RESET" \
    "$DIM" "$RESET" \
    "$BLUE" "$ICON_FOLDER" "$dir_basename" "$RESET" \
    "$DIM" "$RESET" \
    "$git_info" \
    "$DIM" "$RESET" \
    "$DIM" "$RESET" \
    "$YELLOW" "$context_info" "$RESET" \
    "$DIM" "$RESET" \
    "$GREEN" "$cost_info" "$RESET" \
    "$DIM" "$RESET" \
    "$token_info"
