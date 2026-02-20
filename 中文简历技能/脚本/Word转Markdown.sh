#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "用法: $0 输入Word文件.docx [输出Markdown文件.md]"
  exit 1
fi

INPUT="$1"
if [ ! -f "$INPUT" ]; then
  echo "错误: 文件不存在 -> $INPUT"
  exit 1
fi

if [ -z "${2:-}" ]; then
  BASE="${INPUT%.*}"
  OUTPUT="${BASE}.md"
else
  OUTPUT="$2"
fi

if command -v pandoc >/dev/null 2>&1; then
  pandoc "$INPUT" -f docx -t gfm -o "$OUTPUT"
  echo "[OK] 已生成 Markdown: $OUTPUT"
  exit 0
fi

echo "错误: 未检测到 pandoc，无法自动转换 docx -> markdown。"
echo "请先安装 pandoc，或手动将 Word 内容另存为 Markdown。"
exit 2
