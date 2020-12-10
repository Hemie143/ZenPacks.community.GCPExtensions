
# Default Exports
__all__ = [
    "CollectorExt",
    "process",
]

# stdlib Imports
import logging
import re

# ZenPack Imports
from Products.ZenUtils.Utils import prepId
from ZenPacks.zenoss.GoogleCloudPlatform.modeling import validate_modeling_regex, CollectorOptions, Collector
from ZenPacks.zenoss.GoogleCloudPlatform.mapper import DataMapper
from ZenPacks.zenoss.GoogleCloudPlatform.zopeutils import get_id
from . import txgcp

LOG = logging.getLogger("zen.GCPExtensions")

# Static keyword identifying the project (device) being modeled.
PROJECT_ID = "#PROJECT#"


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

        # CloudSQL
        self.operations.append((
            self.collect_cloudsql_instances,
            (project_name,)))

        # PubSub
        self.operations.append((
            self.collect_pubsub_topics,
            (project_name,)))

        # MemoryStore
        self.operations.append((
            self.collect_memorystore_locations,
            (project_name,)))

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

        d = self.client.cloudsql(project_name).databases(instance)
        d.addCallback(handle_success)
        d.addErrback(handle_failure)
        return d

    def collect_pubsub_topics(self, project_name):

        def handle_success(result):
            LOG.info("%s: PubSub is enabled", project_name)
            return result

        def handle_failure(failure):
            error = getattr(failure, "error", None)
            message = getattr(error, "message", None)
            LOG.info("%s: PubSub modeling failed", message)
            # Propagate any other failures.
            return failure

        d = self.client.subscriptions(project_name).topics()
        d.addCallback(handle_success)
        d.addErrback(handle_failure)
        return d

    def collect_pubsub_subscriptions(self, project_name):

        def handle_success(result):
            return result

        def handle_failure(failure):
            error = getattr(failure, "error", None)
            message = getattr(error, "message", None)
            LOG.info("%s: PubSub Subscription modeling failed", message)
            # Propagate any other failures.
            return failure

        d = self.client.subscriptions(project_name).subscriptions()
        d.addCallback(handle_success)
        d.addErrback(handle_failure)
        return d

    def collect_memorystore_locations(self, project_name):

        def handle_success(result):
            LOG.info("%s: MemoryStore is enabled", project_name)
            return result

        def handle_failure(failure):
            error = getattr(failure, "error", None)
            message = getattr(error, "message", None)
            LOG.info("%s: MemoryStore modeling failed", message)
            # Propagate any other failures.
            return failure

        d = self.client.memorystore(project_name).locations()
        d.addCallback(handle_success)
        d.addErrback(handle_failure)
        return d

    def collect_memorystore_instances(self, project_name):

        def handle_success(result):
            LOG.info("%s: MemoryStore is enabled", project_name)
            return result

        def handle_failure(failure):
            error = getattr(failure, "error", None)
            message = getattr(error, "message", None)
            LOG.info("%s: MemoryStore modeling failed", message)
            # Propagate any other failures.
            return failure

        d = self.client.memorystore(project_name).instances()
        d.addCallback(handle_success)
        d.addErrback(handle_failure)
        return d


    def handle_result(self, result):
        """Dispatch result to appropriate handle_* method."""
        if not result:
            return {}
        self.results.append(result)

        LOG.debug("handle_result : {}".format([k for k in result]))

        kind = result.get("kind")
        handle_fn = None
        if kind:
            compute_kind = kind.split("#", 1)[-1]
            handle_fn = getattr(self, "handle_{}".format(compute_kind), None)
        elif result.get('items') and result.get('items')[0].get('kind') == 'sql#instance':
            handle_fn = getattr(self, "handle_cloudSQLInstances", None)
        elif result.get("topics"):
            handle_fn = getattr(self, "handle_pubsub_topics", None)
        elif result.get("locations"):
            handle_fn = getattr(self, "handle_memorystore_locations", None)

        if handle_fn is not None:
            handle_fn(result)
        else:
            LOG.debug("No custom handler method found, skipping.")
        return result

    def handle_cloudSQLInstances(self, result):
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

    def handle_pubsub_topics(self, result):
        project_name = result.get('topics')[0].get("name").split("/")[1]
        model_regex = ".*"
        '''
        model_regex = validate_modeling_regex(
            self.device, 'zGoogleCloudPlatformBigTableInstancesModeled')

        if not model_regex:
            return
        '''
        '''
        for topic in result.get('topics', []):
            topic_name = topic['labels']['name']
            if not re.match(model_regex, topic_name):
                continue
        '''
        self.operations.append((self.collect_pubsub_subscriptions, (project_name, )))

    def handle_memorystore_locations(self, result):
        project_name = result.get('locations')[0].get("name").split("/")[1]
        self.operations.append((self.collect_memorystore_instances, (project_name, )))


def process(device, results, plugin_name):
    mapper = DataMapper(plugin_name)

    for result in results:
        # GCE results will have a "kind" key.
        if "kind" in result:
            map_fn_name = "map_{}".format(
                result["kind"].split('#', 1)[-1])
            map_fn = globals().get(map_fn_name)
            if not map_fn:
                raise Exception("no {} function".format(map_fn_name))

            map_result = map_fn(device, result)
            if map_result:
                mapper.update(map_result)

        # Cloud SQL instances will have "items" key.
        elif "items" in result:
            if any([i['kind'] == 'sql#instance' for i in result['items']]):
                cloudSQLInstance_map_result = map_cloudSQLInstancesList(device, result)
                if cloudSQLInstance_map_result:
                    mapper.update(cloudSQLInstance_map_result)
        # PubSub Topics
        elif "topics" in result:
            pubsub_topics_map_result = map_pubSubTopicsList(device, result)
            if pubsub_topics_map_result:
                mapper.update(pubsub_topics_map_result)
        # PubSub Subscriptions
        elif "subscriptions" in result:
            pubsub_subs_map_result = map_pubSubSubscriptionsList(device, result)
            if pubsub_subs_map_result:
                mapper.update(pubsub_subs_map_result)
        elif "locations" in result:
            memorystore_locations_map_result = map_memoryStoreLocationsList(device, result)
            if memorystore_locations_map_result:
                mapper.update(memorystore_locations_map_result)
        elif "instances" in result:
            memorystore_instances_map_result = map_memoryStoreInstancesList(device, result)
            if memorystore_instances_map_result:
                mapper.update(memorystore_instances_map_result)
        else:
            LOG.debug('process result: {}'.format(result))

    '''
    # Prevent modeling of zones with no instances.
    zone_type = "ZenPacks.zenoss.GoogleCloudPlatform.ComputeZone"
    for zone_id, zone_datum in mapper.by_type(zone_type):
        if not zone_datum["links"].get("instances"):
            mapper.remove(zone_id)
    '''

    return mapper.get_full_datamaps()

# Mapping Functions ###################################################
def map_project(device, result):
    data = {
        PROJECT_ID: {
            "type": "ZenPacks.zenoss.GoogleCloudPlatform.ProjectDevice",
            "properties": {
            },
            "links": {
            },
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
              u'privateNetwork': u'projects/acme-sharedvpc-acc/global/networks/acme-sharedvpc-acc'
            },
            u'userLabels': {
              u'name': u'sql-svc-acc'
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
            u'commonName': u'C=US,O=Google\\, Inc,CN=Google Cloud SQL Server CA,dnQualifier=5be8d212-05c2-4ace-9d38-2f56ad2acddd',
            u'instance': u'sql-svc-acc-8170413f',
            u'cert': u'-----BEGIN CERTIFICATE-----\nMIIDfzCCAmegAwIBAgIBADANBgkqhkiG9w0CAQsFADB3MS0wKwYDVQQuEyQ1YmUz\nZDIxMi0wNWMyLTRhY2UtOWQ0OC0yZjU2YWQyYWNkZGQxIzAhBgNVBAMTGkdvb2ds\nZSBDbG91ZCBTUUwgU2VydmVyIENBMRQwEgYDVQQKEwtHb29nbGUsIEluYzELMAkG\nA1UEBhMCVVMwHhcNMjAwOTE2MDY1NzUxWhcNMzAwOTE0MDY1ODUxWjB3MS0wKwYD\nVQQuEyQ1YmUzZDIxMi0wNWMyLTRhY2UtOWQ0OC0yZjU2YWQyYWNkZGQxIzAhBgNV\nBAMTGkdvb2dsZSBDbG91ZCBTUUwgU2VydmVyIENBMRQwEgYDVQQKEwtHb29nbGUs\nIEluYzELMAkGA1UEBhMCVVMwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIB\nAQClBEBfB2MeCFz8g2KKknrFbgVXcUTAd6GqzA97mYzERB++wVjamQ8I+bE73AtH\nyiWg9AVnn49eVEvQPN2JioDmqQ9V/DYYdDKoKEAs/NwVIencajddBaB0aZiX1XFW\nJkWFQ3jJNLjl8f1+SbGs/6Bx7ARgZpb9En2x31a+I3pFWgSwBs19lqhFSEPHq6Wt\nZmceo+mhYvfv3e1xt72shp+106HZ3wtZrdFi/y4uAJsVTErz52fOSKAsLSWML6Cg\nAbZ/xiT9Xe+L08UFo797sl+YmO5Mdt3O3Tf7Dq/hNcFNVoRsSRb0U+S//3Z/SEkT\nZf9ZdOmB9TvO1L5m5v5sKeEhAgMBAAGjFjAUMBIGA1UdEwEB/wQIMAYBAf8CAQAw\nDQYJKoZIhvcNAQELBQADggEBAKII4qbkbqAb3cwajkt9V8SmBJUVgrjiLwUJYn1x\npP8pUErChDqlNNv7WaaR0mPeLqARUE+NKcLBnYV7XzMJ92SQZ8HUs3o+Ig9xCGyJ\nFTqo870vEOwRtA9z0YXFwtLs+lGzyLTwgG3XJ2vH39GB7RXw9h4IeVKu4wWJ4X1t\nPbrTogtLyEPt/AjxnJZhvSpoe0L+tH2ET1uRD8Z6nHDoSKFxeKsKE/4Yf8H4CvtI\nvFBvFcHWnAp9Kd0vGP6MsSifUZDqqLyu68EzPee3k7YWD53eLEdxTu47vD37XJ08\nYjqEgyo2xFnZvwrhLHdhoF4x7d6Nu26bfFxMMjADNoLDYV8=\n-----END CERTIFICATE-----',
            u'expirationTime': u'2030-09-14T06:58:51.719Z',
            u'createTime': u'2020-09-16T06:57:51.719Z'
          },
          u'gceZone': u'europe-west1-b',
          u'project': u'acme-acc-myapp',
          u'state': u'RUNNABLE',
          u'etag': u'48a7c5bb67d1cec2901bd3872196a97d9ec5b2852bb18aab8db2f45760f04327',
          u'serviceAccountEmailAddress': u'p123456789012-na7gqs@gcp-sa-cloud-sql.iam.gserviceaccount.com',
          u'ipAddresses': [
            {
              u'ipAddress': u'10.1.4.19',
              u'type': u'PRIVATE'
            }
          ],
          u'connectionName': u'acme-acc-myapp:europe-west1:sql-svc-acc-8170413f',
          u'databaseVersion': u'POSTGRES_11',
          u'instanceType': u'CLOUD_SQL_INSTANCE',
          u'selfLink': u'https://sqladmin.googleapis.com/sql/v1beta4/projects/acme-acc-myapp/instances/sql-svc-acc-8170413f',
          u'name': u'sql-svc-acc-8170413f'
        }
      ]
    }
    """
    data = {}
    for instance in result.get("items"):
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
          u'project': u'acme-acc-myapp',
          u'instance': u'sql-svc-acc-8170413f',
          u'etag': u'5abc962b2fa8fcbeff62c5b6679c301e12a56afe63159b67e9cce950e222444c',
          u'collation': u'en_US.UTF8',
          u'selfLink': u'https://sqladmin.googleapis.com/sql/v1beta4/projects/acme-acc-myapp/instances/sql-svc-acc-8170413f/databases/postgres'
        },
        {
          u'kind': u'sql#database',
          u'name': u'svc-acc',
          u'charset': u'UTF8',
          u'project': u'acme-acc-myapp',
          u'instance': u'sql-svc-acc-8170413f',
          u'etag': u'c6c7febfc6a50bc2b8f9846c6bba89be49524c0a33744cf7312af4c1f5d750be',
          u'collation': u'en_US.UTF8',
          u'selfLink': u'https://sqladmin.googleapis.com/sql/v1beta4/projects/acme-acc-myapp/instances/sql-svc-acc-8170413f/databases/svc-acc'
        },
        {
          u'kind': u'sql#database',
          u'name': u'svc-eventlog-acc',
          u'charset': u'UTF8',
          u'project': u'acme-acc-myapp',
          u'instance': u'sql-svc-acc-8170413f',
          u'etag': u'cb156511e0455ab150e29812e7daa4c2fe095c969c4fc02891fb58c6259353f6',
          u'collation': u'en_US.UTF8',
          u'selfLink': u'https://sqladmin.googleapis.com/sql/v1beta4/projects/acme-acc-myapp/instances/sql-svc-acc-8170413f/databases/svc-eventlog-acc'
        },
        {
          u'kind': u'sql#database',
          u'name': u'svc-keycloak-acc',
          u'charset': u'UTF8',
          u'project': u'acme-acc-myapp',
          u'instance': u'sql-svc-acc-8170413f',
          u'etag': u'cbfaa79bfbff00bbad35803b448715cc28586dcde38f0859cf45cb4a462201ff',
          u'collation': u'en_US.UTF8',
          u'selfLink': u'https://sqladmin.googleapis.com/sql/v1beta4/projects/acme-acc-myapp/instances/sql-svc-acc-8170413f/databases/svc-keycloak-acc'
        }
      ],
      u'kind': u'sql#databasesList'
    }
    """
    data = {}
    model_regex = validate_modeling_regex(device, 'zGoogleCloudPlatformDatabasesModeled')
    for instance in result.get("items"):
        name = "{} / {}".format(instance["instance"], instance["name"])
        shortname = instance.get("name")
        if not re.match(model_regex, shortname):
            continue
        data.update({
            get_id(instance["selfLink"]): {
                "title": name,
                "type": "ZenPacks.community.GCPExtensions.CloudSQLDatabase",
                "properties": {
                    "charset": instance.get("charset"),
                    "etag": instance.get("etag"),
                    "collation": instance.get("collation"),
                    "selfLink": instance.get("selfLink"),
                    "shortname": shortname,
                    },
                "links": {
                    "cloudSQLInstance": "instance_{}_{}".format(instance["project"], instance["instance"]),
                    }
            }
        })

    return data

def map_pubSubTopicsList(device, result):
    """
    Example result:
      {
        u'topics': [
          {
            u'labels': {
              u'name': u'topic-app-acc-antivirus-request'
            },
            u'name': u'projects/acme-acc-svc/topics/topic-app-acc-antivirus-request',
            u'messageStoragePolicy': {
              u'allowedPersistenceRegions': [
                u'europe-west1'
              ]
            }
          },
          {
            u'labels': {
              u'name': u'topic-app-acc-antivirus-response'
            },
            u'name': u'projects/acme-acc-svc/topics/topic-app-acc-antivirus-response',
            u'messageStoragePolicy': {
              u'allowedPersistenceRegions': [
                u'europe-west1'
              ]
            }
          },
          {
            u'labels': {
              u'name': u'topic-app-acc-email-dlq'
            },
            u'name': u'projects/acme-acc-svc/topics/topic-app-acc-email-dlq',
            u'messageStoragePolicy': {
              u'allowedPersistenceRegions': [
                u'europe-west1'
              ]
            }
          },
          {
            u'labels': {
              u'name': u'topic-app-acc-eventlog-dlq'
            },
            u'name': u'projects/acme-acc-svc/topics/topic-app-acc-eventlog-dlq',
            u'messageStoragePolicy': {
              u'allowedPersistenceRegions': [
                u'europe-west1'
              ]
            }
          }
        ]
      }
    """
    data = {}
    for topic in result.get("topics"):
        # TODO: get label from name field ?
        if "labels" not in topic:
            continue
        label = topic["labels"]["name"]
        data.update({
            prepId(label): {
                "title": label,
                "type": "ZenPacks.community.GCPExtensions.PubSubTopic",
                "properties": {
                },
                "links": {
                    "project": PROJECT_ID,
                }
            }
        })

    return data

def map_pubSubSubscriptionsList(device, result):
    """
    Example result:
      {
        u'subscriptions': [
          u'projects/acme-acc-svc/subscriptions/topic-app-acc-email.email-service'
        ]
      }
    """
    # TODO: Non-DLQ subscriptions are not linked to their respective topic ?
    data = {}
    model_regex = validate_modeling_regex(device, 'zGoogleCloudPlatformSubscriptionsModeled')
    for sub in result.get("subscriptions"):
        sub_name = sub["name"]
        sub_shortname = sub_name.split("/")[-1]
        if not re.match(model_regex, sub_shortname):
            continue
        topic = sub["topic"]
        topic_id = topic.split("/")[-1]
        deadLetterTopic = sub.get("deadLetterPolicy", {}).get("deadLetterTopic", "-")
        retryPolicymaximumBackoff = sub.get("retryPolicy", {}).get("maximumBackoff", "-")
        retryPolicyminimumBackoff = sub.get("retryPolicy", {}).get("minimumBackoff", "-")
        data.update({
            prepId(sub_shortname): {
                "title": sub_shortname,
                "type": "ZenPacks.community.GCPExtensions.PubSubSubscription",
                "properties": {
                    "messageRetentionDuration": sub["messageRetentionDuration"],
                    "deadLetterTopic": deadLetterTopic,
                    "expirationPolicyTTL": sub["expirationPolicy"]["ttl"],
                    "retryPolicymaximumBackoff": retryPolicymaximumBackoff,
                    "retryPolicyminimumBackoff": retryPolicyminimumBackoff,
                    "ackDeadlineSeconds": sub["ackDeadlineSeconds"],
                    },
                "links": {
                    "pubSubTopic": prepId(topic_id),
                    }
            }
        })
    return data

def map_memoryStoreLocationsList(device, result):
    """
    Example result:
    {
      u'locations': [
        {
          u'locationId': u'asia-east1',
          u'name': u'projects/acme-acc-svc/locations/asia-east1',
          u'metadata': {
            u'availableZones': {
              u'asia-east1-b': {

              },
              u'asia-east1-c': {

              },
              u'asia-east1-a': {

              }
            },
            u'@type': u'type.googleapis.com/google.cloud.redis.v1beta1.LocationMetadata'
          }
        },
        ...
    }
    """
    data = {}
    # model_regex = validate_modeling_regex(device, 'zGoogleCloudPlatformSubscriptionsModeled')
    for location in result.get("locations"):
        location_id = prepId('region_{}'.format(location["locationId"]))
        location_label = location["locationId"]
        data.update({
            location_id: {
                "title": location_label,
                "type": "ZenPacks.zenoss.GoogleCloudPlatform.ComputeRegion",
                "properties": {
                    },
                "links": {
                    "project": PROJECT_ID,
                    }
            }
        })

    return data

def map_memoryStoreInstancesList(device, result):
    """
    Example result:
      {
        u'subscriptions': [
          u'projects/acme-acc-svc/subscriptions/topic-app-acc-email.email-service'
        ]
      }
    """
    data = {}
    # model_regex = validate_modeling_regex(device, 'zGoogleCloudPlatformSubscriptionsModeled')
    for instance in result.get("instances"):
        id = prepId(instance["name"].split("/")[-1])
        # TODO: fix relationship to zone
        zone_id = 'zone_{}'.format(instance["currentLocationId"])
        '''
        if not re.match(model_regex, sub_shortname):
            continue
        '''
        data.update({
            id: {
                "title": instance["displayName"],
                "type": "ZenPacks.community.GCPExtensions.MemoryStore",
                "properties": {
                    "instance_id": instance["name"],
                    "reservedIpRange": instance["reservedIpRange"],
                    "redisVersion": instance["redisVersion"],
                    "host": instance["host"],
                    "port": instance["port"],
                    "memorySizeGb": instance["memorySizeGb"],
                    },
                "links": {
                    "project": PROJECT_ID,
                    "zone": prepId(zone_id),
                    }
            }
        })

    return data
