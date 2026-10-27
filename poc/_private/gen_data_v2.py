"""Generate the LARGE (v2) fake "Lumo Outdoors" database -> poc/data/shop_v2.sqlite.

PRIVATE (encodes data traps). 7 tables: v1's six + shipments. Deterministic.
Run: PYTHONDONTWRITEBYTECODE=1 poc/.venv/bin/python poc/_private/gen_data_v2.py
"""
import bisect
import itertools
import os
import random
import sqlite3
from datetime import datetime, timedelta

random.seed(20251022)
HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "..", "data", "shop_v2.sqlite")

N_CUSTOMERS, N_PRODUCTS_PER_CAT, N_ORDERS = 5000, 40, 60000

DDL = """
CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, name TEXT, email TEXT,
    region_code TEXT, signup_date TEXT, tier TEXT);
CREATE TABLE products (product_id INTEGER PRIMARY KEY, sku TEXT, product_name TEXT,
    category TEXT, list_price_twd INTEGER, is_active INTEGER);
CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER, order_ts TEXT,
    status INTEGER, channel TEXT, coupon_code TEXT);
CREATE TABLE order_items (item_id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER,
    quantity INTEGER, unit_price_cents INTEGER);
CREATE TABLE payments (payment_id INTEGER PRIMARY KEY, order_id INTEGER, method TEXT,
    amount_twd INTEGER, paid_ts TEXT, payment_status TEXT);
CREATE TABLE refunds (refund_id INTEGER PRIMARY KEY, order_id INTEGER, item_id INTEGER,
    refund_amount_twd INTEGER, refund_ts TEXT, reason_code TEXT);
CREATE TABLE shipments (shipment_id INTEGER PRIMARY KEY, order_id INTEGER, carrier TEXT,
    shipped_ts TEXT, delivered_ts TEXT);
"""

SURNAMES = list("陳林黃張李王吳劉蔡楊許鄭謝郭洪曾邱廖賴")
GIVEN = ["怡君", "家豪", "雅婷", "冠宇", "宗翰", "佩珊", "柏翰", "欣怡", "承恩", "品妤",
         "俊傑", "詩涵", "彥廷", "郁婷", "建宏", "淑芬", "志明", "美玲", "子謙", "思穎"]
SERIES = ["雪嶺", "雲杉", "岩峰", "星野", "溪谷", "晨霧", "朔風", "林間", "潮汐", "曙光",
          "青稜", "遠行", "霧淞", "鷹眼", "松濤", "磐石", "瀑布", "月影", "疾風", "拓荒"]
CATEGORIES = {"backpack": ("登山背包", (1500, 6000), "BP"), "tent": ("帳篷", (4000, 15000), "TN"),
              "shoes": ("登山鞋", (2000, 7000), "SH"), "apparel": ("機能服飾", (600, 3500), "AP"),
              "accessory": ("配件", (200, 1500), "AC")}


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def weighted(choices):
    values, weights = zip(*choices)
    return random.choices(values, weights=weights, k=1)[0]


def sampler(weights):
    cum = list(itertools.accumulate(weights))
    total = cum[-1]
    return lambda: bisect.bisect(cum, random.random() * total)


def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(DDL)

    customers = []
    for cid in range(1, N_CUSTOMERS + 1):
        signup = datetime(2023, 1, 1) + timedelta(days=random.randint(0, 1095))
        customers.append((cid, random.choice(SURNAMES) + random.choice(GIVEN), "u%05d@example.com" % cid,
                          weighted([("TW-N", 40), ("TW-C", 25), ("TW-S", 20), ("JP", 10), ("SG", 5)]),
                          signup.strftime("%Y-%m-%d"), weighted([("B", 70), ("S", 20), ("G", 10)])))
    conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?)", customers)

    products, pid = [], 0
    for code, (zh, (lo, hi), prefix) in CATEGORIES.items():
        for n in range(N_PRODUCTS_PER_CAT):
            pid += 1
            price = int(round(random.randint(lo, hi) / 100.0)) * 100
            products.append((pid, "LUMO-%s-%03d" % (prefix, n + 1), "%s %s%d" % (SERIES[n % 20], zh, n // 20 + 1),
                             code, price, 1 if random.random() < 0.85 else 0))
    conn.executemany("INSERT INTO products VALUES (?,?,?,?,?,?)", products)
    price_of = {p[0]: p[4] for p in products}

    pick_customer = sampler([random.random() ** 2 + 0.02 for _ in range(N_CUSTOMERS)])
    pick_product = sampler([random.random() ** 1.5 + 0.05 for _ in range(len(products))])
    start = datetime(2024, 12, 30)
    span = int((datetime(2025, 12, 31, 23, 59) - start).total_seconds())

    orders, items, payments, refunds, shipments = [], [], [], [], []
    item_id = payment_id = refund_id = shipment_id = 0
    for oid in range(1, N_ORDERS + 1):
        order_dt = start + timedelta(seconds=random.randint(0, span))
        status = weighted([(0, 5), (1, 6), (2, 8), (3, 66), (9, 15)])
        channel = weighted([("web", 50), ("app", 35), ("store", 15)])
        coupon = weighted([(None, 70), ("WELCOME10", 15), ("SUMMER15", 15)])
        orders.append((oid, pick_customer() + 1, fmt(order_dt), status, channel, coupon))

        order_items = []
        for _ in range(weighted([(1, 50), (2, 30), (3, 15), (4, 5)])):
            item_id += 1
            prod = pick_product() + 1
            qty = weighted([(1, 70), (2, 20), (3, 10)])
            disc = weighted([(1.0, 60), (0.9, 20), (0.85, 10), (0.8, 10)])
            row = (item_id, oid, prod, qty, int(round(price_of[prod] * disc)) * 100)
            order_items.append(row)
            items.append(row)
        total_twd = sum(r[3] * r[4] for r in order_items) // 100
        method = weighted([("credit_card", 55), ("line_pay", 20), ("atm", 15), ("cod", 10)])

        def add_payment(pstatus, minutes):
            nonlocal payment_id
            payment_id += 1
            payments.append((payment_id, oid, method, total_twd, fmt(order_dt + timedelta(minutes=minutes)), pstatus))

        if status in (1, 2, 3):
            retries = weighted([(0, 88), (1, 9), (2, 3)])
            for k in range(retries):
                add_payment("failed", 1 + k)
            add_payment("ok", 3 + retries)
        elif random.random() < 0.5:
            add_payment("failed", 2)

        if status in (2, 3):
            shipment_id += 1
            shipped = order_dt + timedelta(days=random.randint(1, 3), hours=random.randint(0, 23))
            delivered = None
            carrier = weighted([("blackcat", 45), ("hct", 25), ("sf", 15), ("post", 15)])
            if status == 3:  # trap: delivery speed differs by carrier
                lo, hi = {"blackcat": (20, 100), "hct": (30, 130), "sf": (15, 80), "post": (40, 170)}[carrier]
                delivered = shipped + timedelta(hours=random.randint(lo, hi))
            shipments.append((shipment_id, oid, carrier, fmt(shipped), fmt(delivered) if delivered else None))

        if status == 3 and random.random() < 0.09:
            for row in random.sample(order_items, min(len(order_items), weighted([(1, 75), (2, 25)]))):
                refund_id += 1
                line_twd = row[3] * row[4] // 100
                amount = line_twd if random.random() > 0.3 else line_twd // 2
                refunds.append((refund_id, oid, row[0], amount,
                                fmt(order_dt + timedelta(days=random.randint(5, 25), hours=random.randint(0, 23))),
                                weighted([("R1", 30), ("R2", 40), ("R3", 15), ("R4", 15)])))

    conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?)", orders)
    conn.executemany("INSERT INTO order_items VALUES (?,?,?,?,?)", items)
    conn.executemany("INSERT INTO payments VALUES (?,?,?,?,?,?)", payments)
    conn.executemany("INSERT INTO refunds VALUES (?,?,?,?,?,?)", refunds)
    conn.executemany("INSERT INTO shipments VALUES (?,?,?,?,?)", shipments)
    conn.commit()
    for table in ("customers", "products", "orders", "order_items", "payments", "refunds", "shipments"):
        print(table, conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()
