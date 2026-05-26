"""
A pure-Python stand-in for the ALU DUT used by the example testbench.

In a real flow the DUT is RTL driven by cocotb, and ``vif`` on each agent
cfg is a cocotb signal handle. Here we use plain Python objects so the
example runs as a pytest unit test with no simulator.

The "interface" objects expose tiny put/get coroutines that the driver
and monitors use to talk to the model. They're the ergonomic equivalent
of a SystemVerilog ``virtual interface``.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional


# ---- Opcode encoding -------------------------------------------------

OP_ADD = 0
OP_SUB = 1
OP_AND = 2
OP_OR  = 3
OP_XOR = 4
OP_SHL = 5
OP_SHR = 6
OP_NOP = 7


@dataclass
class AluInputTxn:
    """One input request to the ALU."""
    operand_a: int
    operand_b: int
    opcode: int


@dataclass
class AluOutputTxn:
    """One result emitted by the ALU."""
    result: int
    valid: bool


@dataclass
class AluStatusTxn:
    """One status sample (overflow / zero)."""
    overflow: bool
    zero: bool


# ---- "Virtual interfaces" -------------------------------------------

class AluInputVif:
    """Drive side: agent driver pushes here, model pulls."""
    def __init__(self) -> None:
        self._q: asyncio.Queue[AluInputTxn] = asyncio.Queue()

    async def put(self, txn: AluInputTxn) -> None:
        await self._q.put(txn)

    async def get(self) -> AluInputTxn:
        return await self._q.get()


class AluOutputVif:
    """Result side: model pushes, monitor pulls."""
    def __init__(self) -> None:
        self._q: asyncio.Queue[AluOutputTxn] = asyncio.Queue()

    async def put(self, txn: AluOutputTxn) -> None:
        await self._q.put(txn)

    async def get(self) -> AluOutputTxn:
        return await self._q.get()


class AluStatusVif:
    """Status side: model pushes per result, monitor pulls."""
    def __init__(self) -> None:
        self._q: asyncio.Queue[AluStatusTxn] = asyncio.Queue()

    async def put(self, txn: AluStatusTxn) -> None:
        await self._q.put(txn)

    async def get(self) -> AluStatusTxn:
        return await self._q.get()


# ---- The DUT -----------------------------------------------------------

MASK32 = 0xFFFFFFFF


class AluDut:
    """A tiny ALU that consumes input txns and produces result + status.

    Stands in for the RTL DUT. Started as an asyncio task by the
    testbench glue. Run forever until cancelled.
    """

    def __init__(self,
                 input_vif: AluInputVif,
                 output_vif: AluOutputVif,
                 status_vif: AluStatusVif) -> None:
        self.input_vif = input_vif
        self.output_vif = output_vif
        self.status_vif = status_vif

    @staticmethod
    def _execute(txn: AluInputTxn) -> AluOutputTxn:
        a, b, op = txn.operand_a & MASK32, txn.operand_b & MASK32, txn.opcode
        if op == OP_ADD:
            r = (a + b) & MASK32
        elif op == OP_SUB:
            r = (a - b) & MASK32
        elif op == OP_AND:
            r = a & b
        elif op == OP_OR:
            r = a | b
        elif op == OP_XOR:
            r = a ^ b
        elif op == OP_SHL:
            r = (a << (b & 0x1F)) & MASK32
        elif op == OP_SHR:
            r = (a & MASK32) >> (b & 0x1F)
        else:  # OP_NOP
            r = 0
        return AluOutputTxn(result=r, valid=(op != OP_NOP))

    @staticmethod
    def _status(txn_in: AluInputTxn, txn_out: AluOutputTxn) -> AluStatusTxn:
        a, b, op = txn_in.operand_a & MASK32, txn_in.operand_b & MASK32, txn_in.opcode
        # Overflow only meaningful for ADD/SUB (treat as unsigned wrap).
        overflow = False
        if op == OP_ADD:
            overflow = (a + b) > MASK32
        elif op == OP_SUB:
            overflow = a < b
        zero = txn_out.result == 0 and txn_out.valid
        return AluStatusTxn(overflow=overflow, zero=zero)

    async def run(self) -> None:
        while True:
            txn_in = await self.input_vif.get()
            txn_out = self._execute(txn_in)
            txn_status = self._status(txn_in, txn_out)
            await self.output_vif.put(txn_out)
            await self.status_vif.put(txn_status)
