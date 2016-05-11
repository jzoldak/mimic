from __future__ import absolute_import, division, unicode_literals

import sys

from zope.interface import implementer

from twisted.internet.task import Clock
from twisted.trial.unittest import SynchronousTestCase
from twisted.plugin import IPlugin
from twisted.python.filepath import FilePath
from twisted.web.resource import IResource

from mimic.core import MimicCore
from mimic.plugins import (nova_plugin, loadbalancer_plugin, swift_plugin,
                           queue_plugin, maas_plugin, rackconnect_v3_plugin,
                           glance_plugin, cloudfeeds_plugin, heat_plugin,
                           neutron_plugin, dns_plugin, cinder_plugin)
from mimic.test.dummy import (
    ExampleAPI,
    ExampleEndPointTemplate,
    make_example_external_api
)
from mimic.test.fixtures import APIMockHelper


class CoreBuildingPluginsTests(SynchronousTestCase):
    """
    Tests for creating a :class:`MimicCore` object with plugins
    """
    def test_no_uuids_if_no_plugins(self):
        """
        If there are no plugins provided to :class:`MimicCore`, there are no
        uri prefixes or entries for the tenant.
        """
        core = MimicCore(Clock(), [])
        self.assertEqual(0, len(core._uuid_to_api_internal))
        self.assertEqual(0, len(core._uuid_to_api_external))
        self.assertEqual([], list(core.entries_for_tenant('any_tenant', {},
                                                          'http://mimic')))

    def test_from_plugin_includes_all_plugins(self):
        """
        Using the :func:`MimicRoot.fromPlugin` creator for a
        :class:`MimicCore`, the nova and loadbalancer plugins are included.
        """
        core = MimicCore.fromPlugins(Clock())
        plugin_apis = set((
            glance_plugin.glance,
            heat_plugin.heat,
            loadbalancer_plugin.loadbalancer,
            loadbalancer_plugin.loadbalancer_control,
            maas_plugin.maas,
            maas_plugin.maas_control,
            nova_plugin.nova,
            nova_plugin.nova_control_api,
            queue_plugin.queue,
            rackconnect_v3_plugin.rackconnect,
            swift_plugin.swift,
            cloudfeeds_plugin.cloudfeeds,
            cloudfeeds_plugin.cloudfeeds_control,
            neutron_plugin.neutron,
            dns_plugin.dns,
            cinder_plugin.cinder
        ))
        # all plugsin should be on the internal listing
        self.assertEqual(
            plugin_apis,
            set(core._uuid_to_api_internal.values()))
        # the external listing should still be empty
        self.assertEqual(
            set([]),
            set(core._uuid_to_api_external.values()))
        self.assertEqual(
            len(plugin_apis),
            len(list(core.entries_for_tenant('any_tenant', {},
                                             'http://mimic'))))

    def test_load_domain_plugin_includes_all_domain_plugins(self):
        """
        Using the :func:`MimicRoot.fromPlugin` creator for a
        :class:`MimicCore`, domain mocks implementing `class`:`IAPIDomainMock`
        are included.
        """
        self.root = FilePath(self.mktemp())
        self.root.createDirectory()
        plugin = b"""from mimic.test.dummy import ExampleDomainAPI
dummy_domain_plugin = ExampleDomainAPI()
"""
        self.root.child('fake_plugin.py').setContent(plugin)

        import mimic.plugins
        mimic.plugins.__path__.append(self.root.path)
        from mimic.plugins import fake_plugin

        def cleanup():
            sys.modules.pop("mimic.plugins.fake_plugin")
            del mimic.plugins.fake_plugin
        self.addCleanup(cleanup)

        core = MimicCore.fromPlugins(Clock())
        self.assertIn(
            fake_plugin.dummy_domain_plugin,
            core.domains
        )


class CoreApiBuildingTests(SynchronousTestCase):
    """
    Tests for creating a :class:`MimicCore` object with apis
    """
    def setUp(self):
        self.eeapi_name = u"externalServiceName"

    def test_load_external_api(self):
        """
        Validate loading a valid external API object
        """
        eeapi = make_example_external_api(
            name=self.eeapi_name,
            set_enabled=True
        )
        self.assertIsNotNone(eeapi)
        APIMockHelper(self, [eeapi])

    def test_load_internal_api(self):
        """
        Validate loading a valid internal API object
        """
        APIMockHelper(self, [ExampleAPI()])

    def test_load_invalid_api(self):
        """
        Using a dummy interface that implements :obj:`IPlugin`,
        try to add an object that does not implement either
        :obj:`IAPIMock` or :obj:`IExternalAPIMock`.
        """
        @implementer(IPlugin)
        class brokenApiMock(object):
            pass

        with self.assertRaises(TypeError):
            MimicCore(Clock(), [brokenApiMock()])

    def test_get_external_api(self):
        """
        Validate retrieving an external API
        """
        eeapi = make_example_external_api(
            name=self.eeapi_name,
            set_enabled=True
        )

        core = MimicCore(Clock(), [eeapi])
        api_from_core = core.get_external_api(
            self.eeapi_name
        )
        self.assertEqual(eeapi, api_from_core)

    def test_get_external_api_invalid(self):
        """
        Validate retrieving a non-existent external API
        which should raise an IndexError exception
        """
        core = MimicCore(Clock(), [])
        with self.assertRaises(IndexError):
            core.get_external_api(self.eeapi_name)

    def test_service_with_region_external(self):
        """
        Validate that an external service does not
        provide an internal service resource
        """
        eeapi = make_example_external_api(
            name=self.eeapi_name,
            set_enabled=True
        )
        self.assertIsNotNone(eeapi)
        helper = APIMockHelper(self, [eeapi])
        core = helper.core

        self.assertIsNone(
            core.service_with_region(
                u"EXTERNAL",
                u"some-region-name",
                u"http://some/random/prefix"
            )
        )

    def test_service_with_region_internal(self):
        """
        Validate that an external service does not
        provide an internal service resource
        """
        iapi = ExampleAPI()
        self.assertIsNotNone(iapi)
        helper = APIMockHelper(self, [iapi])
        core = helper.core

        service_id = None
        for a_service_id in core._uuid_to_api_internal:
            if core._uuid_to_api_internal[a_service_id] == iapi:
                service_id = a_service_id

        resource = core.service_with_region(
            u"ORD",
            service_id,
            u"http://some/random/prefix"
        )
        self.assertTrue(
            IResource.providedBy(resource)
        )

    def test_uri_for_service(self):
        """
        Validate that the URI returned by uri_for_service
        returns the appropriate base URI
        """
        iapi = ExampleAPI()
        self.assertIsNotNone(iapi)
        helper = APIMockHelper(self, [iapi])
        core = helper.core

        service_id = None
        for a_service_id in core._uuid_to_api_internal:
            if core._uuid_to_api_internal[a_service_id] == iapi:
                service_id = a_service_id

        base_uri = "http://some/random/prefix"

        uri = core.uri_for_service(
            u"ORD",
            service_id,
            base_uri
        )
        self.assertTrue(
            uri.startswith(base_uri + '/')
        )

    def test_entries_for_tenant_external(self):
        """
        """
        eeapi = make_example_external_api(
            name=self.eeapi_name,
            set_enabled=True
        )

        core = MimicCore(Clock(), [eeapi])

        prefix_map = {}
        base_uri = "http://some/random/prefix"
        catalog_entries = [
            entry
            for entry in core.entries_for_tenant(
                'some-tenant',
                prefix_map,
                base_uri
            )
        ]

        self.assertEqual(len(catalog_entries), 1)

    def test_entries_for_tenant_internal(self):
        """
        """
        core = MimicCore(Clock(), [ExampleAPI()])

        prefix_map = {}
        base_uri = "http://some/random/prefix"
        catalog_entries = [
            entry
            for entry in core.entries_for_tenant(
                'some-tenant',
                prefix_map,
                base_uri
            )
        ]

        self.assertEqual(len(catalog_entries), 1)

    def test_entries_for_tenant_combined(self):
        """
        """
        eeapi = make_example_external_api(
            name=self.eeapi_name,
            set_enabled=True
        )

        core = MimicCore(Clock(), [eeapi, ExampleAPI()])

        prefix_map = {}
        base_uri = "http://some/random/prefix"
        catalog_entries = [
            entry
            for entry in core.entries_for_tenant(
                'some-tenant',
                prefix_map,
                base_uri
            )
        ]

        self.assertEqual(len(catalog_entries), 2)

    def test_entries_for_tenant_external_invalid(self):
        """
        """
        eeapi = make_example_external_api(
            name=self.eeapi_name,
            set_enabled=True
        )
        eeapi2_name = "alternate-external-api"
        eeapi2_template_id = u"uuid-alternate-endpoint-template"
        eeapi2_template = ExampleEndPointTemplate(
            name=eeapi2_name,
            uuid=eeapi2_template_id,
            region=u"NEW_REGION",
            url=u"https://api.new_region.example.com:9090"
        )
        eeapi2 = make_example_external_api(
            name=eeapi2_name,
            endpoint_templates=[eeapi2_template],
            set_enabled=True
        )

        core = MimicCore(Clock(), [eeapi, eeapi2, ExampleAPI()])

        prefix_map = {}
        base_uri = "http://some/random/prefix"
        catalog_entries = [
            entry
            for entry in core.entries_for_tenant(
                'some-tenant',
                prefix_map,
                base_uri
            )
        ]

        self.assertEqual(len(catalog_entries), 3)
