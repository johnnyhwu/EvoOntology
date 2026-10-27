"""Create question sets and compute ground-truth answers directly from the DB.

PRIVATE. Outputs:
  poc/build_input/construction_questions.json   (visible to the Builder; NO answers)
  poc/_private/construction_gt.json             (sanity only)
  poc/_private/heldout.json                     (questions + GT; never shown to Builder)
Run: PYTHONDONTWRITEBYTECODE=1 poc/.venv/bin/python poc/_private/make_questions.py
"""
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "..", "data", "shop.sqlite")
OUT_BUILD = os.path.join(HERE, "..", "build_input", "construction_questions.json")

TZ = "datetime(o.order_ts,'+8 hours')"
VALID = "o.status IN (1,2,3)"


def period(start, end):
    return "%s >= '%s' AND %s < '%s'" % (TZ, start, TZ, end)


def vo_cte(start, end, extra=""):
    return ("WITH vo AS (SELECT o.order_id, o.customer_id FROM orders o WHERE %s AND %s %s) "
            % (VALID, period(start, end), extra))


def net_revenue(start, end, extra=""):
    return (vo_cte(start, end, extra) +
            "SELECT ROUND((SELECT COALESCE(SUM(oi.quantity*oi.unit_price_cents),0)/100.0 "
            "FROM order_items oi JOIN vo ON vo.order_id=oi.order_id) - "
            "(SELECT COALESCE(SUM(r.refund_amount_twd),0) FROM refunds r "
            "JOIN vo ON vo.order_id=r.order_id), 2)")


def aov(start, end):
    return (vo_cte(start, end) +
            "SELECT ROUND(SUM(oi.quantity*oi.unit_price_cents)/100.0/COUNT(DISTINCT vo.order_id),2) "
            "FROM vo JOIN order_items oi ON oi.order_id=vo.order_id")


def valid_orders_by_region(region):
    return ("SELECT COUNT(*) FROM orders o JOIN customers c ON c.customer_id=o.customer_id "
            "WHERE %s AND %s AND c.region_code='%s'" % (VALID, period("2025-01-01", "2026-01-01"), region))


def channel_share(channel):
    return ("SELECT ROUND(100.0*SUM(o.channel='%s')/COUNT(*),1) FROM orders o WHERE %s AND %s"
            % (channel, VALID, period("2025-01-01", "2026-01-01")))


def refund_total(start, end):
    return ("SELECT COALESCE(SUM(refund_amount_twd),0) FROM refunds WHERE "
            "datetime(refund_ts,'+8 hours') >= '%s' AND datetime(refund_ts,'+8 hours') < '%s'" % (start, end))


REPEAT = ("SELECT customer_id, COUNT(*) c FROM orders o WHERE %s AND %s GROUP BY customer_id HAVING c>=2"
          % (VALID, period("2025-01-01", "2026-01-01")))

CATEGORY_ZH = {"backpack": "登山背包", "tent": "帳篷", "shoes": "登山鞋",
               "apparel": "機能服飾", "accessory": "配件"}
METHOD_ZH = {"credit_card": "信用卡", "line_pay": "LINE Pay", "atm": "ATM", "cod": "貨到付款"}

# id, question, gt_sql, kind, accept_extra
CONSTRUCTION = [
    ("C01", "2025 年第一季的淨營收是多少？", net_revenue("2025-01-01", "2025-04-01"), "number", []),
    ("C02", "2025 年 6 月的客單價是多少？", aov("2025-06-01", "2025-07-01"), "number", []),
    ("C03", "歷史上哪個商品類別的退款金額最高？",
     "SELECT p.category FROM refunds r JOIN order_items oi ON oi.item_id=r.item_id "
     "JOIN products p ON p.product_id=oi.product_id GROUP BY p.category "
     "ORDER BY SUM(r.refund_amount_twd) DESC LIMIT 1", "text", CATEGORY_ZH),
    ("C04", "北部客戶在 2025 年共有多少張有效訂單？", valid_orders_by_region("TW-N"), "number", []),
    ("C05", "2025 年有多少位回購客戶？", "SELECT COUNT(*) FROM (%s)" % REPEAT, "number", []),
    ("C06", "2025 年有效訂單中，透過行動 App 下單的占比是多少（%）？", channel_share("app"), "number", []),
    ("C07", "哪一種付款方式的實收金額最高？",
     "SELECT method FROM payments WHERE payment_status='ok' GROUP BY method "
     "ORDER BY SUM(amount_twd) DESC LIMIT 1", "text", METHOD_ZH),
    ("C08", "黃金會員在 2025 年的淨營收是多少？",
     net_revenue("2025-01-01", "2026-01-01",
                 "AND o.customer_id IN (SELECT customer_id FROM customers WHERE tier='G')"), "number", []),
    ("C09", "2025 年 9 月的退款金額總計是多少？", refund_total("2025-09-01", "2025-10-01"), "number", []),
    ("C10", "目前仍在售的商品中，銷售數量最多的是哪一個？",
     "SELECT p.product_name FROM order_items oi JOIN orders o ON o.order_id=oi.order_id "
     "JOIN products p ON p.product_id=oi.product_id WHERE %s AND p.is_active=1 "
     "GROUP BY p.product_id ORDER BY SUM(oi.quantity) DESC LIMIT 1" % VALID, "text", {}),
]

HELDOUT = [
    ("H01", "near", "2025 年第三季的淨營收是多少？", net_revenue("2025-07-01", "2025-10-01"), "number", []),
    ("H02", "near", "2025 年 11 月的客單價是多少？", aov("2025-11-01", "2025-12-01"), "number", []),
    ("H03", "near", "南部客戶在 2025 年共有多少張有效訂單？", valid_orders_by_region("TW-S"), "number", []),
    ("H04", "near", "銀級會員在 2025 年的淨營收是多少？",
     net_revenue("2025-01-01", "2026-01-01",
                 "AND o.customer_id IN (SELECT customer_id FROM customers WHERE tier='S')"), "number", []),
    ("H05", "near", "2025 年 4 月的退款金額總計是多少？", refund_total("2025-04-01", "2025-05-01"), "number", []),
    ("H06", "near", "2025 年有效訂單中，透過官網下單的占比是多少（%）？", channel_share("web"), "number", []),
    ("H07", "far", "帳篷類商品在 2025 年的淨營收是多少？",
     vo_cte("2025-01-01", "2026-01-01") +
     "SELECT ROUND((SELECT COALESCE(SUM(oi.quantity*oi.unit_price_cents),0)/100.0 FROM order_items oi "
     "JOIN vo ON vo.order_id=oi.order_id JOIN products p ON p.product_id=oi.product_id WHERE p.category='tent') - "
     "(SELECT COALESCE(SUM(r.refund_amount_twd),0) FROM refunds r JOIN vo ON vo.order_id=r.order_id "
     "JOIN order_items oi ON oi.item_id=r.item_id JOIN products p ON p.product_id=oi.product_id "
     "WHERE p.category='tent'), 2)", "number", []),
    ("H08", "far", "因配送延遲而退款的金額，哪個商品類別最高？",
     "SELECT p.category FROM refunds r JOIN order_items oi ON oi.item_id=r.item_id "
     "JOIN products p ON p.product_id=oi.product_id WHERE r.reason_code='R4' GROUP BY p.category "
     "ORDER BY SUM(r.refund_amount_twd) DESC LIMIT 1", "text", CATEGORY_ZH),
    ("H09", "far", "2025 年每位回購客戶平均下了幾張有效訂單？",
     "SELECT ROUND(1.0*SUM(c)/COUNT(*),2) FROM (%s)" % REPEAT, "number", []),
    ("H10", "far", "有多少張訂單曾經付款失敗、之後又付款成功？",
     "SELECT COUNT(*) FROM (SELECT order_id FROM payments GROUP BY order_id "
     "HAVING SUM(payment_status='failed')>=1 AND SUM(payment_status='ok')>=1)", "number", []),
]


def answer_of(conn, sql):
    rows = conn.execute(sql).fetchall()
    assert len(rows) == 1 and len(rows[0]) == 1, (sql, rows)
    return rows[0][0]


def accept_list(value, extra):
    if isinstance(extra, dict):
        return [value] + ([extra[value]] if value in extra else [])
    return [value]


def main():
    conn = sqlite3.connect(DB)
    construction_gt, heldout = [], []
    for qid, text, sql, kind, extra in CONSTRUCTION:
        value = answer_of(conn, sql)
        construction_gt.append({"id": qid, "question": text, "gt_sql": sql, "kind": kind,
                                "answer": value, "accept": accept_list(value, extra)})
    for qid, group, text, sql, kind, extra in HELDOUT:
        value = answer_of(conn, sql)
        heldout.append({"id": qid, "group": group, "question": text, "gt_sql": sql, "kind": kind,
                        "answer": value, "accept": accept_list(value, extra)})
    with open(OUT_BUILD, "w", encoding="utf-8") as f:
        json.dump([{"id": q[0], "question": q[1]} for q in CONSTRUCTION], f, ensure_ascii=False, indent=2)
    with open(os.path.join(HERE, "construction_gt.json"), "w", encoding="utf-8") as f:
        json.dump(construction_gt, f, ensure_ascii=False, indent=2)
    with open(os.path.join(HERE, "heldout.json"), "w", encoding="utf-8") as f:
        json.dump(heldout, f, ensure_ascii=False, indent=2)
    for row in construction_gt + heldout:
        print(row["id"], row.get("group", "build"), "|", row["answer"])


if __name__ == "__main__":
    main()
