# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_base_scoreboard: Base scoreboard.

The original SV class is parameterized as

    class dv_base_scoreboard #(type RAL_T = dv_base_reg_block,
                               type CFG_T = dv_base_env_cfg,
                               type COV_T = dv_base_env_cov)
        extends uvm_scoreboard;

and adds a ``cfg`` / ``ral`` / ``cov`` handle plus the standard
``check_phase`` hook. The ``en_scb`` knob on the env cfg gates
checking, so the SV ``check_phase`` early-returns if it's clear.

We keep all that in the Python port. pyuvm provides
:class:`uvm_scoreboard`, which is just a marker subclass of
``uvm_component`` — exactly like SV.
"""
from __future__ import annotations

from typing import Optional

from pyuvm import uvm_scoreboard, uvm_tlm_analysis_fifo, ConfigDB

from .dv_base_env_cfg import DVBaseEnvCfg
from .dv_base_env_cov import DVBaseEnvCov
from .dv_base_reg_block import DVBaseRegBlock


class DVBaseScoreboard(uvm_scoreboard):
    """Base scoreboard. Override :meth:`check_phase` and / or wire up
    analysis FIFOs for the agents you care about.
    """

    def __init__(self, name: str = "dv_base_scoreboard", parent=None) -> None:
        super().__init__(name, parent)
        self.cfg: Optional[DVBaseEnvCfg] = None
        self.cov: Optional[DVBaseEnvCov] = None
        self.ral: Optional[DVBaseRegBlock] = None

    def build_phase(self) -> None:
        super().build_phase()
        try:
            self.cfg = ConfigDB().get(self, "", "cfg")
        except Exception:
            self.cfg = None
        try:
            self.cov = ConfigDB().get(self, "", "cov")
        except Exception:
            self.cov = None
        if self.cfg is not None:
            self.ral = self.cfg.ral

    # ------------------------------------------------------------------
    # Convenience for subclasses: build an analysis FIFO and remember it.
    # SV scoreboards do this with ad-hoc ``uvm_tlm_analysis_fifo``
    # creations in build_phase. Centralising it makes the Python code a
    # little tidier.
    # ------------------------------------------------------------------
    def make_fifo(self, name: str) -> uvm_tlm_analysis_fifo:
        return uvm_tlm_analysis_fifo(name, self)

    # ------------------------------------------------------------------
    # check_phase: gated on en_scb. Subclasses override do_check.
    # ------------------------------------------------------------------
    def check_phase(self) -> None:
        super().check_phase()
        if self.cfg is not None and not self.cfg.en_scb:
            return
        self.do_check()

    def do_check(self) -> None:  # pragma: no cover - abstract
        """Override to add end-of-test checks (queues empty, counts match,
        etc.). The base class does nothing.
        """
        return
