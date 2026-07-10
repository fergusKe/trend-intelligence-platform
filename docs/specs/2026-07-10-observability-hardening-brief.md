# 觀測性強化 spec — brief（三柱補齊＋自癒：OTel/Tempo tracing＋Loki 結構化 log＋SLO/error budget＋pipeline 自癒健康報告）

> **精確度契約**：依 repo `CLAUDE.md`「Fable 5 design 精確度契約（8 條）」交辦；design 逐條自檢，**開放問題一律收斂成決定、不下推**。
> **緣起（Fergus 2026-07-10 定案「全四項」）**：接地盤點（P0/P1/P2/P3/P6/ask-ai design）證實平台**指標（metrics）柱規劃已強**，但作為求職 portfolio 缺**可觀測性三柱的另兩柱（log/trace）＋一個修復層**——正是資深 DE/SRE 面試最愛問、且對「跑基建即目的」CP 值最高的一塊。守 [[feedback_evolve_beyond_past_projects]]（參考是輸入非天花板）。
> **本擴充翻案了 NORTH_STAR「監控只用 Prometheus+Grafana」鎖定**——已由 Fergus 拍板、已記入 NORTH_STAR〈觀測性三柱翻案〉段（binding upstream，見下）。

---

## 框架上游（binding，不得抵觸）

- **[NORTH_STAR〈觀測性三柱翻案〉段](../architecture/NORTH_STAR.md)**（2026-07-10 定案，**本 brief 的頂層合約**）：四項擴充的 ADR-lite 表、「通過一工一具而非違反」論證、拓撲誠實。design 展開為 full ADR-lite、收攏進 P5 `DECISIONS.md`。**不得抵觸**：Loki/Tempo 只選 **Grafana 原生單 binary**（不引 ELK、不引 Jaeger＋獨立 UI）；③④ 零新常駐服務；仍只一個 metrics 系統（Prometheus）、一個儀表板（Grafana）。
- **拓撲鐵律（NORTH_STAR P4 段 §拓撲誠實）**：Loki/Tempo/OTel collector 皆**叢集內服務**（同 Redis/ClickHouse/Flink 性質）——**非公開靜態站 runtime 依賴**；前端 🏗平台架構支柱以 **Grafana 截圖/GIF＋架構圖＋P5 交付截圖**佐證，**不新增 live 後端**。監控資料延續 P0「emptyDir、demo 重建即重來」姿態。
- **only-additive**：**不改寫** P0/P1/P2/P3/P6/ask-ai 既有 design 的合約與 DDL；本 design 是**橫切上位增補**，以「引用＋疊加」方式落地（新增 ServiceMonitor/PodMonitor 之外的 OTel 儀器化、log pipeline、SLO 規則、自癒 task），既有指標/告警/probe 保留。若需在既有服務加 OTel/結構化 log，以「加儀器、不改業務合約」為界。
- **一工一具／M4-CPU 友善／成本紅線不適用**（portfolio 跑 infra 是目的，但仍守 M4/CPU 可跑、不假設 GPU；Loki/Tempo 選單 binary 輕量部署）。

## 接地鐵律（grounding-first，違者作廢）

Fable 5 須**第一手 grep/讀**下列錨點，把現況精確錨進 design（**不得從記憶或本 brief 轉述規劃**；本 repo 幾乎零實作碼，故錨的是 design 合約，同搜尋 spec 之 P2b 誠實處理）：

**A. 平台現有觀測性姿態（要在其上疊加、不重造）**
- `docs/specs/2026-07-08-P0-platform-foundation-design.md`：kube-prometheus-stack 87.10.1 GitOps（:340-391）、ServiceMonitor 全叢集發現（:347,372）、FastAPI `prometheus-fastapi-instrumentator` 8.0.2 `/metrics`（:425-431）、Grafana dashboard sidecar ConfigMap 版本化（:394-410）、hello service liveness/readiness `/healthz`＋resource requests/limits（:470-472）、Prom/Grafana emptyDir 不持久化（:349,528）。
- `docs/specs/2026-07-08-P1-data-pipeline-design.md`：postgres-exporter v0.20.1 自訂 DQ 查詢（`yt_freshness_seconds`/`yt_silver_rows_24h`/`yt_gold_mart_rows`，:434,452）、Airflow statsd-exporter（:434）、告警 `YTDataStale`/`LakehouseComponentDown`/`YTPipelineTaskFailures`（:435）、**Alertmanager 不接通知通道「demo 看 UI」（:435）**、dbt source freshness gate（:225）、Airflow KubernetesPodOperator `get_logs=True`（:222）。
- `docs/specs/2026-07-08-P2-ml-verticals-design.md`：ML drift 指標 `ml_feature_psi`/`ml_rolling_auc`（:305-312）、ML 告警 `MLFeatureDriftHigh`/`MLModelQualityDegraded`（:448）、RAG service `/healthz` 子檢查（:369）、`RAGCostBudget`（:448）。
- `docs/specs/2026-07-10-ask-ai-design.md`：**LangGraph 節點軌跡存 DB＋UI 揭露（:392,400）＝①要升級成真 OTel span 的錨點**；`ga_ask_*` metric 族（:379）；**Cloud Run `/metrics` 對 k8s Prometheus 的 scrape 是「plan 實查 #3」不確定接縫、降級即棄集中監控（:379,485）＝要處理的縫**。
- `docs/specs/2026-07-09-P6-realtime-features-design.md`：Flink metric group counters＋PodMonitor（:135,244,362）、`FlinkCheckpointFailing`/`FlinkJobRestarting` 告警（:379）。
- `docs/specs/2026-07-08-P3-ptt-ingest-design.md`：prometheus_client（:204,369）、`PttDataStale`（:378）、**consumer liveness/readiness 只打 `GET /`「不做深度健康檢查」（:204）＝④健康檢查可深化的錨**。
- `docs/specs/2026-07-08-P5-polish-hardening-design.md`：架構圖 `MON["Prometheus + Grafana"]`（:247,286-287）、**3 張 Grafana dashboard 截圖 PNG 交付（:315,368）＝本 design 要擴充的交付清單**、安全掃描 Trivy+gitleaks+CodeQL。
- `docs/specs/2026-07-10-frontend-design-system-design.md`：`FreshnessBanner` 誠實敘事元件（:174,212）＝前端觀測性敘事的既有錨。

**B. 唯讀取材（不改原專案，沿 NORTH_STAR §可複用素材地圖紀律）**
- **自癒 pattern**：`/Users/fergus/Desktop/workshop/fergus/data-workshop/CodeWithYu/SelfHealingPipeline-main/dags/agentic_pipeline_dag.py`——`_heal_review()`「偵測條件→修復動作→`was_healed` 標記」（:135-195，5 種 DQ 問題）、`generate_health_report` 四級分級 HEALTHY/WARNING/DEGRADED/CRITICAL（degraded>10%→CRITICAL，:424-460）、graceful degradation（:264-275）。**取的是應用層 pattern，碼不照抄**（其為 Airflow3+Ollama Yelp demo，語境不同）。
- **監控棧 code 化片段（對照參考，非主體）**：`CodeWithYu/Full High Performance Systems Monitoring Source/`——`monitoring/prometheus/rules/alert_rules.yml`（單條 alert rule 樣板）、`monitoring/grafana/provisioning/datasources/*.yml`（datasource provisioning-as-code）。**注意：平台已有更成熟的 kube-prometheus-stack，此處只借「rule/provisioning 檔結構」觀念，勿降級平台既有做法**。

**C. 版本敏感處**用 context7（見下必查清單）。

**本階段只出 spec，plan 延後。**

---

## 一句話目標

觀測性強化＝在平台既有強 metrics 基礎上**補齊可觀測性三柱並加修復層**：**① OTel 儀器化＋Grafana Tempo 分散式 tracing＋exemplars（metric↔trace 關聯）**、**② 全服務結構化 JSON log＋Grafana Loki 集中 log**、**③ 把散落閾值收斂成正式 SLO＋error budget＋Grafana SLO 面板**、**④ pipeline 偵測→修復→標記＋四級健康報告（唯讀取材 SelfHealingPipeline）**。全 additive 疊加於既有 design，Loki/Tempo 選 Grafana 原生單 binary（守翻案邊界），叢集內服務以截圖/架構圖佐證（拓撲鐵律不破），敘事＝「可觀測性三柱齊全＋SRE SLO 實踐＋pipeline 自癒」的資深訊號。

## Fable 5 要收斂拍板的項目（逐一給明確決定，不下推）

1. **① Tracing 落地形**：拍板 OTel 儀器化範圍（哪些服務起手＝FastAPI 服務群/ask-ai/RAG/reco 為主）、**ask-ai 現有「LangGraph 節點軌跡存 DB」如何升級成真 OTel span**（節點＝span、保留 DB/UI 揭露當 application view、另出 OTel export 到 Tempo；兩者關係畫清）、跨服務 context propagation 邊界、**Tempo 部署形**（單 binary monolithic、emptyDir）、**exemplars 接法**（Prometheus exemplar storage + Grafana 從 metric 跳 trace）。context7 查 OTel Python SDK＋Tempo＋exemplar 現況。誠實：demo trace 量小、不留存。
2. **② Logging 落地形**：拍板**結構化 JSON log 慣例**（欄位 schema：timestamp/level/service/trace_id（與①關聯）/message/context；Python logging formatter 或 structlog——context7 定案）、**Loki 部署形**（單 binary、Promtail/Grafana Agent/Alloy 哪個當 collector——context7 查現況與取捨）、log↔trace 關聯（log 帶 trace_id → Grafana 從 trace 跳 log）、保留期（emptyDir 誠實）。**明標與原「不要 9 件套」不衝突**（Loki＝Grafana 原生單 binary，非 ELK）。
3. **③ SLO / error budget 落地形**：拍板**哪些服務/pipeline 定 SLO**（傾向：關鍵服務可用性、pipeline freshness、ML serving 延遲、RAG/ask-ai 成功率——從既有告警閾值收斂）、**SLO 表達法**（PrometheusRule recording rules 算 error budget burn rate vs Grafana 原生 SLO——context7 查 Grafana SLO 現況並取捨，守「零新常駐服務」）、**error budget 定義**（目標可用性％、窗口、burn-rate 多級告警）、Grafana SLO 面板。**明標與既有 threshold 告警的關係**（SLO 是上層收斂，不刪既有 A4 告警）。
4. **④ 自癒/健康報告落地形**：拍板**在哪條 pipeline 示範自癒**（傾向 P1 資料清洗或 P2 ML 資料驗證，唯讀取材 `_heal_review` 的「偵測→修復→was_healed 標記」pattern，落成平台自有 Airflow task/dbt 前置）、**修復動作清單**（對照 5 種 DQ 問題，定義本平台語料的對應修復）、**四級健康報告**（HEALTHY/WARNING/DEGRADED/CRITICAL 門檻、輸出成 metric（進 Prometheus，`*_health_status`）＋記錄表）、與既有 dbt DQ gate 的分工（gate＝硬擋不可修復者、自癒＝軟修可修復者並記錄）。**明標非「假裝資料很髒」**——誠實標示範規模與 pattern 展示性質。
5. **Cloud Run live 端點的觀測性縫收斂**（承接 ask-ai :485 已知縫）：`ga-ask-live`/`search-live` 有 `/metrics` 但 scrape 不確定、無專屬 dashboard/告警——拍板本 design 是否補**一支 blackbox/synthetic probe**（外部 uptime 探測 live 端點，blackbox-exporter 或輕量方案——context7 查，守單 binary/零重量）＋為 live 端點補 Grafana dashboard/PrometheusRule，或誠實列 known-limit。**不新增前端 live 依賴**。
6. **告警通知通道拍板**（承接 P1 :435「Alertmanager 不接通道」）：是否補**一個輕量通知 receiver**（webhook→ntfy/Discord，示範「閉環」）當 demo 亮點，或維持「demo 看 UI」誠實姿態。給明確決定＋理由（成本紅線不適用，但守「不為炫技硬加」）。
7. **前端 🏗平台架構支柱的觀測性敘事**（守拓撲鐵律，additive）：三柱＋自癒如何在平台架構支柱呈現——傾向 Grafana 截圖牆（trace 火焰圖/Loki 查詢/SLO 面板/健康報告）＋架構圖新增 `OTel→Tempo`/`Loki`/`SLO` 節點＋**說明式 registry 條目**（`whyBuilt`/`whatItDoes` 硬性）＋承接 `FreshnessBanner` 的誠實敘事。**不新增 live 後端**、不改 Signal token。拍板頁/區落點（沿 P4/P5 `/architecture`，不新增支柱）。
8. **資料流/部署/守門/交付（全 additive）**：Loki/Tempo/OTel collector 的 k8s manifest 落點（`platform/` 沿 ArgoCD GitOps）、OTel 儀器化落點（各服務加 instrumentation）、SLO PrometheusRule 落點、自癒 task 落點（`orchestration/`）、**P5 交付清單擴充**（既有 3 張 dashboard PNG → 補 trace/log/SLO/健康報告截圖）、`DECISIONS.md` ADR-lite 四條、CI（若需）。**逐一標明不改哪些既有資產**。

## 硬約束（違者作廢）

- **翻案邊界（NORTH_STAR〈觀測性三柱翻案〉）**：Loki/Tempo 只選 **Grafana 原生單 binary**（**不引 ELK、不引 Jaeger＋獨立 UI、不引第二個 metrics 系統/儀表板**）；③④ 零新常駐服務；「補三柱」的論證＝各解決 Prom/Grafana 做不到的獨特工作（trace/log），**通過一工一具而非違反**。
- **拓撲鐵律**：Loki/Tempo/OTel/blackbox 皆叢集內服務，**非公開靜態站 runtime 依賴**；前端只以截圖/GIF/架構圖佐證，**零新 live 後端**、`output:'export'` 純靜態不動。
- **only-additive**：不改寫 P0/P1/P2/P3/P6/ask-ai 既有合約/DDL/告警/probe；本 design 以引用＋疊加落地。既有 A1-A6 觀測性資產全保留。
- **grounding／誠實**：現況精確錨 file:line；demo 規模 trace/log 量小、emptyDir 不留存、示範性質——全誠實標；自癒非「假裝資料髒」；SLO 是收斂非取代既有告警；取材 SelfHealingPipeline 碼不照抄。**說明式 registry 阻擋級**（缺 `whyBuilt`/`whatItDoes`＝gate fail）；前端 emoji→lucide。
- **成本紅線不適用**（portfolio 跑 infra 是目的）——但仍守 **M4/CPU 友善、Grafana 原生輕量單 binary、不假設 GPU**。

## context7 必查清單（版本敏感，不得憑記憶）

- **OpenTelemetry Python SDK**（自動/手動 instrumentation、FastAPI instrumentor、trace context propagation、exporter to Tempo/OTLP）。
- **Grafana Tempo**（單 binary/monolithic 部署、OTLP 接收、Grafana 資料源、exemplar/trace-to-logs 關聯現況）。
- **Grafana Loki**（單 binary 部署、collector 選型 Promtail vs Grafana Alloy 現況、LogQL、log-to-trace 關聯、與 Grafana 整合）。
- **結構化 log**（Python `structlog` 或 stdlib logging JSON formatter 現況、與 OTel trace_id 注入）。
- **SLO**：Prometheus recording rules / multi-window multi-burn-rate 告警範式、**Grafana 原生 SLO** 功能現況（取捨零新常駐服務）。
- **blackbox-exporter**（若採 §5 synthetic probe）。

## Scope

- **in**：① OTel＋Tempo tracing＋exemplars、② 結構化 JSON log＋Loki、③ SLO/error budget＋Grafana 面板、④ pipeline 自癒＋四級健康報告、⑤ Cloud Run live 端點觀測性縫、⑥ 告警通知通道拍板、⑦ 前端平台架構支柱觀測性敘事（additive）、⑧ 部署/守門/P5 交付擴充/ADR-lite/CI。
- **out**：改寫既有 P0-P7/ask-ai 合約或 DDL、引 ELK/Jaeger/第二 metrics 系統、新增前端 live 後端、改 Signal token、改既有業務邏輯（只加儀器不改合約）。

## 產出

寫到 `docs/specs/2026-07-10-observability-hardening-design.md`；檔頭指向本 brief＋精確度契約＋NORTH_STAR〈觀測性三柱翻案〉＋所疊加的 P0/P1/P2/P3/P5/P6/ask-ai/frontend design。附「plan 期待查證點」（OTel/Tempo/Loki 實裝、SLO 規則實算、自癒 task 實作、live 端點 scrape 實查）與「本 spec 拍板 vs 下放」對照。**不 git commit**（Opus 把關後處理）。完成回報：檔案路徑、8 項拍板摘要、context7/grep 查證項（尤其 ask-ai LangGraph 節點軌跡錨、P1 Alertmanager 現況、SelfHealingPipeline `_heal_review` pattern、OTel/Tempo/Loki context7）、給 Opus 覆核的風險點（尤其：翻案邊界有無被 Loki/Tempo 之外的工具滲入、拓撲鐵律有無被 live 依賴破壞、additive 有無誤改既有合約）。
