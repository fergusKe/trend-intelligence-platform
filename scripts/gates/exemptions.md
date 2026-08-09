# 守門閘豁免台帳

> [`docs/RULES.md`](../../docs/RULES.md) §5：**繞過要留台帳**。
> 任何「關掉某條檢查」「把某個檔案排除在掃描外」「暫時 skip 某個 case」都要在這裡佔一行。
> 兩支閘每次執行都會把本檔的豁免筆數印在 notes 裡——**筆數的成長本身就是訊號**。
>
> 這裡沒有隱形豁免：`scripts/gates/*.py` 裡不得出現未登錄在本表的 skip / exclude / 白名單。

<!-- exemptions:begin -->

| 日期 | 誰 | 閘 / 檢查碼 | 豁免對象 | 為什麼 | 什麼條件下移除 |
|---|---|---|---|---|---|

<!-- exemptions:end -->

目前 0 筆。

## 已知但**不算豁免**的設計取捨（寫在這裡避免被誤當成隱形旁路）

- `check_docs_drift.py` 的宣稱掃描只涵蓋 `README.md` 與 `CLAUDE.md`。
  這不是豁免，是**母體定義**：這兩份是對外宣告狀態的讀者面文件。
  `docs/RULES.md` 與閘自身的 docstring 會為了說明病灶而引用那些過期字串，納入母體會讓閘咬自己的說明文字。
- 行內 `<!-- drift-gate:ignore -->` 可讓單行跳過宣稱檢查。用了就要在上表登錄一行。
  （目前 repo 內使用次數：0——`grep -rn "drift-gate:ignore" --include=*.md .` 可現查。）
