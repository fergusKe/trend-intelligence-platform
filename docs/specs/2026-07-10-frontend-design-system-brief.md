# 前端視覺設計系統（Tailwind v4 + shadcn/ui + 說明式 UI + client-side 搜尋）— 交給 Fable 5 的 spec brief

> **交付流程**：Fable 5 讀本 brief +（接地）既有前端合約 → `superpowers:brainstorming` → 產出 `docs/specs/2026-07-10-frontend-design-system-design.md` →（**本階段只出 spec，plan 延後**）。
> **精確度契約**：本 brief 產出的 `*-design.md` **必須**滿足 [`../../CLAUDE.md`](../../CLAUDE.md)「Fable 5 design 精確度契約（8 條）」。交稿前自檢：「若我是寫 implementation plan 的人、只拿這份 design、不能問任何人，切得出無歧義 plan 嗎？」
> **定位（防重工，最重要一句）**：頁面結構、資料合約、MCP 工具清單、匯出檔合約**已被 P4/P6/P7 design 鎖死，本 spec 一律不重寫**。本 spec 是**在既有頁面之上疊一層「視覺設計系統 + 元件實作規範 + client-side 搜尋」**——把刻意壓到最低的視覺層，升級成 portfolio 等級的門面。**動到既有頁面/資料/MCP 的欄位或結構＝越界**。
> **接地已由規劃者（Opus）完成**：既有前端版圖、ptt-search 可複用 pattern、拓撲/工具紀律皆已 grep 到 file:line（見下）。Fable 5 設計階段仍須自行以 context7 查證版本用法、並用 ui-ux-pro-max skill 產出設計系統。

## 一句話目標

把 trend-intelligence-platform 的前端從「刻意乾淨可讀的 plain CSS Modules 儀表板」升級為**視覺有記憶點、專業、可被面試官一眼記住**的 portfolio 門面：導入 **Tailwind v4 + shadcn/ui** 設計系統（用 `.claude/skills/ui-ux-pro-max` 產出的 palette/style/typography/effects 落地）、把既有 11 頁與說明式元件重塑到這套系統上、加 **client-side（fuse.js）搜尋**、並讓叢集內 **DMP admin app** 共用同一套視覺語彙。**不碰**任何資料合約與頁面資訊架構。

## 為什麼現在做（且為什麼是純視覺/元件層，不是新功能）

既有 P4/P6/P7 design **刻意把視覺壓到最低**（明碼："CSS Modules + globals.css design tokens（深色單主題）、零 CSS 框架—YAGNI"、"不為一張圖加庫"、系統字疊不掛 webfont）。這在功能規劃期是對的取捨；但這是**求職 portfolio**，門面的視覺水準本身就是差異化。Fergus 已（①加入 ui-ux-pro-max skill ②指定參考 ptt-search 的 Tailwind 前端）表達升級意圖，並拍板下方三決策。故本 spec 專責視覺/元件/搜尋，與資料/ML/DevOps 能力展示正交、零重疊。

## 既有前端版圖（接地，是地基，**逐頁勿改結構**）

> 下列頁面/元件/合約來自已通過精確度契約的 design；本 spec 只換它們的視覺皮與元件實作，不換骨。

- **公開站（Vercel，`output:'export'` 純靜態）共 11 頁**（P4 §5 八頁 + 擴充三頁，頁碼 9/10/11 由 `ga4-extension-crosscut.md:84` 裁定共存）：
  - P4 §5：`/` 總覽、`/trends` 趨勢、`/channels` 頻道、`/videos` 影片+爆紅預測、`/sentiment` 觀眾情緒、`/ai-lab` AI Lab（RAG 問答牆 + LoRA 標題 before/after）、`/ptt` PTT 熱度（CSS grid heatmap）、`/architecture` 平台架構敘事。
  - `/reco` 推薦（recommendation-design.md:387，6 區塊：相似品/熱門榜/分群代表/離線評估圖/A-B 重放卡/線上能力佐證）。
  - `/audience` DMP 分群（p7-dmp-design.md:455：KPI + 8 分群 donut + 4 價值級 bar + R×F CSS-grid heatmap + tag 覆蓋 bar）。
  - `/streaming` 即時正確性（realtime-features-design.md:391：批次對照靜態頁，**非即時輪詢**）。
- **既有元件慣例**（P4 §2 目錄樹 + recommendation-design.md:387/391）：`RegionTabs / KpiTile / DataTable / TitleCompare / RagCard / Heatmap / FreshnessBanner` + `components/charts/`（`'use client'` Recharts 包裝）。
- **說明式 UI 三層（跨 P4/P6/P7 硬性交付，正典路徑已裁定）**：`InfoTooltip / ChartCaption / Explainer`，單一實作落 `frontend/src/components/explainers/`（`ga4-extension-crosscut.md:74`，`Explainer` 帶 `defaultOpen` prop；P7 舊 `explain/` 路徑作廢）。**每個頁/圖帶「這是什麼／為什麼看／怎麼用」**（NORTH_STAR.md:215）。
- **資料讀取**：build-time `fs` 讀 `frontend/public/data/*.json`（P4 §5「讀檔方式」），前端零 runtime 抓取。
- **DMP admin app（叢集內，非公開）**：獨立 Next.js app `admin/`，`output:'standalone'`、server runtime、持 PG/CH 憑證、port-forward 存取（p7-dmp-design.md:18/36/427），4 頁：`/` tag 覆蓋、`/tags` CRUD、`/audiences` 受眾建構器（含即時預覽）、`/olap` 事件洞察（漏斗/留存/交叉）。**與公開 `frontend/` 不共享套件**（p7-dmp-design.md:427）。
- **FastMCP server**（P4 §7，10+ 工具）：無 UI，本 spec 不涉及。
- **狀態**：以上全為 spec，**尚無實作碼**（`frontend/`/`admin/` 目錄尚未建，`docs/plans/` 空）。故本 spec 產出時，前述元件是「將依 design 建立」而非「改既有檔」——design 要據此把視覺規範寫成「建立時即照此」而非「事後重構」。

## 已鎖定決策（Fergus 2026-07-10 拍板，**勿翻案**；其中一項是對 P4 的 approved 翻案）

1. **樣式棧 = Tailwind v4 + shadcn/ui**（**翻 P4「零 CSS 框架 / CSS Modules / YAGNI」決定，Fergus 已批准此架構翻案**）。理由：與 Fergus 自有 ptt-search 一致（已在 Next 16 驗證可跑）、ui-ux-pro-max 最強 stack、元件庫加速精緻度；且 Tailwind/shadcn 全 **build-time**，`output:'export'` 純靜態不破。
2. **搜尋 = client-side（fuse.js）**，在瀏覽器索引 committed JSON，零 backend、不破靜態拓撲。**否決真 ES 後端**（破拓撲 + 與 ptt-search 重複；ES 的搜尋工程展示由 ptt-search 那份獨立作品承擔）。
3. **覆蓋範圍 = 公開站 11 頁 + 叢集內 DMP admin app 一起**，統一到同一套設計系統。
4. **精緻度企圖 = 「wow」高精緻**（重動效/bento 版面/漸層/漸層層次等），但**克制不浮誇**——distinctive 且專業，服務面試第一印象；不得為炫技犧牲可讀性、a11y、或說明式清晰度。

## 硬約束（**貫徹並寫進 design**，違反即失敗）

- **拓撲鐵律（公開站）**：`frontend/` 永遠 `output:'export'` 純靜態、打不到本地 k8s、零 runtime backend；任何 middleware/route handler/server action 一律禁（build fail = 編譯期守門）。搜尋走 client-side、動效走 client 元件、圖表 `'use client'`——皆合靜態。（NORTH_STAR.md:204、`ga4-extension-crosscut.md:147`）
- **工具紀律**：Tailwind/shadcn/fuse.js/動效庫皆為**前端 build-time/client 函式庫、非常駐 infra**，不違「一工一具」（該紀律管的是排程/DB/OLAP/串流等 infra）。**仍禁**：ES/OpenSearch、任何公開站 runtime 服務、為前端新增第二個 OLTP DB。（CLAUDE.md:76-77、p7-dmp-design.md:22 ES 在「刻意不引入」）
- **成本姿態**：本 repo 成本紅線**反向**（跑 server 是目的）——但**公開呈現層仍守靜態優先**（P4 brief §43「呈現層別堆常駐服務」）。視覺升級零新增部署/常駐。
- **說明式 UI 不可退化**：升級視覺**不得**削弱三層說明元件；反而要把它們設計進視覺系統（InfoTooltip/ChartCaption/Explainer 要有一致的視覺語彙）。正典路徑 `frontend/src/components/explainers/` 不變。
- **誠實敘事**：每頁 footer `FreshnessBanner`（讀 meta.json `exported_at`）、`/architecture` 誠實敘事、`/reco`/`/streaming` 的「線上/即時能力在叢集內、本站為批次匯出」誠實文字——這些**內容**不得因改版被移除，只可換視覺呈現。（P4 §5、recommendation-design.md:389、realtime-features-design.md:387）
- **a11y 為 CRITICAL**：ui-ux-pro-max 把 Accessibility/Touch 列 CRITICAL（對比 4.5:1、focus ring、鍵盤序、觸控 44px、無 emoji 當 icon 用 SVG icon set）——design 要把這些寫成可驗收條目，不是口號。
- **非互動不提問**：design 階段所有開放問題照精確度契約收斂成決定，真非實查不可才標「plan 前需實查 X」+ 預設傾向。

## 範圍（簇；Fable 5 定簇內細節與先後）

### 簇 1：設計系統本體（用 ui-ux-pro-max 產出、落成具體 token）
- **必須實際執行 ui-ux-pro-max skill** 取得有據建議（非憑感覺）：`python3 .claude/skills/ui-ux-pro-max/scripts/search.py "<query>" --design-system`（query 建議如 `data engineering analytics dashboard portfolio dark professional`），並可 `--domain style/color/typography/chart/ux` 補查。design 要**引用它回的具體 palette/style/typography/effects/anti-patterns**，收斂成單一設計系統（不兩案並陳）。
- **收斂項**：主色/中性階/語意色（正負/警示）、深色為主是否加淺色切換、字型配對（heading/body，優先可自 Google Fonts 靜態內嵌或系統字，避免 CLS）、圓角/陰影/間距尺標、動效時長曲線、風格取向（如 bento grid / glass / minimal-with-accent 擇一並說明為何配 DE 儀表板）。
- **token 落地機制**：Tailwind v4 的 `@theme` / CSS custom properties 如何承載 token；shadcn/ui 主題如何對齊同一組 token（單一真源，不讓 Tailwind 與 shadcn 各定一套）。
- **跨兩 app 的 token 共享**（關鍵設計問題）：公開 `frontend/` 與 `admin/`「不共享套件」（p7-dmp-design.md:427），但要**共用同一設計系統**——design 要拍一個機制（如：單一 `design-system/tokens.css`/Tailwind preset 由兩 app 各自以相對路徑引用，或明碼複製 + 一支 check 腳本防漂移）。給具體落點與防漂移守門。

### 簇 2：元件系統（把既有元件重塑到 Tailwind+shadcn，借鏡 ptt-search）
- 把 §「既有元件慣例」逐個對映到新系統：哪些用 shadcn/ui 原生（Button/Card/Table/Tabs/Tooltip/Dialog/Command…）、哪些自建、Recharts 圖表如何吃設計 token 上色（統一色板、grid/軸/tooltip 樣式）。
- **借鏡 ptt-search（Fergus 自有、Tailwind v4 已驗證，唯讀取材不改原專案）**，取材點（Opus 已接地）：Recharts KPI tile + 4-up grid（`SearchAnalyticsTab.tsx:22-77`）、tabbed dashboard shell（`app/admin/page.tsx:10-56`）、URL-as-state（`app/page.tsx:85-139`）、debounced autocomplete + race-guard（`SearchBar.tsx:21-33`）、filter sidebar（`FilterSidebar.tsx:37-103`）、typed API client 分層（`lib/admin-api.ts:78-96`）。標清「取哪個 pattern vs 重造哪個工程層」（精確度契約第 6 條）。
- **heatmap**：P4/P7 既有自製 CSS grid heatmap（PTT 頁 / R×F）——design 決定沿用自製（配新 token）或換庫，給理由（延續「不為一張圖加庫」精神 vs wow 需求的權衡）。
- **動效**：選一個動效方案（Framer Motion 或 CSS/tailwindcss-animate）並 context7 查證；守 `prefers-reduced-motion`、transform/opacity-only（ui-ux-pro-max Performance）。

### 簇 3：client-side 搜尋（fuse.js）
- **收斂**：搜什麼（跨頁全站搜？影片/頻道/品牌/PTT 看板/分群？）、索引來源（哪幾支 committed JSON）、索引何時建（build-time 預建索引檔 vs client 首載時建，權衡 bundle/首屏）、UX 形態（shadcn `Command` palette 全站搜 / 各表頁內即時篩）、a11y（鍵盤操作、focus 管理、無結果誠實態）。
- context7 查證 fuse.js 版本與 Next 靜態相容用法；給落點（元件、資料流、鍵盤快捷）。

### 簇 4：DMP admin app 的視覺套用
- 同一設計系統套到 `admin/`（`output:'standalone'`）；因 admin **有 backend**，可用互動元件（表單/即時預覽/OLAP 查詢態）——design 要說明 admin 相對公開站可多用哪些互動/loading 態（shadcn 表單、skeleton、toast），但視覺 token 與公開站一致。
- 尊重既有拆分：兩 app 不共享套件、admin 持憑證叢集內——視覺共享僅止於 token/樣式，不引入跨 app runtime 耦合。

### 簇 5：版本 pin + context7 查證（精確度契約第 2 條）
- **必查並 pin**：Tailwind v4（`@tailwindcss/postcss` 與 Next 16 整合、`@theme`）、shadcn/ui（Next 16 App Router 安裝/CLI/主題、與 Tailwind v4 相容性）、Recharts 3（主題/自訂色）、動效庫、fuse.js。**得對照 ptt-search 已跑通的 `frontend/package.json` 版本**作為錨點（Tailwind ^4 + `@tailwindcss/postcss` + Next 16.2 已驗證），但仍以 context7 查最新用法。

### 簇 6：驗收（每條可測；精確度契約第 8 條）
- **build/topology 守門**：`cd frontend && npm run build`（`output:'export'` 綠即拓撲守門）；grep `out/` 無 `.svc`/`localtest.me`/內網端點；公開站無 env secret。
- **設計系統一致性**：token 單一真源可驗；Tailwind 與 shadcn 同源；兩 app token 防漂移 check 可跑。
- **a11y**：對比 ≥4.5:1、focus ring 可見、鍵盤序、無 emoji-as-icon、`prefers-reduced-motion`——給可驗收清單（可掛 lint/axe smoke）。
- **說明式 UI 留存**：每頁/圖有 InfoTooltip/ChartCaption/Explainer；FreshnessBanner 與誠實文字留存。
- **搜尋**：fuse.js 搜尋回相關結果、無結果誠實態、鍵盤可操作——給斷言。
- **視覺回歸**：（design 判斷是否納入）截圖/Storybook 或最小視覺 smoke，作為未來防回潮基準。

## 範圍邊界

- **in**：設計系統 token、Tailwind v4 + shadcn/ui 導入、既有 11 頁 + 說明式元件的視覺/元件實作規範、client-side fuse.js 搜尋、DMP admin 視覺套用、版本 pin、驗收。
- **out**（**明令不碰**）：任何頁面的資訊架構/欄位/資料合約（P4 §3-5、P6/P7 匯出檔清單）、MCP 工具清單與 schema（P4 §7）、匯出 DAG（P4 §3）、ML/資料/DevOps 能力本身、area02 真資料（不進本 repo）、實際 build 實作（plan 後才做）、真 ES/搜尋後端（已否決）。
- **判斷納否**：視覺回歸工具（Storybook/截圖 smoke）、淺色主題切換、動效庫具體選型——design 依 wow 企圖與摩擦權衡，納入給落點、否則標「後續」並說明。

## 相依與順序

- 前置：無新資料/服務依賴（純前端層）。與 P4/P6/P7 design 解耦（只讀它們的頁面/元件契約、不改）。
- 建議 plan 順序（供 design 尾段給 plan 前實查點時參考）：簇1 設計系統 token → 簇2 元件系統（含 shadcn init + Recharts 主題）→ 簇3 搜尋 → 簇4 admin 套用 → 驗收。**簇1 是其餘簇的地基，必先。**
- **跨兩 app token 共享機制**是本 spec 的關鍵設計問題（兩 app 不共享套件）——design 須先釘死它再展開簇2/簇4。

## 交付流程尾註

Fable 5 走 `superpowers:brainstorming` 出 design，滿足 CLAUDE.md 精確度契約 8 條。**本階段只出 spec，plan 延後**。產出 `docs/specs/2026-07-10-frontend-design-system-design.md`。產出後由規劃者（Opus）逐條把關才據以（未來）寫 plan。
