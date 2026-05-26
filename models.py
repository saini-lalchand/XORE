"""
models.py — XORE Pure Android backend data models.

CHANGES IN THIS VERSION:
  V1 — Added @validator to User for phone (must be 10 digits, start 6-9, digits only)
       and name (letters + spaces only, no digits/symbols).
  V2 — Added @validator to Device for imei (15 digits only) and ram (positive even int).
  V3 — Kept slots=True for memory efficiency; added __post_init__ validators on
       dataclasses since they don't support Pydantic natively.
  V4 — RAM stored as Optional[int] (even number) — never a float or string.
  V5 — IMEI stored as Optional[str] of exactly 15 digit characters.
  V6 — Added Partner dataclass for shop node registration.
"""

import re
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Union


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class BloatwareStatus(Enum):
    """Represents the current bloatware state of a device."""
    UNKNOWN    = auto()
    CLEAN      = auto()
    BLOATED    = auto()
    DEBLOATING = auto()


class PaymentMethod(Enum):
    """Accepted payment methods."""
    UPI        = "upi"
    NETBANKING = "netbanking"
    COD        = "cod"


# ---------------------------------------------------------------------------
# Validators (pure functions — reusable across dataclasses and Pydantic models)
# ---------------------------------------------------------------------------

def validate_client_name(name: str) -> str:
    """
    Name rules:
    - Letters (a-z, A-Z) and spaces only
    - No digits, no symbols
    - Min 3 characters, max 50 characters
    """
    stripped = name.strip()
    if not stripped:
        raise ValueError("Client name is required.")
    if len(stripped) < 3:
        raise ValueError("Client name must be at least 3 characters.")
    if len(stripped) > 50:
        raise ValueError("Client name must be 50 characters or fewer.")
    if not re.fullmatch(r"[a-zA-Z\s]+", stripped):
        raise ValueError("Client name must contain letters and spaces only — no digits or symbols.")
    return stripped


def validate_indian_mobile(phone: str) -> str:
    """
    Indian mobile rules:
    - Exactly 10 digits
    - First digit must be 6, 7, 8, or 9
    - No letters, no symbols (strip +91 prefix if present)
    """
    # Strip all non-digit characters first
    digits_only = re.sub(r"\D", "", phone)
    # If +91 was included, strip the country code to get 10-digit number
    if len(digits_only) == 12 and digits_only.startswith("91"):
        digits_only = digits_only[2:]
    if len(digits_only) != 10:
        raise ValueError("Mobile number must be exactly 10 digits.")
    if digits_only[0] not in "6789":
        raise ValueError("Mobile number must start with 6, 7, 8, or 9.")
    return digits_only


def validate_imei(imei: Union[str, int, None]) -> Optional[str]:
    """
    IMEI rules (optional field):
    - If provided, must be exactly 15 digits
    - No letters, no symbols
    Returns None if blank/None.

    FIX: bool is a subclass of int in Python, so True/False would pass the
    isinstance(imei, int) path and become "True"/"False" which then fails the
    15-digit check with a confusing error.  We explicitly reject bools first.
    """
    if imei is None:
        return None
    # FIX: reject booleans — str(True) == "True", str(False) == "False"
    # both fail the 15-digit check, but with a misleading error message.
    if isinstance(imei, bool):
        raise ValueError("IMEI must be exactly 15 digits — numbers only, no letters or symbols.")
    imei_str = str(imei).strip()
    if imei_str == "":
        return None
    if not re.fullmatch(r"[0-9]{15}", imei_str):
        raise ValueError("IMEI must be exactly 15 digits — numbers only, no letters or symbols.")
    return imei_str


def validate_ram(ram: Union[str, int, None]) -> Optional[int]:  # FIX #5: accept int too
    """
    RAM rules (optional field):
    - If provided, must be a positive even integer (2, 4, 6, 8, 12, 16…)
    - No letters, no symbols
    Returns None if blank/None.
    """
    if ram is None or (isinstance(ram, str) and ram.strip() == ""):
        return None
    try:
        value = int(str(ram).strip())
    except (ValueError, TypeError):
        raise ValueError("RAM must be a whole number — no letters or symbols.")
    if value <= 0:
        raise ValueError("RAM must be a positive number.")
    return value


def validate_device_model(model: str) -> str:
    """
    Device model rules:
    - Must contain at least one letter (cannot be digits-only)
    - Min 3 characters
    """
    stripped = model.strip()
    if not stripped:
        raise ValueError("Device model is required.")
    if len(stripped) < 3:
        raise ValueError("Device model name is too short (minimum 3 characters).")
    if re.fullmatch(r"\d+", stripped):
        raise ValueError("Device model cannot be only numbers.")
    return stripped


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass(slots=True, frozen=False)
class User:
    """
    A customer using the XORE debloating service.

    Attributes:
        name:    Full name (letters + spaces only, 3–50 chars).
        address: Physical address (min 5 chars).
        phone:   10-digit Indian mobile number starting with 6/7/8/9.
        user_id: Unique identifier, auto-generated if not supplied.
    """
    name:    str
    address: str
    phone:   str
    user_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self):
        # FIX: object.__setattr__ is only needed for frozen=True dataclasses.
        # Since frozen=False, plain assignment works and is clearer.
        self.name    = validate_client_name(self.name)
        self.phone   = validate_indian_mobile(self.phone)
        address = self.address.strip()
        if len(address) < 5:
            raise ValueError("Address is too short (minimum 5 characters).")
        self.address = address


@dataclass(slots=True, frozen=False)
class Device:
    """
    A smartphone submitted for bloatware removal.

    Attributes:
        brand:            Manufacturer (e.g., "Motorola", "Samsung").
        model:            Exact model name — must contain letters (e.g., "Moto G67 Power").
        bloatware_status: Current status of the device.
        ram_gb:           RAM in GB — must be a positive even integer if provided.
        imei:             15-digit IMEI string if provided.
        device_id:        Unique identifier, auto-generated.
    """
    brand:            str
    model:            str
    bloatware_status: BloatwareStatus = BloatwareStatus.UNKNOWN
    ram_gb:           Optional[int]   = None   # V4 — int only, even number
    imei:             Optional[str]   = None   # V5 — 15 digits only
    device_id:        str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self):
        self.model = validate_device_model(self.model)
        brand = self.brand.strip()
        if not brand:
            raise ValueError("Device brand is required.")
        self.brand  = brand
        self.ram_gb = validate_ram(self.ram_gb)
        self.imei   = validate_imei(self.imei)


@dataclass(slots=True, frozen=False)
class Order:
    """A complete debloating order."""
    user:            User
    device:          Device
    payment_method:  PaymentMethod
    base_fee:        float
    order_id:        str = field(default_factory=lambda: str(uuid.uuid4()))
    partner_shop_id: Optional[str] = None


# ===== NEW: Partner dataclass for shop node registration =====
@dataclass(slots=True, frozen=False)
class Partner:
    """
    A partner shop node registered with XORE.

    Attributes:
        shop_name:   Name of the shop. Can contain digits but must contain at least one letter.
                     Minimum 3 characters.
        owner_name:  Full name of the shop owner – letters and spaces only, no digits/symbols.
                     Min 3, max 50 characters.
        mobile:      10-digit Indian mobile number starting with 6/7/8/9. +91 prefix allowed.
        address:     Physical address (minimum 5 characters).
        partner_id:  Unique identifier, auto-generated.
        status:      'active' or 'pending' (default 'pending').
    """
    shop_name:     str
    owner_name:    str
    mobile:        str
    address:       str
    partner_id:    str = field(default_factory=lambda: str(uuid.uuid4()))
    status:        str = "pending"

    def __post_init__(self):
        # ---- Owner name: letters + spaces only ----
        self.owner_name = validate_client_name(self.owner_name)

        # ---- Shop name: cannot be only digits, min 3 chars ----
        shop = self.shop_name.strip()
        if not shop or len(shop) < 3:
            raise ValueError("Shop name must be at least 3 characters.")
        if re.fullmatch(r"\d+", shop):
            raise ValueError("Shop name cannot be only numbers – must contain at least one letter.")
        self.shop_name = shop

        # ---- Mobile: 10 digits, first digit 6/7/8/9, accepts +91 ----
        self.mobile = validate_indian_mobile(self.mobile)

        # ---- Address: minimum 5 characters ----
        addr = self.address.strip()
        if len(addr) < 5:
            raise ValueError("Address must be at least 5 characters.")
        self.address = addr