"""A preview failure whose reason the model and the person must see.

`confirmations._build_preview` swallows ordinary preview exceptions (a preview
never blocks a park, or falls back to argument rows). A `PreviewRefusal` is
different: it carries a Solus-composed, already-sanitised `safe_message` and
REFUSES the call — nothing is parked or applied — so SOL learns why (the code
server's plan reason, an exhausted Onshape quota) instead of a generic failure.
"""

from __future__ import annotations

from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.agent.tools.tool import ToolException


class PreviewRefusal(ToolException):
    def __init__(self, safe_message: str, *, code: ToolErrorCode = ToolErrorCode.UNAVAILABLE):
        self.safe_message = safe_message
        super().__init__(safe_message, code=code, retryable=False)
