"""
ALU input agent — active host.

The agent drives ``operand_a / operand_b / opcode`` into the DUT. It's
the only active agent in this testbench: the result and status agents
are passive (monitor-only).

This file shows how the dv_lib base classes line up with one I/O port
of the DUT:

* :class:`AluInputItem` — sequence item carrying the bus payload.
* :class:`AluInputAgentCfg` — agent cfg, parameterised from the env.
  The ``vif`` field holds the input "virtual interface".
* :class:`AluInputDriver` — pulls items from the sequencer and pushes
  them onto ``cfg.vif``.
* :class:`AluInputMonitor` — also taps ``cfg.vif`` (in this toy model
  by piggy-backing on the driver via an analysis port). In a real
  testbench the monitor would observe the bus directly.
* :class:`AluInputAgent` — wires the four together and exposes
  ``analysis_port`` so the scoreboard can subscribe.
"""
from __future__ import annotations

from typing import Optional

from pyuvm import uvm_analysis_port

from dv_lib import (
    DVBaseAgent, DVBaseAgentCfg, DVBaseDriver, DVBaseMonitor, DVBaseSeqItem,
)

from .alu_dut import AluInputTxn, AluInputVif


# ---- Sequence item --------------------------------------------------

class AluInputItem(DVBaseSeqItem):
    """One ALU input transaction.

    Equivalent role to an SV ``alu_input_item extends dv_base_seq_item``
    with three rand fields. We just expose them as Python attributes.
    """
    def __init__(self, name: str = "alu_input_item",
                 operand_a: int = 0, operand_b: int = 0, opcode: int = 0):
        super().__init__(name)
        self.operand_a = operand_a
        self.operand_b = operand_b
        self.opcode = opcode


# ---- Agent cfg ------------------------------------------------------

class AluInputAgentCfg(DVBaseAgentCfg):
    """Adds the typed ``vif`` handle on top of the dv_lib defaults.

    We override the type for clarity — Python doesn't enforce it, but
    it documents intent.
    """
    def __init__(self, name: str = "alu_input_agent_cfg") -> None:
        super().__init__(name)
        self.vif: Optional[AluInputVif] = None


# ---- Driver ---------------------------------------------------------

class AluInputDriver(DVBaseDriver):
    """Drives input items onto the DUT's input bus.

    ``drive_item`` is the only thing the user normally writes — the
    surrounding loop (get_next_item / item_done) lives in
    :class:`DVBaseDriver`.
    """

    def __init__(self, name: str = "alu_input_driver", parent=None) -> None:
        super().__init__(name, parent)
        # A side channel so the monitor can mirror what the driver did
        # without us needing a real bus to sample. In real RTL the
        # monitor would just sniff cfg.vif directly.
        self._mirror_port: Optional[uvm_analysis_port] = None

    def set_mirror_port(self, port: uvm_analysis_port) -> None:
        self._mirror_port = port

    async def drive_item(self, item: AluInputItem) -> None:
        assert self.cfg is not None and self.cfg.vif is not None, \
            "input agent vif not configured"
        txn = AluInputTxn(item.operand_a, item.operand_b, item.opcode)
        await self.cfg.vif.put(txn)
        # Mirror the item to the monitor for analysis-port broadcasting.
        if self._mirror_port is not None:
            self._mirror_port.write(item)


# ---- Monitor --------------------------------------------------------

class AluInputMonitor(DVBaseMonitor):
    """Receives mirrored items from the driver and rebroadcasts them.

    In a real testbench this would be ``async def collect_trans()``
    sampling cfg.vif on each clock — but the loop topology (``while
    True: read_bus(); analysis_port.write(item)``) is identical.
    """
    pass


# ---- Agent ----------------------------------------------------------

class AluInputAgent(DVBaseAgent):
    """Composite agent. The dv_lib base does the heavy lifting — we
    only set the type-class attributes and add the driver-monitor
    mirror wire.
    """
    cfg_type = AluInputAgentCfg
    driver_type = AluInputDriver
    monitor_type = AluInputMonitor

    def connect_phase(self) -> None:
        super().connect_phase()
        # Hand the driver a handle to the monitor's analysis_port so it
        # can mirror items we drive. Only meaningful when active.
        if self.cfg is not None and self.cfg.active:
            assert self.driver is not None and self.monitor is not None
            assert self.monitor.analysis_port is not None
            self.driver.set_mirror_port(self.monitor.analysis_port)
