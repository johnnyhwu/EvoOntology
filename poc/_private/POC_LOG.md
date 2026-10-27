# EvoOntology PoC 進度記錄

> 這份記錄在 PoC 進行中逐階段累積。內容會提到資料陷阱，所以放在 `poc/_private/`，
> 不讓 Builder 與測試子 agent 讀到。全部完成後會整理成 `poc/POC_REPORT.md`。

## 目標與原則

**目標：** 先對 EvoOntology 這個 repo 能帶來的成果有初步感受（taste），之後再深入讀 code、改寫成
「deterministic pipeline + OpenRouter 開源模型」。

**驗收：**
1. Agent 基於建出來的 ontology，在**沒看過的問題**上表現良好。
2. 可以在 UI 上看到建出來的 ontology。

**三條原則（使用者指定）：**
1. 不污染機器環境：套件、資料全部放在這個 repo 下。
2. 不無腦執行 plugin：要清楚每一步發生什麼事，因為之後會改寫成 deterministic pipeline。
3. 每完成一個階段就記錄，最後這份文件要能讓人完整理解 PoC 與整套 solution 的 step by step。

---

## Phase 0：環境準備與關鍵決策

### 0.1 環境（原則 1）

| 項目 | 結果 |
| --- | --- |
| 系統 Python | 3.9.6，而 repo 的 `pyproject.toml` 要求 `>=3.10` |
| 處理方式 | 使用者建議用 uv。機器上**本來就有** `uv 0.12.7` 與 Python 3.12.14（`~/.local/share/uv/python/`，不是本次安裝），因此**沒有下載任何東西**，只用 `uv venv` 在 repo 內建立虛擬環境 |
| 指令 | `UV_CACHE_DIR=poc/.uv-cache uv venv poc/.venv --python 3.12 --no-config` |
| 第三方套件 | **零**。核心 `dependencies = []`，假資料用標準函式庫 `random` / `sqlite3` |
| 位元組碼 | 所有指令加 `PYTHONDONTWRITEBYTECODE=1`，工具腳本內也設 `sys.dont_write_bytecode = True`，避免 `__pycache__` 污染 repo |
| 驗證 | `git status` 只多出 `poc/` 一個未追蹤目錄，repo 追蹤的檔案零改動 |

補充：虛擬環境的直譯器是**符號連結**到機器上既有的 3.12，這是唯一一個 repo 外的依賴（唯讀使用）。
我先用 3.9 試過，核心可以 import（`from __future__ import annotations` 讓 `X | Y` 型別註記不會出錯），
但仍改用 3.12 以符合 repo 的版本要求，避免之後遇到只在 3.10+ 才有的語法。

### 0.2 不安裝 plugin，直接呼叫 plugin 背後的函式（原則 2）

- 官方流程是 `claude plugin install`，這會寫進 `~/.claude/`，違反原則 1；而且 plugin 原始碼本來就在
  `plugins/claude-code/`，不需要「下載」。
- 讀完 `evoontology/runtime/ops.py` 後確認：plugin 的 MCP server（`runtime/mcp_server.py`）只是一層
  stdio JSON-RPC 轉接，真正的實作是 `ops._HANDLERS` 裡 28 個 Python 函式。
  - `publish_ontology_build`、`save_version`、`configure_ontology_project`、
    `prepare_ontology_workload`、`annotate_ontology_version` 等都在其中。
- 因此我寫了一個 CLI 包裝 `poc/tools/ops.py`，用**同一個註冊表**執行這些操作。
  `ops.py <op名稱> '<json>'` 等價於 MCP 的 `tools/call`。

**對改寫的意義：** 未來的 deterministic pipeline 可以直接 import `evoontology.runtime.ops`，
不需要 MCP；MCP 只是為了讓 Claude Code / Codex 能呼叫這些函式。

### 0.3 角色分工

| 角色 | 由誰扮演 | 看得到什麼 |
| --- | --- | --- |
| Builder | 乾淨的子 agent（代表未來的 OpenRouter 模型） | 資料庫、建構題（只有題目）、業務說明、build skill 與 references |
| 測試 agent | 每題每組一個乾淨的子 agent | 題目 + 該組允許的工具 |
| 出題者 / 標準答案 / 評分 | 我（主 session） | 全部 |

隔離只靠「告知不要讀」，沒有技術強制（子 agent 有檔案存取權）。這是已知限制。

---

## Phase 1：場景、資料、題目

### 1.1 場景：Lumo Outdoors 戶外裝備電商

線上與門市販售登山背包、帳篷、登山鞋、機能服飾、配件。資料庫 `poc/data/shop.sqlite`（SQLite，唯讀使用），
共 **6 張表**，**刻意不宣告外鍵、不加欄位註解**（很多企業資料庫就是這樣），關聯只能從欄位命名與資料推斷。

| 表 | 筆數 | 說明 |
| --- | ---: | --- |
| `customers` | 400 | 客戶：地區代碼、會員等級、註冊日 |
| `products` | 60 | 商品：類別、標價、是否在售 |
| `orders` | 3000 | 訂單：時間（UTC）、狀態碼、通路、優惠碼 |
| `order_items` | 5238 | 訂單明細：數量、成交單價 |
| `payments` | 2992 | 付款紀錄：一張訂單可有多筆（含失敗重試） |
| `refunds` | 194 | 退款：到明細層級，含原因碼 |

資料由 `poc/_private/gen_data.py` 以固定 seed（20251021）產生，可重現。

### 1.2 刻意放進去的陷阱（這是我設計的，結果要打折看）

| 陷阱 | 在哪裡 | 業務說明有沒有寫 | 只能靠探索資料發現？ |
| --- | --- | --- | --- |
| 時間戳是 UTC，報表用台北時間（跨月、跨年邊界） | `orders.order_ts` 等 | 有 | 否 |
| 狀態碼 0/1/2/3/9 的意義 | `orders.status` | 有 | **是**（資料裡沒有對照表，非常見的代碼無法猜） |
| 有效訂單、淨營收、客單價、回購客戶、實收的定義 | 跨表 | 有 | 否 |
| 淨營收按「訂單時間」歸屬，退款報表按「退款時間」歸屬 | orders / refunds | 有 | 否 |
| 金額單位不一致：`order_items.unit_price_cents` 是 1/100 元，其他表是元 | order_items vs 其他 | **沒有** | **是** |
| 一張訂單可有多筆付款（失敗重試），只有 `ok` 才算實收 | payments | 代碼有寫，重試現象沒寫 | **是** |
| 成交單價 ≠ 商品標價（有折扣） | order_items vs products | 有寫「不是標價」 | 部分 |
| 商品類別是英文代碼，問題用中文 | products.category | 有 | 否 |
| 沒有外鍵宣告 | 全部 | — | 是 |

### 1.3 題目（中文問題 + 英文欄位名）

- **建構題 C01–C10（10 題）：** 只有題目文字，放在 `poc/build_input/construction_questions.json`，給 Builder。
- **留出題 H01–H10（10 題）：** 題目與標準答案放在 `poc/_private/heldout.json`，Builder 與測試前不給。
  - `near`（H01–H06）：與建構題同一類概念，只換參數（不同季、地區、會員等級…）。
  - `far`（H07–H10）：新的組合，如帳篷淨營收（要跨 4 張表）、依退款原因統計類別、
    回購客戶平均訂單數、「付款失敗後成功」的訂單數（建構題沒碰過付款重試）。
- **標準答案**由 `poc/_private/make_questions.py` 直接對資料庫執行 SQL 算出，不靠人工，並檢查每題結果唯一。
  修正一處：H08 原本答案與 C03 相同（都是 shoes），容易被猜中，改成「因配送延遲（R4）退款」，答案 tent。

### 1.4 業務說明文件 `poc/build_input/domain_knowledge.md`

模擬業務窗口提供的 domain knowledge：報表時間規則、名詞定義、代碼對照表。**不含**單位陷阱與付款重試。
這份文件在 repo 目前**沒有專屬入口**（見前面討論），所以這次是把它當成 Builder 可探索的「資料環境中的文件」。

### 1.5 子 agent 使用的工具 `poc/tools/`

| 檔案 | 功能 | 備註 |
| --- | --- | --- |
| `sql.py` | 唯讀 SQL（`mode=ro` + authorizer，僅允許 SELECT，最多 200 列） | 測過：`DELETE` 會被擋 |
| `ontology.py` | `manifest` / `browse` / `resolve`，包 `SemanticLayer` | 固定 `ontology_v0`，**不暴露任何寫入操作** |
| `ops.py` | Builder 專用，執行 plugin 背後的操作函式 | 測試 agent 不會拿到 |
| `_common.py` | 路徑與呼叫紀錄 | 每次呼叫自動寫入 `poc/eval/runs/<run_id>.jsonl` |

軌跡由**工具自己記錄**，不依賴 agent 自述，所以事後可以客觀看每個 agent 實際做了什麼。

### 1.6 標準答案（私有，僅供記錄）

| 題 | 答案 | 題 | 答案 |
| --- | --- | --- | --- |
| C01 | 5,190,523 | H01 | 5,342,715 |
| C02 | 10,043.31 | H02 | 10,857.43 |
| C03 | shoes | H03 | 612 |
| C04 | 849 | H04 | 3,430,135 |
| C05 | 296 | H05 | 56,575 |
| C06 | 35.1 | H06 | 50.3 |
| C07 | credit_card | H07 | 8,178,790 |
| C08 | 3,182,815 | H08 | tent |
| C09 | 87,510 | H09 | 7.86 |
| C10 | 星野 機能服飾 | H10 | 244 |

---

## Phase 2（試跑）：用 v1（小資料、10 題）跑一次 Builder

> v1 的資料、題目、workspace 已歸檔到 `poc/pilot_v1/`，v1 產生器與標準答案在 `poc/_private/pilot_v1/`。
> 之後因為使用者希望「資料與題目量大一點，結果才有意義」，正式實驗改用 v2（見 Phase 2b）。

**做法：** 派一個乾淨的子 agent 當 Builder，給它資料庫、10 題建構題、業務說明、build skill 與 references、
三個工具（`sql.py`、`ops.py`、檔案讀寫）。耗時約 4.7 分鐘、20 次工具呼叫。

**Builder 實際做的 9 步（對應 skill 的哪一步）：**

| # | skill 步驟 | 動作 |
| --- | --- | --- |
| 1 | Before Starting | 讀 SKILL.md 與 5 份 references、建構題、業務說明 |
| 2 | Step 1 | `sql.py --schema` 與各表筆數、distinct 值、前 5 列 |
| 3 | Step 1 | 約 30 條 SQL，逐一驗證業務說明裡的每個主張，得到 18 筆 Evidence 的內容 |
| 4 | Step 0 | `configure_ontology_project`：mode=rolling_trajectory、data_source=sqlite、evaluation=llm_judge |
| 5 | Step 0 | `prepare_ontology_workload`：10 題、`supplied_only:true` |
| 6 | Step 2 | 寫腳本產生 records.json，`save_version` |
| 7 | Step 2 | `validate_semantics`（第一次就通過） |
| 8 | Step 2 | `annotate_ontology_version`：摘要、7 條限制、每題連結到 8–17 個物件 |
| 9 | Publish | `publish_ontology_build`（`open_browser:false`），產生 HTML |

**產出：** terms 28、mappings 29、relations 27（hierarchy 5、composition 3、association 11、derivation 8、equivalence 0）、
constraints 20、evidence 18。

**Builder 探索資料時自己發現的事實（沒有人告訴它）：**
- `order_items.unit_price_cents` 是 1/100 元：2379 張有效訂單的明細金額加總，全部等於該單成功付款的 `amount_twd`。
- 狀態 1/2/3 的訂單各恰好有 1 筆成功付款；失敗的付款列仍帶金額，不能算進實收。
- 有 101 筆退款的台北月份與原訂單不同，所以「淨營收」與「退款報表」會得到不同的期間總額。
- 資料本身無法證明時間戳是 UTC（訂單小時分布接近均勻），這一條只有業務文件支持，Builder 把 confidence 設成 medium。

**檢查試跑 ontology 的幾個事實（我讀 JSON 與呼叫 `ontology.py` 得到）：**
- Builder 因為問題與業務文件是中文，**自然加了中文別名**（客戶、有效訂單、淨營收、客單價、回購客戶、北部客戶…），
  所以短詞的中文 browse / resolve 能命中。這和我事前對中文檢索的擔心不同。
- 檢索仍是詞彙比對：整句中文問題不會命中，必須是短詞（agent 要自己抽出關鍵詞）。
- 「淨營收」這種跨表衍生指標，Mapping 只能指向單一 `(table, column)`（它指向 `order_items.unit_price_cents`），
  真正的計算邏輯靠 `semantic_filter`、`aggregation_semantics` 的文字，以及 3 條 derivation relation 拼出來。
  這印證了「Mapping 對衍生指標表達力有限」。
- 沒有放進去的：退款原因代碼 R1–R4、優惠碼、註冊日期。Builder 的理由是它們與建構題無關，依「最小化」原則不放。
  這正是我們預期的行為，也是 v2 `far_unseen` 題要測的。

**Builder 回報 skill 在此環境下不明確的地方（對改寫成 pipeline 很重要）：**
1. `save_version` 的參數形狀沒寫明，是試出來的（`records` 必須含五個 key）。
2. 同一版本可以被覆寫（它探路時不小心存了空版本，後來直接覆寫成正式內容）。skill 沒說明這是否允許。
3. 欄位型別不明：Constraint 的 `evidence` 範例是字串，Term/Relation 是「references」，實測 list 可通過驗證。
4. Mapping 只有單一 table/column，跨表衍生指標沒有明確寫法。
5. skill 說「JOIN 不該存成 Relation」，但 schema 又要 `connection_condition` 描述欄位對應；Builder 的取捨是在 association 的
   `connection_condition` 用語意層寫欄位對應，並標註 indirect。
6. `hierarchy` 被 Builder 用來表示「子集合」（有效訂單 ⊂ 訂單、北部 ⊂ 地區、App ⊂ 通路），不是嚴格的 is-a。
7. Step 0 的「詢問使用者」在無人環境下全部要自行決定。
8. 業務文件算不算 skill 禁止的「外部知識」沒有明說。

**Builder 認為可以用固定程式取代（不需要 LLM）的部分：**
資料剖析（schema、distinct 值、筆數、FK 完整性、孤兒資料、時間範圍、單位對帳）、代碼表比對、以 join 成功率找隱含外鍵、
時區邊界影響統計、`save_version` / `annotate` 的 JSON 組裝、validate 與 publish。
**必須用 LLM 的**只剩：把業務詞彙與題目轉成語意物件、判斷 relation_type、處理文件沒定義的歧義與信心評估。

## Phase 2b：放大規模（v2）

**原因：** 使用者希望資料與題目都大一點，結果才有意義。v1 只有 10 題留出題，差 1–2 題就是雜訊。

| 項目 | v1（試跑） | v2（正式） |
| --- | ---: | ---: |
| 表 | 6 | **7**（新增 `shipments` 物流） |
| 客戶 / 商品 | 400 / 60 | 5,000 / 200 |
| 訂單 / 明細 | 3,000 / 5,238 | **60,000 / 104,966** |
| 付款 / 退款 / 物流 | 2,992 / 194 / — | 61,319 / 4,039 / 44,444 |
| 建構題 | 10 | **30** |
| 留出題 | 10 | **40** |

**留出題的三種分組（用來判斷 ontology 的泛化邊界）：**
- `near`（H01–H20）：與建構題同一類概念，只換參數（不同季、地區、會員等級…）。
- `far_combo`（H21–H30）：已見概念的新組合（北部且黃金會員、帳篷在第二季、回購客戶平均訂單數、LINE Pay 占比…）。
- `far_unseen`（H31–H40）：業務文件有定義、但建構題**完全沒問過**的指標（取消率、配送天數、準時送達率、新註冊客戶、
  優惠碼訂單、付款失敗後成功、待出貨）。用來誠實檢驗「ontology 只涵蓋工作負載」這個限制。

**新增的資料陷阱：** 配送時數依物流商不同（黑貓、新竹、順豐、郵政）；`shipments` 只有已出貨/已送達訂單才有紀錄，
已出貨未送達者 `delivered_ts` 為空。

**題目檢查後的修正（避免被猜中或失去鑑別力）：**
- C17、C18 的答案都是 tent（帳篷單價高，退款金額必然最高）。建構題不處理；但留出題 H15 改成「退款筆數最多的類別」，答案 shoes。
- H33（平均配送天數）與 H35（黑貓）原本都是 3.53 天，物流商條件看不出對錯；改成配送時數依物流商不同後，分別為 2.9 與 2.49。
- H28 改成「客單價最低的地區」，不再能靠「新加坡客戶最少」猜到淨營收最低。
- 已知仍可被猜的：C30 的 TW-N（客戶最多）、H28 的 SG。數量很少，影響有限。
- 評分容忍度：金額用相對 0.05%，計數須完全相等，比率與平均值容許 0.06（對應 GT 的 1–2 位小數四捨五入）。

**實驗組別與規模：**
| 組 | 內容 | 目的 |
| --- | --- | --- |
| A | 基本 skill + `sql.py`（可看 schema） | 下限：沒有任何領域知識 |
| B | 基本 skill + `sql.py` + `ontology.py`（manifest 放進 prompt） | 主要受測：ontology 有沒有幫助 |
| C | 基本 skill + `sql.py` + 業務說明文件整份貼進 prompt（無 ontology） | 對照：直接把知識塞進 skill 會怎樣 |

每組各 40 題、每題 1 次，共 120 次乾淨子 agent。用「同一題兩組是否都答對」做配對比較（sign test）。

---

## Phase 2c：用 v2 正式建構 ontology

**做法：** 同樣派一個全新的乾淨 Builder 子 agent，輸入換成 v2（資料庫、30 題建構題、業務說明）。
相較試跑，prompt 只多給**純格式資訊**（`save_version`、`annotate_ontology_version` 的參數形狀，以及不要用空版本探路），
沒有給任何內容上的提示。耗時約 8.4 分鐘、33 次工具呼叫。

**Builder 實際做的 10 步（對應 skill 的哪一步）：**

| # | skill 步驟 | 動作 |
| --- | --- | --- |
| 1 | Before Starting | 讀 SKILL.md 與 5 份 references、業務說明、30 題 |
| 2 | Step 0 | `configure_ontology_project`：mode=rolling_trajectory、data_source=sqlite、evaluation=llm_judge |
| 3 | Step 0 | `prepare_ontology_workload`：30 題、`supplied_only:true`，`coverage_gaps` 為空 |
| 4 | Step 1 | 約 60 條 SQL：各欄位 distinct 值、狀態與付款/出貨對應、金額單位對帳、時區換算影響、退款與明細連結、孤兒外鍵、唯一性 |
| 5 | Step 1 | 工作負載覆蓋對照（直接寫在腳本裡的 C01–C30 對照表，沒有另外產生檔案） |
| 6 | Step 2 | 寫 `gen_records.py` 產生 records，含完整性檢查（id 唯一、引用存在、無未使用 evidence） |
| 7 | Step 2 | `save_version`（一次成功） |
| 8 | Step 2 | `validate_semantics`（passed） |
| 9 | Step 2 | `annotate_ontology_version`：摘要、8 條限制、30 題各連結 6–21 個物件 |
| 10 | Publish | `publish_ontology_build`（`open_browser:false`） |

**產出：** terms 43、mappings 46、relations 29、constraints 27、evidence 25。
- term 型別：entity 6、dimension 15、metric 8、concept 4、category 10。
- relation 型別：hierarchy 15、derivation 9、composition 3、association 2、equivalence 0。
- constraint 型別：enum_semantics 10、business_rule 9、scope 7、data_quality 2、unit 1。
- annotate 連結涵蓋 30 題，validate 通過。

**Builder 從資料中找到、並寫成證據的事實（沒有人告訴它）：** 金額單位（分 vs 元）、UTC→台北時間換算會讓 655 張訂單換月
（2025/3 有效訂單 4128 對 4144）、付款失敗重試、姓名重複、狀態與付款/出貨互證、下架商品仍有歷史銷售。

**Builder 對文件主張的判斷（值得注意）：**
- 文件說「成交價已含優惠碼折扣」，但 Builder 驗證後發現成交價對標價的比例（100/90/85/80）與是否使用優惠碼**沒有關聯**，
  所以**沒有建立優惠碼物件**，只記在限制裡。這是「不採信無資料佐證的主張」的實例。
- 文件沒定義「銷售數量」，Builder 假設只計有效訂單，記成 `con_units_sold_assumption`（confidence low）。
- UTC 時區只有文件支持，資料無法證實，confidence 設 medium。

**未被放進 ontology 的（依「最小化」原則）：** `shipments` 整張表（沒有 mapping）、取消率、配送天數、準時送達、
新註冊客戶、優惠碼、待出貨訂單、回購客戶占比的分母。**與 `far_unseen`（H31–H40）幾乎完全重疊**，這是預期中的覆蓋缺口。

**環境問題與越界（如實記錄）：**
- `sql.py` 原本的執行量上限（約 200 萬步）太緊，Builder 有約 5 次大型 GROUP BY / 相關子查詢被中斷，
  因此有 4 項 evidence 只涵蓋取樣範圍（付款對訂單狀態、出貨對訂單狀態、成交價對標價、每位客戶有效訂單分布）。
  **ontology 已建好，不重建**，列為已知限制。之後我把上限放寬到約 1 億步，避免工具限制干擾測試組。
- Builder 有一次用系統 `python3` 對自己的腳本做字串替換（修兩處文字），沒有碰資料庫或 ops。屬輕微越界，無實質影響。

**Builder 回報 skill 在此環境下不明確的地方（與試跑重疊的不重複）：**
Evidence 的 `query` 欄位不適合文件類證據（沒有 SQL）；Mapping 沒有 evidence 欄位卻要求可追溯，只好寫進 `validation` 文字；
Term 的 `type`（concept / category / entity）與 relation 的 hierarchy / composition / association 邊界主觀；
`aggregation_semantics` 與「不寫 SQL 模板」的界線沒有判準；`publish_ontology_build` 預設會開瀏覽器，本環境必須傳 `open_browser:false`。

**Builder 認為可由固定程式取代的部分：**
`configure` / `prepare` 的參數、schema 與 distinct 值與筆數與孤兒/唯一性檢查、代碼欄位的 enum_semantics 骨架（低基數欄位 distinct 值對文件代碼表）、
每個時間欄位 UTC 與台北時間的差異量化、evidence/object id 引用檢查、save/validate/annotate/publish 呼叫序列、
題目到物件的 links（關鍵字比對，LLM 只審核）。**必須用 LLM 的**：把文件定義對應到欄位並判斷哪些主張有資料佐證、
決定要建哪些概念與型別、寫中文定義與 trigger_keywords、設計可重現的證據查詢。

## Phase 3：檢查 ontology 與 UI（驗收 2）

**UI：** `poc/workspace/.evoontology/visualizations/ontology-layer-explorer.html`（約 858 KB，單一離線檔，雙擊即可用瀏覽器開啟）。
內含「結果與問題 / 本體內容 / Schema 層 / Tool 層」四個分頁。我確認檔案存在且內嵌了 ontology 內容；
**我沒有親眼看過畫面**（沒有開瀏覽器），畫面效果需要你開啟確認。

**結構驗證：** `validate_semantics` passed、版本只有 `ontology_v0`。

**mapping 涵蓋的表：** customers、order_items、orders、payments、products、refunds。**shipments 沒有任何 mapping。**

**中文檢索實測（`browse`，kind=all）：**

| 查詢 | 命中 | 說明 |
| --- | ---: | --- |
| 淨營收 | 7 | 命中淨營收規則、有效訂單規則、金額→淨營收的 relation |
| 取消率 | 1 | 只命中「已取消訂單」的 constraint，沒有取消率這個指標本身 |
| 退款原因 | 4 | 命中原因 enum constraint、term、relation |
| 優惠碼 | 2 | 命中成交單價與訂單（定義文字裡提到優惠碼） |
| 配送天數 / 準時送達 / 新註冊客戶 / 待出貨 / 物流 / 黑貓宅急便 | **0** | ontology 沒有這些概念 |

結論：中文短詞檢索對**已建構的概念有效**；對**沒被問過的概念是空的**，agent 在這些題上只能靠自己查資料。

**manifest（agent 開場看到的說明）** 只有物件統計與兩個工具的用法，不含任何領域內容，共約 15 行。

---

## Phase 4：有無 ontology 的子 agent 測試（驗收 1）

**設計：** 40 題留出題（建構時完全沒看過）× 3 組 × 1 次 = 120 次乾淨子 agent。三組的 skill 檔在 `poc/eval/prompts/{A,B,C}.md`，
只差：A 無任何領域知識；B 多了 `ontology.py`（browse / resolve）與 manifest；C 把業務說明整份貼進 skill、無 ontology。
每個子 agent 只讀自己的 skill 檔，只用 `sql.py`（唯讀）、`ontology.py`（B 組）、`submit.py`。軌跡由工具自己記錄到 `poc/eval/runs/`。
冒煙測試（H01）先跑三組驗證線束，結果保留（沒有改 prompt）。並行上限 20，所以分六批派工；
2 個 agent 因 API 額度中途失敗，重派乾淨 agent 補跑（原本沒有提交答案，不會重複計算）。

### 結果

| 組別 | 全部 | near（20） | far_combo（10） | far_unseen（10） |
| --- | ---: | ---: | ---: | ---: |
| **A** 什麼都沒有 | **62%**（25/40） | 45% | 80% | 80% |
| **B** 有 ontology | **90%**（36/40） | 90% | 100% | 80% |
| **C** 業務說明貼進 prompt | **100%**（40/40） | 100% | 100% | 100% |

**配對比較（同一題；sign test 雙尾）：**
- A vs B：只有 B 對 11 題、只有 A 對 0 題，p = 0.001。
- A vs C：只有 C 對 15 題、只有 A 對 0 題，p < 0.001。
- B vs C：只有 C 對 4 題、只有 B 對 0 題，p = 0.125（樣本不足以斷定差異）。

**軌跡統計：** A 共 381 次 SQL（22 次出錯）；B 共 96 次語意層呼叫（40 題**每題都用了**）+ 138 次 SQL（2 次出錯），其中 21 次 resolve 回 unresolved、8 次 browse 為空；C 共 160 次 SQL、0 錯誤。
B 組用的 SQL 次數約是 A 組的 36%，且幾乎沒有語法/邏輯試錯。

### A 組為什麼錯（15 題）
A 組每個 agent 在回報裡都說「狀態碼沒有說明，是我從資料推測的」，而推測結果不一致：有的只算狀態 3、有的排除狀態 9、有的排除 0 和 9。
其餘錯誤是沒換算台北時間、淨營收退款歸屬方式、把客單價算成實付金額等。有一題（H05）是 agent 把算對的 9224.84 打成 9225.04，無法更正。
**這正是「沒有領域知識」會造成的不穩定：連同一題的重複與不同題之間，對「有效訂單」的定義都不一致。**

### B 組為什麼錯（4 題）——可追查的原因

| 題 | B 的答案 | 正解 | 原因（從軌跡與驗證指令確認） |
| --- | --- | --- | --- |
| H09（7 月有效訂單數） | 3942 | 3936 | 沒換算成台北時間，直接用 UTC 的 `order_ts` 篩選 |
| H10（門市有效訂單數） | 7126 | 7121 | 同上 |
| H37（WELCOME10 優惠碼訂單數） | 7010 | 7004 | 同上 |
| H32（取消率） | 15.02 | 15.8 | 取消率的分母定義（扣除待付款）只在業務文件裡，ontology 沒有這個概念 |

**前三題的根因我另外驗證過：** 這三個 agent 都 `resolve` 了「**訂單日期**」，但 ontology 裡這個概念叫「**訂單成立時間**」，沒有「訂單日期」這個別名，
所以回傳 `unresolved`，拿不到 `con_tz_order_time`（時區規則）。我手動 `resolve("訂單成立時間")` 就會正確回傳這條規則。
代碼層面的原因（讀 `runtime.py` 得知）：`resolve_semantics` 只回傳「目標是該 Term」的 constraint；`trigger_keywords` 只用在 `browse` 的搜尋文字，
不會因為問題裡出現「7 月」「2025」就自動帶出時區規則。所以**知識有進 ontology，但取用靠 agent 猜對詞**。

### 判讀（請連同限制一起看）

1. **ontology 確實有幫助：** 在這個合成場景下，B 比 A 在 11 題上轉對、0 題轉錯，且 agent 的試錯明顯減少。
2. **但 B 沒有贏過 C：** 把一頁業務說明直接貼進 prompt，這個規模下就是更強、更簡單的做法（4 題只有 C 對、0 題只有 B 對）。
   **這個 PoC 沒有測到 ontology 真正的賣點：** 當知識多到無法整份貼進 prompt、或 schema 擴大時，按需檢索才會有優勢。這裡只有 7 張表和 1 頁文件。
3. **B 的失分來自兩個可以改進的地方：** (a) 取用方式（詞彙比對 + 靠 agent 猜詞，時區規則沒有自動帶出）；
   (b) 「最小化、只建工作負載需要的」原則導致取消率這類沒被問過的定義沒進 ontology。
4. **`far_unseen` 組沒有鑑別力：** A 和 B 都是 80%。因為那 10 題大多可以直接從資料算出來（計數、平均），文件定義的影響小。
   原本想用它檢驗「ontology 對沒問過的概念沒有幫助」，結論只能說「沒有看到幫助」，不能說「證明沒有」。

### 這個 PoC 的限制（務必知道）

- 資料與陷阱是我設計的，結果代表「這類情境下機制能運作」，不是你公司真實資料的效果。
- 每題每組只跑 1 次，沒有重複，無法分離模型抽樣雜訊；40 題的 p 值只是方向性訊號。
- Builder 與所有測試 agent 都是同一個模型（Claude Sonnet 5.5），未來換成開源模型，ontology 品質與使用方式可能差很多。
- 隔離靠「告知不要讀」，沒有技術強制；agent 自述都只讀了 skill 檔，我沒有逐一核對讀檔紀錄。
- 評分容忍度：金額相對 0.05%、計數須完全相等、比率與平均 0.06；少數題有邊界案例（H33/H35 答案相同的可能性已用物流商差異排除）。
- 我沒有親眼看過 UI 畫面。
- v1 試跑的結果沒有納入上表（資料量與題數太小）。
- sql.py 的執行量上限在 Build 時過緊（約 200 萬步），4 項 evidence 只涵蓋取樣範圍；測試前我已放寬到約 1 億步，ontology 沒有重建。

---
