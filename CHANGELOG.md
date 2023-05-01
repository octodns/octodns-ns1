## v0.0.5 - 2023-??-?? - ???

* Allow using actual HTTP monitors instead of emulating them in TCP monitors.
  Doing this is not forward-compatible, ie octodns-ns1 cannot be downgraded to
  a previous version that doesn't support modern HTTP monitors. It also doesn't
  honor the `http_version` configuration because these monitors can only talk
  HTTP/1.1.

## v0.0.4 - 2023-04-06 - More (accurately) Dynamic

* Dynamic records filter chain ordering reworked to place country filters before
  regions, see https://github.com/octodns/octodns-ns1/pull/37 for
  details/discussion.
* AS implemented as a list of countries rather than the ASIAPAC region which
  didn't match as the AS list of countries in the first place
* AS, NA, and OC source their list of countries from octodns.record.geo_data
  rather than manually duplicating the information here.
* Add TL to the list of special case countries so that it can be individually
  targeted
* Fix for rule ordering when there's > 10 rules
* Fixed persistent change issue with dynamic records after the API started
  returning new fields under `config`
* Fixed persistent change bug when a dynamic record is updated to be a
  non-dynamic simple record

## v0.0.3 - 2023-01-24 - Support the root

* Enable SUPPORTS_ROOT_NS for management of root NS records. Requires
  octodns>=0.9.16.
* Configurable http version for dynamic HTTPS monitors, to enable HTTP/1.1 support

## v0.0.2 - 2022-02-02 - pycountry-convert install_requires

* install_requires includes pycountry-convert as it's a runtime requirement
* other misc script/tooling improvements

## v0.0.1 - 2022-01-03 - Moving

#### Noteworthy Changes

* Initial extraction of Ns1Provider from octoDNS core

#### Stuff

Nothing
