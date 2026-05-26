# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_clk_rst: A small cocotb-aware clock/reset interface.

In SystemVerilog dv_lib, ``dv_base_env_cfg`` carries a ``virtual
clk_rst_if`` and the base vseq's ``apply_reset`` drives it. cocotb has
first-class primitives for exactly this — :class:`cocotb.clock.Clock`
and edge triggers — so this module wraps them in a small interface that:

* starts a free-running clock on a cocotb clock signal,
* drives an (optionally active-low) reset for a number of cycles,
* exposes ``wait_clks`` / edge helpers sequences can await.

Everything is guarded by :data:`cocotb.is_simulation`. Under a live
simulator the real cocotb primitives run; under plain pytest (no
simulator) the methods become awaitable no-ops so the library and its
unit tests still work without a DUT.

Typical wiring in a cocotb test entry point::

    from dv_lib.dv_clk_rst import ClkRstIf
    cfg.clk_rst_vif = ClkRstIf(dut.clk, dut.rst_n, period_ns=10,
                               reset_active_low=True)
    cfg.clk_rst_vif.start_clk()

Then a base vseq's ``apply_reset`` will drive reset through it
automatically.
"""
from __future__ import annotations

from typing import Any, Optional

import cocotb


class ClkRstIf:
    """Wraps a cocotb clock + reset signal pair.

    Parameters
    ----------
    clk:
        The cocotb clock signal handle (e.g. ``dut.clk``). May be
        ``None`` for the no-simulator path.
    rst:
        The cocotb reset signal handle (e.g. ``dut.rst_n``). May be
        ``None``.
    period_ns:
        Clock period in nanoseconds.
    reset_active_low:
        If True (the common OpenTitan convention, ``rst_ni``), the
        asserted reset value is 0 and the deasserted value is 1. If
        False, it's the other way round.
    """

    def __init__(
        self,
        clk: Any = None,
        rst: Any = None,
        period_ns: float = 10.0,
        reset_active_low: bool = True,
    ) -> None:
        self.clk = clk
        self.rst = rst
        self.period_ns = period_ns
        self.reset_active_low = reset_active_low
        self._clock = None  # cocotb.clock.Clock handle once started
        self._clock_task = None

    # ----- reset polarity helpers --------------------------------------

    @property
    def _asserted(self) -> int:
        return 0 if self.reset_active_low else 1

    @property
    def _deasserted(self) -> int:
        return 1 if self.reset_active_low else 0

    # ----- clock -------------------------------------------------------

    def start_clk(self) -> None:
        """Start a free-running clock on ``self.clk``.

        No-op when there's no simulator or no clock handle. Safe to call
        once; calling again is ignored if a clock is already running.
        """
        if not cocotb.is_simulation or self.clk is None:
            return
        if self._clock is not None:
            return
        # Imported lazily so the module imports cleanly with no sim.
        from cocotb.clock import Clock

        self._clock = Clock(self.clk, self.period_ns, unit="ns")
        # Clock.start() returns a task that drives the signal forever.
        self._clock_task = cocotb.start_soon(self._clock.start())

    def stop_clk(self) -> None:
        """Stop the free-running clock if one is running."""
        if self._clock_task is not None:
            try:
                self._clock_task.kill()
            except Exception:
                pass
            self._clock_task = None
            self._clock = None

    # ----- edges / waits -----------------------------------------------

    async def wait_clks(self, n: int = 1) -> None:
        """Wait for ``n`` rising edges of the clock.

        No-op (returns immediately) without a simulator or clock.
        """
        if not cocotb.is_simulation or self.clk is None:
            return
        from cocotb.triggers import ClockCycles

        await ClockCycles(self.clk, n)

    async def wait_rising_edge(self) -> None:
        if not cocotb.is_simulation or self.clk is None:
            return
        from cocotb.triggers import RisingEdge

        await RisingEdge(self.clk)

    # ----- reset -------------------------------------------------------

    async def apply_reset(
        self,
        reset_cycles: int = 5,
        pre_cycles: int = 1,
    ) -> None:
        """Drive a reset pulse.

        Holds reset asserted for ``reset_cycles`` clocks (after an
        optional ``pre_cycles`` settling period), then deasserts. With
        no simulator this is an awaitable no-op.
        """
        if not cocotb.is_simulation or self.rst is None:
            return

        # Settle, assert, hold, deassert — the canonical reset shape.
        if pre_cycles:
            await self.wait_clks(pre_cycles)
        self.rst.value = self._asserted
        await self.wait_clks(reset_cycles)
        self.rst.value = self._deasserted
        # One more edge so downstream logic sees the deasserted value.
        await self.wait_clks(1)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"ClkRstIf(period_ns={self.period_ns}, "
            f"reset_active_low={self.reset_active_low}, "
            f"clk={'set' if self.clk is not None else 'None'}, "
            f"rst={'set' if self.rst is not None else 'None'})"
        )
