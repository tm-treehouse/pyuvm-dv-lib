# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_base_sequence: Base sequence for agent-level sequences.

The original SV ``dv_base_sequence`` extends ``uvm_sequence`` and just
adds ``cfg`` lookup and a ``p_sequencer`` typedef. Sequences in pyuvm
inherit from ``uvm_sequence`` and reach their sequencer through
``self.sequencer`` (set by ``start``), so we expose the ``cfg`` shortcut
there.
"""
from __future__ import annotations

from typing import Any, Optional

from pyuvm import uvm_sequence

from .dv_base_agent_cfg import DVBaseAgentCfg


class DVBaseSequence(uvm_sequence):
    """Base for any sequence that wants the agent cfg in scope."""

    def __init__(self, name: str = "dv_base_sequence") -> None:
        super().__init__(name)

    @property
    def cfg(self) -> Optional[DVBaseAgentCfg]:
        """Return the cfg held by the sequencer this sequence runs on,
        or ``None`` if the sequence isn't started yet / the sequencer
        has no cfg.
        """
        seqr: Optional[Any] = getattr(self, "sequencer", None)
        if seqr is None:
            return None
        return getattr(seqr, "cfg", None)

    @property
    def p_sequencer(self) -> Optional[Any]:
        """Mirror of the SV ``p_sequencer`` handle. In SystemVerilog
        ``p_sequencer`` is a typed pointer set up by `uvm_declare_p_sequencer`;
        in Python it's just an alias for the sequencer the sequence runs on.
        """
        return getattr(self, "sequencer", None)

    async def body(self) -> None:  # pragma: no cover - abstract
        return
