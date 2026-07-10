# 統一資料作品集 程式 crosscut design（四支柱 IA + 主題切換 + 說明式內容 registry + 問 AI 定框 + 整合/退役/建置序）

> **上游**：[brief](2026-07-10-unified-portfolio-crosscut-brief.md)（契約正本）＋ NORTH_STAR「統一資料作品集重定位」段（架構正本）＋ [Signal 設計系統 design](2026-07-10-frontend-design-system-design.md)（視覺地基，本檔建在其上、不重定 token）＋ P4 §5（8 頁）/P6 §11（`/reco`）/P7 §7.2（`/audience`）/即時 §10（`/streaming`）/[ga4-extension-crosscut](2026-07-09-ga4-extension-crosscut.md) EP-B/EP-C（11 頁與 explainers 正典路徑合約）。
> **精確度**：依 repo `CLAUDE.md`「Fable 5 design 精確度契約（8 條）」產出，逐條自檢見 §13。
> **定位（鐵律）**：本檔是統一作品集的**脊椎**——定四支柱 IA、主題切換、URL 落法、**說明式內容 registry（阻擋級）**、問 AI 定框、整合模式落法、退役/取材接法、建置序、後續 spec 範圍。**不**細設 GA/搜尋支柱的每一頁（各支柱 spec 的事）。**既有 11 頁 route/資料合約/匯出信封/MCP 工具/Signal 本體零改動**；四支柱是在其上**加層**。
> **一句話**：用 Next.js route groups（不進 URL）把全站組成四支柱各自的 shell 層——既有 11 頁原 route 原內容進 `(trends)`/`(platform)` 兩組、新支柱佔 `/ga/*` 與 `/search/*` 新 segment；跨全站立一份 TypeScript 說明式內容 registry（`whyBuilt`/`whatItDoes` 硬性一級欄位 + coverage gate 阻擋級），問 AI 以「策展 trace + 架構圖 + MCP + gated live-demo」守純靜態拓撲，複用 P2b LLM 基建不重造。
> 產出日期：2026-07-10。**本階段只出 spec，plan 延後**；`frontend/`/`admin/` 尚無實作碼，以下全是「建立時即照此」，非事後重構。

---

## 0. 版本敏感宣稱查證（context7 2026-07-10；其餘沿 Signal §0 pin 不重議）

| 宣稱 | 查證結果 | 來源 |
|---|---|---|
| **Next.js route groups `(folder)` 不進 URL、可各掛 `layout.js`** | ✅ 官方文件原文：「wrapping a folder in parenthesis … should not be included in the route's URL path」「adding a `layout.js` file inside each group's folder, you can apply a unique layout to that specific group」——本檔 §2 路由機制的地基 | context7 `/vercel/next.js`（project-structure / route groups） |
| **`output:'export'` 不支援清單不含 route groups / 巢狀 layout** | ✅ App Router 靜態匯出不支援清單 = 動態路由無 `generateStaticParams`、Route Handlers（Request 依賴）、Cookies、Rewrites/Redirects/Headers、Proxy、ISR、預設 image loader、Draft Mode、Server Actions、**Intercepting Routes**——route groups 與巢狀 layout 皆為 build-time 組織性功能，RSC 靜態匯出自 v13.4 支援 | context7 `/vercel/next.js`（static-exports） |
| Tailwind v4 `@theme inline`/shadcn CLI/fuse.js 7/motion 12/Recharts 3/lucide 1 | 沿 **Signal design §0 pin 表**（2026-07-10 已 context7＋npm 查證、Opus §13 獨立覆核通過）——本檔零新增前端依賴，不重查不翻案 | Signal §0/§13 |
| ga-insight / ptt-search 實碼 | 本檔撰寫時**第一手重新 grep 覆核**（非轉抄 brief）：`graph.py:462-493` StateGraph 8 節點（6 功能節點＋2 end）、`:37 MAX_REFLECTION_ROUNDS=2`、`guardrails.py` `_check_numbers` 反幻覺數字檢核、`ui_utils.py:23-52` `render_page_header` 五欄、`conversion.py` `ConversionFunnel`（`analyze_funnel`/`calculate_drop_off`/`identify_bottlenecks`/`get_sankey_data`/`get_recommendations`）、五章 chapter 字串、`src/analytics/` 17 模組、`sub_agents/` 六專家（anomaly/customer/funnel/product/risk/traffic） | 本機唯讀 grep |

---

## 1. 關鍵決策總表（brief 全部「要拍板」項收斂為單一決定；細節在各節）

| # | 開放問題 | 決定 | 一句理由 |
|---|---|---|---|
| 1 | 四支柱切換元件形態 | **頂欄支柱切換列（4 個 tab 型 link，lucide icon＋中文名）＋ sidebar 支柱內導航**的兩層 nav；行動端併入 Sheet 抽屜（§3） | 支柱是「站的分區」不是頁內狀態——頂欄 tab 是分區導航的正典形態；sidebar 留給支柱內頁（Signal 決策 11 的 sidebar 機制原樣沿用、內容支柱化） |
| 2 | 當前支柱標示 | **三重標示**：頂欄 active tab（accent 底線＋`aria-current`）＋ sidebar header 常駐「icon＋支柱名」＋ `<title>` 模板含支柱名（§3.4） | Fergus 明示「讓使用者知道當前在看哪個主題」——單點標示會在深頁迷路，三點皆 server-render 零 client 判斷 |
| 3 | 路由落法 | **route groups**：既有 11 頁原 route 進 `(trends)`（10 頁）與 `(platform)`（`/architecture`）；新支柱佔 **`/ga/*`、`/search/*`** 新頂層 segment（§2） | context7 已證 `(folder)` 不進 URL 且可各掛 layout——**唯一能「零改 route 又給每支柱獨立 shell」的機制**；頁面尚未實作，「移進 group」實為「建立時就建在 group 內」，零遷移 |
| 4 | `/` 歸屬 | **`/` 維持趨勢智能總覽 = 全站首頁、趨勢智能為預設支柱**；「作品集全貌」由 shell 層承擔（頂欄四 tab＋footer 支柱目錄），不動 `/` 頁面合約 | 新開 landing 要嘛改 `/`（違合約）要嘛多一層跳板（摩擦）；shell 常駐標示即是作品集敘事，P4 `/` 區塊清單零改 |
| 5 | GA 支柱 vs `/audience` 邊界 | **`/audience` 留趨勢智能支柱（P7 DMP 工程視角）；GA 支柱 = 業務分析視角，不重繪 R×F/分群正本圖，以 registry `related` cross-link 引用**（§4） | 同資料兩視角：一講「圈人基建怎麼蓋」（ClickHouse/DSL/admin），一講「數據說了什麼」（漏斗/歸因/LTV）——任何圖表只在一個支柱有正本 |
| 6 | registry 載體 | **TypeScript module（per-pillar 檔＋`satisfies` 型別鎖）**，非 JSON/MDX（§5.2） | 缺 `whyBuilt` = **編譯期就紅**（gate 之前多一道免費防線）；`entryId` 型別化為 `keyof`，打錯 id = TS error；內容是結構化短文案非長 prose，MDX 管線零收益 |
| 7 | registry 跨兩 app | **共享 schema 型別檔（逐字節複製＋CI diff，掛進 Signal §2.4 既有 drift job）；內容 registry 各 app 自持** | 兩 app 頁面集合不相交，共內容無意義；會漂移的是 schema 結構——同構才是防漂點，機制直接複用 tokens.css 那套 |
| 8 | coverage gate 實作 | **vitest 守門測試**（glob `src/app/**/page.tsx` → route 推導 → 雙向斷言 registry 條目/硬性欄位/PageHeader 接線/無孤兒）＋ grep 禁裸用元件，**進 frontend-ci / admin-ci 阻擋級**（§5.5） | 「每頁必有完整說明」是 Fergus 阻擋級定案——只有列舉式掃描能保證無漏網；反例可實跑（刪一欄 = CI 紅） |
| 9 | 問 AI 與 P2b 關係 | **複用 P2b LLM 基建**（LLMClient Ollama/Gemini 切換、prompt registry、評估閘、成本/延遲 Prometheus）**擴一個新 LangGraph graph**，不獨立起爐灶（§6.2） | 一套 LLMOps 治理管兩種 agent 範式（檢索型 CRAG＋分析型 orchestrator-worker）本身就是履歷亮點；重造 = 違「agent 框架只 LangGraph」與複用紀律 |
| 10 | 問 AI 範圍歸屬 | **獨立一份「問 AI agentic 分析問答」spec**（非 GA 支柱 spec 章節），建置序在 GA 支柱 spec 之後（§6.5/§9） | 六節點 graph＋兩層 AI＋P2b 接線＋showcase 產線份量足；GA 支柱 spec 已扛分析引擎＋datasets＋頁面，再塞會超載 |
| 11 | live-demo 外連 v1 配置 | **搜尋支柱 ✅**（ptt-search 既有部署）＋**問 AI 支柱 ✅ v1 就上 live-demo（Fergus 2026-07-10 定案：功能完整優先、成本不設限；per-day 執行次數上限列 follow-up 補）**。問 AI live-demo＝獨立部署端點（傾向 Cloud Run＋前置 input guardrail＋誠實標「獨立部署」），站上仍策展 trace＋架構圖＋MCP 並存；部署形態細節由問 AI spec 拍板落地 | Fergus 定案：現階段重點是功能完整，先把 live 問 AI demo 上起來（真跑 LangGraph agent），rate-limit 之後補。**靜態站本身仍零 live LLM**——live-demo 是外連的獨立端點，不破純靜態拓撲 |
| 12 | GA 支柱資料流合約邊界 | **走既有 `export_frontend_data` DAG additive**：分析引擎平台端批次 → `gold.gold_ga4_insight_*`（additive marts，不改地基 4 表）→ exporter `datasets.py` 加條目 → `ga_insight_*.json`（P4 信封同構）→ 前端純讀；absent 容忍沿 P4（§7.3） | P4 §4 穩定性政策本就允許加檔；零新資料通道、零新部署，GA 支柱與其他 18 檔喝同一口井 |
| 13 | 檔名/命名空間保留 | dataset 前綴：GA 支柱 `ga_insight_`、搜尋支柱 `search_`、問 AI `ga_ask_`；Gold 前綴 `gold.gold_ga4_insight_*`；dbt tag `ga4_insight`（EP-D append 紀律） | 先佔命名空間防撞（既有 `ga4_realtime_correctness.json` 已用掉 `ga4_` 語感——GA 支柱不用 `ga4_` 前綴避免混淆） |
| 14 | ⌘K 全站搜 vs 搜尋支柱 | **兩個不同東西，明文釘死**：⌘K（Signal §7）＝全站導航式快速搜，跨四支柱、原樣不動；`/search` 支柱＝搜尋**工程展示**（ES 敘事＋live-demo＋離線示範）（§2.3） | Signal §13 Opus 註記已預告此邊界，本檔落成契約 |

---

## 2. 四支柱 IA 與路由落法

### 2.1 route map（合約級；既有 11 route 一字不改）

```
frontend/src/app/
├── layout.tsx                    # 唯一 root layout：html/body/字型/MotionConfig/⌘K provider/PillarFooter
├── (trends)/                     # 📈 趨勢智能支柱（route group，不進 URL）
│   ├── layout.tsx                #   <PillarShell pillar="trends">
│   ├── page.tsx                  #   /            （總覽＝全站首頁）
│   ├── trends/page.tsx           #   /trends
│   ├── channels/page.tsx         #   /channels
│   ├── videos/page.tsx           #   /videos
│   ├── sentiment/page.tsx        #   /sentiment
│   ├── ai-lab/page.tsx           #   /ai-lab
│   ├── ptt/page.tsx              #   /ptt
│   ├── reco/page.tsx             #   /reco
│   ├── audience/page.tsx         #   /audience
│   └── streaming/page.tsx        #   /streaming
├── (platform)/                   # 🏗 平台架構支柱
│   ├── layout.tsx                #   <PillarShell pillar="platform">
│   └── architecture/page.tsx     #   /architecture（沿 P4 原頁，additive 擴充見 §7.4）
├── (ga)/                         # 📊 GA 分析支柱（頁面組成 → GA 支柱 spec）
│   ├── layout.tsx                #   <PillarShell pillar="ga">
│   └── ga/                       #   /ga（支柱首頁）＋ /ga/<page>（如 /ga/funnel、/ga/ask）
└── (search)/                     # 🔍 搜尋支柱（頁面組成 → 搜尋支柱 spec）
    ├── layout.tsx                #   <PillarShell pillar="search">
    └── search/                   #   /search（支柱首頁）＋ /search/<page>（若需要）
```

- **衝突檢查**：新 segment `/ga`、`/search` 與既有 11 route（`/` `/trends` `/channels` `/videos` `/sentiment` `/ai-lab` `/ptt` `/architecture` `/reco` `/audience` `/streaming`）零交集；route group 括號段經 context7 證不進 URL；全站仍單一 root layout（**不用多 root layout**——那會使跨支柱導航整頁重載，且我方四支柱共用 html/字型/provider，無拆分理由）。
- **「11 頁全數保留」的精確語意**：route、資料檔、區塊清單、說明文字合約零改動（P4 §5/P6 §11/P7 §7.2/即時 §10 原文）；「歸入支柱」只是 **nav 層歸屬**——`/architecture` 的 nav 歸屬從 Signal 決策 11 的「平台」組移為平台架構支柱首頁，其餘 10 頁歸趨勢智能支柱。每頁只在一個支柱的 sidebar 出現（雙掛 = 使用者搞不清自己在哪，違決策 2 的標示原則）。
- **靜態匯出斷言**：`next build` 後 `out/` 必含 `index.html`、`trends/`…等 11 個既有路徑＋`ga/`、`search/` 新路徑，且**不含** `(trends)` 等括號字樣路徑（驗收 #1）。

### 2.2 四支柱定義與頁面組成（v1）

| 支柱 | id | lucide icon | 首頁 | v1 頁面組成 | 細設歸屬 |
|---|---|---|---|---|---|
| 📈 趨勢智能 | `trends` | `TrendingUp` | `/` | 既有 10 頁（8−architecture＋reco＋audience＋streaming），**內容零改** | 已定（P4/P6/P7/即時 design） |
| 📊 GA 分析 | `ga` | `ChartColumn` | `/ga` | `/ga`（支柱首頁）＋漏斗核心分析頁群＋`/ga/ask`（問 AI 頁）——**頁清單由 GA 支柱 spec 拍板**，本檔只鎖 segment、章節敘事約束（§2.4）、資料流邊界（§7.3） | GA 支柱 spec＋問 AI spec |
| 🔍 搜尋 | `search` | `Search` | `/search` | `/search`（支柱首頁：搜尋工程敘事＋live-demo 外連＋離線示範）——單頁或少頁由搜尋支柱 spec 拍板 | 搜尋支柱 spec |
| 🏗 平台架構 | `platform` | `Layers` | `/architecture` | `/architecture`（P4 原頁＋§7.4 additive 整合模式卡）；未來 additive 加頁合法 | 已定（P4）＋本檔 §7.4 |

支柱順序（頂欄左→右）：**趨勢智能 → GA 分析 → 搜尋 → 平台架構**——預設著陸支柱居首，分析次之，工程展示第三，底座壓軸（「資料產品 → 分析 → 搜尋工程 → 平台」的敘事弧）。lucide icon 名以 1.24.0 export 為準（plan 期 lockfile 順手確認別名，`ChartColumn` 舊名 `BarChart3` 兩者擇存在者，非阻擋）。

### 2.3 ⌘K 全站搜 vs 搜尋支柱（邊界釘死）

- **⌘K palette（Signal §7）原樣不動**：全站導航式快速搜（頁面/影片/頻道/問答/商品/分群），跨四支柱可用。additive 銜接兩處：①palette 的 `page` 條目來源（Signal §7.2「bundle 內靜態 registry」）改由本檔 §5 registry 派生——title＝nav 頁名、subtitle＝registry `whatItDoes` 首句（≤40 字），並按**支柱分組**渲染（`CommandGroup` 標題 = 支柱名）；②新支柱 dataset（`ga_insight_*`/`search_*`）進 `build-search-index.mjs` 為 additive 條目（各支柱 spec 定裁切欄）。registry 只在 palette 的 `next/dynamic` lazy chunk 進 client bundle（RSC 頁面端為 server-only 讀取，不上首屏 JS）。
- **`/search` 支柱**＝搜尋**工程能力展示**：ES/FastAPI 架構敘事（取材 ptt-search）、live-demo 外連（真 Elasticsearch 全文檢索）、站內離線示範。頁內首段 Explainer 誠實聲明：「本站站內搜尋（⌘K）是 client-side fuse.js 模糊搜；真 Elasticsearch 全文檢索在 live demo（獨立部署）」。離線示範語料的來源（ptt-search 示範資料裁切 vs P3 Silver 文章標題 additive 匯出 ≤300KB）由搜尋支柱 spec 拍板，**預設傾向後者**（吃自家平台資料，敘事一致）。

### 2.4 GA 支柱章節敘事約束（進化非複刻——本檔給約束，不給頁清單）

ga-insight 的五章弧（第一章業績全貌→第二章認識客群→第三章找到問題→第四章立刻行動→第五章問 AI；grep 實證 5 個 chapter 字串）與問句式標題（如「客人在哪個步驟跑掉？」）是**輸入非模板**。GA 支柱 spec 必須：
1. **自行設計章節弧**（可以不是五章、不必同名），但必須是**問題導向敘事**（每章回答一類業務問題）而非功能清單；**漏斗為核心章**（Fergus 定案）。
2. 每頁 `questionTitle` 用問句（registry gate 強制，§5.5）。
3. **比 ga-insight 更完整的硬性面**（至少涵蓋，超出歡迎）：漏斗含**逐步流失＋瓶頸判定的明確公式**（取材 `conversion.py` `identify_bottlenecks` threshold 邏輯，重寫為批次 SQL/Python）、**歸因**（多模型對照，取材 `attribution.py` 邏輯）、**分群/LTV**（與 P7 資料共源不重繪，§4）、**預測**（取材 `predictive.py`，明標模型與訓練窗）、**AI-vs-程式逐區塊標註**（registry `aiVsComputed`，ga-insight 只有口頭分區）。
4. 版面**不必同模板**：漏斗頁/KPI 頁/歸因頁各給最合適版面（Signal 決策 1 的 variety-with-coherence 授權範圍內）。

---

## 3. 主題切換 UX（PillarShell 元件契約）

### 3.1 元件與落點

```
frontend/src/components/shell/
├── PillarShell.tsx        # <PillarShell pillar="trends">{children}</PillarShell>——四個 group layout 各呼叫一次
├── PillarTopbar.tsx       # 頂欄：站名 + 四支柱 tabs + ⌘K 按鈕
├── PillarSidebar.tsx      # shadcn sidebar（Signal §4.1 機制原樣），內容 = 當前支柱 nav groups
├── PillarDirectory.tsx    # footer 支柱目錄（root layout 級，FreshnessBanner 之上）
└── pillars.ts             # ★ 支柱 registry 單一真源（id/name/icon/homeRoute/navGroups/liveDemo?）
```

`pillars.ts` 形狀（欄位級）：

```ts
export const PILLARS = {
  trends:   { name: '趨勢智能', icon: 'TrendingUp',  homeRoute: '/',
              navGroups: [
                { label: 'YouTube 趨勢', routes: ['/', '/trends', '/channels', '/videos'] },
                { label: '觀眾與語料',   routes: ['/sentiment', '/ptt'] },
                { label: 'AI Lab',       routes: ['/ai-lab'] },
                { label: '推薦與受眾',   routes: ['/reco', '/audience', '/streaming'] },
              ] },
  ga:       { name: 'GA 分析', icon: 'ChartColumn', homeRoute: '/ga',
              navGroups: [/* GA 支柱 spec 填；章節 = group label */] },
  search:   { name: '搜尋', icon: 'Search', homeRoute: '/search',
              navGroups: [{ label: '搜尋工程', routes: ['/search'] }],
              liveDemo: { url: '<ptt-search 部署 URL，plan 期實查回填>',
                          deployment: 'Vercel + Cloud Run + Bonsai Elasticsearch',
                          note: '獨立部署的真 Elasticsearch 全文檢索' } },
  platform: { name: '平台架構', icon: 'Layers', homeRoute: '/architecture',
              navGroups: [{ label: '平台架構', routes: ['/architecture'] }] },
} as const satisfies Record<string, Pillar>;
```

趨勢智能四組＝Signal 決策 11 的五組**去掉「平台」組**（`/architecture` 移平台架構支柱），其餘分組原樣——此為 Signal 決策 11 的**支柱化重組**，是該 design §13 Opus 註記預告的 additive 接縫，非翻案。

### 3.2 桌面形態

- **頂欄**（全寬、`--surface-1` 底、下邊框）：左＝站名「Trend Intelligence · Data Portfolio」（link `/`）；中＝四支柱 tabs（lucide icon＋中文名，`--dur-fast` hover）；右＝⌘K 搜尋按鈕（Signal §7.3 原樣）。**Signal 決策 11 的「麵包屑」移除**：兩層 nav（支柱 tab active＋sidebar item active）已完整定位，且全站頁深最多 2 層，麵包屑是退化冗餘——此為對 Signal 決策 11 的**明文修訂**（該 design §13 已預告 nav 層會被本檔取代）。
- **sidebar**：shadcn sidebar 機制原樣（token/`aria-current="page"`/分組），header 新增**當前支柱標示列**（icon＋支柱名，`--text` 字重 600），內容＝當前支柱 `navGroups`。
- **footer**（root layout 級，所有支柱共用）：`PillarDirectory`（四欄：支柱名＋該支柱頁面連結清單）→ 其下 `FreshnessBanner`（P4 原樣，文字零改）。作品集全貌敘事由此承擔，不動任何頁面合約。

### 3.3 行動端形態

頂欄＝站名＋當前支柱 badge（icon＋名，`--accent` outline）＋漢堡（Sheet）＋⌘K icon 按鈕。Sheet 內容兩段：①**支柱切換段**（4 列大項，當前列 accent 左緣豎線＋`aria-current`）②分隔線＋當前支柱 navGroups。切支柱＝導向該支柱 `homeRoute`。

### 3.4 當前支柱標示（決策 2 的三重落點）與 a11y

| 落點 | 實作 |
|---|---|
| 頂欄 tab active | 2px `--accent` 底線＋文字 `--text`（非 active 用 `--text-muted`）；`aria-current="true"`（分區級，非 `page`——`page` 保留給 sidebar 頁項） |
| sidebar header | 常駐 icon＋支柱名（server-render，由 group layout 的 `pillar` prop 決定，零 client 路徑判斷） |
| `<title>` | 模板 `%s · {支柱名}｜Trend Intelligence`（group layout `metadata` title.template；支柱首頁＝`{支柱名}｜Trend Intelligence`） |

a11y：支柱 tabs 是 `<nav aria-label="作品集主題">` 內的連結列（非 ARIA tabs——它們是導航非面板切換）；全鍵盤可達（Tab 順序：站名→四 tab→⌘K→sidebar）；focus ring 沿 Signal `--ring`。此段納入 Signal 驗收 #7 鍵盤 walkthrough 的擴充段。

---

## 4. GA 支柱 vs P7 `/audience` 邊界（決策 5 細則）

| | `/audience`（趨勢智能支柱，P7 已定） | GA 支柱分群/價值相關頁（GA 支柱 spec） |
|---|---|---|
| 視角 | **DMP 工程**：怎麼蓋圈人基建（ClickHouse OLAP、圈選 DSL、admin app、tag 物化） | **業務分析**：數據說了什麼（生命週期、流失預警、LTV、喚醒策略） |
| 正本圖表 | R×F heatmap、8 行為分群摘要、tag coverage（P7 §7.2 原樣） | LTV 分佈/流失預測/lifecycle stage 轉移等**新分析**（取材 ga-insight `predictive.py`/`rfm.py` 邏輯的進化版） |
| 鐵律 | **同一張圖只在一個支柱有正本**：GA 支柱不重繪 R×F heatmap 與 P7 分群摘要；`/audience` 不長出 LTV 預測 | 同左 |
| 互指 | registry `related` 欄（§5.2）→ PageHeader 渲染「相關：GA 分析支柱的客戶價值頁 →」 | `related` → 「想看這套分群背後的 DMP 基建 → /audience」 |
| 資料共源誠實 | `dataSource` 欄如實標 `gold.gold_ga4_user_rfm`（地基 §5.4）等共用上游——兩支柱吃同源不同衍生，registry 讓共源可稽核 | 同左；GA 支柱衍生表一律 `gold.gold_ga4_insight_*` 前綴，不改 P7 的 `dmp_*` |

同理適用 `/reco`/`/streaming`（皆 GA4 衍生）：趨勢智能支柱講推薦/串流**工程垂直**，GA 支柱若引用其結果一律 cross-link 不重繪。**邊界一句話：資料源不是支柱邊界，視角才是。**

---

## 5. 說明式內容 registry（本 crosscut 核心產出；跨全站硬性、阻擋級）

### 5.1 定位

三層元件（InfoTooltip/ChartCaption/Explainer，正典路徑 `frontend/src/components/explainers/`，EP-B 不動）＝**容器**；本節立**內容單一真源**。對標 ga-insight `render_page_header` 五欄（`ui_utils.py:23-52`：chapter/title/description/can_do/problem）並超越：集中 registry、`whyBuilt`/`whatItDoes` 硬性一級欄位、formula/dataSource/caveats 結構化、AI-vs-程式標註升 schema 一級（ga-insight guardrail 的誠實精神從 runtime 檢核前移到內容層）。

### 5.2 schema（欄位級契約）

```ts
// frontend/src/content/registry/types.ts —— 跨 app 共享正本（admin 逐字節複製，§5.4）
export type AiMode = 'computed' | 'ai-narrative' | 'mixed' | 'none';
//  computed=數字全由程式算｜ai-narrative=敘事由 LLM 生（數字仍程式算）｜mixed=並存｜none=本頁無數據區塊

export type BlockEntry = {
  questionTitle?: string;      // 圖卡標題（問句可選）
  howToRead: string;           // 怎麼看（ChartCaption/InfoTooltip 文字源）
  formula?: string;            // 行內公式（Fira Code 呈現，如 'drop_off% = 1 − step_n/step_{n−1}'）
  dataSource: string[];        // 如 ['ga_insight_funnel.json ← gold.gold_ga4_insight_funnel_daily']
  caveats?: string[];
  aiVsComputed: AiMode;
  aiVsComputedNote?: string;   // mixed/ai-narrative 時必填（模型、生成批次語意）
};

export type PageEntry = {
  pillar: 'trends' | 'ga' | 'search' | 'platform';
  route: `/${string}` | '/';
  chapter?: string;            // GA 支柱章節敘事用；其他支柱可省
  questionTitle: string;       // 問句式標題（gate 強制以「？」結尾）
  whyBuilt: string;            // ★ 硬性：開發目的——為什麼做這個/解決什麼（≥20 字元）
  whatItDoes: string;          // ★ 硬性：這頁提供哪些能力/輸入輸出/怎麼操作（≥20 字元）
  howToRead: string;           // 頁級「怎麼看」
  canDo: string;               // gain（ga-insight can_do 對應）
  problem: string;             // pain（ga-insight problem 對應）
  formula?: string;
  dataSource: string[];
  caveats?: string[];
  aiVsComputed: AiMode;
  aiVsComputedNote?: string;
  related?: { route: string; label: string }[];   // 跨支柱 cross-link（§4）
  blocks: Record<string, BlockEntry>;             // 圖卡/區塊級條目；key = kebab block id
};
```

- **存放**：`frontend/src/content/registry/{types.ts, index.ts, trends.ts, ga.ts, search.ts, platform.ts}`——per-pillar 檔各 export `Record<pageId, PageEntry>`，`index.ts` 合併並 `satisfies Record<string, PageEntry>` 鎖型別，export `REGISTRY` 與 `type RegistryId = keyof typeof REGISTRY`、`getPage(id)`、`getBlock('pageId.blockId')`。
- **pageId 推導（決定性函式，gate 與元件共用）**：`route === '/' ? 'overview' : route.slice(1).replaceAll('/', '-')`（`/ga/funnel` → `ga-funnel`）。block 引用鍵＝`${pageId}.${blockId}`。
- **既有 11 頁條目的內容來源**：各頁已合約化的說明文字（P6 §11/P7 §7.3/即時 §10 原文）**原樣作為 howToRead/caveats 基底**（合約文字零刪改，如 `/streaming` Explainer 首段重放聲明整段進 `caveats[0]`）；`whyBuilt`/`whatItDoes` 為新增文案，於各頁 plan 落地時撰寫。誰寫：頁面歸哪份 plan、條目就歸那份 plan（P4 plan 寫 8 頁＋P6/P7/即時 plan 各寫自己那頁；新支柱頁歸各支柱 spec→plan）。

### 5.3 餵三層元件（與 Signal §6 銜接；props 擴充明列——兩者皆未實作，plan 期一次落地零重工）

| 元件 | 變更 | 說明 |
|---|---|---|
| **`PageHeader`（新增）** | `{ entryId: RegistryId }` 必填 | ga-insight `render_page_header` 的進化版，**每頁第一個元素**（取代 Signal §5 標準頁模板的「頁標＋副標＋Explainer 觸發器」列，視覺沿 Signal 字階/token）。渲染：chapter eyebrow（有才顯）→ h1 `questionTitle`（display 字階）→ `whatItDoes` 副標（muted、**全文不截斷**）→ **`whyBuilt` 常駐列**（lucide `Target`＋「為什麼做這個：」前綴——Fergus 定案「一看就懂」＝可見不摺疊）→ `canDo`/`problem` 雙 chip（`--positive`/`--negative-text` 語調；行動端堆疊）→ `related` 連結列（有才顯）→ 頁級 `Explainer entryId`（defaultOpen，內容＝howToRead/formula/dataSource/caveats/aiVsComputed） |
| `Explainer` | props += `entryId?: RegistryId \| BlockRef` | 給 entryId 即 registry-driven 渲染方法論塊；`children` 保留為補充 prose 槽。`defaultOpen` 語意不變（EP-B） |
| `ChartCaption` | props += `entryId?: BlockRef` | 渲染 block 的 `howToRead`＋`formula`；**frontend/ 內強制 entryId 用法**（gate grep），literal children 僅 admin 合法 |
| `InfoTooltip` | **props 零改** | 文字源改由呼叫端 `getBlock(id).howToRead` 取值傳入——容器不知 registry，維持 Signal §6 純視覺契約 |
| **`AiComputedBadge`（新增）** | `{ mode: AiMode; note?: string }` | 「數字由程式計算」/「敘事由 AI 生成（{note}）」小標（`Badge variant="outline"`＋lucide `Cpu`/`Sparkles`）；RagCard、`/reco` 理由卡、GA 支柱 AI 區塊、`/ga/ask` 全部掛 |
| **`LiveDemoCard`（新增）** | `{ pillar: PillarId }` | 讀 `pillars.ts` 的 `liveDemo`，渲染：外連按鈕（lucide `ExternalLink`＋顯示 hostname）＋部署技術列＋**誠實固定句式**「此連結開啟另一個獨立部署（{deployment}）；本站為純靜態展示，不依賴該服務」。落點＝支柱首頁＋`/architecture` 整合模式卡（§7.4） |

### 5.4 跨 frontend/admin 共享（沿 Signal §2.4 同構機制）

- **共享正本 = `types.ts` 一檔**：`admin/src/content/registry/types.ts` 為逐字節複製；`Makefile` `sync-design-tokens` target 擴為同時 cp tokens.css 與 types.ts（更名 `sync-design-system`，原名保留 alias）；`pr-checks.yaml` 既有 `design-tokens-drift` job **additive 加第二條 diff**（admin 檔不存在則 skip，P4 absent 容忍精神）。
- **內容各自持有**：admin 4 頁（P7 §6）條目放 `admin/src/content/registry/admin.ts`（`pillar` 欄用 `'platform'`？——否：admin 不在四支柱內，型別檔為 admin 加第五值 `'admin'`，公開站 registry 不使用該值）。admin 的 ExplainerSection（P7 §7.3 各自實作原判不動）改吃自家 registry，gate 同款進 admin-ci。

### 5.5 coverage gate（阻擋級；coverage-gate 掃檔模式）

**落點**：`frontend/src/content/registry/coverage.test.ts`（vitest，進 frontend-ci 於 `next build` 之前；本地 `npm run gate:explainers`）。admin 同款一份進 admin-ci。

| # | 斷言 | 失敗語意 |
|---|---|---|
| 1 | glob `src/app/**/page.tsx` → 剝 route group 括號段→推導 route/pageId → **每頁必有 `REGISTRY[pageId]`** | 新頁沒寫說明 = 不得 ship（Fergus 阻擋級定案） |
| 2 | 每條目 `whyBuilt`/`whatItDoes` 非空且 ≥20 字元；`questionTitle` 以「？」結尾；`aiVsComputed ∈ AiMode`；`mixed`/`ai-narrative` 必有 `aiVsComputedNote` | 佔位敷衍（"TODO"）擋下 |
| 3 | 每頁原始碼含 `<PageHeader` 且其 `entryId` 字串 === 該頁 pageId | 條目存在但沒接線 = 假覆蓋 |
| 4 | 反向：每個 registry 條目的 `route` 對應實存 page 檔；每個 `blocks` key 至少被 `src/` 引用一次（grep `'pageId.blockId'` 字串） | 無孤兒條目/死內容 |
| 5 | grep `src/`：`<ChartCaption` 或 `<Explainer` 出現處必含 `entryId`（frontend 限定） | 禁 inline 散落文案回潮（ga-insight 的弱點不准復發） |
| 6 | `route` 與檔案位置的支柱一致：`(trends)/` 下的頁其條目 `pillar==='trends'`（餘同構） | 防歸錯支柱 |

gate 對 route group 的 pageId 推導寫成純函式並自帶單元測試（`'(ga)/ga/funnel/page.tsx'` → `/ga/funnel` → `ga-funnel`）。**驗收反例可實跑**：刪任一頁 `whyBuilt` → gate 紅（驗收 #3）。

---

## 6. 問 AI agentic 分析問答——本 crosscut 定框（細設下放問 AI spec）

### 6.1 接地基準（第一手覆核，見 §0）與進化界線

ga-insight graph（`graph.py:462-493`）：input guardrail（12 條 prompt-injection pattern＋業務相關性）→ orchestrator（LLM 選 1-4 sub-agent，六專家 traffic/customer/product/funnel/anomaly/risk）→ run_sub_agents（`ThreadPoolExecutor(max_workers=4)` 並行、120s timeout、錯誤隔離）→ reflection（sufficiency/gaps/conflicts，補選 ≤2、`MAX_REFLECTION_ROUNDS=2`）→ synthesis（結論先/信心加權/誠實標缺口）→ output guardrail（PII＋`_check_numbers` 反幻覺：答案數字須在 tool_results 有根據）。**取的是這套 orchestrator-worker＋雙 guardrail＋reflection 的邏輯形狀；重造的是工程層**（LLM 呼叫走 P2b LLMClient 非 ga-insight 的直呼、指標進 Prometheus、trace 持久化、跑在平台批次而非 Streamlit runtime）。

### 6.2 與 P2b 的關係（裁定：複用，不重造）

- P2b（CRAG 檢索型 over 留言）與問 AI（tool-calling 分析型 over GA Gold 結構化數據）是**同一 LangGraph 框架下的兩個 graph、互補的兩種 agent 範式**。
- **問 AI 必須複用 P2b 的**：LLMClient（Ollama `qwen3:8b` host 預設/Gemini fallback，EP-J 模型 pin 對齊）、prompt 版本（MLflow Prompt Registry，沿 P2 §10）、評估閘結構、token/成本/延遲 Prometheus 指標面、k8s→host ExternalName 接線。**新建的只有**：問 AI graph 本體、六專家 sub-agent 與其 tool 層（讀 GA Gold/insight marts）、trace schema。
- 守「agent 框架只 LangGraph」；不引 CrewAI/AutoGen 等第二框架。

### 6.3 兩層 AI（定框）

| 層 | 形態 | 拓撲落法 |
|---|---|---|
| (a) 每頁問 AI | GA 支柱每頁一個「問 AI」摺疊區：**該頁範圍的策展 Q&A 2–3 則**（單領域 sub-agent 產出）＋「完整多 agent 問答 →/ga/ask」連結 | 讀 `ga_ask_showcase.json` 中 `scope==='page:<pageId>'` 的列；v1 限 GA 支柱頁，跨支柱＝進化方向 |
| (b) 獨立問 AI 頁 `/ga/ask` | 完整多 agent 展示：策展 Q&A 卡牆（**含逐節點 trace 展開**：orchestrator 選了誰/reflection 幾輪/guardrail 結果/信心值——ga-insight 不給使用者看 graph 內部，我方全揭露=進化點）＋多 agent 架構圖（說明式 SVG/Mermaid）＋ MCP 指引 | 讀 `scope==='global'` 列；每卡掛 `AiComputedBadge mode="ai-narrative"`＋「離線批次產生 · {provider} · {generated_at}」 |

### 6.4 拓撲落法（Option A，鐵律內）

- **站上零 live LLM 呼叫**。呈現四件套：策展 Q&A（預產靜態 JSON，沿 `rag_showcase` 模式）＋架構圖＋MCP 工具（`get_ga_ask_showcase`，docstring 明講「離線批次預產、非即時推理」，沿 P4 §7 誠實紀律）＋ **live-demo 外連 v1 就上**（決策 11，Fergus 2026-07-10 定案：功能完整優先、成本不設限，per-day 執行次數上限列 follow-up）——獨立部署端點（傾向 Cloud Run＋input guardrail 前置＋誠實標「獨立部署」），問 AI spec 拍板部署細節。**注意此為外連的獨立端點跑 live agent；靜態站本身仍零 live LLM。**
- **`ga_ask_showcase.json` 信封＝P4 統一信封；rows 骨架（本檔保留欄，問 AI spec 只准 additive 擴）**：`{ scope: 'global'|'page:<pageId>', question, answer, agents_called: string[], reflection_rounds: number, guardrail: { input_passed: boolean, output_flags: string[] }, confidence: number, provider, latency_ms, token_usage, generated_at }`。產線＝平台端批次（host 跑完整 graph，Ollama 零成本，沿 P6 `make gen-reco-reasons` 慣例），結果落 `ml.ga_ask_showcase` 表 → exporter additive 條目。
- **進化清單裁定**（brief 列的四項）：✅ 納入問 AI spec v1——guardrail/reflection 指標進 Prometheus、reflection 收斂條件嚴謹化（sufficiency 明確評分＋停止條件）、逐節點 trace 持久化與前端揭露；⏭ 列進化方向不做 v1——六專家 tool 開成 MCP 共用工具層（MCP 讀靜態 JSON 與 agent 讀 Gold 是兩個資料面，共層需先統一，收益後置）、跨支柱問答（問趨勢/PTT 資料）。

### 6.5 範圍歸屬

**獨立「問 AI agentic 分析問答」spec**（決策 10）。本檔已拍板：P2b 複用邊界（§6.2）、兩層形態（§6.3）、拓撲四件套與 showcase 骨架（§6.4）、live-demo gated 預設傾向、進化清單取捨。問 AI spec 細設：graph 節點/狀態機、六專家 tool 欄位、guardrail 規則集、評估閘門檻、trace schema 全欄、批次產線 DAG/make target、live-demo 部署拍板、`/ga/ask` 頁 IA。

---

## 7. 整合模式（Option A）落法框架

### 7.1 統一模式（四支柱一體適用）

每個「真運算在叢集/離線」的能力，站上呈現一律四件套：**①預產靜態 JSON**（走 §7.3 合約邊界）**②架構圖/截圖 GIF**（說明式，P5 截圖紀律）**③MCP 工具**（讀同一份公開 JSON，P4 §7 模式 additive）**④選配 live-demo 外連**（§7.2 慣例）。誠實標示三落點：FreshnessBanner（每頁，原文不動）、registry `caveats`/`aiVsComputedNote`、LiveDemoCard 固定句式。

### 7.2 live-demo 外連呈現慣例（拍板）

- **落點**：支柱首頁一張 `LiveDemoCard`（§5.3）＋ `/architecture` 整合模式卡內一行；**不放進 sidebar/topbar**（外連不是站內導航，混入 nav 會誤導拓撲認知）。
- **誠實句式（固定，不得改寫弱化）**：「此連結開啟另一個獨立部署（{deployment}）；本站為純靜態展示，不依賴該服務。」外連一律 `target="_blank" rel="noopener noreferrer"`＋lucide `ExternalLink` icon＋顯示目標 hostname。
- **v1 配置**：搜尋支柱 ✅（~~ptt-search 既有部署~~ **改判 2026-07-10：新建 Cloud Run `search-live`**——見 [搜尋支柱 design v2 §7](2026-07-10-search-pillar-design-v2.md)。搜尋支柱翻案為平台側自建進階中文檢索後，live-demo 目標從「外連 ptt-search 既有部署」改為「新建 search-live（Cloud Run＋Neon Postgres）跑平台同構 hybrid RRF SQL＋rerank」；ptt-search 部署保留不退役（§8.2）但 **v1 作品集不再外連它**，前身對照卡改純敘事＋截圖。此改判使 §8.2 待裁決 #4「ptt-search 部署 URL 存活」與 line 131 `pillars.ts` liveDemo 草樣一併被取代——URL 回填改指 search-live）；**問 AI 支柱 ✅ v1 就上**（Fergus 2026-07-10 定案；獨立 Cloud Run 端點跑 live LangGraph agent，per-day rate-limit follow-up，§6.4）；GA 支柱分析頁 ⏸（gated，GA 支柱 spec 評估是否需 live 運算外連，預設策展 JSON 足）；趨勢智能/平台架構 ✖（本體就是本站＋叢集，無外連對象）。

### 7.3 GA 支柱資料流骨架（合約邊界；細節 dataset/引擎 → GA 支柱 spec）

```
gold.gold_ga4_* 地基 4 表（已鎖）＋ dmp_*（P7）
   → GA 分析引擎（平台端 Python 套件，Airflow 批次；取材 ga-insight src/analytics/* 邏輯重寫）
   → gold.gold_ga4_insight_*（additive marts；dbt tag `ga4_insight`，selectors.yml append 沿 EP-D）
   → orchestration/exporter datasets.py additive 條目 → ga_insight_*.json（P4 §3 信封同構）
   → frontend (ga)/ 頁 build-time fs 讀（loadDataset 原樣）；absent 容忍沿 P4（GA 支柱頁可先上骨架誠實顯示「尚未由平台產出」）
```

本檔鎖的合約：①引擎跑**既有 Airflow**（不開第二排程）②只 additive 加 marts/dataset/MCP 工具（EP-D append 紀律）③不改地基 4 表與 P7 `dmp_*` ④檔名前綴 `ga_insight_`。引擎套件落點、marts 欄位、dataset 清單、頁面對應——全下放 GA 支柱 spec。

### 7.4 `/architecture` additive 擴充（本檔定內容，隨首個支柱 plan 落地）

P4 原頁區塊零改，**尾部 additive 一張「統一作品集整合模式」卡**：四支柱 × 「站上看到的/真運算在哪/佐證方式（截圖/MCP/live-demo）」對照表＋各支柱 live-demo 連結——把 Option A 本身變成展示品（「我知道什麼該靜態、什麼該誠實外連」是架構判斷力的敘事）。條目進 registry（`platform` 支柱 blocks）。

---

## 8. 退役與取材接法（唯讀不改原專案；進化非複刻逐點標）

### 8.1 ga-insight（取材後退役）

| 取材點（唯讀） | 取什麼 | 我方如何做得更好（重造層） |
|---|---|---|
| `src/analytics/conversion.py`（`ConversionFunnel`：`analyze_funnel`/`calculate_drop_off`/`identify_bottlenecks(threshold)`/`get_sankey_data`） | 漏斗步進計數、流失率公式、瓶頸判定 threshold、Sankey 資料形狀——**取材重點** | 重寫為**平台端批次**（SQL/Python on Gold，非 Streamlit runtime pandas）；公式進 registry `formula` 欄可稽核；Sankey/漏斗視覺 Recharts 重造（碼不可抄：Streamlit/Plotly≠Next/Recharts） |
| `src/analytics/{rfm,attribution,predictive,…}`（17 模組） | 各分析的**方法邏輯**（RFM 切分、歸因模型、流失/LTV 特徵） | GA 支柱 spec 逐模組標「取邏輯/重造工程」；預測類補 ga-insight 沒有的模型版本標註＋訓練窗揭露 |
| `src/components/ui_utils.py:23-52` `render_page_header` 五欄 | 每頁強制自我說明的**模式** | 升為集中 registry（§5）：+`whyBuilt`/`whatItDoes` 硬性欄、+formula/dataSource/caveats、+`aiVsComputed` 結構化、+阻擋級 gate——ga-insight 的 inline 散落弱點根治 |
| `src/agents/graph.py`＋`guardrails.py`＋六 sub-agents | orchestrator-worker＋雙 guardrail＋reflection 邏輯形狀 | §6.1/§6.2：P2b 基建複用、Prometheus 可觀測、trace 全揭露、收斂條件嚴謹化 |
| 五章敘事＋問句標題 | 問題導向敘事**原則** | §2.4：自設章節弧、不必同模板、硬性更完整面清單 |
| emoji 章節 icon（📈🚦📊💎🔮…） | **不取**——一律 lucide（Signal 驗收 #9 硬約束） | — |

**退役程序（拍板）**：GA 支柱＋問 AI 兩者 ship（站上漏斗/RFM 交叉引用/歸因/預測/問 AI showcase 全綠）後——①ga-insight repo README 頂部加「本專案已由 trend-intelligence-platform 統一作品集取代（連結）」並 archive ②履歷/求職素材連結替換 ③不刪 repo（歷史保留）。在此之前 ga-insight 維持現狀不動（唯讀取材不改原專案）。

### 8.2 ptt-search（保留部署，不退役）

live-demo 部署來源（§7.2）；唯讀取材搜尋 UX 敘事與 Signal §4.3 已定的六個元件取材點；本站不重建 ES（拓撲鐵律）。搜尋支柱 spec 補：ES 架構敘事的取材頁（`backend/` 檢索 API 形狀、`docker/`+`nginx/` 部署拓撲圖素材）。

---

## 9. 建置序（spec 序與 plan 序分列）

**spec 序**：Signal（已立）→ **本 crosscut** → ③GA 支柱 spec ∥ 搜尋支柱 spec（平行；GA 支柱吃 §2.4/§4/§7.3 契約，搜尋吃 §2.3/§7.2）→ ④問 AI spec（吃 GA 支柱 spec 的頁面/資料接縫，§6.5）。

**plan/實作序**（frontend 尚無碼，本檔契約隨 P4 plan 首次落地）：
1. P0–P3 平台 plans（既定序，與本檔無涉）。
2. **P4 plan**＝frontend 首建，**必含本檔契約**：route groups 骨架（§2.1，含空的 `(ga)`/`(search)` group 與 layout）、PillarShell 全套（§3）、registry types＋trends/platform 條目（8 頁）＋coverage gate（§5.5）、PageHeader/AiComputedBadge/LiveDemoCard、`/architecture` 整合模式卡（§7.4）。Signal＋本檔＋P4 design 三者合為 P4 plan 的完整輸入。
3. P6/P7/即時 plans：各自頁面落 `(trends)` group＋補自己頁的 registry 條目（gate 逼著補，漏了 CI 紅）。
4. 搜尋支柱 plan（前端敘事頁為主，P4 骨架後即可落，不等 GA4 地基）。
5. GA4 地基/P6/P7 實作後 → GA 支柱 plan（引擎＋marts＋datasets＋頁）→ 問 AI plan。
6. GA 支柱＋問 AI ship → ga-insight 退役程序（§8.1）。

---

## 10. 本檔拍板 vs 下放對照表

| 主題 | 本 crosscut 拍板（合約） | 下放（歸屬 spec） |
|---|---|---|
| 四支柱 IA | 支柱定義/順序/icon/頁面歸屬、route groups 機制、`/ga` `/search` segment、`/` 歸屬、route map | GA/搜尋支柱的頁清單與逐頁 IA |
| 切換 UX | PillarShell 元件契約、三重當前標示、桌面/行動形態、麵包屑移除、a11y | — |
| GA vs `/audience` | 視角邊界鐵律、正本圖唯一、`related` cross-link 機制、命名前綴 | GA 支柱各頁具體 cross-link 落點 |
| registry | schema 全欄、TS 載體、存放路徑、pageId 推導、元件 props 擴充清單、跨 app 機制、gate 六斷言 | 各支柱頁的**條目內容**（各 plan 填） |
| 問 AI | P2b 複用邊界、兩層形態、拓撲四件套、showcase 信封+rows 骨架、live-demo gated＋預設傾向、進化清單取捨、獨立 spec 歸屬 | graph 細設/tool 欄位/guardrail 規則/評估閘/trace 全欄/批次產線/live-demo 部署/`/ga/ask` 頁 IA |
| 整合模式 | 四件套統一模式、live-demo 慣例與 v1 配置、GA 資料流合約邊界（4 條）、`/architecture` 整合卡 | GA 引擎套件落點/marts 欄位/dataset 清單；搜尋離線示範語料源（預設傾向已給） |
| 退役/取材 | ga-insight 取材對照表＋退役程序與條件、ptt-search 保留、emoji→lucide | GA 支柱 spec 的逐分析模組取材細表 |
| ⌘K vs 搜尋支柱 | 邊界釘死＋palette 支柱分組＋registry 派生 page 條目 | 搜尋支柱頁內示範細設 |

---

## 11. 驗收清單（每條可實跑；隨 P4 plan 起生效、各支柱 plan 累加）

| # | 檢查 | 方法 | 預期 |
|---|---|---|---|
| 1 | route 零改＋group 不漏出 | `next build` 後斷言 `out/` 含 11 個既有路徑＋`ga/` `search/`；`find out -name '*(*' ` | 11 路徑齊；括號路徑零命中 |
| 2 | coverage gate 正例 | `npm run gate:explainers`（frontend-ci/admin-ci 必跑） | 綠 |
| 3 | coverage gate 反例 | 暫刪任一頁 `whyBuilt`（或 PageHeader 接線）重跑 | **紅**（阻擋級證明；一次性驗證寫進 README runbook） |
| 4 | 三重支柱標示 | 逐支柱開任一頁：頂欄 active tab＋sidebar header 支柱名＋`<title>` 含支柱名 | 三處一致 |
| 5 | 切換 a11y | 鍵盤 walkthrough（Signal 驗收 #7 擴充段）：Tab 走四 tab→sidebar；`aria-current` 語意（tab=`true`、sidebar 頁項=`page`） | 全鍵盤可達、focus ring 可見 |
| 6 | 禁裸用元件 | gate 斷言 5（grep `<ChartCaption`/`<Explainer` 無 `entryId`） | frontend/ 零命中 |
| 7 | 型別檔防漂移 | `pr-checks.yaml` drift job：diff tokens.css＋registry types.ts 兩對 | exit 0（admin 未建則 skip） |
| 8 | 誠實標示 | LiveDemoCard 含固定句式全文；`/ga/ask`＋每則 AI 敘事卡有 `AiComputedBadge`＋generated_at；FreshnessBanner 每頁在（含新支柱頁） | 逐項目視＋grep 句式字串 |
| 9 | 既有合約不退化 | P4 驗收 #9/#10、Signal 驗收 #10 原樣重跑（11 頁說明文字零刪改） | 綠 |
| 10 | cross-link 唯一正本 | 目視：GA 支柱無 R×F heatmap/P7 分群摘要重繪；`/audience` 無 LTV 預測；兩側 `related` 互指存在 | 符合 §4 鐵律 |
| 11 | ⌘K 支柱分組 | 開 palette：`page` 條目按四支柱分組、subtitle 來自 registry `whatItDoes` 首句 | 符合 §2.3 |

---

## 12. plan 期待查證點（皆帶預設傾向與降級；非阻擋本 design 收斂）

1. **route group＋`output:'export'` 實跑 smoke**——context7 已證機制（§0），plan 首個 build 以驗收 #1 斷言 `out/` 路徑收尾；異常（不預期）降級＝去 group、改 `PillarShell` 吃顯式 `pillar` prop 由各頁 layout 傳（URL 不變，只損失「layout 歸組」的整潔）。
2. **gate 的 pageId 推導函式對 App Router 邊角**（route group 巢狀、未來 parallel/private folder）——預設 §5.5 純函式＋自帶單測夠用；出現新路由型態時擴測試而非放寬 gate。
3. **lucide 1.24 icon export 名**（`ChartColumn` vs 舊名 `BarChart3` 等）——lockfile 落定時擇實存者，5 分鐘校準。
4. **ptt-search live-demo 部署 URL 現值與存活**——實查回填 `pillars.ts`；若部署已失效，`LiveDemoCard` 降級為截圖＋「部署已下線，架構見圖」誠實態（搜尋支柱 spec 給該態文案）。
5. **registry 進 palette lazy chunk 的實測體積**——預估數十 KB（文字），palette 本就 `next/dynamic`；若超 150KB，改為 prebuild 時 `tsx` 腳本吐輕量 `page-index.json` 併入 search-index（機制沿 Signal §7.1，additive）。
6. **PageHeader 與 Signal §5 各頁 treatment 的融合**——預設 PageHeader 即是「頁標列」的實作化（§5.3 已明列取代關係）；P4 plan 落頁時逐頁對照 Signal §5 表確認無雙標題。
7. **`sync-design-tokens` 更名的 Makefile 相容**——保留舊名 alias（§5.4），零破壞。

---

## 13. 精確度契約 8 條自檢

1. **開放問題收斂**：brief「Fable 5 要收斂/拍板」全項落單一決定（§1 十四項＋各節細則），零兩案並陳；僅 §12 七點標 plan 期實查且皆帶預設傾向與降級。兩層 AI／GA 頁清單等下放項是 brief 明文授權的範圍切分（§10 對照表），非未收斂。
2. **版本＋context7 查證**：§0——route groups 與 static-export 支援面當日 context7 查證（本檔唯二新承重宣稱）；前端依賴全沿 Signal §0 已證 pin，零新增依賴故零新版本宣稱；ga-insight/ptt-search 實碼第一手重 grep 覆核非轉抄。
3. **欄位級契約**：registry schema 全欄（§5.2）、`pillars.ts` 形狀（§3.1）、`ga_ask_showcase.json` rows 骨架（§6.4）、gate 六斷言（§5.5）、route map 到檔案層（§2.1）。
4. **部署/檔案形狀具體**：目錄樹、元件檔落點、Makefile/CI job 擴充點、dataset/marts/tag 命名空間、`out/` 斷言、退役程序步驟。
5. **沿用慣例不重造**：route 合約（P4 §5/EP-C）、explainers 正典路徑（EP-B）、信封與 absent 容忍（P4 §3）、EP-D append 紀律、Signal §2.4 drift 機制、P6 `make gen-*` 批次慣例、P2 §10 prompt registry、EP-J 模型 pin。
6. **進化非複刻**：§8.1 取材對照表逐點標「取什麼/重造什麼/不取什麼」；§2.4 章節敘事「約束不模板」；§6.1/§6.3 問 AI 逐項標超越點（trace 揭露/Prometheus/registry 化誠實標）。
7. **硬約束貫徹**：拓撲（純靜態、站上零 live LLM/ES、live-demo 外連誠實標、§7 四件套）、11 頁零改（§2.1 語意精確化＋驗收 #1/#9）、一工一具（無新排程/框架/DB；零新前端依賴）、a11y CRITICAL（§3.4＋驗收 #5）、無 emoji-icon（§8.1）、非互動不提問（全檔零待問）。
8. **每步可測**：§11 十一條全給命令或可執行目視程序，含 gate 反例實跑（#3）；gate 常駐兩 app CI 阻擋級。

---

## 14. 給 Opus 的把關提示（規劃者覆核建議點）

- **`/architecture` 的支柱歸屬**是本檔對 brief 表格模糊處（趨勢智能「11 頁」vs 平台架構「沿 /architecture」同時各表）的裁定：nav 歸平台架構支柱、趨勢智能 sidebar 列 10 頁——「全數保留」讀作 route/內容合約不動而非 nav 雙掛。若 Fergus 意圖是 11 頁全在趨勢智能 nav 內，改 `pillars.ts` 一處即回退，其餘設計不受影響。
- **麵包屑移除**是對 Signal 決策 11 的明文修訂（§3.2 有論證），Signal §13 已預告 nav 層會被本檔取代，但值得覆核確認。
- **問 AI live-demo gated（決策 11）**：brief 語氣（「最值得配 live-demo」）偏向要上；本檔以資安/成本理由改為問 AI spec 拍板＋預設傾向 Cloud Run scale-to-zero。若 Fergus 要 v1 就上，把 §6.4 的 gated 段升為問 AI spec 的必做項即可，框架不變。
- **admin 第五 pillar 值 `'admin'`**（§5.4）使共享 types.ts 含一個公開站不用的值——同構複製的必然代價，替代案（admin 自行 extend type）會破逐字節 diff，故取前者。

---

## 15. Opus 把關註記（2026-07-10；規劃者覆核結論）

**結論：PASS，可據以派生各支柱 spec。** 精確度契約 8 條逐條核對成立（§13 自檢屬實、非形式填充）；全檔零開放問題下推，下放項皆 brief 明文授權的範圍切分（§10 對照表）。

**獨立覆核承重宣稱（未只信 Fable 5 自證）**：本 design 全部路由決策壓在「Next.js route groups `(folder)` 不進 URL、可各掛 `layout.js`、且與 `output:'export'` 相容」這一機制上。Opus 獨立重跑 context7 `/vercel/next.js` 覆核，三條腿全 CONFIRMED：①route groups 括號段從最終 URL 省略（project-structure 原文）②每組可各掛 `layout.js` 施用獨立 layout（原文）③route groups 是 build-time 組織性功能、產出同樣靜態路由、無 runtime 依賴 → 與 static export 相容（官方 e2e 測試 `no-root-layout` 佐證多 group 各掛 layout 可共存）。§0 的宣稱屬實。**降級路徑（§12.1：去 group 改顯式 `pillar` prop，URL 不變）已備**，機制風險趨零。

**對 §14 四風險點的處置**：
1. **`/architecture` 支柱歸屬**：Opus 認同 Fable 5 裁定（architecture 頁＝平台架構支柱首頁、趨勢智能 nav 列 10 頁；「11 頁全數保留」讀作 route/內容合約不動非 nav 雙掛）——語意合理且雙掛違「當前支柱唯一標示」原則。一行 `pillars.ts` 可回退，列為向 Fergus 報告的確認點、非阻擋。
2. **麵包屑移除**：認可。Signal §13（Opus 前次註記）已預告頂層 nav 會被四支柱切換取代，本檔落成；兩層 nav＋頁深 ≤2 下麵包屑確為冗餘。
3. **問 AI live-demo → Fergus 2026-07-10 已拍板：v1 就上**（功能完整優先、成本不設限，per-day 執行次數上限列 follow-up）。決策 11／§6.4／§7.2 已同步翻正。問 AI spec 須把「部署 live 端點跑真 LangGraph agent」列為 v1 必做（非 gated）；守拓撲＝**外連獨立端點跑 live agent、靜態站本身仍零 live LLM**，前置 input guardrail 與誠實「獨立部署」標保留。rate-limit 為 v1 後 follow-up（問 AI spec 註記，不阻擋 v1）。
4. **admin 第五 pillar 值**：認可（同構逐字節 diff 的必然代價，替代案更糟）。

**無需改檔**：以上皆判斷認可或屬報告知會層級，design 本體不動。後續 spec 序照 §9 執行。
