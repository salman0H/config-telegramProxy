import { table, integer, text, boolean, index, sql } from 'sdk/db';

export const users = table('users', {
  chatId: integer('chat_id').primaryKey(),
  username: text('username'),
  isOwner: boolean('is_owner').default(false),
  isBlocked: boolean('is_blocked').default(false),
  wantsConfigs: boolean('wants_configs').default(false),
  msgWindowStart: integer('msg_window_start', { mode: 'timestamp' }),
  msgWindowCount: integer('msg_window_count').default(0),
  created: integer('created_at', { mode: 'timestamp' }).default(sql`(unixepoch())`),
}, (t) => ({
  createdIdx: index('idx_users_created').on(t.created),
}));

export const messages = table('messages', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  chatId: integer('chat_id').notNull(),
  direction: text('direction').notNull(),
  text: text('text'),
  created: integer('created_at', { mode: 'timestamp' }).default(sql`(unixepoch())`),
}, (t) => ({
  chatIdx: index('idx_messages_chat').on(t.chatId),
}));

export const todos = table('todos', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  chatId: integer('chat_id').notNull(),
  task: text('task').notNull(),
  isCompleted: boolean('is_completed').default(false),
  created: integer('created_at', { mode: 'timestamp' }).default(sql`(unixepoch())`),
}, (t) => ({
  todoChatIdx: index('idx_todos_chat').on(t.chatId),
}));

export const learnings = table('learnings', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  chatId: integer('chat_id').notNull(),
  subject: text('subject').notNull(),
  content: text('content').notNull(),
  created: integer('created_at', { mode: 'timestamp' }).default(sql`(unixepoch())`),
}, (t) => ({
  learningChatIdx: index('idx_learnings_chat').on(t.chatId),
}));

export const reminders = table('reminders', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  chatId: integer('chat_id').notNull(),
  text: text('text').notNull(),
  remindAt: integer('remind_at', { mode: 'timestamp' }).notNull(),
  isSent: boolean('is_sent').default(false),
  created: integer('created_at', { mode: 'timestamp' }).default(sql`(unixepoch())`),
}, (t) => ({
  reminderChatIdx: index('idx_reminders_chat').on(t.chatId),
  reminderPendingIdx: index('idx_reminders_pending').on(t.isSent),
}));