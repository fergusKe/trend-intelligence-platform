# P7 模型化標籤 spec — brief（K-Means 消費分群升級規則式 value_tier；additive 疊加、不取代規則層）

> **精確度契約**：依 repo `CLAUDE.md`「Fable 5 design 精確度契約（8 條）」交辦；design 逐條自檢，**開放問題一律收斂成決定、不下推**。
> **緣起（Fergus 2026-07-10 令）**：評估兩門 DMP 課（「Spark+ES+ClickHouse 构建DMP用户画像」`Tags/{RFM,Spending,Gender}.scala`／「Spark+ElasticSearch 电商用户标签系统」）後，Fergus 選補「模型化標籤」——我方 P7 的 `value_tier` 目前是**規則式 `rfm_total` 分段**，spec 自標 KMeans/XGBoost 為進化方向未做（P7:37,576）。本 spec 補**K-Means 消費分群**當資料驅動的模型化標籤層。守 [[feedback_evolve_beyond_past_projects]]。
> **參考立場**：課程只參考標籤定義邏輯（RFM 分箱、K-Means 消費分群 `Spending.scala:18-87`、三級標籤分層、TF-IDF+時間衰減）；**碼不照抄、憑證勿引；整套 Hive/HBase/ES/Druid 常駐叢集全拒**（我方 Postgres/ClickHouse 輕量棧）。
> **關鍵接地約束（誠實）**：**GA4 公開 sample 無 PII、無評論文字**→課程的「性別 Naive Bayes（`Gender.scala`）／情感 SVM（`Sentiment.scala`）」在我方資料**做不了**（無標籤、無特徵源）；唯一 grounded 可做的模型化標籤＝**以 RFM/互動能量做 K-Means 分群**（我方有 monetary/frequency/recency/engagement）。本 spec 只做 K-Means，不假裝能做性別/情感（明拒並記 known-limit）。

---

## 框架上游（binding，不得抵觸）

- **[P7 DMP design](2026-07-09-P7-dmp-design.md)**（主複用對象，**唯讀、只 additive 疊加**）：§3.1 RFM（NTILE5，`r/f/m_score`、`rfm_total`）、§3.2 行為分群 8 值（規則 CASE）、**§3.3 `value_tier` 4 級（規則 `rfm_total` 分段——本 spec 的升級對象，但規則層保留不取代）**、§3.4 時間衰減行為標籤（`engagement_score` 衰減加權互動總能量、`preferred_category`）、**§3.5 `gold.dmp_user_profiles` 寬表**（粒度 `user_pseudo_id`，穩定合約，含 `r/f/m_score`/`rfm_total`/`behavior_segment`/`value_tier`/`monetary_total`/`aov`/`engagement_score`/`distinct_items_*`——K-Means 特徵源全在此）、§3.5b 摘要 marts（`dmp_segment_summary` dimension ∈ `('behavior_segment','value_tier')`）、匯出 `dmp_segments.json`/`dmp_rfm_grid.json`/`dmp_tag_coverage.json`＋前端 `/audience`。**本 spec＝additive 加一個 K-Means 分群欄與模型，不改 RFM/規則分群/規則 value_tier 的定義與值。**
- **[P2 ML verticals design](2026-07-08-P2-ml-verticals-design.md)**：MLflow registry alias/晉升閘範式、模型登錄＝DB 表+門檻閘非 MLflow-heavy（[[project_ml_serving_cost_posture]]：rung 低）；K-Means＝sklearn CPU 秒級、不觸 M4 重算力界。
- **NORTH_STAR**：一工一具（OLTP/Gold 只 Postgres、事件 OLAP 只 ClickHouse、**不引 ES**）、拓撲鐵律（前端讀匯出 JSON）、成本紅線不適用但輕量優先（[[feedback_cost_conscious_architecture]] 校正版：不為模型化而養重 infra）。

## 接地鐵律（grounding-first，違者作廢）

Fable 5 須**第一手 grep/讀**：
- **P7 §3.3 規則 `value_tier` 定義**、§3.5 `gold.dmp_user_profiles` 全欄（確認 K-Means 特徵源 `monetary_total`/`aov`/`frequency_orders`/`recency_days`/`engagement_score`/`distinct_items_*` 皆在寬表、additive 加欄的落點）、§3.5b 摘要 marts 與匯出面（additive 加 dimension/dataset 的落點）、§3.6 dbt 測試合約——證明「加 K-Means 欄 additive、不動規則層」可行，錨進 design。**P7 尚無實碼**→鎖 P7 design 合約（問 AI §0.3 誠實處理）。
- **課程取材**（唯讀、碼不照抄）：「Spark+ES+ClickHouse」`code/imocc-dmp-spark/src/main/scala/Tags/Spending.scala:18-87`（RFM 標準化→K-Means 分 4 群→依 avg(m) 規則切高/普通/低——**「K-Means 分群 + 事後規則貼標籤語意」的兩段式**值得參考）、`RFM.scala:16-140`（分箱/加權/切檔對照）、`dim_tags` 三級標籤分層 schema。**明確不取**：`Gender.scala`（NB 性別，我方無 PII）、`Sentiment.scala`（SVM 情感，我方無評論）、整套 Hive/HBase/ES/Druid infra、圈選 ES anti-pattern。
- **版本敏感處**（sklearn KMeans、分群數選擇 elbow/silhouette）用 context7。
**本階段只出 spec，plan 延後。**

---

## 一句話目標

P7 模型化標籤＝在既有規則式畫像上 **additive 疊一層資料驅動的 K-Means 消費分群**：以 `gold.dmp_user_profiles` 既有的 RFM/monetary/engagement 特徵對購買者跑 K-Means（沿課程「分群+事後規則貼語意」兩段式），產出 `value_cluster` 欄與可解釋的群輪廓，**與規則式 `value_tier` 並存對照**（不取代）——秀「規則分層 vs 資料驅動分群」的方法論對比，補上 P7 自標的進化方向。**誠實邊界：只做 GA4 sample 撐得起的 K-Means（有 monetary/engagement），不做性別/情感（無 PII/評論）。**

## Fable 5 要收斂拍板的項目（逐一給明確決定，不下推）

1. **K-Means 特徵與前處理**：拍板特徵集（傾向 RFM 三軸 `recency_days`/`frequency_orders`/`monetary_total` ＋ `engagement_score`／`distinct_items_purchased`——全取自 §3.5 寬表既有欄）、標準化（StandardScaler，沿課程 `Spending.scala` 對 RFM 標準化）、母體（**只購買者**，沿 P7 RFM 母體 `is_purchaser`；未購者 `value_cluster` NULL 同規則層姿態）。
2. **分群數與模型**：拍板 k 選擇法（elbow/silhouette 實跑校準，記入 spec 的實查點）、`KMeans(random_state=42)` 決定性、sklearn CPU（k8s KPO 或 host `dvc repro`，秒級）；**分群後事後貼語意標籤**（沿課程兩段式：對每群算 avg(monetary/frequency) → 決定性規則命名如「高價值群/成長群/流失風險群」，tiebreak 決定性）——明標「群是資料驅動、語意標籤是事後可解釋映射」。
3. **與規則式 value_tier 的關係（合約句）**：**並存不取代**——`value_tier`（規則）保留原定義原值；`value_cluster`（模型）additive 加欄；前端/匯出同時呈現兩者，敘事＝「規則分層給穩定可解釋門檻、K-Means 給資料驅動的自然群落，兩者對照看使用者結構」。明標非「模型比規則好」而是「兩種視角互補」。
4. **落點（additive-only）**：`gold.dmp_user_profiles` **additive 加欄** `value_cluster smallint NULL`＋`value_cluster_label text NULL`（穩定合約允加欄、既有欄零動）；摘要 mart `dmp_segment_summary` **additive 加 dimension 值 `'value_cluster'`**（沿 §3.5b 既有 `(dimension,name)` 粒度，零改表結構）；群輪廓另出 `gold.dmp_cluster_profiles(cluster smallint PK, label text, users_count bigint, avg_recency/avg_frequency/avg_monetary/avg_engagement numeric, …)` 供解釋。
5. **模型登錄與重訓（輕量，沿 [[project_ml_serving_cost_posture]]）**：拍板模型持久化（MLflow registry `dmp-value-kmeans` vs 更輕的「模型參數+cluster centroids 進 DB 表+門檻閘」——傾向 MLflow 沿 P6/P2 一致，但可討論輕量版）；重訓 DAG（沿 P7/dbt 排程慣例，`schedule=None` 靜態資料集）；分群穩定性誠實（靜態資料重訓應穩定，記註）。
6. **評估/誠實**：拍板分群品質指標（silhouette/inertia，實跑填數不宣稱）；**規則 vs K-Means 交叉表**（value_tier × value_cluster 的 confusion，展示兩視角一致/分歧處＝方法論講點）；誠實標「K-Means 群不是真人分眾、是消費特徵的自然聚類」「GA4 sample 無 PII 故不做性別/情感標籤」。
7. **前端/匯出/MCP（additive，拓撲鐵律）**：`/audience` 頁 additive 加「消費分群」區塊（群輪廓 + value_tier×cluster 對照，Recharts；說明式 registry `whyBuilt`/`whatItDoes` 阻擋級、emoji→lucide）；匯出 additive（`dmp_clusters.json` 或併入 `dmp_segments.json`）；MCP additive（`get_value_clusters`）；**零 live 依賴**（前端讀匯出 JSON）。
8. **守門/交付（additive）**：dbt/模型測試（K-Means 決定性 seed 斷言、cluster 數與 label 映射測試、additive 欄的 schema 相容測、母體=購買者斷言）；ArgoCD/DAG additive；ADR-lite（K-Means 補規則層非取代／不做性別情感的誠實理由／不引 ES/Spark）；**逐一標不改哪些既有資產**。

## 硬約束（違者作廢）

- **only-additive**：不改 P7 RFM/規則分群/規則 `value_tier` 的定義與值、不改 `dmp_user_profiles` 既有欄語意/粒度、不改既有摘要 mart 結構；K-Means 以 additive 加欄+加 dimension 值+新輪廓表落地。
- **誠實邊界（本 spec 存在的前提）**：只做 GA4 sample 撐得起的 K-Means（RFM/engagement 特徵）；**明拒性別 NB/情感 SVM**（無 PII/評論=無特徵無標籤，硬做=造假）；K-Means 群語意標籤是事後可解釋映射非真人分眾；規則 vs 模型是互補視角非優劣。
- **一工一具／輕量**：只 Postgres/ClickHouse（**不引 ES**——課程 ES 圈選是 anti-pattern，我方 §3 已用 ClickHouse/PG）、只 sklearn CPU（不引 Spark 常駐叢集）；模型登錄走輕量 rung（DB 表+門檻閘或 MLflow，不養重 infra）。
- **拓撲鐵律**：訓練/推論叢集或 host；前端純靜態讀匯出 JSON、零 live 依賴。
- **grounding/誠實**：不造假標籤、silhouette/inertia 實測填數、規則vs模型交叉表如實。**說明式 registry 阻擋級**；emoji→lucide。
- **成本紅線不適用**（portfolio）——但輕量優先（K-Means 是最便宜的模型化，不為它拉重 infra）。

## context7 必查清單

- **sklearn KMeans**（`n_clusters`/`random_state`/`n_init`、StandardScaler pipeline、silhouette_score/inertia_ 選 k）。

## Scope

- **in**：K-Means 特徵/前處理/選 k/模型、事後語意標籤、與規則 value_tier 並存對照、additive 落點（加欄/加 dimension/輪廓表）、模型登錄/重訓、評估/交叉表、前端/匯出/MCP/守門 additive。
- **out**：改 P7 規則層定義/既有欄、性別/情感/任何需 PII 或評論的標籤、引 ES/Spark 常駐、XGBoost 流失預測（不同 gap、需標籤工程，本 spec 不含——列進化方向）、改前端 live 依賴。

## 產出

寫到 `docs/specs/2026-07-10-p7-model-based-tags-design.md`；檔頭指向本 brief＋精確度契約＋P7 DMP design＋P2。附「plan 期待查證點」（P7 實作 import 錨、K-Means 特徵實測分佈、選 k 校準、value_tier×cluster 交叉）與「本 spec 拍板 vs 下放」對照。**不 git commit**（Opus 把關後處理）。完成回報：檔案路徑、8 項拍板摘要、context7/grep 查證項（尤其 P7 dmp_user_profiles 合約錨、K-Means 特徵源在寬表、課程兩段式取材）、給 Opus 覆核的風險點（尤其：additive 有無誤改規則層、有無硬做性別/情感、有無引 ES/Spark、K-Means 語意是否誠實標示、母體是否=購買者）。
