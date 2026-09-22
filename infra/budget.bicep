targetScope = 'resourceGroup'
param email string = 'administrator@hbstest.com'
@description('First day of current month, e.g. 2026-09-01T00:00:00Z')
param startDate string
resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: 'systracker-monthly'
  properties: {
    amount: 25
    category: 'Cost'
    timeGrain: 'Monthly'
    timePeriod: { startDate: startDate }
    notifications: {
      TenDollars: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 40, contactEmails: [email], thresholdType: 'Actual' }
      TwentyDollars: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 80, contactEmails: [email], thresholdType: 'Actual' }
      TwentyFiveDollars: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 100, contactEmails: [email], thresholdType: 'Actual' }
    }
  }
}
