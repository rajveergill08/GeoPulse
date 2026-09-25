import type {Daypart} from './types';

const DAYPART_LABELS: Record<Daypart, string> = {
  morning_commute: 'Morning commute',
  midday: 'Midday',
  evening_commute: 'Evening commute',
  off_peak: 'Off peak'
};

const percentFormatter = new Intl.NumberFormat('en-IN', {
  style: 'percent',
  maximumFractionDigits: 1
});

const integerFormatter = new Intl.NumberFormat('en-IN', {
  maximumFractionDigits: 0
});

const shortDateFormatter = new Intl.DateTimeFormat('en-IN', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC'
});

const refreshedAtFormatter = new Intl.DateTimeFormat('en-IN', {
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'UTC',
  timeZoneName: 'short'
});

export function formatPercent(value: number): string {
  return percentFormatter.format(value);
}

export function formatInteger(value: number): string {
  return integerFormatter.format(value);
}

export function formatDaypart(daypart: Daypart): string {
  return DAYPART_LABELS[daypart];
}

export function formatTrafficDate(value: string): string {
  return shortDateFormatter.format(new Date(`${value}T00:00:00Z`));
}

export function formatRefreshedAt(value: string): string {
  return refreshedAtFormatter.format(new Date(value));
}
