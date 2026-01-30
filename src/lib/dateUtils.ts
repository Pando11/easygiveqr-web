/**
 * Date utilities for weekly summary calculations
 * All dates are in America/Chicago timezone
 * 
 * Note: For production, consider using a library like date-fns-tz for more reliable timezone handling
 */

/**
 * Get Chicago timezone offset in minutes for a given date
 * Chicago is UTC-6 (CST) or UTC-5 (CDT)
 */
function getChicagoOffsetMinutes(date: Date): number {
  // Create a date string in Chicago timezone
  const chicagoDateStr = date.toLocaleString("en-US", { timeZone: "America/Chicago" });
  const chicagoDate = new Date(chicagoDateStr);
  
  // Create same date string as if it were UTC
  const utcDateStr = date.toLocaleString("en-US", { timeZone: "UTC" });
  const utcDate = new Date(utcDateStr);
  
  // Difference in minutes
  return (chicagoDate.getTime() - utcDate.getTime()) / (1000 * 60);
}

/**
 * Convert a Chicago local time to UTC Date
 */
function chicagoToUTC(year: number, month: number, day: number, hour: number = 0, minute: number = 0, second: number = 0): Date {
  // Create date string in Chicago format
  const chicagoDate = new Date(year, month - 1, day, hour, minute, second);
  const chicagoStr = chicagoDate.toLocaleString("en-US", {
    timeZone: "America/Chicago",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
  
  // Parse components
  const [datePart, timePart] = chicagoStr.split(", ");
  const [m, d, y] = datePart.split("/");
  const [h, min, s] = timePart.split(":");
  
  // Create UTC date that represents this Chicago local time
  const utcDate = new Date(Date.UTC(
    parseInt(y),
    parseInt(m) - 1,
    parseInt(d),
    parseInt(h),
    parseInt(min),
    parseInt(s)
  ));
  
  // Adjust for timezone offset
  const offset = getChicagoOffsetMinutes(utcDate);
  return new Date(utcDate.getTime() - offset * 60 * 1000);
}

/**
 * Get the most recent Wednesday at 00:00:00 in America/Chicago timezone
 * Returns a Date object in UTC that represents that moment
 */
export function getLastWednesday(): Date {
  const now = new Date();
  
  // Get current date components in Chicago timezone
  const chicagoNow = new Date(now.toLocaleString("en-US", { timeZone: "America/Chicago" }));
  const year = chicagoNow.getFullYear();
  const month = chicagoNow.getMonth() + 1; // getMonth() returns 0-11
  const day = chicagoNow.getDate();
  const dayOfWeek = chicagoNow.getDay(); // 0 = Sunday, 3 = Wednesday
  
  // Calculate days since last Wednesday
  const daysSinceWednesday = (dayOfWeek + 4) % 7;
  
  // Calculate last Wednesday's date
  const lastWedDate = new Date(year, month - 1, day - daysSinceWednesday);
  const lastWedYear = lastWedDate.getFullYear();
  const lastWedMonth = lastWedDate.getMonth() + 1;
  const lastWedDay = lastWedDate.getDate();
  
  // Convert to UTC
  return chicagoToUTC(lastWedYear, lastWedMonth, lastWedDay, 0, 0, 0);
}

/**
 * Get this Wednesday at 00:00:00 in America/Chicago timezone
 */
export function getThisWednesday(): Date {
  const lastWed = getLastWednesday();
  const lastWedChicago = new Date(lastWed.toLocaleString("en-US", { timeZone: "America/Chicago" }));
  
  const nextWed = new Date(lastWedChicago);
  nextWed.setDate(lastWedChicago.getDate() + 7);
  
  return chicagoToUTC(
    nextWed.getFullYear(),
    nextWed.getMonth() + 1,
    nextWed.getDate(),
    0,
    0,
    0
  );
}

/**
 * Get the previous week's Wednesday (7 days before last Wednesday)
 */
export function getPreviousWeekWednesday(): Date {
  const lastWed = getLastWednesday();
  const lastWedChicago = new Date(lastWed.toLocaleString("en-US", { timeZone: "America/Chicago" }));
  
  const prevWed = new Date(lastWedChicago);
  prevWed.setDate(lastWedChicago.getDate() - 7);
  
  return chicagoToUTC(
    prevWed.getFullYear(),
    prevWed.getMonth() + 1,
    prevWed.getDate(),
    0,
    0,
    0
  );
}

/**
 * Get the first day of the current month at 00:00:00 in America/Chicago
 */
export function getFirstDayOfMonth(): Date {
  const now = new Date();
  const chicagoNow = new Date(now.toLocaleString("en-US", { timeZone: "America/Chicago" }));
  
  const year = chicagoNow.getFullYear();
  const month = chicagoNow.getMonth() + 1;
  
  return chicagoToUTC(year, month, 1, 0, 0, 0);
}

/**
 * Format date for display (America/Chicago timezone)
 */
export function formatDate(date: Date): string {
  return date.toLocaleDateString("en-US", {
    timeZone: "America/Chicago",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

/**
 * Format date range for display
 */
export function formatDateRange(start: Date, end: Date): { start: string; end: string } {
  return {
    start: formatDate(start),
    end: formatDate(end),
  };
}
