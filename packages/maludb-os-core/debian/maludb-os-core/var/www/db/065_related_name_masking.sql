-- 065_related_name_masking.sql
-- A record you may see must not name a record you may not.
--
-- Found while verifying the Contacts slice: a member holding the contacts grant but in no
-- department could not open a company filed to HR (correct -- app_can_see() refused it), yet
-- the contacts list still showed "Acme Manufacturing" in the At column, because
-- mcp_contacts.organization_name joins organizations straight through. The same held for
-- mcp_deals. The row rule was right; the borrowed label leaked around it.
--
-- Both views now show a related company's name only when app_can_see() admits the caller to
-- that company as well; otherwise the name reads NULL and the screens print an em dash. The
-- rows each view returns are unchanged -- only the borrowed label is masked -- and the id
-- stays, because a caller who cannot see the company cannot open it either way.

BEGIN;

CREATE OR REPLACE VIEW mcp_contacts WITH (security_barrier = true) AS
SELECT c.id AS contact_id, c.organization_id,
       CASE WHEN app_can_see('contacts', o.owner_member_id, o.department_id,
                             'organization', o.id, o.id)
            THEN o.name END AS organization_name,
       c.first_name,
       c.last_name, c.full_name, c.email::text AS email, c.phone, c.mobile, c.job_title,
       c.is_primary_contact, c.relationship_types, c.owner_member_id,
       cm.display_name AS owner_name, c.department_id, c.source, c.source_campaign_id,
       c.source_content_item_id, c.portal_member_id, c.address, c.notes, c.merged_into_id,
       c.archived_at, c.search_tsv, c.created_by, c.created_at, c.updated_at
FROM contacts c
LEFT JOIN organizations o ON o.id = c.organization_id
LEFT JOIN members cm ON cm.id = c.owner_member_id
WHERE c.anonymized_at IS NULL
  AND app_can_see('contacts', c.owner_member_id, c.department_id, 'contact', c.id, c.organization_id);

CREATE OR REPLACE VIEW mcp_deals WITH (security_barrier = true) AS
SELECT d.id AS deal_id, d.title, d.organization_id,
       CASE WHEN app_can_see('contacts', o.owner_member_id, o.department_id,
                             'organization', o.id, o.id)
            THEN o.name END AS organization_name,
       d.primary_contact_id, d.pipeline_id, d.stage_id, s.name AS stage_name, s.stage_kind,
       d.stage_entered_at, d.value, d.currency,
       COALESCE(d.probability_override, s.probability) AS probability,
       round(d.value * COALESCE(d.probability_override, s.probability) / 100, 2) AS weighted_value,
       d.expected_close_date, d.closed_at, d.lost_reason, d.owner_member_id,
       dm.display_name AS owner_name, d.department_id, d.source, d.source_campaign_id,
       d.source_content_item_id, d.description, d.archived_at, d.search_tsv,
       (SELECT max(i.occurred_at) FROM interactions i WHERE i.deal_id = d.id) AS last_interaction_at,
       d.created_by, d.created_at, d.updated_at
FROM deals d
JOIN deal_stages s ON s.id = d.stage_id
LEFT JOIN organizations o ON o.id = d.organization_id
LEFT JOIN members dm ON dm.id = d.owner_member_id
WHERE NOT app_is_external()
  AND app_can_see('contacts', d.owner_member_id, d.department_id, 'deal', d.id, NULL);

GRANT SELECT ON mcp_contacts, mcp_deals TO app_records_ro, app_rw;

COMMIT;
