import { api, db } from 'sdk';
import { users, messages, todos, reminders } from 'schema';
import { eq, and, ne } from 'sdk/db';
import { OWNER_ID, BROADCAST_DELAY_MS } from 'lib/config';
import { processMediaLink } from 'lib/downloader';
import { askGemini } from 'lib/ai';
import { checkRateLimit } from 'lib/rateLimit';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function logMessage(chatId, direction, text) {
  await db.insert(messages).values({ chatId, direction, text: text ?? '' }).run();
}

async function upsertUser(chatId, username) {
  const isOwner = OWNER_ID !== null && chatId === OWNER_ID;
  await db.insert(users)
    .values({ chatId, username, isOwner })
    .onConflictDoUpdate({ target: users.chatId, set: { username } })
    .run();
}

export default async function (message) {
  if (!message.chat || !message.text) return;

  const chatId = message.chat.id;
  const text = message.text.trim();
  const username = message.from?.username ?? null;
  const isOwner = OWNER_ID !== null && chatId === OWNER_ID;

  await upsertUser(chatId, username);

  const userRow = await db.select().from(users).where(eq(users.chatId, chatId)).get();
  
  if (userRow?.isBlocked && !isOwner) return;

  if (!isOwner) {
    const allowed = await checkRateLimit(chatId);
    if (!allowed) return;

    await logMessage(chatId, 'in', text);

    if (text.startsWith('/getConfigs') || text.startsWith('/configs')) {
      await db.update(users).set({ wantsConfigs: true }).where(eq(users.chatId, chatId)).run();
      await api.sendMessage({ chat_id: chatId, text: 'Subscribed to configs.' });
      await logMessage(chatId, 'out', 'subscribed to configs');
      return;
    }

    if (text.startsWith('/end') || text.startsWith('/stop')) {
      await db.update(users).set({ wantsConfigs: false }).where(eq(users.chatId, chatId)).run();
      await api.sendMessage({ chat_id: chatId, text: 'Unsubscribed from configs.' });
      await logMessage(chatId, 'out', 'unsubscribed from configs');
      return;
    }

    await api.sendMessage({ chat_id: OWNER_ID, text: `[USER:${chatId}]\n${text}` });
    try {
      const reply = await askGemini(text);
      await api.sendMessage({ chat_id: chatId, text: reply });
      await logMessage(chatId, 'out', reply);
    } catch (e) {
      await api.sendMessage({ chat_id: chatId, text: 'Error processing request.' });
    }
    return;
  }

  if (isOwner) {
    if (message.reply_to_message?.text) {
      const match = message.reply_to_message.text.match(/\[USER:(\d+)\]/);
      if (match) {
        const targetId = parseInt(match[1], 10);
        await api.sendMessage({ chat_id: targetId, text });
        await logMessage(targetId, 'out', text);
        return;
      }
    }

    if (text === '/check_reminders') {
      const now = new Date();
      const dueReminders = await db.select().from(reminders)
        .where(eq(reminders.isSent, false))
        .all();

      for (const item of dueReminders) {
        if (new Date(item.remindAt) <= now) {
          await api.sendMessage({ chat_id: OWNER_ID, text: `Reminder:\n${item.text}` });
          await db.update(reminders).set({ isSent: true }).where(eq(reminders.id, item.id)).run();
        }
      }
      return;
    }

    if (text === '/sync_data') {
      const pendingTodos = await db.select().from(todos).where(eq(todos.isCompleted, false)).all();
      await api.sendMessage({
        chat_id: OWNER_ID,
        text: JSON.stringify({ type: 'SYNC_RESPONSE', data: pendingTodos })
      });
      return;
    }

    if (text.startsWith('/broadcast ')) {
      const body = text.slice(11);
      const recipients = await db.select().from(users)
        .where(and(eq(users.isBlocked, false), ne(users.chatId, OWNER_ID)))
        .all();
      
      await api.sendMessage({ chat_id: chatId, text: `Broadcasting to ${recipients.length} users...` });
      
      let sent = 0;
      for (const r of recipients) {
        try {
          await api.sendMessage({ chat_id: r.chatId, text: body });
          await logMessage(r.chatId, 'out', body);
          sent++;
        } catch (e) {
          console.warn('broadcast failed for', r.chatId, e.message);
        }
        await sleep(BROADCAST_DELAY_MS);
      }
      await api.sendMessage({ chat_id: chatId, text: `Broadcast complete: ${sent}/${recipients.length} sent.` });
      return;
    }

    // Pass any other text to Gemini for NLP processing (Todo/Learning/Reminder)
    try {
      await api.sendMessage({ chat_id: chatId, text: 'Processing your request...' });
      // TODO: Implement specific Gemini prompt for structured JSON output
    } catch (e) {
      await api.sendMessage({ chat_id: chatId, text: `Error: ${e.message}` });
    }
    return;
  }
}