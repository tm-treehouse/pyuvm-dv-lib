# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_base_agent_cov: Coverage component for an agent.

Mirrors ``dv_base_agent_cov`` from dv_lib. The SV original is a
``uvm_component`` that gets the agent cfg via ``uvm_config_db`` and houses
the agent's covergroups; the user samples them from the monitor.

pyuvm doesn't have native covergroups, so this is a thin component that:

* fetches the cfg object from ``ConfigDB``,
* offers a :meth:`sample` hook the monitor calls with each transaction,
* gates everything on ``cfg.en_cov``.

A real port would lean on a Python coverage tool (cocotb-coverage, vcov,
funcov, ...). We don't pick one for the user — the hook is just a stub.
"""
from __future__ import annotations

from typing import Any, Optional

from pyuvm import uvm_component, ConfigDB

from .dv_base_agent_cfg import DVBaseAgentCfg


class DVBaseAgentCov(uvm_component):
    """Per-agent coverage component."""

    def __init__(self, name: str = "dv_base_agent_cov", parent=None) -> None:
        super().__init__(name, parent)
        self.cfg: Optional[DVBaseAgentCfg] = None

    def build_phase(self) -> None:
        super().build_phase()
        # Fetch the cfg the agent installed for us. Match pyuvm's idiom:
        # pull from ConfigDB at the same scope the agent set it.
        try:
            self.cfg = ConfigDB().get(self, "", "cfg")
        except Exception:
            # Coverage is optional; if the testbench didn't install a
            # cfg we just stay disabled rather than fatal-ing out.
            self.cfg = None

    # ------------------------------------------------------------------
    # Hook for the monitor / driver. Override in IP-specific subclasses
    # to actually sample covergroups, e.g. with cocotb-coverage.
    # ------------------------------------------------------------------
    def sample(self, item: Any) -> None:
        if self.cfg is None or not self.cfg.en_cov:
            return
        self.do_sample(item)

    def do_sample(self, item: Any) -> None:  # pragma: no cover - abstract
        """User hook. No-op in the base class."""
