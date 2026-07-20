import { table, integer, text, boolean, index, sql } from 'sdk/db';

export const users = table('users', {
  chatId: integer('chat_id').primaryKey(),
  username: text('username'),
  isOwner: boolean('is_owner').default(false),
  isBlocked: boolean('is_blocked').default(false),
  wantsConfigs: boolean('wants_configs').default(false), // subscribed to config/proxy broadcasts
  msgWindowStart: integer('msg_window_start', { mode: 'timestamp' }),
  msgWindowCount: integer('msg_window_count').default(0),
  created: integer('created_at', { mode: 'timestamp' }).default(sql`(unixepoch())`),
}, (t) => ({
  createdIdx: index('idx_users_created').on(t.created),
}));

export const messages = table('messages', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  chatId: integer('chat_id').notNull(),
  direction: text('direction').notNull(), // 'in' | 'out'
  text: text('text'),
  created: integer('created_at', { mode: 'timestamp' }).default(sql`(unixepoch())`),
}, (t) => ({
  chatIdx: index('idx_messages_chat').on(t.chatId),
}));