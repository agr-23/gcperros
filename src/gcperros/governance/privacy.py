"""Seudonimización de los datos de usuario desde la ingestión (historia #27).

Detrás de un identificador de sesión y de los mercados que alguien sigue hay una
persona real: es lo único del sistema a lo que aplican la Ley 1581 de 2012 y el
RGPD. De esta frontera sólo sale la versión seudonimizada, con HMAC-SHA256 y una
clave que sólo vive en el entorno; lo crudo no se reenvía, no se registra y no se
archiva. Por qué con clave y no un hash: ``docs/decisiones-de-diseno.md``, §16.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from gcperros.core.contracts import MARKET_OUTCOMES, ContractViolationError, parse_event_time

#: Variable de entorno de la que se lee la clave, en hexadecimal.
KEY_ENV = "GCPERROS_PSEUDONYM_KEY"

#: Longitud mínima de la clave: la del propio resumen de SHA-256.
MIN_KEY_BYTES = 32


class Pseudonymizer:
    """Convierte un valor en un seudónimo estable que sin la clave no se revierte."""

    __slots__ = ("_key",)

    def __init__(self, key: bytes) -> None:
        """Crea el seudonimizador con su clave.

        Raises:
            ValueError: Si la clave es más corta que ``MIN_KEY_BYTES``.
        """
        if len(key) < MIN_KEY_BYTES:
            raise ValueError(f"la clave debe tener al menos {MIN_KEY_BYTES} bytes")
        self._key = key

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> Pseudonymizer:
        """Lee la clave del entorno. Sin clave no hay ingestión: no hay valor por defecto.

        Raises:
            ValueError: Si la variable falta o no es hexadecimal.
        """
        if KEY_ENV not in environ:
            raise ValueError(f"falta {KEY_ENV}: sin clave no se ingieren datos de usuario")
        return cls(bytes.fromhex(environ[KEY_ENV]))

    def pseudonym(self, purpose: str, value: str) -> str:
        """Seudónimo de ``value`` para un propósito concreto."""
        message = f"{purpose}\x00{value}".encode()
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def __repr__(self) -> str:
        """Nunca enseña la clave, ni en un registro ni en una traza de error."""
        return "Pseudonymizer(clave=<oculta>)"


@dataclass(frozen=True, slots=True)
class PseudonymousActivity:
    """Lo único que sale de la frontera: la actividad sin nadie reconocible detrás."""

    session: str
    markets: tuple[str, ...]
    match_id: str
    event_time: datetime


class UserActivityGate:
    """Frontera de la actividad de usuario.

    A diferencia de la de los flujos deportivos (HU-16), **no archiva lo que
    rechaza**: el repositorio de inválidos guarda el mensaje crudo como evidencia,
    y aquí eso sería guardar la sesión en claro. Lo rechazado sólo se cuenta.
    """

    __slots__ = ("_pseudonymizer", "admitted", "rejected")

    def __init__(self, pseudonymizer: Pseudonymizer) -> None:
        """Crea la frontera con el seudonimizador que usará."""
        self._pseudonymizer = pseudonymizer
        self.admitted = 0
        self.rejected: dict[str, int] = {}

    def admit(self, message: bytes | str) -> PseudonymousActivity | None:
        """Seudonimiza un mensaje conforme, o lo cuenta como rechazado y lo olvida."""
        try:
            payload = json.loads(message)
            activity = self._pseudonymize(payload)
        except (ValueError, TypeError, AttributeError) as error:
            # El motivo nombra el campo, nunca su valor: ni el rechazo deja rastro.
            reason = "event_time" if isinstance(error, ContractViolationError) else "malformed"
            reason = str(error) if isinstance(error, _RejectionError) else reason
            self.rejected[reason] = self.rejected.get(reason, 0) + 1
            return None
        self.admitted += 1
        return activity

    def _pseudonymize(self, payload: dict[str, object]) -> PseudonymousActivity:
        session, match_id, stamp = (
            _text(payload, f) for f in ("session_id", "match_id", "event_time")
        )
        markets = payload.get("markets")
        if not isinstance(markets, list) or not set(markets) <= set(MARKET_OUTCOMES):
            raise _RejectionError("markets")
        return PseudonymousActivity(
            session=self._pseudonymizer.pseudonym("session", session),
            markets=tuple(sorted({self._pseudonymizer.pseudonym("market", m) for m in markets})),
            match_id=match_id,
            event_time=parse_event_time(stamp),
        )


def _text(payload: dict[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise _RejectionError(field)
    return value


class _RejectionError(ValueError):
    """Motivo de rechazo. Nombra el campo, nunca su valor."""
