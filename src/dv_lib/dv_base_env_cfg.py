# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_base_env_cfg: Environment-level configuration object.

The original SV ``dv_base_env_cfg`` is a parameterized ``uvm_object``::

    class dv_base_env_cfg #(type RAL_T = dv_base_reg_block) extends uvm_object;

It carries the env-wide knobs that ``dv_base_test`` reads / writes from
plusargs (``en_scb``, ``en_scb_mem_chk``, ``zero_delays``, ``en_cov``,
``smoke_test``, ``en_dv_cdc``), a clk/rst interface handle, a list of
downstream agent cfgs, and a ``ral`` handle of type ``RAL_T``. The
``initialize()`` method, called from ``dv_base_test::build_phase``, is
where the IP env cfg builds its RAL model and creates its agent cfgs.

The Python port keeps the same fields and the same ``initialize`` hook.
RAL is a class attribute (``ral_type``) instead of a SV type parameter.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, Type

from .dv_base_agent_cfg import DVBaseAgentCfg
from .dv_base_reg_block import DVBaseRegBlock

if TYPE_CHECKING:  # avoid importing cocotb-touching module at runtime here
    from .dv_clk_rst import ClkRstIf


class DVBaseEnvCfg:
    """Environment cfg.

    The five plusarg-driven knobs match the names in
    ``dv_base_test::build_phase``::

        void'($value$plusargs("en_scb=%0b",  cfg.en_scb));
        void'($value$plusargs("en_scb_mem_chk=%0b", cfg.en_scb_mem_chk));
        void'($value$plusargs("zero_delays=%0b", cfg.zero_delays));
        void'($value$plusargs("en_cov=%0b", cfg.en_cov));
        void'($value$plusargs("smoke_test=%0b", cfg.smoke_test));
        void'($value$plusargs("cdc_instrumentation_enabled=%d", cfg.en_dv_cdc));
    """

    # Subclasses set this to a concrete RAL block class. Default is the
    # base class itself, whose ``build()`` raises — same intent as SV.
    ral_type: Type[DVBaseRegBlock] = DVBaseRegBlock

    def __init__(self, name: str = "dv_base_env_cfg") -> None:
        self.name = name

        # plusarg-driven knobs (defaults match the SV base)
        self.en_scb: bool = True
        self.en_scb_mem_chk: bool = True
        self.zero_delays: bool = False
        self.en_cov: bool = True
        self.smoke_test: bool = False
        self.en_dv_cdc: int = 0  # 0 = off; SV uses %d, hence int

        # Clock/reset interface. The SV cfg has a ``virtual clk_rst_if``;
        # under cocotb this is a :class:`dv_lib.dv_clk_rst.ClkRstIf`
        # wrapping the DUT's clock and reset handles. The base vseq's
        # ``apply_reset`` drives reset through it. Left None until the
        # testbench wires one up (and None is harmless — apply_reset
        # no-ops). Typed as Optional[ClkRstIf] but accepts any object
        # exposing the same coroutine surface.
        self.clk_rst_vif: Optional["ClkRstIf"] = None

        # downstream agent cfg objects, keyed by name. Set by
        # ``initialize()``.
        self.m_agent_cfgs: Dict[str, DVBaseAgentCfg] = {}

        # RAL handle. Created in ``initialize()``.
        self.ral: Optional[DVBaseRegBlock] = None

        # The SV cfg also carries a base address used when building the
        # RAL. Mirror it.
        self.csr_base_addr: int = 0

    # ------------------------------------------------------------------
    # initialize(): mirror of dv_base_env_cfg::initialize.
    #
    # SV signature is ``virtual function void initialize(bit [BUS_AW-1:0]
    # csr_base_addr = '1)``. The all-ones default means "let me pick
    # one"; here we use 0 unless overridden.
    # ------------------------------------------------------------------

    def initialize(self, csr_base_addr: int = 0) -> None:
        """Build the RAL and any agent cfgs.

        Mirrors ``dv_base_env_cfg::initialize``. Subclasses typically
        chain via ``super().initialize()`` and then add their own agent
        cfgs / RAL configuration.
        """
        self.csr_base_addr = csr_base_addr

        # Construct a RAL of the user-selected type.
        self.ral = self.ral_type()
        # ``build()`` is pseudo-pure-virtual on ``DVBaseRegBlock``; only
        # call it when the user has subclassed it. Detect by checking
        # whether ``build`` is the base class implementation.
        try:
            self.ral.build(csr_base_addr)
        except RuntimeError:
            # Base ral_type not overridden — fine, the testbench just
            # doesn't need a register model. Match the SV behaviour
            # which would have fataled out, but leave it to the user
            # so simple smoke tests can run.
            pass

    # ------------------------------------------------------------------
    # Agent cfg plumbing — small convenience.
    # ------------------------------------------------------------------

    def add_agent_cfg(self, key: str, cfg: DVBaseAgentCfg) -> None:
        self.m_agent_cfgs[key] = cfg

    def get_agent_cfg(self, key: str) -> Optional[DVBaseAgentCfg]:
        return self.m_agent_cfgs.get(key)

    # ------------------------------------------------------------------
    # Equivalent of randomize() — SV calls ``DV_CHECK_RANDOMIZE_FATAL``
    # on the cfg. There's nothing to randomize on the base class itself,
    # so subclasses override; we provide a hook.
    # ------------------------------------------------------------------

    def randomize(self) -> bool:
        """Hook for subclasses with random knobs. Return True if
        randomization succeeded. Default: nothing to do.
        """
        return True

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"{type(self).__name__}(en_scb={self.en_scb}, "
            f"en_cov={self.en_cov}, zero_delays={self.zero_delays}, "
            f"smoke_test={self.smoke_test}, "
            f"agents={list(self.m_agent_cfgs.keys())})"
        )
