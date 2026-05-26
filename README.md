# XORE Pure Android — Debloat Service Platform 🚀

**XORE Pure Android** is a full-stack service platform that connects users with local partner shops to safely remove pre-installed bloatware from Android devices – **no root, no warranty void**.

The system allows users to submit debloat requests (with full client, device, and payment details), registers partner shop nodes, and automatically splits the ₹99 service fee **50/50** between the platform and the partner. Guest users can place orders without logging in and cancel using a one-time JWT token.


> **Note on RAM Validation:** RAM accepts **any positive integer** (e.g., 3GB, 4GB, 6GB, 12GB). Odd values are natively supported to accommodate older devices with 3GB RAM configurations.


---

## ✨ Architectural Highlights & Features

- ✅ **Highly Concurrent API:** Built with FastAPI and `asyncio.to_thread` to offload synchronous database I/O, keeping the main event loop unblocked.
- ✅ **Thread-Safe Persistence:** SQLite3 running in **WAL mode** with a strict module-level write lock (`_write_lock`) to serialize DDL and INSERT operations.
- ✅ **Robust Security & RBAC:** Custom JWT-based authentication for Admins, Partners, and Users. Features short-lived cryptographic cancellation tokens for Guest users.
- ✅ **Partner Shop Network:** Shopkeepers can register as nodes and track their 50% profit share in real-time via the PartnerHub dashboard.
- ✅ **Real-Time Data Sanitization:** Vanilla JS frontend mapped directly to server-side Pydantic schemas, dropping invalid inputs (like symbols in names or letters in IMEIs) at the keystroke level.
- ✅ **Production Ready:** Pre-configured with strict security headers (HSTS, X-Frame-Options, X-XSS-Protection) and ready for TLS/HTTPS deployment.

---

## 🛠 Tech Stack

| Layer          | Technology |
|----------------|------------|
| **Backend** | FastAPI (Python 3.9+) |
| **Database** | SQLite3 (with `_write_lock` and WAL mode) |
| **Auth** | JWT (python-jose), bcrypt (passlib) |
| **Validation** | Pydantic + custom python validators |
| **Frontend** | Plain HTML5, Vanilla JS, Tailwind CSS via CDN |
| **Deployment** | Uvicorn (ready for TLS/SSL) |

---

## 📦 Core API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| **POST** | `/api/v1/order/create` | Submit a debloat request (authenticated or guest) |
| **POST** | `/api/v1/partner/register` | Register a new shop node |
| **POST** | `/api/v1/partner/register-login`| Set login password for an existing partner |
| **PATCH** | `/api/v1/order/status` | Update order status (user/partner/admin) |
| **PATCH** | `/api/v1/order/cancel-guest` | Cancel an order with a guest cancellation token |
| **POST** | `/auth/login` | JWT login (user, partner, admin) |
| **POST** | `/api/v1/user/register`| Create a normal user account |
| **PATCH** | `/api/v1/partner/status` | Update partner status (active/inactive) |

---

## 🛡️ Validation Rules (Enforced Server & Client Side)

| Field | Rule |
|-------|------|
| **Client name** | Letters and spaces only, 3–50 characters |
| **Mobile number** | 10 digits, first digit 6/7/8/9 (accepts +91 prefix) |
| **Address** | Minimum 5 characters |
| **Device model**| Must contain at least one letter, min 3 characters |
| **RAM (optional)**| Any positive integer (e.g., 3, 4, 6, 8, 12) |
| **IMEI (optional)**| Exactly 15 digits, numbers only |
| **Payment method**| One of: `upi`, `netbanking`, `cod` |
| **UPI ID** | Valid `localpart@handle` format |

---

## 🚀 Getting Started

### 1. Clone the repository
> `git clone https://github.com/yourusername/XORE.git`
> `cd XORE`

### 2. Install dependencies
> `pip install fastapi uvicorn python-jose[cryptography] passlib[bcrypt] pydantic`

### 3. Run the Server (Development)
> `uvicorn app:app --reload --host 127.0.0.1 --port 8000`

*Open `http://127.0.0.1:8000/index.html` in your browser.*

### 4. Run with TLS (Production Simulation)
> `openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes`
> `uvicorn app:app --ssl-keyfile=key.pem --ssl-certfile=cert.pem --host 0.0.0.0 --port 443`

---

## 📁 Repository Structure
```
> .
> ├── app.py                 # FastAPI main application (endpoints, middleware)
> ├── auth.py                # JWT helpers, password hashing, optional auth
> ├── database.py            # SQLite layer with TypedDicts and thread-safe writes
> ├── models.py              # Pydantic/dataclass models with strict validators
> ├── services.py            # FinanceService (profit split) & PaymentGateway
> ├── index.html             # Landing page with modal user dashboard
> ├── user_form.html         # Device ingestion form (loaded in iframe)
> ├── partnerhub.html        # Partner dashboard (shopkeeper portal)
> └── validation.js          # Frontend real-time validation & API integration
```

*(Note: `xore_data.db`, `key.pem`, and `cert.pem` are auto-generated at runtime and ignored via `.gitignore`)*

---

## 🔒 Security Notes
- All input validation is performed server-side; client validation exists purely for UX.
- Guest cancellation tokens are cryptographically signed and expire after 7 days.
- Designed to run behind a reverse proxy (like Nginx) or directly via Uvicorn with TLS 1.3 in production.
