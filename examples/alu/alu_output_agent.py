"""
ALU output agent — passive monitor on the result port.

There is no driver: the output port is purely something we *observe*.
Setting ``cfg.is_active = UVM_PASSIVE`` makes :class:`DVBaseAgent`
skip driver/sequencer creation, leaving only the monitor.
"""
from __future__ import annotations

from typing import Optional

from dv_lib import (
    DVBaseAgent, DVBaseAgentCfg, DVBaseMonitor, DVBaseSeqItem,
    UVM_PASSIVE,
)

from .alu_dut import AluOutputVif


class AluOutputItem(DVBaseSeqItem):
    """One ALU result observation."""
    def __init__(self, name: str = "alu_output_item",
                 result: int = 0, valid: bool = False):
        super().__init__(name)
        self.result = result
        self.valid = valid


class AluOutputAgentCfg(DVBaseAgentCfg):
    def __init__(self, name: str = "alu_output_agent_cfg") -> None:
        super().__init__(name)
        # Default to passive — this agent has no driver.
        self.is_active = UVM_PASSIVE
        self.vif: Optional[AluOutputVif] = None


class AluOutputMonitor(DVBaseMonitor):
    """Reads the result port and broadcasts on analysis_port.

    Equivalent SV pattern: a forever loop that ``@(posedge clk)``s and
    samples ``cfg.vif.result`` / ``cfg.vif.result_valid``. In our toy
    model we just await the next AluOutputTxn from the queue.
    """
    async def collect_trans(self) -> None:
        assert self.cfg is not None and self.cfg.vif is not None
        while True:
            txn = await self.cfg.vif.get()
            item = AluOutputItem(result=txn.result, valid=txn.valid)
            self.write_and_sample(item)


class AluOutputAgent(DVBaseAgent):
    """Passive agent. No driver / sequencer instantiated."""
    cfg_type = AluOutputAgentCfg
    monitor_type = AluOutputMonitor
