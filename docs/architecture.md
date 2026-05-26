# Architecture & mapping reference

This document is the detailed companion to the top-level `README.md`. It
covers the full class-by-class mapping from OpenTitan's SystemVerilog
`dv_lib` to this Python port, and walks through the worked ALU example.

## Class mapping

| pyuvm module | SystemVerilog file | Role |
| --- | --- | --- |
| `dv_lib.dv_utils` | `dv_utils_pkg` | plusarg helpers; read `cocotb.plusargs` first |
| `dv_lib.dv_report` | `dv_report_server`, `dv_report_catcher` | severity counters + demote rules as a logging filter |
| `dv_lib.dv_clk_rst` | `clk_rst_if` | cocotb clock/reset interface |
| `dv_lib.dv_base_seq_item` | `dv_base_seq_item` | `do_copy` / `do_compare` over payload attrs |
| `dv_lib.dv_base_agent_cfg` | `dv_base_agent_cfg` | `if_mode`, `is_active`, `en_cov`, `en_monitor`, `zero_delays`, `vif` |
| `dv_lib.dv_base_agent_cov` | `dv_base_agent_cov` | `sample()` gated on `en_cov` |
| `dv_lib.dv_base_monitor` | `dv_base_monitor` | analysis port + `collect_trans` coroutine |
| `dv_lib.dv_base_driver` | `dv_base_driver` | `reset_signals` + `drive_item`; honours `zero_delays` |
| `dv_lib.dv_base_sequencer` | `dv_base_sequencer` | sequencer with `cfg` handle |
| `dv_lib.dv_base_sequence` | `dv_base_sequence` | exposes `cfg` / `p_sequencer` |
| `dv_lib.dv_base_agent` | `dv_base_agent` | active/passive build, driver↔sequencer wiring |
| `dv_lib.dv_base_reg_block` | `dv_base_reg_field/reg/reg_block` | minimal RAL with `gen_n_used_bits`, `get_msb_pos` |
| `dv_lib.dv_base_env_cfg` | `dv_base_env_cfg` | env knobs, `initialize(csr_base_addr)`, `clk_rst_vif` |
| `dv_lib.dv_base_env_cov` | `dv_base_env_cov` | env-level coverage |
| `dv_lib.dv_base_virtual_sequencer` | `dv_base_virtual_sequencer` | dict of sub-sequencers |
| `dv_lib.dv_base_scoreboard` | `dv_base_scoreboard` | `check_phase` gated on `en_scb` |
| `dv_lib.dv_base_env` | `dv_base_env` | builds vseqr / scoreboard / cov, propagates cfg |
| `dv_lib.dv_base_vseq` | `dv_base_vseq` | base virtual sequence; `apply_reset` drives `clk_rst_vif` |
| `dv_lib.dv_base_test` | `dv_base_test` | top-level test; cocotb timeout / drain / poll |

## Idiom translations

- **Type parameters** (`#(type CFG_T = …)`) → class attributes
  (`cfg_type = …`). Subclass and override.
- **`$value$plusargs`** → `dv_utils.plusarg_*`. Under a live simulator
  these read `cocotb.plusargs` (the simulator command line), which
  always wins; `set_plusargs` / `PYUVM_PLUSARGS` are the no-sim path.
- **`dv_report_server` + `dv_report_catcher`** → `DVReportCatcher`, a
  `logging.Filter` installed on the cocotb/pyuvm logger tree. It uses
  stdlib levels (`INFO`/`WARNING`/`ERROR`/`CRITICAL`), not `UVM_*`.
- **`uvm_top.set_timeout`** → `cocotb.triggers.with_timeout` around the
  test sequence.
- **`phase.phase_done.set_drain_time`** → `await Timer(drain_time_ns)`.
- **`dv_utils_pkg::poll_for_stop`** → a background cocotb task polling at
  the requested interval.
- **RAL** → a small in-Python register model. For full register access,
  layer a tool-generated model or pyuvm's native `uvm_reg_block`.

Every cocotb-specific path is guarded by `cocotb.is_simulation`, so the
library runs under plain `pytest` (no simulator) as well as inside a
cocotb regression.

## Worked example: an ALU with multiple I/O ports

The example (`examples/alu/`) drives a toy ALU and shows how multiple
I/O ports map onto agents and the environment.

### The DUT

```
                     +----------------------+
   operand_a [31:0] -|                      |- result        [31:0]
   operand_b [31:0] -|        ALU           |- result_valid
   opcode    [2:0]  -|                      |- overflow
   req_valid        -|                      |- zero
                     +----------------------+
                       input port             output port    status port
                       (host drives in)       (observed)     (observed)
```

| Port | Direction | Driven by | Watched by |
| --- | --- | --- | --- |
| `input`  | DUT input  | testbench (active host) | input monitor |
| `output` | DUT output | DUT                     | output monitor |
| `status` | DUT output | DUT                     | status monitor |

That maps onto three agents: one **active** (input), two **passive**
(output, status).

### Files

```
examples/alu/
  alu_dut.py            toy "RTL" + three vif classes
  alu_input_agent.py    active host agent (item, cfg, driver, monitor, agent)
  alu_output_agent.py   passive monitor-only agent on the result port
  alu_status_agent.py   passive monitor-only agent on the status pins
  alu_env.py            env_cfg, scoreboard, virtual sequencer, env
  alu_test.py           virtual sequence + base test class
```

### The active vs passive decision

An active agent is three lines:

```python
class AluInputAgent(DVBaseAgent):
    cfg_type     = AluInputAgentCfg
    driver_type  = AluInputDriver
    monitor_type = AluInputMonitor
```

A passive agent omits the driver and sets its cfg passive:

```python
class AluOutputAgentCfg(DVBaseAgentCfg):
    def __init__(self, name="alu_output_agent_cfg"):
        super().__init__(name)
        self.is_active = UVM_PASSIVE   # no driver / sequencer built

class AluOutputAgent(DVBaseAgent):
    cfg_type     = AluOutputAgentCfg
    monitor_type = AluOutputMonitor
```

`DVBaseAgent.build_phase` reads `cfg.is_active` and skips the driver and
sequencer for passive agents — only the monitor is built.

### How the env ties the ports together

1. The env cfg carries every port's vif and one cfg per agent
   (`initialize` builds them).
2. `env.build_phase` pushes each vif into its agent's cfg and creates
   all three agents.
3. `env.connect_phase` wires each monitor's `analysis_port` to a
   scoreboard FIFO and registers the active agent's sequencer with the
   virtual sequencer.
4. The scoreboard drains the three FIFOs in lockstep and compares each
   observed `(result, status)` against a reference model, gated by
   `cfg.en_scb`.

### Topology

```
uvm_test_top                 DVBaseTest
  env                        AluEnv
    input_agent   ACTIVE     AluInputAgent  (driver + sequencer + monitor + cov)
    output_agent  PASSIVE    AluOutputAgent (monitor only)
    status_agent  PASSIVE    AluStatusAgent (monitor only)
    scoreboard               AluScoreboard  (input/output/status FIFOs)
    virtual_sequencer        AluVirtualSequencer (sub_seqrs["input"])
```

The structural tests in `tests/test_alu_example.py` assert every
relationship above.

## Running the example under cocotb

The structural tests exercise build/connect without a simulator. To run
the example end-to-end:

1. Replace `examples/alu/alu_dut.py` with cocotb signal handles; the
   three vif classes' `put`/`get` coroutines become bus drivers/samplers.
2. Wire a `ClkRstIf` onto the env cfg and call `start_clk()`.
3. Decorate the test:
   ```python
   import pyuvm
   from examples.alu.alu_test import AluSmokeTest

   @pyuvm.test()
   class AluSmokeTestEntry(AluSmokeTest):
       pass
   ```
4. Run with any cocotb-supported simulator via your usual Makefile /
   `cocotb-test` flow.
