import { fetch } from 'sdk';
import { GEMINI_API_KEY } from 'lib/config';

export async function askGemini(userMessage) {
  if (!GEMINI_API_KEY) {
    throw new Error('GEMINI_API_KEY را در lib/config.js تنظیم کنید.');
  }

  const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${GEMINI_API_KEY}`;

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      contents: [{ parts: [{ text: userMessage }] }],
      systemInstruction: {
        parts: [{ text: 'شما یک دستیار هوشمند و مودب هستید که به زبان فارسی پاسخ می‌دهد.' }],
      },
    }),
  });

  if (!response.ok) {
    const errorData = await response.text();
    throw new Error(`خطا در ارتباط با گوگل: ${errorData}`);
  }

  const data = await response.json();
  const text = data.candidates?.[0]?.content?.parts?.[0]?.text;
  if (text) return text;
  throw new Error('پاسخ معتبری از هوش مصنوعی دریافت نشد.');
}