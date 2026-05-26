# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_base_monitor: Base class for monitors in dv_lib agents.

The original SV ``dv_base_monitor`` extends ``uvm_monitor``, holds:

* a ``cfg`` handle to the agent cfg,
* a ``cov`` handle to the agent coverage component,
* an ``analysis_port`` to broadcast observed transactions,
* and a ``run_phase`` that calls a virtual ``collect_trans`` task in a
  forever loop.

We replicate that almost exactly. pyuvm's :class:`uvm_monitor` already
gives us an ``analysis_port`` attribute when we declare one, but we wire
it up explicitly so that the structure is visible.
"""
from __future__ import annotations

from typing import Any, Optional

from pyuvm import uvm_monitor, uvm_analysis_port, ConfigDB

from .dv_base_agent_cfg import DVBaseAgentCfg
from .dv_base_agent_cov import DVBaseAgentCov


class DVBaseMonitor(uvm_monitor):
    """Base monitor.

    Extended classes typically only need to override
    :meth:`collect_trans`, which is the analogue of the SV
    ``collect_trans`` task. Each transaction yielded should be written
    to ``self.analysis_port`` and forwarded to ``self.cov.sample``.
    """

    def __init__(self, name: str = "dv_base_monitor", parent=None) -> None:
        super().__init__(name, parent)
        self.cfg: Optional[DVBaseAgentCfg] = None
        self.cov: Optional[DVBaseAgentCov] = None
        self.analysis_port: Optional[uvm_analysis_port] = None

    def build_phase(self) -> None:
        super().build_phase()
        self.analysis_port = uvm_analysis_port("analysis_port", self)
        try:
            self.cfg = ConfigDB().get(self, "", "cfg")
        except Exception:
            self.cfg = None
        # cov is optional and may be None if the agent is passive.
        try:
            self.cov = ConfigDB().get(self, "", "cov")
        except Exception:
            self.cov = None

    # ------------------------------------------------------------------
    # The monitor's run loop. SV does this with a fork/join_none of the
    # collect_trans task, but pyuvm's run_phase is already an async
    # coroutine, so a single await is enough.
    # ------------------------------------------------------------------

    async def run_phase(self) -> None:
        # Match the SV gate: don't sample anything if the user has
        # globally disabled the monitor for this agent.
        if self.cfg is not None and not self.cfg.en_monitor:
            return
        await self.collect_trans()

    async def collect_trans(self) -> None:
        """Override in subclasses. Should loop forever, sampling the bus
        and writing observed items to ``self.analysis_port``.

        The base implementation just returns — there is no bus to look at
        in the framework itself.
        """
        return

    # Helper subclasses call once per transaction. Centralising it means
    # the gating on ``en_cov`` lives in one place.
    def write_and_sample(self, item: Any) -> None:
        if self.analysis_port is not None:
            self.analysis_port.write(item)
        if self.cov is not None:
            self.cov.sample(item)
