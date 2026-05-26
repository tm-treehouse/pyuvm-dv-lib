# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_base_driver: Base class for agent drivers.

Mirrors ``dv_base_driver`` from dv_lib. The SV original is a typed
``uvm_driver`` with a cfg handle and a virtual ``run_phase`` that pulls
items from the sequencer and pushes them onto the bus.

In pyuvm the driver is naturally a coroutine. We provide the same shape
and the same hooks: :meth:`drive_item` is the per-transaction worker the
user overrides; the base ``run_phase`` deals with the seq_item port
plumbing.

The ``zero_delays`` knob from the agent cfg is honoured here: when it is
clear, the base inserts an inter-item delay (via cocotb's ``Timer``)
returned by :meth:`get_item_delay_ns`; when it is set, items are driven
back-to-back. Without a simulator the delay is skipped.
"""
from __future__ import annotations

from typing import Optional

from pyuvm import uvm_driver, ConfigDB

import cocotb
from cocotb.triggers import Timer

from .dv_base_agent_cfg import DVBaseAgentCfg
from .dv_base_seq_item import DVBaseSeqItem


class DVBaseDriver(uvm_driver):
    """Base driver. Override :meth:`drive_item`."""

    def __init__(self, name: str = "dv_base_driver", parent=None) -> None:
        super().__init__(name, parent)
        self.cfg: Optional[DVBaseAgentCfg] = None

    def build_phase(self) -> None:
        super().build_phase()
        try:
            self.cfg = ConfigDB().get(self, "", "cfg")
        except Exception:
            self.cfg = None

    async def run_phase(self) -> None:
        # Same pattern as the SV driver: reset, then loop forever.
        await self.reset_signals()
        while True:
            item = await self.seq_item_port.get_next_item()
            await self._maybe_delay()
            await self.drive_item(item)
            self.seq_item_port.item_done()

    # ------------------------------------------------------------------
    # zero_delays support
    # ------------------------------------------------------------------

    async def _maybe_delay(self) -> None:
        """Insert an inter-item delay unless ``cfg.zero_delays`` is set.

        The delay length comes from :meth:`get_item_delay_ns`. Honoured
        only under a live simulator; without one this is a no-op so
        unit tests don't stall.
        """
        if self.cfg is not None and self.cfg.zero_delays:
            return
        if not cocotb.is_simulation:
            return
        delay_ns = self.get_item_delay_ns()
        if delay_ns > 0:
            await Timer(delay_ns, "ns")

    def get_item_delay_ns(self) -> float:
        """Return the inter-item delay in ns. Default is 0 (no delay even
        when ``zero_delays`` is clear). Override to add fixed or
        randomized pacing between transactions.
        """
        return 0.0

    # ------------------------------------------------------------------
    # User overrides
    # ------------------------------------------------------------------

    async def reset_signals(self) -> None:
        """Drive the bus to its idle state. Default: do nothing."""
        return

    async def drive_item(self, item: DVBaseSeqItem) -> None:
        """Override in subclasses. ``item`` will be a transaction the
        sequence handed off via ``finish_item``.
        """
        return
