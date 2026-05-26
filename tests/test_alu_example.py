"""Structural test of the ALU example.

What this test exercises (no simulator required):

* the env's build_phase: three agents instantiated, active/passive
  decisions correct, vifs propagated to each agent's cfg,
* connect_phase: monitor analysis ports wired to scoreboard FIFOs.

What this test does **not** do: drive items end-to-end. pyuvm 4.x's
sequencer and ``uvm_tlm_analysis_fifo`` are built on
``cocotb.queue.Queue``, which depends on cocotb's event scheduler.
Outside a running simulator the queues' get-coroutines block forever.

The end-to-end story for this example is:

1. drop the ALU testbench into a cocotb sim (real RTL or a stub),
2. decorate the test class with ``@pyuvm.test()``,
3. run via ``cocotb-test`` / ``cocotb-config`` / make.

The classes in ``examples/alu/`` are written so that path works
unchanged. See the README for a worked walkthrough.
"""
from __future__ import annotations

import pytest
from pyuvm import ConfigDB

from dv_lib import clear_plusargs

from examples.alu.alu_dut import AluInputVif, AluOutputVif, AluStatusVif
from examples.alu.alu_test import AluSmokeTest


def _reset_world():
    clear_plusargs()
    try:
        ConfigDB().clear()
    except Exception:
        pass
    try:
        from pyuvm import uvm_root as _root
        _root().clear_children()
    except Exception:
        pass


class TestAluExampleStructure:
    def setup_method(self):
        _reset_world()

    def _build_test_top(self):
        """Construct the test, set up vifs, run build/connect."""
        from examples.alu.alu_env import AluEnvCfg

        cfg = AluEnvCfg()
        cfg.initialize()
        cfg.input_vif  = AluInputVif()
        cfg.output_vif = AluOutputVif()
        cfg.status_vif = AluStatusVif()

        test = AluSmokeTest("uvm_test_top", None)
        ConfigDB().set(test, "env", "cfg", cfg)

        # build_phase top-down, connect_phase bottom-up — same order
        # pyuvm's phase walker would use.
        def build_recursive(comp):
            if hasattr(comp, "build_phase"):
                comp.build_phase()
            for child in comp.children:
                build_recursive(child)

        def connect_recursive(comp):
            for child in comp.children:
                connect_recursive(child)
            if hasattr(comp, "connect_phase"):
                comp.connect_phase()

        build_recursive(test)
        connect_recursive(test)
        return test, cfg

    def test_three_agents_built(self):
        test, _ = self._build_test_top()
        env = test.env
        assert env.input_agent  is not None, "input agent missing"
        assert env.output_agent is not None, "output agent missing"
        assert env.status_agent is not None, "status agent missing"

    def test_active_agent_has_driver_and_sequencer(self):
        test, _ = self._build_test_top()
        env = test.env
        assert env.input_agent.driver    is not None
        assert env.input_agent.sequencer is not None

    def test_passive_agents_skip_driver_and_sequencer(self):
        test, _ = self._build_test_top()
        env = test.env
        # ``DVBaseAgent.build_phase`` honours cfg.is_active. Passive
        # agents have neither a driver nor a sequencer, but they always
        # have a monitor.
        assert env.output_agent.driver    is None
        assert env.output_agent.sequencer is None
        assert env.status_agent.driver    is None
        assert env.status_agent.sequencer is None

    def test_all_agents_have_monitors(self):
        test, _ = self._build_test_top()
        env = test.env
        assert env.input_agent.monitor  is not None
        assert env.output_agent.monitor is not None
        assert env.status_agent.monitor is not None

    def test_vifs_propagated_to_agents(self):
        """env.build_phase pushes the per-port vif into each agent's cfg."""
        test, cfg = self._build_test_top()
        env = test.env
        assert env.input_agent.cfg.vif  is cfg.input_vif
        assert env.output_agent.cfg.vif is cfg.output_vif
        assert env.status_agent.cfg.vif is cfg.status_vif

    def test_scoreboard_fifos_built_and_wired(self):
        test, _ = self._build_test_top()
        env = test.env
        sb = env.scoreboard
        # All three FIFOs created in build_phase.
        assert sb.input_fifo  is not None
        assert sb.output_fifo is not None
        assert sb.status_fifo is not None
        # Each monitor's analysis_port lists its scoreboard FIFO export
        # as a subscriber after connect_phase.
        in_subs  = list(env.input_agent.monitor.analysis_port.subscribers)
        out_subs = list(env.output_agent.monitor.analysis_port.subscribers)
        st_subs  = list(env.status_agent.monitor.analysis_port.subscribers)
        assert sb.input_fifo.analysis_export  in in_subs
        assert sb.output_fifo.analysis_export in out_subs
        assert sb.status_fifo.analysis_export in st_subs

    def test_virtual_sequencer_registers_active_seqr(self):
        """The vseqr exposes the input agent's sequencer; passive agents
        contribute nothing.
        """
        test, _ = self._build_test_top()
        env = test.env
        assert "input" in env.virtual_sequencer.sub_seqrs
        assert env.virtual_sequencer.sub_seqrs["input"] \
            is env.input_agent.sequencer
        # Output / status are passive, so no entries for them.
        assert "output" not in env.virtual_sequencer.sub_seqrs
        assert "status" not in env.virtual_sequencer.sub_seqrs

    def test_scoreboard_predict_matches_dut(self):
        """Reference-model sanity: predict() agrees with the DUT for a
        spread of opcodes. This exercises the env's check logic without
        going through the FIFOs.
        """
        from examples.alu.alu_env import AluScoreboard
        from examples.alu.alu_input_agent import AluInputItem
        from examples.alu.alu_dut import (
            AluDut, AluInputTxn,
            OP_ADD, OP_SUB, OP_AND, OP_OR, OP_XOR, OP_SHL, OP_SHR,
        )

        cases = [
            (1, 2, OP_ADD),
            (0xFFFF_FFFF, 1, OP_ADD),     # wraps, overflow
            (0, 5, OP_SUB),                # wraps, overflow
            (0xF0F0, 0x0F0F, OP_AND),
            (0x1234, 0x5678, OP_OR),
            (0xAAAA, 0x5555, OP_XOR),
            (1, 8, OP_SHL),
            (0x80000000, 4, OP_SHR),
        ]
        for a, b, op in cases:
            item = AluInputItem(operand_a=a, operand_b=b, opcode=op)
            exp = AluScoreboard._predict(item)

            # Compare against the actual DUT's output.
            txn_in = AluInputTxn(a, b, op)
            actual_out = AluDut._execute(txn_in)
            actual_st  = AluDut._status(txn_in, actual_out)

            assert (exp["result"], exp["valid"]) \
                == (actual_out.result, actual_out.valid), \
                f"predict mismatch on {a=:#x} {b=:#x} {op=}"
            assert (exp["overflow"], exp["zero"]) \
                == (actual_st.overflow, actual_st.zero), \
                f"status predict mismatch on {a=:#x} {b=:#x} {op=}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
