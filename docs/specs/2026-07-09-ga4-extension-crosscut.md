# GA4 擴充（P6 推薦 / P7 DMP / 即時 Flink）— 跨 spec 主對齊文件（Opus 把關 2026-07-09）

> **地位**：本檔是 GA4 擴充四份 design（地基 + P6 推薦 + P7 DMP + 即時 Flink）的**跨 spec 契約單一真源**。寫任何一份 implementation plan 前先讀本檔；本檔與任一單份 design 的**跨 spec** 描述衝突時，**以本檔為準**。單份 design 自身的**內部**實作細節仍以該 design 為準。
> **緣由**：四份分兩波由 Fable 5 產出——地基（第 1 波，已鎖合約）、P6/P7/即時（第 2 波平行）。平行撰寫時 P6 推薦 design 尚未產出，即時層只能依 brief 級接縫用 `rt-v0` 假設 → 累積數個共用擴充點與命名分歧，Opus 逐份複核（含 grep 實命名對照）後在此集中裁定。
> **各 design 自身的 §接縫/§known-limit 對照仍有效，本檔是其上位補充。**

## 四份 design 索引

| # | design 檔 | 一句話 | 狀態 |
|---|---|---|---|
| 地基 | `2026-07-09-P6-ga4-ingestion-foundation-design.md` | 公開 sample 全漏斗萃取 → Silver `ga4_events` + 4 Gold 合約（**已鎖，勿改**）| ✅ committed `f7eac51` |
| P6 | `2026-07-09-P6-recommendation-design.md` | 3 路召回 → LTR → Redis+KServe 線上 → LLM 理由 → A/B | ✅ committed `f6d8c04` |
| P7 | `2026-07-09-P7-dmp-design.md` | RFM/分群 → ClickHouse OLAP → 圈選 DSL → 叢集內 admin | ✅ committed `370faf4` |
| 即時 | `2026-07-09-P6-realtime-features-design.md` | Flink event-time 特徵 → Redis（接縫 A 消費方）+ 對照驗證 | ✅ committed `8411c56` |

## 建置順序（硬性——執行期真實相依）

```
地基（GA4 Silver/Gold 合約，已鎖）
   ├─ P6 推薦 ─────────────┐
   │     └─ 即時 Flink（吃 P6 接縫 A Redis schema）← 必在 P6 之後
   └─ P7 DMP（與 P6 平行，鬆接縫 I 不阻塞）
```

- **P6 必在即時之前落地**：即時層的 Redis sink 欄位/視窗由 P6 §6.2 契約決定（見 EP-A）。P6 plan 先寫先執行。
- **P7 與 P6 可平行**（接縫 I 是鬆接縫，見 EP-I）。
- 每份下游 plan 開篇必寫「地基是否已實作」：已 → grep 實際欄名對齊（分歧只可能在命名）；未 → 阻塞（四份都吃地基 Silver/Gold）。

---

## EP-A ★ Redis 即時特徵 schema（P6 ↔ 即時；**最大接縫，本檔覆蓋即時 design §6 假設**）

**單一真源 = P6 推薦 design §6（尤其 §6.0 全域約定、§6.2 rt 鍵、§5.1 RECO_FEATURE_SCHEMA rt 群）。即時 Flink design §6 的 `rt-v0` 假設整段作廢，以下列裁定為準。**

### A-1 即時 design 低估了分歧（關鍵）
即時 design 自評「差異只在 key 命名/TTL，吸收在 `RedisFeatureSink` 三處、job 邏輯零改」。**這低估了**：P6 §6.2 要的**欄位與視窗**（`views_1h`/`carts_1h` 60m、`events_30m` 30m、`top_cat_1h` 60m）與即時 design §5.3 算的（`cat_view_5m` 5m、`session_cart_pending` session、`pop_15m` 15m item）**是特徵定義本身不同** → 要改 Flink **視窗運算子**（job 邏輯），不只改 sink。即時 plan 必須據此**重寫 §5.3 特徵表**對齊 P6 契約。

### A-2 裁定：即時 Flink 寫入 Redis 的欄位 = P6 §6.2 `feat:user:rt` 的九欄，一字不差

| 項目 | 裁定（P6 §6 為準） | 即時 design 原假設（作廢） |
|---|---|---|
| **key** | `feat:user:rt:{user_pseudo_id}` | ~~`feat:rt:user:{id}`~~ |
| **型別/TTL** | HASH，**TTL 7200s**（key 級 EXPIRE） | ~~1800s~~ |
| **欄位（九）** | `views_1h`(60m view 計數)/`carts_1h`(60m cart)/`events_30m`(30m 漏斗事件)/`top_cat_1h`(60m view 最高類別，**平手取字典序小**)/`top_cat_views_1h`/`last_item_id`/`last_event_name`/`last_event_ts_ms`/`rt_updated_at_ms` | ~~`cat_view_5m:<cat>`/`session_events`/`session_cart_pending`/`session_started_at`~~ |
| **Redis 位址** | `reco-redis.ml.svc:6379`，db 0（P6 §12；Redis 住 `ml` ns，Flink 在 `data` ns 跨 ns 存取，正常） | ~~`redis.data.svc:6379`~~ |
| **AUTH Secret** | `reco-redis-auth`（P6 §12 已預留四方共用含 Flink sink；**即時 plan 不另建**，只在 `data` ns additive 複製一份或跨 ns 引用） | — |
| **schema_version 協商** | Flink job 啟動檢查 `meta:reco:schema_version`==P6 定值，不符 fail-fast 拒提交（P6 §6.0） | — |
| **寫入者矩陣** | Flink **只寫 `feat:user:rt:*`**（P6 §6.0 鎖死）；**不得寫 item rt 鍵、不得寫任何離線鍵** | ~~`feat:rt:item:{id}`~~ |
| **冪等** | HSET 絕對值覆寫 + EXPIRE，禁 INCR（P6 §6.2 與即時 §6 一致，保留） | 保留 |

### A-3 四個串流 pattern 全數保留（重寫特徵表時的對映）
即時層的教學價值（滑窗/session 視窗/ProcessFunction+timer/狀態去重四 pattern）**不因對齊 P6 契約而流失**：
- `views_1h`/`carts_1h`/`top_cat_1h`/`top_cat_views_1h` → **SlidingEventTimeWindows 60m**（滑窗 pattern）。
- `events_30m` → 30m 滑窗或 ProcessFunction 累計（滑窗/狀態 pattern）。
- `last_item_id`/`last_event_name`/`last_event_ts_ms`/`rt_updated_at_ms` → keyed `ValueState`（**ProcessFunction+state pattern**）。
- **F4 去重** → keyed state（狀態去重 pattern，保留不動）。
- **F3b session 視窗** → 保留為**驗證專用**（EventTimeSessionWindows 對照 `gold_ga4_sessions`，即時 §7 判準 B/C）——**session 視窗 pattern 在驗證路徑展示**，不寫 Redis。

### A-4 P6 不消費的即時特徵：降為驗證專用或移除
即時 design 的 **F2 item 熱度**（`pop_15m`/`purchase_15m`）與 **F3a session 加購未購**（`session_cart_pending`）**不在 P6 §5.1 rt 特徵群** → **不寫 Redis**（違 P6 寫入者矩陣）。二選一（即時 plan 定，傾向前者）：
- **(a) 降為驗證專用**：仍算、仍走 KafkaSink→驗證對照（證明 Flink 能正確算，豐富 §7 correctness demo），但不進 Redis。
- **(b) 移除**：若不值得維護驗證成本。
- **進化方向（非 v1）**：若 Fergus/P6 日後要更豐富的即時信號（item 熱度、當前購物車），P6 additive 擴 §5.1 特徵 + §6.2 欄位 + 重訓 + `schema_version` bump——**那是 P6 的 additive 演進，不是即時層單方 fork**。

### A-5 落地紀律
即時 plan 的 `RedisFeatureSink` key-builder/TTL/EXPIRE 對齊 A-2；**且**其 Flink 視窗運算子（§5.3）重寫對齊 A-2 欄位/視窗（此為 job 邏輯變更，非純 sink 變更——A-1）。P6 plan 先落地（Redis + schema_version + `reco-redis-auth`），即時 plan 依賴之。

---

## EP-B 前端說明式 UI 三元件（P6 ↔ P7 ↔ 即時；**單一實作處，勿三份各造**）

三份 design 各自建了「InfoTooltip/ChartCaption/Explainer」三元件，但**落點命名分歧**：P6 §11 `frontend/src/components/explainers/`、P7 §7.3 `frontend/src/components/explain/`、即時沿用。

**裁定：canonical 落點 = `frontend/src/components/explainers/`（P6 路徑）**，三元件**單一實作**（`InfoTooltip.tsx`/`ChartCaption.tsx`/`Explainer.tsx`，`Explainer` 帶 `defaultOpen` prop 支援「定義類展開/方法論類收合」兩模式）。
- **哪份 plan 先落地就建此目錄**；後續 plan 只 import、不重造（同 Looma §17 R2/R3 共用模組紀律）。
- P7 §7.3 的 `explain/` 路徑作廢，改 import `explainers/`。
- admin（P7 §6，叢集內另一 app）**可各自實作**（跨 app 抽 package 為 3 元件建 workspace 是 YAGNI，P7 §6 已註記）——本裁定只約束 `frontend/`（Vercel 靜態那份）。
- 每份 plan 的前端 Task 開篇判「`explainers/` 是否已存在」：已 → import；未 → 建。

---

## EP-C 前端頁與 nav（三份各稱「第 9 頁」，實為三頁）

P6 `/reco`、P7 `/audience`、即時 `/streaming` 各自稱「P4 第 9 頁」。**裁定：三頁並存 = 第 9/10/11 頁**，各 additive 加進 P4 既有 nav（P4 §5 政策內）。無技術衝突，僅編號釐清；nav 順序由落地序決定，不強制。

---

## EP-D 共用 additive 檔案（append 紀律，勿互覆）

以下檔案三份 plan 都會 additive 修改；**寫法一律「讀既有 → append 自己的條目/行 → 不動他人條目」**，執行順序任意但需冪等：

| 檔案 | P6 | P7 | 即時 |
|---|---|---|---|
| `lakehouse/dbt/selectors.yml` | tag:ga4 已由地基建；P6 無新 tag | **+tag:dmp 排除 + `dmp_only` selector** | — |
| `orchestration/exporter/…/datasets.py` | +4 條目 | +3 條目 | +1 條目 |
| `mcp-server/server.py` | +2 工具 | +2 工具 | +1 工具 |
| `.github/workflows/airflow-ci.yaml`（paths） | （P6 走 ml-batch-ci）| +`ml/dmp/**` | +`ingestion/streaming/replay/**` |
| MinIO mc-init bucket 清單 | — | — | +`flink` bucket |
| `frontend` nav / `components/explainers/` | 見 EP-B/EP-C | 見 EP-B/EP-C | 見 EP-B/EP-C |

- **selectors.yml 三方冪等**（地基已建含 tag:ga4 排除；comments plan 若在此 repo 另有 tag:comments——實為 trend repo 無 comments，該註記係 P6/P7 design 沿用 web-agency 措辭，**本 repo selectors.yml 排除清單 = tag:ga4 + tag:dmp**）。每份 plan：「檔案存在 → append 自己的 tag 排除 + `<x>_only` selector；不存在 → 建含全部已知排除」。

---

## EP-E ArgoCD sync-wave 統整地圖（防撞號）

| wave | app | ns | 來源 spec |
|---|---|---|---|
| 3–6 | lakehouse-postgres/minio/…（既有）+ **clickhouse** | data | P1 + **P7** |
| 7–11 | P2 ML 各 app + **dmp-admin** | ml / **apps** | P2 + **P7** |
| 7–10 | P3 ptt/kafka（既有）| data | P3 |
| 12 | **reco-redis** | ml | P6 |
| 13 | **reco-service** | ml | P6 |
| 14 | **flink-operator** | flink-operator | 即時 |
| 15 | **ga4-streaming** | data | 即時 |
| 16 | **streaming-monitoring** | — | 即時 |
| （既有 10） | kserve-models additive +`reco-ranker.yaml` | ml | P6（零新 app）|

- P7 clickhouse 掛 wave 3（儲存底座層，與 lakehouse-postgres 同層，P0 §3 同號無依賴合法）、dmp-admin wave 7（依賴 wave 3 CH+PG）。
- P6/即時接 12–16。**GA4 地基零新 ArgoCD app**（additive 到既有 Airflow/dbt image）。
- 各 plan 配號照本表；同號 app 之間確認無 CR 依賴（P0 §3）。

---

## EP-I P6 ↔ P7 鬆接縫（畫像/分群/標籤）

P7 §13 已定、P6 §11 已定，**兩者相容，無衝突**：
- P7 出 `gold.dmp_user_profiles`（`behavior_segment`/`value_tier`）+ `dmp.user_custom_tags`（PG 側鏡像）為**穩定合約、additive-only**。
- P6 **可選**讀之做分群推薦/冷啟，於 P6 plan 自行 **LEFT JOIN 容 NULL**；**無同步依賴**（P6 不等 `dmp_refresh`、P7 不讀 P6）。
- **P6 §11 的展示分群**（`buyer_repeat`/`buyer_once`/`browser_active`/`cold`）是 P6 **自有的簡化分群**（供 `reco_segments.json` 展示），與 P7 的 8 行為分群（`VIP 客戶`…）**是不同目的的兩套分群，並存**（P6 展示推薦 vs P7 行銷 DMP）。P6 §11 註記「P7 落地後 additive 替換群定義、segment key 介面不變」——即 P6 若要用 P7 分群，走 additive 不 fork。**v1 兩套獨立，不強耦合。**

---

## EP-J 其餘落地校準（plan 前）

- **Redis 跨 ns**：Flink（`data`）→ Redis（`ml`）跨 ns，`reco-redis.ml.svc:6379` FQDN 可達；`reco-redis-auth` Secret 需在 `data` ns 亦可見（即時 plan additive 複製或 P6 `make reco-secrets` 擴一個 ns）。
- **`top_cat_1h` 決定性**：P6（讀）與即時（寫）**都取「平手字典序小」**（P6 §6.2 已定）——即時 plan 的 top-category 計算照此，否則離線/線上對不上。
- **LLM 理由模型 tag**：P6 §8 寫 `qwen3.5:9b`，地基/P2 生態用 `qwen3:8b`——**裁定對齊 P2 既有 pin `qwen3:8b`**（除非 P6 plan 實查證明 9b 已在 host Ollama 且有理由），避免 host 模型碎裂。P6 plan 校準。
- **P6 rt 特徵訓練側 point-in-time 重算**（P6 §5.1）：即時層未落地時，P6 以 `has_rt=0` 服務；P6 §5.1 的 training-serving 一致性（同定義兩計算面）**其「線上計算面」= 即時 Flink 產出 A-2 九欄**——即時 plan 落地後，P6 的 rt 欄定義（`views_1h` 等）與 Flink 產出必須語意一致（同窗同義），此為 A-2 對齊的下游正確性保證。
- **驗收耦合**：P6 §14 驗收 #8 用手動 `HSET feat:user:rt:*` 模擬即時寫入；即時層 ship 後升級為真 sink 驗證（兩份 plan 順序耦合，即時在 P6 後）。

---

## 誠實/紅線（全擴充共守，已在各 design 落實，本檔彙整供 plan 自檢）

- **資料源只用公開 `ga4_obfuscated_sample_ecommerce`**；area02 真資料與專案 ID **零進入本 repo**（守 [[project_area02_real_ga_demo]] 精神：客戶機密不曝光）。
- **拓撲鐵律**：前端 Vercel 純靜態、打不到本地 k8s → P6 線上服務/P7 CH+admin/即時 Flink 全走「批次表 → P4 匯出 DAG → 靜態 JSON」進前端；線上/OLAP/串流能力以**負載測試 + MCP + 截圖/GIF** 佐證，非公開站 runtime 依賴。
- **三工具翻案各守誠實護欄**：Redis（純線上快取、非第二 OLTP/排程/佇列，寫入者矩陣鎖死）；ClickHouse（欄式 OLAP 正典用途、**非十億級 bitmap**、ADR 明寫「本量級 PG 也扛得住，價值＝角色分工＋×50 合成放大分化＋運維展示」，`amplify.py` 標 synthetic）；Flink（**標註事件重放非真線上流量**，六處落點；展示架構就緒性＋event-time 正確性，不宣稱真流量）。
- **一工一具未破**：排程仍只 Airflow、離線 OLTP 仍只 Postgres、agent 仍只 LangGraph、微調仍只 HuggingFace、messaging 仍只 Kafka；新增三工具各有唯一獨特職務。
- **靜態資料集誠實**：recency/時間衰減/「近期」全錨 `data_anchor_date` 非 now()；drift/回放/分數漂移的靜態語意如實記錄。
- **A/B 與推薦理由**：A/B `labeled_event_replay` 三處烙印；理由 LLM 只吃結構化事實 + 程式化 anti-hallucination 驗證器 + facts 快照可稽核。
- **隱私**：`user_pseudo_id` 裝置級匿名 → 全程「裝置畫像」非「真人身分」，UI/文件如實。

## 下一步

四份 design + 本 crosscut 完成並對齊。下一步＝逐份寫 implementation plan（`superpowers:writing-plans`），**依建置順序：地基 → P6 → 即時 / P7**。每份 plan 開篇引用本檔 EP-A~EP-J 與建置順序；即時 plan 特別據 EP-A 重寫 Flink 特徵表對齊 P6 §6.2。
