"""Harbor external-agent wrapper used through ``qfbench2 track1 run``."""

from __future__ import annotations

import base64
import pathlib
import shlex

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext


class ExemplarAgent(BaseAgent):
    """Upload the deterministic exemplar solver as an inline Python process."""

    @staticmethod
    def name() -> str:
        return "qfbench2-exemplar-agent"

    def version(self) -> str:
        return "1.0.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        del environment

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        del instruction
        source = pathlib.Path(__file__).with_name("solve.py").read_bytes()
        encoded = base64.b64encode(source).decode("ascii")
        program = (
            "import base64; ns={'__name__':'qfbench2_exemplar'}; "
            f"exec(base64.b64decode({encoded!r}), ns); "
            "ns['solve']('/app', '/app/output')"
        )
        result = await environment.exec(command=f"python -c {shlex.quote(program)}")
        if result.return_code != 0:
            raise RuntimeError("the exemplar solver failed inside the task environment")
        context.metadata = {
            "example": True,
            "supported_task": "t1-EXAMPLE-bs-greeks-pde",
        }
