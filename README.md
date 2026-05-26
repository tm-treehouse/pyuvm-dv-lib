# pyuvm-dv-lib

A [pyuvm](https://github.com/pyuvm/pyuvm) / [cocotb](https://github.com/cocotb/cocotb)
port of the **OpenTitan `dv_lib`** SystemVerilog UVM base library.

> ### Standing on the shoulders of OpenTitan
>
> [OpenTitan](https://opentitan.org), developed by
> [lowRISC](https://lowrisc.org) and its partners, is the first open-source
> silicon root of trust — and its design-verification methodology is some of
> the most carefully engineered open hardware DV in existence. At the base of
> every OpenTitan testbench sits
> [`hw/dv/sv/dv_lib`](https://github.com/lowRISC/opentitan/tree/master/hw/dv/sv/dv_lib):
> a small, sharp set of UVM base classes that everything else builds on.
>
> This project is a respectful reimplementation of that library for the
> Python verification world. The class names, the inheritance shape, and the
> role of each class follow the SystemVerilog originals as closely as the host
> language allows, so an engineer who knows OpenTitan's `dv_lib` can read this
> by inspection. All credit for the underlying design belongs to the
> OpenTitan / lowRISC contributors; see [`NOTICE`](NOTICE).

---

## Why this exists

pyuvm brings UVM's structure to Python, and cocotb drives the simulator.
What's missing is the thin layer of *conventions* that makes a testbench
fleet consistent — the shared knobs (`en_scb`, `en_cov`, `zero_delays`,
`smoke_test`), the report catcher, the plusarg plumbing, the standard
build/connect skeleton. OpenTitan solved that with `dv_lib`. This is that
solution, translated.

## Install

```bash
python -m pip install -e ".[dev]"
```

Requires Python 3.9+, `pyuvm >= 2.9`, and `cocotb >= 1.8`.

## Quickstart

```python
from dv_lib import (
    DVBaseTest, DVBaseEnv, DVBaseEnvCfg,
    DVBaseAgent, DVBaseAgentCfg,
    DVBaseDriver, DVBaseMonitor,
    DVBaseScoreboard, DVBaseVSeq, DVBaseSeqItem,
    UVM_ACTIVE,
)
from pyuvm import ConfigDB


class MyItem(DVBaseSeqItem):
    def __init__(self, name="my_item", payload=0):
        super().__init__(name)
        self.payload = payload


class MyDriver(DVBaseDriver):
    async def drive_item(self, item):
        ...  # drive cfg.vif here


class MyMonitor(DVBaseMonitor):
    async def collect_trans(self):
        ...  # sample the bus, write to self.analysis_port


class MyAgent(DVBaseAgent):
    driver_type  = MyDriver
    monitor_type = MyMonitor


class MyEnv(DVBaseEnv):
    def build_phase(self):
        super().build_phase()
        agent_cfg = DVBaseAgentCfg("my_agent_cfg")
        agent_cfg.is_active = UVM_ACTIVE
        ConfigDB().set(self, "my_agent", "cfg", agent_cfg)
        self.my_agent = MyAgent.create("my_agent", self)

    def connect_phase(self):
        super().connect_phase()
        if self.my_agent.sequencer is not None:
            self.virtual_sequencer.register_seqr("my", self.my_agent.sequencer)


class MyVSeq(DVBaseVSeq):
    async def body(self):
        seqr = self.p_sequencer.sub_seqrs["my"]
        for i in range(10):
            item = MyItem(payload=i)
            await self.start_item(item)
            await self.finish_item(item)


class MyTest(DVBaseTest):
    env_type = MyEnv

    def __init__(self, name="MyTest", parent=None):
        super().__init__(name, parent)
        self.test_seq_s = "MyVSeq"   # like +UVM_TEST_SEQ=MyVSeq
```

Run it inside cocotb by decorating a thin entry point:

```python
import pyuvm

@pyuvm.test()
class MyTestEntry(MyTest):
    pass
```

## What you get

- **Components** — `DVBaseTest`, `DVBaseEnv`, `DVBaseAgent`,
  `DVBaseDriver`, `DVBaseMonitor`, `DVBaseSequencer`,
  `DVBaseScoreboard`, `DVBaseVirtualSequencer`, plus coverage hooks.
- **Objects** — `DVBaseSeqItem`, `DVBaseSequence`, `DVBaseVSeq`,
  `DVBaseAgentCfg`, `DVBaseEnvCfg`.
- **A minimal RAL** — `DVBaseRegBlock` / `DVBaseReg` / `DVBaseRegField`
  with the documented `gen_n_used_bits` and `get_msb_pos` helpers.
- **cocotb-native plumbing**:
  - plusargs read from `cocotb.plusargs` (the simulator command line),
    which always wins over Python-side defaults;
  - a report catcher that walks the cocotb/pyuvm logger tree and counts
    / demotes messages using standard logging levels;
  - real `with_timeout` test timeouts, `Timer` drain time, a background
    `poll_for_stop` task;
  - a `ClkRstIf` clock/reset interface the base vseq drives in
    `apply_reset`.

Every cocotb-specific path degrades to a safe no-op when no simulator is
running, so the library — and its 98 unit tests — run under plain
`pytest`.

## Repository layout

```
pyuvm-dv-lib/
  src/dv_lib/            the library (importable as `dv_lib`)
  examples/alu/          worked multi-port ALU testbench
  tests/                 pytest suite (no simulator required)
  docs/architecture.md   full SV->Python mapping + example walkthrough
  pyproject.toml
  LICENSE  NOTICE  CHANGELOG.md  CONTRIBUTING.md
```

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — class-by-class
  mapping table, idiom translations, and the ALU example walkthrough.
- [`examples/README.md`](examples/README.md) — the examples index.

## Testing

```bash
pytest                      # 98 tests, no simulator needed
pytest --cov=dv_lib         # with coverage
```

## Relationship to OpenTitan

This is an independent reimplementation for the pyuvm/cocotb ecosystem.
It is **not** affiliated with or endorsed by lowRISC or the OpenTitan
project. The original `dv_lib` SystemVerilog is © lowRISC contributors,
licensed Apache-2.0; this port is offered under the same licence. See
[`NOTICE`](NOTICE) for attribution details.

`cip_lib` — OpenTitan's higher-level "comportable IP" library that adds
TileLink, interrupt, alert, and shadow-register machinery on top of
`dv_lib` — is **not** ported here. This project covers `dv_lib` only.

## Licence

[Apache-2.0](LICENSE), matching the OpenTitan source it derives from.
