# 觀測性強化 design（三柱補齊＋自癒：OTel/Tempo tracing＋exemplars ｜ 結構化 JSON log＋Loki ｜ SLO/error budget ｜ pipeline 自癒＋四級健康報告）

> **上游**：[brief 正本](2026-07-10-observability-hardening-brief.md)（工作合約）＋ repo `CLAUDE.md`「Fable 5 design 精確度契約（8 條）」（自檢見 §12）＋ [NORTH_STAR〈觀測性三柱翻案〉段](../architecture/NORTH_STAR.md)（**頂層合約 binding**：Loki/Tempo 只選 Grafana 原生單 binary、③④ 零新常駐服務、仍只一個 metrics 系統/一個儀表板、拓撲誠實延續 P4 鐵律）。
> **所疊加的既有 design（只引用不改寫）**：[P0 平台底座](2026-07-08-P0-platform-foundation-design.md)（§5 kube-prometheus-stack 87.10.1 / §6 hello / §8 verify）＋ [P1 資料管線](2026-07-08-P1-data-pipeline-design.md)（§6 dbt DQ / §9 可觀測性）＋ [P1 留言 ingest](2026-07-08-P1-comments-ingest-design.md)（Silver 留言合約）＋ [P2 ML verticals](2026-07-08-P2-ml-verticals-design.md)（§7 drift / §9 RAG 服務 / §13 監控）＋ [P3 PTT ingest](2026-07-08-P3-ptt-ingest-design.md)（§10 指標/告警）＋ [P5 收尾](2026-07-08-P5-polish-hardening-design.md)（§3 架構圖 / §4 DECISIONS / 截圖清單）＋ [P6 即時特徵](2026-07-09-P6-realtime-features-design.md)（§9 Flink 監控）＋ [P6 推薦](2026-07-09-P6-recommendation-design.md)（§7 reco-service）＋ [問 AI](2026-07-10-ask-ai-design.md)（§6 trace schema / §7.5 監控 / §8 live / §12 實查 #3）＋ [統一作品集 crosscut](2026-07-10-unified-portfolio-crosscut-design.md)（§5 registry 阻擋級）＋ [Signal 設計系統](2026-07-10-frontend-design-system-design.md)（FreshnessBanner / /architecture bento）＋ [搜尋支柱 v2](2026-07-10-search-pillar-design-v2.md)（§7 search-live）。
> **定位**：本檔是**橫切上位增補**——在平台已強的 metrics 柱上疊加 trace 柱（①）、log 柱（②）、SLO 收斂層（③）、自癒修復層（④），並收 Cloud Run live 端點觀測性縫（⑤）、告警通知閉環（⑥）、前端敘事（⑦）、部署/守門/交付（⑧）。**既有 P0–P7/ask-ai 的合約、DDL、告警、probe 全數保留，一條不改寫**（唯一觸碰的既有檔案清單見 §8.6，全部是 additive 值/欄）。
> **一句話**：OTel SDK 儀器化四個 FastAPI 面（hello/RAG/reco/ga_ask）送 **Tempo 單 binary**（emptyDir），exemplars 讓 Grafana 從 metric 跳 trace；全 Python 服務 **structlog JSON**（頂層 `trace_id`）由 **Alloy DaemonSet** 收進 **Loki 單 binary**，log↔trace 雙向跳；散落閾值收斂成 **4 條 SLO ＋ error budget ＋ multi-window multi-burn-rate 告警**（純 PrometheusRule，零新常駐服務）；P1 留言清洗前加**偵測→修復→`was_healed` 標記＋四級健康報告**（唯讀取材 SelfHealingPipeline pattern）；blackbox-exporter 補 live 端點黑盒探測；Alertmanager 原生 `discord_configs` 補通知閉環；`/architecture` 頁 additive 擴觀測性敘事區＋P5 截圖清單 +4。

---

## 0. 接地現況（第一手 grep/讀，file:line 錨）

### 0.1 A 組——平台現有觀測性姿態（本 design 疊加其上、不重造）

| 錨點 | 現況（第一手核對） | 本 design 的疊加關係 |
|---|---|---|
| P0 design :340-391 | kube-prometheus-stack **87.10.1** 由 ArgoCD 子 Application（wave 1）GitOps 管，values `valuesObject` 內嵌；`serviceMonitorSelectorNilUsesHelmValues: false`＋`podMonitorSelectorNilUsesHelmValues: false`＋`serviceMonitorNamespaceSelector: {}` 撿全叢集（:347,372-374）；`retention: 24h`、storageSpec 刻意不設＝emptyDir（:349,375-376,528）；Grafana sidecar dashboards（:348,382-383）；Alertmanager enabled（:384） | ①⑤ 的 Prometheus/Grafana/Alertmanager 全複用此部署；本 design 對此 Application 只做三處 **additive values**（§8.3），不動任何既有 key |
| P0 design :394-410 | dashboard＝ConfigMap sidecar（label `grafana_dashboard: "1"`），獨立子 App `monitoring-dashboards`（directory 型，wave 2）；datasource 引用 `{"type":"prometheus","uid":"prometheus"}`（:401 已對 chart 驗證） | 新 dashboard 全走同一 sidecar 慣例；Tempo/Loki datasource 的 uid 也走固定 uid 供互鏈（§1.5/§2.5） |
| P0 design :425-431 | hello＝FastAPI＋`prometheus-fastapi-instrumentator` **8.0.2**（`Instrumentator().instrument(app).expose(app)` → `GET /metrics`），指標 `http_requests_total`/`http_request_duration_seconds` histogram（label `handler/method/status`，:403） | ① 的 OTel 儀器化疊在同一 app 上（兩者互不干擾：instrumentator 管 metrics、OTel 管 trace）；③ 服務可用性 SLI 直接吃 `http_requests_total` |
| P0 design :470-472 | hello liveness/readiness 都打 `/healthz`；resources requests/limits 已定；ServiceMonitor `port: http, path: /metrics, interval: 15s` | probe 姿態零改（only-additive）；新觀測性服務沿同 resources/probe 慣例 |
| P1 design :434 | 管線指標兩源：Airflow chart `statsd.enabled: true`（statsd-exporter）＋ postgres-exporter **v0.20.1** 自訂查詢 ConfigMap `lakehouse-exporter-queries`（`yt_freshness_seconds`／`yt_silver_rows_24h{region}`／`yt_gold_mart_rows{mart}`，SQL 即合約） | ③ 的 freshness SLO SLI 直接吃 `yt_freshness_seconds`；④ 的健康指標走**同一 exporter 自訂查詢模式 additive 加條**（§4.4），零新 exporter |
| P1 design :435 | PrometheusRule：`YTDataStale`（>3h warn / >6h critical）、`YTPipelineTaskFailures`、`LakehouseComponentDown`；**「Alertmanager 用 P0 既有部署，不接通知通道（demo 看 UI）」**＝⑥ 要收的縫 | ③ SLO 告警是上層收斂、**不刪不改**這三條 cause-based 告警；⑥ 接通道（§6） |
| P1 design :222,:225 | dbt 走 KubernetesPodOperator（`get_logs=True`→task log 進 Airflow）；`dbt_test`＝`dbt source freshness && dbt test`，任一非零＝DQ gate 硬擋 DAG；sources freshness warn 2h/error 4h | ④ 的自癒層插在 gate **之前**（軟修可修復者），gate 職責零改（§4.5）；`get_logs=True` 的 pod stdout 天然被 ② 的 Alloy 收走（pod log 同源） |
| P2 design :305-312 | drift：PSI+KS+rolling AUC 自寫（淘汰 evidently）；指標走 postgres-exporter 自訂查詢（`ml_feature_psi{model,feature}`/`ml_rolling_auc{model}`…）；告警 `MLFeatureDriftHigh`/`MLModelQualityDegraded`（rolling_auc<0.60 critical）/`MLStagingCandidateReady` | ③ 不把 drift 收成 SLO（drift 是模型健康非請求服務水準，語意不合 SLO 範式——誠實劃界，§3.4）；既有告警全留 |
| P2 design :369 | RAG 服務＝FastAPI（`ml/rag/service/`，ingress `rag.localtest.me`）：`POST /ask`、`GET /healthz`（含 pgvector＋Ollama 子檢查）、`GET /metrics` | ① 儀器化第一優先服務（LangGraph CRAG 節點＝天然 span 樹）；③ RAG 成功率/延遲 SLO 的 SLI 源 |
| P2 design :442-448 | Grafana ×3（ml-lifecycle/llmops/ml-serving）＋ PrometheusRule `RAGDegradedRateHigh`（degraded/total 1h >0.3 warn）/`MLServingDown`/`RAGCostBudget`（gemini 日成本>$1） | ③ RAG SLO 與 `RAGDegradedRateHigh` 的關係明標（§3.4）；dashboards 不改，新 SLO 面板另立 |
| ask-ai design :138,:293,:318 | LangGraph 節點軌跡：state `trace: Annotated[list[dict], operator.add]` 每節點自 append（:138）；rows additive 欄 `trace: TraceStep[]`（:293）；持久化 `ml.ga_ask_showcase.trace jsonb`（:318）＋前端 Collapsible 逐節點 timeline（:416） | **① 的升級錨**：DB/UI trace＝application view **保留零改**，OTel span＝infra view 疊加（同一節點事件雙寫，§1.2） |
| ask-ai design :379,:392,:399-400,:485 | live 面 `ga_ask_*` metric 族（`ga_ask_requests_total{outcome}`/`ga_ask_node_duration_seconds{node}`…）；Cloud Run `ga-ask-live`（asia-east1，`/healthz`/`/metrics`）；**k8s Prometheus scrape Cloud Run 公網 `/metrics`＝plan 實查 #3 不確定縫，降級即棄集中監控** | ⑤ 的正對象：白盒 scrape 維持原實查 #3 判定不改；本 design 補**黑盒層**（scrape 成不成都有 uptime 觀測，§5） |
| P6 realtime design :135,:244,:362,:379 | Flink：PrometheusReporter :9249（JM/TM）＋自訂 operator metric group counters＋PodMonitor；告警 `FlinkCheckpointFailing`/`FlinkJobRestarting` 等；waves 14-16 已用 | ①② **不儀器化 Flink**（Java job，OTel Java agent＝新工程面，違「起手最小集」；其 metrics 已完整、log 由 ② 的 DaemonSet 天然收 stdout）；wave 編號接續 17/18（§8.2） |
| P3 design :204,:369,:378 | consumer：prometheus_client :8000；**liveness/readiness 只打 `GET /`「不做深度健康檢查」**＝brief 指名的可深化錨；`PttDataStale`（>30h warn/>54h critical）等五條告警 | ④ 健康分級不動 probe（only-additive：probe 淺是刻意設計「Kafka 斷線由 lag 告警看見」，本 design 尊重原判）；PTT 留言不是 v1 自癒對象（§4.1 劃界）；② 收其 JSON log |
| P5 design :247,:286-287 | 架構圖①有 `MON["Prometheus + Grafana"]` 節點；圖③底部共用分區含 Prometheus | ⑦ 架構圖處置：既有 4 張不改，**additive 第 5 張 `observability.md`**（§7.3） |
| P5 design :315,:364-372 | one-pager「可現場 demo 清單」含 Grafana dashboard；截圖清單 8 PNG＋1 GIF（#3＝Grafana 三張擇二） | ⑦ 截圖清單 additive +4（#9–#12，§7.4）；GIF 仍只 #1 |
| frontend design :174,:212 | `FreshnessBanner`：保留 RSC 讀 meta.json 機制與全部文字（誠實敘事硬約束）；`/architecture`＝bento 敘事版面（架構圖全寬卡＋截圖牆 2×3＋誠實敘事文字塊） | ⑦ 落點＝`/architecture` bento additive 加區塊；FreshnessBanner 零改（§7.1） |

### 0.2 B 組——唯讀取材（不改原專案、碼不照抄）

| 素材 | 第一手核對內容 | 取 vs 不取 |
|---|---|---|
| `CodeWithYu/SelfHealingPipeline-main/dags/agentic_pipeline_dag.py` :135-195 | `_heal_review()`：對每筆 review 產 `{original_text, error_type, action_taken, was_healed, healed_text}`；5 種 DQ 分支＝`missing_text`（placeholder）/`wrong_type`（str 轉換）/`empty_text`（placeholder）/`special_characters_only`（`[Non-text content]` 替換）/`too_long`（截斷+`...`） | **取**：「偵測條件→修復動作→`was_healed`+`error_type`+`action_taken` 標記」的三元組 pattern 與 5 分支分類法。**不取**：其碼（Yelp/Ollama 情緒 demo 語境）；placeholder 填充對留言語料是錯的修復（會汙染 RAG embedding）——本平台改「隔離」語意（§4.2） |
| 同檔 :424-460 | `generate_health_report`：四級分級 `degraded > total*0.1 → CRITICAL`／`degraded > 0 → DEGRADED`／`healed > total*0.5 → WARNING`／else `HEALTHY`；報告含 run_info/rates/健康摘要 | **取**：四級分級骨架與「degraded 占比定級、healed 占比警示」的門檻思路；門檻依本平台語料重定（§4.3）。**不取**：log 印 JSON 即丟——本平台落 DB 表＋Prometheus metric（可稽核、可告警） |
| 同檔 :264-275 | `_created_degraded_results`：Ollama 不可達時整批標 `status:'degraded'` 帶 error_message 續跑（graceful degradation） | **取**：「不可修復≠炸管線，標記後續跑」語意（對應本平台 `quarantined`）。**不取**：NEUTRAL/0.5 假預測值填充（那是杜撰資料，違 grounding） |
| `CodeWithYu/Full High Performance Systems Monitoring Source/monitoring/` | `prometheus/rules/alert_rules.yml`（單條 alert rule 樣板：expr/for/labels.severity/annotations）；`grafana/provisioning/datasources/prometheus_ds.yml`（datasource provisioning-as-code）；**另有 `elk/`（filebeat+logstash）目錄** | **取**：rule/provisioning「監控設定即代碼」檔結構觀念——平台既有 PrometheusRule/sidecar 慣例已更成熟，僅對照確認不降級。**明確不取**：其 `elk/` 堆疊（正是翻案邊界排除的 ELK；本 design 的 log 柱＝Loki 單 binary） |

### 0.3 C 組——context7 查證（版本敏感處；查證日 2026-07-10）

| 套件 | 查到的關鍵 API/現況（本 design 據此拍板） |
|---|---|
| OpenTelemetry Python SDK（`/websites/opentelemetry-python_readthedocs_io_en_stable`） | 套件組＝`opentelemetry-api`＋`opentelemetry-sdk`＋`opentelemetry-exporter-otlp-proto-grpc`（另有 `-http`）＋`opentelemetry-instrumentation-logging`；骨架＝`Resource.create({"service.name": …})` → `TracerProvider(resource=…)` → `BatchSpanProcessor(OTLPSpanExporter(endpoint="http://…:4317", insecure=True))`；**gotcha：`BatchSpanProcessor` 非 fork-safe**——gunicorn 需 `post_fork` hook 初始化（本平台服務全跑單進程 uvicorn，不踩；README 註記） |
| OpenTelemetry Python Contrib（`/open-telemetry/opentelemetry-python-contrib`） | `FastAPIInstrumentor.instrument_app(app, excluded_urls=…, exclude_spans=["receive","send"])`（exclude_spans 砍 ASGI 內部雜訊 span）；middleware 包裹順序已處理 exception 記錄；`HTTPXClientInstrumentor().instrument()` 管 outbound propagation；`opentelemetry-instrumentation-psycopg` 存在（DB span） |
| Grafana Tempo（`/grafana/tempo`） | **monolithic 單 binary 是官方一級部署形**；OTLP 接收 gRPC `:4317`／HTTP `:4318`；Grafana datasource `type: tempo, url: http://<svc>:3200`，`jsonData.serviceMap.datasourceUid` 指 prometheus；helm `grafana/tempo` chart＝single-binary 模式；trace↔log 互跳＝Grafana 端 datasource 設定（Tempo 側 tracesToLogs、Loki 側 derived fields） |
| Grafana Loki（`/grafana/loki`） | 單 binary（monolithic）模式官方支援；**Promtail 已於 Loki 3.4 起 deprecated、碼併入 Grafana Alloy**（官方 release notes 明載）→ collector 拍板 Alloy；Alloy 管線＝`discovery.kubernetes "pods"` → `loki.source.kubernetes` → `loki.write "endpoint" { url = "http://<loki>/loki/api/v1/push" }`；label 紀律＝少量 index label（namespace/pod/container/app/job），高基數欄位留 log body |
| structlog（`/hynek/structlog`） | production JSON 鏈＝`structlog.configure(processors=[…, TimeStamper(fmt="iso"), add_log_level, format_exc_info, JSONRenderer()])`；**官方 frameworks 文件即載 OTel 注入 processor**（`trace.get_current_span()` → `format(ctx.trace_id, "032x")` 進 event dict）；stdlib 第三方 log 統一走 `structlog.stdlib.ProcessorFormatter` |
| Grafana exemplars／SLO（`/websites/grafana`） | exemplars 前提：**Prometheus 需 `--enable-feature=exemplar-storage`**、app 需以 OpenMetrics 格式暴露並在指標上附 trace_id exemplar、面板須 TimeSeries＋Exemplars toggle；datasource 端 `exemplarTraceIdDestinations` 指 Tempo。**Grafana SLO 功能的文件全在 Grafana Cloud（IRM）路徑下＝Cloud/Enterprise 功能，OSS Grafana 無原生 SLO 物件** → ③ 拍板不採（§3.1） |
| blackbox-exporter（`/prometheus/blackbox_exporter`） | `http_2xx` module（prober http，`valid_status_codes` 預設 2xx，timeout 可設）；`/probe?target=…&module=http_2xx`；Prometheus 側 relabel 三件套（`__address__`→`__param_target`→`instance`→exporter 位址）；核心指標 `probe_success`/`probe_duration_seconds`/`probe_ssl_earliest_cert_expiry` |

---

## 1. ① Tracing：OTel 儀器化＋Tempo＋exemplars（拍板）

### 1.1 儀器化範圍（起手最小集，明確列入/列外）

| 服務 | 儀器化 | 內容 |
|---|---|---|
| hello（P0，`platform/hello/`） | ✅ v1 | `FastAPIInstrumentor.instrument_app(app, excluded_urls="/metrics,/healthz", exclude_spans=["receive","send"])`——金絲雀服務同時當 tracing 的 smoke 對象（`make verify` 可斷言 Tempo 查得到 hello trace，§9） |
| RAG service（P2b，`ml/rag/service/`） | ✅ v1（**主秀**） | FastAPI 儀器化＋**LangGraph CRAG 節點手動 span**（§1.2 同款包裝）＋`HTTPXClientInstrumentor`（Ollama/Gemini 呼叫成 client span）＋`opentelemetry-instrumentation-psycopg`（pgvector 檢索 SQL span）——一條 `/ask` 請求＝完整 span 樹（retrieve→grade→rewrite→generate），面試現場最有講頭的火焰圖 |
| reco-service（P6，P6-reco §7） | ✅ v1 | FastAPI 儀器化＋召回/特徵/rank 三階段手動 span（該 design 已有 `timings{recall,features,rank,reason}` 應用層計時——span 是其 infra view，timings 欄零改）＋httpx（KServe infer 呼叫） |
| ga_ask graph（ask-ai；批次 host 跑＋Cloud Run live） | ✅ 批次面 v1；live 面誠實列 known-limit | 見 §1.2/§1.3 |
| PTT consumer（P3）、Airflow task pod、Spark、Flink、KServe runtime | ❌ v1 刻意不做 | consumer/批次 pod＝短工序非請求鏈，trace 價值低（log+metrics 已足）；Flink/KServe＝Java/託管 runtime，掛 agent 是新工程面。**誠實劃界寫進 §7 敘事與 README**：「tracing 覆蓋請求式服務鏈；批次/串流面用 metrics+log 柱觀測」。列進化方向，不是 v1 債 |

**共用初始化模組**：正本 `libs/obs/obs.py`（~80 行）：`init_tracing(service_name)`（Resource→TracerProvider→BatchSpanProcessor→OTLPSpanExporter，endpoint 讀 env `OTEL_EXPORTER_OTLP_ENDPOINT`，**未設＝no-op 不初始化**——OTel 是疊加儀器，缺 env 服務照常跑，違者即引入 runtime 依賴）＋`init_logging(service_name)`（§2.2）。各服務 vendor 複製一份＋CI 位元組 diff 守門（沿 crosscut 決策 7「schema 逐字節複製＋CI diff」既有慣例；不做 pip 套件——跨 image path dep 是依賴糾纏，P1 §6 同判）。

### 1.2 ask-ai「LangGraph 節點軌跡存 DB」升級成真 OTel span（兩者關係畫清）

**拍板：雙 view 並存，單一事件源。** ask-ai 的 trace（state `operator.add` 累加 → `ml.ga_ask_showcase.trace jsonb` → 前端 Collapsible timeline，:138/:318/:416）是**application view**——策展給訪客看、進靜態 JSON、合約已定，**零改**。OTel span 是 **infra view**——給 Tempo/Grafana 看，工程診斷用。落法：

- 每個 graph 節點以既有的節點包裝層（ask-ai 各節點本就統一經 wrapper 記 TraceStep）**同一處**加 `tracer.start_as_current_span(f"ga_ask.{node_name}")`，span attributes ＝ TraceStep 既有欄位子集（`node`/`duration_ms`/`provider`/`outcome`；**不放 question/answer 原文**——span attribute 留元資料，內容留 DB，控 Tempo 體積也避免語料進 trace 後端）。一份事件、雙寫兩 view，不出現第二套計時真源。
- LLM 呼叫（P2b LLMClient）經 httpx instrumentation 自然成 child span → 節點 span 樹下看得到每次 provider 呼叫延遲。
- **批次面（host 原生跑）**：OTLP 走既有 host→cluster ingress 慣例——`platform/observability/tempo/` 附 Ingress `tempo.localtest.me`（OTLP HTTP `:4318` 路由），host 側 env `OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo.localtest.me`＋`OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`（gRPC 過 nginx ingress 要另開 grpc 註解，HTTP 版零特殊設定——單 binary 兩口都開，叢集內用 4317 gRPC、host 進來用 HTTP）。
- RAG 服務（P2b 同為 LangGraph）節點 span 同款：`rag.{retrieve|grade|rewrite|generate}`。

### 1.3 跨服務 context propagation 邊界

- **叢集內**：W3C `traceparent`（OTel Python 預設 propagator，零設定）；outbound 全靠 `HTTPXClientInstrumentor`（reco→KServe、graph→Ollama/Gemini）。KServe 不儀器化，但 reco 的 client span 已含 infer 延遲——邊界誠實：trace 到「呼叫 KServe」為止。
- **前端→服務**：不存在（純靜態站無 runtime 呼叫，拓撲鐵律）——trace 的根永遠在服務入口或批次 job，README 明寫。
- **Cloud Run live（ga-ask-live/search-live）**：**不回送 Tempo**（叢集不對公網、Cloud Run 打不進本地——與 ask-ai §8 同一拓撲事實的反向）。誠實處理＝live 面維持既有 `ga_ask_node_duration_seconds{node}` metrics＋回應內 trace 欄（application view 本就隨 response 回給使用者）；README known-limit 一句：「live 端點的 OTel trace 不進本地 Tempo；分散式 tracing 展示以叢集內服務為準」。**淘汰**：Tempo 對公網收 OTLP（把叢集內服務暴露公網＝破拓撲鐵律）、Grafana Cloud 免費層當 live trace 後端（引入第二個 trace 系統，違一工一具）。

### 1.4 Tempo 部署形

| 項 | 拍板 |
|---|---|
| 形態 | **helm chart `grafana/tempo`（單 binary模式）**，ArgoCD 子 Application `tempo`（wave 17，§8.2），namespace `observability`；chart 版本 pin＝plan 前實查 #1（預設當日最新 stable；判準＝appVersion Tempo 2.x、支援 OTLP 雙口與 emptyDir） |
| 儲存 | **emptyDir**（`persistence` 不開；local blocks + wal 都落 emptyDir）＋ `retention: 24h`（與 P0 Prometheus retention 對齊）——延續 P0 「demo 重建即重來」姿態，README known-limit 同句式 |
| 接收 | OTLP gRPC `:4317`＋HTTP `:4318` 都開（chart 預設 distributor receivers 設 otlp http+grpc）；另附 Ingress `tempo.localtest.me`→4318（§1.2 host 批次用；`ingressClassName: nginx` 零專屬註解，P0 可攜鐵律） |
| metrics-generator | **關**（它要 remote_write 回 Prometheus——service graph 好看但多一條寫路徑；v1 以 span 檢索＋exemplar 跳轉為主秀，service graph 列進化方向） |
| 自身監控 | Tempo `/metrics` 由 ServiceMonitor 撿（全叢集發現既有機制，:347）；告警 `TempoDown`（`up==0` 10m warn，§8.4） |
| 資源 | requests `100m/256Mi` limits `500m/512Mi`（demo trace 量小；沿 P0 右尺寸慣例） |

### 1.5 exemplars（metric↔trace 關聯）接法

| 件 | 拍板 |
|---|---|
| Prometheus 側 | kube-prometheus-stack values **additive** 加 `prometheusSpec.enableFeatures: [exemplar-storage]`（context7 已證此 feature flag 為前提；prometheusSpec.enableFeatures 是 Prometheus CRD 既有欄位） |
| app 側 | exemplar 掛在**自有 prometheus_client histogram**上：RAG `rag_request_duration_seconds`、reco 延遲 histogram、ga_ask `ga_ask_request_duration_seconds`——`observe(v, exemplar={"trace_id": <當前 span 的 032x trace_id>})`（`libs/obs` 提供 `current_trace_exemplar()` helper）；exemplar 只在 OpenMetrics 協商下暴露（prometheus_client 既有行為，Prometheus scrape 自動協商）。**`prometheus-fastapi-instrumentator` 8.0.2 的 `http_*` 指標是否原生支援 exemplar＝plan 前實查 #2**（預設不動它——自有 histogram 已足以展示跳轉；若其 8.x `metrics.default` 支援 exemplar callback 則順手開，判準＝不改既有指標名/label） |
| Grafana 側 | Prometheus datasource **additive** `exemplarTraceIdDestinations: [{name: trace_id, datasourceUid: tempo}]`（走 kube-prometheus-stack `grafana.additionalDataSources` 同一 values 區塊改不到內建 datasource——確切 values key＝plan 前實查 #3，預設 `grafana.sidecar.datasources` 補一份帶 exemplar 設定的 prometheus datasource ConfigMap 覆蓋，判準＝Explore 中 metric 面板出現 exemplar 菱形點可點跳 Tempo） |
| 展示鏈 | Grafana `slo-overview`/`llmops` 面板（TimeSeries＋Exemplars on）→ 點 exemplar 菱形 → Tempo trace 瀑布 → span 內「Logs for this span」→ Loki（§2.5）＝**三柱一鍵串連的 demo 動線**，⑦ 的 GIF 候選（但 GIF 仍只 P5 #1 一支，此動線拍 PNG 序列） |

**誠實標**：demo 規模 trace 量小（verify 腳本＋手動 demo 流量）、emptyDir 不留存、exemplar 抽樣是 Prometheus 原生行為非全量——三句全進 README 與 ⑦ 敘事。

---

## 2. ② Logging：結構化 JSON log＋Loki（拍板）

### 2.1 結構化 JSON log 慣例（欄位 schema＝合約）

**拍板：structlog**（context7 已證官方即載 OTel 注入 processor；stdlib JSON formatter 要手刻同樣的東西還沒有 processor 生態——用驗證過的成熟輕量套件，非造輪）。版本 pin＝plan 前實查 #4（預設當日最新 stable 25.x；純 Python 無 ABI 風險）。

**頂層欄位 schema（全 Python 服務統一；`libs/obs/obs.py::init_logging()` 一處實作）**：

| 欄 | 型別 | 源 |
|---|---|---|
| `timestamp` | ISO8601 str | `TimeStamper(fmt="iso", utc=True)` |
| `level` | str（`info`/`warning`/`error`…） | `add_log_level` |
| `service` | str（`hello`/`rag-service`/`reco-service`/`ga-ask`/`ptt-consumer`/`airflow-task`） | `init_logging(service_name)` 綁定 |
| `event` | str（人讀訊息；structlog 慣例主鍵） | 呼叫端 |
| `trace_id` / `span_id` | 032x/016x hex str；**無活躍 span 時省略欄位**（不填 null——Loki json stage 對缺欄容錯，省 bytes） | 自訂 processor（structlog 官方 frameworks 文件的 OTel processor 變體：**平鋪頂層**而非巢狀 `span{}`——Loki derived fields 用 json parser 取頂層鍵最穩，§2.5） |
| `exc_info`→`exception` | str | `format_exc_info` |
| 其餘 kv | 任意 | 呼叫端 context（如 `video_id`、`dag_id`、`outcome`） |

- 第三方/stdlib logger（uvicorn、airflow、langchain…）：`ProcessorFormatter` 掛 root handler 統一出 JSON（structlog 官方 stdlib 整合，0.3 已證）。
- **範圍**：hello、RAG、reco、ga_ask（批次+live）、PTT consumer、Airflow task pod 內我方 Python 工序＝改 logging 初始化一行（`init_logging()`），**業務碼零改**（加儀器不改合約）。**Spark/Flink/Airflow scheduler 本體/第三方 chart 服務不改造**——它們的 stdout 由 §2.3 DaemonSet 原樣收進 Loki（誠實：非 JSON 行就當 raw line 查，`service` 維度靠 pod label 而非 body 欄位）。
- live（Cloud Run）：同一 `init_logging()` 出 JSON 到 stdout → Cloud Run 原生 Logging 收（**不回送本地 Loki**，同 §1.3 拓撲；known-limit 同句處理）。

### 2.2 Loki 部署形

| 項 | 拍板 |
|---|---|
| 形態 | **helm chart `grafana/loki`，`deploymentMode: SingleBinary`**（monolithic，context7 已證官方支援），replicas 1，ArgoCD 子 App `loki`（wave 17），namespace `observability`；chart 版本 pin＝plan 前實查 #1（預設當日最新 stable；判準＝Loki 3.x、SingleBinary 模式、可全關持久化） |
| 儲存 | **emptyDir**（persistence off；filesystem object store 落 emptyDir）＋`limits_config.retention_period: 24h`＋compactor retention 開——與 Prometheus/Tempo 三者同一 24h 誠實姿態 |
| auth | `auth_enabled: false`（單租戶 demo；README 標雲上要開） |
| 自身監控 | `/metrics` ServiceMonitor 全叢集發現既有機制撿；告警 `LokiDown`（`up==0` 10m warn） |
| 資源 | requests `100m/256Mi` limits `500m/1Gi` |

### 2.3 collector 拍板：Grafana Alloy（Promtail 已 deprecated）

**context7 定案**：Promtail 自 Loki 3.4 起官方 deprecated、碼併入 **Grafana Alloy** → 新建一律 Alloy，不選夕陽件。helm chart `grafana/alloy`（版本 pin＝plan 前實查 #1），**DaemonSet**（單節點 kind 實際 1 pod×3 節點；mounts varlog），ArgoCD 子 App `alloy`（wave 17）。config（ConfigMap，宣告式進 git）＝context7 驗證過的官方管線：

```
discovery.kubernetes "pods" { role = "pod" }
discovery.relabel "pod_logs" { …namespace/pod/container/app/job 五個 index label… }
loki.source.kubernetes "pods" { targets → forward }
loki.write "loki" { endpoint { url = "http://loki.observability.svc:3100/loki/api/v1/push" } }
```

**label 紀律**（Loki 官方 label 最佳實踐）：index label 只留 `namespace/pod/container/app/job` 五個；`service`/`level`/`trace_id` **不當 label**（高基數），查詢時 LogQL `| json | level="error"` 動態抽。**Alloy 與「一工一具」關係明標**：Alloy 是 log 柱的 collector 元件（同 Promtail 定位、Grafana 原生），不是第二個 metrics/trace 管線——本 design **不用** Alloy 收 metrics/trace（Prometheus scrape 與 app 直送 OTLP 既有路徑不變，避免 collector 職責膨脹）。

### 2.4 為什麼這不違「不要 9 件套」（翻案論證落地，ADR-lite 素材）

Loki＝Prometheus 做不到的獨特工作（log 儲存查詢）；同一個 Grafana 查（零新 UI）；單 binary＋emptyDir（零持久化負擔）；collector 是 log 柱的必要組成非獨立系統。對照 B 組取材裡的 ELK（filebeat+logstash+elasticsearch+kibana 四件、獨立 UI、JVM 重）＝被拒絕的形狀，唯讀對照後明確不取（§0.2）。

### 2.5 log↔trace 雙向關聯（Grafana datasource 設定，宣告式）

| 方向 | 設定 |
|---|---|
| log→trace | Loki datasource `derivedFields: [{name: "trace_id", matcherType: "label", matcherRegex: "trace_id", datasourceUid: "tempo", url: "${__value.raw}"}]`（json 抽頂層 `trace_id`；確切 matcher 語法以 plan 實查 #3 同步驗——預設 regex `"trace_id":"([a-f0-9]{32})"` 保底，判準＝log 行出現「Tempo」按鈕可跳） |
| trace→log | Tempo datasource `tracesToLogsV2: {datasourceUid: "loki", spanStartTimeShift: "-5m", spanEndTimeShift: "5m", filterByTraceID: true, tags: [{key: "service.name", value: "app"}]}`——span→該服務±5m 帶 trace_id 過濾的 Loki 查詢 |
| datasource 落地 | Tempo（uid `tempo`）/Loki（uid `loki`）兩個 datasource 以 **sidecar datasource ConfigMap** 佈建（P1 §9 Postgres datasource 已用同機制，慣例現成），放 `platform/monitoring/observability/datasources.yaml`，由 §8.2 的 wave 18 App sync |

---

## 3. ③ SLO / error budget（拍板：純 PrometheusRule，零新常駐服務）

### 3.1 表達法拍板

**PrometheusRule recording rules ＋ multi-window multi-burn-rate 告警（Google SRE Workbook 範式），Grafana 普通 dashboard 呈現。** 淘汰：**Grafana 原生 SLO**——context7 查證其文件全在 Grafana Cloud（IRM）之下＝Cloud/Enterprise 功能，OSS Grafana 沒有 SLO 物件（硬事實，不是取捨）；**Sloth/Pyrra 生成器**——新工具面違翻案邊界（本 design 只被授權 Loki/Tempo/OTel），4 條 SLO 手寫 rules 完全可控且「手寫 burn-rate rules」本身是面試講點。**符合硬約束：③ 零新常駐服務**（純 rules＋既有 Grafana）。

### 3.2 SLO 清單（4 條；每條含 SLI 定義、目標、窗口、既有告警對應）

| # | SLO | SLI（PromQL 語意；指標全部既有，零新儀器） | 目標/窗口 | 收斂自（保留不刪） |
|---|---|---|---|---|
| S1 | **YT 管線新鮮度** | good＝`yt_freshness_seconds < 10800`（3h，＝既有 warn 閾值）的時間占比：`avg_over_time((yt_freshness_seconds < bool 10800)[window])`（P1 :434 指標） | **99% / 30d**（≈7.2h/月 預算——容一次週末壞掉修復） | `YTDataStale`（P1 :435） |
| S2 | **請求服務可用性**（hello＋RAG＋reco 各一組 label） | `1 - (sum(rate(http_requests_total{status=~"5..",handler!~"/metrics\|/healthz"}[w])) / sum(rate(http_requests_total{handler!~"/metrics\|/healthz"}[w])))` by (namespace,job)（P0 :425 instrumentator 指標） | **99.5% / 30d** | `MLServingDown`/`LakehouseComponentDown`（up 類 cause 告警） |
| S3 | **RAG/問 AI 成功率** | good＝非 degraded 且非 error：RAG `1 - (degraded+error)/total`（P2 :445 llmops 指標）；ga_ask `sum(rate(ga_ask_requests_total{outcome="ok"}[w]))/sum(rate(ga_ask_requests_total{outcome!~"rejected"}[w]))`（ask-ai :379；**`rejected`＝guardrail 正確拒答，不算 bad event**——把安全行為算失敗是自打臉，明標） | **99% / 30d** | `RAGDegradedRateHigh`（P2 :448） |
| S4 | **RAG 延遲** | 快請求占比：`sum(rate(rag_request_duration_seconds_bucket{le="30"}[w]))/sum(rate(rag_request_duration_seconds_count[w]))`（LLM 生成鏈，30s＝ask-ai §8 已公告的「單題 15–30 秒」上緣） | **95% / 30d** | （新增服務水準語意；無既有告警對應） |

**明確不做成 SLO**（誠實劃界，寫進 dashboard Explainer）：ML drift（`ml_feature_psi`/`ml_rolling_auc`）＝模型健康訊號非使用者可感服務水準，SLO 化是語意誤用——維持 P2 既有告警＋重訓閉環；Flink/PTT 已有針對性告警且屬間歇 demo 負載（P6 :379「重放間歇性、watermark 停滯是常態」同一誠實邏輯——對間歇工作量算 30d 可用性是假數字）。

### 3.3 error budget＋burn-rate 告警（每條 SLO 同構，rules 落 `platform/monitoring/observability/slo-rules.yaml`）

- **recording rules**：每 SLO 出 `sli:<name>:ratio_rate5m/30m/1h/6h`（多窗口預算）＋`slo:<name>:error_budget_remaining`（30d 窗：`1 - (1-sli_30d)/(1-target)`）。
- **告警（Google SRE Workbook 兩級 multi-window multi-burn-rate）**：
  - `<Name>SLOFastBurn`：`burn_rate_1h > 14.4 AND burn_rate_5m > 14.4` → **critical**（14.4x＝1h 燒掉 30d 預算 2%；5m 短窗防已修復仍叫）。
  - `<Name>SLOSlowBurn`：`burn_rate_6h > 3 AND burn_rate_30m > 3` → **warning**。
  - S1（freshness 是 0/1 型慢變 SLI）只設 slow-burn 一級（fast-burn 對小時級管線無意義——3h 才可能 stale，5m 窗恆空，誠實砍）。
- **與既有 threshold 告警的關係（合約句）**：既有 A1–A6 告警（YTDataStale/PttDataStale/MLModelQualityDegraded/Flink*/RAGDegradedRateHigh/…）＝**cause-based**（哪裡壞了），全數保留零改；SLO burn-rate＝**symptom-based 上層收斂**（使用者何時開始受害、還剩多少預算）。兩層並存是 SRE 正統，不是重複告警——這句進 DECISIONS.md 條目與 dashboard Explainer。
- **rules 可測**：`promtool test rules` unit tests（每條 burn-rate 告警配一組合成序列：正常/快燒/慢燒三案例），進 pr-checks（§8.5）——精確度契約「每步可測」在 rules 層的落法。

### 3.4 Grafana `slo-overview` dashboard（ConfigMap sidecar，新檔）

四行（每 SLO 一行）：SLI 30d 曲線（目標線）＋ error budget 剩餘 gauge ＋ burn rate 1h/6h 雙線 ＋（S2–S4）exemplar 開啟的延遲/錯誤面板（§1.5 跳轉入口）。誠實帶（dashboard text panel）：「demo 叢集 Prometheus retention 24h——30d 窗在重建後只有部分資料；SLO 機制與規則是完整實踐，長窗數值在叢集壽命內漸進成立」（**這是 emptyDir 姿態對 SLO 的誠實推論，不迴避**；README 同句）。

---

## 4. ④ pipeline 自癒＋四級健康報告（拍板：純應用層，零新基建）

### 4.1 示範管線拍板：P1 留言 ingest（Bronze→Silver 清洗步）

**選 P1 留言管線**（淘汰 P2 ML 資料驗證：P2 已有 drift→重訓閉環敘事，再疊自癒會糊掉兩個故事；留言語料是「真髒資料」最誠實的落點）。**非假裝資料髒**：YouTube 留言真實存在空文/純顏文字（非字母數字）/超長貼文/控制字元夾帶——`_heal_review` 的 5 分支在此語料是**真實分佈**，README 記實測 heal 率不預造數字。

**落點形狀（additive，不改既有 DAG task 的合約）**：留言 Spark 清洗 job（P1-comments design 的 Bronze→Silver 工序）內，MERGE 之前插入 `heal_comments()` 純函式層（`lakehouse/spark/jobs/` 內同 job 檔的獨立模組函式，~100 行，可單測）；DAG 尾端 additive 加一個 `generate_health_report` task（PythonOperator，讀本次 run 統計寫 DB＋log）。既有 task 鏈、Silver MERGE 語意、dbt gate 全部原樣。

### 4.2 修復動作清單（對照 `_heal_review` 5 分支 → 本平台語料的對應；`error_type` 值即合約）

| # | 偵測（本平台語料） | `error_type` | 修復動作（`action_taken`） | 對照原 pattern 的進化 |
|---|---|---|---|---|
| 1 | text 為 null/非 str 且不可轉 | `missing_text` | **`quarantined`**：該列標記隔離、不進 Silver 語料主體（記 heal_log），**不填 placeholder**——placeholder 假句會汙染 RAG embedding/微調語料（原 demo 填 `'No review text provided.'` 是情緒分類語境才成立的做法，明確不取） | 修復語意從「填充」改「隔離」 |
| 2 | 非 str 但可安全轉（int/float 誤型） | `wrong_type` | `type_conversion`：`str()` 轉換後續入，`was_healed=true` | 照取 |
| 3 | 空字串/純空白 | `empty_text` | `quarantined`（同 #1 理由） | 同 #1 |
| 4 | 剝除控制/零寬字元後為空，或非字母數字/CJK 佔比 100%（純符號/顏文字） | `special_characters_only` | `stripped_control_chars`：剝除控制/零寬字元（ask-ai §4 guardrail 已有同款正規化先例）；剝完仍空→降級 `quarantined` | 「替換為 `[Non-text content]`」改「剝除＋隔離」 |
| 5 | 長度 > 5000 字元（YouTube 留言 API 實際上限量級；確切門檻 plan 對真資料分佈校準，預設 5000） | `too_long` | `truncated`：截 5000＋`…`，`was_healed=true`（截斷對 embedding/展示無害且必要） | 照取，門檻換本平台語料 |

**標記落地（additive-only 邊界內）**：`silver_youtube_comments` **additive 加 2 欄** `was_healed boolean NOT NULL DEFAULT false`、`heal_action text NULL`（P1-comments 13 欄合約是 additive-only 穩定合約——加欄合法、既有欄語意零動；P2b/P2c 消費端不讀新欄零影響，quarantined 列**不進 Silver** 所以下游天然乾淨）。逐 run 統計落新表 `dq.dq_heal_log`（**新 schema `dq`，新表，零改既有 DDL**）：

```sql
CREATE TABLE dq.dq_heal_log (
  run_id        text        NOT NULL,   -- Airflow run_id
  pipeline      text        NOT NULL,   -- 'yt_comments'
  executed_at   timestamptz NOT NULL,
  total_rows    bigint      NOT NULL,
  healed_rows   bigint      NOT NULL,   -- was_healed（#2/#4/#5 成功修復）
  quarantined_rows bigint   NOT NULL,   -- #1/#3/#4 降級（不可修復）
  by_error_type jsonb       NOT NULL,   -- {"missing_text": n, ...}
  health_status text        NOT NULL,   -- §4.3 四級
  PRIMARY KEY (run_id, pipeline)
);
```

### 4.3 四級健康報告（門檻＝拍板值；分級骨架取材 :424-460）

`generate_health_report` task 依本次 run 統計定級並寫 `dq_heal_log.health_status`：

| 級 | 條件（quarantine_rate＝quarantined/total；healed_rate＝healed/total） | 語意 |
|---|---|---|
| `CRITICAL` | quarantine_rate > 10%（沿原 `degraded > 10%` 門檻） | 語料大面積不可修復——上游 API/解析可能壞了 |
| `DEGRADED` | quarantine_rate > 0（沿原 `degraded > 0`） | 有不可修復列（量小屬正常背景，但如實分級——分級是訊號不是判罪） |
| `WARNING` | healed_rate > 10%（原 50% 太鬆——本平台語料通常乾淨，10% 已是分佈異常訊號；拍板收緊並記入 ADR-lite） | 修復率異常高——來源分佈變了 |
| `HEALTHY` | 其餘 | — |

判級順序 CRITICAL→DEGRADED→WARNING→HEALTHY（先壞後好，同原碼 if 鏈）。report 本體（JSON：run_info＋rates＋by_error_type＋status）進 task log（Airflow `get_logs=True` → ② 的 Loki 可查）＋ DB 列——**進化點：原 pattern 只 log 即丟，本平台落表＋metric 可稽核可告警**。

### 4.4 指標與告警（走既有 postgres-exporter 自訂查詢模式，零新 exporter）

`lakehouse-exporter-queries` ConfigMap **additive 加 3 條**（P1 :434 同款 SQL 即合約）：
- `dq_pipeline_health_status{pipeline}`＝最新 run 的級別映射 0/1/2/3（HEALTHY=0…CRITICAL=3）：`SELECT DISTINCT ON (pipeline) pipeline, CASE health_status WHEN 'HEALTHY' THEN 0 WHEN 'WARNING' THEN 1 WHEN 'DEGRADED' THEN 2 ELSE 3 END AS status FROM dq.dq_heal_log ORDER BY pipeline, executed_at DESC`。
- `dq_healed_rate{pipeline}`、`dq_quarantine_rate{pipeline}`＝最新 run 比率。

PrometheusRule（同檔 §8.4）：`PipelineHealthDegraded`（`dq_pipeline_health_status >= 2` 持續 1h → warning）、`PipelineHealthCritical`（`== 3` → critical）。Grafana 新 dashboard `dq-self-healing`（sidecar 新檔，不動既有 pipeline-health）：狀態燈、heal/quarantine 率曲線、by_error_type 堆疊、最近 run 表。

### 4.5 與既有 dbt DQ gate 的分工（合約句）

**自癒＝gate 前的軟修層**（可修復者修復並標記、不可修復者隔離並記錄，管線不炸）；**dbt gate＝硬擋層**（freshness/schema/唯一性等結構性契約違反＝fail DAG，P1 :222/:225 原樣）。自癒**不豁免** gate——修復後的資料照過 `dbt_test`；若自癒本身出 bug 產生違約資料，gate 仍會擋（縱深防禦，兩層職責不重疊）。此句進 DECISIONS.md。

**誠實護欄**：不注入假髒資料、不做「demo 旋鈕弄髒資料」（違 grounding——P2 的演示旋鈕是限縮真母體，性質不同）；README 記示範規模與真實 heal 率；若真實語料乾淨到 heal 率 ≈0，這本身如實展示（健康報告恆 HEALTHY 也是正確行為，敘事講 pattern 與機制不講捏造的搶救戲）。

---

## 5. ⑤ Cloud Run live 端點觀測性縫（拍板：補 blackbox 黑盒層；白盒維持原判）

**拍板：做**——blackbox-exporter 補外部 uptime 探測，理由：ask-ai :485 的縫是「白盒 scrape 不確定、降級即棄集中監控」——黑盒層讓「scrape 成不成」都至少有可用性觀測，且 blackbox-exporter 單 binary 輕量（守翻案邊界的「一工一具」：黑盒探測是 Prometheus 生態原生件非新系統）。

| 件 | 拍板 |
|---|---|
| 部署 | helm chart `prometheus-community/prometheus-blackbox-exporter`（版本 pin＝plan 前實查 #1），ArgoCD 子 App `blackbox`（wave 17），namespace `observability`；只開 `http_2xx` module（timeout **30s**——含 Cloud Run 冷啟；context7 驗過 module/timeout 欄位） |
| 探測對象 | `ga-ask-live`／`search-live` 的 `GET /healthz`（兩者 design 皆已定義 /healthz，:399／search-v2 §7）；目標 URL 部署後回填（同 ask-ai 實查 #2 的 URL 回填動線） |
| 接線 | **Probe CRD**（prometheus-operator 既有 CRD，kube-prometheus-stack 87.10.1 已裝且 :372 已放開 selector——`probeSelectorNilUsesHelmValues: false` additive 補一行，§8.3）；`interval: 15m`（**成本/誠實取捨**：probe 會喚醒 scale-to-zero 實例——15m＝96 次/日 healthz 輕請求，美分級零頭且不常駐保溫；不追秒級 uptime，明標「外部可達性煙囪非 SLA 監控」） |
| 告警＋面板 | `LiveEndpointDown`：`probe_success == 0` 持續 45m（3 個 probe 週期，容單次冷啟 timeout 誤報）→ warning（**不設 critical**——live demo 離線有前端降級文案兜底，ask-ai :403，非平台核心路徑）；`LiveEndpointCertExpiry`：`probe_ssl_earliest_cert_expiry - time() < 14d` → info。Grafana dashboard `live-endpoints`（sidecar 新檔）：probe_success 時間線、probe_duration（冷啟可視化——本身是 scale-to-zero 的誠實展示素材）、cert 到期 |
| 白盒 scrape | **維持 ask-ai plan 實查 #3 原判零改**（預設 additional scrape config 直刮 `/metrics`，失敗降級 Cloud Run 內建 metrics＋known-limit）——本 design 不取代不重判，黑盒白盒互補的關係寫進該 dashboard Explainer |
| 不做 | 前端不出現任何 live 探測資料（拓撲鐵律：前端零新 live 依賴——live 端點狀態只在 Grafana，前端維持既有 LiveDemoCard 降級文案機制） |

---

## 6. ⑥ 告警通知通道（拍板：接一個 Discord webhook receiver，閉環 demo）

**拍板：做**——理由：P1 :435「不接通道、demo 看 UI」在 P1 語境正確（當時無 ⑥ 授權），但「告警→人」是 SRE 閉環的最後一哩，面試必問「告警去哪」；成本零、**零新常駐服務**（Alertmanager 既有，P0 :384）、原生支援。**不為炫技**判準：只接一個通道、只推該推的。

| 件 | 拍板 |
|---|---|
| 通道 | **Discord webhook**（Alertmanager 原生 `discord_configs`，0.25+ 支援；87.10.1 所帶 Alertmanager 遠高於此。淘汰：ntfy——Alertmanager 對 ntfy 無原生 config、要橋接器＝多一個服務違零新常駐；email——要 SMTP 憑證與寄信信譽，重；Slack——Fergus 日用面偏 Discord 量級的免費 webhook，且 Slack 免費層訊息保留限制） |
| 落地 | **AlertmanagerConfig CRD**（`monitoring.coreos.com/v1alpha1`，prometheus-operator 既有；`alertmanagerConfigSelector` 放開＝§8.3 additive 一行）：route `severity =~ "critical\|warning"` → receiver `discord`（`apiURL` 引 k8s Secret `alertmanager-discord` key `webhook-url`）；`group_by: [alertname]`、`group_wait: 1m`、`repeat_interval: 12h`；`severity="info"` 不推（`MLStagingCandidateReady`/cert-expiry 這類提示留 UI）。**AlertmanagerConfig CRD 的 `discordConfigs` 欄位存在性＝plan 前實查 #5**（預設有——operator 追 Alertmanager 上游 config；若無則降級 `webhookConfigs` 打 Discord 的 slack-compatible endpoint `…/slack`，判準＝手機真的收到測試告警） |
| secret 姿態 | webhook URL＝命令式 `kubectl create secret generic alertmanager-discord`（文件化、不進 git）——沿 P0 §7/P1 §8 既定紀律，README secret 邊界章 additive 一列 |
| 誠實 | README 標「demo 環境非 24/7 on-call；通知閉環展示的是機制非值班承諾」；Discord 頻道截圖（告警卡片）進 ⑦ 截圖清單 #12 的素材候選 |

---

## 7. ⑦ 前端平台架構支柱觀測性敘事（additive；零新 live 後端）

### 7.1 落點拍板

**不新增頁、不新增支柱**——`/architecture`（platform 支柱既有頁，P4 :192＋Signal §5.3 bento 版面）**additive 加一個「可觀測性」bento 區塊**：

- **內容**：三柱＋自癒四張卡（lucide icon：trace=`Activity`、log=`ScrollText`、SLO=`Gauge`、自癒=`HeartPulse`；**emoji 禁用**）＋截圖牆 additive 擴 4 張（§7.4 的 #9–#12，沿既有 2×3 grid→擴 grid、hover scale＋Dialog lightbox 既有 pattern）＋一段誠實敘事文字（固定句式，與 FreshnessBanner 同語氣）：「觀測性後端（Tempo/Loki/Prometheus）皆為叢集內服務、資料 emptyDir 不留存——本站以截圖與架構圖佐證，無任何 live 觀測性依賴」。
- **說明式 registry（阻擋級）**：`/architecture` 的既有 registry 條目（crosscut §5）**內容 additive 擴寫**——`whatItDoes` 補「含可觀測性三柱與 pipeline 自癒的架構敘事」、`howToRead` 補觀測性區塊怎麼看；**不新增 entryId**（無新頁＝無新條目，coverage gate 既有斷言天然通過；改的是條目內容非 schema）。區塊內每張卡帶 `ChartCaption` 一行式說明（既有元件）。
- FreshnessBanner／Signal token／`output:'export'`／既有 11 頁：**零觸碰**。

### 7.2 敘事骨（卡片文案方向，plan 撰稿）

每卡三拍：這是什麼（柱）→ 為什麼 Prometheus/Grafana 做不到（獨特工作）→ 憑證（截圖＋「同一個 Grafana 查三種訊號」）。自癒卡多一拍：偵測→修復→標記→四級報告的 pattern 敘事＋「不可修復者隔離而非填充」的資料誠實講法。

### 7.3 架構圖（P5 §3 additive）

既有 Mermaid 4 張**零改**；**additive 第 5 張 `observability.md`**：左＝服務群（hello/RAG/reco/ga_ask）出三箭（`/metrics`→Prometheus、OTLP→Tempo、stdout→Alloy→Loki）；中＝三後端＋同一 Grafana 匯流（exemplar/derived-fields 互跳畫成雙向虛線）；右＝Alertmanager→Discord；下分區＝自癒（heal→health report→exporter→Prometheus）。M4/k8s 界線沿圖③「節點放分區」慣例（不依賴 subgraph direction——P5 :290 已明載的 Mermaid 紀律）。

### 7.4 P5 交付清單擴充（§0.1 P5 :364-372 錨；additive #9–#12）

| # | 內容 | 形式 |
|---|---|---|
| 9 | Tempo trace 瀑布（RAG `/ask` 一條完整 span 樹：retrieve→grade→generate＋LLM client span） | PNG |
| 10 | Grafana Explore split view：metric exemplar 跳 trace、trace 跳 Loki log（三柱一鍵動線） | PNG |
| 11 | `slo-overview` dashboard（error budget gauge＋burn rate） | PNG |
| 12 | `dq-self-healing` dashboard ＋ Discord 告警卡片（合圖或兩張，plan 定） | PNG |

GIF 仍只 #1 一支（P5 原判不動）。one-pager「可現場 demo 清單」（P5 :315）additive 加兩行：`kubectl port-forward` 後 Grafana Explore 三柱互跳、`make verify` 的 tracing smoke。

---

## 8. ⑧ 資料流/部署/守門/交付（全 additive）

### 8.1 檔案落點總表（新增）

```
platform/
├── argocd/apps/
│   ├── tempo.yaml                    # wave 17（helm grafana/tempo，單 binary）
│   ├── loki.yaml                     # wave 17（helm grafana/loki，SingleBinary）
│   ├── alloy.yaml                    # wave 17（helm grafana/alloy，DaemonSet+ConfigMap）
│   ├── blackbox.yaml                 # wave 17（helm prometheus-community/prometheus-blackbox-exporter）
│   └── observability-config.yaml     # wave 18（directory → platform/monitoring/observability/）
└── monitoring/observability/
    ├── datasources.yaml              # Tempo/Loki datasource sidecar ConfigMap（uid: tempo / loki）
    ├── slo-rules.yaml                # PrometheusRule：S1–S4 recording+burn-rate（§3）
    ├── obs-alerts.yaml               # PrometheusRule：TempoDown/LokiDown/PipelineHealth*/LiveEndpoint*（§2/§4/§5）
    ├── probes.yaml                   # Probe CRD ×2（live 端點，§5）
    ├── alertmanager-config.yaml      # AlertmanagerConfig CRD（Discord route，§6）
    └── dashboards/                   # slo-overview / dq-self-healing / live-endpoints（sidecar ConfigMap）
libs/obs/obs.py                       # init_tracing/init_logging/current_trace_exemplar 正本（§1.1/§2.1）
lakehouse/spark/jobs/…（留言 job 檔內 heal_comments 模組函式）＋ orchestration/dags/…（generate_health_report task）  # §4，additive 插入
lakehouse/postgres/init/…             # dq schema + dq_heal_log DDL（沿 P1 init SQL 慣例 additive）
docs/architecture/diagrams/observability.md   # 第 5 張架構圖（§7.3）
scripts/verify-observability.sh       # §9；Makefile += observability-verify
```

### 8.2 sync-wave：**17**（tempo/loki/alloy/blackbox 四個 chart App，互不依賴可同 wave）→ **18**（observability-config：datasource/rules/probe/AlertmanagerConfig/dashboards——CRD 資源全帶 `SkipDryRunOnMissingResource=true`，P0 §6 慣例）。接續 P6 realtime 的 14–16，不與既有任何 wave 衝突。**服務對觀測性零硬依賴**（OTLP env 未設即 no-op、log 本就出 stdout）→ wave 晚於服務不影響服務啟動，這是 only-additive 在部署序上的體現。

### 8.3 觸碰既有檔案清單（**全部 additive 值，逐一列明；此外零檔案改動**）

| 檔 | additive 改動 | 不動的 |
|---|---|---|
| `platform/argocd/apps/monitoring.yaml`（P0 §5） | `prometheusSpec.enableFeatures: [exemplar-storage]`＋`probeSelectorNilUsesHelmValues: false`＋`alertmanagerConfigSelector`/`alertmanagerConfigNamespaceSelector` 放開（確切 key plan 實查 #5 同步）＋（若實查 #3 走 values 路徑）Grafana datasource exemplar 設定 | chart 版本 87.10.1、retention、emptyDir、sidecar、ingress、其餘全部 values 原字 |
| 各服務 Dockerfile/requirements（hello/RAG/reco/ga_ask） | `+ opentelemetry-{api,sdk,exporter-otlp-proto-grpc,instrumentation-fastapi,instrumentation-httpx,instrumentation-psycopg}` ＋ `structlog`（版本 pin＝plan 實查 #4）；`main.py` 加 `init_tracing()/init_logging()` 兩行＋vendor `obs.py` | API/路由/既有指標/healthz/probe 全原樣 |
| 留言 ingest job＋DAG（P1-comments） | §4.1 的 heal 函式層＋health report task＋Silver 兩 additive 欄 | 既有 task 鏈/MERGE key/13 欄語意/quota 姿態 |
| `lakehouse-exporter-queries` ConfigMap（P1 §9） | +3 條 dq 查詢（§4.4） | 既有 `yt_*`/`ml_*`/`ptt_*` 查詢原字 |
| `.github/workflows/pr-checks.yaml` | + promtool rules test job＋obs.py drift diff（§8.5） | 既有 job 原樣 |
| frontend `/architecture` 頁＋registry 條目 | §7.1 區塊與條目內容擴寫 | 其餘頁/schema/token 零動 |
| README | known-limit 三句（trace/log 不留存、live 不回送、SLO 長窗）＋secret 邊界 +1（Discord webhook）＋自癒誠實段 | — |

**明確不改**：P0–P7/ask-ai 全部既有合約/DDL/告警規則/probe/dashboard ConfigMap、P4 匯出信封、MCP 工具、Signal token、`output:'export'`、CodeWithYu 原專案（唯讀）。

### 8.4 CI/守門

- **無新 image**（Tempo/Loki/Alloy/blackbox 全官方 chart image；heal 碼在既有留言 job image 內走既有 CI paths）→ 零新 build workflow。
- pr-checks additive：①`promtool check rules && promtool test rules`（SLO 與 obs 告警 rules＋§3.3 三案例 unit tests）②`libs/obs/obs.py` 與各服務 vendored 副本位元組 diff（沿 crosscut drift job 模式）。
- 既有 grep 守門（P0 :531 `storageClassName`/`alb.ingress` 為空）天然涵蓋新 manifests（全 emptyDir、零專屬註解）。
- heal 函式單測（5 分支×修復/隔離斷言＋分級門檻表測）進留言 job 既有 pytest。
- frontend：既有 `gate:explainers` 天然涵蓋（無新頁無新條目；條目內容改動不觸 gate 結構）。

### 8.5 ADR-lite（P5 `DECISIONS.md` additive 四條；出處＝本檔）

17. Trace 柱＝OTel＋Tempo 單 binary（vs Jaeger：Grafana 原生同棧、單 binary、exemplar 原生）——§1。
18. Log 柱＝structlog JSON＋Alloy＋Loki 單 binary（vs ELK：翻案邊界明拒的堆疊；vs Promtail：官方已 deprecated）——§2。
19. SLO＝手寫 PrometheusRule multi-window multi-burn-rate（vs Grafana SLO：Cloud-only 硬事實；vs Sloth/Pyrra：翻案邊界外的新工具）；SLO 收斂不取代 cause 告警——§3。
20. 自癒＝應用層 heal→標記→隔離＋四級健康報告（取材 SelfHealingPipeline pattern；隔離取代 placeholder 填充、落表取代 log 即丟）；gate 硬擋/自癒軟修分工——§4。

---

## 9. 端到端驗收清單（`scripts/verify-observability.sh`＝`make observability-verify`，全自動任一步 fail 即非零退出；沿 P0 §8 形式）

| # | 檢查 | 要點 | 預期 |
|---|---|---|---|
| 1 | 四 App 收斂 | ArgoCD `tempo/loki/alloy/blackbox/observability-config` 全 `Synced+Healthy`（P0 verify 同款 jq 輪詢） | 5 app 綠 |
| 2 | Tempo 收得到 trace | `curl hello.localtest.me/`（產 trace）→ 輪詢 Tempo `GET /api/search?tags=service.name%3Dhello`（port-forward :3200） | 至少 1 條 trace |
| 3 | RAG span 樹 | `POST rag.localtest.me/ask` → Tempo 查該 trace → span 名含 `rag.retrieve`/`rag.generate` | span 樹成形 |
| 4 | Loki 收得到 JSON log | Loki `query_range`（port-forward :3100）：`{namespace="apps"} \| json \| service="hello"` | 非空且解析出 `level` 欄 |
| 5 | log↔trace 關聯 | 取 #3 的 trace_id → LogQL `{namespace="ml"} \| json \| trace_id="<id>"` | 命中該請求 log 行 |
| 6 | exemplar | Prometheus `/api/v1/query_exemplars?query=rag_request_duration_seconds_bucket` | 回傳含 traceID 的 exemplar |
| 7 | SLO rules 載入 | Prometheus `/api/v1/rules` 含 `slo:*:error_budget_remaining` 且無 rule eval error；promtool test 已在 CI 綠 | recording+alert 全註冊 |
| 8 | 自癒鏈路 | 對 heal 函式單測綠（CI）＋跑一次留言 DAG → `SELECT health_status FROM dq.dq_heal_log ORDER BY executed_at DESC LIMIT 1` 非空；`curl` exporter `/metrics` 含 `dq_pipeline_health_status` | 分級落表＋指標暴露 |
| 9 | blackbox | `/probe?target=<ga-ask-live>/healthz&module=http_2xx` 經 Prometheus `probe_success` 查詢 | ==1（live 未部署時本步 skip＋警示，不 fail——URL 回填前的誠實降級） |
| 10 | 通知閉環（半自動 runbook） | `amtool alert add test-alert severity=warning` → Discord 頻道收到卡片（文件化步驟，一次性） | 手機/桌面可見 |
| 11 | Grafana 三 dashboard | `/api/search?query=SLO`／`Self-Healing`／`Live Endpoints` | 三 title 命中（title 固定，沿 P0 :400 慣例） |
| 12 | 可重現 | `make cluster-down && make cluster-up && make verify && make observability-verify` | 全綠（trace/log 歸零重來＝emptyDir 誠實行為，verify 自產流量） |

---

## 10. plan 期待查證點（皆帶預設傾向與判準；非阻擋本 design 收斂）

1. **四個 helm chart 版本 pin**（tempo/loki/alloy/blackbox-exporter）——設計錨的是部署形與 config 介面（context7 已證）；確切 chart version 於 plan 首步以 `helm search repo` pin 進 Application `targetRevision`（P0 pin 87.10.1 同紀律）。判準：Tempo 2.x 單 binary、Loki 3.x SingleBinary、Alloy 收 pod log 三件套組件可用、blackbox `http_2xx`。
2. **instrumentator 8.0.2 的 http_* 指標 exemplar 支援**——預設不動（自有 histogram 已足）；若支援則開，判準＝不改既有指標名/label（§1.5）。
3. **Grafana 內建 prometheus datasource 加 `exemplarTraceIdDestinations` 的確切 values 路徑**（87.10.1）＋ Loki derivedFields matcher 對 json log 的確切語法——預設 sidecar datasource ConfigMap 路徑；判準＝Explore 可從 metric 跳 trace、log 行出 Tempo 按鈕（§1.5/§2.5）。
4. **structlog／OTel 套件組版本 pin**——預設當日 stable（structlog 25.x、opentelemetry-sdk 1.x stable line）；判準＝§0.3 的 API 面（processors/instrument_app 簽名）不變。
5. **AlertmanagerConfig CRD `discordConfigs` 欄位**——預設有；無則降級 `webhookConfigs` 打 Discord slack-compatible endpoint；判準＝測試告警真的到 Discord（§6）。
6. **留言 too_long 門檻與真實 heal 率**——預設 5000 字元；plan 對真語料分佈跑一次統計校準並記 README（§4.2 #5）；不預造數字。
7. **host→Tempo ingress OTLP HTTP 路徑煙囪**——預設 `tempo.localtest.me`→4318 直通；若 nginx body size 擋批次 span，調 `proxy-body-size` 或改叢集內跑批次 export（判準＝ga_ask 批次跑完 Tempo 查得到 `ga_ask.*` span）。
8. **live 端點 URL 回填後 Probe 目標接線**——沿 ask-ai 實查 #2 的回填動線；未部署期間 verify #9 走 skip 降級。

## 11. 本 spec 拍板 vs 下放對照

| 領域 | 本 spec 拍板（不再議） | 下放 plan（機械執行/實查校準） |
|---|---|---|
| ① tracing | 儀器化四服務清單＋列外清單、雙 view 關係（DB/UI 零改＋span 疊加）、span 命名 `ga_ask.*`/`rag.*`、attributes 不放原文、Tempo 單 binary+emptyDir+雙口+Ingress、metrics-generator 關、live 不回送（known-limit） | chart pin、span attributes 完整鍵表、Ingress body size 煙囪 |
| ② logging | structlog、頂層欄位 schema、trace_id 平鋪、ProcessorFormatter 兜第三方、非 Python 服務不改造、Loki SingleBinary+24h、collector=Alloy、五 index label 紀律 | chart/套件 pin、Alloy relabel 細節、LogQL 範例文案 |
| ③ SLO | 表達法（手寫 rules；Grafana SLO/Sloth 淘汰）、S1–S4 定義/目標/窗口、rejected 不算 bad、burn-rate 兩級門檻（14.4x/3x）、S1 只 slow-burn、drift 不 SLO 化、cause/symptom 兩層並存、rules 附 promtool unit tests | rules 完整 YAML、三案例測試序列、dashboard JSON |
| ④ 自癒 | 落點（P1 留言）、5 分支修復表（隔離取代填充）、Silver +2 欄、`dq.dq_heal_log` DDL、四級門檻（10%/0/10%）、exporter +3 條、gate 分工、不注入假髒資料 | heal 函式實作、單測表、too_long 校準 |
| ⑤ live 縫 | 做 blackbox＋Probe CRD、15m/30s/45m 參數、告警只 warning、白盒維持 ask-ai 實查 #3 原判 | chart pin、URL 回填接線 |
| ⑥ 通知 | Discord（discord_configs）、AlertmanagerConfig CRD、severity 路由、secret 命令式 | CRD 欄位實查、runbook 文案 |
| ⑦ 前端 | 落點 /architecture bento additive、無新頁無新 entryId、lucide 四 icon、截圖 #9–#12、第 5 張架構圖、FreshnessBanner 零改 | 卡片文案、Mermaid 原始碼、截圖執行期拍 |
| ⑧ 部署 | 檔案落點、wave 17/18、additive 觸碰清單（§8.3 即全集）、CI 兩 job、ADR-lite 17–20 條文方向 | manifests 全文、DECISIONS 條目撰寫 |

## 12. 精確度契約 8 條自檢

1. **開放問題收斂**：8 項全拍板（含 3 個「做/不做」判定：⑤做、⑥做、Grafana SLO 不採）；僅 §10 八點標 plan 實查且全帶預設＋判準。2. **選型具體＋context7**：§0.3 表（OTel API 面/Tempo 單 binary 與端口/Loki SingleBinary/Promtail deprecated→Alloy/structlog OTel processor/exemplar-storage flag/Grafana SLO Cloud-only/blackbox module）；chart pin 下放有判準。3. **資料契約欄位級**：log schema 表（§2.1）、`dq.dq_heal_log` DDL＋Silver +2 欄（§4.2）、SLI PromQL＋exporter SQL 語意（§3.2/§4.4）、`error_type` 值域（§4.2）。4. **部署形狀具體**：§8.1 檔樹、wave 17/18、CRD 與 helm source、datasource uid、ingress host。5. **沿用既有慣例**：sidecar ConfigMap（P0 §5）、postgres-exporter 自訂查詢（P1 §9）、右尺寸/probe（P0 §6）、命令式 secret（P0 §7）、vendor+diff（crosscut 決策 7）、verify 腳本形式（P0 §8）、URL 回填（ask-ai 實查 #2）。6. **進化非複刻**：§0.2 逐項「取 vs 不取」（隔離取代 placeholder、落表取代 log 即丟、ELK 明確不取）。7. **硬約束貫徹**：翻案邊界（只 Tempo/Loki/OTel＋生態原生件；③④ 零新常駐）、拓撲（live 不回送、前端零 live 依賴、截圖佐證）、only-additive（§8.3 全集清單）、secret 不進 git、M4/CPU（全單 binary 輕量、無 GPU 假設）、無互動提問。8. **每步可測**：§9 十二步 verify＋promtool unit tests＋heal 單測＋CI drift gate。

---

## 13. Opus 把關註記（PASS）

> 規劃者（Opus 4.8）獨立覆核。**不轉述 Fable 5 自報**——親跑 context7 覆核最吃重的兩個新宣稱、逐條裁定 5 風險點、跑五鐵律。**判定 PASS，commit 進 trend repo（不加 Co-Authored-By footer——專案 repo 慣例）。**

### 13.1 獨立 context7 覆核（規劃者親查，非採信 §0.3）

覆核挑「若錯則整個決策崩」的兩個承重宣稱：

| 宣稱 | 規劃者獨立查證（context7，2026-07-10） | 判定 |
|---|---|---|
| **Promtail 已 deprecated → Grafana Alloy 為官方繼任 collector** | `/grafana/loki` 三處交叉確認：release notes v3「Promtail has been deprecated as its code is now part of Grafana Alloy」＋ README「Alloy (formerly Promtail)... now the recommended agent for log collection」＋ tanka 安裝文件「ksonnet Promtail module no longer available, use Grafana Alloy」；且官方 k8s pod-log Alloy config（`discovery.kubernetes`→`loki.source.kubernetes`→`loki.write`）與 §2.3 一字對應 | ✅ 屬實。Alloy＝log 柱官方必要組成，**守翻案邊界**（見 13.2-①） |
| **Grafana OSS 無原生 SLO 物件（SLO 是 Cloud/IRM 功能）** | `/websites/grafana` 查 OSS SLO——**唯一命中是 Google Cloud Monitoring datasource 的「查詢 GCP SLO」query builder**（＝讀取 GCP 側 SLO，非 Grafana 原生 SLO 物件）；OSS 無 SLO CRUD 功能面 | ✅ 佐證屬實。③ 手寫 PrometheusRule multi-window burn-rate 正當、非過度工程 |

其餘 §0.3 宣稱（OTel API 面、Tempo 單 binary 雙口、structlog OTel processor、exemplar-storage flag、blackbox module）為既有成熟事實或部署形，隨 §10 版本 pin 於 plan 首步實查即可，不阻擋收斂。

### 13.2 Fable 5 給的 5 風險點逐條裁定

1. **翻案邊界滲入（Alloy／blackbox）**：**無滲入，PASS**。Alloy 經 13.1 獨立證實＝Promtail 官方繼任、Grafana 原生、§2.3 明限「只收 log、不收 metrics/trace」＝log 柱組成非第二管線。blackbox＝brief §5 明文授權 context7 查。兩者皆非 ELK/Jaeger/第二 metrics 系統/第二儀表板。翻案邊界（只 Loki/Tempo/OTel＋生態原生件、③④ 零新常駐）完整。
2. **拓撲鐵律**：**PASS**。Loki/Tempo/OTel/blackbox 全叢集內；前端零新 live 依賴（觀測性只截圖）；唯一新對外面＝blackbox **出站**打 Cloud Run（非入站暴露）；Tempo ingress 僅 `*.localtest.me`（本地域，非公網）；live trace/log 不回送 Tempo/Loki＝誠實 known-limit（拒了「Tempo 對公網收 OTLP」「Grafana Cloud 當 live 後端」兩個會破邊界的選項）。
3. **additive 兩處貼線（Silver +2 欄／P0 values +keys）**：**皆合法 additive，PASS**。①`silver_youtube_comments` +2 欄——P1-comments additive-only 合約明允加欄、13 欄語意零動、quarantined 列不進 Silver 故下游天然乾淨。②P0 monitoring Application +3-4 values key（enableFeatures/probeSelector/alertmanagerConfigSelector/datasource exemplar）——既有 key 一字不動。§8.3 給出觸碰既有檔案的**完整清單**（可稽核邊界），此外零改；新 `dq` schema/表、新 rules/dashboards 全 net-new。
4. **誠實性**：**PASS**。自癒不注入假髒資料、heal 率可能≈0 也如實（健康報告恆 HEALTHY 是正確行為，敘事講機制不講捏造搶救戲）；SLO 30d 窗 vs 24h retention 的矛盾主動寫成 dashboard/README 誠實帶而非迴避；blackbox 標「可達性煙囪非 SLA」；span attributes 不放問答原文（既控 Tempo 體積、也避免語料外洩進 trace 後端＝順帶的安全正確）。
5. **版本 pin 下放**：**不違精確度契約**。契約要求「開放問題收斂成決定」＝架構決定（工具選型、部署形、schema、SLI 定義、判定門檻）已全拍板；§10 八點皆機械實查且帶預設＋判準，chart patch 版號隨 plan `helm search repo` pin＝P0 pin 87.10.1 同紀律。屬合規下放非懸而未決。

### 13.3 規劃者五鐵律覆核

- **接地誠實**：§0.1 A 組逐錨 file:line 疊加關係、§0.2 B 組「取 vs 不取」（placeholder→隔離、log 即丟→落表、ELK 明拒）——P2b/P3 無實碼處誠實錨 design 合約（同搜尋 spec §0.3 precedent）。✅
- **拓撲鐵律**：見 13.2-②。✅
- **一工一具／翻案邊界**：見 13.2-①。✅
- **only-additive**：見 13.2-③；§8.3 全集清單＋§8.4 CI drift/grep 守門天然涵蓋。✅
- **安全**：Discord webhook 命令式 Secret 不進 git（沿 P0 §7）；span/log 不含原文密鑰；Loki `auth_enabled:false` 標明單租戶 demo、雲上要開。✅

**額外肯定的判斷力**：S3 把 guardrail-rejected 排除在 bad event 外（安全行為不算失敗）、drift 明確不 SLO 化（模型健康≠使用者可感服務水準）、cause/symptom 兩層告警並存（SRE 正統非重複）——皆為資深訊號，非機械套模板。

### 13.4 判定

**PASS。** 四項（三柱補齊＋自癒）全拍板、兩承重宣稱獨立證實、翻案邊界與拓撲鐵律與 additive 皆守、誠實性到位。commit 進 trend repo（不加 Co-Authored-By footer）。plan 佇列本 design 排在 P0 之後（Tempo/Loki/Alloy/blackbox 部署吃 P0 kube-prometheus-stack＋ArgoCD 底座；wave 17/18 接續 P6 的 14-16），可與其他 P0-後 plan 平行；④自癒吃 P1 留言管線故序在 P1 之後。
