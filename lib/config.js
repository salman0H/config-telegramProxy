export const OWNER_ID = 606424929;

export const GEMINI_API_KEY = 'AQ.Ab8RN6JxRVHB_DxRoh41Vegrc1bV5yG6Fdri0E-m9EWJJzzm8A';

// Rate limiting: max messages per user within RATE_WINDOW_SECONDS.
export const RATE_LIMIT_COUNT = 8;
export const RATE_WINDOW_SECONDS = 60;

// Broadcast pacing: delay between sendMessage calls to avoid Telegram's
// per-chat flood limit (429). Same lesson learned in the Python bot.
export const BROADCAST_DELAY_MS = 800;

// Serverless can't upload files, so large config/proxy lists can only be
// sent as chunked text messages — there is no "attach as file" fallback
// here (unlike the Python bot, which could send a .txt document).
// Cap how many chunks a single /broadcast-configs run will send per user,
// to avoid one call turning into dozens of messages.
export const MAX_BROADCAST_CHUNKS = 15;