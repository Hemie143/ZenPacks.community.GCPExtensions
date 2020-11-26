
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
        '''
        self.operations.append((
            self.collect_subscriptions,
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

        d = self.client.subscriptions(project_name).instances()
        d.addCallback(handle_success)
        d.addErrback(handle_failure)
        return d

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
        elif result.get('items') and result.get('items')[0].get('kind') == 'sql#instance':
            handle_fn = getattr(self, "handle_cloudSQLInstances", None)

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
            u'commonName': u'C=US,O=Google\\, Inc,CN=Google Cloud SQL Server CA,dnQualifier=5be3d212-05c2-4ace-9d48-2f56ad2acddd',
            u'instance': u'sql-svc-acc-8170413f',
            u'cert': u'-----BEGIN CERTIFICATE-----\nMIIDfzCCAmegAwIBAgIBADANBgkqhkiG9w0BAQsFADB3MS0wKwYDVQQuEyQ1YmUz\nZDIxMi0wNWMyLTRhY2UtOWQ0OC0yZjU2YWQyYWNkZGQxIzAhBgNVBAMTGkdvb2ds\nZSBDbG91ZCBTUUwgU2VydmVyIENBMRQwEgYDVQQKEwtHb29nbGUsIEluYzELMAkG\nA1UEBhMCVVMwHhcNMjAwOTE2MDY1NzUxWhcNMzAwOTE0MDY1ODUxWjB3MS0wKwYD\nVQQuEyQ1YmUzZDIxMi0wNWMyLTRhY2UtOWQ0OC0yZjU2YWQyYWNkZGQxIzAhBgNV\nBAMTGkdvb2dsZSBDbG91ZCBTUUwgU2VydmVyIENBMRQwEgYDVQQKEwtHb29nbGUs\nIEluYzELMAkGA1UEBhMCVVMwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIB\nAQClBEBfB2MeCFz8g2KKknrFbgVXcUTAd6GqzA97mYzERB++wVjamQ8I+bE73AtH\nyiWg9AVnn49eVEvQPN2JioDmqQ9V/DYYdDKoKEAs/NwVIencajddBaB0aZiX1XFW\nJkWFQ3jJNLjl8f1+SbGs/6Bx7ARgZpb9En2x31a+I3pFWgSwBs19lqhFSEPHq6Wt\nZmceo+mhYvfv3e1xt72shp+106HZ3wtZrdFi/y4uAJsVTErz52fOSKAsLSWML6Cg\nAbZ/xiT9Xe+L08UFo797sl+YmO5Mdt3O3Tf7Dq/hNcFNVoRsSRb0U+S//3Z/SEkT\nZf9ZdOmB9TvO1L5m5v5sKeEhAgMBAAGjFjAUMBIGA1UdEwEB/wQIMAYBAf8CAQAw\nDQYJKoZIhvcNAQELBQADggEBAKII4qbkbqAb3cwajkt9V8SmBJUVgrjiLwUJYn1x\npP8pUErChDqlNNv7WaaR0mPeLqARUE+NKcLBnYV7XzMJ92SQZ8HUs3o+Ig9xCGyJ\nFTqo870vEOwRtA9z0YXFwtLs+lGzyLTwgG3XJ2vH39GB7RXw9h4IeVKu4wWJ4X1t\nPbrTogtLyEPt/AjxnJZhvSpoe0L+tH2ET1uRD8Z6nHDoSKFxeKsKE/4Yf8H4CvtI\nvFBvFcHWnAp9Kd0vGP6MsSifUZDqqLyu68EzPee3k7YWD53eLEdxTu47vD37XJ08\nYjqEgyo2xFnZvwrhLHdhoF4x7d6Nu26bfFxMMjADNoLDYV8=\n-----END CERTIFICATE-----',
            u'expirationTime': u'2030-09-14T06:58:51.719Z',
            u'createTime': u'2020-09-16T06:57:51.719Z'
          },
          u'gceZone': u'europe-west1-b',
          u'project': u'acme-acc-myapp',
          u'state': u'RUNNABLE',
          u'etag': u'48a7c5bb67d1cec2901bd3872196a97d9ec5b2852bb18aab8db2f45760f04327',
          u'serviceAccountEmailAddress': u'p544053300745-na7gqs@gcp-sa-cloud-sql.iam.gserviceaccount.com',
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
    for instance in result.get("items"):
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
