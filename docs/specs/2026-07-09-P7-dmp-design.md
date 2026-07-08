# P7 使用者畫像 / DMP（資料管理平台）— Design（Fable 5 產出）

> **狀態**：design 完成，待寫 implementation plan。
> **上游**：[`2026-07-09-P7-dmp-brief.md`](2026-07-09-P7-dmp-brief.md) + [`../architecture/NORTH_STAR.md`](../architecture/NORTH_STAR.md)「GA4 第二真來源 ＋ 三工具翻案」段 + **GA4 地基（已鎖合約）**[`2026-07-09-P6-ga4-ingestion-foundation-design.md`](2026-07-09-P6-ga4-ingestion-foundation-design.md)（§4 `silver.ga4_events`、§5.2 `gold_ga4_item_catalog`、§5.3 `gold_ga4_sessions`、§5.4 `gold_ga4_user_rfm`、§13 known-limits）+ [`2026-07-08-P4-presentation-layer-design.md`](2026-07-08-P4-presentation-layer-design.md) §3–4（匯出合約）+ [`2026-07-08-P1-data-pipeline-design.md`](2026-07-08-P1-data-pipeline-design.md)（namespace/DAG/loader/dbt 慣例）+ [`2026-07-08-P0-platform-foundation-design.md`](2026-07-08-P0-platform-foundation-design.md)（GitOps/CI/secret 慣例）。brief 已鎖定決策 1–9 全部沿用，未翻案。
> **定位**：把 GA4 真使用者資料做成**可被行銷操作的資產**——標籤體系（Postgres/dbt）→ ClickHouse 事件 OLAP → 人群圈選 DSL → 叢集內 admin → Vercel 靜態展示頁。**純 additive**：不改地基四表合約、不改 P4 既有 11 檔匯出、不碰 YouTube/PTT 資產。
> **版本查證日**：2026-07-09（ClickHouse server 對 Docker Hub、clickhouse-connect 對 PyPI、@clickhouse/client 與 pg 對 npm 當日查證；MergeTree/ReplacingMergeTree/分區/CLICKHOUSE_* env 用法對 ClickHouse 官方文件（context7）查證；其餘沿用 P1/P4 已查證 pin）。

---

## 0. 版本 pin 表

| 元件 | 版本 | 查證方式 | 備註 |
|---|---|---|---|
| ClickHouse server | **`clickhouse/clickhouse-server:25.8.28.1`** | Docker Hub（2026-07-09） | **本 spec 唯一新基建元件**；25.8 = LTS 線（26.x 為短期 stable，portfolio 選 LTS 敘事正確） |
| clickhouse-connect（Python） | **1.4.2** | PyPI（2026-07-09） | Airflow 同步 task 用（HTTP 介面）；裝進 Airflow image |
| @clickhouse/client（Node） | **1.23.1** | npm（2026-07-09） | admin route handler 查 CH 用（官方 JS client） |
| pg（Node） | **8.22.0** | npm（2026-07-09） | admin 讀寫 Postgres |
| Next.js | 16.2.x（沿 P4 §0 pin） | 沿用 | admin 用 `output:'standalone'`（叢集內 server runtime）；公開前端仍 `output:'export'` |
| Recharts | 3.3.0（沿 P4 §0） | 沿用 | 前端 `/audience` 頁圖表 |
| Airflow chart / dbt-postgres / PostgreSQL | 沿 P1 §0（1.22.0 / 1.10.2 / 16.14） | 沿用 | 零升級 |

**刻意不引入**：Altinity clickhouse-operator（單機一顆 CH 用 operator = 過度工程，operator 的價值在多分片/複本叢集生命週期，我方明示不做叢集）；`clickhouse-driver`（native TCP 協定客戶端——HTTP 介面的 clickhouse-connect 是官方主推且夠用，一工一具內不開兩條協定）；ES / amis（brief 已鎖排除）；Debezium / Kafka Connect CDC（靜態資料集無 CDC 需求，§4 同步拍板批次）；任何 Node ORM（admin SQL 面積小，`pg` 裸用 + 參數化查詢即可）。

---

## 1. 開放問題收斂（8 題全拍板，皆照 brief 傾向）

| # | 開放問題 | 決定 | 一句理由 |
|---|---|---|---|
| 1 | ClickHouse 部署形狀 | **單機 1 replica ＋ PVC 10Gi，載體用 StatefulSet**（照 brief「單機＋PVC」傾向收斂；載體從 Deployment 改 StatefulSet 是**沿 P1 `lakehouse-postgres`/`lakehouse-minio` 既有慣例**——有狀態儲存一律 StatefulSet＋volumeClaimTemplate，傾向的核心「單機、不叢集、不用 operator」不變） | portfolio 規模；ADR（§4.1）誠實註記「示範欄式 OLAP 能力非叢集運維」 |
| 2 | 同步機制 | **Airflow 批次載入**（`dmp_refresh` DAG 內 PythonOperator ＋ clickhouse-connect；事件表按 `event_date` 分區「DROP PARTITION ＋ 重灌」冪等增量，詳 §4.4） | 靜態資料集無 CDC 需求；一工一具不引 Debezium |
| 3 | RFM 分箱 | **五分位 NTILE(5)，三軸皆同，決定性 tiebreak `user_pseudo_id`**——逐字對照 ga-insight `rfm.py:60-62` 的 `qcut(rank(method='first'))` 語意（rank-first = 同分強制打散） | 傳統、可解釋、與對照範本同款；同值跨箱列 known-limit（§13-4） |
| 4 | 行為分群數與命名 | **照抄 ga-insight 8 分群＋4 價值級**（名稱、規則、判斷順序逐條對照，§3.2/§3.3 有完整對照表） | 招募方認得的標準體系；規則 cascade 順序即語意，不改 |
| 5 | DSL 表達力 | **match / range / exists ＋ and/or 巢狀（深度 ≤3、單層條件 ≤20）**，作用域 = 使用者畫像欄位＋自訂標籤；**事件級條件不進 v1 DSL**（事件 OLAP 力道由 admin「事件洞察」罐頭查詢＋預覽的漏斗富化承擔，§5.1 邊界說明），列進化方向 | 涵蓋 90% 圈選需求；不做圖靈完備 DSL |
| 6 | 標籤時間衰減 | **指數衰減 `w = 0.5^(Δdays / half_life)`，half_life = 14 天**（dbt var 單一真源），Δdays 一律錨 `data_anchor_date` 非 `now()` | 半衰期直觀可解釋；靜態資料集誠實（同地基 recency 姿態） |
| 7 | admin 載體 | **Next.js 16.2 `output:'standalone'`，獨立 app `admin/`，叢集內 Deployment（`apps` ns）**；與 Vercel 靜態前端是**兩個 app**：前端零 runtime 零 secret 打不到 k8s，admin 有 server runtime、持 PG/CH 憑證、只在叢集內（port-forward 存取） | 技術棧一致（同 Next.js 心智模型）；ExplainerSection 概念直接複用 |
| 8 | 價值分層 v1 | **規則式**（RFM 總分 3–15 分四段）；KMeans/XGBoost 列進化方向（若做，走 P2 慣例：M4 host 訓練＋MLflow/DVC＋Registry alias） | 簡單可解釋；分箱即分層，v1 不養模型 |

---

## 2. 總體形狀

### 資料流

```
[地基（已建，不動）] silver.ga4_events ＋ gold_ga4_user_rfm / gold_ga4_sessions / gold_ga4_item_catalog
        │
        │  dmp_refresh DAG（§4.4，@daily 04:00 UTC）
        │  ① dbt run --selector dmp_only（tag:dmp 標籤 marts，§3）
        ▼
[標籤層·Postgres] gold.dmp_user_profiles（寬表畫像=系統標籤正本）
                  ＋ gold.dmp_segment_summary / dmp_rfm_grid / dmp_tag_coverage（匯出用摘要）
        │
        │  ② sync_events / ③ sync_profiles / ④ materialize_custom_tags（clickhouse-connect）
        ▼
[OLAP·ClickHouse] dmp.ga4_events（事件鏡像）＋ dmp.user_profiles ＋ dmp.user_custom_tags（§4.3）
        ▲                                    │
        │ 標籤/人群 CRUD（Postgres dmp schema）│ DSL→SQL 秒級預覽 / 罐頭 OLAP
[admin·叢集內 Next.js]（§6）◄────────────────┘
        
[前端·Vercel 靜態]（§7）：gold.dmp_* 摘要 → 既有 export_frontend_data DAG（additive ＋3 檔）
                          → 靜態 JSON → /audience 頁（三層說明式 UI）——不碰 ClickHouse
```

**兩條鐵律的落點**：①前端匯出路徑**只讀 Postgres 摘要 marts**，對 ClickHouse 零依賴（CH 掛了不影響公開站）；②ClickHouse 與 admin 是叢集內能力，佐證走 §9（負載測試＋截圖/GIF＋MCP additive 工具讀匯出 JSON）。

### 新增檔案佈局（全 additive；未列 = 不動）

```
ml/dmp/                              # NORTH_STAR P7 目錄合約；純 Python 套件（裝進 Airflow image）
    pyproject.toml
    src/dmp/
        ch.py            # clickhouse-connect client 工廠（env 憑證）＋ CH DDL 常數（§4.3，DDL 由本檔持有）
        sync_events.py   # silver.ga4_events(PG) → dmp.ga4_events：watermark 增量＋DROP PARTITION 冪等（§4.4）
        sync_profiles.py # gold.dmp_user_profiles → dmp.user_profiles（ReplacingMergeTree 全量 upsert）
        custom_tags.py   # 讀 dmp.tag_definitions → 執行 stored SQL（readonly=1）→ 寫回 PG＋CH 會員表（§5.4）
        amplify.py       # ×50 合成放大表建置（負載測試佐證用，明確標 synthetic，§9）
    tests/               # §11 單元測試
admin/                               # 叢集內 Next.js admin（§6；獨立 app，與 frontend/ 平行）
    Dockerfile           # node:22-slim 多階段，output:'standalone'
    k8s/                 # Deployment + Service + kustomization.yaml（ArgoCD app dmp-admin 的 source path；CI bump image tag 於此）
    src/app/{page.tsx, tags/, audiences/, olap/, api/...}
    src/lib/{dsl/schema.ts, dsl/fields.ts, dsl/compiler.ts, ch.ts, pg.ts}   # DSL 單一實作處（§5）
    db/init.sql          # dmp schema 中繼表冪等 DDL（admin 啟動時執行，§6）
    tests/               # vitest：compiler 黃金測試（§11）
orchestration/airflow/
    Dockerfile           # ＋ dmp 套件 ＋ clickhouse-connect==1.4.2（僅此改動）
    dags/dmp_refresh.py  # §4.4
lakehouse/dbt/
    models/marts/dmp/{_dmp_schema.yml, dmp_user_profiles.sql, dmp_segment_summary.sql,
                      dmp_rfm_grid.sql, dmp_tag_coverage.sql}          # tag:dmp（§3）
    selectors.yml        # default 排除清單 ＋ tag:dmp；新增 selector dmp_only（冪等 additive，同 P6 §6 接縫寫法）
    tests/assert_dmp_*.sql（§3.6 清單）
lakehouse/clickhouse/k8s/            # StatefulSet + Service + config ConfigMap（§4.2）
platform/argocd/apps/{clickhouse.yaml, dmp-admin.yaml}    # wave 3 / wave 7（§2 下表）
orchestration/exporter/…/datasets.py # additive ＋3 個 dataset 條目（§7.1）
frontend/src/app/audience/page.tsx   # 第 9 頁（§7.2）
frontend/src/components/explain/{InfoTooltip,ChartCaption,Explainer}.tsx   # 三層說明元件（§7.3）
mcp-server/server.py                 # additive ＋2 工具（§9）
.github/workflows/admin-ci.yml       # 新 workflow（鏡像 P0 hello-ci 模式；paths: admin/**）
Makefile                             # += dmp-secrets / dmp-init-db / dmp-verify / dmp-bench
scripts/{verify-dmp.sh, bench-dmp.sh}
```

**CI 面**：`airflow-ci` 的 paths **additive 加一行 `ml/dmp/**`**（dmp 套件裝進 Airflow image）；`dbt-ci` 天然涵蓋 dmp models；`admin-ci` 是唯一新 workflow（build → GHCR → bump image tag，照 P0 hello 模式）。ClickHouse 用官方 image，**零自建 image**。

### Namespace 與 sync-wave（接續 P1 的 3–6）

| wave | Application | namespace | 內容 |
|---|---|---|---|
| 3 | clickhouse | `data` | StatefulSet＋Service＋config ConfigMap（與 lakehouse-postgres/minio 同層儲存底座） |
| 7 | dmp-admin | `apps` | admin Deployment＋Service（依賴 wave 3 CH ＋ wave 3 PG，排最後） |

k8s 資源名合約（沿 P1 表尾 additive）：CH StatefulSet＋Service = `dmp-clickhouse`（`data` ns），叢集內位址 **`http://dmp-clickhouse.data.svc:8123`**（HTTP 介面；全設計唯一 CH endpoint 字面值）；admin Deployment＋Service = `dmp-admin`（`apps` ns，ClusterIP :3000）。syncPolicy 沿 P0 標準（automated＋prune＋selfHeal＋CreateNamespace＋retry）。

---

## 3. 標籤體系（P7 造；地基只出度量——接縫 F）

全部落在 dbt `models/marts/dmp/`，**tag `dmp`**、table materialization、schema `gold`（沿 P6 GA4 marts 先例：走既有 `generate_schema_name` 與 default privileges，零新權限管道）。只 `ref()` GA4 域資產（`stg_ga4_events`、`gold_ga4_user_rfm`、`gold_ga4_sessions`、`gold_ga4_item_catalog`），不觸 YouTube/PTT。**穩定性政策同 P1 §6a**：`dmp_user_profiles` 是對 P6（接縫 I）、admin、匯出層的介面承諾，只准加欄。

### 3.1 RFM 分箱（源 → 分數）

- **母體**：`gold_ga4_user_rfm` 中 `orders_count >= 1` 的**購買者**。未購使用者不進 RFM 分箱（R/M 無意義——`recency_days`/`monetary_total` 為 NULL/0），但**仍進畫像寬表**（行為標籤照算），前端與 admin 誠實呈現「購買者 ≈ 少數，RFM 分群只覆蓋購買者」（覆蓋率數字由 `dmp_tag_coverage` 出）。
- **分箱**（dbt SQL，逐字對照 ga-insight `rfm.py:60-62` 的 `qcut(rank(method='first'))` 語意）：

```sql
r_score = 6 - NTILE(5) OVER (ORDER BY recency_days ASC,  user_pseudo_id)   -- 越近 5 分
f_score =     NTILE(5) OVER (ORDER BY orders_count ASC,  user_pseudo_id)   -- 越多 5 分
m_score =     NTILE(5) OVER (ORDER BY monetary_total ASC, user_pseudo_id)  -- 越高 5 分
rfm_total = r_score + f_score + m_score                                     -- 3–15
```

`user_pseudo_id` tiebreak = `rank(method='first')` 的決定性等價物（同分強制打散、重跑結果位元級一致）。同值可能跨箱：known-limit §13-4，與範本同款、非 bug。

### 3.2 行為分群（8 種；CASE cascade 順序即語意，照 ga-insight `rfm.py:88-121` 原順序）

| 序 | 分群 | 規則（依序短路） | 特徵一句話（= dbt description / 前端 Explainer 定義表素材） |
|---|---|---|---|
| 1 | VIP 客戶 | r≥4 AND f≥4 AND m≥4 | 近期消費、高頻次、高金額的完美客戶 |
| 2 | 忠誠客戶 | r≥3 AND f≥4 | 頻繁購買的熟客，黏著度高 |
| 3 | 大額客戶 | m≥4 AND f≥3 | 久久買一次，但一出手就是大單 |
| 4 | 新客戶 | r≥4 AND f=1 | 剛完成首次購買的新朋友 |
| 5 | 潛力客戶 | r≥3 AND m≥3 | 近期有消費且金額不錯，可培養成 VIP |
| 6 | 需要挽回 | r≤2 AND f≥3 | 過去常買但最近不見了，需緊急喚回 |
| 7 | 即將流失 | r≤2 AND f≤2 | 購買頻率低且很久沒來，流失風險高 |
| 8 | 休眠客戶 | ELSE | 長期無互動的沉睡用戶 |

### 3.3 價值等級（4 級；`rfm_total` 分段，照 ga-insight 05 頁定義表）

| 等級 | rfm_total | 語意 |
|---|---|---|
| 白金級 | 13–15 | 各項指標皆頂尖 |
| 黃金級 | 10–12 | 表現優異，穩定貢獻 |
| 白銀級 | 7–9 | 普通或剛起步 |
| 銅級 | 3–6 | 表現較弱或新購 |

### 3.4 行為標籤與時間衰減（未購者也覆蓋；源 = `gold_ga4_sessions`＋`stg_ga4_events`＋`gold_ga4_item_catalog`）

- **衰減函式**（dbt vars 單一真源，`dbt_project.yml`：`dmp_half_life_days: 14`、`dmp_event_weights: {view_item: 1, add_to_cart: 3, begin_checkout: 5, purchase: 10}`）：

  `w(event) = weight[event_name] × 0.5 ^ ((data_anchor_date − event_date) / half_life_days)`

  Δdays 一律錨 **`data_anchor_date`**（取自 `gold_ga4_user_rfm.data_anchor_date`，全表常數）——靜態資料集誠實：錨 `now()` 會讓全部權重塌成 ~0（資料距今五年）。「近期行為權重高」的語意是**相對觀測窗尾端**，Explainer 如實敘述。
- **類別偏好**（接縫 G）：事件列的 `item_id` JOIN `gold_ga4_item_catalog` 取**正典 `item_category`**（目錄的 last-value 取法消化了觀測窗內類別改名飄移；不直接用事件列上的類別快照），`preferred_category = argmax_category Σ w(event)`，同分 tiebreak 類別名字典序（決定性）。
- **session 行為欄**（接縫 E 誠實）：一律從 `gold_ga4_sessions` 衍生，**語意 = 漏斗活躍 session 的行為**（純瀏覽 session 不在源內、地基 §13-3）；欄位命名與 description 都帶 `funnel_` 前綴或註明，不假裝全 session 覆蓋。

### 3.5 `gold.dmp_user_profiles` schema（★ 系統標籤正本；粒度 `user_pseudo_id`，穩定合約）

> **description（Explainer 素材）**：裝置級使用者畫像寬表：每列 = 一個匿名裝置（`user_pseudo_id`）的 RFM 分數、行為分群、價值等級與行為標籤。**這是「裝置畫像」不是「真人身分」**——GA4 sample 的 ID 是裝置級匿名（地基 §13-4），跨裝置同人無法縫合，如實敘述。RFM 分數/分群/等級只對購買者有值（未購者為 NULL）。

| 欄位 | 型別 | 定義 |
|---|---|---|
| user_pseudo_id | text | 粒度鍵（unique + not_null） |
| is_purchaser | boolean | `orders_count >= 1` |
| recency_days / frequency_orders / monetary_total / aov | bigint / bigint / numeric / numeric | 直通 `gold_ga4_user_rfm`（`orders_count` 改名 `frequency_orders` 貼 RFM 語意；未購者 recency/aov NULL） |
| r_score / f_score / m_score | smallint（nullable） | §3.1 五分位；未購者 NULL |
| rfm_total | smallint（nullable） | r+f+m |
| behavior_segment | text（nullable） | §3.2 八值之一；未購者 NULL |
| value_tier | text（nullable） | §3.3 四值之一；未購者 NULL |
| sessions_count / active_days | bigint | 直通 `gold_ga4_user_rfm` |
| first_seen_date / last_seen_date | date | 直通 |
| last_active_days | bigint | `data_anchor_date − last_seen_date`（任一漏斗事件；未購者也有值） |
| funnel_stage_max | text | `'purchase' > 'checkout' > 'cart' > 'view'` 最深觸達（從各階段 events 計數推） |
| has_cart_abandon | boolean | `cart_events > 0 AND purchase_events = 0` |
| funnel_sessions_count | bigint | `gold_ga4_sessions` 該 user 列數（**漏斗活躍 session 數**，接縫 E 命名誠實） |
| avg_funnel_session_depth | numeric | avg(`funnel_events_count`) over 該 user 的漏斗 session，round 2 |
| distinct_items_viewed / distinct_items_purchased | bigint | 直通 `gold_ga4_user_rfm` |
| preferred_category | text（nullable） | §3.4 衰減加權 argmax；全 NULL 類別者為 NULL |
| preferred_category_score | numeric（nullable） | 該類別的 Σw，round 4 |
| engagement_score | numeric | Σ 全事件 w（§3.4 公式），round 4——衰減加權互動總能量 |
| primary_device_category / primary_geo_country | text（nullable） | 事件列眾數（同數 tiebreak 字典序，決定性）——圈選常用維度 |
| data_anchor_date | date | 錨點自述欄（同地基 §5.4 姿態） |

### 3.5b 匯出用摘要 marts（前端/匯出唯一讀取面；前端不碰明細）

| 表 | 粒度 | 欄位 |
|---|---|---|
| `gold.dmp_segment_summary` | `(dimension, name)`；dimension ∈ `('behavior_segment','value_tier')` | users_count、pct_of_purchasers（round 4）、avg_recency_days、avg_frequency_orders、avg_monetary（round 2）、monetary_total、data_anchor_date |
| `gold.dmp_rfm_grid` | `(r_score, f_score)`（≤25 格） | users_count、avg_monetary、monetary_total——R×F 熱圖用（M 以色階外的數字呈現） |
| `gold.dmp_tag_coverage` | `tag_key`（固定枚舉列） | users_count、coverage_pct（分母 = 全使用者）、denominator。tag_key 固定清單：`purchaser` / `cart_abandoner` / `multi_session`（funnel_sessions_count≥2）/ `deep_browser`（avg_funnel_session_depth≥5）/ `has_preferred_category` / `reached_view` / `reached_cart` / `reached_checkout` / `reached_purchase` |

### 3.6 dbt 測試合約（tag:dmp 全列）

**generic**：`dmp_user_profiles.user_pseudo_id` unique＋not_null；`behavior_segment` accepted_values 八值（容 NULL）；`value_tier` accepted_values 四值（容 NULL）；`data_anchor_date`/`engagement_score` not_null。
**singular（沿 P1 自寫慣例，不引 dbt_utils）**：
- `assert_dmp_scores_iff_purchaser.sql`：`is_purchaser = (r_score IS NOT NULL)` 不成立、或分數落 1–5 之外 → fail
- `assert_dmp_segment_totals.sql`：`dmp_segment_summary` 兩個 dimension 的 users_count 總和 ≠ 購買者數 → fail
- `assert_dmp_rfm_grid_conservation.sql`：grid users_count 總和 ≠ 購買者數、或格數 > 25 → fail
- `assert_dmp_profiles_conservation.sql`：profiles 列數 ≠ `gold_ga4_user_rfm` 列數 → fail（畫像不掉人）
- `assert_dmp_decay_sanity.sql`：`engagement_score <= 0` 或 `preferred_category_score < 0` 出列 → fail

---

## 4. ClickHouse 事件 OLAP 層

### 4.1 ADR（誠實段——照 NORTH_STAR 三工具翻案表定調，逐句落實）

- **加它做什麼**：GA4 事件流**互動式欄式 OLAP**——人群圈選 DSL 的秒級查詢後端＋漏斗/留存/標籤交叉即席分析。
- **解決什麼 P1–P5 做不到的**：Postgres 是 OLTP＋Gold 聚合引擎（row store、非向量化欄式掃描）；對事件明細做即席聚合（任意維度組合、無預聚合表可用）是欄式引擎的正典職務。
- **為何不用替代**：擴 Postgres（BRIN/物化視圖）= 為每種切片預建聚合，失去「即席」本質；DuckDB 是嵌入式庫、無常駐服務可 demo（NORTH_STAR 刻意省略清單同理）；ES 違一工一具（brief 鎖定）。
- **誠實護欄（必寫，NORTH_STAR 已定調）**：**我方用的是 ClickHouse 的欄式 OLAP 正典用途，非 Yandex Metrica 那種十億級 RoaringBitmap 圈人**——本資料集 ~百萬級展開列、數十萬 user（精確數字 §12-1 實查），bitmap 圈人在此規模是工程劇場，`WHERE` 直掃已是毫秒級，**我方不用 bitmap**。再誠實一層：**這個量級 Postgres 其實也扛得住**（秒級而非毫秒級）；ClickHouse 的價值展示是（a）正典架構角色分工（OLTP/Gold 歸 PG、事件 OLAP 歸 CH）、（b）×50 放大負載下兩者的分化曲線（§9 負載測試，合成資料明確標註）、（c）欄式引擎運維能力本身。此三點原樣寫進 P5 `DECISIONS.md` ADR-lite 收攏。

### 4.2 部署形狀（開放問題 1 定案的落地）

`lakehouse/clickhouse/k8s/`（ArgoCD Application `clickhouse`，wave 3，`data` ns）：

- **StatefulSet `dmp-clickhouse`**：1 replica、image `clickhouse/clickhouse-server:25.8.28.1`、volumeClaimTemplate `data` 10Gi（無 storageClassName，沿 P1）、掛 `/var/lib/clickhouse`。資源 requests/limits：cpu 500m/2、memory 1Gi/4Gi（kind 單機友善；CH 預設會吃滿記憶體，limits 必設）。readinessProbe = `httpGet /ping :8123`。
- **Service `dmp-clickhouse`**（ClusterIP）：8123（HTTP）＋ 9000（native，clickhouse-client 除錯用）＋ 9363（Prometheus，§8）。
- **憑證（沿官方 image 首次初始化 env 機制，context7 查證）**：env `CLICKHOUSE_USER=dmp_app`、`CLICKHOUSE_PASSWORD`（來自 Secret `clickhouse-auth`，`envFrom`）、`CLICKHOUSE_DB=dmp`；另掛 config ConfigMap `users.d/disable-default.xml` 把 `default` 使用者鎖 `::1`（不裸奔）。**單一 app 使用者 `dmp_app`**：讀寫由呼叫端語意分離——自訂標籤物化執行 stored SQL 時帶 query 級 `readonly=1` setting（§5.4 防衛），不為單租戶 demo 開兩個 DB 使用者（README 註記多租戶時應拆 ro/rw）。
- **config ConfigMap**：`config.d/prometheus.xml`（開 9363 metrics endpoint）＋ `users.d/disable-default.xml`。
- **淘汰替代案**：Altinity operator（見 §0 刻意不引入）；多分片/複本（ADR 誠實：不演叢集運維）。

### 4.3 建表（DDL 由 `ml/dmp/src/dmp/ch.py` 持有，`CREATE TABLE IF NOT EXISTS`，沿 P1 loader-owns-DDL 慣例；MergeTree/ReplacingMergeTree 用法 context7 查證）

```sql
CREATE DATABASE IF NOT EXISTS dmp;

-- ① 事件鏡像（silver.ga4_events 全欄同構鏡像；型別對映註記於 ch.py）
CREATE TABLE IF NOT EXISTS dmp.ga4_events (
    event_date          Date,
    event_ts_micros     Int64,
    event_ts            DateTime64(6, 'UTC'),
    event_name          LowCardinality(String),
    user_pseudo_id      String,
    ga_session_id       Nullable(Int64),
    item_id             String,
    item_name           Nullable(String),
    item_category       LowCardinality(Nullable(String)),
    price               Nullable(Float64),
    quantity            Nullable(Int64),          -- 保 null 不補 0（地基 §4 語意直通）
    item_revenue        Nullable(Float64),
    transaction_id      Nullable(String),
    device_category     LowCardinality(Nullable(String)),
    geo_country         LowCardinality(Nullable(String)),
    first_touch_source  Nullable(String),
    first_touch_medium  Nullable(String),
    ingestion_id        String,
    ingested_at         DateTime64(6, 'UTC')
) ENGINE = MergeTree
PARTITION BY event_date                            -- 92 個日分區（觀測窗固定，分區數安全）
ORDER BY (event_name, user_pseudo_id, event_ts_micros, item_id);
-- ORDER BY 論證：event_name 基數 4 放最前（圈選/漏斗幾乎必過濾階段），再 user 聚攏（group by user 的
-- 人群類查詢局部性），尾綴時間戳＋item 保排序鍵近唯一。分區鍵=同步冪等單位（§4.4）。

-- ② 畫像鏡像（gold.dmp_user_profiles 同構全欄 + 版本欄；查詢一律帶 FINAL——十萬級列 FINAL 成本可忽略）
CREATE TABLE IF NOT EXISTS dmp.user_profiles (
    user_pseudo_id String,
    -- …§3.5 全欄同構（text→String/Nullable(String)、smallint→Nullable(UInt8)、
    --   bigint→Int64/Nullable(Int64)、numeric→Float64/Nullable(Float64)、boolean→Bool、date→Date）…
    synced_at DateTime('UTC')                      -- 版本欄
) ENGINE = ReplacingMergeTree(synced_at)
ORDER BY user_pseudo_id;

-- ③ 自訂標籤會員表（每 tag 一分區 → 重物化 = DROP PARTITION + 重灌，天然冪等）
CREATE TABLE IF NOT EXISTS dmp.user_custom_tags (
    tag_key         LowCardinality(String),
    user_pseudo_id  String,
    materialized_at DateTime('UTC')
) ENGINE = MergeTree
PARTITION BY tag_key                               -- tag_definitions 上限 200 檔（§5.4），分區數有界
ORDER BY (tag_key, user_pseudo_id);
```

**金額欄型別誠實**：Float64 直通地基（地基 §13-5 已註記 GA4 export 是 float 精度非記帳精度），CH 端不假裝升級成 Decimal。

### 4.4 同步 DAG：`dmp_refresh`（開放問題 2 定案；形狀對齊 P1 §7 / P4 §3 慣例）

```python
DAG(dag_id="dmp_refresh", schedule="0 4 * * *",      # UTC；在 ga4_daily 回放批與 05:00 匯出 DAG 之間
    catchup=False, max_active_runs=1,
    dagrun_timeout=timedelta(minutes=45),
    default_args=dict(retries=2, retry_delay=timedelta(minutes=1), retry_exponential_backoff=True),
    tags=["dmp"])
```

```
check_upstream（PythonOperator：gold_ga4_user_rfm count>0 且 silver.ga4_events count>0，否則 fail
      │         ——沿 P4 freshness-gate-非-sensor 姿態；不強制回放收斂，anchor 自適應，§13-2）
      ▼
dbt_run_dmp（KPO，既有 dbt image：dbt run --selector dmp_only）
      ▼
dbt_test_dmp（KPO：dbt test --selector dmp_only）→ 失敗 = DAG 失敗（DQ gate，標籤不帶病下行）
      ▼
sync_events_to_clickhouse（PythonOperator：水位增量——CH 取 max(event_date) 為水位；同步範圍 =
      │   PG 中 event_date **≥ 水位**的日期清單（含水位當日 = 尾日重灌，防前次半批）；逐日
      │   「DROP PARTITION 該日 → psycopg2 server-side cursor 讀 → clickhouse-connect
      │   client.insert 批 100k 列」；空 CH 首跑 = 全窗灌入；重跑冪等）
      ▼
sync_profiles_to_clickhouse（PythonOperator：全量讀 gold.dmp_user_profiles → insert 帶同批 synced_at
      │   → ReplacingMergeTree 收斂；十萬級列全量灌 = 秒～分級，右尺寸不做增量）
      ▼
materialize_custom_tags（PythonOperator：§5.4——active tag_definitions 逐檔物化；0 檔 = 合法直接過）
```

**淘汰替代案（開放問題 2）**：CDC（Debezium/Kafka Connect）——靜態資料集回放收斂後永無增量，CDC 是常駐空轉＋兩個新元件，違一工一具；「dbt 直寫 CH」——dbt-clickhouse adapter 會引入第二個 dbt target 與 profiles 分裂，同步本質是搬運非轉換，PythonOperator 恰如其分。**GA4 回放期間**（92 天 backfill 進行中）每日 04:00 的 `dmp_refresh` 自然吃到已落地的部分窗——分數/分群在回放期會逐日漂移（anchor = 當下已見最大 event_date），收斂後穩定；此行為寫進 README 與 verify 註記（§13-2）。

---

## 5. 人群圈選 DSL

### 5.1 邊界（開放問題 5 定案的完整敘述）

DSL v1 的條件作用域 = **`dmp.user_profiles` 白名單欄位 ＋ 自訂標籤會員**。事件級條件（「近 N 天做過 X ≥ k 次」）**不進 v1 文法**——ClickHouse 的事件掃描力道由兩處承擔：（a）**預覽的漏斗富化**（§5.3：把圈出的人群 JOIN `dmp.ga4_events` 算階段觸達，每次預覽都是真事件掃描）；（b）**admin 事件洞察罐頭查詢**（§6：漏斗/留存/交叉，參數化非 DSL 組合）。事件級 DSL 條件列進化方向（§13 尾）。取材界線：課程「通用標籤條件 DSL → ES bool query」**取其結構化條件表示與遞迴編譯邏輯，載體換 ClickHouse 參數化 SQL**（我方無 ES）。

### 5.2 DSL JSON Schema（欄位級；正本落 `admin/src/lib/dsl/schema.ts`，同檔輸出 JSON Schema 文件）

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "dmp-audience-dsl-v1",
  "$ref": "#/$defs/group",
  "$defs": {
    "group": {
      "type": "object", "additionalProperties": false,
      "required": ["op", "conditions"],
      "properties": {
        "op": { "enum": ["and", "or"] },
        "conditions": {
          "type": "array", "minItems": 1, "maxItems": 20,
          "items": { "oneOf": [ { "$ref": "#/$defs/group" },
                                 { "$ref": "#/$defs/match" },
                                 { "$ref": "#/$defs/range" },
                                 { "$ref": "#/$defs/exists" } ] }
        }
      }
    },
    "match": {
      "type": "object", "additionalProperties": false,
      "required": ["type", "field", "values"],
      "properties": {
        "type":   { "const": "match" },
        "field":  { "type": "string" },
        "values": { "type": "array", "minItems": 1, "maxItems": 100,
                    "items": { "type": ["string", "number", "boolean"] } }
      }
    },
    "range": {
      "type": "object", "additionalProperties": false,
      "required": ["type", "field"],
      "minProperties": 3,
      "properties": {
        "type":  { "const": "range" },
        "field": { "type": "string" },
        "gte": { "type": ["number", "string"] }, "gt": { "type": ["number", "string"] },
        "lte": { "type": ["number", "string"] }, "lt": { "type": ["number", "string"] }
      }
    },
    "exists": {
      "type": "object", "additionalProperties": false,
      "required": ["type", "field"],
      "properties": { "type": { "const": "exists" }, "field": { "type": "string" } }
    }
  }
}
```

編譯期額外限制（schema 之上，compiler 強制）：巢狀深度 ≤ **3**；`field` 必須命中 §5.2b 註冊表（未註冊 = 編譯錯誤，這是 SQL 注入的第一道閘）；range 的 date 型欄位值必須 `YYYY-MM-DD` 格式。

### 5.2b 欄位註冊表（`fields.ts`；DSL 唯一合法欄位面，加欄 = 改此表＋測試）

| DSL field | 型別 | 落點 | 允許條件 |
|---|---|---|---|
| behavior_segment / value_tier / funnel_stage_max / preferred_category / primary_device_category / primary_geo_country | enum/string | profiles 同名欄 | match, exists |
| is_purchaser / has_cart_abandon | bool | profiles 同名欄 | match |
| r_score / f_score / m_score / rfm_total | number | profiles 同名欄 | match, range, exists |
| recency_days / frequency_orders / monetary_total / aov / sessions_count / active_days / last_active_days / funnel_sessions_count / avg_funnel_session_depth / distinct_items_viewed / distinct_items_purchased / engagement_score | number | profiles 同名欄 | range, exists |
| first_seen_date / last_seen_date | date | profiles 同名欄 | range |
| `tag:<tag_key>` | 標籤會員 | `dmp.user_custom_tags` 半連接 | exists（match/range 不適用） |

### 5.3 編譯器（DSL → ClickHouse 參數化 SQL）與人群預覽

- **單一實作在 TypeScript**（`admin/src/lib/dsl/compiler.ts`）——遞迴下降：group → 括號連接 `AND`/`OR`；match → `field IN {p_n:Array(T)}`；range → 比較連接；exists → 一般欄 `isNotNull(field)`／標籤欄 `user_pseudo_id IN (SELECT user_pseudo_id FROM dmp.user_custom_tags WHERE tag_key = {p_n:String})`。**值一律走 @clickhouse/client `query_params`（server-side binding），欄名一律出自註冊表白名單**——兩道閘合成注入防衛。輸出 `{ whereSql, params, compilerVersion }`。
- **Airflow 側不重寫編譯器**（防雙實作漂移）：admin 存檔 tag/audience 時**同時存 DSL JSON 與編譯產物**（§5.4 表），物化 task 只執行 stored SQL——單一編譯真源。
- **人群預覽合約**（admin `POST /api/preview`，body = DSL JSON；全部查 CH）：

```json
{ "audience_size": 1234, "base_count": 270000, "pct": 0.0046,
  "sample": [ { "user_pseudo_id": "…", "behavior_segment": "…", "value_tier": "…",
                "monetary_total": 0, "last_active_days": 12 } ],
  "distributions": { "behavior_segment": [{"name":"…","count":0}],
                     "value_tier": [...], "preferred_category": [...] },
  "funnel": { "reached_view": 0, "reached_cart": 0, "reached_checkout": 0, "reached_purchase": 0 },
  "timing_ms": { "count": 0, "sample": 0, "distributions": 0, "funnel": 0 } }
```

  sample 固定 20 列（`ORDER BY user_pseudo_id LIMIT 20`，決定性）；distributions 各取 top10；**funnel 是事件表真掃描**（圈出的 user 集 JOIN `dmp.ga4_events` 按 `event_name` 算 `uniqExact(user_pseudo_id)`）；`timing_ms` 由 admin 回填並顯示在 UI（OLAP 秒回的現場佐證）。

### 5.4 標籤 / 人群定義表（Postgres schema `dmp`；admin CRUD 面）

`dmp` schema 由 `make dmp-init-db` 建（`kubectl exec` 進 lakehouse-postgres 跑 `lakehouse/postgres/sql/dmp_init.sql`，冪等：`CREATE SCHEMA IF NOT EXISTS dmp AUTHORIZATION pipeline_writer`）；表 DDL 由 `admin/db/init.sql` 持有、admin 啟動時冪等執行（`CREATE TABLE IF NOT EXISTS`）。admin 與 Airflow 物化 task 都用既有 `pipeline_writer` DSN（單租戶 demo；README 註記多使用者時拆專屬角色）。dbt 不碰 `dmp` schema（乾淨邊界：dbt 只管 staging/gold）。

| 表 | 欄位 | 說明 |
|---|---|---|
| `dmp.tag_definitions` | `tag_key text PK`（`^[a-z0-9_]{1,64}$`）、`display_name text`、`description text`、`dsl jsonb`、`compiled_sql text`、`compiler_version text`、`is_active boolean default true`、`created_at/updated_at timestamptz` | **自訂標籤 = 具名 DSL 謂詞**；admin 存檔時編譯並凍結 SQL。上限 **200** 檔 active（CH 分區數護欄，admin 拒超） |
| `dmp.audience_definitions` | `audience_id serial PK`、`name text`、`description text`、`dsl jsonb`、`compiled_sql text`、`compiler_version text`、`last_preview jsonb`（size/timing 快照）、`created_at/updated_at` | 已存人群（圈選建構器的存檔物）；v1 不物化會員名單，開啟即重預覽（資料靜態、重算便宜且永遠新鮮） |
| `dmp.user_custom_tags`（PG 側鏡像） | `tag_key text`、`user_pseudo_id text`、`materialized_at timestamptz`、PK `(tag_key, user_pseudo_id)` | 物化 task 寫（`DELETE WHERE tag_key` ＋ insert，冪等）；**供 P6 讀的鬆接縫落點**（接縫 I：P6 讀 PG 不摸 CH） |

**物化流程**（`materialize_custom_tags`）：逐 active tag → 以 CH query 級 `settings={'readonly': 1}` 執行 `SELECT user_pseudo_id FROM dmp.user_profiles FINAL WHERE <compiled_sql>`（readonly=1 = 任何寫入/DDL 語句直接被 CH 拒絕，stored SQL 被竄改的爆炸半徑收到唯讀）→ 會員名單同批寫 PG（DELETE＋INSERT）與 CH（`ALTER TABLE … DROP PARTITION` ＋ `client.insert`）→ 兩側同 `materialized_at`。`compiler_version` 不符現行版本的 tag 標示於 admin 提示重存（防陳舊 SQL 語意漂移）。

---

## 6. admin 後台（叢集內；開放問題 7 定案）

- **形狀**：`admin/` 獨立 Next.js 16.2 app、`output: 'standalone'`、node:22-slim 多階段 Dockerfile → GHCR（`admin-ci` workflow，鏡像 P0 hello-ci 模式：build→push→bump `admin/k8s/kustomization.yaml` 的 image tag；ArgoCD Application `dmp-admin` 的 source path = `admin/k8s/`）。Deployment `dmp-admin`（`apps` ns、1 replica、readinessProbe `/api/health`）＋ ClusterIP Service。**存取 = `kubectl port-forward svc/dmp-admin 3000`**（同 Grafana/ArgoCD 慣例；不開 Ingress、v1 無登入——邊界即叢集存取權，known-limit §13-6，進化方向 = Ingress＋basic auth）。
- **env（全來自 Secret，`envFrom`）**：`LAKEHOUSE_PG_DSN`（沿 P1 §8 同名合約）、`CLICKHOUSE_URL=http://dmp-clickhouse.data.svc:8123`、`CLICKHOUSE_USER`、`CLICKHOUSE_PASSWORD`、`CLICKHOUSE_DB=dmp`。
- **與 Vercel 前端的區別（設計上防混淆）**：`frontend/` = 純靜態、零 env、公開；`admin/` = server runtime、持憑證、叢集內。兩 app 不共享套件（說明元件各自實作——跨 app 抽共用 package 是為 3 個元件建 monorepo 工作區，YAGNI；概念一致即可，§7.3 註記）。

**頁面（4 頁）＋ API（route handlers）**：

| 頁 | 內容 | 打的 API |
|---|---|---|
| `/` 標籤覆蓋儀表 | 系統標籤覆蓋（讀 PG `gold.dmp_tag_coverage`）＋自訂標籤列表與各檔人數（CH `count() GROUP BY tag_key`）＋畫像/事件列數健康卡 | `GET /api/overview` |
| `/tags` 標籤 CRUD | 列表/建立/編輯/停用 `tag_definitions`；規則用圈選建構器同款表單（存檔時編譯＋jsonschema 驗證＋上限 200 檔防衛） | `GET/POST/PUT/DELETE /api/tags` |
| `/audiences` 圈選建構器 | 巢狀條件表單（op 切換/加條件/加群組，照 §5.2 文法一比一）＋**即時預覽面板**（人群大小/樣本 20 列/三個分佈/漏斗富化/各查詢 timing badge）＋存檔為 audience | `POST /api/preview`、`GET/POST/PUT/DELETE /api/audiences` |
| `/olap` 事件洞察 | 三個罐頭參數化查詢（參數 = 日期範圍/分群/類別下拉）：①漏斗（4 階段 uniqExact 遞進）②留存矩陣（首次互動週 × 後續週活躍，`retention` 聚合函式）③標籤×類別交叉（behavior_segment × item_category 熱度矩陣）——每查顯示掃描列數與耗時（`statistics` 回傳值），欄式秒回的展示主場 | `POST /api/olap/{funnel,retention,cross}` |

**每頁帶 ExplainerSection**（這是什麼／為什麼看／怎麼用；server component、可摺疊）——例：`/audiences` 的 Explainer 講「DSL 怎麼組、預覽數字怎麼讀、裝置≠真人」。API 防衛：所有入參過 zod 解析（DSL 另過 §5.2 schema）、CH 查詢一律 `query_params`、錯誤不外洩 stack（統一 `{error: message}` 500 信封）。

---

## 7. 前端展示頁（Vercel 靜態；接縫 H = P4 additive）

### 7.1 匯出（`datasets.py` additive ＋3 條目；既有 11 檔零改動、DAG 結構零改動）

| 檔案 | 來源表 | 內容形狀 | 預估列數 |
|---|---|---|---|
| `dmp_segments.json` | `gold.dmp_segment_summary` | 全欄平鋪（dimension 兩組） | ≤12 |
| `dmp_rfm_grid.json` | `gold.dmp_rfm_grid` | 全欄平鋪 | ≤25 |
| `dmp_tag_coverage.json` | `gold.dmp_tag_coverage` | 全欄平鋪 | 9 |
| `meta.json` | —（既有機制） | datasets 清單自動多 3 條；dmp 表未建 → `status:"absent"`（P4 既有容忍路徑，前端顯示「此資料尚未由平台產出」） | — |

匯出路徑**只讀 Postgres**（拓撲：公開站對 CH 零依賴）。統一信封/穩定性政策/驗證（單檔 ≤3MB 等）全沿 P4 §3–4，無新規。

### 7.2 `/audience` 頁（第 9 頁，加進既有 nav；對照 ga-insight `05_客戶價值分群.py`）

| 區塊 | 視覺 | 資料 |
|---|---|---|
| KPI tiles | 總裝置數／購買裝置數／購買率／`data_anchor_date` | dmp_tag_coverage（denominator＋purchaser）＋ dmp_segments |
| 行為分群（8 種） | Recharts PieChart（donut）＋逐群人數/佔比/平均貢獻表 | dmp_segments（dimension=behavior_segment） |
| 價值分層（4 級） | Recharts BarChart（含 avg_monetary 第二軸） | dmp_segments（dimension=value_tier） |
| R×F 熱圖 | **CSS grid heatmap**（5×5，users_count 上色、格內顯示 avg_monetary——沿 P4 PTT 頁自製 heatmap 先例，不為一張圖加庫） | dmp_rfm_grid |
| 標籤覆蓋 | 水平 BarChart（coverage_pct） | dmp_tag_coverage |

### 7.3 三層說明式 UI（跨 P4/P6/P7 硬性交付；本頁是首個完整落地，元件供全站複用）

`frontend/src/components/explain/` 三元件（client components；admin 內另有同概念實作，見 §6）：

| 元件 | 對照 ga-insight | 用法（本頁具體落點） |
|---|---|---|
| `InfoTooltip`（ⓘ hover/點擊） | 表單旁 help 參數 | KPI tile 旁（「購買率分母是全裝置」）；熱圖軸標（「R=近度分數，5 最近」） |
| `ChartCaption`（圖下常駐小字） | 逐圖 `st.caption` | 每張圖一句視覺語法/公式——例：熱圖「顏色=人數，格內數字=平均消費金額（USD）」；分群圖「佔比分母=購買裝置數」 |
| `Explainer`（可摺疊，`defaultOpen` prop） | `st.expander(…, expanded=True/False)` | **定義類預設展開**：〈如何解讀兩種分類〉——8 分群定義表＋4 分級定義表（§3.2/§3.3 表文，即 ga-insight `expanded=True` 定義表的 Next.js 映射）。**方法論類預設收合**：〈分數怎麼算〉（五分位/tiebreak/衰減公式/anchor 語意）、〈資料誠實聲明〉（裝置級匿名=裝置畫像非真人；靜態觀測窗 2020-11～2021-01；RFM 只覆蓋購買者） |

頁 footer 沿 P4 `FreshnessBanner`。素材來源紀律：分群/分級定義文字正本在 dbt `_dmp_schema.yml` description（§3 表文），前端引用不另寫一版（單一真源）。

---

## 8. Secret / 監控 / CI（零新監控元件盤點）

| 面向 | 接法 |
|---|---|
| Secret | `make dmp-secrets`（冪等，沿 P2 `make ml-secrets` 風格）：生成隨機密碼 → `clickhouse-auth` Secret（key：`CLICKHOUSE_USER`/`CLICKHOUSE_PASSWORD`/`CLICKHOUSE_DB`）建於 **`data`（CH 本體）、`airflow`（同步 task）、`apps`（admin）三個 ns**；admin 另需 `lakehouse-pg-dsn`（`apps` ns，值沿 P1 `LAKEHOUSE_PG_DSN` 合約組法）。命令式建立、不進 git（P0 §7 紀律）。 |
| Prometheus | ①CH 原生 endpoint（config.d 開 9363）＋ **PodMonitor**（進既有 wave 6 `pipeline-monitoring` app，additive）；②postgres-exporter 自訂查詢 ConfigMap additive ＋2 條：`dmp_profiles_rows` = `SELECT count(*) FROM gold.dmp_user_profiles`、`dmp_purchasers_total` = `… WHERE is_purchaser`。 |
| 告警 / Grafana | 不加專屬 PrometheusRule、不建新 dashboard（沿 P6 §9 姿態：任務失敗已被既有 statsd 告警涵蓋；CH/admin 的展示面在 admin 本身與 §9 佐證物）。 |
| CI | `admin-ci`（唯一新 workflow）；`airflow-ci` paths ＋`ml/dmp/**` 一行；`dbt-ci` 天然涵蓋。CH 官方 image 進 P5 Trivy 掃描清單（image gate 既有機制自動涵蓋——manifest bump 走 GitOps 交棒點）。 |

---

## 9. OLAP 能力佐證（負載測試＋截圖＋MCP；驗收物非敘述）

- **`make dmp-bench`（`scripts/bench-dmp.sh`）**：同構三查詢（①全窗漏斗 4 階段去重人數 ②週×週留存矩陣 ③分群×類別交叉聚合）各跑 **Postgres（`silver.ga4_events`＋profiles）vs ClickHouse（`dmp.ga4_events`＋profiles）**，1× 真實資料與 **×50 合成放大**（`dmp.ga4_events_x50`，由 `amplify.py` 以 `user_pseudo_id || '#' || n` 複製生成，表名/報告**明確標 synthetic**，不與真實表混用）各一輪，輸出 markdown 計時表 → `docs/benchmarks/dmp-olap.md`（執行期產出，同 P5「對真 artifact 做」界線）。**誠實預期**：1× 兩者可能同量級（資料小），×50 分化才是論證主體——報告如實呈現兩組數字，不挑好看的講。
- **截圖/GIF**（進 P4 `/architecture` 截圖牆，沿 P5 資產紀律 PNG≤300KB/GIF≤3MB）：admin 圈選建構器＋預覽 timing badge GIF、`/olap` 留存矩陣截圖、CH `system.query_log` 耗時查詢截圖。
- **MCP additive ＋2 工具**（沿 P4 §7 模式，讀公開 JSON、不碰叢集）：`get_audience_segments`（讀 dmp_segments.json）、`get_rfm_grid`（讀 dmp_rfm_grid.json）。

---

## 10. 取材界線表（進化非複刻）

| 素材（唯讀） | 取的邏輯 | 重造/替換的工程層 |
|---|---|---|
| 課程 DMP：Spark 分層標籤 | 標籤分層概念（度量→分數→分群→分級） | Spark 批次 → **dbt/Postgres marts**（我方 serving 側轉換一律 dbt，P1 慣例） |
| 課程 DMP：通用標籤條件 DSL → ES bool query | match/range/exists＋and-or 的結構化條件表示、遞迴編譯 | ES bool query → **ClickHouse 參數化 SQL**（無 ES，一工一具）；編譯器單一 TS 實作＋stored SQL（§5.3 防雙實作漂移） |
| 課程 DMP：ClickHouse RoaringBitmap 圈人 | **不取**——十億級規模手法，我方規模 WHERE 直掃即毫秒級 | ADR §4.1 誠實寫明（bitmap = 工程劇場） |
| 課程 DMP：標籤 time-decay 權重 | 指數衰減「近期行為權重高」思想 | 錨點從 now() → **`data_anchor_date`**（靜態資料集誠實）；參數收 dbt vars 單一真源 |
| 課程 DMP：amis 低代碼 admin | 「標籤 CRUD＋圈選建構器＋人群預覽」的功能形狀 | amis JSON-schema 低代碼框架 → **輕 Next.js admin**（4 頁手寫，技術棧一致） |
| ga-insight `src/analytics/rfm.py:60-121` | 五分位 qcut(rank-first) 分箱、8 分群 CASE cascade（含判斷順序）、4 價值級切分 | pandas → **dbt SQL（NTILE＋決定性 tiebreak）**；reference_date 參數 → `data_anchor_date` 欄 |
| ga-insight `pages/05_💎_客戶價值分群.py` | 三層說明分類法：定義類 `expanded=True`／方法論收合、逐圖 caption、雙分類（行為 vs 價值）並排敘事 | Streamlit → **Next.js 三元件**（Explainer defaultOpen / ChartCaption / InfoTooltip，§7.3） |
| P1 §5 / P6 §4 | loader-owns-DDL、批次 UPSERT、決定性鍵、DQ gate 進 DAG | 直接沿用不重造（PG→CH 搬運照同款紀律） |

---

## 11. 測試策略與端到端驗收

### 單元/CI 層（每步可測）

| 層 | 測試 |
|---|---|
| dbt（`dbt-ci` parse ＋ runtime DQ gate） | §3.6 全清單；`dbt parse` 守 selectors 與新 model |
| `ml/dmp` pytest | `sync_events`：水位計算、尾日 DROP PARTITION 語句形狀、批次切割（mock clickhouse-connect / pg cursor）；`sync_profiles`：同批 `synced_at` 一致；`custom_tags`：readonly=1 setting 有掛上、PG/CH 雙寫同 `materialized_at`、0 檔 active 合法通過、200 檔上限防衛；`ch.py`：DDL 與 §4.3 逐欄一致（golden 字串）；`amplify.py`：輸出表名帶 `_x50`＋列數 = 50× |
| DAG | DagBag import 零錯誤；6 task 線性鏈斷言；`catchup=False`/`max_active_runs=1` 守門；schedule 在匯出 DAG（05:00）之前 |
| admin vitest | **DSL compiler 黃金測試**（固定 DSL fixtures → SQL/params 逐字元快照；深度>3 拒；未註冊 field 拒；values>100 拒；注入樣本（欄名夾 `;DROP`、值夾引號）全數被白名單/參數化擋下）；jsonschema 驗證器對非法文法 fixtures 全拒；route handler 單元（mock pg/ch） |
| exporter pytest（既有） | 3 新 dataset 條目 SQL 可解析、caps 設定存在（沿 P4 §9 既有守門自動涵蓋） |
| frontend | 既有 `check-data.mjs` 自動涵蓋 3 新檔（信封斷言）；`/audience` 頁 build 過即拓撲守門（`output:'export'`） |

### `make dmp-verify`（`scripts/verify-dmp.sh`；前置 = P6 `make ga4-verify` 綠 ＋ `make dmp-secrets`/`dmp-init-db` 已跑）

| # | 檢查 | 預期 |
|---|---|---|
| 1 | CH 就緒 | `dmp-clickhouse` pod Ready；`curl http://…:8123/ping` = `Ok.`；`default` 使用者遠端連線被拒（安全防衛生效） |
| 2 | `dmp_refresh` dagrun | trigger → 輪詢 success（timeout 20m；含 dbt_test_dmp 綠 = DQ gate 過） |
| 3 | 標籤層 | `gold.dmp_user_profiles` 列數 = `gold_ga4_user_rfm` 列數；`behavior_segment` 出現 ≥6 個不同值；分群加總 = 購買者數 |
| 4 | 同步一致性 | PG `silver.ga4_events` 與 CH `dmp.ga4_events` **逐 event_date 列數全等**；CH `user_profiles FINAL` 列數 = PG profiles 列數 |
| 5 | 冪等 | 重跑 `dmp_refresh` → CH 兩表列數不膨脹（DROP PARTITION／ReplacingMergeTree 語意可執行證明） |
| 6 | **DSL 圈選端到端（brief 核心驗收）** | port-forward admin → `POST /api/preview` 帶 fixture DSL（`behavior_segment IN ('VIP 客戶','忠誠客戶') AND monetary_total >= 100`）→ 回 `audience_size > 0` ＋ 20 樣本 ＋ 分佈 ＋ 漏斗四值 ＋ timing_ms |
| 7 | 自訂標籤物化 | `POST /api/tags` 建 fixture tag → 重跑 materialize task → PG 與 CH 會員列數相等且 > 0 |
| 8 | 匯出/前端 | 匯出 DAG 跑後 `latest/dmp_*.json` 三檔存在、信封合法、`rows > 0`；`meta.json` datasets 多 3 條 |
| 9 | 主線無損（additive 證明，比照 P6 驗收 #6） | `ga4_daily`/`yt_trending_hourly` 最近 dagrun 仍 success；主線 dbt log 無 tag:dmp 資產 |
| 10 | OLAP 佐證物 | `make dmp-bench` 產出 `docs/benchmarks/dmp-olap.md`，×50 組 CH 三查詢皆快於 PG（1× 組僅記錄不斷言——誠實） |

---

## 12. plan 前需實查（設計已收斂，以下為落地校準點，皆帶預設傾向）

1. **資料量級與購買者基數**（3 條 SQL 對已落地 silver/gold）：展開列總數、distinct user 數、購買者數與 `orders_count` 分佈。預設傾向：百萬級列／數十萬 user／購買者為個位數 %；F 軸大量 `orders_count=1` 使 NTILE 靠 tiebreak 打散（與 ga-insight rank-first 行為一致，§13-4 已預留敘述）。若購買者 < 5,000，分群統計小樣本註記進 Explainer 數字位，機制不變。
2. **CH image 25.8.28.1 於 kind/arm64（M4）**：官方 multi-arch，預設傾向直接可跑；若 arm64 異常改 `25.8`（浮動 patch）並記錄。
3. **clickhouse-connect 1.4.2 與 Airflow image 依賴相容**（預設傾向：純 HTTP 客戶端、依賴輕、相容；`uv pip compile` 一次定 lock，同 P1 手法）。
4. **@clickhouse/client `query_params`＋`readonly` setting 煙囪驗證**（預設傾向：文件明載可用；5 分鐘實證 Array 參數與 FINAL 查詢）。
5. **同步吞吐**：百萬級列 PG→CH 全窗首灌耗時（預設傾向：分鐘級，批 100k；若 >15 分鐘調批次大小，機制不變）。
6. **`retention` 聚合函式在留存矩陣查詢的形狀**（預設傾向：可用；備援 = 自寫條件聚合 `uniqExactIf`，語意等價）。
7. **admin standalone image 尺寸與 GHCR 推送**（沿 hello-ci；預設傾向：node:22-slim 兩階段 <300MB）。

---

## 13. known-limits（誠實段）＋ 跨 spec 接縫對照

**known-limits（README 全列）**：
1. **裝置畫像非真人身分**：`user_pseudo_id` 是 Google 已去識別的裝置級 ID（地基 §13-4），跨裝置同人不可縫合——所有「使用者/客戶」字樣在 UI 與文件一律讀作「裝置」，Explainer 誠實聲明（§7.3）。
2. **靜態觀測窗**：時間衰減/recency/「近期」全部相對 `data_anchor_date`（2021-01-31）非今天；GA4 回放收斂前分數逐日漂移屬預期，收斂後穩定（§4.4）。
3. **RFM 只覆蓋購買者**：未購裝置無分群/分級（有行為標籤）；覆蓋率如實出在 `dmp_tag_coverage` 與前端 KPI。
4. **五分位同值跨箱**：NTILE＋決定性 tiebreak = ga-insight `rank(method='first')` 同款——同 `orders_count=1` 的兩個裝置可能拿到不同 f_score；傳統五分位實務、決定性可重放，非 bug。
5. **CH 規模誠實**：本資料量 Postgres 也扛得住；ClickHouse 的論證是正典角色分工＋×50 放大分化＋運維能力展示（§4.1 ADR、§9 報告如實雙呈）。
6. **admin 無登入**：叢集存取權即邊界（port-forward）；多使用者/暴露前必加 Ingress＋auth（進化方向）。
7. **行為標籤的 session 語意**：源是漏斗活躍 session（接縫 E），`funnel_sessions_count`/`avg_funnel_session_depth` 不代表全站瀏覽行為。

**跨 spec 接縫對照（brief §共用契約逐條回填）**：

| 接縫 | 本 design 落點 |
|---|---|
| E（sessions 非全 session） | §3.4/§3.5 欄位帶 `funnel_` 前綴＋description 誠實；不假設全 session 覆蓋；known-limit 7 |
| F（RFM 是源非分數） | 分箱/分群/分級全在 §3；地基 `gold_ga4_user_rfm` 零改動；`recency_days`/`data_anchor_date` 直通 |
| G（item_category 標籤） | §3.4 類別偏好 JOIN `gold_ga4_item_catalog` 取正典類別 |
| H（P7→P4 匯出 additive） | §7.1 只加 3 檔；既有 11 檔/DAG 結構/信封零改動；absent 容忍沿用 |
| I（與 P6 鬆接縫） | P6 **可讀** `gold.dmp_user_profiles`（behavior_segment/value_tier 供分群推薦/冷啟）與 `dmp.user_custom_tags`（PG 側）——皆 Postgres 表、additive-only 穩定合約；**無同步依賴**：P6 不等 `dmp_refresh`、P7 不讀 P6 任何產出；P6 若用，於其 plan 自行 LEFT JOIN 容 NULL |

**進化方向（v1 刻意不做，列給面試敘事）**：KMeans/XGBoost 價值分層（走 P2 MLflow/DVC/M4 慣例）；DSL `not` 運算子與事件級條件（「近 N 天做過 X≥k 次」進文法）；人群會員快照與匯出（模擬廣告平台受眾上傳）；admin Ingress＋auth。
