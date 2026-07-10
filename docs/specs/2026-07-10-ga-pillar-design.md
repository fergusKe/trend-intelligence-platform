# GA 分析支柱 design（漏斗為核心的完整銷售分析——取代並超越 ga-insight）

> **上游**：[brief](2026-07-10-ga-pillar-brief.md)（工作合約正本）＋ repo `CLAUDE.md`「Fable 5 design 精確度契約（8 條）」（自檢見 §15）＋ [統一作品集 crosscut design](2026-07-10-unified-portfolio-crosscut-design.md)（binding：§2.2/§2.4/§4/§5/§6.3(a)/§7.3/§10）＋ [Signal 設計系統 design](2026-07-10-frontend-design-system-design.md)（視覺地基，不重定）＋ [GA4 地基 design](2026-07-09-P6-ga4-ingestion-foundation-design.md)（§4/§5.1–5.4/§13 已鎖合約，唯讀）＋ [P4 呈現層 design](2026-07-08-P4-presentation-layer-design.md) §3–4（信封/absent 容忍）＋ [ga4-extension-crosscut](2026-07-09-ga4-extension-crosscut.md) EP-D（append 紀律）。
> **定位**：GA 分析支柱＝`(ga)/` 純靜態頁群（8 頁）＋ GA 分析引擎（平台端批次）＋ `gold.gold_ga4_insight_*`/`ml.ga_insight_*` additive 表 ＋ `ga_insight_*.json` datasets ＋ MCP 工具。**進化非複刻**（crosscut §2.4）：ga-insight 的五章弧與問句標題是輸入非模板；漏斗為核心章（Fergus 定案）。
> **產出日期**：2026-07-10。**本階段只出 spec，plan 延後**；`frontend/(ga)/` 尚無實作碼，以下全是「建立時即照此」。問 AI graph/sub-agent/guardrail 細設**不在本 spec**（→問 AI spec，crosscut §6.5）。

---

## 0. 接地與版本查證（2026-07-10 第一手）

### 0.1 版本敏感宣稱（context7 當日查證；其餘全沿已證 pin，零新前端依賴）

| 宣稱 | 查證結果 | 來源 |
|---|---|---|
| **Recharts 3 原生支援 `FunnelChart`/`Funnel` 與 `Sankey`** | ✅ 官方 docs 有完整 FunnelChart 範例（`<FunnelChart><Funnel dataKey data>` + `LabelList` + `Tooltip`）；a11y 文件明列支援 chart 清單含「FunnelChart, Treemap, **Sankey**, SunburstChart」且 `accessibilityLayer` 預設開——漏斗核心章的兩個主視覺**不需任何新依賴** | context7 `/recharts/recharts`（2026-07-10） |
| **Recharts `Cell` 已標 deprecated（4.0 將移除）** | ✅ 原始碼 docstring：改用各 chart 的 `shape`/`content` prop 客製——plan 期漏斗分段上色一律走 `fill`/`shape`，禁用 `Cell`（防未來升版重工） | 同上 |
| Next 16 route groups × `output:'export'` / Tailwind 4 / shadcn 4 / lucide 1 / motion 12 | 沿 **crosscut §0 + Signal §0 pin 表**（皆已 context7 查證＋Opus 獨立覆核 PASS）——本檔零新增前端依賴，不重查不翻案 | crosscut §0/§15、Signal §0/§13 |
| Airflow 3.2.2 / dbt-postgres 1.10.2 / google-cloud-bigquery 3.42.2 / pyiceberg 0.11.1 | 沿 **GA4 地基 §0 pin**（已鎖）——本檔平台端零新排程器/零新 DB；引擎新 pin（scikit-learn）見 §8.2 | 地基 §0 |

### 0.2 ga-insight 第一手 grep 覆核（唯讀；碼不可抄 Streamlit/Plotly≠Next/Recharts，取分析邏輯與內容架構）

repo：`/Users/fergus/Desktop/workshop/fergus/llm-workshop/ga-insight`（`src/analytics/` 17 模組實數，`wc -l` 覆核 3,326 行）。

| 素材 | file:line 錨點（本次實讀） |
|---|---|
| 漏斗核心 | `conversion.py:32-75` `analyze_funnel`（逐步 user_count/conversion_rate/drop_off_rate）；`:143-158` `calculate_drop_off`；`:160-184` `identify_bottlenecks(threshold=30.0)`（`drop_off_rate ≥ threshold` 即瓶頸＋`users_lost`）；`:186-238` `get_sankey_data`（頁面轉移 top-N link）；`:240-274` `get_recommendations`（瓶頸→**canned if-else 建議文**）；`:320-326` `DEFAULT_ECOMMERCE_FUNNEL` 五步（session_start→view_item→add_to_cart→begin_checkout→purchase） |
| 歸因 | `attribution.py:26-58` `_prepare_journeys`（30 天 lookback、touch_order/total_touches）；`:60-109` 四模型權重（first/last/linear/`time_decay: 2^(−days/7)` `:84-92` 正規化）；`:111-138` `compare_models` |
| RFM/分群 | `rfm.py:27-73` qcut 五分位 R/F/M 分數；`:75-126` 8 規則分群；`:259-290` KMeans；`reference_date=datetime.now()`（`:23`——靜態資料集下是錯的，地基 §5.4 已用 `data_anchor_date` 修正） |
| 預測 | `predictive.py:38-72` LTV：**XGB 回歸擬合「啟發式捏造目標」**（`:54-56` `y_target = monetary + freq×AOV×3×e^(−0.05×recency)`——訓練目標是自己編的公式＝偽 ML）；`:74-117` churn：**label 直接由特徵 `recency>60` 導出（`:89-93`）＝標籤洩漏、模型只是學回自己的規則**；`:110-114` 風險分帶 0.7/0.4 |
| 購物車 | `cart_abandonment.py:28-75` session 旗標法（has_cart 而無 has_purchase＝放棄）＋ shipping/payment 分步流失（`:60-66`） |
| 搭售 | `market_basket.py:35-116` fpgrowth＋association_rules（support/confidence/lift、**毛利假設硬編 40%** `:33`）；`product.py:85-156` 手寫 pair-count 版（Counter＋combinations，零依賴） |
| NES | `nes_model.py:29-99` New/E0/S1/S2/S3 規則（cycle_days=30、S 級距倍數） |
| 異常 | `anomaly_detector.py:14-44` 日指標（DAU/purchases/CVR）；`:46-65` rolling z-score（window=7, threshold=2.0, upper/lower bound）；`:67-111` IsolationForest |
| 跨期 | `comparative.py:17-43` 期間指標；`:45-126` MoM/YoY＋**連環替代法瀑布拆解**（`:103-121`：`effect_traffic = dS×CR₀×AOV₀`、`effect_conversion = S₁×dCR×AOV₀`、`effect_aov = S₁×CR₁×dAOV`、unexplained 殘差） |
| 流量 | `traffic.py:20-155`（`last_non_direct`/first_click 歸因模式、channel performance）；`:451-513` 獲客品質矩陣 |
| 自我說明 | `ui_utils.py:23-52` `render_page_header` 五欄（chapter/title/description/can_do/problem）——crosscut §5 已升集中 registry |
| 五章弧＋問句標題 | `pages/01…20_*.py` grep 實證：第一章｜業績全貌（01）、第二章｜認識客群（05/07）、第三章｜找到問題（02/03/08）、第四章｜立刻行動（11/12）、第五章｜問 AI（20）；問句標題如 `03:25`「客人在哪個步驟跑掉？」、`02:24`「哪個渠道真的有效？」 |
| 不取清單 | `recommender.py`（推薦＝P6 `/reco` 正本）、`semantic_search.py`（embedding 歸 P6）、`sequence_nlp.py`（4 事件白名單下序列訊號過薄）、`ab_testing.py`（sample 無實驗資料）、`feedback_store.py`（runtime 回饋＝拓撲違法）、emoji 章節 icon（Signal 驗收 #9） |

---

## 1. 關鍵決策總表（brief 8 項全數收斂；細節在各節）

| # | brief 項 | 決定 | 一句理由 |
|---|---|---|---|
| 1 | 章節弧與頁清單 | **五章 8 頁**：①生意整體怎麼樣（`/ga`）②**客人在哪裡流失（核心章：`/ga/funnel`＋`/ga/cart`）**③客人是誰值多少（`/ga/customers`＋`/ga/churn`）④錢從哪來該推什麼（`/ga/attribution`＋`/ga/products`）⑤直接問 AI（`/ga/ask`）；navGroups/版面型別見 §2 | 問題導向非功能清單（§2.4 約束）；漏斗章給兩頁（宏觀流失＋微觀放棄）撐起「核心章」的份量 |
| 2 | 漏斗頁 | 明確公式組（drop-off/瓶頸雙判準/users_lost 優先序）＋ Recharts FunnelChart＋Sankey 階段流視覺＋裝置/來源雙切片＋規則模板建議（computed 非 AI）；全公式進 registry `formula` 欄 | §3；θ 進 pipeline.yaml 單一真源，靜態站無 slider → 門檻是**拍板值**非互動參數 |
| 3 | 歸因頁 | **真 session 級多觸點歸因**：additive 新萃取（session touches，§4.2）→ journey 重建 → 四模型對照（first/last/linear/time_decay）＋逐模型假設表＋**營收守恆驗證**（Σ歸因=Σ實際，ga-insight 沒有的可稽核性） | 地基 `first_touch_*` 是 user-scoped（地基 known-limit 6），做不出多觸點——不硬撐假歸因，補一張誠實的 session 觸點表（地基 §13.3 自帶的 additive Silver 演進條款） |
| 4 | 分群/LTV/流失 | GA 支柱做**新分析**：lifecycle 月轉移（NES 進化）＋LTV 十分位/Pareto（觀測窗實測值，**拒做 ga-insight 式捏造目標的「預測 LTV」**）＋復購/流失預測（**時間切分修正 ga-insight 標籤洩漏**、模型卡＋門檻閘）；R×F heatmap/8 分群正本留 `/audience`，`related` 互指 | crosscut §4 鐵律；§5 |
| 5 | v1 頁面取捨 | 17 模組逐一判定（§7 全表）：**採 10**（conversion/attribution/rfm 衍生/predictive 修正版/cart/market_basket/nes/anomaly/comparative/product/traffic 折半）**、拒 6**（recommender/semantic_search/sequence_nlp/ab_testing/feedback_store/emoji），判準＝Gold+touches 能否真支撐 | completeness-first 但 grounded：每頁都有實資料，不硬撐薄訊號 |
| 6 | 引擎與資料流 | **dbt marts（SQL 可算）＋ Python 引擎（模型/規則類）雙層**：dbt tag `ga4_insight` 出 `gold.gold_ga4_insight_*` 9 張；引擎 `ml/ga_insight/`（自有 image、KPO）出 `ml.ga_insight_*` 4 張＋模型登錄表；跑**既有 Airflow** 兩條新 DAG（touches 有界回放鏡像地基＋`ga_insight_batch` schedule=None）；exporter additive 12 dataset；MCP additive 5 工具 | §8；一工一具不破（排程只 Airflow、DB 只 Postgres、無新框架） |
| 7 | registry 條目 | 8 頁 × 34 blocks 覆蓋清單（§9），`whyBuilt`/`whatItDoes` 硬性欄由本支柱 plan 落地時撰寫（crosscut §5.2 歸屬），**questionTitle 與 formula 欄內容由本 spec 定稿**（它們是章節弧與可稽核公式，非文案）；v1 全站 `aiVsComputed='computed'`（唯 `/ga/ask` 與每頁問 AI 區 `ai-narrative`） | crosscut §5 schema 原樣；gate 六斷言自動涵蓋 `(ga)/` 頁 |
| 8 | 每頁問 AI 摺疊區 | `AskAiTeaser` 元件：位置＝頁尾 FreshnessBanner 之上；讀 `ga_ask_showcase.json` `scope==='page:<pageId>'`；三態（正常/檔 absent/無本頁列）全定義（§10）；graph 細設零涉入 | crosscut §6.3(a) 接縫原樣 |

**贯穿裁定（非 brief 列項但需釘死）**：
- **insight 資產的讀取面**：dbt marts 只准 `ref('stg_ga4_events')`、`ref('stg_ga4_insight_session_touch')` 與地基四 Gold model（`ref('gold_ga4_*')`）；**不觸 YouTube 資產、不讀 P7 `dmp_*`**（crosscut §7.3 雖列 dmp 為引擎可及輸入，本 spec 拍板 v1 不讀——GA↔DMP 走 `related` cross-link 鬆耦合，EP-I 同精神，避免建置序耦合 P7）。
- **/ga/products 與 `/reco` 邊界**：搭售規則表（support/confidence/lift 業務分析）≠ `/reco` 相似商品展示（推薦工程垂直）——不重繪 `/reco` 任何卡，`related` 互指（crosscut §4「資料源不是邊界，視角才是」）。
- **建議文案姿態**：ga-insight `get_recommendations` 的 canned 建議（`conversion.py:263-272`）進化為**規則模板建議**（程式依瓶頸階段選模板、帶入真數字），registry 標 `computed`——v1 分析頁**零 LLM 敘事**，AI 敘事集中在問 AI 面（誠實分工）。

---

## 2. 章節弧與頁清單（brief 項 1）

### 2.1 route map 與 navGroups（回填 crosscut `pillars.ts` 的 `ga.navGroups`）

```
frontend/src/app/(ga)/ga/
├── page.tsx              # /ga           第一章
├── funnel/page.tsx       # /ga/funnel    第二章（核心）
├── cart/page.tsx         # /ga/cart      第二章（核心）
├── customers/page.tsx    # /ga/customers 第三章
├── churn/page.tsx        # /ga/churn     第三章
├── attribution/page.tsx  # /ga/attribution 第四章
├── products/page.tsx     # /ga/products  第四章
└── ask/page.tsx          # /ga/ask       第五章（頁 IA 歸問 AI spec；本 spec 只佔 route＋nav＋registry 覆蓋）
```

```ts
// pillars.ts ga 條目（crosscut §3.1 保留欄回填；本 spec 定稿）
ga: { name: 'GA 分析', icon: 'ChartColumn', homeRoute: '/ga',
     navGroups: [
       { label: '生意全貌',       routes: ['/ga'] },
       { label: '漏斗與流失',     routes: ['/ga/funnel', '/ga/cart'] },      // ★ 核心章
       { label: '客群價值',       routes: ['/ga/customers', '/ga/churn'] },
       { label: '來源與商品',     routes: ['/ga/attribution', '/ga/products'] },
       { label: '問 AI',          routes: ['/ga/ask'] },
     ] },
```

- 與既有 11 route ＋ `/search` 零交集；`(ga)` route group 機制沿 crosscut §2.1（已 context7＋Opus 三腿覆核）。
- 章節（navGroup label）＝registry `chapter` 欄值，兩處同字串（gate 斷言 6 的支柱一致性之上，plan 加一條「chapter ∈ navGroups labels」單測）。

### 2.2 每頁一覽（問句標題＝registry `questionTitle` 定稿；版面型別＝Signal 決策 1 variety-with-coherence 授權內）

| route | pageId | 章節 | questionTitle（定稿） | 版面型別 | 吃的 dataset |
|---|---|---|---|---|---|
| `/ga` | `ga` | 生意全貌 | 這門生意的體質怎麼樣？ | `overview-kpi`：KPI tiles 列 → 營收趨勢＋異常標記全寬卡 → 月對月瀑布卡 → 章節導覽卡（四章入口，取代 bento 首屏的角色） | kpi_daily, period_compare |
| `/ga/funnel` | `ga-funnel` | 漏斗與流失 | 客人在哪一步跑掉？ | `flow-hero`：全寬 FunnelChart 置頂 → 瓶頸卡列 → Sankey 階段流 → 裝置/來源切片 2-col → 建議卡 | funnel, funnel_daily |
| `/ga/cart` | `ga-cart` | 漏斗與流失 | 加了購物車，為什麼沒買？ | `analysis-grid`：放棄率 KPI → 分段（裝置/來源）對比 → 放棄價值估算卡 | cart, funnel |
| `/ga/customers` | `ga-customers` | 客群價值 | 誰在成長、誰在沉睡？ | `analysis-grid`：lifecycle 堆疊面積（月） → 轉移 heatmap（自製 CSS grid，Signal 決策 8 元件參數化重用） → LTV 十分位＋Pareto 曲線 | lifecycle, lifecycle_transitions, ltv |
| `/ga/churn` | `ga-churn` | 客群價值 | 誰快要不回來了？ | `model-card`：模型卡置頂（版本/訓練窗/指標/門檻閘結果——誠實揭露即版面主角） → decile lift 圖 → 風險分帶計數＋特徵摘要 | churn |
| `/ga/attribution` | `ga-attribution` | 來源與商品 | 哪個來源真的帶來營收？ | `model-compare`：四模型假設對照表置頂 → channel×model grouped BarChart → 模型間排名變動表 → 守恆驗證徽章 | attribution |
| `/ga/products` | `ga-products` | 來源與商品 | 該主推哪些商品與組合？ | `analysis-grid`：Pareto 雙軸（Bar＋累積 Line） → 商品漏斗散點（view→purchase rate × revenue） → 搭售規則表（DataTable） | products, basket_rules |
| `/ga/ask` | `ga-ask` | 問 AI | 不想看圖，直接問數據？ | 問 AI spec 定（crosscut §6.3(b) 已定框：策展 Q&A 卡牆＋trace 展開＋架構圖＋MCP 指引＋live-demo 外連） | ga_ask_showcase |

進化非複刻對照：五章弧「業績全貌→認識客群→找到問題→立刻行動→問 AI」→ 我方「全貌→**流失（核心，前移）**→價值→行動面（來源/商品）→問 AI」；「立刻行動」章的受眾匯出/喚醒（ga-insight 11/12 頁）不搬——那是行銷操作工具（web-agency 系統的職務），portfolio 站的行動面收斂為 attribution/products 的決策建議。

---

## 3. 漏斗核心章完整設計（brief 項 2）

### 3.1 漏斗定義與公式（全部進 registry `formula` 欄，可稽核）

**步驟（5 步，對照 `conversion.py:320-326` 的 DEFAULT_ECOMMERCE_FUNNEL，但 step 0 用真 session 數而非 pattern 比對）**：

| step_order | step | 計數來源 |
|---|---|---|
| 0 | 進站（sessions） | `stg_ga4_insight_session_touch`（§4.2；全事件 session 數，非僅漏斗事件——修正地基 known-limit 3 對漏斗分母的影響） |
| 1 | view_item | `stg_ga4_events` / `gold_ga4_sessions.did_view` |
| 2 | add_to_cart | 同上 `did_cart` |
| 3 | begin_checkout | 同上 `did_checkout` |
| 4 | purchase | 同上 `did_purchase` |

**雙計數基準（basis）**：`session`（主視覺；行為單位）與 `user`（輔；distinct user_pseudo_id 觸達）。**「觸達階段」語意非嚴格路徑序**（did_checkout 不必經 did_cart）——與 ga-insight pattern-contains 同語意，caveat 明寫。

**公式（定稿）**：
- `step_conversion_i = reached_i / reached_{i−1}`（`reached_{i−1}=0 → NULL`）
- `drop_off_i = 1 − step_conversion_i`
- `users_lost_i = reached_{i−1} − reached_i`
- `overall_cvr = reached_4 / reached_0`（session basis；user basis 同構）
- **瓶頸雙判準（ga-insight 單一 threshold 的進化）**：`is_bottleneck_i = drop_off_i ≥ θ`（θ=0.40，`pipeline.yaml ga_insight.bottleneck_threshold` 單一真源）；瓶頸間**優先序 = users_lost 降冪**（絕對流失量排修復順位，非只看比率——比率高但量小的階段不該排第一）
- 切片維度：`segment_type ∈ {all, device, source}`×`segment_value`（device 3 值；source 取 top 8 session_source，餘併 `(other)`）

### 3.2 視覺（Recharts 重造；Streamlit/Plotly 零抄）

| 區塊 | 實作 |
|---|---|
| 漏斗主圖 | Recharts `FunnelChart`＋`Funnel`（§0.1 已證），分段色 `var(--chart-1..5)` 走 `fill`（**禁 `Cell`**——已 deprecated）；`LabelList` 帶 step 名＋reached 數；`accessibilityLayer` 開 |
| Sankey 階段流 | Recharts `Sankey`（§0.1 已證）：nodes＝5 階段＋各階段「離開」節點；links＝進階 vs 流失 session 數——ga-insight `get_sankey_data` 是頁面轉移圖（我方無 page_view 明細），**重定義為階段流失流**（漏斗語意更聚焦，且資料誠實） |
| 逐步流失 bars | BarChart（drop_off_i，瓶頸段 `var(--negative)`、非瓶頸 `var(--chart-1)`，θ 參考線 `ReferenceLine`） |
| 日趨勢 | LineChart（funnel_daily：各步 reached 或 overall_cvr 時序）＋異常無關（異常歸 `/ga` KPI 卡） |
| 切片 | 2-col 小漏斗或 grouped bars（device / source top-N） |
| 建議卡 | 規則模板：瓶頸階段→模板文（帶入真 drop_off/users_lost 數字），`AiComputedBadge mode="computed"`＋caption「規則模板建議，非 AI 生成」 |

### 3.3 `/ga/cart`（微觀放棄；`cart_abandonment.py:28-75` 邏輯的誠實裁切）

- `abandonment_rate = (carted_sessions − purchased_after_cart_sessions) / carted_sessions`（session 旗標法照取）。
- shipping/payment 分步流失（`:60-66`）**不做**——地基白名單無 `add_shipping_info`/`add_payment_info`（誠實不硬撐；caveat 寫明「結帳內部步驟不在資料白名單」，列進化方向：地基 additive 擴事件白名單後補）。
- 放棄價值估算：`abandoned_value ≈ Σ price×coalesce(quantity,1)`（cart 事件 quantity 常 null——**估算式明標**進 formula＋caveat「quantity 缺值以 1 計，屬上界估算」）。
- 切片同 §3.1（device/source）。

---

## 4. 歸因頁（brief 項 3）

### 4.1 為何需要新萃取（誠實推理，寫進頁面 Explainer）

地基 `first_touch_source/medium` 是 **user-scoped 首觸**（地基 §4 欄註＋known-limit 6）——每個 user 只有一個恆定值，四種歸因模型會退化成同一答案（假對照）。真多觸點歸因需要 **session 級來源**。GA4 export 的 `event_params` 含 `source`/`medium`/`campaign`（session 起始事件攜帶），公開 sample 可萃——此為 §13 實查 1（帶探測 SQL 與降級路徑）。

### 4.2 additive session touches 萃取（合約邊界內的落法）

**合法性**：地基 §13 known-limit 3 自帶演進條款「需全 session 事實 → 開 additive 新 Silver 表，不改本合約」；crosscut §7.3 四條合約（既有 Airflow／additive／不改地基 4 表與 dmp_*／`ga_insight_` 前綴）逐條滿足。**地基零檔案被修改**（`ga4_daily` DAG、`ingestion/ga4/` 套件、4 marts 全不動）。

- **新 DAG `ga4_insight_touch_daily`**（`orchestration/airflow/dags/ga4_insight_touch_daily.py`）：形狀鏡像地基 §7（`@daily`、`start=2020-11-01`、`end=2021-01-31`、`catchup=True`、`max_active_runs=1`、retries 同款）——**3 task**：`extract_touches → build_silver → load_silver_to_postgres`（不含 per-run dbt——insight marts 是全窗重算，逐日 DQ 對二級 enrichment 表收益低；DQ 由 `ga_insight_batch` 的 dbt test 承擔，取捨誠實記錄）。
- **新套件 `ingestion/ga4_insight/`**（獨立 pyproject，裝進 Airflow image ＝ Dockerfile 加一行 install；依賴 google-cloud-bigquery/boto3/pyiceberg/psycopg2 **全在地基/主線已 pin，零新 Airflow image 依賴**）。萃取 SQL（決定性、對當日分表）：

```sql
SELECT
  PARSE_DATE('%Y%m%d', event_date)                       AS event_date,
  user_pseudo_id,
  (SELECT ep.value.int_value FROM UNNEST(event_params) ep
     WHERE ep.key='ga_session_id' LIMIT 1)               AS ga_session_id,
  MIN(event_timestamp)                                   AS first_event_ts_micros,
  MAX(event_timestamp)                                   AS last_event_ts_micros,
  COUNT(*)                                               AS events_count,
  COUNTIF(event_name='page_view')                        AS pageviews_count,
  LOGICAL_OR(event_name='session_start')                 AS had_session_start,
  ARRAY_AGG((SELECT ep.value.string_value FROM UNNEST(event_params) ep
     WHERE ep.key='source' LIMIT 1) IGNORE NULLS ORDER BY event_timestamp LIMIT 1)[SAFE_OFFSET(0)] AS first_source,
  ARRAY_AGG((SELECT ep.value.string_value FROM UNNEST(event_params) ep
     WHERE ep.key='medium' LIMIT 1) IGNORE NULLS ORDER BY event_timestamp LIMIT 1)[SAFE_OFFSET(0)] AS first_medium,
  ARRAY_AGG((SELECT ep.value.string_value FROM UNNEST(event_params) ep
     WHERE ep.key='campaign' LIMIT 1) IGNORE NULLS ORDER BY event_timestamp LIMIT 1)[SAFE_OFFSET(0)] AS first_campaign,
  MAX(device.category)                                   AS device_category,
  MAX(geo.country)                                       AS geo_country
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
WHERE _TABLE_SUFFIX = '{ds_nodash}'
GROUP BY event_date, user_pseudo_id, ga_session_id
```

（param helper 沿 `ingestion/ga4/src/ga4_ingest/sql.py` 的 `string_param`/`int_param` 逐字同構——import 該套件的純函式即可，不複製；dry-run 位元組護欄＋`maximum_bytes_billed` 兩層沿地基 §3，值走 `pipeline.yaml ga_insight.touch_dry_run_limit_bytes / touch_max_bytes_billed` 獨立鍵。）

- **Silver `silver.ga4_insight_session_touch`**（Iceberg 正本 PARTITIONED BY event_date＋PG serving 同構；穩定性政策同地基 §4 additive-only）。**粒度＝(event_date, user_pseudo_id, ga_session_id) 的「日內 session 分片」**；PK＝三欄——跨午夜 session 產生兩列分片，**session 級聚合放 staging 做**（`stg_ga4_insight_session_touch` view：group by user+session，取 min(first_event_ts) 分片的 source/medium/campaign（row_number 決定性）、Σ events/pageviews、min/max ts、`coalesce(source,'(direct)')`/`coalesce(medium,'(none)')` GA 慣例正規化）。Bronze key：`s3://bronze/ga4_insight_session_touch/date=<YYYY-MM-DD>/touches.json`（信封同地基 §3）。
- 全欄：上述 SQL 欄 ＋ `ingestion_id`（`ga4tch_<YYYYMMDD>`）＋ `ingested_at`。

### 4.3 歸因引擎（Python，`ml/ga_insight/`）

**Journey 重建**（`attribution.py:26-58` 邏輯照取、工程重造為 SQL+pandas over PG）：
- 轉換事件＝`stg_ga4_events` purchase 列聚合成 `(user_pseudo_id, transaction_id, purchase_ts, revenue=Σitem_revenue)`。
- 觸點＝該 user 的 sessions（touches 表），`0 ≤ (purchase_ts − session_start_ts) ≤ lookback_days`（30，pipeline.yaml）；channel＝`session_source / session_medium`；`touch_order` 依 session_start_ts。

**四模型（權重公式定稿，進 registry formula）**：

| 模型 | 權重 | 假設（頁面對照表原文素材） |
|---|---|---|
| first_touch | 首觸 1.0 | 「認識你的那一刻最重要」——高估喚起、無視收割 |
| last_touch | 末觸 1.0 | 「臨門一腳最重要」——GA 預設近似、高估品牌/直接流量 |
| linear | `1/total_touches` | 「每次接觸等值」——無視位置與時近 |
| time_decay | `w=2^(−days_before/7)`，journey 內正規化 Σw=1 | 「越近轉換越重要」——半衰期 7 天是拍板參數非真理（`ga_insight.attribution.half_life_days`） |

**可稽核性（進化點）**：每模型 `Σ attributed_revenue ≡ Σ journey revenue`（浮點容差 1e-6）——引擎內 assert＋dbt 外部 singular 測試＋頁面「守恆驗證」徽章（computed）。無觸點 journey（lookback 內無 session——理論上至少含購買 session 本身，量測後如實標）計入 `(direct)/(none)`。

**輸出 `ml.ga_insight_attribution`**：grain `(model, source_medium)`：`attributed_revenue numeric / attributed_conversions numeric / revenue_share numeric / journeys_count bigint / lookback_days int / half_life_days numeric / computed_at timestamptz / engine_version text`。

**降級路徑（實查 1 失敗時）**：sample 的 source/medium params 缺席或 >80% 遭遮蔽 → 歸因頁保留 route/registry，主區塊替換為「首觸獲客分析」（地基 `first_touch_*` 誠實可做：獲客來源 × 漏斗轉換/營收）＋整頁 Explainer 明講「本資料集無 session 級來源，多觸點歸因不可得」——**誠實降級而非假圖**；touches 表其餘欄（session 數/step 0/裝置切片）不受影響照用。

---

## 5. 客群價值章（brief 項 4；與 `/audience` 切線嚴守 crosscut §4）

### 5.1 `/ga/customers`

- **lifecycle 月階段（`nes_model.py:29-99` 規則進化）**：對三個日曆月（2020-11/12、2021-01）各月月底為錨，對「截至該月有購買史的 user」判：`New`（該月首購）／`Active`（該月有購、非首購）／`Sleeping-1/2/3`（最後購買距今 1／2／≥3 個月）。cycle＝日曆月（≈ nes 的 cycle_days=30，對齊 92 天窗）。輸出：各月階段 user 數＋**月間轉移矩陣**（from_stage→to_stage user 數——NES 只給快照，轉移矩陣是進化點，直接可視「沉睡回流率」）。
- **LTV（觀測窗實測，拒偽預測）**：buyers 依 `gold_ga4_user_rfm.monetary_total` 十分位：各 decile 的 user 數/營收和/營收占比/累積占比/平均 AOV/平均 orders → Pareto 曲線（「前 x% 客人貢獻 y% 營收」）。**明拒 ga-insight `predictive.py:54-56` 的「XGB 擬合捏造目標」**——92 天窗做不出誠實的未來 LTV，觀測窗分佈＋高價值結構是能誠實回答「客人值多少」的最大集合（頁面 Explainer 寫明此取捨）。
- `related`：`/audience`（「這套客群背後的 DMP 圈人基建 → 受眾分群」）；反向 cross-link 由 P7 plan 補 `related`（additive）。**不重繪** R×F heatmap 與 P7 8 分群摘要。

### 5.2 `/ga/churn`（預測；修正 ga-insight 標籤洩漏）

- **時間切分（定稿）**：特徵窗 `2020-11-01 ～ 2021-01-01`（61 天）、標籤窗 `2021-01-02 ～ 2021-01-31`（30 天）——`pipeline.yaml ga_insight.churn.feature_window_end / label_window_days`。母體＝特徵窗內有購買的 user。`label churn=1 ⟺ 標籤窗內 orders=0`。
- **特徵（point-in-time，嚴格只用特徵窗資料——不得讀全窗的 `gold_ga4_user_rfm`，防洩漏）**：recency_obs（相對 2021-01-01）、frequency_obs、monetary_obs、active_days_obs、cart_events_obs、view_events_obs、aov_obs。
- **模型**：scikit-learn `LogisticRegression`（可解釋 baseline+）與 `HistGradientBoostingClassifier` 二擇（PR-AUC 高者），**對照基準＝recency-only 規則**（recency_obs 降冪排序的 PR-AUC）。**門檻閘（ML posture：模型登錄=DB 表+門檻閘）**：`model PR-AUC ≥ baseline × (1+0.05)` 才發佈模型分數；未過閘→發佈 recency 規則分數並在模型卡如實標「規則基準勝出」——**兩種結果都是誠實展示品**。
- **輸出**：`ml.ga_insight_churn_scores`（grain user_pseudo_id：churn_probability、risk_band（≥0.7 高/≥0.4 中/低，沿 `predictive.py:110-114` 分帶、值進 pipeline.yaml）、七特徵快照欄、model_version、scored_at）＋ `ml.ga_insight_model_registry`（model_name/model_version/algo/trained_at/train_window_start/end/label_window_start/end/metrics_json{pr_auc,roc_auc,brier,baseline_pr_auc,positive_rate}/passed_gate bool/is_current bool）。
- **頁面＝模型卡版面**：版本/訓練窗/標籤窗/指標 vs baseline/閘結果置頂（**模型版本標註＋訓練窗揭露＝brief 硬性面**）→ decile lift（依預測分十分位的實際流失率）→ 風險分帶計數＋各帶特徵中位數。caveat 定稿：「靜態歷史資料集的一次性訓練示範；`user_pseudo_id` 為裝置級匿名（地基 known-limit 4），流失＝裝置不再回訪的近似」。

---

## 6. 生意全貌章與來源/商品章（brief 項 5 的落地面）

### 6.1 `/ga`（第一章）

- **KPI tiles**（觀測窗總覽＋錨定 `data_anchor_date` 的「最近 30 天」）：revenue/orders/buyers/sessions/overall_cvr/aov。
- **日趨勢＋異常標記**（`anomaly_detector.py:46-65` 進 SQL）：`gold_ga4_insight_kpi_daily` 對 revenue/orders/cvr 各配 `rolling_mean_7d / rolling_std_7d / z_score / is_anomaly(|z|>2) / upper_bound / lower_bound`（SQL window functions；IsolationForest 版**不取**——z-score 已足且 SQL 可稽核，`:67-111` 的 ML 異常列進化方向）。LineChart＋異常點 accent 標記＋參考帶。
- **月對月瀑布**（`comparative.py:103-121` 連環替代法照取，formula 定稿）：`Δrevenue = dS×CR₀×AOV₀ + S₁×dCR×AOV₀ + S₁×CR₁×dAOV + unexplained`；rows＝(2020-12 vs 2020-11)、(2021-01 vs 2020-12) 兩列（靜態窗的誠實對比集合；YoY 無資料不做）。BarChart 瀑布（透明基座 stack 技法，零新依賴）。
- 章節導覽卡：四章入口卡（lucide icon＋該章 questionTitle）——支柱首頁兼任敘事地圖。

### 6.2 `/ga/products`（第四章）

- **Pareto**：`gold_ga4_insight_product_pareto`（ref `gold_ga4_item_catalog`）：revenue_rank、revenue_share、cum_revenue_share、`in_top80 bool`；雙軸 ComposedChart（Bar 營收＋Line 累積%）。
- **商品漏斗散點**：item_catalog 的 `view_to_purchase_user_rate × revenue_total`（氣泡=users_viewed）——「高流量低轉換」象限即行動清單。
- **搭售規則**（`market_basket.py`/`product.py:85-156` 邏輯，取 product.py 的零依賴 pair-count 版重寫——**不引 mlxtend**，Merch Store 品項數百、手寫 Counter+combinations 足）：basket＝`(user_pseudo_id, transaction_id)` 的 purchase item 集合；`support=P(A,B)`、`confidence=P(B|A)`、`lift=confidence/P(B)`；閾值 `min_support=0.01 / min_confidence=0.3 / top_n=100 by lift`（pipeline.yaml）。**毛利假設硬編 40%（`market_basket.py:33`）不取**——sample 無成本資料，不編造利潤欄。輸出 `ml.ga_insight_basket_rules`（antecedent_item_id/name、consequent_item_id/name、co_count、support、confidence、lift）。
- `related`：`/reco`（「想看這些共購訊號如何變成線上推薦服務 → 推薦系統」）。

---

## 7. v1 取捨全表（brief 項 5；判準＝Gold＋touches 能否真支撐）

| ga-insight 模組 | 判定 | 落點／理由 |
|---|---|---|
| conversion.py | ✅ 完整進化 | `/ga/funnel`（§3） |
| cart_abandonment.py | ✅ 裁切進化 | `/ga/cart`；shipping/payment 分步不做（事件白名單外，誠實標） |
| attribution.py | ✅ 完整進化 | `/ga/attribution`（§4；需 touches 新萃取，降級路徑備妥） |
| rfm.py | ⚖️ 分流 | R/F/M 原料＝地基 `gold_ga4_user_rfm`（已建）；heatmap/8 分群正本歸 `/audience`（P7）；GA 側只做 LTV 分佈衍生（§5.1）——**qcut 分數與 KMeans 不重做** |
| predictive.py | ✅ 修正式進化 | `/ga/churn`（§5.2；修標籤洩漏＋拒捏造目標 LTV） |
| nes_model.py | ✅ 進化 | `/ga/customers` lifecycle＋轉移矩陣（§5.1） |
| anomaly_detector.py | ✅ 裁切進化 | `/ga` z-score 進 SQL；IsolationForest 列進化方向 |
| comparative.py | ✅ 完整進化 | `/ga` 瀑布拆解（§6.1）；YoY 不做（窗不夠） |
| product.py | ✅ 進化 | `/ga/products` Pareto＋pair-count 搭售 |
| market_basket.py | ✅ 併入 | 同上（mlxtend 不引、毛利假設不取） |
| traffic.py | ⚖️ 折半 | channel×漏斗/營收面併入 `/ga/attribution` 切片與 journey 統計；`last_non_direct` 歸因模式列進化方向（v1 四模型已足對照敘事） |
| recommender.py | ❌ | 推薦正本＝P6 `/reco`（cross-link，不重繪） |
| semantic_search.py | ❌ | embedding 歸 P6 召回 spec（地基 known-limit 7） |
| sequence_nlp.py | ❌ | 4 事件白名單下序列語料過薄，不硬撐 |
| ab_testing.py | ❌ | sample 無實驗資料；純計算器無資料支撐（列進化方向：真實驗資料出現時再議） |
| feedback_store.py | ❌ | runtime 回饋寫入＝違純靜態拓撲 |
| emoji 章節 icon | ❌ | lucide only（Signal 驗收 #9） |

---

## 8. GA 分析引擎與資料流（brief 項 6；crosscut §7.3 合約邊界內細設）

### 8.1 全鏈形狀

```
BQ 公開 sample ──(既有 ga4_daily，地基，不動)──▶ silver.ga4_events ─▶ 地基 Gold 4 表（唯讀）
BQ 公開 sample ──(新 ga4_insight_touch_daily：92 run 有界回放)──▶ silver.ga4_insight_session_touch
        ▼ ga_insight_batch（schedule=None，手動/make；靜態資料集的誠實形狀——資料不再變，排程是謊言）
   ①dbt run --selector ga4_insight_only（KPO 既有 dbt image）→ gold.gold_ga4_insight_* 9 marts
   ②引擎三 task 平行（KPO 自有 image）：attribution / churn / basket → ml.ga_insight_* 4 表
   ③dbt test --selector ga4_insight_only（DQ gate）
        ▼ 既有 export_frontend_data DAG（datasets.py additive +12 條目）
   ga_insight_*.json ×12（P4 §3 信封同構）→ frontend/public/data/ → (ga)/ 頁 build-time fs 讀
   （absent 容忍沿 P4：任一檔 status:"absent" → 該頁對應卡顯示「此資料尚未由平台產出」）
```

### 8.2 新增檔案佈局（全 additive；未列＝不動）

```
ingestion/ga4_insight/                 # touches 萃取套件（裝進 Airflow image；零新 Airflow 依賴）
    pyproject.toml
    src/ga4_insight_ingest/{sql.py, bronze.py, silver.py, loader.py}   # bq.py 直接 import ga4_ingest.bq（複用護欄）
    tests/
ml/ga_insight/                         # 分析引擎（自有 image，KPO 執行；零 ArgoCD app——批次無常駐）
    Dockerfile                         # python:3.12-slim + 引擎套件
    pyproject.toml                     # 新 pin：scikit-learn（版本 plan 期 uv compile 定，穩定套件）、pandas、psycopg2
    src/ga_insight_engine/{attribution.py, churn.py, basket.py, model_registry.py, db.py}
    tests/
orchestration/airflow/dags/{ga4_insight_touch_daily.py, ga_insight_batch.py}
orchestration/airflow/dags/config/pipeline.yaml    # += ga_insight: 區塊（§8.5）
orchestration/exporter/src/exporter/datasets.py    # += 12 條目（EP-D append）
lakehouse/dbt/models/staging/stg_ga4_insight_session_touch.sql（+_sources.yml additive 增列）
lakehouse/dbt/models/marts/ga4_insight/{_ga4_insight_schema.yml, 9 張 mart .sql}
lakehouse/dbt/selectors.yml            # default 排除 += tag:ga4_insight；新增 selector ga4_insight_only（EP-D 冪等寫法）
lakehouse/dbt/tests/assert_ga4_insight_*.sql
mcp-server/server.py                   # += 5 工具（EP-D append）
.github/workflows/ga-insight-ci.yaml   # 新：paths ml/ga_insight/** → ruff+pytest+image build（沿 hello-ci/mcp-ci 模式）
                                       # airflow-ci paths 天然涵蓋 ingestion/**（零改）；dbt-ci 涵蓋 dbt 改動（零改）
Makefile                               # += ga-insight-run / ga-insight-verify
scripts/verify-ga-insight.sh
frontend/src/app/(ga)/…（§2.1）＋ frontend/src/content/registry/ga.ts（§9）＋ components/AskAiTeaser.tsx（§10）
```

**零新排程器、零新 DB、零新 ArgoCD Application、零新 Secret**（touches 用地基 `gcp-sa-ga4`＋同 env 掛載——volume 對所有 task pod 已掛，地基 §8）；**唯一新 image**＝引擎（批次 KPO，不常駐）。

### 8.3 dbt marts 合約（`gold` schema、table mat、tag `ga4_insight`、穩定性政策同地基 §4 additive-only；description 即 registry `dataSource`/Explainer 素材）

| # | mart | grain | 欄位（名/型別要點） |
|---|---|---|---|
| 1 | `gold_ga4_insight_funnel` | (basis, segment_type, segment_value, step_order) | basis text{user,session} / segment_type text{all,device,source} / segment_value text / step_order int(0–4) / step_name text / reached_count bigint / prev_count bigint / step_conversion_rate numeric / drop_off_rate numeric / users_lost bigint / overall_share numeric / is_bottleneck bool / bottleneck_rank int(null 非瓶頸) |
| 2 | `gold_ga4_insight_funnel_daily` | (event_date, step_order) | session basis、all segment：reached_count / step_conversion_rate / drop_off_rate / overall_cvr（step4 列） |
| 3 | `gold_ga4_insight_kpi_daily` | event_date | sessions_count / users_count / buyers_count / orders_count / revenue numeric / aov / cvr ＋ 對 revenue、orders、cvr 各五欄：rolling_mean_7d / rolling_std_7d / z_score / is_anomaly / upper_bound / lower_bound |
| 4 | `gold_ga4_insight_period_compare` | (current_period text) | compare_period text / sessions_0,1 / cvr_0,1 / aov_0,1 / revenue_0,1 / revenue_diff / effect_traffic / effect_conversion / effect_aov / unexplained（連環替代法，§6.1 公式） |
| 5 | `gold_ga4_insight_cart_abandonment` | (segment_type, segment_value) | carted_sessions / purchased_after_cart_sessions / abandoned_sessions / abandonment_rate / checkout_reached_sessions / abandoned_value_estimate numeric（估算式 caveat） |
| 6 | `gold_ga4_insight_lifecycle` | (month_key, stage) | month_key text(YYYY-MM) / stage text{New,Active,Sleeping-1,Sleeping-2,Sleeping-3} / users_count bigint |
| 7 | `gold_ga4_insight_lifecycle_transitions` | (from_month, from_stage, to_stage) | users_count bigint（to_month=from_month+1 隱含） |
| 8 | `gold_ga4_insight_ltv` | decile int(1–10) | users_count / monetary_sum / monetary_share / cum_share / avg_aov / avg_orders |
| 9 | `gold_ga4_insight_product_pareto` | item_id | item_name / item_category / revenue_total / revenue_rank / revenue_share / cum_revenue_share / in_top80 bool / users_viewed / view_to_purchase_user_rate（後二 ref 自 item_catalog） |

ref 白名單（§1 贯穿裁定）：`stg_ga4_events`、`stg_ga4_insight_session_touch`、`gold_ga4_user_rfm`、`gold_ga4_sessions`、`gold_ga4_item_catalog`、`gold_ga4_user_item_interactions`。**generic tests**：各 mart 粒度鍵 unique+not_null、rate 欄 0–1 accepted range（singular）。**singular tests（`assert_ga4_insight_*.sql`）**：漏斗單調（`reached_count ≤ prev_count`）、瀑布守恆（`|effect 三項和＋unexplained − revenue_diff| < 0.01`）、lifecycle 轉移守恆（from_stage 列和 = 前月 stage 數，容忍新進者差集規則明寫）、kpi 窗邊界（event_date ∈ 觀測窗，同地基慣例）。

### 8.4 ml 表（引擎持有 DDL，`CREATE TABLE IF NOT EXISTS`，沿 P1 loader 慣例）

§4.3 `ga_insight_attribution`、§5.2 `ga_insight_churn_scores`＋`ga_insight_model_registry`、§6.2 `ga_insight_basket_rules`——四表欄位已在各節定稿。引擎每 run 全量重算＋TRUNCATE-insert（靜態資料冪等最簡形）；registry 表 append-only＋`is_current` 翻旗。

### 8.5 `pipeline.yaml ga_insight:` 區塊（常數單一真源）

```yaml
ga_insight:
  touch_dry_run_limit_bytes: <地基同級值>   # 兩層成本護欄（沿地基 §3）
  touch_max_bytes_billed: <同上>
  bottleneck_threshold: 0.40
  attribution: { lookback_days: 30, half_life_days: 7 }
  churn:
    feature_window_end: "2021-01-01"
    label_window_days: 30
    risk_bands: { high: 0.7, mid: 0.4 }
    gate_min_rel_improvement: 0.05
  basket: { min_support: 0.01, min_confidence: 0.3, top_n: 100 }
  source_slice_top_n: 8
```

### 8.6 datasets（exporter `datasets.py` additive +12；檔名前綴 `ga_insight_`；P4 §3 信封同構、rows=表列平鋪；absent 容忍沿 P4）

| 檔 | 來源表 | 備註 |
|---|---|---|
| ga_insight_kpi_daily.json / ga_insight_period_compare.json / ga_insight_funnel.json / ga_insight_funnel_daily.json / ga_insight_cart.json / ga_insight_lifecycle.json / ga_insight_lifecycle_transitions.json / ga_insight_ltv.json / ga_insight_products.json | 各對應 §8.3 marts 1:1 | 全欄平鋪、全表（各 ≤ 千列級，遠低於 3MB cap） |
| ga_insight_attribution.json | ml.ga_insight_attribution | 全欄平鋪（含 lookback/half_life 參數欄——自帶可稽核性） |
| ga_insight_basket_rules.json | ml.ga_insight_basket_rules | top 100 |
| ga_insight_churn.json | ml.ga_insight_model_registry(is_current)＋churn_scores 聚合 | **rows 用 `section` 欄離散**：`model_card`（1 列）/`risk_bands`（3 列）/`deciles`（10 列：預測分十分位×實際流失率）——**不匯出 per-user 分數列**（無展示必要，公開檔保持聚合層） |

`ga_ask_showcase.json` 信封與 rows 骨架屬 crosscut §6.4（問 AI spec 只准 additive 擴），本 spec 零涉入。1:1 mart↔檔（唯 churn 例外，文件化）＝absent 粒度最細（churn 未跑時漏斗照常 ok）。

### 8.7 MCP 工具（additive +5，EP-D）

`get_ga_overview`（kpi_daily+period_compare）/ `get_ga_funnel`（funnel+cart，參數 `segment: str='all'`）/ `get_ga_customers`（lifecycle+ltv+churn 聚合）/ `get_ga_attribution`（參數 `model: str='time_decay'`，runtime 驗證合法值）/ `get_ga_products`（pareto+basket）。docstring 誠實紀律沿 P4 §7（「平台離線批次預產」）；absent → 明確訊息。

### 8.8 監控

postgres-exporter ConfigMap additive +2 條（沿地基 §9 模式）：`ga_insight_mart_rows{mart}`（9 marts＋4 ml 表 UNION ALL count）、`ga_insight_model_gate_passed`（registry is_current 列的 passed_gate::int）。零新 PrometheusRule/Grafana（地基同判：靜態資料集 freshness 告警是範疇錯誤）。

---

## 9. registry 條目結構與覆蓋清單（brief 項 7；schema＝crosscut §5.2 原樣零改）

- **落點**：`frontend/src/content/registry/ga.ts`（per-pillar 檔，crosscut §5.2 存放約定）。8 條 `PageEntry`（pageId：`ga`/`ga-funnel`/`ga-cart`/`ga-customers`/`ga-churn`/`ga-attribution`/`ga-products`/`ga-ask`）。
- **本 spec 定稿的欄**：`pillar:'ga'`、`route`、`chapter`（＝§2.1 navGroup label）、`questionTitle`（§2.2 表，「？」結尾）、`formula`（下表）、`dataSource`（§8.6 對應）、`related`（§5.1/§6.2）、`aiVsComputed`（全 `computed`；`ga-ask` 與各頁 ask-teaser block 為 `ai-narrative`）。**plan 撰寫的欄**：`whyBuilt`/`whatItDoes`/`howToRead`/`canDo`/`problem`/`caveats` 全文與 blocks 的 howToRead（crosscut §5.2「條目歸 plan 填」；缺任一硬性欄＝gate 紅，coverage gate 六斷言自動涵蓋 `(ga)/`——本支柱零新 gate 機制）。
- **blocks 覆蓋清單（34 個；plan 不得少於此清單，多做合法）**：

| pageId | blocks（kebab id；★＝必帶 formula） |
|---|---|
| `ga` | kpi-tiles、revenue-trend-anomaly★（z-score 式）、waterfall-compare★（連環替代法式）、chapter-map |
| `ga-funnel` | funnel-stages★（step_conversion/overall_cvr）、drop-off-bars★（drop_off 式＋θ）、bottleneck-cards★（雙判準＋users_lost 優先序）、stage-sankey、device-slice、source-slice、playbook（computed 規則模板） |
| `ga-cart` | abandonment-kpi★（放棄率式）、segment-compare、abandoned-value★（估算式＋caveat） |
| `ga-customers` | lifecycle-area、transition-heatmap、ltv-deciles★（decile/cum_share 定義）、pareto-curve |
| `ga-churn` | model-card（版本/訓練窗/指標/閘——`aiVsComputedNote` 不適用，computed）、decile-lift、risk-bands★（分帶閾值）、feature-summary |
| `ga-attribution` | model-assumptions、channel-model-bars★（四模型權重式）、rank-shift-table、conservation-badge★（守恆式） |
| `ga-products` | pareto-dual★（cum_revenue_share 定義）、item-funnel-scatter、basket-rules★（support/confidence/lift 式） |
| `ga-ask` | （blocks 由問 AI spec 定；registry 條目本體仍受 gate 管——問 AI plan 落頁時填） |
| 各頁共通 | `ask-teaser`（§10；`aiVsComputed:'ai-narrative'`＋`aiVsComputedNote` 帶 provider/批次語意） |

- formula 欄字串（Fira Code 呈現）逐條取自 §3.1/§4.3/§5.2/§6 定稿式，如 `drop_off% = 1 − reached_n/reached_{n−1}；瓶頸 = drop_off ≥ 0.40，優先序 = users_lost 降冪`。

---

## 10. 每頁問 AI 摺疊區（brief 項 8；只留接縫，graph 細設歸問 AI spec）

- **元件**：`frontend/src/components/AskAiTeaser.tsx`——`{ pageId: string }`；**位置＝每頁最後一個內容元素（FreshnessBanner 之上）**，全 8 頁一致（說明式 UI 的位置一致性原則，Signal §6 佈局慣例同精神）。
- **資料契約（唯讀消費，不定義產線）**：build-time `loadDataset('ga_ask_showcase')` → 取 `rows.filter(r => r.scope === 'page:' + pageId)` 前 2–3 則；rows 骨架＝crosscut §6.4 保留欄（question/answer/agents_called/confidence/provider/generated_at…），本 spec 只讀不擴。
- **渲染**：shadcn `Collapsible` 卡（`defaultOpen=false`）：標題「問 AI・本頁範圍」（lucide `MessageCircleQuestion`）→ 每則 Q&A：問句/答摘要＋`AiComputedBadge mode="ai-narrative"`＋「離線批次產生 · {provider} · {generated_at}」→ 卡尾固定連結「完整多 agent 問答 → /ga/ask」。
- **三態（定稿）**：①正常＝如上；②`ga_ask_showcase.json` `status:"absent"`＝卡體顯示 P4 absent 標準文案「此資料尚未由平台產出」（接縫可見、誠實，不藏）；③檔 ok 但本頁 scope 零列＝縮減態（只渲染標題＋「完整多 agent 問答 → /ga/ask」連結，不留空殼 Q&A）。
- registry block `ask-teaser` 的 `aiVsComputedNote` 由問 AI plan 依實際 provider/批次填。

---

## 11. 取材界線表（進化非複刻，逐模組「取什麼邏輯 / 重造什麼工程 / 明拒什麼」）

| 素材（file:line 見 §0.2） | 取的邏輯 | 重造／進化 | 明拒 |
|---|---|---|---|
| conversion.py | 逐步計數/流失率/瓶頸 threshold/users_lost/Sankey 資料形狀 | pandas-runtime → dbt SQL 批次；單判準 → 雙判準＋users_lost 優先序；頁面轉移 Sankey → 階段流失 Sankey；Plotly → Recharts；公式進 registry 可稽核 | canned emoji 建議文（改規則模板＋computed 標） |
| attribution.py | journey 30d lookback/touch_order/四模型權重（time_decay 2^(−d/7) 正規化） | 資料層：user 首觸 → 真 session 觸點（additive 萃取）；＋守恆驗證；假設對照表升一級內容 | — |
| rfm.py | R/F/M 概念（原料已在地基） | reference_date=now() → data_anchor_date（地基已修）；分佈分析取代重繪分群 | qcut 分數/8 分群/KMeans 重做（`/audience` 正本）；emoji 等級標籤與權益文案 |
| predictive.py | churn 風險分帶 0.7/0.4 | **標籤洩漏 → 時間切分**；黑箱 → 模型卡＋登錄表＋門檻閘＋baseline 對照 | **捏造目標的「預測 LTV」整段不取**（反面教材，Explainer 點名此取捨） |
| cart_abandonment.py | session 旗標放棄率 | pandas → SQL；＋放棄價值估算（估算式明標） | shipping/payment 分步（資料白名單外） |
| market_basket.py / product.py | support/confidence/lift；product.py 零依賴 pair-count 實作形 | Python 批次落 DB 表→靜態匯出 | mlxtend 依賴；毛利 40% 硬編假設 |
| nes_model.py | New/E0/S1-S3 規則與 cycle 概念 | 快照 → 月轉移矩陣；錨定 data_anchor_date | — |
| anomaly_detector.py | rolling z-score（7d, |z|>2, bounds） | pandas → SQL window functions | IsolationForest（列進化方向） |
| comparative.py | 期間指標＋連環替代法瀑布拆解 | runtime 任意期間 → 靜態窗固定月對（誠實集合） | YoY（窗不夠不假裝） |
| traffic.py | channel×轉換視角 | 併入歸因頁切片/journey 統計 | last_non_direct 完整實作（列進化方向） |
| ui_utils.py render_page_header | 五欄自我說明模式 | crosscut §5 registry（已定，本檔只填 ga.ts） | inline 散落 |
| 五章弧/問句標題 | 問題導向敘事原則 | 自設五章（§2.2），漏斗前移為核心 | 章名照抄、每頁同模板 |

---

## 12. 驗收清單（每條可實跑；隨本支柱 plan 生效，與 crosscut §11 累加）

| # | 檢查 | 方法 | 預期 |
|---|---|---|---|
| 1 | touches 單日全鏈 | unpause `ga4_insight_touch_daily` → 首 dagrun（2020-11-01） | success；`silver.ga4_insight_session_touch` 當日 count>0；Bronze 信封 `bq_job.total_bytes_billed ≤ touch_max_bytes_billed` |
| 2 | 冪等 | clear 該 dagrun rerun | Bronze 物件數/silver 列數不膨脹 |
| 3 | batch 全鏈 | 回放收斂後 `make ga-insight-run` | DAG 綠；9 marts＋4 ml 表 count>0；dbt test（ga4_insight_only）全綠 |
| 4 | 漏斗單調＋瓶頸 | SQL：任一 (basis,segment) 內 `reached_count` 隨 step_order 非遞增；`is_bottleneck ⟺ drop_off ≥ 0.40` | 零違反 |
| 5 | 歸因守恆 | SQL：每 model `Σattributed_revenue` vs journeys 總 revenue | 差 <1e-6×總額 |
| 6 | 瀑布守恆 | singular test（§8.3） | 綠 |
| 7 | 模型閘 | registry 表 is_current 列存在、metrics_json 含 baseline 對照、passed_gate 與指標一致 | 一致（過閘或 baseline 勝出皆合法態） |
| 8 | 匯出 | 觸發 `export_frontend_data` | latest/ 含 12 個 `ga_insight_*.json`、信封合規、單檔 ≤3MB |
| 9 | 前端 build＋gate | `npm run gate:explainers && npm run build` | gate 綠（8 頁條目/硬性欄/PageHeader 接線/blocks 覆蓋 §9 清單）；`out/ga/` 8 路徑存在、無括號路徑 |
| 10 | absent 容忍 | 暫移 `ga_insight_churn.json` 重 build | build 綠、`/ga/churn` 顯示「此資料尚未由平台產出」 |
| 11 | 邊界鐵律 | 目視＋grep：GA 頁無 R×F heatmap/P7 分群摘要/`/reco` 相似商品卡重繪；`related` 互指在；`grep -r 'dmp_' lakehouse/dbt/models/marts/ga4_insight/` 零命中 | 符合 crosscut §4＋§1 裁定 |
| 12 | 誠實標示 | `/ga/churn` 模型卡含訓練窗；`/ga/attribution` 假設表＋守恆徽章；`ask-teaser` 三態各驗一次（正常/absent/零列）；playbook 卡標 computed | 逐項目視 |
| 13 | 地基零改 | `git diff` 範圍斷言：`ingestion/ga4/`、`dags/ga4_daily.py`、地基 4 marts .sql 零 diff | 零 diff |
| 14 | 主線無損 | `yt_trending_hourly` 最近 dagrun success；主線 dbt log 無 tag:ga4_insight 資產 | selector 隔離生效 |

---

## 13. plan 期待查證點（皆帶預設傾向與降級；非阻擋本 design 收斂）

1. **sample `event_params` 的 `source`/`medium`/`campaign` 覆蓋率**（本 spec 最大實查點）——探測 SQL：對單日分表 `SELECT COUNTIF(k.key='source') … FROM UNNEST(event_params)` 聚合非空占比。預設傾向：存在且 session 起始事件高覆蓋（GA4 export 標準 params）。降級判準：session 級 source 非空占比 <20% → 走 §4.3 降級路徑（首觸獲客分析＋誠實 Explainer），touches 其餘欄不受影響。
2. **touches 單日掃描位元組**——dry-run 量測（全事件、少欄），預設 ≪ 地基護欄同級；超出只調 pipeline.yaml 兩鍵，機制不變。
3. **Recharts `Sankey` 對「階段＋離開」小圖的 label/tooltip 呈現**——機制已證（§0.1），plan 首次落圖目視校準；不理想降級＝自製階段流 bars（CSS，零依賴），資料合約不變。
4. **scikit-learn 確切 pin**——plan 期 `uv pip compile` 定 lock（穩定套件，非快速演進，不需 context7）；與 python:3.12-slim 相容預設成立。
5. **churn 母體規模**——特徵窗 buyers 數（預估數千）；若 <500 → 模型卡如實標「小樣本示範」＋只發佈 LogisticRegression（防過擬），閘機制不變。
6. **journey「零觸點」率**——理論上每筆購買至少有其所在 session；量測後如實寫進 attribution 頁 caveat 數字位。
7. **`(ga)` route group build 斷言**——沿 crosscut §12.1（已備降級），本支柱 plan 跑驗收 #9 時一併覆蓋。
8. **lifecycle 轉移守恆的差集規則**——新進 buyers（前月無購買史）不在 from 集合；singular test 的容忍寫法 plan 期以真資料校準（預設：斷言「from 列和＋新進數 = 當月 stage 總和」）。

---

## 14. 本 spec 拍板 vs 下放對照表

| 主題 | 本 spec 拍板 | 下放問 AI spec | 下放 plan |
|---|---|---|---|
| 章節弧/頁清單/navGroups/版面型別 | ✅ §2 全部 | — | 頁面元件細節與間距落地 |
| 漏斗公式/θ/視覺/切片 | ✅ §3 | — | Recharts 具體 props 校準（實查 3） |
| 歸因：touches 萃取/journey/四模型/守恆/降級 | ✅ §4 | — | source 覆蓋率實查（實查 1）與 caveat 數字 |
| lifecycle/LTV/churn（時間切分/門檻閘/模型卡） | ✅ §5 | — | sklearn pin、樣本規模校準（實查 4/5） |
| v1 模組取捨 | ✅ §7 全表 | — | — |
| marts/ml 表欄位級合約、DAG 形狀、pipeline.yaml、CI/監控 | ✅ §8 | — | image tag/lockfile、dbt SQL 本體 |
| datasets 12 檔＋MCP 5 工具 | ✅ §8.6/§8.7 | `ga_ask_showcase.json` 產線與 rows 擴充（crosscut §6.4 骨架內 additive） | exporter 條目 SQL |
| registry：questionTitle/formula/related/aiVsComputed＋blocks 覆蓋清單 | ✅ §9 | `ga-ask` 頁 blocks | `whyBuilt`/`whatItDoes`/`howToRead`/`caveats` 全文撰寫 |
| 每頁問 AI 接縫（位置/契約/三態） | ✅ §10 | graph/sub-agent/guardrail/trace/`/ga/ask` 頁 IA/live-demo 部署 | `aiVsComputedNote` 實值 |
| ga-insight 退役程序 | —（crosscut §8.1 已定，不重述） | — | — |

---

## 15. 精確度契約 8 條自檢

1. **開放問題收斂**：brief 8 項全數單一決定（§1 總表＋各節），零 TBD/兩案並陳；§13 八點皆「plan 前實查」性質且帶預設傾向＋降級判準（含最大風險點 source params 的量化降級門檻）。
2. **版本＋context7 查證**：唯二新承重宣稱（Recharts FunnelChart/Sankey、Cell deprecation）當日 context7 查證（§0.1）；前端零新依賴；平台端唯一新 pin（scikit-learn）標明「穩定套件、plan 期 lockfile 定」；其餘全沿 crosscut/Signal/地基已證 pin。
3. **資料契約欄位級**：Silver touches（§4.2 全欄＋PK＋分區＋跨午夜分片語意）、9 marts（§8.3 grain＋欄型別）、4 ml 表（§4.3/§5.2/§6.2）、12 datasets（§8.6）、registry 8 頁×34 blocks（§9）——皆標穩定政策。
4. **部署形狀具體**：檔案佈局（§8.2）、兩 DAG 形狀與 task 鏈（§4.2/§8.1）、pipeline.yaml 全鍵（§8.5）、CI workflow、exporter/MCP/監控 additive 落點、萃取 SQL 全文。
5. **沿用慣例不重造**：Bronze 決定性 key/兩層成本護欄/SA Secret（地基 §3/§8）、Silver 雙寫 loader（P1 §5）、tag+selector 隔離（地基 §6/EP-D 冪等寫法）、P4 信封/absent/check-data、crosscut registry/gate/PageHeader/AiComputedBadge、Signal token/元件（Heatmap 參數化重用）。
6. **進化非複刻**：§11 逐模組三欄（取/重造/明拒），含兩個點名反面教材（predictive 標籤洩漏＋捏造目標）與其修正設計。
7. **硬約束貫徹**：拓撲（`(ga)/` 純靜態、build-time 讀 committed JSON、零 live 運算——`/ga` 系 v1 無 live-demo 外連，crosscut §7.2 gated 判定＝策展 JSON 足）、只 additive（驗收 #13 git-diff 斷言地基零改；EP-D append 全列）、前綴紀律（`ga_insight_`/`gold_ga4_insight_`/tag `ga4_insight`）、registry 阻擋級（沿 crosscut gate，零豁免）、AI-vs-程式逐區塊（§9；v1 分析頁全 computed 的誠實分工）、emoji→lucide、公開 sample 非 area02、GA vs `/audience`/`/reco` 正本圖唯一（驗收 #11 grep+目視）、非互動不提問（全檔零待問）。
8. **每步可測**：§12 十四條全給命令/SQL/目視程序，含三個數學守恆斷言（漏斗單調/歸因守恆/瀑布守恆）與 absent/gate 反例實跑。

---

## 16. 給 Opus 的把關提示（覆核建議點）

1. **touches additive 萃取的合約解讀**（本檔最大裁定，§4.2）：crosscut §7.3「只 additive 加 marts/dataset/MCP 工具」未明文列「新 Silver 表＋新萃取 DAG」；本檔依地基 §13.3 自帶演進條款（「需全 session 事實→additive 新 Silver 表」）＋「不改地基任何檔案」判定合法，且它是 brief 硬性面「多模型歸因」的唯一誠實資料基礎（否則四模型退化同答案）。若 Opus 判定越界 → 降級路徑已在 §4.3 備妥（首觸獲客分析），漏斗 step 0 退回 `gold_ga4_sessions`（漏斗活躍 session），其餘設計不受影響。
2. **v1 不讀 `dmp_*`**（§1 贯穿裁定）與 crosscut §7.3 圖示（dmp 列為引擎輸入之一）字面有別——本檔以建置序解耦（P7 可平行）＋EP-I 鬆耦合精神裁定不讀；如需翻正只影響 §8.3 ref 白名單一行。
3. **`ga_insight_batch` schedule=None**：與地基 catchup=True 的「誠實排程」論證同源（靜態資料不再變，daily 重算是儀式）；但它使「資料更新」依賴手動觸發——與 P4「平台按需跑」節奏一致，確認 Fergus 對此操作形狀無異議。
4. **churn 門檻閘的雙合法態**（模型過閘 or baseline 勝出都發佈，§5.2）：這把「模型可能輸給規則」作為展示品——確認此敘事姿態符合 portfolio 定位（我方判斷：是，且比假裝模型必勝更有面試價值）。
5. **12 datasets 的檔數**：P4 現有 11＋新支柱 12（＋搜尋/問 AI 後續）——`public/data/` 總量守門（P4 ≤25MB）餘裕仍大（本批全部千列級），但 `check-data.mjs` 的檔數清單維護成本開始線性成長，plan 期可考慮把清單改由 datasets.py 派生（非本 spec 範圍，僅提示）。

---

## 17. Opus 把關（2026-07-10；規劃者覆核，PASS）

**結論：PASS，可進 plan 佇列（spec-only，plan 延後）。** 精確度契約 8 條逐條符合；資料契約做到欄位級（9 marts＋4 ml 表＋12 datasets＋Silver touches PK/分區/跨午夜分片）、部署形狀具體（兩 DAG task 鏈、萃取 SQL 全文、pipeline.yaml 全鍵、CI/監控 additive 落點）、驗收含三個數學守恆斷言（漏斗單調／歸因守恆／瀑布守恆）＋git-diff 地基零改斷言。

**承重宣稱獨立覆核（context7 `/recharts/recharts` 2026-07-10，我方獨立重查非採 agent 自報）→ CONFIRMED**：Recharts 3 原生 `FunnelChart`/`Funnel`（官方範例用法與 §3.2 一致）與 `Sankey`（a11y 支援清單明列）皆存在，漏斗核心章零新前端依賴成立。`Cell` 目前仍可用但 agent 前瞻禁用改 `fill`（避開 4.0 移除）屬保守正確，不影響收斂。route groups × `output:'export'` 沿 crosscut §0 已做的三腿覆核，不重查。

**五風險點裁定：**
1. **touches additive 萃取合法性（§4.2，本檔最大裁定）→ 核准合法。** 地基 §13.3 自帶演進條款明文「需全 session 事實→開 additive 新 Silver 表、不改本合約」；crosscut §7.3 四條合約逐條滿足；驗收 #13 以 git-diff 斷言證明地基 4 表/DAG/套件零改。且這是「多模型歸因」的唯一誠實資料基礎——否則四模型退化成同一答案（假對照）。降級路徑（§4.3 首觸獲客分析＋誠實 Explainer）完整備妥，無鎖死。
2. **v1 不讀 `dmp_*`（§1 贯穿裁定）→ 核准。** crosscut §7.3 只列 dmp 為「可及輸入」非「必讀」；以建置序解耦讓 P7 可平行、EP-I 鬆耦合精神為正解，GA↔DMP 走 `related` cross-link。翻正成本＝ref 白名單一行。
3. **`ga_insight_batch` schedule=None 手動觸發（§16.3）→ 核准，列知會 Fergus。** 與地基「靜態資料集不再變、daily 排程是儀式」論證同源，與 P4「按需跑」節奏一致。非阻擋。
4. **churn 門檻閘雙合法態（模型過閘 or baseline 勝出都發佈，§5.2）→ 核准，且這是正確的 portfolio 姿態。** 把「模型可能輸給規則、誠實揭露」當展示品，比「假裝模型必勝」更有面試價值，且符合 ML serving 成本姿態（模型登錄＝DB 表＋門檻閘）與 grounding-first。
5. **12 datasets 檔數線性成長（§16.5）→ 提示留 plan，非本 spec 範圍。** 同意 plan 期可評估 check-data 清單改由 datasets.py 派生。

**特別嘉許（符合鐵律，記錄以利後續複用）**：agent 第一手 grep 揪出 ga-insight 兩個反面教材——`predictive.py:54-56` 捏造訓練目標（偽 ML）、`:89-93` 標籤洩漏——並設計修正版（時間切分 churn＋拒偽預測 LTV，改觀測窗實測分佈），完全落實 grounding-first 與反幻覺紀律；且全程守住公開 GA4 sample 非 area02 的隱私立場。

**知會 Fergus（須確認，非阻擋）**：GA 支柱資料更新為手動觸發（`ga_insight_batch` schedule=None）——靜態資料集下這是誠實形狀，但操作上「跑一次」需人為 `make ga-insight-run`；確認你對此操作節奏無異議。
