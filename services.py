"""
services.py — Core business logic for XORE Pure Android.

No bugs found in this file. Copied unchanged.

Contains:
- FinanceService: Profit split calculation.
- PaymentGateway: Payment validation and routing with robust exception handling.
"""

import logging
from typing import Dict, Union
from uuid import uuid4
from models import PaymentMethod

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class FinanceService:
    """
    Handles financial calculations, including partner profit sharing.

    Business rule: partner shopkeeper receives exactly 50% of the base service
    fee; remaining 50% goes to XORE.
    """

    @staticmethod
    def calculate_partner_payout(base_fee: float) -> Dict[str, float]:
        """
        Split the base fee 50/50 between XORE and the partner shopkeeper.

        Args:
            base_fee: Total service fee (must be >= 0).

        Returns:
            Dict with keys 'xore_share' and 'partner_share'.

        Raises:
            ValueError: If base_fee is negative.
        """
        if base_fee < 0:
            raise ValueError(f"Base fee cannot be negative: {base_fee}")

        partner_share = round(base_fee * 0.5, 2)
        xore_share    = round(base_fee - partner_share, 2)

        logger.debug(
            "Profit split: base=%.2f -> XORE=%.2f, Partner=%.2f",
            base_fee, xore_share, partner_share,
        )
        return {"xore_share": xore_share, "partner_share": partner_share}


class PaymentGateway:
    """
    Validates and routes payments to the appropriate processing logic.

    Currently a simulated gateway; in production each method would integrate
    with third-party APIs (e.g., Razorpay for UPI/NetBanking).
    """

    SUPPORTED_METHODS = {PaymentMethod.UPI, PaymentMethod.NETBANKING, PaymentMethod.COD}

    def process_payment(self, method: Union[PaymentMethod, str], amount: float) -> Dict[str, str]:
        """
        Validate and route a payment request.

        Args:
            method: PaymentMethod enum or string (case-insensitive).
            amount: Amount to collect (must be > 0).

        Returns:
            Dict with keys 'status', 'transaction_id', 'message'.

        Raises:
            ValueError: If method is invalid/unsupported or amount <= 0.
        """
        payment_method = self._normalize_payment_method(method)

        if amount <= 0:
            msg = f"Invalid payment amount: {amount}. Must be greater than zero."
            logger.error(msg)
            raise ValueError(msg)

        try:
            if payment_method == PaymentMethod.UPI:
                return self._process_upi(amount)
            elif payment_method == PaymentMethod.NETBANKING:
                return self._process_netbanking(amount)
            elif payment_method == PaymentMethod.COD:
                return self._process_cod(amount)
            else:
                raise ValueError(f"Unsupported payment method: {payment_method}")
        except Exception as e:
            logger.exception(
                "Payment processing failed for method=%s, amount=%.2f",
                payment_method, amount,
            )
            raise ValueError(f"Payment failed: {e}") from e

    def _normalize_payment_method(self, method: Union[PaymentMethod, str]) -> PaymentMethod:
        """Convert string input to PaymentMethod enum."""
        if isinstance(method, PaymentMethod):
            if method not in self.SUPPORTED_METHODS:
                raise ValueError(f"Unsupported payment method: {method}")
            return method

        if isinstance(method, str):
            method_lower = method.strip().lower()
            for pm in PaymentMethod:
                if pm.value == method_lower or pm.name.lower() == method_lower:
                    return pm
            raise ValueError(
                f"Invalid payment method string: '{method}'. "
                f"Allowed: {[m.value for m in self.SUPPORTED_METHODS]}"
            )

        raise TypeError(f"Payment method must be PaymentMethod or str, got {type(method)}")

    def _process_upi(self, amount: float) -> Dict[str, str]:
        logger.info("Processing UPI payment of ₹%.2f", amount)
        return {
            "status":         "success",
            "transaction_id": "UPI-" + str(uuid4())[:8].upper(),
            "message":        f"UPI payment of ₹{amount:.2f} completed.",
        }

    def _process_netbanking(self, amount: float) -> Dict[str, str]:
        logger.info("Processing NetBanking payment of ₹%.2f", amount)
        return {
            "status":         "success",
            "transaction_id": "NB-" + str(uuid4())[:8].upper(),
            "message":        f"NetBanking payment of ₹{amount:.2f} completed.",
        }

    def _process_cod(self, amount: float) -> Dict[str, str]:
        logger.info("Marking COD payment of ₹%.2f as pending", amount)
        return {
            "status":         "pending",
            "transaction_id": "COD-" + str(uuid4())[:8].upper(),
            "message":        f"COD payment of ₹{amount:.2f} will be collected on delivery.",
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    finance = FinanceService()
    print("Profit split:", finance.calculate_partner_payout(99.00))

    gateway = PaymentGateway()
    print("UPI:", gateway.process_payment("upi", 99.00))

    try:
        gateway.process_payment("crypto", 100.00)
    except ValueError as e:
        print("Expected error:", e)

    try:
        gateway.process_payment(PaymentMethod.UPI, 0)
    except ValueError as e:
        print("Expected error:", e)
