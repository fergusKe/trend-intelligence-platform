# AI 維運事件敘事者 design（告警觸發 AI SRE 助手：Alertmanager webhook → LangGraph 決定性蒐證 → runbook RAG → grounded 事件報告；數字/時間戳零 LLM 生成）

> **上游**：[brief 正本](2026-07-10-ai-ops-incident-narrator-brief.md)（工作合約）＋ repo `CLAUDE.md`「Fable 5 design 精確度契約（8 條）」（自檢見 §12）＋ [觀測性強化 design](2026-07-10-observability-hardening-design.md)（資料源/觸發源正本，**唯讀複用不改寫**：§6 Alertmanager Discord、§2 Loki、§3 SLO、§8.2 wave 17/18）＋ [P2 ML verticals design](2026-07-08-P2-ml-verticals-design.md)（LLM 棧正本：§8 LLMClient/接線、§10 LLMOps 範式，唯讀複用）＋ [問 AI design](2026-07-10-ask-ai-design.md)（反幻覺 pattern 正本：§4.2 `check_numbers` 純函式、§0.3 無實碼誠實鎖合約先例）＋ [NORTH_STAR](../architecture/NORTH_STAR.md)（一工一具/拓撲鐵律/M4 原則 binding）。
> **緣起與參考立場（Fergus 明示）**：取材 hiskio「Prometheus 智能維運：DeepSeek+Dify」課程的**應用範式與 prompt/workflow 結構**；**棄 Dify（LangGraph 取代）、棄 DeepSeek（P2b LLMClient Ollama/Gemini 取代）**。課程原專案唯讀不改、碼不照抄、憑證勿引。
> **一句話**：Alertmanager 告警 fire → webhook 進 `ml/aiops/` LangGraph 服務 → **決定性蒐證**（PromQL 近況＋相關指標＋Loki error log＋告警 labels 解析，全程式取、結構化成 fact set）→ runbook 直取＋pgvector 補撈 → LLM 只產根因假設＋處置建議 → **`check_timestamps`＋`check_numbers` 雙純函式驗證**（fail 帶清單重試一次，仍 fail 誠實標警示 badge）→ 落表 `ml.ops_incidents`＋選配 Discord 加值卡片＋前端 `/architecture` 策展樣本。次觸發＝Airflow 每日值班摘要（課程路線 B 範式、無 Dify）。**本 spec 最重要正確性面＝反幻覺：數字/百分比/時間戳一律程式取自 PromQL/Loki/告警，LLM 敘事零數字生成、時間戳全程式注入**——比課程嚴謹（課程 6/7 份報告幻覺編造 `2023-10-27（假設）` 時間戳，§0.2 第一手證據）。
> **產出日期**：2026-07-10。**本階段只出 spec，plan 延後**；不 commit（規劃者把關後處理）。

---

## 0. 接地現況（第一手 grep/讀，file:line 錨）

### 0.1 A 組——平台既有資產（本 design 接線其上、一條不改）

| 錨點 | 現況（第一手核對） | 本 design 的關係 |
|---|---|---|
| 觀測性 design §6（:280-289） | Alertmanager 通知閉環＝**AlertmanagerConfig CRD**（`monitoring.coreos.com/v1alpha1`）route `severity =~ "critical\|warning"` → receiver `discord`（原生 `discord_configs`，secret `alertmanager-discord`）；`group_by: [alertname]`、`repeat_interval: 12h`；info 不推；selector 放開＝其 §8.3 additive values | 本 spec **additive 加第二個 AlertmanagerConfig**（webhook receiver 打本服務）；**Discord route 零改**。context7 已證 operator 對 first-level route **強制 `continue: true`**（§0.4）→ 兩個 CRD 並收不互搶，additive 在機制上成立 |
| 觀測性 design §0.1/§3.2/§3.3/§8.4 | 既有告警全集（本 spec 的輸入面）：P1 `YTDataStale`(warn>3h/crit>6h)/`YTPipelineTaskFailures`/`LakehouseComponentDown`；P2 `MLFeatureDriftHigh`/`MLModelQualityDegraded`(crit)/`MLStagingCandidateReady`(info)/`RAGDegradedRateHigh`(warn)/`MLServingDown`(crit)/`RAGCostBudget`(warn)；P3 `PttDataStale` 等五條；P6 `FlinkCheckpointFailing`/`FlinkJobRestarting`；觀測性新增 `TempoDown`/`LokiDown`(warn)/`PipelineHealthDegraded`(warn)/`PipelineHealthCritical`(crit)/`LiveEndpointDown`(warn)/`LiveEndpointCertExpiry`(info)/`<Name>SLOFastBurn`(crit)/`<Name>SLOSlowBurn`(warn) | §2 觸發政策與 §3 蒐證模板對照表的第一手素材；**告警規則本體零改**（過濾在 route matcher＋服務端 config，不動 PrometheusRule） |
| 觀測性 design §0.1（P1 :434）/§4.4/§3.3 | PromQL 指標名（蒐證查詢源）：`yt_freshness_seconds`/`yt_silver_rows_24h{region}`/`yt_gold_mart_rows{mart}`/`ml_feature_psi{model,feature}`/`ml_rolling_auc{model}`/`http_requests_total{handler,method,status}`/`rag_requests_total{provider,outcome}`/`rag_request_duration_seconds`/`rag_cost_usd_total{provider}`/`dq_pipeline_health_status{pipeline}`/`dq_healed_rate`/`dq_quarantine_rate`/`probe_success`/`probe_duration_seconds`/`slo:<name>:error_budget_remaining`/`sli:<name>:ratio_rate*`/`up` | §3 蒐證模板逐條引用；本 spec 不新增指標系統，只以 Prometheus HTTP API 查（§0.4） |
| 觀測性 design §2.2/§2.3 | Loki 單 binary `loki.observability.svc:3100`；**index label 只 `namespace/pod/container/app/job` 五個**，`service`/`level`/`trace_id` 由 LogQL `\| json` 動態抽；structlog 頂層欄位 schema §2.1 | §3 log 蒐證 LogQL 全依此紀律寫（`{namespace="ml"} \| json \| level="error"`）；不假設不存在的 label |
| P2 design §8（:363-368、:7） | **LLMClient 合約（LLM 棧正本）**：預設 **Ollama `qwen3.5:9b`**（:7「RAG 生成 `qwen3:8b`→`qwen3.5:9b`」；:367 明文）／fallback **Gemini `gemini-2.5-flash`**；自動切換＝Ollama 連線錯誤/逾時 30s；手動 `provider` 參數；`provider` 欄如實回報；k8s→host＝ExternalName `ollama-host.ml.svc`→`host.docker.internal`、env `OLLAMA_BASE_URL`；`GEMINI_API_KEY` 無預設值 fail-fast（P2 §10） | §6 換 provider 的全部依據。**model pin 對齊**：本 spec **不自定 pin**，符號引用「LLMClient default」＝P2 §8 合約值 `qwen3.5:9b`（ask-ai §0.1/crosscut 舊標 `qwen3:8b` 屬文件漂移，本 spec 唯讀不改寫它們；報告 `model` 欄 runtime 如實回報不寫死）。**實碼現況**：`ml/rag/service/src/rag_service/llm.py` 今日不存在（`ml/` 零 `.py`、`docs/plans/` 空，第一手 `find` 核對）→ 依 brief 指示**鎖 P2 design §8 合約**，同 ask-ai §0.3 誠實處理先例；plan 期實查 #1 對實碼核簽名 |
| ask-ai design §0.3 | LLMClient 消費窄介面（該 spec 已鎖）：`complete(prompt, *, provider=None, temperature, json_schema=None) -> {text, provider, model, token_usage{prompt,completion}, latency_ms}`；「LLM provider-switch 呼叫層全 repo 單一真源，禁止第二份實作」＝硬合約 | 本 spec 同吃同一窄介面（thin re-export，零第二份 provider 切換邏輯）；plan 序在 P2b plan 之後 |
| ask-ai design §4.2（:245-252） | **`check_numbers(answer, fact_numbers) -> {checked, verified, unverified[]}` 純函式**：①事實數字集＝遞迴收集 tool_results 數值葉，每值展開等價形（原值/round 0-2 位/×100 ÷100）②答案數字抽取 `\d+(?:,\d{3})*(?:\.\d+)?%?`（百分比雙形比對）③豁免集顯式列舉＝整數 0–10、年份 2020/2021、月份形 token④匹配＝字串等價或容差 `\|a−b\| ≤ max(0.005, 0.5%×\|b\|)`⑤政策＝`unverified` 非空即 fail→重試一次→仍 fail 不入 showcase／live 標警示 badge；synthesis prompt 硬性「數字逐字取自工具結果不得推算」（:252） | §4 全結構複用：fact_numbers＝fact set 數值葉；**vendor＋CI 位元組 diff 共用單一真源、不改本體**（沿 crosscut 決策 7）；本 spec 的時間戳加嚴走**新增純函式 `check_timestamps`**（aiops 自有，不動 check_numbers 豁免集——§4.3） |
| P2 design §10/§14 | LLMOps 範式：MLflow Prompt Registry `@prod` alias＋晉升閘 make target；`rag_*` 指標族命名法＋成本單價常數表；LangGraph 圖測試＝fake LLM/fake retriever 注入；secret 紀律測試（缺 env raise 非預設值） | §6/§7/§9 同構複製為 `aiops_*`；CI 測試面照抄範式 |
| 觀測性 design §8.2 | ArgoCD sync-wave 已用至 **17/18** | 本 spec 取 **wave 19**（§9.2） |
| 觀測性 design §7.1/§7.4、P5 design §3/§4 | `/architecture` bento additive 慣例（無新頁無新 entryId、registry 條目內容 additive 擴寫、lucide 禁 emoji）；架構圖已 5 張（第 5 張 observability.md）；截圖清單已用至 #12；DECISIONS.md ADR-lite 已用至 #20 | §8 前端策展沿同慣例；架構圖 additive 第 **6** 張、截圖 **#13–#14**、ADR-lite **#21–#24** |

### 0.2 B 組——課程唯讀取材（第一手讀；碼不照抄、憑證勿引、原專案不改）

| 素材 | 第一手核對內容 | 取 vs 不取 |
|---|---|---|
| 路線 A `prometheus/alert_handler.py` | Flask `POST /alert` 收 Alertmanager webhook → 抽 `labels.alertname/severity`、`annotations.description`、`startsAt` → system prompt「資深運維與安全分析師」＋四段報告結構（基本資訊/原因分析/處置建議/預防措施）→ DeepSeek chat → 存 txt 報告。**bug 實錨**：`handle_alert()` 只取 `alert_data["alerts"][0]`（「提取第一个触发的告警」）——同組多告警全被丟棄 | **取**：webhook→解析→LLM→落報告的骨架；四段報告結構（§5 沿用但畫清程式/LLM 段落所有權）；system prompt 角色設定方向。**不取**：DeepSeek/OpenAI SDK、Flask（我方 FastAPI＋LangGraph）、txt 落檔（我方落表）、**只讀第一筆告警的 bug**（§2 逐筆處理＋單測守門）、憑證進 `.env` 樣板的姿態 |
| 路線 A `alert_rules.yml` | PromQL 比率告警範式（`sum(rate(...{login_status="failed"}[1m]))/sum(rate(...[1m])) > 0.15`，for/severity/annotations 帶 `{{ $value \| humanizePercentage }}`） | **對照確認不降級**：我方 P0–P6 告警與 SLO burn-rate 已更成熟；annotations 內插值＝告警自帶數字（fact set 的告警數值來源之一，§3.1） |
| 路線 B `dify/inspector.sh` | 取數邏輯：curl `PROM_URL/api/v1/query?query=user_login_total` → jq 加總/按 label 過濾 → **程式組出自然語言事實句**（`總登录次数: N，登录成功: X，登录失败: Y`）→ 餵 Dify workflow → 存 JSON 報告 | **取**：「程式查 PromQL→程式算彙總→組結構化事實→LLM 只拿事實敘事」的取數範式（§3 蒐證層＝其工程化版）＋排程巡檢概念（§2.2 值班摘要，Airflow 取代 crontab+Dify）。**不取**：Dify workflow API、shell 拼 JSON（注入面）、API key 明碼寫在腳本第 4 行（反例，我方 secret 全 k8s Secret） |
| 路線 B `dify/Prometheus应用巡检.yml` code 節點 | **規則式 5 級分級→固定 SOP**：Python 純函式算 `anomaly_rate`，≤2%/≤5%/≤10%/≤20%/>20% 五檔各配固定處置建議文字——「**程式判定、LLM 敘事**」的具體落法；LLM 節點 prompt 只做潤稿彙整 | **取**：判定歸程式的原則（我方：severity/分級全來自告警 label 與既有 rules；digest 健康分級直讀 `dq_pipeline_health_status`/SLO budget 既有程式值，LLM 零判定權——§2.2/§5）。**不取**：Dify code 節點形式；固定 SOP 硬編碼在 workflow（我方 SOP 進 `docs/runbooks/` 版本化＋RAG 引用出處） |
| `dify/report/inspector_*.json`（7 份實跑報告） | **幻覺實錨（第一手 grep）**：6/7 份報告出現 LLM 編造時間戳——`2023-10-27 18:00`、`2023-10-27 13:00 - 18:00 (假设时间段)`、`2023-10-27 13:00 - 14:30 (根据数据峰值推测)`（實跑日 2025-09；LLM 憑訓練資料編日期還自標「假設/推測」） | **反面教材本體**＝本 spec `check_timestamps` 閘（§4.3）與「時間戳全程式注入、prompt 禁 LLM 書寫任何日期時刻」鐵律的存在理由；此證據句進 ADR-lite #23 與前端敘事 |

### 0.3 C 組——實碼現況

`find ml/ -name "*.py"` 零命中、`docs/plans/` 空（2026-07-10 第一手）→ P2b LLMClient／ask-ai `check_numbers`（`ml/ga_ask/.../guardrails.py`）皆**尚無實碼**，本 spec 全部鎖 design 合約（§0.1 錨），plan 期實查 #1/#2 對落地實碼核對。此為 ask-ai §0.3 同款誠實處理。

### 0.4 D 組——context7 查證（版本敏感處；查證日 2026-07-10）

| 套件 | 查到的關鍵 API/現況（本 design 據此拍板） |
|---|---|
| LangGraph（`/websites/langchain_oss_python_langgraph`；版本沿 P2 §0 pin `langgraph 1.2.8` 不重議） | `StateGraph(State)`＋`add_node`/`add_edge(START,…)`/`add_conditional_edges(node, fn, [targets])`＋`compile()`；state＝TypedDict、累加欄 `Annotated[list, operator.add]`；條件邊函式回傳目標節點名——§5 graph 的線性＋單迴圈形狀全在正典 API 內，無需 Send fan-out |
| Prometheus HTTP API（`/websites/prometheus_io`） | `GET/POST /api/v1/query`（params `query`,`time`,`timeout`,`limit`）；`GET/POST /api/v1/query_range`（params `query`,`start`,`end`,`step` 必填＋`timeout`/`limit`）；回應 `{status, data:{resultType: "vector"\|"matrix", result:[{metric:{...}, value:[ts,"v"] \| values:[[ts,"v"],…]}]}}`——樣本值是**字串**，蒐證層 `float()` 轉型後算彙總（§3.2） |
| Alertmanager webhook payload（`/prometheus/alertmanager`） | `{version:"4", groupKey, truncatedAlerts, status:"firing"\|"resolved", receiver, groupLabels, commonLabels, commonAnnotations, externalURL, alerts:[{status, labels, annotations, startsAt:"<rfc3339>", endsAt, generatorURL, fingerprint}]}`——§3.1 解析合約；`fingerprint`＋`startsAt`＝去重鍵（§5.4） |
| AlertmanagerConfig CRD（`/prometheus-operator/prometheus-operator`） | `spec.receivers[].webhookConfigs`：`url` 或 `urlSecret`（SecretKeySelector，**須與 CRD 同 namespace**）擇一、`sendResolved`、`maxAlerts`、`timeout`；`spec.route`：matchers/groupBy/groupWait/repeatInterval，**operator 對 first-level route 強制 `continue: true` 且自動加 `namespace: <CRD namespace>` matcher**；matcher 作用域由 `alertmanagerConfigMatcherStrategy`（預設 `OnNamespace`）控制——§2.3 路由與 §10 實查 #4 的依據 |
| Loki LogQL API（`/grafana/loki`） | `GET /loki/api/v1/query_range`（params `query`,`start`,`end`（ns epoch）,`limit`（預設 100，僅 stream）,`direction`（預設 backward）,`since`）；回應 `{status, data:{resultType:"streams"\|"matrix", result:[{stream:{labels}, values:[[ns_ts,"line"],…]}]}}`；LogQL 疊法 `{app="foo"} \|= "error" \| json \| level="error"`——§3.3 log 蒐證合約 |

---

## 1. 八項拍板總表（brief〈要收斂拍板的項目〉逐項；細節在各節）

| # | 項 | 拍板 |
|---|---|---|
| 1 | 觸發模式 | **主＝告警觸發**（webhook，critical＋warning、info 不觸發、服務端 denylist＋rate-limit 控噪）；**次＝排程值班摘要 v1 就做**（Airflow `@daily`，非 Dify cron）；與 Discord 告警分工明標（§2） |
| 2 | 蒐證層 | 決定性三源（告警解析＋PromQL 模板查詢＋Loki error log）→ **fact set schema 欄位級拍板**＋「告警→蒐證模板」對照表（§3） |
| 3 | LangGraph graph | 7 節點線性＋單一驗證重試迴圈：`parse_alert→gather_evidence→retrieve_runbook→narrate→verify→(retry≤1)→persist→notify`；FastAPI k8s Deployment、ingress `aiops.localtest.me`（本地域）（§5） |
| 4 | 反幻覺 | `check_numbers` vendor 複用不改本體＋**新增 `check_timestamps` 純函式**（LLM 敘事禁任何日期/時刻 token，直接針對課程幻覺型態）；時間戳全程式注入；`unverified` 非空→重試一次→仍 fail 落表帶警示 badge 誠實發布（§4） |
| 5 | RAG runbook | **做**：`docs/runbooks/` 自寫 SOP（每告警族一份）→ 新表 `ml.ops_runbook_documents`（pgvector，同基建不同語料）；檢索＝**alertname 決定性直取為主＋hybrid 向量補撈 top-2 為輔**（§5.2） |
| 6 | 換 provider | 複用 P2b LLMClient 窄介面（Ollama `qwen3.5:9b` default/Gemini fallback，合約引用不自定 pin）；`aiops_*` 指標族；prompt 進 MLflow registry（§6） |
| 7 | 報告產出 | 落表 `ml.ops_incidents`（DDL §7.1）＋選配 Discord 加值卡片（env 未設＝no-op）＋前端 `/architecture` additive bento＋靜態樣本 dataset（§7/§8） |
| 8 | 部署/守門/交付 | `ml/aiops/`、AlertmanagerConfig additive receiver、wave 19、CI（fake 注入圖測試/雙純函式單測/webhook 多告警守門/secret 紀律）、截圖 #13–#14、ADR-lite #21–#24（§9） |

---

## 2. 觸發模式（拍板項 1）

### 2.1 主觸發：告警 webhook（課程路線 A 範式，工程化）

- **哪些告警觸發敘事**：route matcher 收 `severity =~ "critical|warning"`（與 Discord route 同集合；**info 不觸發**——`MLStagingCandidateReady`/`LiveEndpointCertExpiry` 這類提示無事件敘事價值）。**服務端二層過濾**（config `ml/aiops/config/narrate.yaml`，git 版本化）：
  - **denylist**：`Watchdog`、`InfoInhibitor` 等 kube-prometheus-stack 心跳/元告警＋日後認定的噪音告警（列名單而非改 rules——**PrometheusRule 零改**）。
  - **rate-limit**：同 `alertname` 60 分鐘內只敘事一次（後續重送記 `deduped`，防 Alertmanager `repeat_interval` 重送與 flapping 燒 LLM 呼叫；去重鍵見 §5.4）。
- **與既有 Discord 告警的分工（合約句，進 ADR-lite #24）**：觀測性 §6 Discord route＝「**哪個告警響了**」（原始告警卡，秒級送達，零 LLM）；本 spec＝「**這個告警發生了什麼、可能為何、怎麼處理**」（加值敘事層，分鐘級，經蒐證與驗證）。兩者並存不取代——同 cause/symptom 兩層告警並存的 SRE 正統（觀測性 §3.3 同款論證）。narrator 死掉不影響原告警送達（fail-safe 分層）。
- **課程 bug 矯正**：payload `alerts[]` **逐筆處理**（每筆一份 incident，按 fingerprint 去重）——`alert_handler.py` 只讀 `alerts[0]` 的 bug 以單測守門（§9.4）。

### 2.2 次觸發：排程值班摘要（課程路線 B 範式；拍板 v1 就做）

- **理由**：①路線 A＋B 統一進同一條 graph（同蒐證/敘事/驗證鏈，差別只在觸發源與 fact set 內容）＝「一套機制兩種應用」的作品集講點；②成本＝每日 1 次 LLM 呼叫（零頭）；③排程走**既有 Airflow**（一工一具——不引 Dify cron/crontab；課程 route B 的 crontab+Dify 被 Airflow DAG 取代）。
- **形狀**：DAG `aiops_daily_digest`（`@daily`，PythonOperator 打 `POST http://aiops.ml.svc:8000/digest`）。digest fact set＝程式查：4 條 SLO `slo:*:error_budget_remaining` 現值、`dq_pipeline_health_status{pipeline}` 分級、`yt_freshness_seconds`/`ptt` freshness、當前 firing 告警數（`ALERTS{alertstate="firing"}`）、昨日 incidents 數（自表查）。**分級判定零 LLM**（直讀既有程式值——課程 code 節點「程式判定」原則的落地）；LLM 只把程式算好的事實寫成值班摘要敘事。落表 `trigger='digest'`、`fingerprint='digest:<YYYY-MM-DD>'`。
- 進化方向（v1 不做）：週報聚合、SLO 燒錄趨勢敘事。

### 2.3 Alertmanager 接線（additive，觀測性 §6 零改）

新 AlertmanagerConfig（`ml/aiops/k8s/alertmanagerconfig.yaml`，namespace `ml`）：

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: AlertmanagerConfig
metadata: {name: aiops-narrator, namespace: ml}
spec:
  route:
    receiver: aiops-webhook
    matchers: [{name: severity, matchType: =~, value: "critical|warning"}]
    groupBy: [alertname]
    groupWait: 30s
    repeatInterval: 4h        # 比 Discord 的 12h 短：narrator 曾漏接時靠重送補敘（§5.4 去重保證不重敘）
  receivers:
  - name: aiops-webhook
    webhookConfigs:
    - url: http://aiops.ml.svc:8000/webhook
      sendResolved: true      # resolved 只更新 resolved_at，不再敘事（§5.4）
      maxAlerts: 0
```

- operator 對 first-level route 強制 `continue: true`（context7 已證，§0.4）→ **Discord receiver 照常收，additive 成立**。
- **namespace matcher 縫（誠實標）**：預設 `alertmanagerConfigMatcherStrategy=OnNamespace` 會把本 CRD 限縮到 `namespace="ml"` 的告警——但敘事對象跨 namespace。**觀測性 §6 的 Discord CRD 有完全相同的縫**（其 plan 實查 #5 涵蓋）。拍板：**與觀測性 plan 同解**——預設傾向 P0 monitoring values additive 一行 `alertmanagerConfigMatcherStrategy: {type: None}`（觀測性 §8.3 同檔同性質 additive；一個設定同時解兩個 receiver）；判準＝跨 namespace 測試告警（`amtool alert add`）同時到 Discord 與本 webhook。列 plan 實查 #4，不阻擋收斂。
- webhook URL 用叢集內 Service DNS 明碼 `url`（非 secret——內網位址無機密性；`urlSecret` 留給帶 token 的外部 webhook，本案不是）。

---

## 3. 決定性蒐證層（拍板項 2；反幻覺的地基）

### 3.1 三證據源與 fact set schema（欄位級合約；全程式產生，供 LLM 敘事與驗證比對）

```jsonc
{
  "alert": {                            // 源 1：webhook payload 解析（§0.4 schema）
    "alertname": "MLServingDown", "severity": "critical", "status": "firing",
    "starts_at": "<rfc3339，取自 payload>", "fingerprint": "<hex>",
    "labels": {…}, "annotations": {…},  // annotations 內插的數字（如「失敗率 22.94%」）天然入事實集
    "generator_url": "<str>"
  },
  "metrics": [                          // 源 2：PromQL（模板驅動，§3.2）
    { "name": "up{job='sentiment-predictor'}", "promql": "<實際查詢>", "kind": "range|instant",
      "window_minutes": 30, "step_seconds": 60,
      "samples": [[1760073600, 1.0], …],          // query_range values，float() 轉型
      "summary": {"latest": 0.0, "min": 0.0, "max": 1.0, "avg": 0.42, "count": 30}  // 程式算
    }, …
  ],
  "logs": {                             // 源 3：Loki（§3.3）
    "logql": "{namespace=\"ml\"} |= \"error\" | json | level=\"error\"",
    "window_minutes": 30, "total_lines": 87, "error_lines": 87,
    "top_patterns": [ {"pattern": "connection refused to ollama-host…", "count": 41}, … ],  // 程式正規化聚類（去數字/hex 後分組計數）
    "samples": [ {"ts": "<rfc3339>", "line": "<原文，截 500 字元>"}, … ]   // ≤10 行
  },
  "meta": {                             // 全程式注入——時間戳唯一合法來源
    "collected_at": "<rfc3339 UTC，datetime.now(timezone.utc)>",
    "evidence_window_minutes": 30,
    "prometheus_status": "ok|error:<msg>", "loki_status": "ok|error:<msg>"   // 蒐證部分失敗＝如實記錄照樣敘事（graceful，不假造）
  }
}
```

- **合約句**：fact set 是報告中一切數字/時間戳的**唯一來源**；`check_numbers` 的 `fact_numbers`＝本結構全數值葉遞迴收集（ask-ai §4.2 演算法同款）。蒐證某源失敗＝該源留空＋`meta.*_status` 記錯誤，LLM prompt 如實告知「log 證據不可用」——**不得以任何佔位數字填充**。
- 體積控：`samples` 指標每條 ≤60 點（30m/30s）、log ≤10 行各 ≤500 字元；`fact_set` jsonb 落表全量、餵 LLM 的 digest 版另行渲染（§5.3）。

### 3.2 PromQL 蒐證模板（「告警→查什麼」對照表＝config `ml/aiops/config/evidence_templates.yaml`，git 版本化；查詢打 `http://kube-prom-stack-prometheus.monitoring.svc:9090/api/v1/query_range`，Service 名 plan 實查 #5 對 P0 chart 釋出名核對）

| alertname（族） | 觸發指標近況（range 30m/60s） | 語意相關指標（同拉） |
|---|---|---|
| `MLServingDown` | `up{job=~".*predictor.*"}` | `kube_pod_container_status_restarts_total{namespace="ml"}`、`http_requests_total{status=~"5.."}` 該 svc、KServe pod error log（§3.3） |
| `RAGDegradedRateHigh` | `rag_requests_total{outcome="degraded"}`/`total` 比率 | `rag_request_duration_seconds`（p95 via `histogram_quantile`）、`rag_requests_total{provider}`（provider 分佈——Ollama 掛了全走 Gemini 是常見根因）、`up{job="rag-service"}` |
| `YTDataStale` | `yt_freshness_seconds` | `yt_silver_rows_24h{region}`、Airflow statsd task failure 計數、`LakehouseComponentDown` 同族 `up` |
| `PttDataStale` | `ptt` freshness 指標（P3 §10 名） | Kafka consumer lag 指標、consumer pod 重啟數 |
| `PipelineHealthDegraded/Critical` | `dq_pipeline_health_status{pipeline}` | `dq_healed_rate`/`dq_quarantine_rate`、該 pipeline 最近 run 的 heal by_error_type（DB 查 `dq.dq_heal_log` 最新列——蒐證層唯一的 SQL 源，唯讀） |
| `<Name>SLOFastBurn/SlowBurn` | `slo:<name>:error_budget_remaining`＋burn rate 多窗 | 對應 SLI 原始序列（S1→freshness/S2→5xx 比率/S3→degraded 比率/S4→延遲桶） |
| `LiveEndpointDown` | `probe_success{instance=~".*<target>.*"}` | `probe_duration_seconds`（冷啟 vs 真死）、cert expiry |
| `FlinkCheckpointFailing/JobRestarting` | 對應 Flink 指標（P6 §9 名） | JM/TM `up`、restart 計數 |
| `TempoDown`/`LokiDown`/`LakehouseComponentDown` | `up{job=…}` | 該 namespace pod 重啟數＋error log |
| **generic fallback（無模板的告警）** | 由告警 labels 推導：`up{job=~".*<labels.job>.*"}`（有 job label 時）＋`ALERTS{alertname="<name>"}` 序列 | 該 `labels.namespace` 的 error log——**機制保證新告警不漏敘**，模板是加值非門檻 |

模板檔語法（每條）：`{alertname_pattern, queries: [{name, promql(可帶 {{label}} 內插自告警 labels), kind, window_minutes}], logql: {...}}`。**內插只允許告警 labels 值且經字元白名單（`[A-Za-z0-9_.:-]`）**——防 LogQL/PromQL 注入（label 值來自我方 rules 理論可信，仍縱深防禦）。

### 3.3 Loki log 蒐證

- 端點 `http://loki.observability.svc:3100/loki/api/v1/query_range`（params：query/start/end ns epoch/`limit=200`/`direction=backward`——context7 §0.4）。
- 預設查詢（模板可覆寫）：`{namespace="<告警 namespace>"} |= "error" | json | level="error"`——先 line-filter 縮量再 json parse（Loki 官方查詢優化順序，§0.4 範例同款）；非 JSON 行（第三方元件）降級 `{namespace="…"} |= "error"` raw 查。
- 程式彙總：`total_lines`/`top_patterns`（行文本去數字/hex/uuid 正規化後分組計數 top 5，純函式可測）/`samples` head 10。**這些統計值全入 fact set**（LLM 引用時受驗證）。

---

## 4. 反幻覺落地（拍板項 4；本 spec 最重要正確性面）

### 4.1 職責鐵律（合約句）

**數字/百分比/時間戳一律程式取自 fact set（PromQL/Loki/告警/DB），LLM 只產根因假設與處置建議敘事**；報告的「告警基本資訊」「證據摘要」兩段＝**程式模板渲染**（Jinja 級字串模板，零 LLM——課程四段報告裡課程讓 LLM 寫全部四段，我方把前兩段收回程式，§5.3）。時間戳（`starts_at`/`collected_at`/`generated_at`/樣本 ts）**全部程式注入**，LLM prompt 硬性禁令（§6.2）。

### 4.2 `check_numbers` 複用（vendor＋diff，不改本體）

- 來源＝ask-ai §4.2 純函式（合約 §0.1 錨；實碼落地後 vendor 自 `ml/ga_ask/.../guardrails.py`，位元組 diff CI 守門沿 crosscut 決策 7——**豁免集/容差/政策一字不改**）。
- 本 spec 的接法：`fact_numbers = collect_numeric_leaves(fact_set)`（遞迴，同 ask-ai 演算法）；驗證對象＝**LLM 產出的敘事欄位**（`narrative.summary`/`root_cause_hypotheses[].text`/`remediation_steps[].text`）串接文本；程式模板渲染的段落不驗（其數字本來就是 fact set 直出）。

### 4.3 `check_timestamps` 加嚴純函式（aiops 自有新增；針對課程幻覺型態）

- **為什麼不夠只靠 check_numbers**：其豁免集含年份 2020/2021 與月份形 token（ask-ai 語境正確——GA 資料窗真有這些年份）；而課程反面教材的幻覺正是**日期時間**（`2023-10-27 13:00 - 18:00 (假设时间段)`，§0.2 第一手）。改 check_numbers 豁免集＝改本體，違 vendor 單一真源——故**另立更嚴的前置閘**。
- `check_timestamps(narrative_text) -> {found: [token, …]}` 純函式：regex 偵測日期形（`\d{4}[-/年]\d{1,2}[-/月]\d{1,2}`、`\d{1,2}:\d{2}(:\d{2})?`、rfc3339 形、相對時間宣稱如「X 小時前」`\d+\s*(小時|分鐘|天)前`）；**`found` 非空即 fail**——LLM 敘事段被禁止書寫任何日期/時刻（時間資訊由程式段落全權呈現），零白名單零豁免。政策同 check_numbers：fail → 帶 found 清單重試一次（§5.1）→ 仍 fail → 落表 `verification.passed=false`＋報告渲染警示 badge「以下敘事含未經查證的時間表述」＋該 incident **不入前端策展樣本**（§8）。
- 單測表（§9.4）至少：課程實錨六型（`2023-10-27 18:00`/區間/「(假設)」尾註/相對時間/純時刻/rfc3339）正例＋「30 分鐘視窗」這類**視窗長度描述不誤殺**的反例（視窗長度是 fact set 的 `window_minutes` 數值，歸 check_numbers 管）。

### 4.4 執行順序與政策

`verify` 節點：①`check_timestamps`（嚴，先跑）②`check_numbers`——任一 fail → `retry<1` 時帶違規清單回 `narrate` 重試一次（prompt 附「以下 token 未經查證，重寫並移除」）；重試後仍 fail → **誠實發布**：落表 `verification`（含兩檢結果全量）、Discord 卡片與前端渲染警示 badge、`aiops_incidents_total{outcome="verify_failed"}` 計數——**不擋落表**（維運報告遲到/殘缺比消失好；但策展樣本零容忍，§8）。「數字零幻覺」是可測斷言：eval 閘（§6.3）hard 要求 fixture 全集 verify pass。

---

## 5. LangGraph graph 與服務形（拍板項 3）

### 5.1 graph（LangGraph 1.2.8 StateGraph；agentic 判斷只保留在敘事層）

```
START → parse_alert → gather_evidence → retrieve_runbook → narrate → verify ─(pass 或 retry 用盡)→ persist → notify → END
                                                              ↑            │
                                                              └─(fail & retry<1，帶違規清單)┘
```

| 節點 | 決定性？ | 內容 |
|---|---|---|
| `parse_alert` | ✅ 純程式 | webhook payload 逐 alert 解析（§0.4 schema）；denylist/rate-limit/去重判定（skip 者記 outcome 直接 END）；digest 觸發時改為組 digest 事實框 |
| `gather_evidence` | ✅ 純程式 | §3 三源蒐證→fact set；Prometheus/Loki client＝`httpx`（同 P2b 生態；30s timeout，單源失敗記 status 續跑） |
| `retrieve_runbook` | ✅ 決定性直取＋向量輔助 | §5.2 |
| `narrate` | 🤖 **唯一 LLM 節點** | LLMClient `complete(prompt, json_schema=NARRATIVE_SCHEMA)`（§6）→ `{summary, root_cause_hypotheses:[{text, likelihood:'high'\|'medium'\|'low'}], remediation_steps:[{text, runbook_ref}], impact_note}`；likelihood 是 LLM 的假設定性詞非數字（明標「假設」語意——LLM 可以推理因果、不可以生產數值） |
| `verify` | ✅ 純函式 | §4.4 雙檢＋重試判定 |
| `persist` | ✅ 純程式 | 落 `ml.ops_incidents`（§7.1）；`generated_at`/報告渲染時間戳程式注入 |
| `notify` | ✅ 純程式 | 選配 Discord（§7.2）；env 未設＝no-op |

State（TypedDict）：`alert, fact_set, runbook_docs, narrative, verification, retry:int, outcome, provider, model, token_usage, latency_ms, prompt_versions, trace:Annotated[list, operator.add]`（trace＝逐節點事件，落表供前端展開——ask-ai TraceStep 同構瘦身版）。**重試上限 1**（沿 ask-ai `MAX_OUTPUT_RETRY=1`）。

### 5.2 runbook RAG（拍板項 5：做；同基建、不同語料、與 P2b/搜尋語料互不相通）

- **語料**：`docs/runbooks/*.md` 自寫 SOP（**誠實標：自寫 runbook 非真值班紀錄**——README 與前端敘事同句）。每告警族一份（§3.2 表的族 ≈14 份起）＋橫切篇（ollama-host 接線排障/ArgoCD sync 排障/kind 叢集重建）。格式：frontmatter `alertnames: […]`＋分節（症狀/檢查步驟/處置/升級判準）。
- **表**：`ml.ops_runbook_documents(doc_id text PK, alertnames text[], title text, section text, content text, embedding vector(384), fts tsvector, updated_at timestamptz)`——**net-new 表**，embedding 沿 P2b e5-small（384 維、`passage:` 前綴、pgvector HNSW cosine——P2b 慣例同款）；`rag_documents`（P2b YouTube 語料）**零觸碰**。
- **索引**：`make aiops-index-runbooks`（host 跑，語料 ~數十 chunk、e5-small CPU 秒級；runbook 改動後重跑，冪等 UPSERT by doc_id）。
- **檢索拍板**：**alertname 直取為主**（`alertnames @> ARRAY[<name>]`——告警→runbook 對應是決定性映射，不該讓向量檢索有取錯空間）＋**hybrid 向量補撈 top-2 為輔**（query＝alertname＋annotations.summary → 向量+FTS RRF（P2b `retrieval.py` 範式同款 SQL）撈**其他** runbook——價值在跨告警關聯：`RAGDegradedRateHigh` 的證據顯示 Ollama 連線錯誤時補撈 ollama-host 接線篇）。generic fallback 告警（無直取命中）全靠 hybrid。`runbook_sources` 記 `match:'direct'|'vector'` 出處。
- **為什麼不是「v1 先不做 RAG」**：處置建議沒有出處＝LLM 憑訓練資料泛答（課程報告的處置段就是泛 SRE 常識），有 runbook 引用才有「建議可稽核」的講點；且複用 P2b 檢索基建增量成本一張表＋一支 make target。

### 5.3 prompt 輸入渲染（fact digest）

餵 LLM 的不是 raw fact set，是程式渲染的**事實摘要文本**（inspector.sh「程式組事實句」範式的工程化）：告警四行（名/級/labels 摘要/annotation）＋每條指標一行（`up{job=…}：最新 0，30 分鐘內 avg 0.42（30 點）`）＋log 三行（總量/top pattern×count/樣本 2 行）＋runbook 節選。渲染器是純函式（單測黃金樣本）；**渲染值與 fact set 數值一致性由構造保證**（同源直出）。

### 5.4 冪等/去重/resolved

- 去重鍵＝`UNIQUE(fingerprint, starts_at)`（§7.1）：同一 firing episode 的 repeat 重送→`deduped` 跳過；同 alertname 新 episode（新 startsAt）→ 受 §2.1 rate-limit（60m）節流。
- `status=resolved` webhook → 只 `UPDATE resolved_at`（payload `endsAt` 程式寫入），**不再敘事**（v1；resolved 總結列進化方向）。
- webhook handler：dedupe 判定後 **FastAPI BackgroundTasks 背景跑 graph、立即回 200**（Alertmanager 通知管線不等 LLM 分鐘級延遲）；單 replica 記憶體佇列，crash 掉單則敘事＝known-limit 誠實標（原告警仍在 Discord/Alertmanager；`repeatInterval: 4h` 重送會補敘）。

### 5.5 服務形

FastAPI（`ml/aiops/service/`，沿 P2b `rag_service` 範本）：`POST /webhook`（Alertmanager payload）、`POST /digest`（Airflow 觸發）、`POST /replay`（body＝存檔 fixture payload，demo/測試重放用）、`GET /healthz`（含 Postgres＋Prometheus API 子檢查；Ollama 可達性不入 healthz——LLM 有 fallback 不算硬依賴）、`GET /metrics`。k8s Deployment 1 replica（namespace `ml`——就近吃 `ollama-host.ml.svc` ExternalName 與 `gemini-api` Secret，零新接線）、resources requests `250m/512Mi` limits `500m/1Gi`、ingress **`aiops.localtest.me`**（本地域，供 demo 手動 replay 與看 healthz；拓撲鐵律內——非公網）。OTel/structlog 儀器化沿觀測性 §1.1/§2.1 `libs/obs` vendor 慣例（本服務自己也是被觀測對象——narrator 的 trace 進 Tempo 是 meta 講點）。

---

## 6. LLM 層（拍板項 6：換掉 DeepSeek 的落地）

### 6.1 provider

- **複用 P2b LLMClient 窄介面**（ask-ai §0.3 同款：`from rag_service.llm import LLMClient` local path dep；若 P2b plan 抽成 `ml/llm_core/` 則同步改 import——檔案落點微調，合約不變）。**禁止第二份 provider 切換實作**（合約沿 ask-ai）。
- default＝**LLMClient default（P2 §8 合約：Ollama `qwen3.5:9b`）**、fallback Gemini `gemini-2.5-flash`、逾時 30s 自動切、`provider`/`model` 欄 runtime 如實落表——**本 spec 不寫死任何 model 字串**（config 不出現 model 名；報告顯示的 model 來自 LLMClient 回報）。temperature 0.2（敘事穩定優先）；`json_schema` 結構化輸出（§5.1 NARRATIVE_SCHEMA）。
- webhook 是背景任務、digest 是日批——**延遲不敏感**，qwen3.5:9b 22–28 tok/s（P2 §8 實測量級）完全可用；M4/CPU 友善、無 GPU 假設。

### 6.2 prompt（MLflow Prompt Registry 版本化，P2b §10 同款晉升閘）

- `prompts:/aiops-narrate@prod`：system＝「資深 SRE 事件分析師」（課程 `alert_handler.py` system prompt 的角色設定＋結構化輸出要求取其方向、改我方語境）＋**反幻覺硬性段**：「所有數字必須逐字取自〈事實摘要〉，不得推算、外推或編造任何數字；**不得書寫任何日期、時刻或相對時間**（時間資訊由系統段落呈現）；處置建議必須引用提供的 runbook 節選並附 `runbook_ref`，runbook 未涵蓋時明說『runbook 未涵蓋，以下為一般性建議』；證據不足就說不足，不得假設」。user＝§5.3 fact digest。
- `prompts:/aiops-digest@prod`：值班摘要版（同反幻覺段）。
- 晉升：`make aiops-promote-prompt NAME=… VERSION=n`（先跑 §6.3 eval、達標才掛 `@prod` alias——P2b 閘門模式照抄）。

### 6.3 eval 閘（`make aiops-eval`；MLflow experiment `aiops_eval`）

fixture 集 `ml/aiops/eval/fixtures/`：≥10 組真形狀 webhook payload＋配套錄製 fact set（涵蓋 §3.2 各族＋generic＋單源蒐證失敗案例＋digest）。閘：①**verify 全過**（`check_timestamps` found=0 且 `unverified`=0，**hard**——「數字/時間戳零幻覺」的可測斷言本體）②LLM-judge（Gemini flash temp 0，rubric 版本化）faithfulness ≥3.5 且 actionability ≥3.5（**hard**，閘值沿 P2 §10）③runbook_ref 覆蓋率：有直取 runbook 的案例中 remediation 至少一步帶 ref ≥0.8（warn）。

### 6.4 指標（`aiops_*` 族，沿 `rag_*` 範式；ServiceMonitor 進本 app）

`aiops_incidents_total{trigger=alert|digest, outcome=ok|verify_failed|deduped|skipped|error}`、`aiops_narrate_duration_seconds`（histogram）、`aiops_tokens_total{provider,kind}`、`aiops_cost_usd_total{provider}`（單價常數表沿 llm.py 同源）、`aiops_evidence_queries_total{source=prometheus|loki, outcome}`、`aiops_verify_retries_total`。告警（本 app 自帶 PrometheusRule，net-new）：`AiopsNarratorDown`（`up==0` 10m warn——它死了 Discord 原告警仍在，warning 足矣）、`AiopsVerifyFailRateHigh`（verify_failed/total 24h >0.3 warn——prompt 回歸的信號）。Grafana dashboard `aiops-narrator`（sidecar 新檔）：incidents 時間線、outcome 分佈、token/成本、verify 失敗率、敘事延遲。

---

## 7. 報告產出（拍板項 7）

### 7.1 落表（net-new；沿 P2b「引擎持有 DDL `CREATE TABLE IF NOT EXISTS`」慣例）

```sql
CREATE TABLE ml.ops_incidents (
  id             bigserial PRIMARY KEY,
  fingerprint    text NOT NULL,             -- alert: payload fingerprint；digest: 'digest:<YYYY-MM-DD>'
  starts_at      timestamptz NOT NULL,      -- payload startsAt（程式）；digest=視窗起點
  trigger        text NOT NULL CHECK (trigger IN ('alert','digest')),
  alertname      text NOT NULL,             -- digest='daily_digest'
  severity       text NOT NULL,
  status         text NOT NULL,             -- firing|resolved（resolved 由 §5.4 更新）
  alert_labels   jsonb NOT NULL, alert_annotations jsonb NOT NULL,
  fact_set       jsonb NOT NULL,            -- §3.1 全量
  runbook_sources jsonb NOT NULL,           -- [{doc_id,title,match:'direct'|'vector'}]
  narrative      jsonb NOT NULL,            -- §5.1 NARRATIVE_SCHEMA
  verification   jsonb NOT NULL,            -- {timestamps:{found[]}, numbers:{checked,verified,unverified[]}, retried:int, passed:bool}
  trace          jsonb NOT NULL,            -- 逐節點事件
  provider text NOT NULL, model text NOT NULL,
  token_usage jsonb, latency_ms int, prompt_versions jsonb,
  resolved_at    timestamptz NULL,
  generated_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (fingerprint, starts_at)
);
```

### 7.2 Discord 加值卡片（選配；env `AIOPS_DISCORD_WEBHOOK_URL` 未設＝no-op，沿 obs no-op 慣例）

verify 後推：程式標頭（alertname/severity/starts_at——全程式值）＋ narrative.summary＋根因假設條列＋「詳見 Grafana/DB」尾行；verify_failed 時卡片帶 ⚠ 警示行（lucide 語意，Discord 端用文字 `[UNVERIFIED]` 前綴）。webhook URL 走 k8s Secret `aiops-discord`（命令式建立，沿 P0 §7 紀律；可與 `alertmanager-discord` 同頻道不同 webhook——頻道內「原告警卡」與「敘事卡」相鄰呈現＝分工的可視 demo）。單訊息 2000 字元限制→summary 截斷政策 plan 定。

### 7.3 呈現面

Grafana dashboard（§6.4）＋ DB 查詢＋前端策展（§8）。**不做報告專屬 web UI**（v1；Grafana＋前端樣本已足，避免第二個 UI 面——一工一具在呈現層的體現）。

---

## 8. 前端策展（拍板項 7 後半；拓撲鐵律，零 live 依賴）

- **落點＝`/architecture` additive bento 區塊**（沿觀測性 §7.1 先例：**無新頁、無新 entryId**）：「AI SRE 事件敘事者」卡（lucide `BotMessageSquare`；**emoji 禁用**）＋機制三拍敘事（告警觸發→程式蒐證→LLM 敘事經雙重驗證）＋**策展樣本 Dialog**：3–5 份真實 incident 報告（`verification.passed=true` 者才入選——策展零未驗證數字，同 ask-ai §4.2 政策）逐段渲染（程式段/LLM 段視覺區分＋verify badge＋runbook 出處）。
- **資料**：靜態 dataset `frontend/public/data/aiops_incidents.json`（P4 匯出信封同款；經既有 `export → make export-sync → 人審 commit` 動線 additive +1 檔；`check-data.mjs` 體積斷言天然涵蓋）。**零 live 依賴**——樣本是叢集實跑後策展的快照，誠實文案：「事件報告由本地叢集真實告警觸發產生；本站展示策展樣本與截圖，無 live 敘事端點」。
- **說明式 registry 阻擋級**：`/architecture` 既有條目 `whatItDoes`/`howToRead` additive 擴寫（含「LLM 只敘事、數字時間戳全程式產生」一句——反幻覺紀律本身就是展示內容）；無新 entryId 故 coverage gate 天然通過。
- 誠實標三句（README＋前端同語）：demo 規模＝自產告警觸發、真實但少量事件；runbook 是自寫 SOP 非真值班紀錄；「AI SRE」是能力示範非 24/7 on-call 承諾。

---

## 9. 部署/守門/交付（拍板項 8；全 additive）

### 9.1 檔案落點

```
ml/aiops/
├── pyproject.toml Dockerfile          # langgraph/langchain-core（P2 pin）、fastapi/uvicorn（ask-ai pin）、httpx、
│                                      #   prometheus-client、mlflow-skinny、psycopg；local path dep → rag-service（LLMClient）
├── config/{narrate.yaml, evidence_templates.yaml}
├── service/src/aiops_service/{api.py, graph.py, evidence.py, runbook.py, narrate.py,
│                              verify.py, guardrails_numbers.py(vendored), render.py, metrics.py}
├── service/k8s/                       # deployment+service+ingress(aiops.localtest.me)+servicemonitor
│                                      #   +alertmanagerconfig.yaml(§2.3)+prometheusrule.yaml(§6.4)
│                                      #   +dashboard ConfigMap(sidecar)
├── eval/{fixtures/, run_eval.py, judge prompts}
├── indexer/                           # runbook 索引（make aiops-index-runbooks）
└── tests/
docs/runbooks/*.md                     # §5.2 語料（net-new）
orchestration/airflow/dags/aiops_daily_digest.py
platform/argocd/apps/aiops.yaml        # wave 19
frontend/public/data/aiops_incidents.json（策展後人審 commit）＋ /architecture 區塊
docs/architecture/diagrams/aiops-narrator.md   # additive 第 6 張架構圖
```

### 9.2 ArgoCD：子 App `aiops`（**wave 19**，接續觀測性 17/18；directory→`ml/aiops/service/k8s/`；AlertmanagerConfig/PrometheusRule 帶 `SkipDryRunOnMissingResource=true`，P0 §6 慣例）。服務對 LLM/Discord 零硬依賴（Ollama 掛→Gemini；兩者皆掛→incident 落表 `outcome=error` 帶蒐證事實、無敘事段——蒐證是程式的，不因 LLM 死而丟證據）。

### 9.3 觸碰既有檔案清單（全部 additive；此外零改動）

| 檔 | additive 改動 | 明確不改 |
|---|---|---|
| P0 `monitoring.yaml` values | （若 plan 實查 #4 判定需要）`alertmanagerConfigMatcherStrategy: {type: None}` 一行——與觀測性 §8.3 同檔同性質，且是兩 receiver 共用解 | 觀測性 §6 Discord AlertmanagerConfig、既有全部 PrometheusRule/告警、P2b RAG graph/`rag_documents`/語料表、ask-ai showcase 與 check_numbers 本體、P4 匯出信封機制、Signal token、`output:'export'` |
| `.github/workflows/pr-checks.yaml` | + `guardrails_numbers.py` vendored diff（掛既有 drift job 模式）＋ aiops PrometheusRule `promtool check rules` | 既有 job |
| 匯出動線 | dataset +1（`aiops_incidents.json`） | 既有 datasets |
| frontend `/architecture`＋registry 條目 | §8 區塊與條目內容擴寫 | 其餘頁/schema |
| P5 交付 | 截圖 +2（#13 Grafana `aiops-narrator`＋Discord 敘事卡；#14 前端樣本報告 Dialog）；DECISIONS.md +4（§9.5）；one-pager demo 清單 +1 行（`amtool alert add` → 敘事卡落 Discord 全鏈 demo） | 既有 8+4 張截圖、GIF 仍只 #1 |
| README | known-limit（單 replica 佇列/敘事分鐘級/自寫 runbook）＋secret 邊界 +1（`aiops-discord`） | — |

課程原專案（`course/hiskio/...`）：**唯讀，零觸碰**。

### 9.4 CI/測試（`aiops-ci.yaml`：paths `ml/aiops/**`，ruff+pytest，image `…/aiops-service`，kustomize newTag bump——P0 hello 同款）

- **graph 測試＝fake 注入**（P2 §14 範式）：fake LLMClient＋fake Prometheus/Loki client（回放 §0.4 schema 的錄製 JSON）——斷言：多告警 payload 逐筆處理（**課程 `alerts[0]` bug 的直接守門測試**）、dedupe/rate-limit/denylist 路徑、單源蒐證失敗續跑、verify fail→重試→badge 路徑、resolved 只更新不敘事。
- **純函式單測**：`check_timestamps`（§4.3 正反例表）、vendored `check_numbers`（沿 ask-ai §11#2 六類）、log pattern 正規化聚類、fact digest 渲染黃金樣本、PromQL/LogQL 模板內插白名單（注入字元被拒）。
- **secret 紀律**（P2 §14 同款）：`GEMINI_API_KEY` 缺失 raise 非預設值；repo grep 無任何 API key/webhook URL 明碼（gitleaks 既有 P5 gate 天然涵蓋——課程 `inspector.sh` 明碼 key 反例的守門）。
- prompt 格式測試＋eval 閘（§6.3）host 跑。

### 9.5 ADR-lite（DECISIONS.md additive #21–#24）

21. 棄 Dify：agent 編排收斂 LangGraph 單框架（Dify＝自帶 DB/Redis/向量庫的常駐平台，違一工一具；課程只取應用範式）——§5。
22. 棄 DeepSeek：LLM 收斂 P2b LLMClient（Ollama qwen3.5:9b default/Gemini fallback；換 provider＝合約引用零新棧）——§6。
23. 反幻覺紀律：數字/時間戳全程式取自 PromQL/Loki/告警，LLM 只敘事；`check_numbers` vendor 複用＋`check_timestamps` 加嚴新閘（課程 6/7 份報告幻覺編造 `2023-10-27（假設）` 時間戳＝反面教材實錨）——§4。
24. 告警敘事分工：Discord 原告警卡（什麼響了，秒級）與 AI 敘事卡（為何/怎麼辦，分鐘級、經驗證）兩層並存不取代；narrator 故障不影響原告警——§2。

### 9.6 v1 邊界（明確劃出）

**v1 只敘事＋建議，不自動執行任何修復動作**（無 kubectl/API 寫操作；服務對叢集只讀 Prometheus/Loki/Postgres）。進化方向（列出不做）：帶審批閘的 runbook 動作執行、resolved 事件總結、同時多告警的關聯敘事（group narrative）、fact set 納入 Tempo trace 證據、敘事品質回饋迴路。

---

## 10. plan 期待查證點（皆帶預設傾向與判準；非阻擋收斂）

1. **P2b LLMClient 實碼錨**（P2b plan 落地後）：`rag_service/llm.py` 實際簽名/可無副作用 import/實際 default model 字串——預設＝§0.1 合約（`qwen3.5:9b`）；判準＝`from … import LLMClient` 單測可跑、`model` 欄回報與 Ollama tag 一致。與 ask-ai plan 實查 #1 同一項，共用結論。
2. **check_numbers vendor 來源錨**（ask-ai plan 落地後）：自 `ml/ga_ask/.../guardrails.py` 位元組複製＋diff job 接線；判準＝CI diff 綠。
3. **Alertmanager webhook payload 實測**：`amtool alert add` 打測試告警 → 收到的 payload 對 §0.4 schema 核對（含多 alert 分組行為與 `repeatInterval` 重送去重實測）；判準＝dedupe 後恰一份 incident。
4. **AlertmanagerConfig matcher strategy**：與觀測性 plan 實查 #5 同步解——預設 `alertmanagerConfigMatcherStrategy: {type: None}` additive 一行；判準＝跨 namespace 測試告警同達 Discord＋webhook 兩 receiver。
5. **Prometheus/Loki 叢集內 Service 名**：預設 `kube-prom-stack-prometheus.monitoring.svc:9090`（以 P0 chart 實際釋出名核對）/`loki.observability.svc:3100`（觀測性 §2 已定）；判準＝healthz 子檢查綠。
6. **蒐證模板指標存在性 smoke**：對 §3.2 每條模板跑 `/api/v1/query` 斷言指標名存在（P3/P6 指標名以其 design 落地名核對）；判準＝模板全綠或 generic fallback 接手。
7. **Discord 卡片格式**：2000 字元截斷點與 `[UNVERIFIED]` 呈現——預設 summary ≤800 字元；判準＝手機端卡片完整可讀。
8. **runbook 語料校準**：chunk 尺寸（預設一節一 chunk）、e5-small `passage:` 前綴、直取/向量補撈的實際命中——判準＝eval fixture 的 runbook_ref 覆蓋 ≥0.8。
9. **套件 pin**：langgraph/langchain-core/fastapi/uvicorn/httpx 沿 P2 §0＋ask-ai §0.1 pin；mlflow-skinny 同 P2；判準＝§0.4 API 面不變。

## 11. 本 spec 拍板 vs 下放對照

| 領域 | 本 spec 拍板（不再議） | 下放 plan（機械執行/實查校準） |
|---|---|---|
| 觸發 | 告警觸發主（critical+warning、info 不觸發、denylist+60m rate-limit、逐筆處理）＋digest v1 就做（Airflow @daily）；Discord 分工合約；AlertmanagerConfig 形狀（§2.3 YAML）＋`repeatInterval: 4h` | matcher strategy 實查、denylist 初始名單細目 |
| 蒐證 | fact set schema（§3.1 欄位級）、三源、30m/60s 窗、模板表（§3.2）＋generic fallback、內插白名單、單源失敗續跑不填充 | 模板 YAML 全文、指標存在性 smoke、P3/P6 指標名核對 |
| graph | 7 節點形狀、State 欄、retry=1、BackgroundTasks 回 200、去重鍵/resolved 政策、服務形（ml ns/ingress/資源/healthz 邊界） | 節點實作、trace 欄細目 |
| 反幻覺 | check_numbers vendor 不改本體、`check_timestamps` 新純函式（零豁免）、執行順序、fail 政策（落表帶 badge、策展零容忍）、程式/LLM 段落所有權 | 兩函式單測表全文、regex 細目 |
| runbook | 做 RAG；直取為主＋向量補撈 top-2；`ml.ops_runbook_documents` DDL；語料自寫誠實標；與 P2b 語料互不相通 | runbook 撰稿、chunk/索引參數 |
| LLM | LLMClient 合約引用（不自定 pin、不寫死 model 字串）、temperature 0.2、json_schema 輸出、prompt 反幻覺硬性段方向、eval 三閘（verify hard/judge hard/ref warn） | prompt 全文、fixture 錄製、judge rubric |
| 產出 | `ml.ops_incidents` DDL、Discord 選配 no-op 慣例、不做專屬 web UI、前端 /architecture bento（無新頁無新 entryId）＋dataset +1＋策展只收 verify-pass | 卡片文案、Dialog 版面、截斷政策 |
| 部署/守門 | 檔案落點、wave 19、§9.3 additive 觸碰全集、CI 面（fake 注入/守門測試/secret 紀律）、ADR #21–24、截圖 #13–14、v1 不執行修復 | manifests 全文、DECISIONS 撰寫、截圖執行期拍 |

## 12. 精確度契約 8 條自檢

1. **開放問題收斂**：brief 8 項全拍板（含 3 個做/不做：digest 做、runbook RAG 做、專屬 web UI 不做）；§10 九點皆機械實查、全帶預設＋判準。2. **選型具體＋context7**：§0.4（LangGraph StateGraph/Prometheus query+query_range schema/Alertmanager webhook v4 payload/AlertmanagerConfig webhookConfigs+route continue+matcher strategy/Loki query_range+LogQL）；版本沿 P2/ask-ai 既有 pin 不自定。3. **資料契約欄位級**：fact set（§3.1）、`ml.ops_incidents`/`ml.ops_runbook_documents` DDL（§7.1/§5.2）、NARRATIVE_SCHEMA（§5.1）、`aiops_*` 指標族（§6.4）、去重鍵語意。4. **部署形狀具體**：§9.1 檔樹、wave 19、AlertmanagerConfig YAML 全文、ingress host、資源、CI workflow 形。5. **沿用既有慣例**：LLMClient 窄介面＋單一真源（ask-ai §0.3）、vendor+diff（crosscut 決策 7）、prompt registry 晉升閘與 fake 注入測試（P2 §10/§14）、sidecar dashboard/命令式 secret/SkipDryRun（P0）、/architecture bento 無新頁（觀測性 §7.1）、no-op env（觀測性 §1.1）。6. **進化非複刻**：§0.2 逐項取/不取（webhook 骨架取、`alerts[0]` bug 矯正＋守門、Dify/DeepSeek/明碼憑證明拒、程式判定+LLM 敘事範式取而工程化、幻覺時間戳反面教材轉化為 `check_timestamps` 閘）。7. **硬約束貫徹**：棄 Dify/DeepSeek（全文零引用其棧）、一工一具（LangGraph 單框架/pgvector 複用/既有 Prometheus+Loki 查證/Airflow 排程/不做第二 UI）、拓撲鐵律（服務叢集內、ingress 本地域、前端零 live 依賴＋策展快照）、only-additive（§9.3 全集）、反幻覺鐵律（§4 雙閘＋程式注入）、grounding 誠實（§8 三句）、M4/CPU 友善（無 GPU 假設、LLM 走既有 host Ollama）。8. **每步可測**：eval 三閘可實跑、graph fake 注入測試、雙純函式單測表、webhook 實測（§10#3）、promtool、「數字/時間戳零幻覺」是 eval hard 斷言非口號。

---

### 附：端到端驗收清單（`scripts/verify-aiops.sh`＝`make aiops-verify`；沿 P0 §8 形式，任一步 fail 非零退出）

| # | 檢查 | 預期 |
|---|---|---|
| 1 | ArgoCD `aiops` app `Synced+Healthy`（wave 19） | 綠 |
| 2 | `curl aiops.localtest.me/healthz` | 200＋Postgres/Prometheus 子檢查 ok |
| 3 | `amtool alert add aiops-smoke severity=warning namespace=ml` → 輪詢 `SELECT * FROM ml.ops_incidents WHERE alertname='aiops-smoke'` | 一列（generic fallback 模板）、`verification.passed` 存在、`generated_at` 非空 |
| 4 | 同告警重打（repeat 模擬） | 仍一列（dedupe）＋`aiops_incidents_total{outcome="deduped"}` 增量 |
| 5 | 報告敘事段 grep 日期/時刻 regex（§4.3 同式） | 零命中（時間戳只在程式段） |
| 6 | `POST /digest` | `trigger='digest'` 一列＋SLO/health 事實入 fact_set |
| 7 | `curl /metrics` | `aiops_incidents_total`/`aiops_tokens_total` 暴露 |
| 8 | `make aiops-eval` | 三閘綠（hard 全過） |
| 9 | Discord（env 已設時；未設 skip＋警示） | 敘事卡送達 |
| 10 | Grafana `/api/search?query=AI Ops` | dashboard title 命中 |

---

## 13. Opus 把關註記（PASS）

> 規劃者（Opus 4.8）獨立覆核。**不轉述 Fable 5 自報**——親跑 context7 覆核最吃重的承重宣稱、逐條裁定風險點、跑五鐵律。**判定 PASS，commit 進 trend repo（不加 Co-Authored-By footer——專案 repo 慣例）。**

### 13.1 獨立 context7 覆核（規劃者親查，非採信 §0.4）

覆核挑「若錯則 additive 邊界崩」的承重宣稱——AlertmanagerConfig 雙 receiver 機制（也是 Fable 5 自報最貼線的風險）：

| 宣稱 | 規劃者獨立查證（context7 `/prometheus-operator/prometheus-operator`，2026-07-10） | 判定 |
|---|---|---|
| **operator 對 first-level route 強制 `continue: true`** | API 文件原文：「The `continue` field ... **is always overridden to true for the first-level route** by the Prometheus operator」 | ✅ 屬實。Discord（觀測性 §6）＋webhook（本 spec）兩個 AlertmanagerConfig 的 first-level route 都被評估 → **兩 receiver additive 並收成立**，Discord route 零改 |
| **`alertmanagerConfigMatcherStrategy` 預設 `OnNamespace`；CRD 只配對同 namespace label 的告警** | API 文件確認 `AlertmanagerConfigMatcherStrategy.type` 「default value is `OnNamespace`」＋AlertmanagerConfigSpec「applies **only to alerts where the namespace label matches** the AlertmanagerConfig resource's namespace」 | ✅ 屬實。namespace matcher 縫是真的；本 CRD 在 `ml` ns 但敘事對象跨 namespace → 需 `type: None`。§2.3/§10#4 的解正確 |

其餘 §0.4 宣稱（LangGraph StateGraph、Prometheus query/query_range、Alertmanager webhook v4 payload、Loki LogQL）為既有成熟 API 或沿 P2/ask-ai pin，隨 plan 實查即可，不阻擋收斂。

### 13.2 跨 spec 協調點（規劃者裁定，兩份 plan binding）

**`alertmanagerConfigMatcherStrategy: {type: None}` 是觀測性 Discord CRD 與本 spec webhook CRD 的共用前置**——兩者都在非 `default`/`monitoring` 的自有 namespace（observability §6 的 Discord、本 spec 的 `ml`），都受 OnNamespace 預設限縮、都要跨 namespace 敘事/通知。**裁定：一行 `type: None` 同時解兩個 receiver**（P0 monitoring values additive，觀測性 §8.3 同檔同性質）。**這是觀測性 plan 實查 #5 與本 spec plan 實查 #4 的同一項——寫 plan 時必須收斂到同一解、不得各設一份**。已在本 §13 記錄供兩份 plan 對齊（避免 [[feedback_no_orphan_worktree_dev]] 式的兩 session 各做一半）。

### 13.3 Fable 5 給的風險點逐條裁定

1. **反幻覺是否真做到數字/時間戳零 LLM 生成**：**機制上成立，PASS**。時間戳唯一來源＝程式段落（fact set＋Jinja 模板渲染），LLM 敘事段經 `check_timestamps`（零豁免、針對課程幻覺型態）＋`check_numbers`（vendor 不改本體）雙閘，eval hard 斷言 fixture 全過。**`check_timestamps` 另立的論證扎實**：check_numbers 豁免年份 2020/2021（ask-ai 語境正確），而課程反面教材幻覺正是日期時間——改 check_numbers 豁免集＝違 vendor 單一真源，另立更嚴前置閘是對的（規劃者接地時亦見 ask-ai `:289-292` 豁免 2018–2025，證實此縫真實）。**殘餘縫**（Fable 5 自問）：verify 兩度 fail 仍落表＋帶 badge 發 Discord。**裁定維持 design 判斷**——維運語境「殘缺誠實（帶 `[UNVERIFIED]` 前綴）＞消失」，badge 使其非欺騙；策展樣本零容忍（只收 verify-pass）已守住對外門面。可接受。
2. **Dify/DeepSeek**：全文零引用其棧（僅 §0.2 取材對照＋ADR #21/#22 拒絕理由）；LangGraph 單框架、LLM 只走 LLMClient 窄介面。PASS。
3. **拓撲鐵律**：服務叢集內（`ml` ns）、ingress 僅 `aiops.localtest.me` 本地域、前端零 live 依賴（策展快照 JSON＋截圖）；服務對叢集**只讀**（v1 明確不執行修復、無 kubectl/API 寫）。PASS。
4. **additive 邊界**：§9.3 完整清單；最貼線一處＝P0 monitoring values 可能 +1 行（見 13.2，且是兩 receiver 共用解）；新表 `ml.ops_*`、新 AlertmanagerConfig receiver（Discord route 零改，經 13.1 continue:true 證實 additive）、新服務/dashboard 全 net-new；check_numbers vendor 複用不改本體。PASS。
5. **model pin**：未自定——符號引用 LLMClient default（P2 §8 合約 `qwen3.5:9b`）、config 零 model 字串、`model` 欄 runtime 回報。ask-ai/crosscut 舊標 `qwen3:8b` 是**既存跨文件漂移**，本 spec 只標不修（對）。**規劃者另記**：此漂移已在 [[project_llm_agent_architecture]] / [[project_trend_intelligence_platform]] 追蹤，日後一次 pin 對齊校正（非本 spec 責任）。

### 13.4 規劃者五鐵律覆核

- **接地誠實**：§0.1 逐錨 file:line、§0.2 課程「取 vs 不取」（webhook 骨架取、`alerts[0]` bug 矯正＋守門、Dify/DeepSeek/明碼憑證明拒、幻覺時間戳轉化為 `check_timestamps` 閘）、§0.3 無實碼誠實鎖合約（ask-ai §0.3 precedent）。✅
- **拓撲鐵律**：見 13.3-③。✅
- **一工一具／棄 Dify+DeepSeek**：見 13.3-②；pgvector 複用（不新增向量庫）、Airflow 排程（不引 Dify cron）、不做第二 UI。✅
- **only-additive**：見 13.3-④。✅
- **反幻覺（核心正確性面）／安全**：見 13.3-①；另 PromQL/LogQL 模板內插只允許告警 label 值經字元白名單 `[A-Za-z0-9_.:-]`（縱深防注入）、secret 全 k8s Secret（課程明碼 key 反例的守門）、gitleaks gate 涵蓋。✅

**額外肯定的判斷力**：digest 健康分級零 LLM（直讀既有程式值＝「程式判定、LLM 敘事」原則落地）、報告前兩段收回程式模板渲染（比課程讓 LLM 寫全部四段更嚴）、narrator 故障不影響原告警送達（fail-safe 分層）、generic fallback 模板保證新告警不漏敘、`UNIQUE(fingerprint,starts_at)` 對持續 firing 告警天然去重（不因 4h repeat 重敘）。

### 13.5 判定

**PASS。** 八項全拍板、承重宣稱獨立證實、反幻覺鐵律嚴謹（且改進了複用靶 check_numbers 的年份豁免縫）、棄 Dify/DeepSeek 徹底、拓撲與 additive 皆守。commit 進 trend repo（不加 footer）。**plan 佇列位置**：本 design 依賴 ①觀測性 spec（Alertmanager webhook/PromQL/Loki——plan 序在觀測性之後）②P2b（LLMClient/RAG retrieval——硬序在 P2b-1 之後、與 ask-ai/search plan 同吃 P2b）③ask-ai（check_numbers vendor 來源——序在 ask-ai plan 之後）。故 plan 硬序：**P2b-1 → ask-ai plan → 本 aiops plan**（觀測性 plan 亦為前置）；與 13.2 的 matcherStrategy 共用解需和觀測性 plan 對齊。
