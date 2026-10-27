{{common}}

# 本階段：Step 1 — 診斷（Diagnose）

輸入是 Evolution Pool 內 agent 的實際軌跡（已壓縮）、目前語意層的目錄、資料剖析與業務說明文件。
你可以用工具驗證你的懷疑：
- `probe_semantics`：用目前（Parent）版本的 browse/resolve 實際試打，看會回傳什麼（例如「換一種說法能不能查到某規則」）；
- `sql_query`：對資料庫做唯讀查詢，確認某個答案是否合理、某個業務定義在資料中是否成立；
- `read_doc`：重讀業務說明文件。

注意：沒有標準答案可以對照。判斷「哪裡可能錯了」要靠證據：軌跡中未命中的語意查詢（unresolved／空結果）、SQL 錯誤、
agent 的 basis 與業務文件／語意層規則不一致、語意層有規則但 agent 沒取到、語意層完全沒有涵蓋的分析需求（覆蓋缺口）等。
也要主動找「系統應該做到卻沒做」的地方，而不只看明顯的失敗。

完成後呼叫 `submit_problem_map`，args 格式：
```
{"problem_map": [
  {"id": "P1",
   "category": "execution_failure | coverage_gap | tool_limitation | structural_constraint | potential_gap",
   "symptom": "<觀察到的現象>",
   "affected_tasks": ["S01", "S07"],          // 只能填 Evolution Pool 內的題目 id
   "evidence": "<你憑什麼這樣說：軌跡中的哪個呼叫、你自己做了什麼探測與其結果>",
   "causal_hypothesis": "<可能原因>",
   "uncertainty": "<還不確定的地方>"}
 ],
 "summary": "<整體觀察，3-5 句>"}
```
