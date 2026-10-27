# EvoOntology PoC 2 報告：把「自我演化（Evolve）」也走完一遍

> 本報告接續 `poc/POC_REPORT.md`（PoC 1：只做了 Build + Use）。
> PoC 2 補上 PoC 1 沒做的部分：**Use 產生軌跡 → 觸發 → Evolve（診斷、歸因、修補、Gate）→ 發佈或保留 Parent**，
> 並且把整個流程寫成一條由 **Python 程式控制的確定性 pipeline**。
> 你說你只會讀這份報告、不看程式碼，所以這份報告的目標是：**讀完就能知道 EvoOntology 每一步實際做了什麼、
> 我的 PoC 怎麼做、真實跑出什麼結果、哪些地方不可靠、你重寫時該注意什麼。**

---

## 0. 怎麼讀這份報告

| 你想知道 | 去看 |
| --- | --- |
| 先要結論（5 分鐘版） | §1 |
| EvoOntology 官方流程到底怎麼運作（不看這章就看不懂後面） | §2 |
| 我的 pipeline 怎麼設計、哪些地方跟官方不同 | §3 |
| 實驗資料與設定（資料庫、題目、模型、預算） | §4 |
| **真實跑出來的每一步長什麼樣**（有真實內容與數字） | §5 |
| 結果好不好、可不可信、為什麼 Gate 沒有發佈新版 | §6 |
| 官方步驟哪些有走到、哪些沒有 | §7 |
| 你重寫時的建議與可客製化的點 | §8 |
| **限制、錯誤、需要你知道的誠實揭露** | §9（強烈建議讀） |
| 檔案在哪、怎麼重跑、成本明細、踩過的坑 | 附錄 A–D |

> **名詞速查**：
> **Parent**＝目前線上的版本（如 `ontology_v0`）；**Candidate**＝演化出的候選（如 `v0-c1`）；
> **Pool**＝演化用的 70% 軌跡（可看、可診斷）；**Reserve**＝保留的 30% 軌跡（只能用在最後 Parent vs Candidate 比較）；
> **Gate**＝比較關卡；**Judge**＝沒有標準答案時，用另一個 LLM 兩兩比較答案的評審；
> **GT**＝Ground Truth 標準答案（本 PoC 中只有事後稽核程式讀得到，演化流程完全看不到）。

---

## 1. 結論摘要

### 1.1 一句話

**整條 Build → Use → Evolve 的流程全部由 Python 跑通了，而且用真實 LLM 呼叫、真實資料跑出完整結果；
但官方意義上的「演化成功（Accept 並發佈 `ontology_v1`）」在這次實跑中沒有發生**——
兩個 Candidate 都被我設定的保守 Gate 拒絕，run 以 `incomplete / budget_exhausted` 結束，active 仍是 `ontology_v0`。
有意思的是：事後用標準答案與全新的測試題檢查，**這兩個 Candidate 其實都讓 Agent 變好**。也就是說，系統「保守地沒有發佈一個其實有益的修補」。

### 1.2 這次實跑的數字（全部來自真實執行，非模擬）

| 階段 | 結果 |
| --- | --- |
| **Build** | 產生 `ontology_v0`：30 Term／33 Mapping／25 Relation／28 Constraint／29 Evidence，通過 repo 的驗證，30 題建構題 100% 被連結 |
| **Use**（40 題線上題，Haiku Agent，v0） | **22/40 = 55%** 正確。失敗集中在：取消率 0/5、準時送達率 0/4、「改了說法的」有效訂單 3/9、優惠碼 1/4 |
| **觸發器** | 40 筆新軌跡 ≥ 30 → 觸發（`evolution_due = true`） |
| **Evolve 第 1 輪**（Content 修補，`v0-c1`） | 補上取消率／出貨／準時送達率。Gate 第 1 次重複 **5:1 通過**，第 2 次重複 **2:4 未通過** → **Reject** |
| **Evolve 第 2 輪**（Tool 修補，`v0-c2`） | 啟用「依關鍵字帶出約束」並釘選時區規則。兩次重複都通過（4:1、7:4），合併 11:5，但我預先設定的「退步規則」否決 → **Reject** |
| **Run 結局** | 預算 2 輪用完 → `incomplete / budget_exhausted`；沒有 `ontology_v1` |
| **事後稽核（標準答案）** | 在 Reserve 12 題上，**Parent 8/12、兩個 Candidate 都 10/12**（4 次重複全部一致）。以標準答案做 Gate，兩個 Candidate 每次重複都會被 Accept |
| **全新測試題 16 題**（演化期間從未出現） | v0 **8/16**；v0-c1 **13/16**；v0-c2 **12/16**；兩個 Candidate 修好的題目類別互補 |
| **LLM Judge 的表現** | 8 組「標準答案說 Candidate 贏」的配對中，Judge 抓到 7 組；但在 40 組「標準答案說平手」的配對中，Judge 有 10 組判 Parent 贏、11 組判 Candidate 贏 → **Judge 在差異很小時主要在放大雜訊** |
| **成本** | 約 **US$9.83**（API 牌價估算，**不是帳單**；原本上限 US$5，已超出，原因見 §9.1） |

### 1.3 你最需要知道的五件事

1. **沒有真的呼叫 OpenRouter。** 這台機器沒有金鑰，你選擇用 `claude -p` 暫代。所以所有結果是 **Claude Haiku／Sonnet／Opus** 的表現，
   **不是開源模型**。OpenRouter 後端已寫好、並以本機模擬伺服器驗證過請求格式與成本解析，但**從未連到真實服務**。
2. **Accept（發佈新版）這條路徑在「實跑」中沒有被走到。** 我用三種方式驗證它：假 LLM 的完整 dry-run（真的走到 Accept）、單元測試、
   以及在**工作區副本**上餵入第 2 輪已記錄的評審結果（反事實）。三者都成功發佈 `ontology_v1`，但**官方實跑的結局是 incomplete**，請勿把反事實當成實跑成果。
3. **我發現了 repo 一個值得你注意的行為**：`resolve_semantics` 只會回傳「`target` 等於被解析 Term 的 id」的約束。
   repo 的 schema 文件明文允許約束指向 Term 或 Mapping；Build 階段的 LLM 把 28 條約束中的 **15 條**指向了 **Mapping**（包含最關鍵的時區規則 `con_tz_order_time`），所以這 15 條約束
   **在 `resolve` 時永遠不會被帶出來**（只有 Agent 剛好用 `browse` 搜到才看得到）——規格與 runtime 之間有落差。Evolver 沒有診斷到這件事，而是用「依關鍵字帶出」的 Tool 旋鈕繞過。詳見 §6.4。
4. **有幾個事後才發現的瑕疵**，已修正或已揭露（§9、附錄 C）：`claude -p` 的記憶檔洩漏（內容只有專案描述，不含任何領域答案）、
   6/48 的 Judge 回覆不是 JSON 被當成平手（重評後沒有任何正式決定改變）、機制驗證選錯重播題目等。
5. **這是單一設計情境、單一樣本、小樣本的 PoC。** 它證明「流程可以端到端運作、每個環節的輸入輸出長什麼樣」，
   **不證明**「EvoOntology 的演化在你的真實資料上會提升多少」。

---

## 2. EvoOntology 到底怎麼運作

> 這一章整理「官方 plugin 的每一步實際發生什麼事」。依據是 repo 的原始碼與 skill 文件。
> 第 3 章再說明「本 PoC 的 pipeline 如何把這些步驟變成 Python 程式」。

### 2.1 一句話與全貌

EvoOntology 把「業務知識」存成一份**有版本號、有證據的語意層（ontology layer）**，讓 Data Agent 用兩個工具按需查詢；
再用 Agent 的使用軌跡，定期**提出修補 → 與舊版比較 → 通過才發佈新版**，讓語意層自己變好。

```mermaid
flowchart LR
    subgraph B["① Build（只做一次）"]
        B1["設定專案"] --> B2["載入工作負載"] --> B3["資料探勘 + 驗證文件"] --> B4["語意設計<br/>五類物件"] --> B5["存版本→驗證→標註→發佈<br/>ontology_v0"]
    end
    subgraph U["② Use（持續）"]
        U1["Data Agent 回答問題<br/>resolve / browse + SQL"] --> U2["記錄軌跡<br/>trajectories/"]
    end
    subgraph E["③ Evolve（觸發後）"]
        E0["Step 0 凍結批次<br/>切 Pool / Reserve"] --> E1["Step 1 診斷"] --> E2["Step 2 歸因"] --> E3["Step 3 修補<br/>產生 Candidate"] --> E4{"Step 4 Gate<br/>Parent vs Candidate"}
        E4 -- "Accept" --> E5["發佈 ontology_vN+1<br/>推進檢查點"]
        E4 -- "Reject" --> E1
        E4 -- "預算用完/外部阻礙" --> E6["Incomplete<br/>保留 Parent"]
    end
    B5 --> U1
    U2 --> T{"觸發器<br/>≥30 新任務 或 ≥7 天"} --> E0
    E5 --> U1
```

### 2.2 三層（Content / Schema / Tool）與五類物件

EvoOntology 把「可以演化的東西」分成三層：

| 層 | 是什麼 | 在本 PoC 裡對應 |
| --- | --- | --- |
| **Content Layer（內容層）** | 業務知識本身：Term／Mapping／Relation／Constraint／Evidence 五類物件 | `versions/<v>/*.json` 的五個檔案 |
| **Schema Layer（規格層）** | 這五類物件「長什麼樣子、哪些欄位合法」的規格與驗證器 | repo 的 `ontology-schema.md` 與 `validate.py`；**PoC 不演化這層**（D6） |
| **Tool Layer（工具層）** | Agent 怎麼取用：manifest（開場說明）、`resolve_semantics`／`browse_semantics` 的行為 | repo 的 `SemanticLayer`；PoC 以 `tool_config.json` 旋鈕表達可演化的部分（D5） |

五類物件（每一類各是一個 JSON 檔）：

| 物件 | 回答什麼問題 | 重要欄位 |
| --- | --- | --- |
| **Term** | 這個詞是什麼意思？ | `name`、`type`（entity／dimension／metric／concept／category）、`definition`、`aliases`、`evidence` |
| **Mapping** | 這個詞對應資料庫哪個欄位？ | `term_id`、`table`、`column`、`semantic_filter`、`aggregation_semantics`、`grain` |
| **Relation** | 詞和詞之間什麼關係？ | `source`、`target`、`relation_type`（5 種之一，如 `hierarchy`） |
| **Constraint** | 使用時有什麼規則、陷阱？ | `target`、`constraint_type`、`trigger_keywords`（必填）、`severity`（`block`／`warning`／`info`）、`description` |
| **Evidence** | 這些主張的證據？ | `query`（可重現的 SQL 或文件引文）、`result`、`validation_method` |

### 2.3 workspace 與檔案：每一步在磁碟上留下什麼

`.evoontology/` 是整個系統的狀態（程式碼：`evoontology/workspace.py`、`ontology/store.py`）：

| 路徑 | 誰寫入 | 內容 |
| --- | --- | --- |
| `project.json` | Build Step 0（`configure_ontology_project`） | `mode`（`fixed_split`／`rolling_trajectory`）、資料來源、工作負載來源、評估方式（`llm_judge`／外部評估器）、資料邊界 |
| `workload/questions.json` | `prepare_ontology_workload` | 建構題，去重並記錄來源（user＞history＞generated） |
| `versions/ontology_vN/` | `save_version`／`accept_evolution` | 5 個 JSON：terms／mappings／relations／constraints／evidence |
| `versions/vN-cK/` | 演化時 `save_version` | **Candidate**：第 K 個從 vN 演化出的候選；Gate 通過前不得動 `active.json` |
| `active.json` | `publish_ontology_build`／`accept_evolution` | `{"active_version": "ontology_v1"}`，Agent 預設載入的版本 |
| `state.json` | `publish_ontology_build` 初始化、`accept_evolution` 推進 | 演化觸發器的檢查點：`checkpoint_trajectory`、`checkpoint_time`、`thresholds`（預設 30 個任務／7 天） |
| `reports/<version>.json` | `annotate_ontology_version` | 摘要、已知限制、題目→語意物件的連結 |
| `trajectories/<task_id>.json` | Data Agent 端（adapter）呼叫 `TrajectoryStore.append` | 每個任務一檔：問題、版本、語意呼叫（輸入+結果）、原生工具呼叫（結果截斷到約 2 KB／20 行）、最終答案、狀態、錯誤；**不存思考鏈** |
| `evolution/run_N/run.json` | `start_evolution_run` 起，每次狀態變更都更新 | 狀態（running／accepted／incomplete）、Parent、目前 Candidate、輪數、**凍結的預算**、驗收標準、`accepted_version`、`end_reason` |
| `evolution/run_N/rounds.jsonl` | `record_evolution_round` | 每個被拒絕的輪次一行：假說、Candidate、指標、決定、備註 |
| `evolution/run_N/evaluations/` | `record_evolution_evaluation` | Parent／Candidate 正式評估的穩定摘要，含 **`gate_input`** |
| `evolution/run_N/trajectory-sources.json` | `confirm_trajectory_sources` | 這次 run 用到的軌跡來源（只記路徑，不複製檔案） |
| `visualizations/*.html` | `visualize_ontology`／`finalize_evolution_run` | 離線 HTML 探索器，可切換版本並排比較 |

### 2.4 Build（簡述；細節見 PoC 1 報告第 2.6 節）

Build 把題目與資料變成 `ontology_v0`。skill 把它分成：

1. **Step 0** 解析並保存專案設定、載入工作負載（使用者題目＞專案歷史＞由資料證據生成的題目，Core 自己不生成題目）。
2. **Step 1** 以工作負載為導向探勘資料：逐一驗證業務文件的主張、檢查候選欄位、記錄「為什麼不選競爭欄位」；資料無法佐證的主張不得直接採信。
3. **Step 2** 產生 Term／Mapping／Relation／Constraint／Evidence；驗證；保存；標註；發佈。
   物件只能含 schema 定義的欄位，**不得放 SQL 範本或解題步驟**；Constraint 必須有 `trigger_keywords`。

發佈後 `state.json` 的觸發器被初始化，`ontology_v0` 成為 active。

### 2.5 Use 與 Record：Evolve 的原料從哪來

Agent 開場看到 manifest（物件統計 + 工具說明），之後用 `resolve_semantics`／`browse_semantics` 取得欄位對應與規則，再自己寫 SQL 驗證。
每個任務結束後，由 Agent 執行端（官方的 benchmark adapter，或 host agent 呼叫 `start/finish_ontology_task`）把任務寫成一份**軌跡**：

```text
task_id / question / ontology_version / split
semantic_calls   : [{tool, input, result}]               ← 語意工具：存輸入與完整結果（診斷要看「問了什麼、命中什麼」）
native_tool_calls: [{tool, input, result(截斷), result_truncated, result_summary}]
final_answer / task_status(completed|failed|interrupted) / errors
```

**兩個語意工具實際怎麼運作**（`evoontology/runtime/runtime.py`）：

- `resolve_semantics(mentions, context)`：對每個提到的詞，用**精確的名稱／別名比對**找 Term；找到就回傳該 Term 的 Mapping、Relation、**`target` 等於該 Term id 的 Constraint**、Evidence；找不到回 `unresolved`。**不做模糊比對，也不看 `trigger_keywords`。**
- `browse_semantics(query, kind)`：依關鍵字搜尋物件（可限定 term／mapping／relation／constraint），回傳清單。搜尋的文字包含物件的名稱、定義、別名，**以及約束的 `trigger_keywords`**——所以 `trigger_keywords` 只在 Agent 主動 `browse` 時才有作用。

> 這兩個行為細節（精確比對、`trigger_keywords` 在 `resolve` 時不參與、只回傳 `target == term_id` 的約束）
> 是後面 §5、§6 許多現象的根源，請記住。

**觸發器**（`trigger/trigger.py`）只決定「要不要提醒你演化」，不會自己啟動：自上次檢查點起**新增 ≥30 個任務，或距上次 ≥7 天**。

### 2.6 Evolve：官方流程逐步拆解

#### Step 0 — 解析並凍結演化上下文

1. 讀取 `project.json`、Parent（目前 active 版本）、最近的檢查點。
2. **決定這次 run 的資料**（`ontology-layer-data-boundary.md`）：
   - `fixed_split`：沿用固定切分（資料集切 Fold A／B，A 再切 70% 演化訓練／30% 驗證，B 當最終測試）。
   - `rolling_trajectory`（**本 PoC 使用**）：蒐集檢查點之後的合格軌跡 → **凍結這一批** → 先把重複／近似重複的題目分組，
     再**依時間順序**切成 **Evolution Pool（前 70%）** 與 **Validation Reserve（後 30%）**，同一組不得跨越兩邊。
3. 固定評估器與驗收標準；**預算**（`quick`＝2 輪，`full`＝8 輪，預設 8）在此凍結，之後不得為了讓結果好看而改。
4. `start_evolution_run` 寫出 `run.json`（Parent、adapter、預算、驗收標準）；`confirm_trajectory_sources` 記錄軌跡來源。

> **資料隔離是整個設計的核心**：Pool 可用於診斷、歸因、設計、重播；**Reserve 只能用在最終的 Parent／Candidate 比較**，
> 且題目、評審理由、驗證結果都不得回流到 Candidate 的設計。Ground Truth 只有評估器能碰。

#### Step 1 — 診斷（Diagnose）

不只看失敗，也要找「系統**應該做到卻沒做**」的地方。skill 要求的動作：比較成功／失敗／改善／退步的案例；
檢查分析覆蓋（哪些維度、指標、概念從未被探索）；檢查工具能力；檢查結構限制；用代表性任務或反事實問題主動測試。
產出一份**問題地圖**：明確的執行失敗、覆蓋不足、工具或流程限制、系統結構限制、待驗證的潛在缺口——每一項都保留症狀、證據、因果假說與不確定性。

#### Step 2 — 歸因（Attribute）

把每個高價值問題歸因到最相關的一層，並判斷性質：

| 層 | 問題長相 | 性質 |
| --- | --- | --- |
| **Content** | 知識錯誤、不完整、粒度不當、涵蓋不足 | 現有設計錯誤／缺少能力或涵蓋 |
| **Tool** | 工具能力、介面、檢索、排序、回傳內容限制了使用 | 同上 |
| **Schema** | 物件模型無法可靠表達需求 | 結構不合 |

要求產生**彼此競爭**的因果解釋，用軌跡、成功案例、反例與針對性測試比較；分開「獨立根因」與「下游症狀」。
**不能因為某個修補容易做就接受它的解釋。**

#### Step 3 — 修補（Patch）

選出目前最值得驗證的機制，寫成**可被證偽的假說**（目前的限制、為何造成問題、修補後預期行為、什麼證據會推翻它）。
一個 Candidate 只驗證**一個主要假說**；修補要局部、可回復、不得靠停用或繞過 ontology 來「改善」。
Candidate 存成 `versions/vN-cK/`，並先做**機制驗證**：跑代表性案例或針對性重播，確認被修補的機制真的改變了行為，之後才進入正式比較。

#### Step 4 — Gate：Parent vs Candidate

在受控條件下比較（同輸入、同資料切分、同模型、同評估器、同預算）；Candidate 是自己的版本，比較期間不得動 `active.json`。

| 評估協定 | 何時用 | Accept 條件（寫在程式裡，`evaluation/evaluation.py`） |
| --- | --- | --- |
| Ground truth | 有標準答案（`fixed_split` 的 benchmark） | Candidate 平均分**嚴格大於** Parent |
| **LLM Judge**（本 PoC 使用） | 沒有標準答案（`rolling_trajectory`、正式環境） | `E_c == 0` **且** `W_c > W_p`：Candidate 沒有任何嚴重錯誤，且勝場嚴格多於 Parent |

LLM Judge 的規格（`docs/evaluation-protocol.md`）：輸入 `(question, answer_A, answer_B)`，**A／B 隨機指派**使其不知道誰是 Parent；
輸出 `{winner: A|B|tie, reason, critical_error}`；評審必須**獨立於 Evolver**（不同模型實例、憑證與上下文）。
評審看不到標準答案，所以只能從四點判斷：有沒有回答問題、結論是否自洽且無明顯錯誤、支撐的資料與計算是否可驗證、關鍵面向是否涵蓋。
Gate 刻意保守：平手不計分，所以大量平手會自然地**保留 Parent**。

**發佈前的「發佈閘」**（`EvolutionSession._publication_gate`）：`accept_evolution` 會**重新計算** Gate，而且要求：
`record_evolution_evaluation` 已為這個 Candidate 與這一輪記錄 `gate_input`；`gate_input.unacceptable_regressions` 明確為 `false`；
`protocol` 必須等於 run 凍結的驗收協定；Judge 協定需要非空且格式正確的 verdicts。任何一項缺少就拒絕發佈。

驗證集很小時，skill 要求**重跑評估，確認改善不是單次運氣**。

#### 結果與狀態機

```mermaid
stateDiagram-v2
    [*] --> running: start_evolution_run（凍結預算）
    running --> running: Reject → record_evolution_round → 下一個 Candidate
    running --> accepted: Accept → 發佈 ontology_vN+1、切換 active.json、推進檢查點
    running --> incomplete: 預算用完（begin_evolution_round 自動觸發）
    running --> incomplete: 使用者中斷／缺權限（立即）
    running --> incomplete: 缺資料／評估不可靠／外部阻礙（須先累積 ≥2 次 Reject）
    accepted --> [*]
    incomplete --> [*]
```

- **單一 Reject 絕不結束 run**；Reject 的 Candidate 與輪次紀錄保留供稽核，檢查點不推進。
- **Accept** 做的事（`EvolutionSession.accept`）：驗證 Candidate 可載入 → 重算發佈閘 → `SemanticStore.publish`（複製成 `ontology_vN+1`，**不覆蓋**既有版本）→
  切換 `active.json` → `advance_checkpoint`（同一批軌跡不會被重複拿來演化）。
- **Incomplete** 不切換 active、不推進檢查點，同一批會在下一次 run 重試。
- `finalize_evolution_run` 在任一終止狀態後渲染 HTML（Results & questions：run 狀態、評估指標、公開任務重播；**驗證題不會被嵌進頁面**）。

#### 禁止事項（skill 的 Research Integrity）

不得修改 benchmark 題目、Ground Truth、標籤、評估器、資料切分、驗收標準；不得把標準答案或任務專屬的正確值寫死；
領域知識必須存放在可追溯、有版本的語意物件，不得藏進 prompt、Builder 程式或編排邏輯。

### 2.7 官方 plugin 模式 vs 本 PoC 的 pipeline：誰做每一步

| 步驟 | 官方 plugin（Claude Code／Codex） | 本 PoC pipeline |
| --- | --- | --- |
| 流程控制（先做什麼、何時停） | LLM agent 讀 SKILL.md 後自己決定 | **Python 程式**（`build.py`／`evolve.py`），LLM 不控制流程 |
| 資料剖析 | Builder 手寫約 60 條 SQL | **程式**（`profile.py`） |
| 驗證文件主張、提出證據 | Builder 自己下 SQL 並寫 Evidence | LLM 只提出查詢；**程式執行查詢並寫入結果**（`records.materialize_evidence`） |
| 語意設計 | Builder 直接寫 JSON | LLM 產 JSON → **程式逐條檢查 schema 規則**，不過就退回重寫 |
| 診斷／歸因 | Evolver agent 用 Bash/SQL 探索 | 同樣由 LLM 判斷，但在 Python 控制的工具迴圈裡，**資料邊界由程式強制** |
| 修補 | Evolver 直接改檔案（含程式碼） | LLM 提出**有型別的修補操作**，程式套用到 Parent 的複本 |
| Gate／Judge／狀態機 | core 函式（Evolver 呼叫） | **同一組 core 函式**（直接 import） |
| Tool Layer 的演化 | 允許 agent 改 runtime／prompt／workflow 程式碼 | **宣告式旋鈕**（`tool_config.json`），見 §3.4 |

---

## 3. 本 PoC 的 pipeline 怎麼設計

### 3.1 你的要求，與我怎麼落實

| 你的要求 | 落實方式 | 實際狀態 |
| --- | --- | --- |
| 整個流程是 deterministic pipeline，由 Python 控制 | `evopipe/` 只用 Python 標準庫；**流程順序、迴圈、停止條件、資料切分、版本命名、Gate、發佈全部由程式決定**。LLM 只回答「這一步需要判斷的問題」，不決定下一步 | ✅ 做到 |
| 需要 LLM 的地方一律走 OpenRouter | 全部 LLM 呼叫集中在 `llm.py` 的**唯一入口** `LLM(role).chat()`，後端可抽換 | ⚠️ **部分**：OpenRouter 後端已寫好並以本機模擬 server 驗證協定，**但沒有金鑰，沒有真的打過 OpenRouter**；實際用 `claude -p` 暫代（§3.5） |
| 之後不再透過 Claude Code／Codex 執行 | pipeline 不依賴 plugin、MCP、skill 載入機制；repo 的 `evoontology` 核心以 **import** 使用 | ✅ 除了「暫代後端」`claude -p`（被限制成純文字補全） |
| 要確實依 repo 做法，不要自己設計不同的做法 | (a) 狀態、版本、軌跡、觸發器、Gate、演化狀態機**全部呼叫 repo 原本的函式**，不重寫；(b) repo 的 `SKILL.md` 與 `ontology-schema.md` **原文**放進 LLM 的 system prompt；(c) 偏離之處列在 §3.4 | ✅ 做到，13 項偏離已列出 |
| 想到你未來會重寫並客製化 | 每個階段是獨立、可單獨執行、可續跑的函式；prompt 是獨立 `.md`；參數集中在 `config.py`；LLM 輸出先經程式驗證才落地；中間產物全部存檔 | ✅ |
| 你只讀報告 | 本報告列出每一步的輸入、LLM 看到什麼、輸出什麼、程式怎麼檢查、磁碟留下什麼，並附真實內容 | ✅（§5） |

### 3.2 架構

```mermaid
flowchart TD
    CLI["cli.py<br/>build · use · evolve · test · cost"] --> BLD["build.py<br/>B0–B4"]
    CLI --> USE["runner.py + use.py<br/>Data Agent × N 題"]
    CLI --> EVO["evolve.py<br/>E0–E5"]
    BLD --> PRF["profile.py<br/>資料剖析（純程式）"]
    BLD --> REC["records.py<br/>檢查 · 證據實體化 · 修補操作"]
    EVO --> REC
    EVO --> JDG["judge.py<br/>匿名 A/B 評審"]
    USE --> AG["agent.py<br/>JSON 工具迴圈"]
    BLD --> AG
    EVO --> AG
    AG --> TOOLS["tools_data.py<br/>sql_query · get_schema · read_doc"]
    AG --> SEM["semantic.py<br/>TunedSemanticLayer<br/>= repo 的 SemanticLayer + tool_config"]
    AG --> LLM["llm.py：唯一的 LLM 入口<br/>ledger（成本）· 重試 · 全文記錄"]
    JDG --> LLM
    BLD --> LLM
    EVO --> LLM
    LLM --> BK1["OpenRouterBackend<br/>（正式；僅協定測試）"]
    LLM --> BK2["ClaudeCliBackend<br/>（暫代；claude -p，工具/記憶/設定全關）"]
    BLD --> CORE["core.py → repo 的 evoontology.runtime.ops<br/>（28 個確定性操作）"]
    EVO --> CORE
    USE --> TRJ["repo 的 TrajectoryStore / from_message_trace"]
    CORE --> WS[(".evoontology/<br/>versions · state · trajectories · evolution")]
    TRJ --> WS
    AUD["audit.py · analyze*.py<br/>私有標準答案（事後稽核，流程完全不碰）"] -. "只讀" .-> WS
```

**「確定性」的意思**：給定同樣的輸入檔與同樣的 LLM 回覆，pipeline 的控制流程、資料切分、A/B 隨機化（以固定 seed 產生）、Gate 計算、
版本命名與檔案內容都完全相同。LLM 本身不是確定性的（`claude -p` 無法設定 temperature），所以**重跑不會得到一模一樣的結果**；
但每個階段都有檔案快取，**已完成的階段重跑時直接讀檔，不再呼叫 LLM**（見 §3.7）。

### 3.3 每個 LLM 呼叫點（一覽）

下表是 pipeline 中**所有**會呼叫 LLM 的地方。其餘一切都是確定性程式。

| 階段 | 角色（實際使用的模型） | LLM 看到什麼 | LLM 產出什麼 | 程式怎麼檢查／處理產出 |
| --- | --- | --- | --- | --- |
| B2 探勘 | builder（Sonnet） | repo 的 Step 1 原文；建構題；業務文件；程式產生的資料剖析；工具 `sql_query`／`read_doc`／`get_schema` | 證據提案（查詢或文件引文 + 主張） | **程式執行每條查詢並寫入真實結果**；引文必須是文件逐字摘錄；失敗者丟棄 |
| B3 設計 a／b | builder（Sonnet） | repo 的 Step 2 原文 + `ontology-schema.md` 全文；題目；文件；剖析；已驗證證據 | a：Terms+Mappings；b：Relations+Constraints+限制+摘要（JSON） | `records.check_records`（見下）；不過就帶著錯誤清單退回重寫，最多 2 次；Mapping 缺漏另有「針對性補填」 |
| E1 診斷 | evolver（Sonnet） | repo 的 Step 1 原文與原則；**Pool** 軌跡；語意層目錄；剖析；文件；工具 `probe_semantics`／`sql_query`／`read_doc` | 問題地圖（JSON） | 程式把 `affected_tasks` 過濾成只剩 Pool 內的題目 |
| E2 歸因 | evolver（Sonnet） | repo 的 Step 2 原文；問題地圖；目錄；探測工具 | 競爭的因果假說、維度、主要假說 | 只檢查格式；`primary` 必須存在 |
| E3 修補 | evolver（Sonnet） | repo 的 Step 3 原文；主要假說；Parent 全部物件；Tool 設定；可用操作清單 | 有型別的修補操作（JSON） | 套用到 Parent 複本 → schema 檢查 → 證據由程式實際執行 → 不得是空修補；有錯就退回，最多 3 次 |
| E4 重播／Gate 的 Agent | agent（Haiku；Use 階段與所有 Gate 重複都是 Haiku） | Data Agent 說明；manifest；工具 | 工具呼叫序列與最終答案 | `from_message_trace` 正規化成軌跡 |
| E4 評審 | judge（Opus 46 次 + Sonnet 2 次） | 評審準則；問題；匿名的答案 A／B；各自執行的 SQL 與結果片段 | `{winner, reason, critical_error}` | repo 的 `EvaluationGate.decode` 解匿名；`decide_judge` 聚合；**格式不符會重問，最多 3 次，仍失敗就中止（不會當成平手）** |
| 事後測試題 | agent（Sonnet） | 同 Data Agent | 同上 | 用私有 GT 比對 |

**`records.check_records` 檢查的規則**（對應 `ontology-schema.md`，且比 repo 的 `validate_semantics` 更嚴）：
id 全域唯一；Term 型別、名稱、定義、至少一個證據；**只允許 schema 定義的欄位**（多餘欄位如 `definity` 會被擋）；
entity／dimension／metric 型 Term **必須至少有一條 Mapping**；Mapping 的 `table`／`column` 必須是**資料庫裡真實存在**的；
Relation 型別只能是 5 種、兩端必須是 Term；Constraint 的 `trigger_keywords` 非空、`severity`／`confidence`／`constraint_type` 在受控詞彙內；
所有證據引用必須存在；任何文字欄位出現 SQL 語句即拒絕。另有 `unreachable_constraints` 提示（目標不是 Term 的約束，見 §6.4）。

### 3.4 與官方做法不同的地方（偏離清單）

誠實列出，每一項都說明為什麼：

| # | 偏離 | 官方做法 | 為什麼 | 對你的意義 |
| --- | --- | --- | --- | --- |
| D1 | LLM 後端是 `claude -p`，不是 OpenRouter | （官方是 Claude Code／Codex 本身） | 這台機器沒有 OpenRouter 金鑰；你選擇先用 `claude -p` 暫代 | 所有結果是 **Claude Haiku／Sonnet／Opus** 的表現，不是開源模型；換成開源模型後的品質未知。後端已抽換化，換金鑰即可跑 |
| D2 | 工具協定是**文字 JSON**（`{"thought","tool","args"}`），不用原生 function calling | Claude Code 內建工具呼叫 | 讓任何聊天模型（含開源模型）都能用，重寫時不綁特定 API | 開源模型可能輸出格式不穩，`agent.py` 內建「格式錯誤重試」 |
| D3 | 證據的 `result` 由程式執行查詢後填入 | Builder agent 自己下 SQL 並手寫 Evidence | 避免幻覺；PoC 1 的 Builder 也回報這是可固定程式的部分 | 這是**改進**；但證據只能是「單條可重現查詢／文件引文」的形式 |
| D4 | 修補以「有型別的操作」表達，由程式套用 | Evolver 直接改檔案（甚至程式碼） | pipeline 不能讓 LLM 任意改 Python；操作式修補可驗證、可回復、可 diff | 修補的表達力受操作清單限制（共 8 種：`add_alias`／`add_term`／`add_mapping`／`add_relation`／`add_constraint`／`update_field`／`add_evidence`／`set_tool_config`；**沒有刪除物件的操作**） |
| D5 | **Tool Layer 以宣告式旋鈕演化**（`versions/<v>/tool_config.json`） | 允許 agent 改 runtime／prompt／workflow 的程式碼 | 同 D4。三個旋鈕：`resolve.trigger_keyword_constraints`、`resolve.fuzzy_fallback`、`manifest.pinned_constraint_ids`。`SemanticStore.publish` 會複製整個版本資料夾，所以設定隨版本一起走，**不需改 core** | 這是我的擴充，**不是 repo 行為**。你重寫時要決定 Tool Layer 怎麼表示 |
| D6 | **Schema Layer 的演化沒有實作** | 允許 | 改 schema 等於改規格文件與檢查器，不適合自動化 PoC | 歸因階段仍可歸因到 schema（本次 H5），但修補階段只能執行 content／tool |
| D7 | `sql_query` 的執行量上限放寬為約 6 千萬 VM 步 | core 的 `execute_query` 約 100 萬步 | PoC 1 發現 core 的上限會中斷合理的彙總查詢 | 若用 core 的原函式，Builder 會遇到同樣問題 |
| D8 | Judge 除了問題與答案，還看到各方**執行的 SQL 與結果片段** | 協定說工具證據「可選」 | 只給兩個數字的評審什麼都判斷不了；語意工具呼叫**不**給評審看，所以它猜不出誰用了 ontology | 屬協定允許的選項；但這也是 Judge 偏好「驗證較多」的原因之一（§6.3） |
| D9 | 「不可接受的退步」由程式規則判定：Candidate 有任何嚴重錯誤，**或 Parent 勝場 × 3 > Candidate 勝場** | 留給 Evolver agent 判斷 | pipeline 需要確定性規則；這在 run 開始時就寫進 `run.json` 並凍結 | **這是我定的政策，不是 repo 的**；在本次實跑中它是第 2 輪被否決的唯一原因（§6.5） |
| D10 | 驗證集太小時的「重跑確認」實作成**第二次獨立重複** | skill 只說要重跑確認 | 需要具體做法：第一次 Accept 後，用全新的 Agent 執行與新的 A/B 隨機化再評一次，**兩次都要 Accept**；第一次沒過就不做第二次 | 讓 Gate 更保守 |
| D11 | 預算 **2 輪**（quick profile） | 預設 8 輪（quick＝2、full＝8） | 控制成本 | 預算在 run 開始時凍結 |
| D12 | 題目串流的「到達順序」是我安排的 | 真實系統只是依時間 70/30 切 | 讓 Reserve 涵蓋每一類題目，否則某些修補無法被驗證 | 實驗設計，不是系統行為（§4.4） |
| D13 | 任務軌跡由 adapter 風格的程式寫入（`from_message_trace` + `TrajectoryStore.append`），不走 `start/finish_ontology_task` | 兩條路都存在：benchmark adapter 與 host agent 工作流 | pipeline 本來就是 adapter 角色 | 與 `trajectory-format.md` 的說明一致 |

### 3.5 LLM 後端：為什麼這樣設計

```text
                 ┌──────────────── LLM(role).chat(stage, system, messages) ─────────────────┐
 build/evolve/   │  1. 預算檢查（累計成本 ≥ 上限 → 中止）                                      │
 use/judge  ───▶ │  2. backend.complete(model, system, messages)   ← 唯一會連到外部的地方         │ ───▶ 文字
                 │  3. 失敗重試（指數退避）；額度用盡 → LLMUnavailable（階段可續跑）               │
                 │  4. 寫 ledger（tokens、成本、延遲）+ 完整 prompt／回覆存檔                       │
                 └───────────────────────────────────────────────────────────────────────────┘
```

| | OpenRouterBackend（正式） | ClaudeCliBackend（暫代，實際使用） |
| --- | --- | --- |
| 呼叫方式 | `POST {base}/chat/completions`，`Authorization: Bearer`，`temperature=0`，`usage:{include:true}` | `claude -p --tools "" --system-prompt … --output-format json --no-session-persistence --strict-mcp-config --disable-slash-commands --setting-sources ""`，工作目錄為 repo 外的暫存資料夾 |
| 效果 | 標準 OpenAI 相容聊天 | **純文字補全**：沒有工具、沒有專案設定；每次呼叫約 600 token 固定開銷 |
| 成本計量 | 回應的 `usage.cost` | JSON 的 `total_cost_usd`（**API 牌價估算，不是帳單**） |
| 驗證狀態 | 以本機 `http.server` 模擬 OpenRouter，驗證請求路徑、標頭、body 與成本解析（單元測試）；**未連線過真服務** | 實際使用 |
| 金鑰 | 環境變數 `OPENROUTER_API_KEY` 或 `poc/.env`；不記錄、不輸出 | 不需要 |
| 取樣 | `temperature=0` | 無法設定溫度 → 結果有隨機性 |

換到 OpenRouter 時：設好金鑰、`EVOPIPE_BACKEND=openrouter`、在 `config.py` 的 `OPENROUTER_ROLE_MODELS` 指定每個角色的模型即可。
我預設填的模型 id（Qwen3 等）是**占位**，未用金鑰驗證過是否可用、是否支援你需要的輸出格式。

### 3.6 Agent 工具迴圈（`agent.py`）

每一輪模型必須回覆**一個 JSON 物件** `{"thought", "tool", "args"}`；Python 執行工具、把結果放進下一則訊息；模型呼叫「最終工具」（如 `submit_answer`）或達到步數上限（`AGENT_MAX_STEPS = 10`）即結束。

- `thought` 只用來讓模型先想一句，**不存進軌跡**（`trajectory-format.md`：不存思考鏈）。
- 格式錯誤會回饋給模型重試，連續 3 次失敗才放棄；未知工具、工具例外都以 `{"error": …}` 回給模型，不會讓流程崩潰。
- 一次只能呼叫一個工具，所以不會再出現 PoC 1 中「把送出答案和最後查詢並行」的問題。
- 工具結果給模型看時截斷到 3,500 字元；寫入軌跡時另有 2 KB／20 行的上限。
- Data Agent 的工具：`resolve_semantics`、`browse_semantics`（repo 的語意工具）、`sql_query`（可一次送多條）、`get_schema`、`submit_answer`。
  **Data Agent 看不到業務文件**；它只有資料庫與語意層——這正是語意層存在的意義。

### 3.7 程式碼模組地圖（`poc/v3/evopipe/`）

| 檔案 | 責任 | 用到 LLM？ | 對應 repo 的哪裡 |
| --- | --- | :-: | --- |
| `config.py` | 路徑、角色→模型、預算、所有旋鈕 | — | — |
| `llm.py` | **唯一的 LLM 入口**、兩個後端、成本帳本、JSON 解析 | ✔ | — |
| `agent.py` | JSON 工具迴圈 | ✔ | （plugin 裡由 Claude Code 本身扮演） |
| `tools_data.py` | `sql_query`、`get_schema`、`read_doc` | — | `ProjectWorkflow.execute_query` |
| `semantic.py` | `TunedSemanticLayer`（repo 的 `SemanticLayer` + `tool_config`） | — | `runtime/runtime.py` |
| `profile.py` | B1 資料剖析 | — | PoC 1 中 Builder 手寫的 SQL |
| `records.py` | 物件檢查、證據實體化、修補操作、版本 diff | — | `validate.py`（本檔規則更多） |
| `build.py` | B0–B4 | ✔ | build-ontology skill |
| `use.py`、`runner.py` | Data Agent、軌跡正規化、並行與逐題快取 | ✔ | benchmark adapter 端 |
| `evolve.py` | E0–E5（可續跑） | ✔ | evolve-ontology skill + `EvolutionSession` |
| `judge.py` | 匿名評審、退步規則 | ✔ | `docs/evaluation-protocol.md` |
| `audit.py`、`analyze.py`、`analyze_final.py`、`rejudge.py`、`counterfactual.py` | 事後稽核、重評、反事實 | 部分 | （repo 沒有，因正式環境無 GT） |
| `core.py` | 呼叫 repo 的 28 個確定性操作（**必須明確傳入 workspace**） | — | `runtime/ops.py` |
| `cli.py` | 命令列入口 | — | — |
| `prompts/*.md` | 所有 prompt（可獨立編輯） | — | skill 原文由程式在執行時載入 |

**哪些 core 操作真的被呼叫**：`configure_ontology_project`、`prepare_ontology_workload`、`save_version`、`validate_semantics`、`annotate_ontology_version`、`publish_ontology_build`、
`evolution_status`、`start_evolution_run`、`confirm_trajectory_sources`、`begin_evolution_round`、`record_evolution_evaluation`、`record_evolution_round`、
`accept_evolution`（僅 dry-run／反事實）、`mark_evolution_incomplete`、`finalize_evolution_run`，以及 `TrajectoryStore.append`、`SemanticStore`。

---

## 4. 實驗設定

### 4.1 情境：Lumo Outdoors（沿用 PoC 1 的資料庫與文件）

一家虛構的戶外裝備電商。SQLite 資料庫 `poc/data/shop_v2.sqlite`，7 張表：

| 表 | 列數 | 說明 |
| --- | ---: | --- |
| `customers` | 5,000 | 地區碼（TW-N/C/S、JP、SG）、註冊日期（台北日期）、會員等級（B/S/G） |
| `products` | 200 | 類別、牌價、是否在售 |
| `orders` | 60,000 | `order_ts`（**UTC**）、`status`（0 待付款、1 已付款、2 已出貨、3 已送達、9 已取消）、通路（web/app/store）、優惠碼 |
| `order_items` | 104,966 | 數量、**成交單價（單位：分）**（已含折扣，不是牌價） |
| `payments` | 61,319 | 付款方式、金額、付款時間（UTC）、狀態（ok/failed；一張單可能多次嘗試） |
| `refunds` | 4,039 | 品項層級退款、退款時間（UTC）、原因碼 |
| `shipments` | 44,444 | 承運商代碼（blackcat/hct/sf/post）、出貨時間、送達時間（UTC） |

業務文件 `poc/build_input_v2/domain_knowledge.md`（「業務窗口提供」）定義了報表時間規則（**時間戳都是 UTC，但報表一律用台北時間 UTC+8 劃分**）、
有效訂單、商品金額、淨營收、客單價、回購客戶、實收金額、退款金額（歸屬方式與淨營收不同）、取消率、配送天數、準時送達（≤3 天）、新註冊客戶、待出貨，以及全部代碼對照。
**Data Agent 看不到這份文件**，它只能靠語意層與資料庫；文件只有 Builder（建構時）與 Evolver（診斷時）看得到。

**設計好的「陷阱」**（要正確回答就必須知道文件規則）：UTC→台北時間換算（約 1% 的訂單會換月，含跨年）、金額單位是分且已含折扣、
退款依原訂單歸屬、取消率分母不含待付款、配送天數的期間依訂單成立時間而非出貨時間、`signup_date` 已是台北日期不需換算。

### 4.2 建構題（Build 階段，30 題 `C01–C30`，PoC 1 同一批）

涵蓋：淨營收（依季／月／地區／會員／類別）、客單價、有效訂單數、回購客戶、通路占比、退款金額、實收金額、在售商品銷量、已取消**張數**（C24）、待付款張數（C25）等。
範例：「C09 2025 年 3 月有多少張有效訂單？」「C15 2025 年 9 月的退款金額總計是多少？」「C24 2025 年第四季有多少張已取消的訂單？」

**刻意沒有問**的：取消**率**、配送天數、準時送達率、新註冊客戶、優惠碼、待出貨——這些是文件有定義、但建構題沒碰到的缺口，模擬「上線後使用者問了建構時沒想到的事」。

### 4.3 線上題串流（Use 階段，40 題 `S01–S40`，我自己生成）

由 `scenario/make_stream.py` 從資料庫以 SQL 算出標準答案（寫入私有檔 `_private/gt.json`，**只有事後稽核程式讀得到**）。
題目分三種性質（`kind`），共 12 個題型（`family`）：

| 性質 | 意思 | 題型（題數） |
| --- | --- | --- |
| `seen_reworded`（9） | 建構題問過的概念，但**換了說法**（例如「訂單成立日期」「下單」「訂單日期」） | `valid_orders`（9） |
| `combo`（9） | 建構題問過的概念的**新組合** | `net_revenue`（4）、`aov`（2）、`repeat`（1）、`refund`（1）、`collected`（1） |
| `unseen`（22） | 文件有定義、建構題**完全沒問過** | `cancel_rate`（5）、`ship_days`（4）、`ontime`（4）、`new_customers`（4）、`coupon`（4）、`pending_ship`（1） |

範例：「S35 2025 年 11 月整體取消率是多少？」「S31 黑貓宅急便 2025 年第一季的準時送達率是多少？」「S38 2025 年 1 月份的有效訂單總數為多少？」「S34 2025 年第一季有效訂單中，使用 WELCOME10 的占比是多少？」

### 4.4 為什麼要安排「到達順序」（偏離 D12）

rolling_trajectory 依時間 70/30 切 Pool／Reserve。若隨機排列，Reserve（最後 12 題）可能完全沒有某個題型，那針對該題型的修補就**無法被 Gate 驗證**。
所以我把串流**分層排序**：前 28 題（S01–S28）是 Pool，最後 12 題（S29–S40）是 Reserve，Reserve 涵蓋
net_revenue、aov、ontime、new_customers、valid_orders×3、coupon、cancel_rate、ship_days、refund、collected。
這讓實驗可以回答問題，但**在真實系統裡你得不到這種保證**（§9）。另外，因為 40 題之間沒有近似重複（Jaccard ≥ 0.85），近似重複分組沒有實際改變切分（40 題＝40 組）。

### 4.5 全新測試題（16 題 `T01–T16`）

最後一道獨立檢查：16 題**從未出現在 Build、Use、Evolve 的任何環節**（含 prompt），事後才拿來測 `ontology_v0`、`v0-c1`、`v0-c2` 三個版本。
性質：`seen_reworded` 4、`combo` 2、`unseen` 10。

### 4.6 評分方式（事後稽核）

答案取第一個數字，依題型比對：計數完全相等；金額誤差 ≤ 0.05%；比率／平均值誤差 ≤ 0.06（標準答案四捨五入到 1–2 位）；任務狀態必須是 `completed`。

### 4.7 模型分配（實際用的）

| 角色 | 實際模型 | 用在哪 | 備註 |
| --- | --- | --- | --- |
| builder | Claude Sonnet 5.5 | Build 探勘與設計 | |
| evolver | Claude Sonnet 5.5 | 診斷、歸因、修補 | |
| agent（Use 階段與所有 Gate 重複） | Claude **Haiku** 5.5 | 40 題線上題 + 機制重播 + 4 次 Gate 重複的 Parent/Candidate 執行 | 為了省錢 |
| judge | Claude **Opus** 5.5（46 次）+ Sonnet 5.5（2 次） | 48 組配對評審 | 與 Evolver 不同模型、不同上下文；最後 2 次改用 Sonnet 是因預算中斷後依你「都用 Sonnet」的指示 |
| agent（事後測試題） | Claude **Sonnet** 5.5 | 16 題 × 3 版本 | 依你的指示改用 Sonnet；三個版本用同一個 Agent，彼此可比 |

> ⚠️ 因此 **Use／Gate 用的是 Haiku Agent，測試題用的是 Sonnet Agent**。兩者數字不能直接相減，但各自內部（同一 Agent 比較不同版本）是公平的。

### 4.8 預算與成本

原定上限 US$5；實際 **US$9.83**（API 牌價估算，由 `claude -p` 回報的 `total_cost_usd` 累加，**不是你的實際帳單**）。
超出原因見 §9.1。

---

## 5. 實跑紀錄：每一步實際發生了什麼

> 本章是整份報告最重要的部分。**以下所有內容都來自真實執行的檔案**（`poc/v3/workspace/.evoontology/` 與 `poc/v3/runs/`），不是示意。
> 引用的 LLM 輸出為節錄（中文原文，只縮短長度）。

### 5.0 時間線總覽

```mermaid
flowchart TD
    A["B0–B4 Build<br/>(3 次嘗試，第 3 次成功)<br/>ontology_v0"] --> B["Use：40 題 × Haiku Agent<br/>22/40 正確；寫入 40 筆軌跡"]
    B --> C{"觸發器<br/>40 ≥ 30 新軌跡"}
    C --> D["E0 凍結批次<br/>Pool 28 / Reserve 12"]
    D --> E["E1 診斷 → 7 個問題"]
    E --> F["E2 歸因 → 5 個假說<br/>主要 H1 (Content)"]
    F --> G1["第 1 輪：E3 修補 H1<br/>(第 1 次被程式擋下) → v0-c1<br/>機制驗證 → Gate 2 次重複"]
    G1 -- "5:1 通過 / 2:4 未通過<br/>Reject" --> G2["第 2 輪：E3 修補 H2 (Tool)<br/>→ v0-c2<br/>機制驗證 → Gate 2 次重複"]
    G2 -- "4:1 / 7:4 都通過<br/>但退步規則否決 → Reject" --> H["預算 2 輪用完<br/>run = incomplete / budget_exhausted<br/>active 仍是 ontology_v0"]
    H --> I["事後稽核（私有標準答案）<br/>+ 16 題全新測試題<br/>+ 反事實 Accept（工作區副本）"]
```

### 5.1 Build：產生 `ontology_v0`

#### B0 設定專案與載入工作負載（純程式）

呼叫 repo 的 `configure_ontology_project` 與 `prepare_ontology_workload`，寫出 `project.json`
（`mode = rolling_trajectory`、資料來源 = SQLite、評估 = `llm_judge`）與 `workload/questions.json`（30 題建構題）。

#### B1 資料剖析（純程式，約 110 秒）

`profile.py` 對 7 張表逐欄計算：型別、distinct 數、唯一性、範圍、前幾名的值與次數、空值數，另外對疑似時間戳記欄位做**格式檢查與時區換算影響量化**。
節錄（`runs/build/profile.md`）：

```text
## orders（60000 列）
- `order_ts`: TEXT；distinct=59943；範圍 2024-12-30 00:03:20 ~ 2025-12-31 23:53:02；若為 UTC 並換算 UTC+8，有 655 列會換月
- `status`: INTEGER；distinct=5；值: 3(39574), 9(9004), 2(4870), 1(3549), 0(3003)
- `coupon_code`: TEXT；distinct=2；null=41966；值: None(41966), SUMMER15(9204), WELCOME10(8830)
```

> ⚠️ 注意「若為 UTC 並換算 UTC+8，有 655 列會換月」是我寫在剖析程式裡的**通用檢查**（對所有疑似時間欄位都做），不是針對答案寫死；
> 但它確實讓 Builder 更容易注意到時區問題。這是 pipeline 設計的一部分（PoC 1 的 Builder 也自己做了類似查詢），不過你要知道它存在（§9.6）。

#### B2 探勘與驗證文件（LLM 迴圈 + 程式執行查詢）

Builder（Sonnet）收到：repo 的 build skill「Step 1」原文、30 題建構題、業務文件、剖析；可用工具 `sql_query`、`read_doc`、`get_schema`、`submit_evidence`。
它在迴圈裡下 SQL 驗證文件的每個主張，最後交出**證據提案**（一個查詢或一段文件引文 + 主張）。
**程式再逐條處理**：執行查詢並把真實結果寫成 `result`；文件引文必須是文件的逐字片段才收；失敗者丟棄。

產生 29 條 Evidence（0 條被拒）。真實例子：

```json
{ "id": "ev_utc_shift_orders",
  "query": "SELECT strftime('%Y-%m', order_ts) utc_m, strftime('%Y-%m', datetime(order_ts,'+8 hours')) tpe_m, COUNT(*) n FROM orders WHERE strftime('%Y-%m', order_ts) <> strftime('%Y-%m', datetime(order_ts,'+8 hours')) GROUP BY 1,2 ORDER BY 1",
  "result": "{\"columns\": [\"utc_m\",\"tpe_m\",\"n\"], \"rows\": [[\"2024-12\",\"2025-01\",51], [\"2025-01\",\"2025-02\",44], ... [\"2025-12\",\"2026-01\",56]]} | 解讀: 月初最後幾小時（UTC 16:00 後）的訂單在台北時間屬於次月；2024-12 有 51 筆改歸 2025-01 ... 所有期間類指標都必須先轉台北時間。" }
```

> `result` 欄位的前半（`{"columns"...}`）是**程式執行查詢得到的真實結果**；「解讀:」之後是 LLM 對結果的說明。這個分工就是 D3。

#### B3 語意設計（兩次 LLM 呼叫 + 程式檢查 + 退回重寫）

- **呼叫 a**：Builder 收到 repo 的 Step 2 原文 + `ontology-schema.md` 全文 + 題目 + 文件 + 剖析 + 已驗證證據 → 產出 Terms 與 Mappings。
- **呼叫 b**：再給它 a 的結果 → 產出 Relations、Constraints、已知限制與摘要。
- 兩次的結果都先過 `records.check_records`（§3.3 的規則）；不過就把**錯誤清單**交回去重寫，最多 2 次。Mapping 缺漏另有一個「針對性補填」步驟。
- 通過後，程式把 Evidence 的 id 對上去、做題目→物件連結。

#### B4 存檔、驗證、標註、發佈（純程式，呼叫 repo 的 core 操作）

`save_version` → `validate_semantics`（repo 的驗證器）→ `annotate_ontology_version` → `publish_ontology_build`（寫 `active.json`、初始化 `state.json` 的檢查點）。
結果：**30 Term／33 Mapping／25 Relation／28 Constraint／29 Evidence，驗證 0 錯誤，30/30 建構題連結成功，0 次修復，0 次補填。**

#### 三次 Build 嘗試（這是你重寫時最該看的教訓）

| 嘗試 | 發生什麼 | 怎麼發現 | 怎麼處理 |
| --- | --- | --- | --- |
| 1 | Builder prompt 裡有我寫的**範例**：「訂單日期／下單日／成立時間」（正是 PoC 1 觀察到的失敗），工具描述還寫了「時間欄位為 UTC」，Data Agent prompt 有「時間如何換算」的範例 | 出貨前自我審查 prompt | **洩題**：等於把答案提示放進 prompt。全部移除、整批重建；舊結果封存在 `runs/archive_build_attempt1_leaky_prompt/`，**不使用** |
| 2 | 設計呼叫回傳 `"mappings": []`（沒有任何 Mapping），還多了不在 schema 的欄位 `definity`；但 repo 的 `validate_semantics` **照樣通過** | 人工檢視輸出 | 在 `check_records` 加規則：只允許 schema 欄位；entity／dimension／metric 必須有 Mapping；加入針對性補填。舊結果封存在 `runs/archive_build_attempt2_no_mappings/` |
| 3 | 乾淨通過 | — | 這就是 `ontology_v0` |

> **教訓**：repo 的驗證器只檢查「格式合法」，不檢查「語意完整」。自動化 Build 時你需要自己的完整性檢查（本 PoC 的 `check_records`）。

#### `ontology_v0` 的內容（節錄真實物件）

30 個 Term：實體（訂單、訂單明細、客戶、付款紀錄、退款、商品）、維度（訂單成立時間、客戶地區、會員等級、下單通路、付款狀態…）、指標（淨營收、客單價、回購客戶、實收金額、退款金額、銷售數量…）、類別（待付款訂單、已取消訂單、在售商品）。
**注意：沒有「取消率」「出貨紀錄」「承運商」「配送天數」「準時送達率」「新註冊客戶」「優惠碼」「待出貨訂單」**——這正是建構題沒問、文件有寫的缺口。

Term 範例：

```json
{ "id": "term_valid_order", "name": "有效訂單", "type": "concept",
  "definition": "訂單狀態為已付款、已出貨、已送達的訂單；待付款與已取消不算有效訂單。",
  "scope": "所有營收、客單價、訂單張數、回購與通路占比類分析",
  "aliases": ["valid order", "有效訂單數", "訂單張數", "訂單數", "valid orders", "orders.status", "狀態1/2/3"],
  "evidence": ["ev_status_codes", "ev_doc_valid_order", "ev_status_payment_consistency"] }
```

Mapping 範例：

```json
{ "id": "map_valid_order_status", "term_id": "term_valid_order", "database_source": "shop_v2",
  "table": "orders", "column": "status",
  "semantic_filter": "狀態碼為 1（已付款）、2（已出貨）、3（已送達）",
  "aggregation_semantics": "以不重複訂單編號計張數", "grain": "每張訂單一列" }
```

Constraint 範例（**最關鍵的時區規則**）：

```json
{ "id": "con_tz_order_time", "target": "map_order_time", "constraint_type": "scope", "severity": "block",
  "trigger_keywords": ["2025年", "2025 年", "年度", "月份", "8月", "3月", "6月", "9月", "12月", "第一季", "第二季", "第三季", "第四季", "季", "台北時間", "UTC", "時區", "期間", "今年"],
  "description": "orders.order_ts 以 UTC 儲存，營運報表必須以台北時間（UTC+8）劃分日、月、季、年。換算後每月都有部分訂單改歸屬到下一個月（含跨年）...",
  "evidence": ["ev_doc_utc", "ev_utc_shift_orders", "ev_year_boundary"] }
```

> 🔍 （補充：repo 的 `ontology-schema.md` 明文允許約束的 `target` 是「Term 或 Mapping id」，並說約束要「在執行期可被發現」。所以這**不是 Builder 違規**，而是 repo 規格與 runtime 行為之間的落差——見 §6.4。）
>
> 🔍 **請注意 `"target": "map_order_time"`**：這條約束掛在一個 **Mapping** 上，不是掛在 Term 上。在 repo 的 `resolve_semantics` 裡，
> 約束只會隨「`target` 等於被解析 Term 的 id」被帶出，所以**使用者說「2025 年 11 月」或甚至直接解析「訂單成立時間」，這條時區規則都不會出現**。
> v0 的 28 條約束中有 **15 條**（約 54%）是這種「掛在 Mapping 上」的約束。這是本次最重要的發現之一，詳見 §6.4。

### 5.2 Use：Data Agent 回答 40 題，並記錄軌跡

#### 單題流程

```text
問題 → [Python] 組 system prompt（Data Agent 說明 + manifest）
     → [LLM 迴圈，最多 10 步，每步一個 JSON 動作]
          resolve_semantics / browse_semantics   (語意層，記錄輸入＋完整結果)
          get_schema / sql_query                 (原生工具，記錄輸入＋截斷結果)
          submit_answer {answer, basis}          (最終工具)
     → [Python] from_message_trace 正規化 → TrajectoryStore.append → trajectories/<task_id>.json
```

manifest（Agent 開場看到的語意層說明）節錄：

```text
Ontology layer version: ontology_v0
Objects: 30 terms, 33 mappings, 25 relations, 28 constraints, 29 evidence records.
Active constraints: 28 (block=26, info=1, warn=1)
## Semantic MCP Tools
- browse_semantics(query, kind, limit) — find up to 6 catalog items relevant to a specific analytical need.
- resolve_semantics(mentions, context) — resolve up to 5 concepts to grounded mappings, relations, constraints, and evidence.
### When to use semantic tools
- Call resolve_semantics with the concepts you plan to use; ...
- Resolved mappings are guidance, not final answers — always validate against the actual data with your native query tools.
```

#### 一個真實對照：S35「2025 年 11 月整體取消率是多少？」（標準答案 15.29）

以下取自第 1 輪 Gate 第 1 次重複中，Parent 與 Candidate 各跑一次 S35 的軌跡（同一個 Haiku Agent、同一題；Use 階段 v0 對 S35 也答錯，但那次是交出了錯誤的數字）。

**Parent（v0）**——`failed / max_steps`，沒交出答案：

```text
resolve ['取消率']               → unresolved           ← 語意層沒有「取消率」
browse  '取消 訂單 狀態 cancel'   → 3 筆
resolve ['已取消訂單','訂單']     → resolved（但沒有任何規則）
resolve ['有效訂單']             → resolved，規則=con_valid_order_definition
browse  '取消率 分母 ...'         → 3 筆
resolve ['取消訂單張數','訂單總數'] → 兩個都 unresolved
SQL × 4（查表結構、查 2025-11 各 status 筆數、檢查 order_ts 格式...）→ 10 步用完，無最終答案
```

**Candidate（v0-c1）**——`completed`，答案 `15.29`（正確）：

```text
resolve ['取消率','訂單取消']      → 取消率 resolved，規則=con_cancellation_rate_definition
resolve ['訂單成立時間','台北時間'] → 訂單成立時間 resolved
SQL × 3 → 最終答案 15.29，依據：「已取消 ÷（有效訂單 + 已取消訂單），不含待付款。期間以 order_ts 轉台北時間的月份歸屬為 2025-11，共 695 筆已取消、3850 筆有效，合計 4545 筆」
```

這就是「語意層缺口 → Agent 失敗 → 補上物件 → Agent 成功」的完整因果鏈。

#### 40 題結果（v0，Haiku Agent，用私有標準答案事後評分）

| 題型 | 正確／題數 | 說明 |
| --- | ---: | --- |
| `net_revenue` | 4/4 | 建構題問過的組合 |
| `aov` | 2/2 | 同上 |
| `repeat`／`refund`／`collected` | 3/3 | 同上 |
| `new_customers` | 4/4 | 語意層沒有，但 Agent 靠 SQL 自己做對 |
| `ship_days` | 4/4 | 同上 |
| `pending_ship` | 1/1 | 同上 |
| `valid_orders`（換說法） | **3/9** | 答錯的 6 題都只差幾張到十張（例如標準答案 4,098、Agent 答 4,089）——典型的「用 UTC 切月」偏差；「成立日期」「訂單日期」等說法沒有帶出時區規則 |
| `coupon` | **1/4** | 答錯的 3 題同樣只差 3–6 張（例如 625 vs 631），也是 UTC 切月偏差 |
| `cancel_rate` | **0/5** | 語意層沒有取消率；其中 3 題 `max_steps` 沒交答案，另 2 題答案錯（例如 S17 分母含待付款：15.41 vs 標準答案 16.2） |
| `ontime` | **0/4** | 3 題答「無法計算」 |
| **合計** | **22/40 = 55%** | Pool 14/28、Reserve 8/12 |

> **關鍵觀察**：Agent 在沒有語意層物件時，不一定會錯（`new_customers`、`ship_days` 全對），但**一旦錯，原因就會是「沒有口徑」或「沒帶出時區規則」**——這正是 Evolve 要找出來的東西。

軌跡以**模擬的到達時間**（每題間隔 3 分鐘）寫入 `trajectories/`，共 40 檔。

### 5.3 觸發器

`evolution_status` 讀 `state.json` 的檢查點，數出檢查點之後的新軌跡：

```json
{"evolution_due": true, "reason": "40 new trajectories >= 30"}
```

觸發器**只提醒**，不自動啟動；是我的 `cli evolve` 決定開始。

### 5.4 E0 凍結批次，切 Pool／Reserve

`evolve.freeze_batch`：取檢查點之後所有 `production` 軌跡 → 依 `recorded_at` 排序 → 近似重複分組（3-gram Jaccard ≥ 0.85；本批 40 題＝40 組，沒有重複）→ 依組順序累積到 70%（28 題）為 Pool、其餘 12 題為 Reserve。
然後呼叫 repo 的 `start_evolution_run`（寫 `run.json`，凍結預算 2 輪與驗收標準）與 `confirm_trajectory_sources`（寫 `trajectory-sources.json`）。
`frozen_batch.json` 記下 Pool／Reserve 的 task id。

凍結下來的驗收標準（**在看到任何結果前就寫進 `run.json`**）：

```json
"acceptance": {
  "protocol": "llm_judge",
  "rule": "E_c == 0 and W_c > W_p (EvaluationGate.decide_judge)",
  "confirmation": "a second independent repetition must also accept",
  "regression_policy": "critical error, or Parent wins > 1/3 as often as Candidate",
  "judge_role": "judge", "validation_reserve_size": 12, "pool_size": 28 },
"budget": {"max_rounds": 2}
```

### 5.5 E1 診斷：問題地圖

Evolver（Sonnet）收到：repo 的 Step 1 原文與原則、**28 題 Pool 軌跡**（壓縮成：每題的語意呼叫與命中、SQL 摘要、最終答案與依據）、語意層目錄、資料剖析、業務文件；
工具：`probe_semantics`（直接對 Parent 試 resolve／browse，用來「主動測試」）、`sql_query`、`read_doc`。**Reserve 完全不給。**
它交出**問題地圖**（7 項），每項都有症狀、證據、因果假說、不確定性。摘要：

| # | 類別 | 症狀 | 受影響 Pool 題 | 證據（它自己查到的） |
| --- | --- | --- | --- | --- |
| P1 | 覆蓋缺口 | 「取消率」語意層沒有定義；3 題沒交出答案，S17 分母含待付款 | S04 S05 S17 S19 | `resolve('取消率')→unresolved`；SQL 顯示 2025Q1 各通路待付款量大，分母選擇會改變結果 |
| P2 | 覆蓋缺口 | 「準時送達率」沒定義，Agent 答「無法計算」 | S02 S03 S14 | 查證 shipments 有出貨與送達時間，已送達 39,574 筆、3 天內 22,733 筆 |
| P3 | 覆蓋缺口 | shipments／承運商完全不在語意層；配送天數口徑各自推斷（用出貨時間歸屬期間，與文件不符） | S02 S03 S06 S07 S08 S14 | 33 個 Mapping 沒有一個指向 shipments；以出貨時間 vs 訂單時間歸屬，月份不一致 2,988 筆（7.5%） |
| P4 | 結構限制 | 時區規則沒有被穩定帶給 Agent，多題直接用 UTC 切月季年 | S10 S11 S15 S18 S21 S24 S27 | 這些題的 SQL 都沒有 +8 小時；`resolve` 只命中 `con_valid_order_definition`；工具設定三個旋鈕皆關閉 |
| P5 | 工具限制 | 別名其實有，但複合說法（「官網通路」「南部客戶」「成立日期」）解析不到 | S04 S05 S10 S27 S12 S25 S15 S21 S22 | `fuzzy_fallback=false`，只有精確別名比對 |
| P6 | 覆蓋缺口 | 新註冊客戶、優惠碼、待出貨訂單沒有 Term | S09 S13 S23 S11 S18 S24 S16 | 這些題目前答對，風險是潛在的 |
| P7 | 潛在缺口 | 一個 mention 只回一條規則，配套規則（單位、時區）拿不到 | S10 S11 S18 S24 S27 S15 | 屬推測，沒直接測試 |

> 程式在收到診斷後做一件事：把每個問題的 `affected_tasks` 過濾成**只剩 Pool 內**的題目（防止 Evolver 提到 Reserve 的題）。

### 5.6 E2 歸因：5 個彼此競爭的假說

Evolver 收到問題地圖與 Step 2 原文，要為每個高價值問題找出最相關的層與性質：

| 假說 | 涵蓋問題 | 層 | 性質 | 一句話機制 | 優先序 |
| --- | --- | --- | --- | --- | :-: |
| **H1** | P1 P2 P3 | **Content** | 缺少涵蓋 | 語意層缺少取消率、出貨實體、承運商代碼、配送天數、準時送達率的口徑；Agent 只能猜 | 1（**主要**） |
| **H2** | P4 P7 | **Tool** | 現有設計錯誤 | 時區規則存在但取不到：`resolve` 不依 `trigger_keywords` 帶出，也沒有常駐釘選 | 2 |
| H3 | P5 | Tool | 現有設計錯誤 | `resolve` 只做精確別名比對、`fuzzy_fallback` 關閉（下游症狀，影響較小） | 3 |
| H4 | P6 | Content | 缺少涵蓋 | 註冊日期、優惠碼、待出貨沒有 Term（目前答對，驗證價值低） | 4 |
| H5 | P4 | **Schema** | 結構不合 | 物件模型一個 mention 只能帶一條規則、沒有全域約束物件（H2 的更深層成因？） | 5（PoC 無法執行 Schema 修補，不單獨驗證） |

Evolver 的選擇理由（節錄）：「H1 是影響最大、證據最強的**獨立根因**：6 題完全沒有交出答案或答『無法計算』……H2 影響題數多（7 題）但每題偏差小（約 1%）……所以排在第二。**一個 Candidate 只驗證 H1，H2 留給後續 Candidate**。」

pipeline 的選擇規則（程式）：每輪取 `primary`；被 Reject 後，下一輪取**尚未試過、優先序最高**的假說（這次就是 H2）；全部試過才重新歸因。

### 5.7 第 1 輪：H1（Content）→ Candidate `v0-c1`

#### E3 修補設計與程式檢查

Evolver 收到：Step 3 原文、主要假說、**Parent 的全部物件**、Tool 設定、可用的 8 種修補操作。它輸出**有型別的修補操作**（不是改檔）。

- **第 1 次提案被程式擋下**：Relation 用了不在 5 種之內的型別（`belongs_to`、`depends_on`），`check_records` 回報錯誤清單，退回重寫。
- **第 2 次提案通過**。程式把操作套用到 Parent 的複本，產生 `v0-c1`，**Parent 完全不動**。

假說原文（Evolver 寫的，可被證偽）：

> 語意層缺少取消率、出貨實體、carrier 代碼對照、配送天數與準時送達率的口徑（33 個 mapping 沒有任何一個指向 shipments）。……補上這些 term、mapping、relation 與 constraint 後，取消率類題目應使用「有效訂單＋已取消」為分母，準時送達率類題目應使用「已送達出貨中配送天數≤3天」，且期間改依訂單成立時間（台北時間）歸屬，同時不再出現「無法計算」。**若補上後這些詞仍 unresolved，或 agent 仍用待付款入分母、或仍以 shipped_ts 歸屬期間，則假說被推翻。** 時區類與別名類題目不應改變，作為對照。

程式算出的 diff（`diff_round1.json`）：

| 類別 | 新增 |
| --- | --- |
| Term（5） | `term_cancellation_rate` 取消率、`term_shipment` 出貨紀錄、`term_carrier` 物流商、`term_delivery_days` 配送天數、`term_on_time_rate` 準時送達率 |
| Mapping（6） | `map_cancellation_rate_status`、`map_carrier`、`map_delivery_days_delivered_ts`、`map_delivery_days_shipped_ts`、`map_on_time_rate_delivered_ts`、`map_shipment_order` |
| Relation（3） | `rel_cancellation_rate_from_orders`（derivation）、`rel_on_time_from_delivery_days`（derivation）、`rel_shipment_to_order`（association） |
| Constraint（4） | `con_cancellation_rate_definition`、`con_delivery_days_definition`、`con_on_time_rate_definition`、`con_carrier_codes` |
| Evidence（4，皆為文件引文） | `ev_doc_cancel_rate`、`ev_doc_delivery_days`、`ev_doc_on_time`、`ev_doc_carrier_codes` |
| 修改既有物件 | 無 |

新增的約束範例：

```json
{ "id": "con_cancellation_rate_definition", "target": "term_cancellation_rate", "severity": "block",
  "trigger_keywords": ["取消率", "取消比例", "取消比率", "取消占比", "cancellation rate", "cancel rate", "取消的比例"],
  "description": "取消率 = 已取消訂單 ÷（有效訂單 + 已取消訂單）。分母不含待付款訂單，也不是全部訂單。期間依訂單成立時間（台北時間）歸屬，不依取消發生時間。" }
```

> 📝 兩點觀察：①這次 Evolver 把 3 條新約束的 `target` 設成 **Term**（所以 `resolve('取消率')` 真的會帶出規則，見 S35 軌跡）；
> 但 `con_carrier_codes` 又掛在 Mapping 上，同樣是不可達的。②Evolver 在 Mapping 裡把 `database_source` 寫成 `lumo.db`，而 v0 是 `shop_v2`——
> 這個欄位 repo 沒有交叉檢查，所以沒被擋下（無實質影響，但屬資料品質瑕疵）。

#### 機制驗證（Gate 之前）

Skill 要求先確認「被修補的機制真的改變了行為」。程式選出 H1 涵蓋問題中的前 6 個 Pool 題（S02 S03 S04 S05 S06 S07），用 `v0-c1` 重播：

| 指標 | 結果 |
| --- | --- |
| 被修補的物件有出現在 Agent 的語意結果中（活化率） | 6/6 |
| 最終答案改變的比例 | 5/6 |
| （事後以標準答案核對）正確數 | Candidate 5/6 vs Parent 2/6 |

通過（活化率 > 0），進入正式 Gate。若活化率為 0，程式會跳過 Gate 並直接 Reject（避免白費評審成本）。

#### E4 Gate：Parent vs Candidate

每次「重複」的流程（`gate_repetition`，全由程式控制）：

```text
Reserve 12 題
  → 用同一個 Agent 模型，分別以 Parent 與 Candidate 各跑一次（並行；兩邊 prompt 完全相同，只差語意層版本）
  → 對每一題：以固定 seed 隨機決定 Parent 是 A 還是 B（呼叫 EvaluationGate.anonymize）
  → Judge（Opus）看「問題 + 匿名的答案 A/B + 各自的 SQL 與結果片段」，回 {winner, reason, critical_error}
  → EvaluationGate.decode 解匿名 → EvaluationGate.decide_judge 聚合：E_c==0 且 W_c>W_p 才 accept
```

**第 1 輪結果**：

| 重複 | Candidate 勝 | Parent 勝 | 平手 | 嚴重錯誤 | 結果 |
| --- | :-: | :-: | :-: | :-: | --- |
| 第 1 次 | 5 | 1 | 6 | 0 | ✅ Accept |
| 第 2 次（獨立重新執行） | 2 | 4 | 6 | 0 | ❌ Reject |
| 合計 | 7 | 5 | 12 | 0 | 兩次不一致；退步規則也觸發（5×3 > 7） |

→ **Reject**。程式呼叫 `record_evolution_evaluation`（寫入 `gate_input`）與 `record_evolution_round`（寫 `rounds.jsonl`）；`v0-c1` 保留在 `versions/` 供稽核。

> 這次 Gate 的「兩次不一致」本身就是重點：**同一個 Candidate、同一批題目，兩次重新執行就從 5:1 變成 2:4。**這是第一個訊號，顯示小樣本 + LLM Judge 的雜訊與真實改善同一個量級（§6.1）。

### 5.8 第 2 輪：H2（Tool）→ Candidate `v0-c2`

#### E3 修補

程式取下一個尚未試過的假說 H2。Evolver 產出（`patch_round2_attempt1.json`）三個操作，一次通過：

```json
[ {"op": "set_tool_config", "section": "resolve",  "key": "trigger_keyword_constraints", "value": true},
  {"op": "set_tool_config", "section": "manifest", "key": "pinned_constraint_ids",       "value": ["con_tz_order_time"]},
  {"op": "update_field", "family": "constraints", "id": "con_tz_order_time", "field": "trigger_keywords",
   "value": ["2024年","2025年","2025 年","2026年","年度","全年","上半年","下半年","月份","每月","當月","本月","1月",…,"12月","第一季","第二季","第三季","第四季","季","Q1","Q2","Q3","Q4","order_ts","下單時間","訂單成立時間","期間","跨年"]} ]
```

白話：①開啟「`resolve` 時，把 `trigger_keywords` 命中的約束也一併回傳」（Tool 旋鈕，D5）；②把時區規則釘在 manifest，Agent **一開場就看得到**；③把時區規則的觸發詞從 19 個擴充到 38 個。
`diff_round2.json`：**沒有新增物件**，只改了 1 條約束的 `trigger_keywords`，加上 `tool_config.json` 的兩個旋鈕——這是一個很小的修補。

關於這個修補的一個重要背景：Evolver 要解決的是「時區規則取不到」，而根因其實是 §5.1 發現的「約束掛在 Mapping 上、`resolve` 帶不出來」。Evolver 沒有診斷出這個根因，
它選了一個**繞過**的 Tool 旋鈕（依關鍵字帶出 + 釘選），效果上等於補救，但沒有把約束改掛到 Term 上。見 §6.4。

#### 機制驗證——這一輪的驗證是**不充分**的（請注意）

| 指標 | 結果 |
| --- | --- |
| 活化率 | 6/6——但這個數字**幾乎是空的**：只要 Tool 旋鈕含「釘選」，程式就視為活化（因為釘選規則每題都會出現在 manifest） |
| 重播的題目 | S02–S07（取消率／準時送達率題）——**不是時區相關題** |
| 最終答案改變 | 4/6 |

**原因**：這個 run 在第 2 輪中途因預算上限被迫中斷，之後續跑；續跑的程式路徑沿用較早版本的「用全部問題的受影響題」選重播題目（事後稽核已修正正常路徑，但官方 run 的第 2 輪已經是這樣跑的）。
所以第 2 輪的機制驗證**沒有真正驗證到「時區規則是否改變了時區題的行為」**。這不影響 Gate 結果（Gate 用的是 Reserve），但意味著「機制驗證」這一關在第 2 輪形同虛設。

#### E4 Gate

| 重複 | Candidate 勝 | Parent 勝 | 平手 | 嚴重錯誤 | 結果 |
| --- | :-: | :-: | :-: | :-: | --- |
| 第 1 次 | 4 | 1 | 7 | 0 | ✅ Accept |
| 第 2 次 | 7 | 4 | 1 | 0 | ✅ Accept |
| 合計 | 11 | 5 | 8 | 0 | 官方裸規則通過；**我的退步規則否決**（5×3=15 > 11） |

→ 依 `gate_input.unacceptable_regressions = true`，程式 **Reject**（若沒有這條政策，repo 的 `decide_judge` 對兩次重複與合計都是 Accept；對 §6.5 有詳細分析）。

### 5.9 結局與磁碟狀態

第 2 輪 Reject 後，`latest()["round"] (=2) >= max_rounds (=2)` → 程式呼叫 `mark_evolution_incomplete(reason="budget_exhausted")` → `finalize_evolution_run`。

`run.json` 最終狀態（節錄）：

```json
{ "run_id": "run_1", "status": "incomplete", "parent_version": "ontology_v0", "round": 2,
  "current_candidate": "v0-c2", "accepted_version": "", "end_reason": "budget_exhausted",
  "budget": {"max_rounds": 2}, "min_rejects_before_incomplete": 2 }
```

| 檔案 | 狀態 |
| --- | --- |
| `active.json` | `{"active_version": "ontology_v0"}`（沒變） |
| `state.json` | `checkpoint_trajectory: null`、`evolution_due: true`（**沒有推進**，同一批軌跡下次 run 會重用） |
| `versions/` | `ontology_v0`、`v0-c1`、`v0-c2`（兩個 Candidate 都留著，各有 `tool_config.json`） |
| `evolution/run_1/` | `run.json`、`rounds.jsonl`（2 行）、`frozen_batch.json`、`problem_map.json`、`attribution_round1.json`、`patch_round1_attempt{1,2}.json`、`patch_round2_attempt1.json`、`diff_round{1,2}.json`、`gate_round{1,2}.json`（完整的 48 個 verdict 與理由）、`evaluations/`、`artifacts/`（每次重複的 Parent／Candidate 完整軌跡）、`report.json` |

> 這個結局完全符合官方狀態機：**「預算用完」→ `incomplete`；不切換 active、不推進檢查點**。

### 5.10 反事實：「如果第 2 輪被 Accept 會怎樣」（**不是官方結果**）

為了展示 Accept 路徑在真實檔案上的產出，`counterfactual.py` 做了這件事（**不呼叫 LLM、不花錢、不動真實工作區**）：

1. 把 `.evoontology/` **複製**到 `runs/counterfactual_ws/`。
2. 在副本中開一個新 run，餵入第 2 輪**已記錄的 48 個評審 verdict 中屬於第 2 輪的 24 個**，並宣告 `unacceptable_regressions = false`（在 repo 裡這是 Evolver 的判斷；這裡就是反事實的假設）。
3. 呼叫 repo 的 `accept_evolution` 與 `finalize_evolution_run`。

結果：

```json
{ "accepted": {"status": "ok", "accepted_version": "ontology_v1"},
  "active": "ontology_v1",
  "versions": ["ontology_v0", "ontology_v1", "v0-c1", "v0-c2"],
  "state": {"checkpoint_trajectory": "task_935466fa8276", "evolution_due": false} }
```

發佈閘重新計算 Gate、複製 `v0-c2` 為 `ontology_v1`（含 `tool_config.json`）、切換 `active.json`、推進檢查點（`evolution_due` 變 `false`）、渲染 HTML 探索器
（`runs/counterfactual_ws/.evoontology/visualizations/ontology-layer-explorer.html`）。這證明我的 pipeline **能正確走完 Accept**，並與 repo 的發佈閘相容；但它**不是**實跑得到的結果。

---

## 6. 結果分析

### 6.1 Gate 逐題對照：Judge 說了什麼 vs. 標準答案怎麼說

Reserve 12 題；**GT** 欄是事後用私有標準答案評分（Parent／v0-c1／v0-c2 在 4 次重複中每題的對錯完全一致，所以只列一次）。
Judge 欄：**C**＝Judge 判 Candidate 勝、**P**＝判 Parent 勝、**＝**＝平手、`*`＝原始回覆不是 JSON、當時被當成平手（見 §9.4；重評後只有 2 個格子改變，沒有任何正式決定改變）。

| 題 | 題型 | GT：Parent | GT：v0-c1 | GT：v0-c2 | 第 1 輪 重複 1（c1） | 第 1 輪 重複 2（c1） | 第 2 輪 重複 1（c2） | 第 2 輪 重複 2（c2） |
| --- | --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| S29 | net_revenue | ✓ | ✓ | ✓ | ＝ | ＝ | ＝ | C |
| S30 | aov | ✓ | ✓ | ✓ | P | C | ＝ | P |
| **S31** | **ontime** | ✗ | **✓** | ✗ | C | ＝* | C | P |
| S32 | new_customers | ✓ | ✓ | ✓ | ＝ | ＝ | ＝ | C |
| **S33** | **valid_orders** | ✗ | ✗ | **✓** | ＝ | P | C | C |
| S34 | coupon | ✓ | ✓ | ✓ | ＝* | P | P | C |
| **S35** | **cancel_rate** | ✗ | **✓** | ✗ | C | C | C | C |
| S36 | valid_orders | ✓ | ✓ | ✓ | ＝* | ＝ | ＝* | P |
| S37 | ship_days | ✓ | ✓ | ✓ | C | P | ＝ | C |
| **S38** | **valid_orders** | ✗ | ✗ | **✓** | C | P | C | C |
| S39 | refund | ✓ | ✓ | ✓ | ＝ | ＝* | ＝ | ＝ |
| S40 | collected | ✓ | ✓ | ✓ | C | ＝ | ＝* | P |
| **Judge 計分（C:P:＝）** | | | | | 5:1:6 | 2:4:6 | 4:1:7 | 7:4:1 |
| 官方裸規則 | | | | | ✅ | ❌ | ✅ | ✅ |
| 標準答案計分 Parent→Candidate | | 8/12 | 10/12 | 10/12 | 8→10 | 8→10 | 8→10 | 8→10 |

粗體列是標準答案認為 Candidate 真的比 Parent 好的題（每個 Candidate 各 2 題）。其他 10 題標準答案認為「兩邊一樣」（一樣對或一樣錯）。

**怎麼讀這張表**：

- 在 4 次重複 × 2 個「真的有差」的題 = 8 個配對中，Judge 抓到 **7 個**（只漏掉第 1 輪重複 2 的 S31，而那個格子是 Judge 回覆壞掉被當成平手，重評後是 C）。**Judge 對「真的有差」的題大致是靈敏的。**
- 在 4 × 10 = 40 個「標準答案認為兩邊一樣」的配對中，Judge 判 **Candidate 勝 11、Parent 勝 10、平手 19**。也就是說有一半以上的配對 Judge 認為有人勝出，但標準答案認為沒有差別。**這些「勝負」是雜訊。**

### 6.2 事後稽核：用標準答案看 Gate 的決定對不對

| 輪 | Candidate | 官方決定（凍結政策） | 裸 repo 規則（單次重複 1） | 裸規則（兩次合併） | 裸規則（每次重複都要過） | 退步規則否決？ | 標準答案 Gate（`decide_gt`）每次重複 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | v0-c1 | **Reject** | Accept | Accept（7:5） | **Reject** | 是（5×3>7） | Accept、Accept |
| 2 | v0-c2 | **Reject** | Accept | Accept（11:5） | **Accept** | 是（5×3>11） | Accept、Accept |

- **標準答案認為兩個 Candidate 都該 Accept**（Reserve 上 8/12 → 10/12，4 次重複皆然；`decide_gt` 的 Accept 條件是 Candidate 平均分嚴格大於 Parent）。
- **第 1 輪**：即使不要我的退步規則，「兩次都要過」也會 Reject（重複 2 是 2:4）。這次 Reject 主要來自 Judge 的雜訊。
- **第 2 輪**：若沒有我的退步規則，官方結果會是 **Accept**（兩次都過）。所以**第 2 輪被拒絕的唯一原因是我自訂的 D9 政策**（§6.5）。

### 6.3 Judge 的行為：它在評什麼？

把 10 個「Judge 判 Parent 勝、但標準答案認為兩邊同樣對／同樣錯」的理由讀完（原文在 `gate_round{1,2}.json`），模式非常一致：

| 配對 | GT | Judge 判 Parent 勝的理由（節錄） |
| --- | --- | --- |
| 第 1 輪重複 1 · S30 | 兩邊都對 | 「兩者最終答案與定義相同且皆正確，但 B 額外比較了 UTC 與 UTC+8 兩種時區切分的差異……**驗證更充分**」 |
| 第 1 輪重複 2 · S33 | 兩邊都錯 | 「有效訂單定義、SQL 與答案（3668）相同；A 只隨機抽樣 5 筆確認時間格式，B 則以 GLOB **全表檢查格式**……佐證更完整」 |
| 第 1 輪重複 2 · S34 | 兩邊都對 | 「B 以 COUNT(DISTINCT order_id) 計張數，能防範重複列……**略為穩健**」 |
| 第 1 輪重複 2 · S37 | 兩邊都對 | 「A 以**出貨時間**界定季度更貼近物流語意……B 改用訂單時間並做**未經佐證的時區換算**」 |
| 第 1 輪重複 2 · S38 | 兩邊都錯 | 「A 額外驗證了 order_ts 全表皆為 19 字元標準格式……可驗證性較高」 |
| 第 2 輪重複 1 · S34 | 兩邊都對 | 「B 完整呈現了 UTC 與 UTC+8 兩種篩選結果的對照……可驗證性略高」 |
| 第 2 輪重複 2 · S30 | 兩邊都對 | 「B 額外驗證了通路代碼並對照 UTC 與台北時區篩選的差異，可驗證性略高」 |
| 第 2 輪重複 2 · S31 | 兩邊都錯 | 「兩者皆正確指出缺乏準時標準而無法計算，但 A 額外查出黑貓 2025Q1 出貨 4979 筆……」 |
| 第 2 輪重複 2 · S36 | 兩邊都對 | 「A 聲稱『依不重複訂單編號計數』，但實際用的是 COUNT(*)，描述與查詢略不一致」 |
| 第 2 輪重複 2 · S40 | 兩邊都對 | 「B 的查詢乾淨……A 含一次因佔位欄位而失敗的無效查詢，過程較雜亂」 |

**這 10 個全是風格差異**（誰多做了一道驗證、誰的查詢比較乾淨），沒有一個涉及答案對錯。其中 7 組兩邊答案都正確、3 組兩邊都錯。
再加上三個值得注意的現象：

1. **Judge 不知道業務定義。** S37 那一格，Judge 認為「依出貨時間歸屬季度更貼近物流語意」而給了 Parent 勝——但業務文件明明規定配送天數**依訂單成立時間**歸屬，也就是被它扣分的那邊才是對的。
   Judge 看不到文件，這是協定本身的設計（它只能從四個面向判斷）。**這意味著 Judge 的判斷上限是「看起來是否嚴謹」，而不是「是否符合業務口徑」。**
2. **Judge 偏好「看起來驗證更多」的答案。** 額外做了時區對照、格式檢查的那一邊容易贏——即使最終數字相同。這會獎勵冗長的驗證，而不是正確性。
3. **回覆格式不穩。** 48 次評審中有 **6 次**（約 13%）回覆不是要求的 JSON（2 次空白、4 次把推理文字混進去）。
   原始版本把它們當成平手；修正後的版本會重問最多 3 次，仍失敗就中止。我用 Sonnet 把這 6 組重評一次：**只有 2 組由平手改成 Candidate 勝，沒有任何一個 Accept／Reject 的決定改變**（`runs/rejudge.json`）。

> 這三點是你規劃 Judge 時最需要的資訊：**如果用開源模型當 Judge，格式失敗率可能更高；如果要讓 Judge 更可靠，可以考慮給它業務定義（但那樣它就不再「無知」）、做多次投票、或要求它對「平手」更寬容。**

### 6.4 根因：被掛在 Mapping 上、永遠帶不出來的約束

這是這次 PoC 在「EvoOntology 行為」上最重要的發現，值得獨立說明。

**事實**：

1. repo 的 `ontology-schema.md` 說約束的 `target` 是「Term 或 Mapping id」，並說「約束必須在執行期可被發現；`trigger_keywords` 讓 Agent 即使不知道約束 id 或目標 Term 也能找到相關約束」。
2. repo 的 `resolve_semantics` 只回傳「`target` 等於被解析 Term 的 id」的約束；`trigger_keywords` **只**用在 `browse_semantics` 的搜尋文字裡。
3. 我的 Builder（Sonnet）依 schema 把 28 條約束中的 **15 條**掛在 Mapping 上：三條時區規則（訂單／付款／退款時間）、金額單位、訂單張數單位、所有代碼對照（通路／會員／地區／付款方式／退款原因／訂單狀態）、待付款與已取消的期間規則、在售商品規則、付款成功才計實收的規則。
4. 所以：Agent 解析「訂單成立時間」「有效訂單」「2025 年 11 月」時，**這 15 條約束一條都不會出現**，只有 Agent 剛好 `browse` 到才看得到。

**對結果的影響**：v0 在 Use 階段失敗的 18 題中，**9 題**是 UTC 切月偏差（`valid_orders` 6 + `coupon` 3，答案都只差幾張到十張），**9 題**是語意層缺口（取消率 5 + 準時送達率 4）。
第一類正是「時區約束帶不出來」造成的。第 2 輪的 Tool 修補（釘選 + 依關鍵字帶出）在全新測試題上把 `valid_orders` 從 1/4 提升到 **4/4**（§6.6），也印證了這個機制。

**Evolver 的診斷準確到哪**：Evolver 的 H2 說「`resolve` 不依 `trigger_keywords` 帶出，也沒有常駐釘選」——這是**正確**的（repo 的確如此），它的修補也確實有效。
它沒說的是「約束 `target` 是 Mapping，所以怎麼 resolve 都帶不出來；只要把 `target` 改成 Term 就能用 repo 原有的機制解決」。
不過公平地說，**我給 Evolver 的修補操作清單裡 `update_field` 不能改 `target`**（`UPDATABLE` 不含 `target`），所以它即使診斷到，也只能新增一條掛在 Term 的重複約束或走 Tool 旋鈕——這是我的設計限制（D4）。

**v0-c1 自己也犯了同一個模式**：它新增的 4 條約束中，`con_carrier_codes` 也掛在 Mapping（`map_carrier`）上；v0-c1 共有 32 條約束、其中 16 條不可達。

**我後來做了什麼**：在 `records.py` 新增 `unreachable_constraints` 檢查（目標不是 Term 的約束會被列出），並有單元測試。
**但這個檢查是事後審計才加的，官方實跑的 Build 與 Evolve 都沒有使用它**。

> **給你重寫的建議**：這是個高槓桿的修正點。選項：(a) Build 時強制約束 `target` 為 Term（或由程式自動把 Mapping 約束上提到其 Term）；(b) 改 `resolve`：回傳被解析 Term 的所有 Mapping 的約束；
> (c) 讓 `resolve` 也依 `trigger_keywords` 帶出約束（本 PoC 的 Tool 旋鈕做的就是這件事，已驗證有效）。(b)＋(c) 都屬 Tool Layer 的改動，正好是 EvoOntology 允許演化的範圍。

### 6.5 Gate 的保守性：我的退步規則（D9）與樣本太小

**1. 規則本身**（寫入 `run.json`，run 開始前凍結，沒有因結果而調整）：Candidate 有任何嚴重錯誤，或「Parent 勝場 × 3 > Candidate 勝場」，即視為不可接受的退步，`gate_input.unacceptable_regressions = true`，發佈閘會擋。
repo 把「不可接受的退步」的判定留給 Evolver agent；我必須把它變成確定性規則，這是我的選擇，**沒有 repo 依據**。

**2. 它在這次的影響**：
- 第 1 輪：即使沒有它也 Reject（重複 2 是 2:4）。
- **第 2 輪：它是唯一的否決理由**——兩次重複在裸規則下都 Accept。

**3. 為什麼這個規則在 12 題的 Reserve 上特別嚴**：Parent 只要贏 1 場，Candidate 就至少要贏 3 場；贏 2 場就要 7 場（12 題裡不可能容易達到）。
當 Judge 在「風格差異」上有隨機勝負時，這個規則幾乎等於要求「Parent 零勝場」。

**4. 更根本的問題：雜訊和訊號一樣大。**
每次重複，「真的有差」的題只有 2 題（標準答案認為 Candidate 多對 2 題），也就是**真實訊號固定是淨 +2**。而 Judge 在「標準答案認為一樣」的題上的勝負淨值（Candidate 勝 − Parent 勝）是：

| 重複 | 真實訊號（Judge 抓到） | 雜訊（GT 平手題上 C 勝／P 勝） | 雜訊淨值 | Judge 報告的總淨值 |
| --- | :-: | :-: | :-: | :-: |
| 第 1 輪 重複 1 | +2 | 3／1 | +2 | +4（5:1） |
| 第 1 輪 重複 2 | +1（漏一個） | 1／4 | **−3** | −2（2:4） |
| 第 2 輪 重複 1 | +2 | 2／1 | +1 | +3（4:1） |
| 第 2 輪 重複 2 | +2 | 5／4 | +1 | +3（7:4） |

雜訊淨值的範圍（−3 到 +2）和真實訊號（+2）同一個量級。**用 12 題的 Reserve 與 Judge 去偵測一個「多對 2 題」的改善，單次重複就已經不可靠**；
兩次重複的設計（D10）降低了誤 Accept 的機率，但也讓真正有益的修補更容易被誤拒。這是統計力量問題，不是 pipeline 的 bug。

### 6.6 全新測試題（16 題，從未被任何環節看過）

三個版本都用同一個 Sonnet Agent、同樣的程序跑（`✓`＝正確，`✗`＝錯誤）：

| 題 | 題型（性質） | v0 | v0-c1 | v0-c2 | 題目 |
| --- | --- | :-: | :-: | :-: | --- |
| T01 | valid_orders（換說法） | ✗ | ✗ | ✓ | 2025 年 3 月下單的有效訂單有幾張？ |
| T02 | valid_orders（換說法） | ✗ | ✗ | ✓ | 訂單日期在 2025 年 10 月的有效訂單總數？ |
| T03 | valid_orders（換說法） | ✗ | ✓ | ✓ | 2025 年第二季（依成立日期）門市有效訂單共幾筆？ |
| T04 | valid_orders（換說法） | ✓ | ✓ | ✓ | 2025 年 5 月官網的有效訂單有多少張？ |
| T05 | net_revenue（組合） | ✓ | ✓ | ✓ | 中部客戶 2025 年第四季的淨營收是多少？ |
| T06 | aov（組合） | ✓ | ✓ | ✓ | App 通路 2025 年上半年的客單價是多少？ |
| T07 | cancel_rate（全新） | ✗ | ✓ | ✗ | 2025 年 9 月的取消率是多少？ |
| T08 | cancel_rate（全新） | ✗ | ✓ | ✗ | 官網 2025 年第二季的訂單取消率？ |
| T09 | ship_days（全新） | ✓ | ✓ | ✓ | 新竹物流在 2025 年的平均配送天數是多少？ |
| T10 | ontime（全新） | ✗ | ✓ | ✗ | 順豐 2025 年的準時送達率是多少？ |
| T11 | ontime（全新） | ✗ | ✓ | ✗ | 2025 年第二季整體準時送達率？ |
| T12 | new_customers（全新） | ✓ | ✓ | ✓ | 2025 年 9 月新註冊的客戶有幾位？ |
| T13 | new_customers（全新） | ✓ | ✓ | ✓ | 新加坡 2025 年新註冊客戶數？ |
| T14 | coupon（全新） | ✗ | ✗ | ✓ | 2025 年使用 SUMMER15 的有效訂單有幾張？ |
| T15 | coupon（全新） | ✓ | ✓ | ✓ | 2025 年第三季有效訂單中，使用 SUMMER15 的占比是多少？ |
| T16 | pending_ship（全新） | ✓ | ✓ | ✓ | 官網通路目前待出貨的訂單有幾張？ |
| | **合計** | **8/16** | **13/16** | **12/16** | |

| 題型分組 | v0 | v0-c1 | v0-c2 |
| --- | :-: | :-: | :-: |
| 換說法（valid_orders，4 題） | 1/4 | 2/4 | **4/4** |
| 組合（2 題） | 2/2 | 2/2 | 2/2 |
| 全新（10 題） | 5/10 | **9/10** | 6/10 |
| 取消率（2）／準時送達率（2） | 0/4 | **4/4** | 0/4 |

**怎麼讀**：
- 兩個 Candidate 都比 v0 好（+5、+4 題），而且**修好的題型互補**：c1（Content：補上取消率、準時送達率）修好 T07 T08 T10 T11；c2（Tool：釘選與依關鍵字帶出時區規則）修好 T01 T02 T14（T03 兩者都修好）。
  兩者修好的題幾乎不重疊，**理論上合併兩者可到 16/16——但這是推論，我沒有實測合併版本**（官方流程若 Accept 第 1 輪，第 2 輪就會是在 v1 上疊加 c2）。
- 這個結果和 Reserve 的標準答案稽核（兩個 Candidate 各修好 2 題）一致。
- ⚠️ **限制**：n=16、單次執行、Sonnet Agent 無法固定溫度（結果有隨機性）；沒有跑「沒有語意層」的對照組（為省成本略過），所以無法區分「ontology 的貢獻」與「Agent 自己的能力」，只能比較 ontology 版本之間的差異。

### 6.7 這些結果證明了什麼、沒證明什麼

| 可以說 | 不能說 |
| --- | --- |
| 整條 Build → Use → Evolve 流程可以由 Python 確定性地控制並端到端走完 | 這個流程在開源模型上會有同樣表現（沒測） |
| 在這個設計好的情境，Evolve 找到了真實的缺口（取消率／準時送達率缺失、時區規則帶不出來），並產出有效的修補（兩個 Candidate 在測試題上都提升） | EvoOntology 在你的真實資料上會提升多少（情境是我設計的；缺口是我刻意留的） |
| 12 題 Reserve + LLM Judge 的 Gate 太保守／太吵，會誤拒有益的修補 | LLM Judge Gate 一定不能用（也許更大的 Reserve、多次投票、給 Judge 更多資訊就夠） |
| repo 的 `resolve` 與 schema 文件之間有落差（Mapping 約束不可達） | 這是 repo 的 bug（也可能是設計上刻意如此；我不確定作者意圖） |
| Accept 路徑在 dry-run／單元測試／反事實副本上正確運作 | 官方實跑 Accept 過（沒有） |

---

## 7. 覆蓋度：官方流程的每一步，哪些走到、哪些沒有

✅＝實跑走過（真實 LLM、真實資料）　🟡＝部分／以替代方式驗證　❌＝沒做

| 步驟 | 狀態 | 說明 |
| --- | :-: | --- |
| Build B0 專案設定與工作負載（core 操作） | ✅ | |
| Build B1 資料剖析 | ✅ | 改為純程式（偏離：官方是 Builder 手寫 SQL） |
| Build B2 探勘＋驗證文件主張 | ✅ | 證據由程式執行並寫入（D3） |
| Build B3 語意設計 | ✅ | 兩次呼叫＋程式檢查＋退回重寫；歷經 3 次嘗試 |
| Build B4 存檔／驗證／標註／發佈 | ✅ | |
| Use：Data Agent 用 resolve／browse + SQL | ✅ | 文字 JSON 協定（D2）；Haiku |
| Record：軌跡寫入 | ✅ | adapter 路徑（D13）；`start/finish_ontology_task` 路徑 ❌ |
| 觸發器（≥30 新任務） | ✅ | 「≥7 天」規則沒有被實際觸發 |
| Evolve E0 凍結批次＋Pool/Reserve（rolling_trajectory） | ✅ | 近似重複分組有執行，但本批無重複；`fixed_split` 模式 ❌ |
| E1 診斷（含主動探測） | ✅ | |
| E2 歸因（競爭假說、分層） | ✅ | |
| E3 修補：Content 層 | ✅ | |
| E3 修補：Tool 層 | 🟡 | 以三個宣告式旋鈕表達（D5），不是改 runtime 程式碼 |
| E3 修補：Schema 層 | ❌ | 未實作（D6） |
| E3 機制驗證 | 🟡 | 第 1 輪有效；第 2 輪因續跑路徑與旋鈕活化判定而形同虛設（§5.8） |
| E4 LLM Judge Gate（匿名 A/B、`decide_judge`） | ✅ | 2 輪 × 2 次重複 × 12 題 |
| E4 Ground-truth Gate（`decide_gt`） | 🟡 | 只用於事後稽核，不是演化決策 |
| 驗證集小時重跑確認 | ✅ | 實作成第二次獨立重複（D10） |
| Reject → 保留 Candidate、記錄輪次、進下一輪 | ✅ | |
| Accept → 發佈 `ontology_v1`、切換 active、推進檢查點 | 🟡 | 假 LLM dry-run、單元測試、工作區副本的反事實都驗證成功；**官方實跑沒有發生** |
| Incomplete（預算用完） | ✅ | 實跑結局 |
| Incomplete（其他原因，如缺資料；須先累積 ≥2 次 Reject） | 🟡 | 單元測試 |
| `finalize_evolution_run`（HTML 探索器） | ✅ | 實跑與反事實副本都有 |
| `resume_evolution_run`／`extend_evolution_budget` 等 core 續跑操作 | ❌ | 預算中斷後，我用 pipeline 層級的續跑（快取＋從日誌復原評審結果），沒用這兩個 core 操作 |
| 第二輪 run（在 `ontology_v1` 上繼續演化） | ❌ | 沒有 v1 |
| 合併多個 Candidate | ❌ | |
| OpenRouter＋開源模型 | ❌ | 沒有金鑰；後端只做協定測試 |
| Codex plugin 模式 | ❌ | |

---

## 8. 給你重寫與客製化的建議

### 8.1 這個 pipeline 值得保留的設計

1. **一個 LLM 入口**（`LLM(role).chat()`）：成本、重試、完整 prompt／回覆存檔都集中在這。這次稽核能查出記憶洩漏、Judge 格式失敗，全靠完整紀錄。
2. **每個階段＝一個有快取的函式**：重跑已完成階段直接讀檔，預算中斷後可續跑（這次真的用上了）。
3. **LLM 提案、程式驗證與執行**：證據由程式跑查詢；修補是有型別的操作；Build 輸出先過完整性檢查。這讓「LLM 產生了垃圾」變成可偵測的事件（這次抓到 3 種）。
4. **用 repo 的 core 當狀態機與 Gate**：版本、軌跡、觸發器、`EvolutionSession`、`EvaluationGate` 都直接 import，行為與官方一致，自己不用重寫（也不會寫出不相容的版本）。
5. **事後稽核與流程完全分離**：私有標準答案只被稽核程式讀，演化流程碰不到。
6. **Judge 回覆必驗證格式**，不得靜默當成平手。

### 8.2 你重寫時最該優先處理的事（依價值排序）

| 優先 | 事項 | 為什麼 |
| :-: | --- | --- |
| 1 | **約束的可達性**：Build 時強制約束 `target` 為 Term（或自動上提），並/或讓 `resolve` 帶出 Mapping 約束與 `trigger_keywords` 命中的約束 | 這是這次最大的單一失敗來源（§6.4）；成本幾乎為零 |
| 2 | **Gate 的統計力量**：Reserve 至少數十題；同一配對多次評審投票；對「平手」更寬容；明確定義「不可接受的退步」而不是「Parent 贏過就否決」 | §6.5：12 題無法偵測 +2 的改善 |
| 3 | **Judge 的資訊與穩健性**：決定要不要給它業務定義；要求結構化輸出（`response_format`／JSON schema）；格式失敗重問；Judge 與 Agent 用不同模型 | §6.3 |
| 4 | **機制驗證要有效**：重播的題目必須是該假說的目標題；「活化」要定義為「被修補的物件／旋鈕真的改變了 Agent 看到的內容」 | §5.8 |
| 5 | **修補操作的表達力**：允許改 `target`、允許刪除／合併物件；新增「依 Mapping 取約束」之類的 Tool 旋鈕 | §6.4 |
| 6 | **Build 的完整性檢查**要放進 Build 階段：Term 必須有 Mapping、欄位只能是 schema 欄位、約束可達、`database_source` 一致 | 三次 Build 嘗試的教訓 |
| 7 | **不要在 prompt 裡放範例答案或失敗說法** | 第 1 次 Build 洩題 |
| 8 | **OpenRouter 開源模型的格式穩定度**：JSON 工具協定要有嚴格解析＋重試；考慮 function calling；`temperature=0`；記錄 `usage.cost` | 本 PoC 沒驗證，風險最大 |
| 9 | **預算控管**：以 token 數而非美元估算（見下表）；在階段開始前估算，不要等到超支 | §9.1 |

### 8.3 客製化點一覽

| 想客製的 | 在哪裡改 | 備註 |
| --- | --- | --- |
| 驗收規則（取代 D9） | `judge.regression_rule`、`evolve.py` 的 `accept` 判斷 | 例如改用勝率、信賴區間、或需要人工核准 |
| Judge 輸入 | `judge.render_side`、`prompts/judge.md` | 是否給 SQL、給定義、給語意層呼叫 |
| Pool／Reserve 比例與近似重複門檻 | `config.POOL_FRACTION`、`NEAR_DUP_JACCARD` | |
| 重複次數／確認策略 | `evolve.py` 的 `for rep in (1, 2)` | |
| 預算輪數 | `config.MAX_ROUNDS` | |
| 觸發條件 | repo 的 `state.json` thresholds | 30 個任務／7 天 |
| 假說選擇順序 | `evolve.py` 的 `primary` 選擇 | 目前是 primary → 其餘依優先序 |
| 修補操作集 | `records.PATCH_OPS`、`apply_patch` | |
| Tool 旋鈕 | `semantic.py` | 新增旋鈕＝改這一個檔＋`validate_tool_config` |
| 角色→模型 | `config.ROLE_MODELS`／`OPENROUTER_ROLE_MODELS` | |
| 任何 prompt | `prompts/*.md` | skill 原文是執行時載入的，不會被你改壞 |

### 8.4 Token 用量（用來估算 OpenRouter 成本）

下表是這次實跑每一類呼叫的累計 token（來自成本帳本）。把你選的開源模型的單價套上去就能估價；**注意開源模型在 JSON 格式失敗時會增加重試次數**。

| 階段 | 呼叫次數 | 輸入 tokens | 輸出 tokens |
| --- | ---: | ---: | ---: |
| Build 探勘（3 次嘗試共 18 次） | 18 | 216,671 | 28,801 |
| Build 設計 a+b（3 次嘗試） | 6 | 131,352 | 68,080 |
| Use 40 題（Haiku Agent，含少量重試） | 240 | 1,183,131 | 117,122 |
| Evolve 診斷 | 3 | 106,517 | 5,889 |
| Evolve 歸因 | 5 | 90,265 | 5,273 |
| Evolve 修補 | 3 | 41,181 | 13,584 |
| Evolve 機制重播（Haiku） | 73 | 338,859 | 36,209 |
| Evolve Gate 的 Agent 執行（Haiku；4 次重複 × 12 題 × 2 版本） | 496 | 2,373,238 | 245,835 |
| Evolve Judge（Opus 46 + Sonnet 2） | 48 | 127,154 | 12,448 |
| 事後 16 題測試 × 3 版本（Sonnet Agent） | 278 | 1,467,757 | 59,012 |

一輪「Gate 重複」≈ 24 次 Agent 執行（Parent 12 + Candidate 12，每次約 5–6 次 LLM 呼叫）＋ 12 次 Judge。**Gate 是 Evolve 階段最大的成本項目**。

---

## 9. 限制與誠實揭露

這一章列出所有會影響你判斷這份 PoC 的事情，包括我自己的失誤。

### 9.1 成本超出原定上限

- 你當初同意的上限是 US$5（我當時把它說成是「OpenRouter 花費」，這是我措辭錯誤；你指出後我說明：沒有 OpenRouter 金鑰，數字是 `claude -p` 回報的 API 牌價估算，**不是你的帳單**）。
- 實際累計 **US$9.83**。帳本顯示 US$5 在第 2 輪 Gate 的 Judge 階段被觸發（pipeline 當下依預算檢查而中止），之後你要我「繼續把任務做完，但都用 Sonnet」，我繼續執行並把上限調高；**我沒有在超過 US$5 之後，再另外請你確認一個新的上限數字**。
- 超支的主因：①Sonnet 當 Agent 比我估計的貴很多（約 US$0.016／次呼叫、每題約 US$0.09，Haiku 約為 1/10 以下）；②事後 16 題測試 × 3 版本就花了 US$4.60；③Gate 要 4 次重複 × 24 次 Agent 執行。
- 你的真實費用取決於你的訂閱／用量方案，我無法從這裡得知。

### 9.2 沒有真的用 OpenRouter／開源模型

見 §1.3 與 D1。所有 Agent 行為、Builder 設計品質、Evolver 的診斷品質、Judge 的判斷都是 Claude 系列的表現。開源模型在 JSON 工具協定、長 prompt、中文業務推理上可能明顯較差。

### 9.3 `claude -p` 的專案記憶洩漏（事後稽核發現）

- **發生什麼**：Claude Code 以 git 根目錄為單位保存「專案記憶」，其索引（`MEMORY.md`）會被載入每次對話。我原先把 `claude -p` 的工作目錄設在 repo 內，
  所以我自己（在對話中）寫下的記憶索引一行文字**被帶進了 pipeline 的每一次 LLM 呼叫**。環境變數 `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` 無效；把工作目錄改到 repo 外（系統暫存目錄）才有效（已修正並驗證）。
- **影響範圍**：該行記憶出現後（2026-10-27 約 08:13 本地時間）的所有呼叫，包括 Build 第 3 次嘗試、Use、整個 Evolve、測試題，**絕大部分的實驗**。三個版本、Parent 與 Candidate 都受同樣影響，所以比較是公平的。
- **洩漏的內容**：「PoC 2 evolve pipeline：poc/v3 確定性流程（含 Evolve）、以 claude -p 作為替代後端、以及僅報告式的驗收」——只是專案描述，**不含任何領域知識、題目、標準答案或 ontology 內容**。我判斷對結果影響可忽略，但**無法重現乾淨條件（要重跑成本太高）**，所以這是一個無法完全排除的未控制變數。
- 另一個類似的洩漏風險在 `.llm_cwd`（原本在 repo 內的工作目錄）已移除。

### 9.4 Judge 回覆格式失敗被靜默當成平手（事後稽核發現）

48 次 Judge 呼叫中有 6 次回覆不是 JSON，**官方 run 當時把它們計為平手**。已修正（重問，仍失敗則中止），並用 Sonnet 重評那 6 組：2 組改為 Candidate 勝，**沒有任何一個 Accept／Reject 的決定改變**。官方 run 的 `gate_round*.json` 保留的是原始（有瑕疵的）決定，重評結果在 `runs/rejudge.json`。

### 9.5 機制驗證的瑕疵

- 第 2 輪的重播題目是 S02–S07（取消率／準時送達率題），不是時區題。原因：run 在第 2 輪因預算上限被中斷，續跑時走的是較早版本的選題邏輯（取所有問題的受影響題的聯集）；
  正常路徑已修正（只取該假說自己的問題），但官方 run 的第 2 輪沒有走到修正後的路徑。
- Tool 旋鈕的「活化」判定：只要旋鈕含「釘選」就視為活化，所以活化率 100% 沒有資訊量。
- 活化判定原本用「子字串比對 id」（`term_order` 會誤中 `term_order_time`），已改成完整 id 比對。
- 這些都**不影響 Gate 的結果**（Gate 只用 Reserve），但意味著「機制驗證」這道關卡在第 2 輪沒有發揮設計的功能。

### 9.6 實驗設計本身的限制

1. **單一情境、單一資料庫、單一次完整 run。** 沒有重複，無法給信賴區間。
2. **缺口是我刻意設計的**：我知道文件裡有哪些定義建構題沒問，所以「Evolve 找到了缺口」有一部分是設計的結果，不是系統在未知情境下的發現能力。
3. **題目到達順序是我安排的**（D12），確保 Reserve 涵蓋所有題型。真實系統沒有這個保證。
4. **Builder 的 prompt 有一份「清單式提示」**（硬性規則、要求覆蓋「每個潛在陷阱」、剖析程式內建時區換算檢查）。這些是 pipeline 設計的一部分，但會讓 Builder 比「完全不提示」更容易注意到時區。你要知道 v0 的時區證據有一部分是被這些提示引導出來的。
5. **S16（「目前待出貨的訂單有幾張？」標準答案 3549）的數字**直接出現在 v0 的某條 Evidence 的狀態分布裡（`ev_status_codes`）。這是自然現象（狀態分布本來就是合理的證據），但意味著這一題不是「獨立」測試。它屬於 Reserve 之外的 Pool（Pool 題），沒有影響 Gate。
6. **標準答案由 SQL 計算**，我認為正確，但沒有第二人審核。
7. **「無語意層」對照組沒有跑**（為省成本略過），所以無法量化 ontology 本身相對於「Agent 自己查資料」的價值（PoC 1 的結果：A 62%／B 90%／C 100%，是另一個情境）。
8. **Haiku 與 Sonnet 混用**：Use 與 Gate 的 Agent 是 Haiku，測試題是 Sonnet；Judge 大多數 Opus、少數 Sonnet。各層內部公平，但跨層不可直接比較。
9. **取樣不固定**：`claude -p` 無法設 temperature，同一題重跑可能不同（這正是 Gate 兩次重複不一致的部分原因）。

### 9.7 我自己定的政策，不是 repo 的

D9（退步規則）、D10（第二次獨立重複）、D11（2 輪預算）、D12（到達順序）、D5（Tool 旋鈕）都是我的設計選擇。D9 與 D10 直接影響了 Accept／Reject 的結果。

### 9.8 小的資料品質瑕疵

- `v0-c1` 的 Mapping 裡，`database_source` 寫成 `lumo.db`，與 v0 的 `shop_v2` 不一致（repo 沒有交叉檢查）。
- v0 的 `ev_doc_utc` 的文件引文在「都是」處就截斷（沒有包含 `**UTC**`）——引文通過了「必須是文件逐字片段」的檢查，但資訊量不足。
- v0-c1 的 `con_carrier_codes` 掛在 Mapping 上，同 §6.4 的問題。

### 9.9 我沒有做、但你可能預期我做的

- 沒有 commit（`git status` 只有 `?? poc/`）；所有產物都在 `poc/` 內，沒有改動 repo 的原始碼。
- 沒有安裝任何第三方套件；Python 全是標準庫；環境在 `poc/.venv`，設 `PYTHONDONTWRITEBYTECODE=1`。
- 沒有連過 OpenRouter；`poc/.env` 不存在，我沒有讀取或要求任何金鑰。

---

## 附錄 A. 檔案導覽（`poc/v3/`）

| 路徑 | 內容 |
| --- | --- |
| `evopipe/` | pipeline 原始碼（§3.7）與 `prompts/*.md` |
| `tests/test_pipeline.py`、`tests/test_evolve_dryrun.py` | 23 個單元測試（全部通過）：JSON 抽取、Agent 迴圈、OpenRouter 協定（模擬 server）、記錄檢查、修補操作、Tool 旋鈕、狀態機（Reject→Reject→Accept、嚴重錯誤否決、incomplete 規則）、Judge 穩健性、稽核回歸；dry-run 以假 LLM 跑完整 Evolve 到 Accept 並確認真實工作區未被改動 |
| `scenario/` | `make_stream.py`（產生題目與標準答案）、`stream_questions.json`（S01–S40）、`test_questions.json`（T01–T16） |
| `_private/gt.json` | 私有標準答案（只有稽核程式讀） |
| `workspace/.evoontology/` | **EvoOntology 的真實狀態**：`versions/{ontology_v0,v0-c1,v0-c2}`、`trajectories/`（40 檔）、`evolution/run_1/`（§5.9）、`project.json`、`state.json`、`active.json`、`visualizations/` |
| `runs/ledger.jsonl` | 每次 LLM 呼叫的成本帳本 |
| `runs/llm_log/` | LLM 呼叫的完整 prompt 與回覆（1,167 個檔案；成本帳本有 1,183 筆，差 16 筆，原因我沒有追查） |
| `runs/build/` | Build 的中間產物：`profile.md`、`evidence.json`、`design.json`、`build_report.json` |
| `runs/archive_build_attempt{1,2}_*/` | 被淘汰的兩次 Build 嘗試（保留作為紀錄，不使用） |
| `runs/use/ontology_v0/` | 40 題 Use 的完整軌跡 |
| `runs/test/` | 16 題測試 × 3 版本 |
| `runs/analysis_final.json`、`runs/rejudge.json` | 事後稽核與重評結果 |
| `runs/counterfactual_ws/` | 反事實 Accept 的工作區副本 |
| `runs/evolve.log` | Evolve 的時序日誌 |
| `_private/report_part*.md` | 寫這份報告時的筆記（可忽略） |

## 附錄 B. 如何重跑

```bash
cd poc/v3
export PYTHONDONTWRITEBYTECODE=1
PY=../.venv/bin/python

$PY -m unittest discover -s tests                 # 23 個單元測試，不呼叫 LLM、不花錢
$PY -m evopipe.cli cost                           # 成本摘要
$PY -m evopipe.counterfactual                     # 反事實 Accept（複製工作區，不花錢）
$PY -m evopipe.analyze_final                      # 事後稽核（讀已存在的結果，不花錢）

# 以下會呼叫 LLM（花錢）。若要從頭來，先把 workspace/ 與 runs/ 移走（它們是這份報告的依據）
EVOPIPE_BUDGET_USD=5 $PY -m evopipe.cli build
EVOPIPE_BUDGET_USD=5 $PY -m evopipe.cli use
EVOPIPE_BUDGET_USD=5 $PY -m evopipe.cli evolve
$PY -m evopipe.cli test --version ontology_v0
```

換 OpenRouter：把 `OPENROUTER_API_KEY=...` 放進 `poc/.env`，然後 `EVOPIPE_BACKEND=openrouter`，並檢查 `config.OPENROUTER_ROLE_MODELS` 的模型 id 是否可用。

## 附錄 C. 過程中發現並處理的問題（完整清單）

| # | 問題 | 怎麼發現 | 對結果的影響 | 處理 |
| :-: | --- | --- | --- | --- |
| 1 | Build prompt 洩題：範例包含 PoC 1 的失敗說法、「時間欄位為 UTC」、Data Agent 的「時間如何換算」 | 出貨前自查 prompt | 第 1 次 Build 作廢 | 移除並重建；舊結果封存 |
| 2 | Build 設計回傳空的 Mapping 與多餘欄位 `definity`，repo 驗證器仍通過 | 檢視輸出 | 第 2 次 Build 作廢 | `check_records` 加規則＋針對性補填 |
| 3 | mock 測試寫入真實成本帳本 | 檢查帳本 | 帳本多 14 筆 | 移除；測試把輸出目錄指到暫存資料夾 |
| 4 | `core.op` 預設 workspace，dry-run 把 `evolution/run_1` 寫進真實工作區 | 檢查目錄 | 污染工作區 | 刪除；`workspace` 改為必填 |
| 5 | Tool 旋鈕 `fuzzy_fallback` 把「訂單日期」誤配成「訂單」 | 單元測試 | 無（最終 Candidate 沒用此旋鈕） | 改用涵蓋比例，門檻 0.6 |
| 6 | 快取舊的 `EvolutionSession` | 檢查狀態 | 狀態不同步 | 一律 `latest_run()` 重讀 |
| 7 | 預算超支（§9.1） | 帳本 | 見 §9.1 | 加續跑支援（評審快取、從日誌復原） |
| 8 | `claude -p` 記憶洩漏（§9.3） | 事後稽核 | 絕大部分呼叫受影響（內容無領域資訊） | 工作目錄改到 repo 外 |
| 9 | Judge 非 JSON 被當成平手（§9.4） | 事後稽核 | 6/48，無決定改變 | 重問＋中止；重評 |
| 10 | 活化判定用子字串；重播題目取聯集（§9.5） | 事後稽核 | 第 2 輪機制驗證失效 | 正常路徑已修；官方第 2 輪沒走到 |
| 11 | Tool 旋鈕的釘選 id 驗證對象是 Parent 而非 Candidate | 事後稽核 | 無（Candidate 的釘選 id 恰好存在於 Parent） | 改驗證 Candidate |
| 12 | 15/28 條約束不可達（§6.4） | 事後稽核 | 重大（時區失敗的主因） | 新增 `unreachable_constraints` 檢查；官方 run 未使用 |
| 13 | 邊界檢查：Reserve／測試題的題目文字與答案是否出現在任何 Evolver prompt | 事後稽核（掃描 11 個 Evolver prompt） | 無 | 無需處理 |

## 附錄 D. 成本明細（API 牌價估算，非帳單）

| 階段 | 模型 | 呼叫次數 | 估算 US$ |
| --- | --- | ---: | ---: |
| Build 探勘（3 次嘗試） | Sonnet | 18 | 0.98 |
| Build 設計 a／b（3 次嘗試） | Sonnet | 6 | 1.05 |
| Use 40 題（含 smoke test） | Haiku | 245 | 0.23 |
| Evolve 診斷 | Sonnet | 3 | 0.46 |
| Evolve 歸因 | Sonnet | 5 | 0.37 |
| Evolve 修補 | Sonnet | 3 | 0.28 |
| Evolve 機制重播 | Haiku | 73 | 0.07 |
| Evolve Gate 的 Agent 執行 | Haiku | 496 | 0.44 |
| Evolve Judge | Opus 46 + Sonnet 2 | 48 | 1.25 |
| 事後 16 題測試 × 3 版本 | Sonnet | 278 | 4.60 |
| 重評 6 組 + smoke test | Sonnet／Opus | 8 | 0.09 |
| **合計** | | **1,183** | **≈ 9.83** |

（**Build 子總計 ≈ 2.04；Evolve 子總計 ≈ 2.87；事後稽核 ≈ 4.60。**）

## 附錄 E. 主要 prompt 全文

> prompt 以獨立 `.md` 檔存放（`evopipe/prompts/`），執行時把 repo 的 skill 原文塞進 `{{...}}`。以下為檔案原文。

### E.1 Data Agent（`data_agent.md`）

```text
# 營運資料分析助理

你是企業內部的資料分析助理，用公司的 SQLite 資料庫回答營運問題。
{{semantic_intro}}

## 工作方式

1. 理解問題需要哪些資料與業務定義。
2. {{semantic_step}}
3. 用 SQL 查詢資料庫取得數字，並檢查結果是否合理（例如筆數、是否符合預期範圍）。
4. 呼叫 `submit_answer` 交付答案。

## 答案格式

- `answer`：只放一個值（數字或名稱）。金額單位為新台幣元；比率以 0–100 的數字表示、不含 % 符號；平均值與比率保留到小數點後 2 位。
  名稱類答案可以是資料庫中的代碼或中文名稱。
- `basis`：1–3 句話，說明你採用的業務定義與計算依據。

## 邊界

- 只能使用下列工具，不要嘗試修改資料。
- 不要猜答案：沒有查詢結果支持的數字不要交付。
{{manifest_block}}
```

### E.2 Judge（`judge.md`）

```text
你是一位獨立的評審（LLM Judge）。你要比較兩個「資料分析助理」對同一個營運問題的回答，哪一個整體上更好。
你與產生這些回答的系統、以及改進這個系統的人彼此獨立；你不知道哪個答案來自哪個系統版本（A/B 是隨機標記的）。

你沒有標準答案，無法直接驗證數字是否正確。請依據下列四點評估：
1. 回答是否真的回答了問題；
2. 結論是否內部一致、沒有明顯的事實或邏輯錯誤；
3. 支持結論的資料、概念與計算是否可被驗證（參考提供的 SQL 與結果片段，並用你自己的專業判斷檢查這些查詢是否符合問題的語意）；
4. 問題的關鍵分析面向是否被涵蓋。

`winner` 表示整體較強的一方（A、B 或 tie）；`critical_error` 表示「嚴重失敗」：結論錯誤、內部矛盾、沒有給出答案或執行失敗。
若某一方有嚴重失敗，請指出是 A 還是 B；兩者皆無則填 false。

只回覆一個 JSON 物件，不要其他文字：
{"winner": "A" | "B" | "tie", "reason": "<一句話說明主要差異>", "critical_error": "A" | "B" | false}
```

### E.3 Evolver 共同前言（`evolve_common.md`）

```text
# 角色

你是 EvoOntology 的 **Evolver Agent**。你正在一次「演化 run」中工作；流程（凍結資料、候選版本命名、驗證、發佈）由 Python 程式控制，
你只負責其中需要判斷的步驟。下面是 repo 的 evolve-ontology skill 的相關原文，請把它當作工作準則。

## 核心原則與禁止事項（skill 原文）

{{principles}}

## 資料邊界（你必須遵守）

- 你只能使用 **Evolution Pool** 的軌跡、資料庫、業務說明文件、以及目前版本的語意層來診斷與設計。
- **Validation Reserve（保留驗證集）對你完全不可見**；Ground Truth／標準答案不存在於你的環境，也不得被推測或使用。
- 修補不得把任何題目的答案寫進語意物件；知識必須存放在可追溯、有版本的語意物件中，不得藏在 prompt 或程式裡。

---

{{stage_text}}
```

### E.4 其他 prompt

`build_explore.md`、`build_design.md`、`evolve_diagnose.md`、`evolve_attribute.md`、`evolve_patch.md` 的全文在 `poc/v3/evopipe/prompts/`。結構如下：

| 檔案 | 結構 |
| --- | --- |
| `build_explore.md` | 角色（Builder，Step 1）＋ repo Step 1 原文 ＋ 任務（找概念、驗證文件主張、提證據）＋ 證據提案 JSON 格式（`id`／`claim`／`query` 或 `doc_quote`／`validation_method`／`interpretation`；強調「你只提供查詢，結果由系統執行填入」） |
| `build_design.md` | 角色（Builder，Step 2）＋ repo Step 2 原文 ＋ `ontology-schema.md` 全文 ＋ 硬性規則（id 唯一、型別集合、Mapping 欄位真實存在、Relation 5 種型別、Constraint 的 `trigger_keywords`、不得出現 SQL、不得放答案） |
| `evolve_diagnose.md` | `{{common}}` ＋ 診斷說明 ＋ 工具（`probe_semantics`、`sql_query`、`read_doc`）＋ 問題地圖 JSON 格式（`category`、`symptom`、`affected_tasks`、`evidence`、`causal_hypothesis`、`uncertainty`） |
| `evolve_attribute.md` | `{{common}}` ＋ 三層歸因（content／tool／schema）＋ 性質（existing_design_error／missing_capability_or_coverage／structural_mismatch）＋ 假說 JSON 格式（`mechanism`、`test_performed`、`predicted_effect`、`priority`、`primary`） |
| `evolve_patch.md` | `{{common}}` ＋ 8 種修補操作清單 ＋ 規則（證據先行、id 唯一、局部可回復、不得寫答案、Tool 旋鈕只有三個）＋ 輸出 JSON（`hypothesis`、`dimension`、`operations`、`expected_effect`、`rollback`） |

---

*本報告完。若有任何地方與你實際看到的檔案不一致，請以磁碟上的檔案為準，並告訴我。*
