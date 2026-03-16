# Car Vault (Vehicle Vault)

Car Vault (Vehicle Vault) is a full-stack Django platform for used-car discovery, listing management, buyer/seller communication, test drives, and deal completion.

It includes role-aware dashboards, OTP-based first-time account activation, profile/rating workflows, and a modern template-based UI.

---

## 🚀 Project Highlights

- Custom user model with roles (`Buyer`, `Seller`) and account states (`Inactive`, `Active`, `Blocked`, `Deleted`)
- OTP email verification for first-time account activation
- Car inventory + listing lifecycle (`Active`, `Pending`, `Sold`, `Withdrawn`)
- Buyer ↔ Seller messaging and deal acceptance workflow
- Test drive scheduling and status tracking
- Role-based dashboard routing (`Admin`, `Buyer`, `Seller`)
- Activity tracking (to-dos, meetings, history)
- Multi-language ready (`i18n`) configuration
- Password reset flow via email templates
---

## ✨ Features

### 🔐 Authentication & User Management
- User signup, login, and logout
- OTP-based first-time account verification
- OTP resend support
- Role-based user system (Admin, Buyer, Seller)
- Account state handling (Active, Inactive, Blocked, Deleted)
- Account settings management
- Password reset via email

### 🚗 Cars & Listings
- Car inventory management
- Create, edit, and delete listings
- Listing status lifecycle (Active, Pending, Sold, Withdrawn)
- Image/media uploads for listings
- Brand-based and all-cars browsing
- Car comparison feature

### 💬 Communication & Deal Flow
- Buyer ↔ Seller messaging
- Message reply flow
- Deal acceptance from message threads
- Transaction creation and update through deal/payment flow

### 🧾 Booking, Payments & Transactions
- Listing booking flow
- Razorpay payment gateway integration
- Razorpay order creation endpoint
- Razorpay signature verification endpoint
- Full-payment and token-booking fallback logic
- Transaction tracking with Razorpay metadata
- EMI fields (months, rate, estimated amount)
- Shipping/contact details captured with transaction
- Invoice emails sent to buyer and seller after successful payment
- Auto-mark listing as Sold on successful full payment

### 📅 Test Drives
- Test drive request creation
- Test drive status updates and management

### 🤖 AI & Smart Features
- AI chatbot page/endpoint
- AI utility layer for insights/automation
- AI-assisted inspection scoring support
- Message sentiment labeling
- Message toxicity score detection

### 📊 Dashboards & Activity
- Role-based dashboard routing (Admin/Buyer/Seller)
- Sales and purchase metrics
- Activity modules:
  - To-dos
  - Meetings
  - Activity history/logs

### 🏙️ Platform Utilities & Pages
- City/showroom discovery pages
- Upcoming arrival management
- Contact, FAQ, Privacy, and Terms pages
- Email health/status check endpoint
- Template-based responsive UI with static assets
- Automated test coverage for key flows (OTP, deal flow, AI-related tests)

---

## 🧰 Tech Stack

- **Backend:** Django 5
- **Database:** PostgreSQL
- **Frontend:** Django Templates + Static CSS/JS
- **Media Handling:** Pillow
- **ML/NLP (optional features):** scikit-learn, transformers, torch, sentence-transformers, langchain

---

## 📁 Repository Structure (What lives where)

```text
car_vault/
  settings.py        # Global config (apps, DB, middleware, static/media, email)
  urls.py            # Root URL routing

core/
  models.py          # Users, listings, messages, test drives, transactions, etc.
  views.py           # Main business workflows
  forms.py           # Signup/login/forms for core features
  middleware.py      # Auth gate middleware
  urls.py            # Main app routes
  tests.py           # Automated tests (OTP + deal flows)
  templatetags/      # Custom template filters/tags

dashboard/
  views.py           # Dashboard role routing + pages
  urls.py            # /dashboard routes

templates/
  core/              # Login/signup/legal pages
  dashboard/         # Buyer/seller/admin dashboard templates
  listings/          # Listing CRUD + detail pages
  messages/          # Inbox + OTP/password-reset email templates
  ...                # Activity, profiles, test drives, etc.

static/
  css/ js/ img/      # Global styling and client-side behavior

media/
  listing_images/    # Uploaded listing media
```

---

## 🏁 Quick Start (Local Development)

### 1) Clone and enter project

- Clone the repository
- Open the project folder in VS Code or terminal

### 2) Create virtual environment

- Windows (PowerShell): `python -m venv .venv`
- Activate: `.venv\Scripts\Activate.ps1`

### 3) Install dependencies

- `pip install -r requirements.txt`

### 4) Configure environment

Create/update `.env` in project root (already added with placeholders):

- `SECRET_KEY`
- `DEBUG`
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, etc.

> Note: Current `settings.py` contains hardcoded development credentials. Move sensitive values to environment variables before publishing or deploying.

### 5) Create PostgreSQL database

- Create DB named `car_vault` (or match your `.env`/settings values)

### 6) Run migrations

- `python manage.py makemigrations`
- `python manage.py migrate`

### 7) Create admin user

- `python manage.py createsuperuser`

### 8) Run server

- `python manage.py runserver`
- Open: `http://127.0.0.1:8000/`

---

## 🔐 Authentication & Account Workflow

### Signup
1. User registers from `/signup/`
2. Account is created with `status = Inactive`
3. OTP is generated and emailed

### First Login (OTP required)
1. User logs in from `/login/`
2. If status is `Inactive`, OTP is requested
3. OTP verification endpoint: `/verify-otp/`
4. On success:
   - status changes to `Active`
   - `otp_code` and `otp_expires` are cleared
   - user is logged in

### After Activation
- Future logins do **not** require OTP (unless status is manually changed back to `Inactive`)

### Account Status Handling
- `Active` → normal login allowed
- `Inactive` → OTP verification required
- `Blocked` → login denied
- `Deleted` → login denied

---

## 🧭 Core Business Workflows

### 1) Listings
- Sellers create listings (`/listings/new/`)
- Listings can be edited/deleted by owners/admin
- Buyers browse listings and listing details

### 2) Messaging + Deal Completion
- Buyer sends message from listing page
- Seller replies via inbox
- Seller can accept a deal from message thread
- Accepting a deal creates/updates transaction and marks listing sold

### 3) Test Drives
- Buyer requests test drive
- Seller/admin can update appointment status

### 4) Ratings
- Users can rate counterparties after interactions
- Ratings update profile quality metrics

### 5) Dashboards
- `/dashboard/` routes users to role-specific pages:
  - `/dashboard/admin/`
  - `/dashboard/buyer/`
  - `/dashboard/seller/`

---

## 🌐 Key Routes at a Glance

- Auth: `/signup/`, `/login/`, `/logout/`, `/verify-otp/`, `/resend-otp/`
- Listings: `/listings/`, `/listings/new/`, `/listings/<id>/`
- Messages: `/messages/`
- Test drives: `/testdrives/`
- Booking: `/booking/`
- Payments: `/razorpay/order/`, `/razorpay/verify/` (aliases: `/create-order/`, `/verify-payment/`)
- Profiles: `/profiles/buyers/`, `/profiles/sellers/`
- Profiles: `/profiles/buyers/`, `/profiles/sellers/`
- Dashboard: `/dashboard/`
- Account settings: `/account/settings/`
- Email health check: `/email/status/`

---

## 🧪 Testing

Run full test suite:

- `python manage.py test`

Run OTP flow tests only:

- `python manage.py test core.tests.OtpAuthFlowTests`

Covered scenarios include:
- OTP verification login path
- OTP resend access behavior
- OTP required only for first activation login

---

## 🤝 Contribution Workflow

Recommended branch strategy:

1. Create feature branch from `main`
2. Make small, focused commits
3. Run tests before pushing
4. Open PR with clear description and screenshots (if UI changed)

Commit message style suggestion:

- `feat(auth): add resend OTP throttling`
- `fix(listings): prevent non-owner edit access`
- `docs(readme): expand setup and workflows`

---

## ⚠️ Security & Production Notes

- Never commit real secrets (DB password, SMTP app password, secret key)
- Set `DEBUG=False` in production
- Restrict `ALLOWED_HOSTS`
- Use environment variables for all sensitive settings
- Consider secure email + storage + HTTPS configuration before deployment

---

## 📌 Current Project Status

This repository contains a working Django application with integrated core flows (auth, listings, messaging, test drives, dashboards). Some setup docs may still reflect older stack notes; this README is the authoritative high-level workflow document for the current codebase.

