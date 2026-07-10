# 搜尋支柱 design（`/search`：搜尋工程展示頁——ES/smartcn 架構敘事 + 真 Elasticsearch live-demo 外連 + 站內離線示範）

> **上游**：[brief](2026-07-10-search-pillar-brief.md)（工作合約正本）＋ repo `CLAUDE.md`「Fable 5 design 精確度契約（8 條）」（自檢見 §12）＋ [統一作品集 crosscut design](2026-07-10-unified-portfolio-crosscut-design.md)（binding：§2.2/§2.3/§5/§7.2/§8.2/§10）＋ [Signal 設計系統 design](2026-07-10-frontend-design-system-design.md)（§4.3 取材點、§7 ⌘K palette、視覺地基）。
> **定位（鐵律）**：`/search` ＝搜尋**工程能力**的展示頁——把一個真實上線的 Elasticsearch 全文檢索系統（ptt-search）拆開講，配真 ES live-demo 外連與站內離線示範。**本站不重建 ES**；站內一切搜尋是 client-side fuse.js；真 ES 只存在於外連的獨立部署。與全站 ⌘K（導航式快速搜）的邊界照 crosscut §2.3 釘死。
> **一句話**：單頁 `/search`，PageHeader（含邊界誠實聲明）→ 兩種搜尋對照 → 離線示範（fuse.js over 自家 P3 PTT 標題語料 `search_ptt_titles.json`）＋ LiveDemoCard → 部署拓撲圖 → 查詢 DSL → 索引與 smartcn 分詞 → 搜尋行為回饋迴圈 → 已知限制與進化方向；全部內容第一手取材 ptt-search 實碼（file:line 見 §2），說明式 registry 條目正典文案本檔給齊。
> 產出日期：2026-07-10。**本階段只出 spec，plan 延後**；`frontend/` 尚無實作碼，以下全是「建立時即照此」。

---

## 0. 版本敏感宣稱查證（context7 2026-07-10；其餘沿 Signal §0 / crosscut §0 pin 不重議）

| 宣稱 | 查證結果 | 來源 |
|---|---|---|
| **smartcn plugin**：提供 `smartcn` analyzer、`smartcn_tokenizer` tokenizer、`smartcn_stop` filter（皆不可配置）；安裝 = `bin/elasticsearch-plugin install analysis-smartcn`；以**機率模型對簡體中文**求最優分詞（先斷句、再逐句分詞），適用中文或中英混合文本 | ✅ 官方文件原文確認——「uses probabilistic knowledge to find the optimal word segmentation for **Simplified Chinese** text」。此「簡體最優」是頁面誠實 caveat 的依據（PTT 為繁體語料，§4 blocks `index-anatomy`） | context7 `/websites/elastic_co_reference`（plugins/analysis-smartcn） |
| **multi_match 欄位加權 `title^2`**（caret boost 語法）、預設 type `best_fields`（dis_max 包裝） | ✅ 官方 query DSL 文件原文（`"fields": ["title^3", "description^2"]` 同款語法） | context7 同上（query-dsl/multi-match） |
| Elasticsearch **9.0.1** ＋ analysis-smartcn 同 image 裝載 | ✅ 非記憶——ptt-search `docker/elasticsearch/Dockerfile:1-2` 第一手：`FROM docker.elastic.co/elasticsearch/elasticsearch:9.0.1` + `RUN elasticsearch-plugin install --batch analysis-smartcn` | 本機唯讀 grep |
| fuse.js **7.4.2**（`new Fuse(list,{keys,threshold})`、`ignoreLocation`）；Next 16 `output:'export'`；route groups 不進 URL | 沿 **Signal §0 pin**（fuse 7.4.2 已 context7 查證）與 **crosscut §0**（route groups/static export 已 context7＋Opus 三腿覆核）——本檔零新增前端依賴，不重查不翻案 | Signal §0／crosscut §0 |
| ptt-search 全部工程事實 | 本檔撰寫時**第一手 grep**（backend/docker/nginx/frontend/README），逐條 file:line 見 §2，非轉抄 brief/Signal | 本機唯讀 grep |

---

## 1. 關鍵決策總表（brief 六項全收斂為單一決定；細節在各節）

| # | brief 項 | 決定 | 一句理由 |
|---|---|---|---|
| 1 | `/search` 支柱頁 IA | **單頁**（crosscut §2.2 授權範圍內取單頁），PageHeader＋8 個 registry blocks 縱向敘事流（§3）；sidebar navGroups 維持 crosscut §3.1 草樣 `[{ label:'搜尋工程', routes:['/search'] }]` 零改 | 一個系統一條故事線——拆多頁會產出彼此依賴的薄頁（查詢 DSL 頁離開索引頁講不通）；離線示範＋live-demo 放同一屏還能互相對照 |
| 2 | ES 架構敘事取材點 | **§2 接地事實表 15 條（file:line）落成 §4 八個 block 的說明式內容**：smartcn 索引 mapping、bool 查詢組裝、highlight、suggest 三層策略、more_like_this、批次 reindex、搜尋日誌迴圈、雙拓撲（docker-compose 本機／Vercel+Cloud Run+Neon+Bonsai 免費雲） | 非泛泛而談的硬性保證=每個 block 的內容都能指回一行實碼 |
| 3 | 離線示範語料源（拍板） | **採 crosscut §2.3 預設傾向：吃自家平台 P3 Silver 文章標題**——新 additive dataset **`search_ptt_titles.json`**（EP-D 紀律、≤300KB、欄位/裁切/SQL 見 §5）。可行性已對 P3 §6 Silver 合約逐欄確認（title/board/category/post_date/comments_score/url 全存在）。否決「裁切 ptt-search 示範資料」：那是另一個部署的另一顆 DB（Neon），跨專案搬資料破壞「本站資料皆出自本平台管線」的敘事一致性 | 敘事一致＋合約已備＝零新機制，只是 datasets.py 多一條目 |
| 4 | live-demo 外連 | `pillars.ts` `search.liveDemo` 沿 crosscut §3.1 形狀（URL plan 期實查回填）；`LiveDemoCard` 用 §7.2 固定句式原文＋`target="_blank" rel="noopener noreferrer"`＋顯示 hostname；**失效降級態文案本檔給定**（§6.3） | crosscut 慣例原樣落地，本檔只補「degraded 態」的正典文案 |
| 5 | ⌘K vs `/search` 邊界落實 | 頁級 Explainer（PageHeader 內、defaultOpen）**首句即邊界聲明**，正典文案 §7.1；**`search_ptt_titles` 語料不進全站 ⌘K 索引**（v1 刻意排除，理由與進化方向見 §7.2——此為對 crosscut §2.3「新支柱 dataset 進 build-search-index」預設的**支柱 spec 權限內裁定**，已列 §13 給 Opus 覆核） | 1,000 條標題全部 href 到同一頁=palette 噪音＋體積，v1 無 deep-link 語意（Signal §7.2 既判）承接不了它 |
| 6 | registry 條目 | `frontend/src/content/registry/search.ts` 單一 PageEntry（pageId `search`）＋8 blocks，`whyBuilt`/`whatItDoes` 等**正典文案本檔給齊**（§4，plan 照抄可微調字句不可刪意）；`aiVsComputed: 'computed'`（本頁零 AI 敘事，示範結果全由程式算） | 本支柱「內容即產品」——文案留給 plan 現寫=品質不可控，spec 給正典 |

**附帶裁定（brief 未點名但落地必須定的）**：離線示範元件形態（§5.3：`'use client'`＋lazy fetch＋fuse 動態載入＋顯示 fuse score）；拓撲圖形態（§3：inline SVG React 元件，沿 P4 `/architecture` SVG 慣例，不引 mermaid 進前端）；exporter 讀 `silver.ptt_articles`（非 gold）的合法性論證（§5.2）。

---

## 2. 接地事實表（第一手 grep ptt-search，2026-07-10；唯讀取材、保留部署不退役 = crosscut §8.2）

| # | 事實 | 出處（file:line） |
|---|---|---|
| 1 | ES index `ptt_articles` mapping：`title`/`content` 為 `text` ＋ `analyzer: smartcn`；`aid`/`board`/`author`/`category`/`url` 為 `keyword`；`posted_at` date；推文計數 integer——**「要全文檢索的欄用分詞 text、要精確過濾的欄用 keyword」的教科書級對照** | `ptt-search/backend/app/es/index.py:5-18` |
| 2 | 檢索查詢組裝：`bool` query——`must` = `multi_match {query, fields:["title^2","content"]}`（標題權重×2），無關鍵字時 fallback `match_all`；`filter` = `term`(category)/`range`(comments_score gte)/`range`(posted_at gte/lte)——**評分子句與過濾子句分離（filter 不參與算分、可快取）** | `backend/app/api/search.py:68-102` |
| 3 | 關鍵字高亮：ES `highlight`（content `fragment_size:200, number_of_fragments:1`），前端只保留 `<em>` 白名單再 `dangerouslySetInnerHTML`（regex strip 其餘 tag，防禦縱深） | `search.py:95-100`＋`frontend/components/search/ResultItem.tsx:4-8` |
| 4 | 搜尋建議三層策略：空 query→精選熱門詞；**單字→查 `search_logs` 以真實搜尋行為補全**（prefix LIKE＋頻次排序，merge 預設詞去重）；≥2 字→ES `match_phrase_prefix`（`max_expansions:10`） | `search.py:16-51` |
| 5 | 相關文章推薦：ES `more_like_this`（`fields:["title","content"]`、`like:[{_index,_id}]`、`min_term_freq:1, min_doc_freq:1`、size 5）——**用既有索引做內容相似推薦，零新基建** | `backend/app/api/articles.py:56-90` |
| 6 | 搜尋行為回饋迴圈：每次有意圖的搜尋（q 或任一 filter 非空）寫 `search_logs`（query/filters JSONB/命中數/**latency_ms 實測**）→ admin 儀表板出 KPI（今日/總量/平均延遲/最熱關鍵字）＋14 天趨勢 → 回饋建議詞（事實 4） | `search.py:109,128-143`＋`backend/app/db/models.py:34-44`＋`backend/app/api/admin.py:33-60` |
| 7 | Reindex 設計：Postgres 為 source of truth → delete-and-recreate index → 批次 200 bulk 寫入、記憶體內進度狀態、`409` 擋並發 reindex；跑於 API 背景 task | `admin.py:186-223,246-251`＋`backend/app/es/index.py:21-26` |
| 8 | 本機拓撲：docker-compose 五服務——nginx :80 反代（`/api/`→backend:8000、`/`→frontend:3000 含 websocket upgrade）＋ ES（single-node、`xpack.security.enabled=false`、堆 512m、healthcheck 讀 cluster health green\|yellow）＋ Postgres 16 | `docker-compose.yml:19-68`＋`nginx/nginx.conf` |
| 9 | 生產拓撲（全免費層）：Vercel（Next 前端＋`rewrites` 把 `/api/*` 導 Cloud Run）＋ Cloud Run（FastAPI）＋ Neon（PG）＋ Bonsai（ES，免費層 10k 文件上限） | `README.md:58-69,143-162` |
| 10 | ES 9.0.1 ＋ analysis-smartcn 打進同一 image（自建 Dockerfile 兩行） | `docker/elasticsearch/Dockerfile:1-2` |
| 11 | runtime ES client = **opensearch-py `AsyncOpenSearch`**（走 REST 相容路徑打 ES 9；lazy singleton、https 自動開 ssl+verify_certs） | `backend/app/es/client.py:7-16`＋`backend/pyproject.toml`（`opensearch-py[async]>=2.0.0`） |
| 12 | 前端搜尋 UX：300ms debounce（timer ref）＋ `latestQuery.current` race-guard 丟棄過期建議回應（Signal §4.3 已取材 debounce 進 palette） | `frontend/components/search/SearchBar.tsx:16-32` |
| 13 | ⚠️ 漂移（誠實記錄，**不上頁面**）：`scripts/reindex.py` import `elasticsearch`/`AsyncElasticsearch` 但 pyproject 依賴只有 opensearch-py——**殘留腳本已不可跑**，活路徑是事實 7 的 admin API | `backend/scripts/reindex.py:6-7` vs `pyproject.toml` |
| 14 | ⚠️ 漂移（同上）：README 稱「reindex 只索引最新 10k 篇」（Bonsai 上限），但 `_run_reindex` 全表 offset 掃描**無 10k cap、無 ORDER BY**——文件與碼不一致 | `README.md:69,134-138` vs `admin.py:196-216` |
| 15 | ⚠️ 資安面（**只給 Opus/plan，嚴禁寫上公開頁**）：admin routes 明文註記「No authentication required — restricted at the network/proxy level」，含 POST `/api/admin/reindex`——live 部署若把 Cloud Run `--allow-unauthenticated` 直曝，此面即公網可打 | `admin.py:22` |

**取材界線（進化非複刻）**：取的是**工程敘事素材與判斷**（mapping 取捨、DSL 組裝、拓撲圖、回饋迴圈概念）；不搬任何碼進本 repo（本站無 ES、無 FastAPI 檢索端）；唯一「機制複用」是 fuse.js 離線示範沿 Signal §7 既有依賴。事實 13-15 是取材過程的誠實副產物：13/14 佐證「文件漂移是真專案常態」可折進 limits 敘事（去指名化），15 純風險回報。

---

## 3. 頁面 IA（單頁 `/search`；Signal Data-Dense 標準頁模板，treatment 沿 Signal §5）

```
frontend/src/app/(search)/search/page.tsx        # RSC；crosscut §2.1 route map 既定位置
frontend/src/components/search-pillar/
├── SearchModesCard.tsx        # 區塊① 兩種搜尋對照（RSC）
├── OfflineSearchDemo.tsx      # 區塊② 'use client'（§5.3）
├── SearchTopologyDiagram.tsx  # 區塊④ inline SVG（RSC；token 上色，沿 P4 /architecture SVG 慣例）
└── QueryDslCard.tsx           # 區塊⑤ 查詢 JSON 展示（RSC；Fira Code <code> 塊）
```

| 順序 | 區塊（= registry block id） | 內容與版面 |
|---|---|---|
| 0 | `PageHeader entryId="search"`（crosscut §5.3） | h1 問句＋whatItDoes 副標＋whyBuilt 常駐列＋頁級 Explainer（defaultOpen；**首句=⌘K 邊界聲明** §7.1） |
| 1 | `search-modes` | 全寬卡：「本站的兩種搜尋」對照表（⌘K fuse.js vs live-demo Elasticsearch：執行位置/索引/分詞/評分/規模/適用場景 六列）——把邊界聲明變成可讀的工程對照，不只一句免責 |
| 2 | `offline-demo`＋`live-demo` | **2-col 並排**（行動端堆疊）：左=離線示範（§5.3）、右=`LiveDemoCard pillar="search"`（§6）——「模糊比對」與「真全文檢索」物理上放在一起對照 |
| 3 | `topology` | 全寬卡：部署拓撲 SVG——上半=本機 docker-compose 五服務（事實 8），下半=生產免費雲四件（事實 9），連線標注 nginx 反代/Vercel rewrites；圖說標「此為 ptt-search（獨立部署）的拓撲，非本站——本站為純靜態」 |
| 4 | `query-dsl` | 全寬卡：真實查詢 JSON（事實 2 的 bool 組裝，Fira Code）＋逐行註解（must vs filter、`title^2`、highlight）；附 suggest 三層策略小節（事實 4） |
| 5 | `index-anatomy` | 全寬卡：mapping 表（事實 1 十欄逐欄「text+smartcn vs keyword」取捨）＋ smartcn 一段（§0 查證內容：機率分詞、先句後詞、**簡體最優的繁體 caveat**） |
| 6 | `feedback-loop` | 卡：search_logs 迴圈圖示（搜尋→記錄 latency/命中→儀表板→回饋建議詞，事實 6）＋「相關文章 = more_like_this」小節（事實 5） |
| 7 | `limits-evolution` | 卡：已知限制與進化方向（§4 正典文案；**去指名化、不含可濫用細節**——§2 事實 15 不出現） |

lucide icons（plan 期以 1.24.0 export 校準，同 crosscut §12.3）：頁 icon `Search`（crosscut 已定）；區塊層 `SearchCode`（query-dsl）/`Database`（index-anatomy）/`Network`（topology）/`RefreshCw`（feedback-loop）/`Construction` 或 `Route`（limits）——擇實存者，非阻擋。無任何 emoji。

---

## 4. 說明式 registry 條目（正典文案；`frontend/src/content/registry/search.ts`，schema 照 crosscut §5.2 零改）

```ts
export const searchPages = {
  search: {
    pillar: 'search',
    route: '/search',
    questionTitle: '一個中文全文檢索引擎是怎麼搭起來的？',
    whyBuilt:
      '展示搜尋工程能力：把一個真實上線的 Elasticsearch 全文檢索系統（ptt-search，獨立部署）拆開講——' +
      '中文分詞、索引設計、查詢 DSL、搜尋行為回饋迴圈、免費雲部署拓撲，並附可實際操作的 live demo。',
    whatItDoes:
      '本頁提供：①站內離線示範（對本平台 PTT 文章標題做 client-side 模糊搜尋，輸入即搜）' +
      '②真 Elasticsearch live demo 外連（獨立部署，可下關鍵字/分類/推文數/日期條件的全文檢索）' +
      '③索引 mapping、查詢 DSL、部署拓撲的逐段解說。',
    howToRead:
      '本站站內搜尋（⌘K）是 client-side fuse.js 模糊搜；真 Elasticsearch 全文檢索在 live demo（獨立部署）。' +
      '先玩區塊②的兩個搜尋感受差異，再往下讀它們背後的工程差異。',
    canDo: '看懂 text/keyword 欄位取捨、bool 查詢的評分/過濾分離、smartcn 分詞、以及 0 元跑起一套檢索服務的拓撲。',
    problem: 'LIKE %kw% 掃全表做不了中文分詞相關性排序；而「會呼叫 ES API」和「能講清楚索引與查詢設計取捨」是兩種深度。',
    dataSource: ['search_ptt_titles.json ← silver.ptt_articles（本平台 P3 管線，Postgres serving）',
                 'live demo ← ptt-search 獨立部署（Vercel + Cloud Run + Neon + Bonsai ES）'],
    caveats: [
      '離線示範語料是本平台 P3 管線抓取的 PTT 文章標題；live demo 索引的是 ptt-search 專案自己的飲料板語料——兩者是不同資料集。',
      '離線示範是 fuse.js 字元級模糊比對（無分詞、無 BM25），刻意用來對照、不假裝是全文檢索。',
      'smartcn 以簡體中文機率模型分詞，對繁體語料屬可用但非最優（見「索引與分詞」段）。',
    ],
    aiVsComputed: 'computed',
    blocks: { /* 八個 block；每塊 howToRead 由上表區塊內容濃縮，plan 照 §3/§4 落字 */
      'search-modes':   { howToRead: '同一個「搜尋」按鈕背後可以是完全不同的系統——六個維度逐列對照 client-side 模糊搜與伺服器端全文檢索。', dataSource: ['（靜態對照內容）'], aiVsComputed: 'none' },
      'offline-demo':   { questionTitle: '不架伺服器能做到多少搜尋？', howToRead: '輸入任意關鍵字（可打錯一兩個字），結果依 fuse.js 相似度分數排序；分數越小越相似。此為純瀏覽器內比對，斷網也能跑。', formula: 'fuse score ∈ [0,1]，0 = 完全符合；threshold 0.35', dataSource: ['search_ptt_titles.json'], caveats: ['僅比對標題字元序列，無分詞、無內文檢索。'], aiVsComputed: 'computed' },
      'live-demo':      { howToRead: '外連為獨立部署的完整系統：關鍵字丟給 Elasticsearch 做 smartcn 分詞後以 BM25 排序，支援分類/推文數/日期過濾與命中高亮。', dataSource: ['ptt-search 獨立部署'], aiVsComputed: 'none' },
      'topology':       { questionTitle: '這套系統跑在哪裡、花多少錢？', howToRead: '上=本機 docker-compose（nginx 反代五服務）；下=生產（Vercel/Cloud Run/Neon/Bonsai 全免費層）。圖為 ptt-search 的拓撲，非本站。', dataSource: ['ptt-search repo docker-compose.yml / nginx.conf / README 部署章'], caveats: ['免費層有硬上限（如 Bonsai 10k 文件），是取捨不是缺陷。'], aiVsComputed: 'none' },
      'query-dsl':      { questionTitle: '一次搜尋在 Elasticsearch 裡長什麼樣？', howToRead: 'bool 查詢兩半：must（multi_match，標題權重 ×2，參與算分）與 filter（分類/推文數/日期，精確過濾、可快取、不影響分數）。', formula: 'fields: ["title^2", "content"]（title 命中分數加倍）', dataSource: ['ptt-search backend 檢索 API 實碼'], aiVsComputed: 'none' },
      'index-anatomy':  { questionTitle: '為什麼有的欄位要分詞、有的不能分？', howToRead: 'title/content 用 text+smartcn（分詞後倒排、可相關性排序）；board/category/author 用 keyword（原字串精確比對，供 filter/聚合）。選錯方向：keyword 搜不到半句話、text 過濾不精確。', dataSource: ['ptt-search ES index mapping 實碼'], caveats: ['smartcn 為簡體最優的機率分詞，繁體語料的進化方向是繁體字典型 analyzer 或索引前正規化。'], aiVsComputed: 'none' },
      'feedback-loop':  { questionTitle: '搜尋系統怎麼越用越好？', howToRead: '每次搜尋記錄 query/條件/命中數/實測延遲 → 儀表板看熱門詞與延遲 → 真實搜尋行為回饋成建議詞（單字前綴補全查的是歷史紀錄，不是索引）。相關文章推薦用 more_like_this 直接吃既有索引，零新基建。', dataSource: ['ptt-search search_logs 表與 admin API 實碼'], aiVsComputed: 'none' },
      'limits-evolution': { howToRead: '誠實列出這套系統的取捨與下一步，見卡片內文。', dataSource: ['（工程判斷）'], aiVsComputed: 'none' },
    },
  },
} as const;
```

**`limits-evolution` 卡正典內文**（plan 照抄；已去指名化、無可濫用細節）：
- 全量 delete-and-recreate reindex 在文件量大時有搜尋空窗——進化方向：別名（alias）雙索引熱切換。
- reindex 進度狀態存在單一實例記憶體——多副本部署需外部化（DB/Redis）。
- smartcn 對繁體屬堪用非最優——進化方向：繁體字典 analyzer 或索引前繁簡正規化，配 A/B 對比召回。
- 免費層 10k 文件上限決定了「取最新子集索引」的策略——文件配額本身是索引設計輸入。
- 文件與碼會漂移（真專案常態）——防治靠把合約寫成可執行守門（本站 registry coverage gate 即此思路）。

---

## 5. 站內離線示範（拍板細節）

### 5.1 dataset 合約：`search_ptt_titles.json`（additive，EP-D 紀律）

- **exporter 條目**（`orchestration/exporter/src/exporter/datasets.py` append，P4 §4 合約正本內）：name `search_ptt_titles`、output `search_ptt_titles.json`、cap **1,000 列**。SQL 形狀（plan 落最終版）：
  `SELECT aid, board, title, category, post_date::text AS post_date, comments_score, url FROM silver.ptt_articles WHERE title IS NOT NULL AND title <> '' ORDER BY post_date DESC, comments_score DESC LIMIT 1000;`
- **讀 silver 而非 gold 的論證**：語料是**原樣標題樣本**非分析聚合，為它立 gold mart = 違 P3「Gold 就 board_daily 一張，YAGNI」判定；P4 exporter 已有讀非 gold schema 先例（`sentiment_daily.json` ← `ml.ml_comment_sentiment`）；`source_tables` 欄如實標 `silver.ptt_articles`。freshness 由 export DAG 既有 `check_freshness` 蓋住。`pipeline_writer` 對 silver 的 SELECT 為 plan 期實查（P1 GRANT 合約預設已含）。
- **信封**：P4 統一信封同構（`dataset/generated_at/source_tables/status/row_count/rows`）；P3 未跑 → `status:"absent"` 空 rows（P4 容忍路徑原樣）。
- **row schema（欄位級）**：`{ aid: string, board: string, title: string, category: string|null, post_date: 'YYYY-MM-DD', comments_score: number, url: string|null }`——author 刻意不出庫（示範用不到，最小化原則）。
- **體積**：估 1,000 列 × ~230-260B ≈ 230-260KB；**≤300KB 斷言**加進 `check-data.mjs`（該檔專屬上限，嚴於全域單檔 3MB）。超限降階序：砍 `url` 欄 → N 1,000→800→600。
- **命名空間**：`search_` 前綴 = crosscut 決策 13 已保留；本檔用掉第一個。

### 5.2 與既有合約的關係

check-data.mjs 檔案清單 append 一條（EP-D「讀既有→append 自己→不動他人」）；`frontend/src/lib/types.ts` 加 TS 鏡像型別；**不加 MCP 工具**（v1 裁定：語料是頁面示範素材非分析資料，MCP 曝露它無問答價值；若日後 `/search` 長出分析內容再議——寫進進化方向，非遺漏）。

### 5.3 示範元件 `OfflineSearchDemo.tsx`（行為契約）

- `'use client'`；初始只渲染輸入框＋說明；**首次 focus 才** `fetch('/data/search_ptt_titles.json')` ＋ `import('fuse.js')`（動態 import，沿 Signal §7.3 palette 的 bundle 紀律——首屏 JS 零搜尋碼）。
- fuse 配置對齊 Signal §7.1 同款參數語彙：`keys:['title','category']`、`threshold:0.35`、`ignoreLocation:true`、`includeScore:true`；輸入 **150ms debounce**（Signal §4.3 取材點的落地）。
- 結果列（上限 20）：title（不做假高亮——fuse 是模糊比對，仿 ES `<em>` 高亮=視覺謊言）＋ board/category badge ＋ post_date ＋ `推 {comments_score}` ＋ **fuse score**（Fira Code，教學點：讓人看見「相似度分數」與 BM25 是兩回事）＋ title 外連原文（`url` 存在時，`target="_blank" rel="noopener noreferrer"`）。
- **常駐誠實標**（輸入框正下方 caption，正典文案）：「此示範為瀏覽器內 fuse.js 模糊比對（無分詞、無 BM25），語料為本平台匯出的 {row_count} 篇 PTT 文章標題（{generated_at}）；真 Elasticsearch 全文檢索見右側 live demo。」
- absent 態：整卡顯示 P4 既定文案「此資料尚未由平台產出」＋ muted 樣式，輸入框 disabled——頁面其餘區塊照常（本頁不依賴語料也成立）。
- 無結果態：「找不到『{q}』——語料僅含 {row_count} 篇文章標題」。
- a11y：input 有 `<label>`（可視）；結果為 `<ul>` 語意清單；全鍵盤可達，納入 Signal 驗收 #7 walkthrough 擴充段。

---

## 6. live-demo 外連（crosscut §7.2 慣例逐條落地）

### 6.1 `pillars.ts` 值（crosscut §3.1 形狀零改）

```ts
search: { name: '搜尋', icon: 'Search', homeRoute: '/search',
          navGroups: [{ label: '搜尋工程', routes: ['/search'] }],
          liveDemo: { url: '<ptt-search Vercel 前端 URL——plan 期實查回填>',
                      deployment: 'Vercel + Cloud Run + Neon + Bonsai Elasticsearch',
                      note: '獨立部署的真 Elasticsearch 全文檢索' } },
```

外連目標 = **ptt-search 的前端站首頁**（不是 API/後台路徑）。

### 6.2 呈現（`LiveDemoCard` 共用元件，crosscut §5.3 已定）

固定句式**原文不得改寫弱化**：「此連結開啟另一個獨立部署（Vercel + Cloud Run + Neon + Bonsai Elasticsearch）；本站為純靜態展示，不依賴該服務。」＋ lucide `ExternalLink` ＋ 顯示目標 hostname ＋ `target="_blank" rel="noopener noreferrer"`。落點兩處：本頁區塊②右欄、`/architecture` 整合模式卡一行（crosscut §7.4，隨該卡 plan 落地）。

### 6.3 失效降級態（brief 要求本 spec 給文案；拍板）

plan 期實查 URL 若已下線（判準：預期頁面無法載入），`LiveDemoCard` 降級渲染：外連按鈕移除，改**介面截圖**（P5 截圖紀律：PNG ≤300KB）＋正典文案：「此系統的線上部署已下線；架構與查詢流程見下方拓撲圖與 DSL 解說，介面如截圖。原始碼部署形狀：Vercel + Cloud Run + Neon + Bonsai Elasticsearch（皆免費層）。」——誠實態不裝活。降級態由 `pillars.ts` `liveDemo` 欄改放 `{ screenshot, deployment, offlineNote }` 變體承載（plan 期依實查結果二選一落型別）。

---

## 7. ⌘K vs `/search` 邊界落實（crosscut §2.3 釘死內容的頁內落點）

### 7.1 頁級 Explainer 首句（正典，逐字）

「本站站內搜尋（⌘K）是 client-side fuse.js 模糊搜；真 Elasticsearch 全文檢索在 live demo（獨立部署）。」——已同時寫進 registry `howToRead` 首句（§4），PageHeader 的頁級 Explainer defaultOpen 即渲染之；區塊①再以六維對照表展開（執行位置：瀏覽器 vs 伺服器｜索引：build-time JSON vs 倒排索引｜中文處理：字元模糊比對 vs smartcn 分詞｜排序：fuse 相似度 vs BM25｜規模：~2k 條目 vs 10k+ 文件｜角色：站內導航 vs 檢索工程本體）。

### 7.2 palette 銜接裁定

- `page` 條目：`/search` 頁自動經 crosscut §2.3①的 registry 派生進 palette（subtitle = §4 `whatItDoes` 首句裁 40 字）——零本檔動作。
- **`search_ptt_titles` 不進 `build-search-index.mjs`**（決策 5）：全部條目 href 同一頁、v1 無 query 預填/deep-link 通道（Signal §7.2 既判），進去只是噪音＋吃 palette 300KB 上限。**進化方向**：palette 選中標題條目 → `/search?q=` 預填離線示範（需 URL-as-state，與 Signal 進化方向同一項解鎖）。

---

## 8. 資料流與守門總圖（全 additive，零新機制）

```
（平台側）export_frontend_data DAG（既有）
  └─ datasets.py append: search_ptt_titles（§5.1）→ latest/search_ptt_titles.json（P4 信封）
（repo 側）make export-sync → 人審 commit → frontend/public/data/search_ptt_titles.json
（build）check-data.mjs：append 檔案清單條目＋本檔專屬 ≤300KB 斷言；absent 容忍沿 P4
（頁面）/search RSC 讀 registry；OfflineSearchDemo client fetch 語料；LiveDemoCard 讀 pillars.ts
（gate）registry coverage gate（crosscut §5.5 六斷言）自動涵蓋本頁——search.ts 缺欄/沒接 PageHeader = CI 紅
```

新增守門（進 frontend-ci 既有步驟，非新 job）：①`search_ptt_titles.json` ≤300KB（check-data.mjs）②grep `frontend/src/app/(search)/` 與 `components/search-pillar/`：外連一律含 `rel="noopener noreferrer"`（一次性驗收也可，plan 定）。

---

## 9. 驗收清單（每條可實跑；併入 crosscut §11 於搜尋支柱 plan 生效）

| # | 檢查 | 方法 | 預期 |
|---|---|---|---|
| 1 | 靜態匯出 | `next build` 後 `out/search/` 存在、無括號路徑 | 綠（crosscut 驗收 #1 子集） |
| 2 | registry gate | `npm run gate:explainers`；反例=刪 `search.ts` 任一 block 的被引用 key 或 `whyBuilt` | 正例綠、反例紅 |
| 3 | 邊界聲明 | grep `out/search/` 含 §7.1 句式全文；⌘K palette 無 `search_ptt_titles` 條目 | 皆符合 |
| 4 | 誠實固定句式 | grep LiveDemoCard 渲染輸出含 §6.2 句式全文＋hostname 顯示＋`rel="noopener noreferrer"` | 符合 |
| 5 | 語料合約 | `check-data.mjs`：檔存在（或 absent 信封）、≤300KB、欄位齊 | 綠 |
| 6 | absent 態 | 暫以 absent 信封替換語料檔 → build 綠、示範卡顯示「此資料尚未由平台產出」、其餘區塊照常 | 符合 |
| 7 | 示範互動 | 手動：focus 載語料（Network 面板見 lazy fetch）、輸錯一字仍命中、fuse score 顯示、20 條上限、無結果態文案 | 符合 §5.3 |
| 8 | a11y | Signal 驗收 #7 擴充：Tab 進輸入框→結果清單→live-demo 外連；focus ring 可見 | 全鍵盤可達 |
| 9 | 首屏 bundle | 首屏 JS chunk 不含 fuse.js 與語料（build analyzer 或 Network 驗證） | 符合 §5.3 lazy 紀律 |
| 10 | 內容接地 | 對照 §2：頁上每個工程宣稱可指回事實表條目；smartcn 段含繁體 caveat | 無「泛泛而談」區塊 |

---

## 10. plan 期待查證點（皆帶預設傾向與降級；非阻擋本 design 收斂）

1. **ptt-search live URL 現值與存活**——實查回填 `pillars.ts`；活=§6.1、死=§6.3 降級態（文案已備）。
2. **live 部署 admin 面曝露**（§2 事實 15）——實查 Cloud Run 端點 `/api/admin/*` 與前端 `/admin` 是否公網可達；預設處置=在 ptt-search 側（獨立 repo）收斂（Cloud Run 加驗證/nginx 層擋/或至少文件化風險），**本站不因此阻擋**（外連只指前端首頁）；此為對外連目標的盡責檢查，非本 repo 範圍。
3. **語料實際體積**——P3 實跑後量 `search_ptt_titles.json`；>300KB 走 §5.1 降階序。
4. **`pipeline_writer` 對 `silver.ptt_articles` 的 SELECT**——預設 P1 GRANT 合約已含；缺則 additive GRANT（P4 §10B 實查 1 同款）。
5. **lucide 區塊 icon 名**（§3 清單）——lockfile 落定擇實存者，5 分鐘校準。
6. **fuse.js 動態 import 與 palette 共 chunk**——預設 bundler 自動去重（同一依賴）；驗收 #9 兜底。

---

## 11. 本 spec 拍板 vs 下放對照

| 主題 | 本 spec 拍板 | 下放（plan） |
|---|---|---|
| IA | 單頁、8 區塊、順序、版面、元件檔落點（§3） | 卡片內文微排版 |
| 內容 | 接地事實 15 條、八 block 正典文案、limits 卡內文、三段正典誠實標語（§4/§5.3/§6.3/§7.1） | 字句潤飾（不可刪意）、SVG 繪製 |
| 語料 | 來源=P3 Silver、dataset 名/欄位/裁切/上限/降階序/absent 行為、讀 silver 論證、不進 MCP、不進 ⌘K | SQL 最終版、實測體積調 N |
| live-demo | pillars.ts 形狀、句式、落點、降級態文案與型別變體 | URL 實查回填、活/死二選一 |
| 邊界 | 首句正典、六維對照表內容、palette 銜接（page 條目進、語料不進）＋進化方向 | — |
| registry | search.ts 全條目（含 aiVsComputed='computed' 論證） | 隨 gate 落地接線 |
| 守門 | 驗收 10 條、300KB 專屬斷言、rel 檢查 | 接進 check-data.mjs/CI 的實作 |

---

## 12. 精確度契約 8 條自檢

1. **開放問題收斂**：brief 六項全落單一決定（§1），含附帶裁定三項；零 TBD/兩案並陳；§10 六點皆「plan 期實查＋預設傾向＋降級」。
2. **版本＋context7**：§0——smartcn（analyzer/tokenizer 名、簡體最優原文）與 multi_match caret boost 當日 context7 查證；ES 9.0.1/opensearch-py 為第一手 Dockerfile/pyproject 事實非記憶；fuse/Next/route groups 沿 Signal/crosscut 已證 pin，零新前端依賴。
3. **欄位級契約**：`search_ptt_titles` row schema/SQL 形狀/cap/降階序（§5.1）、registry 條目全欄含正典文案（§4）、pillars.ts 值與降級變體（§6）。
4. **檔案形狀具體**：頁與元件檔落點（§3）、exporter/check-data/types.ts 的 append 點（§5.2/§8）、驗收命令（§9）。
5. **沿用慣例**：P4 信封/absent/check-data、EP-D append 紀律、crosscut registry schema/gate/LiveDemoCard/PillarShell 零改、Signal fuse 參數語彙與 bundle 紀律、P5 截圖紀律、P3 Gold YAGNI 判定（不為語料立 mart）。
6. **進化非複刻**：§2 取材界線明文（取敘事素材不搬碼）；示範不仿 ES 高亮（視覺誠實）；漂移事實去指名化折進 limits 敘事。
7. **硬約束貫徹**：不重建 ES（全站僅 fuse；ES 只在外連）、純靜態拓撲不破（語料=committed JSON、示範純 client）、誠實標三落點（§5.3/§6.2/§7.1 正典文案）、registry 阻擋級（gate 覆蓋）、emoji→lucide（§3）、≤300KB additive（§5.1）、非互動不提問（全檔零待問）。
8. **每步可測**：§9 十條全給方法與預期，含 gate 反例與 absent 態實跑。

---

## 13. 給 Opus 的把關提示（覆核建議點）

1. **語料不進 ⌘K 索引**（§7.2）是對 crosscut §2.3「新支柱 dataset 進 build-search-index.mjs 為 additive 條目」預設方向的裁定性偏離（crosscut 同句授權「各支柱 spec 定裁切欄」，本檔行使為「裁到零」）：理由=全條目同 href、無 deep-link 通道、palette 體積。若 Opus 認為應進，回退=append 一個 `ptt_title` type（title/`board · 推N`/href `/search`）即可，其餘設計不動。
2. **exporter 讀 `silver.ptt_articles`**（§5.1）：有 `ml.*` 先例但首次讀 silver schema——論證在檔（原樣樣本非聚合、P3 Gold YAGNI 判定），值得確認不與 P1/P3 合約精神衝突。
3. **資安回報（不在本 repo 範圍但必須知會）**：ptt-search live 部署的 `/api/admin/*` 無認證（`admin.py:22` 明文「network/proxy level」防護假設，但 README 部署章是 `--allow-unauthenticated` Cloud Run 直曝），含 POST reindex 可被濫發；前端 `/admin` 儀表板亦公開可逛。已列 §10.2 plan 期實查與處置預設（在 ptt-search 側收斂）；**公開頁內容已刻意排除此細節**（§2 事實 15 標記）。
4. **registry 正典文案寫進 spec**（§4）超出 crosscut §5.2「條目內容各 plan 填」的預設分工——本支柱「內容即產品」，spec 給正典、plan 落地，屬收緊非違約；若 Opus 傾向維持 plan 填，本檔文案降級為「參考稿」即可，結構零改。

---

## 14. Opus 把關（2026-07-10；規劃者覆核，PASS）

**結論：PASS，可進 plan 佇列（spec-only，plan 延後）。** 精確度契約 8 條逐條符合；承重宣稱（route groups × `output:'export'` × per-group layout）沿 crosscut §0 已完成的三腿 context7＋Opus 覆核，本檔零新增架構承重點，不重查；新技術宣稱（smartcn 簡體最優、`multi_match` caret boost）屬**取材敘事內容**非本站架構承重，就算措辭偏保守也只影響頁面 caveat 文案、不破拓撲，且已當日 context7 查證——覆核通過。

**四風險點裁定：**
1. **語料不進 ⌘K 索引（§7.2）→ 核准維持。** crosscut §2.3 同句已授權「各支柱定裁切欄」，「裁到零」在權限內；v1 全條目同 href、無 deep-link 通道，進 palette 只是噪音＋吃 300KB 上限。進化方向（`/search?q=` 預填，與 Signal URL-as-state 同一項解鎖）已記錄，一行可回退，無鎖死。
2. **exporter 讀 `silver.ptt_articles`（§5.1）→ 核准。** 原樣標題樣本非聚合，為它立 gold mart 違 P3「Gold 就 board_daily 一張」YAGNI 判定；P4 已有讀非 gold schema 先例（`sentiment_daily.json ← ml.*`）。`pipeline_writer` SELECT 權限列 §10.4 plan 期實查，非阻擋。
3. **資安回報（ptt-search live admin 無認證，§2 事實 15）→ 升級為 live-demo 上線 gating 前置。** agent 的公開頁處置正確（頁面刻意排除可濫用細節、外連只指前端首頁），但我把它**升級**：在 `pillars.ts` `search.liveDemo.url` 填入真實 URL、讓作品集公開指向該部署**之前**，必須先確認 ptt-search 的 `/api/admin/*`（含 POST reindex）與 `/admin` 儀表板非公網匿名可達——否則等於在求職作品集裡公開指向一個可被匿名濫發 reindex 的端點。**處置在 ptt-search 側（獨立 repo，本規劃者不越界改它）**，列為該 plan 的前置 gate，非「盡責檢查」。→ 已知會 Fergus（見下）。
4. **registry 正典文案寫進 spec（§4）→ 核准維持正典，不降級為參考稿。** 這正落實 Fergus「頁面功能描述要像 ga-insight 那樣完整」的要求——spec 給正典文案，正是保證完整度不被 plan 階段隨意打折的機制。

**知會 Fergus（非本 repo 範圍、須人決策）**：ptt-search 的線上部署 admin 面（reindex 等）在 README 的 `--allow-unauthenticated` Cloud Run 配置下屬公網匿名可達——這是**另一個獨立 repo/部署**的資安面，本規劃者不越界修改，但在把它當作品集 live-demo 對外公開前建議先在 ptt-search 側收斂（加驗證／proxy 層擋）。
