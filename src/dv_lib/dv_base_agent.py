# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_base_agent: Composite UVM agent.

The original SV class wires up the standard set of subcomponents:

* always create the **monitor**, store its ``analysis_port`` so the env
  can hook a scoreboard/coverage to it,
* if ``cfg.is_active == UVM_ACTIVE``, also create a **sequencer** and a
  **driver** and connect their seq_item interfaces,
* if ``cfg.en_cov``, also create a coverage component,
* propagate ``cfg`` down to all of those via ``uvm_config_db``.

This Python version takes class-attribute "type parameters" instead of
SV's ``#(type CFG_T = …)`` template parameters: subclasses set
``cfg_type``, ``driver_type``, ``monitor_type``, ``sequencer_type`` and
``cov_type`` to the concrete classes they want, and the base
``build_phase`` does the rest.
"""
from __future__ import annotations

from typing import Optional, Type

from pyuvm import uvm_agent, ConfigDB

from .dv_base_agent_cfg import DVBaseAgentCfg
from .dv_base_agent_cov import DVBaseAgentCov
from .dv_base_driver import DVBaseDriver
from .dv_base_monitor import DVBaseMonitor
from .dv_base_sequencer import DVBaseSequencer


class DVBaseAgent(uvm_agent):
    """Composite agent. Override the type-class attributes in subclasses.

    Example::

        class MyAgent(DVBaseAgent):
            cfg_type = MyAgentCfg
            driver_type = MyDriver
            monitor_type = MyMonitor
            cov_type = MyAgentCov
    """

    # "Type parameters" — override in subclasses if you want IP-specific
    # types. Defaults give a perfectly serviceable skeleton agent.
    cfg_type: Type[DVBaseAgentCfg] = DVBaseAgentCfg
    driver_type: Type[DVBaseDriver] = DVBaseDriver
    monitor_type: Type[DVBaseMonitor] = DVBaseMonitor
    sequencer_type: Type[DVBaseSequencer] = DVBaseSequencer
    cov_type: Type[DVBaseAgentCov] = DVBaseAgentCov

    def __init__(self, name: str = "dv_base_agent", parent=None) -> None:
        super().__init__(name, parent)
        self.cfg: Optional[DVBaseAgentCfg] = None
        self.driver: Optional[DVBaseDriver] = None
        self.monitor: Optional[DVBaseMonitor] = None
        self.sequencer: Optional[DVBaseSequencer] = None
        self.cov: Optional[DVBaseAgentCov] = None

    def build_phase(self) -> None:
        super().build_phase()

        # 1) Resolve cfg. The env / test sets this with
        #    ConfigDB().set(self, "agent_path", "cfg", cfg_obj)
        try:
            self.cfg = ConfigDB().get(self, "", "cfg")
        except Exception:
            # No cfg? Build a default so users can still run a smoke
            # bringup, just like the SV original does with ``new()``.
            self.cfg = self.cfg_type()

        # 2) Re-publish cfg one level down so children pick it up.
        ConfigDB().set(self, "monitor", "cfg", self.cfg)
        ConfigDB().set(self, "driver", "cfg", self.cfg)
        ConfigDB().set(self, "sequencer", "cfg", self.cfg)
        ConfigDB().set(self, "cov", "cfg", self.cfg)

        # 3) Always-on subcomponents.
        self.monitor = self.monitor_type.create("monitor", self)

        # 4) Active-only subcomponents.
        if self.cfg.active:
            self.sequencer = self.sequencer_type.create("sequencer", self)
            self.driver = self.driver_type.create("driver", self)

        # 5) Coverage is optional and orthogonal to active/passive.
        if self.cfg.en_cov:
            self.cov = self.cov_type.create("cov", self)
            ConfigDB().set(self, "monitor", "cov", self.cov)

    def connect_phase(self) -> None:
        super().connect_phase()
        # Wire driver <-> sequencer for active agents. pyuvm's driver
        # has ``seq_item_port`` and the sequencer has ``seq_item_export``.
        if self.cfg is not None and self.cfg.active:
            assert self.driver is not None and self.sequencer is not None
            self.driver.seq_item_port.connect(self.sequencer.seq_item_export)
