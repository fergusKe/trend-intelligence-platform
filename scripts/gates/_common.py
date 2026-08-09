"""守門閘共用層：現查事實 + 輸出格式。

設計紀律見 docs/RULES.md。本檔實作其中兩條的共用部分：
  §3 分母不能是空的 —— facts() 算出的每個母體都會被 assert_denominators() 檢查
  §4 圍籬 fail-closed —— 找不到 git / 解析失敗一律 raise，不做 fallback

Python 3.9+ 純標準庫（不得引入第三方依賴：這支要能在任何 checkout 上直接跑）。
"""
from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Sequence

# ── 現查（一律走 git index，不走檔案系統走查） ────────────────────────────────
# 為什麼走 git：檔案系統走查會把 .venv / __pycache__ / 未追蹤的暫存檔算進母體，
# 讓數字隨本機髒污浮動；git index 是 CI 與本機唯一一致的母體定義。


class GateError(RuntimeError):
    """閘自身無法運作（fail-closed：一律當紅燈，不得降級成通過）。"""


def _git(root: Path, *args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, check=True,
        )
    except FileNotFoundError as exc:  # 沒有 git → 紅，不 fallback（RULES §4）
        raise GateError("找不到 git 執行檔；閘無法確定母體，fail-closed") from exc
    except subprocess.CalledProcessError as exc:
        raise GateError(
            "git {} 失敗（rc={}）：{}".format(" ".join(args), exc.returncode, exc.stderr.strip())
        ) from exc
    return out.stdout


def tracked_files(root: Path) -> List[str]:
    raw = _git(root, "ls-files", "-z")
    files = [p for p in raw.split("\0") if p]
    if not files:
        raise GateError("git ls-files 回傳 0 筆——母體為空，閘無法作業（RULES §3）")
    return files


def _match(paths: Sequence[str], pattern: str) -> List[str]:
    """glob 比對。`a/b/**` 視為前綴比對；其餘走 fnmatch。"""
    if pattern.endswith("/**"):
        prefix = pattern[:-2]
        return [p for p in paths if p.startswith(prefix)]
    return [p for p in paths if fnmatch.fnmatch(p, pattern)]


_TEST_FUNC_RE = re.compile(r"^\s*def\s+test_", re.MULTILINE)


def facts(root: Path) -> Dict[str, int]:
    """所有「文件裡可能被寫死」的數字，一律由這裡現查（RULES §7）。

    新增 fact 要同時：(a) 在這裡算，(b) 進 REQUIRED_FACTS（若必須被文件宣告）。
    """
    paths = tracked_files(root)
    specs = _match(paths, "docs/specs/*.md")
    plans = _match(paths, "docs/plans/*.md")
    code = _match(paths, "*.py")
    workflows = _match(paths, ".github/workflows/*.yaml") + _match(paths, ".github/workflows/*.yml")

    test_files = [p for p in code if "/tests/" in p or Path(p).name.startswith("test_")]
    test_functions = 0
    for rel in test_files:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        test_functions += len(_TEST_FUNC_RE.findall(text))

    return {
        "spec_count": len(specs),
        "plan_count": len(plans),
        "code_file_count": len(code),
        "test_file_count": len(test_files),
        "test_function_count": test_functions,
        "workflow_count": len(workflows),
        "tracked_file_count": len(paths),
    }


def spec_filenames(root: Path) -> List[str]:
    return sorted(Path(p).name for p in _match(tracked_files(root), "docs/specs/*.md"))


EXEMPTIONS_REL = "scripts/gates/exemptions.md"


def exemption_count(root: Path) -> int:
    """RULES §5：繞過要留台帳，而且筆數要被印出來——成長本身就是訊號。"""
    p = root / EXEMPTIONS_REL
    if not p.is_file():
        raise GateError("{} 不存在——無法確認有多少條檢查被繞過，fail-closed".format(EXEMPTIONS_REL))
    text = p.read_text(encoding="utf-8", errors="replace")
    try:
        body = text.split("<!-- exemptions:begin -->", 1)[1].split("<!-- exemptions:end -->", 1)[0]
    except IndexError:
        raise GateError("{} 缺 exemptions:begin/end 標記，範圍無法界定，fail-closed"
                        .format(EXEMPTIONS_REL))
    n = 0
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue                       # 分隔線
        if cells and cells[0] in ("日期",):
            continue                       # 表頭
        n += 1
    return n


# ── 輸出 ──────────────────────────────────────────────────────────────────────
# 每個 finding 帶一個穩定錯誤碼。陽性對照斷言「碼」，不斷言訊息文字（RULES §2）。


class Findings:
    def __init__(self) -> None:
        self.items: List[Dict[str, str]] = []
        self.notes: List[str] = []

    def add(self, code: str, message: str) -> None:
        self.items.append({"code": code, "message": message})

    def note(self, message: str) -> None:
        self.notes.append(message)

    @property
    def codes(self) -> List[str]:
        return sorted({i["code"] for i in self.items})

    def emit(self, gate: str, as_json: bool, extra: Dict[str, object] = None) -> int:
        ok = not self.items
        if as_json:
            print(json.dumps({
                "gate": gate,
                "ok": ok,
                "codes": self.codes,
                "findings": self.items,
                "notes": self.notes,
                **(extra or {}),
            }, ensure_ascii=False, indent=2))
        else:
            for n in self.notes:
                print("  " + n)
            for i in self.items:
                print("{}  {}".format(i["code"], i["message"]), file=sys.stderr)
            if ok:
                print("PASS  {}（{} 條檢查全綠）".format(gate, len(self.notes)))
            else:
                print("FAIL  {}：{} 筆，碼 {}".format(gate, len(self.items), ",".join(self.codes)),
                      file=sys.stderr)
        return 0 if ok else 1


def resolve_root(arg: str = None) -> Path:
    if arg:
        return Path(arg).resolve()
    return Path(__file__).resolve().parents[2]
