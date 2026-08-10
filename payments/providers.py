import random
import uuid
from abc import ABC, abstractmethod
from django.conf import settings
from django.utils.module_loading import import_string


class PaymentResult:
    def __init__(self, success: bool, payment_id: str = None, error: str = None):
        self.success = success
        self.payment_id = payment_id
        self.error = error


class PaymentProvider(ABC):
    name: str

    @abstractmethod
    def capture(self, amount_cents: int, token: str, idempotency_key: str) -> PaymentResult:
        pass

    @abstractmethod
    def refund(self, payment_id: str, amount_cents: int) -> PaymentResult:
        pass


class FakePaymentProvider(PaymentProvider):
    name = 'fake'
    force_success = True  # Deterministic success for tests and dev

    def capture(self, amount_cents: int, token: str, idempotency_key: str) -> PaymentResult:
        if self.force_success or random.random() < 0.9:
            return PaymentResult(success=True, payment_id=f"fake_pay_{uuid.uuid4().hex[:12]}")
        return PaymentResult(success=False, error="Simulated payment decline")

    def refund(self, payment_id: str, amount_cents: int) -> PaymentResult:
        return PaymentResult(success=True, payment_id=f"fake_ref_{uuid.uuid4().hex[:12]}")


class PaymobPaymentProvider(PaymentProvider):
    """
    Paymob Accept API integration stub.
    API keys loaded from environment variables.
    """
    name = 'paymob'

    def capture(self, amount_cents: int, token: str, idempotency_key: str) -> PaymentResult:
        raise NotImplementedError("Paymob integration pending production credentials")

    def refund(self, payment_id: str, amount_cents: int) -> PaymentResult:
        raise NotImplementedError("Paymob refund integration pending production credentials")


def get_payment_provider() -> PaymentProvider:
    provider_class = import_string(settings.PAYMENT_PROVIDER_CLASS)
    return provider_class()
