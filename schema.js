import { table, integer, text, boolean, sql } from 'sdk/db';

export const users = table('users', {
  chatId: integer('chat_id').primaryKey(),
  isOwner: boolean('is_owner').default(false),
  state: text('state').default('idle'),
  created: integer('created_at', { mode: 'timestamp' }).default(sql`(unixepoch())`),
});