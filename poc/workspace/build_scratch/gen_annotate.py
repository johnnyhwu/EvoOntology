import json
NET = ["term_net_revenue","term_item_amount","term_refund_amount","term_valid_order","term_order_time","term_reporting_calendar",
       "map_net_revenue_amount","map_net_revenue_refund","con_net_revenue_rule","con_valid_order_rule","con_tz_order_time","con_unit_price_cents","con_item_amount_definition"]
AOV = ["term_avg_order_value","term_item_amount","term_valid_order_count","term_valid_order","term_order_time","term_reporting_calendar",
       "map_aov_amount","map_aov_orders","con_aov_rule","con_valid_order_rule","con_tz_order_time","con_unit_price_cents"]
CNT = ["term_valid_order_count","term_valid_order","term_order_time","term_reporting_calendar","map_valid_order_count","con_valid_order_rule","con_tz_order_time","con_order_status_enum"]
REF = ["term_refund_amount","term_refund","term_refund_time","term_reporting_calendar","map_refund_amount","con_refund_report_attribution","con_tz_refund_time","con_refund_partial"]
REG = ["term_customer_region","map_customer_region","con_region_enum","con_customer_attributes_current","rel_customer_orders","term_customer"]
def reg(t): return REG+[t,"map_"+t[5:]]
L = {}
L["C01"]=NET
L["C02"]=NET+reg("term_region_north")
L["C03"]=NET+["term_member_tier","term_tier_gold","map_tier_gold","con_tier_enum","con_customer_attributes_current","rel_customer_orders","term_customer"]
L["C04"]=NET
L["C05"]=AOV
L["C06"]=AOV+["term_sales_channel","term_channel_web","map_channel_web","con_channel_enum"]
L["C07"]=AOV+["term_member_tier","term_tier_basic","map_tier_basic","con_tier_enum","con_customer_attributes_current","rel_customer_orders","term_customer"]
L["C08"]=CNT+reg("term_region_north")
L["C09"]=CNT
L["C10"]=CNT+["term_sales_channel","term_channel_app","map_channel_app","con_channel_enum"]
REP=["term_repeat_customer","map_repeat_customer","con_repeat_customer_rule","term_valid_order","con_valid_order_rule","term_order_time","con_tz_order_time","term_reporting_calendar","con_customer_attributes_current","term_customer"]
L["C11"]=REP
L["C12"]=REP+reg("term_region_north")
SH=["term_channel_order_share","map_channel_share_orders","map_channel_share_channel","con_channel_share_rule","term_valid_order_count","con_valid_order_rule","term_order_time","con_tz_order_time","term_sales_channel","con_channel_enum"]
L["C13"]=SH+["term_channel_app","map_channel_app"]
L["C14"]=SH+["term_channel_store","map_channel_store"]
L["C15"]=REF
L["C16"]=REF
RC=["rel_item_refunds","rel_item_product","term_order_item","term_product","term_product_category","map_product_category","con_category_enum"]
L["C17"]=REF+RC
L["C18"]=REF+RC+["term_refund_reason","term_reason_change_of_mind","map_refund_reason","map_reason_change_of_mind","con_refund_reason_enum"]
L["C19"]=["term_collected_amount","map_collected_amount","term_payment_method","map_payment_method","con_collected_amount_rule","con_payment_status_enum","con_payment_method_enum","term_payment","term_payment_time","con_tz_payment_time"]
L["C20"]=L["C19"]+["term_method_credit_card","map_method_credit_card","term_reporting_calendar"]
SOLD=["term_units_sold","map_units_sold","con_units_sold_assumption","term_product","term_order_item","rel_item_product","term_active_product","map_active_product","con_sale_status_scope","term_product_sale_status","term_valid_order","con_valid_order_rule"]
L["C21"]=SOLD
L["C22"]=SOLD+["term_order_time","con_tz_order_time","term_reporting_calendar","con_calendar_quarters"]
L["C23"]=NET+["term_product_category","term_category_shoes","map_category_shoes","map_product_category","con_category_enum","rel_item_product","term_product"]
L["C24"]=["term_cancelled_order","map_cancelled_order","con_cancelled_order_scope","con_order_status_enum","term_order_status","map_order_status","term_order_time","con_tz_order_time","term_reporting_calendar","con_calendar_quarters"]
L["C25"]=["term_pending_payment_order","map_pending_payment_order","con_pending_order_scope","con_order_status_enum","term_order_status","map_order_status"]
L["C26"]=NET+reg("term_region_japan")
L["C27"]=AOV+["term_member_tier","term_tier_gold","map_tier_gold","con_tier_enum","con_customer_attributes_current","rel_customer_orders","term_customer"]
L["C28"]=REF
L["C29"]=CNT+["term_member_tier","term_tier_silver","map_tier_silver","con_tier_enum","con_customer_attributes_current","rel_customer_orders","term_customer"]
L["C30"]=NET+REG
links=[{"question_id":q,"object_ids":list(dict.fromkeys(v))} for q,v in sorted(L.items())]
# check ids exist
recs=json.load(open("save_v0.json"))["records"]
ids=set()
for k,v in recs.items():
    if k!="evidence": ids|={x["id"] for x in v}
for l in links:
    bad=[o for o in l["object_ids"] if o not in ids]
    assert not bad,(l["question_id"],bad)
summary=("ontology_v0 針對 Lumo Outdoors 電商資料庫 shop_v2，從 30 題建構題（淨營收、客單價、有效訂單數、回購客戶、通路占比、退款金額、實收金額、在售商品銷量、取消與待付款訂單）"
 "與業務窗口文件出發，建立 43 個概念、46 個資料對應、29 條關係、27 條限制條件與 25 筆可重現證據。涵蓋：有效訂單範圍與訂單狀態碼語意（與付款、出貨紀錄互證）；"
 "成交單價以分為單位的金額換算（與付款金額對帳）；淨營收（依訂單成立時間歸屬、退款扣回原訂單）、退款報表（依退款發生時間歸屬）、實收金額（只計付款成功、依付款成功時間歸屬）三種不同的期間歸屬規則；"
 "台北時間（UTC+8）換算對期間劃分的影響；客戶地區與會員等級為目前單一屬性；回購客戶以 customer_id 年度內有效訂單達 2 張計。")
limits=[
 "時區：資料表時間為 UTC、報表用台北時間（UTC+8）僅來自業務文件；資料的時段分布均勻，無法由資料本身證實，只驗證了換算會改變期間歸屬。",
 "銷售數量：業務文件沒有定義銷售數量（C21、C22）；本版假設只計有效訂單明細的數量，此為未經業務窗口確認的假設（confidence low）。",
 "代碼語意：會員等級、地區、退款原因、通路、在售旗標的中文含義來自業務文件，資料只能證實代碼集合一致，無法證實含義。",
 "優惠碼：文件稱成交單價已含優惠碼折扣，但資料中成交價對標價的折扣比例與是否使用優惠碼無關聯，因此未建立優惠碼的語意物件。",
 "未建立物件：取消率、配送天數、準時送達、新註冊客戶、待出貨訂單、客戶註冊日期等文件定義的概念，沒有對應的建構題，依最小化原則未納入。",
 "關係型態：資料中沒有跨來源的同義欄位需求，因此沒有 equivalence 關係；類別/地區/等級的取值以 hierarchy 表示。",
 "驗證範圍：部分跨表證據因查詢預算以 id 區段取樣（付款對訂單狀態、出貨對訂單狀態、成交價對標價、付款對明細合計），結論限於取樣範圍。",
 "結構驗證不代表任務答對率，尚未以實際題目執行驗證。"]
json.dump({"version":"ontology_v0","summary":summary,"limitations":limits,"links":links},open("annotate_v0.json","w"),ensure_ascii=False,indent=1)
print(len(links))
