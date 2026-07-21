"""External-network consecutive-failure circuit breaker (per turn / L1 fallback)."""



from __future__ import annotations



from dataclasses import dataclass, field

from typing import Any





@dataclass

class ExternalCircuit:

    """

    Track consecutive external (web / research) failures within one agent turn.

    When fail_streak >= threshold, further external calls are skipped → L1 only.

    """



    threshold: int = 2

    fail_streak: int = 0

    opened: bool = False

    skipped: list[str] = field(default_factory=list)

    failures: list[str] = field(default_factory=list)



    def record_success(self) -> None:

        self.fail_streak = 0



    def record_failure(self, tool: str, reason: str = "") -> None:

        self.fail_streak += 1

        note = f"{tool}:{reason}" if reason else tool

        self.failures.append(note[:120])

        if self.fail_streak >= max(1, self.threshold):

            self.opened = True



    def allow(self, tool: str) -> bool:

        if self.opened:

            self.skipped.append(tool)

            return False

        return True



    def to_meta(self) -> dict[str, Any]:

        return {

            "opened": self.opened,

            "fail_streak": self.fail_streak,

            "threshold": self.threshold,

            "failures": list(self.failures),

            "skipped": list(self.skipped),

        }





def external_call_failed(payload: dict[str, Any] | None) -> bool:

    """True only for real external errors (not merely empty search hits)."""

    if not payload:

        return True

    if payload.get("error"):

        return True

    errors = payload.get("errors") or []

    if errors:

        hits = payload.get("hits") or payload.get("results") or []

        if not hits:

            return True

    if payload.get("circuit_error"):

        return True

    return False


