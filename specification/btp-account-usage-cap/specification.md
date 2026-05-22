# Specification: btp-account-usage-cap

> **Guidelines**: Read [guidelines.md](../guidelines.md) and [guidelines-cap.md](../guidelines-cap.md) before executing ANY tasks below. Follow all constraints described there throughout execution.

## Basic Setup

- [ ] Read the project input (`product-requirements-document.md`, `intent.md`)
- [ ] Invoke the `cap-development` skill from `assets/btp-account-usage-cap/` to set up the CAP project structure
- [ ] Install dependencies (`npm install`), validate the project starts (`cds watch`) and responds

## Data Model

- [ ] Define CDS entity `Subaccounts` with fields: `id` (key, UUID), `displayName` (String), `region` (String), `state` (String)
- [ ] Define CDS entity `ServiceUsage` with fields: `id` (key, UUID), `subaccountId` (String), `serviceName` (String), `plan` (String), `consumedQuantity` (Decimal), `unit` (String), `cost` (Decimal), `currency` (String), `measuredAt` (DateTime)
- [ ] Define CDS entity `EntitlementAssignment` with fields: `id` (key, UUID), `subaccountId` (String), `serviceName` (String), `plan` (String), `amount` (Decimal), `remaining` (Decimal), `utilizationPercent` (Decimal)
- [ ] Define CDS entity `ServiceInstance` with fields: `id` (key, UUID), `subaccountId` (String), `name` (String), `serviceName` (String), `plan` (String), `status` (String)
- [ ] Define CDS entity `AlertThreshold` with fields: `id` (key, UUID), `serviceName` (String), `metric` (String), `threshold` (Decimal), `notifyAtPercent` (Integer)
- [ ] Run `cds compile srv/` to validate models compile

## BTP API Integration Layer

The CAP backend integrates with BTP platform APIs via bound service credentials (VCAP_SERVICES). Use the `@sap-cloud-sdk/http-client` or Node.js built-in `fetch` with token retrieval from XSUAA service binding.

- [ ] Create `srv/lib/btpClient.js` — utility module that reads service binding credentials from environment variables and returns an authenticated HTTP client (token fetched from XSUAA `tokenurl`)
- [ ] Create `srv/lib/accountsApi.js` — wrapper for BTP Accounts Service:
  - `getSubaccounts()` → calls `GET /accounts/v1/subaccounts` (api-specs: `accounts-service.json`)
  - `getGlobalAccount()` → calls `GET /accounts/v1/globalAccount`
- [ ] Create `srv/lib/entitlementsApi.js` — wrapper for BTP Entitlements Service:
  - `getGlobalAccountAssignments()` → calls `GET /entitlements/v1/globalAccountAssignments` (api-specs: `entitlements-service.json`)
  - `getSubaccountServicePlans(subaccountGUID)` → calls `GET /entitlements/v1/subaccountServicePlans?subaccountGUID={id}`
- [ ] Create `srv/lib/consumptionApi.js` — wrapper for BTP Consumption/Resource Consumption API:
  - `getMonthlyUsage(subaccountId, month)` → calls the BTP Consumption REST endpoint with proper query parameters; return usage per service and plan
- [ ] Create `srv/lib/serviceManagerApi.js` — wrapper for BTP Service Manager API:
  - `getServiceInstances()` → calls `GET /v1/service_instances` on the Service Manager endpoint
- [ ] All API wrappers must handle errors gracefully and return empty arrays on failure (so UI degrades without crash)

## Service Layer (Custom Handlers)

- [ ] Create `srv/dashboard-service.cds` exposing:
  - `function getSubaccounts() returns array of Subaccounts` — reads from Accounts API
  - `function getServiceUsage(subaccountId: String, month: String) returns array of ServiceUsage` — reads from Consumption API
  - `function getEntitlements() returns array of EntitlementAssignment` — reads from Entitlements API; computes `utilizationPercent = (amount - remaining) / amount * 100`
  - `function getServiceInstances() returns array of ServiceInstance` — reads from Service Manager API
  - `entity AlertThresholds` — standard CRUD (reads/writes to in-memory or SQLite store)
- [ ] Implement `srv/dashboard-service.js` handler:
  - Handler for `getSubaccounts`: call `accountsApi.getSubaccounts()`, map to CDS entity shape
  - Handler for `getServiceUsage`: call `consumptionApi.getMonthlyUsage()`, map to `ServiceUsage` shape
  - Handler for `getEntitlements`: call `entitlementsApi.getGlobalAccountAssignments()`, compute utilization percent, flag assignments with `utilizationPercent >= 80` as `alertStatus: 'warning'`
  - Handler for `getServiceInstances`: call `serviceManagerApi.getServiceInstances()`, map to `ServiceInstance` shape
- [ ] Validate: start `cds watch`, call `GET /odata/v4/dashboard/getSubaccounts()` and confirm a valid response

## Threshold Alert Logic

- [ ] In `srv/dashboard-service.js`, add a computed action `checkThresholds()` that:
  - Reads all `AlertThresholds` from store
  - Fetches current usage via `consumptionApi`
  - Returns a list of breached thresholds (items where `consumedQuantity / threshold >= notifyAtPercent/100`)
- [ ] Expose `function checkThresholds() returns array of { serviceName: String, metric: String, threshold: Decimal, current: Decimal, percentUsed: Decimal }`

## React Frontend (UI)

- [ ] Invoke `cap-development` skill frontend scaffolding to create `assets/btp-account-usage-cap/ui/` as a React app with SAP UI5 Web Components
- [ ] Create route `/` — **Dashboard Overview** page:
  - Summary cards: total subaccounts, total monthly cost, services with >80% entitlement usage, active threshold breaches
  - Bar chart: top 10 services by monthly cost
- [ ] Create route `/subaccounts` — **Subaccounts** page:
  - Table listing all subaccounts (name, region, state)
  - Clicking a subaccount navigates to `/subaccounts/:id/usage`
- [ ] Create route `/subaccounts/:id/usage` — **Subaccount Usage Detail** page:
  - Table of services with consumed quantity, unit, cost, and currency for the selected subaccount
  - Month picker to change the reporting period
- [ ] Create route `/entitlements` — **Entitlements** page:
  - Table with columns: Service, Plan, Total Quota, Used, Remaining, Utilization %
  - Rows with utilization >= 80% highlighted in orange/red
- [ ] Create route `/instances` — **Service Instances** page:
  - Table listing all service instances across subaccounts with status badges
- [ ] Create route `/alerts` — **Alert Thresholds** page:
  - Table of configured thresholds with edit/delete actions
  - Form to create a new threshold (service name, metric, threshold value, notify-at percent)
  - Section showing currently breached thresholds (calls `checkThresholds()`)
- [ ] Add navigation sidebar or top nav with links to all routes
- [ ] All pages must call the CAP service endpoints (not the BTP APIs directly)
- [ ] Run `cds watch` and verify UI loads correctly in browser

## Testing

- [ ] Write tests for `getEntitlements` handler: verify `utilizationPercent` is computed correctly and `alertStatus: 'warning'` is set when >= 80%
- [ ] Write tests for `checkThresholds` action: given mock usage and thresholds, verify correct breach detection
- [ ] Run tests and confirm they pass

## Final Validation

- [ ] Run `cds compile srv/` — no errors
- [ ] Run `cds watch` and manually test all UI routes
- [ ] Confirm all 5 dashboard sections (Overview, Subaccounts, Entitlements, Instances, Alerts) are accessible and render data (mock or real)
