##############################################################################
#
# Copyright (C) Zenoss, Inc. 2017-2019, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""API interfaces and implementations module."""

# stdlib Imports
import datetime
import collections
import operator
import time
import os
import re
import subprocess
import sys
import json
import logging
from itertools import imap
from BTrees.OOBTree import OOBTree

log = logging.getLogger('zen.gcp.api')

# Zope imports.
from zope.interface import implements
from zope.event import notify
from zope.component import getMultiAdapter
from ZODB.transact import transact

# Zenoss imports.
from Products import Zuul
from Products.ZenModel.ZenossSecurity import ZEN_MANAGE_DMD
from Products.ZenUtils.Ext import DirectRouter, DirectResponse
from Products.Zuul import getFacade
from Products.Zuul.interfaces import IFacade, IInfo
from Products.Zuul.facades import ZuulFacade
from Products.Zuul.utils import ZuulMessageFactory as _t
from Products.Zuul.catalog.events import IndexingEvent
from Products.ZenUtils.Utils import zenPath, prepId
from Products.ZenEvents.EventManagerBase import EventManagerBase
from Products.Zuul.tree import SearchResults
from zExceptions import NotFound

# ZenPack imports.
from ZenPacks.zenoss import __name__ as ZENPACK_NAME
from ZenPacks.zenoss.GoogleCloudPlatform.utils import (
    chunks,
    valid_project_id,
    valid_email_address,
    valid_private_key,
)
from ZenPacks.zenoss.GoogleCloudPlatform.labels import (
    get_labels_for_device,
    search_gcp_labels,
    create_component_group,
    remove_component_groups,
    label_graph_title
)
from ZenPacks.zenoss.GoogleCloudPlatform.LabelFilter import LabelFilter

from Products.Zuul.interfaces import IMetricServiceGraphDefinition
from Products.Zuul.infos.metricserver import \
    MultiContextMetricServiceGraphDefinition

TAG_TITLE_LENGTH4x = 18
# Default exports.
__all__ = [
    'AddGoogleCloudPlatformEndpointError',
    'IGoogleCloudPlatformFacade',
    'GoogleCloudPlatformFacade',
    'GoogleCloudPlatformRouter'
]

# Constants.
DEVICE_PATH = '/GoogleCloudPlatform'


class LabelsMultiGraph(MultiContextMetricServiceGraphDefinition):
    def __init__(self, graph, context, title):
        super(LabelsMultiGraph, self).__init__(graph, context)
        self._title = title

    @property
    def contextTitle(self):
        return self._title

class AddGoogleCloudPlatformEndpointError(Exception):
    """Error adding a GoogleCloudPlatform endpoint."""


class IGoogleCloudPlatformFacade(IFacade):
    """GoogleCloudPlatform Python API interface."""

    def addGoogleCloudPlatformEndpoint(
            self, device_name, project_id, client_email, private_key,
            guest_use_external_ip, collector='localhost'):
        """Return a GoogleCloudPlatform endpoint creation JobRecord."""

    def getGcpServices(self, uid=None):
        """Return GoogleCloudPlatform services."""

    def getGcpTypes(self, service, uid=None):
        """Return GoogleCloudPlatform types."""

    def get_service_billing_overview_data(self, uid=None):
        '''
        Generate billing overview data.
        '''

    def get_region_billing_overview_data(self, uid=None):
        '''
        Generate billing overview data.
        '''

    def get_billing_overview_data(self, uid=None):
        '''
        Generate billing overview data.
        '''
    def getGCPLabelNames(self, uid, query=''):
        '''
        Returns list of available GCP labels
        '''

    def getGCPLabelFilters(self, uid, query=''):
        '''
        Returns list of GCP label filters
        '''

    def addGCPLabelFilter(self, uid, label, expression, link_with_group=False):
        '''
        Adds new GCP Label Filter to UI
        '''

    def getGCPLabelFilterComponents(
            self, uid=None, types=(), meta_type=(),
            start=0, limit=None, sort='name', dir='ASC',
            name=None, keys=()):
        '''
        Retrieves GCP components filtered by given GCP Label Filter
        '''

    def getExpensesGraphDefs(self, uid, drange=None):
        '''
        Returns graphs for Expenses Analysis page
        '''

    def addGoogleCloudPlatformLabelToCharts(self, uid, label_id, graph_id):
        '''
        Adds GoogleCloudPlatform label charts to Expenses Graphs page
        '''

    def removeGoogleCloudPlatformLabelFromCharts(self, uid, label_id, graph_id):
        '''
        Removes GoogleCloudPlatform label charts from Expenses Graphs page
        '''


class GoogleCloudPlatformFacade(ZuulFacade):
    """GoogleCloudPlatform Python API implementation."""

    implements(IGoogleCloudPlatformFacade)

    def addGoogleCloudPlatformEndpoint(
            self, device_name, project_id, client_email, private_key,
            guest_use_external_ip, collector='localhost'):
        """Return a GoogleCloudPlatform endpoint creation JobRecord.

        :param device_name: Device name
        :type device_name: str
        :param project_id: Project ID
        :type project_id: str
        :param client_email: Client Email Address
        :type client_email: str
        :param private_key: Private Key
        :type private_key: str
        :param guest_use_external_ip: Use an external IP
        :type guest_use_external_ip: bool

        :param collector: Name of the endpoint's collector
        :type collector: str
        :param model: Whether to model the endpoint
        :type model: bool

        :returns: Job info object
        :rtype: Products.Zuul.infos.jobs.JobInfo

        :raises: AddGoogleCloudPlatformEndpointError

        """
        devices = self._dmd.getDmdRoot('Devices')
        try:
            deviceClass = devices.getOrganizer(DEVICE_PATH)
        except KeyError:
            raise AddGoogleCloudPlatformEndpointError(
                _t('%s device class is missing. Reinstall %s.' % (
                    DEVICE_PATH, ZENPACK_NAME)))

        if not Zuul.checkPermission(ZEN_MANAGE_DMD, deviceClass):
            raise AddGoogleCloudPlatformEndpointError(
                _t("You don't have permission to add a GCP endpoint."))

        # Verify that this device does not already exist.
        deviceRoot = self._dmd.getDmdRoot("Devices")
        device = deviceRoot.findDeviceByIdExact(device_name)
        if device:
            return False, _t("A device named %s already exists." % device_name)

        if not collector:
            raise AddGoogleCloudPlatformEndpointError(
                _t("Collector must be the name of a collector."))

        zProperties = {
            'zGoogleCloudPlatformProjectId': project_id,
            'zGoogleCloudPlatformClientEmail': client_email,
            'zGoogleCloudPlatformPrivateKey': private_key,
            'zGoogleCloudPlatformGuestUseExternalIP': guest_use_external_ip,
        }

        if not project_id:
            return False, _t("Project ID must be specified.")

        if not valid_project_id(project_id):
            return False, _t("{!r} is not a valid project ID.".format(project_id))

        if not client_email:
            return False, _t("Client email address must be specified.")

        if not valid_email_address(client_email):
            return False, _t("{!r} is not a valid client email address".format(client_email))

        if not private_key:
            return False, _t("Private key must be specified.")

        if not valid_private_key(private_key):
            return False, _t("Invalid private key.")

        @transact
        def create_device():
            dc = self._dmd.Devices.getOrganizer(DEVICE_PATH)

            device = dc.createInstance(device_name)
            device.setPerformanceMonitor(collector)

            for prop, val in zProperties.items():
                device.setZenProperty(prop, val)

            device.index_object()
            notify(IndexingEvent(device))

        # This must be committed before the following model can be
        # scheduled.
        create_device()
        # Schedule a modeling job for the new device.

        device = deviceRoot.findDeviceByIdExact(device_name)
        device.collectDevice(setlog=False, background=True)

        return True, 'Device addition scheduled'

    def get_service_billing_overview_data(self, uid=None):
        """
        Returns JSON data for billing charts on device overview page
        """
        device = self._getObject(uid)
        serviceList = []
        total = 0
        unlistedCost = 0
        if not device.getRRDTemplateByName('EstimatedCharges'):
            return []
        for datasource in device.getRRDTemplateByName('EstimatedCharges').datasources():
            if datasource.sourcetype == 'Google Cloud Platform Billing Monitoring' and datasource.service is not None:
                serviceDict = {"service": datasource.service, "cost": getRRD(datasource.id, device)}
                if serviceDict['cost'] > 0:
                    serviceList.append(serviceDict)
                    if datasource.service == 'Total':
                        total = serviceDict['cost']
                    else:
                        unlistedCost += serviceDict['cost']

        if serviceList:
            serviceList.sort(key=lambda x: x["cost"], reverse=True)
            serviceList = serviceList[:10]
            serviceList.append({"service": "Other", "cost": round(total - unlistedCost, 2)})
            serviceList.sort(key=lambda x: x["cost"], reverse=True)

        return serviceList

    def get_region_billing_overview_data(self, uid=None):
        """
        Returns JSON data for billing charts on device overview page
        """
        device = self._getObject(uid)
        regionList = []
        total = 0
        unlistedCost = 0
        if not device.getRRDTemplateByName('EstimatedCharges'):
            return []
        for datasource in device.getRRDTemplateByName('EstimatedCharges').datasources():
            if datasource.sourcetype == 'Google Cloud Platform Billing Monitoring' and datasource.region is not None:
                regionDict = {"region": datasource.region, "cost": getRRD(datasource.id, device)}
                if regionDict['cost'] > 0:
                    regionList.append(regionDict)
                    if datasource.region == 'Total':
                        total = regionDict['cost']
                    else:
                        unlistedCost += regionDict['cost']
        if regionList:
            regionList.sort(key=lambda x: x["cost"], reverse=True)
            regionList = regionList[:10]
            regionList.append({"region": "Other", "cost": round(total - unlistedCost, 2)})
            regionList.sort(key=lambda x: x["cost"], reverse=True)

        return regionList

    def get_billing_overview_data(self, uid=None):
        """
        Returns JSON data for billing charts on device overview page
        """

        device = self._getObject(uid)
        month = datetime.datetime.now().strftime("%B")

        day = datetime.date.today().day
        amount = getRRD("TotalCharges", device) or 0
        threshold = device.zGoogleCloudPlatformBillingCostThreshold or 0

        predicted = (amount / day) * 30

        res = {
            "amount": amount,
            "predicted": predicted,
            "threshold": threshold,
            "amount": amount,
            "month": month,
        }
        return res

    def getRegions(self, uid):
        """Return list of regions."""
        return [x.gce_name for x in self._getObject(uid).regions()]

    def getProjectQuotasData(self, uid):
        """Return data for "Project Quotas" chart."""
        project = self._getObject(uid)
        quotas = project.quotas()
        metric_by_key = {x.getResourceKey(): x.metric for x in quotas}

        last_samples = get_last_samples(
            contexts=quotas,
            metricNames=["quota_limit", "quota_usage", "quota_usagePercent"])

        return [{
            "quota": get_metric_label(metric_by_key[k]),
            "limit": v["quota_limit"],
            "usage": v["quota_usage"],
            "utilization": v["quota_usagePercent"],
            } for k, v in last_samples.iteritems() if v["quota_usage"]]

    def getRegionsQuotasData(self, uid):
        """Return data for "Region Quotas" chart."""
        project = self._getObject(uid)

        all_quotas = []
        quotas_by_metric = collections.defaultdict(list)

        for region in project.regions():
            quotas = region.quotas()
            all_quotas.extend(quotas)
            for quota in quotas:
                quotas_by_metric[quota.metric].append(quota)

        last_samples = get_last_samples(
            contexts=all_quotas,
            metricNames=["quota_limit", "quota_usage", "quota_usagePercent"])

        data = []

        for metric, quotas in quotas_by_metric.iteritems():
            row = {"quota": get_metric_label(metric)}

            max_utilization = 0.0
            for quota in quotas:
                quota_samples = last_samples[quota.getResourceKey()]
                limit = quota_samples["quota_limit"]
                usage = quota_samples["quota_usage"]
                utilization = quota_samples["quota_usagePercent"]

                if utilization is not None:
                    max_utilization = max(utilization, max_utilization)

                region = quota.container().gce_name

                row.update({
                    region: utilization,
                    "{}:limit".format(region): limit,
                    "{}:usage".format(region): usage})

            if max_utilization > 0.0:
                row["max-utilization"] = max_utilization
                data.append(row)

        return data

    def getGcpServices(self, uid=None):
        if not uid:
            return {}
        device = self._getObject(uid)
        client_email = device.zGoogleCloudPlatformClientEmail
        private_key = device.zGoogleCloudPlatformPrivateKey
        project = device.zGoogleCloudPlatformProjectId
        if not client_email or not private_key:
            raise Exception("No valid credentials provided.")
        cmd = [
            sys.executable,
            os.path.join(os.path.dirname(__file__), 'apihelpers', 'gcp_queryservices.py'),
            "--client_email=%s" % client_email,
            "'--private_key=%s'" % private_key,
            "--project=%s" % project,
            ]
        # On RM 4.2.5, run the command locally.
        # On 5+, run the command on the appropriate collector via zminion.
        if os.path.exists(zenPath("bin", "zminion")):
            cmd = ['zminion',
                   '--minion-name', 'zminion_%s' % device.getPerformanceServer().id,
                   'run', '--'] + cmd

        p = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        (stdout, stderr) = p.communicate()
        if stderr:
            err = "\n".join([x for x in stderr.split("\n") if "zminion-return" not in x])
            if err and 'CryptographyDeprecationWarning' not in err:
                raise Exception(err)

        results = json.loads(stdout)
        if results['error']:
            raise Exception(results['error'])
        return results['success']

    def getGcpTypes(self, service, uid=None):
        if not uid:
            return {}
        device = self._getObject(uid)
        client_email = device.zGoogleCloudPlatformClientEmail
        private_key = device.zGoogleCloudPlatformPrivateKey
        project = device.zGoogleCloudPlatformProjectId
        if not client_email or not private_key:
            raise Exception("No valid credentials provided.")
        cmd = [
            sys.executable,
            os.path.join(os.path.dirname(__file__), 'apihelpers', 'gcp_querytypes.py'),
            "--client_email=%s" % client_email,
            "'--private_key=%s'" % private_key,
            '''"--filter_=project="%s" AND metric.type=starts_with(\\"%s/\\")"''' % (project, service),
            "--project=%s" % project,
            ]
        # On RM 4.2.5, run the command locally.
        # On 5+, run the command on the appropriate collector via zminion.
        if os.path.exists(zenPath("bin", "zminion")):
            cmd = ['zminion',
                   '--minion-name', 'zminion_%s' % device.getPerformanceServer().id,
                   'run', '--'] + cmd

        p = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        (stdout, stderr) = p.communicate()
        if stderr:
            err = "\n".join([x for x in stderr.split("\n") if "zminion-return" not in x])
            if err and 'CryptographyDeprecationWarning' not in err:
                raise Exception(err)
        results = json.loads(stdout)
        if results['error']:
            raise Exception(results['error'])
        return results['success']

    def getGCPLabelNames(self, uid, query=''):
        '''
        Returns list of available GCP labels
        '''
        device = self._getObject(uid)
        data = []

        for label in get_labels_for_device(device):
            data.append({'name': label, 'value': label})

        data.sort(key=lambda x: x['name'])
        return data

    def getGCPLabelFilters(self, uid, query=''):
        '''
        Returns list of GCP label filters
        '''
        device = self._getObject(uid)
        if not device.label_filters.countObjects():
            return []

        zep = getFacade('zep')
        res = []
        for label_filter in device.label_filters():
            brains = search_gcp_labels(device, label_filter.expression)
            uuids = []
            for brain in brains:
                try:
                    uuids.append(brain.getObject().getUUID())
                except (NotFound, KeyError, AttributeError):
                    # thats ok, index probably outdated
                    pass
            severity = EventManagerBase.severities.get(
                max(zep.getWorstSeverity(uuids).values() or [0]), 0).lower()

            label = {
                "uid": '/'.join(label_filter.getPrimaryPath()),
                "label": label_filter.title,
                "expression": label_filter.expression,
                "count": len(uuids),
                "severity": severity
            }
            res.append(label)

        res.sort(key=lambda x: x['label'])
        return res

    def addGCPLabelFilter(self, uid, label, expression, link_with_group=False):
        '''
        Adds new GCP Label Filter to UI
        '''
        device = self._getObject(uid)

        checkFilter = re.compile(r'[^a-zA-Z0-9-=_,.$\(\) ]')
        if checkFilter.search(label):
            return False, _t("%s is not a valid name" % label)

        label_filter_id = prepId(label)
        label_filter_id = device.getUnusedId('label_filters', label_filter_id)
        if label != label_filter_id:
            return False, _t("%s is already created" % label)

        if link_with_group:
            try:
                group = device.dmd.getObjByPath(
                    '/'.join(['ComponentGroups', "GoogleCloudPlatform", device.id])
                )
                if group.hasObject(label_filter_id):
                    return False, _t("%s already exists in Component Groups" % label)
            except KeyError:
                # if we are creating GCP Labels Filter first time
                # and GCP Component group doesn't exist yet.
                pass

        label_filter = LabelFilter(label_filter_id)
        label_filter.title = label
        label_filter.expression = expression
        label_filter.link_with_group = link_with_group

        device.label_filters._setObject(label_filter.id, label_filter)
        label_filter = device.label_filters._getOb(label_filter.id)
        label_filter.index_object()
        notify(IndexingEvent(label_filter))

        res = True
        if link_with_group:
            res = create_component_group(device, label, expression)

        return res, None

    def getGCPLabelFilterComponents(
            self, uid=None, types=(), meta_type=(),
            start=0, limit=None, sort='name', dir='ASC',
            name=None, keys=()):
        '''
        Retrieves GCP components filtered by given GCP Label Filter for component grid

        :param uid: Device uid
        :type uid: str
        :param types: component Type
        :type types: str
        :param meta_type: component meta_type
        :type meta_type: str
        :param start: start of results
        :type start: int
        :param limit: end of results
        :type limit: int
        :param sort: Sort by field
        :type sort: str
        :param dir: asc or desc
        :type dir : str
        :param name: component name
        :type name : str
        :param keys: component gird columns
        :type list : list

        '''
        reverse = dir=='DESC'
        query = name.lower() if name else None

        device_uid, expression = uid.split("#", 1)
        if not expression.strip():
            return SearchResults(iter([]), 0, "0", False)

        device = self._getObject(device_uid)
        res = []
        for brain in search_gcp_labels(device, expression):
            try:
                obj = brain.getObject()
            except (NotFound, KeyError, AttributeError):
                # thats ok, index probably outdated
                continue
            keep = True
            if query is not None:
                keep = False
                for key in keys:
                    # non searchable fields
                    if key in ('uid', 'uuid', 'events', 'status', 'severity'):
                        continue
                    val = getattr(obj, key, None)
                    if not val:
                        continue
                    if callable(val):
                        val = val()
                    if query in str(val).lower():
                        keep = True
                        break
            if keep:
                res.append(obj)

        comps = map(IInfo, res)
        total = len(comps)
        hash_ = str(total)

        # sort the components
        sortedResults = list(sorted(comps, \
            key=lambda x: getattr(x, sort), reverse=reverse))

        # limit the search results to the specified range
        if limit is None:
            pagedResult = sortedResults[start:]
        else:
            pagedResult = sortedResults[start:start + limit]

        return SearchResults(iter(pagedResult), total, hash_, False)

    def getExpensesGraphDefs(self, uid, drange=None):
        '''
        Returns graphs for Expenses Analysis page
        '''
        obj = self._getObject(uid)
        graphs = []
        template = obj.getRRDTemplateByName("EstimatedCharges")
        if template:
            for g in template.getGraphDefs():
                graph = getMultiAdapter((g, obj), IMetricServiceGraphDefinition)
                graphs.append(graph)

        if not obj.labels_graphs:
            return graphs

        all_labels = obj.label_filters()
        if not all_labels:
            return graphs
        all_graphs = [g for t in all_labels[0].getRRDTemplates() \
            for g in t.getGraphDefs()]

        for label_keys, graph_keys in obj.labels_graphs.iteritems():
            for g in all_graphs:
                if g.id not in graph_keys:
                    continue

                # Special case - graph with all labels, existing and future
                if set(label_keys) == set(["all"]):
                    labels_for_graph = all_labels
                    labels_ids = "all"
                    labels_title = "All Label Filters"
                else:
                    labels_for_graph = [t for t in all_labels if t.id in label_keys]
                    labels_ids = ", ".join([x.id for x in labels_for_graph])
                    labels_title = ", ".join([x.name() for x in labels_for_graph])

                if labels_for_graph:
                    graph = LabelsMultiGraph(
                        graph=g,
                        context=labels_for_graph,
                        title=label_graph_title(labels_ids, g.id, labels_title)
                    )
                    graph._showContextTitle = True
                    graphs.append(graph)
        return graphs

    def addGoogleCloudPlatformLabelToCharts(self, uid, label_id, graph_id):
        '''
        Adds GoogleCloudPlatform label charts to Expenses Graphs page
        '''
        obj = self._getObject(uid)
        if not obj.labels_graphs:
            obj.labels_graphs = OOBTree()

        key = tuple(label_id)
        if not key in obj.labels_graphs:
            obj.labels_graphs[key] = OOBTree()

        obj.labels_graphs[key][graph_id] = graph_id

        return True

    def removeGoogleCloudPlatformLabelFromCharts(self, uid, label_id, graph_id):
        '''
        Removes GoogleCloudPlatform label charts from Expenses Graphs page
        '''
        obj = self._getObject(uid)
        if obj.labels_graphs:
            ids = tuple(label_id.split(', '))
            if ids in obj.labels_graphs:
                obj.labels_graphs[ids].pop(graph_id, None)
        return True

class GoogleCloudPlatformRouter(DirectRouter):
    """ExtJS DirectRouter API endpoint."""

    def _getFacade(self):
        return Zuul.getFacade('googlecloudplatform', self.context)

    def addGoogleCloudPlatformEndpoint(
            self, device_name, project_id, client_email, private_key,
            guest_use_external_ip, collector='localhost'):
        """Add a GoogleCloudPlatform project.

        :param device_name: Device Name
        :type device_name: str
        :param project_id: Project ID
        :type project_id: str
        :param client_email: Client Email Address
        :type client_email: str
        :param private_key: Private Key
        :type private_key: str
        :param collector: Name of the endpoint's collector
        :type collector: str

        :returns: Success response which contains the UUID of the create job.
        :rtype: Products.ZenUtils.extdirect.router.DirectResponse

        """
        try:
            success, message = self._getFacade().addGoogleCloudPlatformEndpoint(
                device_name, project_id, client_email, private_key,
                guest_use_external_ip, collector=collector)

        except AddGoogleCloudPlatformEndpointError as e:
            return DirectResponse.fail(e.message)

        if success:
            return DirectResponse.succeed(jobId=message)

        return DirectResponse.fail(message)

    def getRegions(self, uid):
        return DirectResponse.succeed(data=self._getFacade().getRegions(uid))

    def getGcpServices(self, uid=None, **kwargs):
        '''
        Returns dict of available GCP Services
        '''
        service = self._getFacade().getGcpServices(uid)
        return DirectResponse(success=True, data=service)

    def getGcpTypes(self, service, uid=None,  **kwargs):
        '''
        Returns dict of available GCP Services
        '''
        types = self._getFacade().getGcpTypes(service, uid)
        return DirectResponse(success=True, data=types)

    def getProjectQuotasData(self, uid, **kwargs):
        """Return data for "Project Quotas" chart."""
        return paginate(self._getFacade().getProjectQuotasData(uid), **kwargs)

    def getRegionsQuotasData(self, uid, **kwargs):
        """Return data for "Region Quotas" chart."""
        return paginate(self._getFacade().getRegionsQuotasData(uid), **kwargs)

    def get_service_billing_overview_data(self, uid,**kwargs ):
        "Returns total estimated charges for device overview page"
        data = self._getFacade().get_service_billing_overview_data(uid=uid)
        return DirectResponse(success=True, data=data)

    def get_region_billing_overview_data(self, uid,**kwargs ):
        "Returns total estimated charges for device overview page"
        data = self._getFacade().get_region_billing_overview_data(uid=uid)
        return DirectResponse(success=True, data=data)

    def get_billing_overview_data(self, uid):
        "Returns total estimated charges for device overview page"
        data = self._getFacade().get_billing_overview_data(uid=uid)
        return DirectResponse(success=True, data=data)

    def getGCPLabelNames(self, uid, query=''):
        '''
        Returns list of available GCP Labels
        '''
        data = self._getFacade().getGCPLabelNames(uid, query)
        return DirectResponse(success=True, data=data)

    def getGCPLabelFilters(self, uid, query=''):
        '''
        Returns list of GCP label filters
        '''
        data = self._getFacade().getGCPLabelFilters(uid)
        return DirectResponse(success=True, data=data)

    def removeGCPLabelFilter(self, uids, remove_groups=True):
        '''
        Removes GCP Label Filter from UI
        '''
        device_facade = Zuul.getFacade('device', self.context)
        comps = imap(device_facade._getObject, uids)
        if remove_groups:
            remove_component_groups(self.context, comps)
        device_facade.deleteComponents(uids)
        return DirectResponse.succeed()

    def addGCPLabelFilter(self, uid, label, expression, link_with_group=False):
        '''
        Adds new GCP Label Filter to UI
        '''
        success, message = self._getFacade().addGCPLabelFilter(
            uid,
            label,
            expression,
            link_with_group
        )
        if success:
            return DirectResponse.succeed()
        else:
            if message:
                return DirectResponse.fail(message)
            else:
                return DirectResponse.fail("Failed to add GCP Label")

    def getGCPLabelFilterComponents(
            self, uid=None, types=(), meta_type=(),
            start=0, limit=None, page=0, sort='name',
            dir='ASC', name=None, keys=()):
        '''
        Retrieves GCP components filtered by given GCP Label Filter
        '''
        if name:
            # Load every component if we have a filter
            limit = None

        comps = self._getFacade().getGCPLabelFilterComponents(
            uid=uid,
            meta_type=meta_type,
            start=start,
            limit=limit,
            sort=sort,
            dir=dir,
            name=name,
            keys=keys
        )
        total = comps.total
        hash = comps.hash_
        data = Zuul.marshal(comps, keys=keys)
        return DirectResponse(data=data, totalCount=total, hash=hash)

    def getExpensesGraphDefs(self, uid, drange=None):
        '''
        Returns graphs for Expenses Analysis page
        '''
        facade = self._getFacade()
        data = facade.getExpensesGraphDefs(uid, drange)
        return DirectResponse(data=Zuul.marshal(data))

    def addGoogleCloudPlatformLabelToCharts(self, uid, label_id, graph_id):
        '''
        Adds GoogleCloudPlatform label charts to Expenses Graphs page
        '''
        success = self._getFacade().addGoogleCloudPlatformLabelToCharts(uid, label_id, graph_id)
        if success:
            return DirectResponse.succeed()
        else:
            return DirectResponse.fail("Failed to add GoogleCloudPlatform Label(s) Graph")

    def removeGoogleCloudPlatformLabelFromCharts(self, uid, label_id, graph_id):
        '''
        Removes GoogleCloudPlatform label charts from Expenses Graphs page
        '''
        success = self._getFacade().removeGoogleCloudPlatformLabelFromCharts(uid, label_id, graph_id)
        if success:
            return DirectResponse.succeed()
        else:
            return DirectResponse.fail("Failed to remove GoogleCloudPlatform Label(s) Graph")

def getRRD(point, device):
    res = device.getRRDValue(point)
    if str(res) == 'nan':
        return 0
    return res

def get_metric_label(metric):
    """Return user-friendly label for a ComputeQuota.metric value.

    Converts all underscores (_) to spaces, and uppercases the first letter
    of each word.

    Also includes some special cases for acronym capitalization.

    """
    label = metric.replace("_", " ").title()

    acronyms = (
        ("Https", "HTTPS"),
        ("Http", "HTTP"),
        ("Mbps", "MB/s"),
        ("Cpu", "CPU"),
        ("Gpu", "GPU"),
        ("Ssd", "SSD"),
        ("Ssl", "SSL"),
        ("Tcp", "TCP"),
        ("Url", "URL"),
        ("Vpn", "VPN"),
        ("Gb", "GB"),
    )

    for original, replacement in acronyms:
        label = label.replace(original, replacement)

    return label


def get_last_samples(contexts, metricNames):
    """Return a dict of last collected values for metricNames.

    Example of returned dict:

        {
            "Devices/zenoss-testing-1/quotas/quota_project_backend_buckets": {
                "quota_usage": 1.0,
                "quota_limit": 10.0,
                "quota_usagePercent": 10.0,
            },
        }

    """
    now = int(time.time())

    f = getFacade("metric")
    last_samples = {
        c.getResourceKey(): {m: None for m in metricNames}
        for c in contexts}

    # MetricFacade was logging errors and providing no results when the number
    # of contexts exceeded 79. So we'll only request metrics for 50 contexts
    # at a time to be safe.
    for context_chunk in chunks(contexts, 50):
        results = f.getMetricsForContexts(
            contexts=context_chunk,
            metricNames=metricNames,
            start=now - 900,
            end=now)

        for key, data in results.iteritems():
            for dpname, samples in data.iteritems():
                if samples:
                    last_samples[key][dpname] = samples[-1].get("value")

    return last_samples


def paginate(data, **kwargs):
    """Return paginated DirectResponse for data.

    This assumes data is the complete set of data. So this function is only
    useful to provide server-side paging over complete result sets. In cases
    where it is possible to only query for partial results based on kwargs,
    that would be more efficient.

    """
    sort = kwargs.get("sort")
    sort_dir = kwargs.get("dir")
    start = kwargs.get("start")
    limit = kwargs.get("limit")

    if sort and sort_dir:
        data = sorted(
            data,
            key=operator.itemgetter(sort),
            reverse=sort_dir.lower() == "desc")

    if limit and (start is not None):
        data = data[start:start + limit]

    return DirectResponse.succeed(data=data, totalCount=len(data))
