import { api, db } from 'sdk';
import { users } from 'schema';
import { OWNER_ID } from 'lib/config';
import { processMediaLink } from 'lib/downloader';
import { askGemini } from 'lib/ai';

export default async function (message) {
  if (!message.chat || !message.text) return;

  const chatId = message.chat.id;
  const text = message.text;

  await db.insert(users)
    .values({ chatId: chatId, isOwner: chatId === OWNER_ID })
    .onConflictDoUpdate({
      target: users.chatId,
      set: { state: 'active' },
    })
    .run();

  if (chatId !== OWNER_ID) {
    await api.sendMessage({
      chat_id: OWNER_ID,
      text: `[USER:${chatId}]\n${text}`,
    });
    
    try {
      const aiResponse = await askGemini(text); 
      await api.sendMessage({
        chat_id: chatId,
        text: aiResponse,
      });
    } catch (error) {
      await api.sendMessage({
        chat_id: chatId,
        text: 'در حال حاضر قادر به پاسخگویی نیستم. پیام شما به مدیر ارسال شد.',
      });
    }
    return;
  }

  if (chatId === OWNER_ID) {
    if (message.reply_to_message && message.reply_to_message.text) {
       const match = message.reply_to_message.text.match(/\[USER:(\d+)\]/);
       if (match) {
         const targetId = parseInt(match[1], 10);
         await api.sendMessage({ chat_id: targetId, text: text });
         return;
       }
    }

    if (text.startsWith('/ai ')) {
      const prompt = text.replace('/ai ', '');
      await api.sendMessage({ chat_id: chatId, text: '💡 در حال تفکر...' });
      try {
        // تغییر فراخوانی به جمینی گوگل
        const aiResponse = await askGemini(prompt); 
        await api.sendMessage({ chat_id: chatId, text: aiResponse });
      } catch (error) {
        await api.sendMessage({ chat_id: chatId, text: `❌ خطا: ${error.message}` });
      }
      return;
    }

    if (text.includes('youtube.com') || text.includes('youtu.be') || text.includes('spotify.com')) {
      await api.sendMessage({ chat_id: chatId, text: 'Processing media link...' });
      try {
          const resultUrl = await processMediaLink(text);
          await api.sendMessage({ chat_id: chatId, text: resultUrl });
      } catch (e) {
          await api.sendMessage({ chat_id: chatId, text: 'Error processing link.' });
      }
      return;
    }

    await api.sendMessage({ 
      chat_id: chatId, 
      text: 'پیشخوان مدیریت فعال است.\n- برای پاسخ به کاربر روی پیامش ریپلای کنید.\n- برای استفاده از هوش مصنوعی از دستور `/ai متن شما` استفاده کنید.' 
    });
  }
}