## v0.0.8 - 2024-??-?? - 

* DNAME, DS, and TLSA record type support added.

## v0.0.7 - 2023-11-14 - Maintenance release

* Improved NS1 API error logging
* Misc improvements to the CI setup, documentation and fix to the release
  packaging metadata

## v0.0.6 - 2023-09-28 - Dynamic zones & bug fixes

* Adds Provider.list_zones to enable new dynamic zone config functionality
* Fix bug around root NS records when creating a new zone. See https://github.com/octodns/octodns-ns1/issues/48
* Bump to [octodns v1.2.0](https://pypi.org/project/octodns/1.2.0/) to pull subnet-targeting related bug fixes

## v0.0.5 - 2023-07-27 - Dynamic Subnets

* Allow using actual HTTP monitors instead of emulating them in TCP monitors.
  Doing this is not forward-compatible, ie octodns-ns1 cannot be downgraded to
  a previous version that doesn't support modern HTTP monitors. It also doesn't
  honor the `http_version` configuration because these monitors can only talk
  HTTP/1.1.
* Newly added support for subnet targeting using the Netfence Prefix filter

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
