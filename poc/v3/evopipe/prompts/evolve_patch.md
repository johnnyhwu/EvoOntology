{{common}}

# 本階段：Step 3 — 修補（Patch the Parent system）

輸入是主要假說、Parent 版本的完整語意物件、目前的 Tool Layer 設定、資料剖析與業務文件。你不是重寫整個語意層，
而是**提出一組有型別的修補操作（operations）**，由程式套用到 Parent 的複本上產生 Candidate。

## 可用的操作

{{ops}}

規則：
- 新增的概念／規則必須有證據：先用 `add_evidence` 操作新增證據（你只提供查詢或文件逐字引文，程式會自己執行並寫入結果），
  再在新物件的 `evidence` 欄位引用該證據 id。證據 id 不可與既有 id 重複。
- id 必須全域唯一（不可與既有任何物件 id 衝突）；`trigger_keywords` 要包含問題中可能出現的各種說法。
- 修補要局部、可回復、直接驗證假說；不要順手做無關的改動。不得把任何題目的答案數字寫進物件。不得出現 SQL 語句或解題步驟。
- 若主因是 tool：`set_tool_config` 只能調整上述三個旋鈕。
- 若假說同時需要 content 與 tool 兩種改動，只要它們服務同一個機制，可以放在同一個 Candidate。

## 輸出格式（單一 JSON，不要其他文字、不要 markdown 圍欄）

```
{"hypothesis": "<一句可被證偽的假說：目前的限制、為何造成問題、修補後預期行為如何改變、什麼證據會推翻它>",
 "dimension": "content | tool | content+tool",
 "operations": [ {...}, {...} ],
 "expected_effect": "<預期哪些類型的任務會改變>",
 "rollback": "<如何回復>"}
```
