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
    "Collector",
    "CollectorOptions",
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

from Products.ZenUtils.Utils import prepId

from . import txgcp
from .mapper import DataMapper
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


class Collector(object):
    def __init__(self, device, testing=False, save_responses=False):

        self.client = txgcp.Client(
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


        # Make call to Stackdriver and get list of K8 instance_ids..
        self.operations.append((
            self.collect_kubernetes_clusters,
            (project_name,)))


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

    def collect_kubernetes_clusters(self, project_name):
        """Wrap a Kubernetes cluster call in case GKE isn't enabled."""
        def handle_success(result):
            LOG.info("%s: Kubernetes Engine is enabled", project_name)
            return result

        def handle_failure(failure):
            error = getattr(failure, "value", None)
            code = getattr(error, "code", None)
            message = getattr(error, "message", None)
            if code == 403 and "disabled" in message.lower():
                LOG.info("%s: Kubernetes Engine is disabled", project_name)
                return {}

            # Propagate any other failures.
            return failure

        d = self.client.kubernetes(project_name).clusters()
        d.addCallback(handle_success)
        d.addErrback(handle_failure)
        return d

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

    def collect_buckets(self, project_name):
        def handle_success(result):
            LOG.info("%s: GCP Storage is enabled", project_name)
            return result

        def handle_failure(failure):
            error = getattr(failure, "error", None)
            message = getattr(error, "message", None)
            LOG.info("%s: Bucket modeling failed", message)

            # Propagate any other failures.
            return failure

        d = self.client.storage(project_name).buckets()
        d.addCallback(handle_success)
        d.addErrback(handle_failure)
        return d

    def collect_bigtable_instances(self, project_name):
        def handle_success(result):
            LOG.info("%s: GCP BigTable is enabled", project_name)
            return result

        def handle_failure(failure):
            error = getattr(failure, "error", None)
            message = getattr(error, "message", None)
            LOG.info("%s: BigTable modeling failed", message)

            # Propagate any other failures.
            return failure

        d = self.client.bigtable(project_name).instances()
        d.addCallback(handle_success)
        d.addErrback(handle_failure)
        return d

    def collect_bigtable_clusters(self, project_name):
        def handle_success(result):
            return result

        def handle_failure(failure):
            error = getattr(failure, "error", None)
            message = getattr(error, "message", None)
            LOG.info("BigTable Instance modeling failed: %s", message)
            # Propagate any other failures.
            return failure

        d = self.client.bigtable(project_name).clusters()
        d.addCallback(handle_success)
        d.addErrback(handle_failure)
        return d

    def collect_bigtable_appProfiles(self, project_name):
        def handle_success(result):
            return result

        def handle_failure(failure):
            error = getattr(failure, "error", None)
            message = getattr(error, "message", None)
            LOG.info("BigTable AppProfiles modeling failed: %s", message)
            # Propagate any other failures.
            return failure

        d = self.client.bigtable(project_name).appProfiles()
        d.addCallback(handle_success)
        d.addErrback(handle_failure)
        return d

    def collect_bigtable_tables(self, project_name, instance):
        def handle_success(result):
            return result

        def handle_failure(failure):
            error = getattr(failure, "error", None)
            message = getattr(error, "message", None)
            LOG.info("BigTable Tables modeling failed: %s", message)
            # Propagate any other failures.
            return failure

        d = self.client.bigtable(project_name).tables(instance)
        d.addCallback(handle_success)
        d.addErrback(handle_failure)
        return d

    def collect_autoscalars(self, project_name):
        def handle_success(result):
            return result

        def handle_failure(failure):
            error = getattr(failure, "error", None)
            message = getattr(error, "message", None)
            LOG.info("BigTable Cluster modeling failed: %s", message)
            # Propagate any other failures.
            return failure

        d = self.client.autoscalars(project_name).aggregatedList()
        d.addCallback(handle_success)
        d.addErrback(handle_failure)
        return d

    def collect_gcp_functions(self, project_name):
        """Wrap a GCP functions call in case it isn't enabled."""
        def handle_success(result):
            LOG.info("%s: GCP Functions ara enabled", project_name)
            return result

        def handle_failure(failure):
            error = getattr(failure, "value", None)
            status = getattr(error, "status", None)
            if 'PERMISSION_DENIED' in status:
                LOG.info("%s: PERMISSIONS DENIED on GCP Functions.", project_name)
                return {}

            error = getattr(failure, "error", None)
            code = getattr(error, "code", None)
            message = getattr(error, "message", None)
            if code == 403 and "disabled" in message.lower():
                LOG.info("%s: GCP Functions are disabled.", project_name)
                return {}

            # Propagate any other failures.
            return failure

        d = self.client.cloudfunctions(project_name).functions()
        d.addCallback(handle_success)
        d.addErrback(handle_failure)
        return d

    def collect_dataflow_jobs(self, project_name):
        """Wrap a Dataflow call if not enabled."""
        def handle_success(result):
            LOG.info("%s: Dataflow Jobs collected", project_name)
            return result

        def handle_failure(failure):
            error = getattr(failure, "value", None)
            status = getattr(error, "status", None)
            if 'PERMISSION_DENIED' in status:
                LOG.info("%s: PERMISSIONS DENIED on GCP Dataflows.", project_name)
                return {}

            # Propagate any other failures.
            return failure

        d = self.client.dataflow(project_name).jobs()
        d.addCallback(handle_success)
        d.addErrback(handle_failure)
        return d

    def collect_bigquery_datasets(self, project_name):
        """Collect a list of Bigquery Datasets"""
        d = self.client.bigquery(project_name).list()
        d.addCallback(self.handle_dataset_list)
        d.addErrback(self.handle_failure)
        return d

    def collect_bigquery_datasets_details(
            self, project_name, dataset_id, datasets_list):
        """Collect additional details for Bigquery Datasets"""
        d = self.client.bigquery(project_name).dataset(dataset_id)
        d.addCallback(self.handle_dataset_details, datasets_list)
        d.addErrback(self.handle_failure)
        return d

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

    def handle_failure(self, failure):
        # Unwrap "FirstError" from DeferredList failure.
        if isinstance(failure, TxFailure):
            if isinstance(failure.value, defer.FirstError):
                return failure.value.subFailure

        return failure

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

    def handle_bigTableInstance(self, result):

        project_name = result.get('instances')[0].get("name").split("/")[1]
        model_regex = validate_modeling_regex(
            self.device, 'zGoogleCloudPlatformBigTableInstancesModeled')
        if not model_regex:
            return
        for item in result.get("instances", []):
            name = item['name'].split('/')[-1]
            if not re.match(model_regex, name) and not re.match(model_regex, item["displayName"]):
                continue

            # Validate regex for BigTable zProperty before collecting data
            if validate_modeling_regex(
                    self.device, 'zGoogleCloudPlatformBigTableTablesModeled'):
                self.operations.append((
                    self.collect_bigtable_tables,
                    (project_name, name)))

    def handle_regionList(self, result):
        """Special handling for compute#regionList response.

        Called dynamically from handle_result.

        """
        project = result["id"].split("/")[1]

        # Get per-region data.
        for item in result.get("items", []):
            region = self.client.compute_region(project, item["name"])

            self.operations.extend(
                (region.list, (KIND_MAP[x],))
                for x in self.options.region_kinds())

    def handle_regionInstanceGroupList(self, result):
        """Special handling for compute#regionInstanceGroupList responses.

        Called dynamically from handle_result.

        """
        # projects/zenoss-testing-1/regions/us-east1/instanceGroups
        _, project, _, region, _ = result["id"].split("/")

        for item in result.get("items", []):
            rig = self.client.compute_regionInstanceGroup(
                project,
                region,
                item["name"])

            # This is the only way to get instance group membership.
            self.operations.append((rig.listInstances, ()))

    def handle_zoneList(self, result):
        """Special handling for compute#zoneList response.

        Called dynamically from handle_result.

        """
        project = result["id"].split("/")[1]

        # Get zone data that hasn't been gotten in aggregate in collect.
        for item in result.get("items", []):
            zone_name = item["name"]
            zone = self.client.compute_zone(project, zone_name)

            self.operations.extend(
                (zone.list, (KIND_MAP[x],))
                for x in self.options.zone_kinds())

    def handle_instanceGroupList(self, result):
        """Special handling for compute#instanceGroupList responses.

        Called dynamically from handle_result.

        """
        # projects/zenoss-testing-1/zones/us-east1-b/instanceGroups
        _, project, _, zone, _ = result["id"].split("/")

        for item in result.get("items", []):
            ig = self.client.compute_instanceGroup(
                project,
                zone,
                item["name"])

            # This is the only way to get instance group membership.
            self.operations.append((ig.listInstances, ()))

    def handle_dataset_list(self, result):
        """ Prepare query for dataset details from dataset list

        Example Result:
            {
             "kind": "bigquery#datasetList",
             "etag": "vzKG+rPA50hFeXXcJmXeEA==",
             "datasets": [
              {

               "kind": "bigquery#dataset",
               "id": "zenoss-testing-1:TestBillingDataSet",
               "datasetReference": {
                "datasetId": "TestBillingDataSet",
                "projectId": "zenoss-testing-1"
               },
               "location": "US"
              },
              {

               "kind": "bigquery#dataset",
               "id": "zenoss-testing-1:mihnat_bigquery_dataset",
               "datasetReference": {
                "datasetId": "mihnat_bigquery_dataset",
                "projectId": "zenoss-testing-1"
               },
               "location": "US"
              }
             ]
            }
        """
        if 'datasets' not in result:
            return {}

        datasets_list = {}
        datasets_list['datasets'] = []
        datasets_list['etag'] = result.get('etag', '')
        datasets_list['kind'] = result.get('kind', '')
        project_name = ""
        model_regex = validate_modeling_regex(
            self.device, 'zGoogleCloudPlatformBigQueryDatasetsModeled')

        for dataset in result['datasets']:
            reference = dataset.get('datasetReference', None)
            if not reference:
                continue

            dataset_id = str(reference.get('datasetId', ''))
            if not dataset_id or not re.match(model_regex, dataset_id):
                continue

            project_name = str(reference.get('projectId', ''))
            self.collect_bigquery_datasets_details(
                project_name, dataset_id, datasets_list)

        LOG.info("%s: BigQuery Datasets collected", project_name)

        return datasets_list

    def handle_dataset_details(self, result, datasets_list):
        """ Collect dataset details for processing """
        datasets_list['datasets'].append(result)
        return datasets_list


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


def map_regionList(device, result):
    """Return data given compute#regionList result.

    Example compute#regionList result:

        {u'id': u'projects/zenoss-testing-1/regions',
         u'items': [{u'creationTimestamp': u'1969-12-31T16:00:00.000-08:00',
                     u'description': u'asia-east1',
                     u'id': u'1220',
                     u'kind': u'compute#region',
                     u'name': u'asia-east1',
                     u'quotas': [{u'limit': 2400.0,
                                  u'metric': u'CPUS',
                                  u'usage': 0.0}],
                     u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/regions/asia-east1',
                     u'status': u'UP',
                     u'zones': [u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/asia-east1-a',
                                u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/asia-east1-b',
                                u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/asia-east1-c']}],
         u'kind': u'compute#regionList',
         u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/regions'}

    """

    data = {}

    for item in result.get("items", ()):
        region_id = get_id(item["selfLink"])
        region_name = item["name"]

        data[region_id] = {
            "title": region_name,
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.ComputeRegion",
            "properties": {
                # ComputeKind properties.
                "gce_name": item.get("name"),
                "gce_creationTimestamp": item.get("creationTimestamp"),
                "gce_kind": item.get("kind"),
                "gce_id": item.get("id"),
                "gce_selfLink": item.get("selfLink"),

                # ComputeRegion properties.
                "description": item.get("description"),
            },
            "links": {
                "project": PROJECT_ID,
                "zones": [],
                "instanceGroups": [],
                "quotas": [],
                "dataflowJobs": []
            },
        }

        for quota_item in item.get("quotas", ()):
            metric = quota_item.get("metric")
            if not metric:
                continue

            # No reason to model quotas with a limit of 0.
            limit = quota_item.get("limit")
            if limit == 0:
                continue

            quota_id = "{}_{}".format(
                region_id.replace("region_", "quota_"),
                metric.lower())

            data[quota_id] = {
                "title": "{} / {}".format(region_name, metric),
                "type": "ZenPacks.zenoss.GoogleCloudPlatform.ComputeQuota",
                "properties": {
                    "metric": metric,
                    "limit_modeled": limit,
                },
                "links": {
                    "container": region_id,
                }
            }
    return data


def map_imageList(device, result):
    """Return data given compute#imageList result.

    Example compute#imageList result:

        {u'id': u'projects/zenoss-testing-1/global/images',
         u'items': [{u'archiveSizeBytes': u'419740416',
                     u'creationTimestamp': u'2018-03-30T12:58:02.196-07:00',
                     u'description': u'Created from instance-1.',
                     u'diskSizeGb': u'10',
                     u'family': u'adams',
                     u'guestOsFeatures': [{u'type': u'VIRTIO_SCSI_MULTIQUEUE'}],
                     u'id': u'5595230220007450662',
                     u'kind': u'compute#image',
                     u'labelFingerprint': u'42WmSpB8rSM=',
                     u'licenseCodes': [u'1000010'],
                     u'licenses': [u'https://www.googleapis.com/compute/v1/projects/ubuntu-os-cloud/global/licenses/ubuntu-1404-trusty'],
                     u'name': u'image-1',
                     u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/global/images/image-1',
                     u'sourceDisk': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/disks/instance-1',
                     u'sourceDiskId': u'1409068193805446014',
                     u'sourceType': u'RAW',
                     u'status': u'READY'}],
         u'kind': u'compute#imageList',
         u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/global/images'}

    """
    return {
        get_id(item["selfLink"]): {
            "title": item["name"],
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.ComputeImage",
            "properties": {
                # ComputeKind properties.
                "gce_name": item.get("name"),
                "gce_creationTimestamp": item.get("creationTimestamp"),
                "gce_kind": item.get("kind"),
                "gce_id": item.get("id"),
                "gce_selfLink": item.get("selfLink"),

                # ComputeImage properties.
                "set_labels": labels_list(item.get('labels', {})),
                "description": item.get("description"),
                "family": item.get("family"),
                "diskSize": (maybe_int(item.get("diskSizeGb")) or 0) * ONE_GiB,
                "archiveSize": maybe_int(item.get("archiveSizeBytes")),
            },
            "links": {
                "project": PROJECT_ID,
                "disks": [],
            },
        }
        for item in result.get("items", ())
    }


def map_snapshotList(device, result):
    """Return data given compute#snapshotList result.

    Example compute#snapshotList result:

        {u'id': u'projects/zenoss-testing-1/global/snapshots',
         u'items': [{u'creationTimestamp': u'2018-03-30T12:57:00.272-07:00',
                     u'diskSizeGb': u'10',
                     u'id': u'1059480425964185700',
                     u'kind': u'compute#snapshot',
                     u'labelFingerprint': u'42WmSpB8rSM=',
                     u'licenseCodes': [u'1000010'],
                     u'licenses': [u'https://www.googleapis.com/compute/v1/projects/ubuntu-os-cloud/global/licenses/ubuntu-1404-trusty'],
                     u'name': u'snapshot-1',
                     u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/global/snapshots/snapshot-1',
                     u'sourceDisk': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/disks/instance-1',
                     u'sourceDiskId': u'1409068193805446014',
                     u'status': u'READY',
                     u'storageBytes': u'419738368',
                     u'storageBytesStatus': u'UP_TO_DATE'}],
         u'kind': u'compute#snapshotList',
         u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/global/snapshots'}

    """
    return {
        get_id(item["selfLink"]): {
            "title": item["name"],
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.ComputeSnapshot",
            "properties": {
                # ComputeKind properties.
                "gce_name": item.get("name"),
                "gce_creationTimestamp": item.get("creationTimestamp"),
                "gce_kind": item.get("kind"),
                "gce_id": item.get("id"),
                "gce_selfLink": item.get("selfLink"),

                # ComputeSnapshot properties.
                "set_labels": labels_list(item.get('labels', {})),
                "diskSize": (maybe_int(item.get("diskSizeGb")) or 0) * ONE_GiB,
            },
            "links": {
                "project": PROJECT_ID,
                "sourceDisk": get_id(item.get("sourceDisk")),
            }
        }
        for item in result.get("items", ())
    }


def map_instanceTemplateList(device, result):
    """Return data given compute#instanceTemplateList result.

    Example compute#instanceTemplateList result:

        {u'id': u'projects/zenoss-testing-1/global/instanceTemplates',
         u'items': [{u'creationTimestamp': u'2018-04-25T09:11:14.196-07:00',
                     u'description': u'',
                     u'id': u'2560276968537658957',
                     u'kind': u'compute#instanceTemplate',
                     u'name': u'gke-cluster-1-default-pool-fc3e27a3',
                     u'properties': {u'canIpForward': True,
                                     u'disks': [{u'autoDelete': True,
                                                 u'boot': True,
                                                 u'deviceName': u'persistent-disk-0',
                                                 u'index': 0,
                                                 u'initializeParams': {u'diskSizeGb': u'100',
                                                                       u'diskType': u'pd-standard',
                                                                       u'sourceImage': u'https://www.googleapis.com/compute/v1/projects/gke-node-images/global/images/gke-188-gke0-cos-beta-65-10323-12-0-p-v180223-pre'},
                                                 u'kind': u'compute#attachedDisk',
                                                 u'mode': u'READ_WRITE',
                                                 u'type': u'PERSISTENT'}],
                                     u'machineType': u'g1-small',
                                     u'metadata': {u'fingerprint': u'fAgkYMMAkpA=',
                                                   u'items': [{u'key': u'cluster-location',
                                                               u'value': u'us-central1-a'}],
                                                   u'kind': u'compute#metadata'},
                                     u'networkInterfaces': [{u'accessConfigs': [{u'kind': u'compute#accessConfig',
                                                                                 u'name': u'external-nat',
                                                                                 u'type': u'ONE_TO_ONE_NAT'}],
                                                             u'kind': u'compute#networkInterface',
                                                             u'network': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/global/networks/default',
                                                             u'subnetwork': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/regions/us-central1/subnetworks/default'}],
                                     u'scheduling': {u'automaticRestart': True,
                                                     u'onHostMaintenance': u'MIGRATE',
                                                     u'preemptible': False},
                                     u'serviceAccounts': [{u'email': u'default',
                                                           u'scopes': [u'https://www.googleapis.com/auth/compute',
                                                                       u'https://www.googleapis.com/auth/devstorage.read_only',
                                                                       u'https://www.googleapis.com/auth/logging.write',
                                                                       u'https://www.googleapis.com/auth/monitoring',
                                                                       u'https://www.googleapis.com/auth/servicecontrol',
                                                                       u'https://www.googleapis.com/auth/service.management.readonly',
                                                                       u'https://www.googleapis.com/auth/trace.append']}],
                                     u'tags': {u'items': [u'gke-cluster-1-93a17e13-node']}},
                     u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/global/instanceTemplates/gke-cluster-1-default-pool-fc3e27a3'}],
         u'kind': u'compute#instanceTemplateList',
         u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/global/instanceTemplates'}

    """
    data = {}

    for item in result.get("items", ()):
        properties = item.get("properties", {})

        data[get_id(item["selfLink"])] = {
            "title": item["name"],
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.ComputeInstanceTemplate",
            "properties": {
                # ComputeKind properties.
                "gce_name": item.get("name"),
                "gce_creationTimestamp": item.get("creationTimestamp"),
                "gce_kind": item.get("kind"),
                "gce_id": item.get("id"),
                "gce_selfLink": item.get("selfLink"),

                # ComputeInstanceTemplate properties.
                "set_labels": labels_list(properties.get('labels', {})),
                "description": item.get("description") or "n/a",
                "machineType": properties.get("machineType"),
                "minCpuPlatform": properties.get("minCpuPlatform") or "n/a",
                "disks_count": len(properties.get("disks", ())),
                "networkInterfaces_count": len(properties.get("networkInterfaces", ())),
            },
            "links": {
                "project": PROJECT_ID,
                "instanceGroups": [],
                "instances": [],
            },
        }

    return data


def map_zoneList(device, result):
    """Return data given compute#zoneList result.

    Example compute#zoneList result:

        {u'id': u'projects/zenoss-testing-1/zones',
         u'items': [{u'availableCpuPlatforms': [u'Intel Skylake',
                                                u'Intel Broadwell',
                                                u'Intel Haswell'],
                     u'creationTimestamp': u'1969-12-31T16:00:00.000-08:00',
                     u'description': u'us-east1-b',
                     u'id': u'2231',
                     u'kind': u'compute#zone',
                     u'name': u'us-east1-b',
                     u'region': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/regions/us-east1',
                     u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b',
                     u'status': u'UP'}],
         u'kind': u'compute#zoneList',
         u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones'}

    """
    return {
        get_id(item["selfLink"]): {
            "title": item["name"],
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.ComputeZone",
            "properties": {
                # ComputeKind properties.
                "gce_name": item.get("name"),
                "gce_creationTimestamp": item.get("creationTimestamp"),
                "gce_kind": item.get("kind"),
                "gce_id": item.get("id"),
                "gce_selfLink": item.get("selfLink"),

                # ComputeZone properties.
                "description": item.get("description"),
                "availableCpuPlatforms": item.get("availableCpuPlatforms"),
            },
            "links": {
                "project": PROJECT_ID,
                "region": get_id(item["region"]),
                "diskTypes": [],
                "disks": [],
                "instances": [],
                "instanceGroups": [],
                "machineTypes": [],
                "bigTableClusters": [],
            },
        }
        for item in result.get("items", ())
    }


def map_diskTypeList(device, result):
    """Return data given a compute#diskTypeList result.

    Example compute#diskTypeList result:

        {u'id': u'projects/zenoss-testing-1/zones/us-east1-b/diskTypes',
         u'items': [{u'creationTimestamp': u'1969-12-31T16:00:00.000-08:00',
                     u'defaultDiskSizeGb': u'375',
                     u'description': u'Local SSD',
                     u'kind': u'compute#diskType',
                     u'name': u'local-ssd',
                     u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/diskTypes/local-ssd',
                     u'validDiskSize': u'375GB-375GB',
                     u'zone': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b'}],
         u'kind': u'compute#diskTypeList',
         u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/diskTypes'}

    """
    zone_id = get_id(result["selfLink"].replace("/diskTypes", ""))

    return {
        get_id(item["selfLink"]): {
            "title": "{} / {}".format(
                item["zone"].split("/")[-1],
                item["name"]),

            "type": "ZenPacks.zenoss.GoogleCloudPlatform.ComputeDiskType",
            "properties": {
                # ComputeKind properties.
                "gce_name": item.get("name"),
                "gce_creationTimestamp": item.get("creationTimestamp"),
                "gce_kind": item.get("kind"),
                "gce_id": item.get("id") or "n/a",
                "gce_selfLink": item.get("selfLink"),

                # ComputeDiskType properties.
                "description": item.get("description"),
                "defaultDiskSize": (maybe_int(item.get("defaultDiskSizeGb")) or 0) * ONE_GiB,
                "validDiskSize": maybe_int(item.get("validDiskSize")),
            },
            "links": {
                "zone": zone_id,
                "disks": [],
            }
        }
        for item in result.get("items", ())
    }


def map_diskTypeAggregatedList(device, result):
    # TODO: Model aggregated disk types.
    return


def map_diskList(device, result):
    """Return data given a compute#diskList result.

    Example compute#diskList result.

        {u'id': u'projects/zenoss-testing-1/zones/us-east1-b/disks',
         u'items': [{u'creationTimestamp': u'2018-03-30T12:52:50.062-07:00',
                     u'guestOsFeatures': [{u'type': u'VIRTIO_SCSI_MULTIQUEUE'}],
                     u'id': u'1409068193805446014',
                     u'kind': u'compute#disk',
                     u'labelFingerprint': u'42WmSpB8rSM=',
                     u'lastAttachTimestamp': u'2018-03-30T12:52:50.072-07:00',
                     u'licenseCodes': [u'1000010'],
                     u'licenses': [u'https://www.googleapis.com/compute/v1/projects/ubuntu-os-cloud/global/licenses/ubuntu-1404-trusty'],
                     u'name': u'instance-1',
                     u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/disks/instance-1',
                     u'sizeGb': u'10',
                     u'sourceImage': u'https://www.googleapis.com/compute/v1/projects/ubuntu-os-cloud/global/images/ubuntu-1404-trusty-v20180308',
                     u'sourceImageId': u'9017273704044797360',
                     u'status': u'READY',
                     u'type': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/diskTypes/pd-standard',
                     u'users': [u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/instances/instance-1'],
                     u'zone': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b'}],
         u'kind': u'compute#diskList',
         u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/disks'}

    """
    zone_id = get_id(result["selfLink"].replace("/disks", ""))

    return {
        get_id(item["selfLink"]): {
            "title": item["name"],
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.ComputeDisk",
            "properties": {
                # ComputeKind properties.
                "gce_name": item.get("name"),
                "gce_creationTimestamp": item.get("creationTimestamp"),
                "gce_kind": item.get("kind"),
                "gce_id": item.get("id") or "n/a",
                "gce_selfLink": item.get("selfLink"),

                # ComputeDisk properties.
                "set_labels": labels_list(item.get('labels', {})),
                "size": (maybe_int(item.get("sizeGb")) or 0) * ONE_GiB,
                "lastAttachTimestamp": item.get("lastAttachTimestamp") or "n/a",
                "lastDetachTimestamp": item.get("lastDetachTimestamp") or "n/a",
            },
            "links": {
                "zone": zone_id,
                "diskType": get_id(item["type"]),
                "sourceImage": get_id(item.get("sourceImage")),
                "instances": [get_id(x) for x in item["users"]]
            }
        }
        for item in result.get("items", ())

        # Prevent modeling of unused disks.
        if item.get("users")
    }


def map_diskAggregatedList(device, result):
    # TODO: Model aggregated disks.
    return


def map_machineTypeList(device, result):
    """Return data given compute#machineTypeList result.

    Example compute#machineTypeList result:

        {u'id': u'projects/zenoss-testing-1/zones/us-east1-b/machineTypes',
         u'items': [{u'creationTimestamp': u'1969-12-31T16:00:00.000-08:00',
                     u'description': u'1 vCPU (shared physical core) and 0.6 GB RAM',
                     u'guestCpus': 1,
                     u'id': u'1000',
                     u'imageSpaceGb': 0,
                     u'isSharedCpu': True,
                     u'kind': u'compute#machineType',
                     u'maximumPersistentDisks': 16,
                     u'maximumPersistentDisksSizeGb': u'3072',
                     u'memoryMb': 614,
                     u'name': u'f1-micro',
                     u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/machineTypes/f1-micro',
                     u'zone': u'us-east1-b'}],
         u'kind': u'compute#machineTypeList',
         u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/machineTypes'}

    """
    zone_id = get_id(result["selfLink"].replace("/machineTypes", ""))

    return {
        get_id(item["selfLink"]): {
            "title": "{} / {}".format(item["zone"], item["name"]),
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.ComputeMachineType",
            "properties": {
                # ComputeKind properties.
                "gce_name": item.get("name"),
                "gce_creationTimestamp": item.get("creationTimestamp"),
                "gce_kind": item.get("kind"),
                "gce_id": item.get("id") or "n/a",
                "gce_selfLink": item.get("selfLink"),

                # ComputeMachineType
                "description": item.get("description"),
                "guestCpus": item.get("guestCpus"),
                "isSharedCpu": item.get("isSharedCpu"),
                "memory": (maybe_int(item.get("memoryMb")) or 0) * ONE_MiB,
                "maximumPersistentDisks": maybe_int(item.get("maximumPersistentDisks")),
                "maximumPersistentDisksSize": (maybe_int(item.get("maximumPersistentDisksSizeGb")) or 0) * ONE_GiB,
                "imageSpace": (maybe_int(item.get("imageSpaceGb")) or 0) * ONE_GiB,
            },
            "links": {
                "zone": zone_id,
                "instances": [],
            }
        }
        for item in result.get("items", ())
    }


def map_machineTypeAggregatedList(device, result):
    # TODO: Model aggregated machine types.
    return


def map_instanceList(device, result):
    """Return data given a compute#instanceList result.

    Example compute#instanceList:

        {u'id': u'projects/zenoss-testing-1/zones/us-east1-b/instances',
         u'items': [{u'canIpForward': False,
                     u'cpuPlatform': u'Intel Haswell',
                     u'creationTimestamp': u'2018-03-30T12:52:49.999-07:00',
                     u'deletionProtection': False,
                     u'description': u'',
                     u'disks': [{u'autoDelete': True,
                                 u'boot': True,
                                 u'deviceName': u'instance-1',
                                 u'guestOsFeatures': [{u'type': u'VIRTIO_SCSI_MULTIQUEUE'}],
                                 u'index': 0,
                                 u'interface': u'SCSI',
                                 u'kind': u'compute#attachedDisk',
                                 u'licenses': [u'https://www.googleapis.com/compute/v1/projects/ubuntu-os-cloud/global/licenses/ubuntu-1404-trusty'],
                                 u'mode': u'READ_WRITE',
                                 u'source': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/disks/instance-1',
                                 u'type': u'PERSISTENT'}],
                     u'id': u'6963158289963232127',
                     u'kind': u'compute#instance',
                     u'labelFingerprint': u'FSGLKeMC9y4=',
                     u'labels': {u'environment': u'test',
                                 u'organization': u'engineering',
                                 u'owner': u'cluther'},
                     u'machineType': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/machineTypes/f1-micro',
                     u'metadata': {u'fingerprint': u'k9KaJVcSb9s=',
                                   u'kind': u'compute#metadata'},
                     u'name': u'instance-1',
                     u'networkInterfaces': [{u'accessConfigs': [{u'kind': u'compute#accessConfig',
                                                                 u'name': u'External NAT',
                                                                 u'natIP': u'35.185.71.98',
                                                                 u'type': u'ONE_TO_ONE_NAT'}],
                                             u'fingerprint': u'1btdElNQ1NQ=',
                                             u'kind': u'compute#networkInterface',
                                             u'name': u'nic0',
                                             u'network': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/global/networks/default',
                                             u'networkIP': u'10.142.0.2',
                                             u'subnetwork': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/regions/us-east1/subnetworks/default'}],
                     u'scheduling': {u'automaticRestart': True,
                                     u'onHostMaintenance': u'MIGRATE',
                                     u'preemptible': False},
                     u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/instances/instance-1',
                     u'serviceAccounts': [{u'email': u'469482109134-compute@developer.gserviceaccount.com',
                                           u'scopes': [u'https://www.googleapis.com/auth/devstorage.read_only',
                                                       u'https://www.googleapis.com/auth/logging.write',
                                                       u'https://www.googleapis.com/auth/monitoring.write',
                                                       u'https://www.googleapis.com/auth/servicecontrol',
                                                       u'https://www.googleapis.com/auth/service.management.readonly',
                                                       u'https://www.googleapis.com/auth/trace.append']}],
                     u'startRestricted': False,
                     u'status': u'RUNNING',
                     u'tags': {u'fingerprint': u'FYLDgkTKlA4=',
                               u'items': [u'http-server']},
                     u'zone': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b'}],
         u'kind': u'compute#instanceList',
         u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/instances'}

    """
    data = {}
    # Return empty data if no items to process.
    if not result.get('items'):
        return data

    use_natIP = getattr(device, "zGoogleCloudPlatformGuestUseExternalIP", False)

    # guest_label_dc_map provides {labels => device_classes} for guest devices.
    guest_label_dc_map = getLabelToDeviceClassMap(device.zGoogleCloudPlatformGuestLabels)
    zguest_label_rx = guest_label_dc_map.keys()

    discovered_guest_ids = []
    #Allow mapping to work with instance.get()
    zone_id = get_id(result.get("selfLink", '').replace("/instances", ""))

    for item in result.get("items", ()):
        instance_id = get_id(item["selfLink"])

        instance_networkIPs = []
        instance_natIPs = []

        for nic_item in item.get("networkInterfaces", ()):
            nic_id = "{}_{}".format(
                instance_id.replace("instance_", "networkInterface_"),
                nic_item["name"])

            nic_networkIP = nic_item.get("networkIP")
            if nic_networkIP:
                instance_networkIPs.append(nic_networkIP)

            accessConfigs = nic_item.get("accessConfigs", ())
            accessConfig0 = next(iter(accessConfigs), {})
            nic_natIPs = []

            for accessConfig in accessConfigs:
                natIP = accessConfig.get("natIP")
                if natIP:
                    nic_natIPs.append(natIP)
                    instance_natIPs.append(natIP)

            data[nic_id] = {
                "title": "{} / {}".format(item["name"], nic_item["name"]),
                "type": "ZenPacks.zenoss.GoogleCloudPlatform.ComputeNetworkInterface",
                "properties": {
                    # ComputeKind properties.
                    "gce_name": nic_item.get("name"),
                    "gce_creationTimestamp": item.get("creationTimestamp") or "n/a",
                    "gce_kind": nic_item.get("kind"),
                    "gce_id": nic_item.get("id") or "n/a",
                    "gce_selfLink": nic_item.get("selfLink") or "n/a",

                    # ComputeNetworkInterface properties.
                    "networkIP": nic_networkIP,
                    "accessConfig0_name": accessConfig0.get("name") or "n/a",
                    "accessConfig0_type": accessConfig0.get("type") or "n/a",
                    "natIPs": nic_natIPs,
                },
                "links": {
                    "instance": instance_id,
                }
            }

        instanceTemplate = None
        inKubernetesCluster = False

        for metadata_item in item.get("metadata", {}).get("items", ()):
            metadata_key = metadata_item.get("key")
            if metadata_key == "instance-template":
                instanceTemplate = metadata_item.get("value")
            if metadata_key == "kube-env":
                inKubernetesCluster = True

        manageIP = {
            True: instance_natIPs[0] if instance_natIPs else None,
            False: instance_networkIPs[0] if instance_networkIPs else None,
        }.get(use_natIP)

        instance_labels = labels_list(item.get('labels', {}))

        # Create the list of instances for Zones.discoveredGuests() as well
        # as derivedProductionState properties.
        derivedProductionState = None
        shared_label = find_first_shared_label(zguest_label_rx, instance_labels)
        if shared_label and device.zGoogleCloudPlatformDiscoverGuests:

            # Status is used only to determine what the derivedProductionState
            status = item.get('status', 'UNKNOWN')
            derivedProductionState = guest_status_prodState_map(status)

            discovered_guest_ids.append(instance_id)

        data[instance_id] = {
            "title": item["name"],
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.ComputeInstance",
            "properties": {
                # ComputeKind properties.
                "gce_name": item.get("name"),
                "gce_creationTimestamp": item.get("creationTimestamp"),
                "gce_kind": item.get("kind"),
                "gce_id": item.get("id") or "n/a",
                "gce_selfLink": item.get("selfLink"),

                # ComputeInstance properties.
                "set_labels": instance_labels,
                "description": item.get("description") or "n/a",
                "cpuPlatform": item.get("cpuPlatform") or "n/a",
                "manageIP": manageIP,
                "networkIPs": instance_networkIPs,
                "natIPs": instance_natIPs,
                "canIpForward": item.get("canIpForward"),
                "inKubernetesCluster": inKubernetesCluster,

                # Guest Device Properties
                # We retain derivedProductionState as a property because 'status'
                # (via monitoring) is not readily available at model time.
                "derivedProductionState": derivedProductionState,
            }
        }

        if not zone_id:
            zone_id = get_id(item.get("zone"))
            data[instance_id]['links'] = {
                "zone": zone_id,
                "networkInterfaces": [],
            }
        else:
            data[instance_id]['links'] = {
                "zone": zone_id,
                "instanceTemplate": get_id(instanceTemplate),
                "machineType": get_id(item["machineType"]),
                "networkInterfaces": [],
            }

    # Set the zone_id's instance_state to trigger Guest Device management.
    # This gets added to the existing Zone map data and eventually processed.
    # Make sure you have discovered_guest_ids and zGoogleCloudPlatformDiscoverGuests
    # NOTE: The "delay" param tells mapper.py to put this at end of maps so
    #       that the instance will exist prior to instance handling.
    if discovered_guest_ids and device.zGoogleCloudPlatformDiscoverGuests:
        data[zone_id] = {
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.ComputeZone",
            "properties": {
                'set_discoverGuests': discovered_guest_ids,
            },
            "links": {},
            "delay": 'set_discoverGuests'
        }

    return data


def map_instanceAggregatedList(device, result):
    # TODO: Model aggregated instances.
    return


def map_instanceGroupList(device, result):
    """Return data given a compute#instanceGroup result.

    Example compute#instanceGroup result:

        {u'id': u'projects/zenoss-testing-1/zones/us-east1-b/instanceGroups',
         u'items': [{u'creationTimestamp': u'2018-03-30T12:54:54.635-07:00',
                     u'description': u"This instance group is controlled by Instance Group Manager 'instance-group-2'. To modify instances in this group, use the Instance Group Manager API: https://cloud.google.com/compute/docs/reference/latest/instanceGroupManagers",
                     u'fingerprint': u'42WmSpB8rSM=',
                     u'id': u'5638735103389804769',
                     u'kind': u'compute#instanceGroup',
                     u'name': u'instance-group-2',
                     u'network': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/global/networks/default',
                     u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/instanceGroups/instance-group-2',
                     u'size': 1,
                     u'subnetwork': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/regions/us-east1/subnetworks/default',
                     u'zone': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b'}],
         u'kind': u'compute#instanceGroupList',
         u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/instanceGroups'}

    """
    zone_id = get_id(result["selfLink"].replace("/instanceGroups", ""))

    return {
        get_id(item["selfLink"]): {
            "title": item["name"],
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.ComputeInstanceGroup",
            "properties": {
                # ComputeKind properties.
                "gce_name": item.get("name"),
                "gce_creationTimestamp": item.get("creationTimestamp"),
                "gce_kind": item.get("kind"),
                "gce_id": item.get("id") or "n/a",
                "gce_selfLink": item.get("selfLink"),

                # ComputeInstanceGroup properties.
                "description": item.get("description") or "n/a",
                "multi_zone": False,
                "size": item.get("size"),
            },
            "links": {
                "container": zone_id,
                # instances relationship is deprecated (ZPS-4695)
                "instances": [],
                "instances2": [],
            }
        }
        for item in result.get("items", [])
    }


def map_instanceGroupManagerList(device, result):
    """Return data given a compute#instanceGroupManagerList result.

    Example compute#instanceGroupManagerList result:

        {u'id': u'projects/zenoss-testing-1/zones/us-east1-b/instanceGroupManagers',
         u'items': [{u'baseInstanceName': u'instance-group-2',
                     u'creationTimestamp': u'2018-03-30T12:54:54.634-07:00',
                     u'currentActions': {u'abandoning': 0,
                                         u'creating': 0,
                                         u'creatingWithoutRetries': 0,
                                         u'deleting': 0,
                                         u'none': 1,
                                         u'recreating': 0,
                                         u'refreshing': 0,
                                         u'restarting': 0},
                     u'fingerprint': u'zpCM40FrHKY=',
                     u'id': u'5638735103389804769',
                     u'instanceGroup': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/instanceGroups/instance-group-2',
                     u'instanceTemplate': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/global/instanceTemplates/instance-template-1',
                     u'kind': u'compute#instanceGroupManager',
                     u'name': u'instance-group-2',
                     u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/instanceGroupManagers/instance-group-2',
                     u'targetSize': 1,
                     u'zone': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b'}],
         u'kind': u'compute#instanceGroupManagerList',
         u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/instanceGroupManagers'}

    """
    return {
        get_id(item["instanceGroup"]): {
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.ComputeInstanceGroup",
            "properties": {
                # ComputeInstanceGroup properties.
                "managed": True,
                "multi_zone": False,
                "targetSize": item.get("targetSize"),
                "baseInstanceName": item.get("baseInstanceName") or "n/a",
            },
            "links": {
                "instanceTemplate": get_id(item.get("instanceTemplate")),
            },
        }
        for item in result.get("items", ())
    }


def map_instanceGroupsListInstances(device, result):
    """Return data given a compute#instanceGroupsListInstances result.

    Example compute#instanceGroupsListInstances result:

        {u'items': [{u'instance': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/instances/instance-2',
                     u'status': u'RUNNING'}],
         u'kind': u'compute#instanceGroupsListInstances',
         u'path': u'projects/zenoss-testing-1/zones/us-east1-b/instanceGroups/instance-group-3'}

    """
    return {
        get_id(result["path"]): {
            "links": {
                # instances relationship is deprecated (ZPS-4695)
                "instances": [],
                "instances2": [
                    get_id(x["instance"])
                    for x in result.get("items", ())]}}}


def map_instanceGroupAggregatedList(device, result):
    # TODO: Model aggregated instance groups. (region & zone)
    return


def map_regionInstanceGroupList(device, result):
    """Return data given a compute#regionInstanceGroupList result.

    Example compute#regionInstanceGroupList result:

        {u'id': u'projects/zenoss-testing-1/regions/us-east1/instanceGroups',
         u'items': [{u'creationTimestamp': u'2018-03-30T12:54:38.966-07:00',
                     u'description': u"This instance group is controlled by Regional Instance Group Manager 'instance-group-1'. To modify instances in this group, use the Regional Instance Group Manager API: https://cloud.google.com/compute/docs/reference/latest/instanceGroupManagers",
                     u'fingerprint': u'42WmSpB8rSM=',
                     u'id': u'6502687076563233553',
                     u'kind': u'compute#instanceGroup',
                     u'name': u'instance-group-1',
                     u'network': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/global/networks/default',
                     u'region': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/regions/us-east1',
                     u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/regions/us-east1/instanceGroups/instance-group-1',
                     u'size': 1,
                     u'subnetwork': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/regions/us-east1/subnetworks/default'}],
         u'kind': u'compute#regionInstanceGroupList',
         u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/regions/us-east1/instanceGroups'}

    """
    region_id = get_id(result["selfLink"].replace("/instanceGroups", ""))

    return {
        get_id(item["selfLink"]): {
            "title": item["name"],
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.ComputeInstanceGroup",
            "properties": {
                # ComputeKind properties.
                "gce_name": item.get("name"),
                "gce_creationTimestamp": item.get("creationTimestamp"),
                "gce_kind": item.get("kind"),
                "gce_id": item.get("id") or "n/a",
                "gce_selfLink": item.get("selfLink"),

                # ComputeInstanceGroup properties.
                "description": item.get("description") or "n/a",
                "multi_zone": True,
                "size": item.get("size"),
            },
            "links": {
                "container": region_id,
                # instances relationship is deprecated (ZPS-4695)
                "instances": [],
                "instances2": [],
            }
        }
        for item in result.get("items", [])
    }


def map_regionInstanceGroupManagerList(device, result):
    """Return data given a compute#regionInstanceGroupManagerList result.

    Example compute#regionInstanceGroupManagerList result:

        {u'id': u'projects/zenoss-testing-1/regions/us-east1/instanceGroupManagers',
         u'items': [{u'baseInstanceName': u'instance-group-1',
                     u'creationTimestamp': u'2018-03-30T12:54:38.963-07:00',
                     u'currentActions': {u'abandoning': 0,
                                         u'creating': 0,
                                         u'creatingWithoutRetries': 0,
                                         u'deleting': 0,
                                         u'none': 1,
                                         u'recreating': 0,
                                         u'refreshing': 0,
                                         u'restarting': 0},
                     u'fingerprint': u'zpCM40FrHKY=',
                     u'id': u'6502687076563233553',
                     u'instanceGroup': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/regions/us-east1/instanceGroups/instance-group-1',
                     u'instanceTemplate': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/global/instanceTemplates/instance-template-1',
                     u'kind': u'compute#instanceGroupManager',
                     u'name': u'instance-group-1',
                     u'region': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/regions/us-east1',
                     u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/regions/us-east1/instanceGroupManagers/instance-group-1',
                     u'targetSize': 1}],
         u'kind': u'compute#regionInstanceGroupManagerList',
         u'selfLink': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/regions/us-east1/instanceGroupManagers'}

    """
    return {
        get_id(item["instanceGroup"]): {
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.ComputeInstanceGroup",
            "properties": {
                # ComputeInstanceGroup properties.
                "managed": True,
                "targetSize": item.get("targetSize"),
                "baseInstanceName": item.get("baseInstanceName") or "n/a",
            },
            "links": {
                "instanceTemplate": get_id(item.get("instanceTemplate")),
            },
        }
        for item in result.get("items", ())
    }


def map_autoscalerAggregatedList(device, result):
    """Return data given a compute#autoscalerAggregatedList result.

    Example compute#autoscalerAggregatedList result:

    {
     "kind": "compute#autoscalerAggregatedList",
     "id": "projects/zenoss-testing-1/aggregated/autoscalers",
     "items": {
       "regions/europe-west1": {
           "warning": {
            "code": "NO_RESULTS_ON_PAGE",
            "message": "There are no results for scope 'regions/europe-west1' on this page.",
            "data": [
             {
              "key": "scope",
              "value": "regions/europe-west1"
             }
            ]
           }
          },
      "zones/us-east1-b": {
       "autoscalers": [
        {

         "kind": "compute#autoscaler",
         "id": "9185690547226093812",
         "creationTimestamp": "2018-03-30T12:55:07.450-07:00",
         "name": "instance-group-2",
         "target": "https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/instanceGroupManagers/instance-group-2",
         "autoscalingPolicy": {
          "minNumReplicas": 1,
          "maxNumReplicas": 10,
          "coolDownPeriodSec": 60,
          "cpuUtilization": {
           "utilizationTarget": 0.6
          }
         },
         "zone": "https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b",
         "selfLink": "https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-b/autoscalers/instance-group-2",
         "status": "ACTIVE"
        }
       ]
      },
     },
     "selfLink": "https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/aggregated/autoscalers"
    }

    """

    data = {}
    regions = result.get("items", {})
    for region in regions.keys():
        for item in regions[region].get('autoscalers', []):
            autoscalingPolicy = item.get("autoscalingPolicy", {})
            data[get_id(item["target"].replace('/instanceGroupManagers/', '/instanceGroups/', 1))] = {
                "type": "ZenPacks.zenoss.GoogleCloudPlatform.ComputeInstanceGroup",
                "properties": {
                    # ComputeInstanceGroup properties.
                    "maxInstances": autoscalingPolicy.get("maxNumReplicas"),
                    "minInstances": autoscalingPolicy.get("minNumReplicas"),
                    "utilizationTarget": autoscalingPolicy.get("cpuUtilization", {}).get('utilizationTarget', 0) * 100,

                },
                "links": {},
            }

    return data


def map_regionInstanceGroupsListInstances(device, result):
    """Return data given a compute#regionInstanceGroupsListInstances result.

    Example compute#regionInstanceGroupsListInstances result:

        {u'items': [{u'instance': u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-east1-c/instances/instance-group-1-snjm',
                     u'status': u'RUNNING'}],
         u'kind': u'compute#regionInstanceGroupsListInstances',
         u'path': u'projects/zenoss-testing-1/regions/us-east1/instanceGroups/instance-group-1'}

    """
    return {
        get_id(result["path"]): {
            "links": {
                # instances relationship is deprecated (ZPS-4695)
                "instances": [],
                "instances2": [
                    get_id(x["instance"])
                    for x in result.get("items", ())]}}}


def map_kubernetesClusterList(device, result):
    """Return data given Kubernetes clusters list.

    Example result:

    {
        u'clusterIpv4Cidr': u'10.8.0.0/14',
        u'currentMasterVersion': u'1.8.8-gke.0',
        u'currentNodeCount': 3,
        u'currentNodeVersion': u'1.8.8-gke.0',
        u'endpoint': u'35.224.237.223',
        u'initialClusterVersion': u'1.8.8-gke.0',
        u'instanceGroupUrls': [u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-central1-a/instanceGroupManagers/gke-cluster-1-default-pool-fc3e27a3-grp'],
        u'locations': [u'us-central1-a'],
        u'loggingService': u'logging.googleapis.com',
        u'monitoringService': u'monitoring.googleapis.com',
        u'name': u'cluster-1',
        u'network': u'default',
        u'networkPolicy': {u'provider': u'CALICO'},
        u'subnetwork': u'default',
        u'nodeConfig': {u'diskSizeGb': 100,
                        u'imageType': u'COS',
                        u'machineType': u'g1-small',
                        u'serviceAccount': u'default'},
        u'nodeIpv4CidrSize': 24,
        u'nodePools':
           [{u'autoscaling': {},
             u'config': {u'diskSizeGb': 100,
                         u'imageType': u'COS',
                         u'machineType': u'g1-small',
                         u'serviceAccount': u'default'},
             u'initialNodeCount': 3,
             u'instanceGroupUrls': [u'https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-central1-a/instanceGroupManagers/gke-cluster-1-default-pool-fc3e27a3-grp'],
             u'name': u'default-pool',
             u'selfLink': u'https://container.googleapis.com/v1/projects/zenoss-testing-1/zones/us-central1-a/clusters/cluster-1/nodePools/default-pool',
             u'status': u'RUNNING',
             u'version': u'1.8.8-gke.0'}],
        u'servicesIpv4Cidr': u'10.11.240.0/20',
        u'status': u'RUNNING',
        u'selfLink': u'https://container.googleapis.com/v1/projects/zenoss-testing-1/zones/us-central1-a/clusters/cluster-1',
        u'zone': u'us-central1-a'}

    """
    data = {}
    for cluster in result.get("clusters"):
        data.update({
            get_id(cluster["selfLink"]): {
                "title": "{} / {}".format(
                    cluster["zone"],
                    cluster["name"]),
                "type": "ZenPacks.zenoss.GoogleCloudPlatform.KubernetesCluster",
                "properties": {
                    "gke_name": cluster.get("name"),
                    "clusterIpv4Cidr": cluster.get("clusterIpv4Cidr"),
                    "currentMasterVersion": cluster.get("currentMasterVersion"),
                    "loggingService": cluster.get("loggingService"),
                    "monitoringService": cluster.get("monitoringService"),
                    "endpoint": cluster.get("endpoint"),
                    "network": cluster.get("network"),
                    "subnetwork": cluster.get("subnetwork"),
                    "currentNodeCount": cluster.get("currentNodeCount"),
                    "initialClusterVersion": cluster.get("initialClusterVersion"),
                    "nodeIpv4CidrSize": maybe_int(cluster.get("nodeIpv4CidrSize")),
                    "servicesIpv4Cidr": cluster.get("servicesIpv4Cidr"),
                    "gke_creationTimestamp": cluster.get("createTime"),
                    "selfLink": cluster.get("selfLink"),
                    "set_labels": labels_list(cluster.get('resourceLabels', {})),
                },
                "links": {
                    "project": PROJECT_ID,
                    "zones": [
                        "zone_{}".format(x)
                        for x in cluster["locations"]],
                    "nodePools": [
                        get_id(x.get("selfLink"))
                        for x in cluster.get("nodePools")],
                }
            }
        })

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

    # LOG.debug('XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX')
    # LOG.debug('map_kubernetesClusterList data: {}'.format(data))


    return data


def map_gcpFunctionList(device, result):
    """Return data given clusters list.

    Example result:

    {
      "name": "projects/zenoss-testing-1/locations/us-central1/functions/funcGoogleAnalycisForFirebase",
      "eventTrigger": {
        "eventType": "providers/google.firebase.analytics/eventTypes/event.log",
        "resource": "projects/zenoss-testing-1/events/SuperLogger",
        "service": "app-measurement.com",
        "failurePolicy": {}
      },
      "status": "UNKNOWN",
      "entryPoint": "helloAnalytics",
      "timeout": "60s",
      "availableMemoryMb": 256,
      "serviceAccountEmail": "zenoss-testing-1@appspot.gserviceaccount.com",
      "updateTime": "2019-06-10T19:14:48Z",
      "versionId": "1",
      "labels": {
        "deployment-tool": "console-cloud"
      },
      "sourceUploadUrl": "https://storage.googleapis.com/.........",
      "runtime": "nodejs8"
    }

    """
    data = {}
    whitelist = 'zGoogleCloudPlatformFunctionWhitelist'
    model_regex = validate_modeling_regex(device, whitelist)
    if not model_regex:
        return data

    for function in result.get("functions"):
        parts = function["name"].split('/')
        region_path = '/'.join(parts[:-2])  # Strip off functions/name part
        region_id = get_id(region_path)
        short_name = parts[-1]

        # Check zProperty for functions to be modeled.
        if not re.match(model_regex, str(short_name)):
            continue

        # Get service type. If not eventTrigger, maybe httpsTrigger, else None
        service = function.get('eventTrigger', {}).get('service')
        if not service and function.get('httpsTrigger'):
            service = 'httpsTrigger'

        available_memory = function.get("availableMemoryMb") * 2**20

        data.update({
            get_id(function["name"]): {
                "title": short_name,
                "type": "ZenPacks.zenoss.GoogleCloudPlatform.CloudFunction",
                "properties": {
                    "set_labels": labels_list(function.get('labels', {})),
                    "function_name": function.get("name"),
                    "service": service,
                    "runtime": function.get("runtime"),
                    "status": function.get("status"),
                    "availableMemory": available_memory,
                    "serviceAccountEmail": function.get("serviceAccountEmail"),
                },
                "links": {
                    "region": region_id,
                }
            }
        })

    return data


def map_datasetList(device, result):
    """ Return data given BigQuery dataset list.

    Example Result:
    {u'datasets': [
        {u'access': [{u'role': u'WRITER',
                      u'specialGroup': u'projectWriters'},
                     {u'role': u'OWNER',
                      u'specialGroup': u'projectOwners'},
                     {u'role': u'OWNER',
                      u'userByEmail': u'export-composer@jenkins-zing-project.iam.gserviceaccount.com'},
                     {u'role': u'READER',
                      u'specialGroup': u'projectReaders'}],
         u'creationTime': u'1566841437475',
         u'datasetReference': {u'datasetId': u'zenoss_version',
                               u'projectId': u'zing-dev-197522'},
         u'etag': u'FMn9JzAFYS8a/+wq18oQHw==',
         u'id': u'zing-dev-197522:zenoss_version',
         u'kind': u'bigquery#dataset',
         u'lastModifiedTime': u'1566841437475',
         u'location': u'US',
         u'selfLink': u'https://www.googleapis.com/bigquery/v2/projects/zing-dev-197522/datasets/zenoss_version'}
     ],
     u'etag': u'Xk7y/G/7FTUTgljUo9IJ1w==',
     u'kind': u'bigquery#datasetList'}
    """

    data = {}
    for dataset in result.get("datasets"):
        if 'datasetReference' not in dataset:
            continue

        dataset_name = str(dataset['datasetReference']['datasetId'])

        creationTime = dataset.get('creationTime', "")
        if creationTime:
            creationTime = datetime.utcfromtimestamp(float(creationTime)/1000)

        lastModTime = dataset.get('lastModifiedTime', "")
        if lastModTime:
            lastModTime = datetime.utcfromtimestamp(float(lastModTime)/1000)

        # Extract and process data.
        dataset_id = "dataset_" + dataset_name
        data[dataset_id] = {
            "title": dataset_name,
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.BigQuery",
            "properties": {
                "location": dataset.get('location', ""),
                "friendlyName": dataset.get('friendlyName', ""),
                "creationTime": creationTime,
                "lastModifiedTime": lastModTime,
                "access": dataset.get('access', ""),
            },
            "links": {
                "project": PROJECT_ID,
            }
        }
    return data


def map_dataflowJobsList(device, result):
    """ Return data given Dataflow jobs list.

    Example result:
    {
        "id": "2019-05-30_09_01_00-13747437200176369199",
        "projectId": "zing-dev-197522",
        "name": "iso-forest",
        "type": "JOB_TYPE_BATCH",
        "currentState": "JOB_STATE_DONE",
        "currentStateTime": "2019-05-30T16:07:27.819670Z",
        "createTime": "2019-05-30T16:01:01.380908Z",
        "location": "us-central1",
        "jobMetadata": {
            "sdkVersion": {
                "version": "2.6.0",
                "versionDisplayName": "Apache Beam SDK for Python",
                "sdkSupportStatus": "STALE"
            }
       },
       "startTime": "2019-05-30T16:01:01.380908Z"
    }

    Example Job States (12):
    Unknown, Stopped, Running, Done, Failed, Cancelled, Updated, Draining,
    Drained, Pending, Cancelling, Queued.

    Example Job Types (3):
    Unknown, Batch, Streaming.
    """
    data = {}
    whitelist = 'zGoogleCloudPlatformDataflowJobNamesModeled'
    model_regex = validate_modeling_regex(device, whitelist)
    if not model_regex:
        return data

    for job in result.get("jobs"):
        dataflow_name = str(job.get("name"))
        # Check zProperty for jobs to be modeled.
        if not re.match(model_regex, dataflow_name):
            continue

        # Extract and process data.
        dataflow_id = "dataflow_" + dataflow_name
        current_job_time = job.get("currentStateTime")
        job_type = job.get("type", "").replace("JOB_TYPE_", "").title()
        sdk_info = job.get("jobMetadata", {}).get("sdkVersion", {})
        region_id = "region_" + str(job.get("location"))

        # Map data to properties if needed.
        if dataflow_id not in data:
            # Add all data to mapping.
            data[dataflow_id] = {
                "title": dataflow_name,
                "type": "ZenPacks.zenoss.GoogleCloudPlatform.Dataflow",
                "properties": {
                    "job_type": job_type,
                    "currentStateTime": current_job_time,
                    "createTime": job.get("createTime"),
                    "startTime": job.get("startTime"),
                    "version": sdk_info.get("version"),
                    "versionDisplayName": sdk_info.get("versionDisplayName"),
                    "sdkSupportStatus": sdk_info.get("sdkSupportStatus")
                },
                "links": {
                    "project": PROJECT_ID,
                    "regions": [region_id]
                }
            }

        else:
            # Data exists, map latest data only.
            properties = data[dataflow_id]["properties"]
            links = data[dataflow_id]["links"]
            data_time = properties.get("currentStateTime")
            if is_greater_timestamp(current_job_time, data_time):
                properties["currentStateTime"] = current_job_time
                properties["createTime"] = job.get("createTime")
                properties["startTime"] = job.get("startTime")
                if region_id not in links["regions"]:
                    links["regions"].append(region_id)
    return data


def map_buckets(device, result):
    """Return data given storage#bucket result.

    Example storage#bucket result:

        {
           "kind": "storage#bucket",
           "id": "artifacts.zenoss-testing-1.appspot.com",
           "selfLink": "https://www.googleapis.com/storage/v1/b/artifacts.zenoss-testing-1.appspot.com",
           "projectNumber": "469482109134",
           "name": "artifacts.zenoss-testing-1.appspot.com",
           "timeCreated": "2018-10-30T16:31:22.678Z",
           "updated": "2018-10-30T16:31:22.678Z",
           "metageneration": "1",
           "iamConfiguration": {
            "bucketPolicyOnly": {
             "enabled": false
            },
            "uniformBucketLevelAccess": {
             "enabled": false
            }
           },
           "location": "US",
           "locationType": "multi-region",
           "storageClass": "STANDARD",
           "etag": "CAE="}

    """
    return {
        prepId('bucket_' + item["id"]): {
            "title": item["name"],
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.StorageBucket",
            "properties": {
                # ComputeZone properties.
                "storageClass": item.get("storageClass"),
                "timeCreated": item.get("timeCreated"),
                "updated": item.get("updated"),
                "location": item.get("location"),
                "locationType": item.get("locationType"),
                "set_labels": labels_list(item.get('labels', {})),
            },
            "links": {
                "project": PROJECT_ID,
            },
        }
        for item in result.get("items", ())
    }


def map_bigTableInstanceList(device, result):
    """Return data given BigTable Instances result.

    Example BigTable Instances result:

        {
         "instances": [
          {
           "name": "projects/zing-dev-197522/instances/zenoss-zing-bt1",
           "displayName": "zenoss-zing-bt1",
           "state": "READY",
           "type": "DEVELOPMENT"
          }
         ]
        }

    """

    data = {}
    model_regex = validate_modeling_regex(device, 'zGoogleCloudPlatformBigTableInstancesModeled')

    for item in result.get("instances", ()):
        fullname = item["name"]
        name = fullname.split('/')[-1]

        if not re.match(model_regex, name) and not re.match(model_regex, item["displayName"]):
            continue

        bginstanceid = 'bigtableinstance_' + name
        data[prepId(bginstanceid)] = {
            "title": name,
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.BigTableInstance",
            "properties": {
                "displayName": item["displayName"],
                "fullname": fullname,
                "instanceType": item.get("type"),
                "set_labels": labels_list(item.get('labels', {})),
            },
            "links": {
                "project": PROJECT_ID,
                "bigTableClusters": [],
            },
        }
    return data


def map_bigTableClusterList(device, result):
    """Return data given BigTable Cluster result.

    {
     "clusters": [
      {
       "name": "projects/zenoss-testing-1/instances/zenoss-zing-bt1/clusters/zenoss-zing-bt1-cluster",
       "location": "projects/zenoss-testing-1/locations/us-central1-f",
       "state": "READY",
       "defaultStorageType": "HDD"
      }
     ]
    }


    """

    data = {}
    model_regex = validate_modeling_regex(device, 'zGoogleCloudPlatformBigTableClustersModeled')
    instance_regex = validate_modeling_regex(device, 'zGoogleCloudPlatformBigTableInstancesModeled')
    if not instance_regex:
        return data
    for item in result.get("clusters", ()):
        fullname = item['name']
        name = fullname.split('/')[-1]
        instance = fullname.split('/')[-3]
        if not re.match(model_regex, name) or not re.match(instance_regex, instance):
            continue
        bgclusterid = 'bigtablecluster_' + name
        zone = item['location'].split('/')[-1]

        data[prepId(bgclusterid)] = {
            "title": name,
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.BigTableCluster",
            "properties": {
                "serveNodes": item.get('serveNodes', 1),
                "defaultStorageType": item.get("defaultStorageType"),
                "fullname": fullname,
            },
            "links": {
                "bigTableInstance": prepId('bigtableinstance_' + instance),
                "zone": prepId('zone_' + zone),
            },
        }
    return data


def map_bigTableAppProfilesList(device, result):
    """Return data given BigTable AppProfiles result.

    {
     "appProfiles": [
      {
       "name": "projects/zcloud-prod/instances/zenoss-zing-bt1/appProfiles/anomaly-search-svc",
       "multiClusterRoutingUseAny": {
       }
      },
      {
       "name": "projects/zcloud-prod/instances/zenoss-zing-bt1/appProfiles/dataflow-anomaly-ingest",
       "singleClusterRouting": {
        "clusterId": "zenoss-zing-bt1-cluster",
        "allowTransactionalWrites": true
       }
      }
      ]
    }


    """

    data = {}
    model_regex = validate_modeling_regex(device, 'zGoogleCloudPlatformBigTableAppProfilesModeled')
    instance_regex = validate_modeling_regex(device, 'zGoogleCloudPlatformBigTableInstancesModeled')
    if not instance_regex:
        return data
    for item in result.get("appProfiles", ()):
        fullname = item['name']
        name = fullname.split('/')[-1]
        instance = fullname.split('/')[-3]
        if not re.match(model_regex, name) or not re.match(instance_regex, instance):
            continue
        profileid = get_id(fullname)
        clusterId = []
        singleClusterRoute = item.get('singleClusterRouting', {})
        clusterRouting = "Multiple"
        if singleClusterRoute:
            clusterId = prepId('bigtablecluster_' + singleClusterRoute.get('clusterId'))
            clusterRouting = "Single"
        data[prepId(profileid)] = {
            "title": name,
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.BigTableAppProfile",
            "properties": {
                "fullname": fullname,
                "allowTransactionalWrites": bool(singleClusterRoute.get('allowTransactionalWrites', False)),
                "clusterRouting": clusterRouting,
            },
            "links": {
                "bigTableInstance": prepId('bigtableinstance_' + instance),
                "bigTableCluster": clusterId,
            },
        }
    return data


def map_bigTableTablesList(device, result):
    """Return data given BigTable Table result.

    "tables": [
      {
       "name": "projects/zing-dev-197522/instances/zenoss-zing-bt1/tables/ANOMALY_V2"
      },
      {
       "name": "projects/zing-dev-197522/instances/zenoss-zing-bt1/tables/DEAD_LETTER_QUEUE_V2"
      },
      ]


    """

    data = {}
    model_regex = validate_modeling_regex(device, 'zGoogleCloudPlatformBigTableTablesModeled')

    for item in result.get("tables", ()):
        fullname = item['name']
        name = fullname.split('/')[-1]
        if not re.match(model_regex, name):
            continue
        instance = fullname.split('/')[-3]
        tableId = get_id(fullname)

        data[prepId(tableId)] = {
            "title": name,
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.BigTableTable",
            "properties": {
                "fullname": fullname,
            },
            "links": {
                "bigTableInstance": prepId('bigtableinstance_' + instance),
            },
        }
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
