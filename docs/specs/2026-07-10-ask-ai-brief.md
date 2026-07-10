# 問 AI agentic 分析問答 spec — brief（多 agent 分析問答：策展 trace + 架構圖 + MCP + v1 就上 live-demo；複用 P2b 不重造）

> **精確度契約**：依 repo `CLAUDE.md`「Fable 5 design 精確度契約（8 條）」交辦；design 逐條自檢，開放問題收斂成決定不下推。
> **框架上游（binding，不得抵觸；本 spec 是四支柱 spec 序列的最後一份）**：
> - [統一作品集 crosscut design](2026-07-10-unified-portfolio-crosscut-design.md)——**本 spec 的合約框架**。逐條綁定：**§6 全節**（§6.1 接地基準與進化界線／§6.2 P2b 複用邊界「裁定：複用不重造」／§6.3 兩層 AI 形態／§6.4 拓撲四件套＋`ga_ask_showcase.json` 信封 rows 骨架＋live-demo v1 就上／§6.5 範圍歸屬＝本 spec 待拍板清單）、§7.2（live-demo 外連呈現慣例＋v1 配置）、§5（說明式 registry：`/ga/ask` 與每則 AI 卡掛 `AiComputedBadge`）、決策 9/10/11（複用 P2b／獨立 spec／live-demo v1 就上）、§0 pin 表（前端零新依賴）。
> - [GA 支柱 design](2026-07-10-ga-pillar-design.md)——**本 spec 吃它的頁面/資料接縫**：§2.2（`/ga/ask` route/pageId/questionTitle）、§8.3（9 marts）＋§8.4（4 ml 表）＝六專家 tool 的資料源、§8.6（12 datasets）、§8.7（MCP 5 工具現況，本 spec additive +1）、**§10（每頁 `AskAiTeaser` 接縫：位置/資料契約 `scope==='page:<pageId>'`/三態——本 spec 定其產線，不改其消費契約）**、§9（registry `ga-ask` 條目與各頁 `ask-teaser` block 已列覆蓋清單，本 spec 定其內容）。
> - [Signal 設計系統 design](2026-07-10-frontend-design-system-design.md)——視覺 token/元件/字階地基，不重定；`/ga/ask` 頁與 trace 展開 UI 用既有元件（Collapsible、Badge、Fira Code code 塊、說明式 SVG 慣例沿 P4 `/architecture`）。
> - **P2b 基建（已建，唯讀複用邊界）**：[P2 ML verticals design](2026-07-08-P2-ml-verticals-design.md)——P2b CRAG 檢索型 agent 的 LLMClient（Ollama `qwen3:8b` host／Gemini fallback）、prompt registry（MLflow）、評估閘、token/成本/延遲 Prometheus、k8s→host ExternalName 接線。**問 AI graph 複用這套 LLMOps 治理，不獨立起爐灶。**
> **接地鐵律（grounding-first，違者作廢）**：Fable 5 設計階段須**第一手 grep**：
> - ga-insight agents（`/Users/fergus/Desktop/workshop/fergus/llm-workshop/ga-insight/src/agents/`）：`graph.py`（StateGraph 8 節點＝6 功能＋2 end、`MAX_REFLECTION_ROUNDS`、orchestrator 選 sub-agent、`ThreadPoolExecutor` 並行）、`guardrails.py`（input 12 條 prompt-injection pattern＋業務相關性、output PII＋`_check_numbers` 反幻覺數字檢核）、`sub_agents/`（六專家：anomaly/customer/funnel/product/risk/traffic，`_base_sub_agent.py` 基類、各專家 `tools/`）。**取 orchestrator-worker＋雙 guardrail＋reflection 的邏輯形狀；重造工程層**（LLM 走 P2b LLMClient 非直呼、指標進 Prometheus、trace 持久化、跑平台批次非 Streamlit runtime）。
> - P2b 實作（trend repo 內，`services/`／`ml/` 下 P2b LangGraph graph 落點——先 grep 定位）確認 LLMClient/prompt registry/評估閘的**實際 import 路徑與函式簽名**，證明複用可行非空談。
> - 版本敏感處 context7（LangGraph StateGraph API、FastAPI live-demo 端點若新 pin）。P2b 已 pin 的 LangGraph/Ollama 沿用不重查。
> **本階段只出 spec，plan 延後。**

---

## 一句話目標

問 AI 支柱＝**多 agent 分析問答的展示**：一個複用 P2b LLMOps 基建的新 LangGraph graph（orchestrator-worker＋雙 guardrail＋reflection，六專家讀 GA Gold/insight marts），以**四件套**呈現——①平台端批次預產的策展 Q&A 靜態 JSON（含**逐節點 trace 全揭露**，ga-insight 不給看的 graph 內部我方全開）②多 agent 架構說明式圖 ③MCP 工具 ④**v1 就上的 live-demo 外連**（獨立 Cloud Run 端點跑真 LangGraph agent，input guardrail 前置，誠實標「獨立部署」，per-day rate-limit 列 follow-up）。**靜態站本身零 live LLM**；兩層 AI（每頁 `AskAiTeaser` 摺疊區＋獨立 `/ga/ask` 頁）。

## Fable 5 要收斂拍板的項目（crosscut §6.5 明列＝以下清單；逐一給明確決定）

1. **問 AI graph 節點與狀態機**：複用 P2b LangGraph 框架，定本 graph 的節點鏈（對照 ga-insight `graph.py` 8 節點的邏輯形狀：input_guardrail→orchestrator→run_sub_agents→reflection→synthesis→output_guardrail）、State schema（欄位級）、reflection 收斂條件**嚴謹化**（crosscut §6.4 已納 v1：sufficiency 明確評分＋停止條件，非 ga-insight 的模糊 gaps 判斷）、`MAX_REFLECTION_ROUNDS` 拍板值。明標「複用 P2b 的哪些（LLMClient/prompt registry/評估閘/Prometheus）、新建的哪些（graph 本體/六專家 sub-agent/tool 層/trace schema）」。
2. **六專家 sub-agent 與 tool 層**：六專家（anomaly/customer/funnel/product/risk/traffic，對齊 ga-insight `sub_agents/`）各自的**職責邊界＋讀哪些 GA 資產**（tool 讀 GA design §8.3 marts／§8.4 ml 表，欄位級對應）；orchestrator 選 1–4 專家的選擇邏輯；並行執行形態（對照 `ThreadPoolExecutor`，重造為平台批次的等價形）。**tool 只讀不寫、只讀 GA insight 資產**（不越界 P7 dmp/YouTube）。
3. **雙 guardrail 規則集**：input guardrail（prompt-injection pattern 清單＋業務相關性判斷——取材 `guardrails.py` 12 條，可增補但列出全集）；output guardrail（PII 檢核＋**`_check_numbers` 反幻覺：答案中每個數字須在 tool_results 有根據，否則標記/攔截**——此為 grounding 鐵律核心，規則要能落成可測斷言）。**live-demo 端點的 input guardrail 前置**同一套規則集。
4. **評估閘門檻**：複用 P2b 評估閘結構，定問 AI 的發佈門檻（如答案數字命中率／guardrail 通過率／reflection 收斂率）；未過閘的處置。
5. **trace schema 全欄（前端揭露）**：`ga_ask_showcase.json` rows 骨架（crosscut §6.4 保留欄：`scope/question/answer/agents_called/reflection_rounds/guardrail{input_passed,output_flags}/confidence/provider/latency_ms/token_usage/generated_at`）**只准 additive 擴**——定擴哪些欄（如逐節點 trace 步驟陣列供前端展開 orchestrator 選了誰/reflection 幾輪/guardrail 結果）；欄位級型別。
6. **批次產線 DAG／make target**：平台端 host 跑完整 graph（Ollama 零成本，沿 P6 `make gen-reco-reasons` 慣例）→ 結果落 `ml.ga_ask_showcase` 表 → exporter additive 條目 `ga_ask_showcase.json`（P4 信封同構）。定策展問題集來源（global 範圍問題＋各 GA 頁 `page:<pageId>` 範圍問題）、DAG 形狀（schedule 傾向 None 手動，同 GA `ga_insight_batch`）、make target、CI。**全 additive**（不改 P2b graph、不改 GA marts）。
7. **live-demo 部署拍板（v1 就上，Fergus 2026-07-10 定案）**：獨立部署端點（傾向 Cloud Run＋FastAPI 包 LangGraph agent）跑**真 live 推理**；**input guardrail 前置**（§3 同規則集，擋 prompt-injection）；`LiveDemoCard` 誠實標「此連結開啟另一個獨立部署…本站為純靜態展示，不依賴該服務」＋顯示 hostname＋`rel="noopener noreferrer"`；`pillars.ts` `ga.liveDemo`（或問 AI 專屬落點）URL plan 期回填、失效降級態文案。**per-day 執行次數上限＝follow-up**（v1 不做，但 spec 要留「日後接上限」的接縫位置，不設計死）。部署形態細節（模型：live 端點用 Gemini 還 Ollama？成本 vs 品質）由本 spec 拍板。
8. **`/ga/ask` 頁 IA ＋ 每頁 `AskAiTeaser` 產線**：`/ga/ask`（crosscut §6.3(b) 已定框：策展 Q&A 卡牆＋逐節點 trace 展開＋多 agent 架構 SVG 圖＋MCP 指引＋live-demo 外連）逐區塊 IA；每頁 `AskAiTeaser`（GA design §10 已定**消費**契約：位置/`scope==='page:<pageId>'`/三態）的**產線**＝批次為各 GA 頁產 2–3 則單領域策展 Q&A（本 spec 定產什麼、不改 GA design 定的消費形態）。registry `ga-ask` 條目 `whyBuilt`/`whatItDoes` 與各卡 `AiComputedBadge mode="ai-narrative"`＋provider/generated_at。MCP additive +1：`get_ga_ask_showcase`（docstring 誠實紀律「離線批次預產、非即時推理」，沿 P4 §7）。

## 硬約束（違者作廢）

- **拓撲鐵律**：靜態站**零 live LLM 呼叫**；四件套（預產靜態 JSON＋架構圖＋MCP＋live-demo 外連）。live-demo 是**外連的獨立端點**跑 live agent，不破純靜態（crosscut §6.4/§7.2）。
- **複用 P2b 不重造**（crosscut 決策 9/§6.2）：LLMClient/prompt registry/評估閘/Prometheus/k8s→host 接線全複用；**agent 框架只 LangGraph**，不引 CrewAI/AutoGen 第二框架。
- **只 additive**（EP-D）：新建 = 問 AI graph 本體／六專家 sub-agent＋tool／trace schema／`ml.ga_ask_showcase` 表／exporter 條目／MCP +1／DAG／`/ga/ask` 頁＋`AskAiTeaser` 產線。**不改** P2b graph、GA marts/ml 表、GA design §10 定的 `AskAiTeaser` 消費契約、`ga_ask_showcase.json` 信封（rows 骨架只准 additive 擴）。dataset 前綴 `ga_ask_`（crosscut 決策 13）。
- **反幻覺鐵律**（grounding-first 核心，符 [[llm-grounded-feature]] 精神）：答案數字由程式算的 tool_results 提供，LLM 只敘事；output guardrail `_check_numbers` 落成可測斷言——**這是本 spec 最重要的正確性面**。
- **進化非複刻**：取 ga-insight graph 的邏輯形狀，重造工程層（P2b 接線/Prometheus/trace 全揭露/批次跑）；trace 全揭露、reflection 收斂嚴謹化、guardrail/reflection 指標進 Prometheus＝crosscut §6.4 已定的三個 v1 超越點。
- **說明式 registry 阻擋級**（§5）：`/ga/ask` registry 條目缺 `whyBuilt`/`whatItDoes` = gate fail；每則 AI 敘事卡掛 `AiComputedBadge`＋generated_at。**emoji→lucide**。
- **進化方向不做 v1**（crosscut §6.4 裁定）：六專家 tool 開成 MCP 共用層（資料面需先統一）、跨支柱問答（問趨勢/PTT）——列進化方向，非遺漏。

## Scope

- **in**：問 AI graph 節點/狀態機/reflection 收斂、六專家 sub-agent 職責與 tool 資料源、雙 guardrail 規則集、評估閘、trace schema 全欄、批次產線 DAG/make/CI、`ml.ga_ask_showcase` 表與 exporter 條目、MCP +1、live-demo 部署拍板（v1 就上＋input guardrail＋rate-limit 接縫）、`/ga/ask` 頁 IA、每頁 `AskAiTeaser` 產線、registry `ga-ask`＋`ask-teaser` 內容、驗收（含反幻覺數字檢核可測、absent 容忍）。
- **out**：P2b graph 改動、GA marts/ml 表改動、GA design §10 `AskAiTeaser` 消費契約改動、Signal token 重定、GA 支柱分析頁 IA（GA design 已定）、per-day rate-limit 實作（follow-up，只留接縫）。

## 產出

寫到 `docs/specs/2026-07-10-ask-ai-design.md`；檔頭指向本 brief＋精確度契約＋crosscut §6＋GA 支柱 design。附「plan 期待查證點」（含 live-demo 部署 URL/成本、P2b import 路徑實查）與「本 spec 拍板 vs 下放 plan」對照表。**不 git commit**（Opus 把關後處理）。完成回報：檔案路徑、8 項拍板摘要、context7/grep 查證項清單（尤其 P2b 複用可行性的實際 import 錨點、ga-insight graph/guardrails file:line）、給 Opus 覆核的風險點。
