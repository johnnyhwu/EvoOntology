import json

DB = "shop_v2"
DOC = "domain_knowledge.md (business doc, poc/build_input_v2)"
TS = "2026-10-22T10:54:00Z"

# ---------------------------------------------------------------- Evidence
EV = []


def ev(id, source, query, result, method):
    EV.append({"id": id, "source": source, "query": query, "result": result,
               "validation_method": method, "timestamp": TS})


ev("ev_schema", DB, "SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name",
   "7 tables: customers(customer_id,name,email,region_code,signup_date,tier); orders(order_id,customer_id,order_ts,status,channel,coupon_code); "
   "order_items(item_id,order_id,product_id,quantity,unit_price_cents); products(product_id,sku,product_name,category,list_price_twd,is_active); "
   "payments(payment_id,order_id,method,amount_twd,paid_ts,payment_status); refunds(refund_id,order_id,item_id,refund_amount_twd,refund_ts,reason_code); "
   "shipments(shipment_id,order_id,carrier,shipped_ts,delivered_ts). No cancellation-timestamp, status-history, tier-history or order-level region/address column exists. "
   "SELECT name FROM sqlite_master WHERE type='index' returns no rows.",
   "schema inspection")
ev("ev_fk_integrity", DB,
   "SELECT COUNT(*) FROM orders o LEFT JOIN customers c ON c.customer_id=o.customer_id WHERE c.customer_id IS NULL; "
   "SELECT COUNT(*) FROM order_items oi LEFT JOIN products p ON p.product_id=oi.product_id WHERE p.product_id IS NULL; "
   "SELECT COUNT(*) FROM order_items oi LEFT JOIN orders o ON o.order_id=oi.order_id WHERE o.order_id IS NULL",
   "0 orphan orders (no customer), 0 orphan order_items (no product), 0 orphan order_items (no order). Table row counts: customers 5000, orders 60000, order_items 104966, products 200, payments 61319, refunds 4039, shipments 44444.",
   "referential integrity check")
ev("ev_status_dist", DB, "SELECT status,COUNT(*) FROM orders GROUP BY 1",
   "0:3003, 1:3549, 2:4870, 3:39574, 9:9004 (only five distinct status codes)",
   "distinct value enumeration")
ev("ev_status_payment", DB,
   "SELECT o.status, p.payment_status, COUNT(*), COUNT(DISTINCT p.order_id) FROM payments p JOIN orders o ON o.order_id=p.order_id WHERE p.payment_id<=15000 GROUP BY 1,2 "
   "(also run for payment_id>15000 AND <=35000, and payment_id>35000)",
   "Across all three payment_id ranges: orders with status 0 and 9 only have payment_status='failed' payments; orders with status 1, 2, 3 each have exactly one 'ok' payment "
   "(ok rows = distinct ok orders in every range, e.g. status 3 ok 13028/13028 distinct) and may additionally have failed attempts (e.g. status 3 failed 1924 rows for 1531 orders). "
   "Failed attempts therefore exist on valid orders as well. paid_ts>=order_ts in all 15000 sampled payments.",
   "cross-table distribution over three id ranges (full scan exceeds the query budget)")
ev("ev_status_shipment", DB,
   "SELECT o.status, COUNT(*), SUM(s.delivered_ts IS NULL) FROM shipments s JOIN orders o ON o.order_id=s.order_id WHERE s.shipment_id<=15000 GROUP BY 1; "
   "SELECT COUNT(*), SUM(delivered_ts IS NULL) FROM shipments",
   "Sampled shipments belong only to status 2 (1660, all delivered_ts NULL) and status 3 (13340, delivered_ts never NULL). Full table: 44444 shipments, 4870 with NULL delivered_ts "
   "= number of status-2 orders (4870); 44444 = 4870 + 39574 (status 2 + status 3). Status 1/0/9 orders have no shipment. One shipment per order (n=1 for all 44444 order_ids).",
   "cross-table consistency of status with shipment records")
ev("ev_channel_values", DB, "SELECT channel,COUNT(*) FROM orders GROUP BY 1",
   "app:20970, store:8959, web:30071 (three clean values, no NULLs or case variants)", "distinct value enumeration")
ev("ev_region_values", DB, "SELECT region_code,COUNT(*) FROM customers GROUP BY 1",
   "JP:501, SG:238, TW-C:1289, TW-N:1985, TW-S:987 (five clean values)", "distinct value enumeration")
ev("ev_tier_values", DB, "SELECT tier,COUNT(*) FROM customers GROUP BY 1",
   "B:3539, G:491, S:970 (three clean values)", "distinct value enumeration")
ev("ev_category_active", DB, "SELECT category,is_active,COUNT(*) FROM products GROUP BY 1,2",
   "5 categories: accessory(0:8,1:32), apparel(0:6,1:34), backpack(0:6,1:34), shoes(0:6,1:34), tent(0:9,1:31); is_active has only values 0 and 1 (35 inactive, 165 active).",
   "distinct value enumeration")
ev("ev_payment_values", DB, "SELECT payment_status,method,COUNT(*) FROM payments GROUP BY 1,2",
   "payment_status in {ok, failed}; method in {atm, cod, credit_card, line_pay}; ok: atm 7330, cod 4792, credit_card 26469, line_pay 9402; failed: atm 1990, cod 1353, credit_card 7412, line_pay 2571.",
   "distinct value enumeration")
ev("ev_reason_values", DB, "SELECT reason_code,COUNT(*) FROM refunds GROUP BY 1",
   "R1:1194, R2:1621, R3:619, R4:605 (four clean values)", "distinct value enumeration")
ev("ev_unit_price_scale", DB,
   "SELECT ROUND(oi.unit_price_cents*1.0/p.list_price_twd,0) r, COUNT(*) FROM order_items oi JOIN products p ON p.product_id=oi.product_id WHERE oi.item_id<=10000 GROUP BY 1 ORDER BY 2 DESC",
   "unit_price_cents / list_price_twd takes only the values 100 (5988), 90 (2014), 85 (1012), 80 (986): unit_price_cents is 100x the TWD amount (cents), and the deal price equals list price in ~60% of rows and is 80-90% of list price otherwise. "
   "quantity is in {1:73448, 2:20997, 3:10521}.",
   "ratio of deal unit price to catalog price")
ev("ev_payment_equals_items", DB,
   "SELECT COUNT(*), SUM(t.s=p.amount_twd*100) eq FROM (SELECT order_id, SUM(quantity*unit_price_cents) s FROM order_items WHERE item_id<=4000 GROUP BY order_id) t "
   "JOIN payments p ON p.order_id=t.order_id AND p.payment_status='ok' WHERE t.order_id<(SELECT MAX(order_id) FROM order_items WHERE item_id<=4000)",
   "1822 of 1822 compared orders: sum(quantity*unit_price_cents) = payments.amount_twd*100 for the ok payment (the same also holds for 546 of 546 failed attempts). "
   "So order item amount = quantity x deal unit price / 100 TWD, and payments.amount_twd is the order's full merchandise amount in TWD for each attempt (not a per-item or partial amount). "
   "payments is NOT the source of merchandise amount because it also holds failed attempts and is dated by paid_ts.",
   "reconciliation of two candidate amount sources")
ev("ev_ts_format_range", DB,
   "SELECT length(order_ts),COUNT(*) FROM orders GROUP BY 1; SELECT MIN(order_ts),MAX(order_ts) FROM orders; SELECT MIN(paid_ts),MAX(paid_ts) FROM payments; SELECT MIN(refund_ts),MAX(refund_ts) FROM refunds",
   "order_ts is 'YYYY-MM-DD HH:MM:SS' (length 19 for all 60000 rows) with no offset marker; orders 2024-12-30 00:03:20 .. 2025-12-31 23:53:02; payments paid_ts 2024-12-30 00:06:20 .. 2025-12-31 23:56:02; refunds 2025-01-05 19:07:25 .. 2026-01-23 13:45:30. customers.signup_date is a 10-char date (2023-01-01..2025-12-31).",
   "format and range inspection")
ev("ev_tz_period_impact", DB,
   "SELECT SUM(order_ts<'2024-12-31 16:00:00'), SUM(order_ts>='2024-12-31 16:00:00' AND order_ts<'2025-12-31 16:00:00'), SUM(order_ts>='2025-12-31 16:00:00'), SUM(order_ts LIKE '2025%') FROM orders; "
   "SELECT SUM(strftime('%m',order_ts)<>strftime('%m',datetime(order_ts,'+8 hours'))) FROM orders; "
   "SELECT SUM(order_ts>='2025-02-28 16:00:00' AND order_ts<'2025-03-31 16:00:00' AND status BETWEEN 1 AND 3), SUM(order_ts LIKE '2025-03%' AND status BETWEEN 1 AND 3) FROM orders; "
   "SELECT SUM(refund_ts>='2025-08-31 16:00:00' AND refund_ts<'2025-09-30 16:00:00'), SUM(refund_ts LIKE '2025-09%') FROM refunds; "
   "SELECT SUM(refund_ts>='2024-12-31 16:00:00' AND refund_ts<'2025-12-31 16:00:00'), SUM(refund_ts LIKE '2025%'), SUM(refund_ts>='2025-12-31 16:00:00') FROM refunds; "
   "SELECT SUM(paid_ts>='2024-12-31 16:00:00' AND paid_ts<'2025-12-31 16:00:00' AND payment_status='ok'), SUM(paid_ts LIKE '2025%' AND payment_status='ok') FROM payments",
   "Shifting stored timestamps by +8h changes the calendar month of 655 of 60000 orders. Orders by Taipei time: 301 fall in 2024, 59643 in 2025, 56 in 2026 (vs 59648 with UTC year 2025). "
   "Valid orders in March 2025: 4128 by Taipei time vs 4144 by raw stored time; valid orders in 2025: 47699 vs 47701. Refund count in Sep 2025: 304 vs 307; refunds in 2025: 3861 vs 3862, and 178 refunds occur after 2025-12-31 16:00 (stored), 177 of them in 2026 by stored date. "
   "OK payments in 2025: 47699 vs 47703. Period boundaries therefore differ materially between raw and Taipei time.",
   "sensitivity of period counts to the UTC+8 conversion stated in the business document")
ev("ev_hour_distribution", DB,
   "SELECT CAST(substr(order_ts,12,2) AS INT) h, COUNT(*) FROM orders GROUP BY 1",
   "Orders are spread almost uniformly over all 24 stored hours (2382..2596 per hour), so the data itself cannot confirm or refute that stored timestamps are UTC; the UTC statement rests on the business document only.",
   "negative check: data-based timezone inference not possible")
ev("ev_refund_linkage", DB,
   "SELECT SUM(r.order_id=oi.order_id) same_order, COUNT(*) n, SUM(r.refund_amount_twd*100<=oi.quantity*oi.unit_price_cents) le_item, SUM(r.refund_amount_twd*100=oi.quantity*oi.unit_price_cents) eq_item FROM refunds r JOIN order_items oi ON oi.item_id=r.item_id; "
   "SELECT COUNT(*), SUM(r.refund_amount_twd*100<oi.quantity*oi.unit_price_cents) partial FROM refunds r JOIN order_items oi ON oi.item_id=r.item_id; "
   "SELECT o.status, COUNT(*) FROM refunds r JOIN orders o ON o.order_id=r.order_id GROUP BY 1; "
   "SELECT SUM(r.refund_ts<o.order_ts) FROM refunds r JOIN orders o ON o.order_id=r.order_id",
   "All 4039 refunds reference an existing order item and refunds.order_id always equals that item's order_id (4039/4039). Refund amount never exceeds the item amount (4039/4039); it equals the full item amount in 2798 and is a partial amount in 1241. "
   "All refunds belong to status-3 (delivered) orders (4039). No refund precedes its order. Each refund has a distinct item_id (4039 distinct); 455 orders have 2 refunds, 3129 have 1.",
   "referential and amount consistency of refunds")
ev("ev_customer_name_dup", DB, "SELECT COUNT(DISTINCT customer_id), COUNT(DISTINCT email), COUNT(DISTINCT name) FROM customers",
   "5000 distinct customer_id, 5000 distinct email, but only 380 distinct name: customer names are heavily duplicated, so name cannot identify a customer.",
   "uniqueness check")
ev("ev_product_keys_unique", DB, "SELECT COUNT(DISTINCT sku), COUNT(DISTINCT product_name), COUNT(*) FROM products",
   "200 distinct sku, 200 distinct product_name, 200 rows: both sku and product_name uniquely identify a product.",
   "uniqueness check")
ev("ev_inactive_products_sold", DB,
   "SELECT p.is_active, COUNT(*), COUNT(DISTINCT oi.product_id) FROM order_items oi JOIN products p ON p.product_id=oi.product_id WHERE oi.item_id<=30000 GROUP BY 1",
   "Among the first 30000 order items, inactive products (is_active=0) account for 4799 items over all 35 inactive products and active products for 25201 items over all 165 active products: is_active is a current-state flag on the product master, and discontinued products still appear in historical order items. products has one row per product with no activation history.",
   "cross-table check of product state vs sales history")
ev("ev_orders_per_customer", DB,
   "SELECT n, COUNT(*) FROM (SELECT customer_id, COUNT(*) n FROM orders WHERE status BETWEEN 1 AND 3 AND order_id<=20000 GROUP BY 1) GROUP BY 1",
   "Customers have between 1 and 21 valid orders in the sampled order_id<=20000 range (1:855, 2:598, 3:463, ... 21:1), so customers with 2 or more valid orders exist and customer_id is the grouping key on orders.",
   "distribution check (sample range)")
ev("ev_doc_time_rules", DOC,
   "Section 一 報表時間規則 (document text, no SQL)",
   "'系統資料表裡的所有時間戳記（訂單、付款、退款、出貨、送達）都是 UTC。所有營運報表一律用台北時間（UTC+8）劃分日期、月份、季與年度。客戶的註冊日期本來就是台北日期。第一季=1~3月，第三季=7~9月，上半年=1~6月。'",
   "business document statement (unverifiable from data alone, see ev_hour_distribution; impact quantified in ev_tz_period_impact)")
ev("ev_doc_definitions", DOC,
   "Section 二 名詞定義 (document text, no SQL)",
   "有效訂單=狀態為已付款/已出貨/已送達；商品金額=數量x成交單價(實際付的價格,非目錄標價)；淨營收=期間內有效訂單商品金額總和扣掉這些訂單對應的退款,期間依訂單成立時間歸屬,退款扣回原訂單,不看退款發生月份；"
   "客單價=期間內有效訂單商品金額總和(不扣退款)/有效訂單張數；回購客戶=某一年度內有效訂單達2張(含)以上的客戶；實收金額=付款成功的付款紀錄金額總和,依付款成功時間歸屬；"
   "退款金額(退款報表)=依退款發生時間歸屬期間,與淨營收歸屬方式不同；取消率與配送天數等其他定義另有說明。",
   "business document statements, each cross-checked against data in the evidence entries referenced by the object that uses it")
ev("ev_doc_codes", DOC,
   "Section 三 代碼對照 (document text, no SQL)",
   "orders.status 0待付款/1已付款/2已出貨/3已送達/9已取消; orders.channel web官網/app行動App/store實體門市; customers.tier B一般/S銀級/G黃金; customers.region_code TW-N北部/TW-C中部/TW-S南部/JP日本/SG新加坡; "
   "payments.payment_status ok付款成功/failed付款失敗; payments.method credit_card信用卡/line_pay LINE Pay/atm ATM轉帳/cod貨到付款; refunds.reason_code R1商品瑕疵/R2改變心意/R3寄錯商品/R4配送延遲; "
   "products.is_active 1在售/0已下架; products.category backpack登山背包/tent帳篷/shoes登山鞋/apparel機能服飾/accessory配件.",
   "business document code table; the set of codes was verified to equal the distinct values in the data, meanings of tier/region/reason/channel/is_active codes are document-only")
ev("ev_doc_no_units_sold_def", DOC,
   "Search of domain_knowledge.md for a definition of 銷售數量 / 商品銷量 / 在售商品銷量 (document text, no SQL)",
   "The document defines sales amount (商品金額) and valid orders but gives no explicit definition of '銷售數量' (units sold) or whether cancelled/unpaid orders count towards it. 在售 is defined only as products.is_active=1.",
   "absence check on the business document")

# ---------------------------------------------------------------- Terms
TERMS = []


def term(id, name, type, definition, scope, aliases, evidence):
    TERMS.append({"id": id, "name": name, "type": type, "definition": definition, "scope": scope,
                  "aliases": aliases, "evidence": evidence})


term("term_customer", "客戶 Customer", "entity",
     "購買商品的會員個體，每位客戶在客戶主檔中有一列，以 customer_id 識別。",
     "客戶屬性（地區、會員等級）為客戶主檔上的單一目前值；姓名不唯一，不可用姓名識別客戶。",
     ["customer", "會員", "顧客", "客戶"], ["ev_schema", "ev_customer_name_dup", "ev_tier_values", "ev_region_values"])
term("term_order", "訂單 Order", "entity",
     "客戶成立的一張訂單，含成立時間、狀態、通路與優惠碼；金額在明細層。",
     "包含所有狀態（待付款、已付款、已出貨、已送達、已取消）的訂單；是否算營運上的有效訂單取決於狀態。",
     ["order", "訂單", "訂單張數"], ["ev_schema", "ev_status_dist", "ev_fk_integrity"])
term("term_order_item", "訂單明細 Order Item", "entity",
     "訂單中的一個商品列，記錄商品、數量與成交單價。",
     "一張訂單有一到多筆明細；金額、銷售數量與商品類別都在明細層與商品主檔上取得。",
     ["order item", "line item", "訂單明細", "明細"], ["ev_schema", "ev_fk_integrity", "ev_unit_price_scale"])
term("term_product", "商品 Product", "entity",
     "商品主檔中的一個商品，以 product_id、sku 或 product_name 識別（三者皆唯一），有類別與是否在售狀態。",
     "商品屬性（類別、是否在售）為商品主檔上的目前值，沒有歷史版本。",
     ["product", "商品", "SKU", "品項"], ["ev_schema", "ev_product_keys_unique", "ev_inactive_products_sold"])
term("term_payment", "付款紀錄 Payment", "entity",
     "訂單的一次付款嘗試，含方式、金額、付款時間與成功或失敗狀態。",
     "一張訂單可有多筆付款嘗試（含失敗重試）；有效訂單各有一筆付款成功紀錄。",
     ["payment", "付款", "付款紀錄"], ["ev_schema", "ev_status_payment", "ev_payment_values"])
term("term_refund", "退款 Refund", "entity",
     "針對某筆訂單明細的一次退款，記錄退款金額、發生時間與原因。",
     "退款粒度是訂單明細；可為整筆或部分金額；只發生在已送達的訂單。",
     ["refund", "退款", "退費"], ["ev_schema", "ev_refund_linkage"])

term("term_customer_region", "客戶地區 Customer Region", "dimension",
     "客戶所屬地區，使用客戶主檔上的 region_code（北部、中部、南部、日本、新加坡）。",
     "是客戶屬性，不是訂單出貨地；訂單表沒有任何地區或地址欄位。報表上的「地區」對應此維度。",
     ["region", "地區", "區域", "region_code", "客戶所在地"], ["ev_region_values", "ev_schema", "ev_doc_codes"])
term("term_member_tier", "會員等級 Member Tier", "dimension",
     "客戶的會員等級：一般會員(B)、銀級會員(S)、黃金會員(G)。",
     "客戶主檔上的單一目前值，沒有等級歷史。",
     ["tier", "會員等級", "等級", "會員"], ["ev_tier_values", "ev_doc_codes"])
term("term_sales_channel", "下單通路 Sales Channel", "dimension",
     "訂單成立的通路：官網(web)、行動 App(app)、實體門市(store)。",
     "訂單層屬性。", ["channel", "通路", "下單通路", "渠道"], ["ev_channel_values", "ev_doc_codes"])
term("term_product_category", "商品類別 Product Category", "dimension",
     "商品的類別：登山背包(backpack)、帳篷(tent)、登山鞋(shoes)、機能服飾(apparel)、配件(accessory)。",
     "商品主檔屬性；訂單明細與退款的類別都透過所屬商品取得。",
     ["category", "商品類別", "品類", "類別"], ["ev_category_active", "ev_doc_codes"])
term("term_payment_method", "付款方式 Payment Method", "dimension",
     "付款紀錄使用的付款方式：信用卡(credit_card)、LINE Pay(line_pay)、ATM 轉帳(atm)、貨到付款(cod)。",
     "付款紀錄層屬性。", ["payment method", "付款方式", "支付方式"], ["ev_payment_values", "ev_doc_codes"])
term("term_refund_reason", "退款原因 Refund Reason", "dimension",
     "退款原因代碼：商品瑕疵(R1)、改變心意(R2)、寄錯商品(R3)、配送延遲(R4)。",
     "退款紀錄層屬性。", ["refund reason", "退款原因", "退貨原因", "reason_code"], ["ev_reason_values", "ev_doc_codes"])
term("term_order_status", "訂單狀態 Order Status", "dimension",
     "訂單目前所處的流程狀態：待付款(0)、已付款(1)、已出貨(2)、已送達(3)、已取消(9)。",
     "訂單層的目前狀態，沒有狀態變更時間；決定訂單是否為有效訂單。",
     ["order status", "訂單狀態", "狀態"], ["ev_status_dist", "ev_status_payment", "ev_status_shipment", "ev_doc_codes"])
term("term_product_sale_status", "商品在售狀態 Product Sale Status", "dimension",
     "商品目前是否在售：在售(1)或已下架(0)。",
     "商品主檔上的目前狀態旗標；已下架商品仍有歷史訂單。",
     ["is_active", "在售", "已下架", "仍在售", "上架"], ["ev_category_active", "ev_inactive_products_sold", "ev_doc_codes"])

term("term_order_time", "訂單成立時間 Order Time", "dimension",
     "訂單成立的時間（orders.order_ts），為淨營收、客單價、有效訂單數、取消訂單數、回購客戶等指標的期間歸屬時間。",
     "儲存值需先依業務規則換算成台北時間才能劃分日期、月、季、年。",
     ["order_ts", "訂單時間", "下單時間", "訂單成立時間"], ["ev_ts_format_range", "ev_tz_period_impact", "ev_doc_time_rules"])
term("term_payment_time", "付款成功時間 Payment Time", "dimension",
     "付款紀錄的付款時間（payments.paid_ts），為實收金額的期間歸屬時間。",
     "儲存值需先換算成台北時間；失敗的付款嘗試不構成實收。",
     ["paid_ts", "付款時間", "付款成功時間"], ["ev_ts_format_range", "ev_tz_period_impact", "ev_doc_time_rules"])
term("term_refund_time", "退款發生時間 Refund Time", "dimension",
     "退款發生的時間（refunds.refund_ts），為退款報表的期間歸屬時間。",
     "儲存值需先換算成台北時間；退款可發生在原訂單期間之後（資料中有 2026 年 1 月的退款）。",
     ["refund_ts", "退款時間", "退款發生時間"], ["ev_ts_format_range", "ev_tz_period_impact", "ev_doc_time_rules"])
term("term_reporting_calendar", "報表曆法 Reporting Calendar", "concept",
     "營運報表的期間劃分慣例：以台北時間（UTC+8）劃分日、月、季、年；第一季為 1-3 月、第二季為 4-6 月、第三季為 7-9 月、第四季為 10-12 月，上半年為 1-6 月。",
     "適用於所有以時間範圍提問的報表指標；各指標以哪個時間欄位歸屬期間由指標自己的規則決定。",
     ["季", "第一季", "第二季", "第三季", "第四季", "上半年", "年度", "月份", "台北時間", "Q1", "Q2", "Q3", "Q4"],
     ["ev_doc_time_rules", "ev_tz_period_impact"])

term("term_deal_unit_price", "成交單價 Deal Unit Price", "metric",
     "客人實際付的單價（已含折扣與優惠碼），儲存單位為分（TWD 的 1/100），不是商品目錄標價 list_price_twd。",
     "訂單明細層；與目錄標價不同：資料中約四成明細的成交單價低於標價（80%、85%、90%）。",
     ["unit_price_cents", "成交單價", "實付單價", "deal price"], ["ev_unit_price_scale", "ev_doc_definitions"])
term("term_units_sold", "銷售數量 Units Sold", "metric",
     "售出的商品件數，為訂單明細數量（每列 1 至 3 件）的加總。",
     "業務文件未明確定義銷售數量；本版以有效訂單的明細數量為準（假設），商品層級的排名依商品識別。",
     ["quantity", "銷售數量", "銷量", "件數", "賣出數量"], ["ev_unit_price_scale", "ev_doc_no_units_sold_def"])
term("term_item_amount", "商品金額 Item Amount", "metric",
     "訂單明細的數量 x 成交單價，換算為新台幣元（成交單價儲存單位為分，需除以 100）。",
     "不是商品目錄標價；不含退款扣除；在報表上限定在有效訂單與期間內加總。",
     ["商品金額", "銷售金額", "item amount", "GMV", "營業額"],
     ["ev_doc_definitions", "ev_unit_price_scale", "ev_payment_equals_items"])
term("term_refund_amount", "退款金額 Refund Amount", "metric",
     "退款紀錄的退款金額（新台幣元），可為對應明細的全額或部分金額。",
     "作為退款報表時依退款發生時間歸屬期間；作為淨營收的扣除項時依原訂單成立時間歸屬。",
     ["refund amount", "退款金額", "退款總計", "退款額"], ["ev_refund_linkage", "ev_doc_definitions"])
term("term_valid_order", "有效訂單 Valid Order", "concept",
     "狀態為已付款、已出貨或已送達的訂單；待付款與已取消的訂單不算有效訂單。",
     "營收、客單價、訂單數、通路占比與回購客戶等指標共用的訂單範圍。",
     ["valid order", "有效訂單", "有效單", "成交訂單"],
     ["ev_doc_definitions", "ev_status_dist", "ev_status_payment", "ev_status_shipment"])
term("term_valid_order_count", "有效訂單張數 Valid Order Count", "metric",
     "期間內有效訂單的張數（以訂單為單位計數，不是明細列數）。",
     "期間依訂單成立時間（台北時間）歸屬。",
     ["有效訂單數", "有效訂單張數", "訂單數", "訂單張數", "valid order count", "order count"],
     ["ev_doc_definitions", "ev_status_dist"])
term("term_net_revenue", "淨營收 Net Revenue", "metric",
     "期間內有效訂單的商品金額總和，扣掉這些訂單對應的退款金額。",
     "期間依訂單成立時間（台北時間）歸屬，退款扣回其所屬原訂單，不論退款發生在哪個月份。",
     ["net revenue", "淨營收", "營收", "淨收入"],
     ["ev_doc_definitions", "ev_refund_linkage", "ev_status_payment", "ev_tz_period_impact"])
term("term_avg_order_value", "客單價 Average Order Value", "metric",
     "期間內有效訂單的商品金額總和（不扣退款）除以有效訂單張數。",
     "期間依訂單成立時間（台北時間）歸屬；以訂單為單位，不以客戶或明細為單位。",
     ["AOV", "average order value", "客單價", "平均訂單金額", "每單平均金額"],
     ["ev_doc_definitions", "ev_payment_equals_items"])
term("term_repeat_customer", "回購客戶 Repeat Customer", "concept",
     "某一年度內有效訂單達 2 張（含）以上的客戶。",
     "以年度（台北時間）為計算窗口，以客戶識別碼計算；占比類指標的分母為該年度有下過有效訂單的客戶。",
     ["repeat customer", "回購客戶", "回頭客", "重複購買客戶", "回購"],
     ["ev_doc_definitions", "ev_orders_per_customer", "ev_customer_name_dup"])
term("term_channel_order_share", "通路訂單占比 Channel Order Share", "metric",
     "某通路的有效訂單張數占同期全部有效訂單張數的百分比。",
     "分子與分母都限定同一期間內的有效訂單，分母含所有通路。",
     ["通路占比", "訂單占比", "channel share", "占比"], ["ev_doc_definitions", "ev_channel_values"])
term("term_collected_amount", "實收金額 Collected Amount", "metric",
     "付款成功的付款紀錄的金額總和（新台幣元）。",
     "期間依付款成功時間（台北時間）歸屬；付款失敗的嘗試不計；不扣退款。",
     ["實收", "實收金額", "收款金額", "collected amount", "received amount"],
     ["ev_doc_definitions", "ev_status_payment", "ev_payment_values", "ev_payment_equals_items"])

term("term_cancelled_order", "已取消訂單 Cancelled Order", "category",
     "訂單狀態為已取消（9）的訂單，這類訂單只有付款失敗紀錄且無出貨紀錄。",
     "資料沒有取消時間，期間只能依訂單成立時間歸屬。",
     ["cancelled order", "已取消訂單", "取消訂單", "取消"],
     ["ev_status_dist", "ev_status_payment", "ev_schema", "ev_doc_codes"])
term("term_pending_payment_order", "待付款訂單 Pending Payment Order", "category",
     "訂單狀態為待付款（0）的訂單，這類訂單只有付款失敗紀錄且無出貨紀錄。",
     "「目前」的待付款數量是現況快照，不需期間條件；待付款訂單不是有效訂單。",
     ["pending payment order", "待付款訂單", "待付款", "未付款訂單"],
     ["ev_status_dist", "ev_status_payment", "ev_doc_codes"])
term("term_active_product", "在售商品 Active Product", "category",
     "商品主檔中 is_active=1 的商品（目前仍在售）。",
     "是目前狀態的篩選，不隨銷售期間改變；已下架商品的歷史銷售仍存在於訂單明細。",
     ["在售商品", "仍在售", "active product", "目前在售"],
     ["ev_category_active", "ev_inactive_products_sold", "ev_doc_codes"])
term("term_region_north", "北部客戶 North Region", "category", "地區代碼為 TW-N 的客戶。",
     "客戶屬性。", ["北部", "北部客戶", "TW-N"], ["ev_region_values", "ev_doc_codes"])
term("term_region_japan", "日本客戶 Japan Region", "category", "地區代碼為 JP 的客戶。",
     "客戶屬性。", ["日本", "日本客戶", "JP"], ["ev_region_values", "ev_doc_codes"])
term("term_tier_gold", "黃金會員 Gold Member", "category", "會員等級代碼為 G 的客戶。",
     "客戶屬性的目前值。", ["黃金會員", "金級會員", "G", "gold"], ["ev_tier_values", "ev_doc_codes"])
term("term_tier_silver", "銀級會員 Silver Member", "category", "會員等級代碼為 S 的客戶。",
     "客戶屬性的目前值。", ["銀級會員", "銀會員", "S", "silver"], ["ev_tier_values", "ev_doc_codes"])
term("term_tier_basic", "一般會員 Basic Member", "category", "會員等級代碼為 B 的客戶。",
     "客戶屬性的目前值。", ["一般會員", "普通會員", "B", "basic"], ["ev_tier_values", "ev_doc_codes"])
term("term_channel_web", "官網通路 Web Channel", "category", "下單通路為 web 的訂單。",
     "訂單屬性。", ["官網", "官網通路", "web"], ["ev_channel_values", "ev_doc_codes"])
term("term_channel_app", "行動 App 通路 App Channel", "category", "下單通路為 app 的訂單。",
     "訂單屬性。", ["行動 App", "App", "app", "手機 App"], ["ev_channel_values", "ev_doc_codes"])
term("term_channel_store", "實體門市通路 Store Channel", "category", "下單通路為 store 的訂單。",
     "訂單屬性。", ["實體門市", "門市", "store"], ["ev_channel_values", "ev_doc_codes"])
term("term_category_shoes", "登山鞋 Shoes", "category", "商品類別為 shoes 的商品。",
     "商品屬性。", ["登山鞋", "shoes"], ["ev_category_active", "ev_doc_codes"])
term("term_method_credit_card", "信用卡 Credit Card", "category", "付款方式為 credit_card 的付款紀錄。",
     "付款紀錄屬性。", ["信用卡", "credit_card"], ["ev_payment_values", "ev_doc_codes"])
term("term_reason_change_of_mind", "改變心意 Change of Mind", "category", "退款原因代碼為 R2 的退款。",
     "退款屬性。", ["改變心意", "R2"], ["ev_reason_values", "ev_doc_codes"])

# ---------------------------------------------------------------- Mappings
MAPS = []


def mp(id, term_id, table, column, grain, validation, filt="", agg=""):
    m = {"id": id, "term_id": term_id, "database_source": DB, "table": table, "column": column}
    if filt:
        m["semantic_filter"] = filt
    if agg:
        m["aggregation_semantics"] = agg
    m["grain"] = grain
    m["validation"] = validation
    MAPS.append(m)


VALID = "僅限訂單狀態為已付款(1)、已出貨(2)、已送達(3)的有效訂單；排除待付款(0)與已取消(9)"
mp("map_customer", "term_customer", "customers", "customer_id", "每位客戶一列", "ev_schema; ev_customer_name_dup: customer_id 唯一(5000)，name 不唯一(380)")
mp("map_order", "term_order", "orders", "order_id", "每張訂單一列", "ev_schema; ev_fk_integrity: 訂單皆對應存在的客戶")
mp("map_order_item", "term_order_item", "order_items", "item_id", "每筆訂單明細一列", "ev_schema; ev_fk_integrity: 明細皆對應存在的訂單與商品")
mp("map_product", "term_product", "products", "product_id", "每個商品一列", "ev_product_keys_unique: product_id/sku/product_name 皆唯一(200)")
mp("map_payment", "term_payment", "payments", "payment_id", "每次付款嘗試一列", "ev_status_payment: 一張訂單可有多筆嘗試")
mp("map_refund", "term_refund", "refunds", "refund_id", "每筆明細退款一列", "ev_refund_linkage: 4039 筆退款各對應一個不同的明細")
mp("map_customer_region", "term_customer_region", "customers", "region_code", "每位客戶一個值", "ev_region_values: 5 個乾淨代碼")
mp("map_member_tier", "term_member_tier", "customers", "tier", "每位客戶一個目前值", "ev_tier_values: 3 個乾淨代碼")
mp("map_sales_channel", "term_sales_channel", "orders", "channel", "每張訂單一個值", "ev_channel_values: 3 個乾淨代碼")
mp("map_product_category", "term_product_category", "products", "category", "每個商品一個值", "ev_category_active: 5 個類別")
mp("map_payment_method", "term_payment_method", "payments", "method", "每次付款嘗試一個值", "ev_payment_values: 4 種方式")
mp("map_refund_reason", "term_refund_reason", "refunds", "reason_code", "每筆退款一個值", "ev_reason_values: 4 個代碼")
mp("map_order_status", "term_order_status", "orders", "status", "每張訂單一個目前狀態", "ev_status_dist; ev_status_payment; ev_status_shipment: 狀態與付款/出貨紀錄一致")
mp("map_product_sale_status", "term_product_sale_status", "products", "is_active", "每個商品一個目前值", "ev_category_active; ev_inactive_products_sold")
mp("map_order_time", "term_order_time", "orders", "order_ts", "秒級時間戳（儲存值為 UTC，報表用台北時間）", "ev_ts_format_range; ev_tz_period_impact")
mp("map_payment_time", "term_payment_time", "payments", "paid_ts", "秒級時間戳（儲存值為 UTC，報表用台北時間）", "ev_ts_format_range; ev_tz_period_impact")
mp("map_refund_time", "term_refund_time", "refunds", "refund_ts", "秒級時間戳（儲存值為 UTC，報表用台北時間）", "ev_ts_format_range; ev_tz_period_impact")
mp("map_deal_unit_price", "term_deal_unit_price", "order_items", "unit_price_cents", "每筆明細一個單價，單位為分(1/100 元)",
   "ev_unit_price_scale: 與 products.list_price_twd 的比值只有 100/90/85/80，確認為分且為成交價")
mp("map_units_sold", "term_units_sold", "order_items", "quantity", "每筆明細一個數量（1-3）",
   "ev_unit_price_scale: quantity 只有 1/2/3; ev_doc_no_units_sold_def: 文件未定義，限定有效訂單為假設",
   filt=VALID + "（假設，文件未明確定義銷售數量）", agg="跨明細數量加總；排名時以商品為單位")
mp("map_item_amount_qty", "term_item_amount", "order_items", "quantity", "每筆明細一個數量",
   "ev_payment_equals_items: 數量 x 成交單價等於同訂單付款金額",
   filt=VALID, agg="明細金額為數量乘以成交單價，期間內跨明細加總")
mp("map_item_amount_price", "term_item_amount", "order_items", "unit_price_cents", "每筆明細一個單價，單位為分",
   "ev_payment_equals_items; ev_unit_price_scale: 加總後需由分換算為元",
   filt=VALID, agg="與數量相乘後加總，結果由分換算為新台幣元")
mp("map_refund_amount", "term_refund_amount", "refunds", "refund_amount_twd", "每筆明細退款一個金額（新台幣元）",
   "ev_refund_linkage: 金額不超過對應明細金額，2798 筆為全額、1241 筆為部分退款",
   agg="期間內退款金額加總；歸屬時間依用途而異（見限制條件）")
mp("map_valid_order", "term_valid_order", "orders", "status", "每張訂單一個目前狀態",
   "ev_doc_definitions; ev_status_payment: 狀態 1/2/3 的訂單各有一筆付款成功紀錄，狀態 0/9 沒有",
   filt=VALID)
mp("map_valid_order_count", "term_valid_order_count", "orders", "order_id", "每張訂單一列",
   "ev_status_dist: 狀態 1/2/3 分別 3549/4870/39574 張; ev_status_payment: 各有一筆付款成功紀錄", filt=VALID, agg="不重複訂單的張數")
mp("map_net_revenue_amount", "term_net_revenue", "order_items", "unit_price_cents", "每筆明細一個單價，單位為分",
   "ev_doc_definitions; ev_payment_equals_items: 商品金額部分", filt=VALID,
   agg="有效訂單商品金額總和（數量乘成交單價，分換算為元），期間依訂單成立時間歸屬")
mp("map_net_revenue_refund", "term_net_revenue", "refunds", "refund_amount_twd", "每筆明細退款一個金額（新台幣元）",
   "ev_refund_linkage: 退款的 order_id 與其明細所屬訂單一致(4039/4039)，且全部屬已送達訂單",
   filt="僅扣除屬於期間內有效訂單的退款（退款所屬原訂單的成立時間決定期間）",
   agg="從商品金額總和中扣除對應退款金額總和")
mp("map_aov_amount", "term_avg_order_value", "order_items", "unit_price_cents", "每筆明細一個單價，單位為分",
   "ev_doc_definitions; ev_payment_equals_items: 分子為商品金額，不扣退款", filt=VALID,
   agg="有效訂單商品金額總和（分子）")
mp("map_aov_orders", "term_avg_order_value", "orders", "order_id", "每張訂單一列",
   "ev_doc_definitions: 分母為有效訂單張數", filt=VALID, agg="不重複有效訂單張數（分母）")
mp("map_repeat_customer", "term_repeat_customer", "orders", "customer_id", "每位客戶在一個年度內的有效訂單張數",
   "ev_orders_per_customer: 有效訂單依 customer_id 分組，存在 2 張以上者", filt=VALID + "；訂單成立於該年度（台北時間）",
   agg="年度內有效訂單達 2 張（含）以上的不重複客戶數")
mp("map_channel_share_orders", "term_channel_order_share", "orders", "order_id", "每張訂單一列",
   "ev_doc_definitions; ev_channel_values", filt=VALID, agg="某通路有效訂單張數除以同期全部有效訂單張數，以百分比表示")
mp("map_channel_share_channel", "term_channel_order_share", "orders", "channel", "每張訂單一個值",
   "ev_channel_values: 3 個通路", agg="通路為分子分母的區分欄位")
mp("map_collected_amount", "term_collected_amount", "payments", "amount_twd", "每次付款嘗試一個金額（新台幣元）",
   "ev_status_payment; ev_payment_values; ev_payment_equals_items: 失敗嘗試與成功紀錄金額相同，必須只取付款成功者",
   filt="僅限付款狀態為付款成功(ok)的付款紀錄", agg="付款成功金額總和，期間依付款成功時間歸屬")
mp("map_cancelled_order", "term_cancelled_order", "orders", "status", "每張訂單一個目前狀態",
   "ev_status_dist: 狀態 9 共 9004 張; ev_status_payment: 只有付款失敗紀錄", filt="訂單狀態為已取消(9)",
   agg="不重複訂單張數，期間依訂單成立時間歸屬")
mp("map_pending_payment_order", "term_pending_payment_order", "orders", "status", "每張訂單一個目前狀態",
   "ev_status_dist: 狀態 0 共 3003 張; ev_status_payment: 只有付款失敗紀錄", filt="訂單狀態為待付款(0)",
   agg="目前狀態的不重複訂單張數")
mp("map_active_product", "term_active_product", "products", "is_active", "每個商品一個目前值",
   "ev_category_active: is_active 1 共 165 個商品", filt="商品在售旗標為 1")
mp("map_region_north", "term_region_north", "customers", "region_code", "每位客戶一個值", "ev_region_values: TW-N 共 1985 位", filt="地區代碼為 TW-N")
mp("map_region_japan", "term_region_japan", "customers", "region_code", "每位客戶一個值", "ev_region_values: JP 共 501 位", filt="地區代碼為 JP")
mp("map_tier_gold", "term_tier_gold", "customers", "tier", "每位客戶一個目前值", "ev_tier_values: G 共 491 位", filt="會員等級代碼為 G")
mp("map_tier_silver", "term_tier_silver", "customers", "tier", "每位客戶一個目前值", "ev_tier_values: S 共 970 位", filt="會員等級代碼為 S")
mp("map_tier_basic", "term_tier_basic", "customers", "tier", "每位客戶一個目前值", "ev_tier_values: B 共 3539 位", filt="會員等級代碼為 B")
mp("map_channel_web", "term_channel_web", "orders", "channel", "每張訂單一個值", "ev_channel_values: web 共 30071 張", filt="通路為 web")
mp("map_channel_app", "term_channel_app", "orders", "channel", "每張訂單一個值", "ev_channel_values: app 共 20970 張", filt="通路為 app")
mp("map_channel_store", "term_channel_store", "orders", "channel", "每張訂單一個值", "ev_channel_values: store 共 8959 張", filt="通路為 store")
mp("map_category_shoes", "term_category_shoes", "products", "category", "每個商品一個值", "ev_category_active: shoes 共 40 個商品", filt="商品類別為 shoes")
mp("map_method_credit_card", "term_method_credit_card", "payments", "method", "每次付款嘗試一個值", "ev_payment_values: credit_card 成功 26469 筆", filt="付款方式為 credit_card")
mp("map_reason_change_of_mind", "term_reason_change_of_mind", "refunds", "reason_code", "每筆退款一個值", "ev_reason_values: R2 共 1621 筆", filt="退款原因代碼為 R2")

# ---------------------------------------------------------------- Relations
RELS = []


def rel(id, src, typ, tgt, cond, desc, evidence):
    RELS.append({"id": id, "source": src, "relation_type": typ, "target": tgt,
                 "connection_condition": cond, "description": desc, "evidence": evidence})


rel("rel_order_items", "term_order", "composition", "term_order_item",
    "order_items.order_id corresponds to orders.order_id",
    "訂單由一到多筆明細組成，明細離開訂單沒有意義；訂單金額由明細的數量與成交單價構成。", ["ev_fk_integrity", "ev_payment_equals_items"])
rel("rel_order_payments", "term_order", "composition", "term_payment",
    "payments.order_id corresponds to orders.order_id",
    "付款紀錄是訂單的付款嘗試；一張訂單可有多次嘗試，有效訂單各有一筆付款成功紀錄。", ["ev_status_payment"])
rel("rel_item_refunds", "term_order_item", "composition", "term_refund",
    "refunds.item_id corresponds to order_items.item_id; refunds.order_id equals the order of that item",
    "退款是針對單一訂單明細發生的，退款所屬訂單與明細所屬訂單一致；退款的商品類別透過明細的商品取得。", ["ev_refund_linkage"])
rel("rel_customer_orders", "term_customer", "association", "term_order",
    "orders.customer_id corresponds to customers.customer_id",
    "客戶下訂單；客戶屬性（地區、等級）可用來切分訂單層指標。客戶是獨立主檔，訂單不是客戶的組成部分。", ["ev_fk_integrity", "ev_orders_per_customer"])
rel("rel_item_product", "term_order_item", "association", "term_product",
    "order_items.product_id corresponds to products.product_id",
    "明細指向所售商品；商品類別與在售狀態來自商品主檔。商品是獨立主檔。", ["ev_fk_integrity"])

rel("rel_order_valid", "term_order", "hierarchy", "term_valid_order", "",
    "有效訂單是狀態為 1/2/3 的訂單，值域為全部訂單的子集合。", ["ev_status_dist", "ev_doc_definitions"])
rel("rel_order_cancelled", "term_order", "hierarchy", "term_cancelled_order", "",
    "已取消訂單是狀態為 9 的訂單，值域為全部訂單的子集合。", ["ev_status_dist"])
rel("rel_order_pending", "term_order", "hierarchy", "term_pending_payment_order", "",
    "待付款訂單是狀態為 0 的訂單，值域為全部訂單的子集合。", ["ev_status_dist"])
rel("rel_product_active", "term_product", "hierarchy", "term_active_product", "",
    "在售商品是 is_active=1 的商品，為全部商品的子集合。", ["ev_category_active"])
rel("rel_region_north", "term_customer_region", "hierarchy", "term_region_north", "",
    "北部(TW-N)是客戶地區維度的一個取值。", ["ev_region_values"])
rel("rel_region_japan", "term_customer_region", "hierarchy", "term_region_japan", "",
    "日本(JP)是客戶地區維度的一個取值。", ["ev_region_values"])
rel("rel_tier_gold", "term_member_tier", "hierarchy", "term_tier_gold", "",
    "黃金會員(G)是會員等級維度的一個取值。", ["ev_tier_values"])
rel("rel_tier_silver", "term_member_tier", "hierarchy", "term_tier_silver", "",
    "銀級會員(S)是會員等級維度的一個取值。", ["ev_tier_values"])
rel("rel_tier_basic", "term_member_tier", "hierarchy", "term_tier_basic", "",
    "一般會員(B)是會員等級維度的一個取值。", ["ev_tier_values"])
rel("rel_channel_web", "term_sales_channel", "hierarchy", "term_channel_web", "",
    "官網(web)是下單通路維度的一個取值。", ["ev_channel_values"])
rel("rel_channel_app", "term_sales_channel", "hierarchy", "term_channel_app", "",
    "行動 App(app)是下單通路維度的一個取值。", ["ev_channel_values"])
rel("rel_channel_store", "term_sales_channel", "hierarchy", "term_channel_store", "",
    "實體門市(store)是下單通路維度的一個取值。", ["ev_channel_values"])
rel("rel_category_shoes", "term_product_category", "hierarchy", "term_category_shoes", "",
    "登山鞋(shoes)是商品類別維度的一個取值。", ["ev_category_active"])
rel("rel_method_credit_card", "term_payment_method", "hierarchy", "term_method_credit_card", "",
    "信用卡(credit_card)是付款方式維度的一個取值。", ["ev_payment_values"])
rel("rel_reason_change_of_mind", "term_refund_reason", "hierarchy", "term_reason_change_of_mind", "",
    "改變心意(R2)是退款原因維度的一個取值。", ["ev_reason_values"])

rel("rel_price_to_amount", "term_deal_unit_price", "derivation", "term_item_amount", "",
    "商品金額 = 數量 x 成交單價（再由分換算為元）。", ["ev_payment_equals_items", "ev_doc_definitions"])
rel("rel_qty_to_amount", "term_units_sold", "derivation", "term_item_amount", "",
    "商品金額 = 數量 x 成交單價；數量為明細上的件數。", ["ev_payment_equals_items", "ev_doc_definitions"])
rel("rel_amount_to_net", "term_item_amount", "derivation", "term_net_revenue", "",
    "淨營收 = 有效訂單商品金額總和 - 對應退款金額總和；此為被減項。", ["ev_doc_definitions"])
rel("rel_refund_to_net", "term_refund_amount", "derivation", "term_net_revenue",
    "refunds.order_id identifies the original order whose order time determines the period",
    "淨營收 = 有效訂單商品金額總和 - 對應退款金額總和；此為扣除項，退款扣回原訂單。", ["ev_doc_definitions", "ev_refund_linkage"])
rel("rel_valid_to_count", "term_valid_order", "derivation", "term_valid_order_count", "",
    "有效訂單張數是對有效訂單的計數。", ["ev_doc_definitions", "ev_status_dist"])
rel("rel_amount_to_aov", "term_item_amount", "derivation", "term_avg_order_value", "",
    "客單價 = 有效訂單商品金額總和（不扣退款）/ 有效訂單張數；此為分子。", ["ev_doc_definitions"])
rel("rel_count_to_aov", "term_valid_order_count", "derivation", "term_avg_order_value", "",
    "客單價 = 有效訂單商品金額總和（不扣退款）/ 有效訂單張數；此為分母。", ["ev_doc_definitions"])
rel("rel_count_to_share", "term_valid_order_count", "derivation", "term_channel_order_share", "",
    "通路訂單占比 = 某通路有效訂單張數 / 同期全部有效訂單張數。", ["ev_doc_definitions"])
rel("rel_valid_to_repeat", "term_valid_order", "derivation", "term_repeat_customer",
    "orders.customer_id identifies the customer of each valid order",
    "回購客戶由客戶在年度內的有效訂單張數推得（達 2 張含以上）。", ["ev_doc_definitions", "ev_orders_per_customer"])

# ---------------------------------------------------------------- Constraints
CONS = []


def con(id, target, ctype, kws, sev, scope, conf, desc, evidence):
    CONS.append({"id": id, "target": target, "constraint_type": ctype, "trigger_keywords": kws,
                 "severity": sev, "scope": scope, "confidence": conf, "description": desc,
                 "evidence": evidence})


TZ_KW = ["台北時間", "UTC", "時區", "月份", "季", "年度", "年", "第一季", "上半年", "期間", "日期", "UTC+8"]
con("con_tz_order_time", "term_order_time", "scope", TZ_KW + ["訂單成立時間", "下單時間", "order_ts"], "block",
    "以訂單成立時間劃分任何日期、月、季、年的報表", "medium",
    "orders.order_ts 儲存的是 UTC 時間，營運報表一律以台北時間（UTC+8）劃分日期、月份、季與年度；依原始儲存值直接劃分會讓部分訂單落入錯誤的期間。"
    "資料本身無法證實儲存值為 UTC（時段分布均勻），此規則來自業務文件，但已驗證換算會改變 655 張訂單的月份。",
    ["ev_doc_time_rules", "ev_tz_period_impact", "ev_hour_distribution"])
con("con_tz_payment_time", "term_payment_time", "scope", TZ_KW + ["付款成功時間", "付款時間", "paid_ts", "實收"], "block",
    "以付款成功時間劃分期間的報表", "medium",
    "payments.paid_ts 儲存的是 UTC 時間，實收金額的期間要先換算成台北時間（UTC+8）再歸屬；規則來自業務文件，資料中換算會改變期間內筆數（2025 年 ok 付款 47699 vs 47703）。",
    ["ev_doc_time_rules", "ev_tz_period_impact"])
con("con_tz_refund_time", "term_refund_time", "scope", TZ_KW + ["退款發生時間", "退款時間", "refund_ts", "退款金額"], "block",
    "以退款發生時間劃分期間的報表", "medium",
    "refunds.refund_ts 儲存的是 UTC 時間，退款報表的期間要先換算成台北時間（UTC+8）再歸屬；規則來自業務文件，資料中換算會改變期間內筆數（2025 年 9 月 304 vs 307）。",
    ["ev_doc_time_rules", "ev_tz_period_impact"])
con("con_calendar_quarters", "term_reporting_calendar", "scope",
    ["第一季", "第二季", "第三季", "第四季", "Q1", "Q2", "Q3", "Q4", "季", "上半年", "下半年"], "warning",
    "所有以季或半年提問的報表", "high",
    "第一季為 1-3 月、第二季為 4-6 月、第三季為 7-9 月、第四季為 10-12 月；上半年為 1-6 月。月份以台北時間為準。",
    ["ev_doc_time_rules"])
con("con_order_status_enum", "term_order_status", "enum_semantics",
    ["訂單狀態", "status", "待付款", "已付款", "已出貨", "已送達", "已取消", "有效訂單", "取消"], "block",
    "解讀 orders.status 時", "high",
    "0=待付款、1=已付款、2=已出貨、3=已送達、9=已取消。資料互證：狀態 0 與 9 的訂單只有付款失敗紀錄且無出貨；狀態 1 有付款成功紀錄且無出貨；狀態 2 有出貨但 delivered_ts 為空；狀態 3 有出貨且有 delivered_ts。",
    ["ev_doc_codes", "ev_status_payment", "ev_status_shipment", "ev_status_dist"])
con("con_valid_order_rule", "term_valid_order", "business_rule",
    ["有效訂單", "有效訂單數", "有效訂單張數", "營收", "淨營收", "客單價", "回購", "占比", "訂單數"], "block",
    "營收、客單價、訂單數、回購客戶與通路占比", "high",
    "營運指標只計入狀態為已付款、已出貨、已送達的有效訂單；待付款與已取消的訂單不算。資料驗證：狀態 1/2/3 的訂單各有一筆付款成功紀錄，狀態 0/9 沒有。",
    ["ev_doc_definitions", "ev_status_payment"])
con("con_unit_price_cents", "term_deal_unit_price", "unit",
    ["成交單價", "單價", "unit_price_cents", "金額", "商品金額", "營收", "分"], "block",
    "使用 order_items.unit_price_cents 計算任何金額時", "high",
    "unit_price_cents 的單位是分（TWD 的 1/100），與 payments.amount_twd、refunds.refund_amount_twd、products.list_price_twd 的新台幣元不同；與其他金額欄位合併或比較前須換算為同一單位。"
    "它是客人實付的成交價，不是商品目錄標價。",
    ["ev_unit_price_scale", "ev_payment_equals_items"])
con("con_item_amount_definition", "term_item_amount", "business_rule",
    ["商品金額", "銷售金額", "營收", "客單價", "標價", "list_price"], "block",
    "計算商品金額、淨營收與客單價的金額部分", "high",
    "商品金額是訂單明細的數量乘以成交單價，不是商品目錄標價（products.list_price_twd）；付款紀錄金額與明細合計相同但含失敗嘗試，不作為商品金額來源。",
    ["ev_doc_definitions", "ev_unit_price_scale", "ev_payment_equals_items"])
con("con_net_revenue_rule", "term_net_revenue", "business_rule",
    ["淨營收", "營收", "扣掉退款", "扣除退款", "net revenue"], "block",
    "所有淨營收提問", "high",
    "淨營收期間依訂單成立時間（台北時間）歸屬，只含有效訂單；退款扣回其所屬的原訂單，不看退款發生在哪個月，因此晚於期間結束才發生的退款也要扣。"
    "資料驗證：退款的 order_id 與其明細所屬訂單一致，且有 178 筆退款發生在 2025 年（台北時間）之後。",
    ["ev_doc_definitions", "ev_refund_linkage", "ev_tz_period_impact"])
con("con_refund_report_attribution", "term_refund_amount", "business_rule",
    ["退款金額", "退款總計", "退款", "退款報表", "退款發生"], "block",
    "以退款金額為主題的報表（含依類別或原因拆分）", "high",
    "退款報表依退款發生時間（台北時間）歸屬期間，與淨營收依原訂單成立時間歸屬的方式不同；退款金額不限定原訂單的期間。"
    "退款粒度是訂單明細，退款的商品類別來自該明細的商品，所有退款皆屬已送達(3)的訂單。",
    ["ev_doc_definitions", "ev_refund_linkage"])
con("con_refund_partial", "term_refund", "data_quality",
    ["退款", "部分退款", "退款金額", "全額"], "info",
    "退款金額與明細金額比較時", "high",
    "退款金額可小於對應明細金額（4039 筆中 1241 筆為部分退款、2798 筆為全額）；退款金額以 refunds.refund_amount_twd 為準，不以明細金額推算。",
    ["ev_refund_linkage"])
con("con_aov_rule", "term_avg_order_value", "business_rule",
    ["客單價", "平均訂單金額", "AOV"], "block",
    "所有客單價提問", "high",
    "客單價 = 期間內有效訂單商品金額總和 / 有效訂單張數，分子不扣退款，分母以訂單張數計（不是客戶數或明細數）；期間依訂單成立時間（台北時間）。",
    ["ev_doc_definitions"])
con("con_repeat_customer_rule", "term_repeat_customer", "business_rule",
    ["回購客戶", "回購", "回頭客", "重複購買", "2 張", "兩張"], "block",
    "回購客戶人數與占比", "high",
    "回購客戶指同一年度（台北時間）內有效訂單達 2 張（含）以上的客戶；以 customer_id 計數，客戶姓名重複（5000 位客戶僅 380 個不同姓名），不能以姓名計數。"
    "按地區等條件切分時，採客戶主檔上的地區屬性。",
    ["ev_doc_definitions", "ev_orders_per_customer", "ev_customer_name_dup"])
con("con_channel_share_rule", "term_channel_order_share", "business_rule",
    ["占比", "百分比", "%", "通路占比", "透過行動 App", "實體門市"], "warning",
    "通路訂單占比提問", "high",
    "占比的分子與分母都限定同一期間的有效訂單，分母含所有通路；結果以百分比表示。",
    ["ev_doc_definitions", "ev_channel_values"])
con("con_collected_amount_rule", "term_collected_amount", "business_rule",
    ["實收", "實收金額", "付款成功", "收款"], "block",
    "所有實收金額提問", "high",
    "實收金額只加總付款狀態為付款成功(ok)的付款紀錄，期間依付款成功時間（台北時間）歸屬；付款失敗的嘗試不計入。"
    "有效訂單也可能同時有失敗的重試紀錄，不能把同一訂單所有付款紀錄相加。不扣退款。",
    ["ev_doc_definitions", "ev_status_payment", "ev_payment_values"])
con("con_payment_status_enum", "term_payment", "enum_semantics",
    ["付款狀態", "payment_status", "付款成功", "付款失敗", "ok", "failed"], "block",
    "解讀 payments.payment_status 時", "high",
    "ok=付款成功、failed=付款失敗。待付款(0)與已取消(9)的訂單只有 failed 紀錄；有效訂單恰有一筆 ok 紀錄。",
    ["ev_doc_codes", "ev_status_payment", "ev_payment_values"])
con("con_payment_method_enum", "term_payment_method", "enum_semantics",
    ["付款方式", "信用卡", "LINE Pay", "ATM", "貨到付款", "credit_card", "line_pay", "atm", "cod"], "warning",
    "解讀 payments.method 時", "high",
    "credit_card=信用卡、line_pay=LINE Pay、atm=ATM 轉帳、cod=貨到付款；資料中只有這四種值。",
    ["ev_doc_codes", "ev_payment_values"])
con("con_region_enum", "term_customer_region", "enum_semantics",
    ["地區", "區域", "北部", "中部", "南部", "日本", "新加坡", "region_code", "TW-N", "TW-C", "TW-S", "JP", "SG"], "block",
    "解讀 customers.region_code 並以地區切分指標時", "medium",
    "TW-N=北部、TW-C=中部、TW-S=南部、JP=日本、SG=新加坡。代碼集合與資料中的相異值完全一致，代碼含義來自業務文件。"
    "地區是客戶屬性，不是訂單出貨地；訂單層沒有任何地區欄位，因此「某地區客戶」或「各地區」的指標以客戶的地區屬性歸類。",
    ["ev_doc_codes", "ev_region_values", "ev_schema"])
con("con_tier_enum", "term_member_tier", "enum_semantics",
    ["會員等級", "一般會員", "銀級會員", "黃金會員", "tier", "B", "S", "G"], "block",
    "解讀 customers.tier 並以會員等級切分指標時", "medium",
    "B=一般會員、S=銀級會員、G=黃金會員。代碼集合與資料相異值一致，代碼含義來自業務文件；等級是客戶主檔上的單一目前值，沒有歷史，不隨期間變動。",
    ["ev_doc_codes", "ev_tier_values", "ev_schema"])
con("con_channel_enum", "term_sales_channel", "enum_semantics",
    ["通路", "官網", "行動 App", "實體門市", "web", "app", "store", "channel"], "warning",
    "解讀 orders.channel 時", "high",
    "web=官網、app=行動 App、store=實體門市；資料中只有這三種乾淨的值。",
    ["ev_doc_codes", "ev_channel_values"])
con("con_category_enum", "term_product_category", "enum_semantics",
    ["商品類別", "類別", "登山背包", "帳篷", "登山鞋", "機能服飾", "配件", "backpack", "tent", "shoes", "apparel", "accessory"], "warning",
    "解讀 products.category 並以類別切分銷售或退款時", "high",
    "backpack=登山背包、tent=帳篷、shoes=登山鞋、apparel=機能服飾、accessory=配件；資料中只有這五種值。類別是商品屬性，明細與退款的類別透過商品取得。",
    ["ev_doc_codes", "ev_category_active"])
con("con_refund_reason_enum", "term_refund_reason", "enum_semantics",
    ["退款原因", "商品瑕疵", "改變心意", "寄錯商品", "配送延遲", "R1", "R2", "R3", "R4", "reason_code"], "block",
    "解讀 refunds.reason_code 並以原因切分退款時", "medium",
    "R1=商品瑕疵、R2=改變心意、R3=寄錯商品、R4=配送延遲。代碼集合與資料相異值一致，代碼含義來自業務文件。",
    ["ev_doc_codes", "ev_reason_values"])
con("con_sale_status_scope", "term_active_product", "scope",
    ["在售", "仍在售", "目前仍在售", "已下架", "is_active", "在售商品"], "block",
    "以在售商品篩選銷售量或排名時", "medium",
    "is_active=1 為在售、0 為已下架（含義來自業務文件）；它是商品主檔上的目前狀態旗標，沒有歷史。「在售商品」只限制排名的候選商品，不限制銷售期間；已下架商品在歷史訂單中仍有銷售。",
    ["ev_doc_codes", "ev_category_active", "ev_inactive_products_sold"])
con("con_units_sold_assumption", "term_units_sold", "business_rule",
    ["銷售數量", "銷量", "賣最多", "銷售量", "數量最多", "賣出"], "warning",
    "銷售數量及依其排名的提問", "low",
    "業務文件沒有明確定義銷售數量；本版假設與有效訂單一致，即只計入有效訂單明細的數量加總，期間依訂單成立時間（台北時間）歸屬，商品以 product_id 或 product_name 識別（皆唯一）。此為未被業務窗口確認的假設。",
    ["ev_doc_no_units_sold_def", "ev_doc_definitions", "ev_product_keys_unique"])
con("con_cancelled_order_scope", "term_cancelled_order", "scope",
    ["已取消", "取消", "取消訂單", "取消率", "已取消的訂單"], "warning",
    "計算已取消訂單的張數或期間分布時", "high",
    "資料沒有取消時間欄位，已取消訂單的期間只能依訂單成立時間（台北時間）歸屬；已取消訂單不算有效訂單。",
    ["ev_schema", "ev_status_dist", "ev_doc_definitions"])
con("con_pending_order_scope", "term_pending_payment_order", "scope",
    ["待付款", "目前", "現在", "待付款的訂單", "未付款"], "warning",
    "詢問目前待付款訂單數時", "high",
    "「目前」的待付款是訂單狀態的現況快照，不套用期間條件；訂單狀態沒有歷史，待付款訂單不算有效訂單。",
    ["ev_schema", "ev_status_dist", "ev_doc_codes"])
con("con_customer_attributes_current", "term_customer", "data_quality",
    ["客戶", "會員", "地區", "等級", "姓名", "customer"], "warning",
    "以客戶屬性切分任何指標，或識別客戶時", "high",
    "客戶主檔每位客戶只有一列，地區與會員等級是單一目前值，沒有歷史版本；姓名嚴重重複（5000 位客戶僅 380 個不同姓名），客戶一律以 customer_id 識別。",
    ["ev_schema", "ev_customer_name_dup"])

# ---------------------------------------------------------------- Output
records = {"terms": TERMS, "mappings": MAPS, "relations": RELS, "constraints": CONS, "evidence": EV}
out = {"version": "ontology_v0", "records": records}
json.dump(out, open("/Users/johnnyhwu/Desktop/EvoOntology/poc/workspace/build_scratch/save_v0.json", "w"),
          ensure_ascii=False, indent=1)

# integrity checks
tid = {t["id"] for t in TERMS}
eid = {e["id"] for e in EV}
mid = {m["id"] for m in MAPS}
assert len(tid) == len(TERMS) and len(eid) == len(EV) and len(mid) == len(MAPS)
for t in TERMS:
    assert set(t["evidence"]) <= eid, t["id"]
for m in MAPS:
    assert m["term_id"] in tid, m["id"]
for r in RELS:
    assert r["source"] in tid and r["target"] in tid, r["id"]
    assert set(r["evidence"]) <= eid, r["id"]
for c in CONS:
    assert c["target"] in tid | mid, c["id"]
    assert set(c["evidence"]) <= eid, c["id"]
used = set()
for x in TERMS + RELS + CONS:
    used |= set(x["evidence"])
print({k: len(v) for k, v in records.items()}, "unused evidence:", eid - used)
from collections import Counter
print(Counter(r["relation_type"] for r in RELS))
print("terms without mapping:", tid - {m["term_id"] for m in MAPS})
