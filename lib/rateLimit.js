import { db } from 'sdk';
import { users } from 'schema';
import { eq } from 'sdk/db';
import { RATE_LIMIT_COUNT, RATE_WINDOW_SECONDS } from 'lib/config';

/**
 * Returns true if this message is allowed, false if the user is over the
 * rate limit (caller should drop the message silently or warn once).
 * Owner is expected to be exempted by the caller before this is invoked.
 */
export async function checkRateLimit(chatId) {
  const now = Math.floor(Date.now() / 1000);
  const row = await db.select().from(users).where(eq(users.chatId, chatId)).get();

  // msgWindowStart comes back as a JS Date (mode: 'timestamp'), not raw
  // epoch seconds — convert explicitly instead of letting `-` coerce it
  // to epoch milliseconds (that was the bug: seconds minus milliseconds
  // is always hugely negative, so the "window expired" check never fired
  // and users got stuck rate-limited forever after RATE_LIMIT_COUNT msgs).
  const windowStartSeconds = row?.msgWindowStart
    ? Math.floor(new Date(row.msgWindowStart).getTime() / 1000)
    : null;

  if (!row || windowStartSeconds === null || now - windowStartSeconds >= RATE_WINDOW_SECONDS) {
    await db.update(users)
      .set({ msgWindowStart: new Date(now * 1000), msgWindowCount: 1 })
      .where(eq(users.chatId, chatId))
      .run();
    return true;
  }

  const nextCount = (row.msgWindowCount || 0) + 1;
  await db.update(users).set({ msgWindowCount: nextCount }).where(eq(users.chatId, chatId)).run();
  return nextCount <= RATE_LIMIT_COUNT;
}