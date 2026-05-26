"""
ALU environment.

This is where multiple I/O ports stop being independent and start
acting as a system:

* :class:`AluEnvCfg` carries the three vif handles and one cfg per
  agent. ``initialize`` constructs the agent cfgs so the test can
  later override knobs on them before build_phase runs.
* :class:`AluScoreboard` subscribes to all three analysis ports
  (input, output, status), reference-models the ALU, and asserts that
  the observed result + status match the expected ones for each input.
* :class:`AluVirtualSequencer` registers the input agent's sequencer
  so vseqs can drive stimulus through it.
* :class:`AluEnv` instantiates the three agents, propagates per-agent
  cfgs, and connects every monitor to the scoreboard's FIFOs.
"""
from __future__ import annotations

import logging
from typing import Optional

from pyuvm import ConfigDB, uvm_tlm_analysis_fifo, uvm_subscriber

from dv_lib import (
    DVBaseEnv, DVBaseEnvCfg, DVBaseScoreboard, DVBaseVirtualSequencer,
    UVM_ACTIVE,
)

from .alu_dut import AluInputVif, AluOutputVif, AluStatusVif, AluDut, MASK32
from .alu_input_agent  import AluInputAgent,  AluInputAgentCfg,  AluInputItem
from .alu_output_agent import AluOutputAgent, AluOutputAgentCfg, AluOutputItem
from .alu_status_agent import AluStatusAgent, AluStatusAgentCfg, AluStatusItem


# Side-car logger; see comment in dv_lib.dv_base_test for why we don't
# use ``self.logger`` directly.
_alu_logger = logging.getLogger("dv_lib.example.alu")


# ---- Env cfg -----------------------------------------------------------

class AluEnvCfg(DVBaseEnvCfg):
    """Carries three vif handles and three sub-agent cfgs.

    Same shape as a typical OpenTitan IP env cfg: ``initialize`` is the
    place where the env cfg constructs its sub-agent cfgs so they can
    be tweaked before the env's build_phase runs.
    """
    def __init__(self, name: str = "alu_env_cfg") -> None:
        super().__init__(name)
        # vif handles supplied by the testbench glue. With real RTL
        # these would be cocotb signal bundles set via uvm_config_db.
        self.input_vif:  Optional[AluInputVif]  = None
        self.output_vif: Optional[AluOutputVif] = None
        self.status_vif: Optional[AluStatusVif] = None

        # Concrete agent cfgs. The base class only knows about the
        # generic ``m_agent_cfgs`` dict; we add typed shortcuts for
        # ergonomics in vseqs / scoreboards.
        self.input_agent_cfg:  Optional[AluInputAgentCfg]  = None
        self.output_agent_cfg: Optional[AluOutputAgentCfg] = None
        self.status_agent_cfg: Optional[AluStatusAgentCfg] = None

    def initialize(self, csr_base_addr: int = 0) -> None:
        super().initialize(csr_base_addr)

        self.input_agent_cfg = AluInputAgentCfg("input_agent_cfg")
        self.input_agent_cfg.is_active = UVM_ACTIVE

        self.output_agent_cfg = AluOutputAgentCfg("output_agent_cfg")
        self.status_agent_cfg = AluStatusAgentCfg("status_agent_cfg")

        self.add_agent_cfg("input",  self.input_agent_cfg)
        self.add_agent_cfg("output", self.output_agent_cfg)
        self.add_agent_cfg("status", self.status_agent_cfg)


# ---- Scoreboard --------------------------------------------------------

class AluScoreboard(DVBaseScoreboard):
    """End-to-end checker.

    The pattern is the OpenTitan one: one analysis FIFO per agent,
    drained in the run_phase, all gated by ``cfg.en_scb``.
    """

    def __init__(self, name: str = "alu_scoreboard", parent=None) -> None:
        super().__init__(name, parent)
        self.input_fifo:  Optional[uvm_tlm_analysis_fifo] = None
        self.output_fifo: Optional[uvm_tlm_analysis_fifo] = None
        self.status_fifo: Optional[uvm_tlm_analysis_fifo] = None
        self._mismatches: int = 0

    def build_phase(self) -> None:
        super().build_phase()
        self.input_fifo  = self.make_fifo("input_fifo")
        self.output_fifo = self.make_fifo("output_fifo")
        self.status_fifo = self.make_fifo("status_fifo")

    async def run_phase(self) -> None:
        await super().run_phase()
        # When en_scb is off, just drain (so the FIFOs don't grow
        # unbounded) and skip checking.
        if self.cfg is not None and not self.cfg.en_scb:
            return
        await self._compare_loop()

    async def _compare_loop(self) -> None:
        assert self.input_fifo  is not None
        assert self.output_fifo is not None
        assert self.status_fifo is not None

        while True:
            in_item:     AluInputItem  = await self.input_fifo.get()
            out_item:    AluOutputItem = await self.output_fifo.get()
            status_item: AluStatusItem = await self.status_fifo.get()

            exp = self._predict(in_item)
            if (out_item.result, out_item.valid) != (exp["result"], exp["valid"]):
                self._mismatches += 1
                _alu_logger.error(
                    f"result mismatch: got {out_item} exp {exp}",
                )
            if (status_item.overflow, status_item.zero) != \
               (exp["overflow"], exp["zero"]):
                self._mismatches += 1
                _alu_logger.error(
                    f"status mismatch: got {status_item} exp {exp}",
                )

    @staticmethod
    def _predict(item: AluInputItem) -> dict:
        a, b, op = item.operand_a & MASK32, item.operand_b & MASK32, item.opcode
        # Mirror the DUT's behaviour exactly. In practice the reference
        # model lives in its own module so it can be reused.
        from .alu_dut import (
            OP_ADD, OP_SUB, OP_AND, OP_OR, OP_XOR, OP_SHL, OP_SHR,
            AluInputTxn, AluOutputTxn,
        )
        out = AluDut._execute(AluInputTxn(a, b, op))
        st  = AluDut._status(AluInputTxn(a, b, op), out)
        return {
            "result":   out.result,
            "valid":    out.valid,
            "overflow": st.overflow,
            "zero":     st.zero,
        }

    def do_check(self) -> None:
        # Equivalent of the SV check_phase end-of-test verdict.
        if self._mismatches:
            _alu_logger.error(
                f"alu_scoreboard saw {self._mismatches} mismatches",
            )

    @property
    def mismatches(self) -> int:
        return self._mismatches


# ---- Virtual sequencer ------------------------------------------------

class AluVirtualSequencer(DVBaseVirtualSequencer):
    """Holds typed handles to each agent's sequencer.

    Only the input agent has one — the output and status agents are
    passive — but we keep the dict registration uniform.
    """
    pass


# ---- Env ---------------------------------------------------------------

class AluEnv(DVBaseEnv):
    cfg_type = AluEnvCfg
    scoreboard_type = AluScoreboard
    virtual_sequencer_type = AluVirtualSequencer

    def __init__(self, name: str = "alu_env", parent=None) -> None:
        super().__init__(name, parent)
        self.input_agent:  Optional[AluInputAgent]  = None
        self.output_agent: Optional[AluOutputAgent] = None
        self.status_agent: Optional[AluStatusAgent] = None

    def build_phase(self) -> None:
        super().build_phase()
        # ``self.cfg`` is the AluEnvCfg, fetched from ConfigDB by the
        # base build_phase. Each sub-agent needs its own cfg pushed
        # into ConfigDB at the right scope.
        cfg: AluEnvCfg = self.cfg  # type: ignore[assignment]

        # Wire each sub-agent cfg to its vif. Tests can override either
        # of these before this point.
        cfg.input_agent_cfg.vif  = cfg.input_vif
        cfg.output_agent_cfg.vif = cfg.output_vif
        cfg.status_agent_cfg.vif = cfg.status_vif

        ConfigDB().set(self, "input_agent",  "cfg", cfg.input_agent_cfg)
        ConfigDB().set(self, "output_agent", "cfg", cfg.output_agent_cfg)
        ConfigDB().set(self, "status_agent", "cfg", cfg.status_agent_cfg)

        self.input_agent  = AluInputAgent.create("input_agent",  self)
        self.output_agent = AluOutputAgent.create("output_agent", self)
        self.status_agent = AluStatusAgent.create("status_agent", self)

    def connect_phase(self) -> None:
        super().connect_phase()
        # Each monitor's analysis_port -> its scoreboard FIFO.
        sb: AluScoreboard = self.scoreboard  # type: ignore[assignment]
        self.input_agent.monitor.analysis_port.connect(
            sb.input_fifo.analysis_export,
        )
        self.output_agent.monitor.analysis_port.connect(
            sb.output_fifo.analysis_export,
        )
        self.status_agent.monitor.analysis_port.connect(
            sb.status_fifo.analysis_export,
        )

        # Register the active agent's sequencer with the virtual
        # sequencer so vseqs can drive stimulus.
        if self.input_agent.sequencer is not None:
            self.virtual_sequencer.register_seqr(
                "input", self.input_agent.sequencer,
            )
