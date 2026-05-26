# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_base_sequencer: Base sequencer for agents.

The original SV ``dv_base_sequencer`` is a thin ``uvm_sequencer`` that
holds a ``cfg`` handle so sequences can reach knobs via
``p_sequencer.cfg.<knob>``. There's nothing else interesting about it,
which is why the OpenTitan ``uvmdvgen`` tool typedefs ``dv_base_sequencer``
directly for most agents instead of subclassing.

We do the same in Python.
"""
from __future__ import annotations

from typing import Optional

from pyuvm import uvm_sequencer, ConfigDB

from .dv_base_agent_cfg import DVBaseAgentCfg


class DVBaseSequencer(uvm_sequencer):
    """Sequencer that exposes ``cfg`` to running sequences."""

    def __init__(self, name: str = "dv_base_sequencer", parent=None) -> None:
        super().__init__(name, parent)
        self.cfg: Optional[DVBaseAgentCfg] = None

    def build_phase(self) -> None:
        super().build_phase()
        try:
            self.cfg = ConfigDB().get(self, "", "cfg")
        except Exception:
            self.cfg = None
