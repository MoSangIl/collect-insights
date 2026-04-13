---
title: "Excel incorrectly assumes that the year 1900 is a leap year"
source: "https://learn.microsoft.com/en-us/troubleshoot/microsoft-365-apps/excel/wrongly-assumes-1900-is-leap-year"
score: 10
date: 2026-03-16
category: tools
---

## Summary

Excel has a documented bug treating 1900 as a leap year, maintained for backward compatibility with Lotus 1-2-3

## Key Insight

When importing/exporting Excel dates or building Excel-compatible systems, account for this off-by-one date error before March 1, 1900

## Source

[Excel incorrectly assumes that the year 1900 is a leap year](https://learn.microsoft.com/en-us/troubleshoot/microsoft-365-apps/excel/wrongly-assumes-1900-is-leap-year)
