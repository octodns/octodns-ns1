# Developer Agent Guide for octoDNS NS1 Provider

This repository contains the NS1 provider for octoDNS. It enables planning, syncing, and applying DNS record states directly to the NS1 platform, with support for advanced traffic management and monitoring filters.

> [!IMPORTANT]
> **Core Workflow and Guidelines**
>
> All agents working on this repository must read and follow the general instructions and workflow guidelines defined in the core octoDNS `AGENTS.md` file.
> - **Local check**: Look for the file at `../octodns/AGENTS.md`.
> - **Remote check**: If the local file is not available, fetch it from GitHub: [octoDNS Core AGENTS.md](https://github.com/octodns/octodns/raw/refs/heads/main/AGENTS.md).
>
> You must align your code structure, style, pull request guidelines, and overall development workflows with the instructions specified there.

## Repository & Module Information

### Key Components

- **Provider Class**: [Ns1Provider](file:///home/ross/octodns/octodns-ns1/octodns_ns1/__init__.py#L299-L1866) (defined in [octodns_ns1/__init__.py](file:///home/ross/octodns/octodns-ns1/octodns_ns1/__init__.py)). This is the core provider implementing complex filter chains, monitoring integration, and record conversion logic.
- **Client Class**: [Ns1Client](file:///home/ross/octodns/octodns-ns1/octodns_ns1/__init__.py#L33-L296) wraps the official python `ns1-python` client library (`ns1.NS1`).
  - **Rate Limiting strategy**: Configures the `concurrent` token bucket rate-limit strategy. To prevent 429s, it calculates sleep replenishment intervals based on the configured `parallelism` (which should match the octoDNS worker worker pool size).
  - **Pagination**: Configures `follow_pagination=True` to transparently page through zone records.

### Key Workflows & Features

1. **Supported Record Types**: `A`, `AAAA`, `ALIAS`, `CAA`, `CNAME`, `DNAME`, `DS`, `MX`, `NAPTR`, `NS`, `PTR`, `SPF`, `SRV`, `TLSA`, `TXT`, `URLFWD`.
2. **Advanced Dynamic Routing**: Fully supported (`SUPPORTS_DYNAMIC=True`, `SUPPORTS_GEO=True`) using NS1 filter chains. Configurable filter types include:
   - `up`: Health/UP status filtering.
   - `geofence_regional` & `geofence_country`: Regional and country geofencing filters.
   - `netfence_prefix`: Subnet routing (`SUPPORTS_DYNAMIC_SUBNETS=True`).
   - `select_first_region`, `priority` routing, `weighted_shuffle`, and `select_first_n`.
3. **Pool Value Status**: Supported (`SUPPORTS_POOL_VALUE_STATUS=True`). NS1 feeds and monitoring data sources are queried and mapped to dynamic records.
4. **Name Server Support**: Supports root name servers (`SUPPORTS_ROOT_NS=True`) and multi-value PTRs (`SUPPORTS_MULTIVALUE_PTR=True`).

## Development & Testing

- **Setup Script**: Run `./script/bootstrap` to create a virtual environment, install runtime and development dependencies (including `black`, `isort`, `pyflakes`, and `pytest`), and configure pre-commit hooks.
- **Test Suite**: Run unit tests using `pytest` via `./script/test` (or `pytest tests/`). Test files are located in [tests/](file:///home/ross/octodns/octodns-ns1/tests).
- **Code Coverage**: Verify code coverage using `./script/coverage`.

## Key Constraints & Behaviors

- **Python Version**: Targets Python `>=3.9`.
- **Formatting**: Code formatting is enforced via `black` (version `>=26.0.0,<27.0.0`) and `isort`.
