select
    customer_id,
    customer_name,
    country_code
from {{ ref('stg_customer') }}
