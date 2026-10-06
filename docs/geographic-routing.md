# Geographic routing

`RoutingService` loads active offices and calculates great-circle distance with the Haversine formula. Offices whose configured service radius contains the report are jurisdiction candidates; the nearest candidate wins. If none contains it, the nearest active office is selected. The result records distance and whether the service area matched.

Initial coordinates are immutable. Later movement is appended to `report_locations`; it never changes routing history. Latitude and longitude are validated at the API boundary.

Service-radius circles are an intentional prototype approximation. The PostGIS replacement should store real jurisdiction polygons, use `ST_Covers`, then fall back to nearest-office distance.

