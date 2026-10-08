# Geographic routing

`RoutingService` loads active offices and calculates great-circle distance with the Haversine formula. Offices whose configured service radius contains the report are jurisdiction candidates; the nearest candidate wins. If none contains it, the nearest active office is selected. The result records distance and whether the service area matched.

## Travel-time routing

When `GOOGLE_MAPS_SERVER_KEY` is set, the Haversine ranking becomes a shortlist. The nearest `ROUTING_SHORTLIST_SIZE` offices (default 5), plus the Haversine choice if it fell outside them, are sent to the Routes API `computeRouteMatrix` as origins with the report as the destination, using traffic-aware driving times. Among offices with a route, the lowest ETA inside its service radius wins; if none is in area, the lowest ETA overall wins.

The report stores `eta_seconds` and `route_source` (`routes_api` or `haversine`). The `OFFICE_ASSIGNED` history entry also stores `haversine_office_id`, so pilot reports where travel time picked a different office than straight-line distance can be reviewed.

Report creation never depends on Google. A missing key, a timeout (1.5 s with one retry), an API error or a matrix with no routes all fall back to the Haversine choice, recorded as `route_source = haversine`. Only coordinates are sent to Google.

## Location history

Initial coordinates are immutable. Later movement is appended to `report_locations`; it never changes routing history. Latitude and longitude are validated at the API boundary.

Service-radius circles are an intentional prototype approximation. The PostGIS replacement should store real jurisdiction polygons, use `ST_Covers`, then fall back to nearest-office distance.
