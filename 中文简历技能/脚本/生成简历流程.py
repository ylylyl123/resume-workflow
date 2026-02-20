#!/usr/bin/env python3
"""中文简历流水线：JD匹配 -> STAR改写 -> 生成LaTeX/PDF/HTML"""

from __future__ import annotations

import argparse
from datetime import datetime
import html
import json
import re
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Any, Dict, List

KEYWORD_PATTERNS = {
    "数据分析": ["数据分析", "数据驱动", "分析", "洞察", "报表", "dashboard"],
    "项目管理": ["项目管理", "项目推进", "排期", "里程碑", "SOP"],
    "跨部门协作": ["跨部门", "协同", "沟通", "推进", "联动"],
    "复盘优化": ["复盘", "迭代", "优化", "改进", "闭环"],
    "商业分析": ["商业分析", "商业洞察", "商业化", "ROI", "营收"],
    "用户运营": ["用户运营", "用户增长", "留存", "拉新", "转化", "活跃"],
    "内容运营": ["内容运营", "内容策划", "选题", "内容生产"],
    "活动运营": ["活动运营", "活动策划", "活动执行", "campaign"],
    "行业研究": ["行业研究", "行研", "竞品研究", "市场研究"],
    "金融分析": ["金融分析", "投研", "估值", "财务分析"],
    "财务建模": ["财务建模", "DCF", "三张报表", "敏感性分析"],
    "风险管理": ["风险管理", "风控", "风险控制", "内控", "合规"],
    "客户经营": ["客户经营", "客户拓展", "客户维护", "机构客户", "高净值"],
    "合规执行": ["合规", "监管", "合规执行", "合规审查"],
}

LABEL_BY_KEYWORD = {
    "用户运营": "增长运营",
    "内容运营": "内容运营",
    "活动运营": "活动策划",
    "数据分析": "数据分析",
    "跨部门协作": "协同推进",
    "项目管理": "项目统筹",
    "复盘优化": "复盘优化",
    "商业分析": "商业闭环",
    "行业研究": "行业研究",
    "金融分析": "投研分析",
    "财务建模": "财务建模",
    "风险管理": "风险管控",
    "客户经营": "客户经营",
    "合规执行": "合规执行",
}

LATEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*(?:%|\+|万|千|百|元|人|家|套|天|年|月|次)")
TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9/+._-]{1,24}|[\u4e00-\u9fff]{2,8}")
STOPWORDS = {
    "岗位", "工作", "职责", "要求", "负责", "相关", "以上", "以下", "具备", "能力", "经验",
    "优先", "本科", "硕士", "博士", "学历", "我们", "公司", "团队", "进行", "完成", "推动",
    "以及", "并且", "包括", "能够", "具有", "参与", "良好", "优秀", "较强", "熟悉", "掌握",
    "岗位职责", "任职要求", "加分项", "职位描述", "候选人", "专业", "不限", "方向", "经验者",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成中文岗位化简历 PDF + HTML")
    parser.add_argument("--base-resume", required=True, help="基础简历路径（推荐 Markdown，兼容 JSON）")
    parser.add_argument("--jd-file", required=True, help="JD 文本路径")
    parser.add_argument("--out-dir", required=True, help="输出目录")
    parser.add_argument("--target-role", default="目标岗位", help="目标岗位名称")
    parser.add_argument("--no-compile-pdf", action="store_true", help="只生成 tex/html，不编译 PDF")
    parser.add_argument("--open-html", action="store_true", help="生成后自动打开 HTML")
    return parser.parse_args()


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def split_items(text: str) -> List[str]:
    return [x.strip() for x in re.split(r"[、,，;；/]", text) if x.strip()]


def empty_highlight() -> Dict[str, Any]:
    return {
        "situation": "",
        "task": "",
        "action": "",
        "result": "",
        "metrics": [],
        "tags": [],
    }


def highlight_has_content(item: Dict[str, Any]) -> bool:
    return bool(
        item.get("situation")
        or item.get("task")
        or item.get("action")
        or item.get("result")
        or item.get("metrics")
        or item.get("tags")
    )


def parse_bullet(line: str) -> str:
    if line.startswith("- "):
        return line[2:].strip()
    if line.startswith("* "):
        return line[2:].strip()
    return line.strip()


def parse_key_value(raw: str) -> tuple[str, str]:
    for sep in ("：", ":"):
        if sep in raw:
            k, v = raw.split(sep, 1)
            return k.strip(), v.strip()
    return "", raw.strip()


def parse_resume_markdown(path: Path) -> Dict[str, Any]:
    lines = path.read_text(encoding="utf-8").splitlines()

    resume: Dict[str, Any] = {
        "name": "候选人",
        "title": "目标岗位（应届）",
        "contact": {"phone": "", "email": "", "location": ""},
        "education": [],
        "experiences": [],
        "projects": [],
        "skills": [],
    }

    section = "header"
    current_edu: Dict[str, Any] | None = None
    current_exp: Dict[str, Any] | None = None
    current_proj: Dict[str, Any] | None = None
    current_skill: Dict[str, Any] | None = None
    current_highlight: Dict[str, Any] | None = None

    def finalize_highlight() -> None:
        nonlocal current_highlight, current_exp
        if current_exp is None or current_highlight is None:
            return
        if highlight_has_content(current_highlight):
            current_exp["highlights"].append(current_highlight)
        current_highlight = None

    def finalize_exp() -> None:
        nonlocal current_exp, current_highlight
        if current_exp is None:
            return
        finalize_highlight()
        if not current_exp.get("highlights"):
            current_exp["highlights"] = [
                {
                    "situation": "",
                    "task": "完成岗位相关工作",
                    "action": "推进执行并形成结果",
                    "result": "沉淀可复用经验",
                    "metrics": [],
                    "tags": [],
                }
            ]
        resume["experiences"].append(current_exp)
        current_exp = None
        current_highlight = None

    def finalize_edu() -> None:
        nonlocal current_edu
        if current_edu is not None:
            resume["education"].append(current_edu)
            current_edu = None

    def finalize_proj() -> None:
        nonlocal current_proj
        if current_proj is not None:
            resume["projects"].append(current_proj)
            current_proj = None

    def finalize_skill() -> None:
        nonlocal current_skill
        if current_skill is not None:
            resume["skills"].append(current_skill)
            current_skill = None

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("# "):
            resume["name"] = stripped[2:].strip()
            continue

        if stripped.startswith("## "):
            finalize_edu()
            finalize_exp()
            finalize_proj()
            finalize_skill()

            title = stripped[3:].strip()
            if any(k in title for k in ("教育",)):
                section = "education"
            elif any(k in title for k in ("实习", "工作", "经历")):
                section = "experience"
            elif any(k in title for k in ("项目",)):
                section = "project"
            elif any(k in title for k in ("技能",)):
                section = "skills"
            else:
                section = "header"
            continue

        if stripped.startswith("### "):
            heading = stripped[4:].strip()
            parts = [p.strip() for p in heading.split("|")]

            if section == "education":
                finalize_edu()
                current_edu = {
                    "school": parts[0] if parts else "",
                    "period": parts[1] if len(parts) > 1 else "",
                    "major": "",
                    "degree": "",
                    "highlights": [],
                }
            elif section == "experience":
                finalize_exp()
                current_exp = {
                    "org": parts[0] if parts else "",
                    "role": parts[1] if len(parts) > 1 else "",
                    "period": parts[2] if len(parts) > 2 else "",
                    "location": parts[3] if len(parts) > 3 else "",
                    "highlights": [],
                }
                current_highlight = None
            elif section == "project":
                finalize_proj()
                current_proj = {
                    "name": parts[0] if parts else "",
                    "period": parts[1] if len(parts) > 1 else "",
                    "highlights": [],
                }
            elif section == "skills":
                finalize_skill()
                current_skill = {"category": heading, "items": []}
            continue

        if stripped.startswith(("- ", "* ")):
            body = parse_bullet(stripped)
            key, value = parse_key_value(body)

            if section == "header":
                if key in ("目标岗位", "求职意向", "意向岗位"):
                    resume["title"] = value
                elif key in ("电话", "手机"):
                    resume["contact"]["phone"] = value
                elif key.lower() in ("邮箱", "email", "mail"):
                    resume["contact"]["email"] = value
                elif key in ("地点", "城市", "所在地"):
                    resume["contact"]["location"] = value
                continue

            if section == "education" and current_edu is not None:
                if key in ("专业",):
                    current_edu["major"] = value
                elif key in ("学历", "学位"):
                    current_edu["degree"] = value
                elif key in ("亮点", "核心课程", "荣誉"):
                    current_edu["highlights"].append(value)
                else:
                    current_edu["highlights"].append(body)
                continue

            if section == "experience" and current_exp is not None:
                if current_highlight is None:
                    current_highlight = empty_highlight()

                if key == "场景" and highlight_has_content(current_highlight):
                    finalize_highlight()
                    current_highlight = empty_highlight()

                if key in ("场景",):
                    current_highlight["situation"] = value
                elif key in ("任务",):
                    current_highlight["task"] = value
                elif key in ("动作", "行动", "做法"):
                    current_highlight["action"] = value
                elif key in ("结果", "产出"):
                    current_highlight["result"] = value
                elif key in ("指标", "量化"):
                    current_highlight["metrics"].extend(split_items(value))
                elif key in ("标签",):
                    current_highlight["tags"].extend(split_items(value))
                else:
                    plain = body
                    current_exp["highlights"].append(
                        {
                            "situation": "",
                            "task": plain,
                            "action": plain,
                            "result": plain,
                            "metrics": NUMBER_PATTERN.findall(plain)[:2],
                            "tags": [],
                        }
                    )
                continue

            if section == "project" and current_proj is not None:
                current_proj["highlights"].append(body)
                continue

            if section == "skills" and current_skill is not None:
                if key:
                    current_skill["items"].extend(split_items(value))
                else:
                    current_skill["items"].extend(split_items(body))
                continue

    finalize_edu()
    finalize_exp()
    finalize_proj()
    finalize_skill()

    if not resume["contact"]["email"]:
        m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "\n".join(lines))
        if m:
            resume["contact"]["email"] = m.group(0)
    if not resume["contact"]["phone"]:
        m = re.search(r"(1[3-9]\d{9}|(\+?86[- ]?)?1[3-9]\d{9})", "\n".join(lines))
        if m:
            resume["contact"]["phone"] = m.group(0)

    return resume


def read_base_resume(path: Path) -> Dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in (".md", ".markdown", ".txt"):
        return parse_resume_markdown(path)
    if suffix == ".json":
        raise ValueError("基础简历请使用 Markdown。若你只有 Word，请先运行 Word转Markdown.sh。")
    raise ValueError(f"不支持的基础简历格式：{path.suffix}，请使用 Markdown")


def extract_keywords(jd_text: str) -> List[str]:
    scores: Dict[str, int] = {}
    for keyword, patterns in KEYWORD_PATTERNS.items():
        score = 0
        for p in patterns:
            score += len(re.findall(re.escape(p), jd_text, flags=re.IGNORECASE))
        if score > 0:
            scores[keyword] = score

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    result = [k for k, _ in ranked]

    token_count: Dict[str, int] = {}
    for raw in TOKEN_PATTERN.findall(jd_text):
        token = raw.strip().lower()
        if len(token) < 2:
            continue
        if token in STOPWORDS:
            continue
        if token.isdigit():
            continue
        if token.startswith(("http", "www")):
            continue
        token_count[token] = token_count.get(token, 0) + 1

    token_ranked = sorted(token_count.items(), key=lambda x: (-x[1], -len(x[0]), x[0]))
    dynamic = [t for t, c in token_ranked if c >= 2][:8]

    merged: List[str] = []
    for k in result + dynamic:
        if k not in merged:
            merged.append(k)

    if not merged:
        merged = ["项目管理", "数据分析", "跨部门协作", "复盘优化", "结果导向"]
    return merged[:8]


def score_highlight(item: Dict[str, Any], keywords: List[str]) -> int:
    text = " ".join(
        [
            item.get("situation", ""),
            item.get("task", ""),
            item.get("action", ""),
            item.get("result", ""),
            " ".join(item.get("metrics", [])),
            " ".join(item.get("tags", [])),
        ]
    )
    score = 0
    tags = set(item.get("tags", []))
    for idx, kw in enumerate(keywords):
        weight = max(8 - idx, 1)
        if kw in text:
            score += weight * 3
        if kw in tags:
            score += weight * 4
    score += len(item.get("metrics", [])) * 2
    return score


def pick_bullet_label(item: Dict[str, Any], keywords: List[str]) -> str:
    explicit = item.get("label", "").strip()
    if explicit:
        return explicit[:4] if len(explicit) > 4 else explicit

    text = " ".join(
        [
            item.get("situation", ""),
            item.get("task", ""),
            item.get("action", ""),
            item.get("result", ""),
            " ".join(item.get("tags", [])),
        ]
    )

    for kw in keywords:
        if kw in text and kw in LABEL_BY_KEYWORD:
            return LABEL_BY_KEYWORD[kw]

    for tag in item.get("tags", []):
        if tag in LABEL_BY_KEYWORD:
            return LABEL_BY_KEYWORD[tag]

    return "结果导向"


def collect_metrics(item: Dict[str, Any]) -> List[str]:
    metrics = [m.strip() for m in item.get("metrics", []) if m.strip()]
    if metrics:
        return metrics[:2]

    fallback_text = " ".join(
        [item.get("task", ""), item.get("action", ""), item.get("result", "")]
    )
    detected = NUMBER_PATTERN.findall(fallback_text)
    return detected[:2]


def build_structured_bullet(item: Dict[str, Any], keywords: List[str]) -> Dict[str, Any]:
    label = pick_bullet_label(item, keywords)

    fragments: List[str] = []
    task = item.get("task", "").strip()
    action = item.get("action", "").strip()
    result = item.get("result", "").strip()

    if task:
        fragments.append(task)
    if action and action not in fragments:
        fragments.append(action)
    if result and result not in fragments:
        fragments.append(result)

    if not fragments:
        situation = item.get("situation", "").strip()
        if situation:
            fragments.append(situation)

    content = "；".join(fragments)
    if not content:
        content = "推进项目并达成阶段性结果"

    metrics = collect_metrics(item)

    return {
        "label": label,
        "content": content,
        "metrics": metrics,
        "tags": item.get("tags", []),
    }


def optimize_resume(base_resume: Dict[str, Any], keywords: List[str], target_role: str) -> Dict[str, Any]:
    optimized = json.loads(json.dumps(base_resume, ensure_ascii=False))
    optimized["target_role"] = target_role
    optimized["jd_keywords"] = keywords

    for exp in optimized.get("experiences", []):
        highlights = exp.get("highlights", [])
        ranked = sorted(highlights, key=lambda x: score_highlight(x, keywords), reverse=True)

        if len(ranked) >= 3:
            selected = ranked[:3]
        elif len(ranked) == 2:
            selected = ranked
        else:
            selected = ranked[:1]

        exp["optimized_bullets_struct"] = [
            build_structured_bullet(item, keywords) for item in selected
        ]

    return optimized


def escape_latex(text: str) -> str:
    out = text
    for ch, repl in LATEX_SPECIALS.items():
        out = out.replace(ch, repl)
    return out


def latex_metrics(metrics: List[str]) -> str:
    if not metrics:
        return ""
    rendered = "、".join(rf"\textbf{{{escape_latex(m)}}}" for m in metrics)
    return rf"；关键指标：{rendered}"


def render_latex(resume: Dict[str, Any]) -> str:
    name = escape_latex(resume.get("name", "候选人"))
    contact = resume.get("contact", {})
    target_role = escape_latex(resume.get("target_role", resume.get("title", "目标岗位")))

    lines: List[str] = []
    lines.append(r"\documentclass[a4paper,10pt]{article}")
    lines.append(r"\usepackage[UTF8,fontset=fandol]{ctex}")
    lines.append(r"\usepackage{geometry}")
    lines.append(r"\usepackage{titlesec}")
    lines.append(r"\usepackage{enumitem}")
    lines.append(r"\usepackage{hyperref}")
    lines.append(r"\usepackage{xcolor}")
    lines.append(r"\geometry{a4paper, top=1.2cm, bottom=1.2cm, left=1.5cm, right=1.5cm}")
    lines.append(r"\pagestyle{empty}")
    lines.append(r"\setlength{\parindent}{0pt}")
    lines.append(r"\linespread{1.08}")
    lines.append(r"\titleformat{\section}{\large\bfseries}{}{0em}{}[\titlerule]")
    lines.append(r"\titlespacing*{\section}{0pt}{0.4cm}{0.2cm}")
    lines.append(r"\begin{document}")

    lines.append(r"\begin{center}")
    lines.append(rf"{{\Huge \textbf{{{name}}}}} \\")
    lines.append(r"\vspace{0.15cm}")
    lines.append(rf"\textbf{{意向岗位：{target_role}}} \\")
    lines.append(r"\vspace{0.1cm}")
    lines.append(
        rf"电话：{escape_latex(contact.get('phone', ''))} \quad | \quad 邮箱：{escape_latex(contact.get('email', ''))} \quad | \quad 地点：{escape_latex(contact.get('location', ''))}"
    )
    lines.append(r"\vspace{0.08cm}")
    lines.append(
        rf"\textbf{{岗位关键词：}} {escape_latex(' / '.join(resume.get('jd_keywords', [])))}"
    )
    lines.append(r"\end{center}")

    lines.append(r"\section*{教育背景}")
    for edu in resume.get("education", []):
        lines.append(
            rf"\textbf{{{escape_latex(edu.get('school', ''))}}} \hfill {escape_latex(edu.get('period', ''))} \\"
        )
        lines.append(
            rf"{escape_latex(edu.get('major', ''))} \hfill {escape_latex(edu.get('degree', ''))} \\"
        )
        details = edu.get("highlights", [])
        if details:
            lines.append(
                rf"\textbf{{核心亮点：}} {'；'.join(escape_latex(d) for d in details[:2])}"
            )

    lines.append(r"\section*{实习/项目经历}")
    for exp in resume.get("experiences", []):
        lines.append(
            rf"\textbf{{{escape_latex(exp.get('org', ''))}}} \hfill {escape_latex(exp.get('period', ''))} \\"
        )
        role = escape_latex(exp.get("role", ""))
        location = escape_latex(exp.get("location", ""))
        lines.append(rf"\textit{{{role}}} \hfill {location}")
        lines.append(r"\begin{itemize}[leftmargin=*, itemsep=2pt, parsep=0pt, topsep=2pt]")

        for bullet in exp.get("optimized_bullets_struct", [])[:3]:
            label = escape_latex(bullet.get("label", "结果导向"))
            content = escape_latex(bullet.get("content", ""))
            metrics = latex_metrics(bullet.get("metrics", []))
            lines.append(
                rf"    \item \textbf{{{label}}}：{content}{metrics}。"
            )

        lines.append(r"\end{itemize}")

    if resume.get("projects"):
        lines.append(r"\section*{项目补充}")
        for prj in resume["projects"]:
            lines.append(
                rf"\textbf{{{escape_latex(prj.get('name', ''))}}} \hfill {escape_latex(prj.get('period', ''))} \\"
            )
            lines.append(r"\begin{itemize}[leftmargin=*, itemsep=2pt, parsep=0pt, topsep=2pt]")
            for h in prj.get("highlights", [])[:2]:
                lines.append(rf"    \item \textbf{{项目落地}}：{escape_latex(h)}。")
            lines.append(r"\end{itemize}")

    if resume.get("skills"):
        lines.append(r"\section*{技能与工具}")
        lines.append(r"\begin{itemize}[leftmargin=*, itemsep=2pt, parsep=0pt, topsep=2pt]")
        for group in resume["skills"]:
            lines.append(
                rf"    \item \textbf{{{escape_latex(group.get('category', ''))}：}} {escape_latex('、'.join(group.get('items', [])))}"
            )
        lines.append(r"\end{itemize}")

    lines.append(r"\section*{自我评价}")
    lines.append(
        r"具备强执行力与结果导向，能够在高节奏环境中推进复杂任务落地；重视数据与复盘，能持续优化策略并稳定交付业务结果。"
    )

    lines.append(r"\end{document}")

    return "\n".join(lines) + "\n"


def render_metric_spans(metrics: List[str]) -> str:
    if not metrics:
        return ""
    return "".join(
        f"<span class=\"metric-pill\">{html.escape(m)}</span>" for m in metrics[:2]
    )


def render_html(resume: Dict[str, Any]) -> str:
    name = html.escape(resume.get("name", "候选人"))
    target_role = html.escape(resume.get("target_role", "目标岗位"))
    contact = resume.get("contact", {})
    keywords = resume.get("jd_keywords", [])

    keyword_tags = "".join(
        f"<span class=\"highlight-tag\">{html.escape(k)}</span>" for k in keywords
    )

    education_blocks: List[str] = []
    for edu in resume.get("education", []):
        highlights = "".join(
            f"<li>{html.escape(h)}</li>" for h in edu.get("highlights", [])[:2]
        )
        education_blocks.append(
            f"""
            <div class=\"experience-card\">
              <div class=\"experience-header\">
                <div>
                  <div class=\"experience-company\">{html.escape(edu.get('school', ''))}</div>
                  <div class=\"experience-position\">{html.escape(edu.get('major', ''))}</div>
                </div>
                <div class=\"experience-date\">{html.escape(edu.get('period', ''))}</div>
              </div>
              <div class=\"experience-sub\">{html.escape(edu.get('degree', ''))}</div>
              <ul class=\"experience-highlights\">{highlights}</ul>
            </div>
            """
        )

    experience_blocks: List[str] = []
    for exp in resume.get("experiences", []):
        bullets = []
        for b in exp.get("optimized_bullets_struct", [])[:3]:
            label = html.escape(b.get("label", "结果导向"))
            content = html.escape(b.get("content", ""))
            metric_spans = render_metric_spans(b.get("metrics", []))
            bullets.append(
                f"<li><strong>{label}：</strong>{content}<div class=\"metric-row\">{metric_spans}</div></li>"
            )

        experience_blocks.append(
            f"""
            <div class=\"experience-card\">
              <div class=\"experience-header\">
                <div>
                  <div class=\"experience-company\">{html.escape(exp.get('org', ''))}</div>
                  <div class=\"experience-position\">{html.escape(exp.get('role', ''))}</div>
                </div>
                <div class=\"experience-date\">{html.escape(exp.get('period', ''))}</div>
              </div>
              <div class=\"experience-sub\">{html.escape(exp.get('location', ''))}</div>
              <ul class=\"experience-highlights\">{''.join(bullets)}</ul>
            </div>
            """
        )

    project_cards: List[str] = []
    for prj in resume.get("projects", [])[:2]:
        highs = "".join(
            f"<li><strong>项目落地：</strong>{html.escape(h)}</li>" for h in prj.get("highlights", [])[:2]
        )
        project_cards.append(
            f"""
            <div class=\"project-card\">
              <div class=\"project-date\">{html.escape(prj.get('period', ''))}</div>
              <h3 class=\"project-title\">{html.escape(prj.get('name', ''))}</h3>
              <ul class=\"project-highlights\">{highs}</ul>
            </div>
            """
        )

    skill_groups: List[str] = []
    for group in resume.get("skills", []):
        tags = "".join(
            f"<span class=\"skill-tag\">{html.escape(item)}</span>" for item in group.get("items", [])
        )
        skill_groups.append(
            f"""
            <div class=\"skill-category\">
              <div class=\"category-title\">{html.escape(group.get('category', ''))}</div>
              <div class=\"skill-tags\">{tags}</div>
            </div>
            """
        )

    return f"""<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>{name} | 中文简历</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html {{ scroll-behavior: smooth; font-size: 16px; }}
    body {{
      color: #0f172a;
      background-color: #fff;
      font-family: Inter, 'PingFang SC', 'Microsoft YaHei', sans-serif;
      line-height: 1.6;
    }}
    section {{ padding: 4.5rem 1.2rem; }}
    .container {{ max-width: 1040px; margin: 0 auto; }}
    .grid {{ display: grid; gap: 1.5rem; }}
    .grid-2 {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    @media (max-width: 820px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}

    #hero {{
      min-height: 72vh;
      background: linear-gradient(135deg, #ffffff 0%, #f1f5f9 100%);
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
    }}
    .hero-name {{ font-size: 2.8rem; margin-bottom: 0.6rem; }}
    .hero-title {{ font-size: 1.25rem; font-weight: 600; margin-bottom: 0.8rem; }}
    .hero-info {{ color: #64748b; margin-bottom: 1rem; }}
    .hero-highlights {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 0.55rem; }}
    .highlight-tag {{
      border: 1px solid #e2e8f0;
      background: #f8fafc;
      border-radius: 9999px;
      padding: 0.35rem 0.8rem;
      font-size: 0.82rem;
      font-weight: 500;
    }}

    .section-title {{
      text-align: center;
      font-size: 1.85rem;
      margin-bottom: 2.2rem;
      position: relative;
    }}
    .section-title:after {{
      content: '';
      display: block;
      width: 62px;
      height: 3px;
      background: #0f172a;
      margin: 0.9rem auto 0;
    }}

    .experience-card, .project-card, .skill-category {{
      background: #fff;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 1.35rem;
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
      transition: all 0.2s ease;
    }}
    .experience-card:hover, .project-card:hover, .skill-category:hover {{
      transform: translateY(-2px);
      box-shadow: 0 8px 20px rgba(15, 23, 42, 0.08);
    }}
    .experience-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 0.75rem;
      margin-bottom: 0.7rem;
    }}
    @media (max-width: 640px) {{ .experience-header {{ flex-direction: column; }} }}

    .experience-company {{ font-size: 1.13rem; font-weight: 600; }}
    .experience-position {{ font-size: 0.98rem; font-weight: 500; margin-top: 0.35rem; }}
    .experience-date, .experience-sub {{ color: #64748b; font-size: 0.88rem; }}
    .experience-sub {{ margin-bottom: 0.7rem; }}

    .experience-highlights, .project-highlights {{ list-style: disc; padding-left: 1.2rem; }}
    .experience-highlights li, .project-highlights li {{ margin-bottom: 0.52rem; color: #334155; line-height: 1.72; }}
    .metric-row {{ margin-top: 0.35rem; display: flex; gap: 0.4rem; flex-wrap: wrap; }}
    .metric-pill {{
      border-radius: 9999px;
      background: #0f172a;
      color: #f8fafc;
      padding: 0.2rem 0.55rem;
      font-size: 0.75rem;
      font-weight: 600;
    }}

    .project-date {{ color: #64748b; font-size: 0.85rem; margin-bottom: 0.45rem; }}
    .project-title {{ font-size: 1.1rem; margin-bottom: 0.65rem; }}

    .skills-section {{ background: #f8fafc; }}
    .skills-grid {{ display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }}
    .category-title {{ margin-bottom: 0.7rem; font-size: 1.03rem; font-weight: 600; }}
    .skill-tags {{ display: flex; flex-wrap: wrap; gap: 0.45rem; }}
    .skill-tag {{
      display: inline-block;
      border-radius: 9999px;
      background: #eef2ff;
      color: #0f172a;
      padding: 0.35rem 0.65rem;
      font-size: 0.82rem;
      font-weight: 500;
      border: 1px solid #dbeafe;
    }}

    .footer-note {{
      text-align: center;
      color: #64748b;
      padding: 1.4rem 1rem 2.2rem;
      font-size: 0.84rem;
    }}
  </style>
</head>
<body>
  <section id=\"hero\">
    <div class=\"container\">
      <h1 class=\"hero-name\">{name}</h1>
      <p class=\"hero-title\">意向岗位：{target_role}</p>
      <p class=\"hero-info\">电话：{html.escape(contact.get('phone', ''))} ｜ 邮箱：{html.escape(contact.get('email', ''))} ｜ 地点：{html.escape(contact.get('location', ''))}</p>
      <div class=\"hero-highlights\">{keyword_tags}</div>
    </div>
  </section>

  <section>
    <div class=\"container\">
      <h2 class=\"section-title\">教育背景</h2>
      {''.join(education_blocks)}
    </div>
  </section>

  <section>
    <div class=\"container\">
      <h2 class=\"section-title\">实习/项目经历</h2>
      {''.join(experience_blocks)}
    </div>
  </section>

  <section>
    <div class=\"container\">
      <h2 class=\"section-title\">项目补充</h2>
      <div class=\"grid grid-2\">{''.join(project_cards)}</div>
    </div>
  </section>

  <section class=\"skills-section\">
    <div class=\"container\">
      <h2 class=\"section-title\">技能与工具</h2>
      <div class=\"skills-grid\">{''.join(skill_groups)}</div>
    </div>
  </section>

  <div class=\"footer-note\">说明：本页面为教学演示版，投递前请人工校验事实、量化数据与时间线一致性。</div>
</body>
</html>
"""


def split_jd_sections(jd_text: str) -> Dict[str, List[str]]:
    title = []
    duties = []
    requirements = []
    bonus = []
    others = []

    current = "others"
    lines = [line.strip() for line in jd_text.splitlines() if line.strip()]
    for line in lines:
        if "岗位名称" in line or "职位名称" in line:
            title.append(line)
            continue
        if "岗位职责" in line or "工作职责" in line:
            current = "duties"
            continue
        if "任职要求" in line or "岗位要求" in line:
            current = "requirements"
            continue
        if "加分项" in line or "优先条件" in line:
            current = "bonus"
            continue

        if current == "duties":
            duties.append(line)
        elif current == "requirements":
            requirements.append(line)
        elif current == "bonus":
            bonus.append(line)
        else:
            others.append(line)

    return {
        "title": title,
        "duties": duties,
        "requirements": requirements,
        "bonus": bonus,
        "others": others,
    }


def calc_quality(optimized: Dict[str, Any], keywords: List[str]) -> Dict[str, Any]:
    experiences = optimized.get("experiences", [])
    bullet_total = 0
    bullet_with_metrics = 0
    bullet_count_pass = 0
    merged_text = []

    for exp in experiences:
        bullets = exp.get("optimized_bullets_struct", [])
        if 2 <= len(bullets) <= 3:
            bullet_count_pass += 1
        bullet_total += len(bullets)
        for b in bullets:
            if b.get("metrics"):
                bullet_with_metrics += 1
            merged_text.append(
                " ".join([b.get("label", ""), b.get("content", ""), " ".join(b.get("metrics", []))])
            )

    corpus = " ".join(merged_text)
    hit_keywords = [kw for kw in keywords if kw in corpus]
    coverage = 0.0
    if keywords:
        coverage = len(hit_keywords) / len(keywords)

    return {
        "experience_total": len(experiences),
        "experience_pass": bullet_count_pass,
        "bullet_total": bullet_total,
        "bullet_with_metrics": bullet_with_metrics,
        "keyword_hit": hit_keywords,
        "keyword_coverage": coverage,
    }


def build_jd_analysis_markdown(
    jd_text: str,
    keywords: List[str],
    optimized: Dict[str, Any],
    target_role: str,
    base_resume_path: Path,
    jd_path: Path,
) -> str:
    sections = split_jd_sections(jd_text)
    quality = calc_quality(optimized, keywords)

    lines: List[str] = []
    lines.append("# 岗位调研与简历校准报告")
    lines.append("")
    lines.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 目标岗位：{target_role}")
    lines.append(f"- 基础简历：`{base_resume_path}`")
    lines.append(f"- JD 文件：`{jd_path}`")
    lines.append("")

    lines.append("## 一、JD 信息提炼")
    lines.append("")
    if sections["title"]:
        lines.append("### 岗位标题")
        for item in sections["title"]:
            lines.append(f"- {item}")
        lines.append("")

    lines.append("### 关键词优先级")
    for idx, kw in enumerate(keywords, start=1):
        lines.append(f"{idx}. {kw}")
    lines.append("")

    if sections["duties"]:
        lines.append("### 岗位职责摘要")
        for item in sections["duties"][:8]:
            lines.append(f"- {item}")
        lines.append("")

    if sections["requirements"]:
        lines.append("### 任职要求摘要")
        for item in sections["requirements"][:8]:
            lines.append(f"- {item}")
        lines.append("")

    if sections["bonus"]:
        lines.append("### 加分项摘要")
        for item in sections["bonus"][:6]:
            lines.append(f"- {item}")
        lines.append("")

    lines.append("## 二、简历匹配校准")
    lines.append("")
    for exp in optimized.get("experiences", []):
        lines.append(f"### {exp.get('org', '')}｜{exp.get('role', '')}")
        lines.append(f"- 时间地点：{exp.get('period', '')}｜{exp.get('location', '')}")
        bullets = exp.get("optimized_bullets_struct", [])
        matched = []
        bucket = " ".join(
            [
                b.get("label", "") + " " + b.get("content", "") + " " + " ".join(b.get("metrics", []))
                for b in bullets
            ]
        )
        for kw in keywords:
            if kw in bucket:
                matched.append(kw)
        if matched:
            lines.append(f"- 命中关键词：{' / '.join(matched)}")
        for b in bullets:
            metric_tail = ""
            if b.get("metrics"):
                metric_tail = f"；关键指标：{'、'.join(b.get('metrics', [])[:2])}"
            lines.append(f"- **{b.get('label', '结果导向')}**：{b.get('content', '')}{metric_tail}")
        lines.append("")

    lines.append("## 三、质量检查")
    lines.append("")
    lines.append(
        f"- 2-3条 bullet 合规经历：{quality['experience_pass']}/{quality['experience_total']}"
    )
    lines.append(
        f"- 含量化指标 bullet：{quality['bullet_with_metrics']}/{quality['bullet_total']}"
    )
    lines.append(
        f"- 关键词覆盖率：{quality['keyword_coverage']:.0%}（命中：{' / '.join(quality['keyword_hit']) or '无'}）"
    )
    lines.append("")

    lines.append("## 四、人工确认清单")
    lines.append("")
    lines.append("- 是否每条量化数据都能在面试中解释来源。")
    lines.append("- 是否存在时间线冲突或角色职责夸大。")
    lines.append("- 是否与目标JD的核心要求一致（能力项、业务项、结果项）。")
    lines.append("- 是否保留了你最想在面试里展开的2-3个核心故事。")
    lines.append("")

    return "\n".join(lines) + "\n"


def compile_pdf(tex_path: Path) -> bool:
    if shutil.which("latexmk") is None:
        print("[WARN] 未检测到 latexmk，跳过 PDF 编译。")
        return False

    cmd = [
        "latexmk",
        "-xelatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        tex_path.name,
    ]
    try:
        subprocess.run(cmd, cwd=tex_path.parent, check=True)
        return True
    except subprocess.CalledProcessError:
        print("[ERROR] PDF 编译失败，请检查 tex 内容与本机字体。")
        return False


def main() -> None:
    args = parse_args()

    base_path = Path(args.base_resume).resolve()
    jd_path = Path(args.jd_file).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    base_resume = read_base_resume(base_path)
    jd_text = jd_path.read_text(encoding="utf-8")
    keywords = extract_keywords(jd_text)

    optimized = optimize_resume(base_resume, keywords, args.target_role)

    optimized_json_path = out_dir / "优化后简历.json"
    tex_path = out_dir / "中文简历.tex"
    html_path = out_dir / "中文简历网页.html"
    report_path = out_dir / "岗位调研与简历校准报告.md"

    optimized_json_path.write_text(
        json.dumps(optimized, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tex_path.write_text(render_latex(optimized), encoding="utf-8")
    html_path.write_text(render_html(optimized), encoding="utf-8")
    report_path.write_text(
        build_jd_analysis_markdown(
            jd_text=jd_text,
            keywords=keywords,
            optimized=optimized,
            target_role=args.target_role,
            base_resume_path=base_path,
            jd_path=jd_path,
        ),
        encoding="utf-8",
    )

    pdf_ok = False
    if not args.no_compile_pdf:
        pdf_ok = compile_pdf(tex_path)

    print("\n[OK] 已生成文件：")
    print(f"- {optimized_json_path}")
    print(f"- {tex_path}")
    if pdf_ok:
        print(f"- {out_dir / '中文简历.pdf'}")
    print(f"- {html_path}")
    print(f"- {report_path}")

    if args.open_html:
        webbrowser.open(html_path.as_uri())
        print("[OK] 已尝试打开 HTML 页面。")


if __name__ == "__main__":
    main()
