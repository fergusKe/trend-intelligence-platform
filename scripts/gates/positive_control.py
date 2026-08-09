#!/usr/bin/env python3
"""陽性對照 harness：證明 scripts/gates/ 的每支閘「在該紅的時候真的會紅」。

讀者＝每一次 push / PR 的作者（.github/workflows/guardrails.yaml，無 path filter）。

做法：把 repo 的**工作區快照**（tracked + 未被 .gitignore 排除的 untracked）複製到一個
暫存目錄、`git init` 建索引，在副本上注入缺陷，跑閘，斷言結果。原 repo 全程唯讀，
不需要「注入完再還原」——沒有東西被改過。

兩層斷言（RULES §1 §2）：
  1. **陰性基線**：未注入的副本，兩支閘都必須 exit 0。
     這一層是 harness 自己的陽性對照——如果連乾淨副本都紅（複製漏檔、git init 失敗、
     路徑算錯），那後面每一個 case 都會「紅」，但紅在 harness 而不是在被驗的規則上。
     沒有這一層，整個檔案會變成一個看起來很嚴謹的假證明。
  2. **逐 case**：注入一個缺陷 → 斷言 exit code == 1 **且輸出的錯誤碼集合恰好等於預期**。
     只斷言 exit != 0 不夠：那分不出「規則咬到了」跟「腳本 crash 了」。

用法：
  python scripts/gates/positive_control.py           # 全部；exit 0 = 每支閘都證明會咬人
  python scripts/gates/positive_control.py -v        # 印出每個 case 的實際輸出
  python scripts/gates/positive_control.py -k DRIFT  # 只跑名字含 DRIFT 的 case
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Set, Tuple

GATES_DIR = Path(__file__).resolve().parent
REPO = GATES_DIR.parents[1]
DRIFT = GATES_DIR / "check_docs_drift.py"
LEDGER = GATES_DIR / "check_spec_ledger.py"


# ── 副本 ─────────────────────────────────────────────────────────────────────

def snapshot(dest: Path) -> None:
    """複製工作區快照到 dest 並建立 git 索引（閘的母體一律來自 git ls-files）。"""
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True, text=True, check=True,
    ).stdout
    files = [f for f in out.split("\0") if f]
    if not files:
        raise SystemExit("harness 錯誤：來源 repo 掃到 0 個檔案")
    for rel in files:
        src = REPO / rel
        if not src.is_file():
            continue
        tgt = dest / rel
        tgt.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, tgt)
    subprocess.run(["git", "-C", str(dest), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(dest), "add", "-A"], check=True,
                   capture_output=True)


def run_gate(gate: Path, root: Path) -> Tuple[int, Set[str], str]:
    p = subprocess.run([sys.executable, str(gate), "--root", str(root), "--json"],
                       capture_output=True, text=True)
    raw = p.stdout.strip()
    try:
        codes = set(json.loads(raw)["codes"])
    except Exception:
        # 閘在 fail-closed 路徑上會把碼吐到 stderr 而非 JSON——把它撈出來
        codes = set(re.findall(r"\b(?:DRIFT|LEDGER)\d{3}\b", p.stdout + p.stderr))
    return p.returncode, codes, (p.stdout + p.stderr)


# ── 注入器 ───────────────────────────────────────────────────────────────────

def _edit(root: Path, rel: str, old: str, new: str, count: int = 1) -> None:
    p = root / rel
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit("harness 錯誤：{} 找不到待注入錨點 {!r}".format(rel, old[:60]))
    p.write_text(text.replace(old, new, count), encoding="utf-8")


def _reindex(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)


def inj_drift001(root: Path) -> None:
    """README 首屏重新長出「全專案 spec-only、實作待啟動」——正是實際發生過的病灶。"""
    p = root / "README.md"
    p.write_text(p.read_text(encoding="utf-8").replace(
        "# trend-intelligence-platform",
        "# trend-intelligence-platform\n\n> 狀態：全專案 spec-only、實作待啟動（`docs/plans/` 仍空）。",
        1), encoding="utf-8")


def inj_drift002(root: Path) -> None:
    _edit(root, "docs/SPEC_STATUS.md", "<!-- fact:spec_count=", "<!-- fact:spec_count=999 --><!-- x=")


def inj_drift003(root: Path) -> None:
    text = (root / "docs/SPEC_STATUS.md").read_text(encoding="utf-8")
    text = re.sub(r"<!--\s*fact:workflow_count=\d+\s*-->", "（略）", text)
    (root / "docs/SPEC_STATUS.md").write_text(text, encoding="utf-8")


def inj_drift004(root: Path) -> None:
    """把 plan 宣告成「checkbox 有在追」——但它 0/56。死掉的追蹤器要被抓出來。"""
    _edit(root, "docs/plans/2026-07-16-P0-platform-foundation-implementation.md",
          "<!-- checkbox-policy: not-tracked -->", "<!-- checkbox-policy: tracked -->")


def inj_drift005(root: Path) -> None:
    """狀態值打成沒看過的字 —— fail-closed 要擋，不是跳過（RULES §4）。"""
    _edit(root, "docs/plans/2026-07-16-P0-platform-foundation-implementation.md",
          "<!-- plan-status: implemented -->", "<!-- plan-status: done -->")


def inj_drift000(root: Path) -> None:
    """宣稱掃描母體歸零 —— 迴圈斷言對空集合恆真，必須紅（RULES §3）。"""
    (root / "README.md").unlink()
    (root / "CLAUDE.md").unlink()
    _reindex(root)


def inj_ledger001(root: Path) -> None:
    """新增一份 spec 卻沒在台帳登錄 —— 「17 份 spec 零實作」的第一天就要被看見。"""
    (root / "docs/specs/9999-12-31-injected-fake-spec.md").write_text(
        "# 注入用假 spec（陽性對照）\n", encoding="utf-8")
    _reindex(root)


def inj_ledger002(root: Path) -> None:
    _edit(root, "docs/SPEC_STATUS.md", "<!-- ledger:end -->",
          "| `9999-12-31-ghost-spec.md` | 已規劃未實作 | — |\n\n<!-- ledger:end -->")


def inj_ledger003(root: Path) -> None:
    """標「已實作」但證據 glob 對不到任何追蹤檔 —— 空口宣稱實作。"""
    _edit(root, "docs/SPEC_STATUS.md",
          "| `2026-07-08-P0-platform-foundation-brief.md` | 已實作 | `platform/bootstrap/**`",
          "| `2026-07-08-P0-platform-foundation-brief.md` | 已實作 | `nonexistent/never/**`")


def inj_ledger004(root: Path) -> None:
    """標「已規劃未實作」卻填了實作證據 —— 狀態與證據互相矛盾。"""
    _edit(root, "docs/SPEC_STATUS.md",
          "| `2026-07-08-P2-ml-verticals-design.md` | 已規劃未實作 | — |",
          "| `2026-07-08-P2-ml-verticals-design.md` | 已規劃未實作 | `ml/**` |")


def inj_ledger005(root: Path) -> None:
    """狀態欄錯字 —— fail-open 會讓這一行從此不受任何約束（RULES §4）。"""
    _edit(root, "docs/SPEC_STATUS.md",
          "| `2026-07-08-P3-ptt-ingest-design.md` | 已規劃未實作 | — |",
          "| `2026-07-08-P3-ptt-ingest-design.md` | 已規劃未實做 | — |")


def inj_ledger006(root: Path) -> None:
    _edit(root, "docs/SPEC_STATUS.md",
          "| `2026-07-08-P4-presentation-layer-brief.md` | 已規劃未實作 | — |",
          "| `2026-07-08-P4-presentation-layer-brief.md` | 已規劃未實作 | — |\n"
          "| `2026-07-08-P4-presentation-layer-brief.md` | 已規劃未實作 | — |")


def inj_ledger000(root: Path) -> None:
    for p in (root / "docs/specs").glob("*.md"):
        p.unlink()
    _reindex(root)


# (case 名, 閘, 注入器, 預期錯誤碼集合)
CASES: List[Tuple[str, Path, Callable[[Path], None], Set[str]]] = [
    ("DRIFT000-空母體",        DRIFT,  inj_drift000,  {"DRIFT000"}),
    ("DRIFT001-過期狀態宣告",  DRIFT,  inj_drift001,  {"DRIFT001"}),
    ("DRIFT002-寫死數字漂移",  DRIFT,  inj_drift002,  {"DRIFT002"}),
    ("DRIFT003-必填fact消失",  DRIFT,  inj_drift003,  {"DRIFT003"}),
    ("DRIFT004-死掉的checkbox", DRIFT, inj_drift004,  {"DRIFT004"}),
    ("DRIFT005-未知狀態值",    DRIFT,  inj_drift005,  {"DRIFT005"}),
    ("LEDGER000-空母體",       LEDGER, inj_ledger000, {"LEDGER000"}),
    ("LEDGER001-新spec未登錄", LEDGER, inj_ledger001, {"LEDGER001"}),
    ("LEDGER002-台帳指向幽靈", LEDGER, inj_ledger002, {"LEDGER002"}),
    ("LEDGER003-已實作無證據", LEDGER, inj_ledger003, {"LEDGER003"}),
    ("LEDGER004-狀態證據不符", LEDGER, inj_ledger004, {"LEDGER004"}),
    ("LEDGER005-狀態值錯字",   LEDGER, inj_ledger005, {"LEDGER005"}),
    ("LEDGER006-重複登錄",     LEDGER, inj_ledger006, {"LEDGER006"}),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="守門閘陽性對照")
    ap.add_argument("-k", default=None, help="只跑名字含此字串的 case")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if not CASES:
        print("FAIL  case 清單為空——陽性對照對空集合恆真（RULES §3）", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="gate-pc-baseline-") as tmp:
        base = Path(tmp)
        snapshot(base)
        for gate in (DRIFT, LEDGER):
            rc, codes, out = run_gate(gate, base)
            if rc != 0:
                print("FAIL  陰性基線：未注入的副本上 {} 就已經紅了（rc={} codes={}）\n{}"
                      .format(gate.name, rc, sorted(codes), out), file=sys.stderr)
                print("      → 這代表 harness 本身壞了；所有 case 的『紅』都不可信。", file=sys.stderr)
                return 1
        print("OK    陰性基線：乾淨副本上兩支閘皆 exit 0（harness 可信）")

    failed = 0
    for name, gate, inject, expected in CASES:
        if args.k and args.k not in name:
            continue
        with tempfile.TemporaryDirectory(prefix="gate-pc-") as tmp:
            root = Path(tmp)
            snapshot(root)
            inject(root)
            rc, codes, out = run_gate(gate, root)
        ok = (rc == 1) and (codes == expected)
        print("{}  {:<26} rc={} codes={}{}".format(
            "OK   " if ok else "FAIL ", name, rc, sorted(codes) or "[]",
            "" if ok else "  ← 預期 rc=1 codes={}".format(sorted(expected))))
        if args.verbose or not ok:
            print("\n".join("        " + ln for ln in out.strip().splitlines()[:25]))
        failed += 0 if ok else 1

    total = sum(1 for c in CASES if not args.k or args.k in c[0])
    if failed:
        print("\nFAIL  陽性對照 {}/{} 個 case 未通過".format(failed, total), file=sys.stderr)
        return 1
    print("\nPASS  陽性對照 {}/{} 全數證明會咬人".format(total, total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
