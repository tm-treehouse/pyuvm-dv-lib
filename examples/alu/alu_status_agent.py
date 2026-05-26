"""
ALU status agent — passive monitor on the (overflow, zero) status pins.

Almost identical to the output agent. We split it out to show the
"multiple passive agents" pattern: each one is a tiny class because
the dv_lib base provides everything common.
"""
from __future__ import annotations

from typing import Optional

from dv_lib import (
    DVBaseAgent, DVBaseAgentCfg, DVBaseMonitor, DVBaseSeqItem,
    UVM_PASSIVE,
)

from .alu_dut import AluStatusVif


class AluStatusItem(DVBaseSeqItem):
    def __init__(self, name: str = "alu_status_item",
                 overflow: bool = False, zero: bool = False):
        super().__init__(name)
        self.overflow = overflow
        self.zero = zero


class AluStatusAgentCfg(DVBaseAgentCfg):
    def __init__(self, name: str = "alu_status_agent_cfg") -> None:
        super().__init__(name)
        self.is_active = UVM_PASSIVE
        self.vif: Optional[AluStatusVif] = None


class AluStatusMonitor(DVBaseMonitor):
    async def collect_trans(self) -> None:
        assert self.cfg is not None and self.cfg.vif is not None
        while True:
            txn = await self.cfg.vif.get()
            item = AluStatusItem(overflow=txn.overflow, zero=txn.zero)
            self.write_and_sample(item)


class AluStatusAgent(DVBaseAgent):
    cfg_type = AluStatusAgentCfg
    monitor_type = AluStatusMonitor
