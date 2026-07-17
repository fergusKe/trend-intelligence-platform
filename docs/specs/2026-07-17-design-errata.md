# Design 勘誤與調整清單（2026-07-17）

> **性質**：P0 實作完成後，三路獨立審查（核心 P0–P5／GA4 P6-P7／四支柱+觀測）＋ P0 實跑教訓的收斂文件。
> **效力**：本檔是所有 design 的補丁層——**寫任何 plan 前必讀**；與 design 本文衝突時以本檔為準。
> 拍板人：Fergus（2026-07-17）。

---

## A. 已直接修入 design 本文的事實性 bug（2 條）

| # | 檔案 | 修正 | 原因 |
|---|---|---|---|
| A1 | `2026-07-08-P1-data-pipeline-design.md` §0 | CI actions 版本改為「以 P0 §0 實際值為準」 | 原列 checkout@v5/setup-uv@v4/buildx@v3/login@v3/build-push@v6 是 P0 收緊 pass 之前的舊版號，與 P0 實際 pin（v7/v8.3.2/v4/v4/v7）整套對不上 |
| A2 | `2026-07-08-P2-ml-verticals-design.md` §2 wave 8 | `kserve-crd` Application 補 `syncOptions: [ServerSideApply=true]` | InferenceService CRD 巨大，client-side apply 撞 256KB annotation 上限——與 P0 實跑 ArgoCD install 同型的雷（P0/P3 都處理了，P2 漏） |

## B. Fergus 拍板的取捨（2026-07-17）

| # | 決定 | 影響的 plan |
|---|---|---|
| B1 | **ask-ai live demo 上線前必補最小限流**（per-day 上限或 Cloud Armor 配額；「成本不設限」原案作廢）——曝險自網址公開當下開始計 | ask-ai plan |
| B2 | P2 的 **LoRA 全鏈（GGUF→Ollama→win-rate）與 drift 自動重訓迴圈標為 stretch**；先保 tabular+RAG+情緒蒸餾（P2c-A）主敘事 | P2 plan |
| B3 | **GA 支柱維持完整範圍（8 頁不砍）**——Fergus 定調：「不只 DE，是整個流程」，功能完整性優先於敘事聚焦。審查提出的稀釋風險已知悉、接受 | ga-pillar plan |
| B4 | **search-live 引 Neon 前需二次拍板**（第三個外部雲資源；2 Cloud Run + 1 Neon 的維運面重複三次）——plan 動筆時再問一次 Fergus | search-pillar plan |
| B5 | **T5 受限解碼 layer-2（`prefix_allowed_tokens_fn` 通用機制）砍掉**，保 layer 1（logits mask）+ layer 3（生成後驗證 ∈ catalog） | p6-advanced-recall plan |

## C. 資源治理契約（全 plan 硬性；審查最大系統性缺口）

**背景**：runtime 是 M4 16GiB 上的 OrbStack VM（現配 ~7.8GiB）。20 份 design 沒有任何一份做過全階段資源總帳；P6/P7 五個新元件光 requests 就 ~4.7GiB；P1 的 Airflow/Postgres/MinIO 甚至沒寫 requests/limits。

1. **P1 plan 動筆前先產出全階段資源預算表**（每元件 requests/limits，含 Airflow 各子元件、Postgres、MinIO、Spark 尖峰、MLflow、KServe controller、cert-manager），對照 VM 上限。
2. **每份 plan 新增的常駐元件必須聲明 requests/limits**——design 沒寫的，plan 補。
3. **接受「不必同時全跑」**：分階段/分 demo profile 啟停（見 §D）。Flink 用 `suspended`、ClickHouse 縮 0、KServe minReplicas 0、ClickHouse limit 4Gi→2Gi、Flink state backend 改 HashMap（敘事保留在 README）。
4. **Host 側預算**：16GB − VM ≈ 8GB 要容納 macOS + Ollama（qwen3:8b ~6GB）+ 網站——**跑 Ollama 重活時叢集應暫停**（`make cluster-stop`）。

## D. 分階段啟停（Fergus 2026-07-17 要求：「不要所有服務全開」）

**第一層（P0 已實作，Makefile）**：
- `make cluster-stop` / `make cluster-start`——docker stop/start 全部 kind 節點容器，整座叢集暫停/恢復（狀態保留）。跑 Ollama/微調等 host 重活前先 stop。
- 恢復後 pod 需 1–3 分鐘重新收斂，`make verify` 可複驗。

**第二層（P1 起每份 plan 落實）**：
- 每份 plan 為其重量元件定義 `make demo-<階段>-up / demo-<階段>-down` target（GitOps 相容作法：暫停該 Application 的 auto-sync 再縮 0；恢復＝重開 auto-sync 讓 ArgoCD 收斂回來）。
- 展示 runbook 明列「此 demo 需要哪些 profile 同時在線」。

## E. Pin 再驗證前置 task（全 plan 硬性；P0 實證）

每份 plan 的 Task 0 必含「**pin 存在性驗證**」：動工當天用 API/registry 逐一驗證該階段所有 GitHub Actions tag、Helm chart 版號、image tag、模型名**真實存在**（不是查文件，是打 tags endpoint）。

P0 實證案例：design 宣稱 context7 查證的 `astral-sh/setup-uv@v8` tag 根本不存在（該 repo 不發 major-only tag）→ CI 首跑即摔。高風險清單：codeql-action、gitleaks-action、Airflow chart 1.22.0、spark-operator 2.5.1、KServe 0.19.0（chart 名本身待定）、cert-manager 1.20.3、Strimzi 1.1.0、transformers 5.13.0、`Qwen/Qwen3.5-2B`／Ollama tag（P2 plan 第一個 smoke test）。

## F. P0 實跑教訓（環境既定事實，後續 plan 直接沿用）

| 事實 | 後續 plan 怎麼用 |
|---|---|
| runtime 在 M4（SSH via Tailscale `100.74.192.11`，ssh-guard 白名單+審計）；開發/commit 在 M1 | 所有 live 步驟走 SSH；指令一律絕對路徑 |
| M4 docker=OrbStack；非互動 keychain 鎖死 | runtime 指令一律 `PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin DOCKER_CONFIG=/tmp/docker-noauth`（shim 使 credential helper 不可見） |
| kind hostPort：80 照舊、443→**8443**（M4 的 443 被 Tailscale 佔） | 任何 TLS 展示走 8443 或不做 |
| ArgoCD install 必須 `--server-side`；**install 後刪 argocd ns 的 netpol**（kind 內建 netpol 執法器丟 DNS/UDP 回包→controller 全癱） | 已固化進 Makefile；新增 netpol 的 design（若有）在 kind 上要先實測 |
| macOS bash 3.2：變數緊貼全形字元會炸（`$var（` → unbound）| shell script 中文訊息內變數一律 `${var}` |
| VS Code Remote-SSH auto port forward 會搶佔輸出中出現的 port | 已請 Fergus 關閉；驗證腳本用隨機 port 或先 lsof 檢查 |
| GHCR：public repo 的 Actions 產物 package 自動公開，無需手動改 visibility | P1+ 的新 image 同樣免手動步驟 |
| GitOps 前提：repo 已轉 public（2026-07-17） | ArgoCD 零憑證拉 manifest 成立 |

### F-1. P1 CI 首跑教訓（合 main 當天實證，2026-07-17；後續多 image plan 沿用）

| 事實 | 後續 plan 怎麼用 |
|---|---|
| **DagBag/import smoke 的臨時 venv 必須裝 image 內烤的整組 runtime 依賴，不能只裝套件本身** | airflow-ci 的 DagBag venv 原只裝 `yt_ingest`，但 `test_imports_available` 斷言 `import pyiceberg`（`pyiceberg` 非 `yt_ingest` 依賴、只在 Dockerfile 裝）→ CI 首跑摔。凡「在精簡 venv 驗證 image 可 import 的套件」的 test job，venv 安裝清單要與 Dockerfile 同組（見 airflow-ci `edc68f0` 修法）。 |
| **多支 CI 同 push 觸發、又各自 `git pull --rebase && push` 改同一檔 → bump race 撞合併衝突** | spark-ci／dbt-ci 併發改 `images.yaml` 相鄰行，dbt-ci 的 bump 步驟 rebase 撞衝突失敗（image 已推 GHCR，只缺 manifest 那行）。**每支 CI 的 bump 步驟要包 push-retry 迴圈**（`pull --rebase` 衝突時自動重試 `yq` 重設值再 push），或把三支 image tag 拆成三個獨立檔各自 bump。P1 當下走手動補 `dbt.tag`；此為 P2+ 多 image CI 的硬性設計點。 |

### F-2. P1 live rollout 教訓（首次真部署實證，2026-07-17；後續凡「外接既有 secret 給第三方 chart」沿用）

| 事實 | 後續 plan 怎麼用 |
|---|---|
| **Helm chart 的 value key 放錯層級會被靜默忽略、fallback 到內建預設，不報錯** | airflow.yaml 原把 `metadataSecretName` 放 valuesObject 頂層，但 Airflow chart 該 key 在 **`data.metadataSecretName`** 之下（context7 查證）→ 頂層被忽略→chart fallback 內建 postgresql（`airflow-postgresql.airflow`，本專案 `postgresql.enabled:false` 未部署）→ metadata 連線 DNS 解不出→migrate/create-user/所有 init 全 CrashLoop、app 永久 Degraded。**凡引用既有外部 secret 的 chart value（DB/Redis/S3…），plan 動筆時 context7 查證確切巢狀路徑，別憑記憶放頂層**；部署後首驗必看 migrate job pod log 確認連到正確 host。 |
| **ArgoCD 一次 sync 卡在「waiting for healthy」不會自我重試 apply** | migrate job 用佔位 image 建立後卡死，手動刪 job 後 ArgoCD 同一個 operation 只重跑 health check、不重 apply→job 永不重建（deadlock）。解法：`kubectl patch app --type merge` 把 `status.operationState.phase` 設 `Failed`（Application CRD 無 status subresource，可直接 merge patch），清掉殭屍 operation，再 patch `.operation` 觸發全新 sync 重 apply。**盡量別手刪 ArgoCD 託管的 immutable Job；要重建走「改 manifest→push→ArgoCD replace」**。 |

## G. 審查中確認健康、無需調整的部分（避免 plan 時重新懷疑）

- Gold 5 表 → P4 匯出合約逐欄核對**無斷裂**；P6 推薦→進階召回 schema v1→v2、P7 投影法的 additive 承諾經覆核成立（P7 遺留 known-limit：DAG 外手動 `dbt run` 會暫時抹掉投影欄，操作雷區已揭露）。
- 「問 AI／搜尋」靜態拓撲悖論的解法（預產策展＋標示清楚的外部 live demo）誠實成立。
- P4（Vercel+MCP）投報率全場最高；P5 可照抄；GA4 地基/P1 留言增補/P7 模型化標籤低風險。
- 觀測性三柱選型正確（Tempo/Loki 單 binary+emptyDir、Alloy 非 deprecated Promtail），唯資源帳併入 §C。
- aiops 主 demo 路徑定為 `/replay` fixture 重放（依賴鏈五層，現場真實觸發失敗面過高）——寫 aiops plan 時吸收。
