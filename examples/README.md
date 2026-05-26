# Examples

## `alu/` — a multi-port ALU testbench

A worked example showing how `dv_lib`'s base classes scale to a DUT with
several I/O ports. The ALU has one input port (driven by an **active**
agent) and two output ports — result and status — each watched by a
**passive** monitor-only agent. An env ties them together with a
scoreboard and a virtual sequencer.

See [`../docs/architecture.md`](../docs/architecture.md) for the full
walkthrough, and `tests/test_alu_example.py` for structural tests that
exercise the build/connect wiring without a simulator.

To run the example end-to-end you supply a DUT and a cocotb test entry
point — see the "Running the example under cocotb" section of the
architecture doc.
