# 資料剖析（程式自動產生，非 LLM）

## customers（5000 列）
- `customer_id`: INTEGER；distinct=5000；唯一；範圍 1 ~ 5000
- `name`: TEXT；distinct=380；範圍 劉佩珊 ~ 黃雅婷
- `email`: TEXT；distinct=5000；唯一；範圍 u00001@example.com ~ u05000@example.com
- `region_code`: TEXT；distinct=5；值: TW-N(1985), TW-C(1289), TW-S(987), JP(501), SG(238)
- `signup_date`: TEXT；distinct=1087；範圍 2023-01-01 ~ 2025-12-31
- `tier`: TEXT；distinct=3；值: B(3539), S(970), G(491)

## order_items（104966 列）
- `item_id`: INTEGER；distinct=104966；唯一；範圍 1 ~ 104966
- `order_id`: INTEGER；distinct=60000；範圍 1 ~ 60000
- `product_id`: INTEGER；distinct=200；範圍 1 ~ 200
- `quantity`: INTEGER；distinct=3；值: 1(73448), 2(20997), 3(10521)
- `unit_price_cents`: INTEGER；distinct=297；範圍 16000 ~ 1490000

## orders（60000 列）
- `order_id`: INTEGER；distinct=60000；唯一；範圍 1 ~ 60000
- `customer_id`: INTEGER；distinct=4634；範圍 1 ~ 5000
- `order_ts`: TEXT；distinct=59943；範圍 2024-12-30 00:03:20 ~ 2025-12-31 23:53:02；若為 UTC 並換算 UTC+8，有 655 列會換月
- `status`: INTEGER；distinct=5；值: 3(39574), 9(9004), 2(4870), 1(3549), 0(3003)
- `channel`: TEXT；distinct=3；值: web(30071), app(20970), store(8959)
- `coupon_code`: TEXT；distinct=2；null=41966；值: None(41966), SUMMER15(9204), WELCOME10(8830)

## payments（61319 列）
- `payment_id`: INTEGER；distinct=61319；唯一；範圍 1 ~ 61319
- `order_id`: INTEGER；distinct=53976；範圍 1 ~ 60000
- `method`: TEXT；distinct=4；值: credit_card(33881), line_pay(11973), atm(9320), cod(6145)
- `amount_twd`: INTEGER；distinct=5141；範圍 160 ~ 87030
- `paid_ts`: TEXT；distinct=61265；範圍 2024-12-30 00:06:20 ~ 2025-12-31 23:56:02；若為 UTC 並換算 UTC+8，有 699 列會換月
- `payment_status`: TEXT；distinct=2；值: ok(47993), failed(13326)

## products（200 列）
- `product_id`: INTEGER；distinct=200；唯一；範圍 1 ~ 200
- `sku`: TEXT；distinct=200；唯一；範圍 LUMO-AC-001 ~ LUMO-TN-040
- `product_name`: TEXT；distinct=200；唯一；範圍 岩峰 帳篷1 ~ 鷹眼 配件2
- `category`: TEXT；distinct=5；值: tent(40), shoes(40), backpack(40), apparel(40), accessory(40)
- `list_price_twd`: INTEGER；distinct=84；範圍 200 ~ 14900
- `is_active`: INTEGER；distinct=2；值: 1(165), 0(35)

## refunds（4039 列）
- `refund_id`: INTEGER；distinct=4039；唯一；範圍 1 ~ 4039
- `order_id`: INTEGER；distinct=3584；範圍 23 ~ 59999
- `item_id`: INTEGER；distinct=4039；唯一；範圍 41 ~ 104964
- `refund_amount_twd`: INTEGER；distinct=521；範圍 80 ~ 44700
- `refund_ts`: TEXT；distinct=4038；範圍 2025-01-05 19:07:25 ~ 2026-01-23 13:45:30；若為 UTC 並換算 UTC+8，有 57 列會換月
- `reason_code`: TEXT；distinct=4；值: R2(1621), R1(1194), R3(619), R4(605)

## shipments（44444 列）
- `shipment_id`: INTEGER；distinct=44444；唯一；範圍 1 ~ 44444
- `order_id`: INTEGER；distinct=44444；唯一；範圍 1 ~ 60000
- `carrier`: TEXT；distinct=4；值: blackcat(19911), hct(11092), sf(6806), post(6635)
- `shipped_ts`: TEXT；distinct=44403；範圍 2024-12-31 04:11:32 ~ 2026-01-04 17:53:02；若為 UTC 並換算 UTC+8，有 516 列會換月
- `delivered_ts`: TEXT；distinct=39547；null=4870；範圍 2025-01-01 06:58:33 ~ 2026-01-10 06:08:37；若為 UTC 並換算 UTC+8，有 423 列會換月

## 可能的關聯（欄位同名且對方唯一；資料庫沒有宣告外鍵）
- order_items.item_id → refunds.item_id（孤兒 100927 / 104966）
- order_items.order_id → orders.order_id（孤兒 0 / 104966）
- order_items.order_id → shipments.order_id（孤兒 27337 / 104966）
- order_items.product_id → products.product_id（孤兒 0 / 104966）
- orders.order_id → shipments.order_id（孤兒 15556 / 60000）
- orders.customer_id → customers.customer_id（孤兒 0 / 60000）
- payments.order_id → orders.order_id（孤兒 0 / 61319）
- payments.order_id → shipments.order_id（孤兒 10066 / 61319）
- refunds.order_id → orders.order_id（孤兒 0 / 4039）
- refunds.order_id → shipments.order_id（孤兒 0 / 4039）
- refunds.item_id → order_items.item_id（孤兒 0 / 4039）
- shipments.order_id → orders.order_id（孤兒 0 / 44444）