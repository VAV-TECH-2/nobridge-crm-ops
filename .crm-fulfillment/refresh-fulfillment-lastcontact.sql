-- Daily refresh of fulfillment "Last Contact" (date) + "Days Since Contact" (number),
-- computed as the company-wide last email touch for each fulfillment's point of contact
-- (or anyone at the same company). Mirrors /home/azureuser/refresh-last-contacted.sql (buy-side).
UPDATE workspace_4cukon3ltvwq3m1goqws3p4lv."_fulfillment" f
SET "lastContact" = lc.last,
    "daysSinceContact" = CASE WHEN lc.last IS NULL THEN NULL ELSE (CURRENT_DATE - lc.last) END
FROM (
  SELECT f2.id, MAX(m."receivedAt")::date AS last
  FROM workspace_4cukon3ltvwq3m1goqws3p4lv."_fulfillment" f2
  LEFT JOIN workspace_4cukon3ltvwq3m1goqws3p4lv."person" p
    ON (p.id = f2."pointOfContactId" OR p."companyId" = f2."companyId")
  LEFT JOIN workspace_4cukon3ltvwq3m1goqws3p4lv."messageParticipant" mp
    ON LOWER(mp.handle) = LOWER(p."emailsPrimaryEmail")
  LEFT JOIN workspace_4cukon3ltvwq3m1goqws3p4lv."message" m ON m.id = mp."messageId"
  GROUP BY f2.id
) lc
WHERE lc.id = f.id;
