"""患者独立报告归档；与问诊、病例的生命周期无关。"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class PatientReport(Base):
    __tablename__ = 'patient_reports'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    institution: Mapped[str] = mapped_column(String(200), nullable=False, default='')
    examination_date: Mapped[date | None] = mapped_column(Date)
    report_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default='')
    ownership_declared: Mapped[bool] = mapped_column(nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    links_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default='0')
    lifecycle_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default='0')
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 工作区的脱敏预览独立加载，报告列表不读取临床文字。
    workflow: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default='{}', deferred=True, deferred_raiseload=True)
    # 这里只保存核对版本指针与来源代次，列表不读取临床内容。
    review_state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default='{}')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        UniqueConstraint('patient_id', 'request_id', name='uq_report_patient_request'),
        CheckConstraint("category IN ('lab', 'imaging', 'other')", name='ck_report_category'),
        CheckConstraint('revision >= 0 AND source_version >= 1', name='ck_report_revision'),
        Index('ix_report_patient_created', 'patient_id', 'created_at', 'id'),
        Index('ix_report_patient_content', 'patient_id', 'content_hash'),
    )


class PatientReportFile(Base):
    __tablename__ = 'patient_report_files'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('patient_reports.id', ondelete='CASCADE'), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # 列表和详情只载入文件元数据；原件通过本人下载接口单独取出。
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True, deferred_raiseload=True)
    __table_args__ = (
        UniqueConstraint('report_id', 'position', name='uq_report_file_position'),
        CheckConstraint('position >= 0 AND byte_size > 0 AND page_count > 0', name='ck_report_file_bounds'),
    )


class ReportProcessingJob(Base):
    __tablename__ = 'patient_report_jobs'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('patient_reports.id', ondelete='CASCADE'), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default='queued')
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dispatch_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(String(200))
    input: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, deferred=True, deferred_raiseload=True)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, deferred=True, deferred_raiseload=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        UniqueConstraint('report_id', 'request_id', name='uq_report_job_request'),
        CheckConstraint("kind IN ('extract', 'ai')", name='ck_report_job_kind'),
        CheckConstraint("status IN ('queued', 'processing', 'completed', 'failed', 'cancelled')", name='ck_report_job_status'),
        CheckConstraint('attempts >= 0 AND source_version >= 1', name='ck_report_job_bounds'),
        Index('ix_report_job_pending', 'status', 'updated_at'),
    )


class ReportReviewVersion(Base):
    """人工草稿/确认只追加版本；确认保留精确草稿及机器候选的出处。"""
    __tablename__ = 'patient_report_review_versions'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('patient_reports.id', ondelete='CASCADE'), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    based_on_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    candidate_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    confirmed_draft_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, deferred=True, deferred_raiseload=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        UniqueConstraint('report_id', 'request_id', name='uq_report_review_request'),
        UniqueConstraint('report_id', 'revision', name='uq_report_review_revision'),
        CheckConstraint("kind IN ('draft', 'confirmed')", name='ck_report_review_kind'),
        CheckConstraint('revision > 0 AND source_version > 0 AND source_epoch >= 0', name='ck_report_review_bounds'),
        Index('ix_report_review_history', 'report_id', 'revision'),
    )


class ReportCaseLink(Base):
    """患者侧引用固定来源；病例删除只删除引用，不删除独立报告。"""
    __tablename__ = 'patient_report_case_links'
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('patient_reports.id', ondelete='CASCADE'), primary_key=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('medical_cases.id', ondelete='CASCADE'), primary_key=True)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    review_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('patient_report_review_versions.id', ondelete='SET NULL'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (Index('ix_report_link_case', 'case_id', 'report_id'),
        CheckConstraint('source_version > 0', name='ck_report_link_source'))


class ReportManagementOperation(Base):
    """只存提交合同及修订编号，重放不重做已经解除的引用。"""
    __tablename__ = 'patient_report_management_operations'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('patient_reports.id', ondelete='CASCADE'), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (UniqueConstraint('report_id', 'request_id', name='uq_report_management_request'),)


class ReportUploadSubmission(Base):
    """复用也是一次提交；结果删除后仍保留编号墓碑，重试不重新归档。"""
    __tablename__ = 'patient_report_upload_submissions'
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    report_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('patient_reports.id', ondelete='SET NULL'))
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (CheckConstraint("outcome IN ('archived', 'reused')", name='ck_report_upload_outcome'),
        Index('ix_report_upload_result', 'report_id'))


class ReportLifecycleSubmission(Base):
    """管理操作墓碑不随报告删除；不保存名称、文字或临床内容。"""
    __tablename__ = 'patient_report_lifecycle_submissions'
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (CheckConstraint("kind IN ('trash', 'restore', 'purge')", name='ck_report_lifecycle_kind'),)
