"""v2 question sets (30 construction + 40 held-out) with ground truth computed from shop_v2.sqlite.

PRIVATE. Outputs:
  poc/build_input_v2/construction_questions.json  (Builder-visible, NO answers)
  poc/_private/construction_gt_v2.json, poc/_private/heldout_v2.json
Groups of held-out questions:
  near        H01-H20  same concept families as construction, new parameters
  far_combo   H21-H30  new multi-condition / cross-table combinations of seen concepts
  far_unseen  H31-H40  metrics defined in the business doc but never asked in construction
Run: PYTHONDONTWRITEBYTECODE=1 poc/.venv/bin/python poc/_private/make_questions_v2.py
"""
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "..", "data", "shop_v2.sqlite")
OUT_BUILD = os.path.join(HERE, "..", "build_input_v2", "construction_questions.json")

VALID = "o.status IN (1,2,3)"
YEAR = ("2025-01-01", "2026-01-01")
Q = {1: ("2025-01-01", "2025-04-01"), 2: ("2025-04-01", "2025-07-01"),
     3: ("2025-07-01", "2025-10-01"), 4: ("2025-10-01", "2026-01-01")}
H1 = ("2025-01-01", "2025-07-01")


def month(m):
    return ("2025-%02d-01" % m, "2025-%02d-01" % (m + 1) if m < 12 else "2026-01-01")


def rng(period, col):
    return "datetime(%s,'+8 hours') >= '%s' AND datetime(%s,'+8 hours') < '%s'" % (col, period[0], col, period[1])


def region(code):
    return "AND o.customer_id IN (SELECT customer_id FROM customers WHERE region_code='%s')" % code


def tier(code):
    return "AND o.customer_id IN (SELECT customer_id FROM customers WHERE tier='%s')" % code


def channel(code):
    return "AND o.channel='%s'" % code


def vo_cte(period, extra=""):
    return "WITH vo AS (SELECT o.order_id, o.customer_id FROM orders o WHERE %s AND %s %s) " % (
        VALID, rng(period, "o.order_ts"), extra)


def net_rev(period, extra="", cat=None):
    cond = " AND p.category='%s'" % cat if cat else ""
    items = ("SELECT COALESCE(SUM(oi.quantity*oi.unit_price_cents),0)/100.0 FROM order_items oi "
             "JOIN vo ON vo.order_id=oi.order_id JOIN products p ON p.product_id=oi.product_id WHERE 1=1" + cond)
    refunds = ("SELECT COALESCE(SUM(r.refund_amount_twd),0) FROM refunds r JOIN vo ON vo.order_id=r.order_id "
               "JOIN order_items oi ON oi.item_id=r.item_id JOIN products p ON p.product_id=oi.product_id WHERE 1=1" + cond)
    return vo_cte(period, extra) + "SELECT ROUND((%s)-(%s),2)" % (items, refunds)


def aov(period, extra=""):
    return (vo_cte(period, extra) + "SELECT ROUND(SUM(oi.quantity*oi.unit_price_cents)/100.0/"
            "COUNT(DISTINCT vo.order_id),2) FROM vo JOIN order_items oi ON oi.order_id=vo.order_id")


def valid_orders(period, extra=""):
    return "SELECT COUNT(*) FROM orders o WHERE %s AND %s %s" % (VALID, rng(period, "o.order_ts"), extra)


def status_count(status, period=None):
    cond = " AND " + rng(period, "o.order_ts") if period else ""
    return "SELECT COUNT(*) FROM orders o WHERE o.status=%d%s" % (status, cond)


def repeat_base(period, extra=""):
    return ("SELECT o.customer_id, COUNT(*) c FROM orders o WHERE %s AND %s %s GROUP BY o.customer_id HAVING c>=2"
            % (VALID, rng(period, "o.order_ts"), extra))


def channel_share(code, period):
    return "SELECT ROUND(100.0*SUM(o.channel='%s')/COUNT(*),1) FROM orders o WHERE %s AND %s" % (
        code, VALID, rng(period, "o.order_ts"))


def refund_total(period, join=""):
    return "SELECT COALESCE(SUM(r.refund_amount_twd),0) FROM refunds r %s WHERE %s" % (
        join, rng(period, "r.refund_ts"))


def refund_join_tier(code):
    return ("JOIN orders o ON o.order_id=r.order_id JOIN customers c ON c.customer_id=o.customer_id "
            "AND c.tier='%s'" % code)


def top_refund_category(reason=None):
    cond = " WHERE r.reason_code='%s'" % reason if reason else ""
    return ("SELECT p.category, SUM(r.refund_amount_twd) v FROM refunds r JOIN order_items oi ON oi.item_id=r.item_id "
            "JOIN products p ON p.product_id=oi.product_id%s GROUP BY p.category ORDER BY v DESC LIMIT 2" % cond)


def top_refund_count():
    return ("SELECT p.category, COUNT(*) v FROM refunds r JOIN order_items oi ON oi.item_id=r.item_id "
            "JOIN products p ON p.product_id=oi.product_id WHERE %s GROUP BY p.category ORDER BY v DESC LIMIT 2"
            % rng(YEAR, "r.refund_ts"))


def collected(method, period):
    return ("SELECT COALESCE(SUM(amount_twd),0) FROM payments WHERE payment_status='ok' AND method='%s' AND %s"
            % (method, rng(period, "paid_ts")))


TOP_METHOD = ("SELECT method, SUM(amount_twd) v FROM payments WHERE payment_status='ok' "
              "GROUP BY method ORDER BY v DESC LIMIT 2")


def top_product(period=None):
    cond = " AND " + rng(period, "o.order_ts") if period else ""
    return ("SELECT p.product_name, SUM(oi.quantity) v FROM order_items oi JOIN orders o ON o.order_id=oi.order_id "
            "JOIN products p ON p.product_id=oi.product_id WHERE %s AND p.is_active=1%s "
            "GROUP BY p.product_id ORDER BY v DESC LIMIT 2" % (VALID, cond))


def line_pay_share(period):
    return ("SELECT ROUND(100.0*SUM(CASE WHEN o.order_id IN (SELECT order_id FROM payments WHERE payment_status='ok' "
            "AND method='line_pay') THEN 1 ELSE 0 END)/COUNT(*),1) FROM orders o WHERE %s AND %s"
            % (VALID, rng(period, "o.order_ts")))


def cancel_rate(period):
    return ("SELECT ROUND(100.0*SUM(o.status=9)/SUM(o.status IN (1,2,3,9)),1) FROM orders o WHERE %s"
            % rng(period, "o.order_ts"))


def ship_days(period, carrier=None):
    cond = " AND s.carrier='%s'" % carrier if carrier else ""
    return ("SELECT ROUND(AVG((strftime('%%s',s.delivered_ts)-strftime('%%s',s.shipped_ts))/86400.0),2) FROM shipments s "
            "JOIN orders o ON o.order_id=s.order_id WHERE s.delivered_ts IS NOT NULL AND %s%s"
            % (rng(period, "o.order_ts"), cond))


def on_time(period, carrier=None):
    cond = " AND s.carrier='%s'" % carrier if carrier else ""
    return ("SELECT ROUND(100.0*SUM((strftime('%%s',s.delivered_ts)-strftime('%%s',s.shipped_ts))<=259200)/COUNT(*),1) "
            "FROM shipments s JOIN orders o ON o.order_id=s.order_id WHERE s.delivered_ts IS NOT NULL AND %s%s"
            % (rng(period, "o.order_ts"), cond))


def new_customers(extra=""):
    return ("SELECT COUNT(*) FROM customers WHERE signup_date >= '2025-01-01' AND signup_date < '2026-01-01' %s"
            % extra)


REGIONS = ["TW-N", "TW-C", "TW-S", "JP", "SG"]
CAT_ZH = {"backpack": "登山背包", "tent": "帳篷", "shoes": "登山鞋", "apparel": "機能服飾", "accessory": "配件"}
METHOD_ZH = {"credit_card": "信用卡", "line_pay": "LINE Pay", "atm": "ATM", "cod": "貨到付款"}
REGION_ZH = {"TW-N": "北部", "TW-C": "中部", "TW-S": "南部", "JP": "日本", "SG": "新加坡"}

# (id, group, text, sql, kind, accept_map) ; kind: number | text | top (sql returns 2 rows: name, value)
CONSTRUCTION = [
    ("C01", "2025 年第一季的淨營收是多少？", net_rev(Q[1]), "number", None),
    ("C02", "北部客戶在 2025 年的淨營收是多少？", net_rev(YEAR, region("TW-N")), "number", None),
    ("C03", "黃金會員在 2025 年的淨營收是多少？", net_rev(YEAR, tier("G")), "number", None),
    ("C04", "2025 年 8 月的淨營收是多少？", net_rev(month(8)), "number", None),
    ("C05", "2025 年 6 月的客單價是多少？", aov(month(6)), "number", None),
    ("C06", "官網通路在 2025 年第二季的客單價是多少？", aov(Q[2], channel("web")), "number", None),
    ("C07", "一般會員在 2025 年的客單價是多少？", aov(YEAR, tier("B")), "number", None),
    ("C08", "北部客戶在 2025 年共有多少張有效訂單？", valid_orders(YEAR, region("TW-N")), "number", None),
    ("C09", "2025 年 3 月有多少張有效訂單？", valid_orders(month(3)), "number", None),
    ("C10", "行動 App 在 2025 年共有多少張有效訂單？", valid_orders(YEAR, channel("app")), "number", None),
    ("C11", "2025 年有多少位回購客戶？", "SELECT COUNT(*) FROM (%s)" % repeat_base(YEAR), "number", None),
    ("C12", "北部客戶在 2025 年有多少位回購客戶？",
     "SELECT COUNT(*) FROM (%s)" % repeat_base(YEAR, region("TW-N")), "number", None),
    ("C13", "2025 年有效訂單中，透過行動 App 下單的占比是多少（%）？", channel_share("app", YEAR), "number", None),
    ("C14", "2025 年有效訂單中，實體門市的占比是多少（%）？", channel_share("store", YEAR), "number", None),
    ("C15", "2025 年 9 月的退款金額總計是多少？", refund_total(month(9)), "number", None),
    ("C16", "2025 年第二季的退款金額總計是多少？", refund_total(Q[2]), "number", None),
    ("C17", "歷史上哪個商品類別的退款金額最高？", top_refund_category(), "top", CAT_ZH),
    ("C18", "因改變心意而退款的金額，哪個商品類別最高？", top_refund_category("R2"), "top", CAT_ZH),
    ("C19", "哪一種付款方式的實收金額最高？", TOP_METHOD, "top", METHOD_ZH),
    ("C20", "信用卡在 2025 年的實收金額是多少？", collected("credit_card", YEAR), "number", None),
    ("C21", "目前仍在售的商品中，銷售數量最多的是哪一個？", top_product(), "top", None),
    ("C22", "在售商品中，2025 年第四季銷售數量最多的是哪一個？", top_product(Q[4]), "top", None),
    ("C23", "登山鞋在 2025 年的淨營收是多少？", net_rev(YEAR, "", "shoes"), "number", None),
    ("C24", "2025 年第四季有多少張已取消的訂單？", status_count(9, Q[4]), "number", None),
    ("C25", "目前有多少張待付款的訂單？", status_count(0), "number", None),
    ("C26", "日本客戶在 2025 年的淨營收是多少？", net_rev(YEAR, region("JP")), "number", None),
    ("C27", "黃金會員在 2025 年的客單價是多少？", aov(YEAR, tier("G")), "number", None),
    ("C28", "2025 年 12 月的退款金額總計是多少？", refund_total(month(12)), "number", None),
    ("C29", "銀級會員在 2025 年共有多少張有效訂單？", valid_orders(YEAR, tier("S")), "number", None),
    ("C30", "2025 年淨營收最高的地區是哪一個？", None, "region_max", REGION_ZH),
]

HELDOUT = [
    ("H01", "near", "2025 年第三季的淨營收是多少？", net_rev(Q[3]), "number", None),
    ("H02", "near", "中部客戶在 2025 年的淨營收是多少？", net_rev(YEAR, region("TW-C")), "number", None),
    ("H03", "near", "銀級會員在 2025 年的淨營收是多少？", net_rev(YEAR, tier("S")), "number", None),
    ("H04", "near", "2025 年 11 月的淨營收是多少？", net_rev(month(11)), "number", None),
    ("H05", "near", "2025 年 11 月的客單價是多少？", aov(month(11)), "number", None),
    ("H06", "near", "行動 App 通路在 2025 年第三季的客單價是多少？", aov(Q[3], channel("app")), "number", None),
    ("H07", "near", "銀級會員在 2025 年的客單價是多少？", aov(YEAR, tier("S")), "number", None),
    ("H08", "near", "南部客戶在 2025 年共有多少張有效訂單？", valid_orders(YEAR, region("TW-S")), "number", None),
    ("H09", "near", "2025 年 7 月有多少張有效訂單？", valid_orders(month(7)), "number", None),
    ("H10", "near", "實體門市在 2025 年共有多少張有效訂單？", valid_orders(YEAR, channel("store")), "number", None),
    ("H11", "near", "南部客戶在 2025 年有多少位回購客戶？",
     "SELECT COUNT(*) FROM (%s)" % repeat_base(YEAR, region("TW-S")), "number", None),
    ("H12", "near", "2025 年有效訂單中，透過官網下單的占比是多少（%）？", channel_share("web", YEAR), "number", None),
    ("H13", "near", "2025 年 4 月的退款金額總計是多少？", refund_total(month(4)), "number", None),
    ("H14", "near", "2025 年第四季的退款金額總計是多少？", refund_total(Q[4]), "number", None),
    ("H15", "near", "2025 年退款筆數最多的商品類別是哪一個？", top_refund_count(), "top", CAT_ZH),
    ("H16", "near", "LINE Pay 在 2025 年的實收金額是多少？", collected("line_pay", YEAR), "number", None),
    ("H17", "near", "在售商品中，2025 年第一季銷售數量最多的是哪一個？", top_product(Q[1]), "top", None),
    ("H18", "near", "登山背包在 2025 年的淨營收是多少？", net_rev(YEAR, "", "backpack"), "number", None),
    ("H19", "near", "新加坡客戶在 2025 年的淨營收是多少？", net_rev(YEAR, region("SG")), "number", None),
    ("H20", "near", "2025 年第二季有多少張已取消的訂單？", status_count(9, Q[2]), "number", None),
    ("H21", "far_combo", "北部的黃金會員在 2025 年的淨營收是多少？", net_rev(YEAR, region("TW-N") + " " + tier("G")), "number", None),
    ("H22", "far_combo", "帳篷在 2025 年第二季的淨營收是多少？", net_rev(Q[2], "", "tent"), "number", None),
    ("H23", "far_combo", "2025 年每位回購客戶平均下了幾張有效訂單？",
     "SELECT ROUND(1.0*SUM(c)/COUNT(*),2) FROM (%s)" % repeat_base(YEAR), "number", None),
    ("H24", "far_combo", "2025 年的回購客戶占有下單客戶的比例是多少（%）？",
     "SELECT ROUND(100.0*(SELECT COUNT(*) FROM (%s))/(SELECT COUNT(DISTINCT o.customer_id) FROM orders o "
     "WHERE %s AND %s),1)" % (repeat_base(YEAR), VALID, rng(YEAR, "o.order_ts")), "number", None),
    ("H25", "far_combo", "實體門市在 2025 年上半年的客單價是多少？", aov(H1, channel("store")), "number", None),
    ("H26", "far_combo", "黃金會員在 2025 年的退款金額總計是多少？", refund_total(YEAR, refund_join_tier("G")), "number", None),
    ("H27", "far_combo", "2025 年有效訂單中，用 LINE Pay 付款的占比是多少（%）？", line_pay_share(YEAR), "number", None),
    ("H28", "far_combo", "2025 年客單價最低的地區是哪一個？", None, "region_aov_min", REGION_ZH),
    ("H29", "far_combo", "北部客戶在 2025 年的客單價是多少？", aov(YEAR, region("TW-N")), "number", None),
    ("H30", "far_combo", "2025 年有多少位客戶買過帳篷（有效訂單）？",
     "SELECT COUNT(DISTINCT o.customer_id) FROM orders o JOIN order_items oi ON oi.order_id=o.order_id "
     "JOIN products p ON p.product_id=oi.product_id WHERE %s AND %s AND p.category='tent'"
     % (VALID, rng(YEAR, "o.order_ts")), "number", None),
    ("H31", "far_unseen", "有多少張訂單曾經付款失敗、之後又付款成功？",
     "SELECT COUNT(*) FROM (SELECT order_id FROM payments GROUP BY order_id "
     "HAVING SUM(payment_status='failed')>=1 AND SUM(payment_status='ok')>=1)", "number", None),
    ("H32", "far_unseen", "2025 年的取消率是多少（%）？", cancel_rate(YEAR), "number", None),
    ("H33", "far_unseen", "2025 年的平均配送天數是多少？", ship_days(YEAR), "number", None),
    ("H34", "far_unseen", "2025 年的準時送達率是多少（%）？", on_time(YEAR), "number", None),
    ("H35", "far_unseen", "黑貓宅急便在 2025 年的平均配送天數是多少？", ship_days(YEAR, "blackcat"), "number", None),
    ("H36", "far_unseen", "2025 年有多少位新註冊客戶？", new_customers(), "number", None),
    ("H37", "far_unseen", "使用 WELCOME10 優惠碼的有效訂單在 2025 年有多少張？",
     valid_orders(YEAR, "AND o.coupon_code='WELCOME10'"), "number", None),
    ("H38", "far_unseen", "目前有多少張已付款但尚未出貨的訂單？", status_count(1), "number", None),
    ("H39", "far_unseen", "2025 年北部的新註冊客戶有多少位？",
     new_customers("AND region_code='TW-N'"), "number", None),
    ("H40", "far_unseen", "順豐在 2025 年的準時送達率是多少（%）？", on_time(YEAR, "sf"), "number", None),
]


def evaluate(conn, qid, sql, kind, accept_map):
    if kind in ("region_max", "region_aov_min"):
        scores = {}
        for code in REGIONS:
            builder = net_rev if kind == "region_max" else aov
            scores[code] = conn.execute(builder(YEAR, region(code))).fetchone()[0]
        pick = max if kind == "region_max" else min
        value = pick(scores, key=scores.get)
        ordered = sorted(scores.values(), reverse=(kind == "region_max"))
        assert ordered[0] != ordered[1], qid
        return value, [value, accept_map[value]], "%s per region: %s" % (
            "net_rev" if kind == "region_max" else "aov", scores)
    rows = conn.execute(sql).fetchall()
    if kind == "top":
        assert len(rows) == 2 and rows[0][1] != rows[1][1], (qid, rows)
        value = rows[0][0]
        accept = [value] + ([accept_map[value]] if accept_map and value in accept_map else [])
        return value, accept, sql
    assert len(rows) == 1 and len(rows[0]) == 1, (qid, rows)
    return rows[0][0], [], sql


def main():
    conn = sqlite3.connect(DB)
    construction, heldout = [], []
    for qid, text, sql, kind, accept_map in CONSTRUCTION:
        value, accept, shown_sql = evaluate(conn, qid, sql, kind, accept_map)
        construction.append({"id": qid, "question": text, "kind": "text" if kind != "number" else "number",
                             "answer": value, "accept": accept, "gt_sql": shown_sql})
    for qid, group, text, sql, kind, accept_map in HELDOUT:
        value, accept, shown_sql = evaluate(conn, qid, sql, kind, accept_map)
        heldout.append({"id": qid, "group": group, "question": text,
                        "kind": "text" if kind != "number" else "number",
                        "answer": value, "accept": accept, "gt_sql": shown_sql})
    with open(OUT_BUILD, "w", encoding="utf-8") as f:
        json.dump([{"id": q["id"], "question": q["question"]} for q in construction], f, ensure_ascii=False, indent=2)
    json.dump(construction, open(os.path.join(HERE, "construction_gt_v2.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(heldout, open(os.path.join(HERE, "heldout_v2.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    for row in construction + heldout:
        print(row["id"], row.get("group", "build"), "|", row["answer"])


if __name__ == "__main__":
    main()
