"""The Equal mobile app's API.

Mounted under `/app`, away from the endpoints this service already serves, so
the two never collide: `POST /reports`, `GET /reports/{public_id}` and
`GET /auth/me` all exist here under different shapes, and the console's clients
must keep seeing theirs. The app's base address is configured at runtime, so
pointing it at `https://host/app` needs no change to the app itself.

Everything here reads and writes the same `reports` table the console works
from. What differs is the dialect — see `app/services/mobile_reports.py`.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.security import create_token, hash_password, verify_password
from app.db import get_db
from app.dependencies import Principal, require_user
from app.models import (
    Account,
    AccountStatus,
    AuditLog,
    Office,
    Report,
    ReportHistory,
    Role,
    User,
)
from app.schemas_mobile import (
    HealthResponse,
    LoginRequest,
    LoginResponse,
    MobileUser,
    PredictionResponse,
    RegisterRequest,
    ReportListResponse,
    ReportResponse,
    ReportSubmission,
    StationListResponse,
    StationResponse,
)
from app.services.mobile_reports import (
    PRIORITY_BY_SEVERITY,
    new_reference_code,
    to_app_report,
)
from app.services.realtime import realtime_hub
from app.services.routing_service import haversine_km, routing_service
from app.services.stream_media import link_stream
from app.services.transcription import model_ready, transcribe_video

router = APIRouter(tags=["Equal mobile app"])

VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".webm"}


def display_name_from(identifier: str) -> str:
    """Turns "priya.n@mail.com" or "+91 98765 43210" into something addressable."""
    local = identifier.strip().split("@")[0]
    words = [
        word for word in local.replace("_", " ").replace(".", " ").replace("-", " ").split() if word
    ]
    if not words or not any(character.isalpha() for word in words for character in word):
        return f"Caller {local[-4:]}" if len(local) >= 4 else "Caller"
    return " ".join(word.capitalize() for word in words)


# --- readiness --------------------------------------------------------------


@router.get("/health", summary="Whether signing will work at all")
async def health() -> HealthResponse:
    """The app's pre-flight check, shown on the home screen.

    Reports whether the transcription model can run, not merely whether this
    service is up — it is the only warning a caller gets before they start
    signing at a camera.
    """
    ready = model_ready()
    return HealthResponse(
        status="ok",
        model_loaded=ready,
        model_error=None if ready else "The sign transcription model is not installed.",
    )


# --- recognition ------------------------------------------------------------


@router.post("/api/v1/predict", response_model=PredictionResponse, summary="Recognise one clip")
async def predict(file: UploadFile = File(...)) -> PredictionResponse:
    """One short clip in, one recognised word out.

    An adapter over the same transcriber the console uses. That one answers with
    a word-timed transcript; the app treats a response as a single sign and
    stitches multi-word messages itself from several clips, so this returns the
    strongest word rather than the joined transcript — sending the whole string
    would make the app count one clip twice.

    Unauthenticated, because the app records before anyone signs in and a person
    in trouble should not meet a login screen first. The service-wide rate limit
    is what stands between that and an open door to a subprocess.
    """
    suffix = Path(file.filename or "clip.mp4").suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        # Matches the app's own error handling: it distinguishes an unreadable
        # recording from an offline model, and says something different for each.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That recording couldn't be read. Please record again.",
        )

    temp_path: Path | None = None
    total = 0
    try:
        with NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            temp_path = Path(temporary.name)
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="The signing clip is too large.",
                    )
                temporary.write(chunk)
        if total == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="That recording came out empty. Please record again.",
            )

        result = await transcribe_video(temp_path)
        words = result.get("words") or []
        if not words:
            # A clip the model could not read anything from. "Unknown" is a word
            # the app already handles; an error would lose the caller's clip.
            return PredictionResponse(label="Unknown", confidence=0.0)
        best = max(words, key=lambda word: word.get("confidence", 0.0))
        return PredictionResponse(
            label=best.get("word", "Unknown"),
            confidence=best.get("confidence"),
        )
    finally:
        await file.close()
        if temp_path:
            temp_path.unlink(missing_ok=True)


# --- accounts ---------------------------------------------------------------


def normalize_identifier(identifier: str) -> str:
    """One spelling per person, so the same details always reach the same account.

    Emails are case-insensitive in practice; phone numbers arrive with whatever
    spacing and punctuation the keyboard offered. Anything else (a
    disability-services ID) is kept as typed, trimmed.
    """
    value = identifier.strip()
    if "@" in value:
        return value.lower()
    compact = re.sub(r"[\s().-]", "", value)
    if re.fullmatch(r"\+?\d{6,15}", compact):
        return compact
    return value


async def _account_for(db: AsyncSession, identifier: str) -> Account | None:
    """Looks the identifier up normalised, then as typed.

    Accounts made before identifiers were normalised were stored verbatim; the
    second lookup keeps their owners from finding an empty account.
    """
    normalized = normalize_identifier(identifier)
    account = await db.scalar(select(Account).where(Account.email == normalized))
    if account is None and normalized != identifier.strip():
        account = await db.scalar(select(Account).where(Account.email == identifier.strip()))
    return account


def _require_identifier(identifier: str) -> str:
    if not identifier.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Enter a phone number, email, or ID to continue.",
        )
    return normalize_identifier(identifier)


def _signed_in(account: Account, profile: User, identifier: str) -> LoginResponse:
    # Deliberately long-lived. The console rotates a 15-minute token against a
    # refresh endpoint; the app holds one token and has no refresh flow, and
    # being signed out mid-emergency is not a failure worth designing in.
    lifetime = timedelta(days=settings.mobile_access_token_days)
    token, _ = create_token(account.id, Role.USER, "access", lifetime)
    return LoginResponse(
        user=MobileUser(
            id=f"usr_{profile.id}",
            display_name=profile.name,
            identifier=identifier,
        ),
        access_token=token,
        expires_at=datetime.now(UTC) + lifetime,
    )


REJECTED = "Those sign-in details weren't accepted."


@router.post(
    "/api/v1/auth/register",
    response_model=LoginResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account from the app",
)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    """Creates a caller's account and signs them in.

    The account is what ties reports to a person rather than to a phone: sign in
    with the same identifier and passcode anywhere and the same reports come back.

    ⚠️ The identifier is still not verified (no OTP), so it is a username, not
    proof of identity. The passcode is what protects the account.

    Accounts created before passcodes were required were hashed against the
    identifier itself; registering on one of those claims it, so its owner keeps
    their history instead of meeting "already taken".
    """
    identifier = _require_identifier(payload.identifier)
    account = await _account_for(db, payload.identifier)

    if account is not None:
        legacy = account.role == Role.USER and verify_password(account.email, account.password_hash)
        if not legacy:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account already exists for those details. Sign in instead.",
            )
        if account.status != AccountStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account has been suspended. Call 112 in an emergency.",
            )
        account.password_hash = hash_password(payload.passcode)
        profile = await db.scalar(select(User).where(User.account_id == account.id))
        if profile is None:
            profile = User(account_id=account.id, name=display_name_from(account.email))
            db.add(profile)
        if payload.display_name.strip():
            profile.name = payload.display_name.strip()
        identifier = account.email
    else:
        account = Account(
            email=identifier,
            password_hash=hash_password(payload.passcode),
            role=Role.USER,
            status=AccountStatus.ACTIVE,
        )
        db.add(account)
        await db.flush()
        profile = User(
            account_id=account.id,
            name=payload.display_name.strip() or display_name_from(identifier),
            phone=identifier if "@" not in identifier else None,
        )
        db.add(profile)

    await db.flush()
    account.last_login_at = datetime.now(UTC)
    db.add(
        AuditLog(
            actor_type="USER",
            actor_id=account.id,
            action="APP_ACCOUNT_REGISTERED",
            target_type="ACCOUNT",
            target_id=str(account.id),
        )
    )
    await db.commit()
    return _signed_in(account, profile, identifier)


@router.post("/api/v1/auth/login", response_model=LoginResponse, summary="Sign in from the app")
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    """Signs a caller in to an account made with `/auth/register`.

    The same answer for an unknown identifier and a wrong passcode, so this
    cannot be used to find out who has an account.
    """
    _require_identifier(payload.identifier)
    if not payload.passcode:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Enter your passcode to continue.",
        )

    account = await _account_for(db, payload.identifier)
    # An officer account signing in through the app would get a token the
    # console's own endpoints would then honour, so only USER accounts qualify.
    if (
        account is None
        or account.role != Role.USER
        or not verify_password(payload.passcode, account.password_hash)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=REJECTED)
    if account.status != AccountStatus.ACTIVE:
        # Blocked from the console's Reporters page.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been suspended. Call 112 in an emergency.",
        )

    profile = await db.scalar(select(User).where(User.account_id == account.id))
    if profile is None:
        profile = User(account_id=account.id, name=display_name_from(account.email))
        db.add(profile)
        await db.flush()

    account.last_login_at = datetime.now(UTC)
    await db.commit()
    return _signed_in(account, profile, account.email)


@router.get("/api/v1/auth/me", response_model=MobileUser, summary="Check a stored token")
async def me(principal: Principal = Depends(require_user)) -> MobileUser:
    """Lets the app check a stored token is still good before trusting it."""
    return MobileUser(
        id=f"usr_{principal.user.id}",  # type: ignore[union-attr]
        display_name=principal.user.name,  # type: ignore[union-attr]
        identifier=principal.account.email,
    )


# --- reports ----------------------------------------------------------------


# Office and officer names ride along on every report the caller reads, and the
# async session cannot lazy-load them.
WITH_NAMES = select(Report).options(
    selectinload(Report.office), selectinload(Report.assigned_officer)
)


async def _find(db: AsyncSession, report_id: str, user_id: int) -> Report:
    """Accepts either the reference code or the `rpt_<id>` the app was handed."""
    report = None
    if report_id.startswith("rpt_") and report_id[4:].isdigit():
        report = await db.scalar(WITH_NAMES.where(Report.id == int(report_id[4:])))
    if report is None:
        report = await db.scalar(WITH_NAMES.where(Report.reference_code == report_id))
    # The same answer whether it does not exist or belongs to someone else —
    # otherwise this says which report ids are real.
    if report is None or report.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    return report


@router.post(
    "/api/v1/reports",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Store a report the app wrote",
)
async def submit_report(
    payload: ReportSubmission,
    response: Response,
    principal: Principal = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    """Turns a document on someone's phone into a dispatchable incident.

    Not a generation endpoint — the prose arrives finished from the device. What
    happens here is validation, routing to a responsible office, persistence,
    and assigning what the client is not allowed to decide: the id, the
    reference code, and the status.

    Resubmitting the same `client_id` returns the existing record with 200
    rather than filing twice. A caller retrying over a bad connection must not
    end up with two incidents.
    """
    user_id = principal.user.id  # type: ignore[union-attr]

    existing = await db.scalar(
        WITH_NAMES.where(Report.user_id == user_id, Report.client_id == payload.client_id)
    )
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return to_app_report(existing)

    # A caller who withheld their location still has to reach someone, so the
    # report is routed from the office's own position rather than refused.
    latitude = payload.latitude
    longitude = payload.longitude
    if latitude is None or longitude is None:
        first_office = await db.scalar(select(Office).where(Office.active.is_(True)))
        if first_office is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No response office is currently available",
            )
        latitude, longitude = first_office.latitude, first_office.longitude

    try:
        route = await routing_service.route(db, latitude, longitude)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No response office is currently available",
        ) from exc

    created_at = payload.created_at
    report = Report(
        user_id=user_id,
        office_id=route.office.id,
        category=payload.category,
        description=payload.summary,
        priority=PRIORITY_BY_SEVERITY[payload.severity],
        initial_latitude=latitude,
        initial_longitude=longitude,
        created_at=created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC),
        reference_code=new_reference_code(),
        client_id=payload.client_id,
        title=payload.title,
        severity=payload.severity,
        situation_analysis=payload.situation_analysis,
        recommended_actions=payload.recommended_actions,
        transcript=payload.transcript,
        labels=payload.labels,
        duration_ms=payload.duration_ms,
        location_label=payload.location_label,
        reporter_name=payload.reporter_name or principal.user.name,  # type: ignore[union-attr]
        source=payload.source,
        generated_by=payload.generated_by,
    )
    db.add(report)
    await db.flush()

    db.add_all(
        [
            ReportHistory(
                report_id=report.id,
                actor_type="USER",
                actor_id=user_id,
                event="REPORT_CREATED",
                new_status=report.status.value,
                event_metadata={"source": payload.source, "generated_by": payload.generated_by},
            ),
            ReportHistory(
                report_id=report.id,
                actor_type="SYSTEM",
                actor_id=None,
                event="OFFICE_ASSIGNED",
                new_status=report.status.value,
                event_metadata={
                    "distance_km": round(route.distance_km, 3),
                    "matched_service_area": route.matched_service_area,
                },
            ),
            AuditLog(
                actor_type="USER",
                actor_id=principal.account.id,
                action="REPORT_CREATED",
                target_type="REPORT",
                target_id=report.public_id,
            ),
        ]
    )
    await link_stream(db, report, payload.stream_id, payload.stream_token)
    await db.commit()
    await db.refresh(report)
    await db.refresh(report, ["office", "assigned_officer"])

    # The console is listening; this is what puts the report on a screen someone
    # is actually watching.
    await realtime_hub.office_event(
        report.office_id, {"type": "report.created", "report_id": report.public_id}
    )
    return to_app_report(report)


@router.get("/api/v1/reports", response_model=ReportListResponse, summary="This caller's reports")
async def list_reports(
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> ReportListResponse:
    result = await db.scalars(
        WITH_NAMES.where(Report.user_id == principal.user.id)  # type: ignore[union-attr]
        .order_by(Report.created_at.desc())
        .limit(limit)
    )
    return ReportListResponse(reports=[to_app_report(report) for report in result.all()])


@router.get("/api/v1/reports/{report_id}", response_model=ReportResponse, summary="One report")
async def get_report(
    report_id: str,
    principal: Principal = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    """How the caller watches an officer pick their report up."""
    report = await _find(db, report_id, principal.user.id)  # type: ignore[union-attr]
    return to_app_report(report)


# --- stations ---------------------------------------------------------------


@router.get(
    "/api/v1/stations/nearby",
    response_model=StationListResponse,
    summary="Response offices around a point",
)
async def nearby_stations(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    limit: int = Query(default=20, ge=1, le=100),
    _principal: Principal = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> StationListResponse:
    """The same offices reports are routed to, as the app's map draws them.

    `distance_m` is straight-line; the app displays it and computes nothing.
    No phone number is carried on an office, and a wrong number on an emergency
    screen is worse than none, so it is sent empty rather than invented.
    """
    offices = (await db.scalars(select(Office).where(Office.active.is_(True)))).all()
    ranked = sorted(
        ((office, haversine_km(lat, lon, office.latitude, office.longitude)) for office in offices),
        key=lambda item: item[1],
    )
    return StationListResponse(
        stations=[
            StationResponse(
                id=str(office.id),
                name=office.name,
                address=office.address,
                latitude=office.latitude,
                longitude=office.longitude,
                distance_m=int(distance * 1000),
                phone="",
                open_now=True,
                # No office records whether an ISL-trained officer is on duty.
                # False hides the badge; inventing it would tell a Deaf caller
                # they will be understood when nobody has said so.
                sign_language_officer=False,
            )
            for office, distance in ranked[:limit]
        ]
    )


# --- language model ---------------------------------------------------------


@router.post("/api/v1/llm/chat", summary="Proxy a chat completion to NVIDIA NIM")
async def llm_chat(
    payload: dict,
    _principal: Principal = Depends(require_user),
) -> dict:
    """Holds the NIM key server-side so it stops shipping inside the app binary.

    A thin pass-through, deliberately OpenAI-shaped: moving the app onto it is a
    base-URL change and nothing else. Without a key configured this answers 503
    and the app keeps calling NIM directly, which is the state it ships in.
    """
    if not settings.nvidia_nim_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The language model proxy is not configured.",
        )
    payload.setdefault("model", settings.nim_default_model)
    async with httpx.AsyncClient(timeout=settings.nim_timeout_seconds) as client:
        try:
            response = await client.post(
                f"{settings.nim_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.nvidia_nim_api_key}"},
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The language model could not be reached.",
            ) from exc
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail="The language model rejected the request.",
        )
    return response.json()
