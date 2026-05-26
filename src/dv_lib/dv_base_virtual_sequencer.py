# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_base_virtual_sequencer: Holds handles to every agent sequencer.

Mirrors ``dv_base_virtual_sequencer``. The SV class is a
``uvm_sequencer`` parameterized on ``REQ`` (often ``uvm_sequence_item``)
that holds typed handles to each agent's sequencer plus a ``cfg``
handle, so virtual sequences can do
``p_sequencer.<agent>_seqr.start(...)``.

In Python we keep a ``sub_seqrs`` dict so virtual sequences can do
``self.p_sequencer.sub_seqrs[name].start(...)`` without needing typed
attributes for every agent.
"""
from __future__ import annotations

from typing import Dict, Optional

from pyuvm import uvm_sequencer, ConfigDB

from .dv_base_env_cfg import DVBaseEnvCfg
from .dv_base_env_cov import DVBaseEnvCov
from .dv_base_sequencer import DVBaseSequencer


class DVBaseVirtualSequencer(uvm_sequencer):
    """Virtual sequencer.

    Subclasses can also add typed attributes (``self.uart_seqr``,
    ``self.tl_seqr``, ...) for ergonomics; the dict is the universal
    fallback.
    """

    def __init__(self, name: str = "dv_base_virtual_sequencer", parent=None) -> None:
        super().__init__(name, parent)
        self.cfg: Optional[DVBaseEnvCfg] = None
        self.cov: Optional[DVBaseEnvCov] = None
        self.sub_seqrs: Dict[str, DVBaseSequencer] = {}

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

    def register_seqr(self, key: str, seqr: DVBaseSequencer) -> None:
        self.sub_seqrs[key] = seqr
