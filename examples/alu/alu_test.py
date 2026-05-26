"""
ALU virtual sequence + base test.

The vseq runs on the env's virtual sequencer. From there it can reach
the input agent's sequencer through ``self.p_sequencer.sub_seqrs``
and start lower-level item sequences on it.
"""
from __future__ import annotations

import random

from dv_lib import DVBaseTest, DVBaseVSeq

from .alu_env import AluEnv, AluEnvCfg
from .alu_input_agent import AluInputItem
from .alu_dut import OP_ADD, OP_SUB, OP_AND, OP_OR, OP_XOR, OP_SHL, OP_SHR


class AluSmokeVSeq(DVBaseVSeq):
    """Drive a handful of random ALU operations through the input agent."""

    def __init__(self, name: str = "AluSmokeVSeq") -> None:
        super().__init__(name)
        # By default the base vseq tries to apply_reset; there's no
        # clk_rst in this toy model so disable it.
        self.do_apply_reset = False
        self.num_txns = 16
        self.opcodes = (OP_ADD, OP_SUB, OP_AND, OP_OR, OP_XOR, OP_SHL, OP_SHR)

    async def body(self) -> None:
        # Let the base do its thing (no-op here because do_apply_reset=False).
        await super().body()

        rng = random.Random(0xA1)
        seqr = self.p_sequencer.sub_seqrs["input"]
        # Build a small inline sequence that runs on the input sequencer.
        # In SV this would be ``input_sub_seq`` started via ``seq.start(seqr)``
        # — pyuvm's idiom is the same.
        from dv_lib import DVBaseSequence

        class _InputSubSeq(DVBaseSequence):
            def __init__(self, items):
                super().__init__("alu_input_sub_seq")
                self._items = items

            async def body(self_inner):
                for item in self_inner._items:
                    await self_inner.start_item(item)
                    await self_inner.finish_item(item)

        items = []
        for _ in range(self.num_txns):
            items.append(AluInputItem(
                operand_a=rng.randrange(1 << 32),
                operand_b=rng.randrange(1 << 32),
                opcode=rng.choice(self.opcodes),
            ))
        sub = _InputSubSeq(items)
        await sub.start(seqr)


class AluSmokeTest(DVBaseTest):
    """Base test class. SV equivalent: ``alu_base_test extends dv_base_test
    #(.CFG_T(alu_env_cfg), .ENV_T(alu_env));``
    """
    cfg_type = AluEnvCfg
    env_type = AluEnv

    def __init__(self, name: str = "AluSmokeTest", parent=None) -> None:
        super().__init__(name, parent)
        # Equivalent of +UVM_TEST_SEQ=AluSmokeVSeq.
        self.test_seq_s = "AluSmokeVSeq"
