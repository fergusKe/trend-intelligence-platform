# AI 維運事件敘事者 spec — brief（LLM 讀 Prometheus 告警/指標＋Loki log → 產 grounded 事件報告；複用 P2b LLMClient/RAG＋觀測性 Alertmanager；反幻覺紀律為主體）

> **精確度契約**：依 repo `CLAUDE.md`「Fable 5 design 精確度契約（8 條）」交辦；design 逐條自檢，**開放問題一律收斂成決定、不下推**。
> **緣起（Fergus 2026-07-10 令）**：評估 hiskio 課程「Prometheus 智能維運：DeepSeek + Dify 自動巡檢產出異常報告」。接地確認**明確缺口**：我方觀測性四柱＋自癒都齊，但**「LLM 讀 Prometheus 指標/告警 → 自動產異常/根因報告」完全沒有**（異常判定全走規則式閾值）。此 spec 補這塊。守 [[feedback_evolve_beyond_past_projects]]（參考是輸入非天花板）。
> **參考立場（Fergus 明示）**：**課程只參考「怎麼應用」，不採用 Dify、不採用 DeepSeek**。Dify＝重型常駐平台（自帶 DB/Redis/向量庫）違一工一具——我方有 LangGraph 取代；DeepSeek＝雲端 API——我方用自有 Ollama/Gemini（P2b LLMClient）。可移植的是**應用範式與 prompt/workflow 結構**，非其技術棧。
> **本 spec 最重要正確性面＝反幻覺**：課程的異常「判定」其實是 PromQL/規則算的、**LLM 只做敘事**，但課程仍出現 LLM **幻覺編造時間戳**（實例報告寫「2023-10-27（假設）」）。我方版本以 ask-ai `check_numbers` 純函式紀律根治：**數字/時間戳一律程式取自 PromQL/Loki（決定性），LLM 只提根因假設＋處置建議，絕不推算或編造數字**——這個「比課程更嚴謹的 grounding」本身是作品集講點。

---

## 框架上游（binding，不得抵觸）

- **[觀測性強化 design](2026-07-10-observability-hardening-design.md)**（本 spec 的資料源與觸發源，**唯讀複用不改寫**）：§6 Alertmanager `discord_configs`＋AlertmanagerConfig CRD（:280-289）＝告警路由既有機制，本 spec **additive 加一個 webhook receiver**（不改 Discord route）；既有 PrometheusRule 告警群（YTDataStale/MLServingDown/RAGDegradedRateHigh/PipelineHealth*/LiveEndpoint*/SLO burn-rate…）＝事件敘事的輸入告警；postgres-exporter/statsd/Flink metrics＝PromQL 查證的指標源；Loki（§2）＝log 證據源；Grafana＝報告可視化。**拓撲鐵律延續**：本 spec 服務叢集內、前端零 live 依賴。
- **[P2 ML verticals design](2026-07-08-P2-ml-verticals-design.md)**（LLM 棧正本，**唯讀複用**）：§8 生成 LLM 切換（:363-368）＝**LLMClient 抽象：Ollama `qwen3.5:9b` host 預設／Gemini `gemini-2.5-flash` fallback**、`ollama-host.ml.svc` ExternalName k8s→host 接線、provider 欄如實回報、自動 fallback（Ollama 逾時 30s→Gemini）；`rag_service/{graph.py,llm.py,metrics.py}`（:145）＝LangGraph 服務形範本；`rag_tokens_total`/`rag_cost_usd_total`/`rag_requests_total{provider,outcome}`（:381）＝成本/token/延遲指標範式（本 spec 同款）；MLflow prompt registry（:380）＝prompt 版本化。RAG 檢索面（`retrieval.py` hybrid RRF）＝runbook 檢索可複用。**⚠️model pin 對齊**：P2 design :7 已把 RAG 生成升 `qwen3.5:9b`，但 ask-ai/crosscut 舊標 `qwen3:8b`——**Fable 5 第一手 grep P2b LLMClient 實際 default 為準、不自定 pin**（同 [[project_llm_agent_architecture]] 的 pin 對齊警示）。
- **[問 AI design](2026-07-10-ask-ai-design.md)**（反幻覺 pattern 正本，**複用純函式紀律**）：§4.2 `check_numbers(answer, fact_numbers) -> {checked, verified, unverified[]}` 純函式（:245-252）＝**本 spec 的核心複用**——事實數字集遞迴收集、答案數字抽取比對（含 round/×100÷100 等價形）、`unverified` 非空即 fail；synthesis prompt 硬性「數字必須逐字取自工具結果不得推算」（:252）。本 spec 的「事實數字集」＝PromQL 查詢結果＋Loki 統計＋告警 labels；LLM 敘事的數字/時間戳全部對此驗證。**vendor+CI diff 共用單一真源**（沿 crosscut 決策 7；不跨 image path dep）。
- **NORTH_STAR**：定位＝DE+MLOps+DevOps 三線一體、成本紅線不適用（跑 infra 是目的）、一工一具（agent 框架只 LangGraph、LLM 只 Ollama/Gemini 雙 provider、監控只 Prom+Grafana+Loki+Tempo）、拓撲鐵律（前端純靜態、live 能力以四件套佐證）。

## 接地鐵律（grounding-first，違者作廢）

Fable 5 須**第一手 grep/讀**：
- **觀測性 spec** §6 Alertmanager webhook 機制（AlertmanagerConfig CRD 怎麼加 receiver、route matcher 語法）、既有告警清單（哪些告警值得觸發敘事）、PromQL 指標名（exporter 自訂查詢/instrumentator/statsd）、Loki LogQL 查法（`| json | service=...`）、Grafana datasource。
- **P2b LLMClient 實作合約**（trend repo `ml/rag/service/src/rag_service/llm.py`——若無實碼則鎖 P2 design §8 合約，同問 AI spec §0.3 誠實處理）：provider 切換、token 採集、成本常數表、`ollama-host.ml.svc` 接線、`OLLAMA_BASE_URL` env。證明「複用 LLMClient 換掉 DeepSeek」可行、錨進 design。
- **ask-ai `check_numbers`/guardrails.py 純函式**（`ml/ga_ask/.../guardrails.py` 或 ask-ai design §4.2 合約）：數字驗證演算法、等價形展開、政策——本 spec 的數字/時間戳驗證直接沿用同結構。
- **課程可移植素材**（`/Users/fergus/Desktop/workshop/fergus/course/hiskio/Prometheus 智能維運.../`，唯讀取材、碼不照抄、憑證勿引）：路線 A `alert_handler.py`（webhook→LLM→報告骨架、system/user prompt 樣板 :128-147）、路線 A `alert_rules.yml`（PromQL 閾值告警範式）、路線 B `inspector.sh`（PromQL query→加總→組自然語言句→餵 LLM 的取數邏輯 :23-56）、路線 B `Prometheus应用巡检.yml` code 節點（規則式 5 級分類→固定 SOP :259-279＝「程式判定、LLM 敘事」的具體落法）。**明確不取**：Dify workflow 引擎/平台、DeepSeek、明文洩漏憑證、只讀第一筆告警的 bug。
- **版本敏感處**（LangChain/LangGraph 版、Alertmanager webhook payload schema、Prometheus HTTP API `/api/v1/query`）用 context7。
**本階段只出 spec，plan 延後。**

---

## 一句話目標

AI 維運事件敘事者＝**告警觸發式「AI SRE 助手」**：Alertmanager 告警 fire → webhook 進我方 LangGraph graph → 決定性蒐證（PromQL 查該告警相關指標近況＋相關指標＋Loki 近期 log）→ RAG 檢索 runbook/SOP → LLM 產**grounded 事件報告**（告警資訊＋指標證據＋log 證據＋根因假設＋處置建議＋出處），**數字/時間戳全程式取、LLM 只敘事並經 `check_numbers` 驗證**。複用 P2b LLMClient（Ollama/Gemini，換掉 DeepSeek 零摩擦）＋RAG＋觀測性 Alertmanager；棄 Dify（LangGraph 取代）。報告落表＋選配推 Discord＋前端平台架構支柱以策展樣本佐證。敘事定位＝**LLMOps 應用到 DevOps＝DE+MLOps+DevOps 三線交會**，且以反幻覺紀律做得比課程對。

## 為什麼 grounded 而非畫大餅（複用邊界＝本 spec 的靈魂）

我方**已有全部零件**：Alertmanager+webhook（觀測性 spec §6 剛建）、LangGraph 服務形（P2b `rag_service`）、LLMClient 雙 provider（Ollama/Gemini，換 DeepSeek 只是不同 provider）、RAG hybrid 檢索（跑 runbook 語料）、`check_numbers` 反幻覺純函式（ask-ai）、Prometheus HTTP API/Loki（查證源）、成本/token 指標範式（P2b）、prompt registry（MLflow）。**本 spec 不重造任何一個**——把它們接成一條「告警→蒐證→grounded 敘事」的鏈，補上確認缺口。這就是進化非複刻：課程用 DeepSeek+Dify 拼一個會幻覺數字的巡檢，我方用自有棧拼一個數字零幻覺的 AI SRE。

## Fable 5 要收斂拍板的項目（逐一給明確決定，不下推）

1. **觸發模式拍板**：**主＝告警觸發式**（Alertmanager webhook，路線 A 範式）——哪些既有告警值得觸發敘事（傾向 critical＋部分 warning，避免噪音；info 不觸發）；**次＝是否加排程健康摘要**（路線 B 概念但用 PromQL 非 Dify：cron 定時對關鍵 SLO/指標產「值班摘要」）——拍板做或列進化方向，給理由。**明標與既有 Discord 告警的分工**：Discord＝「哪個告警響了」（既有 §6），本 spec＝「這個告警發生了什麼、可能為何、怎麼處理」（加值敘事層，不取代原告警）。
2. **蒐證層設計（決定性、反幻覺的基礎）**：告警 fire 後怎麼自動蒐證——PromQL 查詢集（該告警的觸發指標近 N 分鐘序列＋語意相關指標，如某服務 5xx 升則同拉其延遲/RPS/重啟數）、Loki 查該服務近期 error log、告警 labels/annotations 解析。**全部程式取、結構化成 fact set**（供 LLM 敘事與 `check_numbers` 驗證）。拍板 fact set schema、查哪些指標（可定「告警→蒐證模板」對照表，如 `MLServingDown`→查 predictor up/延遲/重啟＋KServe log）。
3. **LangGraph graph 設計**：節點串法（傾向 `gather_evidence`[決定性 PromQL/Loki]→`retrieve_runbook`[RAG]→`narrate`[LLM 產報告]→`verify_numbers`[check_numbers 純函式]→`persist`）；是否需要 reflection/重試（narrate 出現 unverified 數字→帶清單重試一次，沿 ask-ai `MAX_OUTPUT_RETRY=1`）。**明標 agentic 判斷保留在該在的層**（蒐證/驗證決定性、敘事才 LLM）。服務形（FastAPI k8s Deployment，沿 P2b `rag_service` 範本；ingress？還是純內部 webhook 端點）。
4. **反幻覺落地（本 spec 最重要正確性面）**：複用 ask-ai `check_numbers` 純函式——**事實數字集＝PromQL 結果＋Loki 統計＋告警數值**；LLM 報告的每個數字/百分比/時間戳對此驗證；**時間戳特別處理**（課程幻覺重災區：報告時間一律程式注入 UTC/當下，prompt 硬性「不得自行生成時間」）；`unverified` 非空政策（重試一次仍 fail→報告標警示 badge「以下數字未能對應查證結果」，誠實優先）。synthesis prompt 硬性指示（沿 ask-ai :252）。
5. **RAG runbook 語料拍板**：處置建議的出處——runbook/SOP 語料哪來（傾向：本 repo 自寫一份 `docs/runbooks/` 對應各告警的處置 SOP，embedding 進 pgvector，複用 P2b `retrieval.py` hybrid 檢索）；語料表落點（新表 `ml.ops_runbook_documents` 或複用機制）；**明標與 P2b RAG 語料（YouTube 留言）/搜尋語料（PTT）獨立**（不同語料、同基建）。若判定 v1 先不做 RAG（LLM 純憑蒐證敘事），須誠實論證並列進化方向。
6. **LLM 換 provider（換掉 DeepSeek）落地**：複用 P2b LLMClient——Ollama `qwen3.5:9b` 預設/Gemini fallback、`ollama-host.ml.svc` 接線、provider 欄回報、成本/token 指標（本服務自有 `aiops_*` 指標族，沿 `rag_*` 範式）。prompt（system＝資深 SRE 分析師角色＋輸出結構；取材課程 §3 prompt 樣板但改我方語境）進 MLflow prompt registry 版本化。model pin 以 P2b 實際 default 為準（見框架上游 ⚠️）。
7. **報告產出與呈現（守拓撲鐵律，四件套）**：事件報告落表（新表 `ml.ops_incidents`：alert 資訊/fact set/root_cause/remediation/sources/provider/token/unverified/generated_at）；選配推 Discord（複用 §6 channel，加值卡片）；**前端平台架構支柱 additive**——策展 N 份樣本事件報告成靜態 JSON＋Grafana 截圖＋架構圖節點，**零 live 依賴**（同觀測性 §7 慣例）；registry 條目 `whyBuilt`/`whatItDoes` 阻擋級；emoji→lucide。
8. **資料流/部署/守門/交付（全 additive）**：服務落點（`ml/aiops/` 或類）、AlertmanagerConfig additive 加 webhook receiver（不改 Discord route）、runbook 語料 backfill、指標 ServiceMonitor、ArgoCD wave（接續觀測性 wave 17/18，如 wave 19）、CI（graph 測試＝fake LLM+fake PromQL 注入、`check_numbers` 單測、prompt 格式測試、secret 紀律測試沿 P2 :462）、P5 交付＋截圖清單 additive、ADR-lite（棄 Dify/棄 DeepSeek/反幻覺紀律/告警敘事分工）。**逐一標明不改哪些既有資產**。

## 硬約束（違者作廢）

- **棄 Dify、棄 DeepSeek**（Fergus 明示只參考應用範式）：agent 編排只 LangGraph（不引 Dify 平台）、LLM 只 Ollama/Gemini（P2b LLMClient，不引 DeepSeek）；可移植的是 prompt/workflow 結構與「程式判定+LLM 敘事」範式。
- **反幻覺鐵律**：數字/百分比/時間戳一律程式取自 PromQL/Loki/告警（決定性），LLM 只敘事並經 `check_numbers` 驗證；`unverified` 非空即誠實標警示；時間戳程式注入不許 LLM 生成。這是本 spec 存在的正確性理由。
- **一工一具**：不引 Dify/DeepSeek/第二 agent 框架/第二 LLM 棧/向量庫（runbook 複用 pgvector）；蒐證用既有 Prometheus HTTP API/Loki，不新增指標系統。
- **拓撲鐵律**：本服務叢集內；前端零 live 依賴（策展樣本 JSON＋截圖佐證）；`output:'export'` 不動。
- **only-additive**：不改寫觀測性 spec §6 Discord route/既有告警/PrometheusRule、不改 P2b RAG graph/語料表、不改 ask-ai showcase；AlertmanagerConfig 加 receiver、新表 `ml.ops_*`、新語料、新服務全 net-new；`check_numbers` 複用（vendor+diff）不改 ask-ai 本體。
- **grounding/誠實**：demo 規模（自產告警觸發、真實但少量事件）誠實標；runbook 是自寫 SOP 非真值班紀錄；「AI SRE」是能力示範非 24/7 on-call 承諾；報告數字零幻覺是可測斷言（`check_numbers` 單測）。**說明式 registry 阻擋級**；emoji→lucide。
- **成本紅線不適用**（portfolio 跑 infra 是目的）——但仍守 M4/CPU 友善（Ollama 本地）、不假設 GPU。

## context7 必查清單

- **LangGraph**（StateGraph 節點/條件邊/重試——沿 P2b 但確認版本 API）。
- **Prometheus HTTP API**（`/api/v1/query`、`/api/v1/query_range` 參數與回應 schema——蒐證層要程式打）。
- **Alertmanager webhook**（webhook receiver payload schema：`alerts[]`/labels/annotations/startsAt/status——蒐證層解析）＋ AlertmanagerConfig CRD 加 webhookConfigs receiver 語法。
- **Loki LogQL**（`/loki/api/v1/query_range`、`| json` filter——log 證據蒐集）。

## Scope

- **in**：觸發模式（告警觸發主＋排程摘要拍板）、決定性蒐證層（PromQL/Loki/告警解析→fact set）、LangGraph graph、反幻覺 `check_numbers` 複用與時間戳處理、RAG runbook、換 provider（Ollama/Gemini）、報告產出/落表/Discord/前端策展、部署/守門/交付/ADR-lite。
- **out**：改觀測性 §6 既有 route/告警、改 P2b RAG graph/語料、引 Dify/DeepSeek/第二框架、前端新 live 後端、改 Signal token、自動修復動作（本 spec 只「敘事+建議」不「執行修復」——自動執行是另一層風險，明確劃出 v1，列進化方向）。

## 產出

寫到 `docs/specs/2026-07-10-ai-ops-incident-narrator-design.md`；檔頭指向本 brief＋精確度契約＋觀測性 design＋P2b＋ask-ai。附「plan 期待查證點」（LLMClient/check_numbers 實作 import 錨、Alertmanager webhook payload 實測、PromQL 蒐證模板、runbook 語料）與「本 spec 拍板 vs 下放」對照。**不 git commit**（Opus 把關後處理）。完成回報：檔案路徑、8 項拍板摘要、context7/grep 查證項（尤其 P2b LLMClient 合約錨＋model pin 對齊、ask-ai check_numbers 純函式、Alertmanager webhook schema、課程 prompt 樣板取材）、給 Opus 覆核的風險點（尤其：反幻覺是否真做到數字/時間戳零 LLM 生成、有無誤引 Dify/DeepSeek、拓撲鐵律、additive 邊界、model pin 有無自定）。
