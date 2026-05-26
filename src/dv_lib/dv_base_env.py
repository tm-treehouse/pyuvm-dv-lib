# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_base_env: Top-level UVM environment.

The original SV class is parameterized on
``CFG_T``, ``COV_T``, ``VIRTUAL_SEQUENCER_T`` and ``SCOREBOARD_T`` and
its ``build_phase``:

* fetches the env cfg from ``uvm_config_db``,
* creates the virtual sequencer, scoreboard and coverage component,
* propagates cfg / cov to them.

We do the same with class-attribute "type parameters" so subclasses
can plug in their own concrete classes:

    class MyEnv(DVBaseEnv):
        cfg_type = MyEnvCfg
        cov_type = MyEnvCov
        scoreboard_type = MyScoreboard
        virtual_sequencer_type = MyVSeqr
"""
from __future__ import annotations

from typing import Optional, Type

from pyuvm import uvm_env, ConfigDB

from .dv_base_env_cfg import DVBaseEnvCfg
from .dv_base_env_cov import DVBaseEnvCov
from .dv_base_scoreboard import DVBaseScoreboard
from .dv_base_virtual_sequencer import DVBaseVirtualSequencer


class DVBaseEnv(uvm_env):
    """Composite env. Override the type-class attributes in subclasses."""

    cfg_type: Type[DVBaseEnvCfg] = DVBaseEnvCfg
    cov_type: Type[DVBaseEnvCov] = DVBaseEnvCov
    scoreboard_type: Type[DVBaseScoreboard] = DVBaseScoreboard
    virtual_sequencer_type: Type[DVBaseVirtualSequencer] = DVBaseVirtualSequencer

    def __init__(self, name: str = "dv_base_env", parent=None) -> None:
        super().__init__(name, parent)
        self.cfg: Optional[DVBaseEnvCfg] = None
        self.cov: Optional[DVBaseEnvCov] = None
        self.scoreboard: Optional[DVBaseScoreboard] = None
        self.virtual_sequencer: Optional[DVBaseVirtualSequencer] = None

    def build_phase(self) -> None:
        super().build_phase()

        # 1) cfg comes from the test, just like SV. If the test forgot
        #    to install one, materialise a default — same behaviour as
        #    ``dv_base_test`` when uvm_config_db::get fails.
        try:
            self.cfg = ConfigDB().get(self, "", "cfg")
        except Exception:
            self.cfg = self.cfg_type()
            self.cfg.initialize()

        # 2) push cfg one level down to env children.
        ConfigDB().set(self, "scoreboard", "cfg", self.cfg)
        ConfigDB().set(self, "virtual_sequencer", "cfg", self.cfg)
        ConfigDB().set(self, "cov", "cfg", self.cfg)

        # 3) cov first so we can publish it to the scoreboard / vseqr.
        if self.cfg.en_cov:
            self.cov = self.cov_type.create("cov", self)
            ConfigDB().set(self, "scoreboard", "cov", self.cov)
            ConfigDB().set(self, "virtual_sequencer", "cov", self.cov)

        # 4) Scoreboard. Always created; its check_phase self-gates on
        #    cfg.en_scb.
        self.scoreboard = self.scoreboard_type.create("scoreboard", self)

        # 5) Virtual sequencer. Always created; this is where vseqs run.
        self.virtual_sequencer = self.virtual_sequencer_type.create(
            "virtual_sequencer", self,
        )

    def connect_phase(self) -> None:
        super().connect_phase()
        # Subclasses connect their agent monitors' analysis ports to
        # scoreboard FIFOs here, and register agent sequencers with
        # ``self.virtual_sequencer.register_seqr(...)``. The base has
        # nothing to wire up.
