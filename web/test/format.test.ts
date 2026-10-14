// pt-PT formats, the same as src/escapadinha/i18n_pt.py (examples from its docstrings and the
// design system). Prices carry a no-break space before "€" so "49 €" never wraps.
import { describe, expect, it } from "vitest";
import {
  dateRange,
  dayMonthYear,
  discount,
  discountParts,
  discountPercent,
  eur,
  eurParts,
  eurPlain,
  lisbonTimestamp,
  longDate,
  monthList,
  monthYear,
  nights,
  numericDate,
  numericDayMonth,
  shortDate,
} from "../src/lib/format";

const NBSP = " ";

describe("pt-PT formats", () => {
  it("prints euros with comma decimals and no cents when whole", () => {
    expect(eur(49)).toBe(`49${NBSP}€`);
    expect(eur(49.5)).toBe(`49,50${NBSP}€`);
    expect(eur(1299)).toBe(`1299${NBSP}€`);
  });

  it("prints short dates with the weekday", () => {
    expect(shortDate("2026-11-06")).toBe("sex, 6 nov");
    expect(shortDate("2026-12-09")).toBe("qua, 9 dez");
  });

  it("prints numeric dates", () => {
    expect(numericDate("2026-10-07")).toBe("07/10/2026");
  });

  it("prints date ranges in prose", () => {
    expect(dateRange("2026-11-06", "2026-11-09")).toBe("6 a 9 de novembro");
    expect(dateRange("2026-11-27", "2026-12-04")).toBe("27 de novembro a 4 de dezembro");
    expect(dateRange("2026-12-30", "2027-01-03")).toBe("30 de dezembro de 2026 a 3 de janeiro de 2027");
  });

  it("prints a day with its full weekday, and a month with its year", () => {
    expect(longDate("2026-11-30")).toBe("segunda-feira, 30 de novembro");
    expect(longDate("2027-02-13")).toBe("sábado, 13 de fevereiro");
    expect(monthYear("2026-10")).toBe("outubro de 2026");
  });

  it("prints a day with its year, and a list of months in prose", () => {
    expect(dayMonthYear("2026-10-14")).toBe("14 de outubro de 2026");
    expect(dayMonthYear("2027-01-05")).toBe("5 de janeiro de 2027");
    expect(monthList([4, 5, 9])).toBe("abril, maio e setembro");
    expect(monthList([12, 1])).toBe("dezembro e janeiro");
    expect(monthList([7])).toBe("julho");
  });

  it("shows instants in Lisbon time, summer and winter", () => {
    // 21:17 UTC in October (WEST, UTC+1) is 22:17 in Lisbon; in January Lisbon is on UTC.
    expect(lisbonTimestamp("2026-10-12T21:17:55Z")).toBe("12/10/2026 às 22:17");
    expect(lisbonTimestamp("2027-01-05T09:04Z")).toBe("05/01/2027 às 09:04");
    expect(lisbonTimestamp("2026-10-12T23:30:00Z")).toBe("13/10/2026 às 00:30");
  });

  it("counts nights", () => {
    expect(nights(1)).toBe("1 noite");
    expect(nights(3)).toBe("3 noites");
  });

  it("prints a discount with a true minus sign", () => {
    expect(discount(0.4397)).toBe("−44%");
    expect(discount(0.322)).toBe("−32%");
    expect(discountPercent(44)).toBe("−44%");
  });

  it("gives prices and discounts in parts, so components never parse the text", () => {
    expect(eurParts(49.5)).toEqual({ amount: "49,50", currency: "€", text: `49,50${NBSP}€` });
    expect(eurParts(86)).toEqual({ amount: "86", currency: "€", text: eur(86) });
    expect(discountParts(0.4397)).toEqual({ sign: "−", value: "44%", text: "−44%" });
  });

  it("prints the recheck's plain-space price and day/month like the pipeline", () => {
    expect(eurPlain(49.5)).toBe("49,50 €");
    expect(numericDayMonth("2026-10-05")).toBe("05/10");
  });
});
