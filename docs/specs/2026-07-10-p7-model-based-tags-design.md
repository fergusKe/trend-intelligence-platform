# P7 模型化標籤 — K-Means 消費分群（additive 疊加規則層）— Design（Fable 5 產出）

> **狀態**：design 完成，待規劃者把關後寫 implementation plan。
> **上游**：[`2026-07-10-p7-model-based-tags-brief.md`](2026-07-10-p7-model-based-tags-brief.md)（交辦單）＋ repo [`CLAUDE.md`](../../CLAUDE.md) §Fable 5 design 精確度契約（8 條逐條自檢於 §14）＋ **[P7 DMP design](2026-07-09-P7-dmp-design.md)（主複用對象，唯讀、只 additive 疊加）**：§3.3 規則 `value_tier`、§3.5 `gold.dmp_user_profiles` 寬表（穩定合約、只准加欄）、§3.5b 摘要 marts、§3.6 dbt 測試、§4.4 `dmp_refresh` DAG、§5.2b DSL 欄位註冊表、§7 匯出/前端 ＋ [P2 ML verticals design](2026-07-08-P2-ml-verticals-design.md)（登錄範式對照，本 spec 走更輕 rung）＋ [統一作品集 crosscut](2026-07-10-unified-portfolio-crosscut-design.md) §5（說明式 registry 阻擋級）。
> **一句話**：在 P7 規則式畫像上 **additive 疊一層資料驅動 K-Means 消費分群**（sklearn CPU、秒級、in-DAG）：對**購買者**以寬表既有 RFM/engagement 特徵分群（沿課程「分群＋事後規則貼語意」兩段式），產出 `value_cluster` 與可解釋群輪廓，**與規則式 `value_tier` 並存對照、不取代**——展示「規則分層 vs 資料驅動分群」的方法論對比。
> **誠實邊界（本 spec 存在前提）**：GA4 公開 sample **無 PII、無評論文字**→課程的性別 Naive Bayes（`Gender.scala`）／情感 SVM（`Sentiment.scala`）**做不了，明拒**（無特徵源無標籤，硬做＝造假）；唯一 grounded 可做的模型化標籤＝以 RFM/互動能量做 K-Means。K-Means 群＝消費特徵的自然聚類、**非真人分眾**（裝置級 ID，P7 known-limit 1）；群語意標籤是**事後可解釋映射**；規則 vs 模型是**互補視角非優劣**。
> **P7 尚無實碼**：本 spec 鎖 **P7 design 合約**（§3.3/§3.5/§3.5b/§3.6/§4.4/§5.2b/§7 逐錨第一手讀畢）；P7 plan/實作若對錨點做落地校準，本 spec 落點跟隨 P7 為上游（§12 plan 查證點 1）。
> **版本查證日**：2026-07-10（sklearn KMeans/StandardScaler/silhouette_score/inertia_ 以 context7 對 scikit-learn stable 官方文件查證；scikit-learn 1.7.x 為現行 stable 線）。

---

## 0. 版本 pin 表

| 元件 | 版本 | 查證方式 | 備註 |
|---|---|---|---|
| scikit-learn | **1.7.1**（`scikit-learn==1.7.1`） | context7（/scikit-learn stable，2026-07-10）；PyPI 最終確認列 §12-5 | **本 spec 唯一新依賴**；裝進既有 Airflow image（沿 P7 加 clickhouse-connect 的同款姿態，Dockerfile +1 行） |
| KMeans 參數 | `KMeans(n_clusters=k, init="k-means++", n_init=10, random_state=42)` | context7 查證：`random_state` int＝重現性、`n_init` 自 1.4 預設 `'auto'` 會隨版本變——**顯式 pin `n_init=10`** 保跨版本決定性 | `inertia_` 屬性、`labels_`、`cluster_centers_` 皆官方 API 面 |
| 前處理 | `sklearn.preprocessing.StandardScaler`（`with_mean=True, with_std=True`）＋ `numpy.log1p` | context7（`make_pipeline(StandardScaler(), KMeans)` 官方範例形狀） | 課程 `Spending.scala:32` 用 `withMean=false` 是 Spark 稀疏向量限制非統計選擇——我方稠密資料用完整標準化，README 註記差異 |
| 選 k 指標 | `sklearn.metrics.silhouette_score`（`sample_size=10000, random_state=42` 當 n>10k）＋ `inertia_`（elbow 佐證） | context7（silhouette 官方用法＋silhouette analysis 範例） | silhouette 全量 O(n²)，抽樣＋seed＝決定性 |
| 交叉一致指標 | `sklearn.metrics.adjusted_rand_score` | sklearn 標準 API | 規則 value_tier × 模型 cluster 的單一一致性數字（§7） |
| 其餘全沿 P7 §0 | Airflow/dbt/ClickHouse/clickhouse-connect/Next.js/Recharts 零升級 | 沿用 | 本 spec 零新基建元件、零新 image |

**刻意不引入**：Spark / SparkML（課程載體；我方數十萬列 × 4 特徵是 sklearn CPU 秒級負載，Spark＝常駐叢集違一工一具與輕量原則）；ES（課程圈選載體；P7 已用 ClickHouse/PG，brief 鎖排除）；MLflow（本模型不掛——理由見 §6 拍板）；XGBoost / 任何監督式模型（無標籤工程，本 spec 不含，列進化方向）；joblib model artifact（KMeans 的完整 artifact＝centroids＋scaler 參數，JSONB 一列即全量可重現，pickle 零增值）。

---

## 1. 八項拍板總表（brief〈要收斂拍板的項目〉逐項；細節見對應節）

| # | 項目 | 決定 | 一句理由 |
|---|---|---|---|
| 1 | 特徵/前處理/母體 | **4 特徵**＝`recency_days`/`frequency_orders`/`log1p(monetary_total)`/`log1p(engagement_score)`（全取自 §3.5 寬表既有欄，取**原始值非 NTILE 分數**）；StandardScaler 完整標準化；母體＝**只購買者 `is_purchaser`**，未購者 `value_cluster` NULL（同規則層姿態） | RFM 三軸沿課程錨＋engagement 是我方獨有衰減能量軸（讓交叉表有戲）；聚 NTILE 分數＝重新發現規則層，違「資料驅動互補視角」本旨（§3） |
| 2 | 選 k ＋模型 | **k-scan k∈{2..6}**：silhouette（抽樣 10k、seed 42）主判準 argmax、同分取小 k；inertia 曲線留 elbow 佐證；`KMeans(k, "k-means++", n_init=10, random_state=42)`；**k 凍結進登錄表**，之後重訓沿用（rescan 走 Airflow Variable 開關）；訓練＝**dmp_refresh DAG 內 PythonOperator（Airflow image ＋ sklearn）**，秒級 CPU，不動 M4 界線 | 決定性、右尺寸；k>6 對 4 特徵消費分群不可解釋且命名表封閉（§4） |
| 3 | 與規則 value_tier 關係 | **並存不取代（合約句）**：`value_tier` 規則層原定義原值零動；`value_cluster` additive 加欄；前端/匯出/admin 同時呈現兩者＋交叉表；敘事固定＝「規則分層給穩定可解釋門檻、K-Means 給資料驅動自然群落，兩視角互補對照使用者結構」 | brief 硬約束；方法論對比即賣點（§3/§7） |
| 4 | additive 落點 | 真源＝新表 `gold.dmp_value_cluster_assignments`（Python loader-owns-DDL）；寬表 `gold.dmp_user_profiles` **加欄** `value_cluster smallint NULL`/`value_cluster_label text NULL`（kmeans task 於 dbt run 後 ALTER+UPDATE 物化投影，dbt model 檔零編輯）；`dmp_segment_summary` **加 dimension 值 `'value_cluster'`**（union 分支，粒度零改）；新輪廓表 `gold.dmp_cluster_profiles`＋交叉表 `gold.dmp_cluster_rule_crosstab`（dbt，tag `dmp_model`） | 規則層 dbt 檔一字不動＝最強 only-additive；brief 明定三落點全落實（§5） |
| 5 | 模型登錄/重訓 | **輕量 rung：DB 登錄表 `gold.dmp_kmeans_registry`（centroids/scaler 參數 JSONB＝完整 artifact）＋門檻閘（silhouette 地板＋不退步閘），不掛 MLflow**；重訓＝`dmp_refresh` 每日 task 內建（靜態資料→決定性收斂，重跑同版不膨脹） | [[project_ml_serving_cost_posture]] 正典 rung；免 P7→P2 runtime 耦合（MLflow server 是 P2 資產）；KMeans artifact 本質＝幾十個數字（§6） |
| 6 | 評估/誠實 | silhouette＋inertia＋**ARI（value_tier×cluster 調整蘭德指數）**實跑填數進登錄表與 Explainer（不宣稱）；**交叉表 mart＋前端熱圖如實呈現**（一致/分歧處＝方法論講點，不挑好看）；三句誠實標語固定進 registry caveats（非真人分眾/明拒性別情感/互補非優劣） | grounding 鐵律（§7） |
| 7 | 前端/匯出/MCP/DSL | `/audience` 頁 additive 加「消費分群（K-Means）」區塊（群輪廓 BarChart＋表、value_tier×cluster CSS grid 熱圖、方法論 Explainer 收合）；匯出 additive ＋2 檔（`dmp_clusters.json`/`dmp_cluster_crosstab.json`）＋ `dmp_segments.json` 天然多 dimension 列；MCP ＋1 工具 `get_value_clusters`；admin DSL 註冊表 additive ＋2 欄位；**零 live 依賴**（前端只讀匯出 JSON）；說明式 registry 條目補齊（阻擋級）；icon 一律 lucide 無 emoji | 拓撲鐵律＋crosscut §5 gate（§8） |
| 8 | 守門/交付/ADR | pytest（決定性 golden/命名規則/閘門/母體斷言）＋ dbt 測試（cluster iff purchaser/守恆/accepted values）＋ `make dmp-verify` +3 檢查＋ ADR-lite 3 條＋「不改資產清單」逐列（§9/§10/§11） | 每步可測（§9–11） |

---

## 2. 總體形狀（對 P7 §2 的 additive 差分；未列＝零改動）

```
[P7 既有，不動] dmp_refresh：check_upstream → dbt_run_dmp → dbt_test_dmp ─┐
                                                                          ▼
[本 spec 插入 3 task]                                    kmeans_fit_assign（PythonOperator）
   讀 gold.dmp_user_profiles（WHERE is_purchaser）4 特徵 → 前處理 → （首跑/rescan：k-scan）
   → KMeans fit_predict → 門檻閘 → 寫 gold.dmp_kmeans_registry（版本/指標/centroids）
   → 寫 gold.dmp_value_cluster_assignments（DELETE+INSERT 冪等）
   → ALTER+UPDATE gold.dmp_user_profiles 兩投影欄
                                                                          ▼
                                       dbt_run_dmp_model（selector dmp_model_marts：
                                         dmp_cluster_profiles ＋ dmp_cluster_rule_crosstab
                                         ＋ 重建 dmp_segment_summary 含 value_cluster 分支）
                                                                          ▼
                                       dbt_test_dmp_model（DQ gate）
                                                                          ▼
[P7 既有，順序不變] sync_events → sync_profiles（鏡像自動含新 2 欄）→ materialize_custom_tags
[匯出/前端] export_frontend_data additive ＋2 dataset → /audience additive 區塊（讀靜態 JSON）
```

- **DAG 形狀**：`dmp_refresh` 6 task 鏈 → 9 task 鏈（線性，插點固定在 `dbt_test_dmp` 之後、`sync_events` 之前——CH 鏡像與匯出永遠看到本輪新鮮分群）。`schedule`/`catchup`/`max_active_runs`/`dagrun_timeout=45m` 全部不變（新增負載＝秒～十秒級）。
- **新檔案佈局**（additive）：

```
ml/dmp/src/dmp/
    kmeans_features.py    # FEATURE_SPEC 常數（4 欄、log1p 標記、序即向量序）＋特徵抽取 SQL（WHERE is_purchaser）
    kmeans_train.py       # k-scan / fit / 門檻閘 / 登錄表寫入 / assignments 寫入 / 寬表 ALTER+UPDATE
    kmeans_naming.py      # 事後語意命名（k∈2..6 名稱表、rank/tiebreak 純函式）
ml/dmp/tests/…            # §9 pytest
orchestration/airflow/Dockerfile          # += scikit-learn==1.7.1（僅此一行）
orchestration/airflow/dags/dmp_refresh.py # += 3 task（上圖）
lakehouse/dbt/models/marts/dmp_model/{_dmp_model_schema.yml, _dmp_model_sources.yml,
    dmp_cluster_profiles.sql, dmp_cluster_rule_crosstab.sql}   # tag:dmp_model
lakehouse/dbt/models/marts/dmp/dmp_segment_summary.sql   # ★唯一編輯的既有 dbt 檔：additive union 分支（brief 授權落點）
lakehouse/dbt/selectors.yml               # += selector dmp_model_marts（tag:dmp_model ＋ dmp_segment_summary）
lakehouse/dbt/tests/assert_dmp_cluster_*.sql              # §9
ml/dmp/src/dmp/ch.py                      # dmp.user_profiles DDL += 2 欄（additive）
admin/src/lib/dsl/fields.ts               # += 2 DSL 欄位（§5.2b 自身合約：「加欄＝改此表＋測試」）
orchestration/exporter/…/datasets.py      # += 2 dataset 條目
frontend/src/app/audience/…               # additive 區塊 ＋ registry blocks（§8）
mcp-server/server.py                      # += get_value_clusters
scripts/verify-dmp.sh                     # += 3 檢查（§11）
```

---

## 3. 拍板 1＋3：特徵、前處理、母體、並存合約

### 3.1 特徵集（4 欄，全部第一手錨在 P7 §3.5 寬表既有欄）

| 向量序 | 特徵 | 寬表源欄（§3.5） | 轉換 | 取的語意 |
|---|---|---|---|---|
| 0 | recency_days | `recency_days`（購買者非 NULL） | 原值 | R 軸（近度） |
| 1 | frequency_orders | `frequency_orders` | 原值（小整數，多為 1，log 無意義） | F 軸（頻次） |
| 2 | monetary_total | `monetary_total` | **`log1p`**（重尾金額，未壓尾則 K-Means 被大戶單極拉走） | M 軸（金額） |
| 3 | engagement_score | `engagement_score`（not_null 合約） | **`log1p`**（Σ 衰減能量同屬重尾和） | 我方獨有衰減互動能量軸——規則 value_tier 完全沒用到它，是「模型看到規則看不到的東西」的來源 |

再過 `StandardScaler(with_mean=True, with_std=True)`。**FEATURE_SPEC**（`kmeans_features.py` 內 ordered 常數：`(name, source_column, log1p: bool)`）＝向量序單一真源，序列化存進登錄表列（§6），任何讀端斷言一致。

- **取原始值、不取 NTILE 分數**（拍板核心理由）：`r/f/m_score` 是規則層產物（五分位＋tiebreak）；拿分數聚類＝在規則格點上重新發現規則層，交叉表必然假性一致，違「資料驅動互補視角」的存在理由。課程 `Spending.scala:22-24` 也是聚 r/f/m 原值。
- **明確排除**（開放問題收斂，不下推）：`aov`＝`monetary_total/frequency_orders` 的決定函數（共線、變相雙倍加權 M 軸）；`distinct_items_purchased`＝與 frequency 高相關且品項多樣性軸另有 profiles 欄呈現——特徵維持 4 維，群輪廓才可解釋。`preferred_category` 等類別欄不進（K-Means 歐氏空間不吃類別，one-hot 會稀釋數值軸）。
- **母體＝購買者**：抽取 SQL 固定 `WHERE is_purchaser`（pytest 斷言 SQL 含此謂詞，§9）；購買者的 4 特徵在寬表合約下皆非 NULL（`recency_days`/`monetary_total` 購買者有值、`frequency_orders`≥1、`engagement_score` not_null）——**零插補**，出現 NULL＝上游合約破損直接 fail。未購者 `value_cluster`/`value_cluster_label` NULL，與規則層 `value_tier` NULL 同姿態。

### 3.2 並存合約（拍板 3，合約句照 brief 原文採納）

- `value_tier`（規則）**保留原定義原值**：P7 §3.3 四級 `rfm_total` 分段一字不改、§3.1 RFM/§3.2 八分群一字不改。
- `value_cluster`（模型）additive 加欄；前端/匯出/admin 同時呈現兩者。
- 固定敘事（進 dbt description 與前端 Explainer，單一真源在 `_dmp_model_schema.yml`）：「規則分層給穩定可解釋的門檻（同分數永遠同級、可向業務背書）；K-Means 給資料驅動的自然群落（群邊界由資料密度決定、能發現規則沒設想的結構）。兩者對照看使用者結構，**非模型比規則好**。」

---

## 4. 拍板 2：選 k、模型、決定性、執行位置

### 4.1 k-scan（首跑或 rescan 時執行；k 凍結進登錄表）

```python
for k in range(2, 7):                                    # k ∈ {2..6}
    km = KMeans(n_clusters=k, init="k-means++", n_init=10, random_state=42).fit(X_scaled)
    sil = silhouette_score(X_scaled, km.labels_,
                           sample_size=10000, random_state=42) if len(X_scaled) > 10000 \
          else silhouette_score(X_scaled, km.labels_)
    scan.append({"k": k, "silhouette": round(sil, 4), "inertia": round(km.inertia_, 2)})
chosen_k = max(scan, key=lambda r: (r["silhouette"], -r["k"]))["k"]   # argmax；同分取小 k
```

- **上界 6 的理由**：4 特徵消費分群超過 6 群人眼不可解釋，且 §4.2 命名表封閉（k∈2..6 全枚舉）——掃描域與命名域同界，無「掃出沒名字的 k」的洞。**預設傾向 k=4**（對齊課程 `Spending.scala:44` 的 4 群與規則層 4 級、交叉表 4×4 最好講），但**judge 是 silhouette 不是偏好**——實跑若非 4 就用實跑值，Explainer 如實寫（§12-3）。
- **k 凍結**：chosen_k 與 `k_scan` 全曲線存登錄表列；後續每日重訓沿用 active 模型的 k（防群 id/語意天天洗牌）。重新掃描＝Airflow Variable `dmp_kmeans_force_rescan=true`（預設 false）＋下輪 DAG 生效後自動復位語意（task 讀後即重置為 false，冪等）。
- **決定性**：同資料＋`random_state=42`＋`n_init=10` 顯式＋sklearn 版本 pin＝labels 位元級可重放（pytest golden 斷言，§9）。抽樣 silhouette 同 seed 42 決定性。

### 4.2 事後語意標籤（課程兩段式的第二段；`kmeans_naming.py` 純函式）

沿 `Spending.scala:48-74`「分群後對每群算 avg → 規則貼語意」兩段式，但**閾值制改秩次制**（課程 `avg_m>=400` 的絕對閾值綁死它的資料幣值，我方採群間相對秩次——決定性且對任何幣值/量綱成立）：

1. 對每群算 `avg_monetary`（原值空間，非 scaled）；
2. **rank 排序**：`avg_monetary` 降冪；tiebreak `avg_frequency_orders` 降冪 → `avg_engagement_score` 降冪 → cluster index 升冪（全鏈決定性）；
3. 依 rank 取封閉名稱表：

| k | 名稱表（rank 0 → k−1） |
|---|---|
| 2 | 高消費群、低消費群 |
| 3 | 高消費群、中消費群、低消費群 |
| 4 | 高消費群、中高消費群、中低消費群、低消費群 |
| 5 | 高消費群、中高消費群、中消費群、中低消費群、低消費群 |
| 6 | 高消費群、中高消費群、中消費群、中低消費群、低消費群、極低消費群 |

- `value_cluster`＝KMeans 原生群號（0..k−1，模型真源）；`value_cluster_label`＝上表映射（呈現層語意）。兩欄都落地——群號給程式、標籤給人。
- **誠實標示（進 schema description 與 Explainer，固定文案）**：「群是資料驅動的自然聚類；『高消費群』等語意標籤是**事後以群均值排序貼上的可解釋映射**，不是模型輸出、也不是真人分眾。」

### 4.3 執行位置（拍板）

**`dmp_refresh` DAG 內 PythonOperator、跑在既有 Airflow image（+`scikit-learn==1.7.1`）**。淘汰替代案：KPO＋P2 `ml-batch` image（造成 P7→P2 image/部署耦合，P2 未部署則 P7 斷；且 ml-batch 為 torch/transformers 重 image，殺雞牛刀）；host `dvc repro` 當排程路徑（P2 §1③ 紀律：排程重訓不跑 DVC；且本模型秒級 CPU 無 M4 需求——**不觸 M4 重算力界線**，該原則管微調/LLM/embedding，不管 4 維 KMeans）。

---

## 5. 拍板 4：additive 落點（資料契約欄位級）

### 5.1 `gold.dmp_value_cluster_assignments`（★分群真源；Python loader-owns-DDL，沿 P1 loader 慣例；dbt 以 source 讀）

| 欄位 | 型別 | 定義 |
|---|---|---|
| user_pseudo_id | text PK | 粒度鍵；只含購買者 |
| value_cluster | smallint not null | KMeans 群號 0..k−1 |
| value_cluster_label | text not null | §4.2 映射 |
| distance_to_centroid | numeric | scaled 空間到所屬中心歐氏距離，round 4（可解釋性：邊緣 vs 核心成員） |
| model_version | text not null | FK 語意 → registry |
| assigned_at | timestamptz not null | 同批常數 |

寫入＝`DELETE FROM … ; INSERT`（單交易，冪等）。**dbt 不管理此表**（`_dmp_model_sources.yml` 宣告 source `dmp_model.dmp_value_cluster_assignments`——source 是唯讀宣告，不違 P7「dbt 只管 staging/gold 轉換」邊界）。

### 5.2 `gold.dmp_user_profiles` 加欄（brief 明定落點；機制＝投影）

kmeans task 在 dbt_run_dmp **之後**執行：`ALTER TABLE gold.dmp_user_profiles ADD COLUMN IF NOT EXISTS value_cluster smallint; ADD COLUMN IF NOT EXISTS value_cluster_label text;` ＋ `UPDATE … FROM assignments`（未購者留 NULL）。

- **為何不改 dbt model SQL 去 JOIN**（開放問題收斂）：P7 `dmp_user_profiles.sql` 是規則層正本，table materialization 每輪重建；若在其中 LEFT JOIN assignments，首輪拿到空/前輪分群（訓練需要本輪 `engagement_score` → 雞生蛋），且動了規則層檔案。投影法讓**規則層 dbt 檔零編輯**＝only-additive 最強證明；代價（known-limit §13-2）：DAG 外手動 `dbt run` 重建寬表會暫時抹掉兩投影欄，直到下輪 kmeans task 重投影——assignments 表是耐久真源，投影一個 task 距離內可復原。
- 既有欄語意/粒度/NULL 姿態零變動；§3.6 既有 dbt 測試全數不動照跑。

### 5.3 `gold.dmp_cluster_profiles`（群輪廓；dbt model，tag `dmp_model`，materialized table，schema gold）

| 欄位 | 型別 | 定義 |
|---|---|---|
| value_cluster | smallint | 群號（unique+not_null） |
| value_cluster_label | text | 語意標籤 |
| users_count | bigint | 群人數 |
| pct_of_purchasers | numeric | round 4 |
| avg_recency_days / avg_frequency_orders / avg_monetary / avg_engagement_score | numeric | 原值空間群均值，round 2/2/2/4（＝§4.2 命名的輸入，表本身就是「標籤為什麼叫這名」的證據） |
| median_monetary | numeric | round 2（重尾誠實：均值旁給中位數） |
| model_version / k / silhouette / inertia / ari_vs_value_tier | text / smallint / numeric / numeric / numeric | 模型級指標（每列同值、≤6 列的刻意反正規化——匯出信封平鋪慣例） |
| data_anchor_date | date | 錨點自述（沿 P7 姿態） |

SQL＝assignments source JOIN `ref('dmp_user_profiles')`（特徵原值）＋ registry source（指標欄）。

### 5.4 `gold.dmp_cluster_rule_crosstab`（規則×模型交叉表；dbt model，tag `dmp_model`）

粒度 `(value_tier, value_cluster)`（≤4×6=24 列）：`value_tier text`、`value_cluster smallint`、`value_cluster_label text`、`users_count bigint`、`pct_of_tier numeric`（該 tier 內佔比，round 4）、`data_anchor_date`。源＝profiles（value_tier）JOIN assignments。**如實輸出全部格子**，一致（對角優勢）與分歧（如「白金級但落在中低消費群」＝高 rfm_total 但 engagement 低的裝置）都是講點。

### 5.5 `gold.dmp_segment_summary` 加 dimension 值（brief 明定；粒度 `(dimension,name)` 零改）

`dmp_segment_summary.sql` **additive union 一個分支**：`dimension='value_cluster'`、`name=value_cluster_label`、其餘欄（users_count/pct_of_purchasers/avg_recency_days/avg_frequency_orders/avg_monetary/monetary_total/data_anchor_date）對 assignments JOIN profiles 同構聚合。既有兩 dimension 分支一字不動。此模型加入 `dmp_model_marts` selector 於 kmeans 後重建（§2 DAG 圖）——它在 tag:dmp 首輪也照舊建（union 分支對空 assignments 得 0 列，合法），第二次重建收斂本輪值；表結構/既有列零變。P7 §3.6 `assert_dmp_segment_totals` 既有斷言（兩規則 dimension 各總和＝購買者數）**不動**；新 dimension 的守恆由**新增測試**管（§9，additive 不改舊測試檔）。

### 5.6 `gold.dmp_kmeans_registry`（模型登錄表；Python loader-owns-DDL）——schema 見 §6。

### 5.7 ClickHouse 鏡像（additive）

`ch.py` 的 `dmp.user_profiles` DDL **加 2 欄**：`value_cluster Nullable(UInt8)`、`value_cluster_label LowCardinality(Nullable(String))`（沿 P7 §4.3 型別對映法）。`sync_profiles` 欄位清單 += 2（task 順序保證 sync 時欄已存在，§2）。若 CH 表已建於加欄前：`ALTER TABLE dmp.user_profiles ADD COLUMN IF NOT EXISTS …`（ch.py DDL 常數旁附 migration 語句，冪等）。事件表/自訂標籤表零動。

### 5.8 DSL 欄位註冊表（additive；走 §5.2b 自身合約「加欄＝改此表＋測試」）

`fields.ts` += `value_cluster`（number；match, range, exists）、`value_cluster_label`（string；match, exists）→ 圈選建構器即刻可用「模型分群」當圈選維度（例：`value_tier='白金級' AND value_cluster_label='低消費群'` 圈出兩視角分歧人群——模型層的實戰價值落點）。compiler 零改（既有型別分支涵蓋）；黃金測試 += 2 fixtures。admin 預覽 `distributions` additive 加第四鍵 `value_cluster_label`（JSON 加鍵＝P4 additive 慣例；sample 欄位清單不動）。

---

## 6. 拍板 5：模型登錄與重訓（輕量 rung）

### 6.1 登錄表 `gold.dmp_kmeans_registry`

| 欄位 | 型別 | 定義 |
|---|---|---|
| model_version | text PK | `kmeans-v<N>`（N 遞增） |
| trained_at | timestamptz | |
| k | smallint | 凍結群數 |
| feature_spec | jsonb | FEATURE_SPEC 序列化（欄名/序/log1p 標記）——讀端斷言用 |
| scaler_params | jsonb | `{"mean": […], "scale": […]}`（4 維） |
| centroids | jsonb | k×4（scaled 空間）＋每群原值空間均值——**與 scaler_params 合計＝完整可重現 artifact** |
| label_map | jsonb | `{cluster: label}`（§4.2 產物凍結） |
| silhouette / silhouette_sample_size / inertia | numeric / int / numeric | 實跑填數 |
| ari_vs_value_tier | numeric | `adjusted_rand_score(value_tier, value_cluster)` over 購買者（規則×模型一致性單一數字） |
| k_scan | jsonb | §4.1 全曲線（elbow/silhouette 佐證，前端 Explainer 引用） |
| n_samples | bigint | 訓練母體數（＝購買者數） |
| sklearn_version | text | 執行期 `sklearn.__version__` |
| is_active | boolean | 唯一 active（partial unique index `WHERE is_active`） |
| activated_at | timestamptz | |

### 6.2 拍板：**DB 表＋門檻閘，不掛 MLflow**（brief 傾向 MLflow「但可討論輕量版」——本 spec 選輕量版並負舉證）

1. **[[project_ml_serving_cost_posture]] 正典 rung**：模型登錄＝DB 表＋門檻閘＋cron，非 MLflow-heavy——本案無 serving 端點、無 staging/prod 晉升生命週期、無人工晉升需求，MLflow 的三個價值面全空轉。
2. **免跨階段 runtime 耦合**：MLflow server 是 P2 資產（`ml` ns）；P7 design 刻意自含（PG+CH+admin）。掛 MLflow＝`dmp_refresh` 每日跑掛在 P2 部署狀態上，違 P7 的自含邊界。
3. **artifact 本質**：KMeans 完整可重現 artifact＝4 維 scaler 參數＋k×4 centroids＋seed——JSONB 一列即全量，且 admin/前端可直接查表展示 centroids（pickle 反而封死可讀性）。
4. **反向誠實**：若進化方向做 XGBoost 流失預測（監督式、真訓練生命週期），**那個**模型照 P2 慣例走 MLflow/DVC/alias——本拍板限 KMeans，ADR 寫明界線。

### 6.3 門檻閘與重訓語意（每日 `dmp_refresh` 內建）

```
fit → metrics → 指紋比對（feature_spec+k+centroids round 6 的 hash）
  ├─ 與 active 模型指紋相同（靜態資料常態）→ 不寫新版、沿用 active model_version，僅重寫 assignments（冪等）
  └─ 不同（backfill 推進/上游變動）→ 過閘才落地：
       ①silhouette ≥ 0.15（絕對地板，預設傾向值，首跑實測後校準凍結，§12-4）
       ②若有 active：silhouette ≥ active.silhouette − 0.02（不退步閘，沿 P2 gate 精神）
       過閘 → 新版 insert、舊版 is_active=false、assignments/投影/marts 用新版
       不過閘 → 保留 active 版與其 assignments、task 標 warning、Prometheus 可見（§6.4）、DAG 不 fail
             （分群是加值層非主線，fail-open-with-alert；主線 DQ gate 姿態不變）
```

靜態資料集誠實（known-limit §13-4）：收斂後每日重訓＝決定性 no-op（指紋相同分支），**這是決定性展示不是 drift 故事**——真 drift 敘事在 P2a，本層不假裝。GA4 回放期間 profiles 逐日長大→會產生 v1→vN 版本序列（登錄表留史，恰好是「模型隨資料收斂」的敘事素材）。

### 6.4 觀測（沿 P7 §8 姿態，零新元件）：postgres-exporter 自訂查詢 ConfigMap additive ＋2 條——`dmp_kmeans_silhouette`（active 列）、`dmp_kmeans_gate_failed`（最近 24h 未過閘次數，源＝registry 寫入時同步記的 gate log 欄位……收斂：gate 拒絕也 insert 一列 `is_active=false` 帶 `gate_passed boolean` 欄，exporter 查它；registry 加欄 `gate_passed boolean not null default true`）。不加 PrometheusRule/dashboard（沿 P7 §8 判斷）。

---

## 7. 拍板 6：評估與誠實呈現

- **指標全實跑填數**：silhouette（主）、inertia（elbow 佐證）、ARI（規則×模型一致性）——設計期**不預告數值**，登錄表/匯出/Explainer 引用執行期真值（P5「對真 artifact 做」界線同款）。
- **交叉表如實**：§5.4 mart 全格子輸出；前端熱圖不做任何「隱藏小格」處理；分歧格是方法論講點（Explainer 固定引導句：「對角集中＝兩視角大體一致；離對角格＝模型看到規則門檻切不出的結構（如高分低互動）」）。
- **三句誠實標語**（固定文案，單一真源 `_dmp_model_schema.yml` description，前端 registry caveats 引用）：①「K-Means 群是消費特徵的自然聚類，不是真人分眾（裝置級匿名 ID）」②「GA4 公開 sample 無 PII、無評論文字——性別/情感等模型化標籤**沒有特徵源，本平台明確不做**（硬做即造假）」③「規則分層與模型分群是互補視角，非優劣關係」。

---

## 8. 拍板 7：前端 / 匯出 / MCP / 說明式 registry（additive；拓撲鐵律）

### 8.1 匯出（`datasets.py` additive ＋2 條目；P7 既有 3 檔與 P4 11 檔零改動）

| 檔案 | 來源表 | 形狀 | 列數 |
|---|---|---|---|
| `dmp_clusters.json` | `gold.dmp_cluster_profiles` | 全欄平鋪 | ≤6 |
| `dmp_cluster_crosstab.json` | `gold.dmp_cluster_rule_crosstab` | 全欄平鋪 | ≤24 |

`dmp_segments.json` **天然**多出 dimension=`'value_cluster'` 列（加列非加欄，粒度合約不變；既有讀端都按 dimension 過濾，P7 §7.2 已如此）。表未建→`meta.json` `status:"absent"` 既有容忍路徑。信封/驗證/穩定性政策全沿 P4 §3–4。**匯出只讀 Postgres**，公開站對 CH/模型 runtime 零依賴。

### 8.2 `/audience` 頁 additive 區塊「消費分群（K-Means）」（置於既有價值分層區塊之後——兩視角相鄰對照）

| 子區塊 | 視覺 | 資料 |
|---|---|---|
| 群輪廓 | Recharts BarChart（users_count）＋逐群表（label/人數/佔比/avg_recency/avg_frequency/avg_monetary/median_monetary/avg_engagement） | dmp_clusters.json |
| 規則×模型交叉 | **CSS grid heatmap**（value_tier 4 行 × cluster ≤6 欄，users_count 上色、格內 pct_of_tier——沿 P7 R×F 熱圖同款自製，不加庫） | dmp_cluster_crosstab.json |
| 模型卡 | k / silhouette / ARI / model_version / trained_at 小卡（lucide `Boxes` icon；**全站無 emoji**） | dmp_clusters.json 模型級欄 |

**說明式三層**（沿 P7 §7.3 元件與 crosscut §5 registry，**阻擋級**）：
- `ChartCaption`：熱圖「顏色＝人數；行＝規則分層、欄＝模型分群；離對角＝兩視角分歧」；群輪廓圖「標籤是事後映射，依群均消費額排序命名」。
- `Explainer`（方法論類，`defaultOpen=false`）〈K-Means 怎麼分群〉：4 特徵/log1p/標準化/seed 42/k-scan 曲線（引 k_scan 實數）/silhouette 語意/命名規則。
- 既有〈資料誠實聲明〉Explainer **additive 追加** §7 三句標語（原文零刪改）。
- **registry 條目**（crosscut §5.2 schema）：audience 頁 entry `blocks` += `audience.value-clusters`、`audience.cluster-crosstab`（各含 `whyBuilt`/`whatItDoes` ≥20 字、`formula`（衰減與標準化一行式）、`dataSource`（`gold.dmp_cluster_profiles` 等如實）、`caveats`（三句標語）、`aiVsComputed:'computed'` ＋ note「分群由 K-Means 計算；語意標籤為事後規則映射；無 LLM 參與」）。coverage gate（crosscut §5.5）自動強制——漏填＝CI 紅。
- admin `/audiences` Explainer additive 一句（新增兩個可圈選欄位的語意）＋ admin registry 條目同步（admin.ts）。

### 8.3 MCP（additive ＋1 工具，沿 P4 §7 模式）：`get_value_clusters`——讀公開 `dmp_clusters.json`＋`dmp_cluster_crosstab.json`（同一邏輯主題一工具雙檔，docstring 寫明含誠實標語），不碰叢集。

---

## 9. 拍板 8（守門一）：測試策略

| 層 | 測試 |
|---|---|
| `ml/dmp` pytest | **決定性 golden**：固定合成購買者 fixture（seed 42）→ labels/centroids/命名快照逐位元一致，跑兩次同結果；**命名純函式**：rank/三段 tiebreak/k∈2..6 名稱表全枚舉、構造同 avg_monetary 群驗 tiebreak 鏈；**母體斷言**：特徵 SQL 含 `WHERE is_purchaser`（golden 字串）＋特徵含 NULL 時 raise；**閘門**：地板拒/不退步拒/過閘落地/拒後 active 不變＋`gate_passed=false` 列寫入；**指紋**：同資料重跑不寫新版；**FEATURE_SPEC**：與 registry `feature_spec` 序一致斷言；**投影**：ALTER 冪等（IF NOT EXISTS）＋ UPDATE 後未購者 NULL；`ch.py` DDL golden += 2 欄 |
| dbt（新增 singular，既有測試檔零改） | `assert_dmp_cluster_iff_purchaser.sql`（寬表：`is_purchaser =（value_cluster IS NOT NULL）` 不成立→fail；鏡射既有 scores_iff_purchaser）；`assert_dmp_cluster_totals.sql`（cluster_profiles users_count 總和＝購買者數；segment_summary dimension='value_cluster' 總和＝購買者數）；`assert_dmp_crosstab_conservation.sql`（交叉表總和＝購買者數、格數 ≤24）；generic：cluster_profiles `value_cluster` unique+not_null、`value_cluster_label` accepted_values（§4.2 全名單）、寬表兩新欄 accepted 範圍（0..5 / 名單，容 NULL）——掛在 `_dmp_model_schema.yml`，由 `dbt_test_dmp_model` step 跑（不動既有 `dbt_test_dmp`） |
| DAG | DagBag import 零錯；9 task 線性鏈斷言（插點位置固定）；schedule/catchup/max_active_runs 不變守門 |
| admin vitest | fields.ts 2 新欄位黃金測試（value_cluster range SQL/label match SQL）＋注入樣本沿既有套路 |
| exporter/frontend | 2 新 dataset 條目 SQL 可解析（既有守門自動涵蓋）；`check-data.mjs` 自動涵蓋 2 新檔；coverage gate 強制 registry 條目（crosscut §5.5，阻擋級） |

---

## 10. 拍板 8（守門二）：ADR-lite（3 條，進 P5 `DECISIONS.md`）＋不改資產清單

**ADR**：
1. **模型化標籤＝additive 疊加非取代**：規則 value_tier 保留（穩定可解釋門檻），K-Means value_cluster 並存（資料驅動群落），交叉表/ARI 呈現互補與分歧——「規則 vs 模型」是方法論展示不是升級汰換。
2. **誠實邊界**：課程性別 NB/情感 SVM 在 GA4 公開 sample **無特徵源無標籤——明拒不做**（硬做＝造假）；K-Means 是此資料唯一 grounded 的模型化標籤；群語意標籤＝事後映射非模型輸出。
3. **輕量 rung**：sklearn CPU in-DAG（秒級、不引 Spark/ES/常駐算力）＋ DB 登錄表（centroids JSONB＝完整 artifact）＋門檻閘，不掛 MLflow（無 serving/晉升生命週期，掛了全空轉且造成 P7→P2 runtime 耦合）；未來監督式模型（XGBoost 流失）才走 P2 MLflow 慣例。

**逐列不改的既有資產**（only-additive 證明）：P7 §3.1 RFM 分箱 SQL／§3.2 八分群 CASE／§3.3 value_tier 分段（定義與值）／`dmp_user_profiles.sql` dbt 檔（一字不動；加欄走投影）／既有 §3.6 全部 dbt 測試檔／`dmp_segment_summary` 既有兩 dimension 分支與表結構／`dmp_rfm_grid`、`dmp_tag_coverage`／`dmp_refresh` 既有 6 task 的內容與相對順序／`dmp_only` selector／CH `dmp.ga4_events`、`dmp.user_custom_tags` DDL／DSL compiler／admin 4 頁既有功能／P4 11＋P7 3 既有匯出檔／前端既有 `/audience` 區塊／MCP 既有工具。**唯二編輯的既有檔**：`dmp_segment_summary.sql`（union 分支，brief 明文授權落點）與 `dmp_refresh.py`（插 task）；其餘全是新檔或 brief/自身合約明文授權的 additive 點（Airflow Dockerfile +1 行、ch.py DDL 加欄、fields.ts 加欄、datasets.py 加條目、exporter/verify 腳本追加）。

---

## 11. `make dmp-verify` 追加檢查（既有 10 項不動，+3）

| # | 檢查 | 預期 |
|---|---|---|
| 11 | 模型層落地 | registry 恰一列 `is_active`；assignments 列數＝購買者數；寬表 `value_cluster` 非 NULL 數＝購買者數且未購者全 NULL；cluster_profiles 列數＝k；silhouette/ARI 欄非 NULL |
| 12 | 決定性/冪等 | 重跑 `dmp_refresh` → active `model_version` 不變、assignments 逐列不變（count＋checksum）、registry 不多 active 列 |
| 13 | 匯出/交叉 | `latest/dmp_clusters.json`、`dmp_cluster_crosstab.json` 存在且 rows>0；`dmp_segments.json` 含 dimension='value_cluster' 列；crosstab users_count 總和＝購買者數；CH `user_profiles FINAL` 兩新欄非 NULL 數＝購買者數 |

---

## 12. plan 期待查證點（設計已收斂；以下為落地校準，皆帶預設傾向）

1. **P7 實作錨**：本 spec 綁 P7 design 合約；P7 plan 落地後對實碼校準——寬表實體欄名/`dmp_refresh` task_id/`dmp_only` selector 寫法/ch.py DDL 常數名/`fields.ts` 結構/datasets.py 條目形狀。預設傾向：P7 plan 照 design 落地、錨點原樣成立；若 P7 與本 spec 同一 plan 波次實作，直接按本 spec 落點一次建齊。
2. **特徵分佈實測**（購買者的 4 特徵分佈 SQL 一次）：確認 monetary/engagement 重尾（log1p 正當）；預設傾向成立；若 engagement 近常態，去掉其 log1p（FEATURE_SPEC 一行改動，機制/測試不變）。
3. **k-scan 實跑**：silhouette/inertia 曲線與 chosen_k 實數（預設傾向 k=4）；實數回填 registry/Explainer/README，**不改判準**。
4. **silhouette 地板校準**：預設 0.15；首跑實測後凍結（若實測 active 遠高於 0.15，地板上調至 active−0.05 量級並記 README；機制不變）。
5. **scikit-learn 1.7.1 相容**：對 Airflow image Python 版本 `uv pip compile` 一次定 lock（沿 P1 手法）；預設傾向相容；衝突則退 1.6.x 並記錄（API 面本 spec 只用穩定 API，無版本敏感用法）。
6. **交叉表/ARI 實數**：如實呈現，不挑格子；若 ARI 極高（>0.9，模型幾乎重現規則）或極低，皆為有效講點——Explainer 兩種話術都預備（「高一致＝規則門檻切在資料自然邊界附近」/「低一致＝engagement 軸帶出規則看不到的結構」）。
7. **backfill 期版本序列**：回放中每日新版是否過閘順暢（預設傾向：過；不過即 warning 可見，收斂後穩定）。

## 「本 spec 拍板 vs 下放」對照

| 已拍板（不再開） | 下放給 plan（僅校準/回填，機制不可改） |
|---|---|
| 特徵集 4 欄與排除清單、log1p 落點、StandardScaler、母體=購買者零插補 | engagement 是否留 log1p（§12-2，單旗標） |
| k-scan 域 {2..6}、silhouette 主判準＋同分取小、seed/n_init/init 全參數、k 凍結＋rescan 開關 | chosen_k 與曲線實數（§12-3） |
| 並存不取代合約句、固定敘事、三句誠實標語文案 | 無 |
| 五個落點全 schema（assignments/寬表投影/cluster_profiles/crosstab/segment_summary 分支）＋投影法選型＋CH 加欄＋DSL 加欄 | 對 P7 實碼錨的欄名校準（§12-1） |
| DB 登錄表 schema、不掛 MLflow、門檻閘結構（地板+不退步+指紋跳過）、fail-open-with-alert 姿態 | 地板數值凍結（§12-4） |
| DAG 插點與 9-task 順序、Airflow image +sklearn、匯出 2 檔、MCP 1 工具、前端區塊/registry blocks、驗收 +3 | sklearn lock（§12-5）、實跑數字回填 |

---

## 13. known-limits（誠實段）

1. **群語意標籤是事後映射**：K-Means 只輸出群號；「高消費群」是按群均值排序貼的名（§4.2），非模型判斷、非真人分眾（裝置級 ID，沿 P7 known-limit 1）。
2. **投影欄非 dbt 管理**：DAG 外手動 `dbt run` 重建寬表會暫時抹掉兩投影欄（下輪 kmeans task 重投影復原；assignments 表為耐久真源）——README 記載，verify #11 可偵測。
3. **silhouette 為抽樣值**（n>10k 時 sample_size=10000, seed 42）：決定性但非全量；登錄表存 sample_size 如實。
4. **靜態資料＝無真 drift**：收斂後重訓是決定性 no-op（指紋跳過），本層展示的是「登錄/閘門/可重現」工程面而非漂移故事（drift 敘事屬 P2a）；回放期的版本序列是真實的資料增長軌跡，如實留史。
5. **K-Means 本身的方法邊界**：歐氏球狀群假設、對前處理選擇敏感（log1p/標準化已明文拍板並記 Explainer）；4 特徵之外的行為結構（品類、時序）不在此模型視野——列進化方向，不宣稱「完整使用者理解」。
6. **明拒清單即能力邊界**：性別/情感/任何需 PII 或評論文字的標籤，在本資料集**永久做不了**（非「未來再做」——是資料本質限制），對外敘事一律如此陳述。

**進化方向**（v1 刻意不做）：XGBoost 流失預測（需標籤工程，走 P2 MLflow/DVC 慣例）；品類/時序特徵入群（sequence embedding）；分群→P6 推薦的 cluster-level 冷啟先驗（讀 `gold.dmp_value_cluster_assignments`，additive 鬆接縫同 P7 接縫 I 姿態）；GMM/HDBSCAN 對照實驗。

## 14. 精確度契約 8 條自檢

1 開放問題全收斂（§1 八拍板；僅存實查點皆帶預設傾向與判準，§12）✅ 2 版本具體＋context7（§0：sklearn 1.7.1、KMeans/StandardScaler/silhouette/inertia 官方 API 面查證、n_init 顯式 pin 的版本漂移理由）✅ 3 資料契約欄位級（§5.1/5.3/5.4/6.1 全欄型別鍵；寬表加欄與 CH 對映明列）✅ 4 部署/DAG 形狀具體（§2 佈局與 9-task 鏈、Dockerfile 行、selector、exporter/MCP/verify 落點）✅ 5 沿既有慣例（loader-owns-DDL、DELETE+INSERT 冪等、P4 匯出信封、P7 §7.3 說明元件、crosscut registry、postgres-exporter 姿態——各節點名）✅ 6 進化非複刻（§4.2 兩段式取秩次制替閾值制；§0/§10 明拒 Gender/Sentiment/Spark/ES/Hive 全套；取材界線散注於 §3/§4/§6）✅ 7 硬約束貫徹（only-additive §10 清單、一工一具零新基建、拓撲 §8 零 live 依賴、M4 界線不觸 §4.3、非互動零提問）✅ 8 每步可測（§9 三層測試＋§11 verify +3，決定性 golden 可實跑反例）✅

---

## 15. Opus 把關註記（PASS）

> 規劃者（Opus 4.8）覆核。**按風險比例把關**：本 spec 是低風險 additive KMeans（無「錯了就崩」的外部承重宣稱——sklearn KMeans 是標準 API，§0 context7 表＋`n_init=10` 顯式 pin 對抗 1.4 版 `'auto'` 漂移皆正確且與既有知識一致），故做五鐵律覆核＋裁定兩處 brief 偏離，**不另燒 context7 親查**（對比觀測性 Promtail→Alloy、aiops AlertmanagerConfig 那種若錯即破 additive/log 柱的承重宣稱才需獨立覆核；此處無等價項）。**判定 PASS，commit 進 trend repo（不加 footer）。**

### 15.1 兩處偏離 brief 的拍板裁定

1. **登錄選 DB 表非 MLflow（§6.2；agent 自報風險 6）**：**批准，且這是好判斷非漂移**。正中我方 durable 決策 [[project_ml_serving_cost_posture]]（模型登錄＝DB 表＋門檻閘＋cron，非 MLflow-heavy）——KMeans 無 serving 端點/無 staging→prod 晉升生命週期/artifact＝4 維 scaler＋k×4 centroids JSONB 一列即完整可重現，MLflow 三價值面全空轉且造成 P7→P2 runtime 耦合（違 P7 自含邊界）。ADR-3 已寫明界線（未來監督式 XGBoost 才走 P2 MLflow）。brief 原文即「傾向 MLflow **但可討論輕量版**」，agent 選輕量版並負四點舉證＝在授權範圍內的正確收斂。
2. **投影法 ALTER+UPDATE 而非 dbt LEFT JOIN（§5.2；agent 自報風險 1）**：**批准**。為達「規則層 dbt 檔一字不動」（only-additive 最強證明）＋避開「訓練需本輪 `engagement_score`→在寬表 JOIN 產生雞生蛋」循環。誠實標 known-limit（§13-2：DAG 外手動 `dbt run` 重建寬表暫抹兩投影欄，assignments 表為耐久真源、下輪 task 重投影復原）。**DAG 順序經核正確**：kmeans 投影 task 在 `dbt_run_dmp` 之後、`sync_profiles` 之前（§2 圖），故 CH 鏡像與匯出永遠看到本輪投影值；唯二編輯的既有檔（`dmp_segment_summary.sql` union 分支＝brief 明文授權；`dmp_refresh.py` 插 task）最小且適當。

### 15.2 規劃者五鐵律覆核

- **only-additive**：§10 逐列不改清單完整；規則層 dbt 檔零編輯（投影法）；新表/mart/欄/dimension 值全 net-new 或授權點。✅
- **grounding 誠實（本 spec 存在前提）**：性別 NB/情感 SVM **明拒**寫進 ADR-2＋known-limit-6，措辭「資料本質限制、永久做不了」非「未來再做」；K-Means 群語意標籤＝事後秩次映射非真人分眾，三句誠實標語落 schema description＋registry caveats＋Explainer 三處單一真源；指標實跑填數不預告；交叉表全格如實。✅
- **一工一具／輕量**：零引 Spark/ES/MLflow/XGBoost/joblib（§0 刻意不引入清單）；sklearn CPU in-DAG、Airflow image +1 行、零新基建。✅ 合 [[feedback_cost_conscious_architecture]] 校正版。
- **拓撲鐵律**：前端純靜態讀匯出 JSON（`dmp_clusters.json`/`crosstab`）、零 live 依賴；匯出只讀 Postgres 對 CH/模型 runtime 零依賴。✅
- **additive 有無誤改規則層／母體／決定性**：規則 value_tier 定義與值零動（並存不取代）；母體＝購買者（SQL 謂詞＋pytest golden＋dbt `assert_dmp_cluster_iff_purchaser`＋verify 四重守）；seed 42＋`n_init=10` 顯式＋版本 pin＝labels 位元級可重放。✅

**額外肯定的判斷力**：特徵取**原始值非 NTILE 分數**（聚規則層分數＝假性一致，違「資料驅動互補視角」本旨——精準洞察）；納 `engagement_score`＝「模型看到規則看不到的軸」讓交叉表有戲；命名**秩次制替課程絕對閾值制**（不綁死幣值）；`n_init` 顯式 pin 防版本漂移。皆為資深訊號。

### 15.3 判定

**PASS。** 八項全拍板、兩處偏離皆為正確收斂（DB 登錄正中成本姿態、投影法守 only-additive）、誠實邊界到位（永久明拒性別情感）、additive/拓撲/一工一具/決定性皆守。commit 進 trend repo（不加 footer）。**plan 佇列位置**：本 spec 依賴 P7 DMP plan（鎖其 design 合約、寬表/DAG/DSL 錨），plan 序在 **P7 plan 之後**（或與 P7 同波次一次建齊，§12-1）；與 P6 進階召回 spec 互不依賴（不同子系統，可平行）。
