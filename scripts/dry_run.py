"""Check membership and send a bounded admin summary without broadcasting configs."""
import logging
import time

try:
    from . import notify_telegram as bot
    from .logging_utils import configure_logging
except ImportError:
    import notify_telegram as bot
    from logging_utils import configure_logging

logger = logging.getLogger(__name__)


def run_dry_run():
    if not bot.TELEGRAM_BOT_TOKEN or not bot.TELEGRAM_ADMIN_CHAT_ID:
        logger.error("Dry run requires TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_CHAT_ID")
        return
    started = time.perf_counter()
    recipients = bot.load_subscribers()
    recipients.setdefault(str(bot.TELEGRAM_ADMIN_CHAT_ID), "Admin")
    active = sum(1 for chat_id in recipients if bot.is_user_member(chat_id))
    report = (
        "👨‍💻 گزارش شبیه‌سازی ارسال (Dry Run)\n\n"
        f"👥 کل گیرندگان: {len(recipients)}\n"
        f"✅ مجاز: {active}\n"
        f"⏭ تأییدنشده: {len(recipients) - active}\n"
        f"📅 {bot.datetime.now(bot.TEHRAN_TZ):%Y-%m-%d | %H:%M}"
    )
    result = bot.send_message(bot.TELEGRAM_ADMIN_CHAT_ID, report)
    logger.info("Dry run completed recipients=%d active=%d report_delivered=%s elapsed_seconds=%.2f",
                len(recipients), active, bool(result.get("ok")), time.perf_counter() - started)


if __name__ == "__main__":
    configure_logging()
    run_dry_run()
