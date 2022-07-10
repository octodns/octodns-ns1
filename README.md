## NS1 provider for octoDNS

An [octoDNS](https://github.com/octodns/octodns/) provider that targets [NS1](https://ns1.com/products/managed-dns).

### Installation

#### Command line

```
pip install octodns_ns1
```

#### requirements.txt/setup.py

Pinning specific versions or SHAs is recommended to avoid unplanned upgrades.

##### Versions

```
# Start with the latest versions and don't just copy what's here
octodns==0.9.14
octodns_ns1==0.0.1
```

##### SHAs

```
# Start with the latest/specific versions and don't just copy what's here
-e git+https://git@github.com/octodns/octodns.git@9da19749e28f68407a1c246dfdf65663cdc1c422#egg=octodns
-e git+https://git@github.com/octodns/octodns-ns1.git@ec9661f8b335241ae4746eea467a8509205e6a30#egg=octodns_ns1
```

### Configuration

```yaml
providers:
  ns1:
    class: octodns_ns1.Ns1Provider
    api_key: env/NS1_API_KEY
    # Only required if using dynamic records
    monitor_regions:
      - lga
    # Optional. Default: false. true is Recommended, but not the default
    # for backwards compatibility reasons. If true, all NS1 monitors will
    # use a shared notify list rather than one per record & value
    # combination. See CHANGELOG,
    # https://github.com/octodns/octodns/blob/master/CHANGELOG.md, for more
    # information before enabling this behavior.
    shared_notifylist: false
    # Optional. Default: None. If set, back off in advance to avoid 429s
    # from rate-limiting. Generally this should be set to the number
    # of processes or workers hitting the API, e.g. the value of
    # `max_workers`.
    parallelism: 11
    # Optional. Default: 4. Number of times to retry if a 429 response
    # is received.
    retry_count: 4
    # Optional. Default: None. Additional options or overrides passed to
    # the NS1 SDK config, as key-value pairs.
    client_config:
        endpoint: my.nsone.endpoint # Default: api.nsone.net
        ignore-ssl-errors: true     # Default: false
        follow_pagination: false    # Default: true
```

### Support Information

#### Records

All octoDNS record types are supported.

#### Root NS Records

Ns1Provider supports full root NS record management.

#### Dynamic

Ns1Provider supports dynamic records.

#### IDN

Ns1Provider supports IDN

#### Health Check Options

See https://github.com/octodns/octodns/blob/master/docs/dynamic_records.md#health-checks for information on health checking for dynamic records. Ns1Provider supports the following options:

| Key  | Description | Default |
|--|--|--|
| policy | One of:<ol><li>`all` - down if every region is down</li><li>`quorum` - down if majority regions are down</li><li>`one` - down if any region is down</ol> | `quorum` |
| frequency | Frequency (in seconds) of health-check | 60 |
| connect_timeout | Timeout (in seconds) before we give up trying to connect | 2 |
| response_timeout | Timeout (in seconds) after connecting to wait for output | 10 |
| rapid_recheck | Enable or disable a second, automatic verification test before changing the status of a host. Enabling this option can help prevent false positives. | False |

```yaml
---
  octodns:
    ns1:
      healthcheck:
        policy: quorum
        frequency: 60
        connect_timeout: 2
        response_timeout: 10
        rapid_recheck: True
```

### Developement

See the [/script/](/script/) directory for some tools to help with the development process. They generally follow the [Script to rule them all](https://github.com/github/scripts-to-rule-them-all) pattern. Most useful is `./script/bootstrap` which will create a venv and install both the runtime and development related requirements. It will also hook up a pre-commit hook that covers most of what's run by CI.
