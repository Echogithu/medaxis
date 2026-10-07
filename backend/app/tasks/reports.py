"""任务消息仅包含UUID；数据库为报告处理状态的真源。"""
import asyncio

from app.db.session import async_engine
from app.services.report_processing import pending_jobs, run_job
from app.tasks.celery_app import celery_app


def fresh_loop(coroutine):
    async def execute():
        try:
            return await coroutine
        finally:
            await async_engine.dispose()
    return asyncio.run(execute())


@celery_app.task(name='app.tasks.reports.process_report', acks_late=True, reject_on_worker_lost=True, time_limit=600)
def process_report(job_id):
    fresh_loop(run_job(job_id))


@celery_app.task(name='app.tasks.reports.scan_pending_report_jobs')
def scan_pending_report_jobs():
    from app.services.report_processing import enqueue_job
    for job_id in fresh_loop(pending_jobs()):
        enqueue_job(job_id)
