#!/usr/bin/env python3
"""閘：docs/specs/ 每一份 spec 都必須在 docs/SPEC_STATUS.md 台帳有且只有一行。

讀者＝每一次 push / PR 的作者（.github/workflows/guardrails.yaml，無 path filter）。

要防的病灶：這個 repo 有數十份 design spec，實作到的只有個位數。沒有台帳時，
「寫了 spec」與「做了東西」在任何載體上都長得一樣，於是差距可以無限期擴大而不被看見。
有台帳之後，新增一份 spec 的當下就必須表態它是「已實作 / 已規劃未實作 / 已作廢 / 勘誤層」，
差距在第一天就是一個可以被數出來的數字。

「有實作」怎麼判定（本閘的操作型定義）：
  台帳那一行填的每個 glob，都要對得到至少一個 **git 追蹤中的檔案**。
  不看 plan 有沒有寫、不看 checkbox、不看 commit 訊息——只看「磁碟上真的有東西」。
  這是刻意收窄的判準：它證明得了「有產出」，證明不了「產出正確」。後者是測試的工作，不是台帳的。

錯誤碼（陽性對照斷言這些碼；RULES §2）：
  LEDGER000  母體為空（spec 掃到 0 份，或台帳解析出 0 行）——不得靜靜通過（RULES §3）
  LEDGER001  spec 檔存在但台帳沒有對應行（新增 spec 忘了登錄）
  LEDGER002  台帳有行，但指向的 spec 檔不存在（刪檔/改名沒同步）
  LEDGER003  狀態=已實作，但實作證據 glob 對不到任何追蹤檔
  LEDGER004  狀態與證據欄不相容（未實作卻填證據 / 已作廢沒指出被誰取代 …）
  LEDGER005  狀態值不在允許集合（fail-closed；RULES §4）
  LEDGER006  同一份 spec 在台帳出現多行

用法：
  python scripts/gates/check_spec_ledger.py [--json] [--root PATH]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (Findings, GateError, _match, exemption_count,  # noqa: E402
                     resolve_root, tracked_files)

GATE = "spec-ledger"
LEDGER_REL = "docs/SPEC_STATUS.md"
BEGIN, END = "<!-- ledger:begin -->", "<!-- ledger:end -->"

STATUS_IMPLEMENTED = "已實作"
STATUS_PLANNED = "已規劃未實作"
STATUS_RETIRED = "已作廢"
STATUS_ERRATA = "勘誤層"
ALLOWED_STATUS = {STATUS_IMPLEMENTED, STATUS_PLANNED, STATUS_RETIRED, STATUS_ERRATA}

NONE_MARK = "—"
CODE_RE = re.compile(r"`([^`]+)`")


def parse_ledger(text: str) -> Tuple[List[Tuple[int, str, str, List[str]]], List[Tuple[int, str]]]:
    """回傳 (rows, malformed)。rows = (行號, spec 檔名, 狀態, 證據 token list)。

    fail-closed：在 begin/end 之間、以 `|` 開頭、又不是表頭/分隔線的行，
    只要解析不出三欄就進 malformed（不是「跳過」）。
    """
    lines = text.splitlines()
    try:
        i0 = next(i for i, ln in enumerate(lines) if BEGIN in ln)
        i1 = next(i for i, ln in enumerate(lines) if END in ln)
    except StopIteration:
        raise GateError("{} 找不到 {} / {} 標記——台帳範圍無法界定，fail-closed"
                        .format(LEDGER_REL, BEGIN, END))
    rows, malformed = [], []
    for lineno, raw in enumerate(lines[i0 + 1:i1], start=i0 + 2):
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and set("".join(cells)) <= set("-: "):
            continue                                     # 表格分隔線
        if cells and cells[0].startswith("spec"):
            continue                                     # 表頭
        if len(cells) < 3:
            malformed.append((lineno, raw))
            continue
        name_m = CODE_RE.search(cells[0])
        if not name_m:
            malformed.append((lineno, raw))
            continue
        evidence = [t for t in CODE_RE.findall(cells[2])]
        if not evidence and cells[2].strip() == NONE_MARK:
            evidence = []
        elif not evidence:
            malformed.append((lineno, raw))
            continue
        rows.append((lineno, name_m.group(1), cells[1].strip(), evidence))
    return rows, malformed


def check(root: Path) -> Findings:
    f = Findings()
    paths = tracked_files(root)
    spec_paths = _match(paths, "docs/specs/*.md")
    specs = sorted(Path(p).name for p in spec_paths)

    ledger_path = root / LEDGER_REL
    if not ledger_path.is_file():
        f.add("LEDGER000", "台帳 {} 不存在——沒有台帳就沒有對帳對象".format(LEDGER_REL))
        return f
    rows, malformed = parse_ledger(ledger_path.read_text(encoding="utf-8", errors="replace"))

    # ── 分母：兩邊都要非空（RULES §3「綠燈本身也有分母」）───────────────────
    if not specs:
        f.add("LEDGER000", "docs/specs/*.md 掃到 0 份——母體為空，逐一斷言恆真")
    if not rows:
        f.add("LEDGER000", "台帳解析出 0 行——母體為空，逐一斷言恆真")
    if f.items:
        return f
    f.note("母體：spec {} 份 / 台帳 {} 行".format(len(specs), len(rows)))
    f.note("豁免台帳（RULES §5）：{} 筆登錄於 scripts/gates/exemptions.md"
           .format(exemption_count(root)))

    # ── fail-closed：解析不了的行是紅，不是跳過（RULES §4）────────────────────
    for lineno, raw in malformed:
        f.add("LEDGER005", "{}:{} 台帳行解析失敗，欄位不足或格式不合：{}"
              .format(LEDGER_REL, lineno, raw.strip()[:90]))

    seen = {}
    for lineno, name, status, evidence in rows:
        if name in seen:
            f.add("LEDGER006", "{}:{} spec `{}` 重複登錄（已見於第 {} 行）"
                  .format(LEDGER_REL, lineno, name, seen[name]))
            continue
        seen[name] = lineno

        if status not in ALLOWED_STATUS:
            f.add("LEDGER005", "{}:{} spec `{}` 狀態 `{}` 不在允許集合 {}（fail-closed）"
                  .format(LEDGER_REL, lineno, name, status, sorted(ALLOWED_STATUS)))
            continue

        if name not in specs:
            f.add("LEDGER002", "{}:{} 台帳指向不存在的 spec `{}`".format(LEDGER_REL, lineno, name))
            continue

        if status == STATUS_IMPLEMENTED:
            if not evidence:
                f.add("LEDGER004", "{}:{} spec `{}` 標 {} 卻沒填實作證據"
                      .format(LEDGER_REL, lineno, name, STATUS_IMPLEMENTED))
            for pat in evidence:
                if not _match(paths, pat):
                    f.add("LEDGER003",
                          "{}:{} spec `{}` 標 {}，但證據 glob `{}` 對不到任何追蹤檔"
                          .format(LEDGER_REL, lineno, name, STATUS_IMPLEMENTED, pat))
        elif status in (STATUS_PLANNED, STATUS_ERRATA):
            if evidence:
                f.add("LEDGER004",
                      "{}:{} spec `{}` 標 {} 卻填了證據 {}——狀態與證據不相容"
                      .format(LEDGER_REL, lineno, name, status, evidence))
        elif status == STATUS_RETIRED:
            if len(evidence) != 1:
                f.add("LEDGER004",
                      "{}:{} spec `{}` 標 {} 必須在證據欄填「被誰取代」的 spec 檔名（恰一個）"
                      .format(LEDGER_REL, lineno, name, STATUS_RETIRED))
            elif evidence[0] not in specs:
                f.add("LEDGER004",
                      "{}:{} spec `{}` 標 {}，但取代者 `{}` 不是現存 spec"
                      .format(LEDGER_REL, lineno, name, STATUS_RETIRED, evidence[0]))

    for name in specs:
        if name not in seen:
            f.add("LEDGER001",
                  "spec `{}` 沒有在 {} 登錄——新增 spec 必須同時表態狀態"
                  .format(name, LEDGER_REL))

    counts = {}
    for _, name, status, _e in rows:
        if status in ALLOWED_STATUS and name in specs:
            counts[status] = counts.get(status, 0) + 1
    f.note("台帳分佈：" + "  ".join("{}={}".format(k, v) for k, v in sorted(counts.items())))
    return f


def main() -> int:
    ap = argparse.ArgumentParser(description="spec ↔ 台帳 對帳閘")
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = resolve_root(args.root)
    try:
        return check(root).emit(GATE, args.json)
    except GateError as exc:  # fail-closed
        print("LEDGER000  {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
