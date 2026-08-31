select distinct from_object_id as contact_id, to_object_id as company_id
from {{ source('hubspot_raw', 'contacts_companies') }}
