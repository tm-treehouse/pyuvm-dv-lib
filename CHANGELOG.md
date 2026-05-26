# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0]

Initial release: a pyuvm port of the OpenTitan `dv_lib` SystemVerilog
UVM base library.

### Added
- Base component classes: `DVBaseTest`, `DVBaseEnv`, `DVBaseAgent`,
  `DVBaseDriver`, `DVBaseMonitor`, `DVBaseSequencer`,
  `DVBaseScoreboard`, `DVBaseVirtualSequencer`, and the coverage
  components `DVBaseAgentCov` / `DVBaseEnvCov`.
- Object/config classes: `DVBaseSeqItem`, `DVBaseSequence`,
  `DVBaseVSeq`, `DVBaseAgentCfg`, `DVBaseEnvCfg`.
- Minimal RAL analogue: `DVBaseRegField`, `DVBaseReg`,
  `DVBaseRegBlock`, with the documented `gen_n_used_bits` /
  `get_msb_pos` helpers and a pseudo-pure-virtual `build`.
- `dv_report`: a report-catcher (`DVReportCatcher`) and installer that
  uses standard stdlib logging levels and walks the cocotb/pyuvm
  logger tree (up and down) to demote and count messages.
- `dv_utils`: plusarg helpers that read from `cocotb.plusargs` when a
  simulator is live (simulator command line always wins), with
  explicit / `PYUVM_PLUSARGS` fallbacks for the no-simulator path.
- `dv_clk_rst`: a cocotb-aware `ClkRstIf` clock/reset interface used by
  the env cfg and base vseq, with no-op fallbacks when no simulator is
  running.
- cocotb-native behaviours in `DVBaseTest`: real `with_timeout` test
  timeout, `Timer`-based drain time, and a background `poll_for_stop`
  task.
- A worked multi-port ALU example under `examples/alu/`.
- 98 unit tests covering the pure-Python behaviour of every module.

### Fixed
- `DVBaseSeqItem.do_copy` / `do_compare` previously included pyuvm's
  internal bookkeeping attributes (`transaction_id`, the condition
  events, etc.) in their state, so compares always failed and copies
  clobbered UVM machinery. Those attributes are now excluded.
