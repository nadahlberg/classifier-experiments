from django.core.checks import CheckMessage, Error

EXEMPTIONS: dict[str, frozenset[str]] = {}

STALE_EXEMPTION_RULE = (
    "A stale exemption is itself an error, so the list ratchets down "
    "instead of accreting."
)


def pattern_error(check_id: str, obj: str, claim: str, rule: str) -> Error:
    """One pattern violation, its message quoting the rule it enforces."""
    return Error(
        claim,
        hint=f'CLAUDE.md: "{rule}"',
        obj=obj,
        id=f"app.{check_id}",
    )


class ExemptionLog:
    """Tracks which EXEMPTIONS entries matched during one check run."""

    def __init__(
        self, exemptions: dict[str, frozenset[str]] | None = None
    ) -> None:
        self.exemptions = EXEMPTIONS if exemptions is None else exemptions
        self.used: set[tuple[str, str]] = set()

    def allows(self, check_id: str, ident: str) -> bool:
        """Whether the violation is exempt, recording the hit."""
        if ident in self.exemptions.get(check_id, frozenset()):
            self.used.add((check_id, ident))
            return True
        return False

    def stale(self) -> list[CheckMessage]:
        """An E801 error for every exemption that matched nothing."""
        messages: list[CheckMessage] = []
        for check_id, idents in sorted(self.exemptions.items()):
            for ident in sorted(idents):
                if (check_id, ident) not in self.used:
                    messages.append(
                        pattern_error(
                            "E801",
                            ident,
                            f"The {check_id} exemption for {ident} matches "
                            f"nothing any more; delete it.",
                            STALE_EXEMPTION_RULE,
                        )
                    )
        return messages
