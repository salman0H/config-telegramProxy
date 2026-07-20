import { api, db } from 'sdk';
import { users, messages } from 'schema';
import { eq, ne, and } from 'sdk/db';
import { OWNER_ID, BROADCAST_DELAY_MS } from 'lib/config';
import { processMediaLink } from 'lib/downloader';
import { askGemini } from 'lib/ai';
import { checkRateLimit } from 'lib/rateLimit';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function logMessage(chatId, direction, text) {
  await db.insert(messages).values({ chatId, direction, text: text ?? '' }).run();
}

async function upsertUser(chatId, username) {
  await db.insert(users)
    .values({ chatId, username, isOwner: chatId === OWNER_ID })
    .onConflictDoUpdate({ target: users.chatId, set: { username } })
    .run();
}

export default async function (message) {
  if (!message.chat || !message.text) return;

  const chatId = message.chat.id;
  const text = message.text.trim();
  const username = message.from?.username ?? null;
  const isOwner = chatId === OWNER_ID;

  await upsertUser(chatId, username);

  const userRow = await db.select().from(users).where(eq(users.chatId, chatId)).get();
  if (userRow?.isBlocked && !isOwner) return; // silently ignore blocked users

  if (!isOwner) {
    const allowed = await checkRateLimit(chatId);
    if (!allowed) return; // over the limit — drop silently, no warning spam
  }

  await logMessage(chatId, 'in', text);

  // ---- subscriber commands (config/proxy broadcast opt-in) — non-owner only.
  // Without the isOwner guard, the owner typing /start would get the
  // subscriber welcome text and never reach the admin panel below.
  if (!isOwner && (text.startsWith('/getConfigs') || text.startsWith('/configs'))) {
    await db.update(users).set({ wantsConfigs: true }).where(eq(users.chatId, chatId)).run();
    await api.sendMessage({ chat_id: chatId, text: '✅ ثبت شد. کانفیگ‌ها و پروکسی‌های جدید براتون ارسال می‌شه.' });
    await logMessage(chatId, 'out', 'subscribed to configs');
    return;
  }
  if (!isOwner && (text.startsWith('/end') || text.startsWith('/stop'))) {
    await db.update(users).set({ wantsConfigs: false }).where(eq(users.chatId, chatId)).run();
    await api.sendMessage({ chat_id: chatId, text: '🛑 لغو شد. دیگه چیزی براتون ارسال نمی‌شه.' });
    await logMessage(chatId, 'out', 'unsubscribed from configs');
    return;
  }
  if (!isOwner && text.startsWith('/start')) {
    await api.sendMessage({ chat_id: chatId, text: 'سلام 👋\nبرای دریافت کانفیگ/پروکسی: /getConfigs\nبرای توقف: /end' });
    return;
  }

  // ---------------------------- owner-only ----------------------------
  if (isOwner) {
    // reply-to-message relay back to whichever user's message it tags
    if (message.reply_to_message?.text) {
      const match = message.reply_to_message.text.match(/\[USER:(\d+)\]/);
      if (match) {
        const targetId = parseInt(match[1], 10);
        await api.sendMessage({ chat_id: targetId, text });
        await logMessage(targetId, 'out', text);
        return;
      }
    }

    if (text.startsWith('/ai ')) {
      const prompt = text.slice(4);
      await api.sendMessage({ chat_id: chatId, text: '💡 در حال تفکر...' });
      try {
        const reply = await askGemini(prompt);
        await api.sendMessage({ chat_id: chatId, text: reply });
      } catch (e) {
        await api.sendMessage({ chat_id: chatId, text: `❌ خطا: ${e.message}` });
      }
      return;
    }

    if (text.startsWith('/block ')) {
      const targetId = parseInt(text.slice(7).trim(), 10);
      if (!Number.isNaN(targetId)) {
        await db.update(users).set({ isBlocked: true }).where(eq(users.chatId, targetId)).run();
        await api.sendMessage({ chat_id: chatId, text: `🚫 کاربر ${targetId} بلاک شد.` });
      }
      return;
    }
    if (text.startsWith('/unblock ')) {
      const targetId = parseInt(text.slice(9).trim(), 10);
      if (!Number.isNaN(targetId)) {
        await db.update(users).set({ isBlocked: false }).where(eq(users.chatId, targetId)).run();
        await api.sendMessage({ chat_id: chatId, text: `✅ کاربر ${targetId} آنبلاک شد.` });
      }
      return;
    }

    if (text.startsWith('/broadcast ')) {
      const body = text.slice(11);
      const recipients = await db.select().from(users)
        .where(and(eq(users.isBlocked, false), ne(users.chatId, OWNER_ID)))
        .all();
      await api.sendMessage({ chat_id: chatId, text: `⏳ در حال ارسال به ${recipients.length} کاربر...` });
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
      await api.sendMessage({ chat_id: chatId, text: `✅ به ${sent}/${recipients.length} نفر ارسال شد.` });
      return;
    }

    if (text.startsWith('/stats')) {
      const total = await db.$count(users);
      const blocked = await db.$count(users, eq(users.isBlocked, true));
      const subscribed = await db.$count(users, eq(users.wantsConfigs, true));
      const totalMessages = await db.$count(messages);
      await api.sendMessage({
        chat_id: chatId,
        text: `📊 آمار\n👥 کاربران: ${total}\n🚫 بلاک‌شده: ${blocked}\n🗂 مشترک کانفیگ: ${subscribed}\n💬 کل پیام‌ها: ${totalMessages}`,
      });
      return;
    }

    if (text.includes('youtube.com') || text.includes('youtu.be') || text.includes('spotify.com')) {
      const result = await processMediaLink(text);
      await api.sendMessage({ chat_id: chatId, text: result });
      return;
    }

    await api.sendMessage({
      chat_id: chatId,
      text:
        'پیشخوان مدیریت فعال است.\n' +
        '- ریپلای روی پیام یک کاربر → پاسخ به همون کاربر\n' +
        '- /ai <متن> → سؤال از هوش مصنوعی\n' +
        '- /broadcast <متن> → پیام به همه\n' +
        '- /block <chat_id> ، /unblock <chat_id>\n' +
        '- /stats → آمار کلی',
    });
    return;
  }

  // -------------------------- non-owner default --------------------------
  await api.sendMessage({ chat_id: OWNER_ID, text: `[USER:${chatId}]\n${text}` });
  try {
    const reply = await askGemini(text);
    await api.sendMessage({ chat_id: chatId, text: reply });
    await logMessage(chatId, 'out', reply);
  } catch (e) {
    await api.sendMessage({ chat_id: chatId, text: 'در حال حاضر قادر به پاسخگویی نیستم. پیام شما به مدیر ارسال شد.' });
  }
}