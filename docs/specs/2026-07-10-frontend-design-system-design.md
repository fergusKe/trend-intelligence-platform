# 前端視覺設計系統 design（Tailwind v4 + shadcn/ui + 說明式 UI 視覺化 + fuse.js 全站搜尋）

> **上游**：[brief](2026-07-10-frontend-design-system-brief.md)（正本，已鎖定決策 1–4 全數沿用、零翻案）＋ P4 §5（8 頁/元件慣例/讀檔方式）＋ P6 §11（`/reco`）＋ P7 §6–7（`/audience` ＋ admin 4 頁）＋ 即時 §10（`/streaming`）＋ crosscut EP-B/EP-C（explainers 正典路徑、頁 9/10/11 共存）＋ NORTH_STAR「拓撲誠實」「說明式 UI」。
> **精確度**：依 CLAUDE.md「Fable 5 design 精確度契約（8 條）」產出，逐條對照見 §12。
> **定位（鐵律）**：本 design 只疊「視覺 token ＋ 元件實作規範 ＋ client-side 搜尋」三層。**11 頁的資訊架構、資料合約（P4 §3–4 信封/檔案清單）、MCP 工具、匯出 DAG 一字不動**；下文所有「頁面規範」都是視覺 treatment，不是 IA 變更。
> **一句話**：把 P4「刻意壓到最低的視覺層」升級為 portfolio 門面——設計系統代號 **Signal**（深空底 × 訊號藍 × 琥珀高亮），Tailwind v4 `@theme` 承載單一 token 真源，shadcn/ui 供元件底座，公開站與叢集內 admin 以「逐字節複製 tokens.css ＋ CI diff 守門」共用同一視覺語彙，搜尋走 build-time 裁切索引 ＋ client fuse.js，全程純靜態零 runtime backend。
> 產出日期：2026-07-10。**本階段只出 spec，plan 延後**；`frontend/`/`admin/` 尚無實作碼，以下規範全是「建立時即照此」，非事後重構。

---

## 0. 版本 pin 表（context7 ＋ npm registry 查證 2026-07-10；ptt-search 為已跑通錨點）

| 元件 | 版本 | 查證 | 備註 |
|---|---|---|---|
| Next.js / React | **16.2.x / 19.2.x**（沿 P4 §0 pin） | ptt-search `frontend/package.json` 錨點：`next 16.2.6` + `react 19.2.4` ＋ Tailwind v4 已在 Next 16 實跑通過 | 不重議 |
| tailwindcss / @tailwindcss/postcss | **4.3.2 / 4.3.2**（major 4 鎖定） | npm registry（2026-07-10）；context7 `/tailwindlabs/tailwindcss.com`：CSS-first `@theme` 定 token、`@theme inline` 引用外部變數、token 自動輸出為 `:root` CSS 變數；PostCSS plugin = `@tailwindcss/postcss`（ptt-search 同款 `^4`） | **無 tailwind.config.js**——v4 全 CSS-first，token 正本就是 CSS 檔（§2 機制的地基） |
| shadcn CLI / 元件 | **shadcn 4.13.0**（CLI；元件為 copy-in 原始碼無 runtime 版號） | npm；context7 `/shadcn-ui/ui`：`npx shadcn init --template next` 支援 Next；Tailwind v4 姿態 = `:root` 變數 ＋ `@theme inline` 映射（官方 tailwind-v4 文件原文形狀，§3 照抄） | style=`new-york`、`cssVariables: true` |
| tw-animate-css | **1.4.0** | npm；shadcn v4 官方手動安裝文件 `@import "tw-animate-css"`（取代已停維護的 tailwindcss-animate） | shadcn data-state 微動畫依賴 |
| motion（Motion for React） | **12.42.x** | npm；context7 `/websites/motion_dev`：import 自 `motion/react`；`<MotionConfig reducedMotion="user">` 自動依系統設定停用 transform/layout 動畫、保留 opacity；`useReducedMotion()` hook | 頁級入場/stagger/count-up 專用（§5.4 動效預算） |
| fuse.js | **7.4.2** | npm；context7 `/krisk/fuse`：`new Fuse(list, {keys, threshold})`、`Fuse.createIndex` 預建、`toJSON()/parseIndex()` 可序列化（本 design 拍板**不**預建索引檔，見 §7） | 零依賴、client-side |
| Recharts | **3.9.x**（major 3 沿 P4 pin；minor 由 lockfile 定案） | npm 3.9.2；ptt-search `^3.8.1` 錨點；context7 `/shadcn-ui/ui`：`ChartContainer`/`ChartConfig`/`ChartStyle` 以 `--color-*`/`--chart-*` CSS 變數上色（§5.3） | shadcn chart wrapper × Recharts 3 相容性 = 實查 1 |
| lucide-react | **1.24.0** | npm | 唯一 icon 來源（無 emoji-as-icon 的執行面） |
| 字型 | **Fira Sans / Fira Code**（Google Fonts，`next/font/google` build-time self-host） | ui-ux-pro-max typography 首選配對「Dashboard Data」；next/font 內建於 Next 16 | 中文 fallback 系統字疊（§2.3），零 runtime 字型請求、防 CLS |

npm 確切 minor/patch 由 plan 時 lockfile 定案；**major 線（Tailwind 4 / shadcn CLI 4 / motion 12 / fuse 7 / Recharts 3 / lucide 1）此處鎖定不再議**。

---

## 1. 關鍵決策（先拍板，細節在各節；brief 六簇開放問題全數收斂）

| # | 開放問題 | 決定 | 一句理由 |
|---|---|---|---|
| 1 | 風格取向 | **Data-Dense Dashboard 為體、Bento Grid 為點綴**（ui-ux-pro-max `--design-system` 主推 Data-Dense Dashboard：multiple charts/KPI cards/minimal padding/maximum data visibility；style domain 補查回 Dark Mode (OLED) ＋ Bento）——資料頁走緊湊卡片網格，僅 `/` 總覽首屏與 `/architecture` 用不對稱 bento span 造記憶點 | DE 儀表板的「wow」來自資料密度被馴服的秩序感，不是裝飾；skill anti-pattern 明列 **Ornate design**（棄）＋ **No filtering**（我方有 RegionTabs＋全站搜尋，過關） |
| 2 | 深色/淺色 | **深色單主題**（沿 P4 既定），token 直接寫在 `:root`、**不留 `.dark` 分支**、不裝主題切換 | 半套雙主題是假象維護面；淺色切換 = a11y 驗證面 ×2、對面試第一印象零增益 → 列進化方向（§11） |
| 3 | palette | **深空底 ＋ 訊號藍 ＋ 琥珀 CTA**：底=ui-ux-pro-max color domain「Financial Dashboard」深色系（`#020617` bg / slate 面板階 / `#F8FAFC` 文字），主色與 CTA 取「Analytics Dashboard」條目的 blue data + amber highlights（`#3B82F6` / `#F59E0B`），語意色取 chart domain sentiment 指引（正 `#22C55E`／負 `#EF4444`／中性 `#94A3B8`） | 兩條 skill 建議收斂成一組（不兩案並陳）；全表與對比驗算見 §2.1 |
| 4 | 字型 | **Fira Sans（標題/內文拉丁）＋ Fira Code（數字/資料/程式）**，`next/font/google` self-host；中文字自動 fallback `system-ui, "PingFang TC", "Microsoft JhengHei"` 系統字疊（**不掛 CJK webfont**） | ui-ux-pro-max 首選「Dashboard Data」配對（mood: data/technical/precise，Best For: dashboards/analytics）；CJK webfont＝MB 級載重＋CLS 風險，介面繁中主體走系統字最穩，拉丁與數字的 Fira 質感即是記憶點 |
| 5 | token 承載 | **單一真源 = `tokens.css`**（`:root` 原始值 ＋ `@theme inline` 映射兩段一檔），Tailwind utilities 與 shadcn 元件變數**同源**——shadcn 的 `--background/--card/--chart-*` 直接由我方 token 賦值，不存在第二套 | Tailwind v4 CSS-first ＋ shadcn 官方 v4 姿態天然同構（§3 有官方文件對照） |
| 6 | 跨兩 app token 共享 | **正本 `frontend/src/styles/tokens.css`；`admin/src/styles/tokens.css` 為逐字節複製**；防漂移 = `pr-checks.yaml` 加 `design-tokens-drift` job 跑 `diff`（§2.4） | Vercel root dir=`frontend/`＋「Include files outside root」關閉（P4 §6）→ frontend 物理上不能引 repo 根共用檔；monorepo workspace 為一個 CSS 檔翻掉兩 app 自足性 = 過度工程（P7 §6 同判） |
| 7 | 動效 | **雙層：tw-animate-css（shadcn 元件微互動）＋ motion 12（頁級入場 stagger / KPI count-up / hover lift）**；全站 `<MotionConfig reducedMotion="user">`，只准 transform/opacity，時長曲線見 §5.4 | wow 企圖需要 orchestrated 入場；CSS-only 做不出 stagger/count-up 的精緻度；motion 是 client 函式庫、build-time 合法 |
| 8 | heatmap | **沿用自製 CSS grid**（PTT 頁 / R×F），只換上 §2.2 sequential 色階 token | 「不為一張圖加庫」精神仍成立——heatmap 的 wow 靠色階設計與 hover 態，不靠換庫 |
| 9 | 搜尋形態 | **shadcn `Command` palette 全站搜（⌘K/Ctrl-K ＋ 頂欄可見按鈕）**；索引 = build-time prebuild 腳本從 `public/data/*.json` 裁切出輕量 `search-index.json`，client 首次開啟時 fetch ＋ `new Fuse()` 現場建索引 | 全站搜 > 各頁內篩（頁內已有 RegionTabs/表排序）；不預建 fuse 索引檔——數千列 `createIndex` 毫秒級，序列化索引=多一個要守門的 artifact（YAGNI，context7 查證 API 保留為進化路徑） |
| 10 | 視覺回歸 | **不納 v1**——Storybook/截圖 smoke 均為新常駐依賴；v1 守門 = build gate ＋ eslint-plugin-jsx-a11y ＋ token 防回潮 grep（§9）；列進化方向 | 摩擦/收益比：11 頁靜態站的視覺回潮由「色值只准活在 tokens.css」的 grep 守門先擋 80% |
| 11 | nav shell | **桌面左側固定 sidebar（分組導航）＋ 頂欄（麵包屑＋搜尋按鈕）；行動裝置 shadcn Sheet 抽屜**。11 頁分 5 組：YouTube 趨勢（`/` `/trends` `/channels` `/videos`）、觀眾與語料（`/sentiment` `/ptt`）、AI Lab（`/ai-lab`）、推薦與受眾（`/reco` `/audience` `/streaming`）、平台（`/architecture`） | 11 頁超出頂欄 tab 容量；sidebar 是 shadcn 一級公民（sidebar token 群現成）；分組是**視覺層導航呈現**，頁面 URL/內容零變動（EP-C「nav 順序不強制」授權範圍內） |

---

## 2. 簇 1：設計系統 token（單一真源全表）

### 2.1 色彩 token（正本值；對比為設計期驗算，WCAG 相對亮度公式手算、驗收時以工具複核）

**中性階（底與層次——深色 UI 以「背景階＋1px 邊框」做 elevation，陰影只輔助）**

| token | 值 | 用途 |
|---|---|---|
| `--bg` | `#020617` | 頁面底（midnight，非純黑——OLED style 條目建議深藍調） |
| `--surface-1` | `#0F172A` | 卡片/面板底 |
| `--surface-2` | `#1E293B` | hover 態、嵌套面板、code 塊底 |
| `--border` | `#1E293B` | 1px 分隔線/卡框（裝飾性，無對比要求） |
| `--border-strong` | `#334155` | 表格線、輸入框框線 |
| `--text` | `#F8FAFC` | 主文字（vs bg ≈19:1、vs surface-1 ≈17:1）✓ |
| `--text-muted` | `#94A3B8` | 次要文字/軸標/caption（vs bg ≈7.9:1、vs surface-1 ≈6.9:1）✓ |

**品牌與語意**

| token | 值 | 用途與對比規則 |
|---|---|---|
| `--primary` | `#3B82F6` | 圖形主色/大字 KPI/按鈕底（vs surface-1 ≈4.8:1——**合格但僅限圖形與 ≥18.66px 粗體大字**） |
| `--primary-text` | `#60A5FA` | 內文連結/互動小字（vs surface-1 ≈7:1）✓——**14px 級文字一律用這階，不用 `--primary`** |
| `--accent` | `#F59E0B` | CTA/高亮 badge/爆紅預測強調（vs surface-1 ≈8.3:1）✓ |
| `--positive` | `#22C55E` | 正向情緒/上升指標（≈7.8:1）✓ |
| `--negative` | `#EF4444` | 負向情緒/下降指標——圖形用；**文字用 `--negative-text: #F87171`**（≈6.5:1）✓ |
| `--neutral-sem` | `#94A3B8` | 中性情緒（chart domain sentiment 指引三色照收） |
| `--ring` | `#60A5FA` | focus ring（2px ＋ 2px offset，深底上可見性佳） |

**圖表 categorical（8 色 = 8 區恰好一色一區；亦供類別系列取前 N）**

`--chart-1: #3B82F6`（藍）`--chart-2: #F59E0B`（琥珀）`--chart-3: #22C55E`（綠）`--chart-4: #A78BFA`（紫）`--chart-5: #F472B6`（粉）`--chart-6: #2DD4BF`（青）`--chart-7: #FB923C`（橘）`--chart-8: #A3E635`（萊姆）——相鄰色相/明度交錯，色盲場景以 legend＋hover tooltip 補冗餘（ui-ux-pro-max chart domain a11y 註記：多系列需 legend/pattern 冗餘）。

**sequential 色階（heatmap 專用 5 階，低→高）**：`--heat-1: #0F172A`（=surface-1，零值格）→ `--heat-2: #1E3A8A` → `--heat-3: #1D4ED8` → `--heat-4: #3B82F6` → `--heat-5: #93C5FD`。格內文字：heat-1～4 上用 `--text`，heat-5 上用 `#0F172A`（深字，≈9:1）✓。

**diverging（情緒分歧條）**：`--negative` ← `--neutral-sem` → `--positive`（P4 `/sentiment` 既定 diverging BarChart 直接吃）。

### 2.2 非色彩尺標

| 軸 | 決定 |
|---|---|
| 圓角 | shadcn `--radius: 0.75rem` 單一旋鈕（衍生 sm/md/lg 照官方公式）；資料密集卡 `rounded-lg`（12px）、bento 大卡 `rounded-2xl`（16px）、badge/input `rounded-md` |
| 間距 | **沿 Tailwind 4px 預設尺標不自訂**；密度規範：資料卡 padding `p-4`、bento 卡 `p-6`、表格 cell `px-3 py-2`、頁面外框 `px-6 max-w-[1440px] mx-auto` |
| 陰影 | 深色 UI 主層次靠背景階；僅兩檔：`--shadow-card: 0 1px 3px rgb(0 0 0 / 0.4)`（常駐）、`--shadow-pop: 0 8px 30px rgb(0 0 0 / 0.5)`（popover/hover lift）。**禁 glow 濫用**：`--glow-accent: 0 0 20px rgb(59 130 246 / 0.15)` 只准出現在 `/` 首屏 hero KPI 與 `/architecture` 標題區（OLED style 條目「minimal glow」原文約束） |
| 字階 | display `30px/1.2 semibold`（頁標）、h2 `20px/1.3 semibold`、body `14px/1.6`、table `13px`、caption `12px`（ChartCaption/軸標）、KPI 值 `28px Fira Code tabular-nums`。數字一律 `font-variant-numeric: tabular-nums`（表格/KPI 對齊） |
| 動效 token | `--dur-fast: 150ms`（hover/focus）、`--dur-base: 250ms`（卡片/展開）、`--dur-slow: 400ms`（頁入場）；`--ease-out: cubic-bezier(0.2, 0, 0, 1)`（Tailwind v4 blog 範例 `--ease-snappy` 同款）。ui-ux-pro-max checklist「150–300ms smooth transitions」在射程內 |

### 2.3 字型接線（防 CLS）

`frontend/src/app/layout.tsx` 以 `next/font/google` 載 `Fira_Sans`（weights 400/500/600）與 `Fira_Code`（400/600），`display: 'swap'`、輸出 CSS 變數 `--font-fira-sans`/`--font-fira-code`；`tokens.css` 的 `@theme inline` 段接：`--font-sans: var(--font-fira-sans), system-ui, "PingFang TC", "Microsoft JhengHei", sans-serif`、`--font-mono: var(--font-fira-code), ui-monospace, monospace`。next/font 於 build 期下載並 self-host 進 `out/`——**零 runtime Google 請求，拓撲合法**；自動 fallback metrics 調整防 CLS。

### 2.4 跨兩 app token 共享機制（brief 點名的關鍵設計問題，拍板）

- **正本**：`frontend/src/styles/tokens.css`——內容 = ①`:root { …§2.1/2.2 全部原始 token… }` ②`@theme inline { …Tailwind/shadcn 命名空間映射（§3）… }` ③`@media (prefers-reduced-motion: reduce)` 全域動畫 kill-switch（§8）。**設計系統的全部 CSS 事實都在這一檔**。
- **副本**：`admin/src/styles/tokens.css`——逐字節複製（檔頭第一行註解 `/* SYNCED COPY — edit frontend/src/styles/tokens.css, then run make sync-design-tokens */`，此行含在 diff 範圍內故兩檔仍逐字節相同）。
- **同步**：Makefile `sync-design-tokens: cp frontend/src/styles/tokens.css admin/src/styles/tokens.css`（P4 Makefile 慣例 additive）。
- **防漂移守門**：`.github/workflows/pr-checks.yaml`（P4 §8 既有全域 workflow）additive 一個 `design-tokens-drift` job：`diff frontend/src/styles/tokens.css admin/src/styles/tokens.css`——**放全域 workflow 而非 frontend-ci/admin-ci**，因為 path-filtered workflow 在「只改單邊」時不會兩邊都醒，全域 diff 是唯一不漏的位置。admin 未建期間 job 以「admin 檔不存在則 skip」容忍（P4 absent 容忍精神）。
- **邊界**：共享**只止於這一個 CSS 檔**。元件碼、`components.json`、shadcn 產出的 `components/ui/*` 兩 app 各自持有（P7 §6「不共享套件」原判不動）；概念一致靠本 design 當規範正本。

---

## 3. Tailwind v4 ＋ shadcn/ui 落地機制（單一真源的接線形狀）

**`frontend/src/app/globals.css`**（admin 同構）：

```css
@import "tailwindcss";
@import "tw-animate-css";
@import "../styles/tokens.css";

@layer base {
  * { @apply border-border outline-ring/50; }
  body { @apply bg-background text-foreground font-sans; }
}
```

**`tokens.css` 的 `@theme inline` 映射段**（shadcn v4 官方姿態照抄——`:root` 放原始值、`@theme inline` 以 `--color-* : var(--*)` 掛進 Tailwind 命名空間，utilities 與 shadcn 元件即同源；context7 `/shadcn-ui/ui` tailwind-v4 文件原文形狀）：

```css
@theme inline {
  --color-background: var(--bg);
  --color-foreground: var(--text);
  --color-card: var(--surface-1);
  --color-card-foreground: var(--text);
  --color-popover: var(--surface-2);
  --color-popover-foreground: var(--text);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--bg);
  --color-secondary: var(--surface-2);
  --color-secondary-foreground: var(--text);
  --color-muted: var(--surface-2);
  --color-muted-foreground: var(--text-muted);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--bg);
  --color-destructive: var(--negative);
  --color-border: var(--border);
  --color-input: var(--border-strong);
  --color-ring: var(--ring);
  --color-chart-1: var(--chart-1);  /* …至 chart-8… */
  --color-positive: var(--positive);
  --color-negative-text: var(--negative-text);
  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --font-sans: …（§2.3）; --font-mono: …;
  --ease-out: cubic-bezier(0.2, 0, 0, 1);
}
```

- **PostCSS**：`postcss.config.mjs = { plugins: { "@tailwindcss/postcss": {} } }`（shadcn Next 模板原文；ptt-search 同款已驗）。**無 `tailwind.config.js`**。
- **shadcn init**：`npx shadcn@latest init`（Next 16 專案內執行；`components.json`：style `new-york`、`cssVariables: true`、baseColor 任選後**由 tokens.css 全量覆蓋**——baseColor 只影響初始生成值，我方 token 是終值）。元件一律 CLI `add`，不手貼（ui-ux-pro-max shadcn stack 條目 Severity High）。
- **深色單主題落法**：token 直接寫 `:root`，`<html>` 不掛 class、不裝 `@custom-variant dark`——沒有第二主題就不留切換機關（決策 2）。
- **admin**：獨立跑一次 `shadcn init`（同 style/同 `cssVariables`），`tokens.css` 用複製副本——兩 app 產出的 `components/ui/*` 各自入 repo，視覺一致性由同一 token 檔保證。

---

## 4. 簇 2：元件系統對映（既有元件慣例 → 新系統；建立時即照此）

### 4.1 對映總表

| 既有元件（P4/P6/P7 合約名） | 實作 | 說明 |
|---|---|---|
| `KpiTile` | **自建**（shadcn `Card` 為底 ＋ Fira Code tabular 數值 ＋ motion count-up ＋ 可選迷你 sparkline 槽） | 取材 ptt-search `SearchAnalyticsTab.tsx:22-33` KpiCard（label 小寫追蹤字距＋大數值）＋ `:57-61` 的 4-up grid（`grid grid-cols-2 lg:grid-cols-4 gap-4`）——**取版面 pattern，重造視覺層**（白底改 token、加動效） |
| `DataTable` | **自建薄殼**（shadcn `Table` ＋ client 排序 state ＋ sticky header） | 不引 TanStack Table——資料 ≤數百列、只需單欄排序；排序鈕 `aria-sort`、行 hover `bg-surface-2`（ui-ux-pro-max effects「row highlighting on hover」） |
| `RegionTabs` | **shadcn `Tabs`**（受控 `useState`，介面/預設 TW 不變） | P4 client-side filter 契約原樣，只換皮 |
| `TitleCompare` | **自建**（兩張 `Card` 並排、`base` 灰調/`tuned` accent 邊、中央 vs 分隔） | `/ai-lab` before/after 記憶點元件 |
| `RagCard` | **自建**（`Card` ＋ shadcn `Collapsible` 摺 sources ＋ provider/latency/token `Badge` 列） | LLMOps 佐證數據用 `Badge variant="outline"` ＋ Fira Code |
| `Heatmap` | **沿用自製 CSS grid**（決策 8），吃 `--heat-1..5`；hover 格 `--shadow-pop` ＋ shadcn `Tooltip` 顯示精確值；鍵盤：格為 `button` 可 Tab、tooltip 隨 focus 開 | PTT 頁與 `/audience` R×F 同一元件參數化（值域→5 階分位映射寫在元件內，兩處共用） |
| `FreshnessBanner` | **保留 RSC 讀 meta.json 的機制與全部文字**，視覺改：頁 footer 全寬條、`--surface-1` 底＋上邊框、左 lucide `Database` icon、`exported_at` 用 Fira Code、右側「平台架構 →」連結 | 誠實敘事內容零刪改（硬約束），只換視覺 |
| `components/explainers/`（InfoTooltip/ChartCaption/Explainer） | 見 §6 | 正典路徑不變（EP-B） |
| `components/charts/*` | 見 §4.2 | `'use client'` Recharts 包裝慣例不變 |
| nav（新增視覺層） | **shadcn 官方 `sidebar` 元件**（`--sidebar-*` token 群映射 `--surface-1`/`--text-muted`/`--primary`）＋ 行動端 `Sheet` | 決策 11 分組；現行路由高亮 `aria-current="page"` |
| 搜尋 | **shadcn `Command`（cmdk）** in `Dialog` | §7 |

**shadcn 元件安裝清單（CLI）**：`button card table tabs tooltip dialog command badge collapsible sheet sidebar skeleton separator scroll-area sonner`（admin 另加 `form input select label alert`）。此清單即 plan 的 `npx shadcn add` 參數，**不在此之外自由加裝**（加元件 = 改本清單）。

### 4.2 Recharts 主題化（統一上色機制）

- **採 shadcn chart wrapper**：`npx shadcn add chart` 得 `components/ui/chart.tsx`（`ChartContainer`/`ChartConfig`/`ChartTooltipContent`/`ChartLegendContent`，context7 查證：`ChartStyle` 把 config 色注入 `--color-<key>`，容器內建 `[&_.recharts-cartesian-axis-tick_text]:fill-muted-foreground`、grid 線改 `stroke-border/50` 等 Recharts 樣式覆寫——**軸/格線/tooltip 的主題化一次到位**）。
- 既有 `components/charts/*` 包裝慣例不變：每張圖仍是 `'use client'` 檔收 RSC props，內部以 `ChartContainer config={…}` 包 Recharts 原件；系列色一律 `color: "var(--chart-n)"`（或語意 `var(--positive)` 等），**元件內禁裸 hex**（§9 grep 守門）。
- 統一圖表規範：`<CartesianGrid vertical={false} strokeDasharray="3 3" />`、軸 `tick fontSize 12`、tooltip 一律 `ChartTooltipContent`（`--surface-2` 底 popover 樣式自帶）、`accessibilityLayer` 一律開（Recharts 3 鍵盤/screen-reader 支援）、sparkline 隱藏軸與 grid。
- diverging 情緒條：正 `var(--positive)`、負 `var(--negative)`；stacked 情緒面積：正/中/負 = positive/neutral-sem/negative（chart domain 指引三色）。
- **降級路徑**（若實查 1 不相容）：不裝 `chart.tsx`，自寫 ~60 行 `ChartTheme.tsx`（同樣以 CSS 變數 ＋ Recharts props 上色，覆寫範圍 = 上列統一規範），元件介面不變——plan 據實查結果二選一，頁面碼零差異。

### 4.3 ptt-search 取材界線（進化非複刻，精確度契約第 6 條）

| 取材點 | 取什麼 | 重造什麼 |
|---|---|---|
| `SearchAnalyticsTab.tsx:22-77` | KPI 4-up grid 版面、「KPI 卡＋圖卡＋表卡」頁面節奏 | 視覺全換 token（原白底淺色）；資料獲取**不取**（它是 runtime fetch＋loading 態，我方是 build-time props，無 loading 態） |
| `app/admin/page.tsx:10-56` | tabbed shell 的受控 tab state 形狀 | 導航升級為 sidebar（決策 11），tab 只在頁內（RegionTabs） |
| `app/page.tsx:85-139` | URL-as-state（searchParams 同步）概念 | **v1 不取**——公開站頁內 filter 是輕量 useState（P4 既定），URL 同步列進化方向；admin 的 OLAP 參數態 plan 可取此 pattern |
| `SearchBar.tsx:21-33` | debounce（300ms timer ref）＋ race-guard（`latestQuery.current` 比對後丟棄過期回應） | 我方搜尋是本地 fuse（無網路 race），取其 **debounce 節流**用於 palette 輸入（150ms）；race-guard 邏輯不需要、不搬 |
| `FilterSidebar.tsx:37-103` | 桌面固定側欄＋分組標籤的版面 | 內容換導航（原為 filter）；filter 語意不搬 |
| `lib/admin-api.ts:78-96` | typed client 分層（回傳型別集中宣告） | 公開站無 runtime API 不需要；**admin 的 `lib/api.ts` 照此分層**（P7 route handlers 的 client 端） |

---

## 5. 頁面視覺規範（11 頁；IA/資料/區塊清單一律照 P4 §5、P6 §11、P7 §7.2、即時 §10 原文，此表只給 treatment）

| 頁 | 視覺 treatment（不動區塊結構） |
|---|---|
| `/` 總覽 | **全站唯一 bento 首屏**：12-col grid，KPI tiles（count-up）佔 4×(3-col)，兩張 highlight 卡（最高爆紅/最負面）2-col span ＋ `--glow-accent`，迷你 AreaChart 卡收尾；入場 stagger（§5.4） |
| `/trends` `/channels` `/videos` `/sentiment` `/ptt` `/reco` `/audience` `/streaming` | **Data-Dense 標準頁模板**：頁標 display 字階＋一句 muted 副標（頁 Explainer 觸發器同列）→ RegionTabs（有 region 維度的頁）→ 圖卡/表卡 `grid gap-4`（單欄圖全寬、並列圖 2-col）；每卡 = `Card` ＋ 標題列（h2＋InfoTooltip）＋ 圖 ＋ ChartCaption |
| `/videos` 預測 badge | `p_doubled_24h ≥ 0.5` 用 `--accent` badge（琥珀=注意力色），tooltip 帶 model_version（既定內容）；機率條用 `--primary` 微型 progress |
| `/ai-lab` | 卡片牆 `columns-1 lg:columns-2` masonry 流；RagCard/TitleCompare（§4.1）；provider/latency badge 排 Fira Code |
| `/architecture` | bento 敘事版面：架構圖 SVG 全寬卡、截圖牆 2×3 grid（hover scale 1.02 ＋ Dialog 放大——ui-ux-pro-max Portfolio Grid 條目的 lightbox/hover-overlay pattern 落點）、誠實敘事文字塊原文保留、MCP 指引卡以 Fira Code code 塊呈現 |
| 全頁共通 | sidebar ＋ 頂欄（麵包屑＋⌘K 按鈕）＋ footer FreshnessBanner；`absent` 資料態 = 卡內 lucide `CircleSlash` ＋「此資料尚未由平台產出」（P4 既定文字）＋ muted 樣式，**不做 skeleton**（靜態站無載入中，skeleton 是拓撲謊言；skeleton 只准 admin 用） |

### 5.4 動效預算（wow 但克制的硬邊界）

| 動效 | 實作 | 約束 |
|---|---|---|
| 頁入場 | motion：卡片 `opacity 0→1 + y 8→0`，stagger 50ms，`--dur-slow` | 每頁一次、首屏元素限 12 個內 |
| KPI count-up | motion `animate(0→value)`，600ms，`--ease-out` | `useReducedMotion()` 為 true → 直接渲染終值 |
| hover | 卡 `translateY(-2px)` ＋ `--shadow-pop`；bento/截圖 `scale(1.02)`；`--dur-fast` | transform/opacity only（ui-ux-pro-max Performance）；`cursor-pointer` 全可點元素 |
| 元件微動 | tw-animate-css（shadcn data-state 進出場） | 不另寫 keyframes |
| 全域護欄 | `<MotionConfig reducedMotion="user">` 包 root layout（context7 查證：自動停用 transform/layout、保留 opacity）＋ tokens.css 內 `@media (prefers-reduced-motion: reduce){ *,::before,::after { animation-duration:0.01ms !important; transition-duration:0.01ms !important } }` 蓋住 tw-animate-css 的 CSS 動畫 | 雙保險寫進 token 正本，兩 app 同得 |
| **禁區** | 無限循環動畫、scroll-jacking、視差、>600ms 任何動效、資料圖表本體動畫（圖表首繪不動畫——資料可讀性優先） | 違者即「為炫技犧牲可讀性」 |

---

## 6. 說明式 UI 三層的視覺語彙（內容契約不動，設計進系統）

正典路徑 `frontend/src/components/explainers/` 不變（EP-B）；`Explainer` `defaultOpen` prop、「定義類展開/方法論類收合」語意、各頁既定說明文字（P6 §11/P7 §7.3/即時 §10 原文）**一字不改**。視覺升級：

| 元件 | 視覺規範 |
|---|---|
| `InfoTooltip` | lucide `Info` 14px `--text-muted`，hover 變 `--primary-text`；內容用 shadcn `Tooltip`（`--surface-2` 底、max-w 280px、caption 字階）；**可 focus**（`tabIndex=0`，focus 同 hover 開啟——鍵盤等權） |
| `ChartCaption` | 圖下常駐、caption 字階 `--text-muted`、左緣 2px `--border-strong` 豎線縮排；公式片段以 `<code>` Fira Code 呈現（如 `hit@10 = …`） |
| `Explainer` | 原生 `<details>` 保留（零依賴既定）＋ 樣式：summary 列 = lucide `BookOpen` ＋ 標題 ＋ 右側 chevron（`open` 態旋轉，`--dur-base`）；展開內容 `--surface-1` 底、`rounded-lg`、`p-4`；**定義類（defaultOpen）加左緣 `--primary` 3px 豎線**視覺標記「先讀我」 |
| 佈局慣例 | 頁級 Explainer 固定在頁標下方第一個元素；圖級 InfoTooltip 固定在卡標題右側——**位置一致性本身是說明式 UI 的可用性**（面試官逛三頁後就知道去哪找解釋） |

admin 的同概念元件各自實作（P7 §6 原判），但**視覺規範照本節**（token 同檔，樣式類名可直接對齊）。

---

## 7. 簇 3：client-side 搜尋（fuse.js 7.4.2；零 backend、純靜態合法）

### 7.1 資料流

```
（build 時）frontend/scripts/build-search-index.mjs（prebuild hook，跑在 check-data.mjs 之後）
  讀 public/data/{videos,channels,rag_showcase,title_examples,ptt_board_daily,reco_similar,dmp_segments}.json
  → 逐 dataset 裁切輕量欄位 → 寫 public/search-index.json（status:"absent" 的 dataset 跳過）
（runtime，client）首次開啟 palette → fetch('/search-index.json')（同站靜態資產，非 runtime backend）
  → new Fuse(items, { keys:['title','subtitle'], threshold:0.35, ignoreLocation:true }) 現場建索引
  → 輸入 150ms debounce → fuse.search(q) → 分組渲染
```

### 7.2 索引 schema（`search-index.json`；本檔為**前端自產自銷的衍生物**，不是新資料合約——不進 P4 §4 合約清單，重跑 prebuild 即重生）

統一條目 `{ type, title, subtitle, href }`：

| type | 來源 | title / subtitle | href |
|---|---|---|---|
| `page` | bundle 內靜態 registry（11 頁） | 頁名 / 一句用途（沿各頁 Explainer 首句） | 該 route |
| `video` | videos.json（每區 top100 既定裁切） | title / `channel_title · region` | `/videos` |
| `channel` | channels.json | channel_title / `region · rank` | `/channels` |
| `rag` | rag_showcase.json | question / 「AI Lab · RAG 問答」 | `/ai-lab` |
| `title_example` | title_examples.json | tuned 標題 / 「LoRA 標題改寫」 | `/ai-lab` |
| `board` | ptt_board_daily.json（board 去重） | 看板名 / 「PTT 熱度」 | `/ptt` |
| `reco_item` | reco_similar.json seeds | 商品名 / category | `/reco` |
| `segment` | dmp_segments.json | 分群名 / 「受眾分群」 | `/audience` |

- **大小守門**：`build-search-index.mjs` 斷言產出 ≤300KB（超限先砍 `video` 條目 title 截 80 字、再降 top-N——守門進 `check-data.mjs` 同層，frontend-ci 必跑）。預估 ~2,000 條目 ×~100B ≈ 200KB，安全。
- **不預建 fuse 索引**（決策 9）：`createIndex` 對 2k 條目毫秒級；`toJSON()/parseIndex()`（context7 查證可行）留作條目破萬時的進化路徑。
- **導航語意**：v1 結果導到對應頁（不 deep-link 高亮單列——需跨頁 state 通道，列進化方向）。

### 7.3 UX 與 a11y

- 觸發：頂欄可見按鈕（`Search` icon ＋「搜尋 ⌘K」kbd 樣式）＋ 全域 `⌘K`/`Ctrl+K`（**按鈕可見是 a11y 硬要求**，快捷鍵不是唯一入口）。
- shadcn `Command` in `Dialog`：cmdk 內建 combobox ARIA、↑↓ 移動、Enter 前往、Esc 關閉、focus trap 與還原。
- 結果按 type 分組（`CommandGroup` 標題 = 上表中文組名）、每組上限 8 條、条目右緣 muted type 標。
- **無結果誠實態**：`CommandEmpty` =「找不到『{q}』——本站搜尋範圍限於已匯出的靜態資料（影片/頻道/看板/問答/商品/分群），匯出於 {meta.exported_at}」——把拓撲誠實寫進空態。
- 載入索引失敗（快取壞檔等邊角）：palette 內顯示「搜尋索引載入失敗，請重新整理」，不裝死。
- fuse.js 以 `next/dynamic` 隨 palette 首開才載（bundle 紀律：首屏 JS 不含搜尋）。

---

## 8. 簇 4：DMP admin app 視覺套用（`admin/`，`output:'standalone'`，叢集內）

- **同一設計系統**：`tokens.css` 複製副本（§2.4）＋ 同款 globals.css ＋ 獨立 `shadcn init`（同 style）。sidebar/頂欄 shell 同構（4 頁一組導航），**視覺上與公開站是同一產品**——這正是 portfolio 敘事點（「公開門面與內部工具共用一套 design token」寫進 `/architecture` tech stack 一行）。
- **admin 專屬互動層**（公開站禁用、admin 因有 server runtime 合法）：
  | 態 | 實作 |
  |---|---|
  | 載入 | shadcn `Skeleton`（表格 5 列骨架/圖卡矩形骨架）——admin 有真網路延遲，skeleton 誠實 |
  | 回饋 | `sonner` toast（標籤存檔/刪除/物化成功失敗） |
  | 表單 | shadcn `form/input/select/label`（`/tags` CRUD、`/audiences` 巢狀條件建構器——結構照 P7 §5.2 文法，本 design 只給控件視覺：條件列 = `--surface-2` 圓角列、群組縮排 ＋ 左緣豎線、and/or 切換用 `Tabs` 微型款） |
  | 查詢佐證 | **timing badge**：每個 OLAP 查詢結果右上 `Badge variant="outline"` ＋ Fira Code「`{elapsed_ms} ms · scanned {rows}`」（P7 §6 既定 statistics 呈現的視覺落點；欄式秒回是展示主場，把數字做成視覺元素） |
  | 錯誤 | P7 統一 `{error}` 信封 → shadcn `Alert variant="destructive"`，不洩 stack（P7 既定） |
- **區別記號**：admin 頂欄左側常駐 `Badge` 「叢集內工具 · port-forward」（`--accent` outline）——誠實標示這不是公開站，與 FreshnessBanner 同一誠實語彙。
- 邊界：視覺共享止於 token 檔；admin 不引公開站任何元件檔，無跨 app runtime 耦合（brief 硬約束原樣）。

---

## 9. 驗收清單（每條可實跑；簇 6）

| # | 檢查 | 命令/方法 | 預期 |
|---|---|---|---|
| 1 | 拓撲守門 | `cd frontend && npm run build` | `output:'export'` 綠、產出 `out/`（任何 server 功能 build fail） |
| 2 | 內網端點守門 | P4 既有 grep（`check-data.mjs`：`.svc`/`localtest.me`/`host.docker.internal`）對 `out/` 與 `src/` | 零命中；`frontend/` 無 env secret |
| 3 | token 單一真源 | `grep -rEn '#[0-9a-fA-F]{3,8}\b' frontend/src --include='*.tsx' --include='*.css' | grep -v styles/tokens.css` 進 frontend-ci | **零命中**——色值只准活在 tokens.css（防回潮守門；chart 色一律 `var(--chart-n)`） |
| 4 | 兩 app 防漂移 | `pr-checks.yaml` `design-tokens-drift` job：`diff frontend/src/styles/tokens.css admin/src/styles/tokens.css` | exit 0（admin 未建則 skip） |
| 5 | a11y 靜態 | `eslint-plugin-jsx-a11y`（recommended）進兩 app eslint config；`npm run lint` | 零 error |
| 6 | a11y 對比 | §2.1 對比表逐條以 WebAIM contrast checker 複核（一次性，token 變更時重跑） | 文字類 token 全 ≥4.5:1（大字/圖形類 ≥3:1）；`--primary` 僅圖形/大字、內文用 `--primary-text` 的規則寫進 tokens.css 註解 |
| 7 | a11y 鍵盤 | 手動 walkthrough 腳本（README runbook）：Tab 走完 sidebar→頂欄→⌘K→頁內卡片；heatmap 格可 focus；InfoTooltip focus 可開；palette ↑↓/Enter/Esc | 全程無滑鼠可操作、focus ring 全程可見 |
| 8 | reduced-motion | 系統開啟「減少動態」重載 | 入場/count-up/hover lift 全停（MotionConfig ＋ CSS kill-switch 雙層），內容即時可讀 |
| 9 | 無 emoji-icon | `grep -rP '[\x{1F300}-\x{1FAFF}]' frontend/src admin/src --include='*.tsx'` 進 CI | 零命中（icon 只准 lucide-react） |
| 10 | 說明式 UI 留存 | 沿 P4 驗收 #9 擴充：11 頁逐頁有頁級 Explainer、每圖卡有 ChartCaption、每頁 footer 有 FreshnessBanner `exported_at`；`/reco` A/B 誠實 banner、`/streaming` 置頂重放聲明原文在 | 內容零刪改 |
| 11 | 搜尋 | ①`build-search-index.mjs` 產出 ≤300KB 斷言 ②vitest：對 fixture index，`fuse.search('教學')` 回含該字影片條目、亂碼 query 回空 ③手動：⌘K 開、鍵盤選、無結果態顯示誠實文案 | 全綠 |
| 12 | 視覺 smoke | `npx serve out` 逐頁目視 ＋ §5 treatment 對照（bento 首屏/badge 色/heatmap 色階） | 與本 design 一致 |

---

## 10. plan 前需實查（皆帶預設傾向與判準）

1. **shadcn `chart.tsx` × Recharts 3.9 相容性**——預設相容（context7 所見 v4 registry 原始碼即 RechartsPrimitive 泛用包裝）；`npx shadcn add chart` 後若 peer/型別衝突 → 走 §4.2 降級路徑（自寫 ~60 行 ChartTheme，頁面碼零差異）。
2. **`shadcn init` 對既存 Next 16 專案的偵測**——預設 CLI 自動偵測 Tailwind v4 ＋ App Router；異常則照官方 manual 安裝文件手落（§3 已列 globals.css 終態形狀，手落成本 ~10 分鐘）。
3. **next/font/google 在 CI/離線 build 的字型下載**——預設可（Vercel/GH Actions 有網）；若 build 環境斷網 → 改 `next/font/local` ＋ 把 Fira 兩家 woff2 收進 `frontend/src/fonts/`（OFL 授權允許，`public/` 總量守門內）。
4. **search-index 實測大小**——預設 ~200KB；超 300KB 照 §7.2 降階順序砍。
5. **admin 端 shadcn 元件於 `output:'standalone'` Docker build 的產物體積**——預設無虞（copy-in 原始碼隨 app 打包）；僅記錄無需前置驗證。

**進化方向（明列不做，防未來誤判為遺漏）**：淺色主題切換、Storybook/截圖視覺回歸、搜尋 deep-link 高亮、URL-as-state 頁內 filter、fuse 預建序列化索引（`toJSON/parseIndex`）。

---

## 11. 沿用慣例與邊界（防重工自檢）

- **不動**：11 頁 IA/區塊/資料檔對應（P4 §5、P6 §11、P7 §7.2、即時 §10）、匯出檔合約與信封（P4 §3–4）、MCP 10+ 工具、`loadDataset` build-time fs 讀檔、RegionTabs client-filter 契約、absent 容忍路徑、explainers 正典路徑與 defaultOpen 語意、FreshnessBanner/誠實文字內容、admin 4 頁與 API 形狀（P7 §6）、兩 app 不共享套件原判。
- **翻案（僅此一項，Fergus 已批）**：P4 §5「CSS Modules ＋ 零 CSS 框架」→ Tailwind v4 ＋ shadcn/ui。P4 design 該格於 plan 落地後由規劃者補一行勘註指向本 spec（文件層動作，非合約變更）。
- **CI 接線全 additive**：frontend-ci 既有四步（P4 §8）中間插 `build-search-index.mjs` 與 grep 守門；pr-checks 加 drift job；admin-ci（P7 既定）加 lint/a11y 同款步驟。
- **成本/拓撲**：新增依賴全為 build-time/client npm 套件；零新部署、零常駐、零 env、零 runtime 請求外站（字型 self-host、無 CDN）。

---

## 12. 精確度契約 8 條自檢

1. **開放問題收斂**：brief 六簇全部拍板單一決定（§1 十一項＋各節細則），零 TBD/兩案並陳；僅 §10 五點標「plan 前需實查」且皆帶預設傾向與降級判準。
2. **版本＋context7 查證**：§0 全表——Tailwind 4.3.2/`@theme`（context7）、shadcn CLI 4.13.0/v4 主題姿態（context7）、motion 12.42/`MotionConfig reducedMotion`（context7）、fuse.js 7.4.2/`createIndex`（context7）、Recharts 3.9/shadcn chart 上色機制（context7）、npm registry 版號 2026-07-10 當日查證、ptt-search package.json 實跑錨點。
3. **欄位級契約**：token 全表（§2.1–2.2 名/值/用途/對比）、`@theme inline` 映射（§3）、search-index 條目 schema（§7.2，並明確劃出「非 P4 合約、自產衍生物」）、shadcn 安裝清單封閉列舉（§4.1）。
4. **部署/檔案形狀具體**：tokens.css 三段內容、globals.css 原文、postcss.config、components.json 關鍵值、prebuild 腳本路徑與斷言、Makefile target、pr-checks job、目錄落點全列。
5. **沿用慣例**：P4 check-data/grep 守門擴充不重造、absent 容忍沿用、EP-B 路徑沿用、P7 admin 拆分沿用、Makefile/CI additive 模式沿用（§11）。
6. **進化非複刻**：ptt-search 六個取材點逐一標「取什麼/重造什麼/不取什麼」（§4.3）。
7. **硬約束貫徹**：拓撲（`output:'export'` build gate＋grep＋字型 self-host＋搜尋純 client）、說明式 UI 不退化反升級（§6）、誠實敘事內容零刪改（§4.1 FreshnessBanner/§7.3 空態/§8 admin 標記）、a11y CRITICAL 落成驗收 #5–9、工具紀律（禁 ES/runtime 服務/第二 OLTP——全案零新服務）。
8. **每步可測**：§9 十二條驗收全部給命令或可執行 walkthrough；防回潮 grep 進 CI 常駐。

---

## 13. Opus 把關註記（規劃者驗收，2026-07-10）

**結論：8 條精確度契約逐條達標，承重整合點經獨立 context7 覆核確認，可作為全站視覺地基。**

- **獨立 context7 覆核（承重整合點，防記憶陷阱）**：規劃者另查 context7 `/shadcn-ui/ui` tailwind-v4 主題文件，確認 §3 機制**正確**——官方原文即 `:root` 放原始 token、`@theme inline` 映射 `--color-*: var(--*)`、`@layer base { * { @apply border-border outline-ring/50 } body { @apply bg-background text-foreground } }`、`--radius-{sm,md,lg}` 以 `calc(var(--radius) …)` 衍生，與本 design §3 一字對應。ptt-search（Next 16.2.6 + Tailwind `^4`）為已實跑錨點，雙重佐證。
- **一處無害偏離（非阻擋，plan 自決）**：shadcn 官方範例多以 `hsl()`/`oklch()` 包色值並保留 `.dark` 變體；本 design 用裸 hex + 深色單主題（決策 2，不留 `.dark`/`@custom-variant dark`）。裸 hex 是合法 CSS 色值、與 `@theme inline` 及 opacity modifier（`outline-ring/50` 靠 `color-mix()`）相容，無正確性問題；單主題省去 `.dark` 分支與本 design 決策一致。plan 若欲對齊官方慣例可改 oklch，屬風格非契約。
- **⚠️ reframe 前瞻標記（2026-07-10，Fergus 令「統一作品集」重定位）**：本 design 的**設計系統本體**（§2 token／§3 Tailwind+shadcn 機制／§4 元件系統／§5.4 動效／§6 說明式視覺／§7 搜尋／§8 admin／§9 驗收）**pillar-agnostic、全數成立、不受重定位影響**，是四主題共用的視覺地基。但**頂層資訊架構層**（§1 決策 11「11 頁分 5 組 sidebar」、§4.1 nav 列）將被後續「統一作品集程式 crosscut」**擴充/取代**為四支柱主題切換（🔍搜尋／📊GA分析／📈趨勢智能／🏗平台架構），讓 nav 從「單站 11 頁分組」升為「跨主題切換 + 主題內導航」。§5/§7.2 的「11 頁」清單屆時擴充為含 GA/搜尋主題新頁——**屬 additive，token/元件/機制零重寫**。實作序：本設計系統為地基先立，crosscut 定四支柱 IA，各主題 spec 補頁。
- **plan 前實查 5 點**（§10）皆帶預設傾向與降級路徑，合契約第 1 條「非實查不可才標且給預設」；規劃者無異議。
- **搜尋 §7 與統一站的銜接**：§7 現以「11 頁靜態資料」為索引源，重定位後搜尋主題（原 ptt-search ES 全文檢索）會另立為一支柱——§7 的 client-side fuse.js 全站搜（跨頁快速跳轉）與「搜尋主題」（PTT 語料全文檢索展示）是**兩個不同東西**，crosscut 會釘清邊界，本 design 的 §7 定位為「全站導航式快速搜」不變。
