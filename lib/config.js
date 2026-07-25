export const OWNER_ID = process.env.TELEGRAM_ADMIN_CHAT_ID 
  ? parseInt(process.env.TELEGRAM_ADMIN_CHAT_ID, 10) 
  : 606424929;

export const GEMINI_API_KEY = process.env.GEMINI_API_KEY || 'AQ.Ab8RN6JxRVHB_DxRoh41Vegrc1bV5yG6Fdri0E-m9EWJJzzm8A';

export const RATE_LIMIT_COUNT = 8;
export const RATE_WINDOW_SECONDS = 60;
export const BROADCAST_DELAY_MS = 800;
export const MAX_BROADCAST_CHUNKS = 15;