/**
 * The name a published record is shown under.
 *
 * A file rarely calls the column "name": a supplier file has "supplier_name",
 * a product file "product_name". Pages that looked only for "name" fell back
 * to the identifier, so a table showed "S-100" twice and never "Acme Metals
 * GmbH". The fields below are tried in order; they are the same ones the
 * backend reads a record's name from (NAME_FIELDS in workspace_facts.py).
 */
export const NAME_ATTRIBUTES = [
  "name",
  "supplier_name",
  "vendor_name",
  "legal_name",
  "company_name",
  "seller_name",
  "customer_name",
  "client_name",
  "carrier_name",
  "facility_name",
  "warehouse_name",
  "plant_name",
  "site_name",
  "dc_name",
  "port_name",
  "product_name",
  "item_name",
  "material_name",
  "route_name",
  "region_name",
  "demand_region_name",
  "title",
  "description",
  "product_description",
  "item_description",
] as const;

/** The record's own name, or `fallback` (usually its identifier) when it has none. */
export function recordName(
  attributes: Record<string, unknown> | null | undefined,
  fallback: string,
): string {
  for (const key of NAME_ATTRIBUTES) {
    const value = attributes?.[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return fallback;
}
