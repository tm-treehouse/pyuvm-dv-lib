# Contributing

Thanks for your interest in improving **pyuvm-dv-lib**.

## Ground rules

- This library mirrors the *shape and contracts* of OpenTitan's
  `dv_lib`. When you add or change a base class, keep the class names
  and method roles aligned with the SystemVerilog original where one
  exists, and note the mapping in a docstring.
- Every cocotb-specific call must degrade gracefully when no simulator
  is running (guard with `cocotb.is_simulation`). The unit-test suite
  runs under plain `pytest` with no simulator, and it must stay that
  way.

## Development setup

```bash
git clone https://github.com/tm-treehouse/pyuvm-dv-lib
cd pyuvm-dv-lib
python -m pip install -e ".[dev]"
```

## Running the tests

```bash
pytest                       # all tests
pytest --cov=dv_lib          # with coverage
pytest tests/test_smoke.py   # a single file
```

The suite must pass with no simulator installed. If you add a behaviour
that only makes sense under a simulator, cover its no-sim branch in a
unit test and exercise the sim branch in a cocotb example.

## Pull requests

1. Add or update unit tests for any behaviour change.
2. Keep the `CHANGELOG.md` `Unreleased` section up to date.
3. Run `pytest` and make sure coverage doesn't regress.
4. Keep docstrings accurate — they double as the SV↔Python mapping
   reference.

## Reporting bugs

Open an issue with a minimal reproduction. If it's a behavioural
mismatch against OpenTitan's `dv_lib`, link the relevant SystemVerilog
source so we can compare.
