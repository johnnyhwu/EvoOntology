{{common}}

# 本階段：Step 2 — 歸因（Attribute causal mechanisms）

輸入是 Step 1 的問題地圖。你要把問題歸因到最相關的層：
- **content**：語意知識本身錯誤、不完整、粒度不當或涵蓋不足（缺概念、缺別名、缺規則、缺對應）；
- **tool**：工具的能力、介面、檢索、排序、回傳內容或互動方式限制了使用（例如規則存在但取不到）；
- **schema**：目前的物件模型無法可靠表達需求（本 PoC 的程式只能執行 content 與 tool 兩種修補；若你判斷主因是 schema，仍要如實歸因並說明，但請同時提出可由 content/tool 先行緩解的次要假說）。

並判斷性質：existing_design_error（現有設計造成錯誤）／missing_capability_or_coverage（缺少能力或涵蓋）／structural_mismatch（結構不合）。

請提出**彼此競爭**的因果解釋，並用工具（`probe_semantics`、`sql_query`）設計並執行小測試來比較它們；把「下游症狀」與「獨立根因」分開。
最後以 `submit_attribution` 交付：
```
{"hypotheses": [
  {"id": "H1", "problems": ["P1", "P3"], "dimension": "content | tool | schema",
   "nature": "existing_design_error | missing_capability_or_coverage | structural_mismatch",
   "mechanism": "<因果機制>", "test_performed": "<你做了什麼測試、結果如何>",
   "predicted_effect": "<若此假說正確，修補後哪些行為會改變>", "priority": 1}
 ],
 "primary": "H1",
 "reasoning": "<為什麼先驗證這一個：影響大小、證據強度、可重現性、驗證成本>"}
```
一次 Candidate 只驗證一個主要假說（`primary`）。
