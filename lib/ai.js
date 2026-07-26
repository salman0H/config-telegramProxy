import { fetch } from 'sdk';
import { GEMINI_API_KEY } from 'lib/config';

export async function askGemini(userMessage) {
  if (!GEMINI_API_KEY) {
    throw new Error('GEMINI_API_KEY is not configured.');
  }

  const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${GEMINI_API_KEY}`;
  
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      contents: [{ parts: [{ text: userMessage }] }],
      systemInstruction: {
        parts: [{ text: 'You are a helpful assistant.' }],
      },
    }),
  });

  if (!response.ok) {
    const errorData = await response.text();
    throw new Error(`API Error: ${errorData}`);
  }

  const data = await response.json();
  const text = data.candidates?.[0]?.content?.parts?.[0]?.text;
  
  if (text) return text;
  throw new Error('Empty response from AI.');
}

// New function dedicated to parsing owner's commands into structured JSON
export async function parseCommandWithAI(userMessage) {
  if (!GEMINI_API_KEY) throw new Error('GEMINI_API_KEY is not configured.');

  const currentTime = new Date().toISOString();
  const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${GEMINI_API_KEY}`;
  
  const systemInstruction = `You are a personal assistant data parser. Analyze the user's message and categorize it.
  Current system time is: ${currentTime}. Use this to calculate any relative time mentioned by the user.
  
  You MUST return a raw JSON object with this EXACT structure (no markdown formatting, no code blocks):
  {
    "type": "TODO" | "LEARNING" | "REMINDER" | "GENERAL",
    "task": "Text of the task (only if type is TODO)",
    "subject": "Topic of what was learned (only if type is LEARNING)",
    "content": "Details of what was learned (only if type is LEARNING) OR general AI response (if type is GENERAL)",
    "remindText": "What to remind the user about (only if type is REMINDER)",
    "remindAt": "ISO 8601 datetime string representing when to remind (only if type is REMINDER)"
  }`;

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      contents: [{ parts: [{ text: userMessage }] }],
      systemInstruction: { parts: [{ text: systemInstruction }] },
      generationConfig: { response_mime_type: "application/json" }
    }),
  });

  if (!response.ok) throw new Error(`Gemini API Error: ${await response.text()}`);

  const data = await response.json();
  const text = data.candidates?.[0]?.content?.parts?.[0]?.text;
  
  if (!text) throw new Error('Empty response from AI.');
  return JSON.parse(text);
}