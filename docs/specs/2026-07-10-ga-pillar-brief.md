# GA 分析支柱 spec — brief（漏斗為核心的完整銷售分析，取代並超越 ga-insight）

> **精確度契約**：本 brief 依 repo `CLAUDE.md`「Fable 5 design 精確度契約（8 條）」交辦；design 產出須逐條自檢。
> **框架上游（binding，不得抵觸）**：
> - [統一作品集 crosscut design](2026-07-10-unified-portfolio-crosscut-design.md)——**本支柱的合約框架**。綁定條款：§2.2（GA 支柱 segment `/ga`、icon、細設歸屬）、**§2.4（章節敘事約束：進化非複刻、問題導向、漏斗為核心、頁面不必同模板）**、**§4（GA 支柱 vs `/audience` 視角切線：正本圖唯一、`related` cross-link）**、**§5（說明式 registry：`whyBuilt`/`whatItDoes` 硬性欄、coverage gate 阻擋級）**、**§7.3（GA 資料流合約邊界 4 條）**、§10 對照表「下放 GA 支柱 spec」欄＝本 brief 的工作清單、§6.3(a)（每頁輕量問 AI 摺疊區接縫）。
> - [Signal 設計系統 design](2026-07-10-frontend-design-system-design.md)——視覺 token/元件/字階地基，不重定。
> - **GA4 地基（已鎖合約，唯讀）**：[`2026-07-09-P6-ga4-ingestion-foundation-design.md`](2026-07-09-P6-ga4-ingestion-foundation-design.md) §4 `silver.ga4_events`、§5.1 `gold_ga4_user_item_interactions`、§5.2 `gold_ga4_item_catalog`、§5.3 `gold_ga4_sessions`、§5.4 `gold_ga4_user_rfm`、§13 known-limits。
> - [P4 呈現層 design](2026-07-08-P4-presentation-layer-design.md) §3–4（匯出信封/absent 容忍）、[ga4-extension-crosscut](2026-07-09-ga4-extension-crosscut.md) EP-D（additive append 紀律）。
> **接地已由規劃者（Opus）完成骨架**；Fable 5 設計階段仍須**第一手 grep** ga-insight 取材碼與 GA4 地基合約補齊 file:line，版本敏感處 context7 查證。
> **本階段只出 spec，plan 延後。**

---

## 一句話目標

GA 分析支柱＝**取代 ga-insight、比它更完整、以「整個銷售漏斗」為核心章**的完整電商行為分析，讀 GA4 地基 Gold（唯讀）＋新增 `gold.gold_ga4_insight_*` additive marts →（既有 exporter DAG）→ `ga_insight_*.json` → 前端 `(ga)/` 純靜態頁群（`/ga` 首頁＋分析頁＋`/ga/ask` 問 AI 頁佔位）。**資料源＝公開 GA4 sample `bigquery-public-data.ga4_obfuscated_sample_ecommerce`**（非 area02，守隱私立場）。

## ⚠️ 靈魂原則：進化非複刻（crosscut §2.4 已鎖，本 brief 落實）

ga-insight 的五章弧（業績全貌→認識客群→找到問題→立刻行動→問 AI）、問句式標題、漏斗呈現＝**輸入與靈感，不是天花板、不是要複製的清單**。既然有 Fable 5，GA 分析要**比 ga-insight 更嚴謹、更完整**：更明確的漏斗流失/瓶頸公式、多模型歸因對照、更誠實的 AI-vs-程式逐區塊標註、更結構化的自我說明。**頁面不必同模板**——漏斗頁/KPI 頁/歸因頁各給最合適版面（Signal 決策 1 variety-with-coherence 授權內）。

## 接地：可取材素材（唯讀，碼不可抄 Streamlit/Plotly≠Next/Recharts；取的是分析邏輯與內容架構）

ga-insight `src/analytics/`（17 模組，第一手 grep 覆核清單）：`conversion.py`（**漏斗核心·取材重點**：`ConversionFunnel.analyze_funnel/calculate_drop_off/identify_bottlenecks(threshold)/get_sankey_data/get_recommendations`）、`attribution.py`（歸因多模型）、`rfm.py`、`predictive.py`（流失/LTV）、`cart_abandonment.py`、`market_basket.py`（共購）、`nes_model.py`、`anomaly_detector.py`、`comparative.py`、`product.py`、`traffic.py`、`recommender.py`、`sequence_nlp.py`、`semantic_search.py`、`ab_testing.py`、`feedback_store.py`。自我說明模式＝`src/components/ui_utils.py:23-52` `render_page_header` 五欄（crosscut §5 已升為集中 registry）。

## Fable 5 要收斂拍板的項目（crosscut §10「下放」欄＝以下清單；逐一給明確決定）

1. **章節弧與頁清單**：自設問題導向章節弧（可不同名、不必五章），**漏斗為核心章**（Fergus 定案）；產出每頁 `route`（`/ga/*` segment）、章節歸屬（＝sidebar navGroup label，回填 crosscut `pillars.ts` 的 `ga.navGroups`）、每頁版面型別（不必同模板）。
2. **漏斗頁（最重要，完整設計）**：逐步流失率＋瓶頸判定**明確公式**（取材 `conversion.py identify_bottlenecks` threshold 邏輯，重寫為平台端批次 SQL/Python）、Sankey/漏斗視覺（Recharts 重造）、drop-off 分解、（可選）分群/裝置維度切片。公式進 registry `formula` 欄可稽核。
3. **歸因頁**：多歸因模型對照（取材 `attribution.py`；明標各模型假設）。
4. **分群/LTV/流失**：取材 `rfm.py`/`predictive.py`；**與 P7 `/audience` 共源不重繪**（crosscut §4 鐵律：R×F heatmap、8 行為分群正本在 `/audience`；GA 支柱做 LTV 分佈/流失預測/lifecycle 轉移等**新分析**，以 `related` cross-link 互指）。預測類**補 ga-insight 沒有的模型版本標註＋訓練窗揭露**。
5. **v1 頁面組合取捨（completeness-first，但須 grounded）**：從其餘模組（`cart_abandonment`/`market_basket`/`nes_model`/`anomaly_detector`/`comparative`/`product`/`traffic`）挑哪些進 v1——**判準＝GA4 地基 Gold 能否支撐該分析**（能就做完整、不能就誠實不做或標降級，不硬撐薄訊號）。Fergus 令「功能完整優先」，傾向多做，但每頁都要真有資料支撐。
6. **GA 分析引擎與資料流**（crosscut §7.3 合約邊界內細設）：引擎 Python 套件落點（平台端、跑**既有 Airflow**不開第二排程）、`gold.gold_ga4_insight_*` marts 清單與欄位（additive、dbt tag `ga4_insight`、selectors.yml append 沿 EP-D）、`ga_insight_*.json` dataset 清單（P4 信封同構、exporter `datasets.py` additive）、MCP 工具（additive）。**不改地基 4 表與 P7 `dmp_*`**。
7. **每頁 registry 條目**（crosscut §5 schema）：`whyBuilt`（開發目的）/`whatItDoes`（功能做什麼怎麼用）硬性；`aiVsComputed` 逐區塊標（ga-insight 只口頭分區，我方升 schema 一級）；`related` cross-link 到 `/audience` 等。條目內容歸本支柱 plan 落地時填，本 spec 定其**結構與覆蓋清單**。
8. **每頁輕量「問 AI」摺疊區**（crosscut §6.3(a) 接縫）：定其位置與資料契約（讀 `ga_ask_showcase.json` `scope==='page:<pageId>'`），**graph 細設不在本 spec**（問 AI spec 的事），本 spec 只留接縫。

## 硬約束（違者作廢）

- **拓撲鐵律**：`(ga)/` 頁純靜態 export、build-time 讀 committed JSON，觸不到 k8s；真運算在平台端批次/離線。
- **只 additive**（EP-D）：不改 GA4 地基 4 表、不改 P7 `dmp_*`、dataset 前綴 `ga_insight_`、dbt tag `ga4_insight`。
- **進化非複刻**（§2.4）、**說明式 registry 阻擋級**（§5，缺 `whyBuilt`/`whatItDoes` = gate fail）、**AI-vs-程式誠實標**、**emoji→lucide**（Signal 驗收 #9）。
- **資料立場**：公開 GA4 sample，非 area02（守 area02 不進公開 repo）。
- **GA vs `/audience` 邊界**（§4）：同一張圖只在一個支柱有正本。

## Scope

- **in**：GA 支柱章節弧＋頁清單＋逐頁 IA/版面、漏斗/歸因/分群-LTV 等分析頁設計、GA 分析引擎套件＋`gold_ga4_insight_*` marts＋`ga_insight_*.json` datasets＋MCP 工具、每頁 registry 條目結構與覆蓋清單、每頁輕量問 AI 接縫、驗收（含 coverage gate 適用、absent 容忍）。
- **out**：問 AI graph/sub-agent/guardrail 細設（→問 AI spec）、GA4 地基改動、`/audience` 重繪、Signal token 重定。

## 產出

寫到 `docs/specs/2026-07-10-ga-pillar-design.md`；檔頭指向本 brief＋精確度契約＋crosscut。附「plan 期待查證點」與「本 spec 拍板 vs 下放（問 AI spec / plan）」對照。**不 git commit**（Opus 把關後處理）。完成回報：檔案路徑、關鍵拍板摘要、context7 查證項、給 Opus 覆核的風險點。
