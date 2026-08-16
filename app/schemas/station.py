from pydantic import BaseModel


class PoliceStationResponse(BaseModel):
    id: str
    name: str
    address: str
    latitude: float
    longitude: float
    distance_m: int
    phone: str
    open_now: bool = True
    sign_language_officer: bool = False


class StationListResponse(BaseModel):
    stations: list[PoliceStationResponse]
