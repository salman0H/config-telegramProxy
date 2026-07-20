// NOT a real Telegram update type — Telegram will never route traffic here.
// This file exists purely to be invoked manually/from CI via:
//   npx tgcloud run handlers/broadcast_configs '{"kind":"Config","uris":[...]}'
// `tgcloud run` is documented as a local-testing tool ("no deploy, no
// waiting for a real message"); using it this way from CI is a repurposing
// beyond the doc's examples. Test it once by hand before wiring it into the
// GitHub Action — if it doesn't behave as expected, keep using the existing
// Python scripts/notify_telegram.py sender instead (it works, unchanged).

import { api, db } from 'sdk';
import { users } from 'schema';
import { eq, and } from 'sdk/db';
import { BROADCAST_DELAY_MS, MAX_BROADCAST_CHUNKS } from 'lib/config';
import { packGroups, formatHeader } from 'lib/format';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export default async function ({ kind, uris }) {
  if (!Array.isArray(uris) || uris.length === 0) {
    return { sent: 0, recipients: 0, note: 'no uris provided' };
  }

  const recipients = await db.select().from(users)
    .where(and(eq(users.wantsConfigs, true), eq(users.isBlocked, false)))
    .all();

  const allGroups = packGroups(uris);
  const truncated = allGroups.length > MAX_BROADCAST_CHUNKS;
  const groups = allGroups.slice(0, MAX_BROADCAST_CHUNKS);
  const totalParts = groups.length;
  const droppedCount = truncated ? uris.length - groups.flat().length : 0;

  if (truncated) {
    console.warn(`[broadcast_configs] truncating: ${allGroups.length} chunks needed, sending only ${MAX_BROADCAST_CHUNKS}, dropping ~${droppedCount} items per recipient`);
  }

  let sentCount = 0;
  for (const r of recipients) {
    for (let i = 0; i < groups.length; i++) {
      const header = formatHeader({ kind, part: i + 1, totalParts, totalCount: uris.length });
      const body = '```\n' + groups[i].join('\n') + '\n```';
      try {
        await api.sendMessage({ chat_id: r.chatId, text: header + body, parse_mode: 'Markdown' });
      } catch (e) {
        console.warn('send failed for', r.chatId, e.message);
      }
      await sleep(BROADCAST_DELAY_MS);
    }
    sentCount++;
  }

  return { sent: sentCount, recipients: recipients.length, chunks: totalParts, truncated, droppedCount };
}