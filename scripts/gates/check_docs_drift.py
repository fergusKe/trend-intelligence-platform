#!/usr/bin/env python3
"""閘：文件宣稱 vs 磁碟事實 對帳。

讀者＝每一次 push / PR 的作者（.github/workflows/guardrails.yaml，無 path filter），
      以及任何在本機跑 `python scripts/gates/check_docs_drift.py` 的接手 session。

要防的病灶（皆為本 repo 實際發生過）：
  A. README.md 首屏（public repo 第一段）宣稱「全專案 spec-only、實作待啟動、docs/plans/ 仍空」，
     而磁碟上已有 plan、Python 程式、Gold 表。
  B. CLAUDE.md §目前狀態自稱「活狀態正本」，卻停在上一個 phase。
  C. 文件裡寫死的計數（幾份 spec / 幾支測試）隨開發漂移，沒有任何機制會發現。
  D. plan 的 checkbox 一個都沒勾，但該 phase 早已實作完成 —— checkbox 是死的追蹤器。

錯誤碼（陽性對照斷言這些碼，不斷言訊息文字；RULES §2）：
  DRIFT000  母體為空（掃不到待掃文件 / git 母體為 0）——不得靜靜通過（RULES §3）
  DRIFT001  文件宣稱與磁碟事實矛盾
  DRIFT002  <!-- fact:NAME=VALUE --> 的 VALUE 與現查值不符
  DRIFT003  必填 fact 沒有在任何文件宣告過
  DRIFT004  plan 宣告 checkbox-policy: tracked，卻 0 勾（死掉的追蹤器）
  DRIFT005  plan 缺 marker 或 marker 值不在允許集合（fail-closed；RULES §4）

用法：
  python scripts/gates/check_docs_drift.py            # 檢查，紅則 exit 1
  python scripts/gates/check_docs_drift.py --json     # 機器可讀
  python scripts/gates/check_docs_drift.py --write    # 把所有 fact marker 回填成現查值
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (Findings, GateError, exemption_count, facts,  # noqa: E402
                     resolve_root)

GATE = "docs-drift"

# ── 掃描母體 ─────────────────────────────────────────────────────────────────
# 只掃「對外宣告狀態」的兩份讀者面文件。docs/RULES.md 與本檔會為了說明病灶而
# 引用那些過期字串，故刻意不在母體內——否則閘會咬自己的說明文字。
CLAIM_DOCS = ["README.md", "CLAUDE.md"]
# fact marker 可以出現在這些文件裡（台帳是主要落點）。
FACT_DOCS = ["README.md", "CLAUDE.md", "docs/SPEC_STATUS.md"]
# 每個必填 fact 至少要在 FACT_DOCS 其中一處被宣告，否則 DRIFT003。
# 固定非空集合 ⇒ 這條檢查的分母不可能是 0（RULES §3）。
REQUIRED_FACTS = ["spec_count", "plan_count", "code_file_count",
                  "test_function_count", "workflow_count"]

IGNORE_MARK = "<!-- drift-gate:ignore -->"

# ── 宣稱規則 ─────────────────────────────────────────────────────────────────
# (規則 id, 正則, 這句話等同於斷言「哪個 fact == 0」, 人話)
# 判準是「這句話宣告某個母體是空的」——只要對應 fact > 0 就是矛盾。
# 刻意用具體片語而非語意判斷：寧可漏抓，不可誤咬（誤咬會讓人關掉閘）。
CLAIM_RULES: List[Tuple[str, str, str, str]] = [
    ("plans-empty", r"`?docs/plans/`?[^。\n]{0,12}仍空|plans?\s*(?:目錄\s*)?仍空",
     "plan_count", "宣稱 docs/plans/ 仍空"),
    ("impl-not-started", r"實作待啟動|實作尚未啟動|尚未開始實作|實作未啟動",
     "code_file_count", "宣稱實作待啟動"),
    ("whole-project-spec-only", r"(?:全專案|全部|整個專案)\s*spec-only",
     "plan_count", "宣稱全專案 spec-only"),
    ("scaffold-only", r"(?:僅|只有|只是)\s*scaffold",
     "code_file_count", "宣稱程式目錄僅 scaffold"),
    ("zero-impl", r"零實作",
     "code_file_count", "宣稱零實作"),
]

FACT_RE = re.compile(r"<!--\s*fact:([a-z_]+)=(-?\d+)\s*-->")

PLAN_STATUS_RE = re.compile(r"<!--\s*plan-status:\s*([a-z-]+)\s*-->")
PLAN_POLICY_RE = re.compile(r"<!--\s*checkbox-policy:\s*([a-z-]+)\s*-->")
ALLOWED_PLAN_STATUS = {"not-started", "in-progress", "implemented", "superseded"}
ALLOWED_CHECKBOX_POLICY = {"tracked", "not-tracked"}
BOX_RE = re.compile(r"^\s*[-*]\s+\[( |x|X)\]", re.MULTILINE)


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8", errors="replace")


def check(root: Path) -> Findings:
    f = Findings()
    live = facts(root)

    # ── 分母（RULES §3）：三個母體任一為 0 都是紅，且各有自己的訊息 ──────────
    present_claim_docs = [d for d in CLAIM_DOCS if (root / d).is_file()]
    if not present_claim_docs:
        f.add("DRIFT000", "宣稱掃描母體為空：{} 一份都找不到".format("/".join(CLAIM_DOCS)))
    present_fact_docs = [d for d in FACT_DOCS if (root / d).is_file()]
    if not present_fact_docs:
        f.add("DRIFT000", "fact 掃描母體為空：{} 一份都找不到".format("/".join(FACT_DOCS)))
    if not CLAIM_RULES:
        f.add("DRIFT000", "宣稱規則表為空——迴圈斷言對空集合恆真")
    if not REQUIRED_FACTS:
        f.add("DRIFT000", "必填 fact 清單為空——迴圈斷言對空集合恆真")
    plan_files = sorted((root / "docs" / "plans").glob("*.md")) if (root / "docs" / "plans").is_dir() else []
    if live["plan_count"] > 0 and not plan_files:
        f.add("DRIFT000", "git 說有 {} 份 plan，但磁碟 glob 掃到 0 份——母體對不上"
              .format(live["plan_count"]))
    if f.items:
        return f  # 母體壞掉時，後面的逐一斷言全部無意義

    f.note("母體：宣稱文件 {} 份 / fact 文件 {} 份 / plan {} 份 / 宣稱規則 {} 條 / 必填 fact {} 項"
           .format(len(present_claim_docs), len(present_fact_docs), len(plan_files),
                   len(CLAIM_RULES), len(REQUIRED_FACTS)))
    f.note("現查：" + "  ".join("{}={}".format(k, v) for k, v in sorted(live.items())))
    f.note("豁免台帳（RULES §5）：{} 筆登錄於 scripts/gates/exemptions.md"
           .format(exemption_count(root)))

    # ── DRIFT001 宣稱 vs 事實 ────────────────────────────────────────────────
    for rel in present_claim_docs:
        for lineno, line in enumerate(_read(root, rel).splitlines(), start=1):
            if IGNORE_MARK in line:
                continue
            for rid, pattern, fact_key, human in CLAIM_RULES:
                if re.search(pattern, line) and live[fact_key] > 0:
                    f.add("DRIFT001",
                          "{}:{} {}（規則 {}），但現查 {}={} > 0"
                          .format(rel, lineno, human, rid, fact_key, live[fact_key]))

    # ── DRIFT002 / DRIFT003 寫死的數字 ───────────────────────────────────────
    declared: Dict[str, int] = {}
    for rel in present_fact_docs:
        for lineno, line in enumerate(_read(root, rel).splitlines(), start=1):
            for m in FACT_RE.finditer(line):
                name, value = m.group(1), int(m.group(2))
                if name not in live:
                    f.add("DRIFT002",
                          "{}:{} 宣告了不存在的 fact `{}`——閘算不出來，fail-closed"
                          .format(rel, lineno, name))
                    continue
                declared.setdefault(name, value)
                if value != live[name]:
                    f.add("DRIFT002",
                          "{}:{} fact {} 寫死 {}，現查 {}（跑 --write 回填）"
                          .format(rel, lineno, name, value, live[name]))
    for name in REQUIRED_FACTS:
        if name not in declared:
            f.add("DRIFT003",
                  "必填 fact `{}` 沒有在 {} 任一處宣告——這個數字目前沒有讀者"
                  .format(name, "/".join(FACT_DOCS)))

    # ── DRIFT004 / DRIFT005 plan 進度追蹤器是否活著 ──────────────────────────
    for path in plan_files:
        rel = str(path.relative_to(root))
        text = path.read_text(encoding="utf-8", errors="replace")
        sm, pm = PLAN_STATUS_RE.search(text), PLAN_POLICY_RE.search(text)
        if not sm or not pm:
            f.add("DRIFT005",
                  "{} 缺 <!-- plan-status: ... --> 或 <!-- checkbox-policy: ... --> marker"
                  .format(rel))
            continue
        status, policy = sm.group(1), pm.group(1)
        if status not in ALLOWED_PLAN_STATUS:
            f.add("DRIFT005", "{} plan-status `{}` 不在允許集合 {}（fail-closed）"
                  .format(rel, status, sorted(ALLOWED_PLAN_STATUS)))
            continue
        if policy not in ALLOWED_CHECKBOX_POLICY:
            f.add("DRIFT005", "{} checkbox-policy `{}` 不在允許集合 {}（fail-closed）"
                  .format(rel, policy, sorted(ALLOWED_CHECKBOX_POLICY)))
            continue
        boxes = BOX_RE.findall(text)
        checked = sum(1 for b in boxes if b.lower() == "x")
        f.note("{}：status={} policy={} checkbox {}/{}"
               .format(rel, status, policy, checked, len(boxes)))
        if policy == "tracked" and status in {"in-progress", "implemented"} \
                and boxes and checked == 0:
            f.add("DRIFT004",
                  "{} 宣告 checkbox-policy: tracked 且 status={}，卻 0/{} 勾——追蹤器是死的"
                  .format(rel, status, len(boxes)))
    return f


def write_facts(root: Path) -> int:
    live = facts(root)
    changed = 0
    for rel in FACT_DOCS:
        p = root / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")

        def sub(m):
            nonlocal changed
            name, old = m.group(1), m.group(2)
            if name not in live:
                return m.group(0)
            new = str(live[name])
            if new != old:
                changed += 1
            return "<!-- fact:{}={} -->".format(name, new)

        new_text = FACT_RE.sub(sub, text)
        if new_text != text:
            p.write_text(new_text, encoding="utf-8")
    print("回填 {} 個 fact marker".format(changed))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="文件宣稱 vs 磁碟事實 對帳閘")
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true", help="回填 fact marker 為現查值")
    args = ap.parse_args()
    root = resolve_root(args.root)
    try:
        if args.write:
            return write_facts(root)
        return check(root).emit(GATE, args.json)
    except GateError as exc:  # fail-closed
        print("DRIFT000  {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
