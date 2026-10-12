"""用预置合成 API/SSE 重放当前页面，录制招聘展示素材，不连接业务库或模型。"""
import argparse
import base64
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / 'docs/media/demo/scenario.json'
MEDIA = ROOT / 'docs/media'


def validate_scenario(data):
    assert data['meta']['synthetic'] is True
    assert data['meta']['recording_mode'] == 'local_api_sse_replay'
    assert data['user']['id'] == data['profile']['id']
    assert data['profile']['email'].endswith('@example.test')
    ids = {case['id'] for case in data['cases']}
    assert data['preparation']['case_id'] == data['cases'][0]['id']
    assert all(plan['source_case_id'] in ids for plan in data['plans'])
    assert all(plan['source_type'] == 'patient_reported' for plan in data['plans'])
    assert all(not fact['confirmed'] for fact in data['preparation']['known_facts'])
    assert data['report']['confidence'] == 'low'
    assert data['report']['interview_is_sufficient'] is False
    assert len(data['interview']['questions']) == len(data['interview']['answers']) == 2
    for question, answer in zip(data['interview']['questions'], data['interview']['answers']):
        assert answer in question['options']
    for citation in data['report']['knowledge_citations']:
        assert citation['url'].startswith('https://www.nhs.uk/')
        assert citation['source_engine'] == 'showcase_preloaded'
        assert citation['relevance_method'] == 'unassessed'
    medication_states = {item['status'] for item in data['profile']['medications']}
    assert medication_states <= {'active', 'stopped'}


def synthetic_token(subject):
    """只在被完整接管的页面中使用；不能作为真实服务的认证凭据。"""
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
    return f'{encode({"alg": "none", "typ": "JWT"})}.{encode({"sub": subject})}.showcase-invalid-signature'


def sse(*items):
    return ''.join(f'event: {name}\ndata: {json.dumps(value, ensure_ascii=False)}\n\n' for name, value in items)


class ShowcaseAPI:
    def __init__(self, data):
        self.data = deepcopy(data)
        self.requests = []
        self.unknown = []
        self.answers = []
        self.completed = False

    def route(self, route):
        request = route.request
        parsed = urlparse(request.url)
        path, query = parsed.path.rstrip('/'), parse_qs(parsed.query)
        self.requests.append({'method': request.method, 'path': path})
        data = self.data
        current_id = data['cases'][0]['id']
        session = data['interview']['session_id']
        if path.endswith('/agents/route/stream'):
            assert request.method == 'POST'
            assert request.post_data_json['message'] == data['chief_complaint']
            assert not {'message', 'token', 'guest_token'} & query.keys()
            body = sse(('text', {'text': data['interview']['opening']}),
                       ('question', {'question_id': data['interview']['questions'][0]['question_id'],
                                     'questions': data['interview']['questions']}),
                       ('complete', {'status': 'waiting_for_answer', 'session_id': session}))
            route.fulfill(content_type='text/event-stream', body=body)
            return
        if path.endswith('/agents/route/stream/continue'):
            index = len(self.answers)
            assert request.method == 'POST' and index < 2
            assert query['session_id'] == [session]
            assert query['question_id'] == [data['interview']['questions'][index]['question_id']]
            answer = request.post_data_json['answer']
            assert answer == data['interview']['answers'][index]
            self.answers.append(answer)
            if index == 0:
                body = sse(('text', {'text': '已记录程度：轻微，能照常做事。接下来确认伴随情况。'}),
                           ('complete', {'status': 'waiting_for_answer', 'session_id': session}))
            else:
                self.completed = True
                body = sse(('text', {'text': '已把本次陈述整理为问诊总结；仍有未知信息，请就医时继续核对。'}),
                           ('structured', data['report']),
                           ('complete', {'status': 'completed', 'session_id': session, 'case_id': current_id}))
            route.fulfill(content_type='text/event-stream', body=body)
            return
        if request.method != 'GET':
            self.unknown.append(f'{request.method} {path}')
            route.fulfill(status=405, json={'detail': '展示录制不执行真实写入'})
            return
        if path.endswith('/demo/status'):
            result = {'enabled': False, 'limit': 0, 'used': 0, 'remaining': 0, 'report_center_ready': False}
        elif path.endswith('/auth/me'):
            result = data['user']
        elif path.endswith('/patient/profile'):
            result = data['profile']
        elif path.endswith('/patient/reminders/count'):
            result = {'follow_up': 0, 'medication': 0, 'total': 0}
        elif path.endswith('/patient/reminders'):
            result = {'items': data['reminders'], 'next_cursor': None}
        elif path.endswith('/patient/measurements'):
            result = {'items': [], 'has_more': False}
        elif path.endswith('/patient/care-plans'):
            plans = data['plans']
            if query.get('status'):
                plans = [plan for plan in plans if plan['status'] == query['status'][0]]
            result = {'items': plans, 'next_cursor': None}
        elif path.endswith('/patient/ai-actions/pending'):
            result = {'items': []}
        elif path.endswith('/patient/cases'):
            result = data['cases'] if self.completed else data['cases'][1:]
        elif '/patient/cases/' in path and path.endswith('/recovery'):
            case_id = path.split('/')[-2]
            case = next(case for case in data['cases'] if case['id'] == case_id)
            assert case_id != current_id or self.completed
            result = {'case': case, 'report': data['report'] if case_id == current_id else None,
                      'materials': [], 'lab_reports': []}
        elif '/patient/cases/' in path and path.endswith('/reports'):
            result = {'items': [], 'total': 0, 'page': 1, 'limit': 10}
        elif '/patient/cases/' in path and path.endswith('/preparation'):
            result = {'package': data['preparation'] if path.split('/')[-2] == current_id else None, 'history': []}
        elif '/patient/cases/' in path and path.endswith('/post-visit-feedback'):
            result = {'feedback': None, 'history': []}
        else:
            self.unknown.append(f'{request.method} {path}')
            route.fulfill(status=404, json={'detail': '展示夹具未定义此接口'})
            return
        route.fulfill(json=result)


def font_path(value):
    candidates = [Path(value)] if value else [Path('C:/Windows/Fonts/msyh.ttc'),
        Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
        Path('/System/Library/Fonts/PingFang.ttc')]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError('未找到中文字体；请用 --font 指定本机中文字体路径。')


class Capture:
    def __init__(self, page, output, font):
        self.page, self.output, self.font = page, output, font
        self.frames = []
        self.durations = []
        self.labels = []
        self.assets = []

    def settle(self):
        self.page.wait_for_load_state('networkidle')
        self.page.evaluate('document.fonts.ready')
        self.page.wait_for_timeout(250)
        assert self.page.evaluate('document.documentElement.scrollWidth <= innerWidth')

    def screenshot(self, name):
        self.settle()
        self.page.screenshot(path=str(self.output / name))
        self.assets.append(name)

    def frame(self, label, duration=1800):
        self.settle()
        raw = Image.open(BytesIO(self.page.screenshot())).convert('RGB')
        width = 1080
        height = round(raw.height * width / raw.width)
        raw = raw.resize((width, height), Image.Resampling.LANCZOS)
        frame = Image.new('RGB', (width, height + 66), '#0f3735')
        frame.paste(raw, (0, 0))
        draw = ImageDraw.Draw(frame)
        draw.text((22, height + 8), label, font=ImageFont.truetype(str(self.font), 20), fill='white')
        draw.text((22, height + 37), '合成案例 · 本地界面重放 · 回答与总结预置，未调用真实模型',
                  font=ImageFont.truetype(str(self.font), 14), fill='#b5d9d0')
        self.frames.append(frame)
        self.durations.append(duration)
        self.labels.append(label)

    def gif(self):
        # 所有帧使用同一调色板，减少页面切换时的颜色闪烁；不改页面内容。
        thumbs = [frame.resize((270, round(frame.height / 4))) for frame in self.frames]
        samples = Image.new('RGB', (270, sum(thumb.height for thumb in thumbs)), 'white')
        offset = 0
        for thumb in thumbs:
            samples.paste(thumb, (0, offset))
            offset += thumb.height
        palette = samples.quantize(colors=256)
        frames = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in self.frames]
        name = 'patient-journey.gif'
        frames[0].save(self.output / name, save_all=True, append_images=frames[1:],
                       duration=self.durations, loop=0, disposal=2, optimize=True)
        self.assets.append(name)


def source_fingerprint():
    digest = sha256()
    for file in sorted((ROOT / 'frontend/src').rglob('*')):
        if file.is_file() and file.suffix in {'.ts', '.tsx', '.css'}:
            digest.update(file.relative_to(ROOT).as_posix().encode())
            digest.update(file.read_bytes())
    return digest.hexdigest()


def verify_media(output):
    """逐帧解码并核对素材清单，也检查 README 的相对素材链接。"""
    output = output.resolve()
    manifest = json.loads((output / 'demo/manifest.json').read_text(encoding='utf-8'))
    assert manifest['scenario_sha256'] == sha256(SCENARIO.read_bytes()).hexdigest(), '场景已变化，请重新录制'
    assert manifest['frontend_source_sha256'] == source_fingerprint(), '前端源码已变化，请重新录制'
    assert manifest['mode'] == 'local_api_sse_replay'
    assert manifest['real_model_calls'] == manifest['real_database_writes'] == 0
    assert not manifest['unknown_api_routes'] and not manifest['browser_errors']
    assert not manifest['blocked_local_requests']
    names = {item['file'] for item in manifest['assets']}
    assert len(names) == len(manifest['assets']) == 10
    total = 0
    for item in manifest['assets']:
        file = (output / item['file']).resolve()
        assert file.parent == output and file.suffix in {'.png', '.gif'}
        payload = file.read_bytes()
        assert len(payload) == item['bytes'] and sha256(payload).hexdigest() == item['sha256'], file.name
        total += len(payload)
        with Image.open(file) as img:
            assert (img.width, img.height) == (item['width'], item['height'])
            duration = 0
            for index in range(img.n_frames):
                img.seek(index)
                img.load()
                duration += img.info.get('duration', 0)
            if file.suffix == '.gif':
                assert img.n_frames == item['frames'] == len(manifest['gif_steps']) == 9
                assert duration == item['duration_ms'] == 22200
                assert img.info.get('loop') == 0 and len(payload) < 2 * 1024 * 1024
    for document in [ROOT / 'README.md', MEDIA / 'README.md']:
        markdown = document.read_text(encoding='utf-8')
        markdown = re.sub(r'<!--.*?-->|```.*?```|`[^`\n]+`', '', markdown, flags=re.S)
        referenced = set()
        for target in re.findall(r'!?\[[^\]]*\]\(([^\s)]+)\)', markdown):
            if not target.startswith(('https://', 'http://', '#')):
                resolved = (document.parent / target.split('#')[0]).resolve()
                if resolved.is_relative_to(MEDIA):
                    assert resolved.is_file(), f'{document.name}: {target}'
                    if resolved.parent == MEDIA and resolved.suffix in {'.png', '.gif'}:
                        referenced.add(resolved.name)
        assert referenced == names, f'{document}: 素材引用与清单不一致'
    print(f'PASS: 10 份素材完整解码、尺寸与 SHA-256 一致；GIF 9 帧/22.2 秒；README 素材链接有效；总计 {total:,} bytes。')


def record(args, data):
    parsed = urlparse(args.base_url)
    if parsed.hostname not in {'127.0.0.1', 'localhost'} or parsed.scheme not in {'http', 'https'}:
        raise ValueError('只允许在本机地址录制；本脚本不登录外部站点。')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=args.channel, headless=True)
        try:
            context = browser.new_context(viewport={'width': 1280, 'height': 900},
                                          reduced_motion='reduce', timezone_id='Asia/Shanghai', locale='zh-CN',
                                          service_workers='block')
            api = ShowcaseAPI(data)
            external = []
            blocked_local = []
            origin = (parsed.scheme, parsed.hostname, parsed.port)
            documents = {'/', '/login', '/chat', '/cases', '/today', '/health', '/followups'}
            def network(route):
                url = urlparse(route.request.url)
                if (url.scheme, url.hostname, url.port) != origin:
                    external.append(url.hostname)
                    route.abort()
                elif url.path.startswith('/api/v1/'):
                    api.route(route)
                elif route.request.method == 'GET' and (
                    (route.request.resource_type == 'document' and url.path in documents)
                    or url.path in {'/favicon.ico', '/favicon.svg'}
                    or (route.request.resource_type in {'script', 'stylesheet', 'image', 'font'}
                        and (url.path.startswith(('/src/', '/node_modules/', '/@vite/', '/@id/'))
                             or url.path == '/@react-refresh'))
                ):
                    route.continue_()
                else:
                    blocked_local.append(f'{route.request.method} {url.path}')
                    route.abort()
            context.route('**/*', network)
            # 仅保持本地模拟连接，既不转发消息，也不连接服务器；避免 Vite 重连轮询。
            context.route_web_socket('**/*', lambda socket: socket.on_message(lambda message: None))
            page = context.new_page()
            page.clock.install(time=datetime.fromisoformat(data['meta']['as_of'] + 'T01:35:00+00:00'))
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            base = args.base_url.rstrip('/')
            page.goto(base + '/login')
            page.evaluate('jwt => {localStorage.setItem("access_token", jwt);localStorage.setItem("user_role", "patient")}',
                          synthetic_token(data['user']['id']))
            page.goto(base + '/chat')
            field = page.get_by_placeholder('描述您的症状，或补充检查报告…')
            expect(field).to_be_enabled()
            capture = Capture(page, output, font_path(args.font))
            field.fill(data['chief_complaint'])
            capture.frame('01 说清哪里不舒服：用自己的话描述症状')
            field.press('Enter')
            first, second = data['interview']['answers']
            expect(page.get_by_role('button', name=first, exact=True)).to_be_enabled()
            capture.screenshot('consultation.png')
            capture.frame('02 补充两点信息：程度与伴随情况', 2600)
            page.get_by_role('button', name=first, exact=True).click()
            expect(page.get_by_role('button', name=second, exact=True)).to_be_enabled()
            page.get_by_role('button', name=second, exact=True).scroll_into_view_if_needed()
            capture.frame('03 按问题补充：保留本人回答', 2200)
            page.get_by_role('button', name=second, exact=True).click()
            dialog = page.get_by_role('dialog')
            expect(dialog.get_by_text('可能是什么问题', exact=True)).to_be_visible()
            expect(page.get_by_role('button', name='查看问诊记录', exact=True)).to_be_enabled()
            capture.screenshot('evidence-report.png')
            capture.frame('04 看懂问诊总结：可能的原因与下一步', 3200)
            dialog.get_by_role('link', name='引用 S1，查看来源', exact=True).first.click()
            expect(dialog.get_by_role('article', name='参考资料 S1')).to_be_visible()
            dialog.get_by_role('article', name='参考资料 S1').evaluate(
                "element => element.scrollIntoView({behavior: 'instant', block: 'center'})")
            capture.screenshot('reference-source.png')
            capture.frame('05 打开参考资料：查看原文与未知项', 2200)
            dialog.get_by_role('button', name='回到总结顶部', exact=True).click()
            page.get_by_role('button', name='查看问诊记录', exact=True).click()
            expect(page).to_have_url(base + '/cases?case_id=' + data['cases'][0]['id'])
            expect(page.get_by_role('button', name='准备去就诊', exact=True)).to_be_visible()
            capture.frame('06 回到同一条病例：再次找回问诊资料', 2200)
            page.get_by_role('button', name='准备去就诊', exact=True).click()
            expect(page.get_by_role('button', name='核对或修改病情', exact=True)).to_be_visible()
            page.get_by_role('button', name='核对或修改病情', exact=True).click()
            expect(page.get_by_text('我确认这项患者陈述准确', exact=True).first).to_be_visible()
            page.get_by_role('button', name='收起病情核对', exact=True).evaluate(
                "element => element.scrollIntoView({behavior: 'instant', block: 'start'})")
            capture.frame('07 就医前核对：本人陈述与未知信息分开', 2800)
            page.get_by_role('button', name='收起病情核对', exact=True).click()
            page.get_by_role('button', name='查看完整摘要', exact=True).click()
            preview = page.get_by_role('textbox', name='就诊摘要预览', exact=True)
            expect(preview).to_have_value(re.compile('待本人核对'))
            preview.scroll_into_view_if_needed()
            capture.screenshot('case-preparation.png')
            capture.frame('08 准备给医生看的摘要：保留原话与待问问题', 2800)
            page.goto(base + '/today')
            expect(page.get_by_role('heading', name='今日健康', exact=True)).to_be_visible()
            expect(page.get_by_text('记录今天头痛出现的时间和变化', exact=False).first).to_be_visible()
            capture.screenshot('today-health.png')
            capture.frame('09 延续到日常记录：查看今天要做什么', 2400)
            page.goto(base + '/health')
            expect(page.get_by_role('heading', name='健康档案', exact=True)).to_be_visible()
            expect(page.locator('main').get_by_text('林晓（演示）', exact=True)).to_be_visible()
            capture.screenshot('health-records.png')
            page.goto(base + '/followups')
            expect(page.get_by_text(data['plans'][0]['title'], exact=True).first).to_be_visible()
            capture.screenshot('followup-plans.png')
            capture.gif()
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(base + '/followups')
            expect(page.get_by_text(data['plans'][0]['title'], exact=True).first).to_be_visible()
            capture.screenshot('followups-mobile.png')
            page.goto(base + '/health')
            expect(page.get_by_role('heading', name='健康档案', exact=True)).to_be_visible()
            capture.screenshot('health-mobile.png')
            assert not api.unknown, api.unknown
            assert not blocked_local, blocked_local
            assert not errors, errors
            assert api.answers == data['interview']['answers'] and api.completed
            manifest = {'schema_version': 1, 'scenario': 'demo/scenario.json',
                        'scenario_sha256': sha256(SCENARIO.read_bytes()).hexdigest(),
                        'frontend_source_sha256': source_fingerprint(),
                        'recorded_at': datetime.now(timezone.utc).isoformat(),
                        'display_clock': data['meta']['as_of'], 'mode': 'local_api_sse_replay',
                        'real_model_calls': 0, 'real_database_writes': 0,
                        'api_requests': len(api.requests), 'unknown_api_routes': api.unknown,
                        'blocked_local_requests': blocked_local,
                        'browser_errors': errors, 'blocked_external_hosts': sorted(set(external)),
                        'gif_steps': capture.labels, 'assets': []}
            for name in capture.assets:
                file = output / name
                with Image.open(file) as img:
                    item = {'file': name, 'width': img.width, 'height': img.height,
                            'bytes': file.stat().st_size, 'sha256': sha256(file.read_bytes()).hexdigest()}
                    if file.suffix == '.gif':
                        item['frames'] = img.n_frames
                        item['duration_ms'] = sum(capture.durations)
                manifest['assets'].append(item)
            (output / 'demo/manifest.json').parent.mkdir(parents=True, exist_ok=True)
            (output / 'demo/manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(f'PASS: {len(capture.assets)} 份页面素材，{len(capture.frames)} 段 GIF；无未知 API、无浏览器异常、无真实模型/数据库写入。')
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:3001')
    parser.add_argument('--channel', default=os.getenv('PLAYWRIGHT_CHANNEL', 'msedge'))
    parser.add_argument('--output', type=Path, default=MEDIA)
    parser.add_argument('--font', help='本机中文字体路径（不会复制到仓库）')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--validate-only', action='store_true')
    mode.add_argument('--verify-media', action='store_true')
    args = parser.parse_args()
    data = json.loads(SCENARIO.read_text(encoding='utf-8'))
    validate_scenario(data)
    if args.validate_only:
        print('PASS: 合成场景结构、归属、问答、未知状态与预置来源一致。')
    elif args.verify_media:
        verify_media(args.output)
    else:
        record(args, data)


if __name__ == '__main__':
    main()
