#
#
#

from collections import defaultdict
from unittest import TestCase
from unittest.mock import call, patch

from ns1.rest.errors import AuthException, RateLimitException, ResourceException

from octodns.provider import SupportsException
from octodns.provider.plan import Plan
from octodns.record import Record, Update
from octodns.zone import Zone

from octodns_ns1 import Ns1Client, Ns1Exception, Ns1Provider


class TestNs1Provider(TestCase):
    zone = Zone('unit.tests.', [])
    expected = set()
    expected.add(
        Record.new(
            zone, '', {'ttl': 32, 'type': 'A', 'value': '1.2.3.4', 'meta': {}}
        )
    )
    expected.add(
        Record.new(
            zone,
            'foo',
            {
                'ttl': 33,
                'type': 'A',
                'values': ['1.2.3.4', '1.2.3.5'],
                'meta': {},
            },
        )
    )
    expected.add(
        Record.new(
            zone,
            'cname',
            {'ttl': 34, 'type': 'CNAME', 'value': 'foo.unit.tests.'},
        )
    )
    expected.add(
        Record.new(
            zone,
            '',
            {
                'ttl': 35,
                'type': 'MX',
                'values': [
                    {'preference': 10, 'exchange': 'mx1.unit.tests.'},
                    {'preference': 20, 'exchange': 'mx2.unit.tests.'},
                ],
            },
        )
    )
    expected.add(
        Record.new(
            zone,
            'naptr',
            {
                'ttl': 36,
                'type': 'NAPTR',
                'values': [
                    {
                        'flags': 'U',
                        'order': 100,
                        'preference': 100,
                        'regexp': '!^.*$!sip:info@bar.example.com!',
                        'replacement': '.',
                        'service': 'SIP+D2U',
                    },
                    {
                        'flags': 'S',
                        'order': 10,
                        'preference': 100,
                        'regexp': '!^.*$!sip:info@bar.example.com!',
                        'replacement': '.',
                        'service': 'SIP+D2U',
                    },
                ],
            },
        )
    )
    expected.add(
        Record.new(
            zone,
            '',
            {
                'ttl': 37,
                'type': 'NS',
                'values': ['ns1.unit.tests.', 'ns2.unit.tests.'],
            },
        )
    )
    expected.add(
        Record.new(
            zone,
            '_srv._tcp',
            {
                'ttl': 38,
                'type': 'SRV',
                'values': [
                    {
                        'priority': 10,
                        'weight': 20,
                        'port': 30,
                        'target': 'foo-1.unit.tests.',
                    },
                    {
                        'priority': 12,
                        'weight': 30,
                        'port': 30,
                        'target': 'foo-2.unit.tests.',
                    },
                ],
            },
        )
    )
    expected.add(
        Record.new(
            zone,
            'sub',
            {
                'ttl': 39,
                'type': 'NS',
                'values': ['ns3.unit.tests.', 'ns4.unit.tests.'],
            },
        )
    )
    expected.add(
        Record.new(
            zone,
            '',
            {
                'ttl': 40,
                'type': 'CAA',
                'value': {'flags': 0, 'tag': 'issue', 'value': 'ca.unit.tests'},
            },
        )
    )
    expected.add(
        Record.new(
            zone,
            'urlfwd',
            {
                'ttl': 41,
                'type': 'URLFWD',
                'value': {
                    'path': '/',
                    'target': 'http://foo.unit.tests',
                    'code': 301,
                    'masking': 2,
                    'query': 0,
                },
            },
        )
    )
    expected.add(
        Record.new(
            zone,
            '1.2.3.4',
            {
                'ttl': 42,
                'type': 'PTR',
                'values': ['one.one.one.one.', 'two.two.two.two.'],
            },
        )
    )
    expected.add(
        Record.new(
            zone,
            'dname',
            {'ttl': 43, 'type': 'DNAME', 'value': 'foo.unit.tests.'},
        )
    )
    expected.add(
        Record.new(
            zone,
            'ds',
            {
                'ttl': 44,
                'type': 'DS',
                'values': [
                    {
                        'key_tag': '60485',
                        'algorithm': 5,
                        'digest_type': 1,
                        'digest': '2BB183AF5F22588179A53B0A98631FAD1A292118',
                    }
                ],
            },
        )
    )
    expected.add(
        Record.new(
            zone,
            'tlsa',
            {
                'ttl': 45,
                'type': 'TLSA',
                'values': [
                    {
                        'certificate_usage': 1,
                        'selector': 1,
                        'matching_type': 1,
                        'certificate_association_data': '8755CDAA8FE24EF16CC0F2C918063185E433FAAF1415664911D9E30A924138C4',
                    }
                ],
            },
        )
    )

    ns1_records = [
        {
            'type': 'A',
            'ttl': 32,
            'short_answers': ['1.2.3.4'],
            'domain': 'unit.tests.',
        },
        {
            'type': 'A',
            'ttl': 33,
            'short_answers': ['1.2.3.4', '1.2.3.5'],
            'domain': 'foo.unit.tests.',
        },
        {
            'type': 'CNAME',
            'ttl': 34,
            'short_answers': ['foo.unit.tests'],
            'domain': 'cname.unit.tests.',
        },
        {
            'type': 'MX',
            'ttl': 35,
            'short_answers': ['10 mx1.unit.tests.', '20 mx2.unit.tests'],
            'domain': 'unit.tests.',
        },
        {
            'type': 'NAPTR',
            'ttl': 36,
            'short_answers': [
                '10 100 S SIP+D2U !^.*$!sip:info@bar.example.com! .',
                '100 100 U SIP+D2U !^.*$!sip:info@bar.example.com! .',
            ],
            'domain': 'naptr.unit.tests.',
        },
        {
            'type': 'NS',
            'ttl': 37,
            'short_answers': ['ns1.unit.tests.', 'ns2.unit.tests'],
            'domain': 'unit.tests.',
        },
        {
            'type': 'SRV',
            'ttl': 38,
            'short_answers': [
                '12 30 30 foo-2.unit.tests.',
                '10 20 30 foo-1.unit.tests',
            ],
            'domain': '_srv._tcp.unit.tests.',
        },
        {
            'type': 'NS',
            'ttl': 39,
            'short_answers': ['ns3.unit.tests.', 'ns4.unit.tests'],
            'domain': 'sub.unit.tests.',
        },
        {
            'type': 'CAA',
            'ttl': 40,
            'short_answers': ['0 issue ca.unit.tests'],
            'domain': 'unit.tests.',
        },
        {
            'type': 'URLFWD',
            'ttl': 41,
            'short_answers': ['/ http://foo.unit.tests 301 2 0'],
            'domain': 'urlfwd.unit.tests.',
        },
        {
            'type': 'PTR',
            'ttl': 42,
            'short_answers': ['one.one.one.one.', 'two.two.two.two.'],
            'domain': '1.2.3.4.unit.tests.',
        },
        {
            'type': 'DNAME',
            'ttl': 43,
            'short_answers': ['foo.unit.tests.'],
            'domain': 'dname.unit.tests.',
        },
        {
            'type': 'DS',
            'ttl': 44,
            'short_answers': [
                '60485 5 1 2BB183AF5F22588179A53B0A98631FAD1A292118'
            ],
            'domain': 'ds.unit.tests.',
        },
        {
            'type': 'TLSA',
            'ttl': 45,
            'short_answers': [
                '1 1 1 8755CDAA8FE24EF16CC0F2C918063185E433FAAF1415664911D9E30A924138C4'
            ],
            'domain': 'tlsa.unit.tests.',
        },
    ]

    @patch('ns1.rest.records.Records.retrieve')
    @patch('ns1.rest.zones.Zones.retrieve')
    def test_populate(self, zone_retrieve_mock, record_retrieve_mock):
        provider = Ns1Provider('test', 'api-key')

        def reset():
            provider._client.reset_caches()
            zone_retrieve_mock.reset_mock()
            zone_retrieve_mock.side_effect = None
            zone_retrieve_mock.__name__ = 'retrieve'
            record_retrieve_mock.reset_mock()
            record_retrieve_mock.side_effect = None

        # Bad auth
        reset()
        zone_retrieve_mock.side_effect = AuthException('unauthorized')
        zone = Zone('unit.tests.', [])
        with self.assertRaises(AuthException) as ctx:
            provider.populate(zone)
        self.assertEqual(zone_retrieve_mock.side_effect, ctx.exception)

        # General error
        reset()
        zone_retrieve_mock.side_effect = ResourceException('boom')
        zone = Zone('unit.tests.', [])
        with self.assertRaises(ResourceException) as ctx:
            provider.populate(zone)
        self.assertEqual(zone_retrieve_mock.side_effect, ctx.exception)
        self.assertEqual(('unit.tests',), zone_retrieve_mock.call_args[0])

        # Non-existent zone doesn't populate anything
        reset()
        zone_retrieve_mock.side_effect = ResourceException(
            'server error: zone not found'
        )
        zone = Zone('unit.tests.', [])
        exists = provider.populate(zone)
        self.assertEqual(set(), zone.records)
        self.assertEqual(('unit.tests',), zone_retrieve_mock.call_args[0])
        self.assertFalse(exists)

        # Existing zone w/o records
        reset()
        ns1_zone = {'records': []}
        zone_retrieve_mock.side_effect = [ns1_zone]
        zone = Zone('unit.tests.', [])
        provider.populate(zone)
        self.assertEqual(0, len(zone.records))

        # Existing zone w/records
        reset()
        ns1_zone = {'records': self.ns1_records}
        zone_retrieve_mock.side_effect = [ns1_zone]
        zone = Zone('unit.tests.', [])
        provider.populate(zone)
        from pprint import pprint

        pprint({'expected': self.expected, 'records': zone.records})
        self.assertEqual(self.expected, zone.records)

        # Test skipping unsupported record type
        reset()
        ns1_zone = {
            'records': self.ns1_records
            + [
                {
                    'type': 'UNSUPPORTED',
                    'ttl': 42,
                    'short_answers': ['unsupported'],
                    'domain': 'unsupported.unit.tests.',
                }
            ]
        }
        zone_retrieve_mock.side_effect = [ns1_zone]
        zone = Zone('unit.tests.', [])
        provider.populate(zone)
        self.assertEqual(self.expected, zone.records)

        # Test handling of record with unsupported filter chains
        # cc https://github.com/octodns/octodns-ns1/issues/17
        reset()
        ns1_zone = {
            'records': [
                {
                    "domain": "unsupported.unit.tests",
                    "zone": "unit.tests",
                    "id": "123",
                    "use_client_subnet": True,
                    "answers": [
                        {
                            "answer": ["FOO"],
                            "meta": {"georegion": ["US-EAST"]},
                            "id": "234",
                        },
                        {
                            "answer": ["BAR"],
                            "meta": {"georegion": ["EUROPE"]},
                            "id": "345",
                        },
                    ],
                    "override_ttl": False,
                    "regions": {},
                    "meta": {},
                    "link": None,
                    "filters": [
                        {"filter": "select_first_n", "config": {"N": "1"}}
                    ],
                    "ttl": 3600,
                    "tier": 2,
                    "type": "CNAME",
                    "networks": [0],
                }
            ]
        }
        zone_retrieve_mock.side_effect = [ns1_zone]
        # Its tier 2 so we'll do a full lookup
        record_retrieve_mock.side_effect = ns1_zone['records']
        zone = Zone('unit.tests.', [])
        with self.assertLogs('Ns1Provider[test]', 'WARNING') as cm:
            provider.populate(zone, lenient=True)
        self.assertEqual(
            [
                'WARNING:Ns1Provider[test]:Cannot parse unsupported.unit.tests dynamic record due to missing pool name in first answer note, treating it as an empty record'
            ],
            cm.output,
        )
        self.assertEqual(
            set(
                [
                    Record.new(
                        zone,
                        'unsupported',
                        {'type': 'CNAME', 'ttl': 3600, 'value': None},
                        lenient=True,
                    )
                ]
            ),
            zone.records,
        )
        self.assertEqual(('unit.tests',), zone_retrieve_mock.call_args[0])
        record_retrieve_mock.assert_has_calls(
            [call('unit.tests', 'unsupported.unit.tests', 'CNAME')]
        )

    @patch('ns1.rest.records.Records.delete')
    @patch('ns1.rest.records.Records.update')
    @patch('ns1.rest.records.Records.create')
    @patch('ns1.rest.records.Records.retrieve')
    @patch('ns1.rest.zones.Zones.create')
    @patch('ns1.rest.zones.Zones.retrieve')
    def test_sync(
        self,
        zone_retrieve_mock,
        zone_create_mock,
        record_retrieve_mock,
        record_create_mock,
        record_update_mock,
        record_delete_mock,
    ):
        provider = Ns1Provider('test', 'api-key')

        desired = Zone('unit.tests.', [])
        for r in self.expected:
            desired.add_record(r)

        plan = provider.plan(desired)
        expected_n = len(self.expected)
        self.assertEqual(expected_n, len(plan.changes))
        self.assertTrue(plan.exists)

        def reset():
            provider._client.reset_caches()
            record_retrieve_mock.reset_mock()
            zone_create_mock.reset_mock()
            zone_create_mock.__name__ = 'create'
            zone_retrieve_mock.reset_mock()
            zone_retrieve_mock.__name__ = 'retrieve'

        # Fails, general error
        reset()
        zone_retrieve_mock.side_effect = ResourceException('boom')
        with self.assertRaises(ResourceException) as ctx:
            provider.apply(plan)
        self.assertEqual(zone_retrieve_mock.side_effect, ctx.exception)

        # Fails, bad auth
        reset()
        zone_retrieve_mock.side_effect = ResourceException(
            'server error: zone not found'
        )
        zone_create_mock.side_effect = AuthException('unauthorized')
        with self.assertRaises(AuthException) as ctx:
            provider.apply(plan)
        self.assertEqual(zone_create_mock.side_effect, ctx.exception)

        # non-existent zone/404, create
        class DummyResponse:
            status_code = 404

        reset()
        zone_retrieve_mock.side_effect = ResourceException(
            'server error: zone not found', response=DummyResponse(), body='x'
        )

        zone_create_mock.side_effect = ['foo']
        # Test out the create rate-limit handling, then successes for the rest
        record_create_mock.side_effect = [
            RateLimitException('boo', period=0)
        ] + ([None] * len(self.expected))

        got_n = provider.apply(plan)
        self.assertEqual(expected_n, got_n)

        # Zone was created
        zone_create_mock.assert_has_calls([call('unit.tests')])
        # Checking that we got some of the expected records too
        record_create_mock.assert_has_calls(
            [
                call(
                    'unit.tests',
                    'unit.tests',
                    'A',
                    answers=['1.2.3.4'],
                    ttl=32,
                    filters=[],
                    regions={},
                ),
                call(
                    'unit.tests',
                    'cname.unit.tests',
                    'CNAME',
                    answers=['foo.unit.tests.'],
                    filters=[],
                    regions={},
                    ttl=34,
                ),
                call(
                    'unit.tests',
                    'unit.tests',
                    'CAA',
                    answers=[(0, 'issue', 'ca.unit.tests')],
                    ttl=40,
                ),
                call(
                    'unit.tests',
                    'unit.tests',
                    'MX',
                    answers=[(10, 'mx1.unit.tests.'), (20, 'mx2.unit.tests.')],
                    ttl=35,
                ),
                call(
                    'unit.tests',
                    '1.2.3.4.unit.tests',
                    'PTR',
                    answers=['one.one.one.one.', 'two.two.two.two.'],
                    ttl=42,
                ),
            ],
            any_order=True,
        )
        # New zone was created, so we should update NS records instead of creating
        record_update_mock.assert_has_calls(
            [
                call(
                    'unit.tests',
                    'unit.tests',
                    'NS',
                    answers=['ns1.unit.tests.', 'ns2.unit.tests.'],
                    filters=[],
                    regions={},
                    ttl=37,
                )
            ]
        )

        # Update & delete
        reset()

        ns1_zone = {
            'records': self.ns1_records
            + [
                {
                    'type': 'A',
                    'ttl': 42,
                    'short_answers': ['9.9.9.9'],
                    'domain': 'delete-me.unit.tests.',
                }
            ]
        }
        ns1_zone['records'][0]['short_answers'][0] = '2.2.2.2'

        # record_retrieve_mock.side_effect = [ns1_record, ns1_record]
        zone_retrieve_mock.side_effect = [ns1_zone, ns1_zone]
        plan = provider.plan(desired)
        self.assertEqual(2, len(plan.changes))
        # Shouldn't rely on order so just count classes
        classes = defaultdict(lambda: 0)
        for change in plan.changes:
            classes[change.__class__] += 1
        self.assertEqual(1, classes[Update])

        record_update_mock.side_effect = [
            RateLimitException('one', period=0),
            None,
            None,
        ]
        record_delete_mock.side_effect = [
            RateLimitException('two', period=0),
            None,
            None,
        ]

        zone_retrieve_mock.side_effect = [ns1_zone, ns1_zone]
        got_n = provider.apply(plan)
        self.assertEqual(2, got_n)

        record_update_mock.assert_has_calls(
            [
                call(
                    'unit.tests',
                    'unit.tests',
                    'A',
                    answers=['1.2.3.4'],
                    filters=[],
                    regions={},
                    ttl=32,
                ),
                call(
                    'unit.tests',
                    'unit.tests',
                    'A',
                    answers=['1.2.3.4'],
                    filters=[],
                    regions={},
                    ttl=32,
                ),
            ]
        )

    def test_escaping(self):
        provider = Ns1Provider('test', 'api-key')
        record = {'ttl': 31, 'short_answers': ['foo; bar baz; blip']}
        self.assertEqual(
            ['foo\\; bar baz\\; blip'],
            provider._data_for_TXT('TXT', record)['values'],
        )

        record = {
            'ttl': 31,
            'short_answers': ['no', 'foo; bar baz; blip', 'yes'],
        }
        self.assertEqual(
            ['no', 'foo\\; bar baz\\; blip', 'yes'],
            provider._data_for_TXT('TXT', record)['values'],
        )

        zone = Zone('unit.tests.', [])
        record = Record.new(
            zone,
            'txt',
            {'ttl': 34, 'type': 'TXT', 'value': 'foo\\; bar baz\\; blip'},
        )
        params, _ = provider._params_for_TXT(record)
        self.assertEqual(['foo; bar baz; blip'], params['answers'])

        record = Record.new(
            zone,
            'txt',
            {'ttl': 35, 'type': 'TXT', 'value': 'foo\\; bar baz\\; blip'},
        )
        params, _ = provider._params_for_TXT(record)
        self.assertEqual(['foo; bar baz; blip'], params['answers'])

    def test_data_for_CNAME(self):
        provider = Ns1Provider('test', 'api-key')

        # answers from ns1
        a_record = {
            'ttl': 31,
            'type': 'CNAME',
            'short_answers': ['foo.unit.tests.'],
        }
        a_expected = {'ttl': 31, 'type': 'CNAME', 'value': 'foo.unit.tests.'}
        self.assertEqual(
            a_expected, provider._data_for_CNAME(a_record['type'], a_record)
        )

        # no answers from ns1
        b_record = {'ttl': 32, 'type': 'CNAME', 'short_answers': []}
        b_expected = {'ttl': 32, 'type': 'CNAME', 'value': None}
        self.assertEqual(
            b_expected, provider._data_for_CNAME(b_record['type'], b_record)
        )


class TestNs1ProviderDynamic(TestCase):
    zone = Zone('unit.tests.', [])

    def record(self):
        # return a new object each time so we can mess with it without causing
        # problems from test to test
        return Record.new(
            self.zone,
            '',
            {
                'dynamic': {
                    'pools': {
                        'lhr': {
                            'fallback': 'iad',
                            'values': [{'value': '3.4.5.6'}],
                        },
                        'iad': {
                            'values': [
                                {'value': '1.2.3.4'},
                                {'value': '2.3.4.5'},
                            ]
                        },
                    },
                    'rules': [
                        {'geos': ['AF', 'EU-GB', 'NA-US-FL'], 'pool': 'lhr'},
                        {'geos': ['NA-US'], 'pool': 'iad'},
                        {'pool': 'iad'},
                    ],
                },
                'octodns': {
                    'healthcheck': {
                        'host': 'send.me',
                        'path': '/_ping',
                        'port': 80,
                        'protocol': 'HTTP',
                    },
                    'ns1': {
                        'healthcheck': {
                            'connect_timeout': 5,
                            'response_timeout': 6,
                        }
                    },
                },
                'ttl': 32,
                'type': 'A',
                'value': '1.2.3.4',
                'meta': {},
            },
        )

    def aaaa_record(self):
        return Record.new(
            self.zone,
            '',
            {
                'dynamic': {
                    'pools': {
                        'lhr': {
                            'fallback': 'iad',
                            'values': [{'value': '::ffff:3.4.5.6'}],
                        },
                        'iad': {
                            'values': [
                                {'value': '::ffff:1.2.3.4'},
                                {'value': '::ffff:2.3.4.5'},
                            ]
                        },
                    },
                    'rules': [
                        {'geos': ['AF', 'EU-GB', 'NA-US-FL'], 'pool': 'lhr'},
                        {'geos': ['NA-US'], 'pool': 'iad'},
                        {'pool': 'iad'},
                    ],
                },
                'octodns': {
                    'healthcheck': {
                        'host': 'send.me',
                        'path': '/_ping',
                        'port': 80,
                        'protocol': 'HTTP',
                    }
                },
                'ttl': 32,
                'type': 'AAAA',
                'value': '::ffff:1.2.3.4',
                'meta': {},
            },
        )

    def cname_record(self):
        return Record.new(
            self.zone,
            'foo',
            {
                'dynamic': {
                    'pools': {
                        'iad': {'values': [{'value': 'iad.unit.tests.'}]}
                    },
                    'rules': [{'pool': 'iad'}],
                },
                'octodns': {
                    'healthcheck': {
                        'host': 'send.me',
                        'path': '/_ping',
                        'port': 80,
                        'protocol': 'HTTP',
                    }
                },
                'ttl': 33,
                'type': 'CNAME',
                'value': 'value.unit.tests.',
                'meta': {},
            },
        )

    def test_notes(self):
        provider = Ns1Provider('test', 'api-key')

        self.assertEqual({}, provider._parse_notes(None))
        self.assertEqual({}, provider._parse_notes(''))
        self.assertEqual({}, provider._parse_notes('blah-blah-blah'))

        # Round tripping
        data = {'key': 'value', 'priority': 1}
        notes = provider._encode_notes(data)
        self.assertEqual(data, provider._parse_notes(notes))

        # integers come out as int
        self.assertEqual(
            {'rule-order': 1}, provider._parse_notes('rule-order:1')
        )

        # floats come out as strings (not currently used so not parsed)
        self.assertEqual(
            {'rule-order': '1.2'}, provider._parse_notes('rule-order:1.2')
        )

        # strings that start with integers are still strings
        self.assertEqual(
            {'rule-order': '1-thing'},
            provider._parse_notes('rule-order:1-thing'),
        )

    def test_monitors_for(self):
        provider = Ns1Provider('test', 'api-key')

        # pre-populate the client's monitors cache
        monitor_one = {
            'config': {'host': '1.2.3.4'},
            'notes': 'host:unit.tests type:A',
        }
        monitor_four = {
            'config': {'host': '2.3.4.5'},
            'notes': 'host:unit.tests type:A',
        }
        monitor_five = {
            'config': {'host': 'iad.unit.tests'},
            'notes': 'host:foo.unit.tests type:CNAME',
        }
        monitor_eight = {
            'config': {'url': 'https://iad.unit.tests/_ping'},
            'notes': 'host:foo.unit.tests type:CNAME value:iad.unit.tests',
        }
        provider._client._monitors_cache = {
            'one': monitor_one,
            'two': {
                'config': {'host': '8.8.8.8'},
                'notes': 'host:unit.tests type:AAAA',
            },
            'three': {
                'config': {'host': '9.9.9.9'},
                'notes': 'host:other.unit.tests type:A',
            },
            'four': monitor_four,
            'five': monitor_five,
            'six': {
                'config': {'host': '10.10.10.10'},
                'notes': 'non-conforming notes',
            },
            'seven': {'config': {'host': '11.11.11.11'}, 'notes': None},
        }

        # Would match, but won't get there b/c it's not dynamic
        record = Record.new(
            self.zone,
            '',
            {'ttl': 32, 'type': 'A', 'value': '1.2.3.4', 'meta': {}},
        )
        self.assertEqual({}, provider._monitors_for(record))

        # Will match some records
        self.assertEqual(
            {'1.2.3.4': monitor_one, '2.3.4.5': monitor_four},
            provider._monitors_for(self.record()),
        )

        # Check match for CNAME values
        self.assertEqual(
            {'iad.unit.tests.': monitor_five},
            provider._monitors_for(self.cname_record()),
        )

        # Check for HTTP monitors match from notes
        provider._client._monitors_cache['eight'] = monitor_eight
        self.assertEqual(
            {'iad.unit.tests.': monitor_eight},
            provider._monitors_for(self.cname_record()),
        )

    def test_uuid(self):
        # Just a smoke test/for coverage
        provider = Ns1Provider('test', 'api-key')
        self.assertTrue(provider._uuid())

    @patch('octodns_ns1.Ns1Provider._uuid')
    @patch('ns1.rest.data.Feed.create')
    def test_feed_create(self, datafeed_create_mock, uuid_mock):
        provider = Ns1Provider('test', 'api-key')

        # pre-fill caches to avoid extranious calls (things we're testing
        # elsewhere)
        provider._client._datasource_id = 'foo'
        provider._client._feeds_for_monitors = {}

        uuid_mock.reset_mock()
        datafeed_create_mock.reset_mock()
        uuid_mock.side_effect = ['xxxxxxxxxxxxxx']
        feed = {'id': 'feed'}
        datafeed_create_mock.side_effect = [feed]
        monitor = {
            'id': 'one',
            'name': 'one name',
            'config': {'host': '1.2.3.4'},
            'notes': 'host:unit.tests type:A',
        }
        self.assertEqual('feed', provider._feed_create(monitor))
        datafeed_create_mock.assert_has_calls(
            [call('foo', 'one name - xxxxxx', {'jobid': 'one'})]
        )

    @patch('octodns_ns1.Ns1Provider._feed_create')
    @patch('octodns_ns1.Ns1Client.monitors_create')
    @patch('octodns_ns1.Ns1Client.notifylists_create')
    def test_monitor_create(
        self, notifylists_create_mock, monitors_create_mock, feed_create_mock
    ):
        provider = Ns1Provider('test', 'api-key')

        # pre-fill caches to avoid extranious calls (things we're testing
        # elsewhere)
        provider._client._datasource_id = 'foo'
        provider._client._feeds_for_monitors = {}

        notifylists_create_mock.reset_mock()
        monitors_create_mock.reset_mock()
        feed_create_mock.reset_mock()
        notifylists_create_mock.side_effect = [{'id': 'nl-id'}]
        monitors_create_mock.side_effect = [{'id': 'mon-id'}]
        feed_create_mock.side_effect = ['feed-id']
        monitor = {'name': 'test monitor'}
        provider._client._notifylists_cache = {}
        monitor_id, feed_id = provider._monitor_create(monitor)
        self.assertEqual('mon-id', monitor_id)
        self.assertEqual('feed-id', feed_id)
        monitors_create_mock.assert_has_calls(
            [call(name='test monitor', notify_list='nl-id')]
        )

    @patch('octodns_ns1.Ns1Provider._feed_create')
    @patch('octodns_ns1.Ns1Client.monitors_create')
    @patch('octodns_ns1.Ns1Client._try')
    def test_monitor_create_shared_notifylist(
        self, try_mock, monitors_create_mock, feed_create_mock
    ):
        provider = Ns1Provider('test', 'api-key', shared_notifylist=True)

        # pre-fill caches to avoid extranious calls (things we're testing
        # elsewhere)
        provider._client._datasource_id = 'foo'
        provider._client._feeds_for_monitors = {}

        # First time we'll need to create the share list
        provider._client._notifylists_cache = {}
        try_mock.reset_mock()
        monitors_create_mock.reset_mock()
        feed_create_mock.reset_mock()
        try_mock.side_effect = [
            {'id': 'nl-id', 'name': provider.SHARED_NOTIFYLIST_NAME}
        ]
        monitors_create_mock.side_effect = [{'id': 'mon-id'}]
        feed_create_mock.side_effect = ['feed-id']
        monitor = {'name': 'test monitor'}
        monitor_id, feed_id = provider._monitor_create(monitor)
        self.assertEqual('mon-id', monitor_id)
        self.assertEqual('feed-id', feed_id)
        monitors_create_mock.assert_has_calls(
            [call(name='test monitor', notify_list='nl-id')]
        )
        try_mock.assert_called_once()
        # The shared notifylist should be cached now
        self.assertEqual(
            [provider.SHARED_NOTIFYLIST_NAME],
            list(provider._client._notifylists_cache.keys()),
        )

        # Second time we'll use the cached version
        try_mock.reset_mock()
        monitors_create_mock.reset_mock()
        feed_create_mock.reset_mock()
        monitors_create_mock.side_effect = [{'id': 'mon-id'}]
        feed_create_mock.side_effect = ['feed-id']
        monitor = {'name': 'test monitor'}
        monitor_id, feed_id = provider._monitor_create(monitor)
        self.assertEqual('mon-id', monitor_id)
        self.assertEqual('feed-id', feed_id)
        monitors_create_mock.assert_has_calls(
            [call(name='test monitor', notify_list='nl-id')]
        )
        try_mock.assert_not_called()

    def test_monitor_gen(self):
        provider = Ns1Provider('test', 'api-key')

        value = '3.4.5.6'
        record = self.record()
        monitor = provider._monitor_gen(record, value)
        self.assertEqual('tcp', monitor['job_type'])
        self.assertEqual(value, monitor['config']['host'])
        self.assertTrue('\\nHost: send.me\\r' in monitor['config']['send'])
        self.assertFalse(monitor['config']['ssl'])
        self.assertEqual('host:unit.tests type:A', monitor['notes'])

        record.octodns['healthcheck']['host'] = None
        monitor = provider._monitor_gen(record, value)
        self.assertTrue(r'\nHost: 3.4.5.6\r' in monitor['config']['send'])

        # Test http version validation
        record.octodns['ns1']['healthcheck']['http_version'] = 'invalid'
        with self.assertRaisesRegex(
            Ns1Exception,
            r"unsupported http version found: 'invalid'. Expected version in \('HTTP/1.0', 'HTTP/1.1'\)",
        ):
            provider._monitor_gen(record, value)
        record.octodns['ns1']['healthcheck']['http_version'] = 'HTTP/1.0'

        record.octodns['healthcheck']['protocol'] = 'HTTPS'
        monitor = provider._monitor_gen(record, value)
        self.assertTrue(monitor['config']['ssl'])

        record.octodns['healthcheck']['protocol'] = 'TCP'
        monitor = provider._monitor_gen(record, value)
        self.assertEqual('tcp', monitor['job_type'])
        # No http send done
        self.assertFalse('send' in monitor['config'])
        # No http response expected
        self.assertFalse('rules' in monitor)

        record.octodns['ns1']['healthcheck']['policy'] = 'all'
        monitor = provider._monitor_gen(record, value)
        self.assertEqual('all', monitor['policy'])

        record.octodns['ns1']['healthcheck']['frequency'] = 300
        monitor = provider._monitor_gen(record, value)
        self.assertEqual(300, monitor['frequency'])

        record.octodns['ns1']['healthcheck']['rapid_recheck'] = True
        monitor = provider._monitor_gen(record, value)
        self.assertTrue(monitor['rapid_recheck'])

        record.octodns['ns1']['healthcheck']['connect_timeout'] = 1
        monitor = provider._monitor_gen(record, value)
        self.assertEqual(1000, monitor['config']['connect_timeout'])

        record.octodns['ns1']['healthcheck']['response_timeout'] = 2
        monitor = provider._monitor_gen(record, value)
        self.assertEqual(2000, monitor['config']['response_timeout'])

    def test_monitor_gen_http(self):
        provider = Ns1Provider('test', 'api-key', use_http_monitors=True)

        value = '3.4.5.6'
        record = self.record()
        monitor = provider._monitor_gen(record, value)
        self.assertEqual('http', monitor['job_type'])
        self.assertEqual(f'http://{value}:80/_ping', monitor['config']['url'])
        self.assertEqual('send.me', monitor['config']['virtual_host'])
        self.assertEqual(
            f'host:unit.tests type:A value:{value}', monitor['notes']
        )

        record.octodns['healthcheck']['host'] = None
        monitor = provider._monitor_gen(record, value)
        self.assertEqual(value, monitor['config']['virtual_host'])

        record.octodns['healthcheck']['protocol'] = 'HTTPS'
        monitor = provider._monitor_gen(record, value)
        self.assertTrue(monitor['config']['url'].startswith('https://'))

        # http version doesn't matter or fail
        record.octodns['ns1']['healthcheck']['http_version'] = 'invalid'
        provider._monitor_gen(record, value)
        record.octodns['ns1']['healthcheck']['http_version'] = 'HTTP/1.0'

        record.octodns['ns1']['healthcheck']['connect_timeout'] = 1
        monitor = provider._monitor_gen(record, value)
        self.assertEqual(1, monitor['config']['connect_timeout'])

        record.octodns['ns1']['healthcheck']['response_timeout'] = 2
        monitor = provider._monitor_gen(record, value)
        self.assertEqual(2, monitor['config']['idle_timeout'])

        record.octodns['healthcheck']['protocol'] = 'TCP'
        monitor = provider._monitor_gen(record, value)
        self.assertEqual('tcp', monitor['job_type'])
        # Nothing to send
        self.assertFalse('send' in monitor['config'])
        # Nothing to expect
        self.assertFalse('rules' in monitor)

        record.octodns['ns1']['healthcheck']['connect_timeout'] = 1
        monitor = provider._monitor_gen(record, value)
        self.assertEqual(1000, monitor['config']['connect_timeout'])

        record.octodns['ns1']['healthcheck']['response_timeout'] = 2
        monitor = provider._monitor_gen(record, value)
        self.assertEqual(2000, monitor['config']['response_timeout'])

    def test_monitor_gen_AAAA_http(self):
        provider = Ns1Provider('test', 'api-key', use_http_monitors=True)

        value = '::ffff:3.4.5.6'
        record = self.aaaa_record()
        monitor = provider._monitor_gen(record, value)
        self.assertTrue(monitor['config']['ipv6'])
        self.assertTrue(f'[{value}]' in monitor['config']['url'])

    def test_monitor_gen_CNAME_http(self):
        provider = Ns1Provider('test', 'api-key', use_http_monitors=True)

        value = 'iad.unit.tests.'
        record = self.cname_record()
        monitor = provider._monitor_gen(record, value)
        self.assertTrue(value[:-1] in monitor['config']['url'])

    def test_monitor_gen_ICMP(self):
        provider = Ns1Provider('test', 'api-key', use_http_monitors=True)

        value = '1.2.3.4'
        record = self.record()
        record.octodns['healthcheck']['protocol'] = 'ICMP'
        monitor = provider._monitor_gen(record, value)
        self.assertEqual('ping', monitor['job_type'])
        self.assertEqual(
            provider._healthcheck_response_timeout(record) * 1000,
            monitor['config']['timeout'],
        )
        self.assertEqual(
            provider._healthcheck_response_timeout(record) * 250,
            monitor['config']['interval'],
        )
        self.assertFalse(monitor['config']['ipv6'])
        self.assertTrue(value in monitor['config']['host'])

        value = '::ffff:3.4.5.6'
        record = self.aaaa_record()
        record.octodns['healthcheck']['protocol'] = 'ICMP'
        monitor = provider._monitor_gen(record, value)
        self.assertEqual('ping', monitor['job_type'])
        self.assertTrue(monitor['config']['ipv6'])
        self.assertTrue(value in monitor['config']['host'])

    def test_monitor_is_match(self):
        provider = Ns1Provider('test', 'api-key')

        # Empty matches empty
        self.assertTrue(provider._monitor_is_match({}, {}))

        # Anything matches empty
        self.assertTrue(provider._monitor_is_match({}, {'anything': 'goes'}))

        # Missing doesn't match
        self.assertFalse(
            provider._monitor_is_match({'exepct': 'this'}, {'anything': 'goes'})
        )

        # Identical matches
        self.assertTrue(
            provider._monitor_is_match({'exepct': 'this'}, {'exepct': 'this'})
        )

        # Different values don't match
        self.assertFalse(
            provider._monitor_is_match({'exepct': 'this'}, {'exepct': 'that'})
        )

        # Different sub-values don't match
        self.assertFalse(
            provider._monitor_is_match(
                {'exepct': {'this': 'to-be'}},
                {'exepct': {'this': 'something-else'}},
            )
        )

        # extra stuff in the config section doesn't cause problems
        self.assertTrue(
            provider._monitor_is_match(
                {'config': {'key': 42, 'value': 43}},
                {'config': {'key': 42, 'value': 43, 'other': 44}},
            )
        )

        # missing regions causes mismatch
        self.assertFalse(
            provider._monitor_is_match({'regions': ['lga', 'sin']}, {})
        )

        # out of order regions doesn't cause mismatch
        self.assertTrue(
            provider._monitor_is_match(
                {'regions': ['lga', 'sin']}, {'regions': ['sin', 'lga']}
            )
        )

    def test_unsupported_continent(self):
        provider = Ns1Provider('test', 'api-key')
        desired = Zone('unit.tests.', [])
        record = Record.new(
            desired,
            'a',
            {
                'ttl': 30,
                'type': 'A',
                'value': '1.2.3.4',
                'dynamic': {
                    'pools': {
                        'one': {'values': [{'value': '1.2.3.4'}]},
                        'two': {'values': [{'value': '2.2.3.4'}]},
                    },
                    'rules': [{'geos': ['AN'], 'pool': 'two'}, {'pool': 'one'}],
                },
            },
            lenient=True,
        )
        desired.add_record(record)
        with self.assertRaises(SupportsException) as ctx:
            provider._process_desired_zone(desired)
        self.assertEqual(
            'test: unsupported continent code AN in a.unit.tests.',
            str(ctx.exception),
        )

        record.dynamic.rules[0].data['geos'][0] = 'NA'
        got = provider._process_desired_zone(desired)
        self.assertEqual(got.records, desired.records)

    def test_unsupported_healthcheck_protocol(self):
        provider = Ns1Provider('test', 'api-key')
        desired = Zone('unit.tests.', [])
        record = Record.new(
            desired,
            'a',
            {
                'ttl': 30,
                'type': 'A',
                'value': '1.2.3.4',
                'dynamic': {
                    'pools': {
                        'one': {'values': [{'value': '1.2.3.4'}]},
                        'two': {'values': [{'value': '2.2.3.4'}]},
                    },
                    'rules': [
                        {'geos': ['EU', 'NA-CA-NB', 'NA-US-OR'], 'pool': 'two'},
                        {'pool': 'one'},
                    ],
                },
                'octodns': {'healthcheck': {'protocol': 'UDP'}},
            },
            lenient=True,
        )
        desired.add_record(record)
        with self.assertRaises(SupportsException) as ctx:
            provider._process_desired_zone(desired)
        self.assertEqual(
            'test: healthcheck protocol "UDP" not supported', str(ctx.exception)
        )

        record.octodns['healthcheck']['protocol'] = 'ICMP'
        got = provider._process_desired_zone(desired)
        self.assertEqual(got.records, desired.records)

    @patch('octodns_ns1.Ns1Provider._feed_create')
    @patch('octodns_ns1.Ns1Provider._monitor_delete')
    @patch('octodns_ns1.Ns1Client.monitors_update')
    @patch('octodns_ns1.Ns1Provider._monitor_create')
    @patch('octodns_ns1.Ns1Provider._monitor_gen')
    def test_monitor_sync(
        self,
        monitor_gen_mock,
        monitor_create_mock,
        monitors_update_mock,
        monitor_delete_mock,
        feed_create_mock,
    ):
        provider = Ns1Provider('test', 'api-key')

        # pre-fill caches to avoid extranious calls (things we're testing
        # elsewhere)
        provider._client._datasource_id = 'foo'
        provider._client._feeds_for_monitors = {'mon-id': 'feed-id'}

        def reset():
            feed_create_mock.reset_mock()
            monitor_create_mock.reset_mock()
            monitor_gen_mock.reset_mock()
            monitors_update_mock.reset_mock()

        # No existing monitor
        reset()
        monitor_gen_mock.side_effect = [{'key': 'value'}]
        monitor_create_mock.side_effect = [('mon-id', 'feed-id')]
        value = '1.2.3.4'
        record = self.record()
        monitor_id, feed_id = provider._monitor_sync(record, value, None)
        self.assertEqual('mon-id', monitor_id)
        self.assertEqual('feed-id', feed_id)
        monitor_gen_mock.assert_has_calls([call(record, value)])
        monitor_create_mock.assert_has_calls([call({'key': 'value'})])
        monitors_update_mock.assert_not_called()
        feed_create_mock.assert_not_called()

        # Existing monitor that doesn't need updates
        reset()
        monitor = {'id': 'mon-id', 'key': 'value', 'name': 'monitor name'}
        monitor_gen_mock.side_effect = [monitor]
        monitor_id, feed_id = provider._monitor_sync(record, value, monitor)
        self.assertEqual('mon-id', monitor_id)
        self.assertEqual('feed-id', feed_id)
        monitor_gen_mock.assert_called_once()
        monitor_create_mock.assert_not_called()
        monitors_update_mock.assert_not_called()
        feed_create_mock.assert_not_called()

        # Existing monitor that doesn't need updates, but is missing its feed
        reset()
        monitor = {'id': 'mon-id2', 'key': 'value', 'name': 'monitor name'}
        monitor_gen_mock.side_effect = [monitor]
        feed_create_mock.side_effect = ['feed-id2']
        monitor_id, feed_id = provider._monitor_sync(record, value, monitor)
        self.assertEqual('mon-id2', monitor_id)
        self.assertEqual('feed-id2', feed_id)
        monitor_gen_mock.assert_called_once()
        monitor_create_mock.assert_not_called()
        monitors_update_mock.assert_not_called()
        feed_create_mock.assert_has_calls([call(monitor)])

        # Existing monitor of same job_type that needs updates
        reset()
        monitor = {'id': 'mon-id', 'job_type': 'value', 'name': 'monitor name'}
        gened = {'other': 'thing', 'job_type': 'value'}
        monitor_gen_mock.side_effect = [gened]
        monitor_id, feed_id = provider._monitor_sync(record, value, monitor)
        self.assertEqual('mon-id', monitor_id)
        self.assertEqual('feed-id', feed_id)
        monitor_gen_mock.assert_called_once()
        monitor_create_mock.assert_not_called()
        monitors_update_mock.assert_has_calls(
            [call('mon-id', other='thing', job_type='value')]
        )
        feed_create_mock.assert_not_called()

        # Existing monitor of different job_type that needs updates
        reset()
        monitor = {'id': 'mon-id', 'job_type': 'value', 'name': 'monitor name'}
        gened = {'other': 'thing', 'job_type': 'value2'}
        monitor_gen_mock.side_effect = [gened]
        monitor_create_mock.side_effect = [('mon-id3', 'feed-id3')]
        monitor_id, feed_id = provider._monitor_sync(record, value, monitor)
        self.assertEqual('mon-id3', monitor_id)
        self.assertEqual('feed-id3', feed_id)
        monitor_gen_mock.assert_called_once()
        monitor_delete_mock.assert_has_calls([call(monitor)])
        monitor_create_mock.assert_has_calls([call(gened)])
        monitors_update_mock.assert_not_called()
        feed_create_mock.assert_not_called()

    @patch('octodns_ns1.Ns1Client.notifylists_delete')
    @patch('octodns_ns1.Ns1Client.monitors_delete')
    @patch('octodns_ns1.Ns1Client.datafeed_delete')
    @patch('octodns_ns1.Ns1Provider._monitors_for')
    def test_monitors_gc(
        self,
        monitors_for_mock,
        datafeed_delete_mock,
        monitors_delete_mock,
        notifylists_delete_mock,
    ):
        provider = Ns1Provider('test', 'api-key')

        # pre-fill caches to avoid extranious calls (things we're testing
        # elsewhere)
        provider._client._datasource_id = 'foo'
        provider._client._feeds_for_monitors = {'mon-id': 'feed-id'}

        def reset():
            datafeed_delete_mock.reset_mock()
            monitors_delete_mock.reset_mock()
            monitors_for_mock.reset_mock()
            notifylists_delete_mock.reset_mock()

        # No active monitors and no existing, nothing will happen
        reset()
        monitors_for_mock.side_effect = [{}]
        record = self.record()
        provider._monitors_gc(record)
        monitors_for_mock.assert_has_calls([call(record)])
        datafeed_delete_mock.assert_not_called()
        monitors_delete_mock.assert_not_called()
        notifylists_delete_mock.assert_not_called()

        # No active monitors and one existing, delete all the things
        reset()
        monitors_for_mock.side_effect = [
            {'x': {'id': 'mon-id', 'notify_list': 'nl-id'}}
        ]
        provider._client._notifylists_cache = {
            'not shared': {'id': 'nl-id', 'name': 'not shared'}
        }
        provider._monitors_gc(record)
        monitors_for_mock.assert_has_calls([call(record)])
        datafeed_delete_mock.assert_has_calls([call('foo', 'feed-id')])
        monitors_delete_mock.assert_has_calls([call('mon-id')])
        notifylists_delete_mock.assert_has_calls([call('nl-id')])

        # Same existing, this time in active list, should be noop
        reset()
        monitors_for_mock.side_effect = [
            {'x': {'id': 'mon-id', 'notify_list': 'nl-id'}}
        ]
        provider._monitors_gc(record, {'mon-id'})
        monitors_for_mock.assert_has_calls([call(record)])
        datafeed_delete_mock.assert_not_called()
        monitors_delete_mock.assert_not_called()
        notifylists_delete_mock.assert_not_called()

        # Non-active monitor w/o a feed, and another monitor that's left alone
        # b/c it's active
        reset()
        monitors_for_mock.side_effect = [
            {
                'x': {'id': 'mon-id', 'notify_list': 'nl-id'},
                'y': {'id': 'mon-id2', 'notify_list': 'nl-id2'},
            }
        ]
        provider._client._notifylists_cache = {
            'not shared': {'id': 'nl-id', 'name': 'not shared'},
            'not shared 2': {'id': 'nl-id2', 'name': 'not shared 2'},
        }
        provider._monitors_gc(record, {'mon-id'})
        monitors_for_mock.assert_has_calls([call(record)])
        datafeed_delete_mock.assert_not_called()
        monitors_delete_mock.assert_has_calls([call('mon-id2')])
        notifylists_delete_mock.assert_has_calls([call('nl-id2')])

        # Non-active monitor w/o a notifylist, generally shouldn't happen, but
        # code should handle it just in case someone gets clicky in the UI
        reset()
        monitors_for_mock.side_effect = [
            {'y': {'id': 'mon-id2', 'notify_list': 'nl-id2'}}
        ]
        provider._client._notifylists_cache = {
            'not shared a': {'id': 'nl-ida', 'name': 'not shared a'},
            'not shared b': {'id': 'nl-idb', 'name': 'not shared b'},
        }
        provider._monitors_gc(record, {'mon-id'})
        monitors_for_mock.assert_has_calls([call(record)])
        datafeed_delete_mock.assert_not_called()
        monitors_delete_mock.assert_has_calls([call('mon-id2')])
        notifylists_delete_mock.assert_not_called()

        # Non-active monitor with a shared notifylist, monitor deleted, but
        # notifylist is left alone
        reset()
        provider.shared_notifylist = True
        monitors_for_mock.side_effect = [
            {'y': {'id': 'mon-id2', 'notify_list': 'shared'}}
        ]
        provider._client._notifylists_cache = {
            'shared': {'id': 'shared', 'name': provider.SHARED_NOTIFYLIST_NAME}
        }
        provider._monitors_gc(record, {'mon-id'})
        monitors_for_mock.assert_has_calls([call(record)])
        datafeed_delete_mock.assert_not_called()
        monitors_delete_mock.assert_has_calls([call('mon-id2')])
        notifylists_delete_mock.assert_not_called()

    @patch('octodns_ns1.Ns1Provider._monitors_for')
    def test_params_for_dynamic_with_pool_status(self, monitors_for_mock):
        provider = Ns1Provider('test', 'api-key')
        monitors_for_mock.reset_mock()
        monitors_for_mock.return_value = {}
        record = Record.new(
            self.zone,
            '',
            {
                'dynamic': {
                    'pools': {
                        'iad': {
                            'values': [{'value': '1.2.3.4', 'status': 'up'}]
                        }
                    },
                    'rules': [{'pool': 'iad'}],
                },
                'ttl': 32,
                'type': 'A',
                'value': '1.2.3.4',
                'meta': {},
            },
        )
        params, active_monitors = provider._params_for_dynamic(record)
        self.assertEqual(params['answers'][0]['meta']['up'], True)
        self.assertEqual(len(active_monitors), 0)

        # check for down also
        record.dynamic.pools['iad'].data['values'][0]['status'] = 'down'
        params, active_monitors = provider._params_for_dynamic(record)
        self.assertEqual(params['answers'][0]['meta']['up'], False)
        self.assertEqual(len(active_monitors), 0)

    @patch('octodns_ns1.Ns1Provider._monitor_sync')
    @patch('octodns_ns1.Ns1Provider._monitors_for')
    def test_params_for_dynamic_region_only(
        self, monitors_for_mock, monitor_sync_mock
    ):
        provider = Ns1Provider('test', 'api-key')

        # pre-fill caches to avoid extranious calls (things we're testing
        # elsewhere)
        provider._client._datasource_id = 'foo'
        provider._client._feeds_for_monitors = {'mon-id': 'feed-id'}

        # provider._params_for_A() calls provider._monitors_for() and
        # provider._monitor_sync(). Mock their return values so that we don't
        # make NS1 API calls during tests
        monitors_for_mock.reset_mock()
        monitor_sync_mock.reset_mock()
        monitors_for_mock.side_effect = [{'3.4.5.6': 'mid-3'}]
        monitor_sync_mock.side_effect = [
            ('mid-1', 'fid-1'),
            ('mid-2', 'fid-2'),
            ('mid-3', 'fid-3'),
        ]

        record = self.record()
        rule0 = record.data['dynamic']['rules'][0]
        rule1 = record.data['dynamic']['rules'][1]
        rule0['geos'] = ['AF', 'EU']
        rule1['geos'] = ['SA']
        ret, monitor_ids = provider._params_for_A(record)
        self.assertEqual(10, len(ret['answers']))
        self.assertEqual(ret['filters'], provider._FILTER_CHAIN_WITH_REGION)
        self.assertEqual(
            {
                'iad__catchall': {'meta': {'note': 'rule-order:2'}},
                'iad__georegion': {
                    'meta': {
                        'georegion': ['SOUTH-AMERICA'],
                        'note': 'rule-order:1',
                    }
                },
                'lhr__georegion': {
                    'meta': {
                        'georegion': ['AFRICA', 'EUROPE'],
                        'note': 'fallback:iad rule-order:0',
                    }
                },
            },
            ret['regions'],
        )
        self.assertEqual({'mid-1', 'mid-2', 'mid-3'}, monitor_ids)

    @patch('octodns_ns1.Ns1Provider._monitor_sync')
    @patch('octodns_ns1.Ns1Provider._monitors_for')
    def test_params_for_dynamic_state_only(
        self, monitors_for_mock, monitor_sync_mock
    ):
        provider = Ns1Provider('test', 'api-key')

        # pre-fill caches to avoid extranious calls (things we're testing
        # elsewhere)
        provider._client._datasource_id = 'foo'
        provider._client._feeds_for_monitors = {'mon-id': 'feed-id'}

        # provider._params_for_A() calls provider._monitors_for() and
        # provider._monitor_sync(). Mock their return values so that we don't
        # make NS1 API calls during tests
        monitors_for_mock.reset_mock()
        monitor_sync_mock.reset_mock()
        monitors_for_mock.side_effect = [{'3.4.5.6': 'mid-3'}]
        monitor_sync_mock.side_effect = [
            ('mid-1', 'fid-1'),
            ('mid-2', 'fid-2'),
            ('mid-3', 'fid-3'),
        ]

        record = self.record()
        rule0 = record.data['dynamic']['rules'][0]
        rule1 = record.data['dynamic']['rules'][1]
        rule0['geos'] = ['AF', 'EU']
        rule1['geos'] = ['NA-US-CA', 'NA-CA-NL']
        ret, _ = provider._params_for_A(record)
        self.assertEqual(10, len(ret['answers']))
        exp = provider._FILTER_CHAIN_WITH_REGION_AND_COUNTRY
        self.assertEqual(ret['filters'], exp)
        self.assertEqual(
            {
                'iad__catchall': {'meta': {'note': 'rule-order:2'}},
                'iad__country': {
                    'meta': {
                        'note': 'rule-order:1',
                        'us_state': ['CA'],
                        'ca_province': ['NL'],
                    }
                },
                'lhr__georegion': {
                    'meta': {
                        'georegion': ['AFRICA', 'EUROPE'],
                        'note': 'fallback:iad rule-order:0',
                    }
                },
            },
            ret['regions'],
        )

    @patch('octodns_ns1.Ns1Provider._monitors_for')
    def test_params_for_dynamic_subnet_only(self, monitors_for_mock):
        provider = Ns1Provider('test', 'api-key')

        # provider._params_for_A() calls provider._monitors_for().
        # Mock it's return value so that we don't make NS1 API calls during tests
        monitors_for_mock.reset_mock()
        monitors_for_mock.side_effect = [{}]

        dynamic_rules = [
            {'subnets': ['10.1.0.0/16'], 'pool': 'lhr'},
            {'pool': 'iad'},
        ]
        record = Record.new(
            self.zone,
            '',
            {
                'dynamic': {
                    'pools': {
                        'lhr': {
                            'values': [{'value': '3.4.5.6', 'status': 'up'}]
                        },
                        'iad': {
                            'values': [{'value': '5.6.7.8', 'status': 'up'}]
                        },
                    },
                    'rules': dynamic_rules,
                },
                'ttl': 32,
                'type': 'A',
                'value': '1.2.3.4',
                'meta': {},
            },
        )
        ret, _ = provider._params_for_A(record)
        self.assertEqual(4, len(ret['answers']))
        exp = provider._FILTER_CHAIN_WITH_SUBNET
        self.assertEqual(ret['filters'], exp)
        exp_regions = {
            'iad__catchall': {'meta': {'note': 'rule-order:1'}},
            'lhr__subnet': {
                'meta': {'ip_prefixes': ['10.1.0.0/16'], 'note': 'rule-order:0'}
            },
        }
        self.assertEqual(exp_regions, ret['regions'])

        # test parsing back into the same dynamic rules
        parsed_rules = provider._parse_rules({}, exp_regions)
        for rule in parsed_rules:
            del rule['_order']
        self.assertEqual(dynamic_rules, parsed_rules)

    @patch('octodns_ns1.Ns1Provider._monitor_sync')
    @patch('octodns_ns1.Ns1Provider._monitors_for')
    def test_params_for_dynamic_contient_and_countries(
        self, monitors_for_mock, monitor_sync_mock
    ):
        provider = Ns1Provider('test', 'api-key')

        # pre-fill caches to avoid extranious calls (things we're testing
        # elsewhere)
        provider._client._datasource_id = 'foo'
        provider._client._feeds_for_monitors = {'mon-id': 'feed-id'}

        # provider._params_for_A() calls provider._monitors_for() and
        # provider._monitor_sync(). Mock their return values so that we don't
        # make NS1 API calls during tests
        provider._client.reset_caches()
        monitors_for_mock.reset_mock()
        monitor_sync_mock.reset_mock()
        monitors_for_mock.side_effect = [{'3.4.5.6': 'mid-3'}]
        monitor_sync_mock.side_effect = [
            ('mid-1', 'fid-1'),
            ('mid-2', 'fid-2'),
            ('mid-3', 'fid-3'),
        ]

        record = self.record()
        rule0 = record.data['dynamic']['rules'][0]
        rule1 = record.data['dynamic']['rules'][1]
        rule0['geos'] = ['AF', 'EU', 'NA-US-CA']
        rule1['geos'] = ['SA', 'AS-IN']
        ret, _ = provider._params_for_A(record)

        self.assertEqual(17, len(ret['answers']))
        # Deeply check the answers we have here
        # group the answers based on where they came from
        notes = defaultdict(list)
        for answer in ret['answers']:
            notes[answer['meta']['note']].append(answer)
            # Remove the meta and region part since it'll vary based on the
            # exact pool, that'll let us == them down below
            del answer['meta']
            del answer['region']

        # Expected groups. iad has occurances in here: a country and region
        # that was split out based on targeting a continent and a state. It
        # finally has a catchall.  Those are examples of the two ways pools get
        # expanded.
        #
        # lhr splits in two, with a region and country and includes a fallback
        #
        # All values now include their own `pool:` name
        #
        # well as both lhr georegion (for contients) and country. The first is
        # an example of a repeated target pool in a rule (only allowed when the
        # 2nd is a catchall.)
        self.assertEqual(
            [
                'fallback: from:iad__catchall pool:iad',
                'fallback: from:iad__country pool:iad',
                'fallback: from:iad__georegion pool:iad',
                'fallback: from:lhr__country pool:iad',
                'fallback: from:lhr__georegion pool:iad',
                'fallback:iad from:lhr__country pool:lhr',
                'fallback:iad from:lhr__georegion pool:lhr',
                'from:--default--',
            ],
            sorted(notes.keys()),
        )

        # All the iad's should match (after meta and region were removed)
        self.assertEqual(
            notes['from:iad__catchall'], notes['from:iad__country']
        )
        self.assertEqual(
            notes['from:iad__catchall'], notes['from:iad__georegion']
        )

        # The lhrs should match each other too
        self.assertEqual(
            notes['from:lhr__georegion'], notes['from:lhr__country']
        )

        # We have both country and region filter chain entries
        exp = provider._FILTER_CHAIN_WITH_REGION_AND_COUNTRY
        self.assertEqual(ret['filters'], exp)

        # and our region details match the expected behaviors/targeting
        self.assertEqual(
            {
                'iad__catchall': {'meta': {'note': 'rule-order:2'}},
                'iad__country': {
                    'meta': {'country': ['IN'], 'note': 'rule-order:1'}
                },
                'iad__georegion': {
                    'meta': {
                        'georegion': ['SOUTH-AMERICA'],
                        'note': 'rule-order:1',
                    }
                },
                'lhr__country': {
                    'meta': {
                        'note': 'fallback:iad rule-order:0',
                        'us_state': ['CA'],
                    }
                },
                'lhr__georegion': {
                    'meta': {
                        'georegion': ['AFRICA', 'EUROPE'],
                        'note': 'fallback:iad rule-order:0',
                    }
                },
            },
            ret['regions'],
        )

    @patch('octodns_ns1.Ns1Provider._monitors_for')
    def test_params_for_dynamic_region_and_subnet(self, monitors_for_mock):
        provider = Ns1Provider('test', 'api-key')

        # provider._params_for_A() calls provider._monitors_for().
        # Mock it's return value so that we don't make NS1 API calls during tests
        monitors_for_mock.reset_mock()
        monitors_for_mock.side_effect = [{}]

        dynamic_rules = [
            {'subnets': ['10.1.0.0/16'], 'geos': ['EU'], 'pool': 'lhr'},
            {'pool': 'iad'},
        ]
        record = Record.new(
            self.zone,
            '',
            {
                'dynamic': {
                    'pools': {
                        'lhr': {
                            'values': [{'value': '3.4.5.6', 'status': 'up'}]
                        },
                        'iad': {
                            'values': [{'value': '5.6.7.8', 'status': 'up'}]
                        },
                    },
                    'rules': dynamic_rules,
                },
                'ttl': 32,
                'type': 'A',
                'value': '1.2.3.4',
                'meta': {},
            },
        )
        ret, _ = provider._params_for_A(record)
        self.assertEqual(6, len(ret['answers']))
        exp = provider._FILTER_CHAIN_WITH_REGION_AND_SUBNET
        self.assertEqual(ret['filters'], exp)
        exp_regions = {
            'iad__catchall': {'meta': {'note': 'rule-order:1'}},
            'lhr__subnet': {
                'meta': {'ip_prefixes': ['10.1.0.0/16'], 'note': 'rule-order:0'}
            },
            'lhr__georegion': {
                'meta': {'georegion': ['EUROPE'], 'note': 'rule-order:0'}
            },
        }
        self.assertEqual(exp_regions, ret['regions'])

        # test parsing back into the same dynamic rules
        parsed_rules = provider._parse_rules({}, exp_regions)
        for rule in parsed_rules:
            del rule['_order']
        self.assertEqual(dynamic_rules, parsed_rules)

    @patch('octodns_ns1.Ns1Provider._monitors_for')
    def test_params_for_dynamic_country_and_subnet(self, monitors_for_mock):
        provider = Ns1Provider('test', 'api-key')

        # provider._params_for_A() calls provider._monitors_for().
        # Mock it's return value so that we don't make NS1 API calls during tests
        monitors_for_mock.reset_mock()
        monitors_for_mock.side_effect = [{}]

        dynamic_rules = [
            {'subnets': ['10.1.0.0/16'], 'geos': ['EU-GB'], 'pool': 'lhr'},
            {'pool': 'iad'},
        ]
        record = Record.new(
            self.zone,
            '',
            {
                'dynamic': {
                    'pools': {
                        'lhr': {
                            'values': [{'value': '3.4.5.6', 'status': 'up'}]
                        },
                        'iad': {
                            'values': [{'value': '5.6.7.8', 'status': 'up'}]
                        },
                    },
                    'rules': dynamic_rules,
                },
                'ttl': 32,
                'type': 'A',
                'value': '1.2.3.4',
                'meta': {},
            },
        )
        ret, _ = provider._params_for_A(record)
        self.assertEqual(6, len(ret['answers']))
        exp = provider._FILTER_CHAIN_WITH_COUNTRY_AND_SUBNET
        self.assertEqual(ret['filters'], exp)
        exp_regions = {
            'iad__catchall': {'meta': {'note': 'rule-order:1'}},
            'lhr__subnet': {
                'meta': {'ip_prefixes': ['10.1.0.0/16'], 'note': 'rule-order:0'}
            },
            'lhr__country': {
                'meta': {'country': ['GB'], 'note': 'rule-order:0'}
            },
        }
        self.assertEqual(exp_regions, ret['regions'])

        # test parsing back into the same dynamic rules
        parsed_rules = provider._parse_rules({}, exp_regions)
        for rule in parsed_rules:
            del rule['_order']
        self.assertEqual(dynamic_rules, parsed_rules)

    @patch('octodns_ns1.Ns1Provider._monitors_for')
    def test_params_for_dynamic_region_and_country_and_subnet(
        self, monitors_for_mock
    ):
        provider = Ns1Provider('test', 'api-key')

        # provider._params_for_A() calls provider._monitors_for().
        # Mock it's return value so that we don't make NS1 API calls during tests
        monitors_for_mock.reset_mock()
        monitors_for_mock.side_effect = [{}]

        dynamic_rules = [
            {
                'subnets': ['10.1.0.0/16'],
                'geos': ['AF', 'EU-GB'],
                'pool': 'lhr',
            },
            {'pool': 'iad'},
        ]
        record = Record.new(
            self.zone,
            '',
            {
                'dynamic': {
                    'pools': {
                        'lhr': {
                            'values': [{'value': '3.4.5.6', 'status': 'up'}]
                        },
                        'iad': {
                            'values': [{'value': '5.6.7.8', 'status': 'up'}]
                        },
                    },
                    'rules': dynamic_rules,
                },
                'ttl': 32,
                'type': 'A',
                'value': '1.2.3.4',
                'meta': {},
            },
        )
        ret, _ = provider._params_for_A(record)
        self.assertEqual(8, len(ret['answers']))
        exp = provider._FILTER_CHAIN_WITH_REGION_AND_COUNTRY_AND_SUBNET
        self.assertEqual(ret['filters'], exp)
        exp_regions = {
            'iad__catchall': {'meta': {'note': 'rule-order:1'}},
            'lhr__subnet': {
                'meta': {'ip_prefixes': ['10.1.0.0/16'], 'note': 'rule-order:0'}
            },
            'lhr__country': {
                'meta': {'country': ['GB'], 'note': 'rule-order:0'}
            },
            'lhr__georegion': {
                'meta': {'georegion': ['AFRICA'], 'note': 'rule-order:0'}
            },
        }
        self.assertEqual(exp_regions, ret['regions'])

        # test parsing back into the same dynamic rules
        parsed_rules = provider._parse_rules({}, exp_regions)
        for rule in parsed_rules:
            del rule['_order']
        self.assertEqual(dynamic_rules, parsed_rules)

    @patch('octodns_ns1.Ns1Provider._monitor_sync')
    @patch('octodns_ns1.Ns1Provider._monitors_for')
    def test_params_for_dynamic_oceania(
        self, monitors_for_mock, monitor_sync_mock
    ):
        provider = Ns1Provider('test', 'api-key')

        # pre-fill caches to avoid extranious calls (things we're testing
        # elsewhere)
        provider._client._datasource_id = 'foo'
        provider._client._feeds_for_monitors = {'mon-id': 'feed-id'}

        # provider._params_for_A() calls provider._monitors_for() and
        # provider._monitor_sync(). Mock their return values so that we don't
        # make NS1 API calls during tests
        monitors_for_mock.reset_mock()
        monitor_sync_mock.reset_mock()
        monitors_for_mock.side_effect = [{'3.4.5.6': 'mid-3'}]
        monitor_sync_mock.side_effect = [
            ('mid-1', 'fid-1'),
            ('mid-2', 'fid-2'),
            ('mid-3', 'fid-3'),
        ]

        # Set geos to 'OC' in rules[0] (pool - 'lhr')
        # Check returned dict has list of countries under 'OC'
        record = self.record()
        rule0 = record.data['dynamic']['rules'][0]
        rule0['geos'] = ['OC']
        ret, _ = provider._params_for_A(record)

        # Make sure the country list expanded into all the OC countries
        got = set(ret['regions']['lhr__country']['meta']['country'])
        self.assertEqual(got, Ns1Provider._CONTINENT_TO_LIST_OF_COUNTRIES['OC'])

        # When rules has 'OC', it is converted to list of countries in the
        # params. Look if the returned filters is the filter chain with country
        self.assertEqual(ret['filters'], provider._FILTER_CHAIN_WITH_COUNTRY)

    @patch('octodns_ns1.Ns1Provider._monitor_sync')
    @patch('octodns_ns1.Ns1Provider._monitors_for')
    def test_params_for_dynamic(self, monitors_for_mock, monitors_sync_mock):
        provider = Ns1Provider('test', 'api-key')

        # pre-fill caches to avoid extranious calls (things we're testing
        # elsewhere)
        provider._client._datasource_id = 'foo'
        provider._client._feeds_for_monitors = {'mon-id': 'feed-id'}

        monitors_for_mock.reset_mock()
        monitors_sync_mock.reset_mock()
        monitors_for_mock.side_effect = [{'3.4.5.6': 'mid-3'}]
        monitors_sync_mock.side_effect = [
            ('mid-1', 'fid-1'),
            ('mid-2', 'fid-2'),
            ('mid-3', 'fid-3'),
        ]
        # This indirectly calls into _params_for_dynamic and tests the
        # handling to get there
        record = self.record()
        # copy an existing answer from a different pool to 'lhr' so
        # in order to test answer repetition across pools (monitor reuse)
        record.dynamic._data()['pools']['lhr']['values'].append(
            record.dynamic._data()['pools']['iad']['values'][0]
        )
        ret, _ = provider._params_for_A(record)

        # Given that record has both country and region in the rules,
        # the returned filter chain should be one with region and country
        self.assertEqual(
            ret['filters'], provider._FILTER_CHAIN_WITH_REGION_AND_COUNTRY
        )

        monitors_for_mock.assert_has_calls([call(record)])
        monitors_sync_mock.assert_has_calls(
            [
                call(record, '1.2.3.4', None),
                call(record, '2.3.4.5', None),
                call(record, '3.4.5.6', 'mid-3'),
            ]
        )

    @patch('octodns_ns1.Ns1Provider._monitor_sync')
    @patch('octodns_ns1.Ns1Provider._monitors_for')
    def test_params_for_dynamic_CNAME(
        self, monitors_for_mock, monitor_sync_mock
    ):
        provider = Ns1Provider('test', 'api-key')

        # pre-fill caches to avoid extranious calls (things we're testing
        # elsewhere)
        provider._client._datasource_id = 'foo'
        provider._client._feeds_for_monitors = {'mon-id': 'feed-id'}

        # provider._params_for_A() calls provider._monitors_for() and
        # provider._monitor_sync(). Mock their return values so that we don't
        # make NS1 API calls during tests
        monitors_for_mock.reset_mock()
        monitor_sync_mock.reset_mock()
        monitors_for_mock.side_effect = [{'iad.unit.tests.': 'mid-1'}]
        monitor_sync_mock.side_effect = [('mid-1', 'fid-1')]

        record = self.cname_record()
        ret, _ = provider._params_for_CNAME(record)

        # Check if the default value was correctly read and populated
        # All other dynamic record test cases are covered by dynamic_A tests
        self.assertEqual(ret['answers'][-1]['answer'][0], 'value.unit.tests.')

    def test_data_for_dynamic(self):
        provider = Ns1Provider('test', 'api-key')

        # empty record turns into empty data
        ns1_record = {
            'answers': [],
            'domain': 'unit.tests',
            'filters': provider._BASIC_FILTER_CHAIN,
            'regions': {},
            'ttl': 42,
        }
        data = provider._data_for_dynamic('A', ns1_record)
        self.assertEqual(
            {
                'dynamic': {'pools': {}, 'rules': []},
                'ttl': 42,
                'type': 'A',
                'values': [],
            },
            data,
        )

        # Test out a small, but realistic setup that covers all the options
        # We have country and region in the test config
        filters = provider._get_updated_filter_chain(True, True, False)
        catchall_pool_name = 'iad__catchall'
        ns1_record = {
            'answers': [
                {
                    'answer': ['3.4.5.6'],
                    'meta': {
                        'priority': 1,
                        'note': 'from:lhr__country',
                        'up': {},
                    },
                    'region': 'lhr',
                },
                {
                    'answer': ['2.3.4.5'],
                    'meta': {
                        'priority': 2,
                        'weight': 12,
                        'note': 'from:iad',
                        'up': {},
                    },
                    'region': 'lhr',
                },
                {
                    'answer': ['1.2.3.4'],
                    'meta': {'priority': 3, 'note': 'from:--default--'},
                    'region': 'lhr',
                },
                {
                    'answer': ['2.3.4.5'],
                    'meta': {
                        'priority': 1,
                        'weight': 12,
                        'note': 'from:iad',
                        'up': {},
                    },
                    'region': 'iad',
                },
                {
                    'answer': ['1.2.3.4'],
                    'meta': {'priority': 2, 'note': 'from:--default--'},
                    'region': 'iad',
                },
                {
                    'answer': ['2.3.4.5'],
                    'meta': {
                        'priority': 1,
                        'weight': 12,
                        'note': f'from:{catchall_pool_name}',
                        'up': {},
                    },
                    'region': catchall_pool_name,
                },
                {
                    'answer': ['1.2.3.4'],
                    'meta': {'priority': 2, 'note': 'from:--default--'},
                    'region': catchall_pool_name,
                },
            ],
            'domain': 'unit.tests',
            'filters': filters,
            'regions': {
                # lhr will use the new-split style names (and that will require
                # combining in the code to produce the expected answer
                'lhr__georegion': {
                    'meta': {
                        'note': 'rule-order:1 fallback:iad',
                        'georegion': ['AFRICA'],
                    }
                },
                'lhr__country': {
                    'meta': {
                        'note': 'rule-order:1 fallback:iad',
                        'country': ['MX'],
                        'us_state': ['OR'],
                        'ca_province': ['NL'],
                    }
                },
                # iad will use the old style "plain" region naming. We won't
                # see mixed names like this in practice, but this should
                # exercise both paths
                'iad': {'meta': {'note': 'rule-order:2', 'country': ['ZW']}},
                catchall_pool_name: {'meta': {'note': 'rule-order:3'}},
            },
            'tier': 3,
            'ttl': 42,
        }
        data = provider._data_for_dynamic('A', ns1_record)
        self.assertEqual(
            {
                'dynamic': {
                    'pools': {
                        'iad': {
                            'fallback': None,
                            'values': [{'value': '2.3.4.5', 'weight': 12}],
                        },
                        'lhr': {
                            'fallback': 'iad',
                            'values': [{'weight': 1, 'value': '3.4.5.6'}],
                        },
                    },
                    'rules': [
                        {
                            '_order': 1,
                            'geos': ['AF', 'NA-CA-NL', 'NA-MX', 'NA-US-OR'],
                            'pool': 'lhr',
                        },
                        {'_order': 2, 'geos': ['AF-ZW'], 'pool': 'iad'},
                        {'_order': 3, 'pool': 'iad'},
                    ],
                },
                'ttl': 42,
                'type': 'A',
                'values': ['1.2.3.4'],
            },
            data,
        )

        # Same answer if we go through _data_for_A which out sources the job to
        # _data_for_dynamic
        data2 = provider._data_for_A('A', ns1_record)
        self.assertEqual(data, data2)

        # Same answer if we have an old-style catchall name
        old_style_catchall_pool_name = 'catchall__iad'
        ns1_record['answers'][-2]['region'] = old_style_catchall_pool_name
        ns1_record['answers'][-1]['region'] = old_style_catchall_pool_name
        ns1_record['regions'][old_style_catchall_pool_name] = ns1_record[
            'regions'
        ][catchall_pool_name]
        del ns1_record['regions'][catchall_pool_name]
        data3 = provider._data_for_dynamic('A', ns1_record)
        self.assertEqual(data, data2)

        # Oceania test cases
        # 1. Full list of countries should return 'OC' in geos
        oc_countries = Ns1Provider._CONTINENT_TO_LIST_OF_COUNTRIES['OC']
        ns1_record['regions']['lhr__country']['meta']['country'] = list(
            oc_countries
        )
        data3 = provider._data_for_A('A', ns1_record)
        self.assertTrue('OC' in data3['dynamic']['rules'][0]['geos'])

        # 2. Partial list of countries should return just those
        partial_oc_cntry_list = list(oc_countries)[:5]
        ns1_record['regions']['lhr__country']['meta'][
            'country'
        ] = partial_oc_cntry_list
        data4 = provider._data_for_A('A', ns1_record)
        for c in partial_oc_cntry_list:
            self.assertTrue(f'OC-{c}' in data4['dynamic']['rules'][0]['geos'])

        # NA test cases
        # 1. Full list of countries should return 'NA' in geos
        na_countries = Ns1Provider._CONTINENT_TO_LIST_OF_COUNTRIES['NA']
        del ns1_record['regions']['lhr__country']['meta']['us_state']
        ns1_record['regions']['lhr__country']['meta']['country'] = list(
            na_countries
        )
        data5 = provider._data_for_A('A', ns1_record)
        self.assertTrue('NA' in data5['dynamic']['rules'][0]['geos'])

        # 2. Partial list of countries should return just those
        partial_na_cntry_list = list(na_countries)[:5] + ['SX']
        ns1_record['regions']['lhr__country']['meta'][
            'country'
        ] = partial_na_cntry_list
        data6 = provider._data_for_A('A', ns1_record)
        for c in partial_na_cntry_list:
            self.assertTrue(f'NA-{c}' in data6['dynamic']['rules'][0]['geos'])

        # Test out fallback only pools and new-style notes
        ns1_record = {
            'answers': [
                {
                    'answer': ['1.1.1.1'],
                    'meta': {
                        'priority': 1,
                        'note': 'from:one__country pool:one fallback:two',
                        'up': True,
                    },
                    'region': 'one_country',
                },
                {
                    'answer': ['2.2.2.2'],
                    'meta': {
                        'priority': 2,
                        'note': 'from:one__country pool:two fallback:three',
                        'up': {},
                    },
                    'region': 'one_country',
                },
                {
                    'answer': ['3.3.3.3'],
                    'meta': {
                        'priority': 3,
                        'note': 'from:one__country pool:three fallback:',
                        'up': False,
                    },
                    'region': 'one_country',
                },
                {
                    'answer': ['5.5.5.5'],
                    'meta': {'priority': 4, 'note': 'from:--default--'},
                    'region': 'one_country',
                },
                {
                    'answer': ['4.4.4.4'],
                    'meta': {
                        'priority': 1,
                        'note': 'from:four__country pool:four fallback:',
                        'up': {},
                    },
                    'region': 'four_country',
                },
                {
                    'answer': ['5.5.5.5'],
                    'meta': {'priority': 2, 'note': 'from:--default--'},
                    'region': 'four_country',
                },
            ],
            'domain': 'unit.tests',
            'filters': filters,
            'regions': {
                'one__country': {
                    'meta': {
                        'note': 'rule-order:1 fallback:two',
                        'country': ['CA'],
                        'us_state': ['OR'],
                    }
                },
                'four__country': {
                    'meta': {
                        'note': 'rule-order:2',
                        'country': ['CA'],
                        'us_state': ['OR'],
                    }
                },
                catchall_pool_name: {'meta': {'note': 'rule-order:3'}},
            },
            'tier': 3,
            'ttl': 42,
        }
        data = provider._data_for_dynamic('A', ns1_record)
        self.assertEqual(
            {
                'dynamic': {
                    'pools': {
                        'four': {
                            'fallback': None,
                            'values': [{'value': '4.4.4.4', 'weight': 1}],
                        },
                        'one': {
                            'fallback': 'two',
                            'values': [
                                {
                                    'value': '1.1.1.1',
                                    'weight': 1,
                                    'status': 'up',
                                }
                            ],
                        },
                        'three': {
                            'fallback': None,
                            'values': [
                                {
                                    'value': '3.3.3.3',
                                    'weight': 1,
                                    'status': 'down',
                                }
                            ],
                        },
                        'two': {
                            'fallback': 'three',
                            'values': [{'value': '2.2.2.2', 'weight': 1}],
                        },
                    },
                    'rules': [
                        {
                            '_order': 1,
                            'geos': ['NA-CA', 'NA-US-OR'],
                            'pool': 'one',
                        },
                        {
                            '_order': 2,
                            'geos': ['NA-CA', 'NA-US-OR'],
                            'pool': 'four',
                        },
                        {'_order': 3, 'pool': 'iad'},
                    ],
                },
                'ttl': 42,
                'type': 'A',
                'values': ['5.5.5.5'],
            },
            data,
        )

    def test_data_for_A_non_dynamic(self):
        provider = Ns1Provider('test', 'api-key')

        # empty note
        ns1_record = {
            'answers': [
                {
                    'answer': ['iad.unit.tests.'],
                    'meta': {'priority': 1, 'weight': 12, 'note': '', 'up': {}},
                    'region': None,
                }
            ],
            'domain': 'foo.unit.tests',
            'filters': None,
            'regions': None,
            'tier': 3,
            'ttl': 43,
            'type': 'A',
        }
        data = provider._data_for_A('A', ns1_record)
        self.assertEqual({'ttl': 43, 'type': 'A', 'values': []}, data)

        # no note
        ns1_record = {
            'answers': [
                {
                    'answer': ['iad.unit.tests.'],
                    'meta': {'priority': 1, 'weight': 12, 'up': {}},
                    'region': None,
                }
            ],
            'domain': 'foo.unit.tests',
            'filters': None,
            'regions': None,
            'tier': 3,
            'ttl': 43,
            'type': 'A',
        }
        data = provider._data_for_A('A', ns1_record)
        self.assertEqual({'ttl': 43, 'type': 'A', 'values': []}, data)

    def test_data_for_dynamic_CNAME(self):
        provider = Ns1Provider('test', 'api-key')

        # Test out a small setup that just covers default value validation
        # Everything else is same as dynamic A whose tests will cover all
        # other options and test cases
        # Not testing for geo/region specific cases
        filters = provider._get_updated_filter_chain(False, False, False)
        catchall_pool_name = 'iad__catchall'
        ns1_record = {
            'answers': [
                {
                    'answer': ['iad.unit.tests.'],
                    'meta': {
                        'priority': 1,
                        'weight': 12,
                        'note': f'pool:iad from:{catchall_pool_name}',
                        'up': {},
                    },
                    'region': catchall_pool_name,
                },
                {
                    'answer': ['value.unit.tests.'],
                    'meta': {
                        'priority': 2,
                        'note': 'from:--default--',
                        'up': {},
                    },
                    'region': catchall_pool_name,
                },
            ],
            'domain': 'foo.unit.tests',
            'filters': filters,
            'regions': {catchall_pool_name: {'meta': {'note': 'rule-order:1'}}},
            'tier': 3,
            'ttl': 43,
            'type': 'CNAME',
        }
        data = provider._data_for_CNAME('CNAME', ns1_record)
        self.assertEqual(
            {
                'dynamic': {
                    'pools': {
                        'iad': {
                            'fallback': None,
                            'values': [
                                {'value': 'iad.unit.tests.', 'weight': 12}
                            ],
                        }
                    },
                    'rules': [{'_order': 1, 'pool': 'iad'}],
                },
                'ttl': 43,
                'type': 'CNAME',
                'value': 'value.unit.tests.',
            },
            data,
        )

    def test_data_for_invalid_dynamic_CNAME(self):
        provider = Ns1Provider('test', 'api-key')

        # Potential setup created outside of octoDNS, so it could be missing
        # notes and region names can be arbitrary
        filters = provider._get_updated_filter_chain(False, False, False)
        ns1_record = {
            'answers': [
                {
                    'answer': ['iad.unit.tests.'],
                    'meta': {'priority': 1, 'weight': 12, 'up': {}},
                    'region': 'global',
                },
                {
                    'answer': ['value.unit.tests.'],
                    'meta': {'priority': 2, 'up': {}},
                    'region': 'global',
                },
            ],
            'domain': 'foo.unit.tests',
            'filters': filters,
            'regions': {'global': {}},
            'tier': 3,
            'ttl': 44,
            'type': 'CNAME',
        }
        data = provider._data_for_CNAME('CNAME', ns1_record)
        self.assertEqual({'ttl': 44, 'type': 'CNAME', 'value': None}, data)

    @patch('octodns_ns1.Ns1Provider._monitor_sync')
    @patch('octodns_ns1.Ns1Provider._monitors_for')
    def test_dynamic_explicit_countries(
        self, monitors_for_mock, monitors_sync_mock
    ):
        provider = Ns1Provider('test', 'api-key')
        record_data = {
            'dynamic': {
                'pools': {
                    'iad': {
                        'values': [{'value': 'iad.unit.tests.', 'status': 'up'}]
                    },
                    'lhr': {
                        'values': [{'value': 'lhr.unit.tests.', 'status': 'up'}]
                    },
                },
                'rules': [
                    {'geos': ['NA-US'], 'pool': 'iad'},
                    {'geos': ['NA'], 'pool': 'lhr'},
                    {'pool': 'iad'},
                ],
            },
            'ttl': 33,
            'type': 'CNAME',
            'value': 'value.unit.tests.',
        }
        record = Record.new(self.zone, 'foo', record_data)

        ns1_record, _ = provider._params_for_dynamic(record)
        regions = [
            r
            for r in ns1_record['regions'].values()
            if 'US' in r['meta'].get('country', [])
        ]
        self.assertEqual(len(regions), 1)

        ns1_record['domain'] = record.fqdn[:-1]
        data = provider._data_for_dynamic(record._type, ns1_record)['dynamic']
        self.assertEqual(data['rules'][0]['geos'], ['NA-US'])
        self.assertEqual(data['rules'][1]['geos'], ['NA'])

    @patch('ns1.rest.records.Records.retrieve')
    @patch('ns1.rest.zones.Zones.retrieve')
    @patch('octodns_ns1.Ns1Provider._monitors_for')
    def test_extra_changes(
        self, monitors_for_mock, zones_retrieve_mock, records_retrieve_mock
    ):
        provider = Ns1Provider('test', 'api-key')

        desired = Zone('unit.tests.', [])

        def reset():
            monitors_for_mock.reset_mock()
            provider._client.reset_caches()
            records_retrieve_mock.reset_mock()
            zones_retrieve_mock.reset_mock()

        # Empty zone and no changes
        reset()

        extra = provider._extra_changes(desired, [])
        self.assertFalse(extra)
        monitors_for_mock.assert_not_called()

        # Non-existent zone. No changes
        reset()
        zones_retrieve_mock.side_effect = ResourceException(
            'server error: zone not found'
        )
        extra = provider._extra_changes(desired, [])
        self.assertFalse(extra)

        # Simple record, ignored, filter update lookups ignored
        reset()
        zones_retrieve_mock.side_effect = ResourceException(
            'server error: zone not found'
        )

        simple = Record.new(
            desired,
            '',
            {'ttl': 32, 'type': 'A', 'value': '1.2.3.4', 'meta': {}},
        )
        desired.add_record(simple)
        extra = provider._extra_changes(desired, [])
        self.assertFalse(extra)
        monitors_for_mock.assert_not_called()

        # Dynamic record, inspectable
        dynamic = Record.new(
            desired,
            'dyn',
            {
                'dynamic': {
                    'pools': {'iad': {'values': [{'value': '1.2.3.4'}]}},
                    'rules': [{'pool': 'iad'}],
                },
                'octodns': {
                    'healthcheck': {
                        'host': 'send.me',
                        'path': '/_ping',
                        'port': 80,
                        'protocol': 'HTTP',
                    }
                },
                'ttl': 32,
                'type': 'A',
                'value': '1.2.3.4',
                'meta': {},
            },
        )
        desired.add_record(dynamic)

        # untouched, but everything in sync so no change needed
        reset()
        # Generate what we expect to have
        provider.record_filters[dynamic.fqdn[:-1]] = {
            dynamic._type: provider._get_updated_filter_chain(
                False, False, False
            )
        }
        gend = provider._monitor_gen(dynamic, '1.2.3.4')
        gend.update(
            {
                'id': 'mid',  # need to add an id
                'notify_list': 'xyz',  # need to add a notify list (for now)
            }
        )
        monitors_for_mock.side_effect = [{'1.2.3.4': gend}]
        extra = provider._extra_changes(desired, [])
        self.assertFalse(extra)
        monitors_for_mock.assert_has_calls([call(dynamic)])

        update = Update(dynamic, dynamic)

        # If we don't have a notify list we're broken and we'll expect to see
        # an Update
        reset()
        del gend['notify_list']
        monitors_for_mock.side_effect = [{'1.2.3.4': gend}]
        extra = provider._extra_changes(desired, [])
        self.assertEqual(1, len(extra))
        extra = list(extra)[0]
        self.assertIsInstance(extra, Update)
        self.assertEqual(dynamic, extra.new)
        monitors_for_mock.assert_has_calls([call(dynamic)])
        gend['notify_list'] = 'xyz'

        # change the healthcheck protocol, we'll still
        # expect to see an update
        reset()
        dynamic.octodns['healthcheck']['protocol'] = 'HTTPS'
        monitors_for_mock.side_effect = [{'1.2.3.4': gend}]
        extra = provider._extra_changes(desired, [])
        self.assertEqual(1, len(extra))
        extra = list(extra)[0]
        self.assertIsInstance(extra, Update)
        self.assertEqual(dynamic, extra.new)
        monitors_for_mock.assert_has_calls([call(dynamic)])
        dynamic.octodns['healthcheck']['protocol'] = 'HTTP'

        # Expect to see an update from TCP to HTTP monitor/job_type
        ## no change if use_http_monitors=False (default)
        monitors_for_mock.side_effect = [{'1.2.3.4': gend}]
        extra = provider._extra_changes(desired, [])
        self.assertFalse(extra)
        ## change triggered if use_http_monitors=True
        monitors_for_mock.side_effect = [{'1.2.3.4': gend}]
        provider.use_http_monitors = True
        extra = provider._extra_changes(desired, [])
        self.assertTrue(extra)
        provider.use_http_monitors = False

        # If it's in the changed list, it'll be ignored
        reset()
        monitors_for_mock.side_effect = [{}]
        extra = provider._extra_changes(desired, [update])
        self.assertFalse(extra)

        # Missing monitor should trigger an update
        reset()
        monitors_for_mock.side_effect = [{}]
        provider.use_http_monitors = True
        extra = provider._extra_changes(desired, [])
        self.assertTrue(extra)
        provider.use_http_monitors = False

        # Missing monitor for non-obey shouldn't trigger update
        reset()
        dynamic.dynamic.pools['iad'].data['values'][0]['status'] = 'up'
        monitors_for_mock.side_effect = [{}]
        extra = provider._extra_changes(desired, [])
        self.assertFalse(extra)

        # Test changes in filters

        # No change in filters
        reset()
        ns1_zone = {
            'records': [
                {
                    "domain": "dyn.unit.tests",
                    "zone": "unit.tests",
                    "type": "A",
                    "tier": 3,
                    "filters": provider._BASIC_FILTER_CHAIN,
                }
            ]
        }
        monitors_for_mock.side_effect = [{}]
        zones_retrieve_mock.side_effect = [ns1_zone]
        records_retrieve_mock.side_effect = ns1_zone['records']
        extra = provider._extra_changes(desired, [])
        self.assertFalse(extra)

        # filters need an update
        reset()
        ns1_zone = {
            'records': [
                {
                    "domain": "dyn.unit.tests",
                    "zone": "unit.tests",
                    "type": "A",
                    "tier": 3,
                    "filters": provider._BASIC_FILTER_CHAIN[:-1],
                }
            ]
        }
        monitors_for_mock.side_effect = [{}]
        zones_retrieve_mock.side_effect = [ns1_zone]
        records_retrieve_mock.side_effect = ns1_zone['records']
        ns1_record = ns1_zone['records'][0]
        provider.record_filters[ns1_record['domain']] = {
            ns1_record['type']: ns1_record['filters']
        }
        extra = provider._extra_changes(desired, [])
        self.assertTrue(extra)

        # disabled=False in filters doesn't trigger an update
        reset()
        ns1_zone = {
            'records': [
                {
                    "domain": "dyn.unit.tests",
                    "zone": "unit.tests",
                    "type": "A",
                    "tier": 3,
                    "filters": provider._BASIC_FILTER_CHAIN,
                }
            ]
        }
        ns1_zone['records'][0]['filters'][0]['disabled'] = False
        monitors_for_mock.side_effect = [{}]
        zones_retrieve_mock.side_effect = [ns1_zone]
        records_retrieve_mock.side_effect = ns1_zone['records']
        ns1_record = ns1_zone['records'][0]
        provider.record_filters[ns1_record['domain']] = {
            ns1_record['type']: ns1_record['filters']
        }
        extra = provider._extra_changes(desired, [])
        self.assertFalse(extra)

        # disabled=True in filters does trigger an update
        ns1_zone['records'][0]['filters'][0]['disabled'] = True
        monitors_for_mock.side_effect = [{}]
        extra = provider._extra_changes(desired, [])
        self.assertTrue(extra)

    DESIRED = Zone('unit.tests.', [])

    SIMPLE = Record.new(
        DESIRED, 'sim', {'ttl': 33, 'type': 'A', 'value': '1.2.3.4'}
    )

    # Dynamic record, inspectable
    DYNAMIC = Record.new(
        DESIRED,
        'dyn',
        {
            'dynamic': {
                'pools': {'iad': {'values': [{'value': '1.2.3.4'}]}},
                'rules': [{'pool': 'iad'}],
            },
            'octodns': {
                'healthcheck': {
                    'host': 'send.me',
                    'path': '/_ping',
                    'port': 80,
                    'protocol': 'HTTP',
                }
            },
            'ttl': 32,
            'type': 'A',
            'value': '1.2.3.4',
            'meta': {},
        },
    )

    def test_has_dynamic(self):
        provider = Ns1Provider('test', 'api-key')

        simple_update = Update(self.SIMPLE, self.SIMPLE)
        dynamic_update = Update(self.DYNAMIC, self.DYNAMIC)

        self.assertFalse(provider._has_dynamic([simple_update]))
        self.assertTrue(provider._has_dynamic([dynamic_update]))
        self.assertTrue(provider._has_dynamic([simple_update, dynamic_update]))

    @patch('octodns_ns1.Ns1Client.zones_retrieve')
    @patch('octodns_ns1.Ns1Provider._apply_Update')
    def test_apply_monitor_regions(
        self, apply_update_mock, zones_retrieve_mock
    ):
        provider = Ns1Provider('test', 'api-key')

        simple_update = Update(self.SIMPLE, self.SIMPLE)
        simple_plan = Plan(self.DESIRED, self.DESIRED, [simple_update], True)
        dynamic_update = Update(self.DYNAMIC, self.DYNAMIC)
        dynamic_update = Update(self.DYNAMIC, self.DYNAMIC)
        dynamic_plan = Plan(self.DESIRED, self.DESIRED, [dynamic_update], True)
        both_plan = Plan(
            self.DESIRED, self.DESIRED, [simple_update, dynamic_update], True
        )

        # always return foo, we aren't testing this part here
        zones_retrieve_mock.side_effect = ['foo', 'foo', 'foo', 'foo']

        # Doesn't blow up, and calls apply once
        apply_update_mock.reset_mock()
        provider._apply(simple_plan)
        apply_update_mock.assert_has_calls([call('foo', simple_update)])

        # Blows up and apply not called
        apply_update_mock.reset_mock()
        with self.assertRaises(Ns1Exception) as ctx:
            provider._apply(dynamic_plan)
        self.assertTrue('monitor_regions not set' in str(ctx.exception))
        apply_update_mock.assert_not_called()

        # Blows up and apply not called even though there's a simple
        apply_update_mock.reset_mock()
        with self.assertRaises(Ns1Exception) as ctx:
            provider._apply(both_plan)
        self.assertTrue('monitor_regions not set' in str(ctx.exception))
        apply_update_mock.assert_not_called()

        # with monitor_regions set
        provider.monitor_regions = ['lga']

        apply_update_mock.reset_mock()
        provider._apply(both_plan)
        apply_update_mock.assert_has_calls(
            [call('foo', dynamic_update), call('foo', simple_update)]
        )


class TestNs1Client(TestCase):
    @patch('ns1.rest.zones.Zones.retrieve')
    def test_retry_behavior(self, zone_retrieve_mock):
        client = Ns1Client('dummy-key')

        # No retry required, just calls and is returned
        client.reset_caches()
        zone_retrieve_mock.reset_mock()
        zone_retrieve_mock.side_effect = ['foo']
        self.assertEqual('foo', client.zones_retrieve('unit.tests'))
        zone_retrieve_mock.assert_has_calls([call('unit.tests')])

        # One retry required
        client.reset_caches()
        zone_retrieve_mock.reset_mock()
        zone_retrieve_mock.side_effect = [
            RateLimitException('boo', period=0),
            'foo',
        ]
        self.assertEqual('foo', client.zones_retrieve('unit.tests'))
        zone_retrieve_mock.assert_has_calls([call('unit.tests')])

        # Two retries required
        client.reset_caches()
        zone_retrieve_mock.reset_mock()
        zone_retrieve_mock.side_effect = [
            RateLimitException('boo', period=0),
            'foo',
        ]
        self.assertEqual('foo', client.zones_retrieve('unit.tests'))
        zone_retrieve_mock.assert_has_calls([call('unit.tests')])

        # Exhaust our retries
        client.reset_caches()
        zone_retrieve_mock.reset_mock()
        zone_retrieve_mock.side_effect = [
            RateLimitException('first', period=0),
            RateLimitException('boo', period=0),
            RateLimitException('boo', period=0),
            RateLimitException('last', period=0),
        ]
        with self.assertRaises(RateLimitException) as ctx:
            client.zones_retrieve('unit.tests')
        self.assertEqual('last', str(ctx.exception))

    def test_client_config(self):
        with self.assertRaises(TypeError):
            Ns1Client()

        client = Ns1Client('dummy-key')
        self.assertEqual(
            client._client.config.get('keys'),
            {'default': {'key': u'dummy-key', 'desc': 'imported API key'}},
        )
        self.assertEqual(client._client.config.get('follow_pagination'), True)
        self.assertEqual(client._client.config.get('rate_limit_strategy'), None)
        self.assertEqual(client._client.config.get('parallelism'), None)

        client = Ns1Client('dummy-key', parallelism=11)
        self.assertEqual(
            client._client.config.get('rate_limit_strategy'), 'concurrent'
        )
        self.assertEqual(client._client.config.get('parallelism'), 11)

        client = Ns1Client(
            'dummy-key',
            client_config={
                'endpoint': 'my.endpoint.com',
                'follow_pagination': False,
            },
        )
        self.assertEqual(
            client._client.config.get('endpoint'), 'my.endpoint.com'
        )
        self.assertEqual(client._client.config.get('follow_pagination'), False)

    @patch('ns1.rest.data.Source.list')
    @patch('ns1.rest.data.Source.create')
    def test_datasource_id(self, datasource_create_mock, datasource_list_mock):
        client = Ns1Client('dummy-key')

        # First invocation with an empty list create
        datasource_list_mock.reset_mock()
        datasource_create_mock.reset_mock()
        datasource_list_mock.side_effect = [[]]
        datasource_create_mock.side_effect = [{'id': 'foo'}]
        self.assertEqual('foo', client.datasource_id)
        name = 'octoDNS NS1 Data Source'
        source_type = 'nsone_monitoring'
        datasource_create_mock.assert_has_calls(
            [call(name=name, sourcetype=source_type)]
        )
        datasource_list_mock.assert_called_once()

        # 2nd invocation is cached
        datasource_list_mock.reset_mock()
        datasource_create_mock.reset_mock()
        self.assertEqual('foo', client.datasource_id)
        datasource_create_mock.assert_not_called()
        datasource_list_mock.assert_not_called()

        # Reset the client's cache
        client._datasource_id = None

        # First invocation with a match in the list finds it and doesn't call
        # create
        datasource_list_mock.reset_mock()
        datasource_create_mock.reset_mock()
        datasource_list_mock.side_effect = [
            [
                {'id': 'other', 'name': 'not a match'},
                {'id': 'bar', 'name': name},
            ]
        ]
        self.assertEqual('bar', client.datasource_id)
        datasource_create_mock.assert_not_called()
        datasource_list_mock.assert_called_once()

    @patch('ns1.rest.data.Feed.delete')
    @patch('ns1.rest.data.Feed.create')
    @patch('ns1.rest.data.Feed.list')
    def test_feeds_for_monitors(
        self, datafeed_list_mock, datafeed_create_mock, datafeed_delete_mock
    ):
        client = Ns1Client('dummy-key')

        # pre-cache datasource_id
        client._datasource_id = 'foo'

        # Populate the cache and check the results
        datafeed_list_mock.reset_mock()
        datafeed_list_mock.side_effect = [
            [
                {'config': {'jobid': 'the-job'}, 'id': 'the-feed'},
                {'config': {'jobid': 'the-other-job'}, 'id': 'the-other-feed'},
            ]
        ]
        expected = {'the-job': 'the-feed', 'the-other-job': 'the-other-feed'}
        self.assertEqual(expected, client.feeds_for_monitors)
        datafeed_list_mock.assert_called_once()

        # 2nd call uses cache
        datafeed_list_mock.reset_mock()
        self.assertEqual(expected, client.feeds_for_monitors)
        datafeed_list_mock.assert_not_called()

        # create a feed and make sure it's in the cache/map
        datafeed_create_mock.reset_mock()
        datafeed_create_mock.side_effect = [{'id': 'new-feed'}]
        client.datafeed_create(
            client.datasource_id, 'new-name', {'jobid': 'new-job'}
        )
        datafeed_create_mock.assert_has_calls(
            [call('foo', 'new-name', {'jobid': 'new-job'})]
        )
        new_expected = expected.copy()
        new_expected['new-job'] = 'new-feed'
        self.assertEqual(new_expected, client.feeds_for_monitors)
        datafeed_create_mock.assert_called_once()

        # Delete a feed and make sure it's out of the cache/map
        datafeed_delete_mock.reset_mock()
        client.datafeed_delete(client.datasource_id, 'new-feed')
        self.assertEqual(expected, client.feeds_for_monitors)
        datafeed_delete_mock.assert_called_once()

    @patch('ns1.rest.monitoring.Monitors.delete')
    @patch('ns1.rest.monitoring.Monitors.update')
    @patch('ns1.rest.monitoring.Monitors.create')
    @patch('ns1.rest.monitoring.Monitors.list')
    def test_monitors(
        self,
        monitors_list_mock,
        monitors_create_mock,
        monitors_update_mock,
        monitors_delete_mock,
    ):
        client = Ns1Client('dummy-key')

        one = {'id': 'one', 'key': 'value'}
        two = {'id': 'two', 'key': 'other-value'}

        # Populate the cache and check the results
        monitors_list_mock.reset_mock()
        monitors_list_mock.side_effect = [[one, two]]
        expected = {'one': one, 'two': two}
        self.assertEqual(expected, client.monitors)
        monitors_list_mock.assert_called_once()

        # 2nd round pulls it from cache
        monitors_list_mock.reset_mock()
        self.assertEqual(expected, client.monitors)
        monitors_list_mock.assert_not_called()

        # Create a monitor, make sure it's in the list
        monitors_create_mock.reset_mock()
        monitor = {'id': 'new-id', 'key': 'new-value'}
        monitors_create_mock.side_effect = [monitor]
        self.assertEqual(monitor, client.monitors_create(param='eter'))
        monitors_create_mock.assert_has_calls([call({}, param='eter')])
        new_expected = expected.copy()
        new_expected['new-id'] = monitor
        self.assertEqual(new_expected, client.monitors)

        # Update a monitor, make sure it's updated in the cache
        monitors_update_mock.reset_mock()
        monitor = {'id': 'new-id', 'key': 'changed-value'}
        monitors_update_mock.side_effect = [monitor]
        self.assertEqual(
            monitor, client.monitors_update('new-id', key='changed-value')
        )
        monitors_update_mock.assert_has_calls(
            [call('new-id', {}, key='changed-value')]
        )
        new_expected['new-id'] = monitor
        self.assertEqual(new_expected, client.monitors)

        # Delete a monitor, make sure it's out of the list
        monitors_delete_mock.reset_mock()
        monitors_delete_mock.side_effect = ['deleted']
        self.assertEqual('deleted', client.monitors_delete('new-id'))
        monitors_delete_mock.assert_has_calls([call('new-id')])
        self.assertEqual(expected, client.monitors)

    @patch('ns1.rest.monitoring.NotifyLists.delete')
    @patch('ns1.rest.monitoring.NotifyLists.create')
    @patch('ns1.rest.monitoring.NotifyLists.list')
    def test_notifylists(
        self,
        notifylists_list_mock,
        notifylists_create_mock,
        notifylists_delete_mock,
    ):
        client = Ns1Client('dummy-key')

        def reset():
            notifylists_create_mock.reset_mock()
            notifylists_delete_mock.reset_mock()
            notifylists_list_mock.reset_mock()

        reset()
        notifylists_list_mock.side_effect = [{}]
        expected = {'id': 'nl-id', 'name': 'bar'}
        notifylists_create_mock.side_effect = [expected]
        notify_list = [{'config': {'sourceid': 'foo'}, 'type': 'datafeed'}]
        got = client.notifylists_create(
            name='some name', notify_list=notify_list
        )
        self.assertEqual(expected, got)
        notifylists_list_mock.assert_called_once()
        notifylists_create_mock.assert_has_calls(
            [call({'name': 'some name', 'notify_list': notify_list})]
        )
        notifylists_delete_mock.assert_not_called()

        reset()
        client.notifylists_delete('nlid')
        notifylists_list_mock.assert_not_called()
        notifylists_create_mock.assert_not_called()
        notifylists_delete_mock.assert_has_calls([call('nlid')])

        # Delete again, this time with a cache item that needs cleaned out and
        # another that needs to be ignored
        reset()
        client._notifylists_cache = {
            'another': {'id': 'notid', 'name': 'another'},
            # This one comes 2nd on purpose
            'the-one': {'id': 'nlid', 'name': 'the-one'},
        }
        client.notifylists_delete('nlid')
        notifylists_list_mock.assert_not_called()
        notifylists_create_mock.assert_not_called()
        notifylists_delete_mock.assert_has_calls([call('nlid')])
        # Only another left
        self.assertEqual(['another'], list(client._notifylists_cache.keys()))

        reset()
        expected = ['one', 'two', 'three']
        notifylists_list_mock.side_effect = [expected]
        nls = client.notifylists_list()
        self.assertEqual(expected, nls)
        notifylists_list_mock.assert_has_calls([call()])
        notifylists_create_mock.assert_not_called()
        notifylists_delete_mock.assert_not_called()

    @patch('ns1.rest.records.Records.delete')
    @patch('ns1.rest.records.Records.update')
    @patch('ns1.rest.records.Records.create')
    @patch('ns1.rest.records.Records.retrieve')
    @patch('ns1.rest.zones.Zones.create')
    @patch('ns1.rest.zones.Zones.delete')
    @patch('ns1.rest.zones.Zones.retrieve')
    def test_client_caching(
        self,
        zone_retrieve_mock,
        zone_delete_mock,
        zone_create_mock,
        record_retrieve_mock,
        record_create_mock,
        record_update_mock,
        record_delete_mock,
    ):
        client = Ns1Client('dummy-key')

        def reset():
            zone_retrieve_mock.reset_mock()
            zone_delete_mock.reset_mock()
            zone_create_mock.reset_mock()
            record_retrieve_mock.reset_mock()
            record_create_mock.reset_mock()
            record_update_mock.reset_mock()
            record_delete_mock.reset_mock()
            # Testing caches so we don't reset those

        # Initial zone get fetches and caches
        reset()
        zone_retrieve_mock.side_effect = ['foo']
        self.assertEqual('foo', client.zones_retrieve('unit.tests'))
        zone_retrieve_mock.assert_has_calls([call('unit.tests')])
        self.assertEqual({'unit.tests': 'foo'}, client._zones_cache)

        # Subsequent zone get does not fetch and returns from cache
        reset()
        self.assertEqual('foo', client.zones_retrieve('unit.tests'))
        zone_retrieve_mock.assert_not_called()

        # Zone create stores in cache
        reset()
        zone_create_mock.side_effect = ['bar']
        self.assertEqual('bar', client.zones_create('sub.unit.tests'))
        zone_create_mock.assert_has_calls([call('sub.unit.tests')])
        self.assertEqual(
            {'sub.unit.tests': 'bar', 'unit.tests': 'foo'}, client._zones_cache
        )

        # Initial record get fetches and caches
        reset()
        record_retrieve_mock.side_effect = ['baz']
        self.assertEqual(
            'baz', client.records_retrieve('unit.tests', 'a.unit.tests', 'A')
        )
        record_retrieve_mock.assert_has_calls(
            [call('unit.tests', 'a.unit.tests', 'A')]
        )
        self.assertEqual(
            {'unit.tests': {'a.unit.tests': {'A': 'baz'}}},
            client._records_cache,
        )

        # Subsequent record get does not fetch and returns from cache
        reset()
        self.assertEqual(
            'baz', client.records_retrieve('unit.tests', 'a.unit.tests', 'A')
        )
        record_retrieve_mock.assert_not_called()

        # Record create stores in cache
        reset()
        record_create_mock.side_effect = ['boo']
        self.assertEqual(
            'boo',
            client.records_create(
                'unit.tests', 'aaaa.unit.tests', 'AAAA', key='val'
            ),
        )
        record_create_mock.assert_has_calls(
            [call('unit.tests', 'aaaa.unit.tests', 'AAAA', key='val')]
        )
        self.assertEqual(
            {
                'unit.tests': {
                    'a.unit.tests': {'A': 'baz'},
                    'aaaa.unit.tests': {'AAAA': 'boo'},
                }
            },
            client._records_cache,
        )

        # Record delete removes from cache and removes zone
        reset()
        record_delete_mock.side_effect = [{}]
        self.assertEqual(
            {}, client.records_delete('unit.tests', 'aaaa.unit.tests', 'AAAA')
        )
        record_delete_mock.assert_has_calls(
            [call('unit.tests', 'aaaa.unit.tests', 'AAAA')]
        )
        self.assertEqual(
            {
                'unit.tests': {
                    'a.unit.tests': {'A': 'baz'},
                    'aaaa.unit.tests': {},
                }
            },
            client._records_cache,
        )
        self.assertEqual({'sub.unit.tests': 'bar'}, client._zones_cache)

        # Delete the other record, no zone this time, record should still go
        # away
        reset()
        record_delete_mock.side_effect = [{}]
        self.assertEqual(
            {}, client.records_delete('unit.tests', 'a.unit.tests', 'A')
        )
        record_delete_mock.assert_has_calls(
            [call('unit.tests', 'a.unit.tests', 'A')]
        )
        self.assertEqual(
            {'unit.tests': {'a.unit.tests': {}, 'aaaa.unit.tests': {}}},
            client._records_cache,
        )
        self.assertEqual({'sub.unit.tests': 'bar'}, client._zones_cache)

        # Record update removes zone and caches result
        record_update_mock.side_effect = ['done']
        self.assertEqual(
            'done',
            client.records_update(
                'sub.unit.tests', 'aaaa.sub.unit.tests', 'AAAA', key='val'
            ),
        )
        record_update_mock.assert_has_calls(
            [call('sub.unit.tests', 'aaaa.sub.unit.tests', 'AAAA', key='val')]
        )
        self.assertEqual(
            {
                'unit.tests': {'a.unit.tests': {}, 'aaaa.unit.tests': {}},
                'sub.unit.tests': {'aaaa.sub.unit.tests': {'AAAA': 'done'}},
            },
            client._records_cache,
        )
        self.assertEqual({}, client._zones_cache)

    def test_parse_rule_geos_special_cases(self):
        provider = Ns1Provider('test', 'api-key')

        notes = {}

        meta = {'country': ('TL',)}
        geos = provider._parse_rule_geos(meta, notes)
        self.assertEqual({'AS-TL'}, geos)

        meta = {'country': ('SX',)}
        geos = provider._parse_rule_geos(meta, notes)
        self.assertEqual({'NA-SX'}, geos)

        meta = {'country': ('PN', 'UM')}
        geos = provider._parse_rule_geos(meta, notes)
        self.assertEqual({'OC-PN', 'OC-UM'}, geos)

    @patch('ns1.rest.zones.Zones.list')
    def test_zones_list(self, mock):
        data = [
            {'a': 42, 'zone': 'other.net'},
            {'other': 'stuff', 'zone': 'first.com'},
        ]
        mock.side_effect = [data, data]

        provider = Ns1Provider('test', 'api-key')

        self.assertEqual(data, provider._client.zones_list())
        self.assertEqual(['first.com.', 'other.net.'], provider.list_zones())
