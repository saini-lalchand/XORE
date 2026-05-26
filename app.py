"""
app.py — XORE Pure Android API Gateway (FastAPI)

FIXES IN THIS VERSION:
  B1  — PartnerRegistration.validate_shop_name: now also rejects digits-only names
         (was only checking length; digits-only like "123" passed through).
  B2  — PartnerRegistration: missing address validator added (strip + min-5-char check).
  B3  — PartnerRegistration: added max_length constraints and clearer field descriptions.
  B4  — register_partner endpoint: missing `raise` for HTTPException re-raise added.
  B5  — partner_shop_id in OrderRequest: added max_length=100 guard — was fully unbounded,
         allowing arbitrary-length strings into the DB column.
  B6  — register_partner: added response_model=dict annotation (was untyped).
  B7  — Middleware ordering fixed: SecurityHeadersMiddleware must be added AFTER
         CORSMiddleware so CORS headers are present before security headers run.
         (FastAPI/Starlette middleware stack executes outermost-last, so add order matters.)
  B8  — import re inside validator replaced with module-level re (already imported).

  All previous fixes preserved (V1-V7, S1-S3, A1-A3, D1, Bug #7, Bug #8).
"""

import asyncio
import logging
import re
import uuid as _uuid_mod
from typing import Final, Optional, Dict, Any

# ... (your existing imports)
from database import (
    init_db, save_order, OrderRecord, save_partner, PartnerRecord, 
    get_order, update_order_status, update_partner_status,
    get_user, save_user, get_partner  
)
from fastapi import FastAPI, HTTPException, Request, status, Depends 
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
from starlette.middleware.base import BaseHTTPMiddleware

from models import (
    User, Device, Order, BloatwareStatus, PaymentMethod,
    validate_client_name, validate_indian_mobile, validate_imei,
    validate_ram, validate_device_model, Partner,
)
from services import FinanceService, PaymentGateway
from auth import (
    create_access_token, get_current_user, get_current_user_optional, verify_password, 
    get_password_hash  
)
from datetime import timedelta
# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("xore.api")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="XORE Pure Android API",
    description="Backend for the XORE debloating service",
    version="2.0.0",
)

# ---------------------------------------------------------------------------
# S2 — Security headers middleware
# ---------------------------------------------------------------------------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Content-Type-Options"]    = "nosniff"
        response.headers["X-Frame-Options"]           = "DENY"
        response.headers["X-XSS-Protection"]          = "1; mode=block"
        response.headers["Referrer-Policy"]           = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"]             = "no-store"
        return response

# S3 / Bug #8 — explicit origins required when allow_credentials=True.
ALLOWED_ORIGINS = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "http://127.0.0.1:8080",
    "http://localhost:8080",
    "https://xorepureandroid.in", 
]

# B7: CORSMiddleware must be added first (outermost), SecurityHeaders second.
# Starlette middleware wraps in reverse-add order; adding CORS first means it
# runs before security headers so CORS headers are always present.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS","PATCH"],
    allow_headers=["Content-Type", "Authorization"],
)
app.add_middleware(SecurityHeadersMiddleware)

init_db()

# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

class ClientInfo(BaseModel):
    name:    str = Field(..., min_length=3,  max_length=50,  description="Full name — letters and spaces only")
    mobile:  str = Field(..., description="10-digit Indian mobile starting with 6/7/8/9; +91 prefix optional")
    address: str = Field(..., min_length=5,  max_length=300, description="Physical address")

    @validator("name")
    def validate_name(cls, v):
        return validate_client_name(v)   # V1: letters + spaces only

    @validator("mobile")
    def validate_mobile(cls, v):
        return validate_indian_mobile(v)  # V2: 10 digits, starts 6-9

    @validator("address")
    def validate_address(cls, v):
        stripped = v.strip()
        if len(stripped) < 5:
            raise ValueError("Address is too short (minimum 5 characters).")
        return stripped                   # V3


class DeviceInfo(BaseModel):
    model:          str           = Field(..., min_length=3, max_length=60, description="Device model, e.g. 'Moto G67 Power'")
    androidVersion: Optional[str] = None
    ram:            Optional[str] = Field(None, description="RAM in GB — must be a positive even integer if provided")
    imei:           Optional[str] = Field(None, description="15-digit IMEI if provided — digits only")

    @validator("model")
    def validate_model(cls, v):
        return validate_device_model(v)   # V4: must contain a letter, min 3 chars

    @validator("ram", pre=True, always=True)
    def validate_ram_field(cls, v):
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return None
        result = validate_ram(v)          # V6: positive even integer
        return str(result) if result is not None else None

    @validator("imei", pre=True, always=True)
    def validate_imei_field(cls, v):
        return validate_imei(v)           # V5: 15 digits only


class PaymentInfo(BaseModel):
    method:  str                      = Field(..., description="upi | netbanking | cod")
    details: Optional[Dict[str, Any]] = None

    @validator("method")
    def validate_method(cls, v):
        allowed = [m.value for m in PaymentMethod]
        if v.lower() not in allowed:
            raise ValueError(f"Payment method must be one of {allowed}")
        return v.lower()



class PartnerResponse(BaseModel):
    partner_id: str
    status: str
    message: str


class UserLogin(BaseModel):
    user_id: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str


class PartnerRegistration(BaseModel):
    # B3: added max_length and clearer descriptions on all fields
    shop_name:  str = Field(..., min_length=3, max_length=100, description="Shop name — must contain at least one letter")
    owner_name: str = Field(..., min_length=3, max_length=50,  description="Owner full name — letters and spaces only")
    mobile:     str = Field(..., description="10-digit Indian mobile starting with 6/7/8/9; +91 prefix optional")
    address:    str = Field(..., min_length=5, max_length=300, description="Physical shop address")

    @validator("owner_name")
    def validate_owner_name(cls, v):
        return validate_client_name(v)  # letters + spaces only, 3-50 chars

    @validator("mobile")
    def validate_mobile(cls, v):
        return validate_indian_mobile(v)  # 10 digits, starts 6-9

    @validator("shop_name")
    def validate_shop_name(cls, v):
        stripped = v.strip()
        if len(stripped) < 3:
           raise ValueError("Shop name must be at least 3 characters.")
        if not re.search(r"[a-zA-Z]", stripped):  # require at least one letter
           raise ValueError("Shop name must contain at least one letter.")
        return stripped

    @validator("address")
    def validate_address(cls, v):
        # B2: address validator was completely missing from PartnerRegistration
        stripped = v.strip()
        if len(stripped) < 5:
            raise ValueError("Shop address is too short (minimum 5 characters).")
        return stripped


class OrderRequest(BaseModel):
    client:          ClientInfo
    device:          DeviceInfo
    payment:         PaymentInfo
    # B5: partner_shop_id was fully unbounded — added max_length guard
    partner_shop_id: Optional[str] = Field(None, max_length=100)


class OrderResponse(BaseModel):
    order_id:           str
    user_id:            str
    device_id:          str
    payment_method:     str
    base_fee:           float
    partner_share:      Optional[float] = None
    xore_share:         float
    message:            str
    # FIX: guests receive a one-time cancellation token so they can cancel
    # their order without needing a JWT login.  It is None for authenticated users.
    guest_cancel_token: Optional[str] = None


class OrderStatusUpdate(BaseModel):
    order_id: str
    status: str = Field(..., description="new status: pending, completed, cancelled")

class PartnerStatusUpdate(BaseModel):
    partner_id: str
    status: str = Field(..., description="active or inactive")

# ── New Registration Models ──
class UserRegister(BaseModel):
    user_id: str = Field(..., min_length=3, max_length=50, description="Login ID (e.g., email or phone)")
    password: str = Field(..., min_length=6, max_length=100, description="Password (min 6 characters)")
    # For a real user, you might also want name, email, etc. – but for login, only user_id/password needed.

class PartnerRegisterLogin(BaseModel):
    partner_id: str = Field(..., description="Partner ID received after shop registration")
    password: str = Field(..., min_length=6, max_length=100, description="Password (min 6 characters)")

# ── Authentication Endpoint ──
@app.post("/auth/login", response_model=Token)
def login(user_data: UserLogin):
    # Running as plain `def` — FastAPI automatically dispatches to its
    # external thread-pool, preventing synchronous DB calls from blocking
    # the async event loop.
    user = get_user(user_data.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(user_data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token(
        data={"sub": user["user_id"], "role": user["role"]},
        expires_delta=timedelta(minutes=30)
    )
    return {"access_token": access_token, "token_type": "bearer"}

#-----------------------------------------------------------------------
# -- ------------------form based - login Endpoint-----------------------
#----------------------------------------------------------------------
@app.post("/auth/token", response_model=Token)
def login_form(form_data: OAuth2PasswordRequestForm = Depends()):
    # Plain `def` — same threadpool reason as /auth/login above.
    user = get_user(form_data.username)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token(
        data={"sub": user["user_id"], "role": user["role"]},
        expires_delta=timedelta(minutes=30)
    )
    return {"access_token": access_token, "token_type": "bearer"}

# ── User Registration Endpoint ──
@app.post("/api/v1/user/register", status_code=status.HTTP_201_CREATED)
async def register_user(payload: UserRegister):
    """Register a new user account."""
    try:
        # FIX: get_user/save_user acquire _write_lock — must run in thread-pool
        existing = await asyncio.to_thread(get_user, payload.user_id)
        if existing:
            raise HTTPException(status_code=409, detail="User ID already exists")

        password_hash = get_password_hash(payload.password)
        await asyncio.to_thread(save_user, payload.user_id, password_hash, "user")
        return {"message": "User registered successfully. Please login."}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("Unhandled error during user registration")
        raise HTTPException(status_code=500, detail="An internal error occurred.")

# ── Partner Login Registration Endpoint ──
@app.post("/api/v1/partner/register-login", status_code=status.HTTP_201_CREATED)
async def register_partner_login(payload: PartnerRegisterLogin):
    """Register a login password for an existing partner shop."""
    try:
        # FIX: all three DB calls hold or wait on _write_lock — offload to thread-pool
        partner  = await asyncio.to_thread(get_partner, payload.partner_id)
        if not partner:
            raise HTTPException(status_code=404, detail="Partner ID not found")

        existing = await asyncio.to_thread(get_user, payload.partner_id)
        if existing:
            raise HTTPException(status_code=409, detail="Partner already has a login")

        password_hash = get_password_hash(payload.password)
        await asyncio.to_thread(save_user, payload.partner_id, password_hash, "partner")
        return {"message": "Partner login registered successfully. You can now login with your partner ID."}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("Unhandled error during partner registration")
        raise HTTPException(status_code=500, detail="An internal error occurred.")


# ---------------------------------------------------------------------------
# Service instances
# ---------------------------------------------------------------------------
finance_service  = FinanceService()
payment_gateway  = PaymentGateway()   # FIX: was never instantiated — payments were accepted blindly

# A3: Final[float] — constant, prevents accidental reassignment.
BASE_FEE: Final[float] = 99.00


def extract_brand(model: str) -> str:
    """Heuristic: first word of model string becomes the brand name."""
    match = re.match(r"^(\w+)", model.strip())
    return match.group(1) if match else "Unknown"


# ---------------------------------------------------------------------------
# Global exception handler — never leak stack traces to the client
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please try again later."},
    )


# ---------------------------------------------------------------------------
# Endpoint: Create Order
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/order/create",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_order(payload: OrderRequest, current_user: Optional[dict] = Depends(get_current_user_optional)):
    """
    Accept nested frontend JSON, validate all fields server-side,
    build domain objects, compute profit split, and persist to SQLite.

    S1: Run with TLS for E2E encryption:
        uvicorn app:app --ssl-keyfile=key.pem --ssl-certfile=cert.pem --host 0.0.0.0 --port 443
    """
    try:
        payment_enum = PaymentMethod(payload.payment.method)

        resolved_user_id = current_user["user_id"] if current_user else str(_uuid_mod.uuid4())

        user = User(
            name=payload.client.name,
            address=payload.client.address,
            phone=payload.client.mobile,
            user_id=resolved_user_id,
        )

        brand = extract_brand(payload.device.model)

        # Convert RAM from validated string back to int (or None)
        ram_int: Optional[int] = int(payload.device.ram) if payload.device.ram else None

        device = Device(
            brand=brand,
            model=payload.device.model,
            bloatware_status=BloatwareStatus.BLOATED,
            ram_gb=ram_int,
            imei=payload.device.imei,
        )

        partner_share: Optional[float] = None
        xore_share: float = BASE_FEE
        if payload.partner_shop_id:
            # FIX: validate that the supplied partner_shop_id actually exists and is
            # active in the database.  Without this check a malicious caller could
            # forge any arbitrary UUID and cause the profit split to run against a
            # non-existent (or inactive) partner, corrupting financial records.
            partner_record = await asyncio.to_thread(get_partner, payload.partner_shop_id)
            if not partner_record:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Partner shop '{payload.partner_shop_id}' does not exist.",
                )
            if partner_record.get("status") != "active":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Partner shop '{payload.partner_shop_id}' is not active.",
                )
            split = finance_service.calculate_partner_payout(BASE_FEE)
            partner_share = split["partner_share"]
            xore_share    = split["xore_share"]

        # FIX: PaymentGateway was built but never called — payments were accepted blindly.
        # Process payment now; raises ValueError (→ 422) if method/amount is invalid.
        try:
            payment_result = await asyncio.to_thread(
                payment_gateway.process_payment, payload.payment.method, BASE_FEE
            )
        except ValueError as pve:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(pve))

        logger.info(
            "Payment processed: method=%s txn=%s status=%s",
            payload.payment.method,
            payment_result.get("transaction_id"),
            payment_result.get("status"),
        )

        if payment_result.get("status") not in ("success", "pending"):
            raise HTTPException(
                status_code=402,
                detail="Payment failed: " + payment_result.get("message", "Unknown error")
            )

        order = Order(
            user=user,
            device=device,
            payment_method=payment_enum,
            base_fee=BASE_FEE,
            partner_shop_id=payload.partner_shop_id,
        )

        logger.info(
            "Order created: id=%s user=%s device=%s/%s payment=%s partner=%s ram=%s imei=%s",
            order.order_id, user.user_id, brand, payload.device.model,
            payment_enum.value, payload.partner_shop_id or "none",
            device.ram_gb, "provided" if device.imei else "none",
        )

        record: OrderRecord = {
            "order_id":        order.order_id,
            "user_id":         user.user_id,
            "device_id":       device.device_id,
            "client_name":     user.name,
            "mobile":          user.phone,
            "address":         user.address,
            "device_model":    payload.device.model,
            "android_version": payload.device.androidVersion,
            "ram_gb":          device.ram_gb,
            "imei":            device.imei,
            "payment_method":  payment_enum.value,
            "base_fee":        BASE_FEE,
            "xore_share":      xore_share,
            "partner_shop_id": payload.partner_shop_id,
            "partner_share":   partner_share,
        }
        # FIX: guest cancellation token — signed JWT, 7-day TTL, encodes order_id.
        # The /api/v1/order/cancel-guest endpoint verifies it so guests can cancel
        # without a login account.
        guest_cancel_token: Optional[str] = None
        if not current_user:
            guest_cancel_token = create_access_token(
                data={"sub": resolved_user_id, "order_id": order.order_id, "role": "guest"},
                expires_delta=timedelta(days=7),
            )

        # FIX: save_order acquires a threading.Lock() internally.  Calling it
        # directly inside an async route would block the entire event loop until
        # the lock is released.  asyncio.to_thread() runs the call in a worker
        # thread from the default ThreadPoolExecutor, keeping the event loop free
        # to serve other requests while the DB write is in progress.
        await asyncio.to_thread(save_order, record)

        return OrderResponse(
            order_id           = order.order_id,
            user_id            = user.user_id,
            device_id          = device.device_id,
            payment_method     = payment_enum.value,
            base_fee           = BASE_FEE,
            partner_share      = partner_share,
            xore_share         = xore_share,
            message            = "Order created successfully." + (
                " Save your cancellation token — it is the only way to cancel this order as a guest." if guest_cancel_token else ""
            ),
            guest_cancel_token = guest_cancel_token,
        )

    except HTTPException:
        raise  # always re-raise HTTP exceptions as-is
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(ve),
        )
    except Exception:
        logger.exception("Unhandled error during order creation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while processing the order.",
        )


# ---------------------------------------------------------------------------
# Endpoint: Register Partner
# ---------------------------------------------------------------------------
@app.post("/api/v1/partner/register", response_model=PartnerResponse, status_code=status.HTTP_201_CREATED)
async def register_partner(payload: PartnerRegistration):
    """Register a new partner shop node."""
    try:
        partner = Partner(
            shop_name=payload.shop_name,
            owner_name=payload.owner_name,
            mobile=payload.mobile,
            address=payload.address,
        )

        record: PartnerRecord = {
            "partner_id": partner.partner_id,
            "shop_name":  partner.shop_name,
            "owner_name": partner.owner_name,
            "mobile":     partner.mobile,
            "address":    partner.address,
            "status":     partner.status,
        }
        # FIX: same reason as save_order — run blocking DB write off the event loop.
        await asyncio.to_thread(save_partner, record)

        logger.info("Partner registered: id=%s shop=%s", partner.partner_id, partner.shop_name)

        return {
            "partner_id": partner.partner_id,
            "status":     "registered",
            "message":    "Shop node registered successfully. Your partner ID is: " + partner.partner_id,
        }

    except HTTPException:
        raise  # B4: was missing — HTTPException was swallowed by the bare except below
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve))
    except Exception:
        logger.exception("Unhandled error during partner registration")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while registering partner.",
        )

#  protected endpoints ──
class GuestCancelRequest(BaseModel):
    order_id:           str
    guest_cancel_token: str


@app.patch("/api/v1/order/cancel-guest", status_code=status.HTTP_200_OK)
async def cancel_guest_order(payload: GuestCancelRequest):
    """
    FIX #3 — Allow guests to cancel their own orders without a JWT login.

    Guests receive a signed `guest_cancel_token` in the create-order response.
    This endpoint verifies that token (same SECRET_KEY / HS256 as normal JWTs),
    ensures it belongs to the requested order_id, and cancels the order.
    The token has a 7-day TTL; after that the guest can contact support instead.
    """
    from jose import JWTError, jwt as _jwt
    from auth import SECRET_KEY, ALGORITHM

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired cancellation token.",
    )
    try:
        payload_data = _jwt.decode(payload.guest_cancel_token, SECRET_KEY, algorithms=[ALGORITHM])
        role     = payload_data.get("role")
        order_id = payload_data.get("order_id")
        if role != "guest" or order_id != payload.order_id:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    order = await asyncio.to_thread(get_order, payload.order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="Order is already cancelled.")
    if order["status"] == "completed":
        raise HTTPException(status_code=409, detail="Completed orders cannot be cancelled.")

    await asyncio.to_thread(update_order_status, payload.order_id, "cancelled")
    return {"order_id": payload.order_id, "status": "cancelled", "message": "Order cancelled successfully."}


@app.patch("/api/v1/order/status")
async def update_order_status_handler(payload: OrderStatusUpdate, current_user: dict = Depends(get_current_user)):
    role = current_user["role"]

    # Define allowed statuses once (used for non-user roles)
    allowed_statuses = {"pending", "completed", "cancelled"}

    # ── 1. Validate status transitions per role ──────────────────────────
    if role == "user":
        if payload.status != "cancelled":
            raise HTTPException(
                status_code=403,
                detail="Users may only cancel orders, not change them to other statuses."
            )
    elif role == "partner":
        if payload.status not in allowed_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Status must be one of: {allowed_statuses}"
            )
    elif role == "admin":
        if payload.status not in allowed_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Status must be one of: {allowed_statuses}"
            )
    else:
        raise HTTPException(status_code=403, detail="Insufficient permissions.")

    # ── 2. Fetch order (offload to thread pool) ──────────────────────────
    order = await asyncio.to_thread(get_order, payload.order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # ── 3. Ownership / permission checks ──────────────────────────────────
    if role == "user" and order["user_id"] != current_user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="You can only cancel your own orders"
        )
    elif role == "partner" and order.get("partner_shop_id") != current_user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="Partners may only update orders assigned to their own shop."
        )
    # Admin has no additional restrictions – falls through

    # ── 4. Guard against terminal states ──────────────────────────────────
    if order["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="Order is already cancelled.")
    if order["status"] == "completed":
        raise HTTPException(status_code=409, detail="Completed orders cannot be modified.")

    # ── 5. Update status ──────────────────────────────────────────────────
    await asyncio.to_thread(update_order_status, payload.order_id, payload.status)
    return {
        "order_id": payload.order_id,
        "status":   payload.status,
        "message":  f"Order status updated to '{payload.status}'."
    }

@app.patch("/api/v1/partner/status")
async def update_partner_status_handler(payload: PartnerStatusUpdate, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "partner":
        raise HTTPException(status_code=403, detail="Only partners can update their status")
    if current_user["user_id"] != payload.partner_id:
        raise HTTPException(status_code=403, detail="You can only update your own partnership status")

    allowed_statuses = {"active", "inactive"}
    if payload.status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"Status must be one of: {allowed_statuses}")

    # FIX: offload blocking DB write to thread-pool
    await asyncio.to_thread(update_partner_status, payload.partner_id, payload.status)
    return {
        "partner_id": payload.partner_id,
        "status":     payload.status,
        "message":    f"Partner status updated to '{payload.status}'."
    }


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    return {"status": "healthy", "service": "XORE API Gateway", "version": "2.0.0"}


# ---------------------------------------------------------------------------
# HTTPS / E2E Encryption — HOW TO RUN
# ---------------------------------------------------------------------------
# Development (self-signed cert):
#   openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes
#   uvicorn app:app --ssl-keyfile=key.pem --ssl-certfile=cert.pem --reload
#
# Production (Let's Encrypt):
#   certbot certonly --standalone -d xorepureandroid.in
#   uvicorn app:app --ssl-keyfile=/etc/letsencrypt/live/xorepureandroid.in/privkey.pem \
#                   --ssl-certfile=/etc/letsencrypt/live/xorepureandroid.in/fullchain.pem \
#                   --host 0.0.0.0 --port 443
#
# All data (name, mobile, address, IMEI) is encrypted in-transit via TLS 1.3.
# For database-level encryption at rest, replace sqlite3 with SQLCipher:
#   pip install sqlcipher3
#   conn = sqlcipher3.connect(DB_PATH)
#   conn.execute(f"PRAGMA key='{DB_ENCRYPTION_KEY}'")
