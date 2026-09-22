targetScope = 'resourceGroup'

@description('Globally unique lowercase prefix, 3–16 alphanumeric characters.')
@minLength(3)
@maxLength(16)
param prefix string
param location string = resourceGroup().location
param adminEmail string = 'administrator@hbstest.com'
@secure()
param sqlAdminPassword string
@secure()
param sessionSecret string
@secure()
@description('Runtime application connection string; use a separate contained database user, not the SQL administrator.')
param databaseUrl string

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${prefix}-plan'
  location: location
  kind: 'linux'
  sku: { name: 'B1', tier: 'Basic', capacity: 1 }
  properties: { reserved: true }
}
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${prefix}-vault'
  location: location
  properties: {
    tenantId: tenant().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enablePurgeProtection: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
}
resource sessionKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'session-secret'
  properties: { value: sessionSecret }
}
resource databaseKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'database-url'
  properties: { value: databaseUrl }
}
resource sql 'Microsoft.Sql/servers@2023-08-01' = {
  name: '${prefix}-sql'
  location: location
  properties: {
    administratorLogin: 'systracker_bootstrap'
    administratorLoginPassword: sqlAdminPassword
    version: '12.0'
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
  }
}
resource database 'Microsoft.Sql/servers/databases@2023-08-01' = {
  parent: sql
  name: 'systracker'
  location: location
  sku: { name: 'GP_S_Gen5', tier: 'GeneralPurpose', family: 'Gen5', capacity: 2 }
  properties: {
    autoPauseDelay: 60
    minCapacity: json('0.5')
    maxSizeBytes: 34359738368
    useFreeLimit: true
    freeLimitExhaustionBehavior: 'AutoPause'
    requestedBackupStorageRedundancy: 'Local'
  }
}
resource emailService 'Microsoft.Communication/emailServices@2023-03-31' = {
  name: '${prefix}-email'
  location: 'global'
  properties: { dataLocation: 'United States' }
}
resource emailDomain 'Microsoft.Communication/emailServices/domains@2023-03-31' = {
  parent: emailService
  name: 'hbstest.com'
  location: 'global'
  properties: { domainManagement: 'CustomerManaged' }
}
resource communication 'Microsoft.Communication/communicationServices@2023-03-31' = {
  name: '${prefix}-communications'
  location: 'global'
  properties: { dataLocation: 'United States' }
}
resource emailKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'email-connection'
  properties: { value: 'endpoint=https://${communication.properties.hostName}/;accesskey=${communication.listKeys().primaryKey}' }
}
resource app 'Microsoft.Web/sites@2023-12-01' = {
  name: '${prefix}-web'
  location: location
  kind: 'app,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      appCommandLine: 'sh startup.sh'
      alwaysOn: true
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      scmMinTlsVersion: '1.2'
      http20Enabled: true
      appSettings: [
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'APP_ENV', value: 'production' }
        { name: 'PUBLIC_URL', value: 'https://systracker.hbstest.com' }
        { name: 'INGEST_HOST', value: 'ingest.hbstest.com' }
        { name: 'MAIL_MODE', value: 'azure' }
        { name: 'MAIL_SENDER', value: 'systracker@hbstest.com' }
        { name: 'ACS_CONNECTION_STRING', value: '@Microsoft.KeyVault(SecretUri=${emailKey.properties.secretUriWithVersion})' }
        { name: 'SECRET_KEY', value: '@Microsoft.KeyVault(SecretUri=${sessionKey.properties.secretUriWithVersion})' }
        { name: 'DATABASE_URL', value: '@Microsoft.KeyVault(SecretUri=${databaseKey.properties.secretUriWithVersion})' }
      ]
    }
  }
}
resource scmPolicy 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01' = {
  parent: app
  name: 'scm'
  properties: { allow: false }
}
resource ftpPolicy 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01' = {
  parent: app
  name: 'ftp'
  properties: { allow: false }
}
resource secretsReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id,app.id,'secrets-reader')
  scope: vault
  properties: {
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions','4633458b-17de-408a-b874-0445c86b69e6')
  }
}
// Explicit web-app egress addresses only; no "Allow all Azure services" firewall rule.
module sqlFirewall 'sql-firewall.bicep' = {
  name: 'sql-firewall'
  params: { serverName: sql.name, addresses: split(app.properties.possibleOutboundIpAddresses,',') }
}
// Separate runtime and publishing surface for signed releases; no access to application secrets.
resource updates 'Microsoft.Web/sites@2023-12-01' = {
  name: '${prefix}-updates'
  location: location
  kind: 'app,linux'
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      appCommandLine: 'gunicorn app:app --bind 0.0.0.0:8000 --workers 1 --access-logfile /dev/null'
      alwaysOn: false
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      scmMinTlsVersion: '1.2'
      appSettings: [{ name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }]
    }
  }
}
resource updatesScm 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01' = {
  parent: updates
  name: 'scm'
  properties: { allow: false }
}
resource updatesFtp 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01' = {
  parent: updates
  name: 'ftp'
  properties: { allow: false }
}
output appName string = app.name
output sqlHost string = sql.properties.fullyQualifiedDomainName
output sqlDatabase string = database.name
output dnsTarget string = app.properties.defaultHostName
output domainVerificationId string = app.properties.customDomainVerificationId
output emailResource string = emailService.name
output communicationResource string = communication.name
output appPrincipalId string = app.identity.principalId
output administrator string = adminEmail
output updatesAppName string = updates.name
output updatesDnsTarget string = updates.properties.defaultHostName
output updatesVerificationId string = updates.properties.customDomainVerificationId
