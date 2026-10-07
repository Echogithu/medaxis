/** 测试用随机端口 Vite：沿用项目配置，只把代理指向本轮隔离后端。 */
import { createServer } from 'vite';

const api = new URL(process.env.REPORTS_API_URL);
const database = new URL(process.env.DATABASE_URL);
const web = new URL(process.env.REPORTS_WEB_URL);
if (![api, web, database].every(url => ['127.0.0.1', 'localhost'].includes(url.hostname)) ||
    !database.pathname.startsWith('/medaxis_demo_e2e_')) throw new Error('仅允许合成隔离测试目标');
const server = await createServer({ server: {
  host: '127.0.0.1', port: Number(web.port), strictPort: true,
  proxy: { '/api': { target: api.origin, changeOrigin: true } },
} });
await server.listen();
server.printUrls();
