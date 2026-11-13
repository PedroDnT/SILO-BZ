# SILO documentation brief

## Description
Read-only Brazilian financial data through REST and MCP, with coverage and provenance.

## Primary audience
Developers and research agents choosing an operation and making a reproducible query.

## Jobs to be done
Discover an operation by financial task, resolve identifiers, check coverage, send a request,
read pagination and errors, and connect an authenticated agent.

## Motivation
Owner requested the discoverability and interactive onboarding of Financial Datasets.
Preserve SILO's English documentation, theme, existing URLs and deployed-preview status.
Do not infer dataset parity from similar page titles. No DNS or paid benchmark changes.

Operation routes use meaningful inputs and compact metadata. Prefer `/macro/series?series=CDI` and `/prices/latest?ticker=PETR4`. Do not expose kind on their playgrounds. Legacy resource routes and MCP still use kind/id. Python v2 results convert locally to pandas/Polars and refuse partial data by default.
