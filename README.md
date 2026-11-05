# artpipeline

> **v2 is under construction on this branch.** The released v1 (May 2026, browser-driven CLI) is at tag [`v0.1.0`](../../tree/v0.1.0).

artpipeline v2 is a Claude Code plugin that lets an agent produce a full set of game art assets that are correct, consistent, reviewable and reproducible. It pairs:

- **the `casual-mobile-art-director` skill** (`skills/casual-mobile-art-director/`): art direction, tool routing, taste review; and
- **the `artpipeline` engine** (Python, MCP server + CLI): enforced per-asset state, attempt provenance, style-lock and review gates, checks, contact sheets, and engine placement.

See [`docs/v2/spec.md`](docs/v2/spec.md) for the design and milestones.

## License

MIT — see [LICENSE](LICENSE).
