# Team 210 Coding Agent Baseline

This directory packages the Team 210 participant coding agent baseline for Track 1 (Quantitative Finance Coding Agents).

## Architecture

1. **CLI Contract**: Implements `solve --task-dir <path> --out <path>` conforming to `interface_version = "2.0"`.
2. **Exploration & Preflight**: Discovers task configuration, schemas, option structures, and data requirements before code generation.
3. **Execution & Repair Loop**: Runs the generated solution in an isolated environment, asserts financial invariants, and applies multi-candidate consensus repair.
4. **Invariant Library**: Uses financial domain invariants (put-call parity, delta/gamma/vega bounds, no-arbitrage bounds, Sharpe/drawdown sanity checks) to self-verify deliverables.
5. **Restricted Network Compliance**: Supports organizer-hosted `` via ``/`` with zero external network egress.
