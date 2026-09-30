# 200K review dataset schema

Required target:
- 200,000 unique written reviews
- cutoff: 2024-09-29
- walking pad / under-desk treadmill / treadmill products
- source traceability preserved

Columns:
source_platform, source_origin, product_id, product_name, product_url, review_id,
review_date, rating, review_title, review_text, author, verified_purchase,
review_url, scraped_at

Deduplication:
1. stable review_id when present
2. fallback SHA1(product_id + review_date + author + title + text)

Do not count star-only ratings as written reviews.
Do not synthesize or duplicate reviews to hit the target.
