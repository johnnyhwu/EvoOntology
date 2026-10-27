"""Generate the PoC-2 question sets (with SQL-computed ground truth) from shop_v2.sqlite.

Outputs
  scenario/stream_questions.json      40 "production" tasks (visible to the pipeline, NO answers)
  scenario/test_questions.json        16 fresh test tasks (visible, NO answers; used only for the final audit)
  _private/gt.json                    ground truth + family labels (read ONLY by evopipe/audit.py)

Why these questions: the stream imitates what users would ask after ontology_v0 went live.
It mixes (a) concepts the construction questions already covered, asked with *different wording*
(e.g. "下單日期" / "成立日期" for the order timestamp), and (b) metrics that the business doc
defines but the construction workload never asked about (cancel rate, delivery days, ...).
Those two groups are exactly the gaps the Evolve loop is supposed to discover.

Run:  PYTHONDONTWRITEBYTECODE=1 poc/.venv/bin/python poc/v3/scenario/make_stream.py
"""
import json
import os
import random
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
V3 = os.path.dirname(HERE)
DB = os.path.join(V3, "..", "data", "shop_v2.sqlite")
SEED = 20261027

VALID = "o.status IN (1,2,3)"


# ---------------------------------------------------------------- SQL helpers
def month(m):
    return ("2025-%02d-01" % m, "2025-%02d-01" % (m + 1) if m < 12 else "2026-01-01")


QUARTER = {1: ("2025-01-01", "2025-04-01"), 2: ("2025-04-01", "2025-07-01"),
           3: ("2025-07-01", "2025-10-01"), 4: ("2025-10-01", "2026-01-01")}
YEAR = ("2025-01-01", "2026-01-01")
H1 = ("2025-01-01", "2025-07-01")


def rng(period, col):
    """Period filter on a UTC timestamp column, evaluated in Taipei time (UTC+8)."""
    return "datetime(%s,'+8 hours') >= '%s' AND datetime(%s,'+8 hours') < '%s'" % (col, period[0], col, period[1])


def cust(field, value):
    return "AND o.customer_id IN (SELECT customer_id FROM customers WHERE %s='%s')" % (field, value)


def vo(period, extra=""):
    return "WITH vo AS (SELECT o.order_id, o.customer_id FROM orders o WHERE %s AND %s %s) " % (
        VALID, rng(period, "o.order_ts"), extra)


def q_valid_orders(period, extra=""):
    return "SELECT COUNT(*) FROM orders o WHERE %s AND %s %s" % (VALID, rng(period, "o.order_ts"), extra)


def q_net_revenue(period, extra="", cat=None):
    cond = " AND p.category='%s'" % cat if cat else ""
    items = ("SELECT COALESCE(SUM(oi.quantity*oi.unit_price_cents),0)/100.0 FROM order_items oi "
             "JOIN vo ON vo.order_id=oi.order_id JOIN products p ON p.product_id=oi.product_id WHERE 1=1" + cond)
    refunds = ("SELECT COALESCE(SUM(r.refund_amount_twd),0) FROM refunds r JOIN vo ON vo.order_id=r.order_id "
               "JOIN order_items oi ON oi.item_id=r.item_id JOIN products p ON p.product_id=oi.product_id WHERE 1=1" + cond)
    return vo(period, extra) + "SELECT ROUND((%s)-(%s),2)" % (items, refunds)


def q_aov(period, extra=""):
    return (vo(period, extra) + "SELECT ROUND(SUM(oi.quantity*oi.unit_price_cents)/100.0/"
            "COUNT(DISTINCT vo.order_id),2) FROM vo JOIN order_items oi ON oi.order_id=vo.order_id")


def q_repeat_count(period, extra=""):
    return ("SELECT COUNT(*) FROM (SELECT o.customer_id FROM orders o WHERE %s AND %s %s "
            "GROUP BY o.customer_id HAVING COUNT(*)>=2)" % (VALID, rng(period, "o.order_ts"), extra))


def q_repeat_share(period, extra=""):
    return ("SELECT ROUND(100.0*SUM(c>=2)/COUNT(*),1) FROM (SELECT o.customer_id, COUNT(*) c FROM orders o "
            "WHERE %s AND %s %s GROUP BY o.customer_id)" % (VALID, rng(period, "o.order_ts"), extra))


def q_refund_total(period, extra=""):
    return "SELECT COALESCE(SUM(r.refund_amount_twd),0) FROM refunds r WHERE %s %s" % (rng(period, "r.refund_ts"), extra)


def q_collected(period, method):
    return ("SELECT COALESCE(SUM(amount_twd),0) FROM payments WHERE payment_status='ok' AND method='%s' AND %s"
            % (method, rng(period, "paid_ts")))


def q_cancel_rate(period, extra=""):
    return ("SELECT ROUND(100.0*SUM(o.status=9)/SUM(o.status IN (1,2,3,9)),1) FROM orders o WHERE %s %s"
            % (rng(period, "o.order_ts"), extra))


def q_ship_days(period, carrier=None):
    cond = " AND s.carrier='%s'" % carrier if carrier else ""
    return ("SELECT ROUND(AVG((strftime('%%s',s.delivered_ts)-strftime('%%s',s.shipped_ts))/86400.0),2) FROM shipments s "
            "JOIN orders o ON o.order_id=s.order_id WHERE s.delivered_ts IS NOT NULL AND %s%s"
            % (rng(period, "o.order_ts"), cond))


def q_ontime(period, carrier=None):
    cond = " AND s.carrier='%s'" % carrier if carrier else ""
    return ("SELECT ROUND(100.0*SUM((strftime('%%s',s.delivered_ts)-strftime('%%s',s.shipped_ts))<=259200)/COUNT(*),1) "
            "FROM shipments s JOIN orders o ON o.order_id=s.order_id WHERE s.delivered_ts IS NOT NULL AND %s%s"
            % (rng(period, "o.order_ts"), cond))


def q_new_customers(lo, hi, extra=""):
    return "SELECT COUNT(*) FROM customers WHERE signup_date >= '%s' AND signup_date < '%s' %s" % (lo, hi, extra)


def q_coupon_orders(code, period):
    return ("SELECT COUNT(*) FROM orders o WHERE %s AND o.coupon_code='%s' AND %s" % (VALID, code, rng(period, "o.order_ts")))


def q_coupon_share(code, period):
    return ("SELECT ROUND(100.0*SUM(o.coupon_code='%s')/COUNT(*),1) FROM orders o WHERE %s AND %s"
            % (code, VALID, rng(period, "o.order_ts")))


def q_pending_ship(extra=""):
    return "SELECT COUNT(*) FROM orders o WHERE o.status=1 %s" % extra


# ---------------------------------------------------------------- question lists
# Each item: (family, kind, text, sql, tolerance_kind)
#   kind: seen_reworded | combo | unseen        (private label, only for the final analysis)
#   tolerance: count | money | ratio | name
STREAM = [
    # -- seen concept, reworded time dimension (the timezone rule hides behind a different word) --
    ("valid_orders", "seen_reworded", "2025 年 7 月下單的有效訂單有幾張？", q_valid_orders(month(7)), "count"),
    ("valid_orders", "seen_reworded", "訂單日期落在 2025 年 9 月的有效訂單數是多少？", q_valid_orders(month(9)), "count"),
    ("valid_orders", "seen_reworded", "2025 年第三季（依成立日期）有效訂單共幾筆？", q_valid_orders(QUARTER[3]), "count"),
    ("valid_orders", "seen_reworded", "網站通路 2025 年 4 月的有效訂單有多少張？", q_valid_orders(month(4), "AND o.channel='web'"), "count"),
    ("valid_orders", "seen_reworded", "App 通路在 2025 年 12 月的有效訂單數？", q_valid_orders(month(12), "AND o.channel='app'"), "count"),
    ("valid_orders", "seen_reworded", "2025 年 1 月份的有效訂單總數為多少？", q_valid_orders(month(1)), "count"),
    ("valid_orders", "seen_reworded", "門市 2025 年 6 月成立的有效訂單有幾張？", q_valid_orders(month(6), "AND o.channel='store'"), "count"),
    # -- seen concepts, same wording style as construction (control group) --
    ("net_revenue", "combo", "南部客戶在 2025 年第二季的淨營收是多少？", q_net_revenue(QUARTER[2], cust("region_code", "TW-S")), "money"),
    ("net_revenue", "combo", "銀級會員 2025 年上半年的淨營收是多少？", q_net_revenue(H1, cust("tier", "S")), "money"),
    ("net_revenue", "combo", "帳篷類別在 2025 年第三季的淨營收是多少？", q_net_revenue(QUARTER[3], cat="tent"), "money"),
    ("aov", "combo", "網站通路 2025 年全年的客單價是多少？", q_aov(YEAR, "AND o.channel='web'"), "money"),
    ("aov", "combo", "黃金會員在 2025 年第四季的客單價是多少？", q_aov(QUARTER[4], cust("tier", "G")), "money"),
    ("repeat", "combo", "2025 年南部客戶的回購客戶有幾位？", q_repeat_count(YEAR, cust("region_code", "TW-S")), "count"),
    ("refund", "combo", "2025 年 8 月的退款金額（退款報表）是多少？", q_refund_total(month(8)), "money"),
    ("collected", "combo", "2025 年 5 月 LINE Pay 的實收金額是多少？", q_collected(month(5), "line_pay"), "money"),
    # -- unseen metrics: defined in the business doc, never asked while building v0 --
    ("cancel_rate", "unseen", "2025 年 6 月的取消率是多少？", q_cancel_rate(month(6)), "ratio"),
    ("cancel_rate", "unseen", "官網通路在 2025 年第一季的取消率是多少？", q_cancel_rate(QUARTER[1], "AND o.channel='web'"), "ratio"),
    ("cancel_rate", "unseen", "App 通路 2025 年 10 月的訂單取消率？", q_cancel_rate(month(10), "AND o.channel='app'"), "ratio"),
    ("cancel_rate", "unseen", "2025 年 11 月整體取消率是多少？", q_cancel_rate(month(11)), "ratio"),
    ("ship_days", "unseen", "黑貓宅急便在 2025 年的平均配送天數是多少？", q_ship_days(YEAR, "blackcat"), "ratio"),
    ("ship_days", "unseen", "2025 年第二季所有物流商合計的平均配送天數？", q_ship_days(QUARTER[2]), "ratio"),
    ("ship_days", "unseen", "順豐在 2025 年上半年的平均配送天數是多少？", q_ship_days(H1, "sf"), "ratio"),
    ("ontime", "unseen", "新竹物流 2025 年的準時送達率是多少？", q_ontime(YEAR, "hct"), "ratio"),
    ("ontime", "unseen", "2025 年第三季整體準時送達率？", q_ontime(QUARTER[3]), "ratio"),
    ("ontime", "unseen", "中華郵政在 2025 年的準時送達率是多少？", q_ontime(YEAR, "post"), "ratio"),
    ("new_customers", "unseen", "2025 年 3 月新註冊的客戶有幾位？", q_new_customers("2025-03-01", "2025-04-01"), "count"),
    ("new_customers", "unseen", "2025 年第二季新註冊的客戶有多少位？", q_new_customers("2025-04-01", "2025-07-01"), "count"),
    ("new_customers", "unseen", "日本地區 2025 年新註冊客戶數是多少？",
     q_new_customers("2025-01-01", "2026-01-01", "AND region_code='JP'"), "count"),
    ("coupon", "unseen", "2025 年使用 WELCOME10 優惠碼的有效訂單有幾張？", q_coupon_orders("WELCOME10", YEAR), "count"),
    ("coupon", "unseen", "2025 年 7 月使用 SUMMER15 的有效訂單數？", q_coupon_orders("SUMMER15", month(7)), "count"),
    ("coupon", "unseen", "2025 年第一季有效訂單中，使用 WELCOME10 的占比是多少？", q_coupon_share("WELCOME10", QUARTER[1]), "ratio"),
    ("pending_ship", "unseen", "目前待出貨的訂單有幾張？", q_pending_ship(), "count"),
    # -- extra time-sensitive questions with unusual wording (mixed into the tail of the stream) --
    ("valid_orders", "seen_reworded", "請問 2025 年 2 月成立的有效訂單有多少筆？", q_valid_orders(month(2)), "count"),
    ("valid_orders", "seen_reworded", "2025 年 11 月官網下單的有效訂單數？", q_valid_orders(month(11), "AND o.channel='web'"), "count"),
    ("cancel_rate", "unseen", "2025 年 8 月門市通路的取消率？", q_cancel_rate(month(8), "AND o.channel='store'"), "ratio"),
    ("ship_days", "unseen", "2025 年第四季的平均配送天數是多少？", q_ship_days(QUARTER[4]), "ratio"),
    ("coupon", "unseen", "2025 年 12 月使用 WELCOME10 的有效訂單有幾張？", q_coupon_orders("WELCOME10", month(12)), "count"),
    ("new_customers", "unseen", "北部客戶在 2025 年新註冊的有幾位？",
     q_new_customers("2025-01-01", "2026-01-01", "AND region_code='TW-N'"), "count"),
    ("ontime", "unseen", "黑貓宅急便 2025 年第一季的準時送達率是多少？", q_ontime(QUARTER[1], "blackcat"), "ratio"),
    ("net_revenue", "combo", "北部客戶 2025 年 11 月的淨營收是多少？", q_net_revenue(month(11), cust("region_code", "TW-N")), "money"),
]

TEST = [
    ("valid_orders", "seen_reworded", "2025 年 3 月下單的有效訂單有幾張？", q_valid_orders(month(3)), "count"),
    ("valid_orders", "seen_reworded", "訂單日期在 2025 年 10 月的有效訂單總數？", q_valid_orders(month(10)), "count"),
    ("valid_orders", "seen_reworded", "2025 年第二季（依成立日期）門市有效訂單共幾筆？",
     q_valid_orders(QUARTER[2], "AND o.channel='store'"), "count"),
    ("valid_orders", "seen_reworded", "2025 年 5 月官網的有效訂單有多少張？", q_valid_orders(month(5), "AND o.channel='web'"), "count"),
    ("net_revenue", "combo", "中部客戶 2025 年第四季的淨營收是多少？", q_net_revenue(QUARTER[4], cust("region_code", "TW-C")), "money"),
    ("aov", "combo", "App 通路 2025 年上半年的客單價是多少？", q_aov(H1, "AND o.channel='app'"), "money"),
    ("cancel_rate", "unseen", "2025 年 9 月的取消率是多少？", q_cancel_rate(month(9)), "ratio"),
    ("cancel_rate", "unseen", "官網 2025 年第二季的訂單取消率？", q_cancel_rate(QUARTER[2], "AND o.channel='web'"), "ratio"),
    ("ship_days", "unseen", "新竹物流在 2025 年的平均配送天數是多少？", q_ship_days(YEAR, "hct"), "ratio"),
    ("ontime", "unseen", "順豐 2025 年的準時送達率是多少？", q_ontime(YEAR, "sf"), "ratio"),
    ("ontime", "unseen", "2025 年第二季整體準時送達率？", q_ontime(QUARTER[2]), "ratio"),
    ("new_customers", "unseen", "2025 年 9 月新註冊的客戶有幾位？", q_new_customers("2025-09-01", "2025-10-01"), "count"),
    ("new_customers", "unseen", "新加坡 2025 年新註冊客戶數？", q_new_customers("2025-01-01", "2026-01-01", "AND region_code='SG'"), "count"),
    ("coupon", "unseen", "2025 年使用 SUMMER15 的有效訂單有幾張？", q_coupon_orders("SUMMER15", YEAR), "count"),
    ("coupon", "unseen", "2025 年第三季有效訂單中，使用 SUMMER15 的占比是多少？", q_coupon_share("SUMMER15", QUARTER[3]), "ratio"),
    ("pending_ship", "unseen", "官網通路目前待出貨的訂單有幾張？", q_pending_ship("AND o.channel='web'"), "count"),
]


# How many questions of each family arrive in the *last* 30% of the stream (= Validation Reserve).
# The real system just splits chronologically; here we control the arrival order of the simulated
# stream so that the reserve is representative of every family (otherwise a fix for e.g. delivery
# metrics could not be validated at all). Documented in the report.
RESERVE_QUOTA = {"valid_orders": 3, "net_revenue": 1, "aov": 1, "refund": 1, "cancel_rate": 1,
                 "ship_days": 1, "ontime": 1, "new_customers": 1, "coupon": 1, "collected": 1}


def build(items, prefix, conn, shuffle):
    rows = []
    for fam, kind, text, sql, tol in items:
        value = conn.execute(sql).fetchall()
        assert len(value) == 1 and len(value[0]) == 1 and value[0][0] is not None, (text, value)
        rows.append({"family": fam, "kind": kind, "question": text, "sql": sql, "tolerance": tol, "gt": value[0][0]})
    if shuffle:
        rng_ = random.Random(SEED)
        rng_.shuffle(rows)
        taken, pool, reserve = {}, [], []
        for r in rows:
            if taken.get(r["family"], 0) < RESERVE_QUOTA.get(r["family"], 0):
                taken[r["family"]] = taken.get(r["family"], 0) + 1
                reserve.append(r)
            else:
                pool.append(r)
        rows = pool + reserve
    for i, r in enumerate(rows, 1):
        r["id"] = "%s%02d" % (prefix, i)
    return rows


def main():
    conn = sqlite3.connect("file:%s?mode=ro" % os.path.abspath(DB), uri=True)
    stream = build(STREAM, "S", conn, shuffle=True)
    test = build(TEST, "T", conn, shuffle=False)
    # sanity: no duplicated question text
    texts = [r["question"] for r in stream + test]
    assert len(texts) == len(set(texts)), "duplicate question text"
    visible = lambda rows: [{"id": r["id"], "question": r["question"]} for r in rows]
    json.dump(visible(stream), open(os.path.join(HERE, "stream_questions.json"), "w"), ensure_ascii=False, indent=1)
    json.dump(visible(test), open(os.path.join(HERE, "test_questions.json"), "w"), ensure_ascii=False, indent=1)
    gt = {r["id"]: {k: r[k] for k in ("family", "kind", "tolerance", "gt", "sql", "question")} for r in stream + test}
    json.dump(gt, open(os.path.join(V3, "_private", "gt.json"), "w"), ensure_ascii=False, indent=1)
    pool_n = int(len(stream) * 0.7)
    print("stream=%d test=%d  (chronological 70/30 -> pool %d / reserve %d)" % (len(stream), len(test), pool_n, len(stream) - pool_n))
    for label, part in (("pool", stream[:pool_n]), ("reserve", stream[pool_n:])):
        by = {}
        for r in part:
            by.setdefault(r["kind"] + "/" + r["family"], 0)
            by[r["kind"] + "/" + r["family"]] += 1
        print(label, dict(sorted(by.items())))


if __name__ == "__main__":
    main()
