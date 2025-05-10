<h1 align="center">HK Monitoring Bot</h1>

<p align="center"><b>Watches a monitoring web UI and sends alarm changes to Telegram</b></p>

<p align="center">
  ![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
  ![Platform](https://img.shields.io/badge/platform-Windows-0078D6?logo=windows&logoColor=white)
  ![Updated](https://img.shields.io/badge/updated-2025-05-10-success)
  [![Releases](https://img.shields.io/badge/downloads-Releases-blue)](https://github.com/alisadhk/hk-monitoring-bot/releases/latest)
</p>

---

## Overview
A PyQt5 application that logs in to a monitoring system's web interface with Selenium, polls the alarm page and sends a Telegram message whenever an alarm changes state. Account details are stored encrypted with Fernet.

## Features
- Multiple saved accounts (Add / Del)
- Configurable poll interval, alarm time threshold and similarity threshold
- Telegram notifications with status changes
- Encrypted local storage of credentials
- Live log with Clear Log

## Screenshots
<p align="center"><img src="screenshots/screenshot-1.png" alt="HK Monitoring Bot screenshot" width="720"></p>

## Download and install
### Option A - Ready-to-run download (recommended)
1. Open the **[Releases page](https://github.com/alisadhk/hk-monitoring-bot/releases/latest)**.
2. Download the file(s) listed under **Assets**:

| File | Size |
|---|---|
| `HK-Monitoring-Bot.exe` | 53.5 MB |
| `HK-Monitoring-Bot-archive.rar` | 52.6 MB |

3. Run it. 

### Option B - Run from source
Requirements: Windows 10/11 and Python 3.10+.

```bash
git clone https://github.com/alisadhk/hk-monitoring-bot.git
cd hk-monitoring-bot
python -m pip install -r requirements.txt
python 7.py
```

## How to use
1. Create a Telegram bot with **@BotFather** and copy its token; get the chat/channel ID you want to notify.
2. Start the program, press **Add** and create an account name.
3. Fill **Web username**, **Web password**, **Login URL**, **Alarms URL**, **Telegram bot token** and **Telegram channel**.
4. Set the poll interval and thresholds, press **Save**, then **Start**.
5. Watch the log; press **Stop** to end monitoring.

## Configuration and privacy
- All sensitive values from the original private version (passwords, tokens, license codes, user names, internal IP addresses, personal names and links) were replaced with `*****`.
- larm_config.json and the *.key files are created on first run and are never part of the repository.
- Keep your Telegram token private; revoke it with @BotFather if it is ever exposed.

## Build the executable yourself
```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm 7.spec
```
The executable is created in the `dist/` folder.

## Notes
- Needs Google Chrome (Selenium Manager downloads the driver).

---

<p align="center">Maintained by <a href="https://github.com/alisadhk">@alisadhk</a> - last update 2025-05-10</p>