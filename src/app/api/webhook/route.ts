import { NextResponse } from 'next/server';

const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const OWNER_ID = parseInt(process.env.TELEGRAM_ADMIN_CHAT_ID || '0', 10);
const API_URL = `https://api.telegram.org/bot${BOT_TOKEN}`;

async function sendMessage(chatId: number, text: string) {
  await fetch(`${API_URL}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chatId, text }),
  });
}

export async function POST(req: Request) {
  try {
    const update = await req.json();
    
    console.log("[Incoming Webhook]:", JSON.stringify(update, null, 2));

    const message = update.message;

    if (!message || !message.text) {
      return NextResponse.json({ status: 'ignored' });
    }

    console.log(`Chat ID: ${message.chat.id} | Expected Owner ID: ${OWNER_ID}`);

    if (message.chat.id !== OWNER_ID) {
      console.log("Unauthorized attempt blocked.");
      return NextResponse.json({ status: 'unauthorized' });
    }

    const text = message.text.trim();

    if (text === '/start') {
      await sendMessage(OWNER_ID, 'System is online and ready.');
      return NextResponse.json({ status: 'success' });
    }

    await sendMessage(OWNER_ID, `Message received: ${text}`);
    
    return NextResponse.json({ status: 'success' });
  } catch (error) {
    console.error('Webhook error:', error);
    return NextResponse.json({ status: 'error' }, { status: 500 });
  }
}