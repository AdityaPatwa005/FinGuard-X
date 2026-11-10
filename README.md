# FinGuard X

A financial cybersecurity intelligence and investigation platform.

## Project Components

- FinGuard X: Fraud detection, behavioral analytics, AML intelligence, threat detection, investigations, and response.
- FinBank Simulator: A synthetic banking environment for generating simulated transactions and security events.

## Development Status

## Geospatial Intelligence (synthetic demonstration)

The Geospatial Intelligence page uses a separate `geospatial_events` table. The records reference existing completed simulator transactions and accounts, and may reference an incident only when persisted triggered evaluations already associate that incident with the transaction. They do not represent real customer/device location, GPS, real banking activity, confirmed fraud, or a person's physical route. The generator uses documented demo city-centre coordinates in India and tags every generated row as synthetic.

### Map tiles and attribution

The frontend uses MapLibre GL JS with OpenFreeMap's public Liberty style at `https://tiles.openfreemap.org/styles/liberty`. OpenFreeMap's quick start documents this style URL and its example uses it directly without a key parameter. Its Terms provide the service as-is with no availability warranty; do not bulk-download tiles (offline use is limited by its published terms). MapLibre's attribution control displays credits supplied by the style, and the page also shows `© OpenMapTiles · Data © OpenStreetMap contributors · Style/tiles: OpenFreeMap`. The style URL can be overridden with `VITE_MAP_STYLE_URL`; setting it to `none` intentionally disables the basemap while keeping the event list available. Current references: [OpenFreeMap Quick Start](https://openfreemap.org/quick_start/), [OpenFreeMap Terms](https://openfreemap.org/tos/), [MapLibre attribution control](https://maplibre.org/maplibre-gl-js/docs/API/classes/AttributionControl/) and the [MapLibre GL JS documentation](https://maplibre.org/maplibre-gl-js/docs/).

The generator's fixed demo city-centre coordinate set is: Mumbai (19.076000, 72.877700), Delhi (28.613900, 77.209000), Bengaluru (12.971600, 77.594600), Chennai (13.082700, 80.270700), Hyderabad (17.385000, 78.486700), Kolkata (22.572600, 88.363900), Pune (18.520400, 73.856700), and Ahmedabad (23.022500, 72.571400). These points are repeatable illustrative coordinates, never collected customer positions.

### Local setup

1. Configure `backend/.env` as already required by the backend (`DATABASE_URL` must point at the intended local development database).
2. In `frontend/`, copy `.env.example` to `.env.local`; set `VITE_API_BASE_URL` to the local FastAPI URL and, optionally, `VITE_MAP_STYLE_URL` to a compatible MapLibre style.
3. From `backend/`, apply the additive geospatial migration with `alembic upgrade head` after reviewing the migration. It creates only `geospatial_events`; it does not alter transactions, balances, ledgers, or incidents.
4. From `backend/`, preview generated rows with `python -m scripts.generate_synthetic_geospatial_events --dry-run`; populate with `python -m scripts.generate_synthetic_geospatial_events`. The script reads completed transactions only and uses deterministic UUIDs and keys, so reruns are idempotent. It writes only synthetic geospatial event rows.
5. Start the API from `backend/` with `uvicorn main:app --reload`. Start the frontend from `frontend/` with `npm run dev`.

### Geospatial API

- `GET /geospatial/events`: bounded location event list; filters include `event_type`, incident `risk_band`, `incident_id`, `start_at`, `end_at`, `limit` and `offset`.
- `GET /geospatial/routes`: bounded route records joined to explicitly referenced origin and beneficiary location events and existing transaction status/amount; filters include incident risk, incident ID and time range.

Results are capped at 500 rows per request. Incident risk is returned only where a persisted incident relationship exists. The route is a financial transaction connection between synthetic coordinates, not a physical journey. No browser location or real-time GPS is collected. If there are no completed transactions, the generator correctly produces no map records.
