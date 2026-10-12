"""可关闭的面试演示访问控制与持久化供应商请求额度。"""
from contextvars import ContextVar
from dataclasses import dataclass
from http.cookies import SimpleCookie
from urllib.parse import parse_qs
from uuid import UUID

import httpx
from fastapi import HTTPException
from openai import DefaultAsyncHttpxClient
from sqlalchemy import select
from starlette.responses import JSONResponse

from app.db.session import AsyncSessionLocal
from app.models.config import SystemSetting
from app.models.user import User, UserRole, UserStatus

PREFIX = 'interview_demo.'
demo_actor: ContextVar[str | None] = ContextVar('interview_demo_actor', default=None)


@dataclass(frozen=True)
class DemoPolicy:
    enabled: bool = False
    user_id: str = ''
    limit: int = 0
    used: int = 0
    report_center_ready: bool = False

    def public_status(self):
        return {'enabled': self.enabled, 'limit': self.limit, 'used': self.used,
                'remaining': max(0, self.limit - self.used), 'report_center_ready': self.report_center_ready}


async def demo_max_tokens(value: int | None) -> int | None:
    policy = await load_policy()
    return min(value or 2048, 8192) if policy.enabled else value


async def load_policy(db=None) -> DemoPolicy:
    if db is None:
        async with AsyncSessionLocal() as session:
            return await load_policy(session)
    rows = (await db.scalars(select(SystemSetting).where(SystemSetting.key.startswith(PREFIX, autoescape=True)))).all()
    values = {row.key.removeprefix(PREFIX): row.value for row in rows}
    if values.get('enabled', 'false') == 'false':
        return DemoPolicy()
    try:
        if values['enabled'] != 'true':
            raise ValueError()
        user_id = str(UUID(values['user_id']))
        limit, used = int(values['limit']), int(values['used'])
        if not 1 <= limit <= 20 or used < 0:
            raise ValueError()
        return DemoPolicy(True, user_id, limit, used, values.get('report_center_ready') == 'true')
    except (KeyError, ValueError) as exc:
        raise HTTPException(503, '演示费用控制配置不可用，已停止模型调用') from exc


async def reserve_provider_request(request: httpx.Request) -> None:
    """每次实际 HTTP 尝试先扣额度，包括 SDK 重试；失败不退还，绝不自动补充。"""
    async with AsyncSessionLocal() as db:
        policy = await load_policy(db)
        if not policy.enabled:
            return
        if demo_actor.get() != policy.user_id:
            raise HTTPException(403, '面试演示仅允许专用账号调用模型；后台模型任务暂停')
        # 单独连接锁住同一个计数行，多请求/多进程共享上限；数据库失败则不发出请求。
        counter = await db.scalar(select(SystemSetting).where(
            SystemSetting.key == PREFIX + 'used').with_for_update())
        if counter is None:
            raise HTTPException(503, '演示额度不可用，已停止模型调用')
        try:
            used = int(counter.value)
        except ValueError as exc:
            raise HTTPException(503, '演示额度不可用，已停止模型调用') from exc
        if used < 0 or used >= policy.limit:
            raise HTTPException(429, '本次面试演示的模型请求额度已用完，资料仍可浏览')
        counter.value = str(used + 1)
        await db.commit()


def provider_http_client(**kwargs):
    """保留 SDK 的连接默认值，在发送前统一计费拦截，不修改供应商或回答。"""
    return DefaultAsyncHttpxClient(event_hooks={'request': [reserve_provider_request]}, **kwargs)


class InterviewDemoMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] != 'http' or path in ('/health', '/ready'):
            return await self.app(scope, receive, send)
        try:
            policy = await load_policy()
            if path == '/api/v1/demo/status':
                return await JSONResponse(policy.public_status())(scope, receive, send)
            if not policy.enabled:
                policy = None
            else:
                receive = await self.authorize(scope, receive, policy)
        except HTTPException as exc:
            return await JSONResponse({'detail': exc.detail}, status_code=exc.status_code)(scope, receive, send)
        except Exception:
            # 配置读取失败时关闭入口，不吞掉原应用或流式响应的错误。
            return await JSONResponse({'detail': '演示服务保护检查失败，请稍后重试'}, status_code=503)(scope, receive, send)
        actor = demo_actor.set(policy.user_id if policy else None)
        started = False
        async def guarded_send(message):
            nonlocal started
            if message['type'] == 'http.response.start':
                started = True
            await send(message)
        try:
            return await self.app(scope, receive, guarded_send)
        except Exception:
            if not policy or started:
                raise
            # 演示环境不能把开发模式的堆栈或数据库错误返回给浏览者。
            return await JSONResponse({'detail': '当前演示操作暂不可用，请稍后重试'}, status_code=500)(scope, receive, send)
        finally:
            demo_actor.reset(actor)

    async def authorize(self, scope, receive, policy):
        path = scope['path']
        if path in ('/docs', '/redoc', '/openapi.json') or path.startswith('/uploads/'):
            raise HTTPException(404, '面试演示不开放此入口')
        if not path.startswith('/api/'):
            return receive
        if path.startswith(('/api/v1/auth/guest', '/api/v1/auth/register')):
            raise HTTPException(403, '面试演示已停用访客和公开注册，请使用专用演示账号')
        if path in ('/api/v1/auth/change-password', '/api/v1/users/me/password', '/api/v1/auth/switch-role'):
            raise HTTPException(403, '共享演示账号不能修改登录凭据')
        if path.startswith('/api/v1/llm/'):
            raise HTTPException(403, '面试演示请通过原AI问诊入口使用默认模型')
        if path == '/api/v1/auth/login':
            # 仅允许专用身份进入原密码验证流程，不向其他真实账号发放令牌。
            body = bytearray()
            while True:
                message = await receive()
                if message['type'] != 'http.request':
                    raise HTTPException(400, '登录请求未完成')
                body.extend(message.get('body', b''))
                if len(body) > 8192:
                    raise HTTPException(413, '登录请求过大')
                if not message.get('more_body'):
                    break
            username = parse_qs(bytes(body).decode('utf-8', errors='replace')).get('username', [''])[0]
            async with AsyncSessionLocal() as db:
                allowed = await db.scalar(select(User.id).where(
                    User.id == UUID(policy.user_id), User.email == username,
                    User.role == UserRole.PATIENT, User.status == UserStatus.ACTIVE))
            if allowed is None:
                raise HTTPException(403, '面试演示仅开放专用患者账号')
            async def replay():
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return replay
        # 继续使用原 JWT、撤销及账号状态检查；不会以演示模式绕过认证。
        from app.api.deps import _resolve_token
        headers = dict(scope.get('headers', []))
        authorization = headers.get(b'authorization', b'').decode()
        query = parse_qs(scope.get('query_string', b'').decode('utf-8', errors='replace'))
        cookies = SimpleCookie()
        cookies.load(headers.get(b'cookie', b'').decode('utf-8', errors='replace'))
        token = (authorization[7:] if authorization.lower().startswith('bearer ') else None) or (
            query.get('token') or query.get('guest_token') or [None])[0] or (
            cookies['auth_token'].value if 'auth_token' in cookies else None)
        async with AsyncSessionLocal() as db:
            user, _, is_guest, _ = await _resolve_token(token, db)
            if user is None or is_guest:
                raise HTTPException(401, '请登录专用演示账号')
            if str(user.id) != policy.user_id or user.role != UserRole.PATIENT:
                raise HTTPException(403, '面试演示仅开放专用患者账号')
        if path.startswith('/api/v1/patient/reports') or (
            path.startswith('/api/v1/patient/cases/') and path.rstrip('/').endswith('/reports')):
            if not policy.report_center_ready:
                raise HTTPException(503, '报告中心数据库尚未初始化，合成报告可在病例附件中查看')
        return receive
