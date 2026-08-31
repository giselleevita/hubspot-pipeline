select distinct from_object_id as deal_id, to_object_id as contact_id
from {{ source('hubspot_raw', 'deals_contacts') }}
