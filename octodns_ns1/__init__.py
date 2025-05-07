#
#
#

from collections import defaultdict
from collections.abc import Mapping
from itertools import chain
from logging import getLogger
from time import sleep
from uuid import uuid4

from ns1 import NS1
from ns1.rest.errors import RateLimitException, ResourceException

from octodns.provider import ProviderException, SupportsException
from octodns.provider.base import BaseProvider
from octodns.record import Create, Record, Update
from octodns.record.geo import GeoCodes
from octodns.record.geo_data import geo_data

# TODO: remove __VERSION__ with the next major version release
__version__ = __VERSION__ = '1.0.1'


def _ensure_endswith_dot(string):
    return string if string.endswith('.') else f'{string}.'


class Ns1Exception(ProviderException):
    pass


class Ns1Client(object):
    log = getLogger('NS1Client')

    def __init__(
        self, api_key, parallelism=None, retry_count=4, client_config=None
    ):
        self.log.debug(
            '__init__: parallelism=%s, retry_count=%d, client_config=%s',
            parallelism,
            retry_count,
            client_config,
        )
        self.retry_count = retry_count

        client = NS1(apiKey=api_key)

        # NS1 rate limits via a "token bucket" scheme, and provides information
        # about rate limiting in headers on responses. Token bucket can be
        # thought of as an initially "full" bucket, where, if not full, tokens
        # are added at some rate. This allows "bursting" requests until the
        # bucket is empty, after which, you are limited to the rate of token
        # replenishment.
        # There are a couple of "strategies" built into the SDK to avoid 429s
        # from rate limiting. Since octodns operates concurrently via
        # `max_workers`, a concurrent strategy seems appropriate.
        # This strategy does nothing until the remaining requests are equal to
        # or less than our `parallelism`, after which, each process will sleep
        # for the token replenishment interval times parallelism.
        # For example, if we can make 10 requests in 60 seconds, a token is
        # replenished every 6 seconds. If parallelism is 3, we will burst 7
        # requests, and subsequently each process will sleep for 18 seconds
        # before making another request.
        # In general, parallelism should match the number of workers.
        if parallelism is not None:
            client.config['rate_limit_strategy'] = 'concurrent'
            client.config['parallelism'] = parallelism

        # The list of records for a zone is paginated at around ~2.5k records,
        # this tells the client to handle any of that transparently and ensure
        # we get the full list of records.
        client.config['follow_pagination'] = True

        # additional options or overrides
        if isinstance(client_config, Mapping):
            for k, v in client_config.items():
                client.config[k] = v

        self._client = client

        self._records = client.records()
        self._zones = client.zones()
        self._monitors = client.monitors()
        self._notifylists = client.notifylists()
        self._datasource = client.datasource()
        self._datafeed = client.datafeed()

        self.reset_caches()

    def reset_caches(self):
        self._datasource_id = None
        self._feeds_for_monitors = None
        self._monitors_cache = None
        self._notifylists_cache = None
        self._zones_cache = {}
        self._records_cache = {}

    def update_record_cache(func):
        def call(self, zone, domain, _type, **params):
            if zone in self._zones_cache:
                # remove record's zone from cache
                del self._zones_cache[zone]

            cached = self._records_cache.setdefault(zone, {}).setdefault(
                domain, {}
            )

            if _type in cached:
                # remove record from cache
                del cached[_type]

            # write record to cache if its not a delete
            new_record = func(self, zone, domain, _type, **params)
            if new_record:
                cached[_type] = new_record

            return new_record

        return call

    def read_or_set_record_cache(func):
        def call(self, zone, domain, _type):
            cached = self._records_cache.setdefault(zone, {}).setdefault(
                domain, {}
            )
            if _type not in cached:
                cached[_type] = func(self, zone, domain, _type)

            return cached[_type]

        return call

    @property
    def datasource_id(self):
        if self._datasource_id is None:
            name = 'octoDNS NS1 Data Source'
            source = None
            for candidate in self.datasource_list():
                if candidate['name'] == name:
                    # Found it
                    source = candidate
                    break

            if source is None:
                self.log.info('datasource_id: creating datasource %s', name)
                # We need to create it
                source = self.datasource_create(
                    name=name, sourcetype='nsone_monitoring'
                )
                self.log.info('datasource_id:   id=%s', source['id'])

            self._datasource_id = source['id']

        return self._datasource_id

    @property
    def feeds_for_monitors(self):
        if self._feeds_for_monitors is None:
            self.log.debug('feeds_for_monitors: fetching & building')
            self._feeds_for_monitors = {
                f['config']['jobid']: f['id']
                for f in self.datafeed_list(self.datasource_id)
            }

        return self._feeds_for_monitors

    @property
    def monitors(self):
        if self._monitors_cache is None:
            self.log.debug('monitors: fetching & building')
            self._monitors_cache = {m['id']: m for m in self.monitors_list()}
        return self._monitors_cache

    @property
    def notifylists(self):
        if self._notifylists_cache is None:
            self.log.debug('notifylists: fetching & building')
            self._notifylists_cache = {
                l['name']: l for l in self.notifylists_list()
            }
        return self._notifylists_cache

    def datafeed_create(self, sourceid, name, config):
        ret = self._try(self._datafeed.create, sourceid, name, config)
        self.feeds_for_monitors[config['jobid']] = ret['id']
        return ret

    def datafeed_delete(self, sourceid, feedid):
        ret = self._try(self._datafeed.delete, sourceid, feedid)
        self._feeds_for_monitors = {
            k: v for k, v in self._feeds_for_monitors.items() if v != feedid
        }
        return ret

    def datafeed_list(self, sourceid):
        return self._try(self._datafeed.list, sourceid)

    def datasource_create(self, **body):
        return self._try(self._datasource.create, **body)

    def datasource_list(self):
        return self._try(self._datasource.list)

    def monitors_create(self, **params):
        body = {}
        ret = self._try(self._monitors.create, body, **params)
        self.monitors[ret['id']] = ret
        return ret

    def monitors_delete(self, jobid):
        ret = self._try(self._monitors.delete, jobid)
        self.monitors.pop(jobid)
        return ret

    def monitors_list(self):
        return self._try(self._monitors.list)

    def monitors_update(self, job_id, **params):
        body = {}
        ret = self._try(self._monitors.update, job_id, body, **params)
        self.monitors[ret['id']] = ret
        return ret

    def notifylists_delete(self, nlid):
        for name, nl in self.notifylists.items():
            if nl['id'] == nlid:
                del self._notifylists_cache[name]
                break
        return self._try(self._notifylists.delete, nlid)

    def notifylists_create(self, **body):
        nl = self._try(self._notifylists.create, body)
        # cache it
        self.notifylists[nl['name']] = nl
        return nl

    def notifylists_list(self):
        return self._try(self._notifylists.list)

    @update_record_cache
    def records_create(self, zone, domain, _type, **params):
        return self._try(self._records.create, zone, domain, _type, **params)

    @update_record_cache
    def records_delete(self, zone, domain, _type):
        return self._try(self._records.delete, zone, domain, _type)

    @read_or_set_record_cache
    def records_retrieve(self, zone, domain, _type):
        return self._try(self._records.retrieve, zone, domain, _type)

    @update_record_cache
    def records_update(self, zone, domain, _type, **params):
        return self._try(self._records.update, zone, domain, _type, **params)

    def zones_create(self, name):
        self._zones_cache[name] = self._try(self._zones.create, name)
        return self._zones_cache[name]

    def zones_retrieve(self, name):
        if name not in self._zones_cache:
            self._zones_cache[name] = self._try(self._zones.retrieve, name)
        return self._zones_cache[name]

    def zones_list(self):
        # TODO: explore caching all of these if they have sufficient details
        return self._try(self._zones.list)

    def _try(self, method, *args, **kwargs):
        tries = self.retry_count
        while True:  # We'll raise to break after our tries expire
            try:
                return method(*args, **kwargs)
            except RateLimitException as e:
                if tries <= 1:
                    raise
                period = float(e.period)
                self.log.warning(
                    'rate limit encountered, pausing '
                    'for %ds and trying again, %d remaining',
                    period,
                    tries,
                )
                sleep(period)
                tries -= 1
            except ResourceException as e:
                if not e.response or e.response.status_code != 404:
                    self.log.exception(
                        "_try: method=%s, args=%s, response=%s, body=%s",
                        method.__name__,
                        str(args),
                        e.response,
                        e.body,
                    )
                raise


class Ns1Provider(BaseProvider):
    SUPPORTS_GEO = True
    SUPPORTS_DYNAMIC = True
    SUPPORTS_POOL_VALUE_STATUS = True
    SUPPORTS_DYNAMIC_SUBNETS = True
    SUPPORTS_MULTIVALUE_PTR = True
    SUPPORTS_ROOT_NS = True
    SUPPORTS = set(
        (
            'A',
            'AAAA',
            'ALIAS',
            'CAA',
            'CNAME',
            'DNAME',
            'DS',
            'MX',
            'NAPTR',
            'NS',
            'PTR',
            'SPF',
            'SRV',
            'TLSA',
            'TXT',
            'URLFWD',
        )
    )

    ZONE_NOT_FOUND_MESSAGE = 'server error: zone not found'
    SHARED_NOTIFYLIST_NAME = 'octoDNS NS1 Notify List'

    @property
    def _UP_FILTER(self):
        return {'config': {}, 'filter': 'up'}

    @property
    def _REGION_FILTER(self):
        return {
            'config': {'remove_no_georegion': True},
            'filter': u'geofence_regional',
        }

    @property
    def _COUNTRY_FILTER(self):
        return {
            'config': {'remove_no_location': True},
            'filter': u'geofence_country',
        }

    @property
    def _SUBNET_FILTER(self):
        return {
            'config': {'remove_no_ip_prefixes': True},
            'filter': u'netfence_prefix',
        }

    # In the NS1 UI/portal, this filter is called "SELECT FIRST GROUP" though
    # the filter name in the NS1 api is 'select_first_region'
    @property
    def _SELECT_FIRST_REGION_FILTER(self):
        return {'config': {}, 'filter': u'select_first_region'}

    @property
    def _PRIORITY_FILTER(self):
        return {'config': {'eliminate': u'1'}, 'filter': 'priority'}

    @property
    def _WEIGHTED_SHUFFLE_FILTER(self):
        return {'config': {}, 'filter': u'weighted_shuffle'}

    @property
    def _SELECT_FIRST_N_FILTER(self):
        return {'config': {'N': u'1'}, 'filter': u'select_first_n'}

    @property
    def _BASIC_FILTER_CHAIN(self):
        return [
            self._UP_FILTER,
            self._SELECT_FIRST_REGION_FILTER,
            self._PRIORITY_FILTER,
            self._WEIGHTED_SHUFFLE_FILTER,
            self._SELECT_FIRST_N_FILTER,
        ]

    @property
    def _FILTER_CHAIN_WITH_REGION(self):
        return [
            self._UP_FILTER,
            self._REGION_FILTER,
            self._SELECT_FIRST_REGION_FILTER,
            self._PRIORITY_FILTER,
            self._WEIGHTED_SHUFFLE_FILTER,
            self._SELECT_FIRST_N_FILTER,
        ]

    @property
    def _FILTER_CHAIN_WITH_COUNTRY(self):
        return [
            self._UP_FILTER,
            self._COUNTRY_FILTER,
            self._SELECT_FIRST_REGION_FILTER,
            self._PRIORITY_FILTER,
            self._WEIGHTED_SHUFFLE_FILTER,
            self._SELECT_FIRST_N_FILTER,
        ]

    @property
    def _FILTER_CHAIN_WITH_SUBNET(self):
        return [
            self._UP_FILTER,
            self._SUBNET_FILTER,
            self._SELECT_FIRST_REGION_FILTER,
            self._PRIORITY_FILTER,
            self._WEIGHTED_SHUFFLE_FILTER,
            self._SELECT_FIRST_N_FILTER,
        ]

    @property
    def _FILTER_CHAIN_WITH_REGION_AND_COUNTRY(self):
        return [
            self._UP_FILTER,
            self._COUNTRY_FILTER,
            self._REGION_FILTER,
            self._SELECT_FIRST_REGION_FILTER,
            self._PRIORITY_FILTER,
            self._WEIGHTED_SHUFFLE_FILTER,
            self._SELECT_FIRST_N_FILTER,
        ]

    @property
    def _FILTER_CHAIN_WITH_REGION_AND_SUBNET(self):
        return [
            self._UP_FILTER,
            self._SUBNET_FILTER,
            self._REGION_FILTER,
            self._SELECT_FIRST_REGION_FILTER,
            self._PRIORITY_FILTER,
            self._WEIGHTED_SHUFFLE_FILTER,
            self._SELECT_FIRST_N_FILTER,
        ]

    @property
    def _FILTER_CHAIN_WITH_COUNTRY_AND_SUBNET(self):
        return [
            self._UP_FILTER,
            self._SUBNET_FILTER,
            self._COUNTRY_FILTER,
            self._SELECT_FIRST_REGION_FILTER,
            self._PRIORITY_FILTER,
            self._WEIGHTED_SHUFFLE_FILTER,
            self._SELECT_FIRST_N_FILTER,
        ]

    @property
    def _FILTER_CHAIN_WITH_REGION_AND_COUNTRY_AND_SUBNET(self):
        return [
            self._UP_FILTER,
            self._SUBNET_FILTER,
            self._COUNTRY_FILTER,
            self._REGION_FILTER,
            self._SELECT_FIRST_REGION_FILTER,
            self._PRIORITY_FILTER,
            self._WEIGHTED_SHUFFLE_FILTER,
            self._SELECT_FIRST_N_FILTER,
        ]

    _REGION_TO_CONTINENT = {
        'AFRICA': 'AF',
        'ASIAPAC': 'AS',
        'EUROPE': 'EU',
        'SOUTH-AMERICA': 'SA',
        # continent NA has been handled as part of Geofence Country filter
        # starting from v0.9.13. These below US-* just need to continue to
        # exist here so it doesn't break the ugrade path
        'US-CENTRAL': 'NA',
        'US-EAST': 'NA',
        'US-WEST': 'NA',
    }
    _CONTINENT_TO_REGIONS = {
        'AF': ('AFRICA',),
        'EU': ('EUROPE',),
        'SA': ('SOUTH-AMERICA',),
    }

    # Necessary for handling unsupported continents in _CONTINENT_TO_REGIONS
    _CONTINENT_TO_LIST_OF_COUNTRIES = {
        'AS': set(geo_data['AS'].keys()),
        'OC': set(geo_data['OC'].keys()),
        'NA': set(geo_data['NA'].keys()),
    }

    def __init__(
        self,
        id,
        api_key,
        retry_count=4,
        monitor_regions=[],
        parallelism=None,
        client_config=None,
        shared_notifylist=False,
        use_http_monitors=False,
        default_healthcheck_http_version="HTTP/1.0",
        *args,
        **kwargs,
    ):
        self.log = getLogger(f'Ns1Provider[{id}]')
        self.log.debug(
            '__init__: id=%s, api_key=***, retry_count=%d, '
            'monitor_regions=%s, parallelism=%s, client_config=%s, '
            'shared_notifylist=%s, use_http_monitors=%s, '
            'default_healthcheck_http_version=%s',
            id,
            retry_count,
            monitor_regions,
            parallelism,
            client_config,
            shared_notifylist,
            use_http_monitors,
            default_healthcheck_http_version,
        )
        super().__init__(id, *args, **kwargs)
        self.monitor_regions = monitor_regions
        self.shared_notifylist = shared_notifylist
        self.use_http_monitors = use_http_monitors
        self.record_filters = dict()
        self._client = Ns1Client(
            api_key, parallelism, retry_count, client_config
        )
        self.default_healthcheck_http_version = default_healthcheck_http_version

    def _sanitize_disabled_in_filter_config(self, filter_cfg):
        # remove disabled=False from filters
        for filter in filter_cfg:
            if 'disabled' in filter and filter['disabled'] is False:
                del filter['disabled']
        return filter_cfg

    def _valid_filter_config(self, filter_cfg):
        self._sanitize_disabled_in_filter_config(filter_cfg)
        has_region = self._REGION_FILTER in filter_cfg
        has_country = self._COUNTRY_FILTER in filter_cfg
        has_subnet = self._SUBNET_FILTER in filter_cfg
        expected_filter_cfg = self._get_updated_filter_chain(
            has_region, has_country, has_subnet
        )
        return filter_cfg == expected_filter_cfg

    def _get_updated_filter_chain(self, has_region, has_country, has_subnet):
        if has_region and has_country and has_subnet:
            filter_chain = self._FILTER_CHAIN_WITH_REGION_AND_COUNTRY_AND_SUBNET
        elif has_region and has_country:
            filter_chain = self._FILTER_CHAIN_WITH_REGION_AND_COUNTRY
        elif has_region and has_subnet:
            filter_chain = self._FILTER_CHAIN_WITH_REGION_AND_SUBNET
        elif has_country and has_subnet:
            filter_chain = self._FILTER_CHAIN_WITH_COUNTRY_AND_SUBNET
        elif has_region:
            filter_chain = self._FILTER_CHAIN_WITH_REGION
        elif has_country:
            filter_chain = self._FILTER_CHAIN_WITH_COUNTRY
        elif has_subnet:
            filter_chain = self._FILTER_CHAIN_WITH_SUBNET
        else:
            filter_chain = self._BASIC_FILTER_CHAIN

        return filter_chain

    def _encode_notes(self, data):
        return ' '.join([f'{k}:{v}' for k, v in sorted(data.items())])

    def _parse_notes(self, note):
        data = {}
        if note:
            for piece in note.split(' '):
                try:
                    k, v = piece.split(':', 1)
                except ValueError:
                    continue
                try:
                    v = int(v)
                except ValueError:
                    pass
                data[k] = v if v != '' else None
        return data

    def _parse_dynamic_pool_name(self, pool_name):
        catchall_prefix = 'catchall__'
        if pool_name.startswith(catchall_prefix):
            # Special case for the old-style catchall prefix
            return pool_name[len(catchall_prefix) :]
        try:
            pool_name, _ = pool_name.rsplit('__', 1)
        except ValueError:
            pass
        return pool_name

    def _parse_pools(self, answers):
        # All regions (pools) will include the list of default values
        # (eventually) at higher priorities, we'll just add them to this set to
        # we'll have the complete collection.
        default = set()

        # Fill out the pools by walking the answers and looking at their
        # region (< v0.9.11) or notes (> v0.9.11).
        pools = defaultdict(lambda: {'fallback': None, 'values': []})
        for answer in answers:
            meta = answer['meta']
            notes = self._parse_notes(meta.get('note', ''))

            value = str(answer['answer'][0])
            if notes.get('from', False) == '--default--':
                # It's a final/default value, record it and move on
                default.add(value)
                continue

            # NS1 pool names can be found in notes > v0.9.11, in order to allow
            # us to find fallback-only pools/values. Before that we used
            # `region` (group name in the UI) and only paid attention to
            # priority=1 (first level)
            notes_pool_name = notes.get('pool', None)
            if notes_pool_name is None:
                # < v0.9.11
                if meta['priority'] != 1:
                    # Ignore all but priority 1
                    continue
                # And use region's name as the pool name
                pool_name = self._parse_dynamic_pool_name(answer['region'])
            else:
                # > v0.9.11, use the notes-based name and consider all values
                pool_name = notes_pool_name

            pool = pools[pool_name]
            value_dict = {'value': value, 'weight': int(meta.get('weight', 1))}
            if isinstance(meta['up'], bool):
                value_dict['status'] = 'up' if meta['up'] else 'down'

            if value_dict not in pool['values']:
                # If we haven't seen this value before add it to the pool
                pool['values'].append(value_dict)

            # If there's a fallback recorded in the value for its pool go ahead
            # and use it, another v0.9.11 thing
            fallback = notes.get('fallback', None)
            if fallback is not None:
                pool['fallback'] = fallback

        # Order and convert to a list
        default = sorted(default)

        return default, pools

    def _parse_rule_geos(self, meta, notes):
        geos = set()

        for georegion in meta.get('georegion', []):
            geos.add(self._REGION_TO_CONTINENT[georegion])

        # Countries are easy enough to map, we just have to find their
        # continent
        #
        # NOTE: Some continents need special handling since NS1
        # does not supprt them as regions. These are defined under
        # _CONTINENT_TO_LIST_OF_COUNTRIES. So the countries for these
        # regions will be present in meta['country']. If all the countries
        # in _CONTINENT_TO_LIST_OF_COUNTRIES[<region>] list are found,
        # set the continent as the region and remove individual countries

        # continents that don't have all countries here because a subset of
        # them were used in another rule, but we still need this rule to use
        # continent instead of the remaining subset of its countries
        continents_from_notes = set(notes.get('continents', '').split(','))

        special_continents = dict()
        for country in meta.get('country', []):
            geo_code = GeoCodes.country_to_code(country)
            con = GeoCodes.parse(geo_code)['continent_code']

            if con in self._CONTINENT_TO_LIST_OF_COUNTRIES:
                special_continents.setdefault(con, set()).add(country)
            else:
                geos.add(geo_code)

        for continent, countries in special_continents.items():
            if (
                countries == self._CONTINENT_TO_LIST_OF_COUNTRIES[continent]
                or continent in continents_from_notes
            ):
                # All countries found or continent in notes, so add it to geos
                geos.add(continent)
            else:
                # Partial countries found, so just add them as-is to geos
                for c in countries:
                    geos.add(f'{continent}-{c}')

        # States and provinces are easy too,
        # just assume NA-US or NA-CA
        for state in meta.get('us_state', []):
            geos.add(f'NA-US-{state}')

        for province in meta.get('ca_province', []):
            geos.add(f'NA-CA-{province}')

        return geos

    def _parse_rules(self, pools, regions):
        # The regions objects map to rules, but it's a bit fuzzy since they're
        # tied to pools on the NS1 side, e.g. we can only have 1 rule per pool,
        # that may eventually run into problems, but I don't have any use-cases
        # examples currently where it would
        rules = {}
        for pool_name, region in sorted(regions.items()):
            # Get the actual pool name by removing the type
            pool_name = self._parse_dynamic_pool_name(pool_name)

            meta = region['meta']
            notes = self._parse_notes(meta.get('note', ''))

            # The group notes field in the UI is a `note` on the region here,
            # that's where we can find our pool's fallback in < v0.9.11 anyway
            if 'fallback' in notes:
                # set the fallback pool name
                pools[pool_name]['fallback'] = notes['fallback']

            rule_order = notes['rule-order']
            try:
                rule = rules[rule_order]
            except KeyError:
                rule = {'pool': pool_name, '_order': rule_order}
                rules[rule_order] = rule

            geos = self._parse_rule_geos(meta, notes)
            if geos:
                # There are geos, combine them with any existing geos for this
                # pool and recorded the sorted unique set of them
                rule['geos'] = sorted(set(rule.get('geos', [])) | geos)
            subnets = set(meta.get('ip_prefixes', []))
            if subnets:
                rule['subnets'] = sorted(subnets)

        # Convert to list and order
        rules = sorted(rules.values(), key=lambda r: (r['_order'], r['pool']))

        return rules

    def _data_for_dynamic(self, _type, record):
        # Cache record filters for later use
        record_filters = self.record_filters.setdefault(record['domain'], {})
        record_filters[_type] = record['filters']

        default, pools = self._parse_pools(record['answers'])
        rules = self._parse_rules(pools, record['regions'])

        data = {
            'dynamic': {'pools': pools, 'rules': rules},
            'ttl': record['ttl'],
            'type': _type,
        }

        if _type == 'CNAME':
            data['value'] = default[0]
        else:
            data['values'] = default

        return data

    def _data_for_A(self, _type, record):
        if record.get('tier', 1) > 1:
            # Advanced record, see if it's first answer has a note
            try:
                first_answer_note = record['answers'][0]['meta']['note']
            except (IndexError, KeyError):
                first_answer_note = ''
            # If that note includes a `pool` it's a valid dynamic record
            if 'from:' in first_answer_note:
                # it's a dynamic record
                return self._data_for_dynamic(_type, record)
            # If not, it can't be parsed. Let it be an empty record
            self.log.warning(
                'Cannot parse %s dynamic record due to missing '
                'pool name in first answer note, treating it as '
                'an empty record',
                record['domain'],
            )
            values = []
        else:
            values = [str(x) for x in record['short_answers']]

        # This is a basic record, just convert it
        return {'ttl': record['ttl'], 'type': _type, 'values': values}

    _data_for_AAAA = _data_for_A

    def _data_for_SPF(self, _type, record):
        values = [v.replace(';', '\\;') for v in record['short_answers']]
        return {'ttl': record['ttl'], 'type': _type, 'values': values}

    _data_for_TXT = _data_for_SPF

    def _data_for_CAA(self, _type, record):
        values = []
        for answer in record['short_answers']:
            flags, tag, value = answer.split(' ', 2)
            values.append({'flags': flags, 'tag': tag, 'value': value})
        return {'ttl': record['ttl'], 'type': _type, 'values': values}

    def _data_for_CNAME(self, _type, record):
        if record.get('tier', 1) > 1:
            # Advanced record, see if it's first answer has a note
            try:
                first_answer_note = record['answers'][0]['meta']['note']
            except (IndexError, KeyError):
                first_answer_note = ''
            # If that note includes a `pool` it's a valid dynamic record
            if 'pool:' in first_answer_note:
                return self._data_for_dynamic(_type, record)
            # If not, it can't be parsed. Let it be an empty record
            self.log.warning(
                'Cannot parse %s dynamic record due to missing '
                'pool name in first answer note, treating it as '
                'an empty record',
                record['domain'],
            )
            value = None
        else:
            try:
                value = record['short_answers'][0]
            except IndexError:
                value = None

        return {'ttl': record['ttl'], 'type': _type, 'value': value}

    _data_for_ALIAS = _data_for_CNAME
    _data_for_DNAME = _data_for_CNAME

    def _data_for_MX(self, _type, record):
        values = []
        for answer in record['short_answers']:
            preference, exchange = answer.split(' ', 1)
            values.append({'preference': preference, 'exchange': exchange})
        return {'ttl': record['ttl'], 'type': _type, 'values': values}

    def _data_for_NAPTR(self, _type, record):
        values = []
        for answer in record['short_answers']:
            (order, preference, flags, service, regexp, replacement) = (
                answer.split(' ', 5)
            )
            values.append(
                {
                    'flags': flags,
                    'order': order,
                    'preference': preference,
                    'regexp': regexp,
                    'replacement': replacement,
                    'service': service,
                }
            )
        return {'ttl': record['ttl'], 'type': _type, 'values': values}

    def _data_for_NS(self, _type, record):
        return {
            'ttl': record['ttl'],
            'type': _type,
            'values': record['short_answers'],
        }

    _data_for_PTR = _data_for_NS

    def _data_for_SRV(self, _type, record):
        values = []
        for answer in record['short_answers']:
            priority, weight, port, target = answer.split(' ', 3)
            values.append(
                {
                    'priority': priority,
                    'weight': weight,
                    'port': port,
                    'target': target,
                }
            )
        return {'ttl': record['ttl'], 'type': _type, 'values': values}

    def _data_for_URLFWD(self, _type, record):
        values = []
        for answer in record['short_answers']:
            path, target, code, masking, query = answer.split(' ', 4)
            values.append(
                {
                    'path': path,
                    'target': target,
                    'code': code,
                    'masking': masking,
                    'query': query,
                }
            )
        return {'ttl': record['ttl'], 'type': _type, 'values': values}

    def _data_for_DS(self, _type, record):
        values = []
        for answer in record['short_answers']:
            key_tag, algorithm, digest_type, digest = answer.split(' ', 3)
            values.append(
                {
                    'key_tag': key_tag,
                    'algorithm': algorithm,
                    'digest_type': digest_type,
                    'digest': digest,
                }
            )
        return {'ttl': record['ttl'], 'type': _type, 'values': values}

    def _data_for_TLSA(self, _type, record):
        values = []
        for answer in record['short_answers']:
            (
                certificate_usage,
                selector,
                matching_type,
                certificate_association_data,
            ) = answer.split(' ', 3)
            values.append(
                {
                    'certificate_usage': certificate_usage,
                    'selector': selector,
                    'matching_type': matching_type,
                    'certificate_association_data': certificate_association_data,
                }
            )
        return {'ttl': record['ttl'], 'type': _type, 'values': values}

    def list_zones(self):
        return sorted([f'{z["zone"]}.' for z in self._client.zones_list()])

    def populate(self, zone, target=False, lenient=False):
        self.log.debug(
            'populate: name=%s, target=%s, lenient=%s',
            zone.name,
            target,
            lenient,
        )

        try:
            ns1_zone_name = zone.name[:-1]
            ns1_zone = self._client.zones_retrieve(ns1_zone_name)

            records = []
            geo_records = []

            # change answers for certain types to always be absolute
            for record in ns1_zone['records']:
                if record['type'] in [
                    'ALIAS',
                    'CNAME',
                    'MX',
                    'NS',
                    'PTR',
                    'SRV',
                ]:
                    record['short_answers'] = [
                        _ensure_endswith_dot(a)
                        for a in record.get('short_answers', [])
                    ]

                if record.get('tier', 1) > 1:
                    # Need to get the full record data for geo records
                    record = self._client.records_retrieve(
                        ns1_zone_name, record['domain'], record['type']
                    )
                    geo_records.append(record)
                else:
                    records.append(record)

            exists = True
        except ResourceException as e:
            if e.message != self.ZONE_NOT_FOUND_MESSAGE:
                raise
            records = []
            geo_records = []
            exists = False

        before = len(zone.records)
        # geo information isn't returned from the main endpoint, so we need
        # to query for all records with geo information
        zone_hash = {}
        for record in chain(records, geo_records):
            _type = record['type']
            if _type not in self.SUPPORTS:
                continue
            data_for = getattr(self, f'_data_for_{_type}')
            name = zone.hostname_from_fqdn(record['domain'])
            data = data_for(_type, record)
            record = Record.new(zone, name, data, source=self, lenient=lenient)
            zone_hash[(_type, name)] = record
        [zone.add_record(r, lenient=lenient) for r in zone_hash.values()]
        self.log.info(
            'populate:   found %s records, exists=%s',
            len(zone.records) - before,
            exists,
        )
        return exists

    def _process_desired_zone(self, desired):
        for record in desired.records:
            if getattr(record, 'dynamic', False):
                protocol = record.healthcheck_protocol
                if protocol not in ('HTTP', 'HTTPS', 'ICMP', 'TCP'):
                    msg = f'healthcheck protocol "{protocol}" not supported'
                    # no workable fallbacks so straight error
                    raise SupportsException(f'{self.id}: {msg}')

                # validate supported geos
                for rule in record.dynamic.rules:
                    for geo in rule.data.get('geos', []):
                        if (
                            len(geo) == 2
                            and geo not in self._REGION_TO_CONTINENT.values()
                        ):
                            msg = f'unsupported continent code {geo} in {record.fqdn}'
                            # no workable fallbacks so straight error
                            raise SupportsException(f'{self.id}: {msg}')

        return super()._process_desired_zone(desired)

    def _monitors_for(self, record):
        monitors = {}

        if getattr(record, 'dynamic', False):
            expected_host = record.fqdn[:-1]
            expected_type = record._type

            for monitor in self._client.monitors.values():
                data = self._parse_notes(monitor['notes'])
                if not data:
                    continue
                if (
                    expected_host == data['host']
                    and expected_type == data['type']
                ):
                    # This monitor belongs to this record
                    value = data.get('value')
                    if not value:
                        # old style notes in TCP monitors
                        value = monitor['config']['host']
                    if record._type == 'CNAME':
                        # Append a trailing dot for CNAME records so that
                        # lookup by a CNAME answer works
                        value = value + '.'
                    monitors[value] = monitor

        return monitors

    def _uuid(self):
        return uuid4().hex

    def _feed_create(self, monitor):
        monitor_id = monitor['id']
        self.log.debug('_feed_create: monitor=%s', monitor_id)
        name = f'{monitor["name"]} - {self._uuid()[:6]}'

        # Create the data feed
        config = {'jobid': monitor_id}
        feed = self._client.datafeed_create(
            self._client.datasource_id, name, config
        )
        feed_id = feed['id']
        self.log.debug('_feed_create:   feed=%s', feed_id)

        return feed_id

    def _notifylists_find_or_create(self, name):
        self.log.debug('_notifylists_find_or_create: name="%s"', name)
        try:
            nl = self._client.notifylists[name]
            self.log.debug(
                '_notifylists_find_or_create:   existing=%s', nl['id']
            )
        except KeyError:
            notify_list = [
                {
                    'config': {'sourceid': self._client.datasource_id},
                    'type': 'datafeed',
                }
            ]
            nl = self._client.notifylists_create(
                name=name, notify_list=notify_list
            )
            self.log.debug(
                '_notifylists_find_or_create:   created=%s', nl['id']
            )

        return nl

    def _monitor_create(self, monitor):
        self.log.debug('_monitor_create: monitor="%s"', monitor['name'])

        # Find the right notifylist
        nl_name = (
            self.SHARED_NOTIFYLIST_NAME
            if self.shared_notifylist
            else monitor['name']
        )
        nl = self._notifylists_find_or_create(nl_name)

        # Create the monitor
        monitor['notify_list'] = nl['id']
        monitor = self._client.monitors_create(**monitor)
        monitor_id = monitor['id']
        self.log.debug('_monitor_create:   monitor=%s', monitor_id)

        return monitor_id, self._feed_create(monitor)

    def _monitor_delete(self, monitor):
        monitor_id = monitor['id']
        feed_id = self._client.feeds_for_monitors.get(monitor_id)
        if feed_id:
            self._client.datafeed_delete(self._client.datasource_id, feed_id)

        self._client.monitors_delete(monitor_id)

        notify_list_id = monitor['notify_list']
        for nl_name, nl in self._client.notifylists.items():
            if nl['id'] == notify_list_id:
                # We've found the that might need deleting
                if nl['name'] != self.SHARED_NOTIFYLIST_NAME:
                    # It's not shared so is safe to delete
                    self._client.notifylists_delete(notify_list_id)
                break

    def _healthcheck_policy(self, record):
        return (
            record.octodns.get('ns1', {})
            .get('healthcheck', {})
            .get('policy', 'quorum')
        )

    def _healthcheck_frequency(self, record):
        return (
            record.octodns.get('ns1', {})
            .get('healthcheck', {})
            .get('frequency', 60)
        )

    def _healthcheck_rapid_recheck(self, record):
        return (
            record.octodns.get('ns1', {})
            .get('healthcheck', {})
            .get('rapid_recheck', False)
        )

    def _healthcheck_connect_timeout(self, record):
        return (
            record.octodns.get('ns1', {})
            .get('healthcheck', {})
            .get('connect_timeout', 2)
        )

    def _healthcheck_response_timeout(self, record):
        return (
            record.octodns.get('ns1', {})
            .get('healthcheck', {})
            .get('response_timeout', 10)
        )

    def _healthcheck_http_version(self, record):
        http_version = (
            record.octodns.get("ns1", {})
            .get("healthcheck", {})
            .get("http_version", self.default_healthcheck_http_version)
        )
        acceptable_http_versions = ("HTTP/1.0", "HTTP/1.1")
        if http_version not in acceptable_http_versions:
            raise Ns1Exception(
                f"unsupported http version found: {http_version!r}. Expected version in {acceptable_http_versions}"
            )
        return http_version

    def _monitor_gen(self, record, value):
        host = record.fqdn[:-1]
        _type = record._type

        if _type == 'CNAME':
            # NS1 does not accept a host value with a trailing dot
            value = value[:-1]

        ret = {
            'active': True,
            'name': f'{host} - {_type} - {value}',
            'notes': {'host': host, 'type': _type},
            'policy': self._healthcheck_policy(record),
            'frequency': self._healthcheck_frequency(record),
            'rapid_recheck': self._healthcheck_rapid_recheck(record),
            'region_scope': 'fixed',
            'regions': self.monitor_regions,
        }

        connect_timeout = self._healthcheck_connect_timeout(record)
        response_timeout = self._healthcheck_response_timeout(record)

        healthcheck_protocol = record.healthcheck_protocol
        if healthcheck_protocol == 'ICMP':
            ret['job_type'] = 'ping'
            ret['config'] = {
                'count': 4,
                'host': value,
                'interval': response_timeout * 250,  # 1/4 response_timeout
                'ipv6': _type == 'AAAA',
                'timeout': response_timeout * 1000,
            }
        elif healthcheck_protocol == 'TCP' or not self.use_http_monitors:
            ret['job_type'] = 'tcp'
            ret['config'] = {
                'host': value,
                'port': record.healthcheck_port,
                # TCP monitors use milliseconds, so convert from seconds to milliseconds
                'connect_timeout': connect_timeout * 1000,
                'response_timeout': response_timeout * 1000,
                'ssl': healthcheck_protocol == 'HTTPS',
            }

            if healthcheck_protocol != 'TCP':
                # legacy HTTP-emulating TCP monitor
                # we need to send the HTTP request string
                path = record.healthcheck_path
                host = record.healthcheck_host(value=value)
                http_version = self._healthcheck_http_version(record)
                request = (
                    fr'GET {path} {http_version}\r\nHost: {host}\r\n'
                    r'User-agent: NS1\r\n\r\n'
                )
                ret['config']['send'] = request
                # We'll also expect a HTTP response
                ret['rules'] = [
                    {
                        'comparison': 'contains',
                        'key': 'output',
                        'value': '200 OK',
                    }
                ]
        else:
            # modern HTTP monitor
            ret['job_type'] = 'http'
            proto = healthcheck_protocol.lower()
            domain = f'[{value}]' if _type == 'AAAA' else value
            port = record.healthcheck_port
            path = record.healthcheck_path
            ret['config'] = {
                'url': f'{proto}://{domain}:{port}{path}',
                'virtual_host': record.healthcheck_host(value=value),
                'user_agent': 'NS1',
                'tls_add_verify': False,
                'follow_redirect': False,
                'connect_timeout': connect_timeout,
                'idle_timeout': response_timeout,
            }
            ret['rules'] = [
                {'comparison': '==', 'key': 'status_code', 'value': '200'}
            ]

        if _type == 'AAAA':
            ret['config']['ipv6'] = True

        if self.use_http_monitors:
            ret['notes']['value'] = value
        ret['notes'] = self._encode_notes(ret['notes'])

        return ret

    def _monitor_is_match(self, expected, have):
        # Make sure what we have matches what's in expected exactly. Anything
        # else in have will be ignored.
        log_prefix = 'monitor mismatch'
        if 'name' in have:
            name = have['name']
            log_prefix = f'monitor "{name}" mismatch'
        for k, v in expected.items():
            if k == 'config':
                # config is a nested dict and we need to only consider keys in
                # expected for it as well
                have_config = have.get(k, {})
                for k, v in v.items():
                    if have_config.get(k, '--missing--') != v:
                        self.log.debug(
                            f'{log_prefix}: got config.{k}={have_config.get(k)}, expected {v}'
                        )
                        return False
            elif k == 'regions':
                # regions can be out of order
                if set(have.get(k, [])) != set(v):
                    self.log.info(
                        f'{log_prefix}: got {k}={have.get(k)}, expected {v}'
                    )
                    return False
            elif have.get(k, '--missing--') != v:
                self.log.info(
                    f'{log_prefix}: got {k}={have.get(k)}, expected {v}'
                )
                return False

        return True

    def _monitor_sync(self, record, value, existing):
        self.log.debug('_monitor_sync: record=%s, value=%s', record.fqdn, value)
        expected = self._monitor_gen(record, value)

        if existing:
            self.log.debug('_monitor_sync:   existing=%s', existing['id'])
            monitor_id = existing['id']
            feed_id = None

            if not self._monitor_is_match(expected, existing):
                if expected['job_type'] == existing['job_type']:
                    self.log.debug('_monitor_sync:   existing needs update')
                    # Update the monitor to match expected, everything else will be
                    # left alone and assumed correct
                    self._client.monitors_update(monitor_id, **expected)
                else:
                    # NS1 monitor job types cannot be changed, so we will do a
                    # delete+create
                    self.log.debug(
                        '_monitor_sync: existing needs to be replaced (delete+create new)'
                    )
                    self._monitor_delete(existing)
                    monitor_id, feed_id = self._monitor_create(expected)

            if not feed_id:
                feed_id = self._client.feeds_for_monitors.get(monitor_id)
                if feed_id is None:
                    self.log.warning(
                        '_monitor_sync: %s (%s) missing feed, creating',
                        existing['name'],
                        monitor_id,
                    )
                    feed_id = self._feed_create(existing)
        else:
            self.log.debug('_monitor_sync:   needs create')
            # We don't have an existing monitor create it (and related bits)
            monitor_id, feed_id = self._monitor_create(expected)

        return monitor_id, feed_id

    def _monitors_gc(self, record, active_monitor_ids=None):
        self.log.debug(
            '_monitors_gc: record=%s, active_monitor_ids=%s',
            record.fqdn,
            active_monitor_ids,
        )

        if active_monitor_ids is None:
            active_monitor_ids = set()

        for monitor in self._monitors_for(record).values():
            monitor_id = monitor['id']
            if monitor_id in active_monitor_ids:
                continue

            self.log.debug('_monitors_gc:   deleting %s', monitor_id)

            self._monitor_delete(monitor)

    def _add_answers_for_pool(
        self,
        answers,
        default_answers,
        pool_name,
        pool_label,
        pool_answers,
        pools,
        priority,
    ):
        current_pool_name = pool_name
        seen = set()
        while current_pool_name and current_pool_name not in seen:
            seen.add(current_pool_name)
            pool = pools[current_pool_name]
            for answer in pool_answers[current_pool_name]:
                fallback = pool.data['fallback']
                if answer['feed_id']:
                    up = {'feed': answer['feed_id']}
                else:
                    up = answer['status'] == 'up'
                answer = {
                    'answer': answer['answer'],
                    'meta': {
                        'priority': priority,
                        'note': self._encode_notes(
                            {
                                'from': pool_label,
                                'pool': current_pool_name,
                                'fallback': fallback or '',
                            }
                        ),
                        'up': up,
                        'weight': answer['weight'],
                    },
                    'region': pool_label,  # the one we're answering
                }
                answers.append(answer)

            current_pool_name = pool.data.get('fallback', None)
            priority += 1

        # Static/default
        for answer in default_answers:
            answer = {
                'answer': answer['answer'],
                'meta': {
                    'priority': priority,
                    'note': self._encode_notes({'from': '--default--'}),
                    'up': True,
                    'weight': 1,
                },
                'region': pool_label,  # the one we're answering
            }
            answers.append(answer)

    def _generate_regions(self, record):
        pools = record.dynamic.pools
        has_subnet = False
        has_country = False
        has_region = False
        regions = {}

        explicit_countries = dict()
        for rule in record.dynamic.rules:
            for geo in rule.data.get('geos', []):
                if len(geo) == 5:
                    con, country = geo.split('-', 1)
                    explicit_countries.setdefault(con, set()).add(country)

        for i, rule in enumerate(record.dynamic.rules):
            pool_name = rule.data['pool']

            notes = {'rule-order': i}

            fallback = pools[pool_name].data.get('fallback', None)
            if fallback:
                notes['fallback'] = fallback

            country = set()
            georegion = set()
            us_state = set()
            ca_province = set()
            subnet = set(rule.data.get('subnets', []))

            for geo in rule.data.get('geos', []):
                n = len(geo)
                if n == 8:
                    # US state, e.g. NA-US-KY
                    # CA province, e.g. NA-CA-NL
                    (
                        us_state.add(geo[-2:])
                        if "NA-US" in geo
                        else ca_province.add(geo[-2:])
                    )
                    # For filtering. State filtering is done by the country
                    # filter
                    has_country = True
                elif n == 5:
                    # Country, e.g. EU-FR
                    country.add(geo[-2:])
                    has_country = True
                else:
                    # Continent, e.g. AS
                    if geo in self._CONTINENT_TO_REGIONS:
                        georegion.update(self._CONTINENT_TO_REGIONS[geo])
                        has_region = True
                    else:
                        # No maps for geo in _CONTINENT_TO_REGIONS.
                        # Use the country list
                        self.log.debug(
                            'Converting geo {} to country list'.format(geo)
                        )
                        continent_countries = (
                            self._CONTINENT_TO_LIST_OF_COUNTRIES[geo]
                        )
                        exclude = explicit_countries.get(geo, set())
                        country.update(continent_countries - exclude)
                        notes.setdefault('continents', set()).add(geo)
                        has_country = True

            if 'continents' in notes:
                notes['continents'] = ','.join(sorted(notes['continents']))

            if subnet:
                has_subnet = True

            meta = {'note': self._encode_notes(notes)}

            if georegion:
                georegion_meta = dict(meta)
                georegion_meta['georegion'] = sorted(georegion)
                regions[f'{pool_name}__georegion'] = {'meta': georegion_meta}

            if country or us_state or ca_province:
                # If there's country and/or states its a country pool,
                # countries and states can coexist as they're handled by the
                # same step in the filterchain (countries and georegions
                # cannot as they're seperate stages and run the risk of
                # eliminating all options)
                country_state_meta = dict(meta)
                if country:
                    country_state_meta['country'] = sorted(country)
                if us_state:
                    country_state_meta['us_state'] = sorted(us_state)
                if ca_province:
                    country_state_meta['ca_province'] = sorted(ca_province)
                regions[f'{pool_name}__country'] = {'meta': country_state_meta}

            if subnet:
                subnet_meta = dict(meta)
                subnet_meta['ip_prefixes'] = sorted(subnet)
                regions[f'{pool_name}__subnet'] = {'meta': subnet_meta}

            if not (subnet or country or us_state or ca_province or georegion):
                # If there's no targeting it's a catchall
                regions[f'{pool_name}__catchall'] = {'meta': meta}

        return has_subnet, has_country, has_region, regions

    def _generate_answers(self, record, regions):
        pools = record.dynamic.pools
        existing_monitors = self._monitors_for(record)
        active_monitors = set()

        # Build a list of primary values for each pool, including their
        # feed_id (monitor)
        value_feed = dict()
        pool_answers = defaultdict(list)
        for pool_name, pool in sorted(pools.items()):
            for value in pool.data['values']:
                weight = value['weight']
                status = value['status']
                value = value['value']

                feed_id = None
                if status == 'obey':
                    # state is not forced, let's find a monitor
                    feed_id = value_feed.get(value)
                    # check for identical monitor and skip creating one if
                    # found
                    if not feed_id:
                        existing = existing_monitors.get(value)
                        monitor_id, feed_id = self._monitor_sync(
                            record, value, existing
                        )
                        value_feed[value] = feed_id
                        active_monitors.add(monitor_id)

                pool_answers[pool_name].append(
                    {
                        'answer': [value],
                        'weight': weight,
                        'feed_id': feed_id,
                        'status': status,
                    }
                )

        if record._type == 'CNAME':
            default_values = [record.value]
        else:
            default_values = record.values
        default_answers = [{'answer': [v], 'weight': 1} for v in default_values]

        # Build our list of answers
        # The regions dictionary built above already has the required pool
        # names. Iterate over them and add answers.
        answers = []
        for pool_label in sorted(regions.keys()):
            priority = 1

            # Remove the pool type from the end of the name
            pool_name = self._parse_dynamic_pool_name(pool_label)
            self._add_answers_for_pool(
                answers,
                default_answers,
                pool_name,
                pool_label,
                pool_answers,
                pools,
                priority,
            )

        return active_monitors, answers

    def _params_for_dynamic(self, record):
        # Convert rules to regions
        has_subnet, has_country, has_region, regions = self._generate_regions(
            record
        )

        # Convert pools to answers
        active_monitors, answers = self._generate_answers(record, regions)

        # Update filters as necessary
        filters = self._get_updated_filter_chain(
            has_region, has_country, has_subnet
        )

        return {
            'answers': answers,
            'filters': filters,
            'regions': regions,
            'ttl': record.ttl,
        }, active_monitors

    def _params_for_A(self, record):
        if getattr(record, 'dynamic', False):
            return self._params_for_dynamic(record)

        return {
            'answers': record.values,
            'ttl': record.ttl,
            'filters': [],
            'regions': {},
        }, None

    _params_for_AAAA = _params_for_A
    _params_for_NS = _params_for_A

    def _params_for_SPF(self, record):
        # NS1 seems to be the only provider that doesn't want things
        # escaped in values so we have to strip them here and add
        # them when going the other way
        values = [v.replace('\\;', ';') for v in record.values]
        return {'answers': values, 'ttl': record.ttl}, None

    _params_for_TXT = _params_for_SPF

    def _params_for_CAA(self, record):
        values = [(v.flags, v.tag, v.value) for v in record.values]
        return {'answers': values, 'ttl': record.ttl}, None

    def _params_for_CNAME(self, record):
        if getattr(record, 'dynamic', False):
            return self._params_for_dynamic(record)

        return {
            'answers': [record.value],
            'ttl': record.ttl,
            'filters': [],
            'regions': {},
        }, None

    _params_for_ALIAS = _params_for_CNAME
    _params_for_DNAME = _params_for_CNAME

    def _params_for_MX(self, record):
        values = [(v.preference, v.exchange) for v in record.values]
        return {'answers': values, 'ttl': record.ttl}, None

    def _params_for_NAPTR(self, record):
        values = [
            (v.order, v.preference, v.flags, v.service, v.regexp, v.replacement)
            for v in record.values
        ]
        return {'answers': values, 'ttl': record.ttl}, None

    def _params_for_PTR(self, record):
        return {'answers': record.values, 'ttl': record.ttl}, None

    def _params_for_SRV(self, record):
        values = [
            (v.priority, v.weight, v.port, v.target) for v in record.values
        ]
        return {'answers': values, 'ttl': record.ttl}, None

    def _params_for_URLFWD(self, record):
        values = [
            (v.path, v.target, v.code, v.masking, v.query)
            for v in record.values
        ]
        return {'answers': values, 'ttl': record.ttl}, None

    def _params_for_DS(self, record):
        values = [
            (v.key_tag, v.algorithm, v.digest_type, v.digest)
            for v in record.values
        ]
        return {'answers': values, 'ttl': record.ttl}, None

    def _params_for_TLSA(self, record):
        values = [
            (
                v.certificate_usage,
                v.selector,
                v.matching_type,
                v.certificate_association_data,
            )
            for v in record.values
        ]
        return {'answers': values, 'ttl': record.ttl}, None

    def _extra_changes(self, desired, changes, **kwargs):
        self.log.debug('_extra_changes: desired=%s', desired.name)
        changed = set([c.record for c in changes])
        extra = []
        for record in desired.records:
            if not getattr(record, 'dynamic', False):
                # no need to check non-dynamic simple records
                continue

            update = False

            # Filter normalization
            # Check if filters for existing domains need an update
            # Needs an explicit check since there might be no change in the
            # config at all. Filters however might still need an update
            domain = record.fqdn[:-1]
            _type = record._type
            record_filters = self.record_filters.get(domain, {}).get(_type, [])
            if not self._valid_filter_config(record_filters):
                # unrecognized set of filters, overwrite them by updating the
                # record
                self.log.info(
                    '_extra_changes: unrecognized filters in %s, '
                    'will update record',
                    domain,
                )
                update = True

            # check if any monitor needs to be synced
            existing = self._monitors_for(record)
            for pool in record.dynamic.pools.values():
                for val in pool.data['values']:
                    if val['status'] != 'obey':
                        # no monitor necessary
                        continue

                    value = val['value']
                    expected = self._monitor_gen(record, value)
                    name = expected['name']

                    have = existing.get(value)
                    if not have:
                        if self.use_http_monitors:
                            self.log.warning(
                                '_extra_changes: missing monitor "%s" will be created of type http, '
                                'octodns-ns1 cannot be downgraded below v0.0.5 after applying this change',
                                name,
                            )
                        else:
                            self.log.info(
                                '_extra_changes: missing monitor %s', name
                            )
                        update = True
                        continue

                    if not self._monitor_is_match(expected, have):
                        if expected['job_type'] == have['job_type']:
                            self.log.info(
                                '_extra_changes: monitor mis-match for %s', name
                            )
                        else:
                            # NS1 monitor job types cannot be changed, so we need to do
                            # delete+create, which has a few implications:
                            self.log.warning(
                                '_extra_changes: existing %s monitor "%s" will be deleted and replaced by a new %s monitor, '
                                '`%s` will be temporarily treated as being healthy as a result, '
                                'this is operation will be irreversible and not forward-compatible, ie '
                                'octodns-ns1 cannot be downgraded below v0.0.5 after applying this change',
                                have['job_type'],
                                name,
                                expected['job_type'],
                                value,
                            )
                        update = True

                    if not have.get('notify_list'):
                        self.log.info(
                            '_extra_changes: broken monitor no notify list %s (%s)',
                            name,
                            have['id'],
                        )
                        update = True

            if update and record not in changed:
                extra.append(Update(record, record))

        return extra

    def _force_root_ns_update(self, changes):
        '''
        Changes any 'Create' changetype for a root NS record to an 'Update'
        changetype. Used on new zone creation, since NS1 will automatically create root NS records (see https://ns1.com/api?docId=2184).
        This means our desired NS records must be applied as an Update, rather than a Create.
        '''
        for i, change in enumerate(changes):
            if (
                change.record.name == ''
                and change.record._type == 'NS'
                and isinstance(change, Create)
            ):
                self.log.info(
                    '_force_root_ns_update: found root NS record creation, changing to update'
                )
                changes[i] = Update(None, change.record)
        return changes

    def _apply_Create(self, ns1_zone, change):
        new = change.new
        zone = new.zone.name[:-1]
        domain = new.fqdn[:-1]
        _type = new._type
        params, active_monitor_ids = getattr(self, f'_params_for_{_type}')(new)
        self._client.records_create(zone, domain, _type, **params)
        self._monitors_gc(new, active_monitor_ids)

    def _apply_Update(self, ns1_zone, change):
        new = change.new
        zone = new.zone.name[:-1]
        domain = new.fqdn[:-1]
        _type = new._type
        params, active_monitor_ids = getattr(self, f'_params_for_{_type}')(new)
        self._client.records_update(zone, domain, _type, **params)
        # It's possible change.existing is None because in the case of zone creation, we swap out the NS record Create for an Update, but we don't set the existing
        # record (see _force_root_ns_update).
        if change.existing is not None:
            # If we're cleaning up we need to send in the old record since it'd
            # have anything that needs cleaning up
            self._monitors_gc(change.existing, active_monitor_ids)

    def _apply_Delete(self, ns1_zone, change):
        existing = change.existing
        zone = existing.zone.name[:-1]
        domain = existing.fqdn[:-1]
        _type = existing._type
        self._client.records_delete(zone, domain, _type)
        self._monitors_gc(existing)

    def _has_dynamic(self, changes):
        for change in changes:
            if getattr(change.record, 'dynamic', False):
                return True

        return False

    def _apply(self, plan):
        desired = plan.desired
        changes = plan.changes
        self.log.debug(
            '_apply: zone=%s, len(changes)=%d', desired.name, len(changes)
        )

        # Make sure that if we're going to make any dynamic changes that we
        # have monitor_regions configured before touching anything so we can
        # abort early and not half-apply
        if self._has_dynamic(changes) and not self.monitor_regions:
            raise Ns1Exception('Monitored record, but monitor_regions not set')

        domain_name = desired.name[:-1]
        try:
            ns1_zone = self._client.zones_retrieve(domain_name)
        except ResourceException as e:
            if e.message != self.ZONE_NOT_FOUND_MESSAGE:
                raise
            self.log.debug('_apply:   no matching zone, creating')
            ns1_zone = self._client.zones_create(domain_name)
            changes = self._force_root_ns_update(changes)

        for change in changes:
            class_name = change.__class__.__name__
            getattr(self, f'_apply_{class_name}')(ns1_zone, change)
