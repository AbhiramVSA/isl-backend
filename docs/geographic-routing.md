# Geographic routing

`RoutingService` loads active offices and calculates great-circle distance with the Haversine formula. Offices whose configured service radius contains the report are jurisdiction candidates; the nearest candidate wins. If none contains it, the nearest active office is selected. The result records distance and whether the service area matched.

## Travel-time routing

When `GOOGLE_MAPS_SERVER_KEY` is set, the Haversine ranking becomes a shortlist. The nearest `ROUTING_SHORTLIST_SIZE` offices (default 5), plus the Haversine choice if it fell outside them, are sent to the Routes API `computeRouteMatrix` as origins with the report as the destination, using traffic-aware driving times. Among offices with a route, the lowest ETA inside its service radius wins; if none is in area, the lowest ETA overall wins.

The report stores `eta_seconds` and `route_source` (`routes_api` or `haversine`). The `OFFICE_ASSIGNED` history entry also stores `haversine_office_id`, so pilot reports where travel time picked a different office than straight-line distance can be reviewed.

Report creation never depends on Google. A missing key, a timeout (1.5 s with one retry), an API error or a matrix with no routes all fall back to the Haversine choice, recorded as `route_source = haversine`. Only coordinates are sent to Google.

## Location history

Initial coordinates are immutable. Later movement is appended to `report_locations`; it never changes routing history. Latitude and longitude are validated at the API boundary.

Service-radius circles are an intentional prototype approximation. The PostGIS replacement should store real jurisdiction polygons, use `ST_Covers`, then fall back to nearest-office distance.

## Officer route map

The officer report page draws the driving route from the assigned office to the latest point in `report_locations` (or the initial point) with the Maps JavaScript API, and shows the current ETA and the reported accuracy radius. The route comes from `GET /api/v1/officer/reports/{public_id}/route`, which calls Routes `computeRoutes` with the server key. The page refreshes it when the reporter moves, at most every 30 seconds, and otherwise every minute while open.

The console loads Maps JS only when `PUBLIC_GOOGLE_MAPS_BROWSER_KEY` is set. Without it, or if the script fails to load, the page falls back to the MapLibre/OpenStreetMap map. The live map page and the mobile app stay on MapLibre.

## Keys

- `GOOGLE_MAPS_SERVER_KEY` (backend): restrict it by server IP and to the Routes, Geocoding and Places (New) APIs. It never reaches a client.
- `PUBLIC_GOOGLE_MAPS_BROWSER_KEY` (console): restrict it by HTTP referrer to the console domain and to the Maps JavaScript API only.

Set per-API daily quotas and a billing budget alert on the Google Cloud project.
