"""报告整理工作区及任务状态；原件只进入平台内识字进程。"""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import HTTPException
from openai import AsyncOpenAI
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import undefer

from app.db.session import async_session_maker
from app.models.patient_report import PatientReport, PatientReportFile, ReportProcessingJob
from app.models.user import User
from app.services.llm import LLMConfigurationError, LLMService, _get_default_provider, _get_provider_config
from app.services.report_candidates import CandidateError, POLICY, SYSTEM, fingerprint, grounded_candidate, masked_pages, outgoing_text
from app.services.report_files import MAX_TEXT_CHARACTERS, ReportFileError, extract_report_file


def now():
    return datetime.now(timezone.utc)


async def workspace_report(db, report_id, patient_id=None, *, lock=False, include_trashed=False):
    statement = select(PatientReport).options(undefer(PatientReport.workflow)).where(PatientReport.id == report_id)
    if patient_id is not None:
        statement = statement.where(PatientReport.patient_id == patient_id)
    if not include_trashed:
        statement = statement.where(PatientReport.trashed_at.is_(None))
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(statement)


async def load_job(db, job_id, *, lock=False, payload=False, report_id=None):
    if not job_id:
        return None
    statement = select(ReportProcessingJob).where(ReportProcessingJob.id == UUID(str(job_id)))
    if report_id is not None:
        statement = statement.where(ReportProcessingJob.report_id == report_id)
    if payload:
        statement = statement.options(undefer(ReportProcessingJob.input), undefer(ReportProcessingJob.result))
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(statement)


def source_hash(report, kind):
    return fingerprint([report.source_version, report.content_hash, report.category if kind == 'ai' else None])


def job_view(job, *, payload=False):
    if job is None:
        return None
    result = {key: getattr(job, key) for key in ('id', 'request_id', 'kind', 'status', 'source_version', 'created_at',
        'updated_at', 'completed_at', 'dispatch_started_at', 'error_code', 'error_message')}
    if payload:
        result['result'] = job.result if job.status == 'completed' else None
    return result


def public_preview(preview):
    if not preview:
        return None
    result = deepcopy(preview)
    if result['recipient']:
        result['recipient'].pop('route_hash', None)
    return result


async def workspace(db, report):
    state = report.workflow or {}
    extract = await load_job(db, state.get('extract_id'), payload=True)
    ai = await load_job(db, state.get('ai_id'), payload=True)
    return {'revision': state.get('revision', 0), 'source_version': report.source_version, 'category': report.category,
        'extract_job': job_view(extract, payload=True), 'ai_job': job_view(ai, payload=True),
        'preview': public_preview(state.get('preview'))}


def expect_version(report, data):
    if report.source_version != data.expected_source_version or (report.workflow or {}).get('revision', 0) != data.expected_workflow_revision:
        raise HTTPException(409, '整理工作区已更新，本页输入仍保留，请对照最新版本')


async def replay_job(db, report, data):
    job = await db.scalar(select(ReportProcessingJob).where(ReportProcessingJob.report_id == report.id,
        ReportProcessingJob.request_id == data.request_id))
    if job is not None and job.request_fingerprint != fingerprint(data.model_dump(mode='json')):
        raise HTTPException(409, '该提交编号已用于不同内容，请重新提交')
    return job


async def cancel_pending(db, report, kinds):
    state = report.workflow or {}
    for kind in kinds:
        job = await load_job(db, state.get(kind + '_id'), lock=True)
        if job and job.status in ('queued', 'processing'):
            job.status, job.completed_at, job.updated_at = 'cancelled', now(), now()


def update_state(report, **changes):
    state = deepcopy(report.workflow or {})
    state.update(changes)
    state['revision'] = state.get('revision', 0) + 1
    report.workflow = state


async def invalidate_category(db, report):
    await cancel_pending(db, report, ['ai'])
    update_state(report, preview=None, ai_id=None)


async def recipient_config(db):
    provider = await _get_default_provider(db, platform='web')
    config = await _get_provider_config(db, provider, platform='web')
    url = urlsplit(config['base_url'])
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise LLMConfigurationError('报告AI接收方配置不可用于明确的脱敏预览')
    recipient = {'provider': provider, 'model': config['default_model'], 'host': url.hostname,
        'origin': f'{url.scheme}://{url.netloc}', 'route_hash': fingerprint(config['base_url'])}
    return recipient, config


def enqueue_job(job_id):
    # 投递失败保持数据库queued，beat补投；不把文字/原件/配置交给broker。
    from app.tasks.reports import process_report
    try:
        process_report.apply_async(args=[str(job_id)], retry=False)
    except Exception:
        return False
    return True


async def create_extract(db, report, data):
    replay = await replay_job(db, report, data)
    if replay:
        await db.commit()
        return replay
    expect_version(report, data)
    prior = await load_job(db, (report.workflow or {}).get('extract_id'))
    if prior and prior.status in ('queued', 'processing'):
        raise HTTPException(409, '本地识别正在处理，请查看现有进度或取消后重试')
    await cancel_pending(db, report, ['ai'])
    job = ReportProcessingJob(report_id=report.id, request_id=data.request_id, kind='extract',
        request_fingerprint=fingerprint(data.model_dump(mode='json')), source_version=report.source_version,
        source_hash=source_hash(report, 'extract'), input={}, result={})
    db.add(job)
    await db.flush()
    update_state(report, extract_id=str(job.id), ai_id=None, preview=None)
    await db.commit()
    await asyncio.to_thread(enqueue_job, job.id)
    return job


async def create_preview(db, report, user, data):
    expect_version(report, data)
    state = report.workflow or {}
    files = (await db.scalars(select(PatientReportFile).where(PatientReportFile.report_id == report.id)
        .order_by(PatientReportFile.position))).all()
    page_count = sum(file.page_count for file in files)
    pages = [page.model_dump() for page in data.pages] if data.pages is not None else None
    if pages is None:
        if state.get('preview'):
            pages = state['preview']['pages']
        else:
            job = await load_job(db, state.get('extract_id'), payload=True)
            if job and job.status == 'completed' and job.source_hash == source_hash(report, 'extract'):
                pages = job.result['pages']
            else:
                pages = [{'page': index + 1, 'text': ''} for index in range(page_count)]
    if len(pages) != page_count:
        raise HTTPException(422, '文字页数需与原件总页数一致，请逐页对照')
    try:
        masked = masked_pages(pages, user)
        text = outgoing_text(report.category, masked)
    except CandidateError as error:
        raise HTTPException(422, str(error)) from None
    warning = None
    try:
        recipient, _ = await recipient_config(db)
    except LLMConfigurationError:
        recipient, warning = None, '当前未配置可用的报告整理模型，可先编辑脱敏文字或人工录入'
    preview = {'id': str(uuid4()), 'policy': POLICY, 'source_version': report.source_version,
        'source_hash': source_hash(report, 'ai'), 'pages': masked, 'text': text, 'recipient': recipient,
        'created_at': now().isoformat(), 'expires_at': (now() + timedelta(minutes=30)).isoformat(), 'warning': warning}
    preview['hash'] = fingerprint(preview)
    from app.services.report_review import changed_source
    changed_source(report, masked)
    await cancel_pending(db, report, ['ai'])
    update_state(report, preview=preview)
    await db.commit()
    return public_preview(preview)


async def create_ai(db, report, user, data):
    replay = await replay_job(db, report, data)
    if replay:
        await db.commit()
        return replay
    preview = (report.workflow or {}).get('preview')
    if (not preview or str(data.preview_id) != preview['id'] or data.preview_hash != preview['hash']
        or data.expected_source_version != report.source_version or preview['source_hash'] != source_hash(report, 'ai')
        or datetime.fromisoformat(preview['expires_at']) < now()):
        raise HTTPException(409, '脱敏预览已更新或过期，请重新预览并逐次同意')
    try:
        recipient, _ = await recipient_config(db)
    except LLMConfigurationError:
        raise HTTPException(503, '当前报告整理模型不可用，请重新预览或人工录入') from None
    if preview['recipient'] != recipient or masked_pages(preview['pages'], user) != preview['pages']:
        raise HTTPException(409, '接收模型或身份信息已变化，请重新生成预览并同意')
    if not any(page['text'].strip() for page in preview['pages']):
        raise HTTPException(422, '请先对照原件填写可整理的文字')
    prior = await load_job(db, (report.workflow or {}).get('ai_id'))
    if prior and prior.status in ('queued', 'processing'):
        raise HTTPException(409, 'AI整理正在处理，请查看进度或取消后重新预览')
    # 同一预览只消费一次；失败或取消后仍须重新预览并重新同意。
    if preview.get('consumed_by'):
        raise HTTPException(409, '本次预览已提交过整理，请重新预览并逐次同意')
    job = ReportProcessingJob(report_id=report.id, request_id=data.request_id, kind='ai',
        request_fingerprint=fingerprint(data.model_dump(mode='json')), source_version=report.source_version,
        source_hash=source_hash(report, 'ai'), input={'preview': deepcopy(preview), 'category': report.category,
            'consented_at': now().isoformat(), 'consent': True, 'ownership_confirmed': True}, result={})
    db.add(job)
    await db.flush()
    preview = deepcopy(preview)
    preview['consumed_by'] = str(job.id)
    update_state(report, ai_id=str(job.id), preview=preview)
    await db.commit()
    await asyncio.to_thread(enqueue_job, job.id)
    return job


class ReportLLM(LLMService):
    """固定路由、关闭HTTP客户端、不自动重试或更换接收模型。"""
    def __init__(self, recipient, config):
        super().__init__(provider=recipient['provider'], timeout=45, max_retries=0)
        self.config, self.client = config, None

    async def _get_client(self):
        self.client = AsyncOpenAI(base_url=self.config['base_url'], api_key=self.config['api_key'], timeout=45, max_retries=0)
        return self.client

    async def _get_default_model(self):
        return self.config['default_model']


async def send_candidate(preview, category, config):
    if outgoing_text(category, preview['pages']) != preview['text']:
        raise CandidateError('脱敏发送文本不一致，请重新预览')
    llm = ReportLLM(preview['recipient'], config)
    try:
        async with asyncio.timeout(45):
            response = await llm.chat(messages=[{'role': 'user', 'content': preview['text']}],
                system_prompt=SYSTEM, max_tokens=8000)
        if response.tool_calls or response.finish_reason != 'stop':
            raise CandidateError('AI结果未完整结束，请重新预览或人工录入')
        return grounded_candidate(response.content, category, preview['pages'])
    finally:
        if llm.client:
            await llm.client.close()


async def locked_job(db, job_id, *, payload=True):
    reference = await db.scalar(select(ReportProcessingJob.report_id).where(ReportProcessingJob.id == job_id))
    if reference is None:
        return None, None
    report = await workspace_report(db, reference, lock=True, include_trashed=True)
    if report is None:
        return None, None
    job = await load_job(db, job_id, lock=True, payload=payload)
    return report, job


def active_source(report, job):
    return report.trashed_at is None and job.source_hash == source_hash(report, job.kind) and (report.workflow or {}).get(job.kind + '_id') == str(job.id)


def fail_job(job, code, message):
    job.status, job.error_code, job.error_message = 'failed', code, message
    job.completed_at, job.updated_at = now(), now()


async def run_job(job_id):
    """短锁保留租约；网络/OCR不占数据库行锁；迟到响应按租约和来源拒绝。"""
    job_id, lease = UUID(str(job_id)), uuid4()
    async with async_session_maker() as db:
        report, job = await locked_job(db, job_id)
        if job is None or job.status not in ('queued', 'processing'):
            return
        if job.status == 'processing':
            timeout = 900 if job.kind == 'extract' else 120
            if job.updated_at > now() - timedelta(seconds=timeout):
                return
            if job.dispatch_started_at:
                fail_job(job, 'delivery_unknown', '此前外发结果未知，不会自动重复发送，请重新预览并同意')
                await db.commit()
                return
        if not active_source(report, job):
            job.status, job.completed_at, job.updated_at = 'cancelled', now(), now()
            await db.commit()
            return
        if job.attempts >= 3:
            fail_job(job, 'worker_interrupted', '处理多次中断，请保留原件并重试或人工录入')
            await db.commit()
            return
        job.status, job.lease, job.updated_at = 'processing', lease, now()
        job.attempts += 1
        kind, report_id = job.kind, report.id
        await db.commit()
    result, code, message = None, None, None
    try:
        if kind == 'extract':
            async with async_session_maker() as db:
                originals = (await db.execute(select(PatientReportFile.id, PatientReportFile.position,
                    PatientReportFile.filename, PatientReportFile.mime_type, PatientReportFile.page_count, PatientReportFile.content)
                    .where(PatientReportFile.report_id == report_id).order_by(PatientReportFile.position))).all()
            pages, characters = [], 0
            for file in originals:
                async with async_session_maker() as db:
                    live_report, live_job = await locked_job(db, job_id, payload=False)
                    if live_job is None or live_job.status != 'processing' or live_job.lease != lease or not active_source(live_report, live_job):
                        return
                extracted = await extract_report_file(file.content, file.filename, file.mime_type)
                if len(extracted['pages']) != file.page_count:
                    raise ReportFileError('source_changed', '原件页数不一致，请保留原件并人工核对')
                for page in extracted['pages']:
                    characters += len(page['text'])
                    if characters > MAX_TEXT_CHARACTERS:
                        raise ReportFileError('too_much_text', '识别文字超出60000字，请人工录入必要内容')
                    pages.append({'page': len(pages) + 1, 'text': page['text'], 'file_id': str(file.id),
                        'file_position': file.position, 'file_page': page['page'], 'method': page['method']})
            result = {'pages': pages, 'needs_manual_entry': not any(page['text'].strip() for page in pages), 'source': 'platform_local_extraction'}
        else:
            async with async_session_maker() as db:
                report, job = await locked_job(db, job_id)
                if job is None or job.status != 'processing' or job.lease != lease or not active_source(report, job):
                    return
                preview, category = job.input['preview'], job.input['category']
                recipient, config = await recipient_config(db)
                user = await db.get(User, report.patient_id)
                if recipient != preview['recipient'] or masked_pages(preview['pages'], user) != preview['pages']:
                    raise CandidateError('接收模型或身份信息已变化，请重新预览并同意')
                # 外发分界先持久化；崩溃重投不会再发。取消晚于此处不能召回已发送文字。
                job.dispatch_started_at, job.updated_at = now(), now()
                await db.commit()
            result = await send_candidate(preview, category, config)
            result.update({'preview_id': preview['id'], 'preview_hash': preview['hash'], 'evidence_source': 'consented_text'})
    except ReportFileError as error:
        code, message = error.code, error.message
    except CandidateError as error:
        code, message = 'needs_review', str(error)
    except LLMConfigurationError:
        code, message = 'model_unavailable', '报告整理模型已不可用，请重新预览或人工录入'
    except Exception:
        # 不记录原始异常，第三方错误可能回显临床文字或HTTP鉴权参数。
        code, message = 'processing_failed', '报告整理失败，原件仍保留；请重新预览并同意或人工录入'
    async with async_session_maker() as db:
        report, job = await locked_job(db, job_id)
        if job is None or job.status != 'processing' or job.lease != lease or not active_source(report, job):
            return
        if code:
            fail_job(job, code, message)
        else:
            job.status, job.result, job.completed_at, job.updated_at = 'completed', result, now(), now()
        await db.commit()


async def pending_jobs():
    async with async_session_maker() as db:
        jobs = (await db.scalars(select(ReportProcessingJob).join(PatientReport, PatientReport.id == ReportProcessingJob.report_id)
            .where(PatientReport.trashed_at.is_(None), or_(ReportProcessingJob.status == 'queued',
            and_(ReportProcessingJob.status == 'processing', or_(
                and_(ReportProcessingJob.kind == 'extract', ReportProcessingJob.updated_at < now() - timedelta(seconds=900)),
                and_(ReportProcessingJob.kind == 'ai', ReportProcessingJob.updated_at < now() - timedelta(seconds=120))))))
            .order_by(ReportProcessingJob.updated_at).limit(20))).all()
        return [str(job.id) for job in jobs]
