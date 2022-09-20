Goal
----
Monitor additional resources of Google Cloud Platform that are not included in the commercial ZenPack (ZenPacks.zenoss.GoogleCloudPlatform):

- CloudSQL instances
- CloudSQL databases (PostgreSQL)
- PubSub topics
- PubSub Subscription
- Memory Store (Redis)

Collection method
-----------------
Through the Google APIs, using modules from ZenPacks.zenoss.GoogleCloudPlatform.

Releases
--------

- 1.4.3 (20/09/2022)
  - Corrected bug caused Pubsub Subscriptions without expirationPolicyTTL
- 1.4.2 (02/02/2021)
  - Corrected the scale on the threshold and event transform of cache hit ratio of Memory Store
  - Added monitoring of MySQL connections
  - ALIGN_MAX for CloudSQL connection
- 1.4.1 (02/02/2021)
  - Corrected Event Transforms
  - Corrected aggregator for uptime of MemoryStore
- 1.4.0 (29/01/2021)
  - Added thresholds and Event Transforms
- 1.3.0 (10/12/2020)
  - MemoryStore (Redis) Modeling and monitoring
- 1.2.0 (04/12/2020)
  - Filters on databases and subscriptions
- 1.1.0 (04/12/2020)
  - PubSub Modeling & Monitoring
- 1.0.0 (20/11/2020)
  - Initial release.
-- CloudSQL Modeling and monitoring