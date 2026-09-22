param serverName string
param addresses array
resource server 'Microsoft.Sql/servers@2023-08-01' existing = { name: serverName }
resource rules 'Microsoft.Sql/servers/firewallRules@2023-08-01' = [for (ip,i) in addresses: {
  parent: server
  name: 'app-egress-${i}'
  properties: { startIpAddress: ip, endIpAddress: ip }
}]
