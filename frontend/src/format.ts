export function formatOpsDate(value: string | null) {
  if (!value) return 'Not recorded'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Invalid timestamp'
  return `${new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(date)} UTC`
}

export function formatOpsMoney(amount: string, currency: string) {
  const raw = String(amount)
  const [whole, fraction = ''] = raw.split('.')
  if (!/^\d+$/.test(whole)) return `${raw} ${currency}`
  const symbol = new Intl.NumberFormat('en-IN', { style: 'currency', currency }).formatToParts(0).find(part => part.type === 'currency')?.value ?? currency
  return `${symbol}${new Intl.NumberFormat('en-IN').format(BigInt(whole))}.${fraction.padEnd(2, '0').slice(0, 2)}`
}

export function displayLabel(value: string) {
  return value.toLowerCase().split('_').map(part => part.charAt(0).toUpperCase() + part.slice(1)).join(' ')
}
