# EvoOntology PoC 完整報告

> 讀這份就能理解：PoC 怎麼做、結果如何、整套 solution 每一步發生什麼事。
> 前半（本節到「Solution 逐步說明」）是摘要與導覽；後半是依階段累積的詳細進度記錄（含 v1 試跑與所有細節）。

## 一、結論（TL;DR）

- **驗收 1（沒看過的問題表現好）：部分達成。** 40 題留出題上，無 ontology 62%、有 ontology **90%**、業務說明直接貼進 prompt 100%。
  ontology 相對「什麼都沒有」是顯著進步（11 題轉對、0 題轉錯，p=0.001），但**沒有贏過「直接把說明貼進 prompt」**。
  這個規模（7 張表、1 頁文件）本來就不是 ontology 的主場，PoC 沒有測到「知識太多貼不進 prompt」的情境。
- **驗收 2（UI 看得到 ontology）：檔案已產生，我沒有親眼看過畫面。** 路徑見下。
- **最有價值的發現：**
  1. ontology 的失分不是知識沒建，而是**取用靠 agent 猜對詞**——B 組 3 題因為查「訂單日期」（ontology 叫「訂單成立時間」）拿不到時區規則。
  2. Builder 自己從資料裡找出沒人告訴它的事實（金額單位是 1/100 元、付款重試、退款歸屬月份不同），並且拒絕採信一條資料佐證不了的文件主張（優惠碼折扣）。
  3. Build 流程中**大部分步驟可以用固定程式取代**，真正需要 LLM 的只有語意設計與歧義判斷（見第三節）。

## 二、檔案導覽（全部在 `poc/` 底下）

| 路徑 | 內容 |
| --- | --- |
| `workspace/.evoontology/visualizations/ontology-layer-explorer.html` | **UI**：單一離線 HTML，用瀏覽器雙擊開啟 |
| `workspace/.evoontology/versions/ontology_v0/` | 建出來的 ontology（5 個 JSON：terms / mappings / relations / constraints / evidence） |
| `workspace/build_scratch/` | Builder 當時寫的產生腳本與 records（可看它怎麼組出 ontology） |
| `data/shop_v2.sqlite` | 假資料（7 張表、60,000 張訂單） |
| `build_input_v2/` | Builder 的輸入：30 題建構題 + 業務說明 |
| `tools/` | 子 agent 用的工具：`sql.py`（唯讀）、`ontology.py`（browse/resolve）、`ops.py`（plugin 背後的函式）、`submit.py` |
| `eval/prompts/{A,B,C}.md` | 三組的 skill 檔 |
| `eval/answers.jsonl`、`eval/runs/*.jsonl` | 120 個答案與每次工具呼叫的完整軌跡（`BUILD.jsonl` 是 Builder 的軌跡） |
| `_private/` | 資料產生器（含陷阱）、標準答案、評分器、本報告來源 |
| `pilot_v1/` | v1 試跑（小資料、10 題）的歸檔 |
| `.venv/`（Python 3.12，沿用機器上既有直譯器） | 零第三方套件 |

**重新評分：** `PYTHONDONTWRITEBYTECODE=1 poc/.venv/bin/python poc/_private/score.py --per-question`
**重新產生資料與題目：** `gen_data_v2.py`、`make_questions_v2.py`（固定 seed，可重現）。

## 三、Solution 逐步說明（給「改寫成 deterministic pipeline + OpenRouter 模型」用）

下面是這次實際發生的流程。每一步標註：**固定程式** = 不需要 LLM、可直接寫死；**LLM** = 需要語言模型判斷。
對應的函式都在 `evoontology/runtime/ops.py` 的 `_HANDLERS`（28 個），plugin 的 MCP server 只是它的 stdio 包裝，你的 pipeline 可以直接 import，不需要 MCP。

### Build（建 ontology）

| # | 步驟 | 呼叫的函式 | 誰做 | 輸入 → 輸出 |
| --- | --- | --- | --- | --- |
| 1 | 設定專案 | `configure_ontology_project` | 固定程式 | 模式、資料來源、評估方式 → `project.json` |
| 2 | 載入工作負載 | `prepare_ontology_workload` | 固定程式 | 建構題 → `workload/questions.json`（去重、記錄來源） |
| 3 | 資料剖析 | （自己寫 SQL） | **可固定程式** | schema、distinct 值、筆數、孤兒外鍵、唯一性、時間範圍、單位對帳 → 一批基礎 Evidence |
| 4 | 業務文件對資料驗證 | （自己寫 SQL） | **LLM** | 文件裡每個主張 → 用查詢驗證，能證實的留證據，證不了的降低 confidence |
| 5 | 語意設計 | — | **LLM** | 題目 + 文件 + 剖析結果 → Terms / Mappings / Relations / Constraints / Evidence（嚴格符合 `ontology-schema.md`） |
| 6 | 組裝與完整性檢查 | — | 固定程式 | id 唯一、引用存在、無孤立 evidence |
| 7 | 存版本 | `save_version` | 固定程式 | 五個 key 的 records → `versions/ontology_v0/` |
| 8 | 驗證 | `validate_semantics` | 固定程式 | 檢查 JSON、跨紀錄引用、可載入 |
| 9 | 標註 | `annotate_ontology_version` | 固定程式 | 摘要、限制、題目→物件連結 → `reports/` |
| 10 | 發佈與渲染 | `publish_ontology_build` | 固定程式 | 啟用版本、初始化演化狀態、產生 HTML（`open_browser:false`） |

Builder 自己回報可由固定程式取代的：步驟 1–3、6–10，以及「代碼表（enum）骨架」「時區邊界影響量化」「題目→物件 links 的關鍵字比對」。
**真正要 LLM 的：** 步驟 4、5（文件對應到欄位、決定建哪些概念與關係型態、寫中文定義與 trigger_keywords、處理歧義）。

### Use（執行時）

| 步驟 | 內容 |
| --- | --- |
| 開場 | agent 讀到 manifest（物件統計 + 兩個工具用法，約 15 行，不含領域內容） |
| `browse_semantics(query, kind, limit)` | 純詞彙比對（token 交集 + 子字串），最多回 6 筆，不能列舉全部 |
| `resolve_semantics(mentions, context)` | 先精確比對名稱/別名，再子集比對；回傳 Term + 其 Mapping + 相關 Relation + **目標為該 Term 的 Constraint** + Evidence |
| 之後 | agent 自己寫 SQL 驗證（語意層明說「是指引不是答案」） |

### 評估

`tools/sql.py`（唯讀、授權器只允許 SELECT）+ `submit.py` + 三組 skill 檔 + 評分器；軌跡由工具自己寫檔，不依賴 agent 自述。

## 四、改寫時值得注意的設計問題（從這次實測與讀 code 得到）

1. **檢索太脆弱：** `resolve` 只回傳「目標是該 Term」的 constraint，`trigger_keywords` 只用在 `browse`。問題裡出現「7 月」不會自動帶出時區規則。
   → 可考慮：對整句問題做關鍵字比對、自動帶出相關 constraint；補同義詞/別名；或把「全域規則」（時區、有效訂單定義）放進 manifest。
2. **「最小化」原則與覆蓋：** 沒被問過的定義（取消率的分母）不會進 ontology。若你的使用情境有大量業務定義，要有另外的入口讓它們進來。
3. **Mapping 只有單一 table/column：** 跨表衍生指標（淨營收）只能靠文字欄位與 derivation relation 拼出來。
4. **skill 規格不明處（Builder 回報）：** `save_version` 參數形狀沒寫、同版本可覆寫、evidence 欄位型別、Mapping 沒 evidence 欄位卻要求可追溯、
   文件類證據的格式、Term `type` 與 Relation `relation_type` 的邊界、`aggregation_semantics` 與「不寫 SQL」的界線。改寫成固定 pipeline 時需要先決定這些。
5. **Python 版本：** repo 要求 `>=3.10`；系統 Python 是 3.9。這次用 uv 管理的 3.12 虛擬環境（機器上既有）。
6. **工具限制會影響證據品質：** 唯讀 SQL 工具的執行量上限太小，Build 時有大型查詢被中斷，證據只能取樣。

## 五、尚未做 / 可以做的下一步

- 親眼確認 UI 畫面；並請業務人員看一次，檢查建出來的關係是否合理。
- 做一組「知識多到貼不進 prompt」的規模測試（更多表、更長文件），這才是 ontology 與 C 組真正比較的地方。
- 重複跑（每題每組 ≥3 次）以分離抽樣雜訊。
- 修檢索（見上），重跑 B 組，看 4 題錯誤能否消除。
- 換成開源模型當 Builder 與測試 agent，比較 ontology 品質。
- 未跑 Evolve（原本就排除在這次範圍外）。

---

# 以下為詳細進度記錄（依階段累積）

