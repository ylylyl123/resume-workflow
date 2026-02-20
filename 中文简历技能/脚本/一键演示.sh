#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

python3 "$SCRIPT_DIR/生成简历流程.py" \
  --base-resume "$SKILL_DIR/素材/样例/雷军_基础简历样例.md" \
  --jd-file "$SKILL_DIR/素材/样例/岗位JD样例.txt" \
  --out-dir "$SKILL_DIR/输出/最终版" \
  --target-role "目标岗位" \
  --open-html
