import { clearGuestToken, migrateGuestData } from '../api/agent.ts';
import { getToken } from '../api/client.ts';
import { migrateGuestChatHistory } from '../state/chatHistory.ts';

/** 服务端迁移和本地历史合并都成功后，才清理访客身份。 */
export async function completeGuestMigration(): Promise<number> {
  const guestToken = localStorage.getItem('guest_token');
  if (!guestToken) return 0;

  const userToken = getToken();
  if (!userToken) throw new Error('请先登录后再迁移访客记录');

  const migrated = await migrateGuestData(guestToken);
  migrateGuestChatHistory(guestToken, userToken);
  clearGuestToken();
  return migrated;
}
