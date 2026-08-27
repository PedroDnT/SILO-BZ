"""Focused backfill controls must not re-fetch unrelated FI datasets."""

from unittest.mock import AsyncMock

import pytest

from src.pipeline.cvm_pipeline import CVMIngestor


@pytest.mark.asyncio
async def test_fi_balancete_filter_schedules_only_balancete():
    ingestor = CVMIngestor.__new__(CVMIngestor)
    ingestor.ingest_fi_balancete = AsyncMock(return_value=1)

    async def run_tasks(tasks, _concurrency, totals, _label):
        for task in tasks:
            totals[task.table] += await task.operation

    ingestor._run_task_batches = run_tasks

    totals = await ingestor.backfill(
        start_year=2021,
        end_year=2021,
        entity_filter="fi",
        doc_type_filter="balancete",
    )

    assert ingestor.ingest_fi_balancete.await_count == 12
    assert totals["cvm_fi_balancete"] == 12
    assert sum(totals.values()) == 12


@pytest.mark.asyncio
async def test_doc_type_filter_rejects_non_fi_entity():
    ingestor = CVMIngestor.__new__(CVMIngestor)

    with pytest.raises(ValueError, match="requires entity_filter='fi'"):
        await ingestor.backfill(
            entity_filter="fidc",
            doc_type_filter="balancete",
        )
