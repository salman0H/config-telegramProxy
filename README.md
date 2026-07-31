# 🚀 Telegram Proxy & Config Distributor

![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg?style=for-the-badge&logo=python)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-Automated-2088FF.svg?style=for-the-badge&logo=github-actions)
![Security](https://img.shields.io/badge/Security-AES--256-success.svg?style=for-the-badge&logo=spring-security)
![Telegram API](https://img.shields.io/badge/Telegram_Bot-Integrated-2CA5E0.svg?style=for-the-badge&logo=telegram)

A fully serverless, highly secure, and automated Telegram bot system powered by **GitHub Actions**. This project fetches fresh proxies and V2Ray configs, securely manages subscribers, and broadcasts updates directly to users' Telegram chats every 12 hours.

---

## ✨ Key Features

*   **🔄 Fully Automated (Serverless):** No need for a dedicated VPS. Broadcasts and user management are handled entirely by GitHub Actions via Cron Jobs and `push` triggers.
*   **🔐 Military-Grade Security:** User privacy is our top priority. The subscriber database (`subscribers.json`) is encrypted using **AES-256** directly within the workflow. No plain-text user data is ever exposed in the repository.
*   **📢 Channel Membership Verification:** Forces users to join a specific community channel (`@sentencedIntoMusic`) before they can receive updates, effectively boosting channel growth.
*   **👨‍💻 Admin Dashboard & Logging:** Sends real-time system logs (subscriptions, unsubscriptions, and broadcast reports) directly to the Admin's Telegram PV.
*   **📦 Smart Delivery:** Automatically chunks massive config lists to bypass Telegram's character limits, or sends them neatly as text documents if they exceed limits.
*   **🎨 Elegant UI:** Messages are beautifully formatted using Telegram's Markdown and HTML parse modes for a premium user experience.

---

## 🏗️ Project Architecture

1.  **Local Bash Integration (`run-ping`):** Local scripts fetch and test configs, then push the updated `config/` and `proxy/` directories to GitHub.
2.  **Workflow Triggers:**
    *   `broadcast-on-config-update.yml`: Triggers immediately when new configs/proxies are pushed to the repository.
    *   `notify-telegram.yml`: Runs on a 12-hour schedule to send regular updates to subscribers.
3.  **Decryption & Execution:** GitHub Actions safely decrypts the user database using a secret key, polls for new `/start` or `/stop` commands, updates the list, sends the messages, and re-encrypts the data before committing it back.

---

## ⚙️ Setup & Installation

### 1. GitHub Secrets Configuration
To run this project securely, you must configure the following **Repository Secrets** in your GitHub repository (`Settings > Secrets and variables > Actions`):

| Secret Name | Description |
| :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | The API Token provided by [@BotFather](https://t.me/BotFather). |
| `TELEGRAM_ADMIN_CHAT_ID` | Your personal Telegram User ID (to receive logs and reports). |
| `DB_PASSWORD` | A strong, random string used as the key for AES-256 database encryption. |

### 2. Bot Commands
Set up the following commands via `@BotFather` for user convenience:
*   `/start` - Subscribe to the automatic proxy/config broadcast.
*   `/stop` - Unsubscribe from the broadcast.

### 3. Local Database Decryption (For Admins)
If you need to manually view or edit the subscriber list on your local machine, use OpenSSL:
```bash
# To Decrypt:
openssl aes-256-cbc -d -pbkdf2 -in bot_state.enc -out bot_state.tar.gz
tar -xzf bot_state.tar.gz

# To Encrypt & Lock:
tar -czf bot_state.tar.gz subscribers.json scripts/telegram_offset.json
openssl aes-256-cbc -salt -pbkdf2 -in bot_state.tar.gz -out bot_state.enc
