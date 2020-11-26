##############################################################################
#
# Copyright (C) Zenoss, Inc. 2018-2019, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""Compute service modeling."""

# Default Exports
__all__ = [
    "CollectorExt",
    # "CollectorOptions",
    "process",
]

# stdlib Imports
import logging
import re

from datetime import datetime

# Twisted Imports
from twisted.internet import defer
from twisted.python.failure import Failure as TxFailure

# ZenPack Imports
from ZenPacks.zenoss.GoogleCloudPlatform.constants import (
    KIND_MAP,
    PROJECT_KINDS,
    PROJECT_GLOBAL_KINDS,
    PROJECT_AGGREGATED_KINDS,
    REGION_KINDS,
    ZONE_KINDS,
)
from ZenPacks.zenoss.GoogleCloudPlatform.modeling import validate_modeling_regex, CollectorOptions, Collector


from Products.ZenUtils.Utils import prepId

from . import txgcp
# from .mapper import DataMapper
from ZenPacks.zenoss.GoogleCloudPlatform.mapper import DataMapper
from ZenPacks.zenoss.GoogleCloudPlatform.utils import (maybe_int,
                                                       is_greater_timestamp,
                                                       find_first_shared_label,
                                                       guest_status_prodState_map,
                                                       getLabelToDeviceClassMap)
# from .zopeutils import get_id
from ZenPacks.zenoss.GoogleCloudPlatform.zopeutils import get_id
from ZenPacks.zenoss.GoogleCloudPlatform.labels import labels_list

LOG = logging.getLogger("zen.GoogleCloudPlatform")

DEFAULT_MODELED_KINDS = (
    "compute#disk",
    "compute#diskType",
    "compute#image",
    "compute#instance",
    "compute#instanceGroup",
    "compute#instanceGroupManager",
    "compute#instanceTemplate",
    "compute#machineType",
    "compute#project",
    "compute#region",
    "compute#snapshot",
    "compute#zone",
)

DEFAULT_AGGREGATED_KINDS = (
    # "compute#disk",
    # "compute#diskType",
    # "compute#instance",
    # "compute#instanceGroup",
    # "compute#machineType",
)


# Static keyword identifying the project (device) being modeled.
PROJECT_ID = "#PROJECT#"

# For unit translation.
ONE_GiB = 1073741824
ONE_MiB = 1048576

'''
def validate_modeling_regex(device, zprop):
    """ Validate zProp Regex list and return valid composite regex or None

    Params:
        device: device object
        zprop:  A zProperty string, representing a 'lines' type property

    Returns:
        A valid composite regular expression, or None
    """
    ModelZpropList = getattr(device, zprop, [])
    if not ModelZpropList:
        return None

    # Validate each regex in list
    model_list = []
    for item in ModelZpropList:
        name = item.strip()
        # Ignore line with newline and empty spaces characters
        if not name:
            continue
        try:
            re.compile(name)
            model_list.append(name)
        except Exception:
            LOG.warn('Ignoring "%s" in %s. Invalid Regular Expression.',
                     name, zprop)

    # Its possible that there were no valid regular expressions in model_list.
    if not model_list:
        return None

    regex = re.compile('(?:{})'.format('|'.join(model_list)))
    return regex
'''

'''
class CollectorOptions(object):
    def __init__(
            self,
            modeled_kinds=DEFAULT_MODELED_KINDS,
            aggregated_kinds=DEFAULT_AGGREGATED_KINDS):
        self.modeled_kinds = modeled_kinds
        self.aggregated_kinds = aggregated_kinds

    def is_kind_modeled(self, kind):
        """Return True if "kind" should be modeled."""
        return kind in self.modeled_kinds

    def get_modeled_kinds(self, source):
        """Return tuple of kinds to be modeled."""
        return tuple(x for x in source if self.is_kind_modeled(x))

    def project_kinds(self):
        """Return tuple of kinds to be modeled per project."""
        return self.get_modeled_kinds(PROJECT_KINDS)

    def project_global_kinds(self):
        """Return tuple of global kinds to be modeled per project."""
        return self.get_modeled_kinds(PROJECT_GLOBAL_KINDS)

    def project_aggregated_kinds(self):
        """Return tuple of aggregated kinds to be modeled per project."""
        return tuple(
            x
            for x in self.get_modeled_kinds(PROJECT_AGGREGATED_KINDS)
            if x in self.aggregated_kinds)

    def region_kinds(self):
        """Return tuple of kinds to be modeled per region."""
        return self.get_modeled_kinds(REGION_KINDS)

    def zone_kinds(self):
        """Return tuple of kinds to be modeled per zone."""
        return tuple(
            x
            for x in self.get_modeled_kinds(ZONE_KINDS)
            if x not in self.project_aggregated_kinds())
'''

class CollectorExt(Collector):
    def __init__(self, device, testing=False, save_responses=False):

        self.client = txgcp.ClientExt(
            client_email=device.zGoogleCloudPlatformClientEmail,
            private_key=device.zGoogleCloudPlatformPrivateKey,
            compute_maxResults=device.zGoogleCloudPlatformComputeMaxResults,
            mock_responses=testing,
            save_responses=save_responses)

        self.device = device
        self.options = CollectorOptions()
        self.operations = []
        self.results = []

    def collect(self, project_name):
        project = self.client.compute_project(project_name)

        # Get singular project details.
        self.operations.append((project.get, ()))

        '''
        # Get top-level collections without a namespace.
        self.operations.extend(
            (project.list, (KIND_MAP[x],))
            for x in self.options.project_kinds())
        '''


        self.operations.append((
            self.collect_cloudsql_instances,
            (project_name,)))


        '''
        self.operations.append((
            self.collect_subscriptions,
            (project_name,)))
        '''

        '''
        # Get top-level collections with the global namespace.
        self.operations.extend(
            (project.global_list, (KIND_MAP[x],))
            for x in self.options.project_global_kinds())

        # Get top-level collections with the aggregated namespace.
        self.operations.extend(
            (project.aggregated_list, (KIND_MAP[x],))
            for x in self.options.project_aggregated_kinds())
        '''

        '''
        # Make call to Stackdriver and get list of K8 instance_ids..
        self.operations.append((
            self.collect_kubernetes_clusters,
            (project_name,)))
        '''

        ''' 
        # Make call to GCP Functions
        self.operations.append((
            self.collect_gcp_functions,
            (project_name,)))

        self.operations.append((
            self.collect_dataflow_jobs,
            (project_name,)))

        # Validate regex for BigQuery zProperty before collecting data
        if validate_modeling_regex(
                self.device, 'zGoogleCloudPlatformBigQueryDatasetsModeled'):
            self.operations.append((
                self.collect_bigquery_datasets,
                (project_name,)))

        self.operations.append((
            self.collect_autoscalars,
            (project_name,)))

        self.operations.append((
            self.collect_buckets,
            (project_name,)))

        # Validate regex for BigTable zProperty before collecting data
        if validate_modeling_regex(
                self.device, 'zGoogleCloudPlatformBigTableInstancesModeled'):
            self.operations.append((
                self.collect_bigtable_instances,
                (project_name,)))

        # Validate regex for BigTable zProperty before collecting data
        if validate_modeling_regex(
                self.device, 'zGoogleCloudPlatformBigTableClustersModeled'):
            self.operations.append((
                self.collect_bigtable_clusters,
                (project_name,)))


        # Validate regex for BigTable zProperty before collecting data
        if validate_modeling_regex(
                self.device, 'zGoogleCloudPlatformBigTableAppProfilesModeled'):
            self.operations.append((
                self.collect_bigtable_appProfiles,
                (project_name,)))
        '''

        return self.collect_phase([], 1)

    def collect_cloudsql_instances(self, project_name):

        def handle_success(result):
            LOG.info("%s: Cloud SQL is enabled", project_name)
            return result

        def handle_failure(failure):
            error = getattr(failure, "error", None)
            message = getattr(error, "message", None)
            LOG.info("%s: Cloud SQL modeling failed", message)
            # Propagate any other failures.
            return failure

        d = self.client.cloudsql(project_name).instances()
        d.addCallback(handle_success)
        d.addErrback(handle_failure)
        return d

    def collect_cloudsql_databases(self, project_name, instance):

        def handle_success(result):
            return result

        def handle_failure(failure):
            error = getattr(failure, "error", None)
            message = getattr(error, "message", None)
            LOG.info("%s: Cloud SQL databases modeling failed", message)
            # Propagate any other failures.
            return failure

        LOG.debug('XXX collect_cloudsql_databases')

        d = self.client.cloudsql(project_name).databases(instance)
        d.addCallback(handle_success)
        d.addErrback(handle_failure)
        return d

    def collect_subscriptions(self, project_name):

        def handle_success(result):
            LOG.info("%s: Subscriptions are enabled", project_name)
            return result

        def handle_failure(failure):
            error = getattr(failure, "error", None)
            message = getattr(error, "message", None)
            LOG.info("%s: Subscriptions modeling failed", message)
            # Propagate any other failures.
            return failure

        LOG.debug('XXXXXXXXXXXXXXXXXX collect_subscriptions')

        d = self.client.subscriptions(project_name).instances()
        d.addCallback(handle_success)
        d.addErrback(handle_failure)
        return d

    '''
    def collect_phase(self, results, phase):
        total_results = len(results)
        success_results = len([x for x in results if x[0]])
        fail_results = len([x for x in results if not x[0]])

        if phase > 1:
            LOG.debug(
                "received %s responses for phase %s [success=%s, fail=%s]",
                total_results,
                phase - 1,
                success_results,
                fail_results)

        for success, result in results:
            if not success:
                LOG.debug("failure: %s", result)
                return defer.succeed(None)

        if not self.operations:
            LOG.debug("completed all phases")
            return defer.succeed(self.results)

        LOG.debug(
            "sending %s requests for phase %s",
            len(self.operations),
            phase)

        # Create deferreds out of operations in this phase.
        deferreds = [
            fn(*args).addCallback(self.handle_result)
            for fn, args in self.operations]

        # Clear operations for next phase.
        self.operations = []

        # Phase only completes when all deferreds succeed, or one fails.
        d = defer.DeferredList(
            deferreds,
            consumeErrors=True,
            fireOnOneErrback=True).addCallback(
                self.collect_phase,
                phase + 1)

        d.addErrback(self.handle_failure)

        return d
    '''
    '''
    def handle_failure(self, failure):
        # Unwrap "FirstError" from DeferredList failure.
        if isinstance(failure, TxFailure):
            if isinstance(failure.value, defer.FirstError):
                return failure.value.subFailure

        return failure
    '''

    def handle_result(self, result):
        """Dispatch result to appropriate handle_* method."""

        if not result:
            return {}
        self.results.append(result)

        kind = result.get("kind")
        handle_fn = None
        if kind:
            compute_kind = kind.split("#", 1)[-1]
            handle_fn = getattr(self, "handle_{}".format(compute_kind), None)

        elif result.get('instances'):
            handle_fn = getattr(self, "handle_bigTableInstance", None)
        elif result.get('items') and result.get('items')[0].get('kind') == 'sql#instance':
            handle_fn = getattr(self, "handle_cloudSQLInstances", None)

        if handle_fn is not None:
            handle_fn(result)
        else:
            LOG.debug("No custom handler method found, skipping.")
        return result

    def handle_cloudSQLInstances(self, result):

        LOG.debug('XXX handle_cloudSQLInstances')
        # project_name = result.get('instances')[0].get("name").split("/")[1]
        model_regex = ".*"
        '''
        model_regex = validate_modeling_regex(
            self.device, 'zGoogleCloudPlatformBigTableInstancesModeled')

        if not model_regex:
            return
        '''
        for item in result.get('items', []):
            project_name = item['project']
            name = item['name']
            if not re.match(model_regex, name):
                continue
            self.operations.append((self.collect_cloudsql_databases, (project_name, name)))


def process(device, results, plugin_name):
    mapper = DataMapper(plugin_name)

    for result in results:

        # GCE results will have a "kind" key.
        if "kind" in result:


            LOG.debug ('XXX process : kind')

            map_fn_name = "map_{}".format(
                result["kind"].split('#', 1)[-1])
            map_fn = globals().get(map_fn_name)
            if not map_fn:
                raise Exception("no {} function".format(map_fn_name))

            LOG.debug('XXX process map_fn: {}'.format(map_fn))

            map_result = map_fn(device, result)
            if map_result:
                mapper.update(map_result)

        # GKE results will have a "clusters" key.
        # Bigtable clusters also use cluster key
        elif "clusters" in result:
            clustlist = result.get('clusters')
            if clustlist and clustlist[0].get('selfLink'):
                kubernetes_map_result = map_kubernetesClusterList(device, result)
                if kubernetes_map_result:
                    mapper.update(kubernetes_map_result)
            else:
                bigTableCluster_map_result = map_bigTableClusterList(device, result)
                if bigTableCluster_map_result:
                    mapper.update(bigTableCluster_map_result)
        # Process GoogleCloudFunctions here.
        elif "functions" in result:
            functions_map_result = map_gcpFunctionList(device, result)
            if functions_map_result:
                mapper.update(functions_map_result)

        # Dataflow jobs will have "jobs" key.
        elif "jobs" in result:
            dataflow_map_result = map_dataflowJobsList(device, result)
            if dataflow_map_result:
                mapper.update(dataflow_map_result)

        # BigTable instances will have "instances" key.
        elif "instances" in result:
            bigTableInstance_map_result = map_bigTableInstanceList(device, result)
            if bigTableInstance_map_result:
                mapper.update(bigTableInstance_map_result)

        # BigTable appProfiles will have "appProfiles" key.
        elif "appProfiles" in result:
            bigTableAppProfile_map_result = map_bigTableAppProfilesList(device, result)
            if bigTableAppProfile_map_result:
                mapper.update(bigTableAppProfile_map_result)

        # BigTable Tables will have "tables" key.
        elif "tables" in result:
            bigTableTable_map_result = map_bigTableTablesList(device, result)
            if bigTableTable_map_result:
                mapper.update(bigTableTable_map_result)

        # Cloud SQL instances will have "items" key.
        elif "items" in result:
            if any([i['kind'] == 'sql#instance' for i in result['items']]):
                cloudSQLInstance_map_result = map_cloudSQLInstancesList(device, result)
                if cloudSQLInstance_map_result:
                    mapper.update(cloudSQLInstance_map_result)

    '''
    # Prevent modeling of zones with no instances.
    zone_type = "ZenPacks.zenoss.GoogleCloudPlatform.ComputeZone"
    for zone_id, zone_datum in mapper.by_type(zone_type):
        if not zone_datum["links"].get("instances"):
            mapper.remove(zone_id)

    # Prevent modeling of regions with no zones.
    region_type = "ZenPacks.zenoss.GoogleCloudPlatform.ComputeRegion"
    for region_id, region_datum in mapper.by_type(region_type):
        if not region_datum["links"].get("zones"):
            mapper.remove(region_id)

    # Prevent modeling of images with no disks.
    image_type = "ZenPacks.zenoss.GoogleCloudPlatform.ComputeImage"
    for image_id, image_datum in mapper.by_type(image_type):
        if not image_datum["links"].get("disks"):
            mapper.remove(image_id)

    # Prevent modeling of instanceGroups with no instances..
    instanceGroup_type = "ZenPacks.zenoss.GoogleCloudPlatform.ComputeInstanceGroup"
    for instanceGroup_id, instanceGroup_datum in mapper.by_type(instanceGroup_type):
        if not instanceGroup_datum["links"].get("instances2"):
            mapper.remove(instanceGroup_id)

    # Prevent modeling of unused instanceTemplates.
    instanceTemplate_type = "ZenPacks.zenoss.GoogleCloudPlatform.ComputeInstanceTemplate"
    for instanceTemplate_id, instanceTemplate_datum in mapper.by_type(instanceTemplate_type):
        instanceTemplate_used = any((
            instanceTemplate_datum["links"].get("instances"),
            instanceTemplate_datum["links"].get("instanceGroups")))

        if not instanceTemplate_used:
            mapper.remove(instanceTemplate_id)

    # Prevent modeling of machineTypes with no instances.
    machineType_type = "ZenPacks.zenoss.GoogleCloudPlatform.ComputeMachineType"
    for machineType_id, machineType_datum in mapper.by_type(machineType_type):
        if not machineType_datum["links"].get("instances"):
            mapper.remove(machineType_id)

    # Prevent modeling of disks attached to no instances.
    disk_type = "ZenPacks.zenoss.GoogleCloudPlatform.ComputeDisk"
    for disk_id, disk_datum in mapper.by_type(disk_type):
        if not disk_datum["links"].get("instances"):
            mapper.remove(disk_id)

    # Prevent modeling of diskTypes with no disks.
    diskType_type = "ZenPacks.zenoss.GoogleCloudPlatform.ComputeDiskType"
    for diskType_id, diskType_datum in mapper.by_type(diskType_type):
        if not diskType_datum["links"].get("disks"):
            mapper.remove(diskType_id)
    '''

    return mapper.get_full_datamaps()


# Mapping Functions ###################################################

def map_project(device, result):
    """Return data given compute#project result.

    Example compute#project result:

        {u'commonInstanceMetadata': {u'fingerprint': u'eSm54VHwyRw=',
                                     u'items': [{u'key': u'ssh-keys',
                                                 u'value': u'blah blah blah'}],
                                     u'kind': u'compute#metadata'},
         u'creationTimestamp': u'2018-03-30T12:47:20.427-07:00',
         u'defaultServiceAccount': u'469482109134-compute@developer.gserviceaccount.com',
         u'id': u'217208988139465383',
         u'kind': u'compute#project',
         u'name': u'zenoss-testing-1',
         u'quotas': [{u'limit': 25000.0, u'metric': u'SNAPSHOTS', u'usage': 1.0}],
         u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1',
         u'xpnProjectStatus': u'UNSPECIFIED_XPN_PROJECT_STATUS'}

    """
    data = {
        PROJECT_ID: {
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.ProjectDevice",
            "properties": {
                # ComputeKind properties.
                "gce_name": result.get("name"),
                "gce_creationTimestamp": result.get("creationTimestamp"),
                "gce_kind": result.get("kind"),
                "gce_id": result.get("id"),
                "gce_selfLink": result.get("selfLink"),

                # ProjectDevice properties.
                "defaultServiceAccount": result.get("defaultServiceAccount"),
                "xpnProjectStatus": result.get("xpnProjectStatus"),
            },
            "links": {
                # ProjectDevice links.
                "images": [],
                "instanceTemplates": [],
                "regions": [],
                "snapshots": [],
                "zones": [],
                "dataflowJobs": [],
                "buckets": [],
                "bigTableInstances": [],
                # ComputeQuotaContainer links.
                "quotas": [],
            },
        },
    }

    '''
    for quota_item in result.get("quotas", ()):
        metric = quota_item.get("metric")
        if not metric:
            continue

        # No reason to model quotas with a limit of 0.
        limit = quota_item.get("limit")
        if limit == 0:
            continue

        quota_id = "quota_project_{}".format(metric.lower())

        data[quota_id] = {
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.ComputeQuota",
            "title": "project / {}".format(metric),
            "properties": {
                "metric": metric,
                "limit_modeled": limit,
            },
            "links": {
                "container": PROJECT_ID,
            }
        }
    '''
    return data


def map_cloudSQLInstancesList(device, result):
    """Return data given CloudSQL instance list.

    Example result:

    {
      u'items': [
        {
          u'kind': u'sql#instance',
          u'backendType': u'SECOND_GEN',
          u'secondaryGceZone': u'europe-west1-d',
          u'failoverReplica': {
            u'available': True
          },
          u'settings': {
            u'databaseFlags': [
              {
                u'name': u'max_connections',
                u'value': u'100'
              },
              {
                u'name': u'log_connections',
                u'value': u'on'
              },
              {
                u'name': u'log_disconnections',
                u'value': u'on'
              },
              {
                u'name': u'log_statement',
                u'value': u'ddl'
              }
            ],
            u'kind': u'sql#settings',
            u'dataDiskType': u'PD_SSD',
            u'availabilityType': u'REGIONAL',
            u'maintenanceWindow': {
              u'kind': u'sql#maintenanceWindow',
              u'updateTrack': u'stable',
              u'day': 7,
              u'hour': 1
            },
            u'authorizedGaeApplications': [
              
            ],
            u'activationPolicy': u'ALWAYS',
            u'backupConfiguration': {
              u'kind': u'sql#backupConfiguration',
              u'backupRetentionSettings': {
                u'retentionUnit': u'COUNT',
                u'retainedBackups': 7
              },
              u'replicationLogArchivingEnabled': True,
              u'enabled': True,
              u'transactionLogRetentionDays': 7,
              u'binaryLogEnabled': False,
              u'location': u'eu',
              u'startTime': u'01:00',
              u'pointInTimeRecoveryEnabled': True
            },
            u'ipConfiguration': {
              u'requireSsl': False,
              u'ipv4Enabled': False,
              u'authorizedNetworks': [
                
              ],
              u'privateNetwork': u'projects/fednot-sharedvpc-acc/global/networks/fednot-sharedvpc-acc'
            },
            u'userLabels': {
              u'name': u'sql-izimi-acc'
            },
            u'pricingPlan': u'PER_USE',
            u'replicationType': u'SYNCHRONOUS',
            u'storageAutoResizeLimit': u'0',
            u'tier': u'db-custom-8-15360',
            u'settingsVersion': u'18',
            u'storageAutoResize': True,
            u'locationPreference': {
              u'kind': u'sql#locationPreference',
              u'zone': u'europe-west1-d'
            },
            u'dataDiskSizeGb': u'10'
          },
          u'region': u'europe-west1',
          u'serverCaCert': {
            u'certSerialNumber': u'0',
            u'kind': u'sql#sslCert',
            u'sha1Fingerprint': u'adcb02902342cec8c20fb60dcd656b6dc755f654',
            u'commonName': u'C=US,O=Google\\, Inc,CN=Google Cloud SQL Server CA,dnQualifier=5be3d212-05c2-4ace-9d48-2f56ad2acddd',
            u'instance': u'sql-izimi-acc-8170413f',
            u'cert': u'-----BEGIN CERTIFICATE-----\nMIIDfzCCAmegAwIBAgIBADANBgkqhkiG9w0BAQsFADB3MS0wKwYDVQQuEyQ1YmUz\nZDIxMi0wNWMyLTRhY2UtOWQ0OC0yZjU2YWQyYWNkZGQxIzAhBgNVBAMTGkdvb2ds\nZSBDbG91ZCBTUUwgU2VydmVyIENBMRQwEgYDVQQKEwtHb29nbGUsIEluYzELMAkG\nA1UEBhMCVVMwHhcNMjAwOTE2MDY1NzUxWhcNMzAwOTE0MDY1ODUxWjB3MS0wKwYD\nVQQuEyQ1YmUzZDIxMi0wNWMyLTRhY2UtOWQ0OC0yZjU2YWQyYWNkZGQxIzAhBgNV\nBAMTGkdvb2dsZSBDbG91ZCBTUUwgU2VydmVyIENBMRQwEgYDVQQKEwtHb29nbGUs\nIEluYzELMAkGA1UEBhMCVVMwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIB\nAQClBEBfB2MeCFz8g2KKknrFbgVXcUTAd6GqzA97mYzERB++wVjamQ8I+bE73AtH\nyiWg9AVnn49eVEvQPN2JioDmqQ9V/DYYdDKoKEAs/NwVIencajddBaB0aZiX1XFW\nJkWFQ3jJNLjl8f1+SbGs/6Bx7ARgZpb9En2x31a+I3pFWgSwBs19lqhFSEPHq6Wt\nZmceo+mhYvfv3e1xt72shp+106HZ3wtZrdFi/y4uAJsVTErz52fOSKAsLSWML6Cg\nAbZ/xiT9Xe+L08UFo797sl+YmO5Mdt3O3Tf7Dq/hNcFNVoRsSRb0U+S//3Z/SEkT\nZf9ZdOmB9TvO1L5m5v5sKeEhAgMBAAGjFjAUMBIGA1UdEwEB/wQIMAYBAf8CAQAw\nDQYJKoZIhvcNAQELBQADggEBAKII4qbkbqAb3cwajkt9V8SmBJUVgrjiLwUJYn1x\npP8pUErChDqlNNv7WaaR0mPeLqARUE+NKcLBnYV7XzMJ92SQZ8HUs3o+Ig9xCGyJ\nFTqo870vEOwRtA9z0YXFwtLs+lGzyLTwgG3XJ2vH39GB7RXw9h4IeVKu4wWJ4X1t\nPbrTogtLyEPt/AjxnJZhvSpoe0L+tH2ET1uRD8Z6nHDoSKFxeKsKE/4Yf8H4CvtI\nvFBvFcHWnAp9Kd0vGP6MsSifUZDqqLyu68EzPee3k7YWD53eLEdxTu47vD37XJ08\nYjqEgyo2xFnZvwrhLHdhoF4x7d6Nu26bfFxMMjADNoLDYV8=\n-----END CERTIFICATE-----',
            u'expirationTime': u'2030-09-14T06:58:51.719Z',
            u'createTime': u'2020-09-16T06:57:51.719Z'
          },
          u'gceZone': u'europe-west1-b',
          u'project': u'fednot-acc-certinot',
          u'state': u'RUNNABLE',
          u'etag': u'48a7c5bb67d1cec2901bd3872196a97d9ec5b2852bb18aab8db2f45760f04327',
          u'serviceAccountEmailAddress': u'p544053300745-na7gqs@gcp-sa-cloud-sql.iam.gserviceaccount.com',
          u'ipAddresses': [
            {
              u'ipAddress': u'10.1.4.19',
              u'type': u'PRIVATE'
            }
          ],
          u'connectionName': u'fednot-acc-certinot:europe-west1:sql-izimi-acc-8170413f',
          u'databaseVersion': u'POSTGRES_11',
          u'instanceType': u'CLOUD_SQL_INSTANCE',
          u'selfLink': u'https://sqladmin.googleapis.com/sql/v1beta4/projects/fednot-acc-certinot/instances/sql-izimi-acc-8170413f',
          u'name': u'sql-izimi-acc-8170413f'
        }
      ]
    }
    """
    data = {}
    for instance in result.get("items"):

        # LOG.debug('DDDD map_cloudSQLInstancesList instance: {}'.format(instance))
        # LOG.debug('DDDD map_cloudSQLInstancesList selfLink: {}'.format(instance["selfLink"]))
        # LOG.debug('DDDD map_cloudSQLInstancesList get_id: {}'.format(get_id(instance["selfLink"])))

        zone = instance.get("gceZone")
        projectName = instance.get("project")
        gke_name = instance.get("name")
        database_id = '{}:{}'.format(projectName, gke_name)

        data.update({
            get_id(instance["selfLink"]): {
                "title": "{} / {}".format(
                    instance["region"],
                    instance["name"]),
                "type": "ZenPacks.community.GCPExtensions.CloudSQLInstance",
                "properties": {
                    "gke_name": gke_name,
                    "backendType": instance.get("backendType"),
                    "gceZone": zone,
                    "secondaryGceZone": instance.get("secondaryGceZone"),
                    "region": instance.get("region"),
                    "projectName": projectName,
                    "ipAddress": instance.get("ipAddresses")[0].get("ipAddress"),
                    "connectionName": instance.get("connectionName"),
                    "databaseVersion": instance.get("databaseVersion"),
                    "database_id": database_id,
                },
                "links": {
                    "project": PROJECT_ID,
                    "zone": prepId('zone_' + zone),
                }
            }
        })

        '''
                    "gke_name": instance.get("name"),
                    "backendType": instance.get("backendType"),
                    "gceZone": instance.get("gceZone"),
                    "secondaryGceZone": instance.get("secondaryGceZone"),
                    "region": instance.get("region"),
                    "project": instance.get("project"),
                    "ipAddress": instance.get("ipAddresses")[0].get("ipAddress"),
                    "connectionName": instance.get("connectionName"),
                    "databaseVersion": instance.get("databaseVersion"),
        
        '''


        '''
        # While in clusters loop: Add the KubernetesNodePools.
        for nodePool in cluster.get("nodePools", ()):
            data.update({
                get_id(nodePool["selfLink"]): {
                    "title": "{zone} / {cluster} / {name}".format(
                        zone=nodePool["selfLink"].split("/")[-5],
                        cluster=nodePool["selfLink"].split("/")[-3],
                        name=nodePool["name"]),
                    "type": "ZenPacks.zenoss.GoogleCloudPlatform.KubernetesNodePool",
                    "properties": {
                        "gke_name": nodePool.get("name"),
                        "version": nodePool.get("version"),
                        "initialNodeCount": maybe_int(nodePool.get("initialNodeCount")),
                        "nodeDiskSize": (maybe_int(nodePool["config"].get("diskSizeGb")) or 0) * ONE_GiB,
                        "nodeImageType": nodePool["config"].get("imageType"),
                        "nodeServiceAccount": nodePool["config"].get("serviceAccount"),
                        "nodeMachineType": nodePool["config"].get("machineType"),
                        "selfLink": nodePool.get("selfLink"),
                    },
                    "links": {
                        "instanceGroups": [
                            get_id(x).replace("GroupManager", "Group")
                            for x in nodePool.get("instanceGroupUrls")],
                    }
                }
            })
            '''

    # 'ZenPacks.zenoss.GoogleCloudPlatform.KubernetesCluster'
    '''
    data = {
        'test': {
            'type': 'ZenPacks.community.GCPExtensions.CloudSQLInstance',
            'properties': {
            },
            'links': {
                'project': '#PROJECT#',
            },
            'title': 'test'
        }
    }
    '''

    LOG.debug('map_cloudSQLInstancesList data: {}'.format(data))

    return data


def map_databasesList(device, result):
    """
    Example result:
    {
      u'items': [
        {
          u'kind': u'sql#database',
          u'name': u'postgres',
          u'charset': u'UTF8',
          u'project': u'fednot-acc-certinot',
          u'instance': u'sql-izimi-acc-8170413f',
          u'etag': u'5abc962b2fa8fcbeff62c5b6679c301e12a56afe63159b67e9cce950e222444c',
          u'collation': u'en_US.UTF8',
          u'selfLink': u'https://sqladmin.googleapis.com/sql/v1beta4/projects/fednot-acc-certinot/instances/sql-izimi-acc-8170413f/databases/postgres'
        },
        {
          u'kind': u'sql#database',
          u'name': u'izimi-acc',
          u'charset': u'UTF8',
          u'project': u'fednot-acc-certinot',
          u'instance': u'sql-izimi-acc-8170413f',
          u'etag': u'c6c7febfc6a50bc2b8f9846c6bba89be49524c0a33744cf7312af4c1f5d750be',
          u'collation': u'en_US.UTF8',
          u'selfLink': u'https://sqladmin.googleapis.com/sql/v1beta4/projects/fednot-acc-certinot/instances/sql-izimi-acc-8170413f/databases/izimi-acc'
        },
        {
          u'kind': u'sql#database',
          u'name': u'izimi-eventlog-acc',
          u'charset': u'UTF8',
          u'project': u'fednot-acc-certinot',
          u'instance': u'sql-izimi-acc-8170413f',
          u'etag': u'cb156511e0455ab150e29812e7daa4c2fe095c969c4fc02891fb58c6259353f6',
          u'collation': u'en_US.UTF8',
          u'selfLink': u'https://sqladmin.googleapis.com/sql/v1beta4/projects/fednot-acc-certinot/instances/sql-izimi-acc-8170413f/databases/izimi-eventlog-acc'
        },
        {
          u'kind': u'sql#database',
          u'name': u'izimi-keycloak-acc',
          u'charset': u'UTF8',
          u'project': u'fednot-acc-certinot',
          u'instance': u'sql-izimi-acc-8170413f',
          u'etag': u'cbfaa79bfbff00bbad35803b448715cc28586dcde38f0859cf45cb4a462201ff',
          u'collation': u'en_US.UTF8',
          u'selfLink': u'https://sqladmin.googleapis.com/sql/v1beta4/projects/fednot-acc-certinot/instances/sql-izimi-acc-8170413f/databases/izimi-keycloak-acc'
        }
      ],
      u'kind': u'sql#databasesList'
    }
    """
    data = {}

    LOG.debug('OOOOOOOOOO map_databasesList: {}'.format(result))
    for instance in result.get("items"):

        # LOG.debug('DDDD map_cloudSQLInstancesList instance: {}'.format(instance))
        # LOG.debug('DDDD map_cloudSQLInstancesList selfLink: {}'.format(instance["selfLink"]))
        # LOG.debug('DDDD map_cloudSQLInstancesList get_id: {}'.format(get_id(instance["selfLink"])))

        data.update({
            get_id(instance["selfLink"]): {
                "title": "{} / {}".format(
                    instance["instance"],
                    instance["name"]),
                "type": "ZenPacks.community.GCPExtensions.CloudSQLDatabase",
                "properties": {
                    "charset": instance.get("charset"),
                    "etag": instance.get("etag"),
                    "collation": instance.get("collation"),
                    "selfLink": instance.get("selfLink"),
                    "shortname": instance.get("name"),
        },
                "links": {
                    "cloudSQLInstance": "instance_{}_{}".format(instance["project"], instance["instance"]),
        }
            }
        })


    return data
