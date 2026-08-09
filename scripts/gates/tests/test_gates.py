"""守門閘的測試。

分三層，缺任何一層這組測試就會退化成裝飾品：
  1. 現況綠 —— 兩支閘在**當前 checkout** 上必須 exit 0。防「閘寫完就沒人跑」。
  2. 陽性對照 —— 逐一注入缺陷，斷言「exit 1 且錯誤碼恰好等於預期」（RULES §1 §2）。
     這一層是 positive_control.py 的 case 表，在這裡以每個 case 一個測試的形式跑，
     好處是 CI 的失敗訊息會直接指名「哪一條斷言炸了」。
  3. 母體/解析單元 —— facts() 與 parse_ledger() 的邊界行為（RULES §3 §4）。

跑法：
  pytest scripts/gates/tests/ -v
  python -m unittest discover -s scripts/gates/tests -t .   （無 pytest 時的退路）
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

GATES = Path(__file__).resolve().parents[1]
REPO = GATES.parents[1]
sys.path.insert(0, str(GATES))

import positive_control as pc  # noqa: E402
from _common import GateError, facts, tracked_files  # noqa: E402
from check_spec_ledger import parse_ledger  # noqa: E402


# ── 層 1：現況必須綠 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("gate", ["check_docs_drift.py", "check_spec_ledger.py"])
def test_gate_is_green_on_current_checkout(gate):
    p = subprocess.run([sys.executable, str(GATES / gate)], capture_output=True, text=True)
    assert p.returncode == 0, "{} 在當前 checkout 上是紅的：\n{}".format(gate, p.stdout + p.stderr)


# ── 層 2：陽性對照（每個 case 一個測試，失敗訊息會指名是哪一條）───────────────

def test_case_table_is_not_empty():
    """RULES §3：case 表若為空，下面的 parametrize 會 0 個測試，整層恆真。"""
    assert len(pc.CASES) >= 10, "陽性對照 case 少於 10 個，覆蓋不足"


def test_negative_baseline_is_green():
    """harness 自己的對照組：乾淨副本上兩支閘都得綠，否則所有『紅』都不可信。"""
    with tempfile.TemporaryDirectory(prefix="gate-test-base-") as tmp:
        root = Path(tmp)
        pc.snapshot(root)
        for gate in (pc.DRIFT, pc.LEDGER):
            rc, codes, out = pc.run_gate(gate, root)
            assert rc == 0, "乾淨副本上 {} 紅了（codes={}）：\n{}".format(gate.name, sorted(codes), out)


@pytest.mark.parametrize("name,gate,inject,expected",
                         pc.CASES, ids=[c[0] for c in pc.CASES])
def test_positive_control_bites(name, gate, inject, expected):
    with tempfile.TemporaryDirectory(prefix="gate-test-") as tmp:
        root = Path(tmp)
        pc.snapshot(root)
        inject(root)
        rc, codes, out = pc.run_gate(gate, root)
    assert rc == 1, "{}：注入缺陷後閘竟然通過了（rc={}）\n{}".format(name, rc, out)
    assert codes == expected, (
        "{}：紅了，但紅在別的地方——預期碼 {}，實際 {}。"
        "紅在非預期的原因等於沒驗到（RULES §2）\n{}"
        .format(name, sorted(expected), sorted(codes), out))


# ── 層 3：母體與解析 ─────────────────────────────────────────────────────────

def test_facts_denominators_are_all_positive():
    live = facts(REPO)
    zeros = [k for k, v in live.items() if v <= 0]
    assert not zeros, "以下母體為 0，掃描型斷言會恆真：{}".format(zeros)


def test_tracked_files_fails_closed_outside_a_repo():
    """RULES §4：拿不到 git 母體時要 raise，不得回傳空 list 讓閘靜靜通過。"""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(GateError):
            tracked_files(Path(tmp))


def test_parse_ledger_requires_markers():
    with pytest.raises(GateError):
        parse_ledger("# 沒有 ledger:begin / ledger:end 的檔案\n")


def test_parse_ledger_reports_malformed_rows_instead_of_skipping():
    text = (
        "<!-- ledger:begin -->\n"
        "| spec 檔 | 狀態 | 實作證據 |\n"
        "|---|---|---|\n"
        "| `a.md` | 已規劃未實作 | — |\n"
        "| 沒有 backtick 的檔名 | 已規劃未實作 | — |\n"
        "| `c.md` | 已實作 |\n"
        "<!-- ledger:end -->\n"
    )
    rows, malformed = parse_ledger(text)
    assert [r[1] for r in rows] == ["a.md"]
    assert len(malformed) == 2, "格式不合的行必須進 malformed（會變成 LEDGER005），不是被跳過"
