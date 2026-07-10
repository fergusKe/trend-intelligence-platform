# 問 AI agentic 分析問答 design（多 agent 分析問答四件套：策展 trace 全揭露 + 架構圖 + MCP + v1 live-demo；複用 P2b 不重造）

> **上游**：[brief](2026-07-10-ask-ai-brief.md)（工作合約正本）＋ repo `CLAUDE.md`「Fable 5 design 精確度契約（8 條）」（自檢見 §14）＋ [統一作品集 crosscut design](2026-07-10-unified-portfolio-crosscut-design.md)（binding：§6 全節/§7.2/§5/決策 9/10/11/§0 pin）＋ [GA 支柱 design](2026-07-10-ga-pillar-design.md)（binding：§2.2 `/ga/ask` route、§8.3 9 marts＋§8.4 4 ml 表、§8.6 12 datasets、§8.7 MCP 現況、**§10 AskAiTeaser 消費契約（唯讀，本 spec 只定產線）**、§9 registry 覆蓋）＋ [Signal 設計系統 design](2026-07-10-frontend-design-system-design.md)（視覺地基不重定）＋ [P2 ML verticals design](2026-07-08-P2-ml-verticals-design.md)（P2b 基建唯讀複用邊界）＋ [P4 呈現層 design](2026-07-08-P4-presentation-layer-design.md) §3–4/§7（信封/absent/MCP 誠實紀律）。
> **定位**：問 AI 支柱＝一個複用 P2b LLMOps 治理的**新 LangGraph graph**（orchestrator-worker＋雙 guardrail＋reflection，六專家讀 GA insight 資產），以四件套呈現：①平台端批次預產策展 Q&A（逐節點 trace 全揭露）②多 agent 架構說明式圖 ③MCP 工具 +1 ④**v1 就上的 live-demo 外連**（獨立 Cloud Run 端點跑真 agent）。**靜態站零 live LLM**（crosscut §6.4 拓撲鐵律）。
> **產出日期**：2026-07-10。**本階段只出 spec，plan 延後**；不 commit（Opus 把關後處理）。

---

## 0. 接地與版本查證（2026-07-10 第一手）

### 0.1 版本敏感宣稱

| 宣稱 | 查證結果 | 來源 |
|---|---|---|
| **LangGraph `Send` API（map-reduce fan-out）**：`from langgraph.types import Send`；conditional edge 回傳 `list[Send("worker", payload)]` 動態展開並行 worker；fan-in＝`add_edge("worker", "next")`（superstep 語意，全分支完成才進下節點）；並行寫入用 `Annotated[list, operator.add]` reducer | ✅ 官方文件「Orchestrator-Worker Workflow with Send API」範例與本 graph §2 形狀逐行對得上——**官方正典 pattern，非自創** | context7 `/websites/langchain_oss_python_langgraph`（2026-07-10）；版本沿 P2 §0 pin `langgraph 1.2.8` 不重議 |
| **FastAPI / uvicorn（live-demo 新 pin）** | **fastapi 0.139.0 / uvicorn 0.51.0**（PyPI 2026-07-10 當日現值；穩定套件，用法面與 P2b rag-service 同款不另查） | PyPI |
| LangGraph 1.2.8 / langchain-core 1.4.8 / langchain-ollama 1.1.0 / langchain-google-genai 4.2.7 / Ollama v0.31.1 / mlflow-skinny 3.14.0 | 沿 **P2 §0 pin 表**（已查證）——本 spec 零翻案 | P2 §0 |
| 生成模型 | **Ollama `qwen3:8b`（host 預設）/ Gemini `gemini-2.5-flash`（fallback 與 live 端點）**——沿 **EP-J 裁定**（ga4-extension-crosscut §EP-J：對齊 P2 生態 pin，防 host 模型碎裂）＋ crosscut §6.2 原文 | EP-J、crosscut §6.2 |
| 前端 | **零新依賴**（crosscut §0 pin 表原樣；trace 展開/卡牆/badge 全用 Signal 既有元件與 CSS） | crosscut §0/Signal §0 |

### 0.2 ga-insight agents 第一手 grep（唯讀；本次實讀 file:line）

repo：`/Users/fergus/Desktop/workshop/fergus/llm-workshop/ga-insight/src/agents/`。

| 素材 | file:line 錨點 |
|---|---|
| graph 8 節點（6 功能＋2 end） | `graph.py:460-499` `build_graph()`：input_guardrail/orchestrator/run_sub_agents/reflection/synthesis/output_guardrail＋end_rejected/end_answer；條件邊 `:483-497` |
| 常數 | `:37 MAX_REFLECTION_ROUNDS=2`、`:38 MAX_OUTPUT_RETRY=1`、`:219 SUB_AGENT_TIMEOUT=120` |
| State | `:45-74 AgentState`（TypedDict 17 欄：question/guardrail/planned_agents/sub_results/reflection_count/gaps/additional_agents/final_answer/sources/output_passed/retry/hallucination_flags） |
| orchestrator | `:122-187`：LLM 選 **1–4** 個 sub-agent（規則 prompt `:157-165` 關鍵字路由）；LLM 失敗 fallback `traffic+customer`（`:179-181`）；reflection 補呼叫直通（`:130-137`） |
| 並行執行 | `:190-237 node_run_sub_agents`：`ThreadPoolExecutor(max_workers=4)`（`:221`）、逐 agent 錯誤隔離（`:216-217/:230-232`）、已跑過的 agent 跳過（`:195`） |
| reflection | `:240-303`：LLM 回 `{sufficient: bool, gaps[], additional_agents[], conflicts[]}`，補選 **≤2**（`:283`）、只能選未跑過的（`:291`）——**sufficient 是模糊布林，無評分無明確停止條件**（我方 §2.3 嚴謹化的靶） |
| synthesis | `:306-383`：結論先/交叉驗證/信心加權（confidence<0.6 加註 `:353`）/reflection gaps 誠實段（`:338`）/emoji 區塊標題（`:362-370` 📌📊🎯——**明拒**，見 §10） |
| output guardrail＋重試 | `:386-408`；`:431-440` 未過且 retry<1 → 回 synthesis |
| streaming | `:515-568 stream_analysis`（graph.stream 逐節點 yield——trace 概念的雛形，但 ga-insight 不持久化也不給使用者看內部） |
| input 12 條 injection pattern | `guardrails.py:31-44 _INJECTION_PATTERNS`（本 spec §4.1 全集收錄＋增補） |
| 業務關鍵字＋LLM 二次判斷 | `:47-59 _BUSINESS_KEYWORDS`；`:120-131` 關鍵字未中→`:145-166 _llm_relevance_check`（保守放行） |
| 日期範圍檢查 | `:133-137/:168-202`（我方 v1 API 無日期參數——明拒，§10） |
| PII 5 pattern＋遮蔽 | `:62-68 _PII_PATTERNS`；`:230-239` 遮蔽為 `***` |
| **`_check_numbers` 反幻覺** | `:275-301`：regex 抽答案數字→在 `json.dumps(tool_results)` 字串找根據；**弱點：`:289-292` 豁免 <100 與 2018–2025 全部數字（小百分比全逃檢）、`:260-266` >3 個 flags 才擋**——我方 §4.2 的進化靶 |
| sub-agent 內層迴圈 | `_base_sub_agent.py:19 MAX_ITERATIONS=3`、`:235-310 run()`（reason→tool→reflect，LLM 選 tool）；`:24-34 SubAgentResult`（tool_results/analysis/key_findings/confidence/iterations/hit_limit） |
| 六專家×各 3 tools | `sub_agents/__init__.py ALL_SUB_AGENTS`；traffic（get_channel_performance/get_attribution_model/get_geo_performance）、customer（get_rfm_segments/get_ltv_prediction/get_cohort_retention）、product（get_top_products/get_bundle_rules/get_category_performance）、funnel（get_funnel_conversion/get_cart_abandonment/get_device_performance）、anomaly（get_daily_kpi/get_anomaly_report/get_period_comparison）、risk（get_churn_risk/get_high_value_at_risk/get_sleeping_customers）——各 `sub_agents/<name>_agent.py:10-14` |
| tool 輸入形 | `tools/_base.py DateRangeInput`（pydantic 驗日期） |

### 0.3 P2b 複用可行性接地（誠實記錄——本 spec 最重要的接地發現）

**實況**：trend repo 內 `grep -rl "StateGraph\|LLMClient\|langgraph"` 對 `services/`、`ml/`、全 repo `*.py` **零命中**；`ml/` 目錄空、`docs/plans/` 空——**P2b（含 LLMClient/prompt registry/評估閘）目前只存在於 P2 design 合約，尚無實作碼**。brief 要求的「實際 import 路徑與函式簽名」在今日不可能 grep 到實碼；可鎖的錨是 **P2 design 的合約路徑與行為**（P2 §2 目錄結構、§9–§10）：

| 複用面 | P2 design 合約錨 | 問 AI 消費的窄介面（本 spec 鎖定） |
|---|---|---|
| LLMClient | `ml/rag/service/src/rag_service/llm.py`（P2 §2 檔案佈局）；行為＝Ollama host 預設（`OLLAMA_BASE_URL=http://ollama-host.ml.svc:11434` ExternalName，host 直跑時 `http://localhost:11434`）/Gemini fallback（連線錯誤/逾時 30s 自動切）、`provider` 參數強制指定、`GEMINI_API_KEY` **無預設值 fail-fast**（P2 §10 明文）、成本單價常數表 | `complete(prompt, *, provider=None, temperature, json_schema=None) -> {text, provider, model, token_usage{prompt,completion}, latency_ms}`——只吃這一面，不碰 rag_service 其他模組 |
| prompt registry | MLflow Prompt Registry（P2 §3.1）：`load_prompt("prompts:/<name>@prod", cache_ttl_seconds=60)`；晉升閘 `make rag-promote-prompt` 模式（P2 §10） | 新 prompt 五支（§2.5）＋同款晉升閘 make target——**additive 掛同一 registry** |
| 評估閘結構 | evalset.yaml＋LLM-judge（Gemini flash temp 0，rubric 版本化）＋MLflow experiment 一 eval 一 run（P2 §10） | experiment `ga_ask_eval`＋§5 門檻——結構同款、題集/指標自有 |
| Prometheus | `rag_*` 指標命名法＋單價常數表（P2 §10）；postgres-exporter 自訂查詢（GA design §8.8 模式） | `ga_ask_*` 同構命名（§7.5） |
| k8s→host 接線 | ExternalName `ollama-host.ml.svc`（P2 §9） | 批次在 host 直跑不需要；若未來進 KPO 用同接線，零新接線 |

**裁定**：問 AI plan **排在 P2b plan 之後**；主路徑＝`ga_ask` 套件以 local path dependency 引 `rag-service` 套件、`from rag_service.llm import LLMClient`。**plan 期實查點 #1**＝P2b plan 落地後核對 llm.py 實際簽名與「可無副作用 import」（若套件 import 有 FastAPI/env 副作用，降級＝P2b plan 把 llm.py 抽成獨立小套件如 `ml/llm_core/`，rag_service 與 ga_ask、P6 ml_reco 同吃——屬檔案落點微調，不動 P2b graph/合約）。**本 spec 鎖死的合約是「LLM provider-switch 呼叫層全 repo 單一真源，禁止第二份實作」**；ga_ask 內只允許 thin re-export（`ga_ask/llm.py` 一行 import），不允許重寫 provider 切換邏輯。

---

## 1. 關鍵決策總表（brief 8 項全數收斂；細節在各節）

| # | brief 項 | 決定 | 一句理由 |
|---|---|---|---|
| 1 | graph 節點與狀態機 | 6 功能節點＋2 end（邏輯形狀照 ga-insight `graph.py:460-499`）；**並行改 LangGraph `Send` fan-out（官方 orchestrator-worker 正典）取代 ThreadPoolExecutor 手刻**；State 欄位級 §2.2；reflection 嚴謹化＝sufficiency 0–1 評分＋三停止條件（§2.3）；`MAX_REFLECTION_ROUNDS=2`（照 `:37` 原值，嚴謹化在評分不在輪數）；複用 vs 新建明細 §2.6 | validated-library 原生 pattern 非手刻；ga-insight 的模糊 `sufficient` 布林是本 graph 唯一不可測環節，評分化後可進指標 |
| 2 | 六專家與 tool 層 | 六專家對齊 ga-insight 名（anomaly/customer/funnel/product/risk/traffic）；**專家內層「LLM 選 tool」迴圈（`_base_sub_agent.py:19` MAX_ITERATIONS=3）砍掉，改決定性全 tool fan-out＋單次 LLM findings**（§3.2 裁定）；tool 資料面＝**12 份 `ga_insight_*.json`（P4 信封）單一 `JsonMartRepo`**，批次讀 `frontend/public/data/`、live 讀 image 內快照——同一份公開合約檔（§3.3）；17 支 tool 欄位對應 §3.4 | 我方 tool 讀的是預聚合千列級 marts，全取成本近零——LLM 選 tool 的不確定性純負債；「六專家與網站/MCP 喝同一口井」且批次/live 零資料面漂移 |
| 3 | 雙 guardrail | input＝ga-insight 12 條 pattern 全集收錄＋4 條增補（16 條全列 §4.1）＋關鍵字/LLM 二次相關性；output＝PII 5 pattern＋**`check_numbers` 進化版純函式**（撤銷 <100 豁免、容差規則明確、**策展發佈零容忍**——對照原碼 >3 才擋）；live 端點同一規則集模組前置（§4.3） | 反幻覺是本 spec 最重要正確性面；純函式＝可測斷言 |
| 4 | 評估閘 | 三 hard（策展數字命中 100%／adversarial 100% 攔＋curated 100% 過／judge faithfulness、relevance ≥3.5）＋一 warn（reflection 收斂率 ≥0.8）；未過 hard＝make 非零退出、**不寫表**（保留上次良好版）（§5） | 沿 P2b 閘結構；「不寫表」使壞批次永不上站 |
| 5 | trace schema | crosscut §6.4 保留欄零改；**additive 四欄**：`question_id`/`trace: TraceStep[]`/`sufficiency_score`/`answer_struct`＋`model`/`prompt_versions`（§6.1 欄位級）；`ml.ga_ask_showcase` DDL §6.3；trace 內 tool 結果存 digest（≤20 列/tool）控體積 | 只准 additive 擴（EP-D）；trace 全揭露＝v1 超越點之一 |
| 6 | 批次產線 | **不開新 DAG**（偏離 brief「傾向 schedule=None DAG」，論證：P2 §13 明文「LLM showcase 批次＝host make target 不進 Airflow」＋`gen-rag-showcase`/P6 `gen-reco-reasons` 兩個先例同形）；`make ga-ask-showcase` host 跑（Ollama 零成本）→ 過 §5 閘 → TRUNCATE-insert `ml.ga_ask_showcase` → 既有 `export_frontend_data` additive +1 條目；策展題集＝git 版本化 `questions.yaml`（global 10＋7 分析頁×3=31 題）；CI `ga-ask-ci.yaml`（§7） | M4 界線誠實：排程自動化在 k8s，host LLM 批次是人工觸發離線工序；資料靜態、排程是儀式（與 `ga_insight_batch` schedule=None 同論證，形式更誠實） |
| 7 | live-demo 部署 | **Cloud Run `ga-ask-live`**（FastAPI 0.139 包同一個 graph）＋**模型固定 Gemini `gemini-2.5-flash`**（Cloud Run 摸不到 host Ollama——拓撲事實，誠實標 provider）；資料/prompt 皆 **build 時烘進 image**（同 commit 的 12 份 JSON＋prompt snapshot）；input guardrail 前置（同一規則集）；scale-to-zero、max-instances=1、concurrency=4、timeout 120s；rate-limit 只留接縫（middleware 掛點＋429 schema＋env 開關，實作 follow-up）；極簡單頁 UI（vanilla JS，零框架）；手動 `workflow_dispatch` 部署（§8） | v1 就上（Fergus 定案）且守「靜態站零 live LLM」——live 是外連獨立端點；烘資料進 image＝零雲端 DB、零回連本地叢集，成本＝flash 零頭＋scale-to-zero |
| 8 | `/ga/ask` IA＋teaser 產線 | 頁 IA 七段（§9.1）；registry `ga-ask` blocks 拍板 4 個＋`ask-teaser`；**answer 結構化**：synthesis 產 `answer_struct`（conclusion/key_numbers/sections/actions/limitations）前端結構化渲染——**零 markdown 依賴**、比 ga-insight markdown 更機器可讀；teaser 產線＝7 分析頁各 3 則單領域 Q&A（`allowed_agents` 鎖該頁主專家），`page:ga-ask` 不產（GA §10 三態③縮減態即合法）（§9.3） | crosscut §6.3 定框原樣；GA §10 消費契約零改 |

**貫穿裁定**：①agent 框架只 LangGraph、不引第二框架（硬約束）；②tool 只讀不寫、只讀 `ga_insight_*` 12 檔白名單（不越界 YouTube/`dmp_*`/PTT——單元測試斷言，§11#3）；③runtime output guardrail **砍 LLM answer-relevance 檢查**（`guardrails.py:303-326`）——不可測且每問多一次呼叫，其職責由離線 judge（§5）承擔；runtime 只留決定性檢核（PII＋數字），live 延遲直接受益；④全 additive：不改 P2b graph、GA marts/ml 表、AskAiTeaser 消費契約、showcase 信封（rows 只 additive 擴）；前綴 `ga_ask_`。

---

## 2. 問 AI graph（brief 項 1）

### 2.1 節點與邊（LangGraph 1.2.8；Send fan-out 為 context7 已證正典）

```
START → input_guardrail ──(fail)──→ end_rejected → END
              │(pass)
              ▼
        orchestrator ──(Send fan-out：[Send("run_expert", {agent, question, scope}) for agent in 待跑集])──▶ run_expert ×N（並行）
              ▲                                                                                                  │（reducer fan-in）
              │(insufficient 且 rounds<2 且有可補專家 → 補選模式，只 Send 未跑過的)                                ▼
              └───────────────────────────────────────────────────────────────────────────────────────── reflection
                                                                                                                 │(sufficient 或停止條件)
                                                                                                                 ▼
                                                                            synthesis → output_guardrail ──(fail 且 retry<1)──→ synthesis
                                                                                              │(pass 或 retry 耗盡)
                                                                                              ▼
                                                                                         end_answer → END
```

- 6 功能節點＋`end_rejected`/`end_answer` 兩終止節點——節點集與 ga-insight `graph.py:465-472` 一比一，**差異只在 run_sub_agents 由單節點內 ThreadPoolExecutor（`:221`）改為 `Send` 動態 fan-out**（`add_conditional_edges("orchestrator", assign_experts, ["run_expert"])`＋`add_edge("run_expert", "reflection")` fan-in）。
- 已跑過的專家不重跑（照 `:195` 邏輯形狀）：`assign_experts` 對 `planned - {r.agent for r in expert_results}` 差集 Send。
- 逾時與錯誤隔離：單一專家 LLM 呼叫逾時（`params.yaml expert_timeout_s`：batch 300 / live 60）→ 該專家記 `error`，graph 不倒（照 `:216-232` 錯誤隔離精神）；並行度 `expert_parallelism`（batch 2——host Ollama 單服務排隊、live 4）。
- `MAX_OUTPUT_RETRY=1`（照 `:38`）；重試時 synthesis prompt 附上未驗證數字清單（進化：告訴它錯哪裡，非盲重生）。

### 2.2 State schema（欄位級；TypedDict）

```python
class ToolCall(TypedDict):
    tool: str; params: dict; row_count: int; elapsed_ms: int

class ExpertResult(TypedDict):
    agent: str                              # 'anomaly'|'customer'|'funnel'|'product'|'risk'|'traffic'
    tools_called: list[ToolCall]
    tool_results: dict[str, Any]            # 全量（供 check_numbers；trace 只存 digest）
    analysis: str
    key_findings: list[str]                 # 3–5 條
    confidence: float                        # 0–1（LLM 自報，僅作合成輸入）
    token_usage: dict                        # {prompt, completion}
    error: str | None

class AskState(TypedDict):
    question: str
    scope: str                               # 'global' | 'page:<pageId>' | 'live'
    allowed_agents: list[str] | None         # None=六專家全開；page 範圍鎖主專家（§9.3）
    guardrail_input: dict                    # {passed, violation_type|None, matched_pattern|None, relevance_source:'keyword'|'llm'|'n/a'}
    planned_agents: list[str]
    orchestrator_reasoning: str
    expert_results: Annotated[list[ExpertResult], operator.add]   # Send 並行 reducer
    reflection_rounds: int
    sufficiency_score: float | None          # 0–1（§2.3）
    reflection_gaps: list[str]
    additional_agents: list[str]
    answer: str                               # 全文純文字（answer_struct 的平鋪投影；MCP/搜尋用）
    answer_struct: dict                       # §9.2
    confidence: float                         # 程式合成（§2.4），非 LLM 自報
    guardrail_output: dict                    # {passed, pii_masked_count, number_check:{checked,verified,unverified[]}, retry_count}
    provider: str; model: str                 # 'ollama'/'qwen3:8b' 或 'gemini'/'gemini-2.5-flash'
    token_usage: dict                         # 全程累計
    prompt_versions: dict[str, str]
    trace: Annotated[list[dict], operator.add]  # TraceStep（§6.2）；每節點自 append
```

### 2.3 reflection 收斂嚴謹化（v1 超越點；對照 `graph.py:287-289` 模糊布林）

reflection LLM 以 structured output 回 `{sufficiency: float 0–1, gaps: [], additional_agents: [], conflicts: []}`（prompt 明定評分 rubric：問題各面向覆蓋度×數據充分度）。**停止條件（三選一即停，順序判定）**：
1. `sufficiency ≥ 0.75`（`params.yaml sufficiency_threshold`）→ 進 synthesis，`converged=true`；
2. `reflection_rounds ≥ 2`（`max_reflection_rounds`，照 ga-insight 原值）→ 進 synthesis，`converged=false`，gaps 傳給 synthesis 誠實標「分析限制」（照 `:338` 精神）；
3. 無可補專家（`allowed_agents` 差集空）→ 同 2 處置。

補選上限每輪 ≤2（照 `:283`）、只能選未跑過且在 allowed 集內的。`sufficiency_score`/`converged` 進 trace、進表、進指標（§7.5）——**ga-insight 只 log、我方可稽核**。

### 2.4 confidence 合成（程式算非 LLM 自報；式進 registry `formula`）

`confidence = clip( mean(專家 confidence) − 0.1×[有未驗證數字] − 0.1×[未收斂], 0, 1 )`，四捨五入 2 位。LLM 自報信心只作輸入，扣分項全是程式事實——與反幻覺紀律同向。

### 2.5 prompt registry（複用 P2b MLflow Prompt Registry，additive 五支）

`ga_ask-orchestrator` / `ga_ask-expert-findings` / `ga_ask-reflection` / `ga_ask-synthesis` / `ga_ask-judge`——alias `@prod`，runtime `load_prompt(...)`（P2 §3.1 同款）；晉升走 `make ga-ask-promote-prompt NAME=… VERSION=…`（先跑 §5 eval、達標才掛 alias，鏡像 P2 §10 `rag-promote-prompt`）。溫度拍板（照 ga-insight 實值）：orchestrator/reflection 0.1（`:174/:286`）、expert-findings 0.2、synthesis 0.4（`:376`）。**live 端點讀不到本地叢集 MLflow**→prompt 於 image build 時 snapshot 成檔烘入（§8.3），`prompt_versions` 如實記 build 當下版本。

### 2.6 複用 vs 新建明細（brief 項 1 要求明標）

| 複用 P2b（零重造） | 新建（本 spec 產物） |
|---|---|
| LLMClient（§0.3 窄介面；ollama qwen3:8b/gemini fallback/成本常數表/fail-fast key） | graph 本體 `ga_ask/graph.py`＋`state.py` |
| MLflow Prompt Registry＋晉升閘模式 | 六專家 sub-agent＋17 支 tool＋`JsonMartRepo`（§3） |
| 評估閘結構（evalset/judge/MLflow experiment） | 雙 guardrail 規則集模組（§4；`check_numbers` 純函式） |
| Prometheus 指標命名法＋postgres-exporter 自訂查詢模式（GA §8.8） | trace schema＋`ml.ga_ask_showcase` 表（§6） |
| P4 信封/exporter/MCP/absent 慣例 | 批次 CLI、eval CLI、live FastAPI＋UI、Cloud Run 部署（§7/§8） |

---

## 3. 六專家 sub-agent 與 tool 層（brief 項 2）

### 3.1 職責邊界（對齊 ga-insight 六名；讀 GA 資產重繫結）

| 專家 | 職責（一句） | 讀的資產（dataset＝GA §8.6；欄位＝GA §8.3/§8.4 定稿） | 對應 GA 頁（teaser 主專家） |
|---|---|---|---|
| `anomaly` | KPI 趨勢、異常點、跨期拆解 | ga_insight_kpi_daily、ga_insight_period_compare | `/ga`（pageId `ga`） |
| `funnel` | 漏斗轉換/瓶頸、購物車放棄 | ga_insight_funnel、ga_insight_funnel_daily、ga_insight_cart | `/ga/funnel`＋`/ga/cart` |
| `customer` | 生命週期、LTV 結構 | ga_insight_lifecycle、ga_insight_lifecycle_transitions、ga_insight_ltv | `/ga/customers` |
| `risk` | 流失模型、風險分帶 | ga_insight_churn（model_card/risk_bands/deciles 三 section） | `/ga/churn` |
| `traffic` | 歸因模型對照、來源成效 | ga_insight_attribution、ga_insight_funnel（source 切片列） | `/ga/attribution` |
| `product` | Pareto、商品漏斗、搭售 | ga_insight_products、ga_insight_basket_rules | `/ga/products` |

ga-insight 專家中職責在我方資料上不成立的面向如實不搬：traffic 的地理分布（`get_geo_performance`——我方 marts 無 geo 維度切片）、customer 的世代留存（無 cohort mart）——不硬撐，orchestrator prompt 的專家描述只寫真有的能力。

### 3.2 專家執行形（裁定：決定性 tool fan-out＋單次 LLM findings；砍內層 LLM 選 tool 迴圈）

ga-insight 專家有內層 reason→tool→reflect 迴圈（`_base_sub_agent.py:19` MAX_ITERATIONS=3，LLM 逐輪選 tool `:114-148`）——那是「tool 打大 DB、全取昂貴」下的設計。我方 tool 讀的是**預聚合千列級 JSON**，單一專家全部 tool 全取 <100ms、零成本。**裁定**：專家＝①決定性執行自己的全部 tool（無 LLM 參與、無參數協商）②單次 LLM 呼叫產 `{analysis, key_findings[], confidence}`（structured output；形狀照 `_base_sub_agent.py:188-231 _synthesize`）。收益：砍掉一個幻覺/不確定性面、LLM 呼叫數 3–9×↓（live 延遲直接受益）、專家行為完全可重現可單測。**agentic 判斷保留在該在的層**：orchestrator 選專家、reflection 補專家——這才是 orchestrator-worker 展示的主角。單題呼叫帳：orchestrator 1＋專家 ≤4（並行）＋reflection 1–2＋synthesis 1（＋重試 ≤1）＝**5–9 次**。

### 3.3 tool 資料面（裁定：12 份 `ga_insight_*.json` 單一 `JsonMartRepo`）

- `JsonMartRepo(data_dir)`：讀 P4 信封檔、驗 `status`（`absent` → tool 回明確缺席訊息，專家 findings 如實標，不裝死——P4 慣例）；`data_dir` 走 env `GA_ASK_DATA_DIR`——批次＝`frontend/public/data/`（committed 正本）、live＝image 內 `/app/data/`（build 時 COPY 同一批檔）。
- **單一後端零漂移**：批次、live、網站、MCP 四個消費者喝同一份公開合約檔；tool 層不碰 Postgres/k8s（「只讀不寫」由構造保證）。
- 白名單＝GA §8.6 的 12 檔（`ga_insight_kpi_daily/period_compare/funnel/funnel_daily/cart/lifecycle/lifecycle_transitions/ltv/products/attribution/basket_rules/churn`）；repo 建構時斷言存取檔名 ⊆ 白名單（單測 §11#3）。
- 產線順序含二次匯出（誠實記錄）：`ga-insight-run` → export → export-sync/commit（12 檔就位）→ `make ga-ask-showcase`（讀 committed JSON、寫 `ml.ga_ask_showcase`）→ 再觸發 export（既有檔冪等、新增 `ga_ask_showcase.json`）→ export-sync/commit。寫進 Makefile runbook 註解與 README。

### 3.4 tool 清單（17 支；全部純函式 `tool(repo, params) -> {rows_digest, stats}`）

| 專家 | tool | 讀 | 回傳要點（數字全在此層算好） |
|---|---|---|---|
| anomaly | `get_kpi_overview` | kpi_daily | 全窗＋最近 30 天（錨 data_anchor 語意沿 GA §6.1）revenue/orders/sessions/cvr/aov 匯總 |
| anomaly | `get_anomalies` | kpi_daily | `is_anomaly=true` 列（metric/date/z_score/實值/bounds） |
| anomaly | `get_period_compare` | period_compare | 兩列月對比＋連環替代法四效果項 |
| funnel | `get_funnel` | funnel | basis=session、segment=all 五步 reached/step_conversion/drop_off/users_lost＋瓶頸列（is_bottleneck/rank） |
| funnel | `get_funnel_slices` | funnel | device 3 值×source top8 的 overall_cvr/最弱步 digest |
| funnel | `get_funnel_trend` | funnel_daily | overall_cvr 時序摘要（min/max/首尾值±日期） |
| funnel | `get_cart_abandonment` | cart | 放棄率×segment＋abandoned_value_estimate（帶「上界估算」caveat 字串） |
| customer | `get_lifecycle` | lifecycle＋lifecycle_transitions | 各月 stage 計數＋轉移矩陣 top 流向（含沉睡回流數） |
| customer | `get_ltv_deciles` | ltv | 十分位表＋top-decile share＋cum_share 80% 交點 |
| risk | `get_churn_model_card` | churn(section=model_card) | model_version/訓練窗/PR-AUC vs baseline/passed_gate |
| risk | `get_risk_bands` | churn(section=risk_bands) | 三帶人數與占比 |
| risk | `get_decile_lift` | churn(section=deciles) | 預測分十分位×實際流失率 |
| traffic | `get_attribution` | attribution | 四模型×channel attributed_revenue/share（含 lookback/half_life 參數欄） |
| traffic | `get_model_shifts` | attribution | 模型間 channel 排名變動（程式算 rank diff） |
| traffic | `get_source_funnel` | funnel | segment_type=source 列的逐步轉換 |
| product | `get_pareto` | products | top 列＋in_top80 家數/營收占比＋view_to_purchase 極值 |
| product | `get_basket_rules` | basket_rules | top lift 規則（support/confidence/lift） |

rows_digest 上限 20 列/tool（`params.yaml tool_digest_rows`）；`tool_results` 全量留在 State 供 `check_numbers`。tool 輸入不吃 LLM 生成參數（決定性）；日期範圍固定＝資料窗 2020-11-01～2021-01-31（GA 地基窗），API 無日期參數（§4.1）。

---

## 4. 雙 guardrail 規則集（brief 項 3；單一真源模組 `ga_ask/guardrails.py`，批次/live 共用）

### 4.1 input guardrail（規則全集；純程式＋LLM 二次相關性）

**A. prompt-injection patterns（16 條全列；1–12 照 `guardrails.py:31-44` 原文收錄）**：

| # | pattern（re.IGNORECASE） |
|---|---|
| 1–12 | `ignore\s+(all\s+)?previous\s+instructions?`／`忽略.{0,10}(以上|之前|前面|所有).{0,10}指令`／`forget\s+everything`／`你現在是.{0,20}(AI|機器人|助手)`／`act\s+as\s+(if\s+you\s+are|a)`／`system\s*prompt`／`jailbreak`／`DAN\s+mode`／`pretend\s+you\s+(are|have\s+no)`／`<\s*(system|assistant|user)\s*>`／`\[INST\]`／`###\s*(System|Instruction)` |
| 13（增補） | `<\|im_start\|>|<\|im_end\|>|<\|system\|>`（chat-template 控制 token——qwen 系模型的注入面，ga-insight 用 Gemini 沒這問題、我方 Ollama 有） |
| 14（增補） | `developer\s+mode` |
| 15（增補） | `(repeat|reveal|print|輸出|重複).{0,20}(system|instructions?|prompt|指令|提示詞)`（prompt 洩漏誘導） |
| 16（增補·前置正規化） | 檢查前先剝除零寬/方向控制字元 `[​-‏‪-‮⁦-⁩]` 再比對（防 unicode 夾帶繞過）——此為正規化步驟＋「剝除後長度差 >0 記 trace」 |

**B. 業務相關性**：關鍵字表照 `:47-59` 收錄＋GA 支柱詞增補（漏斗/瓶頸/歸因/生命週期/沉睡/Pareto/搭售/放棄/LTV/churn/attribution/funnel/lifecycle）；未命中且長度 >5 → LLM 二次判斷（照 `:145-166`：yes/no、temp 0、**失敗放行**——相關性非安全面，fail-open 正確；injection 檢查是決定性 regex，無 fail-open 問題）。`relevance_source` 記 trace。

**C. 長度與格式**：question ≤500 字元（API 層 pydantic＋guardrail 雙檢）；無日期參數（明拒 `:133-137/:168-202` 日期檢查——v1 API 面就沒有這個輸入，資料窗寫死在 synthesis prompt 與頁面誠實文案）。

拒絕處置：`end_rejected` 回 `{status:'rejected', reason}`（不進 LLM、不入 showcase）；live 回 HTTP 200＋rejected body（guardrail 拒絕是正常行為非伺服器錯誤；429 保留給 rate-limit follow-up、422 給 pydantic）。

### 4.2 output guardrail（PII＋`check_numbers` 進化版——本 spec 最重要正確性面）

- **PII**：5 pattern 照 `:62-68` 收錄、遮蔽 `***`（照 `:230-239`）。資料為 GA4 公開遮蔽樣本、理論無真 PII——保留為縱深防禦＋展示敘事，`pii_masked_count` 進 trace。
- **`check_numbers(answer, fact_numbers) -> {checked, verified, unverified[]}` 純函式（可測斷言）**：
  1. **事實數字集**：遞迴收集全量 `tool_results` 數值葉；每值展開等價形＝原值、round 0/1/2 位、×100 與 ÷100（rate↔percent 換算）。
  2. **答案數字抽取**：`\d+(?:,\d{3})*(?:\.\d+)?%?`——百分比帶回 `%` 語意（`3.2%` 以 3.2 與 0.032 兩形比對）。
  3. **豁免集（顯式列舉，對照原碼 `:289-292` 的「<100 全豁免」缺陷）**：整數 0–10（列舉序數）與年份 2020/2021、月份形 `2020-11` 類 token——**其餘一律檢**（小百分比不再逃檢）。
  4. **匹配**：字串等價（含千分位正規化）或數值容差 `|a−b| ≤ max(0.005, 0.5%×|b|)`（覆蓋四捨五入）。
  5. **政策（進化：對照 `:260-266` 的「>3 flags 才擋」）**：`unverified` 非空即 fail →（a）批次：帶未驗證清單重試 synthesis 一次（§2.1），仍 fail → 該題**不入 showcase**、記 eval；**策展發佈零未驗證數字**（§5 hard 閘）。（b）live：答案照出但 `output_flags` 如實入 trace/回應，UI 渲染警示 badge「以下數字未能對應工具結果」——誠實優先於美觀。
- 單測表（§11#2）至少涵蓋：千分位/百分比換算/容差邊界/豁免序數/捏造大數/捏造小百分比（原碼漏檢靶）六類正反例。
- synthesis prompt 硬性指示：「所有數字必須逐字取自工具結果，不得推算新數字；需要比較就引用兩個原始數字」——LLM 只敘事、數字由 §3.4 tool 層程式算（[[llm-grounded-feature]] 精神）。

### 4.3 live 端點前置

同一 `ga_ask.guardrails` 模組：API 層 pydantic（長度/型別）→ graph 節點 1 input guardrail（16 pattern＋相關性）→ 才可能碰 LLM。**規則集無第二份拷貝**（live image 裝同一套件）。

---

## 5. 評估閘（brief 項 4；結構複用 P2b，MLflow experiment `ga_ask_eval`）

| # | 閘 | 門檻 | 級別 |
|---|---|---|---|
| 1 | 數字命中率 | 擬發佈 rows 的 `unverified` 總數 ＝ 0（100% 命中） | **hard** |
| 2 | guardrail 通過率 | `adversarial.yaml`（16 pattern×變體＋離題題，≥20 條）100% 攔截；`questions.yaml` 31 題 100% 通過 input guardrail | **hard** |
| 3 | 答案品質 | LLM-judge＝Gemini flash temp 0（rubric prompt `ga_ask-judge` 版本化）：faithfulness ≥3.5 且 relevance ≥3.5（1–5 平均；閘值沿 P2 §10） | **hard** |
| 4 | reflection 收斂率 | `converged=true` 占比 ≥0.8 | warn（資料真缺口導致不收斂是誠實態；低於線＝記錄檢視，不擋發佈） |

- 流程：`make ga-ask-eval`（host；跑 31＋adversarial 全集 → 指標 log MLflow：params=prompt versions＋provider、一次 eval＝一個 run，A/B＝兩 run 並排——P2 §10 同構）。
- **未過 hard 閘處置**：make 非零退出、`ml.ga_ask_showcase` **不 TRUNCATE 不寫入**（表保留上次良好版，exporter 照舊匯出）→ 壞批次在資料層就進不了站。`make ga-ask-showcase` 內嵌此閘（產生→評→過才寫）。
- prompt 晉升閘共用同一 eval（§2.5）。

---

## 6. trace schema 全欄（brief 項 5；crosscut §6.4 骨架只 additive 擴）

### 6.1 `ga_ask_showcase.json` rows（P4 信封；crosscut 保留欄零改＋additive 六欄）

| 欄 | 型別 | 出處 |
|---|---|---|
| `scope` | `'global' \| 'page:<pageId>'` | crosscut 保留欄 |
| `question` / `answer` | string | 同上（answer＝純文字全文投影） |
| `agents_called` | string[] | 同上 |
| `reflection_rounds` | number | 同上 |
| `guardrail` | `{input_passed: boolean, output_flags: string[]}` | 同上 |
| `confidence` | number（§2.4 合成式） | 同上 |
| `provider` / `latency_ms` / `token_usage` / `generated_at` | string / number / `{prompt,completion}` / ISO | 同上 |
| **`question_id`**（新） | string（`questions.yaml` id，slug 穩定鍵） | additive |
| **`model`**（新） | string（`qwen3:8b` 等——provider 只到廠牌，model 到型號） | additive |
| **`sufficiency_score`**（新） | number \| null（最後一輪評分） | additive |
| **`answer_struct`**（新） | §9.2 物件 | additive |
| **`prompt_versions`**（新） | Record<string,string> | additive |
| **`trace`**（新） | TraceStep[]（§6.2） | additive |

### 6.2 TraceStep（前端逐節點展開的資料源）

```ts
type TraceStep = {
  seq: number;
  node: 'input_guardrail'|'orchestrator'|'expert'|'reflection'|'synthesis'|'output_guardrail';
  agent: string | null;          // node==='expert' 時＝專家名
  started_at: string;            // ISO
  duration_ms: number;
  summary: string;               // 一句話，程式模板產生（非 LLM）——如「orchestrator 選了 funnel、traffic（理由：…）」
  detail:                        // node-specific：
    | { passed: boolean; violation_type: string|null; matched_pattern: string|null; relevance_source: 'keyword'|'llm'|'n/a' }                    // input_guardrail
    | { selected_agents: string[]; reasoning: string; allowed_agents: string[]|null; mode: 'initial'|'reflection-補選' }                          // orchestrator
    | { tools_called: {tool: string; row_count: number; elapsed_ms: number}[]; results_digest: object; key_findings: string[]; confidence: number } // expert（digest ≤20 列/tool）
    | { round: number; sufficiency_score: number; sufficient: boolean; gaps: string[]; added_agents: string[] }                                   // reflection
    | { sources_count: number; retry: number }                                                                                                     // synthesis
    | { passed: boolean; number_check: {checked: number; verified: number; unverified: string[]}; pii_masked_count: number }                       // output_guardrail
  token_usage?: {prompt: number; completion: number};
};
```

### 6.3 `ml.ga_ask_showcase`（引擎持有 DDL `CREATE TABLE IF NOT EXISTS`；TRUNCATE-insert 冪等——沿 GA §8.4 慣例）

`scope text / question_id text / question text / answer text / answer_struct jsonb / agents_called jsonb / reflection_rounds int / sufficiency_score numeric / guardrail jsonb / confidence numeric / provider text / model text / prompt_versions jsonb / latency_ms int / token_usage jsonb / trace jsonb / generated_at timestamptz`，`UNIQUE(scope, question_id)`。exporter 1:1 平鋪成 §6.1 rows。

### 6.4 體積控制

31 rows×（trace 含 digest）預估 300–600KB；`check-data.mjs` 既有單檔 ≤3MB 斷言涵蓋；digest 列數上限與 `results_digest` 字串截斷（單 tool ≤4KB）進 `params.yaml`，plan 實查 #6 以真跑校準。

---

## 7. 批次產線（brief 項 6）

### 7.1 檔案佈局（全 additive；未列＝不動）

```
ml/ga_ask/
├── pyproject.toml            # langgraph/langchain-*（P2 pin）、fastapi 0.139/uvicorn 0.51（live）、
│                             #   prometheus-client、mlflow-skinny、psycopg；local path dep → rag-service（§0.3）
├── params.yaml               # 常數單一真源（沿 P6 ml/reco/params.yaml 慣例）：max_reflection_rounds:2 /
│                             #   sufficiency_threshold:0.75 / max_agents_initial:4 / max_added_per_round:2 /
│                             #   expert_parallelism:{batch:2, live:4} / expert_timeout_s:{batch:300, live:60} /
│                             #   tool_digest_rows:20 / number_tolerance:{abs:0.005, rel:0.005} / temperatures
├── questions.yaml            # 策展題集（git 版本化）：31 題 = global 10 ＋ 7 分析頁×3（id/scope/question/allowed_agents）
├── adversarial.yaml          # ≥20 條注入/離題題（§5 閘 2）
├── Dockerfile                # live image（§8）
├── src/ga_ask/
│   ├── graph.py  state.py    # §2
│   ├── experts/              # base.py + 六專家（§3.1；宣告 tools＋專家描述字串）
│   ├── tools/                # repo.py(JsonMartRepo) + 六 domain tools（§3.4）
│   ├── guardrails.py         # §4（純函式；批次/live 共用單一真源）
│   ├── llm.py                # thin re-export：from rag_service.llm import LLMClient（§0.3）
│   ├── batch.py  eval.py     # showcase 產線 CLI／評估閘 CLI
│   ├── metrics.py            # prometheus-client 指標定義（§7.5）
│   └── live/                 # api.py + index.html + rate_limit.py（no-op 接縫）（§8）
└── tests/
orchestration/exporter/src/exporter/datasets.py   # += 1 條目 ga_ask_showcase（EP-D append）
mcp-server/server.py                              # += 1 工具（§7.4）
.github/workflows/{ga-ask-ci.yaml, ga-ask-live-deploy.yaml}
Makefile                                          # += ga-ask-showcase / ga-ask-eval / ga-ask-promote-prompt /
                                                  #    ga-ask-live-build / ga-ask-verify
scripts/verify-ga-ask.sh
frontend/src/app/(ga)/ga/ask/page.tsx ＋ registry ga.ts 的 ga-ask 條目 blocks（§9）
```

零新排程器、零新 DB、零新 k8s 元件；唯二新 CI workflow；唯一新雲面＝Cloud Run（§8）。

### 7.2 產線形（裁定：不開新 DAG）

`make ga-ask-showcase`（host；人工觸發）＝ ①讀 `questions.yaml`（前置檢查：12 份 dataset 檔在且非 absent，缺→列缺檔清單退出）②逐題跑 graph（Ollama qwen3:8b；Ollama 不可達→自動 fallback Gemini，provider 逐列如實記）③內嵌 §5 eval hard 閘 ④過閘才 TRUNCATE-insert `ml.ga_ask_showcase`（PG 連線沿 P2 `make pg-tunnel`＋`.env.ml` 慣例）⑤提示操作者觸發既有 `export_frontend_data` → `make export-sync` → 人審 commit（P4 流程原樣；二次匯出語意見 §3.3）。

**偏離 brief 傾向的論證（給 Opus）**：brief 傾向「DAG schedule=None」；本 spec 裁定不開 DAG，依據＝P2 §13 明文「host 側 make targets 不在 Airflow 內：排程自動化的都在 k8s；host 重算力步是人工觸發的離線工序」＋兩個同類先例（P2 `make gen-rag-showcase`、P6 `make gen-reco-reasons` 皆 host make target 而非 DAG）。LLM 批次走 host Ollama＝重算力步，開 schedule=None 的 DAG 反而立了第三種「假排程」形狀。回退成本：若 Opus 判定要 DAG，包一個 KPO（經 `ollama-host` ExternalName 打 host Ollama，P2 §9 接線零新增）即可，graph 碼零改。

### 7.3 exporter（additive +1）

`datasets.py` 加 `ga_ask_showcase` 條目：source `ml.ga_ask_showcase` 全欄平鋪、P4 信封、absent 容忍（表缺/空→`status:"absent"`，前端 §9 三態照 GA §10）。`check-data.mjs` 檔清單 +1。

### 7.4 MCP（additive +1，EP-D）

`get_ga_ask_showcase(scope: str | None = None, keyword: str | None = None, include_trace: bool = False)`——scope 過濾（`global`/`page:<pageId>`）、keyword 對 question/answer 過濾、trace 預設不含（省 token）。docstring 誠實紀律（沿 P4 §7 原句式）：「回傳的是平台**離線批次預先產生**的多 agent 問答範例（含逐節點 trace），**非即時推理**；live 問答在獨立部署的 demo 端點」。absent → 明確訊息。

### 7.5 監控（v1 超越點三：guardrail/reflection 指標進 Prometheus）

- **批次面（host 跑、Prometheus 刮不到程序）**：走 postgres-exporter 自訂查詢 additive +3 條（GA §8.8 同模式）：`ga_ask_showcase_rows{scope_kind}`、`ga_ask_reflection_rounds_avg`／`ga_ask_convergence_ratio`（sufficiency 達標占比）、`ga_ask_flagged_ratio`（output_flags 非空占比——應恆 0，非 0 即產線閘漏）。
- **live 面**：FastAPI 內 prometheus-client `/metrics`（P2b `rag_*` 同構命名）：`ga_ask_requests_total{outcome=ok|rejected|flagged|error}`、`ga_ask_request_duration_seconds`、`ga_ask_node_duration_seconds{node}`、`ga_ask_reflection_rounds`（histogram）、`ga_ask_guardrail_blocks_total{stage=input|output}`、`ga_ask_tokens_total{provider,kind}`、`ga_ask_cost_usd_total{provider}`（單價常數沿 P2b llm 層）。k8s Prometheus 對 Cloud Run 公網 URL 的 additional scrape＝plan 實查 #3（預設傾向做；失敗降級＝Cloud Run 內建 metrics＋README known-limit）。
- 零新 Grafana dashboard（沿 GA §8.8 判定）；零新 PrometheusRule。

### 7.6 CI

`ga-ask-ci.yaml`：paths `ml/ga_ask/**` → ruff＋pytest（guardrail 表測/check_numbers 表測/tool 白名單/graph stub-LLM 整測）＋ `docker build`（live image 可建）——沿 hello-ci/ga-insight-ci 模式。exporter/MCP 改動由既有 airflow-ci/mcp-ci paths 天然涵蓋（零改）。

---

## 8. live-demo 部署（brief 項 7；v1 就上，Fergus 2026-07-10 定案）

| 項 | 拍板 |
|---|---|
| 形態 | **Cloud Run service `ga-ask-live`**（region `asia-east1`）：單容器＝FastAPI 0.139＋同一個 `ga_ask` graph＋烘入資料/prompt＋極簡 UI。淘汰：Vercel Functions（Python graph＋120s 長請求不合）、常駐 VM/k8s 外露（違成本姿態；Cloud Run scale-to-zero 是本案唯一常識解，與 crosscut 決策 11「傾向 Cloud Run」一致） |
| **模型** | **Gemini `gemini-2.5-flash` 固定**（LLMClient `provider='gemini'` 強制）。理由＝拓撲事實：Cloud Run 摸不到 M4 host Ollama；把 Ollama 塞進容器＝8B 模型冷啟數十秒＋vCPU 推理慢到不可用。品質/成本帳：flash 單題 5–9 次呼叫、萬級 token＝美分級零頭；`provider`/`model` 在回應與 UI 如實標（誠實紀律） |
| 資料 | image build 時 `COPY frontend/public/data/ga_insight_*.json /app/data/`（同 commit 快照；`GA_ASK_DATA_DIR=/app/data`）——零雲端 DB、零回連本地叢集、與站上策展同一份資料。UI 誠實句標「資料＝GA4 公開樣本 2020-11～2021-01 靜態快照」 |
| prompt | build 時 `make ga-ask-live-build` 先從 MLflow 匯出五支 `@prod` prompt snapshot（json 檔烘入 image）；`prompt_versions` 記 build 當下版本——live 讀不到本地 MLflow 的誠實處理（§2.5） |
| guardrail 前置 | §4.3：pydantic（question ≤500 字元）→ graph 節點 1 input guardrail（16 pattern＋相關性）；同一模組零拷貝 |
| **rate-limit 接縫（follow-up 不設計死）** | `live/rate_limit.py` middleware 掛點 v1 no-op；預留 env `GA_ASK_DAILY_LIMIT`（未設＝無限制）＋ 429 回應 schema `{status:'rate_limited', retry_after}` 已定義並在 API 文件列出；日後實作只填 middleware 本體（計數存放屆時再定，不在 v1 綁死） |
| 資源/成本護欄 | `min-instances=0`（scale-to-zero；UI 標「閒置後首次請求需冷啟數秒」）、`max-instances=1`、`concurrency=4`、`timeout=120s`、memory 1Gi——max-instances=1 本身就是天然總量閘；GCP billing alert（plan 實查 #2 一併設） |
| API | `POST /ask {question: str}` → 同 §6.1 row 形（`scope:'live'`，含 trace）／`{status:'rejected', reason}`；`GET /healthz`；`GET /metrics`；`GET /`＝UI |
| UI | 單檔 `index.html`（vanilla JS，零框架零 CDN）：輸入框＋6 顆策展範例題 chip（自 questions.yaml 烘入）＋送出→進度 spinner→渲染 answer_struct＋trace 手風琴＋provider/latency/token badge＋未驗證數字警示帶（§4.2b）。頁首誠實帶：「此為獨立部署的 live 示範（Cloud Run＋Gemini），與純靜態作品集主站分離；單題約 15–30 秒」。SSE 逐節點串流列進化方向（LangGraph 原生 astream 支援，v1 不做） |
| 憑證 | `GEMINI_API_KEY` 走 Cloud Run env（由 deploy workflow 從 GitHub secret 注入）；沿 P2b fail-fast 紀律（缺 key 起服即倒） |
| 部署 | `ga-ask-live-deploy.yaml`：**`workflow_dispatch` 手動觸發**（非每 push 自動——對外部署謹慎＋控成本）：build→push GHCR→`gcloud run deploy`。URL 產出後回填 `pillars.ts ga.liveDemo`（additive 欄：`{url, deployment:'Cloud Run + FastAPI + LangGraph + Gemini', note:'獨立部署的 live 多 agent 問答'}`）——plan 實查 #2 |
| 前端呈現 | `LiveDemoCard(pillar='ga')` 落點＝`/ga` 支柱首頁＋`/ga/ask` 頁（crosscut §6.3(b) 授權）＋`/architecture` 整合卡一行（crosscut §7.2）；固定誠實句式＋hostname＋`target="_blank" rel="noopener noreferrer"`＋lucide `ExternalLink`；URL 未回填/部署失效→LiveDemoCard 降級態文案「live demo 目前離線；完整多 agent 執行過程見下方策展 trace」（沿 crosscut §12.4 同型降級） |

---

## 9. `/ga/ask` 頁 IA ＋ AskAiTeaser 產線（brief 項 8）

### 9.1 頁 IA（pageId `ga-ask`；questionTitle「不想看圖，直接問數據？」＝GA §2.2 定稿；版面用 Signal 既有元件，零新依賴）

| 序 | 區塊（registry block id） | 內容 |
|---|---|---|
| 1 | `PageHeader entryId='ga-ask'` | crosscut §5.3 契約原樣 |
| 2 | `architecture-diagram` | 多 agent 架構說明式圖：**inline JSX SVG**（8 節點 graph 圖，token 色 `var(--chart-*)`/currentColor 隨主題——沿 P4 `/architecture` 架構圖 SVG 全寬卡慣例）＋`Explainer entryId`（defaultOpen：orchestrator-worker/雙 guardrail/reflection 怎麼運作、與 `/ai-lab` RAG agent 的範式差異一句）；`related: [{route:'/ai-lab', label:'另一種 agent 範式：檢索型 CRAG →'}]` |
| 3 | `live-demo` | `LiveDemoCard(pillar='ga')`（§8 落點） |
| 4 | `qa-cards` | 策展 Q&A 卡牆（`scope==='global'` 列）：每卡＝question（h3 問句）→ answer_struct 結構化渲染（§9.2）→ meta badge 列（`Badge variant="outline"`＋Fira Code：agents_called chips/reflection_rounds/confidence/provider·model/latency/token）→ `AiComputedBadge mode="ai-narrative"`＋「離線批次產生 · {provider} · {generated_at}」（crosscut §6.3(b) 硬性）→ **`Collapsible`「逐節點 trace」**：TraceStep 直列 timeline，每步＝lucide 節點 icon（input_guardrail `ShieldCheck`/orchestrator `GitBranch`/expert `Bot`/reflection `RefreshCw`/synthesis `Combine`/output_guardrail `ShieldAlert`——emoji 禁用）＋summary＋duration＋detail 縮排明細（guardrail 檢核結果/選誰/評分/數字檢核 verified·unverified 計數） |
| 5 | `mcp-guide` | MCP 指引卡：`get_ga_ask_showcase` 用法＋誠實句（Fira Code code 塊，沿 P4 §7/`/architecture` MCP 卡慣例） |
| 6 | — | `AskAiTeaser pageId='ga-ask'`（GA §10「全 8 頁一致」消費契約，不由本 spec 改動；本頁 scope 零列→三態③縮減態，見 §9.3 裁定與 §15 給 Opus 提示） |
| 7 | — | FreshnessBanner（P4 原樣） |

**absent 態**：`ga_ask_showcase.json` absent → 區塊 4 顯示 P4 標準文案「此資料尚未由平台產出」，區塊 2/3/5 照常（架構圖/live 連結/MCP 說明不依賴資料檔）——頁面可先上骨架（P4 absent 容忍精神）。

**registry `ga-ask` 條目拍板欄**：`pillar:'ga'`、`route:'/ga/ask'`、`chapter:'問 AI'`、`questionTitle`（GA 定稿）、`aiVsComputed:'ai-narrative'`、`aiVsComputedNote` 模板「答案敘事由 LLM 離線批次生成（{provider}·{model}）；所有數字由程式自 GA insight 資料計算並經反幻覺檢核」（實值 plan 填）、`formula:'confidence = clip(mean(expert_conf) − 0.1·[未驗證數字] − 0.1·[未收斂], 0, 1)'`、blocks＝上表 4 個（`architecture-diagram`/`live-demo`/`qa-cards`/`mcp-guide`）＋`ask-teaser`；`whyBuilt`/`whatItDoes`/`howToRead`/`caveats` 全文歸 plan（crosscut §5.2 歸屬），缺欄＝gate 紅（零新 gate 機制）。

### 9.2 `answer_struct`（synthesis structured output；前端零 markdown 依賴）

```ts
type AnswerStruct = {
  conclusion: string;                                  // 2–3 句直接結論（結論先，照 ga-insight synthesis 原則）
  key_numbers: { value: string; label: string; agent: string }[];   // 關鍵數字卡（全部通過 check_numbers）
  sections: { agent: string; heading: string; text: string }[];     // 依專家分段
  actions: string[];                                   // 1–3 條行動建議
  limitations: string[];                               // gaps 誠實段（未收斂/低信心專家加註——照 :338/:353 精神）
};
```
`answer`（純文字欄）＝struct 決定性平鋪（程式串接，非二次 LLM）——MCP/eval/搜尋消費用。ga-insight 的 markdown＋emoji 區塊標題（`graph.py:362-370`）明拒：結構化欄位＋lucide 才是本站語言。

### 9.3 AskAiTeaser 產線（消費契約＝GA §10 唯讀）

- **產什麼**：7 個分析頁（`ga`/`ga-funnel`/`ga-cart`/`ga-customers`/`ga-churn`/`ga-attribution`/`ga-products`）各 **3 則**單領域 Q&A，`scope='page:<pageId>'`；跑同一個 graph、`allowed_agents=[該頁主專家]`（§3.1 對應表；`ga-cart`→funnel）——orchestrator/reflection 只能在鎖定集內動作，trace 照樣真實。題目在 `questions.yaml` 逐題定稿（plan 撰寫題文，本 spec 鎖數量/範圍/機制）。
- **`page:ga-ask` 不產**：`/ga/ask` 本體即完整問答，teaser 落 GA §10 三態③縮減態（合法態）；此舉零改 GA 消費契約。附帶觀察給 Opus：縮減態下 ga-ask 頁尾會出現指向自身的「完整多 agent 問答 →」連結——若嫌冗餘，GA plan 落頁時跳過該頁 teaser 是一行調整，屬 GA 側裁量（§15#5）。
- registry 各頁 `ask-teaser` block 的 `aiVsComputedNote` 由問 AI plan 依實際 provider 填（GA §10 原句）。

---

## 10. 取材界線表（進化非複刻；file:line 見 §0.2）

| 素材 | 取的邏輯 | 重造／進化 | 明拒 |
|---|---|---|---|
| `graph.py` 節點鏈與條件邊 | 6 功能節點＋2 end、reflection 迴圈上限 2、output retry 1、orchestrator 選 1–4、補選 ≤2、錯誤隔離 | ThreadPoolExecutor→**Send fan-out（LangGraph 原生）**；LLM 呼叫→P2b LLMClient；`stream_analysis` 只 yield 不存→**trace 持久化＋前端全揭露**；Streamlit runtime→平台批次＋Cloud Run live | `_parse_json_from` 手刻 JSON 撈取（`:92-102`）——改 structured output |
| `graph.py` reflection（`:287-289`） | sufficient/gaps/additional 三件套形狀 | **sufficiency 0–1 評分＋三停止條件＋收斂率進指標**（模糊布林→可稽核） | — |
| `graph.py` synthesis（`:306-383`） | 結論先/交叉驗證/信心加權/gaps 誠實段 | markdown 自由文→**answer_struct 結構化**（機器可讀、前端零 md 依賴）；confidence 改程式合成式（§2.4） | emoji 區塊標題（`:362-370`）；「金額加元」等在地化格式指示（我方在前端層排版） |
| `guardrails.py` input（`:31-59/:145-166`） | 12 條 injection pattern 全集、關鍵字＋LLM 二次相關性（保守放行） | ＋4 條增補（chat-template token/unicode 剝除等，§4.1）；規則集單一模組批次/live 共用；命中記 trace | 日期範圍檢查（`:133-202`）——v1 API 無日期參數 |
| `guardrails.py` output（`:207-301`） | PII 5 pattern＋遮蔽；`_check_numbers` 「答案數字須在 tool_results 有根據」核心思想 | **豁免集顯式化（撤 <100 全豁免）、百分比/容差規則明確、策展零容忍（撤 >3 才擋）、純函式可測**（§4.2） | runtime LLM answer-relevance（`:303-326`）——不可測且慢，職責移離線 judge |
| `_base_sub_agent.py` | SubAgentResult 形狀（tool_results/key_findings/confidence）、`_synthesize` 單呼叫形 | 專家＝決定性全 tool fan-out＋單次 findings（§3.2 裁定） | 內層 LLM 選 tool 迴圈（`:19/:114-148/:235-310`）——預聚合資料下純負債 |
| 六專家名與 tool 三件套 | 專家命名/職責切分/每專家 3±1 tool 的粒度 | tool 重繫結到 GA §8.3/§8.4 資產（§3.4 十七支）；讀 JSON 合約檔非打 DB | geo/cohort 等我方資料不支撐的 tool（§3.1）——不硬撐 |

---

## 11. 驗收清單（每條可實跑；隨問 AI plan 生效，與 crosscut §11/GA §12 累加）

| # | 檢查 | 方法 | 預期 |
|---|---|---|---|
| 1 | guardrail 表測 | pytest：16 pattern×正反例＋unicode 夾帶＋離題/相關題 | 全綠；injection 全攔 |
| 2 | check_numbers 表測 | pytest §4.2 六類案例（含「捏造小百分比」原碼漏檢靶） | 捏造全 flag、合法全過 |
| 3 | tool 邊界 | pytest：JsonMartRepo 存取檔名 ⊆ 12 檔白名單；`grep -r "dmp_\|yt_\|ptt_" ml/ga_ask/src/` 零命中 | 綠；零越界 |
| 4 | graph 整測（stub LLM） | 決定性假 LLM 跑：正常題（選專家→收斂→過檢）/注入題（end_rejected、零 LLM 呼叫）/捏數題（flag→重試→仍 fail 不入 showcase）/reflection 補選題 | 四路徑全綠；trace 步序正確 |
| 5 | 批次煙囪（真 Ollama） | 12 檔就位後 `make ga-ask-showcase` 取 3 題子集 | 表有列、`output_flags` 全空、provider 如實 |
| 6 | 評估閘反例 | 對 fixture 注入一列捏造數字重跑 eval | **make 非零退出、表未被覆寫**（阻擋級證明） |
| 7 | 匯出＋信封 | 觸發 export → `ga_ask_showcase.json` 信封合規、≤3MB、rows 含 §6.1 全欄 | 綠 |
| 8 | absent 容忍 | 暫移 ga_ask_showcase.json 重 build | build 綠；`/ga/ask` qa-cards 顯示標準缺席文案；teaser 走 GA #10 既有斷言 |
| 9 | 前端 gate＋頁面 | `npm run gate:explainers && npm run build`；目視 `/ga/ask` 七段 IA、每卡 AiComputedBadge＋generated_at、trace 展開、lucide 無 emoji | gate 綠（ga-ask 條目/4 blocks）；逐項目視 |
| 10 | live 端點 | 部署後 curl：`/healthz` ok；`POST /ask` 正常題回 §6.1 形（scope='live'）；注入題回 rejected 且 `/metrics` `ga_ask_guardrail_blocks_total` +1 | 三項全符 |
| 11 | live 誠實標 | 目視 UI 頁首誠實帶＋provider·model badge；站上 LiveDemoCard 固定句式全文＋hostname＋`rel="noopener noreferrer"`（grep） | 逐項符 |
| 12 | 成本護欄 | `gcloud run services describe ga-ask-live`：max-instances=1、min-instances=0、timeout=120s | 三值正確 |
| 13 | 指標 | postgres-exporter +3 條查詢有值；live `/metrics` 含 §7.5 指標名 | 全在 |
| 14 | teaser 產線覆蓋 | SQL：`scope like 'page:%'` 的 distinct pageId＝7 個分析頁、各 ≥2 列；`page:ga-ask` 零列 | 符 §9.3 |

---

## 12. plan 期待查證點（皆帶預設傾向與降級；非阻擋本 design 收斂）

1. **P2b LLMClient 實際 import 錨（brief 指名）**——今日接地實況：`ml/` 空、`docs/plans/` 空，P2b 只有 design 合約（§0.3 誠實記錄）。問 AI plan 排 P2b plan 之後；預設＝`from rag_service.llm import LLMClient`（path dep）；判準＝可無副作用 import＋簽名含 §0.3 窄介面；降級＝P2b plan 抽 `ml/llm_core/` 小套件三方共用（rag_service/ml_reco/ga_ask）。**硬合約不變：provider-switch 單一真源，禁第二實作。**
2. **live-demo 部署 URL 與成本（brief 指名）**——部署後回填 `pillars.ts ga.liveDemo.url`；GCP billing alert 一併設（預設 $5/月 warn）；flash 實測單題 token/成本記進 README（不預先宣稱數字）。失效降級＝LiveDemoCard 離線態文案（§8）。
3. **k8s Prometheus scrape Cloud Run 公網 `/metrics`**——預設 additional scrape config（static target）；跨網不穩降級＝Cloud Run 內建 metrics＋known-limit（§7.5）。
4. **qwen3:8b structured output 品質**（Ollama format/json schema）——預設可用（Ollama 0.31 支援）；解析失敗率高降級＝該節點自動改走 Gemini fallback（LLMClient 現成機制），provider 如實記。
5. **Send fan-out＋reflection 迴圈重入的 reducer 語意實跑 smoke**——機制 context7 已證（§0.1）；邊角＝二輪 fan-out 對 `expert_results`/`trace` append 的順序穩定性，graph 整測（驗收 #4）覆蓋；異常降級＝單節點內 `asyncio.gather`（graph 形狀不變，只損 Send 的原生 trace 粒度）。
6. **showcase 檔實際體積**——預估 300–600KB；超限先調 `tool_digest_rows`/digest 截斷（params.yaml 兩鍵），仍超才議 trace 拆檔（`_v2` 政策外的 additive 新檔，非改信封）。
7. **prompt snapshot 匯出流程**——`make ga-ask-live-build` 內以 mlflow client 匯出五支 @prod 成 json；MLflow 不可達時 build fail（不烘過期 prompt——fail-fast）。
8. **31 題題文定稿**——本 spec 鎖數量/scope/allowed_agents 機制；題文由 plan 撰寫並跑 §5 閘驗證（input guardrail 100% 通過即合格判準）。

---

## 13. 本 spec 拍板 vs 下放對照表

| 主題 | 本 spec 拍板 | 下放 plan |
|---|---|---|
| graph | 節點/邊/Send fan-out/State 全欄/reflection 評分與停止條件/溫度/retry/timeout/並行度 | prompt 全文、Send 邊角 smoke（實查 5） |
| 複用邊界 | §0.3 窄介面合約＋單一真源鐵律＋主/降級路徑 | import 錨實查（實查 1） |
| 六專家/tool | 職責/17 支 tool/資料對應/JsonMartRepo/決定性 fan-out 裁定/digest 上限 | tool 回傳 dict 的逐鍵實作 |
| guardrail | 16 pattern 全集/相關性機制/PII/check_numbers 規格（豁免/容差/政策）/live 前置 | 測試表案例補齊 |
| 評估閘 | 四閘與門檻/未過處置/MLflow experiment/晉升閘 | adversarial 題文、judge rubric 全文 |
| trace/表/匯出 | rows additive 六欄/TraceStep 全欄/DDL/exporter 條目/MCP 工具面/體積控制鍵 | exporter SQL、體積校準（實查 6） |
| 批次產線 | make target 流程/不開 DAG 裁定/二次匯出語意/CI | Makefile 細節、runbook |
| live-demo | Cloud Run 形態/Gemini 固定/資料與 prompt 烘入/資源與成本護欄/rate-limit 接縫/API 面/UI 形/部署 workflow/pillars.ts 欄 | URL/成本回填（實查 2）、UI 文案定稿 |
| `/ga/ask`＋teaser | 七段 IA/4 blocks/answer_struct schema/registry 拍板欄/teaser 產線（7 頁×3、主專家鎖定、ga-ask 不產） | whyBuilt/whatItDoes/howToRead/caveats 全文、31 題文（實查 8） |

---

## 14. 精確度契約 8 條自檢

1. **開放問題收斂**：brief 8 項全數單一決定（§1 總表＋§2–§9），零 TBD/兩案並陳；§12 八點皆 plan 前實查性質且帶預設傾向＋判準＋降級（含 brief 指名的兩點）。對 brief 傾向的唯一偏離（不開 DAG）帶完整論證與回退成本（§7.2）。
2. **版本＋context7 查證**：LangGraph Send（本檔唯一新 API 面承重宣稱）當日 context7 查證且官方範例與本 graph 同構（§0.1）；FastAPI/uvicorn 新 pin 標當日 PyPI 現值；LangGraph/langchain-*/Ollama/模型 pin 全沿 P2 §0＋EP-J 不重議；前端零新依賴。
3. **資料契約欄位級**：State/ExpertResult/ToolCall（§2.2）、TraceStep（§6.2）、rows additive 六欄（§6.1）、DDL＋唯一鍵（§6.3）、answer_struct（§9.2）、params.yaml 全鍵（§7.1）、17 支 tool 輸入輸出（§3.4）——皆標穩定政策（信封 additive-only）。
4. **部署形狀具體**：檔案佈局（§7.1）、make 流程（§7.2）、Cloud Run 全參數與 workflow（§8）、exporter/MCP/監控 additive 落點（§7.3–7.5）、CI（§7.6）。
5. **沿用慣例不重造**：P4 信封/absent/MCP 誠實句式、P2 §10 prompt registry/eval/promote 閘、P6 params.yaml/gen-* host 批次慣例、GA §8.4 TRUNCATE-insert/§8.8 postgres-exporter 模式、crosscut §5 registry/gate/AiComputedBadge/LiveDemoCard、Signal Collapsible/Badge/Fira Code/lucide。
6. **進化非複刻**：§10 逐素材三欄（取/重造/明拒），三個 v1 超越點（trace 全揭露/收斂嚴謹化/指標進 Prometheus）各有落點（§6/§2.3/§7.5）；另兩項裁定砍原碼弱點（內層 tool 迴圈、runtime LLM relevance）皆帶論證。
7. **硬約束貫徹**：拓撲（靜態站零 live LLM——live 是外連獨立端點；四件套齊）、複用 P2b（§0.3 單一真源鐵律）、只 additive（P2b graph/GA marts/AskAiTeaser 消費契約/信封零改；`ga_ask_` 前綴）、反幻覺（§4.2 純函式＋策展零容忍＋LLM 只敘事）、registry 阻擋級（§9.1 條目、缺欄 gate 紅）、emoji→lucide（§9.1/§10 明拒）、進化方向不做 v1（六專家 tool 開 MCP 共用層、跨支柱問答、SSE 串流、per-day rate-limit——全列明非遺漏）、非互動不提問（全檔零待問）。
8. **每步可測**：§11 十四條全給命令/pytest/SQL/目視程序，含兩個阻擋級反例實跑（#4 捏數路徑、#6 閘紅不覆寫）。

---

## 15. 給 Opus 的把關提示（覆核建議點）

1. **不開新 DAG（§7.2，對 brief 傾向的唯一偏離）**：依據 P2 §13 M4 界線明文＋`gen-rag-showcase`/`gen-reco-reasons` 兩先例；回退＝KPO 包一層（ExternalName 打 host Ollama，graph 零改）。請覆核此裁定或翻正。
2. **P2b 複用的接地實況（§0.3）**：brief 假設可 grep P2b 實碼，實況＝`ml/` 空、P2b 尚未實作——本 spec 以「design 合約錨＋窄介面＋單一真源鐵律＋plan 序（P2b plan 先行）」處理。請確認此為可接受的複用證明形式，並在排 plan 佇列時落實「P2b plan → 問 AI plan」順序。
3. **專家內層 LLM 選 tool 迴圈砍除（§3.2）**：對 ga-insight 的最大結構性偏離——理由是資料面差異（預聚合千列 JSON vs 打大 DB）。若認為「展示 tool-calling agent」敘事價值高於決定性，回退＝專家改 LLM 選 tool 單輪（不迴圈），tool 層不變。
4. **live 端點固定 Gemini（§8）**：拓撲事實（Cloud Run 摸不到 host Ollama）；「batch=Ollama 零成本、live=Gemini」的雙形態已在 UI/trace 誠實標 provider。確認此敘事姿態可接受（我方判斷：是——這本身就是「同一 graph、兩種部署形態」的架構故事）。
5. **`page:ga-ask` 不產 teaser 列（§9.3）**：GA §10「全 8 頁一致」下 ga-ask 頁尾 teaser 會落縮減態並出現自指連結——建議 GA plan 落頁時跳過該頁 teaser（GA 側一行裁量，非本 spec 越權改其契約）。
6. **runtime 砍 LLM answer-relevance（貫穿裁定③）**：職責移離線 judge；若堅持 runtime 全檢，加回一次呼叫即可（graph 尾插節點，State 已留 guardrail_output 擴充位）。

---

## 16. Opus 把關（2026-07-10；規劃者覆核，PASS）

**結論：PASS，可進 plan 佇列（spec-only，plan 延後）——但帶一條硬性排序依賴，見下。** 三份支柱 design 中工程密度最高的一份；精確度契約 8 條逐條符合，資料契約做到欄位級（State/TraceStep/rows/DDL/17 tool），部署形狀具體（Cloud Run 全參數＋make 流程＋CI），驗收含兩個阻擋級反例實跑（捏數路徑不入 showcase、閘紅不覆寫表）。

**承重宣稱獨立覆核（context7 `/websites/langchain_oss_python_langgraph` 2026-07-10，我方獨立重查非採 agent 自報）→ CONFIRMED**：LangGraph `Send` orchestrator-worker fan-out 三腿全對——①`from langgraph.types import Send`＋conditional edge 回傳 `[Send(...)]` 官方範例逐行同構；②`add_conditional_edges(orchestrator, assign_workers, [worker])`＋`add_edge(worker, next)` fan-in 與 §2.1 一致；③`Annotated[list, operator.add]` reducer 與 State `expert_results`/`trace` 一致。graph 機制為官方正典 pattern。LangGraph/模型 pin 沿 P2 §0＋EP-J，前端零新依賴，不重查。

**六風險點裁定：**
1. **不開新 DAG，改 host make target（§7.2，對 brief 傾向唯一偏離）→ 核准。** P2 §13 明文「host LLM 批次＝make target 不進 Airflow」＋兩先例（`gen-rag-showcase`/`gen-reco-reasons`）論證強；且比 GA `ga_insight_batch` schedule=None 更誠實——開 schedule=None DAG 反而立第三種假排程形狀。回退（KPO 包 ExternalName 打 host Ollama、graph 零改）已備。
2. **P2b 尚無實作碼（§0.3）→ 核准處理方式，並鎖定硬性排序依賴。** agent 第一手 grep 誠實揭露 trend repo `ml/` 空、P2b 只有 design 合約，改鎖 P2 design 合約錨＋窄介面＋**「provider-switch 全 repo 單一真源、禁第二實作」鐵律**——這是接地紀律的典範（不假裝 grep 到不存在的碼）。**Opus 硬性裁定：plan 佇列必須落實「P2b plan → 問 AI plan」順序依賴，問 AI plan 不得先於 P2b plan 執行**（否則 `from rag_service.llm import LLMClient` 無標的）。降級（P2b plan 抽 `ml/llm_core/` 三方共用）屬檔案落點微調，不動合約。→ 已記 memory plan backlog。
3. **砍專家內層 LLM 選 tool 迴圈，改決定性 fan-out＋單次 findings（§3.2，對 ga-insight 最大結構偏離）→ 核准。** 理由紮實：我方 tool 讀預聚合千列 JSON、全取零成本，LLM 選 tool 純負債；砍後專家可單測可重現、live 延遲 3–9×↓，而 agentic 展示保留在真正的主角（orchestrator 選專家＋reflection 補專家）。符合 grounding＋成本＋可測性三線。回退已備。
4. **live 固定 Gemini（batch Ollama／live Gemini 雙形態，§8）→ 核准。** 拓撲事實（Cloud Run 摸不到 M4 host Ollama、塞 8B 進容器冷啟慢到不可用），provider/model 在 UI/trace 誠實標；「同一 graph 兩種部署形態」本身是架構故事，flash 成本零頭＋scale-to-zero。
5. **`page:ga-ask` 不產 teaser（§9.3）→ 核准，記 GA plan 落頁提示。** GA §10 三態③縮減態合法；自指連結冗餘由 GA plan 一行裁量，非本 spec 越權改其消費契約。
6. **runtime 砍 LLM answer-relevance（貫穿裁定③）→ 核准。** 移離線 judge（§5 已有 relevance ≥3.5 hard 閘，職責不漏）；runtime 只留決定性檢核（PII＋數字），延遲受益。回退（尾插節點）已備。

**特別嘉許（符合鐵律，記錄以利複用）**：①**反幻覺 `check_numbers` 進化**——第一手揪出 ga-insight `_check_numbers` 兩缺陷（`<100` 全豁免致小百分比逃檢、`>3 flags` 才擋），改純函式＋顯式豁免集＋容差規則＋策展發佈零容忍，落成可測斷言，是本 spec 最重要正確性面（[[llm-grounded-feature]]）；②**input guardrail 增補理解威脅模型**——加 chat-template 控制 token（qwen 系 Ollama 的注入面、ga-insight 用 Gemini 沒此問題）＋unicode 剝除，非照抄；③評估閘「不寫表」使壞批次進不了站、單一 `JsonMartRepo` 四消費者零漂移——皆紮實工程判斷。

**知會 Fergus（須知道，非阻擋）**：問 AI live-demo 是**獨立 Cloud Run 端點跑真 Gemini 推理**（不是靜態站的一部分）——需 `GEMINI_API_KEY`（GitHub secret）、手動 `workflow_dispatch` 部署、GCP billing alert（預設 $5/月 warn）；成本＝flash 零頭＋scale-to-zero，v1 無 per-day 上限（只留接縫，follow-up 補）。此為你 2026-07-10 定案「功能完整優先、成本不設限、上限之後補」的落地。
