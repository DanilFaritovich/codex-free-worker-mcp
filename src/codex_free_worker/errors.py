class WorkerExecutionError(RuntimeError):
    """Raised when an execution backend cannot produce a valid worker result."""


class InvalidWorkerReport(WorkerExecutionError):
    """A bounded report rejected by validation; payload must never be logged."""

    def __init__(self, payload: str, diagnostic: str, *, repairable: bool) -> None:
        super().__init__(f"Worker returned an invalid compact JSON result: {diagnostic}")
        self.payload = payload
        self.diagnostic = diagnostic
        self.repairable = repairable
