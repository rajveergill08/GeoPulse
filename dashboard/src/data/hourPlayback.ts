export function nextHour(hour: number): number {
  return (hour + 1) % 24;
}
