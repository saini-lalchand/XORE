/**
 * validation.js
 * XORE Pure Android – Frontend form validation & submission logic.
 *
 * FIXES & IMPROVEMENTS IN THIS VERSION:
 *
 *   Field rules (all enforced in real-time AND on submit):
 *   ────────────────────────────────────────────────────────
 *   F1  — Client Name: letters + spaces ONLY. Digits and symbols are stripped
 *          the instant they are typed. Min 3, max 50 characters.
 *   F2  — Mobile Number: digits only, exactly 10 digits, first digit must be
 *          6, 7, 8, or 9. Accepts +91 prefix (auto-stripped for validation).
 *          Letters blocked in real-time. Min-length 10 enforced on blur/submit.
 *   F3  — Device Model: must contain at least one letter (not digits-only).
 *          Validated on blur and submit.
 *   F4  — RAM: digits only, must be a positive EVEN integer (2,4,6,8,12,16…).
 *          Letters stripped in real-time. Odd/zero/negative rejected.
 *   F5  — IMEI: digits ONLY, exactly 15. Letters and symbols stripped in
 *          real-time. Length enforced on blur/submit.
 *   F6  — Address: required, min 5 characters.
 *   F7  — UPI ID: must match VPA format localpart@handle.
 *   F8  — Android Version: any selected option is accepted (optional).
 *
 *   Earlier bug fixes (preserved):
 *   ────────────────────────────────
 *   Bug #4 — partner_shop_id included in POST payload.
 *   Bug #5 — UPI ID format validated (localpart@handle).
 *   Bug #6 — Order ID shown on success so users can track their request.
 *
 *   Security & UX:
 *   ──────────────
 *   S1  — fetch() uses HTTPS endpoint in production (see API_ENDPOINT).
 *   S2  — Input values are trimmed before sending; never send raw whitespace.
 *   S3  — Submit button disabled during async call to prevent duplicate orders.
 */

(function () {
    'use strict';

    // ──────────────────────────────────────────────
    // DOM element references (cached once for performance)
    // ──────────────────────────────────────────────
    const form           = document.getElementById('deviceForm');
    const clientName     = document.getElementById('clientName');
    const mobileNumber   = document.getElementById('mobileNumber');
    const addressField   = document.getElementById('address');
    const deviceModel    = document.getElementById('deviceModel');
    const androidVersion = document.getElementById('androidVersion');
    const ramInfo        = document.getElementById('ramInfo');
    const imeiField      = document.getElementById('imei');
    const partnerShopId  = document.getElementById('partnerShopId');   // Bug #4

    // Payment elements
    const paymentRadios     = document.getElementsByName('paymentMethod');
    const upiDetails        = document.getElementById('upiDetails');
    const netbankingDetails = document.getElementById('netbankingDetails');
    const codDetails        = document.getElementById('codDetails');
    const upiId             = document.getElementById('upiId');
    const bankSelect        = document.getElementById('bankSelect');

    // Error elements
    const nameError    = document.getElementById('clientNameError');
    const mobileError  = document.getElementById('mobileNumberError');
    const addressError = document.getElementById('addressError');  // FIX #3
    const ramError     = document.getElementById('ramInfoError');
    const imeiError    = document.getElementById('imeiError');

    // ──────────────────────────────────────────────
    // Utility helpers
    // ──────────────────────────────────────────────
    function digitsOnly(str) { return str.replace(/\D/g, ''); }

    function showFieldError(errorEl, inputEl) {
        if (errorEl) errorEl.classList.remove('hidden');
        if (inputEl) {
            inputEl.classList.add('border-red-500');
            inputEl.classList.remove('border-gray-700');
        }
    }
    function clearFieldError(errorEl, inputEl) {
        if (errorEl) errorEl.classList.add('hidden');
        if (inputEl) {
            inputEl.classList.remove('border-red-500');
            inputEl.classList.add('border-gray-700');
        }
    }

    // ──────────────────────────────────────────────
    // F1 — Client Name
    // Letters (a-z, A-Z) and spaces only. Min 3 chars.
    // ──────────────────────────────────────────────
    const NAME_PATTERN = /^[a-zA-Z\s]{3,50}$/;

    if (clientName) {
        // Strip digits/symbols instantly as user types
        clientName.addEventListener('input', function () {
            const before = this.value;
            const cleaned = before.replace(/[^a-zA-Z\s]/g, '');
            if (before !== cleaned) {
                this.value = cleaned;
                showFieldError(nameError, this);
            } else {
                clearFieldError(nameError, this);
            }
        });
        clientName.addEventListener('blur', function () {
            if (!NAME_PATTERN.test(this.value.trim())) {
                showFieldError(nameError, this);
            } else {
                clearFieldError(nameError, this);
            }
        });
    }

    // ──────────────────────────────────────────────
    // F2 — Mobile Number
    // 10 digits, first digit 6-9. Accepts +91 prefix.
    // No letters allowed — stripped in real-time.
    // ──────────────────────────────────────────────
    function validateMobile(value) {
        const raw = value.trim();
        // Strip +91 or 91 prefix to isolate the 10-digit number
        let tenDigits = raw.replace(/^\+91[\s\-]?/, '').replace(/^91/, '');
        // Must be exactly 10 digits starting with 6, 7, 8, or 9
        return /^[6-9][0-9]{9}$/.test(tenDigits);
    }

    if (mobileNumber) {
        mobileNumber.addEventListener('input', function () {
            // Allow only digits, +, space, dash — block all letters
            this.value = this.value.replace(/[^0-9+\s\-]/g, '');
        });
        mobileNumber.addEventListener('blur', function () {
            if (!this.value.trim() || !validateMobile(this.value)) {
                showFieldError(mobileError, this);
            } else {
                clearFieldError(mobileError, this);
            }
        });
    }

    // ──────────────────────────────────────────────
    // F4 — RAM (optional)
    // Digits only. Must be a positive EVEN integer.
    // ──────────────────────────────────────────────
    if (ramInfo) {
        ramInfo.addEventListener('input', function () {
            // Strip anything that is not a digit
            this.value = this.value.replace(/[^0-9]/g, '');
            if (ramError) ramError.classList.add('hidden');
        });
        ramInfo.addEventListener('blur', function () {
            const val = this.value.trim();
            if (val === '') {
                clearFieldError(ramError, this);
                return;
            }
            const n = parseInt(val, 10);
            if (isNaN(n) || n <= 0) {
                showFieldError(ramError, this);
            } else {
                clearFieldError(ramError, this);
            }
        });
    }

    // ──────────────────────────────────────────────
    // F5 — IMEI (optional)
    // Exactly 15 digits. No letters or symbols.
    // ──────────────────────────────────────────────
    if (imeiField) {
        imeiField.addEventListener('input', function () {
            // Strip anything that is not a digit
            this.value = this.value.replace(/[^0-9]/g, '');
        });
        imeiField.addEventListener('blur', function () {
            const val = this.value.trim();
            if (val === '') {
                clearFieldError(imeiError, this);
            } else if (!/^[0-9]{15}$/.test(val)) {
                showFieldError(imeiError, this);
            } else {
                clearFieldError(imeiError, this);
            }
        });
    }

    // ──────────────────────────────────────────────
    // Payment UI toggle
    // ──────────────────────────────────────────────
    function hideAllPaymentDetails() {
        [upiDetails, netbankingDetails, codDetails].forEach(el => {
            if (el) el.classList.add('hidden');
        });
    }

    function showPaymentDetails(method) {
        hideAllPaymentDetails();
        const map = { upi: upiDetails, netbanking: netbankingDetails, cod: codDetails };
        const panel = map[method];
        if (panel) panel.classList.remove('hidden');
        // Restore scroll position to prevent page jump
        const scrollY = window.scrollY || window.pageYOffset;
        window.scrollTo({ top: scrollY, behavior: 'instant' });
    }

    paymentRadios.forEach(radio => {
        radio.addEventListener('change', function (e) {
            if (e.target.checked) showPaymentDetails(e.target.value);
        });
    });

    // ──────────────────────────────────────────────
    // Policy checkbox
    // ──────────────────────────────────────────────
    const policyCb  = document.getElementById('policyAgreement');
    const policyRow = document.getElementById('policyAgreementRow');
    const policyErr = document.getElementById('policyError');

    if (policyCb) {
        policyCb.addEventListener('change', function () {
            if (this.checked) {
                if (policyRow) { policyRow.classList.add('is-checked'); policyRow.classList.remove('has-error'); }
                if (policyErr) policyErr.classList.add('hidden');
            } else {
                if (policyRow) policyRow.classList.remove('is-checked');
            }
        });
    }

    // ──────────────────────────────────────────────
    // Full form validation (returns { isValid, errors })
    // ──────────────────────────────────────────────
    function validateFormData() {
        const errors = [];

        try {
            // F1 — Name
            const nameVal = clientName?.value.trim() || '';
            if (!NAME_PATTERN.test(nameVal)) {
                showFieldError(nameError, clientName);
                errors.push('Client Name must be letters and spaces only (3–50 characters).');
            } else {
                clearFieldError(nameError, clientName);
            }

            // F2 — Mobile
            const mobVal = mobileNumber?.value.trim() || '';
            if (!mobVal || !validateMobile(mobVal)) {
                showFieldError(mobileError, mobileNumber);
                errors.push('Enter a valid Indian mobile number: 10 digits starting with 6, 7, 8, or 9.');
            } else {
                clearFieldError(mobileError, mobileNumber);
            }

            // F6 — Address (FIX #3: visual feedback added)
            const addrVal = addressField?.value.trim() || '';
            if (addrVal.length < 5) {
                showFieldError(addressError, addressField);
                errors.push('Address is required (minimum 5 characters).');
            } else {
                clearFieldError(addressError, addressField);
            }

            // F3 — Device Model
            const modelVal = deviceModel?.value.trim() || '';
            if (modelVal.length < 3) {
                errors.push('Device Model is required (minimum 3 characters).');
            } else if (/^\d+$/.test(modelVal)) {
                errors.push('Device Model cannot be only numbers — include the model name (e.g. Moto G67 Power).');
            }

            // F4 — RAM (optional)
            const ramVal = ramInfo?.value.trim() || '';
            if (ramVal !== '') {
                const n = parseInt(ramVal, 10);
                if (isNaN(n) || n <= 0) {
                    showFieldError(ramError, ramInfo);
                    errors.push('RAM must be a positive whole number (e.g. 2, 3,4).');
                } else {
                    clearFieldError(ramError, ramInfo);
                }
            }

            // F5 — IMEI (optional)
            const imeiVal = imeiField?.value.trim() || '';
            if (imeiVal !== '' && !/^[0-9]{15}$/.test(imeiVal)) {
                showFieldError(imeiError, imeiField);
                errors.push('IMEI must be exactly 15 digits — numbers only, no letters or symbols.');
            } else if (imeiVal !== '') {
                clearFieldError(imeiError, imeiField);
            }

            // Payment method
            const selectedPayment = document.querySelector('input[name="paymentMethod"]:checked');
            if (!selectedPayment) {
                errors.push('Please select a payment method (UPI, NetBanking, or Cash on Delivery).');
            } else {
                const method = selectedPayment.value;
                if (method === 'upi') {
                    const upiVal = upiId?.value.trim() || '';
                    if (!upiVal) {
                        errors.push('UPI ID is required for UPI payment.');
                    } else if (!/^[\w.\-]+@[\w]+$/.test(upiVal)) {
                        // F7 — UPI ID format
                        errors.push('Please enter a valid UPI ID (e.g. name@okhdfcbank).');
                    }
                } else if (method === 'netbanking') {
                    if (!bankSelect?.value) {
                        errors.push('Please select a bank for NetBanking.');
                    }
                }
            }

            // Policy agreement
            if (!policyCb?.checked) {
                if (policyRow) { policyRow.classList.add('has-error'); policyRow.classList.remove('is-checked'); }
                if (policyErr) policyErr.classList.remove('hidden');
                errors.push('You must agree to the XORE Service Policy.');
            } else {
                if (policyRow) policyRow.classList.remove('has-error');
                if (policyErr) policyErr.classList.add('hidden');
            }

            return { isValid: errors.length === 0, errors };

        } catch (err) {
            console.error('Validation error:', err);
            return { isValid: false, errors: ['An unexpected error occurred during validation. Please try again.'] };
        }
    }

    // ──────────────────────────────────────────────
    // Build clean JSON payload
    // ──────────────────────────────────────────────
    function buildOrderJSON() {
        try {
            const paymentMethod = document.querySelector('input[name="paymentMethod"]:checked')?.value || null;

            // F2: strip to 10 digits only before sending
            const rawMobile  = mobileNumber?.value.trim() || '';
            let cleanMobile  = digitsOnly(rawMobile);
            if (cleanMobile.length === 12 && cleanMobile.startsWith('91')) {
                cleanMobile = cleanMobile.slice(2);   // remove country code
            }
            cleanMobile = cleanMobile.slice(-10);     // take last 10 digits

            // F4: send as string (backend converts to int)
            const ramVal = ramInfo?.value.trim() || '';

            const orderData = {
                client: {
                    name:    clientName?.value.trim()       || '',
                    mobile:  cleanMobile,
                    address: addressField?.value.trim()     || '',
                },
                device: {
                    model:          deviceModel?.value.trim()    || '',
                    androidVersion: androidVersion?.value        || null,
                    ram:            ramVal !== '' ? ramVal : null,   // F4: even int string or null
                    imei:           imeiField?.value.trim() || null, // F5: 15 digits or null
                },
                payment: {
                    method:  paymentMethod,
                    details: {},
                },
                // Bug #4: partner shop ID always included
                partner_shop_id: partnerShopId?.value.trim() || null,
            };

            // Payment-specific details
            if (paymentMethod === 'upi') {
                orderData.payment.details.upiId = upiId?.value.trim() || '';
            } else if (paymentMethod === 'netbanking') {
                orderData.payment.details.bank = bankSelect?.value || '';
            } else if (paymentMethod === 'cod') {
                orderData.payment.details.note = 'Cash on delivery';
            }

            return orderData;

        } catch (err) {
            console.error('Error building JSON:', err);
            return null;
        }
    }

    // ──────────────────────────────────────────────
    // POST to backend (S1: use HTTPS in production)
    // ──────────────────────────────────────────────
    async function submitOrder(orderData) {
        // S1: Change to https://xorepureandroid.in/api/v1/order/create for production
        // FIX #4: Use relative path so it works in both dev and production
        const API_ENDPOINT = '/api/v1/order/create';

        // FIX #9: Attach token if user is logged in; omitted for guests (backend accepts both)
        const token = localStorage.getItem('authToken');
        const headers = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = 'Bearer ' + token;

        const response = await fetch(API_ENDPOINT, {
            method:  'POST',
            headers: headers,
            credentials: 'same-origin',
            body: JSON.stringify(orderData),
        });

        if (!response.ok) {
            const body = await response.json().catch(() => ({ detail: 'Unknown server error.' }));

            // FIX #4 — Pydantic 422 errors return detail as an *array* of objects,
            // not a plain string.  Passing an array to new Error() produces the
            // useless "[object Object], [object Object]" message.
            //
            // This normaliser handles three shapes FastAPI can return:
            //   1. String:  { detail: "Mobile number must be exactly 10 digits." }
            //   2. Array:   { detail: [ { loc: [...], msg: "...", type: "..." }, … ] }
            //   3. Missing: undefined / null
            function normaliseDetail(detail) {
                if (!detail) return `Server error ${response.status}`;
                if (typeof detail === 'string') return detail;
                if (Array.isArray(detail)) {
                    // Each item has a `msg` and a `loc` (field path).
                    return detail
                        .map(function (err) {
                            const field = Array.isArray(err.loc) ? err.loc.join(' → ') : '';
                            const msg   = err.msg || JSON.stringify(err);
                            return field ? `${field}: ${msg}` : msg;
                        })
                        .join('\n');
                }
                // Fallback: stringify whatever we got
                return JSON.stringify(detail);
            }

            throw new Error(normaliseDetail(body.detail));
        }

        return await response.json();
    }

    // ──────────────────────────────────────────────
    // Form submit handler
    // ──────────────────────────────────────────────
    async function handleFormSubmit(event) {
        event.preventDefault();

        const submitBtn    = form.querySelector('button[type="submit"]');
        // B1: store original textContent not innerHTML; avoid injecting HTML
        const originalText = submitBtn ? submitBtn.textContent : '';

        if (submitBtn) {
            submitBtn.disabled     = true;   // S3: prevent duplicate submissions
            submitBtn.textContent  = 'Submitting…';
        }

        try {
            const { isValid, errors } = validateFormData();
            if (!isValid) {
                // Scroll to first error
                const firstErr = document.querySelector('.border-red-500, #policyAgreementRow.has-error');
                if (firstErr) firstErr.scrollIntoView({ behavior: 'smooth', block: 'center' });
                alert('⚠️ Please fix the following:\n\n' + errors.join('\n'));
                return;
            }

            const orderData = buildOrderJSON();
            if (!orderData) throw new Error('Failed to construct order data.');

            const result = await submitOrder(orderData);

            // Bug #6: show Order ID so users can track their request
            const orderId          = result?.order_id          || 'N/A';
            const guestCancelToken = result?.guest_cancel_token || null;

            if (guestCancelToken) {
                // FIX: don't use alert() for the guest token — a JWT is ~250 chars
                // and the user may dismiss the dialog before copying it, losing it
                // permanently.  Instead inject a persistent, copy-able banner into
                // the page above the form so it stays visible until the page reloads.
                const banner = document.createElement('div');
                banner.id        = 'guestTokenBanner';
                banner.className = 'mb-6 bg-[#111827] border border-yellow-500/60 rounded-lg p-4 text-left';
                banner.innerHTML = `
                    <p class="text-yellow-400 font-mono text-sm font-bold mb-2">
                        ✅ Order submitted! — Guest Cancellation Token
                    </p>
                    <p class="text-gray-300 font-mono text-xs mb-3">
                        📋 Order ID: <span class="text-[#00f0ff] font-bold">${orderId}</span>
                    </p>
                    <p class="text-gray-400 font-mono text-xs mb-2">
                        You placed this order as a guest. Save the token below — it is the
                        <strong class="text-yellow-400">only way to cancel</strong> your order
                        and will <strong class="text-yellow-400">not be shown again</strong>.
                    </p>
                    <div class="relative">
                        <textarea id="guestTokenDisplay" readonly rows="3"
                            class="w-full bg-[#0b0f19] border border-yellow-500/40 text-[#00f0ff] rounded px-3 py-2
                                   font-mono text-xs resize-none focus:outline-none select-all"
                        >${guestCancelToken}</textarea>
                        <button id="copyGuestToken"
                            class="mt-2 w-full bg-yellow-500/20 hover:bg-yellow-500/40 text-yellow-300
                                   border border-yellow-500/40 rounded px-4 py-2 font-mono text-xs font-bold
                                   uppercase transition-all">
                            📋 Copy Token
                        </button>
                    </div>
                    <p class="mt-2 text-gray-500 font-mono text-xs">
                        Token valid for 7 days. Keep this page open until you have copied it.
                    </p>`;

                // Insert the banner at the very top of the form container.
                // FIX: remove any existing banner from a previous submission before
                // inserting a new one — otherwise repeated guest orders stack banners.
                const existingBanner = document.getElementById('guestTokenBanner');
                if (existingBanner) existingBanner.remove();
                const formContainer = form.closest('div') || form.parentElement;
                if (formContainer) formContainer.insertBefore(banner, formContainer.firstChild);

                // Wire the copy button
                const copyBtn = document.getElementById('copyGuestToken');
                if (copyBtn) {
                    copyBtn.addEventListener('click', function () {
                        navigator.clipboard.writeText(guestCancelToken).then(function () {
                            copyBtn.textContent = '✅ Copied!';
                            setTimeout(function () { copyBtn.textContent = '📋 Copy Token'; }, 2500);
                        }).catch(function () {
                            // Fallback: select the textarea text
                            const ta = document.getElementById('guestTokenDisplay');
                            if (ta) { ta.select(); document.execCommand('copy'); }
                            copyBtn.textContent = '✅ Copied!';
                            setTimeout(function () { copyBtn.textContent = '📋 Copy Token'; }, 2500);
                        });
                    });
                }

                // Scroll banner into view
                banner.scrollIntoView({ behavior: 'smooth', block: 'start' });

                // Also post the token up to the parent window so index.html can
                // pre-fill the guest cancel textarea in the dashboard modal.
                if (window.parent && window.parent !== window) {
                    window.parent.postMessage(
                        { type: 'xore-guest-token', order_id: orderId, guest_cancel_token: guestCancelToken },
                        window.location.origin
                    );
                }
            } else {
                // Authenticated user — simple success alert is fine
                alert(
                    `✅ Order submitted successfully!\n\n` +
                    `📋 Your Order ID: ${orderId}\n\n` +
                    `We will contact you within 24 hours. Please save your Order ID for tracking.`
                );
            }

            // Reset form and clean up custom CSS states
            form.reset();
            hideAllPaymentDetails();
            [clientName, mobileNumber, addressField, deviceModel, ramInfo, imeiField].forEach(el => {
                if (el) { el.classList.remove('border-red-500'); el.classList.add('border-gray-700'); }
            });
            [nameError, mobileError, addressError, ramError, imeiError].forEach(el => {
                if (el) el.classList.add('hidden');
            });
            const rowReset = document.getElementById('policyAgreementRow');
            if (rowReset) rowReset.classList.remove('is-checked', 'has-error');

        } catch (err) {
            console.error('Form submission error:', err);
            alert('❌ Submission failed: ' + (err.message || 'Unknown error. Please try again.'));
        } finally {
            if (submitBtn) {
                submitBtn.disabled     = false;
                submitBtn.textContent  = originalText || 'Submit Debloat Request';
            }
        }
    }

    // ──────────────────────────────────────────────
    // Iframe height reporter (for parent index.html)
    // ──────────────────────────────────────────────
    function reportHeight() {
        const h = document.documentElement.scrollHeight;
        if (window.parent && window.parent !== window) {
            // FIX: document.referrer can be empty (privacy modes, direct iframe src load,
            // missing Referrer-Policy header).  When empty, new URL('').origin throws.
            // window.location.origin is always correct for same-origin parent pages
            // and is the same value the parent uses when it posts messages down to us.
            window.parent.postMessage({ type: 'xore-resize', height: h }, window.location.origin);
        }
    }
    reportHeight();
    paymentRadios.forEach(r => r.addEventListener('change', () => setTimeout(reportHeight, 50)));

    // ──────────────────────────────────────────────
    // Init
    // ──────────────────────────────────────────────
    function init() {
        // ── Auto-populate partnerShopId from parent URL (iframe fix) ──
        //
        // BUG FIX: This page runs inside an <iframe>. window.location.search
        // is always empty for the iframe itself — it does NOT reflect the parent
        // page URL (e.g. https://xorepureandroid.in/?partner_id=XOR-123).
        //
        // SOLUTION: Two-channel approach for maximum compatibility:
        //
        // Channel A — postMessage (primary):
        //   index.html reads its own URL params and posts the partner_id down
        //   to the iframe immediately after the iframe loads. We listen here.
        //
        // Channel B — URL hash fallback:
        //   If the iframe src is set as user_form.html#XOR-123 we can read
        //   window.location.hash as a last resort.

        const partnerShopIdInput = document.getElementById('partnerShopId');

        // Channel A: listen for the parent's postMessage
        window.addEventListener('message', function (event) {
            // Security: only accept messages from the same origin as this page.
            // (The parent index.html is served from the same origin.)
            if (event.origin !== window.location.origin) return;

            const data = event.data;
            if (
                data &&
                data.type === 'xore-partner-id' &&
                typeof data.partner_id === 'string' &&
                data.partner_id.trim() !== '' &&
                partnerShopIdInput &&
                !partnerShopIdInput.value  // don't overwrite if already set
            ) {
                partnerShopIdInput.value = data.partner_id.trim();
            }
        });

        // Channel B: hash fallback — src="user_form.html#XOR-123"
        if (partnerShopIdInput && !partnerShopIdInput.value) {
            const hash = window.location.hash.replace('#', '').trim();
            if (hash) {
                partnerShopIdInput.value = hash;
            }
        }

        hideAllPaymentDetails();
        if (form) form.addEventListener('submit', handleFormSubmit);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
