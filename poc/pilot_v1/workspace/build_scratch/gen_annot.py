import json
L=lambda q,ids:{"question_id":q,"object_ids":ids}
links=[
 L("C01",["term_net_revenue","term_valid_order","term_order_time","term_item_amount","term_order_attributed_refund","map_net_revenue","map_item_amount_price","map_item_amount_qty","map_order_attributed_refund","map_order_time","con_net_revenue_def","con_valid_order_def","con_amount_unit","con_report_timezone_order","con_order_status_enum","rel_item_amount_net_revenue","rel_refund_net_revenue"]),
 L("C02",["term_avg_order_value","term_valid_order","term_order_time","term_item_amount","map_avg_order_value","map_item_amount_price","con_aov_def","con_valid_order_def","con_amount_unit","con_report_timezone_order","con_grain_orders_items_payments","rel_item_amount_aov","rel_valid_aov"]),
 L("C03",["term_refund_amount","term_refund","term_product_category","map_refund_amount","map_product_category","con_refund_report_attribution","con_product_enum","con_amount_unit","rel_refund_category","rel_item_product","rel_order_refunds"]),
 L("C04",["term_valid_order","term_north_region","term_customer_region","term_customer","term_order_time","map_valid_order","map_north_region","map_customer_region","con_valid_order_def","con_region_enum","con_report_timezone_order","con_customer_attr_snapshot","con_grain_orders_items_payments","rel_customer_orders","rel_region_north"]),
 L("C05",["term_repeat_customer","term_valid_order","term_order_time","map_repeat_customer","con_repeat_customer_def","con_valid_order_def","con_report_timezone_order","rel_valid_repeat"]),
 L("C06",["term_app_order_share","term_app_channel","term_sales_channel","term_valid_order","term_order_time","map_app_order_share","map_app_channel","con_app_share_basis","con_channel_enum","con_valid_order_def","con_report_timezone_order","rel_valid_app_share","rel_app_app_share","rel_channel_app"]),
 L("C07",["term_received_amount","term_payment_method","term_payment","map_received_amount","map_payment_method","con_received_amount_def","con_payment_enum","rel_payment_received","rel_payment_method"]),
 L("C08",["term_net_revenue","term_gold_tier","term_customer_tier","term_valid_order","term_order_time","map_net_revenue","map_gold_tier","map_customer_tier","con_net_revenue_def","con_tier_enum","con_customer_attr_snapshot","con_amount_unit","con_report_timezone_order","rel_tier_gold","rel_customer_orders"]),
 L("C09",["term_refund_amount","term_refund_time","term_refund","map_refund_amount","map_refund_time","con_refund_report_attribution","con_report_timezone_refund","con_amount_unit","rel_refund_amount_variants"]),
 L("C10",["term_sales_quantity","term_active_product","term_product","term_order_item","map_sales_quantity","map_active_product","con_sales_quantity_basis","con_active_product_current","con_product_enum","rel_product_active","rel_item_sales_qty","rel_item_product"]),
]
summary=("Initial ontology (ontology_v0) for the Lumo Outdoors SQLite shop database (customers, orders, order_items, payments, products, refunds). "
"It grounds the business glossary definitions (valid order, item amount, net revenue, average order value, repeat customer, received amount, refund-report amount) in observed columns, "
"records code meanings for status/channel/tier/region/payment/product, the cents-vs-TWD unit difference, the UTC-to-Taipei reporting rule, and the two different refund period attributions. "
"All 10 construction questions (C01-C10) are linked to supporting objects. Structural validation only; no task accuracy is claimed.")
limitations=[
 "UTC storage of order_ts / refund_ts and the Taipei (UTC+8) reporting rule come only from the business glossary; the data (uniform hour-of-day, no zone marker) cannot confirm it.",
 "Sales quantity (銷售數量) is not defined in the glossary; valid-order basis is an assumption (low confidence), though it did not change the top-ranked active product in the construction data.",
 "The basis of '占比' (order count vs amount) is not stated; order-count basis is assumed (medium confidence).",
 "Customer tier and region are current-state values only; historical tier/region at order time is unavailable.",
 "products.is_active is a current flag without history.",
 "Refund reason codes (R1-R4), coupon_code, signup_date and payments.paid_ts are in the data/glossary but not required by the construction workload and are intentionally not modeled.",
 "No equivalence relations were created: no pair of Terms was found that expresses the same concept in different columns without differing semantics.",
]
json.dump({"version":"ontology_v0","summary":summary,"limitations":limitations,"links":links},open('/Users/johnnyhwu/Desktop/EvoOntology/poc/workspace/build_scratch/annot.json','w'),ensure_ascii=False)
