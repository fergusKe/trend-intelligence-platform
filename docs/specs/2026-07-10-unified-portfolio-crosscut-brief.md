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

- **現況**：既有「說明式 UI 三層元件」（InfoTooltip/ChartCaption/Explainer，正典路徑 `frontend/src/components/explainers/`，見 NORTH_STAR 說明式 UI 段）＝**容器**；但**內容散在各頁 inline**（Signal design §6 只定視覺）。
- **ga-insight 的模式（唯讀接地，`src/components/ui_utils.py:23-52` `render_page_header`）**：每頁 5 欄 `{chapter, title(問句), description(怎麼看), can_do(gain), problem(pain)}` + inline `help=`/`caption` 的公式+實例。**弱點**：文案 inline、無集中 registry、無 formula/dataSource/caveats 一級欄位、無 AI-vs-程式的結構化標註。
- **本站超越法（Fable 5 要設計）**：把說明升為**集中式 registry**（keyed by feature/page/chart id），schema 至少含：`{ pillar, chapter, questionTitle, howToRead, canDo, problem, formula?, dataSource, caveats?, aiVsComputed }`（`aiVsComputed` 明標「此區塊數字由程式算 / 敘事由 AI 生」——對齊 ga-insight guardrail `src/agents/guardrails.py:275-301` 的誠實精神，且升為 schema 一級）。
  - **Fable 5 要拍板**：registry 存哪（TS/JSON/MDX？keyed 結構）、如何餵三層元件（元件從容器變 registry-driven，可能需擴 Explainer props——與 Signal design §6 銜接，若需擴 props 明列，因兩者皆未實作、plan 期一次落地零重工）、跨兩 app（frontend/admin）如何共享（沿 Signal §2.4 token 複製+CI diff 的同構作法 or 其他）。
  - **驗收**：每支柱每頁/每圖能從 registry 取到結構化說明；AI 區與程式區可區分；schema 覆蓋率有守門（如 coverage gate 掃頁面斷言都有 registry 條目）。

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
