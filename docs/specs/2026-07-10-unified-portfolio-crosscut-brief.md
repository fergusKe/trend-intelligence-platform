# 統一資料作品集 程式 crosscut — 交給 Fable 5 的 spec brief

> **交付流程**：Fable 5 讀本 brief + NORTH_STAR「統一資料作品集重定位」段 +（接地）既有合約 → `superpowers:brainstorming` → 產出 `docs/specs/2026-07-10-unified-portfolio-crosscut-design.md` →（**本階段只出 spec，plan 延後**）。
> **精確度契約**：產出的 design 必須滿足 `../../CLAUDE.md`「Fable 5 design 精確度契約（8 條）」。**尤其第 6 條「進化非複刻」是本 brief 的靈魂**——見下。
> **接地已由規劃者（Opus）完成**：ga-insight（Streamlit 自我說明模式 + analytics 引擎 + 章節 IA）、ptt-search（ES 全文檢索 + Tailwind 前端）、trend 平台既有 11 頁/合約/拓撲，皆已 grep 到 file:line（見各節）。Fable 5 設計階段仍須自行 grep 補齊 + context7 查版本。
> **定位（本 crosscut 的角色）**：這是**統一作品集的脊椎**——定四支柱 IA、主題切換、整合模式落法、**說明式內容 registry schema**、退役/取材接法、建置序、列後續 spec。它**不**細設 GA/搜尋支柱的每一頁（那是各支柱 spec 的事），只定**跨支柱的共用契約與框架**。

## 一句話目標

把三份分散求職作品（ga-insight GA 分析 / ptt-search 搜尋 / trend DE-MLOps）收攏成**一個站、四支柱主題切換**的統一資料作品集——直接展示這個網站就涵蓋全部能力，取代 ga-insight、納入 ptt-search 搜尋。本 crosscut 定框架，各支柱 spec 填內容。

## ⚠️ 靈魂原則：進化非複刻（Fergus 明令，寫進 design 每個設計判斷）

- **參考 ≠ 照抄**：ga-insight 的章節敘事（截圖：業績全貌→認識客群→找到問題→立刻行動→問 AI、問句式標題、漏斗為核心）是**輸入與靈感，不是天花板、不是要複製的清單**。Fable 5 **要規劃我方更完整、更好的 IA 與功能流程**，不是把 ga-insight 的頁重畫一遍。
- **不必每頁同模板**：頁面依內容給**最合適的版面**（漏斗頁、KPI 總覽頁、分群頁、AI 問答頁本就該長得不一樣）——Signal 設計系統給的是 token/元件/風格一致性，**不是要求版面千篇一律**。variety-with-coherence。
- **更完整**：既然有 Fable 5，GA 分析要**比 ga-insight 更完整**（更嚴謹的漏斗/歸因/分群/LTV 方法、更誠實的 AI-vs-程式標註、更結構化的自我說明），而非追平。
- 這條對應精確度契約第 6 條「進化非複刻：取材既有專案原始碼時，標清取什麼邏輯 vs 重造哪個工程層」——**每個取材點都要標「取靈感/邏輯什麼、我方如何做得更好」**。

## 四支柱 IA（本 crosscut 要拍板的框架）

| 支柱 | 是什麼 | 內容來源 | 本 crosscut 要定 |
|---|---|---|---|
| 🔍 **搜尋** | 搜尋工程展示 | 取材 ptt-search ES 全文檢索敘事 | 支柱在統一站的呈現框架（fuse.js 快速搜 + live-demo 外連 + 誠實敘事的分工）；細節 → 搜尋支柱 spec |
| 📊 **GA 分析** | 比 ga-insight 更完整、**漏斗為核心**的 GA 分析 | 取材 ga-insight analytics 引擎邏輯（唯讀）+ 跑公開 GA4 sample | 支柱在統一站的框架與它與 P6/P7 既有 GA 頁（`/audience`）的邊界；細節 IA/頁清單 → GA 支柱 spec |
| 📈 **趨勢智能** | 現有 11 頁（**全數保留**，Fergus 明示每頁都重要） | 沿 P4/P6/P7 合約，零改 | 只定它作為一支柱如何被主題切換納入 |
| 🏗 **平台架構** | DE/MLOps/DevOps 敘事 | 沿 P4 `/architecture` | 只定它作為一支柱 |

**Fable 5 要收斂**：
1. **主題切換 UX**——頂層四支柱怎麼切、**當前主題如何清楚標示**（Fergus 明示「讓使用者知道當前在看哪個主題」）；與 Signal 既有 sidebar/頂欄 shell（design §1 決策 11、§4.1）如何整合成「支柱切換 + 支柱內導航」兩層；桌機/行動端形態。給具體元件與落點。
2. **URL/路由結構**——四支柱如何映射路由（`/search` `/ga` `/`（趨勢為預設首頁？）`/architecture`？或 `/trends/*`？）；既有 11 頁 route 如何歸入趨勢支柱**而不改 route**（P4/P6/P7 route 是合約，動 route = 越界；用路由分組/prefix 或 nav 分層達成，不改實體 route）——這是關鍵約束，給無衝突方案。
3. **支柱邊界**——📊GA 支柱 與 P7 既有 `/audience`（DMP 分群，也是 GA4 衍生）的關係：是 `/audience` 併入 GA 支柱、還是 GA 支柱新增頁而 `/audience` 留趨勢支柱？給裁定與理由（避免同一 GA4 資料兩處重複呈現）。

## 說明式內容 registry schema（跨全站硬性；本 crosscut 的核心產出，對標並超越 ga-insight）

> **Fergus 加碼定案（2026-07-10，硬性、阻擋級）**：**每一個功能／每一頁都必須像 ga-insight 那樣把「開發目的（我們為什麼做這個）＋這個功能有什麼（做什麼、怎麼用）」寫到完整**，讓使用者一看就懂。這**不是只 GA 支柱**——四支柱（搜尋／GA／趨勢智能／平台架構）每一頁一律適用，無例外。schema 必含**目的敘述**（`whyBuilt`：這個功能存在的理由／解決什麼）與**功能說明**（`whatItDoes`：這頁提供哪些能力、輸入輸出、怎麼操作），與下方問句式欄位並存。**驗收升為阻擋級**：任何頁面缺 registry 條目或缺 `whyBuilt`/`whatItDoes` = coverage gate 失敗、不得 ship。

- **現況**：既有「說明式 UI 三層元件」（InfoTooltip/ChartCaption/Explainer，正典路徑 `frontend/src/components/explainers/`，見 NORTH_STAR 說明式 UI 段）＝**容器**；但**內容散在各頁 inline**（Signal design §6 只定視覺）。
- **ga-insight 的模式（唯讀接地，`src/components/ui_utils.py:23-52` `render_page_header`）**：每頁 5 欄 `{chapter, title(問句), description(怎麼看), can_do(gain), problem(pain)}` + inline `help=`/`caption` 的公式+實例。**弱點**：文案 inline、無集中 registry、無 formula/dataSource/caveats 一級欄位、無 AI-vs-程式的結構化標註。
- **本站超越法（Fable 5 要設計）**：把說明升為**集中式 registry**（keyed by feature/page/chart id），schema 至少含：`{ pillar, chapter, questionTitle, whyBuilt, whatItDoes, howToRead, canDo, problem, formula?, dataSource, caveats?, aiVsComputed }`（`whyBuilt`＝開發目的、`whatItDoes`＝功能做什麼／怎麼用，二者為硬性一級欄位，不可省）（`aiVsComputed` 明標「此區塊數字由程式算 / 敘事由 AI 生」——對齊 ga-insight guardrail `src/agents/guardrails.py:275-301` 的誠實精神，且升為 schema 一級）。
  - **Fable 5 要拍板**：registry 存哪（TS/JSON/MDX？keyed 結構）、如何餵三層元件（元件從容器變 registry-driven，可能需擴 Explainer props——與 Signal design §6 銜接，若需擴 props 明列，因兩者皆未實作、plan 期一次落地零重工）、跨兩 app（frontend/admin）如何共享（沿 Signal §2.4 token 複製+CI diff 的同構作法 or 其他）。
  - **驗收（阻擋級）**：每支柱每頁/每圖能從 registry 取到結構化說明，且**每頁必備 `whyBuilt`+`whatItDoes`**（缺任一 = gate fail）；AI 區與程式區可區分；coverage gate 掃全站頁面斷言都有 registry 條目、無孤兒頁。

## 📊 GA 支柱的 AI 大腦：agentic 分析問答（問 AI）——實碼接地 + 進化方向

> Fergus 明示：「問 AI」不是單純問答，**每頁都能問 AI（頁範圍輕量）＋ 一個獨立「問 AI」頁（完整多 agent）**，用 **LangGraph 多 agent + GUARDRAIL + REFLECTION**。這是 GA 支柱的 LLMOps 核心亮點，Fable 5 必須把它設計進來（**進化非複刻**——參考實碼、規劃我方更好版本）。

**ga-insight 實碼架構（規劃者已第一手讀碼接地，`llm-workshop/ga-insight/src/agents/`）**：LangGraph `StateGraph`（`graph.py:460-493`）六節點——
1. **input guardrail**（`graph.py:107`／`guardrails.py`）：業務相關性關鍵字 + **12 條 prompt-injection pattern**（`guardrails.py:31-44`）+ 日期範圍 → 不合法即 `end_rejected`。
2. **orchestrator**（`graph.py:122`）：LLM 動態選 **1-4 個** sub-agent（六專家：traffic/customer/product/funnel/anomaly/risk），規則提示 + fallback；亦處理 reflection 的補呼叫。
3. **run_sub_agents**（`graph.py:190`）：`ThreadPoolExecutor(max_workers=4)` **並行**、每 agent 120s timeout、錯誤隔離；每個 sub-agent 有自己的 `tools/` 模組、回 `SubAgentResult{key_findings, analysis, confidence, hit_limit, tool_results}`。
4. **reflection**（`graph.py:240`）：LLM 判 **sufficiency / gaps / conflicts**，從未呼叫者補選 ≤2 agent，`MAX_REFLECTION_ROUNDS` 上限 → 迴圈回 orchestrator 或進 synthesis（`edge_after_reflection:419`）。
5. **synthesis**（`graph.py:306`）：結論先 / 分析脈絡 / 交叉驗證 / **信心加權**（confidence<0.6 或 data_incomplete 加註）/ **誠實標數據缺口**（📌 分析限制）。
6. **output guardrail**（`graph.py:386`／`guardrails.py`）：PII 偵測（email/手機/信用卡）+ **反幻覺數字檢核**（答案中每個數字須能在 `tool_results` 找到根據，否則 flag/重試 synthesis，`edge_after_output_guardrail:431`）。

**與既有 P2b 的關係（Fable 5 要釐清，不重造）**：P2b（NORTH_STAR「P2b LLMOps/RAG」）是 **agentic RAG + CRAG over 留言文字**（檢索型）；問 AI 是 **tool-calling 分析型 orchestrator-worker over 結構化 GA 數據**（不同 agent pattern）。兩者**互補**、都是 LLMOps 展示。Fable 5 要決定：問 AI 是**沿用 P2b 的 LangGraph/LLM 基礎設施**（同一套 LLMClient/Ollama-Gemini 可切/評估閘/成本監控）擴一個新 graph，還是獨立——**傾向前者**（複用不重造，一套 LLMOps 治理兩種 agent）。

**兩層 AI（Fable 5 設計）**：(a)**每頁問 AI**＝頁範圍輕量（單 agent/單領域，如 ga-insight 各頁 🤖 區）；(b)**獨立問 AI 頁**＝完整多 agent（上述六節點 graph，跨領域）。

**拓撲落法（守 Option A）**：問 AI 是 live LLM/tool 呼叫，公開靜態站**不能即時跑** → 站上呈現 = **策展 Q&A 範例（預產靜態 JSON，沿 P4 `rag_showcase` 模式）+ 多 agent 架構圖（即你給的架構圖，說明式呈現）+ MCP 工具（遠端 Claude 可實查）+ 選配 live-demo 外連**（問 AI 是最值得配 live-demo 的亮點）。**誠實標**「此為離線批次產生的範例／架構在叢集內」（沿既有誠實紀律 + ga-insight guardrail 精神）。

**進化方向（做得比 ga-insight 更好，Fable 5 規劃）**：可考慮——用 MCP 把六專家的 tool 開成標準工具（agent 與 MCP 共用工具層）、guardrail/reflection 指標進 Prometheus（LLMOps 可觀測性，ga-insight 無）、reflection 收斂條件更嚴謹、跨支柱問答（不只 GA、也能問趨勢/PTT 資料）。**Fable 5 判斷哪些納入本輪、哪些列後續。**

**範圍歸屬（本 crosscut 裁定）**：問 AI 多 agent 系統夠份量，**傾向獨立一份「agentic 分析問答」spec**（或 GA 支柱 spec 的主要章節）——crosscut 記錄接地與方向、裁定它與 P2b/GA 支柱的邊界，細設下放該 spec。

## 整合模式（已鎖定，Fergus 拍板）＝統一靜態站 + 選配 live 連結

- 搜尋/GA 兩支柱**重建為本站原生頁、讀平台端預產靜態 JSON**；真運算/ES 在叢集或離線批次，站上以**預產結果 + 截圖/GIF + MCP 實查**佐證，**每支柱可附一個「live demo」外連**。
- 公開站**仍 `output:'export'` 純靜態、禁 ES/runtime 服務於公開站、匯出 JSON 為合約邊界**（P4 拓撲鐵律零鬆動）。
- **本 crosscut 要定**：live-demo 外連的呈現慣例（放哪、如何誠實標示「這是另一個部署/這是叢集內」）；GA 分析引擎跑平台端批次的資料流骨架（**細節 dataset/引擎 → GA 支柱 spec**，crosscut 只定「GA 分析走既有匯出 DAG 加 dataset」這條合約邊界，不細設）。

## 退役與取材（唯讀不改原專案，沿 NORTH_STAR 可複用素材地圖紀律）

- **ga-insight**：唯讀取材 analytics 引擎邏輯（`src/analytics/{conversion,rfm,attribution,predictive,...}`——**漏斗 `conversion.py` 是取材重點**）與五欄自我說明模式；碼不可抄（Streamlit/Plotly≠Next/Recharts）；取材後 ga-insight **退役**。**取的是分析邏輯與內容架構，做的是我方更完整版本**（進化非複刻）。
- **ptt-search**：保留為搜尋支柱 live-demo 部署來源（Vercel+CloudRun+Bonsai）；唯讀取材搜尋 UX 敘事；本站搜尋支柱不重建 ES。
- **emoji→lucide**：ga-insight 章節 nav 用 emoji（截圖），本站一律 lucide SVG icon（Signal design §0/驗收 #9「無 emoji-icon」硬約束）——取章節敘事結構、不取 emoji。

## 硬約束（貫徹並寫進 design）

- **不動既有合約**：11 頁 IA/route/資料合約（P4 §3-5/P6/P7）、匯出信封（P4 §4）、MCP 工具、explainers 正典路徑、Signal 設計系統本體——全零改；四支柱是**在其上加頂層 IA**，不改底層。
- **拓撲鐵律**：公開站純靜態、禁 ES/runtime；GA 分析批次算在平台端、匯出 JSON。
- **工具紀律**：不因 GA 支柱引第二 OLTP／新常駐服務於公開站；GA 分析引擎跑既有 Airflow 批次。
- **誠實敘事**：live-demo 外連、叢集內標記、AI-vs-程式標註——皆誠實，不假裝整套雲上即時跑。
- **a11y CRITICAL**、**無 emoji-icon**（沿 Signal 驗收）。
- **非互動不提問**：開放問題照契約收斂，真非實查不可才標「plan 前需實查 X」+ 預設傾向。

## 範圍邊界

- **in**：四支柱 IA + 主題切換框架、說明式內容 registry schema、整合模式落法框架、退役/取材接法、建置序、列後續 spec（GA 支柱 spec / 搜尋支柱 spec 的範圍界定）。
- **out**（→ 各支柱 spec）：GA 支柱的逐頁 IA/分析引擎/匯出 dataset/漏斗細設、搜尋支柱的 fuse.js 細設/live-demo 部署細節；Signal 設計系統本體（已定）；實作（plan 後）。
- **不動**：既有 11 頁一切、既有合約、Signal 本體。

## 建置序（design 尾段給）

Signal 設計系統（已立）→ **本 crosscut（框架）**→ GA 支柱 spec（漏斗核心）+ 搜尋支柱 spec（可平行）→ 說明式內容各支柱填 registry →（plan 後實作）。crosscut 要明確：哪些是本檔拍板、哪些下放各支柱 spec、接縫在哪（像既有 `ga4-extension-crosscut.md` 那樣集中裁定共用擴充點）。

## 交付流程尾註

Fable 5 走 `superpowers:brainstorming` 出 design，滿足精確度契約 8 條（**第 6 條進化非複刻是重中之重**）。**本階段只出 spec，plan 延後**。產出 `docs/specs/2026-07-10-unified-portfolio-crosscut-design.md`。產出後規劃者（Opus）逐條把關才據以續寫各支柱 spec。
