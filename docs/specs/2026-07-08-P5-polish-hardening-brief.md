# P5 收尾（安全掃描 + 架構圖 + 面試敘事）— 交給 Fable 5 的 spec brief

> **交付流程**：Fable 5 讀本 brief + [`../architecture/NORTH_STAR.md`](../architecture/NORTH_STAR.md) + **P0 design**（CI 結構——per-service workflow + paths 過濾 + GHCR/GITHUB_TOKEN，安全掃描要掛進這模式）+ 掃視 P1/P2/P3/P4 design（掌握整套要被敘事/繪圖/掃描的範圍）→ `superpowers:brainstorming` → 產出 `docs/specs/2026-07-08-P5-polish-hardening-design.md` →（plan 延後）。
> **精確度**：滿足 [`../../CLAUDE.md`](../../CLAUDE.md)「Fable 5 design 精確度契約（8 條）」——工具/version 具體、CI 掛載點具體、gate 政策明確。
> **定位**：P5 是**收尾打磨層**，把 P0–P4 做成的東西補上「求職 portfolio 該有的最後一哩」：**CI 安全掃描**（DevOps 成熟度訊號）、**架構圖**（一眼看懂整套）、**面試敘事**（把技術決策說成故事）。這是課程常缺、但面試最吃的一塊。

## 為什麼現在就能出 spec
P5 要掃描/繪圖/敘事的對象＝**整套已定案的架構**（P0–P4 design 全在）。掃描工具怎麼選、掛 CI 哪裡、gate 怎麼卡、圖畫什麼、敘事怎麼分 JD——這些**現在就決定得了**。只有「掃真實 image、截真實儀表板」是執行期對著實物做——**本 spec 明確標出那條界線**：spec 定「做什麼/用什麼/掛哪裡」，執行 plan 才對真 artifact 跑。

## 已鎖定決策（NORTH_STAR + 前階段，勿翻案）
- **一個平台打三種 JD**：DE / MLOps-LLMOps / DevOps-平台——敘事要能分別對這三種職缺講。
- **CI = GitHub Actions**，per-service workflow + paths 過濾（P0 已立 `hello-ci.yaml` 範本，安全掃描掛進同模式）。
- **成本紀律**：安全工具優先選**免費/OSS**（Trivy、gitleaks、CodeQL 免費），不引入付費 SaaS。
- **portfolio 誠實**：敘事只講「可示範的能力 + 真實做出的決策」，**不宣稱拿不出證據的成果數字**（對齊 README 誠實章、微調 B「只標可示範能力」）。

## 範圍（簇；Fable 5 定簇內細節與先後）

**P5-1 CI 安全掃描（DevOps 成熟度）**
- 把安全掃描掛進既有 GitHub Actions（沿 P0 per-service workflow / PR-checks 模式）：**image 弱點掃描**（Trivy 掃 build 出的 image）、**SAST**（CodeQL——GitHub 原生免費 / 或 Semgrep OSS）、**secret 掃描**（gitleaks / GitHub secret scanning）、可選 **IaC/manifest 掃描**（Trivy config / kube-linter 掃 k8s manifests）。
- **開放問題（要收斂）**：選哪幾個工具（傾向 Trivy image + gitleaks + CodeQL，皆免費）？掛在哪（PR-checks 只掃不 block？main workflow build 後掃？獨立 scheduled scan？）？**gate 政策**（HIGH/CRITICAL 擋 merge vs 只報告——portfolio 傾向「擋 CRITICAL、HIGH 警告」示範務實 gate）？掃描結果去哪（GitHub Security tab / SARIF upload / workflow summary）？誤報抑制機制（`.trivyignore` 等）？要不要對 P4 `frontend/`（npm audit / CodeQL JS）也掃？

**P5-2 架構圖**
- 產出「一眼看懂整套」的架構圖：整體三層（DE/MLOps/DevOps）+ 資料流（ingest→lakehouse→ML→呈現）+ GitOps/CI 迴圈 + M4/k8s 算力界線。可能不只一張（總覽 + 資料流 + ML 生命週期）。
- **開放問題**：用什麼工具（傾向**文字可版控的圖**——Mermaid / D2 / Excalidraw，Mermaid 在 GitHub README 原生渲染最省事；若複雜可 D2）？畫幾張、各張範圍？放哪（README + docs/architecture/）？是否含「本地 kind 按需跑」的部署拓撲圖（呼應平台不部署的敘事）？（注意 Mermaid 中文標點/subgraph direction 等坑——見主 harness 的 mermaid gotcha 紀律。）

**P5-3 面試敘事**
- 把技術決策寫成可講的故事，分別對 **DE / MLOps-LLMOps / DevOps** 三種 JD 各一組。每個決策點的「情境→取捨→為何這樣選」（如：為何 Kafka only、為何 pgvector 不 Qdrant、為何微調原生跑 M4、為何 CRAG、為何平台不部署只前端上雲、為何 Silver parse 用 Python 不硬上 Spark）。
- **開放問題**：敘事形式（每 JD 一份 one-pager？STAR 格式？決策紀錄 ADR 風格？）？放哪（`docs/` 下 / README 連結）？要點清單怎麼對齊各 design 已寫的「取捨理由」（很多 design 已有取捨論證——敘事是收攏，不是重寫）？要不要一份「這專案展示了哪些 JD 關鍵字」對照表？

**P5-4 README/文件最終打磨**
- README 已在規劃期更新過（架構/技術棧/藍圖）；P5 補**實作完成後**的最後一哩：一鍵啟動指令、截圖/GIF、公開 demo 連結（Vercel）、架構圖嵌入。
- **開放問題**：README 最終該有的區塊清單？截圖/GIF 拍哪些（ArgoCD sync、Grafana 儀表板、Airflow DAG、KServe 推論、前端）？demo 連結與「平台本地跑」的誠實說明並存？

## 設計方向約束（硬性，寫進 design）
- **spec 定義「做什麼」，不假裝已執行**：明確標出哪些是「現在可定的決策」（工具/掛載點/gate/圖範圍/敘事結構）vs 哪些是「執行 plan 才對真 artifact 跑」（掃真 image、截真儀表板）。**不要在 spec 裡放假的掃描結果或假數字**。
- **免費/OSS 優先**：安全工具不引入付費 SaaS。
- **誠實**：敘事與 README 不宣稱未驗證的成果；平台不部署要誠實講。
- **右尺寸**：P5 是收尾，別膨脹成第二個平台——掃描掛既有 CI、圖用文字可版控工具、敘事收攏既有取捨。YAGNI。
- **每步可測**：安全掃描有「跑得起來、會擋一個已知壞樣本」的驗收；圖能渲染；敘事對齊真實 design 決策。

## 交付與驗收（design 要回答的）
- 尤其拍板：**選哪幾個安全工具 + 掛 CI 哪裡 + gate 政策**、**架構圖工具與張數/範圍**、**面試敘事形式與落點**、**「可現在定」vs「執行期對實物做」的界線**。
- 具體：workflow YAML 掛載形狀（沿 P0 模式）、gate 條件、圖清單與工具、敘事文件清單與結構、README 最終區塊。

## 交付流程尾註
Fable 5 走 `superpowers:brainstorming` 出 design。**本階段只出 spec，plan 延後**。P5 收尾在 P0–P4 全實作後才執行，但 spec 現在就能定（掃描/繪圖/敘事的對象＝已定案架構）。右尺寸、免費工具、誠實敘事。滿足 CLAUDE.md 精確度契約 8 條。
