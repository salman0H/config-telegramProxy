// Left as a mock intentionally: Telegram Serverless can't upload a file
// from a handler yet, and YouTube/Spotify redistribution to many
// subscribers raises separate copyright concerns. See chat notes.
export async function processMediaLink(url) {
  return `[Mock] این قابلیت روی این پلتفرم پیاده‌سازی نشده: ${url}`;
}