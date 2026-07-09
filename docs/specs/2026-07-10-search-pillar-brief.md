# 搜尋支柱 spec — brief（搜尋工程能力展示：ES 架構敘事 + 真 Elasticsearch live-demo + 站內離線示範）

> **精確度契約**：依 repo `CLAUDE.md`「Fable 5 design 精確度契約（8 條）」交辦；design 逐條自檢。
> **框架上游（binding）**：
> - [統一作品集 crosscut design](2026-07-10-unified-portfolio-crosscut-design.md)——綁定：§2.2（搜尋支柱 segment `/search`、icon `Search`、首頁）、**§2.3（⌘K 全站搜 vs 搜尋支柱邊界釘死＋離線示範語料源預設傾向）**、**§7.2（live-demo 外連呈現慣例＋誠實固定句式＋v1 配置）**、**§8.2（ptt-search 取材：保留部署不退役）**、§5（說明式 registry）、§10 對照表「搜尋支柱 spec」欄。
> - [Signal 設計系統 design](2026-07-10-frontend-design-system-design.md)——§4.3 已定的 ptt-search 元件取材點、§7 ⌘K palette、視覺地基。
> **接地**：Fable 5 須**第一手 grep** ptt-search（`/Users/fergus/Desktop/workshop/fergus/data-workshop/fergus/ptt-search`）的 `backend/`（FastAPI 檢索 API 形狀）、`docker/`＋`nginx/`（部署拓撲）、前端搜尋 UX；版本敏感處 context7。
> **本階段只出 spec，plan 延後。**

---

## 一句話目標

搜尋支柱＝**搜尋工程能力的展示頁**：Elasticsearch/FastAPI 全文檢索架構敘事（取材 ptt-search）＋**真 Elasticsearch 的 live-demo 外連**（獨立部署）＋站內離線示範。與全站 ⌘K（client-side fuse.js 模糊搜）**明確區分**——⌘K 是導航式快速搜，`/search` 是搜尋**工程本身**的展示。

## 接地：ptt-search（唯讀取材，保留部署不退役）

ptt-search＝已建的 Next.js 16 + Tailwind v4 + FastAPI + Postgres 16 + **Elasticsearch 9 + smartcn** 全文檢索，部署 Vercel + Cloud Run + Neon + Bonsai ES。取材＝檢索 API 形狀、ES/smartcn 架構、部署拓撲圖素材、搜尋 UX 敘事（Signal §4.3 六元件取材點）。**本站不重建 ES**（拓撲鐵律）。

## Fable 5 要收斂拍板的項目（crosscut §10「下放」欄）

1. **`/search` 支柱頁 IA**：單頁或少頁（crosscut §2.2 授權）——收斂頁數與每頁內容。內容至少含：ES/smartcn/FastAPI 架構敘事（說明式，含拓撲圖）、`LiveDemoCard`（§5.3，真 ES 全文檢索外連）、站內離線示範。
2. **ES 架構敘事取材點**：從 ptt-search `backend/`/`docker/`/`nginx/` grep 出具體可講的工程點（分詞 smartcn、索引設計、檢索 API、部署拓撲），落成說明式內容（非泛泛而談）。
3. **站內離線示範語料源（拍板）**：crosscut §2.3 **預設傾向＝吃自家平台 P3 Silver 文章標題 additive 匯出 ≤300KB**（敘事一致，勝 ptt-search 示範資料裁切）；Fable 5 確認可行性（P3 資料合約）與裁切欄，或給更好方案。站內搜尋機制沿 Signal §7 fuse.js，不引 ES。
4. **live-demo 外連**（§7.2 慣例）：`pillars.ts` 的 `search.liveDemo`（部署 URL plan 期實查回填；若失效→截圖降級態文案）；`LiveDemoCard` 誠實固定句式「此連結開啟另一個獨立部署…本站為純靜態展示，不依賴該服務」；`target="_blank" rel="noopener noreferrer"`＋顯示 hostname。
5. **⌘K vs `/search` 邊界落實**（§2.3 已釘死）：頁內首段 Explainer 誠實聲明「站內 ⌘K＝client-side fuse.js 模糊搜；真 Elasticsearch 全文檢索在 live demo（獨立部署）」。
6. **registry 條目**（§5 schema）：`whyBuilt`（為什麼做搜尋工程展示）/`whatItDoes`（這頁展示什麼、怎麼用）硬性；`dataSource`/`caveats` 誠實標離線示範 vs live-demo。

## 硬約束

- **不重建 ES**（拓撲鐵律）；站內搜尋是 fuse.js（Signal §7），真 ES 只在 live-demo 外連。
- **誠實標** live-demo 為獨立部署；**說明式 registry 阻擋級**（缺 `whyBuilt`/`whatItDoes` = gate fail）；**emoji→lucide**。
- 純靜態 export 拓撲不破；離線示範語料若吃 P3 Silver 走 additive 匯出（EP-D）。

## Scope

- **in**：`/search` 支柱頁 IA、ES 架構敘事取材與說明式內容、離線示範語料源拍板、live-demo 外連落法、⌘K 邊界落實、registry 條目結構、驗收。
- **out**：重建 ES/檢索後端、P3 資料合約改動、Signal token 重定、⌘K palette 機制改動（沿 Signal §7 原樣）。

## 產出

寫到 `docs/specs/2026-07-10-search-pillar-design.md`；檔頭指向本 brief＋精確度契約＋crosscut。附「plan 期待查證點」與「本 spec 拍板 vs 下放」對照。**不 git commit**（Opus 把關後處理）。完成回報：檔案路徑、關鍵拍板摘要、context7/grep 查證項、給 Opus 覆核的風險點。
