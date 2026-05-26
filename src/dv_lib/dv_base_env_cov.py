# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_base_env_cov: Environment-level coverage component.

Mirrors ``dv_base_env_cov``. Same role as ``DVBaseAgentCov`` but at the
env level — passed to the scoreboard and virtual sequencer so any of
them can sample env-wide coverpoints.
"""
from __future__ import annotations

from typing import Any, Optional

from pyuvm import uvm_component, ConfigDB

from .dv_base_env_cfg import DVBaseEnvCfg


class DVBaseEnvCov(uvm_component):
    """Env coverage component."""

    def __init__(self, name: str = "dv_base_env_cov", parent=None) -> None:
        super().__init__(name, parent)
        self.cfg: Optional[DVBaseEnvCfg] = None

    def build_phase(self) -> None:
        super().build_phase()
        try:
            self.cfg = ConfigDB().get(self, "", "cfg")
        except Exception:
            self.cfg = None

    def sample(self, item: Any) -> None:
        if self.cfg is None or not self.cfg.en_cov:
            return
        self.do_sample(item)

    def do_sample(self, item: Any) -> None:  # pragma: no cover - abstract
        return
