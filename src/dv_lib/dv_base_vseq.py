# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_base_vseq: Base virtual sequence.

The OpenTitan ``dv_base_vseq`` is a ``uvm_sequence`` that runs on a
``dv_base_virtual_sequencer``. It exposes:

* ``cfg`` — the env cfg held by the vseqr,
* ``ral`` — convenience pointer into the env cfg's RAL,
* ``cov`` — env coverage component,
* ``do_dut_init`` / ``apply_reset`` / ``run_csr_vseq_wrapper`` — virtual
  hooks reused across many tests.

``apply_reset`` now drives the env cfg's ``clk_rst_vif`` when one is
wired up (typically a :class:`dv_lib.dv_clk_rst.ClkRstIf`). Under a live
cocotb simulator that toggles the real reset signal; without a
simulator (or without a clk_rst_vif) it's an awaitable no-op, so the
hook is safe to call unconditionally.
"""
from __future__ import annotations

from typing import Optional

from .dv_base_env_cfg import DVBaseEnvCfg
from .dv_base_env_cov import DVBaseEnvCov
from .dv_base_reg_block import DVBaseRegBlock
from .dv_base_sequence import DVBaseSequence


class DVBaseVSeq(DVBaseSequence):
    """Base virtual sequence."""

    def __init__(self, name: str = "dv_base_vseq") -> None:
        super().__init__(name)
        # User knobs that mirror the SV flags of the same name.
        self.do_dut_init: bool = True
        self.do_apply_reset: bool = True
        # Default reset length in clocks; override per-vseq as needed.
        self.reset_cycles: int = 5

    # ----- env-level handles ----------------------------------------

    @property
    def cfg(self) -> Optional[DVBaseEnvCfg]:
        seqr = self.p_sequencer
        return None if seqr is None else getattr(seqr, "cfg", None)

    @property
    def cov(self) -> Optional[DVBaseEnvCov]:
        seqr = self.p_sequencer
        return None if seqr is None else getattr(seqr, "cov", None)

    @property
    def ral(self) -> Optional[DVBaseRegBlock]:
        c = self.cfg
        return None if c is None else c.ral

    # ----- virtual hooks --------------------------------------------

    async def dut_init(self, reset_kind: str = "HARD") -> None:
        """Initialise the DUT — typically apply reset. Override in
        IP-specific vseqs to add bring-up (e.g. CSR init) after reset.
        """
        if self.do_apply_reset:
            await self.apply_reset(reset_kind)

    async def apply_reset(self, reset_kind: str = "HARD") -> None:
        """Drive a reset cycle through the env cfg's ``clk_rst_vif``.

        If the cfg has a ``clk_rst_vif`` exposing an ``apply_reset``
        coroutine (e.g. :class:`dv_lib.dv_clk_rst.ClkRstIf`), we await
        it. Otherwise this is a no-op — which is the right behaviour
        both before a vif is wired up and when running without a
        simulator. ``reset_kind`` is accepted for SV parity; the base
        treats every kind the same.
        """
        cfg = self.cfg
        vif = None if cfg is None else getattr(cfg, "clk_rst_vif", None)
        if vif is None:
            return
        reset_fn = getattr(vif, "apply_reset", None)
        if reset_fn is None:
            return
        await reset_fn(reset_cycles=self.reset_cycles)

    # The CSR-test wrapper in SV is the workhorse of the auto-generated
    # CSR test suite. A real port needs a register-access mechanism we
    # haven't picked here, so we leave it as a hook.
    async def run_csr_vseq_wrapper(self, num_times: int = 1) -> None:  # pragma: no cover
        return

    async def body(self) -> None:
        if self.do_dut_init:
            await self.dut_init()
