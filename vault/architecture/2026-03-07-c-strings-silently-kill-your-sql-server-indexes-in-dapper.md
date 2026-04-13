---
title: "C# strings silently kill your SQL Server indexes in Dapper"
source: "https://consultwithgriff.com/dapper-nvarchar-implicit-conversion-performance-trap"
score: 12
date: 2026-03-07
category: architecture
---

## Summary

C# string parameters in Dapper queries can trigger implicit NVARCHAR conversions that prevent SQL Server from using indexes effectively

## Key Insight

Implicit string-to-NVARCHAR conversions in Dapper can silently bypass SQL Server indexes, causing severe performance degradation that's easily overlooked

## Source

[C# strings silently kill your SQL Server indexes in Dapper](https://consultwithgriff.com/dapper-nvarchar-implicit-conversion-performance-trap)
