import asyncio
import os
import time
import json
import random
import logging
import traceback
import re
import glob
import signal
import sys
from typing import Dict, Set, Optional
from io import BytesIO
import requests
import qrcode
from gtts import gTTS
import yt_dlp
from telethon import TelegramClient, events, functions, types
from telethon.tl.custom import Button
from telethon.errors import FloodWaitError, RPCError, SessionPasswordNeededError, MessageNotModifiedError, UnauthorizedError, AuthKeyDuplicatedError
from telethon.sessions import StringSession
from cryptography.fernet import Fernet
import asyncpg
import hashlib
import math
import datetime
from datetime import datetime, timedelta
from flask import Flask
import threading
from waitress import serve
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.types import ChatBannedRights
from telethon.tl.functions.contacts import BlockRequest, UnblockRequest   # ✅ ADDED

# ─── CONFIGURATION ───
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MY_OWNER_IDS = {int(x) for x in os.environ.get("OWNER_IDS", "8909378644,8711082433").split(",") if x.strip()}
UPI_ID = os.environ.get("UPI_ID", "paryush01@nyes")
QR_IMAGE_PATH = os.environ.get("QR_IMAGE_PATH", "upi_qr.jpg")
PREMIUM_FEATURES_LINK = os.environ.get("PREMIUM_FEATURES_LINK", "https://t.me/userbotsupport_ZA/20")

# ─── CHANNEL VERIFICATION ───
REQUIRED_CHANNELS = [
    {"id": -1004404975416, "invite": "https://t.me/+j9ndQJG6wdc3ZDE1", "name": "Channel 1"},
    {"id": -1004334756214, "invite": "https://t.me/+5DvNxDnfAApjYWNk", "name": "Channel 2"},
    {"id": -1004452969098, "invite": "https://t.me/+A1qEdXj8ZUI5ZGM1", "name": "Channel 3"},
    {"id": -1004331434090, "invite": "https://t.me/+Wkmu7JUvlrBkZTI1", "name": "Channel 4"},
    {"id": -1004331557651, "invite": "https://t.me/+nOmFPUNhI6Q3MGQ1", "name": "Channel 5"},
]

USERS_FILE = "broadcast_users.json"

def load_users():
    try:
        with open(USERS_FILE, "r") as f:
            return set(json.load(f))
    except:
        return set()

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(list(users), f)

broadcast_users = load_users()

# ─── DATABASE & ENCRYPTION ───
db_pool = None
cipher = None

async def init_db():
    global db_pool
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise Exception("DATABASE_URL not set")
    db_pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id BIGINT PRIMARY KEY,
                session_encrypted TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS app_config (
                key_name TEXT PRIMARY KEY,
                key_value TEXT NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS premium_users (
                user_id BIGINT PRIMARY KEY,
                plan TEXT NOT NULL,
                start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expiry_date TIMESTAMP,
                status TEXT DEFAULT 'active'
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS premium_protections (
                user_id BIGINT,
                command_name TEXT,
                PRIMARY KEY (user_id, command_name)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_wallet (
                user_id BIGINT PRIMARY KEY,
                balance DECIMAL(10,2) DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS dm_settings (
                user_id BIGINT PRIMARY KEY,
                shield_enabled BOOLEAN DEFAULT FALSE,
                god_protection BOOLEAN DEFAULT FALSE,
                "freeze" BOOLEAN DEFAULT FALSE,
                auto_reply TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS dm_approved (
                user_id BIGINT,
                approved_id BIGINT,
                PRIMARY KEY (user_id, approved_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS dm_blocked (
                user_id BIGINT,
                blocked_id BIGINT,
                PRIMARY KEY (user_id, blocked_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS dm_warnings (
                user_id BIGINT,
                target_id BIGINT,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, target_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS dm_filters (
                user_id BIGINT,
                word TEXT,
                PRIMARY KEY (user_id, word)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sangmata_history (
                user_id BIGINT,
                target_id BIGINT,
                old_name TEXT,
                old_username TEXT,
                new_name TEXT,
                new_username TEXT,
                change_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_freeze (
                user_id BIGINT PRIMARY KEY,
                frozen BOOLEAN DEFAULT FALSE
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS god_protection (
                uid BIGINT,
                chat_id BIGINT,
                enabled BOOLEAN DEFAULT FALSE,
                action TEXT DEFAULT 'delete',
                auto_mute BOOLEAN DEFAULT TRUE,
                mute_min INTEGER DEFAULT 5,
                threshold_mentions INTEGER DEFAULT 5,
                threshold_sec INTEGER DEFAULT 10,
                PRIMARY KEY (uid, chat_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_filters (
                user_id BIGINT,
                trigger_word TEXT,
                reply_text TEXT,
                reply_sticker_id TEXT,
                reply_type TEXT DEFAULT 'text',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, trigger_word)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS redeem_codes (
                code TEXT PRIMARY KEY,
                amount DECIMAL(10,2) NOT NULL,
                expiry_date TIMESTAMP,
                max_uses INTEGER,
                used_count INTEGER DEFAULT 0,
                created_by BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

# ─── ENCRYPTION ──────────────────────────────────────────────────────
async def get_encryption_key():
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT key_value FROM app_config WHERE key_name='encryption_key'")
        if row:
            return row["key_value"]
        new_key = Fernet.generate_key().decode()
        await conn.execute(
            "INSERT INTO app_config (key_name, key_value) VALUES ($1, $2)",
            "encryption_key", new_key
        )
        return new_key

async def init_cipher():
    global cipher
    key = await get_encryption_key()
    cipher = Fernet(key.encode())

def encrypt_session(sess: str):
    if cipher is None:
        raise RuntimeError("Cipher not initialized")
    return cipher.encrypt(sess.encode()).decode()

def decrypt_session(data: str):
    if cipher is None:
        raise RuntimeError("Cipher not initialized")
    return cipher.decrypt(data.encode()).decode()

# ─── SESSION FUNCTIONS ──────────────────────────────────────────────
async def save_session(user_id: int, session_str: str):
    encrypted = encrypt_session(session_str)
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_sessions (user_id, session_encrypted)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET
                session_encrypted = $2,
                updated_at = CURRENT_TIMESTAMP
            """,
            user_id, encrypted
        )

async def load_sessions() -> dict:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, session_encrypted FROM user_sessions")
    sessions = {}
    for row in rows:
        try:
            sessions[row["user_id"]] = decrypt_session(row["session_encrypted"])
        except Exception:
            await delete_session(row["user_id"])
    return sessions

async def delete_session(user_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM user_sessions WHERE user_id=$1", user_id)

# ─── FREEZE FUNCTIONS ──────────────────────────────────────────────
async def set_freeze(user_id: int, frozen: bool):
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_freeze (user_id, frozen)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET frozen=$2
            """,
            user_id, frozen
        )

async def get_freeze(user_id: int) -> bool:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT frozen FROM user_freeze WHERE user_id=$1", user_id)
        return row["frozen"] if row else False

# ─── WALLET FUNCTIONS ──────────────────────────────────────────────
async def get_balance(user_id: int) -> float:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT balance FROM user_wallet WHERE user_id=$1", user_id)
        return float(row["balance"]) if row else 0.0

async def add_balance(user_id: int, amount: float):
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_wallet (user_id, balance)
            VALUES ($1, $2)
            ON CONFLICT(user_id) DO UPDATE SET
                balance = user_wallet.balance + $2,
                updated_at = CURRENT_TIMESTAMP
            """,
            user_id, amount
        )

async def deduct_balance(user_id: int, amount: float):
    balance = await get_balance(user_id)
    if balance < amount:
        raise ValueError("Insufficient balance")
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_wallet SET balance = balance - $2, updated_at = CURRENT_TIMESTAMP WHERE user_id = $1",
            user_id, amount
        )

# ─── PREMIUM ──────────────────────────────────────────────────────
PROTECTED_COMMANDS = [
    "reply", "sreply", "rr", "srr", "flag", "sflag", "hrr", "shrr",
    "replygod", "sgod", "customraid", "stopcustomraid",
    "shayariraid", "sshayariraid", "rizzraid", "srizzraid",
    "pickupraid", "spickupraid", "romanceraid", "sromanceraid",
    "trollraid", "strollraid", "ragebaitraid", "sragebaitraid",
    "roastraid", "sroastraid",
    "attackraid", "sattackraid", "warraid", "swarraid",
    "savageraid", "ssavageraid", "ultraraid", "sultraraid",
    "shameraid", "sshameraid", "dissraid", "sdissraid",
    "devilraid", "sdevilraid", "karmaraid", "skarmaraid",
    "doomraid", "sdoomraid",
    "spray", "dspray", "tspray", "rspray", "multispray", "countspray",
    "deathgod", "sdeathgod",
    "mr", "smr", "mr2", "smr2", "br", "sbr", "br2", "sbr2", "br3", "sbr3",
    "sqr", "ssqr", "sq2", "ssq2", "cr", "scr", "bar", "sbar", "gr", "sgr",
    "ms", "sms", "ms2", "sms2", "bs", "sbs", "bs2", "sbs2", "bs3", "sbs3",
    "sqs", "ssqs", "sqs2", "ssqs2", "cs", "scs", "bas", "sbas", "gs", "sgs",
    "pwr", "spwr", "ows", "sows"
]

async def add_premium_user(user_id: int, plan: str, days: int):
    expiry = datetime.now() + timedelta(days=days)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO premium_users (user_id, plan, expiry_date, status)
            VALUES ($1, $2, $3, 'active')
            ON CONFLICT (user_id) DO UPDATE
            SET plan = $2, expiry_date = $3, status = 'active', start_date = CURRENT_TIMESTAMP
        """, user_id, plan, expiry)
    for cmd in PROTECTED_COMMANDS:
        await add_protection(user_id, cmd)
    try:
        await MAIN_BOT_CLIENT.send_message(
            user_id,
            f"🛡️ **Premium Activated!**\n\n"
            f"You are now protected from all raids, spam, and deathgod attacks.\n"
            f"Your userbot will automatically ignore these attacks.\n\n"
            f"📅 Plan: {plan.upper()}\n"
            f"⏳ Expires: {expiry.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"Use `.premiumstatus` in your userbot to check your premium details."
        )
    except:
        pass

async def get_premium_user(user_id: int):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM premium_users WHERE user_id = $1", user_id)
        return dict(row) if row else None

async def check_premium_status(user_id: int):
    data = await get_premium_user(user_id)
    if not data or data['status'] != 'active':
        return None
    if data['expiry_date'] < datetime.now():
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE premium_users SET status = 'expired' WHERE user_id = $1", user_id)
        return None
    return data

async def extend_premium(user_id: int, days: int):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE premium_users SET expiry_date = GREATEST(expiry_date, CURRENT_TIMESTAMP) + INTERVAL '$1 days', status = 'active' WHERE user_id = $2",
            days, user_id
        )

async def add_protection(user_id: int, command: str):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO premium_protections (user_id, command_name) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            user_id, command
        )

async def remove_protection(user_id: int, command: str):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM premium_protections WHERE user_id = $1 AND command_name = $2", user_id, command)

async def get_protections(user_id: int) -> Set[str]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT command_name FROM premium_protections WHERE user_id = $1", user_id)
    return {row['command_name'] for row in rows}

async def is_protected(target_user: int, command: str) -> bool:
    prem = await check_premium_status(target_user)
    if not prem:
        return False
    protections = await get_protections(target_user)
    return command in protections

# ─── MAIN BOT ─────────────────────────────────────────────────────
MAIN_BOT_CLIENT = TelegramClient(
    "main_bot_session",
    API_ID,
    API_HASH,
    connection_retries=10,
    auto_reconnect=True
)

active_userbots = {}
user_sessions = {}
user_states = {}
running_tasks = set()

print("🚀 Main Bot started...")

# ─── MENU BOX BUILDER ──────────────────────────────────────────────
def build_box(title, lines, footer="", back_cmd=None):
    TL = "┌"
    TR = "┐"
    BL = "└"
    BR = "┘"
    H  = "─"
    V  = "│"
    T  = "├"
    BT = "┤"

    box_width = 36
    title_line = f"{V}  {title.center(box_width - 6)}  {V}"
    sep_line   = f"{T}{H * (box_width - 2)}{BT}"
    top_line   = f"{TL}{H * (box_width - 2)}{TR}"
    bot_line   = f"{BL}{H * (box_width - 2)}{BR}"

    content_lines = []
    for line in lines:
        stripped = line.rstrip()
        if stripped.strip() == "":
            content_lines.append(f"{V}{' ' * (box_width - 2)}{V}")
        else:
            inner = stripped[:box_width - 6].ljust(box_width - 6)
            content_lines.append(f"{V}  {inner}  {V}")

    footer_line = ""
    if footer:
        footer_inner = footer[:box_width - 6].ljust(box_width - 6)
        footer_line = f"{V}  {footer_inner}  {V}"

    back_text = ""
    if back_cmd:
        back_inner = f"🔙  Back to Main Menu".ljust(box_width - 6)
        back_text = f"{V}  {back_inner}  {V}"

    parts = [top_line, title_line, sep_line]
    parts.extend(content_lines)
    if back_text:
        parts.append(sep_line)
        parts.append(back_text)
    if footer_line:
        parts.append(sep_line)
        parts.append(footer_line)
    parts.append(bot_line)

    return "\n".join(parts)

BACK_TO_MAIN = ".menu"

MENU_MAIN = build_box("📖 MAIN MENU", [
    "",
    "  ◈  SYSTEM INFO  ◈",
    "",
    "  ✦ Owner  : ZYЯΣX ✕ ΛΣƬΉΣЯ",
    "  ✦ Cmds   : 500+",
    "  ✦ Prefix : `.`",
    "",
    "  ◈  NAVIGATION  ◈",
    "",
    "  ▸ .menu1   → Admin & Group",
    "  ▸ .menu2   → Raid Engine",
    "  ▸ .menu3   → Spam & Text",
    "  ▸ .menu4   → Protection",
    "  ▸ .menu5   → Tools & Utility",
    "  ▸ .menu6   → Send & Tag",
    "  ▸ .menu7   → Fun Meters",
    "  ▸ .menu8   → Fun Raids",
    "  ▸ .menu9   → Non-Abusive Raids",
    "  ▸ .menu10  → Games & Fun",
    "  ▸ .menu11a → Premium Part A",
    "  ▸ .menu11b → Premium Part B",
    "  ▸ .menu12  → Protection & Cleanup",
    "  ▸ .menu13  → Premium Raids",
    "  ▸ .menu14  → Premium Spam",
    "",
], footer="💡 Use `.cmds` for full list  •  `.ping` for latency")

MENU_1 = build_box("👑 ADMIN & GROUP", [
    "",
    "  ◆  ADMIN  ◆",
    "",
    "  ▸ .admins    → List admins",
    "  ▸ .addadmin  → Add admin (reply)",
    "  ▸ .deladmin  → Remove admin",
    "",
    "  ◆  MUTE  ◆",
    "",
    "  ▸ .mute      → Local mute",
    "  ▸ .unmute    → Unmute",
    "  ▸ .gmute     → Global mute",
    "  ▸ .gunmute   → Global unmute",
    "  ▸ .mutelist  → Status",
    "",
    "  ◆  GROUP MOD  ◆",
    "",
    "  ▸ .lock      → Lock group",
    "  ▸ .unlock    → Unlock",
    "  ▸ .addbots   → Add bots",
    "",
    "  ◆  AUTO TAG  ◆",
    "",
    "  ▸ .autotag       → Tag all members",
    "  ▸ .stopautotag   → Stop tagging",
    "",
], back_cmd=BACK_TO_MAIN)

MENU_2 = build_box("⚔️ RAID ENGINE", [
    "",
    "  ◆  REPLY RAID  ◆",
    "",
    "  ▸ .reply    → Start reply raid",
    "  ▸ .sreply   → Stop reply raid",
    "",
    "  ◆  RR (Reply+React)  ◆",
    "",
    "  ▸ .rr    → Start RR raid",
    "  ▸ .srr   → Stop RR raid",
    "",
    "  ◆  FLAG RAID  ◆",
    "",
    "  ▸ .flag    → Start flag raid",
    "  ▸ .sflag   → Stop flag raid",
    "",
    "  ◆  HEART RAID  ◆",
    "",
    "  ▸ .hrr    → Start heart raid",
    "  ▸ .shrr   → Stop heart raid",
    "",
    "  ◆  GOD RAID (4 replies)  ◆",
    "",
    "  ▸ .replygod → Start god raid",
    "  ▸ .sgod     → Stop god raid",
    "",
    "  ◆  CUSTOM RAID  ◆",
    "",
    "  ▸ .customraid     → Start custom",
    "  ▸ .stopcustomraid → Stop custom",
    "",
    "  ◆  PWR RAID (Sequential)  ◆",
    "",
    "  ▸ .pwr   → Start PWR raid",
    "  ▸ .spwr  → Stop PWR raid",
    "",
], back_cmd=BACK_TO_MAIN)

MENU_3 = build_box("💣 SPAM & TEXT", [
    "",
    "  ◆  SPRAY COMMANDS  ◆",
    "",
    "  ▸ .spray       → Infinite spray",
    "  ▸ .dspray      → Stop spray (current chat)",
    "  ▸ .tspray      → Spam saved text (slot)",
    "  ▸ .rspray      → Random saved text",
    "  ▸ .multispray  → Rotate saved texts",
    "  ▸ .countspray  → Exactly N times",
    "  ▸ .spraydelay  → Adjust speed (owner)",
    "",
    "  ◆  TEXT MANAGER  ◆",
    "",
    "  ▸ .addtext    → Save text",
    "  ▸ .listtexts  → Show saved texts",
    "  ▸ .deltext    → Delete text (slot)",
    "  ▸ .cleartext  → Clear all (confirm)",
    "",
    "  ◆  DEATHGOD  ◆",
    "",
    "  ▸ .deathgod   → Start deathgod",
    "  ▸ .sdeathgod  → Stop deathgod",
    "",
    "  ◆  OWS SPAM (Sequential)  ◆",
    "",
    "  ▸ .ows   → Start OWS spam",
    "  ▸ .sows  → Stop OWS spam",
    "",
    "  ◆  GLOBAL STOP  ◆",
    "",
    "  ▸ .stopallspray → Stop ALL sprays/raids",
    "",
], back_cmd=BACK_TO_MAIN)

MENU_4 = build_box("🛡️ PROTECTION", [
    "",
    "  ◆  ANTI-DELETE  ◆",
    "",
    "  ▸ .antidel on/off → Toggle",
    "  ▸ .antidel        → Status",
    "",
    "  ◆  WATCHSPAM  ◆",
    "",
    "  ▸ .watchspam    → Add watch",
    "  ▸ .unwatchspam  → Remove watch",
    "  ▸ .watchlist    → Active watches",
    "",
    "  ◆  AUTO REACT  ◆",
    "",
    "  ▸ .ar       → Set auto-react (emoji)",
    "  ▸ .sar      → Disable",
    "  ▸ .react    → React to target",
    "  ▸ .unreact  → Remove react",
    "  ▸ .reactlist→ All targets",
    "",
], back_cmd=BACK_TO_MAIN)

MENU_5 = build_box("⚙️ TOOLS & UTILITY", [
    "",
    "  ◆  TOOLS  ◆",
    "",
    "  ▸ .tts     → Text-to-Speech",
    "  ▸ .qrcode  → Generate QR",
    "  ▸ .fancy   → Fancy styles",
    "  ▸ .style   → Bold/Italic/Mono",
    "  ▸ .emoji   → Add random emojis",
    "  ▸ .calc    → Calculate expression",
    "  ▸ .weather → Weather info",
    "  ▸ .ip      → IP location",
    "  ▸ .short   → Shorten URL",
    "  ▸ .info    → User info",
    "",
    "  ◆  ECHO  ◆",
    "",
    "  ▸ .echo → Echo back text",
    "",
    "  ◆  MUSIC  ◆",
    "",
    "  ▸ .music  → Send as voice",
    "  ▸ .dmusic → Download MP3",
    "",
    "  ◆  NOTES  ◆",
    "",
    "  ▸ .notesadd    → Save note",
    "  ▸ .noteslist   → List notes",
    "  ▸ .notesdelete → Delete note",
    "",
    "  ◆  DM SHIELD (Premium)  ◆",
    "",
    "  ▸ .dmshield on/off → Toggle shield",
    "  ▸ .approve         → Approve DM user",
    "  ▸ .unapprove       → Remove approval",
    "  ▸ .block           → Block user",
    "  ▸ .unblock         → Unblock user",
    "  ▸ .blockedlist     → List blocked users",
    "",
    "  ◆  OWNER/ADMIN  ◆",
    "",
    "  ▸ .copy     → Clone profile (reply)",
    "  ▸ .normal   → Restore original",
    "  ▸ .banner   → Set menu banner (reply to media)",
    "  ▸ .rembanner→ Remove banner",
    "  ▸ .nc       → Name Changer (set/stop)",
    "",
], back_cmd=BACK_TO_MAIN)

MENU_6 = build_box("📨 SEND & TAG", [
    "",
    "  ◆  SEND MESSAGE  ◆",
    "",
    "  ▸ .send @user <msg> → Direct message",
    "",
    "  ◆  TAG MULTIPLE  ◆",
    "",
    "  ▸ .tag @user1 msg1 @user2 msg2 ...",
    "",
    "  ◆  BASIC  ◆",
    "",
    "  ▸ .ping    → Check latency",
    "  ▸ .status  → Bot status & uptime",
    "  ▸ .id      → User & chat ID",
    "",
], back_cmd=BACK_TO_MAIN)

MENU_7 = build_box("🎭 FUN METERS", [
    "",
    "  ◆  % METERS  ◆",
    "",
    "  ▸ .studmeter   → Stud %",
    "  ▸ .looks       → Looks %",
    "  ▸ .gay         → Gay %",
    "  ▸ .lesbian     → Lesbian %",
    "  ▸ .straight    → Straight %",
    "  ▸ .bi          → Bi %",
    "  ▸ .trans       → Trans %",
    "  ▸ .simp        → Simp %",
    "  ▸ .chad        → Chad %",
    "  ▸ .friendly    → Friendly %",
    "  ▸ .stupidmeter → Stupid %",
    "  ▸ .sigma       → Sigma %",
    "  ▸ .pookie      → Pookie %",
    "  ▸ .baddie      → Baddie %",
    "",
    "  ◆  SCORE METERS  ◆",
    "",
    "  ▸ .rizz  → Rizz (1-100)",
    "  ▸ .iq    → IQ (1-200)",
    "",
    "  ◆  RELATIONSHIP  ◆",
    "",
    "  ▸ .bestfrnd → Ask best friend",
    "  ▸ .marriage → Propose",
    "  ▸ .divorce  → Ask divorce",
    "",
], back_cmd=BACK_TO_MAIN)

MENU_8 = build_box("🎯 FUN RAIDS", [
    "",
    "  ◆  SHAYARI RAID  ◆",
    "      ▸ .shayariraid  •  .sshayariraid",
    "",
    "  ◆  RIZZ RAID  ◆",
    "      ▸ .rizzraid  •  .srizzraid",
    "",
    "  ◆  PICKUP RAID  ◆",
    "      ▸ .pickupraid  •  .spickupraid",
    "",
    "  ◆  ROMANCE RAID  ◆",
    "      ▸ .romanceraid  •  .sromanceraid",
    "",
    "  ◆  TROLL RAID  ◆",
    "      ▸ .trollraid  •  .strollraid",
    "",
    "  ◆  RAGEBAIT RAID  ◆",
    "      ▸ .ragebaitraid  •  .sragebaitraid",
    "",
    "  ◆  ROAST RAID  ◆",
    "      ▸ .roastraid  •  .sroastraid",
    "",
], back_cmd=BACK_TO_MAIN)

MENU_9 = build_box("💢 NON-ABUSIVE RAIDS", [
    "",
    "  ◆  ATTACK  ◆",
    "      ▸ .attackraid  •  .sattackraid",
    "",
    "  ◆  WAR  ◆",
    "      ▸ .warraid  •  .swarraid",
    "",
    "  ◆  SAVAGE  ◆",
    "      ▸ .savageraid  •  .ssavageraid",
    "",
    "  ◆  ULTRA  ◆",
    "      ▸ .ultraraid  •  .sultraraid",
    "",
    "  ◆  SHAME  ◆",
    "      ▸ .shameraid  •  .sshameraid",
    "",
    "  ◆  DISS  ◆",
    "      ▸ .dissraid  •  .sdissraid",
    "",
    "  ◆  DEVIL  ◆",
    "      ▸ .devilraid  •  .sdevilraid",
    "",
    "  ◆  KARMA  ◆",
    "      ▸ .karmaraid  •  .skarmaraid",
    "",
    "  ◆  DOOM  ◆",
    "      ▸ .doomraid  •  .sdoomraid",
    "",
], back_cmd=BACK_TO_MAIN)

MENU_10 = build_box("🎮 GAMES & FUN", [
    "",
    "  ◆  TRUTH / DARE / SITUATION  ◆",
    "",
    "  ▸ .truth      → Random truth",
    "  ▸ .dare       → Random dare",
    "  ▸ .situation  → Random situation",
    "",
    "  ◆  RIDDLE & QUIZ (60s timer)  ◆",
    "",
    "  ▸ .riddle → Paheli with timer",
    "  ▸ .quiz   → JEE/NEET/GK quiz",
    "",
    "  ◆  RPS (Rock-Paper-Scissors)  ◆",
    "",
    "  ▸ .rps r/p/s → Play RPS",
    "",
    "  ◆  TIC-TAC-TOE  ◆",
    "",
    "  ▸ .ttt       → Start game",
    "  ▸ .ttt_move  → Make a move (1-9)",
    "",
    "  ◆  DICE / FLIP  ◆",
    "",
    "  ▸ .dice → Roll dice",
    "  ▸ .flip → Flip coin",
    "",
    "  ◆  JOKE / FACT / COMPLIMENT / QUOTE  ◆",
    "",
    "  ▸ .joke       → Random joke",
    "  ▸ .fact       → Interesting fact",
    "  ▸ .compliment → Compliment",
    "  ▸ .quote      → Quote",
    "",
], back_cmd=BACK_TO_MAIN)

MENU_11A = build_box("✨ PREMIUM PART A", [
    "",
    "  ◆  TEXT FORMATTING  ◆",
    "",
    "  ▸ .upper      → Uppercase",
    "  ▸ .lower      → Lowercase",
    "  ▸ .reverse    → Reverse text",
    "  ▸ .len        → Char count",
    "  ▸ .wcount     → Word count",
    "  ▸ .bold       → Bold",
    "  ▸ .italic     → Italic",
    "  ▸ .mono       → Monospace",
    "  ▸ .camel      → camelCase",
    "  ▸ .repeat     → Repeat N times",
    "  ▸ .big        → Big text",
    "  ▸ .small      → Small text",
    "  ▸ .shadow     → Shadow text",
    "  ▸ .zalgo      → Zalgo effect",
    "  ▸ .leet       → Leet speak",
    "",
    "  ◆  UTILITY  ◆",
    "",
    "  ▸ .hex        → Hex encode",
    "  ▸ .octal      → Octal encode",
    "  ▸ .ascii      → ASCII codes",
    "  ▸ .nato       → NATO phonetic",
    "  ▸ .palindrome → Check palindrome",
    "  ▸ .vowels     → Count vowels",
    "  ▸ .wordfreq   → Word frequency",
    "  ▸ .charcount  → Chars (with spaces)",
    "  ▸ .lettercount→ Letters (no spaces)",
    "  ▸ .charinfo   → Unicode info",
    "",
    "  ◆  STYLISH TEXT  ◆",
    "",
    "  ▸ .titlecase     → Title Case",
    "  ▸ .snake         → snake_case",
    "  ▸ .shout         → SHOUT IT!",
    "  ▸ .mock          → mOcKiNg",
    "  ▸ .spaceit       → S p a c e d",
    "  ▸ .removespaces  → Remove spaces",
    "  ▸ .clap          → 👏 Clap 👏",
    "  ▸ .mirror        → Mirror text",
    "  ▸ .flip_text     → Flip upside down",
    "",
], back_cmd=BACK_TO_MAIN)

MENU_11B = build_box("🌟 PREMIUM PART B", [
    "",
    "  ◆  TYPING EFFECT  ◆",
    "",
    "  ▸ .typing bold     → Bold style",
    "  ▸ .typing italic   → Italic style",
    "  ▸ .typing double   → Double struck",
    "  ▸ .typing script   → Script style",
    "  ▸ .typing mono     → Monospace",
    "  ▸ .typing circle   → Circled letters",
    "  ▸ .typing square   → Squared letters",
    "  ▸ .typing <text>   → Bold (default)",
    "",
    "  ◆  MATH & FUNCTIONS  ◆",
    "",
    "  ▸ .bmi        → BMI calculator",
    "  ▸ .age        → Age from DOB (YYYY-MM-DD)",
    "  ▸ .prime      → Check prime",
    "  ▸ .factorial  → Factorial",
    "  ▸ .fibonacci  → Fibonacci seq",
    "  ▸ .square     → Square number",
    "  ▸ .roman      → Roman numeral",
    "  ▸ .table      → Multiplication table",
    "  ▸ .percentage → Calculate %",
    "  ▸ .number     → Number properties",
    "  ▸ .countdown  → Countdown timer",
    "",
    "  ◆  ENCRYPTION & HASH  ◆",
    "",
    "  ▸ .encrypt  → Caesar cipher (shift 3)",
    "  ▸ .decrypt  → Decrypt Caesar",
    "  ▸ .sha1     → SHA-1 hash",
    "  ▸ .sha512   → SHA-512 hash",
    "",
    "  ◆  FUN GAMES  ◆",
    "",
    "  ▸ .coin       → Flip a coin",
    "  ▸ .lucky      → Lucky number",
    "  ▸ .roll       → Roll a dice (max)",
    "  ▸ .timer      → Set a timer (seconds)",
    "  ▸ .typetest   → Typing speed test",
    "",
    "  ◆  OTHER PREMIUM  ◆",
    "",
    "  ▸ .afk           → Set AFK (or .afk off)",
    "  ▸ .premiumstatus → Check status",
    "  ▸ .protect       → Protect a command",
    "  ▸ .unprotect     → Remove protection",
    "  ▸ .protectlist   → List protected commands",
    "",
], back_cmd=BACK_TO_MAIN)

MENU_12 = build_box("🔰 PROTECTION & CLEANUP", [
    "",
    "  ◆  GOD PROTECTION  ◆",
    "",
    "  ▸ .godprotection on      → Enable",
    "  ▸ .godprotection off     → Disable",
    "  ▸ .godprotection         → Show status",
    "  ▸ .setgp action ...      → Set action",
    "  ▸ .setgp automute on/off → Toggle",
    "  ▸ .setgp threshold 5 10  → Threshold",
    "",
    "  ◆  DM SHIELD (Premium)  ◆",
    "",
    "  ▸ .dmshield on/off → Toggle",
    "  ▸ .approve @user   → Approve user",
    "  ▸ .unapprove @user → Remove approval",
    "  ▸ .block           → Block user",
    "  ▸ .unblock         → Unblock user",
    "  ▸ .blockedlist     → List blocked users",
    "",
    "  ◆  AUTO-REPLY & FILTERS  ◆",
    "",
    "  ▸ .addfilter <word>   → Add filter word",
    "  ▸ .delfilter <word>   → Remove filter",
    "  ▸ .listfilters        → Show all filters",
    "  ▸ .setautoreply <text>→ Set DM auto-reply",
    "  ▸ .delautoreply       → Remove auto-reply",
    "",
    "  ◆  NOTES (persistent)  ◆",
    "",
    "  ▸ .notesadd <text>   → Save note",
    "  ▸ .noteslist         → List notes",
    "  ▸ .notesdelete <id>  → Delete note",
    "",
    "  ◆  MASS DELETE  ◆",
    "",
    "  ▸ .dltall   → Reply to msg, delete from there",
    "  ▸ .clearme  → Delete ALL your messages in chat",
    "",
    "  ◆  SANGMATA (Name History)  ◆",
    "",
    "  ▸ .sangmata @user → Show name/username history",
    "",
], back_cmd=BACK_TO_MAIN)

MENU_13 = build_box("💥 PREMIUM RAIDS", [
    "",
    "  ◆  START / STOP  ◆",
    "",
    "  ▸ .mr   •  .smr   → Raid 1",
    "  ▸ .mr2  •  .smr2  → Raid 2",
    "  ▸ .br   •  .sbr   → Raid 3",
    "  ▸ .br2  •  .sbr2  → Raid 4",
    "  ▸ .br3  •  .sbr3  → Raid 5",
    "  ▸ .sqr  •  .ssqr  → Raid 6",
    "  ▸ .sq2  •  .ssq2  → Raid 7",
    "  ▸ .cr   •  .scr   → Raid 8",
    "  ▸ .bar  •  .sbar  → Raid 9",
    "  ▸ .gr   •  .sgr   → Raid 10",
    "",
], back_cmd=BACK_TO_MAIN)

MENU_14 = build_box("🔥 PREMIUM SPAM", [
    "",
    "  ◆  START / STOP  ◆",
    "",
    "  ▸ .ms   •  .sms   → Spam 1",
    "  ▸ .ms2  •  .sms2  → Spam 2",
    "  ▸ .bs   •  .sbs   → Spam 3",
    "  ▸ .bs2  •  .sbs2  → Spam 4",
    "  ▸ .bs3  •  .sbs3  → Spam 5",
    "  ▸ .sqs  •  .ssqs  → Spam 6",
    "  ▸ .sqs2 •  .ssqs2 → Spam 7",
    "  ▸ .cs   •  .scs   → Spam 8",
    "  ▸ .bas  •  .sbas  → Spam 9",
    "  ▸ .gs   •  .sgs   → Spam 10",
    "",
], back_cmd=BACK_TO_MAIN)

MENU_MAP = {
    "menu":     MENU_MAIN,
    "menu1":    MENU_1,
    "menu2":    MENU_2,
    "menu3":    MENU_3,
    "menu4":    MENU_4,
    "menu5":    MENU_5,
    "menu6":    MENU_6,
    "menu7":    MENU_7,
    "menu8":    MENU_8,
    "menu9":    MENU_9,
    "menu10":   MENU_10,
    "menu11a":  MENU_11A,
    "menu11b":  MENU_11B,
    "menu12":   MENU_12,
    "menu13":   MENU_13,
    "menu14":   MENU_14,
}

# ─── MAIN BOT HANDLERS ────────────────────────────────────────────

async def is_user_in_channel(user_id, channel_data):
    try:
        channel = await MAIN_BOT_CLIENT.get_entity(channel_data["id"])
        await MAIN_BOT_CLIENT.get_permissions(channel, user_id)
        return True
    except:
        return False

def get_join_buttons():
    buttons = []
    for idx, ch in enumerate(REQUIRED_CHANNELS, 1):
        buttons.append([Button.url(text=f"🔗 Join {ch['name']}", url=ch["invite"])])
    buttons.append([Button.inline(text="✅ I have joined all", data=b"verify_channels")])
    return buttons

async def shutdown_handler(sig, frame):
    print("🛑 Shutting down...")
    for uid in broadcast_users:
        try:
            await MAIN_BOT_CLIENT.send_message(uid, "⚠️ Bot is going offline for maintenance.\nWe'll be back soon!")
            await asyncio.sleep(0.5)
        except:
            pass
    for uid, client in active_userbots.items():
        try:
            await client.disconnect()
        except:
            pass
    for task in list(running_tasks):
        if not task.done():
            task.cancel()
            try:
                await asyncio.shield(task)
            except:
                pass
    await MAIN_BOT_CLIENT.disconnect()
    sys.exit(0)

signal.signal(signal.SIGTERM, lambda s, f: asyncio.create_task(shutdown_handler(s, f)))
signal.signal(signal.SIGINT, lambda s, f: asyncio.create_task(shutdown_handler(s, f)))

async def safe_reply(event, text, buttons=None, **kwargs):
    try:
        return await event.reply(text, buttons=buttons, **kwargs)
    except FloodWaitError as e:
        wait = e.seconds + 1
        await asyncio.sleep(wait)
        return await event.reply(text, buttons=buttons, **kwargs)
    except:
        return None

async def safe_respond(event, text, **kwargs):
    try:
        return await event.respond(text, **kwargs)
    except FloodWaitError as e:
        wait = e.seconds + 1
        await asyncio.sleep(wait)
        return await event.respond(text, **kwargs)
    except:
        return None

async def safe_edit(event, text, buttons=None, **kwargs):
    try:
        return await event.edit(text, buttons=buttons, **kwargs)
    except FloodWaitError as e:
        wait = e.seconds + 1
        await asyncio.sleep(wait)
        return await event.edit(text, buttons=buttons, **kwargs)
    except MessageNotModifiedError:
        pass
    except:
        return None

async def safe_send_main(chat, text, **kwargs):
    try:
        return await MAIN_BOT_CLIENT.send_message(chat, text, **kwargs)
    except FloodWaitError as e:
        wait = e.seconds + 1
        await asyncio.sleep(wait)
        return await MAIN_BOT_CLIENT.send_message(chat, text, **kwargs)
    except:
        return None

def plan_price(plan):
    return {"monthly": 45, "quarterly": 120, "yearly": 490}[plan]

def plan_price_str(plan):
    return f"₹{plan_price(plan)}"

# ─── REDEEM CODE FUNCTIONS ────────────────────────────────────────
async def generate_redeem_code(amount: float, expiry_days: int, max_uses: Optional[int] = None) -> str:
    code = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=12))
    expiry = datetime.now() + timedelta(days=expiry_days)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO redeem_codes (code, amount, expiry_date, max_uses, created_by) VALUES ($1, $2, $3, $4, $5)",
            code, amount, expiry, max_uses, 0
        )
    return code

async def redeem_code(user_id: int, code: str) -> (bool, str):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM redeem_codes WHERE code = $1", code)
        if not row:
            return False, "❌ Invalid code."
        if row['expiry_date'] and row['expiry_date'] < datetime.now():
            return False, "❌ Code has expired."
        if row['max_uses'] is not None and row['used_count'] >= row['max_uses']:
            return False, "❌ Code has been fully redeemed."
        amount = float(row['amount'])
        await conn.execute(
            "UPDATE redeem_codes SET used_count = used_count + 1 WHERE code = $1",
            code
        )
        await add_balance(user_id, amount)
        return True, f"✅ Successfully redeemed ₹{amount:.2f}!"

# ─── MAIN HANDLERS ─────────────────────────────────────────────────
@MAIN_BOT_CLIENT.on(events.NewMessage(pattern="/start"))
async def start_handler(event):
    user_id = event.sender_id
    broadcast_users.add(user_id)
    save_users(broadcast_users)
    buttons = [
        [Button.inline("💎 Buy Premium", data="buy_menu")],
        [Button.inline("💰 Deposit / Check Balance", data="deposit")],
        [Button.inline("🎟️ Redeem Code", data="redeem_prompt")],
        [Button.url("🔗 Premium Features", url=PREMIUM_FEATURES_LINK)],
    ]
    bal = await get_balance(user_id)
    intro = (
        "╔═══════════════════════════════════════════╗\n"
        "║  ✦ 👑 ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️ 𝐀𝐔𝐓𝐎-𝐃𝐄𝐏𝐋𝐎𝐘 👑 ✦  ║\n"
        "╚═══════════════════════════════════════════╝\n\n"
        f"Welcome to the **Ultimate Userbot Manager**.\n"
        f"• To start your personal userbot, type `/login`\n"
        f"• To stop it, use `/logout`\n"
        f"• Use the buttons below to buy premium or deposit.\n\n"
        f"💰 **Your Wallet Balance:** ₹{bal:.2f}\n\n"
        "Enjoy the premium experience! 🚀"
    )
    await safe_reply(event, intro, buttons=buttons)
    not_joined = []
    for ch in REQUIRED_CHANNELS:
        if not await is_user_in_channel(user_id, ch):
            not_joined.append(ch)
    if not_joined:
        force_join_msg = (
            "⚠️═══⟦ ꜰᴏʀᴄᴇ ᴊᴏɪɴ ʀᴇqᴜɪʀᴇᴅ ⟧═══⚠️\n\n"
            "✧➤ ᴘʟᴇᴀꜱᴇ ᴊᴏɪɴ ᴀʟʟ 4 ᴄʜᴀɴɴᴇʟꜱ ᴛᴏ\n"
            "   ᴜꜱᴇ ᴛʜɪꜱ ʙᴏᴛ ᴀɴᴅ ᴅᴇᴘʟᴏʏ\n"
            "❀═════════════════════════════❀"
        )
        await safe_respond(event, force_join_msg, buttons=get_join_buttons())

@MAIN_BOT_CLIENT.on(events.NewMessage(pattern="/freeze"))
async def freeze_cmd(event):
    if event.sender_id not in MY_OWNER_IDS:
        return
    args = event.text.strip().split()
    if len(args) != 2 or not args[1].isdigit():
        await safe_reply(event, "❌ Usage: /freeze <user_id>")
        return
    uid = int(args[1])
    await set_freeze(uid, True)
    if uid in active_userbots:
        try:
            await active_userbots[uid].send_message(uid, "❄️ Your userbot has been frozen by the owner.")
        except:
            pass
    await safe_reply(event, f"✅ User {uid} frozen.")

@MAIN_BOT_CLIENT.on(events.NewMessage(pattern="/unfreeze"))
async def unfreeze_cmd(event):
    if event.sender_id not in MY_OWNER_IDS:
        return
    args = event.text.strip().split()
    if len(args) != 2 or not args[1].isdigit():
        await safe_reply(event, "❌ Usage: /unfreeze <user_id>")
        return
    uid = int(args[1])
    await set_freeze(uid, False)
    if uid in active_userbots:
        try:
            await active_userbots[uid].send_message(uid, "🔥 Your userbot has been unfrozen by the owner.")
        except:
            pass
    await safe_reply(event, f"✅ User {uid} unfrozen.")

@MAIN_BOT_CLIENT.on(events.NewMessage(pattern="/freezelist"))
async def freezelist_cmd(event):
    if event.sender_id not in MY_OWNER_IDS:
        return
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM user_freeze WHERE frozen = TRUE")
    if not rows:
        await safe_reply(event, "📭 No frozen users.")
        return
    msg = "❄️ **Frozen Users:**\n" + "\n".join(f"• `{r['user_id']}`" for r in rows)
    await safe_reply(event, msg)

@MAIN_BOT_CLIENT.on(events.NewMessage(pattern="/login"))
async def login_handler(event):
    if not event.is_private:
        return
    user_id = event.sender_id
    not_joined = []
    for ch in REQUIRED_CHANNELS:
        if not await is_user_in_channel(user_id, ch):
            not_joined.append(ch)
    if not_joined:
        msg = "⚠️═══⟦ ꜰᴏʀᴄᴇ ᴊᴏɪɴ ʀᴇqᴜɪʀᴇᴅ ⟧═══⚠️\n\n"
        for ch in not_joined:
            msg += f"✧➤ {ch['name']} ({ch['invite']})\n"
        msg += "\n❀═════════════════════════════❀"
        buttons = get_join_buttons()
        await safe_reply(event, msg, buttons=buttons)
        return
    user_states[user_id] = {"step": "NUMBER"}
    await safe_reply(
        event,
        "📱 **Step 1:** Please send your Telegram phone number **with country code**.\n"
        "Example: `+919876543210`"
    )

@MAIN_BOT_CLIENT.on(events.NewMessage)
async def handle_login_phone(event):
    if not event.is_private:
        return
    if event.raw_text and event.raw_text.startswith('/'):
        return
    user_id = event.sender_id
    state = user_states.get(user_id)
    if not state or state.get("step") != "NUMBER":
        return
    phone = event.raw_text.strip()
    phone = re.sub(r'[\s\-\(\)]', '', phone)
    if not re.match(r'^\+?\d{10,15}$', phone):
        await safe_reply(event, "❌ Invalid phone number format. Please send with country code, e.g., `+919876543210`")
        return
    try:
        temp_client = TelegramClient(StringSession(), API_ID, API_HASH)
        await temp_client.connect()
        await temp_client.send_code_request(phone)
        user_states[user_id]["step"] = "CODE"
        user_states[user_id]["phone"] = phone
        user_states[user_id]["temp_client"] = temp_client
        await safe_reply(event, "📨 **Code sent!** Please send the numeric code (e.g., `12345` or `1 2 3 4 5`).")
    except ValueError as e:
        await safe_reply(event, f"❌ Invalid phone number: {str(e)}. Check the number and country code.")
        user_states.pop(user_id, None)
        try:
            await temp_client.disconnect()
        except:
            pass
    except FloodWaitError as e:
        await safe_reply(event, f"⏳ Too many requests. Please wait {e.seconds} seconds and try again.")
        user_states.pop(user_id, None)
        try:
            await temp_client.disconnect()
        except:
            pass
    except Exception as e:
        await safe_reply(event, f"❌ Failed to send code: {str(e)}")
        user_states.pop(user_id, None)
        try:
            await temp_client.disconnect()
        except:
            pass

@MAIN_BOT_CLIENT.on(events.NewMessage)
async def handle_login_code(event):
    if not event.is_private:
        return
    if event.raw_text and event.raw_text.startswith('/'):
        return
    user_id = event.sender_id
    state = user_states.get(user_id)
    if not state or state.get("step") != "CODE":
        return
    code = event.raw_text.strip().replace(" ", "").replace("-", "")
    if not code.isdigit():
        await safe_reply(event, "❌ Please send only the numeric code (e.g., `12345`). Spaces are allowed.")
        return
    temp_client = state.get("temp_client")
    phone = state.get("phone")
    if not temp_client or not phone:
        await safe_reply(event, "❌ Login session expired. Please start again with `/login`.")
        user_states.pop(user_id, None)
        return
    try:
        await temp_client.sign_in(phone, code=code)
        session_str = temp_client.session.save()
        await save_session(user_id, session_str)
        task = asyncio.create_task(run_user_bot_with_restart(session_str, user_id))
        task.set_name(f"userbot_restart_{user_id}")
        running_tasks.add(task)
        task.add_done_callback(running_tasks.discard)
        user_entity = await MAIN_BOT_CLIENT.get_entity(user_id)
        user_name = user_entity.first_name or "Unknown"
        username = f"@{user_entity.username}" if user_entity.username else "No username"
        if len(phone) > 6:
            phone_display = phone[:3] + "*" * (len(phone) - 6) + phone[-3:]
        else:
            phone_display = phone[:3] + "*" * (len(phone) - 3) if len(phone) > 3 else phone
        for owner in MY_OWNER_IDS:
            try:
                await MAIN_BOT_CLIENT.send_message(
                    owner,
                    f"🔐 **User Login**\n"
                    f"👤 Name: {user_name}\n"
                    f"🆔 ID: `{user_id}`\n"
                    f"🔗 Username: {username}\n"
                    f"📱 Phone: `{phone_display}`\n"
                    f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
            except:
                pass
        await safe_reply(event, "✅ **Userbot started successfully!**\nYou can now use it in groups.\nType `.menu` to see commands.")
        user_states.pop(user_id, None)
        await temp_client.disconnect()
    except SessionPasswordNeededError:
        state["step"] = "PASSWORD"
        await safe_reply(event, "🔐 **Two-factor authentication is enabled.**\nPlease send your 2FA password.")
    except FloodWaitError as e:
        wait = e.seconds + 1
        await safe_reply(event, f"⏳ Too many attempts. Please wait **{wait} seconds** and try again.")
    except Exception as e:
        error_msg = str(e)
        if "code invalid" in error_msg.lower() or "invalid code" in error_msg.lower():
            await safe_reply(event, "❌ **Invalid code.** Please check and try again.\nSend the code again (e.g., `12345`).")
        else:
            await safe_reply(event, f"❌ Login failed: {error_msg}")
            user_states.pop(user_id, None)
            try:
                await temp_client.disconnect()
            except:
                pass

@MAIN_BOT_CLIENT.on(events.NewMessage)
async def handle_login_password(event):
    if not event.is_private:
        return
    if event.raw_text and event.raw_text.startswith('/'):
        return
    user_id = event.sender_id
    state = user_states.get(user_id)
    if not state or state.get("step") != "PASSWORD":
        return
    password = event.raw_text.strip()
    temp_client = state.get("temp_client")
    if not temp_client:
        await safe_reply(event, "❌ Session expired. Please start again with `/login`.")
        user_states.pop(user_id, None)
        return
    try:
        await temp_client.sign_in(password=password)
        session_str = temp_client.session.save()
        await save_session(user_id, session_str)
        task = asyncio.create_task(run_user_bot_with_restart(session_str, user_id))
        task.set_name(f"userbot_restart_{user_id}")
        running_tasks.add(task)
        task.add_done_callback(running_tasks.discard)
        user_entity = await MAIN_BOT_CLIENT.get_entity(user_id)
        user_name = user_entity.first_name or "Unknown"
        username = f"@{user_entity.username}" if user_entity.username else "No username"
        phone = state.get("phone", "Unknown")
        if len(phone) > 6:
            phone_display = phone[:3] + "*" * (len(phone) - 6) + phone[-3:]
        else:
            phone_display = phone[:3] + "*" * (len(phone) - 3) if len(phone) > 3 else phone
        for owner in MY_OWNER_IDS:
            try:
                await MAIN_BOT_CLIENT.send_message(
                    owner,
                    f"🔐 **User Login (2FA)**\n"
                    f"👤 Name: {user_name}\n"
                    f"🆔 ID: `{user_id}`\n"
                    f"🔗 Username: {username}\n"
                    f"📱 Phone: `{phone_display}`\n"
                    f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
            except:
                pass
        await safe_reply(event, "✅ **Userbot started successfully!**\nYou can now use it in groups.\nType `.menu` to see commands.")
        user_states.pop(user_id, None)
        await temp_client.disconnect()
    except FloodWaitError as e:
        wait = e.seconds + 1
        await safe_reply(event, f"⏳ Too many incorrect attempts. Please wait **{wait} seconds** and try again.")
    except Exception as e:
        error_msg = str(e)
        if "password" in error_msg.lower() and ("invalid" in error_msg.lower() or "hash" in error_msg.lower()):
            await safe_reply(event, "❌ **Incorrect 2FA password.** Please try again.\n\nSend your correct 2FA password.")
        else:
            await safe_reply(event, f"❌ Login failed: {error_msg}")
            user_states.pop(user_id, None)
            try:
                await temp_client.disconnect()
            except:
                pass

@MAIN_BOT_CLIENT.on(events.CallbackQuery)
async def callback_handler(event):
    data = event.data.decode()
    if data == "verify_channels":
        user_id = event.sender_id
        not_joined = []
        for ch in REQUIRED_CHANNELS:
            if not await is_user_in_channel(user_id, ch):
                not_joined.append(ch)
        if not_joined:
            msg = "⚠️═══⟦ ꜰᴏʀᴄᴇ ᴊᴏɪɴ ʀᴇqᴜɪʀᴇᴅ ⟧═══⚠️\n\n"
            for ch in not_joined:
                msg += f"✧➤ {ch['name']} ({ch['invite']})\n"
            msg += "\n❀═════════════════════════════❀"
            buttons = get_join_buttons()
            try:
                await safe_edit(event, msg, buttons=buttons)
            except MessageNotModifiedError:
                pass
            await event.answer("Please join all channels first.", alert=True)
        else:
            try:
                await safe_edit(event, "✅ **All channels verified!**\n\n📱 Now send your phone number (with country code).")
            except MessageNotModifiedError:
                pass
            user_states[user_id] = {"step": "NUMBER"}
            await safe_respond(
                event,
                "📱 **Step 1:** Send your phone number with country code.\n"
                "Example: `+919876543210`"
            )
            await event.answer("Verified! Now send your number.")
    elif data == "deposit":
        user_id = event.sender_id
        if event.chat_id != user_id:
            await event.answer("Please use this in private chat.", alert=True)
            return
        caption = (
            "💰 **Deposit Funds**\n\n"
            "1. Scan the QR below or use UPI: `{UPI_ID}`\n"
            "2. Send any amount you want to deposit.\n"
            "3. **After payment, send a screenshot** with the **amount paid** in the caption.\n"
            "4. Example caption: `I paid ₹100`\n"
            "5. Our team will verify and credit your wallet."
        ).format(UPI_ID=UPI_ID)
        buttons = [[Button.url("🔗 Premium Features", url=PREMIUM_FEATURES_LINK)]]
        try:
            await event.delete()
        except:
            pass
        try:
            await event.respond(caption, file=QR_IMAGE_PATH, buttons=buttons)
        except Exception as e:
            await event.respond(caption + "\n\n⚠️ QR image not found. Please contact owner.", buttons=buttons)
            print(f"Deposit QR send error: {e}")
        user_states[user_id] = {"step": "waiting_deposit"}
        await event.answer("Deposit instructions sent.")
    elif data == "buy_menu":
        user_id = event.sender_id
        if event.chat_id != user_id:
            await event.answer("Please use this in private chat.", alert=True)
            return
        prem = await check_premium_status(user_id)
        if prem:
            expiry = prem['expiry_date'].strftime("%Y-%m-%d")
            await safe_edit(event, f"💎 You are already a premium user!\nPlan: {prem['plan'].upper()}\nExpires: {expiry}")
            return
        buttons = [
            [Button.inline("📅 Monthly (₹45/30 days)", data="buy_monthly")],
            [Button.inline("📅 Quarterly (₹120/90 days)", data="buy_quarterly")],
            [Button.inline("📅 Yearly (₹490/365 days)", data="buy_yearly")],
        ]
        await safe_edit(event, "💰 **Select your premium plan:**", buttons=buttons)
    elif data.startswith("buy_"):
        plan = data.split("_")[1]
        user_id = event.sender_id
        price = plan_price(plan)
        bal = await get_balance(user_id)
        if bal < price:
            msg = (
                f"❌ **Insufficient Balance!**\n\n"
                f"Your balance: ₹{bal:.2f}\n"
                f"Plan price: ₹{price}\n"
                f"Need additional: ₹{price - bal:.2f}\n\n"
                f"Please deposit more funds using the **Deposit** button."
            )
            buttons = [[Button.inline("💰 Deposit Now", data="deposit")]]
            await safe_edit(event, msg, buttons=buttons)
            return
        try:
            await deduct_balance(user_id, price)
        except ValueError as e:
            await safe_edit(event, f"❌ {e}")
            return
        days = {"monthly":30, "quarterly":90, "yearly":365}[plan]
        await add_premium_user(user_id, plan, days)
        await safe_edit(event, f"✅ **Premium activated!**\nPlan: {plan.upper()}\nValid for {days} days.\nBalance deducted: ₹{price:.2f}")
        await safe_send_main(user_id, f"🎉 **Your premium subscription has been activated!**\nPlan: {plan.upper()}\nExpires: {datetime.now() + timedelta(days=days)}")
        await MAIN_BOT_CLIENT.send_message(user_id, "You can now use all premium commands in your userbot. Type `.menu11a` and `.menu11b` to see them.")
        user_states.pop(user_id, None)
    elif data.startswith("approve_deposit_"):
        parts = data.split("_")
        if len(parts) != 4:
            return
        _, _, user_id_str, amount_str = parts
        user_id = int(user_id_str)
        amount = float(amount_str)
        if event.sender_id not in MY_OWNER_IDS:
            await event.answer("❌ Not authorized.", alert=True)
            return
        await add_balance(user_id, amount)
        await event.edit(f"✅ Deposit of ₹{amount:.2f} approved for user {user_id}")
        await safe_send_main(user_id, f"✅ Your deposit of ₹{amount:.2f} has been credited.\nNew balance: ₹{await get_balance(user_id):.2f}")
    elif data.startswith("reject_deposit_"):
        _, _, user_id_str = data.split("_")
        user_id = int(user_id_str)
        if event.sender_id not in MY_OWNER_IDS:
            await event.answer("❌ Not authorized.", alert=True)
            return
        await event.edit(f"❌ Deposit rejected for user {user_id}")
        await safe_send_main(user_id, "❌ Your deposit was rejected. Please try again or contact support.")
    elif data.startswith("approve_"):
        _, user_id_str, plan = data.split("_")
        user_id = int(user_id_str)
        if event.sender_id not in MY_OWNER_IDS:
            await event.answer("❌ Not authorized.", alert=True)
            return
        days = {"monthly":30, "quarterly":90, "yearly":365}[plan]
        await add_premium_user(user_id, plan, days)
        await event.edit(f"✅ Premium activated for user {user_id} ({plan})")
        await safe_send_main(user_id, f"🎉 **Your premium subscription has been activated!**\nPlan: {plan.upper()}\nExpires: {datetime.now() + timedelta(days=days)}")
        await MAIN_BOT_CLIENT.send_message(user_id, "You can now use all premium commands in your userbot. Type `.menu11a` and `.menu11b` to see them.")
    elif data.startswith("reject_"):
        _, user_id_str = data.split("_")
        user_id = int(user_id_str)
        if event.sender_id not in MY_OWNER_IDS:
            await event.answer("❌ Not authorized.", alert=True)
            return
        await event.edit(f"❌ Payment rejected for user {user_id}")
        await safe_send_main(user_id, "❌ Your payment was rejected. Please try again or contact support.")
    elif data.startswith("bestfrnd_yes_"):
        _, _, uid = data.split("_")
        uid = int(uid)
        sender = event.sender_id
        try:
            u = await MAIN_BOT_CLIENT.get_entity(uid)
            name = u.first_name or str(uid)
            await event.edit(f"💞 **{name}** said YES! 🎉\nYou are now best friends forever! 🌟")
            await MAIN_BOT_CLIENT.send_message(uid, f"💞 {sender} asked you to be best friend and you said YES! 🥳")
        except:
            await event.edit("❌ Something went wrong.")
    elif data.startswith("bestfrnd_no_"):
        _, _, uid = data.split("_")
        uid = int(uid)
        sender = event.sender_id
        try:
            u = await MAIN_BOT_CLIENT.get_entity(uid)
            name = u.first_name or str(uid)
            await event.edit(f"💔 **{name}** said NO. 😢\nMaybe next time...")
            await MAIN_BOT_CLIENT.send_message(uid, f"💔 {sender} asked you to be best friend but you said NO.")
        except:
            await event.edit("❌ Something went wrong.")
    elif data.startswith("marriage_yes_"):
        _, _, uid = data.split("_")
        uid = int(uid)
        sender = event.sender_id
        try:
            u = await MAIN_BOT_CLIENT.get_entity(uid)
            name = u.first_name or str(uid)
            await event.edit(f"💍 **{name}** said YES! 💍🎉\nYou are now married! ❤️")
            await MAIN_BOT_CLIENT.send_message(uid, f"💍 {sender} proposed and you said YES! Congratulations! 🥂")
        except:
            await event.edit("❌ Something went wrong.")
    elif data.startswith("marriage_no_"):
        _, _, uid = data.split("_")
        uid = int(uid)
        sender = event.sender_id
        try:
            u = await MAIN_BOT_CLIENT.get_entity(uid)
            name = u.first_name or str(uid)
            await event.edit(f"💔 **{name}** said NO. 😢\nMaybe next time...")
            await MAIN_BOT_CLIENT.send_message(uid, f"💔 {sender} proposed but you said NO.")
        except:
            await event.edit("❌ Something went wrong.")
    elif data.startswith("divorce_yes_"):
        _, _, uid = data.split("_")
        uid = int(uid)
        sender = event.sender_id
        try:
            u = await MAIN_BOT_CLIENT.get_entity(uid)
            name = u.first_name or str(uid)
            await event.edit(f"💔 **{name}** agreed to divorce. 😢\nIt's over...")
            await MAIN_BOT_CLIENT.send_message(uid, f"💔 {sender} wants a divorce and you agreed.")
        except:
            await event.edit("❌ Something went wrong.")
    elif data.startswith("divorce_no_"):
        _, _, uid = data.split("_")
        uid = int(uid)
        sender = event.sender_id
        try:
            u = await MAIN_BOT_CLIENT.get_entity(uid)
            name = u.first_name or str(uid)
            await event.edit(f"💔 **{name}** said NO to divorce. 💔\nMaybe try to work it out?")
            await MAIN_BOT_CLIENT.send_message(uid, f"💔 {sender} asked for divorce but you said NO.")
        except:
            await event.edit("❌ Something went wrong.")
    elif data == "redeem_prompt":
        user_id = event.sender_id
        if event.chat_id != user_id:
            await event.answer("Please use this in private chat.", alert=True)
            return
        await event.edit("🎟️ **Redeem Code**\n\nPlease send the redeem code you have.\nFormat: `/redeem <code>`")
        await event.answer("Use /redeem <code>")
    else:
        await event.answer("Unknown action.")

@MAIN_BOT_CLIENT.on(events.NewMessage(pattern="/buy"))
async def buy_cmd(event):
    if not event.is_private:
        return
    user_id = event.sender_id
    prem = await check_premium_status(user_id)
    if prem:
        expiry = prem['expiry_date'].strftime("%Y-%m-%d")
        await safe_reply(event, f"💎 You are already a premium user!\nPlan: {prem['plan'].upper()}\nExpires: {expiry}")
        return
    buttons = [
        [Button.inline("📅 Monthly (₹45/30 days)", data="buy_monthly")],
        [Button.inline("📅 Quarterly (₹120/90 days)", data="buy_quarterly")],
        [Button.inline("📅 Yearly (₹490/365 days)", data="buy_yearly")],
    ]
    await safe_reply(event, "💰 **Select your premium plan:**", buttons=buttons)

@MAIN_BOT_CLIENT.on(events.NewMessage(pattern="/deposit"))
async def deposit_cmd(event):
    if not event.is_private:
        return
    user_id = event.sender_id
    caption = (
        "💰 **Deposit Funds**\n\n"
        "1. Scan the QR below or use UPI: `{UPI_ID}`\n"
        "2. Send any amount you want to deposit.\n"
        "3. **After payment, send a screenshot** with the **amount paid** in the caption.\n"
        "4. Example caption: `I paid ₹100`\n"
        "5. Our team will verify and credit your wallet."
    ).format(UPI_ID=UPI_ID)
    buttons = [[Button.url("🔗 Premium Features", url=PREMIUM_FEATURES_LINK)]]
    try:
        await event.reply(caption, file=QR_IMAGE_PATH, buttons=buttons)
    except Exception as e:
        await event.reply(caption + "\n\n⚠️ QR image not found. Please contact owner.", buttons=buttons)
        print(f"Deposit QR send error: {e}")
    user_states[user_id] = {"step": "waiting_deposit"}

@MAIN_BOT_CLIENT.on(events.NewMessage(pattern="/redeem"))
async def redeem_cmd(event):
    if not event.is_private:
        return
    user_id = event.sender_id
    args = event.text.strip().split()
    if len(args) != 2:
        await safe_reply(event, "❌ Usage: /redeem <code>")
        return
    code = args[1].strip().upper()
    success, msg = await redeem_code(user_id, code)
    await safe_reply(event, msg)

@MAIN_BOT_CLIENT.on(events.NewMessage(pattern="/gencode"))
async def gencode_cmd(event):
    if event.sender_id not in MY_OWNER_IDS:
        return
    args = event.text.strip().split()
    if len(args) < 3:
        await safe_reply(event, "❌ Usage: /gencode <amount> <expiry_days> [max_uses]")
        return
    try:
        amount = float(args[1])
        expiry_days = int(args[2])
        max_uses = None
        if len(args) >= 4:
            max_uses = int(args[3])
            if max_uses <= 0:
                max_uses = None
    except ValueError:
        await safe_reply(event, "❌ Invalid arguments. Use: /gencode <amount> <expiry_days> [max_uses]")
        return
    code = await generate_redeem_code(amount, expiry_days, max_uses)
    await safe_reply(event, f"✅ **Redeem Code Generated**\n\nCode: `{code}`\nAmount: ₹{amount:.2f}\nExpires in {expiry_days} days\nMax uses: {'Unlimited' if max_uses is None else max_uses}\n\nShare this code with users to redeem.")

@MAIN_BOT_CLIENT.on(events.NewMessage)
async def payment_handler(event):
    if not event.is_private:
        return
    if event.raw_text and event.raw_text.startswith('/'):
        return
    user_id = event.sender_id
    state = user_states.get(user_id, {})
    step = state.get("step")
    if step == "waiting_deposit":
        if not event.photo:
            await safe_reply(event, "❌ Please send a screenshot image of the deposit transaction.")
            return
        caption_text = event.raw_text or ""
        amount = None
        match = re.search(r'(\d+(\.\d+)?)', caption_text)
        if match:
            amount = float(match.group(1))
        if amount is None or amount <= 0:
            await safe_reply(event, "❌ Please include the amount you paid in the caption.\nExample: `I paid ₹100`")
            return
        try:
            user_entity = await MAIN_BOT_CLIENT.get_entity(user_id)
            user_name = user_entity.first_name or "Unknown"
            user_username = f"@{user_entity.username}" if user_entity.username else "No username"
        except:
            user_name = "Unknown"
            user_username = "Unknown"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        caption = (
            f"💰 **New Deposit Request**\n"
            f"👤 **User:** {user_name}\n"
            f"🆔 **ID:** `{user_id}`\n"
            f"🔗 **Username:** {user_username}\n"
            f"💵 **Amount:** ₹{amount:.2f}\n"
            f"⏰ **Time:** {now}"
        )
        for owner in MY_OWNER_IDS:
            try:
                fwd = await MAIN_BOT_CLIENT.forward_messages(owner, event.id, event.chat_id)
                if fwd:
                    await MAIN_BOT_CLIENT.send_message(
                        owner,
                        caption,
                        buttons=[
                            [Button.inline("✅ Approve", f"approve_deposit_{user_id}_{amount}")],
                            [Button.inline("❌ Reject", f"reject_deposit_{user_id}")],
                        ]
                    )
            except Exception as e:
                print(f"Failed to forward deposit to owner {owner}: {e}")
        await safe_reply(event, "✅ Your deposit screenshot has been sent for verification.")
        return
    if step == "waiting_payment":
        if not event.photo:
            await safe_reply(event, "❌ Please send a screenshot image of the payment.")
            return
        plan = state.get("plan", "monthly")
        try:
            user_entity = await MAIN_BOT_CLIENT.get_entity(user_id)
            user_name = user_entity.first_name or "Unknown"
            user_username = f"@{user_entity.username}" if user_entity.username else "No username"
        except:
            user_name = "Unknown"
            user_username = "Unknown"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        caption = (
            f"💳 **New Payment Request**\n"
            f"👤 **User:** {user_name}\n"
            f"🆔 **ID:** `{user_id}`\n"
            f"🔗 **Username:** {user_username}\n"
            f"📅 **Plan:** {plan.upper()}\n"
            f"💰 **Amount:** {plan_price_str(plan)}\n"
            f"⏰ **Time:** {now}"
        )
        for owner in MY_OWNER_IDS:
            try:
                fwd = await MAIN_BOT_CLIENT.forward_messages(owner, event.id, event.chat_id)
                if fwd:
                    await MAIN_BOT_CLIENT.send_message(
                        owner,
                        caption,
                        buttons=[
                            [Button.inline("✅ Approve", f"approve_{user_id}_{plan}")],
                            [Button.inline("❌ Reject", f"reject_{user_id}")],
                        ]
                    )
            except Exception as e:
                print(f"Failed to forward to owner {owner}: {e}")
        await safe_reply(event, "✅ Your payment screenshot has been sent for verification.")
        user_states.pop(user_id, None)

# ─── BROADCAST COMMAND ──────────────────────────────────
@MAIN_BOT_CLIENT.on(events.NewMessage(pattern="/broadcast"))
async def broadcast_cmd(event):
    if event.sender_id not in MY_OWNER_IDS:
        return await safe_reply(event, "❌ Owner only.")
    text = event.text.strip().replace("/broadcast", "").strip()
    if not text:
        return await safe_reply(event, "Usage: /broadcast <message>")
    count = 0
    failed = 0
    for uid in list(broadcast_users):
        try:
            await safe_send_main(uid, f"📢 **Broadcast from Owner:**\n{text}")
            count += 1
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Broadcast failed for {uid}: {e}")
            failed += 1
    await safe_reply(event, f"✅ Broadcast sent to {count} users. Failed: {failed}")

@MAIN_BOT_CLIENT.on(events.NewMessage(pattern="/listusers"))
async def listusers_cmd(event):
    if event.sender_id not in MY_OWNER_IDS:
        return
    if not broadcast_users:
        return await event.reply("📭 Koi user registered nahi hai.")
    ids = "\n".join(f"• `{uid}`" for uid in sorted(broadcast_users))
    await event.reply(f"👥 **Registered Users** ({len(broadcast_users)}):\n{ids}")

@MAIN_BOT_CLIENT.on(events.NewMessage(pattern="/logout"))
async def logout_handler(event):
    if not event.is_private:
        return
    user_id = event.sender_id
    if user_id not in active_userbots:
        await safe_reply(event, "❌ You don't have an active userbot.\n\nUse `/login` to start one.")
        return
    try:
        user_bot = active_userbots[user_id]
        tasks_to_cancel = []
        for task in asyncio.all_tasks():
            if task.get_name() in [f"userbot_{user_id}", f"userbot_restart_{user_id}"]:
                tasks_to_cancel.append(task)
        for task in tasks_to_cancel:
            if not task.done():
                task.cancel()
                try:
                    await asyncio.shield(task)
                except:
                    pass
        await user_bot.disconnect()
        del active_userbots[user_id]
        user_sessions.pop(user_id, None)
        await delete_session(user_id)
        user_states.pop(user_id, None)
        await safe_reply(
            event,
            "✅ **Your userbot has been safely logged out.**\n\n"
            "• Userbot session terminated.\n"
            "• You can start a new one anytime with `/login`.\n"
            "• Your ID remains in the broadcast list."
        )
        user_entity = await MAIN_BOT_CLIENT.get_entity(user_id)
        user_name = user_entity.first_name or "Unknown"
        username = f"@{user_entity.username}" if user_entity.username else "No username"
        for owner in MY_OWNER_IDS:
            try:
                await MAIN_BOT_CLIENT.send_message(
                    owner,
                    f"🚪 **User Logout**\n"
                    f"👤 Name: {user_name}\n"
                    f"🆔 ID: `{user_id}`\n"
                    f"🔗 Username: {username}\n"
                    f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
            except:
                pass
    except Exception as e:
        await safe_reply(event, f"❌ Logout error: `{str(e)}`")
        active_userbots.pop(user_id, None)
        user_sessions.pop(user_id, None)
        await delete_session(user_id)

@MAIN_BOT_CLIENT.on(events.NewMessage(pattern="/purnjanam"))
async def purnjanam_handler(event):
    if event.sender_id not in MY_OWNER_IDS:
        return
    await safe_reply(event, "🌀 **पुनर्जन्म**...\n⏳ Userbot restart ho raha hai...")
    count = 0
    for uid, session_str in list(user_sessions.items()):
        try:
            if uid in active_userbots:
                try:
                    await active_userbots[uid].disconnect()
                except:
                    pass
                del active_userbots[uid]
            task = asyncio.create_task(run_user_bot_with_restart(session_str, uid))
            task.set_name(f"userbot_restart_{uid}")
            running_tasks.add(task)
            task.add_done_callback(running_tasks.discard)
            count += 1
            await asyncio.sleep(1)
        except Exception as e:
            print(f"Purnjanam error for {uid}: {e}")
    await safe_reply(event, f"✅ **पुनर्जन्म पूर्ण!**\n🔄 {count} userbots restart kiye gaye.")

@MAIN_BOT_CLIENT.on(events.NewMessage(pattern="/giftpremium"))
async def gift_premium(event):
    if event.sender_id not in MY_OWNER_IDS:
        return
    args = event.text.strip().split()
    if len(args) < 3:
        await safe_reply(event, "Usage: /giftpremium <user_id> <days>")
        return
    try:
        user_id = int(args[1])
        days = int(args[2])
        if days <= 0:
            await safe_reply(event, "Days must be a positive integer.")
            return
        plan = f"{days} days"
        expiry = datetime.now() + timedelta(days=days)
        await add_premium_user(user_id, plan, days)
        await safe_reply(
            event,
            f"✅ Premium gifted to {user_id} for {days} days.\n"
            f"📅 Expires on: {expiry.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await safe_send_main(
            user_id,
            f"🎁 You have received a premium gift of **{days} days**!\n"
            f"📅 Expires on: {expiry.strftime('%Y-%m-%d %H:%M:%S')}"
        )
    except ValueError:
        await safe_reply(event, "❌ Invalid user ID or days. Usage: /giftpremium <user_id> <days>")
    except Exception as e:
        await safe_reply(event, f"❌ Error: {e}")

# ─── USERBOT LAUNCHER WITH RESTART ──────────────────────────────
async def run_user_bot_with_restart(session_string, chat_id):
    restart_count = 0
    max_restarts = 10
    backoff = 5
    last_restart_time = 0
    session_invalid_notified = False

    while True:
        try:
            await run_user_bot(session_string, chat_id)
            break
        except FloodWaitError as e:
            wait = e.seconds + 5
            print(f"⏳ FloodWait: {wait}s for {chat_id}")
            try:
                await MAIN_BOT_CLIENT.send_message(chat_id, f"⚠️ Flood limit reached. Wait {wait//60}m {wait%60}s.")
            except:
                pass
            await asyncio.sleep(wait)
            restart_count = 0
            session_invalid_notified = False
            continue

        except (UnauthorizedError, ValueError, RPCError) as e:
            error_msg = str(e)
            if "SESSION_INVALID" in error_msg or "invalid" in error_msg.lower():
                if not session_invalid_notified:
                    session_invalid_notified = True
                    try:
                        await MAIN_BOT_CLIENT.send_message(chat_id,
                            "⚠️ Session expired. Please login again with /login.\n"
                            "🛑 This userbot will NOT restart automatically.")
                        for owner in MY_OWNER_IDS:
                            await MAIN_BOT_CLIENT.send_message(owner,
                                f"🔴 Session invalid for user {chat_id}")
                    except:
                        pass
                try:
                    if chat_id in active_userbots:
                        await active_userbots[chat_id].disconnect()
                        del active_userbots[chat_id]
                except:
                    pass
                user_sessions.pop(chat_id, None)
                await delete_session(chat_id)
                break

        except AuthKeyDuplicatedError as e:
            try:
                await MAIN_BOT_CLIENT.send_message(chat_id,
                    "⚠️ Session used from another device. Please login again.")
            except:
                pass
            if chat_id in active_userbots:
                try:
                    await active_userbots[chat_id].disconnect()
                except:
                    pass
                del active_userbots[chat_id]
            user_sessions.pop(chat_id, None)
            await delete_session(chat_id)
            break

        except asyncio.CancelledError:
            print(f"Restart task cancelled for {chat_id}")
            break

        except Exception as e:
            now = time.time()
            error_msg = str(e)
            if "EOF" in error_msg or "input" in error_msg.lower() or "interactive" in error_msg.lower():
                try:
                    await MAIN_BOT_CLIENT.send_message(chat_id,
                        "⚠️ Your session became invalid. Please login again.")
                    for owner in MY_OWNER_IDS:
                        await MAIN_BOT_CLIENT.send_message(owner,
                            f"🚫 Session invalid (EOF/interactive) for {chat_id}")
                except:
                    pass
                if chat_id in active_userbots:
                    try:
                        await active_userbots[chat_id].disconnect()
                    except:
                        pass
                    del active_userbots[chat_id]
                user_sessions.pop(chat_id, None)
                await delete_session(chat_id)
                break

            restart_count += 1
            if restart_count > max_restarts:
                print(f"⚠️ Too many restarts ({restart_count}) for {chat_id}. Stopping.")
                try:
                    await MAIN_BOT_CLIENT.send_message(chat_id,
                        "⚠️ Userbot crashing repeatedly. Stopping automatic restarts.\n"
                        "Please contact owner.")
                except:
                    pass
                break

            wait = min(backoff * (2 ** (restart_count - 1)), 300)
            if now - last_restart_time < 60 and restart_count > 3:
                wait = max(wait, 60)

            print(f"⚠️ Crash: {error_msg[:100]}. Restarting in {wait}s (attempt {restart_count})")
            try:
                await MAIN_BOT_CLIENT.send_message(chat_id,
                    f"⚠️ Userbot crashed. Restarting in {wait}s (attempt {restart_count})")
            except:
                pass
            await asyncio.sleep(wait)
            last_restart_time = now

# ─── FULL USERBOT ENGINE ──────────────────────────────────────────
async def run_user_bot(session_string, chat_id):
    user_bot = None
    try:
        user_bot = TelegramClient(
            StringSession(session_string),
            API_ID,
            API_HASH,
            auto_reconnect=True,
            connection_retries=10,
          
        )
        await user_bot.start()
        active_userbots[chat_id] = user_bot

        me = await user_bot.get_me()
        OWNER_IDS = {me.id}

        # ─── PER-USER DATA FOLDER ───
        USER_DATA_DIR = "user_data"
        os.makedirs(USER_DATA_DIR, exist_ok=True)

        def get_user_file(name):
            return os.path.join(USER_DATA_DIR, f"{me.id}_{name}")

        ADMINS_FILE = get_user_file("admins.json")
        NOTES_FILE = get_user_file("notes.json")
        BANNER_FILE = get_user_file("banner.txt")
        COMMON_SPAM_FILE = get_user_file("common_spam_texts.json")
        AUTO_REPLY_FILE = get_user_file("autoreply.txt")
        FILTERS_FILE = get_user_file("filters.json")
        SANGMATA_DIR = os.path.join(USER_DATA_DIR, "sangmata")
        os.makedirs(SANGMATA_DIR, exist_ok=True)

        # ─── STATE VARIABLES ──────────────────────────────────────────────────
        user_bot.admins = set()
        user_bot.muted_users = set()
        user_bot.global_muted = set()
        user_bot.reply_users = set()
        user_bot.rr_users = set()
        user_bot.flag_users = set()
        user_bot.hrr_users = set()
        user_bot.replygod_users = set()
        user_bot.custom_raid_users = {}
        user_bot.group_locks = set()
        user_bot.spray_tasks = {}
        user_bot.notes = {}
        user_bot.spam_texts = []
        user_bot.menu_banner_msg = None
        user_bot.auto_react_emoji = None
        user_bot.antidel_enabled = False
        user_bot.antidel_cache = {}
        user_bot.watch_spam = {}
        user_bot.CLONE_ACTIVE = False
        user_bot.LAST_CLONE_ID = None
        user_bot.CLONE_DATA = {
            "name": None, "last": None, "bio": None, "photo_bytes": None
        }
        user_bot.SPRAY_DELAY = 0.1
        user_bot.GC_FAST_EMOJIS = [
            "❤️","🧡","💛","💚","💙","💜",
            "🖤","🤍","🤎","🩷","🩵","🩶",
            "💖","💘","💝","💗","💓","💞",
            "💕","💟","❣️","❤️‍🔥","❤️‍🩹"
        ]
        user_bot.ADD_BOTS_LIST = [
            "@Soulreaper99_bot", "@Soulreaper98_bot", "@Soulreaper97_bot",
            "@Soulreaper96_bot", "@Soulreaper95_bot", "@Soulreaper94_bot",
            "@Soulreaper93_bot", "@Soulreapernc1_bot", "@Soulreapernc2_bot",
            "@Soulreapernc3_bot", "@Asurfighter12bot",
        ]
        user_bot.START_TIME = time.time()
        user_bot.react_targets = {}
        user_bot.shayari_raid = {}
        user_bot.rizz_raid = {}
        user_bot.reply_cooldowns = {}
        user_bot.pickup_users = set()
        user_bot.romance_users = set()
        user_bot.trollraid_users = set()
        user_bot.ragebait_users = set()
        user_bot.roastraid_users = set()
        user_bot.pickup_raid = {}
        user_bot.romance_raid = {}
        user_bot.troll_raid = {}
        user_bot.ragebait_raid = {}
        user_bot.roast_raid = {}
        user_bot.attackraid_users = set()
        user_bot.warraid_users = set()
        user_bot.savageraid_users = set()
        user_bot.ultraraid_users = set()
        user_bot.attack_raid = {}
        user_bot.war_raid = {}
        user_bot.savage_raid = {}
        user_bot.ultra_raid = {}
        user_bot.shame_users = set()
        user_bot.diss_users = set()
        user_bot.devil_users = set()
        user_bot.karma_users = set()
        user_bot.doom_users = set()
        user_bot.shame_raid = {}
        user_bot.diss_raid = {}
        user_bot.devil_raid = {}
        user_bot.karma_raid = {}
        user_bot.doom_raid = {}
        user_bot.pwr_users = set()
        user_bot.pwr_raid = {}
        user_bot.pwr_index = {}
        user_bot.ows_users = set()
        user_bot.ows_spam = {}
        user_bot.ows_index = {}
        user_bot.premium_raids = {
            "mr": [], "mr2": [], "br": [], "br2": [], "br3": [],
            "sqr": [], "sq2": [], "cr": [], "bar": [], "gr": []
        }
        user_bot.premium_spams = {
            "ms": [], "ms2": [], "bs": [], "bs2": [], "bs3": [],
            "sqs": [], "sqs2": [], "cs": [], "bas": [], "gs": []
        }
        user_bot.premium_raid_targets = {}
        user_bot.premium_spam_targets = {}
        user_bot.NC_STATE = {
            "active": False,
            "task": None,
            "lang": None,
            "text": None,
            "chat_id": None,
        }
                # ─── NC PATTERNS ────────────────────────────────────────────────────
        HINDINC_PATTERNS = [
            "{text} चुडाकड़ ⊹ ࣪ ﹏𓊝﹏𓂁﹏⊹ ࣪ ˖",
            "{text} रैंडी ˖ ࣪ ꉂ🗯˙🫐⃟.꩜‹—",
            "{text} गरीब ⊹ ࣪ ﹏𓊝﹏𓂁﹏⊹ ࣪ ˖",
            "{text} चमार˖ ࣪ ꉂ🗯˙🫐⃟.꩜‹—",
            "{text} भेंगे⊹ ࣪ ﹏𓊝﹏𓂁﹏⊹ ࣪ ˖",
            "{text} रैंडी के बच्चे˖ ࣪ ꉂ🗯˙🫐⃟.꩜‹—",
            "{text} गुलाम⊹ ࣪ ﹏𓊝﹏𓂁﹏⊹ ࣪ ˖",
            "{text} गुलामी कर˖ ࣪ ꉂ🗯˙🫐⃟.꩜‹—",
            "{text} चुदाई केंद्र⊹ ࣪ ﹏𓊝﹏𓂁﹏⊹ ࣪ ˖",
            "{text} नांगा नाच कर˖ ࣪ ꉂ🗯˙🫐⃟.꩜‹—",
            "{text} पापा बोल Mere को⊹ ࣪ ﹏𓊝﹏𓂁﹏⊹ ࣪ ˖",
            "{text} तेरी मां नंगी करू˖ ࣪ ꉂ🗯˙🫐⃟.꩜‹—",
            "{text} छक्के⊹ ࣪ ﹏𓊝﹏𓂁﹏⊹ ࣪ ˖",
            "{text} भोसड़ी के˖ ࣪ ꉂ🗯˙🫐⃟.꩜‹—",
        ]

        URDU_PATTERNS = [
            "{text} ٹی ایم کے بی࣪ ִֶָ☾.ִ ࣪𖤐࣪ ִֶָ☾.ִ ࣪𖤐",
            "{text} ٹی ایم کے سی𓍢ִႋ🌷͙֒ᰔᩚ",
            "{text} تیری ماں رندی࣪ ִֶָ☾.ִ ࣪𖤐࣪ ִֶָ☾.ִ ࣪𖤐",
            "{text} چوداکڑ 𓍢ִႋ🌷͙֒ᰔᩚ",
            "{text} گلام ࣪ ִֶָ☾.ִ ࣪𖤐࣪ ִֶָ☾.ִ ࣪𖤐",
            "{text} رنڈی𓍢ִႋ🌷͙֒ᰔᩚ",
            "{text} تیری ماں چھوڑ کر فیک دو ࣪ ִֶָ☾.ִ ࣪𖤐࣪ ִֶָ☾.ִ ࣪𖤐",
            "{text} گلامی کے آر𓍢ִႋ🌷͙֒ᰔᩚ",
            "{text} عجیب کو باپ بول࣪ ִֶָ☾.ִ ࣪𖤐࣪ ִֶָ☾.ִ ࣪𖤐",
            "{text} رنڈی پوترا 𓍢ִႋ🌷͙֒ᰔᩚ",
            "{text} چکے ִ ࣪𖤐࣪ ִֶָ☾.ִ ࣪𖤐࣪ ִֶָ☾.",
            "{text} بی ٹی ایس کے لنڈ 𓍢ִႋ🌷͙֒ᰔᩚ",
        ]

        BENGALI_PATTERNS = [
            "{text} শালা °❀.ೃ࿔*ꫂ❁",
            "{text} এলোমেলো ꫂ❁°❀.ೃ࿔*",
            "{text} গরিবꫂ❁°❀.ೃ࿔*",
            "{text} ককার ꫂ❁°❀.ೃ࿔*",
            "{text} প্রজাতিꫂ❁°❀.ೃ࿔*",
            "{text} এক এলোমেলোর সন্তানꫂ❁°❀.ೃ࿔*",
            "{text} দাসꫂ❁°❀.ೃ࿔*",
            "{text} শালা কেন্দ্রꫂ❁°❀.ೃ࿔*",
            "{text} নগ্নꫂ❁°❀.ೃ࿔*",
            "{text} বাবা, আমাকে বল, আমি ꫂ❁°❀.ೃ࿔*",
            "{text} তোর মাকে বিবস্ত্র করব।ꫂ❁°❀.ೃ࿔*",
            "{text} সিক্সার্সꫂ❁°❀.ೃ࿔*",
            "{text} তুই হারামজাদাꫂ❁°❀.ೃ࿔*",
        ]

        BIHARI_PATTERNS = [
            "{text} भोसड़ी के बा⋆꙳^̩̩͙❅*̩̩͙‧͙ ‧͙*̩̩͙❆ ͙͛ ˚₊⋆",
            "{text} सतमेरवनी₊˚ʚ ᗢ₊˚✧ ﾟ.",
            "{text} गरीब⋆꙳^̩̩͙❅*̩̩͙‧͙ ‧͙*̩̩͙❆ ͙͛ ˚₊⋆",
            "{text} कॉकर के ह₊˚ʚ ᗢ₊˚✧ ﾟ.",
            "{text} नसल⋆꙳^̩̩͙❅*̩̩͙‧͙ ‧͙*̩̩͙❆ ͙͛ ˚₊⋆",
            "{text} एगो बेतरतीब के लइका₊˚ʚ ᗢ₊˚✧ ﾟ.",
            "{text} गुलाम⋆꙳^̩̩͙❅*̩̩͙‧͙ ‧͙*̩̩͙❆ ͙͛ ˚₊⋆",
            "{text} कमबख्त सेंटर के बा₊˚ʚ ᗢ₊˚✧ ﾟ.",
            "{text} नंगा हो गइल बा⋆꙳^̩̩͙❅*̩̩͙‧͙ ‧͙*̩̩͙❆ ͙͛ ˚₊⋆",
            "{text} पापा बताव हम तोहार माई के {text} उतार देब।₊˚ʚ ᗢ₊˚✧ ﾟ.",
            "{text} छक्का के लोग⋆꙳^̩̩͙❅*̩̩͙‧͙ ‧͙*̩̩͙❆ ͙͛ ˚₊⋆",
            "{text} रे हरामी₊˚ʚ ᗢ₊˚✧ ﾟ.",
        ]

        ENGLISH_PATTERNS = [
            "{text} 🅱🅻🅾🅾🅳🆈 🅷🅴🅻🅻.𖥔 ݁ ˖ִ🛸༄˖°.",
            "{text} 🅼🅾🆃🅷🅴🆁🅵🆄🅲🅺🅴🆁🌊⋆｡ 𖦹°.🐚⋆❀˖°🫧",
            "{text} 🅱🅸🆃🅲🅷 🆂🅾🅽.𖥔 ݁ ˖ִ🛸༄˖°.",
            "{text} 🆂🅻🅰🆅🅴🌊⋆｡ 𖦹°.🐚⋆❀˖°🫧",
            "{text} 🆂🅾🅽 🅾🅵 🅼🅸🅰 🅺🅷🅰🅻🅸🅵🅰 .𖥔 ݁ ˖ִ🛸༄˖°.",
            "{text} 🆂🅰🆈 🅵🆁🅴🅰🅺🆈 🅳🅰🅳🅳🆈🌊⋆｡ 𖦹°.🐚⋆❀˖°🫧",
            "{text} 🅵🆄🅲🅺🄽🄶 🅲🅴🅽🆃🆁🅴.𖥔 ݁ ˖ִ🛸༄˖°.",
            "{text} 🆂🅾🅽 🅵🆄🅲🅺🅴🅳 🅼🅾🅼🌊⋆｡ 𖦹°.🐚⋆❀˖°🫧",
        ]

        EMOJI_NC_EMOJIS = ["🐧","🦭","🦈","🫍","🐬","🐋","🐳","🐟","🐠","🐡","🦐","🦞","🦀","🦑","🐙","🪼","🦪","🪸","🫧","🦂"]
        EMOJI_NC_PATTERN = "{text} <⋆.ೃ࿔*:･{emoji}⋆.ೃ࿔*:･>" 
       
        # ─── TEXT LISTS ──────────────────────────────────────────────────────
        # ─── PREMIUM RAID TEXT LISTS ──────────────────────────────────────────
        mr_texts = [
        "TTTTTTT🍷EEEEEE💊RRRRR🔘OOOOO🎲BBBBB🤍EEEEEE💊GGGGGG🖤EEEEEE💊JJJJJJ👅 CCCCCC⚔️OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 CCCCCC⚔️OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE💊OOOOO🎲 AAAAAA👿AAAAAA👿AAAAAA👿MMMMM🚀MMMMM🚀AAAAAA👿 CCCCCC⚔️OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘OOOOO🎲 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 LLLLLL🔨AAAAAA👿 BBBBB🤍UUUUU💣RRRRR🔘",
        "OOOOOO👅YYYYYYEEEEEE💊 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 KKKKKK💜EEEEEE💊 BBBBB🤍AAAAAA👿CCCCCC⚔️CCCCCC⚔️EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜 BBBBB🤍JJJJJJ👅OOOOO🎲SSSSS⚒️RRRRR🔘WWWWW🥰",
        "TTTTTTT🍷EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜 FFFFFF🔥AAAAAA👿NNNNNN🤣RRRRR🔘",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀UUUUU💣MMMMM🚀MMMMM🚀YYYYYY",
        "RRRRRR⚔️AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷RRRRR🔘",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿KKKKKK💜IIIIII🍷 GGGGGG🖤EEEEEE💊TTTTT🚭IIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜EEEEEE💊 MMMMM🚀UUUUU💣HHHHH🖤",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜OOOOO🎲 GGGGGG🖤AAAAAA👿NNNNNN🤣DDDDD👿",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 CCCCCC⚔️HHHHH🖤IIIIII🍷NNNNNN🤣AAAAAA👿LLLLLL🔨",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 MMMMM🚀AAAAAA👿RRRRR🔘 GGGGGG🖤AAAAAA👿YYYYYYIIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀UUUUU💣TTTTT🚭IIIIII🍷 RRRRR🔘AAAAAA👿DDDDD👿IIIIII🍷 KKKKKK💜IIIIII🍷 HHHHH🖤EEEEEE💊TTTTT🚭",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 CCCCCC⚔️OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿IIIIII🍷YYYYYYAAAAAA👿 CCCCCC⚔️IIIIII🍷OOOOO🎲DDDDD👿AAAAAA👿 AAAAAA👿AAAAAA👿AAAAAA👿AAAAAA👿KKKKKK💜 MMMMM🚀",
        "OOOOOO👅YYYYYYEEEEEE💊 KKKKKK💜IIIIII🍷NNNNNN🤣NNNNNN🤣AAAAAA👿RRRRR🔘 KKKKKK💜EEEEEE💊 BBBBB🤍AAAAAA??CCCCCC⚔️CCCCCC⚔️GGGGGG🖤EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII?? MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜AAAAAA👿 BBBBB🤍IIIIII🍷OOOOO🎲AAAAAA👿RRRRR🔘SSSSS⚒️",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜OOOOO🎲 GGGGGG🖤AAAAAA👿NNNNNN🤣DDDDD👿 MMMMM🚀AAAAAA👿RRRRR🔘AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿OOOOO🎲UUUUU💣AAAAAA👿 JJJJJJ👅AAAAAA👿AAAAAA👿NNNNNN🤣 CCCCCC⚔️JJJJJJ👅OOOOO🎲DDDDD👿YYYYYYAAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜EEEEEE💊 BBBBB🤍HHHHH🖤OOOOO🎲AAAAAA👿DDDDD👿AAAAAA👿 CCCCCC⚔️OOOOO🎲DDDDD👿AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜OOOOO🎲 CCCCCC⚔️HHHHH🖤UUUUU💣TTTTT??EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿.    KKKKKK📌AAAAAA👿AAAAAA👿 BBBBB🤍HHHHH🖤OOOOO🎲SSSSS⚒️DDDDD👿AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍RRRRR🔘HHHHH🖤EEEEEE💊NNNNNN🤣 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀UUUUU💣MMMMM🚀MMMMM🚀YYYYYY KKKKKK💜UUUUU💣TTTTT🚭IIIIII🍷YYYYYYAAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍AAAAAA👿HHHHH🖤IIIIII🍷 KKKKKK💜AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜AAAAAA👿 BBBBB🤍UUUUU💣RRRRR🔘",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 CCCCCC⚔️GGGGGG🖤OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿IIIIII🍷YYYYYYAAAAAA👿 CCCCCC⚔️GGGGGG🖤OOOOO🎲DDDDD👿UUUUU💣",
        "OOOOOO??YYYYYYEEEEEE💊 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 KKKKKK💜EEEEEE💊 BBBBB🤍AAAAAA👿CCCCCC⚔️CCCCCC⚔️HHHHH🖤EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜IIIIII🍷 CCCCCC⚔️HHHHH🖤UUUUU💣CCCCCC⚔️HHHHH🖤OOOOO🎲 KKKKKK💜AAAAAA👿TTTTT🚭YYYYYY",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍AAAAAA👿HHHHH🖤IIIIII🍷 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿IIIIII🍷YYYYYYAAAAAA👿 CCCCCC⚔️GGGGGG🖤OOOOO🎲DDDDD👿YYYYYY",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀UUUUU💣MMMMM🚀MMMMM🚀YYYYYY RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀UUUUU💣MMMMM🚀YYYYYY CCCCCC⚔️HHHHH🖤OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍AAAAAA👿JJJJJJ👅IIIIII🍷 CCCCCC⚔️HHHHH🖤OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 KKKKKK💜IIIIII🍷 LLLLLL🔨AAAAAA👿DDDDD👿KKKKKK💜IIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿IIIIII🍷YYYYYYAAAAAA👿 JJJJJJ👅AAAAAA👿AAAAAA👿NNNNNN🤣 CCCCCC⚔️HHHHH🖤OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE??RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜AAAAAA👿 BBBBB🤍UUUUU💣RRRRR🔘 FFFFFF🔥AAAAAA👿DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 BBBBB🤍AAAAAA👿NNNNNN🤣AAAAAA👿 DDDDD👿UUUUU💣NNNNNN🤣GGGGGG🖤AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 CCCCCC⚔️HHHHH🖤OOOOO🎲DDDDD👿KKKKKK💜EEEEEE💊 FFFFFF🔥EEEEEE💊KKKKKK💜UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜EEEEEE💊 MMMMM🚀UUUUU💣HHHHH🖤 MMMMM🚀EEEEEE💊IIIIII🍷 PPPPPP📌AAAAAA👿KKKKKK💜IIIIII🍷SSSSS⚒️TTTTT🚭AAAAAA👿NNNNNN🤣IIIIII🍷 LLLLLL🔨AAAAAA👿VVVVDDDDD👿AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 PPPPPP📌KKKKKK💜AAAAAA👿OOOOO🎲SSSSS⚒️TTTTT🚭AAAAAA👿NNNNNN🤣IIIIII🍷 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷",
        "RRRRRR⚔️AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 KKKKKK💜EEEEEE💊 BBBBB🤍EEEEEE💊TTTTT🚭",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘UUUUU💣 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜AAAAAA👿 BBBBB🤍UUUUU💣TTTTT🚭",
        "OOOOOO👅YYYYYYEEEEEE💊 TTTTT🚭AAAAAA👿TTTTT🚭TTTTT🚭TTTTT🚭EEEEEE💊 UUUUU💣TTTTT🚭HHHHH🖤",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 CCCCCC⚔️HHHHH🖤UUUUU💣DDDDD👿VVVVAAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀UUUUU💣MMMMM🚀MMMMM🚀YYYYYY CCCCCC⚔️HHHHH🖤UUUUU💣DDDDD👿VVVVAAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 CCCCCC⚔️UUUUU💣UUUUU💣DDDDD👿VVVVAAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿IIIIII🍷YYYYYYAAAAAA👿 KKKKKK💜AAAAAA👿 BBBBB🤍HHHHH🖤OOOOO🎲SSSSS⚒️DDDDD👿AAAAAA👿 DDDDD👿EEEEEE💊DDDDD👿EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘OOOOO🎲 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 KKKKKK💜OOOOO🎲 GGGGGG🖤AAAAAA👿NNNNNN🤣DDDDD👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 KKKKKK💜EEEEEE💊 BBBBB🤍HHHHH🖤OOOOO🎲SSSSS⚒️DDDDD👿EEEEEE💊 PPPPPP📌EEEEEE💊 LLLLLL🔨OOOOO🎲LLLLLL🔨LLLLLL🔨AAAAAA👿",
        "LLLLLLL🎲OOOOO🎲LLLLLL🔨LLLLLL🔨EEEEEE💊 HHHHH🖤OOOOO🎲 LLLLLL🔨OOOOO🎲LLLLLL🔨LLLLLL🔨EEEEEE💊 TTTTT🚭EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜OOOOO🎲 GGGGGG🖤AAAAAA👿NNNNNN🤣DDDDD👿 PPPPPP📌EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 DDDDD👿EEEEEE💊 MMMMM🚀UUUUU💣JJJJJJ👅GGGGGG🖤EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀UUUUU💣MMMMM🚀YYYYYY CCCCCC⚔️HHHHH🖤UUUUU💣DDDDD👿AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜 BBBBB🤍UUUUU💣RRRRR🔘 CCCCCC⚔️HHHHH🖤UUUUU💣DDDDD👿VVVVAAAAAA👿",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 VVVVEEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 CCCCCC⚔️HHHHH🖤UUUUU💣DDDDD👿VVVVAAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 AAAAAA👿MMMMM🚀MMMMM🚀AAAAAA👿 CCCCCC⚔️HHHHH🖤UUUUU💣DDDDD👿VVVVAAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜IIIIII🍷 FFFFFF🔥AAAAAA👿BBBBB🤍DDDDD👿 MMMMM🚀AAAAAA👿RRRRR🔘VVVVAAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜AAAAAA👿 BBBBB🤍UUUUU💣RRRRR🔘  MMMMM🚀AAAAAA👿RRRRR🔘VVVVAAAAAA👿",
        "IIIIIIII⚒️DDDDD👿GGGGGG🖤AAAAAA👿RRRRR🔘 AAAAAA👿JJJJJJ👅AAAAAA👿AAAAAA👿 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 KKKKKK💜AAAAAA👿 LLLLLL🔨AAAAAA👿DDDDD👿KKKKKK💜AAAAAA👿",
        "IIIIIIII⚒️DDDDD👿HHHHH🖤AAAAAA👿 TTTTT🚭EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜AAAAAA👿 BBBBB🤍HHHHH🖤OOOOO🎲SSSSS⚒️DDDDD👿AAAAAA👿 DDDDD👿EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜IIIIII🍷 GGGGGG🖤AAAAAA👿NNNNNN🤣DDDDD👿 DDDDD👿EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 HHHHH🖤AAAAAA👿IIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜YYYYYYTTTTT🚭TTTTT🚭OOOOO🎲 HHHHH🖤AAAAAA👿IIIIII🍷",
        "YYYYYY🤍EEEEEE💊 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 KKKKKK💜EEEEEE💊 BBBBB🤍AAAAAA👿CCCCCC⚔️CCCCCC⚔️HHHHH🖤EEEEEE💊",
        "MMMMM💥AAAAAA👿RRRRR🔘 GGGGGG🖤AAAAAA👿YYYYYYAAAAAA👿 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 KKKKKK💜EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜AAAAAA👿 BBBBB🤍HHHHH🖤OOOOO🎲SSSSS⚒️DDDDD👿 AAAAAA👿 DDDDD👿EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊. KKKKKK📌 PPPPPP📌EEEEEE💊LLLLLL🔨UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜OOOOO🎲 LLLLLL🔨EEEEEE💊UUUUU💣 LLLLLL🔨UUUUU💣NNNNNN🤣DDDDD👿 PPPPPP📌EEEEEE💊 AAAAAA👿PPPPPP📌NNNNNN🤣EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜IIIIII🍷 GGGGGG🖤AAAAAA👿NNNNNN🤣DDDDD👿 MMMMM🚀AAAAAA👿RRRRR🔘AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿 KKKKKK💜AAAAAA👿 BBBBB🤍HHHHH🖤OOOOO🎲SSSSS⚒️DDDDD👿AAAAAA👿 MMMMM🚀AAAAAA👿RRRRR🔘AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍AAAAAA👿JJJJJJ👅IIIIII🍷 CCCCCC⚔️HHHHH🖤OOOOO🎲DDDDD👿AAAAAA👿",
        "OOOOOO👅YYYYYYEEEEEE💊 TTTTT🚭AAAAAA👿TTTTT🚭TTTTT🚭EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 AAAAAA👿CCCCCC⚔️UUUUU💣DDDDD👿AAAAAA👿. AAAAAA👿BBBBB🤍",
        "MMMMM💥AAAAAA👿RRRRR🔘NNNNNN??AAAAAA👿 MMMMM🚀AAAAAA👿NNNNNN🤣AAAAAA👿 HHHHH🖤AAAAAA👿IIIIII🍷 RRRRR🔘AAAAAA👿 DDDDD👿IIIIII🍷 KKKKKK💜EEEEEE💊",
        "MMMMM💥AAAAAA👿RRRRR🔘 MMMMM🚀AAAAAA👿RRRRR🔘 KKKKKK💜EEEEEE💊 LLLLLL🔨IIIIII🍷MMMMM🚀HHHHH🖤EEEEEE💊AAAAAA👿 TTTTT🚭EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 CCCCCC⚔️HHHHH🖤OOOOO🎲DDDDD👿HHHHH🖤",
        "OOOOOO👅YYYYYYEEEEEE💊 KKKKKK💜IIIIII🍷NNNNNN🤣AAAAAA👿AAAAAA👿RRRRR🔘 KKKKKK💜EEEEEE💊 BBBBB🤍AAAAAA??CCCCCC⚔️CCCCCC⚔️HHHHH🖤EEEEEE💊 UUUUU💣TTTTT🚭HHHHH🖤",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 CCCCCC⚔️HHHHH🖤UUUUU💣DDDDD👿VVVVAAAAAA👿 OOOOO🎲YYYYYYEEEEEE💊 TTTTT🚭AAAAAA👿TTTTT🚭TTTTT🚭EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊 CCCCCC⚔️BBBBB🤍UUUUU💣DDDDD👿VVVVAAAAAA👿 LLLLLL🔨EEEEEE💊",
        "GGGGGG🌿EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜IIIIII🍷 FFFFFF🔥AAAAAA👿NNNNNN🤣DDDDD👿 OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍AAAAAA👿JJJJJJ👅IIIIII🍷 KKKKKK💜AAAAAA👿AAAAAA👿AAAAAA👿 BBBBB🤍UUUUU💣RRRRR🔘 TTTTT🚭OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷AAAAAA👿TTTTT🚭TTTTT🚭TTTTT🚭EEEEEE💊 TTTTT🚭EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜EEEEEE💊 MMMMM🚀UUUUU💣HHHHH🖤 PPPPPP📌EEEEEE💊 LLLLLL🔨OOOOO🎲DDDDD👿AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜IIIIII🍷 GGGGGG🖤AAAAAA👿NNNNNN🤣DDDDD👿 PPPPPP📌EEEEEE💊 LLLLLL🔨OOOOO🎲DDDDD👿AAAAAA👿",
        "OOOOOO👅YYYYYYEEEEEE💊 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 SSSSS⚒️AAAAAA👿MMMMM🚀JJJJJJ👿 WWWWW??AAAAAA👿LLLLLL🔨EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜IIIIII🍷.GGGGGG🖤AAAAAA👿 DDDDD👿 SSSSS⚒️AAAAAA👿MMMMM🚀BBBBB🤍HHHHH🖤AAAAAA👿LLLLLL🔨AAAAAA👿 KKKKKK💜EEEEEE💊 CCCCCC⚔️HHHHH🖤OOOOO🎲DDDDD👿UUUUU💣",
        "RRRRRR⚔️AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 IIIIII🍷EEEEEE💊 BBBBB🤍EEEEEE💊YYYYYY",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 GGGGGG🖤AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 CCCCCC⚔️HHHHH🖤UUUUU💣TTTTT🚭EEEEEE💊 WWWWW🥰AAAAAA👿LLLLLL🔨IIIIII🍷 RRRRR🔘AAAAAA👿 DDDDD👿IIIIII🍷",
        "MMMMM💥AAAAAA👿AAAAAA👿AAAAAA👿AAAAAA👿AAAAAA👿AAAAAA👿",
        "KKKKKK📌WWWWW🥰EEEEEE💊EEEEEE💊EEEEEE💊 BBBBB🤍HHHHH🖤OOOOO🎲SSSSS⚒️DDDDD👿EEEEEE💊 DDDDD👿EEEEEE💊",
        "OOOOOO👅YYYYYYEEEEEE💊 BBBBB🤍HHHHH🖤AAAAAA👿NNNNNN🤣GGGGGG🖤IIIIII🍷 TTTTT🚭AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 KKKKKK💜EEEEEE💊",
        "RRRRRR⚔️AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 KKKKKK💜EEEEEE💊 BBBBB🤍AAAAAA👿CCCCCC⚔️CCCCCC⚔️HHHHH🖤EEEEEE💊",
        "KKKKKK📌IIIIII🍷NNNNNN🤣NNNNNN🤣AAAAAA👿RRRRR🔘 KKKKKK💜EEEEEE💊 BBBBB🤍AAAAAA👿CCCCCC⚔️CCCCCC⚔️HHHHH🖤EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 NNNNNN🤣AAAAAA👿 CCCCCC⚔️HHHHH🖤UUUUU💣DDDDD👿BBBBB🤍YYYYYYEEEEEE💊GGGGGG🖤AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 BBBBB🤍AAAAAA👿JJJJJJ👅IIIIII🍷 KKKKKK💜AAAAAA👿AAAAAA👿AAAAAA👿 BBBBB🤍HHHHH🖤OOOOO🎲SSSSS⚒️DDDDD👿SSSSS⚒️ DDDDD👿EEEEEE💊DDDDD👿EEEEEE💊",
        "AAAAAA👿BBBBB🤍 CCCCCC⚔️HHHHH🖤AAAAAA??LLLLLL🔨 LLLLLL🔨UUUUU💣NNNNNN🤣DDDDD👿 KKKKKK💜EEEEEE💊 CCCCCC⚔️HHHHH🖤UUUUU💣PPPPPP📌PPPPPP📌EEEEEE💊 KKKKKK💜AAAAAA👿RRRRR🔘",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 BBBBB🤍AAAAAA👿JJJJJJ👅IIIIII🍷 CCCCCC⚔️HHHHH🖤OOOOO🎲DDDDD👿UUUUU💣 OOOOO🎲YYYYYYEEEEEE💊"
        ]



            
        mr2_texts = [
        "B⃠a⃠a⃠p⃠ b⃠h⃠i⃠ b⃠n⃠a⃠l⃠e⃠ m⃠u⃠j⃠e⃠ r⃠n⃠d⃠i⃠k⃠e⃠",
        "T⃠e⃠r⃠a⃠ b⃠a⃠a⃠p⃠ r⃠a⃠n⃠d⃠i⃠b⃠a⃠a⃠z⃠ e⃠y⃠ y⃠a⃠a⃠d⃠ e⃠y⃠ t⃠u⃠j⃠h⃠e⃠",
        "T⃠u⃠ a⃠p⃠n⃠i⃠ M⃠a⃠a⃠ c⃠u⃠d⃠a⃠ n⃠a⃠ t⃠y⃠m⃠p⃠a⃠s⃠s⃠",
        "O⃠y⃠e⃠ u⃠n⃠f⃠u⃠n⃠n⃠y⃠ s⃠w⃠i⃠p⃠e⃠ m⃠t⃠t⃠ k⃠r⃠",
        "O⃠h⃠ h⃠e⃠l⃠l⃠o⃠ b⃠i⃠h⃠a⃠r⃠i⃠ t⃠e⃠r⃠a⃠ b⃠a⃠a⃠p⃠ b⃠i⃠h⃠a⃠r⃠i⃠ o⃠r⃠ t⃠u⃠ v⃠ b⃠i⃠h⃠a⃠r⃠i⃠ a⃠a⃠u⃠k⃠a⃠t⃠ m⃠e⃠ r⃠h⃠a⃠ k⃠r⃠.",
        "O⃠y⃠y⃠ k⃠i⃠n⃠n⃠e⃠r⃠ t⃠u⃠j⃠h⃠e⃠ g⃠c⃠ m⃠e⃠ a⃠a⃠n⃠e⃠ k⃠i⃠ p⃠e⃠r⃠m⃠i⃠s⃠s⃠i⃠o⃠n⃠ k⃠i⃠s⃠n⃠e⃠ d⃠i⃠.",
        "C⃠u⃠d⃠k⃠e⃠ d⃠i⃠k⃠h⃠a⃠",
        "C⃠u⃠d⃠k⃠e⃠ d⃠i⃠k⃠h⃠a⃠ e⃠k⃠ b⃠a⃠a⃠r⃠.",
        "S⃠u⃠n⃠ s⃠u⃠n⃠ m⃠a⃠ c⃠u⃠d⃠a⃠.",
        "T⃠e⃠r⃠i⃠ m⃠a⃠c⃠a⃠ b⃠h⃠o⃠s⃠d⃠a⃠.",
        "O⃠y⃠e⃠ c⃠h⃠o⃠t⃠i⃠ j⃠a⃠t⃠i⃠ k⃠e⃠ t⃠m⃠r⃠.",
        "K⃠y⃠? j⃠l⃠d⃠i⃠ l⃠i⃠k⃠h⃠ k⃠i⃠d⃠d⃠e⃠.",
        "B⃠i⃠h⃠a⃠r⃠i⃠ c⃠o⃠m⃠ g⃠a⃠n⃠g⃠ k⃠e⃠ b⃠a⃠a⃠p⃠ k⃠o⃠ t⃠a⃠g⃠ c⃠r⃠e⃠g⃠a⃠ t⃠u⃠",
        "M⃠u⃠j⃠h⃠e⃠ c⃠y⃠a⃠ t⃠u⃠ b⃠i⃠h⃠a⃠r⃠i⃠ e⃠y⃠ t⃠m⃠k⃠c⃠ b⃠s⃠",
        "J⃠a⃠l⃠d⃠i⃠ s⃠e⃠ r⃠a⃠n⃠d⃠i⃠b⃠a⃠a⃠z⃠ p⃠a⃠p⃠a⃠ b⃠o⃠l⃠",
        "S⃠i⃠d⃠e⃠ h⃠o⃠j⃠a⃠ b⃠i⃠h⃠a⃠r⃠i⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ a⃠b⃠",
        "H⃠y⃠e⃠ p⃠g⃠l⃠ b⃠h⃠g⃠ m⃠a⃠t⃠ a⃠c⃠h⃠e⃠ s⃠e⃠ c⃠u⃠d⃠",
        "b⃠h⃠g⃠ n⃠y⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ t⃠u⃠ a⃠j⃠j⃠",
        "H⃠y⃠e⃠ p⃠g⃠l⃠ k⃠e⃠ b⃠c⃠h⃠e⃠ b⃠h⃠a⃠g⃠ m⃠a⃠t⃠",
        "H⃠y⃠e⃠ d⃠u⃠r⃠ h⃠a⃠t⃠t⃠ m⃠a⃠d⃠h⃠c⃠h⃠o⃠d⃠ k⃠e⃠ b⃠a⃠c⃠h⃠e⃠",
        "k⃠o⃠i⃠ b⃠a⃠t⃠ n⃠y⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠ e⃠s⃠l⃠i⃠y⃠e⃠ m⃠a⃠f⃠ c⃠r⃠ r⃠h⃠a⃠ h⃠u⃠ t⃠u⃠j⃠h⃠e⃠",
        "k⃠o⃠i⃠ b⃠a⃠a⃠t⃠ n⃠y⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠w⃠a⃠ a⃠p⃠n⃠i⃠ t⃠u⃠ m⃠a⃠f⃠i⃠ d⃠e⃠ d⃠u⃠n⃠g⃠a⃠",
        "A⃠c⃠h⃠e⃠ s⃠e⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠w⃠a⃠ a⃠p⃠n⃠i⃠ t⃠u⃠ m⃠a⃠f⃠i⃠ m⃠i⃠l⃠ j⃠a⃠y⃠e⃠g⃠i⃠ t⃠u⃠j⃠h⃠e⃠",
        "a⃠p⃠n⃠i⃠ m⃠a⃠ m⃠a⃠t⃠ c⃠h⃠u⃠d⃠a⃠ m⃠u⃠j⃠e⃠ s⃠w⃠i⃠p⃠e⃠ c⃠r⃠k⃠e⃠",
        "A⃠c⃠h⃠e⃠ s⃠e⃠ a⃠p⃠n⃠i⃠ m⃠a⃠ c⃠u⃠d⃠w⃠a⃠ t⃠u⃠ s⃠w⃠i⃠p⃠e⃠ c⃠r⃠k⃠e⃠",
        "F⃠r⃠ b⃠o⃠l⃠n⃠a⃠ n⃠a⃠ k⃠i⃠ c⃠u⃠d⃠w⃠a⃠ l⃠e⃠ a⃠p⃠n⃠i⃠ m⃠a⃠ s⃠w⃠i⃠p⃠e⃠ c⃠r⃠k⃠e⃠",
        "C⃠y⃠a⃠ h⃠u⃠a⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠y⃠i⃠ t⃠e⃠r⃠y⃠",
        "p⃠r⃠ k⃠e⃠s⃠e⃠ c⃠u⃠d⃠ g⃠y⃠i⃠ t⃠e⃠r⃠y⃠ m⃠a⃠",
        "m⃠u⃠j⃠h⃠e⃠ p⃠t⃠a⃠ t⃠h⃠a⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "m⃠e⃠y⃠ n⃠y⃠ m⃠a⃠n⃠t⃠a⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠y⃠i⃠ t⃠e⃠r⃠y⃠",
        "t⃠e⃠r⃠i⃠ m⃠a⃠ r⃠n⃠d⃠y⃠",
        "l⃠o⃠d⃠e⃠ s⃠e⃠ u⃠t⃠r⃠ m⃠c⃠",
        "l⃠u⃠n⃠ m⃠t⃠ c⃠h⃠u⃠s⃠ m⃠e⃠r⃠a⃠",
        "n⃠i⃠k⃠a⃠l⃠ m⃠a⃠d⃠a⃠r⃠c⃠h⃠d⃠",
        "c⃠h⃠u⃠p⃠ o⃠y⃠e⃠ g⃠a⃠s⃠h⃠t⃠i⃠ k⃠ b⃠a⃠c⃠h⃠e⃠",
        "m⃠a⃠k⃠i⃠c⃠h⃠u⃠t⃠ t⃠e⃠r⃠i⃠",
        "c⃠h⃠u⃠p⃠ r⃠n⃠d⃠y⃠k⃠e⃠",
        "m⃠a⃠ r⃠n⃠d⃠y⃠ t⃠e⃠r⃠i⃠",
        "t⃠e⃠r⃠i⃠ m⃠a⃠ k⃠ h⃠a⃠t⃠h⃠ t⃠o⃠d⃠h⃠ k⃠ t⃠e⃠r⃠e⃠ b⃠a⃠a⃠p⃠ k⃠ m⃠u⃠h⃠ m⃠e⃠ f⃠a⃠s⃠a⃠d⃠u⃠n⃠g⃠a⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠",
        "l⃠e⃠a⃠v⃠e⃠ l⃠e⃠ t⃠u⃠ r⃠n⃠d⃠y⃠k⃠e⃠ p⃠a⃠s⃠a⃠n⃠d⃠ n⃠a⃠i⃠ a⃠y⃠a⃠ m⃠e⃠k⃠o⃠",
        "l⃠e⃠a⃠v⃠e⃠ l⃠e⃠ t⃠u⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ i⃠d⃠e⃠r⃠ s⃠e⃠",
        "L⃠e⃠a⃠v⃠e⃠ l⃠e⃠ j⃠l⃠d⃠i⃠ s⃠e⃠ w⃠r⃠n⃠a⃠ m⃠a⃠ c⃠h⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "L⃠e⃠a⃠v⃠e⃠ n⃠y⃠ l⃠e⃠g⃠a⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ t⃠e⃠r⃠y⃠",
        "S⃠m⃠j⃠h⃠ b⃠a⃠t⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠ t⃠e⃠r⃠y⃠ l⃠e⃠a⃠v⃠e⃠ l⃠e⃠",
        "f⃠a⃠s⃠t⃠ l⃠e⃠a⃠v⃠e⃠ l⃠e⃠ k⃠a⃠m⃠j⃠o⃠r⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠",
        "t⃠u⃠t⃠o⃠ c⃠h⃠u⃠p⃠ r⃠n⃠d⃠y⃠k⃠",
        "o⃠y⃠ h⃠i⃠j⃠d⃠e⃠ k⃠h⃠a⃠n⃠a⃠ k⃠h⃠a⃠ k⃠e⃠ a⃠a⃠ k⃠a⃠m⃠z⃠o⃠r⃠",
        "t⃠e⃠r⃠i⃠ m⃠a⃠k⃠o⃠ i⃠l⃠y⃠ r⃠e⃠y⃠🌚😂",
        "c⃠h⃠u⃠p⃠ c⃠h⃠a⃠p⃠ c⃠h⃠u⃠d⃠ t⃠m⃠k⃠c⃠",
        "c⃠h⃠u⃠p⃠c⃠h⃠a⃠p⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠w⃠a⃠ a⃠p⃠n⃠i⃠ t⃠u⃠",
        "s⃠h⃠i⃠ s⃠e⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠w⃠a⃠ a⃠p⃠n⃠i⃠ t⃠u⃠ c⃠h⃠u⃠p⃠c⃠h⃠a⃠p⃠",
        "f⃠r⃠ s⃠e⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠w⃠a⃠ t⃠u⃠ a⃠p⃠n⃠i⃠ c⃠h⃠u⃠p⃠c⃠h⃠a⃠p⃠",
        "s⃠h⃠i⃠ s⃠e⃠ l⃠i⃠k⃠h⃠ w⃠r⃠n⃠a⃠ m⃠a⃠ c⃠h⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "m⃠a⃠ c⃠y⃠u⃠ c⃠h⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠ c⃠h⃠u⃠p⃠c⃠h⃠a⃠p⃠",
        "p⃠r⃠o⃠o⃠f⃠ c⃠r⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠ g⃠y⃠i⃠ t⃠e⃠r⃠y⃠",
        "p⃠r⃠o⃠o⃠f⃠ e⃠y⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠",
        "p⃠r⃠o⃠o⃠f⃠ h⃠o⃠ c⃠h⃠u⃠k⃠a⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ t⃠e⃠r⃠y⃠",
        "C⃠h⃠u⃠p⃠ c⃠h⃠i⃠l⃠l⃠a⃠r⃠",
        "c⃠h⃠u⃠p⃠ c⃠h⃠u⃠p⃠ m⃠a⃠a⃠ k⃠ b⃠o⃠s⃠d⃠a⃠ t⃠e⃠r⃠y⃠",
        "o⃠y⃠ h⃠i⃠j⃠d⃠e⃠ k⃠h⃠a⃠n⃠a⃠ k⃠h⃠a⃠ k⃠e⃠ a⃠a⃠ k⃠a⃠m⃠z⃠o⃠r⃠",
        "c⃠h⃠u⃠p⃠ m⃠a⃠d⃠a⃠r⃠c⃠h⃠o⃠d⃠ ?",
        "A⃠b⃠ t⃠k⃠ c⃠u⃠d⃠ g⃠y⃠i⃠ h⃠o⃠g⃠i⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ ?",
        "n⃠y⃠ n⃠y⃠ m⃠e⃠ k⃠u⃠c⃠h⃠ n⃠y⃠ j⃠a⃠n⃠t⃠a⃠ b⃠s⃠ t⃠e⃠r⃠i⃠ m⃠a⃠ r⃠n⃠d⃠y⃠ e⃠y⃠",
        "S⃠b⃠s⃠e⃠ p⃠h⃠e⃠l⃠e⃠ a⃠p⃠n⃠i⃠ m⃠a⃠a⃠ k⃠o⃠ b⃠o⃠l⃠ c⃠h⃠u⃠d⃠n⃠a⃠ k⃠a⃠a⃠m⃠ k⃠r⃠e⃠",
        "Y⃠a⃠h⃠a⃠ b⃠h⃠i⃠ c⃠h⃠u⃠d⃠a⃠ t⃠u⃠ r⃠n⃠d⃠y⃠c⃠e⃠ p⃠i⃠l⃠l⃠e⃠",
        "t⃠e⃠r⃠i⃠m⃠a⃠k⃠a⃠b⃠o⃠s⃠d⃠a⃠",
        "t⃠e⃠r⃠i⃠ t⃠o⃠ b⃠h⃠e⃠n⃠ c⃠u⃠d⃠e⃠g⃠i⃠",
        "c⃠h⃠u⃠p⃠ r⃠n⃠d⃠y⃠k⃠e⃠ t⃠o⃠m⃠m⃠y⃠",
        "n⃠i⃠k⃠a⃠l⃠ m⃠a⃠d⃠a⃠r⃠c⃠h⃠d⃠ c⃠u⃠d⃠k⃠e⃠ y⃠h⃠a⃠ s⃠e⃠",
        "c⃠o⃠z⃠ t⃠e⃠r⃠i⃠ m⃠a⃠ a⃠n⃠d⃠h⃠i⃠ r⃠a⃠n⃠d⃠i⃠ h⃠e⃠",
        "n⃠y⃠t⃠o⃠ b⃠a⃠a⃠p⃠ b⃠o⃠l⃠ m⃠u⃠j⃠h⃠e⃠",
        "n⃠y⃠n⃠y⃠ t⃠e⃠r⃠i⃠ m⃠a⃠a⃠ h⃠o⃠g⃠i⃠ r⃠n⃠d⃠i⃠i⃠ j⃠o⃠ c⃠h⃠u⃠d⃠w⃠a⃠t⃠i⃠ j⃠o⃠g⃠i⃠",
        "t⃠r⃠y⃠ a⃠m⃠m⃠i⃠ c⃠e⃠ b⃠h⃠o⃠s⃠d⃠e⃠ m⃠e⃠ e⃠m⃠o⃠j⃠i⃠ d⃠a⃠l⃠ m⃠c⃠",
        "c⃠y⃠a⃠ ? c⃠h⃠m⃠r⃠ c⃠h⃠u⃠d⃠ g⃠y⃠a⃠ c⃠y⃠a⃠ ?",
        "t⃠m⃠ c⃠h⃠u⃠d⃠r⃠i⃠ h⃠o⃠g⃠i⃠ f⃠r⃠r⃠t⃠o⃠",
        "c⃠y⃠a⃠ ? k⃠b⃠ ? p⃠g⃠l⃠ e⃠y⃠ c⃠y⃠a⃠ r⃠n⃠d⃠k⃠e⃠k⃠",
        "c⃠y⃠a⃠ s⃠c⃠h⃠ m⃠e⃠y⃠ p⃠g⃠l⃠ e⃠y⃠ c⃠y⃠a⃠ t⃠u⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ c⃠u⃠d⃠w⃠a⃠ l⃠i⃠ t⃠u⃠n⃠e⃠ a⃠p⃠n⃠i⃠ m⃠a⃠",
        "i⃠t⃠n⃠a⃠ s⃠c⃠h⃠ n⃠y⃠ b⃠o⃠l⃠ m⃠a⃠ c⃠h⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "s⃠c⃠h⃠ m⃠e⃠y⃠ p⃠g⃠l⃠ e⃠y⃠ t⃠u⃠ a⃠p⃠n⃠i⃠ m⃠a⃠ c⃠u⃠d⃠w⃠a⃠ l⃠i⃠a⃠ m⃠e⃠r⃠e⃠ s⃠t⃠h⃠",
        "m⃠t⃠l⃠b⃠ t⃠m⃠r⃠",
        "n⃠y⃠t⃠o⃠",
        "p⃠u⃠r⃠a⃠ l⃠i⃠k⃠h⃠ m⃠c⃠",
        "t⃠m⃠r⃠ f⃠r⃠r⃠t⃠o⃠",
        "o⃠h⃠ o⃠k⃠ c⃠u⃠d⃠l⃠e⃠ f⃠i⃠r⃠",
        "t⃠e⃠r⃠i⃠ m⃠a⃠a⃠ k⃠a⃠ d⃠a⃠m⃠a⃠d⃠",
        "c⃠y⃠a⃠ ? a⃠c⃠h⃠e⃠ s⃠e⃠ l⃠i⃠k⃠h⃠e⃠ p⃠e⃠h⃠l⃠e⃠ r⃠n⃠d⃠i⃠k⃠e⃠b⃠a⃠c⃠h⃠e⃠",
        "n⃠y⃠t⃠o⃠ t⃠e⃠r⃠i⃠ m⃠a⃠a⃠ c⃠h⃠o⃠d⃠n⃠e⃠ m⃠e⃠ v⃠y⃠a⃠s⃠t⃠ h⃠u⃠",
        "n⃠y⃠t⃠o⃠ p⃠g⃠l⃠ e⃠y⃠ c⃠y⃠a⃠ k⃠u⃠c⃠h⃠ b⃠i⃠",
        "o⃠y⃠e⃠e⃠ c⃠y⃠a⃠ ? c⃠h⃠u⃠d⃠ g⃠y⃠a⃠ ?",
        "c⃠h⃠u⃠d⃠ m⃠t⃠ h⃠s⃠s⃠",
        "y⃠u⃠r⃠ r⃠n⃠d⃠i⃠i⃠ m⃠o⃠m⃠",
        "a⃠r⃠e⃠ s⃠b⃠k⃠i⃠ m⃠a⃠a⃠ r⃠n⃠d⃠i⃠i⃠ o⃠r⃠ t⃠e⃠r⃠i⃠ b⃠i⃠",
        "a⃠r⃠e⃠ i⃠d⃠a⃠r⃠ c⃠u⃠d⃠l⃠e⃠ e⃠k⃠ b⃠a⃠a⃠r⃠",
        "t⃠r⃠i⃠ m⃠a⃠a⃠ c⃠i⃠ t⃠r⃠h⃠",
        "e⃠k⃠ l⃠i⃠n⃠e⃠ m⃠e⃠ t⃠m⃠r⃠",
        "Q⃠",
        "o⃠c⃠y⃠ a⃠b⃠ c⃠h⃠u⃠d⃠l⃠e⃠",
        "p⃠e⃠h⃠e⃠l⃠e⃠ t⃠e⃠r⃠i⃠ m⃠a⃠a⃠ c⃠h⃠o⃠d⃠u⃠",
        "n⃠y⃠t⃠o⃠",
        "q⃠ ?",
        "h⃠y⃠y⃠y⃠ c⃠h⃠u⃠d⃠ k⃠e⃠ d⃠i⃠k⃠a⃠ e⃠k⃠ b⃠a⃠a⃠r⃠",
        "o⃠y⃠e⃠e⃠ s⃠u⃠n⃠ d⃠o⃠s⃠t⃠ t⃠m⃠r⃠",
        "b⃠h⃠a⃠g⃠ j⃠a⃠ r⃠a⃠a⃠n⃠d⃠ m⃠a⃠a⃠f⃠ c⃠r⃠r⃠ d⃠u⃠n⃠g⃠a⃠",
        "o⃠y⃠e⃠e⃠ p⃠g⃠l⃠ r⃠n⃠d⃠i⃠i⃠ i⃠d⃠a⃠r⃠ a⃠a⃠",
        "c⃠y⃠a⃠ t⃠m⃠r⃠ f⃠r⃠r⃠t⃠o⃠",
        "o⃠y⃠e⃠e⃠ i⃠d⃠a⃠r⃠ a⃠a⃠k⃠e⃠ c⃠h⃠u⃠d⃠ l⃠e⃠ c⃠h⃠m⃠r⃠",
        "n⃠y⃠t⃠o⃠ a⃠e⃠s⃠e⃠ h⃠i⃠ c⃠u⃠d⃠",
        "o⃠y⃠e⃠e⃠ h⃠y⃠y⃠ a⃠i⃠s⃠e⃠ h⃠i⃠ c⃠u⃠d⃠ l⃠e⃠n⃠a⃠",
        "o⃠r⃠ c⃠h⃠u⃠d⃠ l⃠e⃠",
        "c⃠h⃠u⃠d⃠ k⃠e⃠ d⃠i⃠k⃠a⃠ o⃠r⃠",
        "h⃠y⃠y⃠ c⃠h⃠u⃠d⃠o⃠ n⃠a⃠",
        "c⃠h⃠u⃠d⃠o⃠ m⃠t⃠ b⃠h⃠a⃠g⃠ j⃠a⃠o⃠",
        "b⃠y⃠y⃠e⃠e⃠ h⃠y⃠y⃠ c⃠y⃠a⃠ ?",
        "Q⃠c⃠h⃠u⃠d⃠ q⃠ r⃠h⃠e⃠ h⃠o⃠ ?",
        "p⃠g⃠l⃠ e⃠y⃠ c⃠y⃠a⃠ m⃠c⃠",
        "c⃠h⃠u⃠d⃠ m⃠t⃠",
        "c⃠y⃠a⃠ p⃠g⃠l⃠ r⃠n⃠d⃠i⃠i⃠ i⃠d⃠a⃠r⃠ a⃠a⃠",
        "t⃠e⃠r⃠i⃠ a⃠m⃠m⃠i⃠ c⃠e⃠ b⃠h⃠o⃠s⃠d⃠e⃠ m⃠e⃠ c⃠h⃠a⃠p⃠p⃠a⃠l⃠",
        "o⃠y⃠e⃠e⃠ i⃠d⃠a⃠r⃠ a⃠a⃠ m⃠c⃠",
        "k⃠m⃠z⃠r⃠o⃠r⃠ e⃠y⃠ c⃠y⃠a⃠ r⃠n⃠d⃠i⃠e⃠k⃠",
        "c⃠y⃠a⃠ l⃠i⃠k⃠h⃠ r⃠h⃠a⃠ ?",
        "c⃠h⃠u⃠d⃠ t⃠h⃠a⃠ c⃠y⃠a⃠ ?",
        "o⃠y⃠e⃠e⃠ s⃠l⃠i⃠d⃠e⃠ l⃠e⃠k⃠e⃠ b⃠a⃠a⃠t⃠ c⃠r⃠m⃠c⃠",
        "i⃠d⃠a⃠r⃠ a⃠ t⃠e⃠r⃠i⃠ m⃠a⃠a⃠ c⃠h⃠o⃠d⃠u⃠",
        "o⃠y⃠e⃠e⃠ c⃠p⃠ m⃠t⃠ c⃠r⃠r⃠ c⃠h⃠u⃠d⃠l⃠e⃠",
        "o⃠y⃠e⃠e⃠ h⃠y⃠y⃠ c⃠h⃠u⃠d⃠ k⃠e⃠ d⃠i⃠k⃠a⃠",
        "i⃠d⃠a⃠r⃠ a⃠a⃠ t⃠r⃠y⃠ m⃠a⃠ s⃠c⃠h⃠o⃠f⃠u⃠ k⃠h⃠a⃠c⃠h⃠a⃠r⃠ k⃠h⃠a⃠c⃠h⃠a⃠r⃠",
        "i⃠d⃠a⃠r⃠ a⃠a⃠ j⃠a⃠ m⃠c⃠",
        "h⃠y⃠y⃠ i⃠d⃠a⃠r⃠ a⃠a⃠k⃠e⃠ c⃠h⃠u⃠d⃠l⃠e⃠",
        "o⃠y⃠e⃠e⃠ k⃠m⃠z⃠o⃠r⃠ m⃠c⃠ i⃠d⃠a⃠r⃠ a⃠a⃠",
        "y⃠e⃠ c⃠y⃠a⃠ t⃠m⃠r⃠",
        "o⃠y⃠e⃠e⃠ n⃠y⃠ c⃠p⃠ n⃠y⃠ c⃠r⃠r⃠",
        "o⃠y⃠e⃠e⃠ p⃠g⃠l⃠ m⃠t⃠ c⃠r⃠r⃠",
        "c⃠u⃠d⃠l⃠e⃠ a⃠r⃠a⃠m⃠ s⃠e⃠ m⃠c⃠",
        "p⃠g⃠l⃠ e⃠y⃠ c⃠y⃠a⃠ r⃠n⃠d⃠i⃠e⃠k⃠",
        "c⃠p⃠ c⃠r⃠c⃠e⃠ c⃠h⃠u⃠d⃠e⃠g⃠a⃠ !",
        "b⃠a⃠a⃠p⃠ ? m⃠c⃠ m⃠e⃠r⃠a⃠ c⃠o⃠i⃠ m⃠a⃠ b⃠a⃠a⃠p⃠ n⃠y⃠ e⃠y⃠ m⃠a⃠i⃠ u⃠p⃠a⃠r⃠ s⃠e⃠ r⃠o⃠c⃠k⃠e⃠t⃠ p⃠e⃠ b⃠e⃠t⃠h⃠ c⃠e⃠ b⃠s⃠s⃠ t⃠e⃠r⃠i⃠ m⃠a⃠ c⃠h⃠o⃠d⃠n⃠e⃠ a⃠y⃠a⃠ h⃠u⃠",
        "C⃠h⃠o⃠t⃠a⃠ l⃠i⃠k⃠h⃠ r⃠n⃠d⃠i⃠ k⃠ b⃠a⃠c⃠h⃠e⃠",
        "C⃠h⃠o⃠t⃠a⃠ l⃠i⃠k⃠h⃠a⃠ w⃠r⃠n⃠a⃠ t⃠r⃠y⃠ m⃠a⃠ r⃠n⃠d⃠y⃠",
        "T⃠r⃠y⃠ m⃠a⃠ b⃠a⃠k⃠a⃠ c⃠o⃠d⃠e⃠g⃠a⃠",
        "T⃠m⃠k⃠c⃠ m⃠a⃠i⃠n⃠ b⃠u⃠r⃠f⃠",
        "B⃠h⃠i⃠k⃠a⃠r⃠i⃠ k⃠i⃠ j⃠h⃠a⃠t⃠ m⃠a⃠ c⃠u⃠d⃠a⃠ l⃠e⃠",
        "C⃠h⃠o⃠d⃠k⃠e⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ m⃠a⃠r⃠j⃠a⃠y⃠e⃠g⃠i⃠",
        "T⃠m⃠k⃠c⃠ m⃠a⃠i⃠n⃠ M⃠o⃠u⃠n⃠t⃠ E⃠v⃠e⃠r⃠e⃠s⃠t⃠",
        "M⃠u⃠h⃠ m⃠e⃠y⃠ l⃠e⃠g⃠a⃠ l⃠u⃠n⃠d⃠ m⃠e⃠r⃠a⃠",
        "H⃠i⃠j⃠d⃠e⃠ k⃠i⃠ j⃠h⃠a⃠t⃠ c⃠h⃠u⃠p⃠ w⃠r⃠n⃠a⃠ t⃠r⃠y⃠ m⃠a⃠ r⃠n⃠d⃠i⃠",
        "M⃠e⃠n⃠u⃠ n⃠y⃠ p⃠t⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ r⃠a⃠n⃠d⃠y⃠",
        "M⃠e⃠n⃠u⃠ k⃠i⃠ p⃠t⃠a⃠ m⃠a⃠ r⃠a⃠n⃠d⃠y⃠ t⃠e⃠r⃠y⃠",
        "M⃠e⃠n⃠u⃠ p⃠t⃠a⃠ m⃠a⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "M⃠e⃠n⃠u⃠ s⃠b⃠ p⃠t⃠a⃠ m⃠a⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠ t⃠e⃠r⃠y⃠",
        "M⃠e⃠n⃠u⃠ p⃠r⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ r⃠a⃠n⃠d⃠y⃠",
        "R⃠a⃠n⃠d⃠y⃠ m⃠a⃠a⃠ t⃠e⃠r⃠y⃠ m⃠e⃠n⃠u⃠ p⃠t⃠a⃠",
        "T⃠e⃠n⃠u⃠ o⃠r⃠ m⃠e⃠n⃠u⃠ p⃠t⃠a⃠ e⃠y⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ t⃠e⃠r⃠y⃠",
        "B⃠s⃠ b⃠s⃠ m⃠a⃠a⃠ c⃠u⃠d⃠w⃠a⃠ a⃠p⃠n⃠i⃠",
        "B⃠s⃠ b⃠s⃠ m⃠a⃠ r⃠a⃠n⃠d⃠y⃠ t⃠e⃠r⃠y⃠ t⃠h⃠n⃠k⃠s⃠s⃠",
        "B⃠s⃠ b⃠s⃠ c⃠h⃠u⃠d⃠w⃠a⃠ l⃠i⃠a⃠ t⃠u⃠ a⃠p⃠n⃠i⃠ m⃠a⃠a⃠",
        "B⃠s⃠ b⃠s⃠ k⃠a⃠m⃠j⃠o⃠r⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ t⃠e⃠r⃠y⃠",
        "S⃠m⃠j⃠h⃠ g⃠y⃠a⃠ a⃠p⃠n⃠i⃠ m⃠a⃠ c⃠u⃠d⃠w⃠a⃠ l⃠e⃠ a⃠b⃠",
        "s⃠m⃠j⃠h⃠ g⃠y⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠",
        "s⃠m⃠j⃠h⃠ g⃠y⃠a⃠ t⃠u⃠ s⃠a⃠b⃠i⃠t⃠ k⃠r⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ t⃠e⃠r⃠y⃠",
        "C⃠y⃠a⃠ h⃠u⃠a⃠ m⃠a⃠ c⃠u⃠d⃠w⃠a⃠ t⃠u⃠ a⃠p⃠n⃠i⃠",
        "E⃠a⃠s⃠y⃠ m⃠a⃠a⃠ c⃠u⃠d⃠w⃠a⃠ l⃠e⃠ a⃠p⃠n⃠i⃠ t⃠u⃠",
        "E⃠a⃠s⃠y⃠ w⃠8⃠ m⃠a⃠ c⃠h⃠u⃠d⃠w⃠a⃠ l⃠e⃠ a⃠p⃠n⃠i⃠ a⃠b⃠",
        "S⃠a⃠n⃠s⃠ a⃠r⃠i⃠ h⃠a⃠ k⃠y⃠ t⃠e⃠r⃠i⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠g⃠i⃠ a⃠j⃠j⃠",
        "T⃠e⃠r⃠i⃠ m⃠a⃠a⃠ k⃠o⃠ b⃠i⃠n⃠a⃠ s⃠a⃠n⃠s⃠s⃠ l⃠e⃠t⃠e⃠ h⃠u⃠e⃠ c⃠h⃠o⃠d⃠u⃠n⃠g⃠a⃠",
        "c⃠h⃠u⃠p⃠ r⃠a⃠n⃠d⃠i⃠k⃠e⃠ k⃠a⃠m⃠j⃠o⃠r⃠",
        "a⃠p⃠n⃠i⃠ m⃠a⃠ n⃠o⃠r⃠m⃠i⃠e⃠ c⃠u⃠d⃠w⃠a⃠ l⃠e⃠ t⃠u⃠",
        "f⃠r⃠ c⃠y⃠a⃠ n⃠o⃠r⃠m⃠i⃠e⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "b⃠a⃠s⃠ t⃠h⃠e⃠k⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ r⃠a⃠n⃠d⃠y⃠",
        "b⃠a⃠s⃠ t⃠h⃠e⃠k⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ c⃠u⃠d⃠ g⃠y⃠i⃠",
        "k⃠a⃠m⃠j⃠o⃠r⃠ t⃠h⃠i⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ e⃠s⃠l⃠i⃠y⃠e⃠ c⃠u⃠d⃠ g⃠a⃠i⃠",
        "M⃠a⃠i⃠ s⃠b⃠ j⃠a⃠n⃠t⃠a⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "c⃠h⃠l⃠ c⃠h⃠l⃠ h⃠t⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ c⃠u⃠d⃠ g⃠y⃠i⃠",
        "f⃠r⃠ k⃠a⃠i⃠s⃠e⃠ c⃠u⃠d⃠ g⃠y⃠i⃠ m⃠a⃠a⃠ t⃠e⃠r⃠y⃠",
        "m⃠a⃠a⃠ t⃠e⃠r⃠y⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠",
        "b⃠a⃠s⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠",
        "f⃠r⃠ r⃠a⃠n⃠d⃠y⃠ m⃠a⃠ t⃠e⃠r⃠y⃠ e⃠y⃠",
        "K⃠a⃠m⃠j⃠o⃠r⃠ m⃠a⃠ k⃠a⃠ b⃠c⃠h⃠a⃠ t⃠u⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠",
        "b⃠h⃠o⃠t⃠ g⃠n⃠d⃠i⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ m⃠a⃠a⃠ t⃠e⃠r⃠y⃠",
        "p⃠r⃠ k⃠a⃠i⃠s⃠e⃠ m⃠a⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠ i⃠t⃠n⃠a⃠ g⃠n⃠d⃠a⃠",
        "m⃠u⃠j⃠h⃠e⃠ c⃠y⃠a⃠ b⃠t⃠a⃠ r⃠h⃠a⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ t⃠e⃠r⃠y⃠",
        "m⃠u⃠j⃠h⃠e⃠ c⃠y⃠a⃠ p⃠t⃠a⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠y⃠i⃠ t⃠e⃠r⃠y⃠",
        "f⃠i⃠r⃠ m⃠u⃠j⃠h⃠e⃠ n⃠y⃠ p⃠t⃠a⃠ m⃠a⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "p⃠t⃠a⃠ n⃠y⃠ k⃠o⃠n⃠ c⃠o⃠d⃠ d⃠i⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ k⃠o⃠",
        "r⃠u⃠k⃠ a⃠a⃠y⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ c⃠o⃠d⃠k⃠e⃠",
        "w⃠a⃠i⃠t⃠ c⃠r⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ c⃠o⃠d⃠ r⃠h⃠a⃠ h⃠u⃠",
        "w⃠a⃠i⃠t⃠ c⃠r⃠ r⃠a⃠b⃠d⃠y⃠k⃠e⃠ m⃠a⃠a⃠ c⃠u⃠d⃠ r⃠h⃠i⃠ e⃠y⃠ t⃠e⃠r⃠y⃠",
        "w⃠a⃠i⃠t⃠ k⃠r⃠ s⃠m⃠j⃠h⃠ r⃠h⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ c⃠o⃠d⃠k⃠e⃠",
        "w⃠a⃠i⃠t⃠ l⃠e⃠ t⃠h⃠o⃠d⃠a⃠ c⃠h⃠o⃠d⃠n⃠e⃠ d⃠e⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠o⃠",
        "r⃠u⃠k⃠ j⃠a⃠ a⃠a⃠n⃠d⃠ r⃠k⃠h⃠ d⃠u⃠n⃠g⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠e⃠ l⃠i⃠y⃠e⃠",
        "t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ f⃠a⃠m⃠o⃠u⃠s⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠",
        "m⃠a⃠a⃠n⃠ l⃠i⃠a⃠ m⃠e⃠n⃠e⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ s⃠a⃠l⃠i⃠ t⃠e⃠r⃠y⃠",
        "m⃠a⃠a⃠n⃠ l⃠i⃠a⃠ m⃠a⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "s⃠h⃠a⃠n⃠t⃠ b⃠e⃠t⃠h⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠w⃠a⃠ t⃠u⃠ a⃠p⃠n⃠i⃠",
        "s⃠h⃠a⃠n⃠t⃠ b⃠e⃠t⃠h⃠k⃠e⃠ c⃠h⃠u⃠d⃠w⃠a⃠ l⃠e⃠ a⃠p⃠n⃠i⃠ m⃠a⃠k⃠o⃠ t⃠u⃠",
        "f⃠r⃠ s⃠e⃠ s⃠h⃠a⃠n⃠t⃠ B⃠e⃠t⃠h⃠ t⃠u⃠ c⃠u⃠d⃠ a⃠b⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ y⃠h⃠a⃠",
        "m⃠e⃠r⃠e⃠ s⃠m⃠j⃠h⃠ n⃠y⃠ a⃠y⃠a⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ t⃠e⃠r⃠y⃠",
        "L⃠e⃠ k⃠e⃠l⃠a⃠ K⃠h⃠a⃠ t⃠u⃠ m⃠a⃠d⃠a⃠r⃠c⃠h⃠o⃠d⃠",
        "H⃠y⃠e⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠y⃠i⃠ c⃠y⃠a⃠",
        "h⃠y⃠e⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ m⃠a⃠r⃠ g⃠a⃠i⃠ c⃠y⃠a⃠",
        "H⃠y⃠e⃠ s⃠c⃠h⃠ b⃠t⃠a⃠ c⃠o⃠m⃠ c⃠o⃠d⃠ d⃠i⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠o⃠",
        "C⃠h⃠l⃠ c⃠h⃠o⃠d⃠ d⃠i⃠a⃠ t⃠e⃠r⃠i⃠ m⃠a⃠a⃠ k⃠o⃠ s⃠m⃠j⃠h⃠l⃠e⃠",
        "B⃠a⃠k⃠i⃠ k⃠o⃠i⃠ d⃠i⃠k⃠k⃠a⃠t⃠ n⃠y⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠",
        "b⃠a⃠k⃠i⃠ s⃠b⃠ j⃠a⃠n⃠t⃠e⃠ e⃠y⃠ k⃠i⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠d⃠k⃠a⃠d⃠ e⃠y⃠ t⃠e⃠r⃠y⃠",
        "m⃠u⃠j⃠h⃠e⃠ c⃠y⃠a⃠ p⃠t⃠a⃠ t⃠h⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ c⃠u⃠d⃠n⃠e⃠ w⃠l⃠i⃠ e⃠y⃠",
        "p⃠r⃠ m⃠e⃠i⃠ k⃠a⃠i⃠s⃠e⃠ j⃠n⃠t⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ k⃠o⃠ k⃠o⃠i⃠ c⃠h⃠o⃠d⃠ d⃠i⃠a⃠",
        "p⃠r⃠ m⃠e⃠r⃠a⃠ v⃠i⃠ m⃠a⃠n⃠n⃠a⃠ s⃠h⃠i⃠ t⃠h⃠a⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "p⃠r⃠ w⃠o⃠ g⃠l⃠t⃠ n⃠y⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠",
        "p⃠r⃠ w⃠o⃠ s⃠h⃠i⃠ e⃠y⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠d⃠k⃠a⃠d⃠ e⃠y⃠",
        "p⃠r⃠ k⃠a⃠i⃠s⃠e⃠ k⃠i⃠a⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠ o⃠m⃠f⃠o⃠o⃠",
        "b⃠u⃠r⃠ c⃠h⃠e⃠e⃠r⃠ d⃠u⃠n⃠g⃠a⃠ t⃠r⃠i⃠ m⃠a⃠ k⃠a⃠",
        "t⃠e⃠r⃠i⃠ m⃠a⃠ k⃠e⃠ d⃠i⃠l⃠ m⃠e⃠ l⃠o⃠d⃠a⃠ m⃠a⃠r⃠k⃠e⃠ u⃠s⃠k⃠i⃠ d⃠h⃠a⃠d⃠k⃠a⃠n⃠ r⃠o⃠k⃠ d⃠u⃠n⃠g⃠a⃠",
        "l⃠u⃠l⃠l⃠e⃠ k⃠h⃠a⃠ t⃠r⃠i⃠ m⃠a⃠k⃠a⃠b⃠h⃠o⃠s⃠d⃠a⃠",
        "t⃠r⃠i⃠ b⃠h⃠n⃠ k⃠i⃠ b⃠h⃠o⃠s⃠d⃠i⃠ b⃠e⃠t⃠a⃠",
        "t⃠r⃠i⃠ m⃠a⃠ r⃠n⃠d⃠i⃠ b⃠a⃠a⃠t⃠ k⃠h⃠t⃠m⃠",
        "S⃠u⃠n⃠ e⃠k⃠ m⃠a⃠z⃠e⃠ k⃠i⃠ b⃠a⃠a⃠t⃠ b⃠a⃠t⃠a⃠o⃠ k⃠y⃠a⃠ t⃠e⃠r⃠i⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠"
        "c⃠o⃠d⃠u⃠ c⃠o⃠d⃠u⃠ m⃠a⃠k⃠o⃠ t⃠e⃠r⃠y⃠",
        "a⃠j⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ o⃠y⃠e⃠",
        "s⃠u⃠n⃠ s⃠u⃠n⃠ r⃠a⃠n⃠d⃠y⃠ m⃠a⃠k⃠e⃠ b⃠a⃠c⃠h⃠e⃠ t⃠u⃠",
        "k⃠i⃠l⃠a⃠s⃠ n⃠y⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠",
        "m⃠u⃠j⃠h⃠e⃠ c⃠y⃠a⃠ p⃠t⃠a⃠ t⃠e⃠r⃠y⃠ b⃠h⃠e⃠n⃠ c⃠u⃠d⃠ g⃠a⃠i⃠",
        "p⃠r⃠ p⃠r⃠ c⃠y⃠a⃠ h⃠o⃠t⃠e⃠ e⃠y⃠ t⃠m⃠k⃠c⃠",
        "t⃠m⃠c⃠l⃠ s⃠u⃠n⃠l⃠e⃠",
        "m⃠o⃠o⃠t⃠ d⃠u⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠i⃠ c⃠h⃠u⃠t⃠ m⃠e⃠y⃠",
        "b⃠h⃠g⃠n⃠y⃠ c⃠u⃠d⃠k⃠e⃠ d⃠i⃠k⃠h⃠a⃠ f⃠r⃠",
        "f⃠r⃠ s⃠e⃠ c⃠u⃠d⃠l⃠e⃠ t⃠u⃠",
        "y⃠e⃠ v⃠i⃠ s⃠h⃠i⃠ e⃠y⃠ t⃠e⃠r⃠y⃠ m⃠k⃠c⃠ b⃠s⃠",
        "a⃠j⃠ k⃠u⃠c⃠h⃠ n⃠y⃠ m⃠a⃠ c⃠u⃠d⃠w⃠a⃠ t⃠u⃠ a⃠p⃠n⃠i⃠",
        "t⃠r⃠y⃠ k⃠r⃠ m⃠e⃠r⃠a⃠ l⃠u⃠n⃠d⃠ c⃠h⃠u⃠s⃠k⃠e⃠",
        "t⃠o⃠r⃠m⃠a⃠k⃠i⃠b⃠u⃠r⃠ s⃠u⃠n⃠",
        "t⃠o⃠r⃠ m⃠a⃠k⃠i⃠ f⃠u⃠d⃠d⃠i⃠ o⃠y⃠e⃠",
        "H⃠a⃠y⃠e⃠ H⃠a⃠y⃠e⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠",
        "o⃠y⃠e⃠ l⃠u⃠n⃠d⃠k⃠e⃠ p⃠a⃠s⃠i⃠n⃠e⃠..",
        "k⃠u⃠t⃠t⃠e⃠ k⃠e⃠ t⃠a⃠t⃠t⃠e⃠ s⃠u⃠n⃠",
        "k⃠u⃠t⃠t⃠a⃠ j⃠a⃠i⃠s⃠a⃠ c⃠u⃠d⃠ r⃠h⃠a⃠ t⃠u⃠",
        "M⃠u⃠h⃠ m⃠e⃠i⃠ l⃠e⃠ m⃠e⃠r⃠a⃠..",
        "j⃠h⃠a⃠a⃠t⃠ k⃠e⃠ p⃠i⃠s⃠s⃠u⃠ s⃠u⃠n⃠ t⃠m⃠k⃠c⃠",
        "H⃠a⃠h⃠a⃠h⃠h⃠a⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "w⃠e⃠a⃠k⃠ t⃠a⃠t⃠t⃠e⃠ u⃠t⃠h⃠",
        "w⃠e⃠a⃠k⃠ e⃠y⃠ t⃠u⃠ c⃠u⃠d⃠ r⃠h⃠a⃠",
        "w⃠e⃠a⃠k⃠ a⃠c⃠h⃠e⃠ s⃠e⃠ c⃠u⃠d⃠ t⃠u⃠",
        "w⃠e⃠a⃠k⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ c⃠u⃠d⃠ r⃠h⃠i⃠ d⃠e⃠k⃠h⃠",
        "w⃠e⃠e⃠k⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ a⃠b⃠",
        "m⃠u⃠j⃠h⃠e⃠ n⃠y⃠ r⃠o⃠k⃠ t⃠u⃠ w⃠e⃠a⃠k⃠ e⃠y⃠",
        "c⃠h⃠u⃠p⃠ h⃠i⃠z⃠d⃠e⃠",
        "o⃠k⃠a⃠t⃠ n⃠y⃠ m⃠e⃠r⃠i⃠ m⃠a⃠ c⃠u⃠d⃠w⃠a⃠ t⃠u⃠ a⃠p⃠n⃠i⃠",
        "l⃠u⃠n⃠ l⃠e⃠g⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠i⃠ g⃠a⃠n⃠d⃠ m⃠e⃠i⃠ ?",
        "t⃠e⃠r⃠y⃠ m⃠a⃠k⃠i⃠ b⃠a⃠c⃠h⃠i⃠ c⃠o⃠d⃠u⃠..",
        "t⃠e⃠r⃠y⃠ b⃠h⃠e⃠n⃠ k⃠i⃠ c⃠h⃠u⃠t⃠ a⃠j⃠ f⃠a⃠d⃠ d⃠u⃠",
        "s⃠p⃠e⃠e⃠d⃠ l⃠e⃠k⃠r⃠ a⃠a⃠ c⃠u⃠d⃠k⃠e⃠ d⃠i⃠k⃠h⃠a⃠",
        "s⃠p⃠e⃠e⃠d⃠ n⃠y⃠ t⃠e⃠r⃠e⃠ a⃠n⃠d⃠r⃠ w⃠e⃠a⃠k⃠ p⃠r⃠o⃠s⃠n⃠",
        "u⃠g⃠l⃠y⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ c⃠h⃠u⃠p⃠",
        "m⃠a⃠k⃠a⃠f⃠u⃠d⃠d⃠a⃠t⃠e⃠r⃠y⃠",
        "t⃠e⃠r⃠a⃠ b⃠a⃠a⃠p⃠ k⃠o⃠ t⃠a⃠g⃠ k⃠r⃠..?",
        "a⃠c⃠h⃠e⃠ s⃠e⃠ t⃠a⃠g⃠ k⃠r⃠ r⃠a⃠n⃠d⃠i⃠b⃠a⃠a⃠z⃠ b⃠h⃠a⃠g⃠w⃠n⃠ k⃠o⃠..",
        "c⃠u⃠d⃠k⃠e⃠ p⃠g⃠l⃠ n⃠y⃠ h⃠o⃠ t⃠u⃠",
        "c⃠u⃠d⃠k⃠e⃠ p⃠g⃠l⃠ h⃠o⃠ r⃠h⃠a⃠ t⃠u⃠ k⃠i⃠d⃠",
        "m⃠a⃠ t⃠o⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠ h⃠a⃠w⃠a⃠b⃠z⃠i⃠ c⃠r⃠..",
        "b⃠s⃠ m⃠a⃠ c⃠o⃠d⃠n⃠i⃠ e⃠y⃠ t⃠e⃠r⃠y⃠",
        "t⃠o⃠w⃠n⃠ m⃠e⃠i⃠ c⃠u⃠d⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠o⃠ l⃠e⃠k⃠r⃠",
        "t⃠e⃠r⃠y⃠ m⃠a⃠ s⃠e⃠x⃠y⃠ k⃠o⃠ b⃠e⃠j⃠ - r⃠a⃠n⃠d⃠i⃠b⃠a⃠a⃠z⃠ b⃠h⃠g⃠w⃠n⃠ p⃠e⃠",
        "s⃠p⃠e⃠e⃠d⃠ p⃠k⃠d⃠ c⃠p⃠ n⃠y⃠ k⃠r⃠",
        "T⃠r⃠y⃠ m⃠a⃠ r⃠e⃠n⃠d⃠y⃠",
        "B⃠h⃠k⃠k⃠ c⃠u⃠d⃠",
        "t⃠e⃠y⃠ m⃠a⃠a⃠ r⃠n⃠d⃠i⃠",
        "t⃠e⃠r⃠y⃠ b⃠e⃠h⃠e⃠n⃠ r⃠a⃠n⃠d⃠i⃠",
        "C⃠u⃠d⃠ j⃠a⃠",
        "t⃠e⃠r⃠y⃠ d⃠i⃠d⃠i⃠ r⃠n⃠d⃠i⃠",
        "S⃠l⃠o⃠w⃠",
        "t⃠e⃠r⃠i⃠ M⃠a⃠i⃠y⃠a⃠ c⃠i⃠o⃠d⃠u⃠",
        "B⃠h⃠a⃠g⃠?",
        "B⃠h⃠a⃠k⃠ c⃠u⃠d⃠",
        "T⃠m⃠a⃠ c⃠o⃠d⃠u⃠",
        "S⃠l⃠o⃠w⃠",
        "S⃠l⃠o⃠w⃠ f⃠i⃠r⃠s⃠e⃠",
        "C⃠u⃠d⃠g⃠r⃠i⃠b⃠",
        "T⃠r⃠y⃠ m⃠a⃠ d⃠o⃠u⃠",
        "t⃠b⃠k⃠c⃠ c⃠o⃠d⃠u⃠",
        "N⃠e⃠t⃠ o⃠n⃠ o⃠f⃠f⃠ w⃠a⃠l⃠i⃠ r⃠n⃠d⃠y⃠",
        "O⃠y⃠e⃠ t⃠r⃠y⃠ m⃠a⃠ c⃠o⃠d⃠u⃠",
        "I⃠d⃠h⃠a⃠r⃠ a⃠a⃠k⃠e⃠ c⃠u⃠d⃠ c⃠h⃠u⃠p⃠ c⃠h⃠a⃠a⃠p⃠",
        "t⃠b⃠k⃠c⃠ m⃠r⃠d⃠u⃠",
        "o⃠i⃠ m⃠a⃠a⃠k⃠e⃠ l⃠o⃠d⃠e⃠e⃠",
        "r⃠a⃠n⃠d⃠y⃠k⃠e⃠ b⃠e⃠e⃠j⃠",
        "t⃠m⃠k⃠c⃠ c⃠h⃠o⃠d⃠u⃠",
        "s⃠u⃠a⃠r⃠ k⃠e⃠ b⃠e⃠e⃠j⃠",
        "n⃠e⃠t⃠ o⃠f⃠f⃠ o⃠n⃠ k⃠r⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ l⃠a⃠d⃠k⃠e⃠",
        "T⃠r⃠y⃠ m⃠a⃠ c⃠u⃠d⃠i⃠ k⃠e⃠s⃠e⃠",
        "C⃠h⃠u⃠p⃠ s⃠l⃠o⃠w⃠ m⃠a⃠d⃠h⃠a⃠r⃠c⃠o⃠d⃠",
        "t⃠b⃠k⃠c⃠ c⃠o⃠d⃠u⃠ k⃠r⃠ m⃠s⃠g⃠ d⃠e⃠l⃠e⃠t⃠e⃠",
        "o⃠i⃠ s⃠u⃠a⃠r⃠ k⃠e⃠ l⃠a⃠d⃠k⃠e⃠",
        "t⃠m⃠k⃠c⃠ f⃠u⃠f⃠i⃠",
        "t⃠e⃠r⃠y⃠ d⃠i⃠d⃠i⃠ c⃠h⃠u⃠d⃠i⃠",
        "t⃠m⃠k⃠c⃠ d⃠i⃠k⃠h⃠a⃠",
        "C⃠u⃠d⃠ a⃠b⃠",
        "r⃠a⃠n⃠d⃠y⃠k⃠e⃠ c⃠u⃠d⃠",
        "B⃠h⃠a⃠k⃠ c⃠u⃠d⃠",
        "c⃠u⃠d⃠l⃠e⃠ t⃠b⃠k⃠c⃠ m⃠r⃠u⃠",
        "t⃠m⃠k⃠l⃠ c⃠u⃠d⃠l⃠e⃠ g⃠r⃠i⃠b⃠",
        "t⃠e⃠r⃠y⃠ b⃠e⃠h⃠e⃠n⃠ v⃠e⃠s⃠i⃠y⃠a⃠a⃠ r⃠n⃠d⃠i⃠",
        "I⃠t⃠n⃠a⃠ g⃠n⃠d⃠a⃠ c⃠h⃠u⃠d⃠a⃠ t⃠u⃠ f⃠i⃠r⃠s⃠e⃠ n⃠e⃠t⃠ o⃠n⃠ o⃠f⃠f⃠",
        "g⃠r⃠i⃠b⃠ k⃠e⃠ b⃠e⃠t⃠e⃠",
        "B⃠h⃠a⃠g⃠ j⃠a⃠ l⃠o⃠d⃠e⃠ t⃠m⃠k⃠c⃠ m⃠a⃠r⃠u⃠ d⃠u⃠n⃠g⃠a⃠",
        "t⃠b⃠k⃠c⃠ m⃠r⃠d⃠u⃠n⃠g⃠a⃠a⃠",
        "b⃠h⃠a⃠g⃠ t⃠m⃠k⃠c⃠",
        "b⃠h⃠a⃠g⃠ t⃠b⃠k⃠c⃠",
        "t⃠b⃠k⃠c⃠ m⃠e⃠y⃠ c⃠p⃠",
        "c⃠p⃠ t⃠b⃠k⃠c⃠ m⃠e⃠h⃠h⃠",
        "c⃠p⃠ t⃠m⃠k⃠l⃠ m⃠e⃠h⃠",
        "c⃠p⃠ b⃠o⃠l⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠",
        "A⃠b⃠e⃠ c⃠p⃠ b⃠o⃠l⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠",
        "d⃠o⃠u⃠b⃠l⃠e⃠ s⃠e⃠n⃠d⃠ k⃠o⃠ c⃠p⃠ t⃠m⃠k⃠c⃠ c⃠o⃠d⃠u⃠",
        "t⃠b⃠k⃠c⃠ m⃠e⃠ c⃠p⃠ c⃠o⃠d⃠ d⃠u⃠n⃠g⃠a⃠ A⃠a⃠j⃠ m⃠e⃠h⃠h⃠",
        "h⃠t⃠ t⃠b⃠k⃠c⃠ d⃠a⃠l⃠a⃠l⃠ k⃠e⃠ b⃠e⃠t⃠e⃠.",
        "R⃠n⃠d⃠y⃠ j⃠l⃠d⃠i⃠ j⃠l⃠d⃠i⃠ c⃠u⃠d⃠q⃠ t⃠r⃠y⃠m⃠a⃠",
        "P⃠a⃠r⃠a⃠ l⃠i⃠k⃠h⃠e⃠g⃠a⃠..",
        "T⃠r⃠a⃠ r⃠n⃠d⃠h⃠b⃠h⃠a⃠k⃠",
        "L⃠a⃠g⃠d⃠i⃠ k⃠e⃠ l⃠a⃠d⃠c⃠e⃠ c⃠p⃠ b⃠o⃠l⃠",
        "c⃠p⃠ b⃠o⃠l⃠ l⃠a⃠g⃠d⃠i⃠ k⃠e⃠ b⃠e⃠t⃠e⃠..",
        "c⃠u⃠d⃠k⃠e⃠ c⃠p⃠ b⃠o⃠l⃠",
        "b⃠h⃠i⃠k⃠a⃠r⃠i⃠ l⃠u⃠n⃠d⃠ c⃠h⃠u⃠s⃠ m⃠e⃠r⃠a⃠.",
        "L⃠o⃠w⃠ l⃠e⃠v⃠e⃠l⃠ c⃠p⃠ c⃠r⃠",
        "c⃠p⃠ b⃠o⃠l⃠ l⃠o⃠w⃠ l⃠e⃠v⃠e⃠l⃠ w⃠e⃠a⃠k⃠",
        "m⃠e⃠r⃠e⃠ l⃠u⃠n⃠d⃠ p⃠e⃠ e⃠y⃠ t⃠u⃠ h⃠i⃠j⃠d⃠e⃠",
        "f⃠r⃠e⃠e⃠ c⃠u⃠d⃠w⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠o⃠",
        "F⃠r⃠e⃠e⃠ m⃠e⃠y⃠ c⃠u⃠d⃠ t⃠u⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠"
        "s⃠p⃠e⃠e⃠d⃠ n⃠y⃠ w⃠e⃠a⃠k⃠ t⃠a⃠t⃠t⃠e⃠ t⃠e⃠r⃠m⃠e⃠",
        "k⃠i⃠t⃠n⃠i⃠ b⃠r⃠ c⃠u⃠d⃠w⃠a⃠y⃠e⃠g⃠a⃠ t⃠e⃠r⃠y⃠m⃠a⃠k⃠o⃠",
        "l⃠u⃠n⃠d⃠ l⃠e⃠ r⃠a⃠n⃠d⃠i⃠b⃠a⃠a⃠z⃠ b⃠a⃠p⃠k⃠a⃠",
        "l⃠u⃠n⃠ c⃠u⃠s⃠ j⃠a⃠l⃠d⃠i⃠ s⃠e⃠ r⃠a⃠n⃠d⃠i⃠b⃠a⃠a⃠z⃠ b⃠a⃠p⃠k⃠a⃠",
        "k⃠o⃠i⃠ n⃠y⃠ d⃠e⃠k⃠h⃠ r⃠h⃠a⃠ c⃠u⃠d⃠l⃠e⃠ t⃠u⃠",
        "c⃠u⃠d⃠l⃠e⃠ b⃠e⃠t⃠i⃠c⃠h⃠o⃠d⃠ a⃠c⃠h⃠e⃠ s⃠e⃠",
        "m⃠a⃠k⃠i⃠ c⃠h⃠u⃠t⃠ t⃠e⃠r⃠y⃠ b⃠s⃠ y⃠e⃠h⃠i⃠ j⃠a⃠n⃠t⃠a⃠ m⃠e⃠y⃠",
        "c⃠p⃠ b⃠o⃠l⃠e⃠g⃠a⃠ t⃠o⃠ t⃠m⃠k⃠c⃠",
        "w⃠r⃠n⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ c⃠u⃠d⃠ j⃠a⃠y⃠e⃠g⃠i⃠",
        "s⃠l⃠o⃠w⃠ e⃠y⃠ t⃠u⃠ k⃠i⃠d⃠",
        "j⃠l⃠d⃠i⃠ l⃠i⃠k⃠h⃠..t⃠m⃠k⃠c⃠",
        "j⃠l⃠d⃠i⃠ l⃠i⃠k⃠h⃠..r⃠a⃠n⃠d⃠c⃠e⃠ t⃠u⃠",
        "t⃠y⃠m⃠ s⃠e⃠ p⃠h⃠l⃠e⃠ c⃠u⃠d⃠k⃠e⃠ d⃠i⃠k⃠h⃠a⃠",
        "t⃠y⃠m⃠ h⃠o⃠g⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ c⃠u⃠d⃠w⃠a⃠",
        "m⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠ t⃠y⃠m⃠ s⃠e⃠ p⃠h⃠l⃠e⃠",
        "u⃠t⃠h⃠ r⃠a⃠n⃠d⃠c⃠e⃠ k⃠e⃠ l⃠d⃠k⃠e⃠",
        "m⃠a⃠c⃠a⃠b⃠o⃠s⃠d⃠a⃠t⃠e⃠r⃠y⃠",
        "c⃠o⃠n⃠ k⃠b⃠ c⃠o⃠d⃠ d⃠i⃠a⃠ m⃠a⃠k⃠o⃠ t⃠e⃠r⃠y⃠",
        "k⃠o⃠i⃠ h⃠o⃠g⃠a⃠ t⃠m⃠l⃠",
        "m⃠a⃠c⃠h⃠a⃠r⃠ c⃠u⃠d⃠l⃠e⃠ t⃠u⃠",
        "m⃠e⃠n⃠u⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠o⃠ c⃠o⃠d⃠n⃠a⃠ s⃠e⃠",
        "t⃠e⃠r⃠y⃠ m⃠a⃠k⃠o⃠ b⃠o⃠l⃠ m⃠u⃠j⃠h⃠e⃠ c⃠o⃠d⃠ d⃠e⃠",
        "b⃠s⃠ m⃠e⃠y⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ s⃠e⃠ c⃠u⃠d⃠n⃠a⃠ c⃠h⃠t⃠a⃠ h⃠u⃠",
        "E⃠w⃠w⃠ m⃠a⃠k⃠a⃠ l⃠o⃠d⃠e⃠ u⃠t⃠h⃠",
        "M⃠e⃠o⃠w⃠ c⃠r⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠o⃠ c⃠o⃠d⃠u⃠",
        "l⃠u⃠n⃠d⃠ r⃠k⃠h⃠ d⃠i⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠e⃠ f⃠u⃠d⃠e⃠ p⃠e⃠",
        "m⃠e⃠r⃠a⃠ l⃠u⃠n⃠d⃠ k⃠e⃠ b⃠a⃠l⃠ u⃠t⃠h⃠",
        "k⃠i⃠d⃠e⃠e⃠ Z⃠i⃠n⃠d⃠a⃠ h⃠o⃠",
        "m⃠a⃠r⃠ n⃠y⃠ k⃠i⃠d⃠d⃠e⃠ t⃠y⃠p⃠e⃠ k⃠r⃠",
        "c⃠h⃠u⃠p⃠ b⃠k⃠l⃠",
        "b⃠c⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠i⃠ c⃠h⃠u⃠t⃠",
        "m⃠c⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ l⃠i⃠k⃠h⃠ f⃠a⃠s⃠t⃠",
        "f⃠a⃠s⃠t⃠ l⃠i⃠k⃠h⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠",
        "f⃠a⃠s⃠t⃠ l⃠i⃠k⃠h⃠ k⃠a⃠m⃠z⃠o⃠r⃠"
        "t⃠e⃠r⃠y⃠ m⃠a⃠k⃠i⃠ c⃠h⃠u⃠t⃠ c⃠l⃠a⃠i⃠m⃠ c⃠r⃠w⃠a⃠",
        "a⃠w⃠z⃠ n⃠i⃠c⃠h⃠e⃠ r⃠a⃠n⃠d⃠c⃠e⃠ k⃠e⃠ b⃠c⃠h⃠e⃠",
        "s⃠a⃠w⃠a⃠l⃠ n⃠y⃠ p⃠u⃠c⃠h⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠a⃠b⃠o⃠s⃠d⃠a⃠",
        "f⃠y⃠t⃠e⃠r⃠ b⃠n⃠e⃠g⃠a⃠ l⃠a⃠g⃠d⃠e⃠ m⃠a⃠d⃠r⃠c⃠h⃠o⃠d⃠",
        "o⃠y⃠e⃠ k⃠a⃠a⃠l⃠e⃠ r⃠o⃠ k⃠e⃠ d⃠i⃠k⃠h⃠a⃠",
        "o⃠y⃠e⃠ k⃠a⃠a⃠l⃠e⃠ r⃠o⃠o⃠ n⃠y⃠",
        "s⃠h⃠o⃠r⃠t⃠ n⃠y⃠ c⃠u⃠d⃠ t⃠u⃠ b⃠i⃠n⃠a⃠ r⃠u⃠k⃠e⃠",
        "s⃠h⃠o⃠r⃠t⃠ n⃠y⃠ c⃠u⃠d⃠ t⃠u⃠ a⃠p⃠n⃠i⃠ m⃠a⃠k⃠o⃠ l⃠e⃠k⃠r⃠",
        "t⃠e⃠r⃠y⃠ m⃠a⃠k⃠e⃠ s⃠t⃠h⃠ t⃠e⃠r⃠y⃠ b⃠h⃠e⃠n⃠ v⃠i⃠ c⃠u⃠d⃠w⃠a⃠ l⃠e⃠",
        "t⃠e⃠r⃠y⃠ m⃠a⃠k⃠e⃠ s⃠t⃠h⃠ t⃠e⃠r⃠y⃠ d⃠i⃠d⃠i⃠ v⃠i⃠ c⃠u⃠d⃠ g⃠a⃠i⃠",
        "C⃠h⃠a⃠t⃠ f⃠y⃠t⃠e⃠r⃠ b⃠n⃠e⃠g⃠a⃠ r⃠a⃠n⃠d⃠c⃠e⃠ c⃠o⃠d⃠u⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠o⃠",
        "b⃠o⃠l⃠ r⃠a⃠n⃠d⃠i⃠b⃠a⃠a⃠z⃠ d⃠a⃠d⃠d⃠y⃠ e⃠y⃠",
        "b⃠u⃠l⃠l⃠y⃠x⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ u⃠t⃠h⃠",
        "m⃠a⃠r⃠ m⃠a⃠r⃠k⃠e⃠ c⃠u⃠d⃠ r⃠h⃠a⃠ t⃠u⃠",
        "o⃠r⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ m⃠a⃠r⃠k⃠e⃠ c⃠u⃠d⃠ g⃠a⃠i⃠"
        "J⃠a⃠l⃠d⃠i⃠ l⃠i⃠k⃠h⃠ r⃠n⃠d⃠y⃠k⃠e⃠ b⃠e⃠j⃠",
        "O⃠r⃠ b⃠d⃠a⃠ l⃠i⃠k⃠h⃠ t⃠m⃠c⃠",
        "O⃠r⃠ b⃠d⃠a⃠ 2⃠ l⃠i⃠n⃠e⃠ w⃠l⃠a⃠ l⃠i⃠k⃠h⃠ t⃠m⃠k⃠c⃠",
        "O⃠r⃠ b⃠d⃠a⃠ o⃠y⃠e⃠ l⃠i⃠k⃠h⃠ t⃠m⃠l⃠",
        "T⃠e⃠r⃠i⃠ m⃠a⃠a⃠ k⃠a⃠ b⃠u⃠r⃠",
        "O⃠y⃠e⃠ k⃠e⃠e⃠d⃠e⃠",
        "R⃠a⃠n⃠d⃠i⃠ k⃠e⃠ l⃠a⃠d⃠k⃠e⃠",
        "J⃠a⃠l⃠d⃠i⃠ l⃠i⃠k⃠h⃠ t⃠e⃠r⃠i⃠ b⃠e⃠h⃠e⃠n⃠ c⃠h⃠o⃠d⃠u⃠",
        "M⃠k⃠l⃠ u⃠t⃠h⃠ r⃠a⃠n⃠d⃠i⃠ k⃠e⃠ b⃠a⃠c⃠c⃠h⃠e⃠",
        "T⃠e⃠r⃠i⃠ n⃠a⃠n⃠i⃠ m⃠e⃠r⃠i⃠ m⃠a⃠a⃠l⃠",
        "T⃠e⃠j⃠ l⃠i⃠k⃠h⃠ r⃠a⃠n⃠d⃠c⃠e⃠",
        "O⃠y⃠e⃠ m⃠a⃠a⃠k⃠e⃠ l⃠o⃠d⃠e⃠ m⃠r⃠e⃠n⃠g⃠a⃠",
        "T⃠e⃠r⃠i⃠ m⃠a⃠a⃠ c⃠h⃠o⃠d⃠y⃠",
        "T⃠e⃠r⃠i⃠ M⃠a⃠i⃠y⃠a⃠ k⃠i⃠ g⃠a⃠n⃠d⃠",
        "T⃠e⃠r⃠y⃠ d⃠a⃠d⃠i⃠ k⃠a⃠ f⃠u⃠d⃠d⃠a⃠",
        "M⃠k⃠l⃠ u⃠t⃠h⃠ b⃠e⃠h⃠e⃠n⃠c⃠o⃠d⃠",
        "T⃠e⃠r⃠i⃠ m⃠a⃠a⃠ k⃠i⃠ b⃠u⃠r⃠ d⃠e⃠",
        "T⃠e⃠r⃠y⃠ m⃠a⃠a⃠ k⃠a⃠ f⃠u⃠d⃠d⃠a⃠ m⃠e⃠ l⃠a⃠u⃠d⃠a⃠",
        "T⃠e⃠r⃠i⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠v⃠a⃠",
        "R⃠a⃠n⃠d⃠i⃠ k⃠e⃠ b⃠e⃠t⃠e⃠ m⃠a⃠r⃠ g⃠a⃠y⃠a⃠",
        "T⃠e⃠r⃠i⃠ m⃠a⃠a⃠ k⃠i⃠ c⃠h⃠u⃠t⃠ m⃠r⃠u⃠",
        "J⃠a⃠l⃠i⃠d⃠ k⃠r⃠ s⃠p⃠a⃠m⃠",
        "M⃠c⃠ s⃠p⃠a⃠m⃠ r⃠o⃠k⃠e⃠n⃠g⃠a⃠",
        "T⃠e⃠r⃠i⃠ m⃠a⃠a⃠k⃠i⃠ c⃠h⃠u⃠t⃠ s⃠p⃠a⃠m⃠ k⃠r⃠",
        "s⃠p⃠a⃠m⃠ k⃠r⃠.⃠m⃠a⃠a⃠k⃠e⃠ l⃠o⃠d⃠e⃠",
        "R⃠a⃠n⃠d⃠y⃠k⃠e⃠ c⃠h⃠o⃠d⃠e⃠ s⃠p⃠a⃠m⃠ k⃠r⃠ w⃠r⃠n⃠a⃠ c⃠u⃠d⃠ t⃠u⃠",
        "S⃠p⃠a⃠m⃠ k⃠r⃠ k⃠i⃠d⃠",
        "N⃠o⃠o⃠b⃠ t⃠e⃠r⃠i⃠ m⃠a⃠a⃠ c⃠h⃠o⃠d⃠u⃠",
        "R⃠n⃠d⃠y⃠k⃠e⃠ b⃠e⃠t⃠e⃠ m⃠a⃠r⃠ m⃠a⃠t⃠ t⃠u⃠",
        "N⃠o⃠o⃠b⃠ j⃠a⃠l⃠d⃠i⃠ l⃠i⃠k⃠h⃠ w⃠r⃠n⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠",
        "c⃠u⃠d⃠ g⃠a⃠i⃠ m⃠a⃠a⃠ t⃠e⃠r⃠y⃠ n⃠o⃠o⃠b⃠",
        "u⃠t⃠h⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ n⃠o⃠o⃠b⃠",
        "c⃠h⃠l⃠ c⃠u⃠d⃠k⃠e⃠ d⃠i⃠k⃠h⃠a⃠ n⃠o⃠o⃠b⃠",
        "j⃠l⃠d⃠i⃠ t⃠y⃠p⃠ c⃠r⃠ n⃠o⃠o⃠b⃠ h⃠a⃠l⃠k⃠e⃠",
        "c⃠u⃠d⃠ k⃠e⃠ p⃠g⃠l⃠ n⃠y⃠ h⃠o⃠ n⃠o⃠o⃠b⃠",
        "c⃠u⃠d⃠ c⃠u⃠d⃠ k⃠e⃠ r⃠a⃠n⃠d⃠ b⃠n⃠j⃠a⃠ t⃠u⃠ n⃠o⃠o⃠b⃠",
        "m⃠a⃠k⃠i⃠c⃠h⃠u⃠t⃠ t⃠e⃠r⃠y⃠ n⃠o⃠o⃠b⃠",
        "g⃠a⃠n⃠d⃠a⃠ c⃠y⃠u⃠ c⃠u⃠d⃠ r⃠h⃠a⃠ t⃠u⃠ ?",
        "i⃠t⃠n⃠a⃠ g⃠n⃠d⃠a⃠ n⃠y⃠ c⃠u⃠d⃠ a⃠c⃠h⃠e⃠ s⃠e⃠ c⃠u⃠d⃠",
        "M⃠a⃠a⃠n⃠ l⃠e⃠ c⃠u⃠d⃠ g⃠y⃠a⃠ t⃠u⃠ s⃠u⃠n⃠ b⃠a⃠t⃠ a⃠b⃠",
        "m⃠a⃠k⃠a⃠f⃠u⃠d⃠d⃠a⃠ f⃠a⃠t⃠ g⃠y⃠a⃠ t⃠e⃠r⃠y⃠ r⃠u⃠k⃠",
        ]
        br_texts = [
        "ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓅ᕗ ᕙ𝒷ᕗᕙ𝒽ᕗᕙ𝒾ᕗ ᕙ𝒷ᕗᕙ𝓃ᕗᕙ𝒶ᕗᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝓂ᕗᕙ𝓊ᕗᕙ𝒿ᕗᕙ𝑒ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝑒ᕗ",
        "ᕙ𝒯ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒶ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓅ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓏ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝓎ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝒹ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗᕙ𝒿ᕗᕙ𝒽ᕗᕙ𝑒ᕗ",
        "ᕙ𝒯ᕗᕙ𝓊ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙℳᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝒶ᕗ ᕙ𝓃ᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝓎ᕗᕙ𝓂ᕗᕙ𝓅ᕗᕙ𝒶ᕗᕙ𝓈ᕗᕙ𝓈ᕗ",
        "ᕙ𝒪ᕗᕙ𝓎ᕗᕙ𝑒ᕗ ᕙ𝓊ᕗᕙ𝓃ᕗᕙ𝒻ᕗᕙ𝓊ᕗᕙ𝓃ᕗᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝓈ᕗᕙ𝓌ᕗᕙ𝒾ᕗᕙ𝓅ᕗᕙ𝑒ᕗ ᕙ𝓂ᕗᕙ𝓉ᕗᕙ𝓉ᕗ ᕙ𝓀ᕗᕙ𝓇ᕗ",
        "ᕙ𝒪ᕗᕙ𝒽ᕗ ᕙ𝒽ᕗᕙ𝑒ᕗᕙ𝓁ᕗᕙ𝓁ᕗᕙ𝑜ᕗ ᕙ𝒷ᕗᕙ𝒾ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒶ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓅ᕗ ᕙ𝒷ᕗᕙ𝒾ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝑜ᕗᕙ𝓇ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝓋ᕗ ᕙ𝒷ᕗᕙ𝒾ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝒶ᕗᕙ𝓊ᕗᕙ𝓀ᕗᕙ𝒶ᕗᕙ𝓉ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗ ᕙ𝓇ᕗᕙ𝒽ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝓇ᕗ.",
        "ᕙ𝒪ᕗᕙ𝓎ᕗᕙ𝓎ᕗ ᕙ𝓀ᕗᕙ𝒾ᕗᕙ𝓃ᕗᕙ𝓃ᕗᕙ𝑒ᕗᕙ𝓇ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗᕙ𝒿ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙℊᕗᕙ𝒸ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗ ᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝑒ᕗ ᕙ𝓀ᕗᕙ𝒾ᕗ ᕙ𝓅ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓂ᕗᕙ𝒾ᕗᕙ𝓈ᕗᕙ𝓈ᕗᕙ𝒾ᕗᕙ𝑜ᕗᕙ𝓃ᕗ ᕙ𝓀ᕗᕙ𝒾ᕗᕙ𝓈ᕗᕙ𝓃ᕗᕙ𝑒ᕗ ᕙ𝒹ᕗᕙ𝒾ᕗ.",
        "ᕙ𝒞ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒽ᕗᕙ𝒶ᕗ",
        "ᕙ𝒞ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒽ᕗᕙ𝒶ᕗ ᕙ𝑒ᕗᕙ𝓀ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓇ᕗ.",
        "ᕙ𝒮ᕗᕙ𝓊ᕗᕙ𝓃ᕗ ᕙ𝒮ᕗᕙ𝓊ᕗᕙ𝓃ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝒶ᕗ.",
        "ᕙ𝒯ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒸ᕗᕙ𝒶ᕗ ᕙ𝒷ᕗᕙ𝒽ᕗᕙ𝑜ᕗᕙ𝓈ᕗᕙ𝒹ᕗᕙ𝒶ᕗ.",
        "ᕙ𝒪ᕗᕙ𝓎ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑜ᕗᕙ𝓉ᕗᕙ𝒾ᕗ ᕙ𝒿ᕗᕙ𝒶ᕗᕙ𝓉ᕗᕙ𝒾ᕗ ᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝓉ᕗᕙ𝓂ᕗᕙ𝓇ᕗ.",
        "ᕙ𝒦ᕗᕙ𝓎ᕗ? ᕙ𝒿ᕗᕙ𝓁ᕗᕙ𝒹ᕗᕙ𝒾ᕗ ᕙ𝓁ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒽ᕗ ᕙ𝓀ᕗᕙ𝒾ᕗᕙ𝒹ᕗᕙ𝒹ᕗᕙ𝑒ᕗ.",
        "ᕙℬᕗᕙ𝒾ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝒸ᕗᕙ𝑜ᕗᕙ𝓂ᕗ ᕙℊᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙℊᕗ ᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓅ᕗ ᕙ𝓀ᕗᕙ𝑜ᕗ ᕙ𝓉ᕗᕙ𝒶ᕗᕙℊᕗ ᕙ𝒸ᕗᕙ𝓇ᕗᕙ𝑒ᕗᕙℊᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ",
        "ᕙℳᕗᕙ𝓊ᕗᕙ𝒿ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝒷ᕗᕙ𝒾ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝓂ᕗᕙ𝓀ᕗᕙ𝒸ᕗ ᕙ𝒷ᕗᕙ𝓈ᕗ",
        "ᕙ𝒥ᕗᕙ𝒶ᕗᕙ𝓁ᕗᕙ𝒹ᕗᕙ𝒾ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓏ᕗ ᕙ𝓅ᕗᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝒶ᕗ ᕙ𝒷ᕗᕙ𝑜ᕗᕙ𝓁ᕗ",
        "ᕙ𝒮ᕗᕙ𝒾ᕗᕙ𝒹ᕗᕙ𝑒ᕗ ᕙ𝒽ᕗᕙ𝑜ᕗᕙ𝒿ᕗᕙ𝒶ᕗ ᕙ𝒷ᕗᕙ𝒾ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝒶ᕗᕙ𝒾ᕗ ᕙ𝒶ᕗᕙ𝒷ᕗ",
        "ᕙℋᕗᕙ𝓎ᕗᕙ𝑒ᕗ ᕙ𝓅ᕗᕙℊᕗᕙ𝓁ᕗ ᕙ𝒷ᕗᕙ𝒽ᕗᕙℊᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝓉ᕗ ᕙ𝒶ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗ",
        "ᕙ𝒷ᕗᕙ𝒽ᕗᕙℊᕗ ᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝒶ᕗᕙ𝒿ᕗᕙ𝒿ᕗ",
        "ᕙℋᕗᕙ𝓎ᕗᕙ𝑒ᕗ ᕙ𝓅ᕗᕙℊᕗᕙ𝓁ᕗ ᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒷ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙ𝒷ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙℊᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝓉ᕗ",
        "ᕙℋᕗᕙ𝓎ᕗᕙ𝑒ᕗ ᕙ𝒹ᕗᕙ𝓊ᕗᕙ𝓇ᕗ ᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓉ᕗᕙ𝓉ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒹ᕗᕙ𝒽ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑜ᕗᕙ𝒹ᕗ ᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑒ᕗ",
        "ᕙ𝓀ᕗᕙ𝑜ᕗᕙ𝒾ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝓉ᕗ ᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝑒ᕗᕙ𝓈ᕗᕙ𝓁ᕗᕙ𝒾ᕗᕙ𝓎ᕗᕙ𝑒ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒻ᕗ ᕙ𝒸ᕗᕙ𝓇ᕗ ᕙ𝓇ᕗᕙ𝒽ᕗᕙ𝒶ᕗ ᕙ𝒽ᕗᕙ𝓊ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗᕙ𝒿ᕗᕙ𝒽ᕗᕙ𝑒ᕗ",
        "ᕙ𝓀ᕗᕙ𝑜ᕗᕙ𝒾ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓉ᕗ ᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ𝒶ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒻ᕗᕙ𝒾ᕗ ᕙ𝒹ᕗᕙ𝑒ᕗ ᕙ𝒹ᕗᕙ𝓊ᕗᕙ𝓃ᕗᕙℊᕗᕙ𝒶ᕗ",
        "ᕙ𝒜ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ??ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒻ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒾ᕗᕙ𝓁ᕗ ᕙ𝒿ᕗᕙ𝒶ᕗᕙ𝓎ᕗᕙ𝑒ᕗᕙℊᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗᕙ𝒿ᕗᕙ𝒽ᕗᕙ𝑒ᕗ",
        "ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝓉ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝓊ᕗᕙ𝒿ᕗᕙ𝑒ᕗ ᕙ𝓈ᕗᕙ𝓌ᕗᕙ𝒾ᕗᕙ𝓅ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝓇ᕗᕙ𝓀ᕗᕙ𝑒ᕗ",
        "ᕙ𝒜ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝓈ᕗᕙ𝓌ᕗᕙ𝒾ᕗᕙ𝓅ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝓇ᕗᕙ𝓀ᕗᕙ𝑒ᕗ",
        "ᕙℱᕗᕙ𝓇ᕗ ᕙ𝒷ᕗᕙ𝑜ᕗᕙ𝓁ᕗᕙ𝓃ᕗᕙ𝒶ᕗ ᕙ𝓃ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝒾ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ𝒶ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝓈ᕗᕙ𝓌ᕗᕙ𝒾ᕗᕙ𝓅ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝓇ᕗᕙ𝓀ᕗᕙ𝑒ᕗ",
        "ᕙ𝒞ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝓎ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ𝓅ᕗᕙ𝓇ᕗ ᕙ𝓀ᕗᕙ𝑒ᕗᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝓎ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ",
        "ᕙ𝓂ᕗᕙ𝓊ᕗᕙ𝒿ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙ𝓅ᕗᕙ𝓉ᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝒽ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝒶ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ𝓂ᕗᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝓉ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝓎ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗ",
        "ᕙ𝓁ᕗᕙ𝑜ᕗᕙ𝒹ᕗᕙ𝑒ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝓊ᕗᕙ𝓉ᕗᕙ𝓇ᕗ ᕙ𝓂ᕗᕙ𝒸ᕗ",
        "ᕙ𝓁ᕗᕙ𝓊ᕗᕙ𝓃ᕗ ᕙ𝓂ᕗᕙ𝓉ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓈ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒶ᕗ",
        "ᕙ𝓃ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒶ᕗᕙ𝓁ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒹ᕗᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝒹ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗ ᕙ𝑜ᕗᕙ𝓎ᕗᕙ𝑒ᕗ ᕙℊᕗᕙ𝒶ᕗᕙ𝓈ᕗᕙ𝒽ᕗᕙ𝓉ᕗᕙ𝒾ᕗ ᕙ𝓀ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑒ᕗ",
        "ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝓀ᕗᕙ𝒾ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓉ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝓀ᕗᕙ𝑒ᕗ",
        "ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ",
        "ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗ ᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓉ᕗᕙ𝒽ᕗ ᕙ𝓉ᕗᕙ𝑜ᕗᕙ𝒹ᕗᕙ𝒽ᕗ ᕙ𝓀ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝑒ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓅ᕗ ᕙ𝓀ᕗ ᕙ𝓂ᕗᕙ𝓊ᕗᕙ𝒽ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗ ᕙ𝒻ᕗᕙ𝒶ᕗᕙ𝓈ᕗᕙ𝒶ᕗᕙ𝒹ᕗᕙ𝓊ᕗᕙ𝓃ᕗᕙℊᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝓀ᕗᕙ𝑒ᕗ",
        "ᕙ𝓁ᕗᕙ𝑒ᕗᕙ𝒶ᕗᕙ𝓋ᕗᕙ𝑒ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝓅ᕗᕙ𝒶ᕗᕙ𝓈ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗ ᕙ𝓃ᕗᕙ𝒶ᕗᕙ𝒾ᕗ ᕙ𝒶ᕗᕙ??ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗᕙ𝓀ᕗᕙ𝑜ᕗ",
        "ᕙ𝓁ᕗᕙ𝑒ᕗᕙ𝒶ᕗᕙ𝓋ᕗᕙ𝑒ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒾ᕗᕙ𝒹ᕗᕙ𝑒ᕗᕙ𝓇ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ",
        "ᕙ𝓁ᕗᕙ𝑒ᕗᕙ𝒶ᕗᕙ𝓋ᕗᕙ𝑒ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝒿ᕗᕙ𝓁ᕗᕙ𝒹ᕗᕙ𝒾ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝓌ᕗᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝒶ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ𝓁ᕗᕙ𝑒ᕗᕙ𝒶ᕗᕙ𝓋ᕗᕙ𝑒ᕗ ᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗᕙℊᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ𝒮ᕗᕙ𝓂ᕗᕙ𝒿ᕗᕙ𝒽ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝓉ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗᕙ𝒶ᕗᕙ𝓋ᕗᕙ𝑒ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗ",
        "ᕙ𝒻ᕗᕙ𝒶ᕗᕙ𝓈ᕗᕙ𝓉ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗᕙ𝒶ᕗᕙ𝓋ᕗᕙ𝑒ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝓀ᕗᕙ𝒶ᕗᕙ𝓂ᕗᕙ𝒿ᕗᕙ𝑜ᕗᕙ𝓇ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝓀ᕗᕙ𝑒ᕗ",
        "ᕙ𝓉ᕗᕙ𝓊ᕗᕙ𝓉ᕗᕙ𝑜ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝓀ᕗ",
        "ᕙ𝑜ᕗᕙ𝓎ᕗ ᕙ𝒽ᕗᕙ𝒾ᕗᕙ𝒿ᕗᕙ𝒹ᕗᕙ𝑒ᕗ ᕙ𝓀ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝒽ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝒶ᕗᕙ𝓂ᕗᕙ𝓏ᕗᕙ𝑜ᕗᕙ𝓇ᕗ",
        "ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝓀ᕗᕙ𝑜ᕗ ᕙ𝒾ᕗᕙ𝓁ᕗᕙ𝓎ᕗ ᕙ𝓇ᕗᕙ𝑒ᕗᕙ𝓎ᕗ 🌚😂",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓅ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙ𝓉ᕗᕙ𝓂ᕗᕙ𝓀ᕗᕙ𝒸ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓅ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ𝒶ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ",
        "ᕙ𝓈ᕗᕙ𝒽ᕗᕙ𝒾ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ𝒶ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓅ᕗ",
        "ᕙ𝒻ᕗᕙ𝓇ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ??ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓅ᕗ",
        "ᕙ𝓈ᕗᕙ𝒽ᕗᕙ𝒾ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝓁ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒽ᕗ ᕙ𝓌ᕗᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝒶ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝓊ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝒶ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓅ᕗ",
        "ᕙ𝓅ᕗᕙ𝓇ᕗᕙ𝑜ᕗᕙ𝑜ᕗᕙ𝒻ᕗ ᕙ𝒸ᕗᕙ𝓇ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝓎ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ𝓅ᕗᕙ𝓇ᕗᕙ𝑜ᕗᕙ𝑜ᕗᕙ𝒻ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ",
        "ᕙ𝓅ᕗᕙ𝓇ᕗᕙ𝑜ᕗᕙ𝑜ᕗᕙ𝒻ᕗ ᕙ𝒽ᕗᕙ𝑜ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓀ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝒾ᕗᕙ𝓁ᕗᕙ𝓁ᕗᕙ𝒶ᕗᕙ𝓇ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗ ᕙ𝒷ᕗᕙ𝑜ᕗᕙ𝓈ᕗᕙ𝒹ᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ??ᕗᕙ𝓎ᕗ ᕙ𝒽ᕗᕙ𝒾ᕗᕙ𝒿ᕗᕙ𝒹ᕗᕙ𝑒ᕗ ᕙ𝓀ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝒽ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝒶ᕗᕙ𝓂ᕗᕙ𝓏ᕗᕙ𝑜ᕗᕙ𝓇ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒹ᕗᕙ𝓇ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑜ᕗᕙ𝒹ᕗ ?",
        "ᕙ𝒶ᕗᕙ𝒷ᕗ ᕙ𝓉ᕗᕙ𝓀ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝓎ᕗᕙ𝒾ᕗ ᕙ𝒽ᕗᕙ𝑜ᕗᕙℊᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ?",
        "ᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗ ᕙ𝓀ᕗᕙ𝓊ᕗᕙ𝒸ᕗᕙ𝒽ᕗ ᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝒿ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝓉ᕗᕙ𝒶ᕗ ᕙ𝒷ᕗᕙ𝓈ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ",
        "ᕙ𝒮ᕗᕙ𝒷ᕗᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝓅ᕗᕙ𝒽ᕗᕙ𝑒ᕗᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝑜ᕗ ᕙ𝒷ᕗᕙ𝑜ᕗᕙ𝓁ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓃ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝒶ᕗᕙ𝓂ᕗ ᕙ𝓀ᕗᕙ𝓇ᕗᕙ𝑒ᕗ",
        "ᕙ𝓎ᕗᕙ𝒶ᕗᕙ𝒽ᕗᕙ𝒶ᕗ ᕙ𝒷ᕗᕙ𝒽ᕗᕙ𝒾ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝒸ᕗᕙ𝑒ᕗ ᕙ𝓅ᕗᕙ𝒾ᕗᕙ𝓁ᕗᕙ𝓁ᕗᕙ𝑒ᕗ",
        "ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝓀ᕗᕙ𝒶ᕗᕙ𝒷ᕗᕙ𝑜ᕗᕙ𝓈ᕗᕙ𝒹ᕗᕙ𝒶ᕗ",
        "ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑜ᕗ ᕙ𝒷ᕗᕙ𝒽ᕗᕙ𝑒ᕗᕙ𝓃ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝑒ᕗᕙℊᕗᕙ𝒾ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝓉ᕗᕙ𝑜ᕗᕙ𝓂ᕗᕙ𝓂ᕗᕙ𝓎ᕗ",
        "ᕙ𝓃ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒶ᕗᕙ𝓁ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒹ᕗᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝒹ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝓎ᕗᕙ𝒽ᕗᕙ𝒶ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ",
        "ᕙ𝒸ᕗᕙ𝑜ᕗᕙ𝓏ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒽ᕗᕙ𝒾ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒾ᕗ ᕙ𝒽ᕗᕙ𝑒ᕗ",
        "ᕙ𝓃ᕗᕙ𝓎ᕗᕙ𝓉ᕗᕙ𝑜ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓅ᕗ ᕙ𝒷ᕗᕙ𝑜ᕗᕙ𝓁ᕗ ᕙ𝓂ᕗᕙ𝓊ᕗᕙ𝒿ᕗᕙ𝒽ᕗᕙ𝑒ᕗ",
        "ᕙ𝓃ᕗᕙ𝓎ᕗᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒽ᕗᕙ𝑜ᕗᕙℊᕗᕙ𝒾ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝒾ᕗ ᕙ𝒿ᕗᕙ𝑜ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ𝒶ᕗᕙ𝓉ᕗᕙ𝒾ᕗ ᕙ𝒿ᕗᕙ𝑜ᕗᕙℊᕗᕙ𝒾ᕗ",
        "ᕙ𝓉ᕗᕙ𝓇ᕗᕙ𝓎ᕗ ᕙ𝒶ᕗᕙ𝓂ᕗᕙ𝓂ᕗᕙ𝒾ᕗ ᕙ𝒸ᕗᕙ𝑒ᕗ ᕙ𝒷ᕗᕙ𝒽ᕗᕙ𝑜ᕗᕙ𝓈ᕗᕙ𝒹ᕗᕙ𝑒ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗ ᕙ𝑒ᕗᕙ𝓂ᕗᕙ𝑜ᕗᕙ𝒿ᕗᕙ𝒾ᕗ ᕙ𝒹ᕗᕙ𝒶ᕗᕙ𝓁ᕗ ᕙ𝓂ᕗᕙ𝒸ᕗ",
        "ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ? ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓂ᕗᕙ𝓇ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝓎ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ?",
        "ᕙ𝓉ᕗᕙ𝓂ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝒽ᕗᕙ𝑜ᕗᕙℊᕗᕙ𝒾ᕗ ᕙ𝒻ᕗᕙ𝓇ᕗᕙ𝓇ᕗᕙ𝓉ᕗᕙ𝑜ᕗ",
        "ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ? ᕙ𝓀ᕗᕙ𝒷ᕗ ? ᕙ𝓅ᕗᕙℊᕗᕙ𝓁ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓀ᕗᕙ𝑒ᕗᕙ𝓀ᕗ",
        "ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ᕙ𝓈ᕗᕙ𝒸ᕗᕙ𝒽ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝓅ᕗᕙℊᕗᕙ𝓁ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ𝒶ᕗ ᕙ𝓁ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗᕙ𝓃ᕗᕙ𝑒ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ",
        "ᕙ𝒾ᕗᕙ𝓉ᕗᕙ𝓃ᕗᕙ𝒶ᕗ ᕙ𝓈ᕗᕙ𝒸ᕗᕙ𝒽ᕗ ᕙ𝓃ᕗᕙ??ᕗ ᕙ𝒷ᕗᕙ𝑜ᕗᕙ𝓁ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝒶ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ𝓈ᕗᕙ𝒸ᕗᕙ𝒽ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝓅ᕗᕙℊᕗᕙ𝓁ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ𝒶ᕗ ᕙ𝓁ᕗᕙ𝒾ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝑒ᕗ ᕙ𝓈ᕗᕙ𝓉ᕗᕙ𝒽ᕗ",
        "ᕙ𝓂ᕗᕙ𝓉ᕗᕙ𝓁ᕗᕙ𝒷ᕗ ᕙ𝓉ᕗᕙ𝓂ᕗᕙ𝓇ᕗ",
        "ᕙ𝓃ᕗᕙ𝓎ᕗᕙ𝓉ᕗᕙ𝑜ᕗ",
        "ᕙ𝓅ᕗᕙ𝓊ᕗᕙ𝓇ᕗᕙ𝒶ᕗ ᕙ𝓁ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒽ᕗ ᕙ𝓂ᕗᕙ𝒸ᕗ",
        "ᕙ𝓉ᕗᕙ𝓂ᕗᕙ𝓇ᕗ ᕙ𝒻ᕗᕙ𝓇ᕗᕙ𝓇ᕗᕙ𝓉ᕗᕙ𝑜ᕗ",
        "ᕙ𝑜ᕗᕙ𝒽ᕗ ᕙ𝑜ᕗᕙ𝓀ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝒻ᕗᕙ𝒾ᕗᕙ𝓇ᕗ",
        "ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝒶ᕗ ᕙ𝒹ᕗᕙ𝒶ᕗᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒹ᕗ",
        "ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ? ᕙ𝒶ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝓁ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙ𝓅ᕗᕙ𝑒ᕗᕙ𝒽ᕗᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝑒ᕗᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑒ᕗ",
        "ᕙ𝓃ᕗᕙ𝓎ᕗᕙ𝓉ᕗᕙ𝑜ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑜ᕗᕙ𝒹ᕗᕙ𝓃ᕗᕙ𝑒ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗ ᕙ𝓋ᕗᕙ𝓎ᕗᕙ𝒶ᕗᕙ𝓈ᕗᕙ𝓉ᕗ ᕙ𝒽ᕗᕙ𝓊ᕗ",
        "ᕙ𝓃ᕗᕙ𝓎ᕗᕙ𝓉ᕗᕙ𝑜ᕗ ᕙ𝓅ᕗᕙℊᕗᕙ𝓁ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝓊ᕗᕙ𝒸ᕗᕙ𝒽ᕗ ᕙ𝒷ᕗᕙ𝒾ᕗ",
        "ᕙ𝑜ᕗᕙ𝓎ᕗᕙ𝑒ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ? ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝓎ᕗᕙ𝒶ᕗ ?",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙ𝓂ᕗᕙ𝓉ᕗ ᕙ𝒽ᕗᕙ𝓈ᕗᕙ𝓈ᕗ",
        "ᕙ𝓎ᕗᕙ𝓊ᕗᕙ𝓇ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝑜ᕗᕙ𝓂ᕗ",
        "ᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝑒ᕗ ᕙ𝓈ᕗᕙ𝒷ᕗᕙ𝓀ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝒾ᕗ ᕙ𝑜ᕗᕙ𝓇ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝒷ᕗᕙ𝒾ᕗ",
        "ᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝑒ᕗ ᕙ𝒾ᕗᕙ𝒹ᕗᕙ𝒶ᕗᕙ𝓇ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝑒ᕗᕙ𝓀ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓇ᕗ",
        "ᕙ𝓉ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝓇ᕗᕙ𝒽ᕗ",
        "ᕙ𝑒ᕗᕙ𝓀ᕗ ᕙ𝓁ᕗᕙ𝒾ᕗᕙ𝓃ᕗᕙ𝑒ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗ ᕙ𝓉ᕗᕙ𝓂ᕗᕙ𝓇ᕗ",
        "ᕙ𝒬ᕗ",
        "ᕙ𝑜ᕗᕙ𝒸ᕗᕙ𝓎ᕗ ᕙ𝒶ᕗᕙ𝒷ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓁ᕗᕙ𝑒ᕗ",
        "ᕙ𝓅ᕗᕙ𝑒ᕗᕙ𝒽ᕗᕙ𝑒ᕗᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑜ᕗᕙ𝒹ᕗᕙ𝓊ᕗ",
        "ᕙ𝓃ᕗᕙ𝓎ᕗᕙ𝓉ᕗᕙ𝑜ᕗ",
        "ᕙ𝓆ᕗ ?",
        "ᕙ𝒽ᕗᕙ𝓎ᕗᕙ𝓎ᕗᕙ𝓎ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒶ᕗ ᕙ𝑒ᕗᕙ𝓀ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓇ᕗ",
        "ᕙ𝑜ᕗᕙ𝓎ᕗᕙ𝑒ᕗᕙ𝑒ᕗ ᕙ𝓈ᕗᕙ𝓊ᕗᕙ𝓃ᕗ ᕙ𝒹ᕗᕙ𝑜ᕗᕙ𝓈ᕗᕙ𝓉ᕗ ᕙ𝓉ᕗᕙ𝓂ᕗᕙ𝓇ᕗ",
        "ᕙ𝒷ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙℊᕗ ᕙ𝒿ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝒻ᕗ ᕙ𝒸ᕗᕙ𝓇ᕗᕙ𝓇ᕗ ᕙ𝒹ᕗᕙ𝓊ᕗᕙ𝓃ᕗᕙℊᕗᕙ𝒶ᕗ",
        "ᕙ𝑜ᕗᕙ𝓎ᕗᕙ𝑒ᕗᕙ𝑒ᕗ ᕙ𝓅ᕗᕙℊᕗᕙ𝓁ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝒾ᕗ ᕙ𝒾ᕗᕙ𝒹ᕗᕙ𝒶ᕗᕙ𝓇ᕗ ᕙ𝒶ᕗᕙ𝒶ᕗ",
        "ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝓂ᕗᕙ𝓇ᕗ ᕙ𝒻ᕗᕙ𝓇ᕗᕙ𝓇ᕗᕙ𝓉ᕗᕙ𝑜ᕗ",
        "ᕙ𝑜ᕗᕙ𝓎ᕗᕙ𝑒ᕗᕙ𝑒ᕗ ᕙ𝒾ᕗᕙ𝒹ᕗᕙ𝒶ᕗᕙ𝓇ᕗ ᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓂ᕗᕙ𝓇ᕗ",
        "ᕙ𝓃ᕗᕙ𝓎ᕗᕙ𝓉ᕗᕙ𝑜ᕗ ᕙ𝒶ᕗᕙ𝑒ᕗᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝒽ᕗᕙ𝒾ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗ",
        "ᕙ𝑜ᕗᕙ𝓎ᕗᕙ𝑒ᕗᕙ𝑒ᕗ ᕙ𝒽ᕗᕙ𝓎ᕗᕙ𝓎ᕗ ᕙ𝒶ᕗᕙ𝒾ᕗᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝒽ᕗᕙ𝒾ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗᕙ𝓃ᕗᕙ𝒶ᕗ",
        "ᕙ𝑜ᕗᕙ𝓇ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒶ᕗ ᕙ𝑜ᕗᕙ𝓇ᕗ",
        "ᕙ𝒽ᕗᕙ𝓎ᕗᕙ𝓎ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝑜ᕗ ᕙ𝓃ᕗᕙ𝒶ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝑜ᕗ ᕙ𝓂ᕗᕙ𝓉ᕗ ᕙ𝒷ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙℊᕗ ᕙ𝒿ᕗᕙ𝒶ᕗᕙ𝑜ᕗ",
        "ᕙ𝒷ᕗᕙ𝓎ᕗᕙ𝓎ᕗᕙ𝑒ᕗᕙ𝑒ᕗ ᕙ𝒽ᕗᕙ𝓎ᕗᕙ𝓎ᕗ ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ?",
        "ᕙ𝒬ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙ𝒬ᕗ ᕙ𝓇ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙ𝒽ᕗᕙ𝑜ᕗ ?",
        "ᕙ𝓅ᕗᕙℊᕗᕙ𝓁ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝒸ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙ𝓂ᕗᕙ𝓉ᕗ",
        ]
        br2_texts = [
        "⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇮​⋰⋰🇮​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇰​⋰⋰🇦​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇸​⋰⋰🇪​⋰⋰🇼​⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇮​⋰⋰🇰​⋰⋰🇪​⋰⋰🇧​⋰⋰🇦​⋰⋰🇨​⋰⋰🇭​⋰⋰🇪​⋰, ⋰🇹​⋰⋰🇺​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇮​⋰ ⋰🇰​⋰⋰🇮​⋰⋰🇸​⋰⋰🇸​⋰⋰🇦​⋰⋰🇬​⋰⋰🇦​⋰",
        "⋰🇦​⋰⋰🇦​⋰⋰🇯​⋰ ⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇮​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇰​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇹​⋰, ⋰🇹​⋰⋰🇺​⋰ ⋰🇰​⋰⋰🇾​⋰⋰🇦​⋰ ⋰🇭​⋰⋰🇦​⋰⋰🇮​⋰",
        "⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇩​⋰⋰🇷​⋰⋰🇨​⋰⋰🇭​⋰⋰🇴​⋰⋰🇩​⋰, ⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇮​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇰​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇹​⋰",
        "⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇮​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇪​⋰⋰🇳​⋰ ⋰🇰​⋰⋰🇮​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇹​⋰, ⋰🇹​⋰⋰🇺​⋰ ⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇮​⋰",
        "⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇩​⋰ ⋰🇯​⋰⋰🇦​⋰, ⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇮​⋰ ⋰🇩​⋰⋰🇮​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇮​⋰",
        "⋰🇸​⋰⋰🇱​⋰⋰🇴​⋰⋰🇼​⋰, ⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇮​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇮​⋰⋰🇾​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇮​⋰⋰🇴​⋰⋰🇩​⋰⋰🇺​⋰",
        "⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰, ⋰🇹​⋰⋰🇺​⋰ ⋰🇰​⋰⋰🇾​⋰⋰🇦​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇸​⋰⋰🇰​⋰⋰🇹​⋰⋰🇦​⋰",
        "⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇰​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰, ⋰🇹​⋰⋰🇲​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇴​⋰⋰🇩​⋰⋰🇺​⋰",
        "⋰🇸​⋰⋰🇱​⋰⋰🇴​⋰⋰🇼​⋰ ⋰🇫​⋰⋰🇮​⋰⋰🇷​⋰⋰🇸​⋰⋰🇪​⋰, ⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇮​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇰​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇹​⋰",
        "⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇬​⋰⋰🇷​⋰⋰🇮​⋰⋰🇧​⋰, ⋰🇹​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇲​⋰⋰🇦​⋰ ⋰🇩​⋰⋰🇴​⋰⋰🇺​⋰",
        "⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇨​⋰⋰🇴​⋰⋰🇩​⋰⋰🇺​⋰, ⋰🇳​⋰⋰🇪​⋰⋰🇹​⋰ ⋰🇴​⋰⋰🇳​⋰ ⋰🇴​⋰⋰🇫​⋰⋰🇫​⋰ ⋰🇼​⋰⋰🇦​⋰⋰🇱​⋰⋰🇮​⋰ ⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰",
        "⋰🇴​⋰⋰🇾​⋰⋰🇪​⋰ ⋰🇹​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇲​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇴​⋰⋰🇩​⋰⋰🇺​⋰, ⋰🇮​⋰⋰🇩​⋰⋰🇭​⋰⋰🇦​⋰⋰🇷​⋰ ⋰🇦​⋰⋰🇦​⋰⋰🇰​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰",
        "⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇷​⋰⋰🇩​⋰⋰🇺​⋰, ⋰🇴​⋰⋰🇮​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇦​⋰⋰🇰​⋰⋰🇪​⋰ ⋰🇱​⋰⋰🇴​⋰⋰🇩​⋰⋰🇪​⋰⋰🇪​⋰",
        "⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇪​⋰⋰🇯​⋰, ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇴​⋰⋰🇩​⋰⋰🇺​⋰",
        "⋰🇸​⋰⋰🇺​⋰⋰🇦​⋰⋰🇷​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇪​⋰⋰🇯​⋰, ⋰🇳​⋰⋰🇪​⋰⋰🇹​⋰ ⋰🇴​⋰⋰🇫​⋰⋰🇫​⋰ ⋰🇴​⋰⋰🇳​⋰ ⋰🇰​⋰⋰🇷​⋰ ⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰ ⋰🇱​⋰⋰🇦​⋰⋰🇩​⋰⋰🇰​⋰⋰🇪​⋰",
        "⋰🇹​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇲​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇰​⋰⋰🇪​⋰⋰🇸​⋰⋰🇪​⋰, ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇵​⋰ ⋰🇸​⋰⋰🇱​⋰⋰🇴​⋰⋰🇼​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇩​⋰⋰🇭​⋰⋰🇦​⋰⋰🇷​⋰⋰🇨​⋰⋰🇴​⋰⋰🇩​⋰",
        "⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇨​⋰⋰🇴​⋰⋰🇩​⋰⋰🇺​⋰ ⋰🇰​⋰⋰🇷​⋰ ⋰🇲​⋰⋰🇸​⋰⋰🇬​⋰ ⋰🇩​⋰⋰🇪​⋰⋰🇱​⋰⋰🇪​⋰⋰🇹​⋰⋰🇪​⋰, ⋰🇴​⋰⋰🇮​⋰ ⋰🇸​⋰⋰🇺​⋰⋰🇦​⋰⋰🇷​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇱​⋰⋰🇦​⋰⋰🇩​⋰⋰🇰​⋰⋰🇪​⋰",
        "⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇫​⋰⋰🇺​⋰⋰🇫​⋰⋰🇮​⋰, ⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇩​⋰⋰🇮​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇩​⋰⋰🇮​⋰",
        "⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇩​⋰⋰🇮​⋰⋰🇰​⋰⋰🇭​⋰⋰🇦​⋰, ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰ ⋰🇦​⋰⋰🇧​⋰",
        "⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰, ⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇰​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰",
        "⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇱​⋰⋰🇪​⋰ ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇷​⋰⋰🇺​⋰, ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇱​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇱​⋰⋰🇪​⋰ ⋰🇬​⋰⋰🇷​⋰⋰🇮​⋰⋰🇧​⋰",
        "⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇭​⋰⋰🇪​⋰⋰🇳​⋰ ⋰🇻​⋰⋰🇪​⋰⋰🇸​⋰⋰🇮​⋰⋰🇾​⋰⋰🇦​⋰⋰🇦​⋰ ⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇮​⋰, ⋰🇮​⋰⋰🇹​⋰⋰🇳​⋰⋰🇦​⋰ ⋰🇬​⋰⋰🇳​⋰⋰🇩​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇩​⋰⋰🇦​⋰ ⋰🇹​⋰⋰🇺​⋰ ⋰🇫​⋰⋰🇮​⋰⋰🇷​⋰⋰🇸​⋰⋰🇪​⋰ ⋰🇳​⋰⋰🇪​⋰⋰🇹​⋰ ⋰🇴​⋰⋰🇳​⋰ ⋰🇴​⋰⋰🇫​⋰⋰🇫​⋰",
        "⋰🇬​⋰⋰🇷​⋰⋰🇮​⋰⋰🇧​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇹​⋰⋰🇪​⋰, ⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇯​⋰⋰🇦​⋰ ⋰🇱​⋰⋰🇴​⋰⋰🇩​⋰⋰🇪​⋰ ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇷​⋰⋰🇺​⋰ ⋰🇩​⋰⋰🇺​⋰⋰??​⋰⋰🇬​⋰⋰🇦​⋰",
        "⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇷​⋰⋰🇩​⋰⋰🇺​⋰⋰🇳​⋰⋰🇬​⋰⋰🇦​⋰⋰🇦​⋰, ⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰",
        "⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰, ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇾​⋰ ⋰🇨​⋰⋰🇵​⋰",
        "⋰🇨​⋰⋰🇵​⋰ ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇭​⋰⋰🇭​⋰, ⋰🇨​⋰⋰🇵​⋰ ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇱​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇭​⋰",
        "⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰ ⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰, ⋰🇦​⋰⋰🇧​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰ ⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰",
        "⋰🇩​⋰⋰🇴​⋰⋰🇺​⋰⋰🇧​⋰⋰🇱​⋰⋰🇪​⋰ ⋰🇸​⋰⋰🇪​⋰⋰🇳​⋰⋰🇩​⋰ ⋰🇰​⋰⋰🇴​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇨​⋰⋰🇴​⋰⋰🇩​⋰⋰🇺​⋰, ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇨​⋰⋰🇴​⋰⋰🇩​⋰ ⋰🇩​⋰⋰🇺​⋰⋰🇳​⋰⋰🇬​⋰⋰🇦​⋰ ⋰🇦​⋰⋰🇦​⋰⋰🇯​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇭​⋰⋰🇭​⋰",
        "⋰🇭​⋰⋰🇹​⋰ ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇩​⋰⋰🇦​⋰⋰🇱​⋰⋰🇦​⋰⋰🇱​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇹​⋰⋰🇪​⋰., ⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰ ⋰🇯​⋰⋰🇱​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇯​⋰⋰🇱​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇶​⋰ ⋰🇹​⋰⋰??​⋰⋰🇾​⋰⋰🇲​⋰⋰🇦​⋰",
        "⋰🇵​⋰⋰🇦​⋰⋰🇷​⋰⋰🇦​⋰ ⋰🇱​⋰⋰🇮​⋰⋰🇰​⋰⋰🇭​⋰⋰🇪​⋰⋰🇬​⋰⋰🇦​⋰.., ⋰🇹​⋰⋰🇷​⋰⋰🇦​⋰ ⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇭​⋰⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇰​⋰",
        "⋰🇱​⋰⋰🇦​⋰⋰🇬​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇱​⋰⋰🇦​⋰⋰🇩​⋰⋰🇨​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰, ⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰ ⋰🇱​⋰⋰🇦​⋰⋰🇬​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇹​⋰⋰🇪​⋰..",
        "⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇰​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰, ⋰🇧​⋰⋰🇭​⋰⋰🇮​⋰⋰🇰​⋰⋰🇦​⋰⋰🇷​⋰⋰🇮​⋰ ⋰🇱​⋰⋰🇺​⋰⋰🇳​⋰⋰🇩​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇸​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇷​⋰⋰🇦​⋰.",
        "⋰🇱​⋰⋰🇴​⋰⋰🇼​⋰ ⋰🇱​⋰⋰🇪​⋰⋰🇻​⋰⋰🇪​⋰⋰🇱​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇨​⋰⋰🇷​⋰, ⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰ ⋰🇱​⋰⋰🇴​⋰⋰🇼​⋰ ⋰🇱​⋰⋰🇪​⋰⋰🇻​⋰⋰🇪​⋰⋰🇱​⋰ ⋰🇼​⋰⋰🇪​⋰⋰🇦​⋰⋰🇰​⋰",
        "⋰🇲​⋰⋰🇪​⋰⋰🇷​⋰⋰🇪​⋰ ⋰🇱​⋰⋰🇺​⋰⋰🇳​⋰⋰🇩​⋰ ⋰🇵​⋰⋰🇪​⋰ ⋰🇪​⋰⋰🇾​⋰ ⋰🇹​⋰⋰🇺​⋰ ⋰🇭​⋰⋰🇮​⋰⋰🇯​⋰⋰🇩​⋰⋰🇪​⋰, ⋰🇫​⋰⋰🇷​⋰⋰🇪​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇼​⋰⋰🇦​⋰ ⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇰​⋰⋰🇴​⋰",
        "⋰🇫​⋰⋰🇷​⋰⋰🇪​⋰⋰🇪​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇾​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰ ⋰🇹​⋰⋰🇺​⋰ ⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰, ⋰🇹​⋰⋰🇺​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇮​⋰ ⋰🇰​⋰⋰🇮​⋰ ⋰🇰​⋰⋰🇾​⋰⋰🇦​⋰ ⋰🇭​⋰⋰🇦​⋰⋰🇮​⋰",
        "⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇰​⋰⋰🇮​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇹​⋰ ⋰🇨​⋰⋰🇱​⋰⋰🇦​⋰⋰🇮​⋰⋰🇲​⋰ ⋰🇨​⋰⋰🇷​⋰⋰🇼​⋰⋰🇦​⋰, ⋰🇹​⋰⋰🇺​⋰ ⋰🇰​⋰⋰🇾​⋰⋰🇦​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇮​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇸​⋰⋰🇰​⋰⋰🇹​⋰⋰🇦​⋰",
        "⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇪​⋰⋰🇳​⋰ ⋰🇻​⋰⋰🇪​⋰⋰🇸​⋰⋰🇮​⋰⋰🇾​⋰⋰🇦​⋰⋰🇦​⋰ ⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇮​⋰, ⋰🇹​⋰⋰🇺​⋰ ⋰🇰​⋰⋰🇾​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇩​⋰ ⋰🇯​⋰⋰🇦​⋰",
        "⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇩​⋰⋰🇮​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇩​⋰⋰🇮​⋰, ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇩​⋰⋰🇮​⋰⋰🇰​⋰⋰🇭​⋰⋰🇦​⋰",
        "⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰ ⋰🇦​⋰⋰🇧​⋰, ⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰",
        "⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇰​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰, ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇱​⋰⋰🇪​⋰ ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇷​⋰⋰🇺​⋰",
        "⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇱​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇱​⋰⋰🇪​⋰ ⋰🇬​⋰⋰🇷​⋰⋰??​⋰⋰🇧​⋰, ⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇭​⋰⋰🇪​⋰⋰🇳​⋰ ⋰🇻​⋰⋰🇪​⋰⋰🇸​⋰⋰🇮​⋰⋰🇾​⋰⋰🇦​⋰⋰🇦​⋰ ⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇮​⋰",
        "⋰🇮​⋰⋰🇹​⋰⋰🇳​⋰⋰🇦​⋰ ⋰🇬​⋰⋰🇳​⋰⋰🇩​⋰⋰??​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇩​⋰⋰🇦​⋰ ⋰🇹​⋰⋰🇺​⋰ ⋰🇫​⋰⋰🇮​⋰⋰🇷​⋰⋰🇸​⋰⋰🇪​⋰ ⋰🇳​⋰⋰🇪​⋰⋰🇹​⋰ ⋰🇴​⋰⋰🇳​⋰ ⋰🇴​⋰⋰🇫​⋰⋰🇫​⋰, ⋰🇬​⋰⋰🇷​⋰⋰🇮​⋰⋰🇧​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇹​⋰⋰🇪​⋰",
        "⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇯​⋰⋰🇦​⋰ ⋰🇱​⋰⋰🇴​⋰⋰🇩​⋰⋰🇪​⋰ ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇷​⋰⋰🇺​⋰ ⋰🇩​⋰⋰🇺​⋰⋰🇳​⋰⋰🇬​⋰⋰🇦​⋰, ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇷​⋰⋰🇩​⋰⋰🇺​⋰⋰🇳​⋰⋰🇬​⋰⋰🇦​⋰⋰🇦​⋰",
        "⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰, ⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰",
        "⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇾​⋰ ⋰🇨​⋰⋰🇵​⋰, ⋰🇨​⋰⋰🇵​⋰ ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇭​⋰⋰🇭​⋰",
        "⋰🇨​⋰⋰🇵​⋰ ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇱​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇭​⋰, ⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰ ⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰",
        "⋰🇦​⋰⋰🇧​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰ ⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰, ⋰🇩​⋰⋰🇴​⋰⋰🇺​⋰⋰🇧​⋰⋰🇱​⋰⋰🇪​⋰ ⋰🇸​⋰⋰🇪​⋰⋰🇳​⋰⋰🇩​⋰ ⋰🇰​⋰⋰🇴​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇨​⋰⋰🇴​⋰⋰🇩​⋰⋰🇺​⋰",
        "⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇨​⋰⋰🇴​⋰⋰🇩​⋰ ⋰🇩​⋰⋰🇺​⋰⋰🇳​⋰⋰🇬​⋰⋰🇦​⋰ ⋰🇦​⋰⋰🇦​⋰⋰🇯​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇭​⋰⋰🇭​⋰, ⋰🇭​⋰⋰🇹​⋰ ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇩​⋰⋰🇦​⋰⋰🇱​⋰⋰🇦​⋰⋰🇱​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇹​⋰⋰🇪​⋰.",
        "⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰ ⋰🇯​⋰⋰🇱​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇯​⋰⋰🇱​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇶​⋰ ⋰🇹​⋰⋰🇷​⋰⋰🇾​⋰⋰🇲​⋰⋰🇦​⋰, ⋰🇵​⋰⋰🇦​⋰⋰🇷​⋰⋰🇦​⋰ ⋰🇱​⋰⋰🇮​⋰⋰🇰​⋰⋰🇭​⋰⋰🇪​⋰⋰🇬​⋰⋰🇦​⋰..",
        "⋰🇹​⋰⋰🇷​⋰⋰🇦​⋰ ⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇭​⋰⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇰​⋰, ⋰🇱​⋰⋰🇦​⋰⋰🇬​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇱​⋰⋰🇦​⋰⋰🇩​⋰⋰🇨​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰",
        "⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰ ⋰🇱​⋰⋰🇦​⋰⋰🇬​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇹​⋰⋰🇪​⋰.., ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇰​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰",
        "⋰🇧​⋰⋰🇭​⋰⋰🇮​⋰⋰🇰​⋰⋰🇦​⋰⋰🇷​⋰⋰🇮​⋰ ⋰🇱​⋰⋰🇺​⋰⋰🇳​⋰⋰🇩​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇸​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇷​⋰⋰🇦​⋰., ⋰🇱​⋰⋰🇴​⋰⋰🇼​⋰ ⋰🇱​⋰⋰🇪​⋰⋰🇻​⋰⋰🇪​⋰⋰🇱​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇨​⋰⋰🇷​⋰",
        "⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰ ⋰🇱​⋰⋰🇴​⋰⋰🇼​⋰ ⋰🇱​⋰⋰🇪​⋰⋰🇻​⋰⋰🇪​⋰⋰🇱​⋰ ⋰🇼​⋰⋰🇪​⋰⋰🇦​⋰⋰🇰​⋰, ⋰🇲​⋰⋰🇪​⋰⋰🇷​⋰⋰🇪​⋰ ⋰🇱​⋰⋰🇺​⋰⋰🇳​⋰⋰🇩​⋰ ⋰🇵​⋰⋰🇪​⋰ ⋰🇪​⋰⋰🇾​⋰ ⋰🇹​⋰⋰🇺​⋰ ⋰🇭​⋰⋰🇮​⋰⋰🇯​⋰⋰🇩​⋰⋰🇪​⋰",
        "⋰🇫​⋰⋰🇷​⋰⋰🇪​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇼​⋰⋰🇦​⋰ ⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰??​⋰⋰🇦​⋰⋰🇰​⋰⋰🇴​⋰, ⋰🇫​⋰⋰🇷​⋰⋰🇪​⋰⋰🇪​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇾​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰ ⋰🇹​⋰⋰🇺​⋰ ⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰",
        "⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇰​⋰⋰🇮​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇹​⋰ ⋰🇨​⋰⋰🇱​⋰⋰🇦​⋰⋰🇮​⋰⋰🇲​⋰ ⋰🇨​⋰⋰🇷​⋰⋰🇼​⋰⋰🇦​⋰, ⋰🇹​⋰⋰🇺​⋰ ⋰🇰​⋰⋰🇾​⋰⋰🇦​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇮​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇸​⋰⋰🇰​⋰⋰🇹​⋰⋰🇦​⋰",
        "⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇪​⋰⋰🇳​⋰ ⋰🇻​⋰⋰🇪​⋰⋰🇸​⋰⋰🇮​⋰⋰🇾​⋰⋰🇦​⋰⋰🇦​⋰ ⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇮​⋰, ⋰🇹​⋰⋰🇺​⋰ ⋰🇰​⋰⋰🇾​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇩​⋰ ⋰🇯​⋰⋰🇦​⋰"
        "⋰🇧⋰⋰🇭⋰⋰🇴⋰⋰🇸⋰⋰🇩⋰⋰🇮⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇫⋰⋰🇦⋰⋰🇹⋰⋰🇮⋰ ⋰🇭⋰⋰🇦⋰⋰🇮⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇭⋰⋰🇴⋰⋰🇯⋰⋰🇦⋰",
        "⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰ ⋰🇯⋰⋰🇦⋰⋰🇾⋰⋰🇪⋰⋰🇬⋰⋰🇮⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇧⋰⋰🇭⋰⋰🇮⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇭⋰⋰🇦⋰⋰🇮⋰",
        "⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇴⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇫⋰⋰🇮⋰⋰🇷⋰⋰🇸⋰⋰🇪⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇬⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰ ⋰🇫⋰⋰🇦⋰⋰🇩⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇳⋰⋰🇦⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇲⋰⋰🇦⋰⋰🇷⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰??⋰⋰🇪⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇨⋰⋰🇭⋰⋰🇦⋰⋰🇵⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰ ⋰🇩⋰⋰🇮⋰⋰🇩⋰⋰🇮⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇫⋰⋰🇦⋰⋰🇩⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇧⋰⋰🇭⋰⋰🇮⋰⋰🇰⋰⋰🇦⋰⋰🇷⋰⋰🇮⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇱⋰⋰🇦⋰⋰🇩⋰⋰🇰⋰⋰🇪⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰",
        "⋰🇳⋰⋰🇪⋰⋰🇹⋰ ⋰🇴⋰⋰🇫⋰⋰🇫⋰ ⋰🇰⋰⋰🇷⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰, ⋰🇹⋰⋰🇧⋰⋰🇰⋰⋰🇨⋰ ⋰🇨⋰⋰🇴⋰⋰🇩⋰⋰🇺⋰ ⋰🇰⋰⋰🇷⋰ ⋰🇲⋰⋰🇸⋰⋰🇬⋰ ⋰🇩⋰⋰🇪⋰⋰🇱⋰⋰🇪⋰⋰🇹⋰⋰🇪⋰",
        "⋰🇴⋰⋰🇾⋰⋰🇪⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⋰🇰⋰⋰🇪⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇴⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰",
        "⋰🇹⋰⋰??⋰⋰🇰⋰⋰🇨⋰ ⋰🇲⋰⋰🇦⋰⋰🇷⋰⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇫⋰⋰🇦⋰⋰🇹⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰",
        "⋰🇸⋰⋰🇱⋰⋰🇴⋰⋰🇼⋰ ⋰🇫⋰⋰🇮⋰⋰🇷⋰⋰🇸⋰⋰🇪⋰ ⋰🇧⋰⋰🇭⋰⋰🇮⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰ ⋰🇯⋰⋰🇦⋰⋰🇾⋰⋰🇪⋰⋰🇬⋰⋰🇮⋰",
        "⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇬⋰⋰🇷⋰⋰🇮⋰⋰🇧⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰, ⋰🇹⋰⋰🇷⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇩⋰⋰🇴⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇳⋰⋰🇦⋰",
        "⋰🇹⋰⋰🇧⋰⋰🇰⋰⋰🇨⋰ ⋰🇨⋰⋰🇴⋰⋰🇩⋰⋰🇺⋰ ⋰🇵⋰⋰🇺⋰⋰🇷⋰⋰🇦⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇧⋰⋰🇪⋰⋰🇨⋰⋰🇭⋰ ⋰🇩⋰⋰🇴⋰",
        "⋰🇴⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇪⋰ ⋰🇱⋰⋰🇴⋰⋰🇩⋰⋰🇪⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰",
        "⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰ ⋰🇧⋰⋰🇪⋰⋰🇪⋰⋰🇯⋰, ⋰🇹⋰⋰🇲⋰⋰🇰⋰⋰🇨⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰⋰🇺⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇰⋰⋰🇴⋰",
        "⋰🇸⋰⋰🇺⋰⋰🇦⋰⋰🇷⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇧⋰⋰🇪⋰⋰🇪⋰⋰🇯⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇧⋰⋰🇦⋰⋰🇩⋰⋰🇮⋰ ⋰🇭⋰⋰🇦⋰⋰🇮⋰",
        "⋰🇹⋰⋰🇷⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇮⋰ ⋰🇰⋰⋰🇪⋰⋰🇸⋰⋰🇪⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇴⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇫⋰⋰🇮⋰⋰🇷⋰⋰🇸⋰⋰🇪⋰",
        "⋰🇹⋰⋰🇧⋰⋰🇰⋰⋰🇨⋰ ⋰🇨⋰⋰🇴⋰⋰🇩⋰⋰🇺⋰ ⋰🇰⋰⋰🇷⋰ ⋰🇲⋰⋰🇸⋰⋰🇬⋰ ⋰🇩⋰⋰🇪⋰⋰🇱⋰⋰🇪⋰⋰🇹⋰⋰🇪⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰",
        "⋰🇴⋰⋰🇮⋰ ⋰🇸⋰⋰🇺⋰⋰🇦⋰⋰🇷⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇱⋰⋰🇦⋰⋰🇩⋰⋰🇰⋰⋰🇪⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰",
        "⋰🇹⋰⋰🇺⋰ ⋰🇧⋰⋰🇭⋰⋰🇮⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇭⋰⋰🇦⋰⋰🇮⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇯⋰⋰🇦⋰⋰🇾⋰⋰🇪⋰⋰🇬⋰⋰🇮⋰",
        "⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇯⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇱⋰⋰🇪⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇬⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰ ⋰🇫⋰⋰🇦⋰⋰🇩⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇸⋰⋰🇱⋰⋰🇴⋰⋰🇼⋰ ⋰🇹⋰⋰🇾⋰⋰🇵⋰⋰🇪⋰⋰🇷⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰??⋰ ⋰🇧⋰⋰🇭⋰⋰🇴⋰⋰🇸⋰⋰🇩⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇦⋰⋰🇦⋰⋰🇯⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇬⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰ ⋰🇲⋰⋰🇪⋰⋰🇮⋰⋰🇳⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇸⋰⋰🇰⋰⋰🇹⋰⋰🇦⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇲⋰⋰🇦⋰⋰🇩⋰⋰🇷⋰⋰🇨⋰⋰🇴⋰⋰🇩⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇩⋰⋰🇮⋰⋰🇩⋰⋰🇮⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇫⋰⋰🇦⋰⋰🇩⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇧⋰⋰🇭⋰⋰🇮⋰⋰🇰⋰⋰🇦⋰⋰🇷⋰⋰🇮⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇱⋰⋰🇦⋰⋰🇩⋰⋰🇰⋰⋰🇪⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰",
        "⋰🇳⋰⋰🇪⋰⋰🇹⋰ ⋰🇴⋰⋰🇫⋰⋰🇫⋰ ⋰🇰⋰⋰🇷⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰, ⋰🇹⋰⋰🇧⋰⋰🇰⋰⋰🇨⋰ ⋰🇨⋰⋰🇴⋰⋰🇩⋰⋰🇺⋰ ⋰🇰⋰⋰🇷⋰ ⋰🇲⋰⋰🇸⋰⋰🇬⋰ ⋰🇩⋰⋰🇪⋰⋰🇱⋰⋰🇪⋰⋰🇹⋰⋰🇪⋰",
        "⋰🇴⋰⋰🇾⋰⋰🇪⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⋰🇰⋰⋰🇪⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇴⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰",
        "⋰🇹⋰⋰🇲⋰⋰🇰⋰⋰🇨⋰ ⋰🇲⋰⋰🇦⋰⋰🇷⋰⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇫⋰⋰🇦⋰⋰🇹⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰",
        "⋰🇸⋰⋰🇱⋰⋰🇴⋰⋰🇼⋰ ⋰??⋰⋰🇮⋰⋰🇷⋰⋰🇸⋰⋰🇪⋰ ⋰🇧⋰⋰🇭⋰⋰🇮⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰ ⋰🇯⋰⋰🇦⋰⋰🇾⋰⋰🇪⋰⋰🇬⋰⋰🇮⋰",
        "⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇬⋰⋰🇷⋰⋰🇮⋰⋰🇧⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰, ⋰🇹⋰⋰🇷⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇩⋰⋰🇴⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇳⋰⋰🇦⋰",
        "⋰🇹⋰⋰🇧⋰⋰🇰⋰⋰🇨⋰ ⋰🇨⋰⋰🇴⋰⋰🇩⋰⋰🇺⋰ ⋰🇵⋰⋰🇺⋰⋰🇷⋰⋰🇦⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇧⋰⋰🇪⋰⋰🇨⋰⋰🇭⋰ ⋰🇩⋰⋰🇴⋰",
        "⋰🇴⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇪⋰ ⋰🇱⋰⋰🇴⋰⋰🇩⋰⋰🇪⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰",
        "⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰ ⋰🇧⋰⋰🇪⋰⋰🇪⋰⋰🇯⋰, ⋰🇹⋰⋰🇲⋰⋰🇰⋰⋰🇨⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰⋰🇺⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇰⋰⋰🇴⋰",
        "⋰🇸⋰⋰🇺⋰⋰🇦⋰⋰🇷⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇧⋰⋰🇪⋰⋰🇪⋰⋰🇯⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇧⋰⋰🇦⋰⋰🇩⋰⋰🇮⋰ ⋰🇭⋰⋰🇦⋰⋰🇮⋰",
        "⋰🇹⋰⋰🇷⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇮⋰ ⋰🇰⋰⋰🇪⋰⋰🇸⋰⋰🇪⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇴⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇫⋰⋰🇮⋰⋰🇷⋰⋰🇸⋰⋰🇪⋰",
        "⋰🇹⋰⋰🇧⋰⋰🇰⋰⋰🇨⋰ ⋰🇨⋰⋰🇴⋰⋰🇩⋰⋰🇺⋰ ⋰🇰⋰⋰🇷⋰ ⋰🇲⋰⋰🇸⋰⋰🇬⋰ ⋰🇩⋰⋰🇪⋰⋰🇱⋰⋰🇪⋰⋰🇹⋰⋰🇪⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰",
        "⋰🇴⋰⋰🇮⋰ ⋰🇸⋰⋰🇺⋰⋰🇦⋰⋰🇷⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇱⋰⋰🇦⋰⋰🇩⋰⋰🇰⋰⋰🇪⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰",
        "⋰🇹⋰⋰🇺⋰ ⋰🇧⋰⋰🇭⋰⋰🇮⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇭⋰⋰🇦⋰⋰🇮⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇯⋰⋰🇦⋰⋰🇾⋰⋰🇪⋰⋰🇬⋰⋰🇮⋰",
        "⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇯⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇱⋰⋰🇪⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇬⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰ ⋰🇫⋰⋰🇦⋰⋰🇩⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇸⋰⋰🇱⋰⋰🇴⋰⋰🇼⋰ ⋰🇹⋰⋰🇾⋰⋰🇵⋰⋰🇪⋰⋰🇷⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇧⋰⋰🇭⋰⋰🇴⋰⋰🇸⋰⋰🇩⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇦⋰⋰🇦⋰⋰🇯⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇰⋰⋰??⋰ ⋰🇬⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰ ⋰🇲⋰⋰🇪⋰⋰🇮⋰⋰🇳⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇸⋰⋰🇰⋰⋰🇹⋰⋰🇦⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇲⋰⋰🇦⋰⋰🇩⋰⋰🇷⋰⋰🇨⋰⋰🇴⋰⋰🇩⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇩⋰⋰🇮⋰⋰🇩⋰⋰🇮⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇫⋰⋰🇦⋰⋰🇩⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇧⋰⋰🇭⋰⋰🇮⋰⋰🇰⋰⋰🇦⋰⋰🇷⋰⋰🇮⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇱⋰⋰🇦⋰⋰🇩⋰⋰🇰⋰⋰🇪⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰"
        "⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇵⋰ ⋰🇧⋰⋰🇭⋰⋰🇮⋰ ⋰🇧⋰⋰🇳⋰⋰🇦⋰⋰🇱⋰⋰🇪⋰ ⋰🇲⋰⋰🇺⋰⋰🇯⋰⋰🇪⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⋰🇰⋰⋰🇪⋰",
        "⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇦⋰ ⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇵⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇿⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇾⋰⋰🇦⋰⋰🇦⋰⋰🇩⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇹⋰⋰🇺⋰⋰🇯⋰⋰🇭⋰⋰🇪⋰",
        "⋰🇹⋰⋰🇺⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇦⋰ ⋰🇳⋰⋰🇦⋰ ⋰🇹⋰⋰🇾⋰⋰🇲⋰⋰🇵⋰⋰🇦⋰⋰🇸⋰⋰🇸⋰",
        "⋰🇴⋰⋰🇾⋰⋰🇪⋰ ⋰🇺⋰⋰🇳⋰⋰🇫⋰⋰🇺⋰⋰🇳⋰⋰🇳⋰⋰🇾⋰ ⋰🇸⋰⋰🇼⋰⋰🇮⋰⋰🇵⋰⋰🇪⋰ ⋰🇲⋰⋰🇹⋰⋰🇹⋰ ⋰🇰⋰⋰🇷⋰",
        "⋰🇴⋰⋰🇭⋰ ⋰🇭⋰⋰🇪⋰⋰🇱⋰⋰🇱⋰⋰🇴⋰ ⋰🇧⋰⋰🇮⋰⋰🇭⋰⋰🇦⋰⋰🇷⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇦⋰ ⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇵⋰ ⋰🇧⋰⋰🇮⋰⋰🇭⋰⋰🇦⋰⋰🇷⋰⋰🇮⋰ ⋰🇴⋰⋰🇷⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇻⋰ ⋰🇧⋰⋰🇮⋰⋰🇭⋰⋰🇦⋰⋰🇷⋰⋰🇮⋰ ⋰🇦⋰⋰🇺⋰⋰🇰⋰⋰🇦⋰⋰🇹⋰ ⋰🇲⋰⋰🇪⋰ ⋰🇷⋰⋰🇭⋰⋰🇦⋰ ⋰🇰⋰⋰🇷⋰.",
        "⋰🇴⋰⋰🇾⋰⋰🇾⋰ ⋰🇰⋰⋰🇮⋰⋰🇳⋰⋰🇳⋰⋰🇪⋰⋰🇷⋰ ⋰🇹⋰⋰🇺⋰⋰🇯⋰⋰🇭⋰⋰🇪⋰ ⋰🇬⋰⋰🇨⋰ ⋰🇲⋰⋰🇪⋰ ⋰🇦⋰⋰🇦⋰⋰🇳⋰⋰🇪⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇵⋰⋰🇪⋰⋰🇷⋰⋰🇲⋰⋰🇮⋰⋰🇸⋰⋰🇸⋰⋰🇮⋰⋰🇴⋰⋰🇳⋰ ⋰🇰⋰⋰🇮⋰⋰🇸⋰⋰🇳⋰⋰🇪⋰ ⋰🇩⋰⋰🇮⋰.",
        "⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇰⋰⋰🇪⋰ ⋰🇩⋰⋰🇮⋰⋰🇰⋰⋰🇭⋰⋰🇦⋰",
        "⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇰⋰⋰🇪⋰ ⋰🇩⋰⋰🇮⋰⋰🇰⋰⋰🇭⋰⋰🇦⋰ ⋰🇪⋰⋰🇰⋰ ⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇷⋰.",
        "⋰🇸⋰⋰🇺⋰⋰🇳⋰ ⋰🇸⋰⋰🇺⋰⋰🇳⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇦⋰.",
        "⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰??⋰ ⋰🇲⋰⋰🇦⋰⋰🇨⋰⋰🇦⋰ ⋰🇧⋰⋰🇭⋰⋰🇴⋰⋰🇸⋰⋰🇩⋰⋰🇦⋰.",
        "⋰🇴⋰⋰🇾⋰⋰🇪⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇹⋰⋰🇮⋰ ⋰🇯⋰⋰🇦⋰⋰🇹⋰⋰🇮⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇹⋰⋰🇲⋰⋰🇷⋰.",
        "⋰🇰⋰⋰🇾⋰? ⋰🇯⋰⋰🇱⋰⋰🇩⋰⋰🇮⋰ ⋰🇱⋰⋰🇮⋰⋰🇰⋰⋰🇭⋰ ⋰🇰⋰⋰🇮⋰⋰🇩⋰⋰🇩⋰⋰🇪⋰.",
        "⋰🇧⋰⋰🇮⋰⋰🇭⋰⋰🇦⋰⋰🇷⋰⋰🇮⋰ ⋰🇨⋰⋰🇴⋰⋰🇲⋰ ⋰🇬⋰⋰🇦⋰⋰🇳⋰⋰🇬⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇵⋰ ⋰🇰⋰⋰🇴⋰ ⋰🇹⋰⋰🇦⋰⋰🇬⋰ ⋰🇨⋰⋰🇷⋰⋰🇪⋰⋰🇬⋰⋰🇦⋰ ⋰🇹⋰⋰🇺⋰",
        "⋰🇲⋰⋰🇺⋰⋰🇯⋰⋰🇭⋰⋰🇪⋰ ⋰🇨⋰⋰🇾⋰⋰🇦⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇧⋰⋰🇮⋰⋰🇭⋰⋰🇦⋰⋰🇷⋰⋰🇮⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇹⋰⋰🇲⋰⋰🇰⋰⋰🇨⋰ ⋰🇧⋰⋰🇸⋰",
        "⋰🇯⋰⋰🇦⋰⋰🇱⋰⋰🇩⋰⋰🇮⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇿⋰ ⋰🇵⋰⋰🇦⋰⋰🇵⋰⋰🇦⋰ ⋰🇧⋰⋰🇴⋰⋰🇱⋰",
        "⋰🇸⋰⋰🇮⋰⋰🇩⋰⋰🇪⋰ ⋰🇭⋰⋰🇴⋰⋰🇯⋰⋰🇦⋰ ⋰🇧⋰⋰🇮⋰⋰🇭⋰⋰🇦⋰⋰🇷⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇦⋰⋰🇮⋰ ⋰🇦⋰⋰🇧⋰",
        "⋰🇭⋰⋰🇾⋰⋰🇪⋰ ⋰🇵⋰⋰🇬⋰⋰🇱⋰ ⋰🇧⋰⋰🇭⋰⋰🇬⋰ ⋰🇲⋰⋰🇦⋰⋰🇹⋰ ⋰🇦⋰⋰🇨⋰⋰🇭⋰⋰🇪⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰",
        "⋰🇧⋰⋰🇭⋰⋰🇬⋰ ⋰🇳⋰⋰🇾⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇦⋰⋰🇯⋰⋰🇯⋰",
        "⋰🇭⋰⋰🇾⋰⋰🇪⋰ ⋰🇵⋰⋰🇬⋰⋰🇱⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇧⋰⋰🇨⋰⋰🇭⋰⋰🇪⋰ ⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇲⋰⋰🇦⋰⋰🇹⋰",
        "⋰🇭⋰⋰🇾⋰⋰🇪⋰ ⋰🇩⋰⋰🇺⋰⋰🇷⋰ ⋰🇭⋰⋰🇦⋰⋰🇹⋰⋰🇹⋰ ⋰🇲⋰⋰🇦⋰⋰🇩⋰⋰🇭⋰⋰🇦⋰⋰🇷⋰⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇧⋰⋰🇦⋰⋰🇨⋰⋰🇭⋰⋰🇪⋰",
        "⋰🇰⋰⋰🇴⋰⋰🇮⋰ ⋰🇧⋰⋰🇦⋰⋰🇹⋰ ⋰🇳⋰⋰🇾⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇪⋰⋰🇸⋰⋰🇱⋰⋰🇮⋰⋰🇾⋰⋰🇪⋰ ⋰🇲⋰⋰🇦⋰⋰🇫⋰ ⋰🇨⋰⋰🇷⋰ ⋰🇷⋰⋰🇭⋰⋰🇦⋰ ⋰🇭⋰⋰🇺⋰ ⋰🇹⋰⋰🇺⋰⋰🇯⋰⋰🇭⋰⋰🇪⋰",
        "⋰🇰⋰⋰🇴⋰⋰🇮⋰ ⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇹⋰ ⋰🇳⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇲⋰⋰🇦⋰⋰🇫⋰⋰🇮⋰ ⋰🇩⋰⋰🇪⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇦⋰⋰🇨⋰⋰🇭⋰⋰🇪⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇲⋰⋰🇦⋰⋰🇫⋰⋰🇮⋰ ⋰🇲⋰⋰🇮⋰⋰🇱⋰ ⋰🇯⋰⋰🇦⋰⋰🇾⋰⋰🇪⋰⋰🇬⋰⋰🇮⋰ ⋰🇹⋰⋰🇺⋰⋰🇯⋰⋰🇭⋰⋰🇪⋰",
        "⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇲⋰⋰🇦⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇦⋰ ⋰🇲⋰⋰🇺⋰⋰🇯⋰⋰🇪⋰ ⋰🇸⋰⋰🇼⋰⋰🇮⋰⋰🇵⋰⋰🇪⋰ ⋰🇨⋰⋰🇷⋰⋰🇰⋰⋰🇪⋰",
        "⋰🇦⋰⋰🇨⋰⋰🇭⋰⋰🇪⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇸⋰⋰🇼⋰⋰🇮⋰⋰🇵⋰⋰🇪⋰ ⋰🇨⋰⋰🇷⋰⋰🇰⋰⋰🇪⋰",
        "⋰🇫⋰⋰🇷⋰ ⋰🇧⋰⋰🇴⋰⋰🇱⋰⋰🇳⋰⋰🇦⋰ ⋰🇳⋰⋰🇦⋰ ⋰??⋰⋰🇮⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇱⋰⋰🇪⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇸⋰⋰🇼⋰⋰🇮⋰⋰🇵⋰⋰🇪⋰ ⋰🇨⋰⋰🇷⋰⋰🇰⋰⋰🇪⋰",
        "⋰🇨⋰⋰🇾⋰⋰🇦⋰ ⋰🇭⋰⋰🇺⋰⋰🇦⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰",
        "⋰🇵⋰⋰🇷⋰ ⋰🇰⋰⋰🇪⋰⋰🇸⋰⋰🇪⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰",
        "⋰🇲⋰⋰🇺⋰⋰🇯⋰⋰🇭⋰⋰🇪⋰ ⋰🇵⋰⋰🇹⋰⋰🇦⋰ ⋰🇹⋰⋰🇭⋰⋰🇦⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇦⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰",
        "⋰🇲⋰⋰🇪⋰⋰🇾⋰ ⋰🇳⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰⋰🇳⋰⋰🇹⋰⋰🇦⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰",
        "⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰",
        "⋰🇱⋰⋰🇴⋰⋰🇩⋰⋰🇪⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇺⋰⋰🇹⋰⋰🇷⋰ ⋰🇲⋰⋰??⋰",
        "⋰🇱⋰⋰🇺⋰⋰🇳⋰ ⋰🇲⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇸⋰ ⋰🇲⋰⋰🇪⋰⋰🇷⋰⋰🇦⋰",
        "⋰🇳⋰⋰🇮⋰⋰🇰⋰⋰🇦⋰⋰🇱⋰ ⋰🇲⋰⋰🇦⋰⋰🇩⋰⋰🇦⋰⋰🇷⋰⋰🇨⋰⋰🇭⋰⋰🇩⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇴⋰⋰🇾⋰⋰🇪⋰ ⋰🇬⋰⋰🇦⋰⋰🇸⋰⋰🇭⋰⋰🇹⋰⋰🇮⋰ ⋰🇰⋰ ⋰🇧⋰⋰🇦⋰⋰🇨⋰⋰🇭⋰⋰🇪⋰",
        "⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇮⋰⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰",
        "⋰🇲⋰⋰🇦⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰",
        "⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇰⋰ ⋰🇭⋰⋰🇦⋰⋰🇹⋰⋰🇭⋰ ⋰🇹⋰⋰🇴⋰⋰🇩⋰⋰🇭⋰ ⋰🇰⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇪⋰ ⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇵⋰ ⋰🇰⋰ ⋰🇲⋰⋰🇺⋰⋰🇭⋰ ⋰🇲⋰⋰🇪⋰ ⋰🇫⋰⋰🇦⋰⋰🇸⋰⋰🇦⋰⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰",
        "⋰🇱⋰⋰🇪⋰⋰🇦⋰⋰??⋰⋰🇪⋰ ⋰🇱⋰⋰🇪⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰ ⋰🇵⋰⋰🇦⋰⋰🇸⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰ ⋰🇳⋰⋰🇦⋰⋰🇮⋰ ⋰🇦⋰⋰🇾⋰⋰🇦⋰ ⋰🇲⋰⋰🇪⋰⋰🇰⋰⋰🇴⋰",
        "⋰🇱⋰⋰🇪⋰⋰🇦⋰⋰🇻⋰⋰🇪⋰ ⋰🇱⋰⋰🇪⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰ ⋰🇮⋰⋰🇩⋰⋰🇪⋰⋰🇷⋰ ⋰🇸⋰⋰🇪⋰",
        "⋰🇱⋰⋰🇪⋰⋰🇦⋰⋰🇻⋰⋰🇪⋰ ⋰🇱⋰⋰🇪⋰ ⋰🇯⋰⋰🇱⋰⋰🇩⋰⋰🇮⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇼⋰⋰🇷⋰⋰🇳⋰⋰🇦⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇦⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰",
        "⋰🇱⋰⋰🇪⋰⋰🇦⋰⋰🇻⋰⋰🇪⋰ ⋰🇳⋰⋰🇾⋰ ⋰🇱⋰⋰🇪⋰⋰🇬⋰⋰🇦⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰",
        "⋰🇸⋰⋰🇲⋰⋰🇯⋰⋰🇭⋰ ⋰🇧⋰⋰🇦⋰⋰🇹⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰ ⋰🇱⋰⋰🇪⋰⋰🇦⋰⋰🇻⋰⋰🇪⋰ ⋰🇱⋰⋰🇪⋰",
        "⋰🇫⋰⋰🇦⋰⋰🇸⋰⋰🇹⋰ ⋰🇱⋰⋰🇪⋰⋰🇦⋰⋰🇻⋰⋰🇪⋰ ⋰🇱⋰⋰🇪⋰ ⋰🇰⋰⋰🇦⋰⋰🇲⋰⋰🇯⋰⋰🇴⋰⋰🇷⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰",
        "⋰🇹⋰⋰🇺⋰⋰🇹⋰⋰🇴⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰",
        "⋰🇴⋰⋰🇾⋰ ⋰🇭⋰⋰🇮⋰⋰🇯⋰⋰🇩⋰⋰🇪⋰ ⋰🇰⋰⋰🇭⋰⋰🇦⋰⋰🇳⋰⋰🇦⋰ ⋰🇰⋰⋰🇭⋰⋰🇦⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇦⋰⋰🇦⋰ ⋰🇰⋰⋰🇦⋰⋰🇲⋰⋰🇿⋰⋰🇴⋰⋰🇷⋰",
        "⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇴⋰ ⋰🇮⋰⋰🇱⋰⋰🇾⋰ ⋰🇷⋰⋰🇪⋰⋰🇾",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇨⋰⋰🇭⋰⋰🇦⋰⋰🇵⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇹⋰⋰🇲⋰⋰🇰⋰⋰🇨⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰⋰🇨⋰⋰🇭⋰⋰🇦⋰⋰🇵⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇹⋰⋰🇺⋰",
        "⋰🇸⋰⋰🇭⋰⋰🇮⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰⋰🇨⋰⋰🇭⋰⋰🇦⋰⋰🇵⋰",
        "⋰🇫⋰⋰🇷⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰??⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰⋰🇨⋰⋰🇭⋰⋰🇦⋰⋰🇵⋰",
        "⋰🇸⋰⋰🇭⋰⋰🇮⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇱⋰⋰🇮⋰⋰🇰⋰⋰🇭⋰ ⋰🇼⋰⋰🇷⋰⋰🇳⋰⋰🇦⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇦⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰",
        "⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇾⋰⋰🇺⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇦⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰⋰🇨⋰⋰🇭⋰⋰🇦⋰⋰🇵⋰",
        "⋰🇵⋰⋰🇷⋰⋰🇴⋰⋰🇴⋰⋰🇫⋰ ⋰🇨⋰⋰🇷⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰",
        "⋰🇵⋰⋰🇷⋰⋰🇴⋰⋰🇴⋰⋰🇫⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰ ⋰🇪⋰⋰🇾⋰",
        "⋰🇵⋰⋰🇷⋰⋰🇴⋰⋰🇴⋰⋰🇫⋰ ⋰🇭⋰⋰🇴⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇰⋰⋰🇦⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇨⋰⋰🇭⋰⋰🇮⋰⋰🇱⋰⋰🇱⋰⋰🇦⋰⋰🇷⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇰⋰ ⋰🇧⋰⋰🇴⋰⋰🇸⋰⋰🇩⋰⋰🇦⋰ ⋰🇹⋰⋰🇪⋰⋰??⋰⋰🇾⋰",
        "⋰🇴⋰⋰🇾⋰ ⋰🇭⋰⋰🇮⋰⋰🇯⋰⋰🇩⋰⋰🇪⋰ ⋰🇰⋰⋰🇭⋰⋰🇦⋰⋰🇳⋰⋰🇦⋰ ⋰🇰⋰⋰🇭⋰⋰🇦⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇦⋰⋰🇦⋰ ⋰🇰⋰⋰🇦⋰⋰🇲⋰⋰🇿⋰⋰🇴⋰⋰🇷⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇩​⋰⋰🇷​⋰⋰🇨​⋰⋰🇭​⋰⋰🇴​⋰⋰🇩​⋰ ?",
        "⋰🇦⋰⋰🇧⋰ ⋰🇹⋰⋰🇰⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰ ⋰🇭⋰⋰🇴⋰⋰🇬⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ?",
        "⋰🇳⋰⋰🇾⋰ ⋰🇳⋰⋰🇾⋰ ⋰🇲⋰⋰🇪⋰ ⋰🇰⋰⋰🇺⋰⋰🇨⋰⋰🇭⋰ ⋰🇳⋰⋰🇾⋰ ⋰🇯⋰⋰🇦⋰⋰🇳⋰⋰🇹⋰⋰🇦⋰ ⋰🇧⋰⋰🇸⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰ ⋰🇪⋰⋰🇾⋰",
        "⋰🇸⋰⋰🇧⋰⋰🇸⋰⋰🇪⋰ ⋰🇵⋰⋰🇭⋰⋰🇪⋰⋰🇱⋰⋰🇪⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇰⋰⋰🇴⋰ ⋰🇧⋰⋰🇴⋰⋰🇱⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇳⋰⋰🇦⋰ ⋰🇰⋰⋰🇦⋰⋰🇲⋰ ⋰🇰⋰⋰🇷⋰⋰🇪⋰",
        "⋰🇾⋰⋰🇦⋰⋰🇭⋰⋰🇦⋰ ⋰🇧⋰⋰🇭⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇦⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇨⋰⋰🇪⋰ ⋰🇵⋰⋰🇮⋰⋰🇱⋰⋰🇱⋰⋰🇪⋰",
        "⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰⋰🇧⋰⋰🇴⋰⋰🇸⋰⋰🇩⋰⋰🇦⋰",
        "⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇹⋰⋰🇴⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇪⋰⋰🇬⋰⋰🇮⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰ ⋰🇹⋰⋰🇴⋰⋰🇲⋰⋰🇲⋰⋰🇾⋰",
        "⋰🇳⋰⋰🇮⋰⋰🇰⋰⋰🇦⋰⋰🇱⋰ ⋰🇲⋰⋰🇦⋰⋰🇩⋰⋰🇦⋰⋰🇷⋰⋰🇨⋰⋰🇭⋰⋰🇩⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇰⋰⋰🇪⋰ ⋰🇾⋰⋰🇭⋰⋰🇦⋰ ⋰🇸⋰⋰🇪⋰",
        "⋰🇨⋰⋰🇴⋰⋰🇿⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇭⋰⋰🇮⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰ ⋰🇭⋰⋰🇪⋰",
        "⋰🇳⋰⋰🇾⋰⋰🇹⋰⋰🇴⋰ ⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇵⋰ ⋰🇧⋰⋰🇴⋰⋰🇱⋰ ⋰🇲⋰⋰🇺⋰⋰🇯⋰⋰🇭⋰⋰🇪⋰",
        "⋰🇳⋰⋰🇾⋰⋰🇳⋰⋰🇾⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇭⋰⋰🇴⋰⋰🇬⋰⋰🇮⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⊶⊶🇮⋰ ⋰🇯⋰⋰🇴⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰⋰🇹⋰⋰🇮⋰ ⋰🇯⋰⋰🇴⋰⋰🇬⋰⋰🇮⋰",
        "⋰🇹⋰⋰🇷⋰⋰🇾⋰ ⋰🇦⋰⋰🇲⋰⋰🇲⋰⋰🇮⋰ ⋰🇨⋰⋰🇪⋰ ⋰🇧⋰⋰🇭⋰⋰🇴⋰⋰🇸⋰⋰🇩⋰⋰🇪⋰ ⋰🇲⋰⋰🇪⋰ ⋰🇪⋰⋰🇲⋰⋰🇴⋰⋰🇯⋰⋰🇮⋰ ⋰🇩⋰⋰🇦⋰⋰🇱⋰ ⋰🇲⋰⋰🇨⋰",
        "⋰🇨⋰⋰🇾⋰⋰🇦⋰ ? ⋰🇨⋰⋰🇭⋰⋰🇲⋰⋰🇷⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇦⋰ ⋰🇨⋰⋰🇾⋰⋰🇦⋰ ?",
        "⋰🇹⋰⋰🇲⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇷⋰⋰🇮⋰ ⋰🇭⋰⋰🇴⋰⋰🇬⋰⋰🇮⋰ ⋰🇫⋰⋰🇷⋰⋰🇷⋰⋰🇹⋰⋰🇴⋰",
        "⋰🇨⋰⋰🇾⋰⋰🇦⋰ ? ⋰🇰⋰⋰🇧⋰ ? ⋰🇵⋰⋰🇬⋰⋰🇱⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇨⋰⋰🇾⋰⋰🇦⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇰⋰⋰🇪⋰⋰🇰⋰",
        "⋰🇨⋰⋰🇾⋰⋰🇦⋰ ⋰🇸⋰⋰🇨⋰⋰🇭⋰ ⋰🇲⋰⋰🇪⋰⋰🇾⋰ ⋰🇵⋰⋰🇬⋰⋰🇱⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇨⋰⋰🇾⋰⋰🇦⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇱⋰⋰🇮⋰ ⋰🇹⋰⋰🇺⋰⋰🇳⋰⋰🇪⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰",
        "⋰🇮⋰⋰🇹⋰⋰🇳⋰⋰🇦⋰ ⋰🇸⋰⋰🇨⋰⋰🇭⋰ ⋰🇳⋰⋰🇾⋰ ⋰🇧⋰⋰🇴⋰⋰🇱⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇦⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰",
        "⋰🇸⋰⋰🇨⋰⋰🇭⋰ ⋰🇲⋰⋰🇪⋰⋰🇾⋰ ⋰🇵⋰⋰🇬⋰⋰🇱⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇱⋰⋰🇮⋰⋰🇦⋰ ⋰🇲⋰⋰🇪⋰⋰🇷⋰⋰🇪⋰ ⋰🇸⋰⋰🇹⋰⋰🇭⋰",
        "⋰🇲⋰⋰🇹⋰⋰🇱⋰⋰🇧⋰ ⋰🇹⋰⋰🇲⋰⋰🇷⋰",
        "⋰🇳⋰⋰🇾⋰⋰🇹⋰⋰🇴⋰",
        "⋰🇵⋰⋰🇺⋰⋰🇷⋰⋰🇦⋰ ⋰🇱⋰⋰🇮⋰⋰🇰⋰⋰🇭⋰ ⋰🇲⋰⋰🇨⋰",
        "⋰🇹⋰⋰🇲⋰⋰🇷⋰ ⋰🇫⋰⋰🇷⋰⋰🇷⋰⋰🇹⋰⋰🇴⋰",
        "⋰🇴⋰⋰🇭⋰ ⋰🇴⋰⋰🇰⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇱⋰⋰🇪⋰ ⋰🇫⋰⋰🇮⋰⋰🇷⋰",
        "⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇰⋰⋰🇦⋰ ⋰🇩⋰⋰🇦⋰⋰🇲⋰⋰🇦⋰⋰🇩⋰",
        "⋰🇨⋰⋰🇾⋰⋰🇦⋰ ? ⋰🇦⋰⋰🇨⋰⋰🇭⋰⋰🇪⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇱⋰⋰🇮⋰⋰🇰⋰⋰🇭⋰⋰🇪⋰ ⋰🇵⋰⋰🇪⋰⋰🇭⋰⋰🇱⋰⋰🇪⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⋰🇰⋰⋰🇪⋰⋰🇧⋰⋰🇦⋰⋰🇨⋰⋰🇭⋰⋰🇪⋰",
        "⋰🇳⋰⋰🇾⋰⋰🇹⋰⋰🇴⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰⋰🇳⋰⋰🇪⋰ ⋰🇲⋰⋰🇪⋰ ⋰🇻⋰⋰🇾⋰⋰🇦⋰⋰🇸⋰⋰🇹⋰ ⋰🇭⋰⋰🇺⋰",
        "⋰🇳⋰⋰🇾⋰⋰🇹⋰⋰🇴⋰ ⋰🇵⋰⋰🇬⋰⋰🇱⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇨⋰⋰🇾⋰⋰🇦⋰ ⋰🇰⋰⋰🇺⋰⋰🇨⋰⋰🇭⋰ ⋰🇧⋰⋰🇮⋰",
        "⋰🇴⋰⋰🇾⋰⋰🇪⋰⋰🇪⋰ ⋰🇨⋰⋰🇾⋰⋰🇦⋰ ? ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇦⋰ ?",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇲⋰⋰🇹⋰ ⋰🇭⋰⋰🇸⋰⋰🇸⋰",
        "⋰🇾⋰⋰🇺⋰⋰🇷⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⊶⊶🇮⋰ ⋰🇲⋰⋰🇴⋰⋰🇲⋰",
        "⋰🇦⋰⋰🇷⋰⋰🇪⋰ ⋰🇸⋰⋰🇧⋰⋰🇰⋰⋰🇮⋰ ⋰🇲⋰⋰??⋰⋰🇦⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⊶⊶🇮⋰ ⋰🇴⋰⋰🇷⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇧⋰⋰🇮⋰",
        "⋰🇦⋰⋰🇷⋰⋰🇪⋰ ⋰🇮⋰⋰🇩⋰⋰🇦⋰⋰🇷⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇱⋰⋰🇪⋰ ⋰🇪⋰⋰🇰⋰ ⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇷⋰",
        "⋰🇹⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇮⋰ ⋰🇹⋰⋰🇷⋰⋰🇭⋰",
        "⋰🇪⋰⋰🇰⋰ ⋰🇱⋰⋰🇮⋰⋰🇳⋰⋰🇪⋰ ⋰🇲⋰⋰🇪⋰ ⋰🇹⋰⋰🇲⋰⋰🇷⋰",
        "⋰🇶⋰",
        "⋰🇴⋰⋰🇨⋰⋰🇾⋰ ⋰🇦⋰⋰🇧⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇱⋰⋰🇪⋰",
        "⋰🇵⋰⋰🇪⋰⋰🇭⋰⋰🇪⋰⋰🇱⋰⋰🇪⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰⋰🇺⋰",
        "⋰🇳⋰⋰🇾⋰⋰🇹⋰⋰🇴⋰",
        "⋰🇶⋰ ?",
        "⋰??⋰⋰🇾⋰⋰🇾⋰⋰🇾⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇩⋰⋰🇮⋰⋰🇰⋰⋰🇦⋰ ⋰🇪⋰⋰🇰⋰ ⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇷⋰",
        "⋰🇴⋰⋰🇾⋰⋰🇪⋰⋰🇪⋰ ⋰🇸⋰⋰🇺⋰⋰🇳⋰ ⋰🇩⋰⋰🇴⋰⋰🇸⋰⋰🇹⋰ ⋰🇹⋰⋰🇲⋰⋰🇷⋰",
        "⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇯⋰⋰🇦⋰ ⋰🇷⋰⋰🇦⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰⋰🇫⋰ ⋰🇨⋰⋰🇷⋰⋰🇷⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇴⋰⋰🇾⋰⋰🇪⋰⋰🇪⋰ ⋰🇵⋰⋰🇬⋰⋰🇱⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⊶⊶🇮⋰ ⋰🇮⋰⋰🇩⋰⋰🇦⋰⋰🇷⋰ ⋰🇦⋰⋰🇦⋰",
        "⋰🇨⋰⋰🇾⋰⋰🇦⋰ ⋰🇹⋰⋰🇲⋰⋰🇷⋰ ⋰🇫⋰⋰🇷⋰⋰🇷⋰⋰🇹⋰⋰🇴⋰",
        "⋰🇴⋰⋰🇾⋰⋰🇪⋰⋰🇪⋰ ⋰🇮⋰⋰🇩⋰⋰🇦⋰⋰🇷⋰ ⋰🇦⋰⋰🇦⋰⋰🇰⋰⋰🇪⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇱⋰⋰🇪⋰ ⋰🇨⋰⋰🇭⋰⋰🇲⋰⋰🇷⋰",
        "⋰🇳⋰⋰🇾⋰⋰🇹⋰⋰🇴⋰ ⋰🇦⋰⋰🇪⋰⋰🇸⋰⋰🇪⋰ ⋰🇭⋰⋰🇮⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰",
        "⋰🇴⋰⋰🇾⋰⋰🇪⋰⋰🇪⋰ ⋰🇭⋰⋰🇾⋰⋰🇾⋰ ⋰🇦⋰⋰🇮⋰⋰🇸⋰⋰🇪⋰ ⋰🇭⋰⋰🇮⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰ ⋰🇱⋰⋰🇪⋰⋰🇳⋰⋰🇦⋰",
        "⋰🇴⋰⋰🇷⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇱⋰⋰🇪⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇩⋰⋰🇮⋰⋰🇰⋰⋰🇦⋰ ⋰🇴⋰⋰🇷⋰",
        "⋰🇭⋰⋰🇾⋰⋰🇾⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇴⋰ ⋰??⋰⋰🇦⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇴⋰ ⋰🇲⋰⋰🇹⋰ ⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇯⋰⋰🇦⋰⋰🇴⋰",
        "⋰🇧⋰⋰🇾⋰⋰🇾⋰⋰🇪⋰⋰🇪⋰ ⋰🇭⋰⋰🇾⋰⋰🇾⋰ ⋰🇨⋰⋰🇾⋰⋰🇦⋰ ?",
        "⋰🇶⋰⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇶⋰ ⋰🇷⋰⋰🇭⋰⋰🇪⋰ ⋰🇭⋰⋰🇴⋰ ?",
        "⋰🇵⋰⋰🇬⋰⋰🇱⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇨⋰⋰🇾⋰⋰🇦⋰ ⋰🇲⋰⋰🇨⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇲⋰⋰🇹⋰",
        ]
        br3_texts = [
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰ ⋰🄱⋰⋰🄾⋰⋰🄻⋰ ⋰🅃⋰⋰🄾⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄳⋰⋰??⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄴⋰ ⋰🄼⋰⋰🅄⋰⋰🄷⋰ ⋰🄼⋰⋰🄴⋰ ⋰🅁⋰⋰🄰⋰⋰🄶⋰⋰🄰⋰⋰🄳⋰ ⋰🄳⋰⋰🅄⋰",
        "⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰ ⋰??⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄼⋰⋰🄴⋰ ⋰🄻⋰⋰🄾⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🄰⋰⋰🄰⋰⋰🄻⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄼⋰⋰🄰⋰⋰🅂⋰⋰🄰⋰⋰🄻⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰",
        "⋰🄵⋰⋰🄰⋰⋰🄼⋰⋰🄴⋰ ⋰🄻⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄿⋰⋰🄴⋰ ⋰🅃⋰⋰🄷⋰⋰🄰⋰⋰🄿⋰⋰🄿⋰⋰🄰⋰⋰🄳⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🅄⋰",
        "⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄼⋰⋰🄴⋰ ⋰🄻⋰⋰🄾⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🄰⋰⋰🄰⋰⋰🄻⋰⋰🅄⋰",
        "⋰🅇⋰⋰🄷⋰⋰🄰⋰⋰🄻⋰ ⋰🅄⋰⋰🅃⋰⋰🄷⋰ ⋰🄼⋰⋰🄰⋰⋰🄳⋰⋰🄷⋰⋰🄴⋰⋰🅁⋰⋰🄲⋰⋰🄷⋰⋰??⋰⋰🄳⋰",
        "⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🄽⋰⋰🄰⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄻⋰⋰🄰⋰⋰🄳⋰⋰🄺⋰⋰🄴⋰",
        "⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄱⋰⋰🅄⋰⋰🄳⋰⋰🄷⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄻⋰⋰🄰⋰⋰🄳⋰⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄸⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄳⋰⋰🄷⋰⋰🄴⋰⋰🅁⋰⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰ ⋰🄲⋰⋰🄷⋰⋰🄰⋰⋰🄻⋰ ⋰🅄⋰⋰🅃⋰⋰🄷⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄰⋰⋰🄺⋰⋰🄴⋰⋰🄻⋰⋰🄰⋰ ⋰🄿⋰⋰🄰⋰⋰🄽⋰ ⋰🄼⋰⋰🄸⋰⋰🅃⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰ ⋰🄱⋰⋰🄸⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰⋰🄸⋰ ⋰🅇⋰⋰🄷⋰⋰🄰⋰⋰🄻⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄷⋰⋰🄾⋰ ⋰🄹⋰⋰🄰⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰⋰🄽⋰ ⋰🄺⋰⋰🄸⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰⋰🅃⋰⋰🅃⋰ ⋰🄿⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰ ⋰🄲⋰⋰🄷⋰⋰🄰⋰⋰🄿⋰⋰🄿⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰⋰🄻⋰⋰🄻⋰⋰🄻⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄽⋰⋰🄰⋰⋰🄽⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄺⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄱⋰⋰🄾⋰⋰🄾⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄴⋰⋰🅁⋰⋰🅁⋰ ⋰🄵⋰⋰🄰⋰⋰🄰⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰⋰🅃⋰⋰🅃⋰ ⋰🅂⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰⋰🅁⋰⋰🅁⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰⋰🄻⋰⋰🄻⋰⋰🄻⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰⋰🄹⋰⋰🄹⋰ ⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄱⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄵⋰⋰🄰⋰⋰🄰⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰ ⋰🅁⋰⋰🄴⋰⋰🄿⋰⋰??⋰⋰🅈⋰⋰🅈⋰⋰🅈⋰ ⋰🄺⋰⋰🅁⋰⋰🅁⋰⋰🅁⋰⋰🅁⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄱⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄽⋰⋰🄸⋰⋰🄻⋰⋰🄰⋰⋰🄰⋰⋰🄼⋰⋰🄼⋰⋰🄼⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰⋰🄽⋰⋰🄽⋰ ⋰🄺⋰⋰🄾⋰⋰🄾⋰⋰🄾⋰ ⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰⋰🄺⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰ ⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰⋰🄰⋰⋰🄰⋰ ⋰🅂⋰⋰🄴⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰⋰🅁⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰⋰🄶⋰⋰🄶⋰⋰🄶⋰ ⋰🄹⋰⋰🄰⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🅁⋰⋰🄴⋰⋰🄿⋰⋰🄻⋰⋰🅈⋰⋰🅈⋰⋰🅈⋰ ⋰🄳⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄺⋰⋰🄰⋰⋰🄰⋰⋰🄻⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄺⋰⋰🄰⋰⋰🄰⋰⋰🄻⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰⋰🅃⋰⋰🅃⋰ ⋰🄼⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰ ⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰⋰🄽⋰⋰🄽⋰ ⋰🄺⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰⋰🅃⋰ ⋰🄼⋰⋰🄴⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰⋰🄽⋰ ⋰🄷⋰⋰🄰⋰⋰🅃⋰⋰🄷⋰⋰🄷⋰⋰🄷⋰ ⋰🄳⋰⋰🄰⋰⋰🄰⋰⋰🄻⋰⋰🄻⋰⋰🄻⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰⋰🄹⋰⋰🄹⋰⋰🄹⋰ ⋰??⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰⋰🄽⋰⋰🄽⋰",
        "⋰🅂⋰⋰🄿⋰⋰🄴⋰⋰🄴⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🄿⋰⋰🄰⋰⋰🄺⋰⋰🄰⋰⋰🄰⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰⋰🄴⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰",
        "⋰🅂⋰⋰🄿⋰⋰🄴⋰⋰🄴⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🄻⋰⋰🄴⋰⋰🄺⋰⋰🄺⋰⋰🄰⋰⋰🅁⋰⋰🅁⋰⋰🅁⋰ ⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🄳⋰⋰🄰⋰⋰🅁⋰⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🅂⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰",
        "⋰🅁⋰⋰🄴⋰⋰🄿⋰⋰🄻⋰⋰🅈⋰⋰🅈⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄺⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰ ⋰🄽⋰⋰🄰⋰⋰🄽⋰⋰🄸⋰ ⋰🄺⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰⋰🅃⋰ ⋰🄺⋰⋰🄰⋰⋰🄰⋰ ⋰🄱⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄱⋰⋰🄰⋰⋰🄽⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄺⋰⋰🄰⋰⋰🅃⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄰⋰⋰🅄⋰⋰🄻⋰⋰🄰⋰⋰🄳⋰ ⋰🄷⋰⋰🄰⋰⋰🄸⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄺⋰⋰🄰⋰⋰🅃⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄰⋰⋰🅄⋰⋰🄻⋰⋰🄰⋰⋰🄳⋰ ⋰🄷⋰⋰🄰⋰⋰🄸⋰ ⋰🅃⋰⋰🅄⋰ ⋰🄼⋰⋰🄰⋰⋰🄳⋰⋰🄰⋰⋰🅁⋰⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰⋰🄳⋰ ⋰🄺⋰⋰🄸⋰⋰🄳⋰⋰🄳⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🅂⋰⋰🄰⋰⋰🅃⋰⋰🄷⋰ ⋰🅂⋰⋰🄾⋰ ⋰🄹⋰⋰🄰⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🅅⋰⋰🄾⋰⋰🄸⋰⋰🄲⋰⋰🄴⋰ ⋰🄷⋰⋰🄾⋰ ⋰🄹⋰⋰🄰⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰ ⋰🅂⋰⋰🄴⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🅄⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰ ⋰🅂⋰⋰🄰⋰⋰🄺⋰⋰🅃⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄻⋰⋰🄰⋰⋰🅄⋰⋰🄳⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄱⋰⋰🄰⋰⋰🄰⋰⋰🄿⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄸⋰⋰🄶⋰⋰🄽⋰⋰🄾⋰⋰🅁⋰⋰🄴⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄺⋰⋰🄰⋰⋰🅃⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰ ⋰🄹⋰⋰🄰⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🅄⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🄸⋰⋰🄶⋰⋰🄽⋰⋰🄾⋰⋰🅁⋰⋰🄴⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🅁⋰⋰🄰⋰ ⋰🄷⋰⋰🄰⋰⋰🄸⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰ ⋰??⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄵⋰⋰🄰⋰⋰🅃⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄰⋰ ⋰🄻⋰⋰🄾⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🄰⋰⋰🄻⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄰⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄾⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄰⋰⋰🄰⋰⋰🄿⋰ ⋰🄲⋰⋰🄿⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄺⋰⋰🄰⋰⋰🄻⋰⋰🄸⋰ ⋰🄹⋰⋰🅄⋰⋰🄱⋰⋰🄰⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰⋰🅃⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄵⋰⋰🄴⋰⋰🄽⋰⋰🄺⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰??⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄽⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰ ⋰🄹⋰⋰🄰⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄼⋰⋰🄰⋰⋰🄸⋰ ⋰🄺⋰⋰🄰⋰⋰🄱⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰⋰🄰⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰ ⋰🅂⋰⋰🄴⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰ ⋰🄺⋰⋰🄴⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄵⋰⋰🄰⋰⋰🅃⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄴⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰ ⋰🄹⋰⋰🄰⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄻⋰⋰🄸⋰⋰🄺⋰⋰🄷⋰ ⋰🄰⋰⋰🄱⋰ ⋰🅃⋰⋰🅄⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄳⋰⋰🄰⋰⋰🄵⋰⋰🄰⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄴⋰ ⋰🄻⋰⋰🄰⋰⋰🅄⋰⋰🄳⋰⋰🄴⋰ ⋰🄿⋰⋰🄴⋰⋰🅁⋰ ⋰🄶⋰⋰??⋰⋰🅄⋰⋰🄼⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄺⋰⋰🄷⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🄺⋰⋰🄷⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🄻⋰⋰🄴⋰⋰🄺⋰⋰🄸⋰⋰🄽⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄹⋰⋰🄷⋰⋰🅄⋰⋰🄺⋰⋰🄽⋰⋰🄴⋰ ⋰🄽⋰⋰🄰⋰⋰🄸⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰ ⋰🄱⋰⋰🄰⋰⋰🄽⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄰⋰ ⋰🅁⋰⋰🄴⋰⋰🄿⋰⋰🄻⋰⋰🅈⋰ ⋰🄷⋰⋰🄾⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄳⋰⋰🄸⋰⋰🄺⋰⋰🄷⋰⋰🄰⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰ ⋰🄹⋰⋰🄰⋰⋰🅈⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰⋰🄽⋰⋰🄰⋰ ⋰🄲⋰⋰🄷⋰⋰🄰⋰⋰🄻⋰⋰🅄⋰ ⋰🄺⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🅃⋰⋰🄾⋰ ⋰🄲⋰⋰🄿⋰ ⋰🄱⋰⋰🄾⋰⋰🄻⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🅄⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄰⋰⋰🅃⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰ ⋰🄷⋰⋰🄾⋰⋰🄹⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🅄⋰⋰🅃⋰⋰🄷⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄵⋰⋰🄴⋰⋰🄽⋰⋰🄺⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🄿⋰ ⋰🄼⋰⋰🄰⋰⋰🄳⋰⋰🅁⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄺⋰⋰🄾⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰??⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰ ⋰🄹⋰⋰🄰⋰⋰🅈⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄴⋰ ⋰🄻⋰⋰🄰⋰⋰🅄⋰⋰🄳⋰⋰🄴⋰ ⋰🄿⋰⋰🄴⋰",
        "⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄳⋰⋰🄸⋰⋰🄺⋰⋰🄷⋰⋰🄰⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄳⋰⋰🄰⋰⋰🄵⋰⋰🄰⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰⋰🄾⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🄼⋰⋰🄴⋰⋰🄴⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🅂⋰⋰🄰⋰⋰🅃⋰⋰🄷⋰ ⋰🅃⋰⋰🅄⋰ ⋰🄱⋰⋰🄷⋰⋰🄸⋰ ⋰🄳⋰⋰🄰⋰⋰🄵⋰⋰🄰⋰⋰🄽⋰ ⋰🄷⋰⋰🄾⋰ ⋰🄹⋰⋰🄰⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄰⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄷⋰⋰🄰⋰⋰🄸⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰??⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🅂⋰⋰🄴⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰",
        "⋰🄶⋰⋰🄰⋰⋰🄸⋰⋰🅁⋰⋰🄱⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄰⋰⋰🅄⋰⋰🄻⋰⋰🄰⋰⋰🄳⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄱⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰⋰🄿⋰ ⋰🄺⋰⋰🄸⋰ ⋰🅂⋰⋰🄿⋰⋰🄴⋰⋰🄴⋰⋰🄳⋰ ⋰🄼⋰⋰🄰⋰⋰🅃⋰⋰🄲⋰⋰🄷⋰ ⋰🄺⋰⋰🅁⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰ ⋰🄶⋰⋰🄰⋰⋰🅁⋰⋰🄸⋰⋰🄱⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄲⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅃⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄵⋰⋰🄴⋰⋰🄺⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄴⋰⋰🄴⋰⋰🄹⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰??⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄲⋰⋰🄿⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰ ⋰🅃⋰⋰🅄⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄴⋰ ⋰🄺⋰⋰🄾⋰ ⋰🅃⋰⋰🄰⋰⋰🄶⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄺⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰⋰🅁⋰ ⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄵⋰⋰🄰⋰⋰🅃⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄴⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰ ⋰🄹⋰⋰🄰⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄻⋰⋰🄸⋰⋰🄺⋰⋰🄷⋰ ⋰🄰⋰⋰🄱⋰ ⋰🅃⋰⋰🅄⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄳⋰⋰🄰⋰⋰🄵⋰⋰🄰⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄴⋰ ⋰🄻⋰⋰🄰⋰⋰🅄⋰⋰🄳⋰⋰🄴⋰ ⋰🄿⋰⋰🄴⋰⋰🅁⋰ ⋰🄶⋰⋰🄷⋰⋰🅄⋰⋰🄼⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄺⋰⋰🄷⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🄺⋰⋰🄷⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🄻⋰⋰🄴⋰⋰🄺⋰⋰🄸⋰⋰🄽⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄹⋰⋰🄷⋰⋰🅄⋰⋰🄺⋰⋰🄽⋰⋰🄴⋰ ⋰🄽⋰⋰🄰⋰⋰🄸⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰ ⋰🄱⋰⋰🄰⋰⋰🄽⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄰⋰ ⋰🅁⋰⋰🄴⋰⋰🄿⋰⋰🄻⋰⋰🅈⋰ ⋰🄷⋰⋰🄾⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄳⋰⋰🄸⋰⋰🄺⋰⋰🄷⋰⋰🄰⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰??⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰??⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰ ⋰🄹⋰⋰🄰⋰⋰🅈⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰⋰🄽⋰⋰🄰⋰ ⋰🄲⋰⋰🄷⋰⋰🄰⋰⋰🄻⋰⋰🅄⋰ ⋰🄺⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🅃⋰⋰🄾⋰ ⋰🄲⋰⋰🄿⋰ ⋰🄱⋰⋰🄾⋰⋰🄻⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🅄⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄰⋰⋰🅃⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰??⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰ ⋰🄷⋰⋰🄾⋰⋰🄹⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🅄⋰⋰🅃⋰⋰🄷⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄵⋰⋰🄴⋰⋰🄽⋰⋰🄺⋰ ⋰🄳⋰⋰🅄⋰⋰??⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🄿⋰ ⋰🄼⋰⋰🄰⋰⋰🄳⋰⋰🅁⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄺⋰⋰🄾⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰ ⋰🄹⋰⋰🄰⋰⋰🅈⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄴⋰ ⋰🄻⋰⋰🄰⋰⋰🅄⋰⋰🄳⋰⋰🄴⋰ ⋰🄿⋰⋰🄴⋰",
        "⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄳⋰⋰🄸⋰⋰🄺⋰⋰🄷⋰⋰🄰⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄳⋰⋰🄰⋰⋰🄵⋰⋰🄰⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰⋰🄾⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🄼⋰⋰🄴⋰⋰🄴⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🅂⋰⋰🄰⋰⋰🅃⋰⋰🄷⋰ ⋰🅃⋰⋰🅄⋰ ⋰🄱⋰⋰🄷⋰⋰🄸⋰ ⋰🄳⋰⋰🄰⋰⋰🄵⋰⋰🄰⋰⋰🄽⋰ ⋰🄷⋰⋰🄾⋰ ⋰🄹⋰⋰🄰⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄰⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄷⋰⋰🄰⋰⋰🄸⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🅂⋰⋰🄴⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰",
        "⋰🄶⋰⋰🄰⋰⋰🄸⋰⋰🅁⋰⋰🄱⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄰⋰⋰🅄⋰⋰🄻⋰⋰🄰⋰⋰🄳⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄱⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰⋰🄿⋰ ⋰🄺⋰⋰🄸⋰ ⋰🅂⋰⋰🄿⋰⋰🄴⋰⋰🄴⋰⋰🄳⋰ ⋰🄼⋰⋰🄰⋰⋰🅃⋰⋰🄲⋰⋰🄷⋰ ⋰🄺⋰⋰🅁⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰ ⋰🄶⋰⋰🄰⋰⋰🅁⋰⋰🄸⋰⋰🄱⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄲⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅃⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄵⋰⋰🄴⋰⋰🄺⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄴⋰⋰🄴⋰⋰🄹⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄲⋰⋰🄿⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰ ⋰🅃⋰⋰🅄⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄴⋰ ⋰🄺⋰⋰🄾⋰ ⋰🅃⋰⋰🄰⋰⋰🄶⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄺⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰⋰🅁⋰ ⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰"
        ]

        sqr_texts = [
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓐ ⊶Ⓑ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ, ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓒ⊶Ⓐ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ",
        "⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓟ ⊶Ⓑ⊶Ⓗ⊶Ⓘ ⊶Ⓑ⊶Ⓝ⊶Ⓐ⊶Ⓛ⊶Ⓔ ⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓔ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓐ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓟ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓩ ⊶Ⓔ⊶Ⓨ ⊶Ⓨ⊶Ⓐ⊶Ⓐ⊶Ⓓ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓤ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓐ ⊶Ⓝ⊶Ⓐ ⊶Ⓣ⊶Ⓨ⊶Ⓜ⊶Ⓟ⊶Ⓐ⊶Ⓢ⊶Ⓢ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ ⊶Ⓤ⊶Ⓝ⊶Ⓕ⊶Ⓤ⊶Ⓝ⊶Ⓝ⊶Ⓨ ⊶Ⓢ⊶Ⓦ⊶Ⓘ⊶Ⓟ⊶Ⓔ ⊶Ⓜ⊶Ⓣ⊶Ⓣ ⊶Ⓚ⊶Ⓡ",
        "⊶Ⓞ⊶Ⓗ ⊶Ⓗ⊶Ⓔ⊶Ⓛ⊶Ⓛ⊶Ⓞ ⊶Ⓑ⊶Ⓘ⊶Ⓗ⊶Ⓐ⊶Ⓡ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓐ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓟ ⊶Ⓑ⊶Ⓘ⊶Ⓗ⊶Ⓐ⊶Ⓡ⊶Ⓘ ⊶Ⓞ⊶Ⓡ ⊶Ⓣ⊶Ⓤ ⊶Ⓥ ⊶Ⓑ⊶Ⓘ⊶Ⓗ⊶Ⓐ⊶Ⓡ⊶Ⓘ ⊶Ⓐ⊶Ⓤ⊶Ⓚ⊶Ⓐ⊶Ⓣ ⊶Ⓜ⊶Ⓔ ⊶Ⓡ⊶Ⓗ⊶Ⓐ ⊶Ⓚ⊶Ⓡ.",
        "⊶Ⓞ⊶Ⓨ⊶Ⓨ ⊶Ⓚ⊶Ⓘ⊶Ⓝ⊶Ⓝ⊶Ⓔ⊶Ⓡ ⊶Ⓣ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ ⊶Ⓖ⊶Ⓒ ⊶Ⓜ⊶Ⓔ ⊶Ⓐ⊶Ⓐ⊶Ⓝ⊶Ⓔ ⊶Ⓚ⊶Ⓘ ⊶Ⓟ⊶Ⓔ⊶Ⓡ⊶Ⓜ⊶Ⓘ⊶Ⓢ⊶Ⓢ⊶Ⓘ⊶Ⓞ⊶Ⓝ ⊶Ⓚ⊶Ⓘ⊶Ⓢ⊶Ⓝ⊶Ⓔ ⊶Ⓓ⊶Ⓘ.",
        "⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓚ⊶Ⓔ ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓗ⊶Ⓐ",
        "⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓚ⊶Ⓔ ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓗ⊶Ⓐ ⊶Ⓔ⊶Ⓚ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓡ.",
        "⊶Ⓢ⊶Ⓤ⊶Ⓝ ⊶Ⓢ⊶Ⓤ⊶Ⓝ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓐ.",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓒ⊶Ⓐ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ.",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓣ⊶Ⓘ ⊶Ⓙ⊶Ⓐ⊶Ⓣ⊶Ⓘ ⊶Ⓚ⊶Ⓔ ⊶Ⓣ⊶Ⓜ⊶Ⓡ.",
        "⊶Ⓚ⊶Ⓨ? ⊶Ⓙ⊶Ⓛ⊶Ⓓ⊶Ⓘ ⊶Ⓛ⊶Ⓘ⊶Ⓚ⊶Ⓗ ⊶Ⓚ⊶Ⓘ⊶Ⓓ⊶Ⓓ⊶Ⓔ.",
        "⊶Ⓑ⊶Ⓘ⊶Ⓗ⊶Ⓐ⊶Ⓡ⊶Ⓘ ⊶Ⓒ⊶Ⓞ⊶Ⓜ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓖ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓟ ⊶Ⓚ⊶Ⓞ ⊶Ⓣ⊶Ⓐ⊶Ⓖ ⊶Ⓒ⊶Ⓡ⊶Ⓔ⊶Ⓖ⊶Ⓐ ⊶Ⓣ⊶Ⓤ",
        "⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓑ⊶Ⓘ⊶Ⓗ⊶Ⓐ⊶Ⓡ⊶Ⓘ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓜ⊶Ⓚ⊶Ⓒ ⊶Ⓑ⊶Ⓢ",
        "⊶Ⓙ⊶Ⓐ⊶Ⓛ⊶Ⓓ⊶Ⓘ ⊶Ⓢ⊶Ⓔ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓩ ⊶Ⓟ⊶Ⓐ⊶Ⓟ⊶Ⓐ ⊶Ⓑ⊶Ⓞ⊶Ⓛ",
        "⊶Ⓢ⊶Ⓘ⊶Ⓓ⊶Ⓔ ⊶Ⓗ⊶Ⓞ⊶Ⓙ⊶Ⓐ ⊶Ⓑ⊶Ⓘ⊶Ⓗ⊶Ⓐ⊶Ⓡ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓐ⊶Ⓑ",
        "⊶Ⓗ⊶Ⓨ⊶Ⓔ ⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓑ⊶Ⓗ⊶Ⓖ ⊶Ⓜ⊶Ⓐ⊶Ⓣ ⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓒ⊶Ⓤ⊶Ⓓ",
        "⊶Ⓑ⊶Ⓗ⊶Ⓖ ⊶Ⓝ⊶Ⓨ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ ⊶Ⓣ⊶Ⓤ ⊶Ⓐ⊶Ⓙ⊶Ⓙ",
        "⊶Ⓗ⊶Ⓨ⊶Ⓔ ⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓒ⊶Ⓗ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓐ⊶Ⓖ ⊶Ⓜ⊶Ⓐ⊶Ⓣ",
        "⊶Ⓗ⊶Ⓨ⊶Ⓔ ⊶Ⓓ⊶Ⓤ⊶Ⓡ ⊶Ⓗ⊶Ⓐ⊶Ⓣ⊶Ⓣ ⊶Ⓜ⊶Ⓐ⊶Ⓓ⊶Ⓗ⊶Ⓐ⊶Ⓡ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓔ",
        "⊶Ⓚ⊶Ⓞ⊶Ⓘ ⊶Ⓑ⊶Ⓐ⊶Ⓣ ⊶Ⓝ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ ⊶Ⓔ⊶Ⓢ⊶Ⓛ⊶Ⓘ⊶Ⓨ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓕ ⊶Ⓒ⊶Ⓡ ⊶Ⓡ⊶Ⓗ⊶Ⓐ ⊶Ⓗ⊶Ⓤ ⊶Ⓣ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ",
        "⊶Ⓚ⊶Ⓞ⊶Ⓘ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓣ ⊶Ⓝ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓣ⊶Ⓤ ⊶Ⓜ⊶Ⓐ⊶Ⓕ⊶Ⓘ ⊶Ⓓ⊶Ⓔ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓣ⊶Ⓤ ⊶Ⓜ⊶Ⓐ⊶Ⓕ⊶Ⓘ ⊶Ⓜ⊶Ⓘ⊶Ⓛ ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓖ⊶Ⓘ ⊶Ⓣ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ",
        "⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓣ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓐ ⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓔ ⊶Ⓢ⊶Ⓦ⊶Ⓘ⊶Ⓟ⊶Ⓔ ⊶Ⓒ⊶Ⓡ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓢ⊶Ⓦ⊶Ⓘ⊶Ⓟ⊶Ⓔ ⊶Ⓒ⊶Ⓡ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓕ⊶Ⓡ ⊶Ⓑ⊶Ⓞ⊶Ⓛ⊶Ⓝ⊶Ⓐ ⊶Ⓝ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓛ⊶Ⓔ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓢ⊶Ⓦ⊶Ⓘ⊶Ⓟ⊶Ⓔ ⊶Ⓒ⊶Ⓡ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓗ⊶Ⓤ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓟ⊶Ⓡ ⊶Ⓚ⊶Ⓔ⊶Ⓢ⊶Ⓔ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ",
        "⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓣ⊶Ⓗ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓔ⊶Ⓨ ⊶Ⓝ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓝ⊶Ⓣ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓨ",
        "⊶Ⓛ⊶Ⓞ⊶Ⓓ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓤ⊶Ⓣ⊶Ⓡ ⊶Ⓜ⊶Ⓒ",
        "⊶Ⓛ⊶Ⓤ⊶Ⓝ ⊶Ⓜ⊶Ⓣ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓢ ⊶Ⓜ⊶Ⓔ⊶Ⓡ⊶Ⓐ",
        "⊶Ⓝ⊶Ⓘ⊶Ⓚ⊶Ⓐ⊶Ⓛ ⊶Ⓜ⊶Ⓐ⊶Ⓓ⊶Ⓐ⊶Ⓡ⊶Ⓒ⊶Ⓗ⊶Ⓓ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓞ⊶Ⓨ⊶Ⓔ ⊶Ⓖ⊶Ⓐ⊶Ⓢ⊶Ⓗ⊶Ⓣ⊶Ⓘ ⊶Ⓚ ⊶Ⓑ⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓔ",
        "⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓘ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓚ ⊶Ⓗ⊶Ⓐ⊶Ⓣ⊶Ⓗ ⊶Ⓣ⊶Ⓞ⊶Ⓓ⊶Ⓗ ⊶Ⓚ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓟ ⊶Ⓚ ⊶Ⓜ⊶Ⓤ⊶Ⓗ ⊶Ⓜ⊶Ⓔ ⊶Ⓕ⊶Ⓐ⊶Ⓢ⊶Ⓐ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓛ⊶Ⓔ⊶Ⓐ⊶Ⓥ⊶Ⓔ ⊶Ⓛ⊶Ⓔ ⊶Ⓣ⊶Ⓤ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ ⊶Ⓟ⊶Ⓐ⊶Ⓢ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓝ⊶Ⓐ⊶Ⓘ ⊶Ⓐ⊶Ⓨ⊶Ⓐ ⊶Ⓜ⊶Ⓔ⊶Ⓚ⊶Ⓞ",
        "⊶Ⓛ⊶Ⓔ⊶Ⓐ⊶Ⓥ⊶Ⓔ ⊶Ⓛ⊶Ⓔ ⊶Ⓣ⊶Ⓤ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ ⊶Ⓘ⊶Ⓓ⊶Ⓔ⊶Ⓡ ⊶Ⓢ⊶Ⓔ",
        "⊶Ⓛ⊶Ⓔ⊶Ⓐ⊶Ⓥ⊶Ⓔ ⊶Ⓛ⊶Ⓔ ⊶Ⓙ⊶Ⓛ⊶Ⓓ⊶Ⓘ ⊶Ⓢ⊶Ⓔ ⊶Ⓦ⊶Ⓡ⊶Ⓝ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓛ⊶Ⓔ⊶Ⓐ⊶Ⓥ⊶Ⓔ ⊶Ⓝ⊶Ⓨ ⊶Ⓛ⊶Ⓔ⊶Ⓖ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓢ⊶Ⓜ⊶Ⓙ⊶Ⓗ ⊶Ⓑ⊶Ⓐ⊶Ⓣ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓛ⊶Ⓔ⊶Ⓐ⊶Ⓥ⊶Ⓔ ⊶Ⓛ⊶Ⓔ",
        "⊶Ⓕ⊶Ⓐ⊶Ⓢ⊶Ⓣ ⊶Ⓛ⊶Ⓔ⊶Ⓐ⊶Ⓥ⊶Ⓔ ⊶Ⓛ⊶Ⓔ ⊶Ⓚ⊶Ⓐ⊶Ⓜ⊶Ⓙ⊶Ⓞ⊶Ⓡ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓤ⊶Ⓣ⊶Ⓞ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ",
        "⊶Ⓞ⊶Ⓨ ⊶Ⓗ⊶Ⓘ⊶Ⓙ⊶Ⓓ⊶Ⓔ ⊶Ⓚ⊶Ⓗ⊶Ⓐ⊶Ⓝ⊶Ⓐ ⊶Ⓚ⊶Ⓗ⊶Ⓐ ⊶Ⓚ⊶Ⓔ ⊶Ⓐ⊶Ⓐ ⊶Ⓚ⊶Ⓐ⊶Ⓜ⊶Ⓩ⊶Ⓞ⊶Ⓡ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓞ ⊶Ⓘ⊶Ⓛ⊶Ⓨ ⊶Ⓡ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓣ⊶Ⓜ⊶Ⓚ⊶Ⓒ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓣ⊶Ⓤ",
        "⊶Ⓢ⊶Ⓗ⊶Ⓘ ⊶Ⓢ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓣ⊶Ⓤ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ",
        "⊶Ⓕ⊶Ⓡ ⊶Ⓢ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ",
        "⊶Ⓢ⊶Ⓗ⊶Ⓘ ⊶Ⓢ⊶Ⓔ ⊶Ⓛ⊶Ⓘ⊶Ⓚ⊶Ⓗ ⊶Ⓦ⊶Ⓡ⊶Ⓝ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓨ⊶Ⓤ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ⊶ⓒ⊶ⓤ⊶ⓓ⊶ⓦ⊶ⓐ",
        "⊶Ⓟ⊶Ⓡ⊶Ⓞ⊶Ⓞ⊶Ⓕ ⊶Ⓒ⊶Ⓡ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓟ⊶Ⓡ⊶Ⓞ⊶Ⓞ⊶Ⓕ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓟ⊶Ⓡ⊶Ⓞ⊶Ⓞ⊶Ⓕ ⊶Ⓗ⊶Ⓞ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓚ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓒ⊶Ⓗ⊶Ⓘ⊶Ⓛ⊶Ⓛ⊶Ⓐ⊶Ⓡ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓚ ⊶Ⓑ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓞ⊶Ⓨ ⊶Ⓗ⊶Ⓘ⊶Ⓙ⊶Ⓓ⊶Ⓔ ⊶Ⓚ⊶Ⓗ⊶Ⓐ⊶Ⓝ⊶Ⓐ ⊶Ⓚ⊶Ⓗ⊶Ⓐ ⊶Ⓚ⊶Ⓔ ⊶Ⓐ⊶Ⓐ ⊶Ⓚ⊶Ⓐ⊶Ⓜ⊶Ⓩ⊶Ⓞ⊶Ⓡ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶ⓜ⊶ⓐ⊶ⓓ⊶ⓡ⊶ⓒ⊶ⓗ⊶ⓞ⊶ⓓ?",
        "⊶Ⓐ⊶Ⓑ ⊶Ⓣ⊶Ⓚ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ ⊶Ⓗ⊶Ⓞ⊶Ⓖ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ?",
        "⊶Ⓝ⊶Ⓨ ⊶Ⓝ⊶Ⓨ ⊶Ⓜ⊶Ⓔ ⊶Ⓚ⊶Ⓤ⊶Ⓒ⊶Ⓗ ⊶Ⓝ⊶Ⓨ ⊶Ⓙ⊶Ⓐ⊶Ⓝ⊶Ⓣ⊶Ⓐ ⊶Ⓑ⊶Ⓢ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓢ⊶Ⓑ⊶Ⓢ⊶Ⓔ ⊶Ⓟ⊶Ⓗ⊶Ⓔ⊶Ⓛ⊶Ⓔ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓚ⊶Ⓞ ⊶Ⓑ⊶Ⓞ⊶Ⓛ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓝ⊶Ⓐ ⊶Ⓚ⊶Ⓐ⊶Ⓜ ⊶Ⓚ⊶Ⓡ⊶Ⓔ",
        "⊶Ⓨ⊶Ⓐ⊶Ⓗ⊶Ⓐ ⊶Ⓑ⊶Ⓗ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓒ⊶Ⓔ ⊶Ⓟ⊶Ⓘ⊶Ⓛ⊶Ⓛ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓐ⊶Ⓑ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓣ⊶Ⓞ ⊶Ⓑ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓔ⊶Ⓖ⊶Ⓘ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ ⊶Ⓣ⊶Ⓞ⊶Ⓜ⊶Ⓜ⊶Ⓨ",
        "⊶Ⓝ⊶Ⓘ⊶Ⓚ⊶Ⓐ⊶Ⓛ ⊶Ⓜ⊶Ⓐ⊶Ⓓ⊶Ⓐ⊶Ⓡ⊶Ⓒ⊶Ⓗ⊶Ⓓ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓚ⊶Ⓔ ⊶Ⓨ⊶Ⓗ⊶Ⓐ ⊶Ⓢ⊶Ⓔ",
        "⊶Ⓒ⊶Ⓞ⊶Ⓩ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓗ⊶Ⓘ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓘ ⊶Ⓗ⊶Ⓔ",
        "⊶Ⓝ⊶Ⓨ⊶Ⓣ⊶Ⓞ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓟ ⊶Ⓑ⊶Ⓞ⊶Ⓛ ⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ",
        "⊶Ⓝ⊶Ⓨ⊶Ⓝ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓗ⊶Ⓞ⊶Ⓖ⊶Ⓘ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶⊶Ⓘ ⊶Ⓙ⊶Ⓞ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ⊶Ⓣ⊶Ⓘ ⊶Ⓙ⊶Ⓞ⊶Ⓖ⊶Ⓘ",
        "⊶Ⓣ⊶Ⓡ⊶Ⓨ ⊶Ⓐ⊶Ⓜ⊶Ⓜ⊶Ⓘ ⊶Ⓒ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓔ⊶Ⓜ⊶Ⓞ⊶Ⓙ⊶Ⓘ ⊶Ⓓ⊶Ⓐ⊶Ⓛ ⊶Ⓜ⊶Ⓒ",
        "⊶Ⓒ⊶Ⓨ⊶Ⓐ ? ⊶Ⓒ⊶Ⓗ⊶Ⓜ⊶Ⓡ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓐ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ?",
        "⊶Ⓣ⊶Ⓜ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓡ⊶Ⓘ ⊶Ⓗ⊶Ⓞ⊶Ⓖ⊶Ⓘ ⊶Ⓕ⊶Ⓡ⊶Ⓡ⊶Ⓣ⊶Ⓞ",
        "⊶Ⓒ⊶Ⓨ⊶Ⓐ ? ⊶Ⓚ⊶Ⓑ ? ⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓔ⊶Ⓨ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓚ⊶Ⓔ⊶Ⓚ",
        "⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓢ⊶Ⓒ⊶Ⓗ ⊶Ⓜ⊶Ⓔ⊶Ⓨ ⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓔ⊶Ⓨ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓛ⊶Ⓘ ⊶Ⓣ⊶Ⓤ⊶Ⓝ⊶Ⓔ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ",
        "⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓐ ⊶Ⓢ⊶Ⓒ⊶Ⓗ ⊶Ⓝ⊶Ⓨ ⊶Ⓑ⊶Ⓞ⊶Ⓛ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓢ⊶Ⓒ⊶Ⓗ ⊶Ⓜ⊶Ⓔ⊶Ⓨ ⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓤ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓛ⊶Ⓘ⊶Ⓐ ⊶Ⓜ⊶Ⓔ⊶Ⓡ⊶Ⓔ ⊶Ⓢ⊶Ⓣ⊶Ⓗ",
        "⊶Ⓜ⊶Ⓣ⊶Ⓛ⊶Ⓑ ⊶Ⓣ⊶Ⓜ⊶Ⓡ",
        "⊶Ⓝ⊶Ⓨ⊶Ⓣ⊶Ⓞ",
        "⊶Ⓟ⊶Ⓤ⊶Ⓡ⊶Ⓐ ⊶Ⓛ⊶Ⓘ⊶Ⓚ⊶Ⓗ ⊶Ⓜ⊶Ⓒ",
        "⊶Ⓣ⊶Ⓜ⊶Ⓡ ⊶Ⓕ⊶Ⓡ⊶Ⓡ⊶Ⓣ⊶Ⓞ",
        "⊶Ⓞ⊶Ⓗ ⊶Ⓞ⊶Ⓚ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓛ⊶Ⓔ ⊶Ⓕ⊶Ⓘ⊶Ⓡ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓚ⊶Ⓐ ⊶Ⓓ⊶Ⓐ⊶Ⓜ⊶Ⓐ⊶Ⓓ",
        "⊶Ⓒ⊶Ⓨ⊶Ⓐ ? ⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓛ⊶Ⓘ⊶Ⓚ⊶Ⓗ⊶Ⓔ ⊶Ⓟ⊶Ⓔ⊶Ⓗ⊶Ⓛ⊶Ⓔ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓔ⊶Ⓑ⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓔ",
        "⊶Ⓝ⊶Ⓨ⊶Ⓣ⊶Ⓞ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ⊶Ⓝ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓥ⊶Ⓨ⊶Ⓐ⊶Ⓢ⊶Ⓣ ⊶Ⓗ⊶Ⓤ",
        "⊶Ⓝ⊶Ⓨ⊶Ⓣ⊶Ⓞ ⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓔ⊶Ⓨ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓚ⊶Ⓤ⊶Ⓒ⊶Ⓗ ⊶Ⓑ⊶Ⓘ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ? ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓐ ?",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓜ⊶Ⓣ ⊶Ⓗ⊶Ⓢ⊶Ⓢ",
        "⊶Ⓨ⊶Ⓤ⊶Ⓡ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶⊶Ⓘ ⊶Ⓜ⊶Ⓞ⊶Ⓜ",
        "⊶Ⓐ⊶Ⓡ⊶Ⓔ ⊶Ⓢ⊶Ⓑ⊶Ⓚ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶⊶Ⓘ ⊶Ⓞ⊶Ⓡ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓘ",
        "⊶Ⓐ⊶Ⓡ⊶Ⓔ ⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓛ⊶Ⓔ ⊶Ⓔ⊶Ⓚ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓡ",
        "⊶Ⓣ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓘ ⊶Ⓣ⊶Ⓡ⊶Ⓗ",
        "⊶Ⓔ⊶Ⓚ ⊶Ⓛ⊶Ⓘ⊶Ⓝ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓣ⊶Ⓜ⊶Ⓡ",
        "⊶Ⓠ",
        "⊶Ⓞ⊶Ⓒ⊶Ⓨ ⊶Ⓐ⊶Ⓑ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓛ⊶Ⓔ",
        "⊶Ⓟ⊶Ⓔ⊶Ⓗ⊶Ⓔ⊶Ⓛ⊶Ⓔ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ⊶Ⓤ",
        "⊶Ⓝ⊶Ⓨ⊶Ⓣ⊶Ⓞ",
        "⊶Ⓠ ?",
        "⊶Ⓗ⊶Ⓨ⊶Ⓨ⊶Ⓨ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓚ⊶Ⓔ ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓐ ⊶Ⓔ⊶Ⓚ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓡ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓢ⊶Ⓤ⊶Ⓝ ⊶Ⓓ⊶Ⓞ⊶Ⓢ⊶Ⓣ ⊶Ⓣ⊶Ⓜ⊶Ⓡ",
        "⊶Ⓑ⊶Ⓗ⊶Ⓐ⊶Ⓖ ⊶Ⓙ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓕ ⊶Ⓒ⊶Ⓡ⊶Ⓡ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶⊶Ⓘ ⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓐ⊶Ⓐ",
        "⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓣ⊶Ⓜ⊶Ⓡ ⊶Ⓕ⊶Ⓡ⊶Ⓡ⊶Ⓣ⊶Ⓞ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓛ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓜ⊶Ⓡ",
        "⊶Ⓝ⊶Ⓨ⊶Ⓣ⊶Ⓞ ⊶Ⓐ⊶Ⓔ⊶Ⓢ⊶Ⓔ ⊶Ⓗ⊶Ⓘ ⊶Ⓒ⊶Ⓤ⊶Ⓓ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓗ⊶Ⓨ⊶Ⓨ ⊶Ⓐ⊶Ⓘ⊶Ⓢ⊶Ⓔ ⊶Ⓗ⊶Ⓘ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓛ⊶Ⓔ⊶Ⓝ⊶Ⓐ",
        "⊶Ⓞ⊶Ⓡ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓛ⊶Ⓔ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓚ⊶Ⓔ ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓐ ⊶Ⓞ⊶Ⓡ",
        "⊶Ⓗ⊶Ⓨ⊶Ⓨ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓞ ⊶Ⓝ⊶Ⓐ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓞ ⊶Ⓜ⊶Ⓣ ⊶Ⓑ⊶Ⓗ⊶Ⓐ⊶Ⓖ ⊶Ⓙ⊶Ⓐ⊶Ⓞ",
        "⊶Ⓑ⊶Ⓨ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓗ⊶Ⓨ⊶Ⓨ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ?",
        "⊶Ⓠ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓠ ⊶Ⓡ⊶Ⓗ⊶Ⓔ ⊶Ⓗ⊶Ⓞ ?",
        "⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓔ⊶Ⓨ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓜ⊶Ⓒ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓜ⊶Ⓣ",
        "⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶⊶Ⓘ ⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓐ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓐ⊶Ⓜ⊶Ⓜ⊶Ⓘ ⊶Ⓒ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ⊶Ⓟ⊶Ⓐ⊶Ⓛ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓐ⊶Ⓐ ⊶Ⓜ⊶Ⓒ",
        "⊶Ⓚ⊶Ⓜ⊶Ⓩ⊶Ⓡ⊶Ⓞ⊶Ⓡ ⊶Ⓔ⊶Ⓨ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶Ⓔ⊶Ⓚ",
        "⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓛ⊶Ⓘ⊶Ⓚ⊶Ⓗ ⊶Ⓡ⊶Ⓗ⊶Ⓐ ?",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓣ⊶Ⓗ⊶Ⓐ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ?",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓢ⊶Ⓛ⊶Ⓘ⊶Ⓓ⊶Ⓔ ⊶Ⓛ⊶Ⓔ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶ⒶⓉ ⊶Ⓒ⊶Ⓡ⊶Ⓜ⊶Ⓒ",
        "⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ⊶Ⓤ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓒ⊶Ⓟ ⊶Ⓜ⊶Ⓣ ⊶Ⓒ⊶Ⓡ⊶Ⓡ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓛ⊶Ⓔ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓗ⊶Ⓨ⊶Ⓨ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓚ⊶Ⓔ ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓐ",
        "⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓐ⊶Ⓐ ⊶Ⓣ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓢ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓕ⊶Ⓤ ⊶Ⓚ⊶Ⓗ⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓡ ⊶Ⓚ⊶Ⓗ⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓡ",
        "⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓐ⊶Ⓐ ⊶Ⓙ⊶Ⓐ ⊶Ⓜ⊶Ⓒ",
        "⊶Ⓗ⊶Ⓨ⊶Ⓨ ⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓛ⊶Ⓔ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓚ⊶Ⓜ⊶Ⓩ⊶Ⓞ⊶Ⓡ ⊶Ⓜ⊶Ⓒ ⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓐ⊶Ⓐ",
        "⊶Ⓨ⊶Ⓔ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓣ⊶Ⓜ⊶Ⓡ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓝ⊶Ⓨ ⊶Ⓒ⊶Ⓟ ⊶Ⓝ⊶Ⓨ ⊶Ⓒ⊶Ⓡ⊶Ⓡ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓜ⊶Ⓣ ⊶Ⓒ⊶Ⓡ⊶Ⓡ",
        "⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓛ⊶Ⓔ ⊶Ⓐ⊶Ⓡ⊶ⒶⓂ ⊶Ⓢ⊶Ⓔ ⊶Ⓜ⊶Ⓒ",
        "⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓔ⊶Ⓨ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶Ⓔ⊶Ⓚ",
        "⊶Ⓒ⊶Ⓟ ⊶Ⓒ⊶Ⓡ⊶Ⓒ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓔ⊶Ⓖ⊶Ⓐ !",
        "⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓟ ? ⊶Ⓜ⊶Ⓒ ⊶Ⓜ⊶Ⓔ⊶Ⓡ⊶Ⓐ ⊶Ⓒ⊶Ⓞ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓟ ⊶Ⓝ⊶Ⓨ ⊶Ⓔ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓘ ⊶Ⓤ⊶Ⓟ⊶Ⓐ⊶Ⓡ ⊶Ⓢ⊶Ⓔ ⊶Ⓡ⊶Ⓞ⊶Ⓒ⊶Ⓚ⊶Ⓔ⊶Ⓣ ⊶Ⓟ⊶Ⓔ ⊶Ⓑ⊶Ⓔ⊶Ⓣ⊶Ⓗ ⊶Ⓒ⊶Ⓔ ⊶ⒷⓈⓈ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ⊶Ⓝ⊶Ⓔ ⊶Ⓐ⊶Ⓨ⊶Ⓐ ⊶Ⓗ⊶Ⓤ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓣ⊶Ⓐ ⊶Ⓛ⊶Ⓘ⊶Ⓚ⊶Ⓗ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ ⊶Ⓚ ⊶Ⓑ⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓔ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓣ⊶Ⓐ ⊶Ⓛ⊶Ⓘ⊶Ⓚ⊶Ⓗ⊶Ⓐ ⊶Ⓦ⊶Ⓡ⊶Ⓝ⊶Ⓐ ⊶ⓉⓇ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓨ",
        "⊶Ⓣ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓑ⊶Ⓐ⊶Ⓚ⊶Ⓐ ⊶Ⓒ⊶Ⓞ⊶Ⓓ⊶Ⓔ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓜ⊶Ⓚ⊶Ⓒ ⊶Ⓜ⊶Ⓐ⊶Ⓘ⊶Ⓝ ⊶Ⓑ⊶Ⓤ⊶Ⓡ⊶Ⓕ",
        "⊶Ⓑ⊶Ⓗ⊶Ⓘ⊶Ⓚ⊶Ⓐ⊶Ⓡ⊶Ⓘ ⊶Ⓚ⊶Ⓘ ⊶Ⓙ⊶Ⓗ⊶Ⓐ⊶Ⓣ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓐ ⊶Ⓛ⊶Ⓔ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ⊶Ⓚ⊶Ⓔ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓖ⊶Ⓘ",
        "⊶Ⓣ⊶Ⓜ⊶Ⓚ⊶Ⓒ ⊶Ⓜ⊶Ⓐ⊶Ⓘ⊶Ⓝ ⊶Ⓜ⊶Ⓞ⊶Ⓤ⊶Ⓝ⊶Ⓣ ⊶Ⓔ⊶Ⓥ⊶Ⓔ⊶Ⓡ⊶Ⓔ⊶Ⓢ⊶Ⓣ",
        "⊶Ⓜ⊶Ⓤ⊶Ⓗ ⊶Ⓜ⊶Ⓔ⊶Ⓨ ⊶Ⓛ⊶Ⓔ⊶Ⓖ⊶Ⓐ ⊶Ⓛ⊶Ⓤ⊶Ⓝ⊶Ⓓ ⊶Ⓜ⊶Ⓔ⊶Ⓡ⊶Ⓐ",
        "⊶Ⓗ⊶Ⓘ⊶Ⓙ⊶Ⓓ⊶Ⓔ ⊶Ⓚ⊶Ⓘ ⊶Ⓙ⊶Ⓗ⊶Ⓐ⊶Ⓣ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓦ⊶Ⓡ⊶Ⓝ⊶Ⓐ ⊶ⓉⓇ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ",
        "⊶Ⓜ⊶Ⓔ⊶Ⓝ⊶Ⓤ ⊶Ⓝ⊶Ⓨ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓔ⊶Ⓝ⊶Ⓤ ⊶Ⓚ⊶Ⓘ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓔ⊶Ⓝ⊶Ⓤ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓔ⊶Ⓝ⊶Ⓤ ⊶Ⓢ⊶Ⓑ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓔ⊶Ⓝ⊶Ⓤ ⊶Ⓟ⊶Ⓡ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ",
        "⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓔ⊶Ⓝ⊶Ⓤ ⊶Ⓟ⊶Ⓣ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓝ⊶Ⓤ ⊶Ⓞ⊶Ⓡ ⊶Ⓜ⊶Ⓔ⊶Ⓝ⊶Ⓤ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓔ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓑ⊶Ⓢ ⊶Ⓑ⊶Ⓢ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ",
        "⊶Ⓑ⊶Ⓢ ⊶Ⓑ⊶Ⓢ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓣ⊶Ⓗ⊶Ⓝ⊶Ⓚ⊶Ⓢ⊶Ⓢ",
        "⊶Ⓑ⊶Ⓢ ⊶Ⓑ⊶Ⓢ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓛ⊶Ⓘ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ",
        "⊶Ⓑ⊶Ⓢ ⊶Ⓑ⊶Ⓢ ⊶Ⓚ⊶Ⓐ⊶Ⓜ⊶Ⓙ⊶Ⓞ⊶Ⓡ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓢ⊶Ⓜ⊶Ⓙ⊶Ⓗ ⊶Ⓖ⊶Ⓨ⊶Ⓐ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓛ⊶Ⓔ ⊶Ⓐ⊶Ⓑ",
        "⊶Ⓢ⊶Ⓜ⊶Ⓙ⊶Ⓗ ⊶Ⓖ⊶Ⓨ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓢ⊶Ⓜ⊶Ⓙ⊶Ⓗ ⊶Ⓖ⊶Ⓨ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓢ⊶Ⓐ⊶Ⓑ⊶Ⓘ⊶Ⓣ ⊶Ⓚ⊶Ⓡ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓗ⊶Ⓤ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ",
        "⊶Ⓔ⊶Ⓐ⊶Ⓢ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓛ⊶Ⓔ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓣ⊶Ⓤ",
        "⊶Ⓔ⊶Ⓐ⊶Ⓢ⊶Ⓨ ⊶Ⓦ⊶8 ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓛ⊶Ⓔ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓐ⊶Ⓑ",
        "⊶Ⓢ⊶Ⓐ⊶Ⓝ⊶Ⓢ ⊶Ⓐ⊶Ⓡ⊶Ⓘ ⊶Ⓗ⊶Ⓐ ⊶Ⓚ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓖ⊶Ⓘ ⊶Ⓐ⊶Ⓙ⊶Ⓙ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓚ⊶Ⓞ ⊶Ⓑ⊶Ⓘ⊶Ⓝ⊶Ⓐ ⊶Ⓢ⊶Ⓐ⊶Ⓝ⊶Ⓢ⊶Ⓢ ⊶Ⓛ⊶Ⓔ⊶Ⓣ⊶Ⓔ ⊶Ⓗ⊶Ⓤ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓔ ⊶Ⓚ⊶Ⓐ⊶Ⓜ⊶Ⓙ⊶Ⓞ⊶Ⓡ",
        "⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓝ⊶Ⓞ⊶Ⓡ⊶Ⓜ⊶Ⓘ⊶Ⓔ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓛ⊶Ⓔ ⊶Ⓣ⊶Ⓤ",
        "⊶Ⓕ⊶Ⓡ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓝ⊶Ⓞ⊶Ⓡ⊶Ⓜ⊶Ⓘ⊶Ⓔ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓑ⊶Ⓐ⊶Ⓢ ⊶Ⓣ⊶Ⓗ⊶Ⓔ⊶Ⓚ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ",
        "⊶Ⓑ⊶Ⓐ⊶Ⓢ ⊶Ⓣ⊶Ⓗ⊶Ⓔ⊶Ⓚ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ",
        "⊶Ⓚ⊶Ⓐ⊶Ⓜ⊶Ⓙ⊶Ⓞ⊶Ⓡ ⊶Ⓣ⊶Ⓗ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓔ⊶Ⓢ⊶Ⓛ⊶Ⓘ⊶Ⓨ⊶Ⓔ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ",
        "⊶Ⓜ⊶Ⓐ⊶Ⓘ ⊶Ⓢ⊶Ⓑ ⊶Ⓙ⊶Ⓐ⊶Ⓝ⊶Ⓣ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓛ ⊶Ⓒ⊶Ⓗ⊶Ⓛ ⊶Ⓗ⊶Ⓣ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ",
        "⊶Ⓕ⊶Ⓡ ⊶Ⓚ⊶Ⓐ⊶Ⓘ⊶Ⓢ⊶Ⓔ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓑ⊶Ⓐ⊶Ⓢ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓕ⊶Ⓡ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓚ⊶Ⓐ⊶Ⓜ⊶Ⓙ⊶Ⓞ⊶Ⓡ ⊶Ⓜ⊶Ⓐ ⊶Ⓚ⊶Ⓐ ⊶Ⓑ⊶Ⓒ⊶Ⓗ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓣ ⊶Ⓖ⊶Ⓝ⊶Ⓓ⊶Ⓘ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓟ⊶Ⓡ ⊶Ⓚ⊶Ⓐ⊶Ⓘ⊶Ⓢ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓐ ⊶Ⓖ⊶Ⓝ⊶Ⓓ⊶Ⓐ",
        "⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓑ⊶Ⓣ⊶Ⓐ ⊶Ⓡ⊶Ⓗ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓕ⊶Ⓘ⊶Ⓡ ⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ ⊶Ⓝ⊶Ⓨ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓝ⊶Ⓨ ⊶Ⓚ⊶Ⓞ⊶Ⓝ ⊶Ⓒ⊶Ⓞ⊶Ⓓ ⊶Ⓓ⊶Ⓘ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓚ⊶Ⓞ",
        "⊶Ⓡ⊶Ⓤ⊶Ⓚ ⊶Ⓐ⊶Ⓐ⊶Ⓨ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓞ⊶Ⓓ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓦ⊶Ⓐ⊶Ⓘ⊶Ⓣ ⊶Ⓒ⊶Ⓡ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓞ⊶Ⓓ ⊶Ⓡ⊶Ⓗ⊶Ⓐ ⊶Ⓗ⊶Ⓤ",
        "⊶Ⓦ⊶Ⓐ⊶Ⓘ⊶Ⓣ ⊶Ⓒ⊶Ⓡ ⊶Ⓡ⊶Ⓐ⊶Ⓑ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓡ⊶Ⓗ⊶Ⓘ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓦ⊶Ⓐ⊶Ⓘ⊶Ⓣ ⊶Ⓚ⊶Ⓡ ⊶Ⓢ⊶Ⓜ⊶Ⓙ⊶Ⓗ ⊶Ⓡ⊶Ⓗ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓞ⊶Ⓓ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓦ⊶Ⓐ⊶Ⓘ⊶Ⓣ ⊶Ⓛ⊶Ⓔ ⊶Ⓣ⊶Ⓗ⊶Ⓞ⊶Ⓓ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ⊶Ⓝ⊶Ⓔ ⊶Ⓓ⊶Ⓔ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓞ",
        "⊶Ⓡ⊶Ⓤ⊶Ⓚ ⊶Ⓙ⊶Ⓐ ⊶Ⓐ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓡ⊶Ⓚ⊶Ⓗ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓛ⊶Ⓘ⊶Ⓨ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓕ⊶Ⓐ⊶Ⓜ⊶Ⓞ⊶Ⓤ⊶Ⓢ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓐ⊶ⒶⓃ ⊶Ⓛ⊶Ⓘ⊶Ⓐ ⊶Ⓜ⊶Ⓔ⊶Ⓝ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓢ⊶Ⓐ⊶Ⓛ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓐ⊶ⒶⓃ ⊶Ⓛ⊶Ⓘ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓢ⊶Ⓗ⊶Ⓐ⊶Ⓝ⊶Ⓣ ⊶Ⓑ⊶Ⓔ⊶Ⓣ⊶Ⓗ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ",
        "⊶Ⓢ⊶Ⓗ⊶Ⓐ⊶Ⓝ⊶Ⓣ ⊶Ⓑ⊶Ⓔ⊶Ⓣ⊶Ⓗ⊶Ⓚ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓛ⊶Ⓔ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓞ ⊶Ⓣ⊶Ⓤ",
        "⊶Ⓕ⊶Ⓡ ⊶Ⓢ⊶Ⓔ ⊶Ⓢ⊶Ⓗ⊶Ⓐ⊶Ⓝ⊶Ⓣ ⊶Ⓑ⊶Ⓔ⊶Ⓣ⊶Ⓗ ⊶Ⓣ⊶Ⓤ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓐ⊶Ⓑ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ ⊶Ⓨ⊶Ⓗ⊶Ⓐ",
        "⊶Ⓜ⊶Ⓔ⊶Ⓡ⊶Ⓔ ⊶Ⓢ⊶Ⓜ⊶Ⓙ⊶Ⓗ ⊶Ⓝ⊶Ⓨ ⊶Ⓐ⊶Ⓨ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓛ⊶Ⓔ ⊶ⓛ⊶ⓤ⊶ⓝ⊶ⓓ ⊶Ⓚ⊶Ⓗ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓜ⊶Ⓐ⊶Ⓓ⊶Ⓐ⊶Ⓡ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ",
        "⊶Ⓗ⊶Ⓨ⊶Ⓔ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ ⊶Ⓒ⊶Ⓨ⊶Ⓐ",
        "⊶Ⓗ⊶Ⓨ⊶Ⓔ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓡ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓒ⊶Ⓨ⊶Ⓐ",
        "⊶Ⓗ⊶Ⓨ⊶Ⓔ ⊶Ⓢ⊶Ⓒ⊶Ⓗ ⊶Ⓑ⊶Ⓣ⊶Ⓐ ⊶Ⓒ⊶Ⓞ⊶Ⓜ ⊶Ⓒ⊶Ⓞ⊶Ⓓ ⊶Ⓓ⊶Ⓘ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓞ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓛ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓓ⊶Ⓘ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓚ⊶Ⓞ ⊶Ⓢ⊶Ⓜ⊶Ⓙ⊶Ⓗ⊶Ⓛ⊶Ⓔ",
        "⊶Ⓑ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓚ⊶Ⓞ⊶Ⓘ ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓚ⊶Ⓐ⊶Ⓣ ⊶Ⓝ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓑ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓢ⊶Ⓑ ⊶Ⓙ⊶Ⓐ⊶Ⓝ⊶Ⓣ⊶Ⓔ ⊶Ⓔ⊶Ⓨ ⊶Ⓚ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓓ⊶Ⓚ⊶Ⓐ⊶Ⓓ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓣ⊶Ⓗ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓝ⊶Ⓔ ⊶Ⓦ⊶Ⓛ⊶Ⓘ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓟ⊶Ⓡ ⊶Ⓜ⊶Ⓔ⊶Ⓘ ⊶Ⓚ⊶Ⓐ⊶Ⓘ⊶Ⓢ⊶Ⓔ ⊶Ⓙ⊶Ⓝ⊶Ⓣ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓚ⊶Ⓞ ⊶Ⓚ⊶Ⓞ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓓ⊶Ⓘ⊶Ⓐ",
        "⊶Ⓟ⊶Ⓡ ⊶Ⓜ⊶Ⓔ⊶Ⓡ⊶Ⓐ ⊶Ⓥ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓝ⊶Ⓝ⊶Ⓐ ⊶Ⓢ⊶Ⓗ⊶Ⓘ ⊶Ⓣ⊶Ⓗ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓟ⊶Ⓡ ⊶Ⓦ⊶Ⓞ ⊶Ⓖ⊶Ⓛ⊶Ⓣ ⊶Ⓝ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓟ⊶Ⓡ ⊶Ⓦ⊶Ⓞ ⊶Ⓢ⊶Ⓗ⊶Ⓘ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓓ⊶Ⓚ⊶Ⓐ⊶Ⓓ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓟ⊶Ⓡ ⊶Ⓚ⊶Ⓐ⊶Ⓘ⊶Ⓢ⊶Ⓔ ⊶Ⓚ⊶Ⓘ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓞ⊶Ⓜ⊶Ⓕ⊶Ⓞ⊶Ⓞ",
        "⊶Ⓑ⊶Ⓤ⊶Ⓡ ⊶Ⓒ⊶Ⓗ⊶Ⓔ⊶Ⓔ⊶Ⓡ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓣ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓚ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓚ⊶Ⓔ ⊶Ⓓ⊶Ⓘ⊶Ⓛ ⊶Ⓜ⊶Ⓔ ⊶Ⓛ⊶Ⓞ⊶Ⓓ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓚ⊶Ⓔ ⊶Ⓤ⊶Ⓢ⊶Ⓚ⊶Ⓘ ⊶Ⓓ⊶Ⓗ⊶Ⓐ⊶Ⓓ⊶Ⓚ⊶Ⓐ⊶Ⓝ ⊶Ⓡ⊶Ⓞ⊶Ⓚ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓛ⊶Ⓤ⊶Ⓛ⊶Ⓛ⊶Ⓔ ⊶Ⓚ⊶Ⓗ⊶Ⓐ ⊶Ⓣ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓐ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓗ⊶Ⓝ ⊶Ⓚ⊶Ⓘ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓘ ⊶Ⓑ⊶Ⓔ⊶Ⓣ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ ⊶Ⓑ⊶Ⓐ⊶ⒶⓉ ⊶Ⓚ⊶Ⓗ⊶ⓉⓂ",
        "⊶Ⓢ⊶Ⓤ⊶Ⓝ ⊶Ⓔ⊶Ⓚ ⊶Ⓜ⊶Ⓐ⊶Ⓩ⊶Ⓔ ⊶Ⓚ⊶Ⓘ ⊶Ⓑ⊶Ⓐ⊶ⒶⓉ ⊶Ⓑ⊶Ⓐ⊶Ⓣ⊶Ⓐ⊶Ⓞ ⊶Ⓚ⊶Ⓨ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶रैं⊶डी ⊶Ⓗ⊶Ⓐ⊶Ⓘ",
        "⊶Ⓒ⊶Ⓞ⊶Ⓓ⊶Ⓤ ⊶Ⓒ⊶Ⓞ⊶Ⓓ⊶Ⓤ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓞ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓐ⊶Ⓙ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓞ⊶Ⓨ⊶Ⓔ",
        "⊶Ⓢ⊶Ⓤ⊶Ⓝ ⊶Ⓢ⊶Ⓤ⊶Ⓝ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓔ ⊶Ⓣ⊶Ⓤ",
        "⊶Ⓚ⊶Ⓘ⊶Ⓛ⊶Ⓐ⊶Ⓢ ⊶Ⓝ⊶Ⓨ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓑ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ",
        "⊶Ⓟ⊶Ⓡ ⊶Ⓟ⊶Ⓡ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓗ⊶Ⓞ⊶Ⓣ⊶Ⓔ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓜ⊶Ⓚ⊶Ⓒ",
        "⊶Ⓣ⊶Ⓜ⊶Ⓒ⊶Ⓛ ⊶Ⓢ⊶Ⓤ⊶Ⓝ⊶Ⓛ⊶Ⓔ",
        "⊶Ⓜ⊶Ⓞ⊶Ⓞ⊶Ⓣ ⊶Ⓓ⊶Ⓤ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓜ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓑ⊶Ⓗ⊶Ⓖ⊶Ⓝ⊶Ⓨ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓚ⊶Ⓔ ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓗ⊶Ⓐ ⊶Ⓕ⊶Ⓡ",
        "⊶Ⓕ⊶Ⓡ ⊶Ⓢ⊶Ⓔ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓛ⊶Ⓔ ⊶Ⓣ⊶Ⓤ",
        "⊶Ⓨ⊶Ⓔ ⊶Ⓥ⊶Ⓘ ⊶Ⓢ⊶Ⓗ⊶Ⓘ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓚ⊶Ⓒ ⊶Ⓑ⊶Ⓢ",
        "⊶Ⓐ⊶Ⓙ ⊶Ⓚ⊶Ⓤ⊶Ⓒ⊶Ⓗ ⊶Ⓝ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ",
        "⊶Ⓣ⊶Ⓡ⊶Ⓨ ⊶Ⓚ⊶Ⓡ ⊶Ⓜ⊶Ⓔ⊶Ⓡ⊶Ⓐ ⊶Ⓛ⊶Ⓤ⊶Ⓝ⊶Ⓓ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓢ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓞ⊶Ⓡ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓘ⊶Ⓑ⊶Ⓤ⊶Ⓡ ⊶Ⓢ⊶Ⓤ⊶Ⓝ",
        "⊶Ⓣ⊶Ⓞ⊶Ⓡ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓕ⊶Ⓤ⊶Ⓓ⊶Ⓓ⊶Ⓘ ⊶Ⓞ⊶Ⓨ⊶Ⓔ",
        "⊶Ⓗ⊶Ⓐ⊶Ⓨ⊶Ⓔ ⊶Ⓗ⊶Ⓐ⊶Ⓨ⊶Ⓔ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ ⊶Ⓛ⊶Ⓤ⊶Ⓝ⊶Ⓓ⊶Ⓚ⊶Ⓔ ⊶Ⓟ⊶Ⓐ⊶Ⓢ⊶Ⓘ⊶Ⓝ⊶Ⓔ..",
        "⊶Ⓚ⊶Ⓤ⊶Ⓣ⊶Ⓣ⊶Ⓔ ⊶Ⓚ⊶Ⓔ ⊶Ⓣ⊶Ⓐ⊶Ⓣ⊶Ⓣ⊶Ⓔ ⊶Ⓢ⊶Ⓤ⊶Ⓝ",
        "⊶Ⓚ⊶Ⓤ⊶Ⓣ⊶Ⓣ⊶Ⓐ ⊶Ⓙ⊶Ⓐ⊶Ⓘ⊶Ⓢ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓡ⊶Ⓗ⊶Ⓐ ⊶Ⓣ⊶Ⓤ",
        "⊶Ⓜ⊶Ⓤ⊶Ⓗ ⊶Ⓜ⊶Ⓔ⊶Ⓘ ⊶Ⓛ⊶Ⓔ ⊶Ⓜ⊶Ⓔ⊶Ⓡ⊶Ⓐ..",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ⊶Ⓘ⊶Ⓨ⊶Ⓐ ⊶Ⓚ⊶Ⓐ⊶Ⓣ ⊶Ⓚ⊶Ⓔ ⊶Ⓕ⊶Ⓔ⊶Ⓝ⊶Ⓚ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓝ⊶Ⓞ⊶Ⓝ ⊶Ⓢ⊶Ⓣ⊶Ⓞ⊶Ⓟ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓕ⊶Ⓐ⊶ⒶⓉ ⊶Ⓖ⊶Ⓐ⊶Ⓨ⊶Ⓘ ⊶Ⓐ⊶Ⓙ⊶Ⓣ⊶Ⓞ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓗ⊶Ⓐ⊶Ⓝ ⊶Ⓚ⊶Ⓐ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ ⊶Ⓜ⊶Ⓔ ⊶Ⓚ⊶Ⓤ⊶Ⓣ⊶Ⓣ⊶Ⓐ ⊶Ⓚ⊶Ⓐ ⊶Ⓛ⊶Ⓤ⊶Ⓝ⊶Ⓓ ⊶Ⓒ⊶Ⓗ⊶Ⓘ⊶Ⓟ⊶Ⓚ⊶Ⓐ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓝ⊶Ⓞ⊶Ⓝ ⊶Ⓢ⊶Ⓣ⊶Ⓞ⊶Ⓟ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓖ⊶Ⓞ⊶Ⓛ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶ⒶⓇ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓤ⊶Ⓢ⊶Ⓢ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶100 ⊶Ⓒ⊶Ⓗ⊶Ⓔ⊶Ⓓ⊶Ⓓ ⊶Ⓚ⊶Ⓐ⊶Ⓡ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓓ⊶Ⓘ⊶Ⓓ⊶Ⓘ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ⊶Ⓟ⊶Ⓐ⊶Ⓛ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓓ⊶Ⓘ⊶Ⓓ⊶Ⓘ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓦ⊶Ⓐ⊶Ⓢ⊶Ⓘ⊶Ⓡ ⊶Ⓗ⊶Ⓞ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓜ⊶Ⓔ⊶Ⓡ⊶Ⓔ ⊶Ⓛ⊶Ⓐ⊶Ⓥ⊶Ⓓ⊶Ⓔ ⊶Ⓟ⊶Ⓐ⊶Ⓡ ⊶Ⓤ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓛ ⊶Ⓤ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓛ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓣ⊶Ⓘ ⊶Ⓗ⊶Ⓐ⊶Ⓘ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓔ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓚ⊶Ⓘ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓜ⊶Ⓔ ⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ⊶Ⓟ⊶Ⓐ⊶Ⓛ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓔ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓚ⊶Ⓘ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓣ⊶Ⓐ⊶Ⓜ⊶Ⓐ⊶Ⓣ⊶Ⓐ⊶Ⓡ ⊶Ⓚ⊶Ⓔ ⊶Ⓣ⊶Ⓐ⊶Ⓡ⊶Ⓐ⊶Ⓗ ⊶Ⓛ⊶Ⓐ⊶ⒶⓁ ⊶Ⓗ⊶Ⓞ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓓ⊶Ⓘ⊶Ⓓ⊶Ⓘ ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓕ⊶Ⓐ⊶ⒶⓅ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓑ⊶Ⓘ⊶Ⓒ⊶Ⓗ ⊶Ⓑ⊶Ⓐ⊶Ⓙ⊶Ⓐ⊶Ⓡ ⊶Ⓜ⊶Ⓔ ⊶Ⓝ⊶Ⓘ⊶Ⓛ⊶Ⓐ⊶Ⓜ ⊶Ⓚ⊶Ⓐ⊶Ⓡ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓑ⊶Ⓔ⊶Ⓣ⊶Ⓘ⊶Ⓨ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓚ⊶Ⓐ⊶Ⓕ⊶Ⓕ⊶Ⓐ⊶Ⓝ ⊶Ⓜ⊶Ⓔ ⊶Ⓓ⊶Ⓐ⊶Ⓕ⊶Ⓐ⊶Ⓝ ⊶Ⓚ⊶Ⓐ⊶Ⓡ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓙ⊶Ⓐ⊶Ⓓ⊶Ⓐ ⊶Ⓝ⊶Ⓐ ⊶Ⓤ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓛ ⊶Ⓦ⊶Ⓐ⊶Ⓡ⊶Ⓝ⊶Ⓐ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓓ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓔ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓔ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓢ⊶Ⓐ⊶Ⓢ⊶Ⓣ⊶Ⓐ ⊶Ⓚ⊶Ⓔ⊶Ⓨ⊶Ⓑ⊶Ⓞ⊶Ⓐ⊶Ⓡ⊶Ⓓ ⊶Ⓛ⊶Ⓐ⊶Ⓖ⊶Ⓐ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓐ⊶Ⓖ⊶Ⓐ⊶Ⓡ ⊶Ⓣ⊶Ⓤ ⊶Ⓒ⊶Ⓟ ⊶Ⓑ⊶Ⓞ⊶Ⓛ⊶Ⓔ⊶Ⓖ⊶Ⓐ ⊶Ⓣ⊶Ⓞ ⊶Ⓜ⊶Ⓔ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓖ⊶Ⓐ⊶Ⓡ⊶Ⓐ⊶Ⓜ ⊶Ⓜ⊶Ⓤ⊶Ⓣ⊶Ⓣ⊶Ⓗ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓤ⊶Ⓡ ⊶Ⓜ⊶Ⓔ ⊶Ⓗ⊶Ⓐ⊶Ⓣ⊶Ⓗ⊶Ⓞ⊶Ⓡ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓚ⊶Ⓘ⊶Ⓛ⊶Ⓛ⊶Ⓘ ⊶Ⓣ⊶Ⓗ⊶Ⓞ⊶Ⓚ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓔ ⊶Ⓣ⊶Ⓔ⊶Ⓙ⊶Ⓙ⊶Ⓘ ⊶Ⓢ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ⊶Ⓟ⊶Ⓐ⊶Ⓛ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ ⊶Ⓕ⊶Ⓐ⊶ⒶⓉ ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓐ⊶Ⓜ⊶Ⓜ⊶Ⓐ ⊶Ⓙ⊶Ⓐ⊶ⒶⓃ ⊶Ⓚ⊶Ⓔ ⊶Ⓒ⊶Ⓐ⊶Ⓝ⊶Ⓒ⊶Ⓔ⊶Ⓡ ⊶Ⓦ⊶Ⓐ⊶Ⓛ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓜ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ⊶Ⓟ⊶Ⓐ⊶Ⓛ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓝ⊶Ⓞ⊶Ⓝ ⊶Ⓢ⊶Ⓣ⊶Ⓞ⊶Ⓟ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓐ⊶Ⓜ⊶Ⓜ⊶Ⓐ ⊶Ⓙ⊶Ⓐ⊶ⒶⓃ ⊶Ⓚ⊶Ⓔ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓜ⊶Ⓔ ⊶Ⓖ⊶Ⓛ⊶Ⓘ⊶Ⓣ⊶Ⓒ⊶Ⓗ ⊶Ⓣ⊶Ⓨ⊶Ⓟ⊶Ⓘ⊶Ⓝ⊶Ⓖ ⊶Ⓚ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓥ⊶Ⓐ⊶Ⓢ⊶Ⓘ⊶Ⓨ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓗ⊶Ⓐ⊶Ⓘ ⊶Ⓢ⊶Ⓐ⊶Ⓑ⊶Ⓚ⊶Ⓐ ⊶Ⓜ⊶Ⓤ⊶Ⓗ ⊶Ⓜ⊶Ⓔ⊶Ⓗ ⊶Ⓛ⊶Ⓤ⊶Ⓝ⊶Ⓓ ⊶Ⓛ⊶Ⓔ⊶Ⓚ⊶Ⓡ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓐ ⊶Ⓚ⊶Ⓗ⊶Ⓐ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓐ⊶Ⓝ ⊶Ⓚ⊶Ⓞ ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓛ⊶Ⓐ⊶Ⓣ⊶Ⓘ ⊶Ⓗ⊶Ⓐ⊶Ⓘ",
        "⊶Ⓣ⊶Ⓤ ⊶Ⓞ⊶Ⓡ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓐ ⊶Ⓚ⊶Ⓗ⊶Ⓐ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓐ⊶Ⓝ ⊶Ⓚ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓑ⊶Ⓘ⊶Ⓒ⊶Ⓗ ⊶Ⓑ⊶Ⓐ⊶Ⓙ⊶Ⓐ⊶Ⓡ ⊶Ⓜ⊶Ⓔ ⊶Ⓜ⊶Ⓞ⊶Ⓙ⊶Ⓡ⊶Ⓐ ⊶Ⓚ⊶Ⓐ⊶Ⓡ⊶Ⓦ⊶Ⓐ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓔ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓚ⊶Ⓔ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓜ⊶Ⓔ ⊶Ⓖ⊶Ⓞ⊶Ⓛ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶ⒶⓇ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓓ⊶Ⓤ⊶Ⓢ⊶Ⓡ⊶Ⓐ ⊶Ⓑ⊶Ⓛ⊶Ⓐ⊶Ⓒ⊶Ⓚ ⊶Ⓗ⊶Ⓞ⊶Ⓛ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓝ⊶Ⓐ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓜ⊶Ⓜ⊶Ⓐ ⊶Ⓛ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓔ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓚ⊶Ⓐ⊶Ⓕ⊶Ⓕ⊶Ⓐ⊶Ⓝ ⊶Ⓜ⊶Ⓔ ⊶Ⓓ⊶Ⓐ⊶Ⓕ⊶Ⓐ⊶Ⓝ ⊶Ⓚ⊶Ⓐ⊶Ⓡ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓑ⊶Ⓔ⊶Ⓣ⊶Ⓘ⊶ⓨ⊶Ⓞ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓖ⊶Ⓞ⊶Ⓓ⊶Ⓩ⊶Ⓘ⊶Ⓛ⊶Ⓛ⊶Ⓐ ⊶Ⓚ⊶Ⓐ ⊶Ⓛ⊶Ⓤ⊶Ⓝ⊶Ⓓ ⊶Ⓓ⊶Ⓐ⊶Ⓛ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓖ⊶Ⓞ⊶Ⓓ⊶Ⓩ⊶Ⓘ⊶Ⓛ⊶Ⓛ⊶Ⓐ ⊶Ⓚ⊶Ⓐ ⊶Ⓛ⊶Ⓤ⊶Ⓝ⊶Ⓓ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓕ⊶Ⓐ⊶ⒶⓇ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓢ⊶Ⓔ ⊶Ⓝ⊶Ⓘ⊶Ⓚ⊶Ⓐ⊶Ⓛ ⊶Ⓓ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓨ⊶Ⓐ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓕ⊶Ⓛ⊶Ⓨ ⊶Ⓚ⊶Ⓘ⊶Ⓢ⊶Ⓢ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓟ⊶Ⓐ⊶Ⓐ⊶Ⓝ⊶Ⓘ ⊶Ⓝ⊶Ⓘ⊶Ⓚ⊶Ⓐ⊶Ⓛ ⊶Ⓓ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓘ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓤ⊶Ⓜ⊶Ⓜ⊶Ⓨ ⊶Ⓚ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓒ⊶Ⓗ⊶Ⓘ⊶ⓨ⊶Ⓞ ⊶Ⓚ⊶Ⓞ ⊶Ⓚ⊶Ⓐ⊶Ⓣ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓟ⊶Ⓐ⊶Ⓚ⊶Ⓚ⊶Ⓐ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓔ ⊶Ⓙ⊶Ⓤ⊶Ⓣ⊶Ⓣ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓚ⊶Ⓗ⊶Ⓤ⊶Ⓝ⊶Ⓝ ⊶Ⓝ⊶Ⓘ⊶Ⓚ⊶Ⓐ⊶Ⓛ ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓤ⊶Ⓢ⊶Ⓢ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓟ⊶Ⓐ⊶Ⓐ⊶Ⓝ⊶Ⓘ ⊶Ⓝ⊶Ⓘ⊶Ⓚ⊶Ⓐ⊶Ⓛ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓓ⊶Ⓞ⊶Ⓝ⊶Ⓐ⊶Ⓣ⊶Ⓔ ⊶Ⓚ⊶Ⓐ⊶Ⓡ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ⊶Ⓟ⊶Ⓐ⊶Ⓛ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓒ⊶Ⓒ⊶Ⓗ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓗ⊶Ⓐ⊶Ⓡ ⊶Ⓝ⊶Ⓘ⊶Ⓚ⊶Ⓐ⊶Ⓛ ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓓ⊶Ⓘ⊶Ⓓ⊶Ⓘ ⊶Ⓚ⊶Ⓔ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓜ⊶Ⓔ ⊶Ⓨ⊶Ⓞ⊶Ⓖ⊶Ⓘ ⊶Ⓙ⊶Ⓘ ⊶Ⓚ⊶Ⓐ ⊶Ⓑ⊶Ⓤ⊶Ⓛ⊶Ⓛ⊶Ⓓ⊶Ⓞ⊶Ⓩ⊶Ⓔ⊶Ⓡ ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓛ⊶Ⓐ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓓ⊶Ⓘ⊶Ⓓ⊶Ⓘ ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓕ⊶Ⓛ⊶Ⓐ⊶Ⓣ ⊶Ⓗ⊶Ⓞ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓘ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓑ⊶Ⓔ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓔ ⊶Ⓙ⊶Ⓤ⊶Ⓣ⊶Ⓣ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓑ⊶Ⓔ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓚ⊶Ⓐ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ ⊶Ⓕ⊶Ⓐ⊶ⒶⓉ ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓓ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓐ⊶Ⓚ⊶49 ⊶Ⓢ⊶Ⓔ ⊶Ⓖ⊶Ⓞ⊶Ⓛ⊶Ⓘ⊶Ⓨ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓔ ⊶Ⓖ⊶Ⓞ⊶Ⓛ⊶Ⓘ⊶Ⓨ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶9 ⊶Ⓤ⊶Ⓝ⊶Ⓘ⊶Ⓥ⊶Ⓔ⊶Ⓡ⊶Ⓢ ⊶Ⓐ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓐ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓗ⊶Ⓐ ⊶Ⓓ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓜ⊶Ⓔ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶ⓨ⊶Ⓞ ⊶Ⓚ⊶Ⓐ ⊶Ⓚ⊶Ⓞ⊶Ⓣ⊶Ⓗ⊶Ⓐ ⊶Ⓑ⊶Ⓐ⊶Ⓝ⊶Ⓐ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓔ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓚ⊶Ⓞ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ⊶Ⓝ⊶Ⓔ ⊶Ⓚ⊶Ⓞ ⊶Ⓑ⊶Ⓐ⊶Ⓘ⊶Ⓣ⊶Ⓗ⊶Ⓐ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓚ⊶Ⓞ⊶Ⓣ⊶Ⓗ⊶Ⓔ ⊶Ⓟ⊶Ⓐ⊶Ⓡ⊶Ⓡ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓚ⊶Ⓞ ⊶Ⓑ⊶Ⓐ⊶Ⓒ⊶Ⓒ⊶Ⓗ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓘ ⊶Ⓑ⊶Ⓐ⊶Ⓗ⊶Ⓐ⊶Ⓝ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓙ⊶Ⓘ⊶Ⓨ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓔ⊶Ⓖ⊶Ⓐ ⊶Ⓣ⊶Ⓞ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓐ⊶Ⓝ⊶Ⓒ⊶Ⓔ⊶Ⓡ ⊶Ⓦ⊶Ⓐ⊶Ⓛ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓜ⊶Ⓔ ⊶Ⓚ⊶Ⓞ ⊶Ⓣ⊶Ⓘ⊶Ⓚ⊶Ⓣ⊶Ⓞ⊶Ⓚ ⊶Ⓚ⊶Ⓔ ⊶Ⓣ⊶Ⓐ⊶Ⓡ⊶Ⓐ⊶Ⓗ ⊶Ⓑ⊶Ⓐ⊶Ⓝ ⊶Ⓚ⊶Ⓐ⊶Ⓡ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓘ⊶Ⓢ⊶Ⓢ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓘ⊶Ⓨ⊶Ⓐ ⊶Ⓢ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓚ⊶Ⓐ ⊶Ⓟ⊶Ⓞ⊶Ⓦ⊶Ⓔ⊶Ⓡ ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓗ⊶Ⓐ",
        "⊶Ⓐ⊶Ⓘ⊶Ⓢ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓐ⊶Ⓖ⊶Ⓔ⊶Ⓖ⊶Ⓐ ⊶Ⓣ⊶Ⓞ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓣ⊶Ⓞ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓜ⊶Ⓔ ⊶Ⓜ⊶Ⓤ⊶Ⓣ⊶Ⓣ⊶Ⓗ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶ⒶⓇ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓟ⊶Ⓞ⊶Ⓛ⊶Ⓘ⊶Ⓒ⊶Ⓔ ⊶Ⓚ⊶Ⓐ ⊶Ⓓ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓤ⊶Ⓢ⊶Ⓢ⊶Ⓔ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓚ⊶Ⓐ ⊶Ⓦ⊶Ⓞ⊶Ⓡ⊶Ⓚ⊶Ⓞ⊶Ⓤ⊶Ⓣ ⊶Ⓗ⊶Ⓞ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓐ⊶Ⓜ⊶Ⓜ⊶Ⓐ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓐ ⊶Ⓔ⊶Ⓝ⊶Ⓔ⊶Ⓡ⊶Ⓖ⊶Ⓨ ⊶Ⓗ⊶Ⓐ⊶Ⓘ ⊶Ⓚ⊶Ⓘ ⊶Ⓔ⊶Ⓚ ⊶Ⓑ⊶Ⓐ⊶ⒶⓇ ⊶Ⓜ⊶Ⓔ ⊶10 ⊶Ⓛ⊶Ⓞ⊶Ⓖ⊶Ⓞ ⊶Ⓚ⊶Ⓐ ⊶Ⓛ⊶Ⓤ⊶Ⓝ⊶Ⓓ⊶Ⓐ ⊶Ⓛ⊶Ⓔ⊶Ⓛ⊶Ⓔ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓐ⊶Ⓜ⊶Ⓜ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓑ⊶Ⓐ⊶Ⓒ⊶Ⓒ⊶Ⓗ⊶Ⓐ ⊶Ⓐ⊶Ⓘ⊶Ⓢ⊶Ⓔ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓨ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓑ⊶Ⓗ⊶Ⓐ⊶Ⓖ⊶Ⓔ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓚ⊶Ⓞ ⊶Ⓤ⊶Ⓛ⊶Ⓣ⊶Ⓐ ⊶Ⓛ⊶Ⓐ⊶Ⓣ⊶Ⓚ⊶Ⓐ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓐ⊶Ⓜ⊶Ⓜ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓜ⊶Ⓔ ⊶Ⓗ⊶Ⓞ⊶Ⓛ⊶Ⓛ⊶Ⓞ⊶Ⓦ ⊶Ⓟ⊶Ⓤ⊶Ⓡ⊶Ⓟ⊶Ⓛ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶ⒶⓇ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓐ⊶Ⓜ⊶Ⓜ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓜ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓔ⊶Ⓓ⊶Ⓓ ⊶Ⓚ⊶Ⓐ⊶Ⓡ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ"
        ]
            
        sq2_texts = [
        "⋰Ⓑ⋰⋰⒪⋰⋰⒧⋰ ⋰⒯⋰⋰⒪⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰Ⓓ⋰⋰⒤⋰⋰Ⓓ⋰⋰⒤⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒠⋰ ⋰⒨⋰⋰⒰⋰⋰⒣⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒭⋰⋰⒜⋰⋰⒢⋰⋰⒜⋰⋰⒟⋰ ⋰⒟⋰⋰⒰⋰",
        "⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒧⋰⋰⒪⋰⋰⒟⋰⋰⒜⋰⋰⒜⋰ ⋰⒟⋰⋰⒜⋰⋰⒜⋰⋰⒧⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒨⋰⋰⒜⋰⋰⒮⋰⋰⒜⋰⋰⒧⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰",
        "⋰⒡⋰⋰⒜⋰⋰⒨⋰⋰⒠⋰ ⋰⒧⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒫⋰⋰⒠⋰ ⋰⒯⋰⋰⒣⋰⋰⒜⋰⋰⒫⋰⋰⒫⋰⋰⒜⋰⋰⒟⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰⋰⒰⋰",
        "⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒧⋰⋰⒪⋰⋰⒟⋰⋰⒜⋰⋰⒜⋰ ⋰⒟⋰⋰⒜⋰⋰⒜⋰⋰⒧⋰⋰⒰⋰",
        "⋰⒳⋰⋰⒣⋰⋰⒜⋰⋰⒧⋰ ⋰⒰⋰⋰⒯⋰⋰⒣⋰ ⋰⒨⋰⋰⒜⋰⋰⒟⋰⋰⒣⋰⋰⒠⋰⋰⒭⋰⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰",
        "⋰⒨⋰⋰⒜⋰⋰⒭⋰⋰⒩⋰⋰⒜⋰ ⋰⒩⋰⋰⒜⋰⋰⒣⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒧⋰⋰⒜⋰⋰⒟⋰⋰⒦⋰⋰⒠⋰",
        "⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒝⋰⋰⒰⋰⋰⒟⋰⋰⒣⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒧⋰⋰⒜⋰⋰⒟⋰⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒤⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒟⋰⋰⒣⋰⋰⒠⋰⋰⒭⋰⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰ ⋰⒞⋰⋰⒣⋰⋰⒜⋰⋰⒧⋰ ⋰⒰⋰⋰⒯⋰⋰⒣⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒜⋰⋰⒦⋰⋰⒠⋰⋰⒧⋰⋰⒜⋰ ⋰⒫⋰⋰⒜⋰⋰⒩⋰ ⋰⒨⋰⋰⒤⋰⋰⒯⋰⋰⒜⋰⋰⒜⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰ ⋰⒝⋰⋰⒤⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒤⋰ ⋰⒳⋰⋰⒣⋰⋰⒜⋰⋰⒧⋰ ⋰⒥⋰⋰⒤⋰⋰⒩⋰⋰⒟⋰⋰⒜⋰⋰⒜⋰ ⋰⒣⋰⋰⒪⋰ ⋰⒥⋰⋰⒜⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰⋰⒩⋰ ⋰⒦⋰⋰⒤⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰⋰⒯⋰⋰⒯⋰ ⋰⒫⋰⋰⒠⋰⋰⒠⋰⋰⒠⋰ ⋰⒞⋰⋰⒣⋰⋰⒜⋰⋰⒫⋰⋰⒫⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰⋰⒧⋰⋰⒧⋰⋰⒧⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒩⋰⋰⒜⋰⋰⒩⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒦⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰ ⋰⒝⋰⋰⒪⋰⋰⒪⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒠⋰⋰⒠⋰⋰⒭⋰⋰⒭⋰ ⋰⒡⋰⋰⒜⋰⋰⒜⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰⋰⒯⋰⋰⒯⋰ ⋰⒮⋰⋰⒠⋰⋰⒠⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒭⋰⋰⒭⋰ ⋰⒩⋰⋰⒤⋰⋰⒦⋰⋰⒜⋰⋰⒧⋰⋰⒧⋰⋰⒧⋰⋰⒧⋰ ⋰⒜⋰⋰⒜⋰⋰⒥⋰⋰⒥⋰⋰⒥⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒝⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒡⋰⋰⒜⋰⋰⒜⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰⋰⒭⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰ ⋰⒭⋰⋰⒠⋰⋰⒫⋰⋰⒧⋰⋰⒴⋰⋰⒴⋰⋰⒴⋰ ⋰⒦⋰⋰⒭⋰⋰⒭⋰⋰⒭⋰⋰⒭⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰⋰⒩⋰ ⋰⒦⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰ ⋰⒝⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰⋰⒜⋰ ⋰⒩⋰⋰⒤⋰⋰⒧⋰⋰⒜⋰⋰⒜⋰⋰⒨⋰⋰⒨⋰⋰⒨⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰⋰⒭⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰⋰⒠⋰⋰⒠⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰⋰⒠⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰⋰⒩⋰⋰⒩⋰ ⋰⒦⋰⋰⒪⋰⋰⒪⋰⋰⒪⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒦⋰⋰⒠⋰⋰⒠⋰⋰⒠⋰ ⋰⒤⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒜⋰⋰⒜⋰ ⋰⒮⋰⋰⒠⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒭⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰⋰⒢⋰⋰⒢⋰⋰⒢⋰ ⋰⒥⋰⋰⒜⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰ ⋰⒭⋰⋰⒠⋰⋰⒫⋰⋰⒧⋰⋰⒴⋰⋰⒴⋰⋰⒴⋰ ⋰⒟⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒦⋰⋰⒜⋰⋰⒜⋰⋰⒧⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒦⋰⋰⒜⋰⋰⒜⋰⋰⒧⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰⋰⒯⋰⋰⒯⋰ ⋰⒨⋰⋰⒠⋰⋰⒠⋰⋰⒠⋰ ⋰⒧⋰⋰⒰⋰⋰⒩⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰ ⋰⒜⋰⋰⒜⋰⋰⒥⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰⋰⒩⋰⋰⒩⋰ ⋰⒦⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰⋰⒯⋰ ⋰⒨⋰⋰⒠⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰⋰⒩⋰ ⋰⒣⋰⋰⒜⋰⋰⒯⋰⋰⒣⋰⋰⒣⋰⋰⒣⋰ ⋰⒟⋰⋰⒜⋰⋰⒜⋰⋰⒧⋰⋰⒧⋰⋰⒧⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰ ⋰⒜⋰⋰⒜⋰⋰⒥⋰⋰⒥⋰⋰⒥⋰⋰⒥⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰⋰⒩⋰⋰⒩⋰",
        "⋰⒮⋰⋰⒫⋰⋰⒠⋰⋰⒠⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰ ⋰⒫⋰⋰⒜⋰⋰⒦⋰⋰⒜⋰⋰⒜⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰⋰⒠⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰⋰⒠⋰⋰⒠⋰",
        "⋰⒮⋰⋰⒫⋰⋰⒠⋰⋰⒠⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰ ⋰⒧⋰⋰⒠⋰⋰⒦⋰⋰⒦⋰⋰⒜⋰⋰⒭⋰⋰⒭⋰⋰⒭⋰ ⋰⒜⋰⋰⒜⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰⋰⒟⋰⋰⒜⋰⋰⒭⋰⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰ ⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒮⋰⋰⒠⋰⋰⒠⋰⋰⒠⋰",
        "⋰⒭⋰⋰⒠⋰⋰⒫⋰⋰⒧⋰⋰⒴⋰⋰⒴⋰⋰⒴⋰ ⋰⒦⋰⋰⒜⋰⋰⒤⋰⋰⒮⋰⋰⒠⋰ ⋰⒦⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰ ⋰⒩⋰⋰⒜⋰⋰⒩⋰⋰⒤⋰ ⋰⒦⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰⋰⒯⋰ ⋰⒦⋰⋰⒜⋰⋰⒜⋰ ⋰⒝⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰⋰⒜⋰ ⋰⒝⋰⋰⒜⋰⋰⒩⋰⋰⒜⋰⋰⒜⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰⋰⒜⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰⋰⒴⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒦⋰⋰⒜⋰⋰⒯⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒜⋰⋰⒰⋰⋰⒧⋰⋰⒜⋰⋰⒟⋰ ⋰⒣⋰⋰⒜⋰⋰⒤⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒦⋰⋰⒜⋰⋰⒯⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒜⋰⋰⒰⋰⋰⒧⋰⋰⒜⋰⋰⒟⋰ ⋰⒣⋰⋰⒜⋰⋰⒤⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒨⋰⋰⒜⋰⋰⒟⋰⋰⒜⋰⋰⒭⋰⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒟⋰ ⋰⒦⋰⋰⒤⋰⋰⒟⋰⋰⒟⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒮⋰⋰⒜⋰⋰⒯⋰⋰⒣⋰ ⋰⒮⋰⋰⒪⋰ ⋰⒥⋰⋰⒜⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰ ⋰⒱⋰⋰⒪⋰⋰⒤⋰⋰⒞⋰⋰⒠⋰ ⋰⒣⋰⋰⒪⋰ ⋰⒥⋰⋰⒜⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒤⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒩⋰⋰⒤⋰⋰⒦⋰⋰⒜⋰⋰⒧⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒩⋰⋰⒜⋰⋰⒣⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰ ⋰⒮⋰⋰⒜⋰⋰⒦⋰⋰⒯⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰ ⋰⒧⋰⋰⒜⋰⋰⒰⋰⋰⒟⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰⋰⒭⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒫⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒤⋰⋰⒢⋰⋰⒩⋰⋰⒪⋰⋰⒭⋰⋰⒠⋰ ⋰⒦⋰⋰⒜⋰⋰⒤⋰⋰⒮⋰⋰⒠⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒝⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰ ⋰⒜⋰⋰⒜⋰⋰⒥⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒦⋰⋰⒜⋰⋰⒯⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰ ⋰⒥⋰⋰⒜⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒰⋰ ⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒤⋰⋰⒢⋰⋰⒩⋰⋰⒪⋰⋰⒭⋰⋰⒠⋰ ⋰⒦⋰⋰⒜⋰⋰⒤⋰⋰⒮⋰⋰⒠⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰ ⋰⒭⋰⋰⒜⋰ ⋰⒣⋰⋰⒜⋰⋰⒤⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒡⋰⋰⒜⋰⋰⒯⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰ ⋰⒨⋰⋰⒠⋰⋰⒭⋰⋰⒜⋰ ⋰⒧⋰⋰⒪⋰⋰⒟⋰⋰⒜⋰⋰⒜⋰ ⋰⒟⋰⋰⒜⋰⋰⒧⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒜⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒪⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰ ⋰⒜⋰⋰⒜⋰⋰⒫⋰ ⋰⒞⋰⋰⒫⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒦⋰⋰⒜⋰⋰⒧⋰⋰⒤⋰ ⋰⒥⋰⋰⒰⋰⋰⒝⋰⋰⒜⋰⋰⒩⋰ ⋰⒦⋰⋰⒜⋰⋰⒯⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒡⋰⋰⒠⋰⋰⒩⋰⋰⒦⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒩⋰⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰ ⋰⒥⋰⋰⒜⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒨⋰⋰⒜⋰⋰⒤⋰ ⋰⒦⋰⋰⒜⋰⋰⒝⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰⋰⒜⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒤⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒩⋰⋰⒤⋰⋰⒦⋰⋰⒜⋰⋰⒧⋰ ⋰⒦⋰⋰⒠⋰",
        "⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒥⋰⋰⒤⋰⋰⒩⋰⋰⒟⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒡⋰⋰⒜⋰⋰⒯⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒠⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰ ⋰⒥⋰⋰⒜⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰ ⋰⒜⋰⋰⒝⋰ ⋰⒯⋰⋰⒰⋰",
        "⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰ ⋰⒟⋰⋰⒜⋰⋰⒡⋰⋰⒜⋰⋰⒩⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰??⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒠⋰ ⋰⒧⋰⋰⒜⋰⋰⒰⋰⋰⒟⋰⋰⒠⋰ ⋰⒫⋰⋰⒠⋰⋰⒭⋰ ⋰⒢⋰⋰??⋰⋰⒰⋰⋰⒨⋰⋰⒜⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒦⋰⋰⒣⋰⋰⒜⋰⋰⒟⋰⋰⒠⋰ ⋰⒦⋰⋰⒣⋰⋰⒜⋰⋰⒟⋰⋰⒠⋰ ⋰⒧⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰ ⋰⒧⋰⋰⒠⋰⋰⒦⋰⋰⒤⋰⋰⒩⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒥⋰⋰⒣⋰⋰⒰⋰⋰⒦⋰⋰⒩⋰⋰⒠⋰ ⋰⒩⋰⋰⒜⋰⋰⒤⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰ ⋰⒝⋰⋰⒜⋰⋰⒩⋰⋰⒜⋰⋰⒜⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰ ⋰⒨⋰⋰⒠⋰⋰⒭⋰⋰⒜⋰ ⋰⒭⋰⋰⒠⋰⋰⒫⋰⋰⒧⋰⋰⒴⋰ ⋰⒣⋰⋰⒪⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰⋰⒜⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰ ⋰⒥⋰⋰⒜⋰⋰⒴⋰⋰⒠⋰⋰⒢⋰⋰⒤⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒩⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒜⋰⋰⒧⋰⋰⒰⋰ ⋰⒦⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒯⋰⋰⒪⋰ ⋰⒞⋰⋰⒫⋰ ⋰⒝⋰⋰⒪⋰⋰⒧⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰⋰⒰⋰⋰⒢⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒜⋰⋰⒯⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒥⋰⋰⒤⋰⋰⒩⋰⋰⒟⋰⋰⒜⋰ ⋰⒣⋰⋰⒪⋰⋰⒥⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒰⋰⋰⒯⋰⋰⒣⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰ ⋰⒡⋰⋰⒠⋰⋰⒩⋰⋰⒦⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒨⋰⋰⒜⋰⋰⒟⋰⋰⒭⋰⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰",
        "⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒥⋰⋰⒤⋰⋰⒩⋰⋰⒟⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒦⋰⋰⒪⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰ ⋰⒥⋰⋰⒜⋰⋰⒴⋰⋰⒠⋰⋰⒢⋰⋰⒤⋰ ⋰⒨⋰⋰⒠⋰⋰⒭⋰⋰⒠⋰ ⋰⒧⋰⋰⒜⋰⋰⒰⋰⋰⒟⋰⋰⒠⋰ ⋰⒫⋰⋰⒠⋰",
        "⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒤⋰⋰⒮⋰⋰⒠⋰ ⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰⋰⒜⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒟⋰⋰⒜⋰⋰⒡⋰⋰⒜⋰⋰⒩⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰⋰⒪⋰ ⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒨⋰⋰⒠⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒮⋰⋰⒜⋰⋰⒯⋰⋰⒣⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒝⋰⋰⒣⋰⋰⒤⋰ ⋰⒟⋰⋰⒜⋰⋰⒡⋰⋰⒜⋰⋰⒩⋰ ⋰⒣⋰⋰⒪⋰ ⋰⒥⋰⋰⒜⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒜⋰ ⋰⒩⋰⋰⒜⋰⋰⒣⋰⋰⒤⋰ ⋰⒣⋰⋰⒜⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰⋰⒟⋰⋰⒠⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒩⋰⋰⒤⋰⋰⒦⋰⋰⒜⋰⋰⒧⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰",
        "⋰⒢⋰⋰⒜⋰⋰⒤⋰⋰⒭⋰⋰⒝⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒜⋰⋰⒰⋰⋰⒧⋰⋰⒜⋰⋰⒟⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰⋰⒧⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰⋰⒫⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒮⋰⋰⒫⋰⋰⒠⋰⋰⒠⋰⋰⒟⋰ ⋰⒨⋰⋰⒜⋰⋰⒯⋰⋰⒞⋰⋰⒣⋰ ⋰⒦⋰⋰⒭⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰ ⋰⒢⋰⋰⒜⋰⋰⒭⋰⋰⒤⋰⋰⒝⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒞⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒯⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒡⋰⋰⒠⋰⋰⒦⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒠⋰⋰⒠⋰⋰⒥⋰",
        "⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒩⋰⋰⒜⋰⋰⒣⋰⋰⒤⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰⋰⒢⋰⋰⒤⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰⋰⒟⋰⋰⒠⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰ ⋰⒞⋰⋰⒫⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰ ⋰⒩⋰⋰⒤⋰⋰⒦⋰⋰⒜⋰⋰⒧⋰",
        "⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒩⋰⋰⒜⋰⋰⒣⋰⋰⒤⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰⋰⒢⋰⋰⒤⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒨⋰⋰⒠⋰⋰⒭⋰⋰⒠⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒯⋰⋰⒜⋰⋰⒢⋰ ⋰⒦⋰⋰⒜⋰⋰⒤⋰⋰⒮⋰⋰⒠⋰ ⋰⒦⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰⋰⒭⋰ ⋰⒧⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒥⋰⋰⒤⋰⋰⒩⋰⋰⒟⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒡⋰⋰⒜⋰⋰⒯⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒠⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰ ⋰⒥⋰⋰⒜⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰ ⋰⒜⋰⋰⒝⋰ ⋰⒯⋰⋰⒰⋰",
        "⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰ ⋰⒟⋰⋰⒜⋰⋰⒡⋰⋰⒜⋰⋰⒩⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒠⋰ ⋰⒧⋰⋰⒜⋰⋰⒰⋰⋰⒟⋰⋰⒠⋰ ⋰⒫⋰⋰⒠⋰⋰⒭⋰ ⋰⒢⋰⋰⒣⋰⋰⒰⋰⋰⒨⋰⋰⒜⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒦⋰⋰⒣⋰⋰⒜⋰⋰⒟⋰⋰⒠⋰ ⋰⒦⋰⋰⒣⋰⋰⒜⋰⋰⒟⋰⋰⒠⋰ ⋰⒧⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰ ⋰⒧⋰⋰⒠⋰⋰⒦⋰⋰⒤⋰⋰⒩⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒥⋰⋰⒣⋰⋰⒰⋰⋰⒦⋰⋰⒩⋰⋰⒠⋰ ⋰⒩⋰⋰⒜⋰⋰⒤⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰ ⋰⒝⋰⋰⒜⋰⋰⒩⋰⋰⒜⋰⋰⒜⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰ ⋰⒨⋰⋰⒠⋰⋰⒭⋰⋰⒜⋰ ⋰⒭⋰⋰⒠⋰⋰⒫⋰⋰⒧⋰⋰⒴⋰ ⋰⒣⋰⋰⒪⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰⋰⒜⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰ ⋰⒥⋰⋰⒜⋰⋰⒴⋰⋰⒠⋰⋰⒢⋰⋰⒤⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒩⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒜⋰⋰⒧⋰⋰⒰⋰ ⋰⒦⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒯⋰⋰⒪⋰ ⋰⒞⋰⋰⒫⋰ ⋰⒝⋰⋰⒪⋰⋰",
        "⋰Ⓑ⋰⋰⒜⋰⋰⒜⋰⋰⒫⋰ ⋰Ⓑ⋰⋰⒣⋰⋰⒤⋰ ⋰Ⓑ⋰⋰⒩⋰⋰⒜⋰⋰⒧⋰⋰⒠⋰ ⋰⒨⋰⋰⒰⋰⋰⒥⋰⋰⒠⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒜⋰ ⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒫⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒵⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒴⋰⋰⒜⋰⋰⒜⋰⋰⒟⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒯⋰⋰⒰⋰⋰⒥⋰⋰⒣⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒰⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒜⋰ ⋰⒩⋰⋰⒜⋰ ⋰⒯⋰⋰⒴⋰⋰⒨⋰⋰⒫⋰⋰⒜⋰⋰⒮⋰⋰⒮⋰",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰ ⋰⒰⋰⋰⒩⋰⋰⒡⋰⋰⒰⋰⋰⒩⋰⋰⒩⋰⋰⒴⋰ ⋰⒮⋰⋰⒲⋰⋰⒤⋰⋰⒫⋰⋰⒠⋰ ⋰⒨⋰⋰⒯⋰⋰⒯⋰ ⋰⒦⋰⋰⒭⋰",
        "⋰⒪⋰⋰⒣⋰ ⋰⒣⋰⋰⒠⋰⋰⒧⋰⋰⒧⋰⋰⒪⋰ ⋰⒝⋰⋰⒤⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒜⋰ ⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒫⋰ ⋰⒝⋰⋰⒤⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒤⋰ ⋰⒪⋰⋰⒭⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒱⋰ ⋰⒝⋰⋰⒤⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒤⋰ ⋰⒜⋰⋰⒜⋰⋰⒰⋰⋰⒦⋰⋰⒜⋰⋰⒯⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒭⋰⋰⒣⋰⋰⒜⋰ ⋰⒦⋰⋰⒭⋰.",
        "⋰⒪⋰⋰⒴⋰⋰⒴⋰ ⋰⒦⋰⋰⒤⋰⋰⒩⋰⋰⒩⋰⋰⒠⋰⋰⒭⋰ ⋰⒯⋰⋰⒰⋰⋰⒥⋰⋰⒣⋰⋰⒠⋰ ⋰⒢⋰⋰⒞⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒜⋰⋰⒜⋰⋰⒩⋰⋰⒠⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒫⋰⋰⒠⋰⋰⒭⋰⋰⒨⋰⋰⒤⋰⋰⒮⋰⋰⒮⋰⋰⒤⋰⋰⒪⋰⋰⒩⋰ ⋰⒦⋰⋰⒤⋰⋰⒮⋰⋰⒩⋰⋰⒠⋰ ⋰⒟⋰⋰⒤⋰.",
        "⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒦⋰⋰⒠⋰ ⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰⋰⒜⋰",
        "⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒦⋰⋰⒠⋰ ⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰⋰⒜⋰ ⋰⒠⋰⋰⒦⋰ ⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒭⋰.",
        "⋰⒮⋰⋰⒰⋰⋰⒩⋰ ⋰⒮⋰⋰⒰⋰⋰⒩⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒜⋰.",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒞⋰⋰⒜⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰.",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒯⋰⋰⒤⋰ ⋰⒥⋰⋰⒜⋰⋰⒯⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒯⋰⋰⒨⋰⋰⒭⋰.",
        "⋰⒦⋰⋰⒴⋰? ⋰⒥⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰ ⋰⒦⋰⋰⒤⋰⋰⒟⋰⋰⒟⋰⋰⒠⋰.",
        "⋰⒝⋰⋰⒤⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒤⋰ ⋰⒞⋰⋰⒪⋰⋰⒨⋰ ⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒢⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒫⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒯⋰⋰⒜⋰⋰⒢⋰ ⋰⒞⋰⋰⒭⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰ ⋰⒯⋰⋰⒰⋰",
        "⋰⒨⋰⋰⒰⋰⋰⒥⋰⋰⒣⋰⋰⒠⋰ ⋰⒞⋰⋰⒴⋰⋰⒜⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒝⋰⋰⒤⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒤⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒯⋰⋰⒨⋰⋰⒦⋰⋰⒞⋰ ⋰⒝⋰⋰⒮⋰",
        "⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒵⋰ ⋰⒫⋰⋰⒜⋰⋰⒫⋰⋰⒜⋰ ⋰⒝⋰⋰⒪⋰⋰⒧⋰",
        "⋰⒮⋰⋰⒤⋰⋰⒟⋰⋰⒠⋰ ⋰⒣⋰⋰⒪⋰⋰⒥⋰⋰⒜⋰ ⋰⒝⋰⋰⒤⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒜⋰⋰⒤⋰ ⋰⒜⋰⋰⒝⋰",
        "⋰⒣⋰⋰⒴⋰⋰⒠⋰ ⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒝⋰⋰⒣⋰⋰⒢⋰ ⋰⒨⋰⋰⒜⋰⋰⒯⋰ ⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰",
        "⋰⒝⋰⋰⒣⋰⋰⒢⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒜⋰⋰⒥⋰⋰⒥⋰",
        "⋰⒣⋰⋰⒴⋰⋰⒠⋰ ⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰ ⋰⒨⋰⋰⒜⋰⋰⒯⋰",
        "⋰⒣⋰⋰⒴⋰⋰⒠⋰ ⋰⒟⋰⋰⒰⋰⋰⒭⋰ ⋰⒣⋰⋰⒜⋰⋰⒯⋰⋰⒯⋰ ⋰⒨⋰⋰⒜⋰⋰⒟⋰⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰",
        "⋰⒦⋰⋰⒪⋰⋰⒤⋰ ⋰⒝⋰⋰⒜⋰⋰⒯⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒠⋰⋰⒮⋰⋰⒧⋰⋰⒤⋰⋰⒴⋰⋰⒠⋰ ⋰⒨⋰⋰⒜⋰⋰⒡⋰ ⋰⒞⋰⋰⒭⋰ ⋰⒭⋰⋰⒣⋰⋰⒜⋰ ⋰⒣⋰⋰⒰⋰ ⋰⒯⋰⋰⒰⋰⋰⒥⋰⋰⒣⋰⋰⒠⋰",
        "⋰⒦⋰⋰⒪⋰⋰⒤⋰ ⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒯⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒨⋰⋰⒜⋰⋰⒡⋰⋰⒤⋰ ⋰⒟⋰⋰⒠⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒨⋰⋰⒜⋰⋰⒡⋰⋰⒤⋰ ⋰⒨⋰⋰⒤⋰⋰⒧⋰ ⋰⒥⋰⋰⒜⋰⋰⒴⋰⋰⒠⋰⋰⒢⋰⋰⒤⋰ ⋰⒯⋰⋰⒰⋰⋰⒥⋰⋰⒣⋰⋰⒠⋰",
        "⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰⋰⒯⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒜⋰ ⋰⒨⋰⋰⒰⋰⋰⒥⋰⋰⒠⋰ ⋰⒮⋰⋰⒲⋰⋰⒤⋰⋰⒫⋰⋰⒠⋰ ⋰⒞⋰⋰⒭⋰⋰⒦⋰⋰⒠⋰",
        "⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒮⋰⋰⒲⋰⋰⒤⋰⋰⒫⋰⋰⒠⋰ ⋰⒞⋰⋰⒭⋰⋰⒦⋰⋰⒠⋰",
        "⋰⒡⋰⋰⒭⋰ ⋰⒝⋰⋰⒪⋰⋰⒧⋰⋰⒩⋰⋰⒜⋰ ⋰⒩⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰ ⋰⒧⋰⋰⒠⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒮⋰⋰⒲⋰⋰⒤⋰⋰⒫⋰⋰⒠⋰ ⋰⒞⋰⋰⒭⋰⋰⒦⋰⋰⒠⋰",
        "⋰⒞⋰⋰⒴⋰⋰⒜⋰ ⋰⒣⋰⋰⒰⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒴⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒫⋰⋰⒭⋰ ⋰⒦⋰⋰⒠⋰⋰⒮⋰⋰⒠⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒴⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰",
        "⋰⒨⋰⋰⒰⋰⋰⒥⋰⋰⒣⋰⋰⒠⋰ ⋰⒫⋰⋰⒯⋰⋰⒜⋰ ⋰⒯⋰⋰⒣⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒜⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒨⋰⋰⒠⋰⋰⒴⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒩⋰⋰⒯⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒴⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰",
        "⋰⒧⋰⋰⒪⋰⋰⒟⋰⋰⒠⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒰⋰⋰⒯⋰⋰⒭⋰ ⋰⒨⋰⋰⒞⋰",
        "⋰⒧⋰⋰⒰⋰⋰⒩⋰ ⋰⒨⋰⋰⒯⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒮⋰ ⋰⒨⋰⋰⒠⋰⋰⒭⋰⋰⒜⋰",
        "⋰⒩⋰⋰⒤⋰⋰⒦⋰⋰⒜⋰⋰⒧⋰ ⋰⒨⋰⋰⒜⋰⋰⒟⋰⋰⒜⋰⋰⒭⋰⋰⒞⋰⋰⒣⋰⋰⒟⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒪⋰⋰⒴⋰⋰⒠⋰ ⋰⒢⋰⋰⒜⋰⋰⒮⋰⋰⒣⋰⋰⒯⋰⋰⒤⋰ ⋰⒦⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰",
        "⋰⒨⋰⋰⒜⋰⋰⒦⋰⋰⒤⋰⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰",
        "⋰⒨⋰⋰⒜⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒦⋰ ⋰⒣⋰⋰⒜⋰⋰⒯⋰⋰⒣⋰ ⋰⒯⋰⋰⒪⋰⋰⒟⋰⋰⒣⋰ ⋰⒦⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒠⋰ ⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒫⋰ ⋰⒦⋰ ⋰⒨⋰⋰⒰⋰⋰⒣⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒡⋰⋰⒜⋰⋰⒮⋰⋰⒜⋰⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰",
        "⋰⒧⋰⋰⒠⋰⋰⒜⋰⋰⒱⋰⋰⒠⋰ ⋰⒧⋰⋰⒠⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰ ⋰⒫⋰⋰⒜⋰⋰⒮⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒩⋰⋰⒜⋰⋰⒤⋰ ⋰⒜⋰⋰⒴⋰⋰⒜⋰ ⋰⒨⋰⋰⒠⋰⋰⒦⋰⋰⒪⋰",
        "⋰⒧⋰⋰⒠⋰⋰⒜⋰⋰⒱⋰⋰⒠⋰ ⋰⒧⋰⋰⒠⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰ ⋰⒤⋰⋰⒟⋰⋰⒠⋰⋰⒭⋰ ⋰⒮⋰⋰⒠⋰",
        "⋰⒧⋰⋰⒠⋰⋰⒜⋰⋰⒱⋰⋰⒠⋰ ⋰⒧⋰⋰⒠⋰ ⋰⒥⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒲⋰⋰⒭⋰⋰⒩⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒜⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒧⋰⋰⒠⋰⋰⒜⋰⋰⒱⋰⋰⒠⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒧⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒮⋰⋰⒨⋰⋰⒥⋰⋰⒣⋰ ⋰⒝⋰⋰⒜⋰⋰⒯⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒧⋰⋰⒠⋰⋰⒜⋰⋰⒱⋰⋰⒠⋰ ⋰⒧⋰⋰⒠⋰",
        "⋰⒡⋰⋰⒜⋰⋰⒮⋰⋰⒯⋰ ⋰⒧⋰⋰⒠⋰⋰⒜⋰⋰⒱⋰⋰⒠⋰ ⋰⒧⋰⋰⒠⋰ ⋰⒦⋰⋰⒜⋰⋰⒨⋰⋰⒥⋰⋰⒪⋰⋰⒭⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒰⋰⋰⒯⋰⋰⒪⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰",
        "⋰⒪⋰⋰⒴⋰ ⋰⒣⋰⋰⒤⋰⋰⒥⋰⋰⒟⋰⋰⒠⋰ ⋰⒦⋰⋰⒣⋰⋰⒜⋰⋰⒩⋰⋰⒜⋰ ⋰⒦⋰⋰⒣⋰⋰⒜⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒨⋰⋰⒵⋰⋰⒪⋰⋰⒭⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒦⋰⋰⒪⋰ ⋰⒤⋰⋰⒧⋰⋰⒴⋰ ⋰⒭⋰⋰⒠⋰⋰⒴⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒞⋰⋰⒣⋰⋰⒜⋰⋰⒫⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒯⋰⋰⒨⋰⋰⒦⋰⋰⒞⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰⋰⒞⋰⋰⒣⋰⋰⒜⋰⋰⒫⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒯⋰⋰⒰⋰",
        "⋰⒮⋰⋰⒣⋰⋰⒤⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰⋰⒞⋰⋰⒣⋰⋰⒜⋰⋰⒫⋰",
        "⋰⒡⋰⋰⒭⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰⋰⒞⋰⋰⒣⋰⋰⒜⋰⋰⒫⋰",
        "⋰⒮⋰⋰⒣⋰⋰⒤⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰ ⋰⒲⋰⋰⒭⋰⋰⒩⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒜⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒴⋰⋰⒰⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒜⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰⋰⒞⋰⋰⒣⋰⋰⒜⋰⋰⒫⋰",
        "⋰⒫⋰⋰⒭⋰⋰⒪⋰⋰⒪⋰⋰⒡⋰ ⋰⒞⋰⋰⒭⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒴⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒫⋰⋰⒭⋰⋰⒪⋰⋰⒪⋰⋰⒡⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰ ⋰⒠⋰⋰⒴⋰",
        "⋰⒫⋰⋰⒭⋰⋰⒪⋰⋰⒪⋰⋰⒡⋰ ⋰⒣⋰⋰⒪⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒦⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒞⋰⋰⒣⋰⋰⒤⋰⋰⒧⋰⋰⒧⋰⋰⒜⋰⋰⒭⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰ ⋰⒝⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒪⋰⋰⒴⋰ ⋰⒣⋰⋰⒤⋰⋰⒥⋰⋰⒟⋰⋰⒠⋰ ⋰⒦⋰⋰⒣⋰⋰⒜⋰⋰⒩⋰⋰⒜⋰ ⋰⒦⋰⋰⒣⋰⋰⒜⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒨⋰⋰⒵⋰⋰⒪⋰⋰⒭⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒨⋰⋰⒜⋰⋰⒟⋰⋰⒭⋰⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰ ?",
        "⋰⒜⋰⋰⒝⋰ ⋰⒯⋰⋰⒦⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒴⋰⋰⒤⋰ ⋰⒣⋰⋰⒪⋰⋰⒢⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ?",
        "⋰⒩⋰⋰⒴⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒦⋰⋰⒰⋰⋰⒞⋰⋰⒣⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒥⋰⋰⒜⋰⋰⒩⋰⋰⒯⋰⋰⒜⋰ ⋰⒝⋰⋰⒮⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰ ⋰⒠⋰⋰⒴⋰",
        "⋰⒮⋰⋰⒝⋰⋰⒮⋰⋰⒠⋰ ⋰⒫⋰⋰⒣⋰⋰⒠⋰⋰⒧⋰⋰⒠⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒝⋰⋰⒪⋰⋰⒧⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒩⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒨⋰ ⋰⒦⋰⋰⒭⋰⋰⒠⋰",
        "⋰⒴⋰⋰⒜⋰⋰⒣⋰⋰⒜⋰ ⋰⒝⋰⋰⒣⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒜⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒞⋰⋰⒠⋰ ⋰⒫⋰⋰⒤⋰⋰⒧⋰⋰⒧⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒨⋰⋰⒜⋰⋰⒦⋰⋰⒜⋰⋰⒝⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒯⋰⋰⒪⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒠⋰⋰⒢⋰⋰⒤⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰ ⋰⒯⋰⋰⒪⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰",
        "⋰⒩⋰⋰⒤⋰⋰⒦⋰⋰⒜⋰⋰⒧⋰ ⋰⒨⋰⋰⒜⋰⋰⒟⋰⋰⒜⋰⋰⒭⋰⋰⒞⋰⋰⒣⋰⋰⒟⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒦⋰⋰⒠⋰ ⋰⒴⋰⋰⒣⋰⋰⒜⋰ ⋰⒮⋰⋰⒠⋰",
        "⋰⒞⋰⋰⒪⋰⋰⒵⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒣⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒣⋰⋰⒠⋰",
        "⋰⒩⋰⋰⒴⋰⋰⒯⋰⋰⒪⋰ ⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒫⋰ ⋰⒝⋰⋰⒪⋰⋰⒧⋰ ⋰⒨⋰⋰⒰⋰⋰⒥⋰⋰⒣⋰⋰⒠⋰",
        "⋰⒩⋰⋰⒴⋰⋰⒩⋰⋰⒴⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒣⋰⋰⒪⋰⋰⒢⋰⋰⒤⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒤⋰ ⋰⒥⋰⋰⒪⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰⋰⒯⋰⋰⒤⋰ ⋰⒥⋰⋰⒪⋰⋰⒢⋰⋰⒤⋰",
        "⋰⒯⋰⋰⒭⋰⋰⒴⋰ ⋰⒜⋰⋰⒨⋰⋰⒨⋰⋰⒤⋰ ⋰⒞⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒠⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒠⋰⋰⒨⋰⋰⒪⋰⋰⒥⋰⋰⒤⋰ ⋰⒟⋰⋰⒜⋰⋰⒧⋰ ⋰⒨⋰⋰⒞⋰",
        "⋰⒞⋰⋰⒴⋰⋰⒜⋰ ? ⋰⒞⋰⋰⒣⋰⋰⒨⋰⋰⒭⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒴⋰⋰⒜⋰ ⋰⒞⋰⋰⒴⋰⋰⒜⋰ ?",
        "⋰⒯⋰⋰⒨⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒭⋰⋰⒤⋰ ⋰⒣⋰⋰⒪⋰⋰⒢⋰⋰⒤⋰ ⋰⒡⋰⋰⒭⋰⋰⒭⋰⋰⒯⋰⋰⒪⋰",
        "⋰⒞⋰⋰⒴⋰⋰⒜⋰ ? ⋰⒦⋰⋰⒝⋰ ? ⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒞⋰⋰⒴⋰⋰⒜⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒦⋰⋰⒠⋰⋰⒦⋰",
        "⋰⒞⋰⋰⒴⋰⋰⒜⋰ ⋰⒮⋰⋰⒞⋰⋰⒣⋰ ⋰⒨⋰⋰⒠⋰⋰⒴⋰ ⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒞⋰⋰⒴⋰⋰⒜⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰ ⋰⒧⋰⋰⒤⋰ ⋰⒯⋰⋰⒰⋰⋰⒩⋰⋰⒠⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰",
        "⋰⒤⋰⋰⒯⋰⋰⒩⋰⋰⒜⋰ ⋰⒮⋰⋰⒞⋰⋰⒣⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒝⋰⋰⒪⋰⋰⒧⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒜⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒮⋰⋰⒞⋰⋰⒣⋰ ⋰⒨⋰⋰⒠⋰⋰⒴⋰ ⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰ ⋰⒧⋰⋰⒤⋰⋰⒜⋰ ⋰⒨⋰⋰⒠⋰⋰⒭⋰⋰⒠⋰ ⋰⒮⋰⋰⒯⋰⋰⒣⋰",
        "⋰⒨⋰⋰⒯⋰⋰⒧⋰⋰⒝⋰ ⋰⒯⋰⋰⒨⋰⋰⒭⋰",
        "⋰⒩⋰⋰⒴⋰⋰⒯⋰⋰⒪⋰",
        "⋰⒫⋰⋰⒰⋰⋰⒭⋰⋰⒜⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰ ⋰⒨⋰⋰⒞⋰",
        "⋰⒯⋰⋰⒨⋰⋰⒭⋰ ⋰⒡⋰⋰⒭⋰⋰⒭⋰⋰⒯⋰⋰⒪⋰",
        "⋰⒪⋰⋰⒣⋰ ⋰⒪⋰⋰⒦⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒧⋰⋰⒠⋰ ⋰⒡⋰⋰⒤⋰⋰⒭⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒟⋰⋰⒜⋰⋰⒨⋰⋰⒜⋰⋰⒟⋰",
        "⋰⒞⋰⋰⒴⋰⋰⒜⋰ ? ⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰⋰⒠⋰ ⋰⒫⋰⋰⒠⋰⋰⒣⋰⋰⒧⋰⋰⒠⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒠⋰⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰",
        "⋰⒩⋰⋰⒴⋰⋰⒯⋰⋰⒪⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒩⋰⋰⒠⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒱⋰⋰⒴⋰⋰⒜⋰⋰⒮⋰⋰⒯⋰ ⋰⒣⋰⋰⒰⋰",
        "⋰⒩⋰⋰⒴⋰⋰⒯⋰⋰⒪⋰ ⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒞⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒰⋰⋰⒞⋰⋰⒣⋰ ⋰⒝⋰⋰⒤⋰",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰⋰⒠⋰ ⋰⒞⋰⋰⒴⋰⋰⒜⋰ ? ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒴⋰⋰⒜⋰ ?",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒨⋰⋰⒯⋰ ⋰⒣⋰⋰⒮⋰⋰⒮⋰",
        "⋰⒴⋰⋰⒰⋰⋰⒭⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒤⋰ ⋰⒨⋰⋰⒪⋰⋰⒨⋰",
        "⋰⒜⋰⋰⒭⋰⋰⒠⋰ ⋰⒮⋰⋰⒝⋰⋰⒦⋰⋰⒤⋰ ⋰⒨⋰⋰??⋰⋰⒜⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒤⋰ ⋰⒪⋰⋰⒭⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒝⋰⋰⒤⋰",
        "⋰⒜⋰⋰⒭⋰⋰⒠⋰ ⋰⒤⋰⋰⒟⋰⋰⒜⋰⋰⒭⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒧⋰⋰⒠⋰ ⋰⒠⋰⋰⒦⋰ ⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒭⋰",
        "⋰⒯⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒤⋰ ⋰⒯⋰⋰⒭⋰⋰⒣⋰",
        "⋰⒠⋰⋰⒦⋰ ⋰⒧⋰⋰⒤⋰⋰⒩⋰⋰⒠⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒯⋰⋰⒨⋰⋰⒭⋰",
        "⋰⒬⋰",
        "⋰⒪⋰⋰⒞⋰⋰⒴⋰ ⋰⒜⋰⋰⒝⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒧⋰⋰⒠⋰",
        "⋰⒫⋰⋰⒠⋰⋰⒣⋰⋰⒠⋰⋰⒧⋰⋰⒠⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒰⋰",
        "⋰⒩⋰⋰⒴⋰⋰⒯⋰⋰⒪⋰",
        "⋰⒬⋰ ?",
        "⋰⒣⋰⋰⒴⋰⋰⒴⋰⋰⒴⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒜⋰ ⋰⒠⋰⋰⒦⋰ ⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒭⋰",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰⋰⒠⋰ ⋰⒮⋰⋰⒰⋰⋰⒩⋰ ⋰⒟⋰⋰⒪⋰⋰⒮⋰⋰⒯⋰ ⋰⒯⋰⋰⒨⋰⋰⒭⋰",
        "⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰ ⋰⒥⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰⋰⒡⋰ ⋰⒞⋰⋰⒭⋰⋰⒭⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰⋰⒠⋰ ⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒤⋰ ⋰⒤⋰⋰⒟⋰⋰⒜⋰⋰⒭⋰ ⋰⒜⋰⋰⒜⋰",
        "⋰⒞⋰⋰⒴⋰⋰⒜⋰ ⋰⒯⋰⋰⒨⋰⋰⒭⋰ ⋰⒡⋰⋰⒭⋰⋰⒭⋰⋰⒯⋰⋰⒪⋰",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰⋰⒠⋰ ⋰⒤⋰⋰⒟⋰⋰⒜⋰⋰⒭⋰ ⋰⒜⋰⋰⒜⋰⋰⒦⋰⋰⒠⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒧⋰⋰⒠⋰ ⋰⒞⋰⋰⒣⋰⋰⒨⋰⋰⒭⋰",
        "⋰⒩⋰⋰⒴⋰⋰⒯⋰⋰⒪⋰ ⋰⒜⋰⋰⒠⋰⋰⒮⋰⋰⒠⋰ ⋰⒣⋰⋰⒤⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰⋰⒠⋰ ⋰⒣⋰⋰⒴⋰⋰⒴⋰ ⋰⒜⋰⋰⒤⋰⋰⒮⋰⋰⒠⋰ ⋰⒣⋰⋰⒤⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒧⋰⋰⒠⋰⋰⒩⋰⋰⒜⋰",
        "⋰⒪⋰⋰⒭⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒧⋰⋰⒠⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒜⋰ ⋰⒪⋰⋰⒭⋰",
        "⋰⒣⋰⋰⒴⋰⋰⒴⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒪⋰ ⋰⒩⋰⋰⒜⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒪⋰ ⋰⒨⋰⋰⒯⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰ ⋰⒥⋰⋰⒜⋰⋰⒪⋰",
        "⋰⒝⋰⋰⒴⋰⋰⒴⋰⋰⒠⋰⋰⒠⋰ ⋰⒣⋰⋰⒴⋰⋰⒴⋰ ⋰⒞⋰⋰⒴⋰⋰⒜⋰ ?",
        "⋰⒬⋰⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒬⋰ ⋰⒭⋰⋰⒣⋰⋰⒠⋰ ⋰⒣⋰⋰⒪⋰ ?",
        "⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒞⋰⋰⒴⋰⋰⒜⋰ ⋰⒨⋰⋰⒞⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒨⋰⋰⒯⋰",
        "⋰Ⓙ⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒠⋰⋰⒥⋰",
        "⋰⒪⋰⋰⒭⋰ ⋰⒝⋰⋰⒟⋰⋰⒜⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰",
        "⋰⒪⋰⋰⒭⋰ ⋰⒝⋰⋰⒟⋰⋰⒜⋰",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰ ⋰⒦⋰⋰⒤⋰⋰⒟⋰⋰⒟⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒝⋰⋰⒰⋰⋰⒭⋰",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰ ⋰⒦⋰⋰⒠⋰⋰⒠⋰⋰⒟⋰⋰⒠⋰",
        "⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒧⋰⋰⒜⋰⋰⒟⋰⋰⒦⋰⋰⒠⋰",
        "⋰Ⓙ⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒝⋰⋰⒠⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒰⋰",
        "⋰⒨⋰⋰⒦⋰⋰⒧⋰ ⋰⒰⋰⋰⒯⋰⋰⒣⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒩⋰⋰⒜⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰⋰⒧⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒥⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒞⋰⋰⒠⋰",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰⋰⒦⋰⋰⒠⋰ ⋰⒧⋰⋰⒪⋰⋰⒟⋰⋰⒠⋰ ⋰⒨⋰⋰⒭⋰⋰⒠⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒴⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒟⋰⋰⒜⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒡⋰⋰⒰⋰⋰⒟⋰⋰⒟⋰⋰⒜⋰",
        "⋰⒨⋰⋰⒦⋰⋰⒧⋰ ⋰⒰⋰⋰⒯⋰⋰⒣⋰ ⋰⒝⋰⋰⒠⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰⋰⒞⋰⋰⒪⋰⋰⒟⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒝⋰⋰⒰⋰⋰⒭⋰ ⋰⒟⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒡⋰⋰⒰⋰⋰⒟⋰⋰⒟⋰⋰⒜⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒧⋰⋰⒪⋰⋰⒟⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒱⋰⋰⒜⋰",
        "⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒠⋰⋰⒯⋰⋰⒠⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰ ⋰⒢⋰⋰⒜⋰⋰⒴⋰⋰⒜⋰",
        "⋰Ⓙ⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒭⋰ ⋰⒮⋰⋰⒫⋰⋰⒜⋰⋰⒨⋰",
        "⋰⒨⋰⋰⒞⋰ ⋰⒮⋰⋰⒫⋰⋰⒜⋰⋰⒨⋰ ⋰⒭⋰⋰⒪⋰⋰⒦⋰⋰⒠⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒮⋰⋰⒫⋰⋰⒜⋰⋰⒨⋰ ⋰⒦⋰⋰⒭⋰",
        "⋰⒮⋰⋰⒫⋰⋰⒜⋰⋰⒨⋰ ⋰⒦⋰⋰⒭⋰.⋰⒨⋰⋰⒜⋰⋰⒜⋰⋰⒦⋰⋰⒠⋰ ⋰⒧⋰⋰⒪⋰⋰⒟⋰⋰⒠⋰",
        "⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒠⋰ ⋰⒮⋰⋰⒫⋰⋰⒜⋰⋰⒨⋰ ⋰⒦⋰⋰⒭⋰",
        "⋰⒮⋰⋰⒫⋰⋰⒜⋰⋰⒨⋰ ⋰⒦⋰⋰⒭⋰ ⋰⒦⋰⋰⒤⋰⋰⒟⋰",
        "⋰⒩⋰⋰⒪⋰⋰⒪⋰⋰⒝⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒰⋰",
        "⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒠⋰⋰⒯⋰⋰⒠⋰",
        "⋰⒩⋰⋰⒪⋰⋰⒪⋰⋰⒝⋰ ⋰Ⓙ⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰ ⋰⒲⋰⋰⒭⋰⋰⒩⋰⋰⒜⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰",
        "⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒜⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒩⋰⋰⒪⋰⋰⒪⋰⋰⒝⋰",
        "⋰⒰⋰⋰⒯⋰⋰⒣⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰ ⋰⒩⋰⋰⒪⋰⋰⒪⋰⋰⒝⋰",
        "⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒣⋰⋰⒪⋰ ⋰⒩⋰⋰⒪⋰⋰⒪⋰⋰⒝⋰",
        "⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒝⋰⋰⒩⋰⋰⒥⋰⋰⒜⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒩⋰⋰⒪⋰⋰⒪⋰⋰⒝⋰",
        "⋰⒨⋰⋰⒜⋰⋰⒦⋰⋰⒤⋰⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒩⋰⋰⒪⋰⋰⒪⋰⋰⒝⋰",
        "⋰⒣⋰⋰⒜⋰⋰⒧⋰⋰⒦⋰⋰⒠⋰",
        "⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒣⋰⋰⒪⋰ ⋰⒩⋰⋰⒪⋰⋰⒪⋰⋰⒝⋰",
        "⋰⒨⋰⋰⒜⋰⋰⒦⋰⋰⒤⋰⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰",
        "⋰⒨⋰⋰⒜⋰⋰⒦⋰⋰⒤⋰⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒱⋰⋰⒜⋰",
        "⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒠⋰⋰⒯⋰⋰⒠⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰ ⋰⒢⋰⋰⒜⋰⋰⒴⋰⋰⒜⋰",
        "⋰Ⓓ⋰⋰⒪⋰⋰⒮⋰⋰⒯⋰",
        ]
        cr_texts = [
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇰​ะะ🇦​ะ ะ🇧​ะะ🇴​ะะ🇸​ะะ🇪​ะะ🇼​ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะะ🇰​ะะ🇪​ะะ🇧​ะะ🇦​ะะ🇨​ะะ🇭​ะะ🇪​ะ, ะ🇹​ะะ🇺​ะ ะ🇧​ะะ🇭​ะะ🇮​ะ ะ🇰​ะะ🇮​ะะ🇸​ะะ🇸​ะะ🇦​ะะ🇬​ะะ🇦​ะ",
        "ะ🇦​ะะ🇦​ะะ🇯​ะ ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇰​ะะ🇦​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ, ะ🇹​ะะ🇺​ะ ะ🇰​ะะ🇾​ะะ🇦​ะ ะ🇭​ะะ🇦​ะะ🇮​ะ",
        "ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇷​ะะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะ, ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇰​ะะ🇦​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇧​ะะ🇭​ะะ🇪​ะะ🇳​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ, ะ🇹​ะะ🇺​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะ",
        "ะ🇨​ะะ🇭​ะะ🇺​ะะ🇩​ะ ะ🇯​ะะ🇦​ะ, ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇩​ะะ🇮​ะะ🇩​ะะ🇮​ะ ะ🇷​ะะ🇳​ะะ🇩​ะะ🇮​ะ",
        "ะ🇸​ะะ🇱​ะะ🇴​ะะ🇼​ะ, ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇮​ะะ🇾​ะะ🇦​ะ ะ🇨​ะะ🇮​ะะ🇴​ะะ🇩​ะะ🇺​ะ",
        "ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ, ะ🇹​ะะ🇺​ะ ะ🇰​ะะ🇾​ะะ🇦​ะ ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇸​ะะ🇰​ะะ🇹​ะะ🇦​ะ",
        "ะ🇧​ะะ🇭​ะะ🇦​ะะ🇰​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ, ะ🇹​ะะ🇲​ะะ🇦​ะ ะ🇨​ะะ🇴​ะะ🇩​ะะ🇺​ะ",
        "ะ🇸​ะะ🇱​ะะ🇴​ะะ🇼​ะ ะ🇫​ะะ🇮​ะะ🇷​ะะ🇸​ะะ🇪​ะ, ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇰​ะะ🇦​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ",
        "ะ🇨​ะะ🇺​ะะ🇩​ะะ🇬​ะะ🇷​ะะ🇮​ะะ🇧​ะ, ะ🇹​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะ ะ🇩​ะะ🇴​ะะ🇺​ะ",
        "ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇨​ะะ🇴​ะะ🇩​ะะ🇺​ะ, ะ🇳​ะะ🇪​ะะ🇹​ะ ะ🇴​ะะ🇳​ะ ะ🇴​ะะ🇫​ะะ🇫​ะ ะ🇼​ะะ🇦​ะะ🇱​ะะ??​ะ ะ🇷​ะะ🇳​ะะ🇩​ะะ??​ะ",
        "ะ🇴​ะะ🇾​ะะ🇪​ะ ะ🇹​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะ ะ🇨​ะะ🇴​ะะ🇩​ะะ🇺​ะ, ะ🇮​ะะ🇩​ะะ🇭​ะะ🇦​ะะ🇷​ะ ะ🇦​ะะ🇦​ะะ🇰​ะะ🇪​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ",
        "ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇷​ะะ🇩​ะะ🇺​ะ, ะ🇴​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะะ🇰​ะะ🇪​ะ ะ🇱​ะะ🇴​ะะ🇩​ะะ🇪​ะะ🇪​ะ",
        "ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇪​ะะ🇪​ะะ🇯​ะ, ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ ะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะะ🇺​ะ",
        "ะ🇸​ะะ🇺​ะะ🇦​ะะ🇷​ะ ะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇪​ะะ🇪​ะะ🇯​ะ, ะ🇳​ะะ🇪​ะะ🇹​ะ ะ🇴​ะะ🇫​ะะ🇫​ะ ะ🇴​ะะ🇳​ะ ะ🇰​ะะ🇷​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ ะ🇱​ะะ🇦​ะะ🇩​ะะ🇰​ะะ🇪​ะ",
        "ะ🇹​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะ ะ🇨​ะะ🇺​ะะ🇩​ะะ🇮​ะ ะ🇰​ะะ🇪​ะะ🇸​ะะ🇪​ะ, ะ🇨​ะะ🇭​ะะ🇺​ะะ🇵​ะ ะ🇸​ะะ🇱​ะะ🇴​ะะ🇼​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇭​ะะ🇦​ะะ🇷​ะะ🇨​ะะ🇴​ะะ🇩​ะ",
        "ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇨​ะะ🇴​ะะ🇩​ะะ🇺​ะ ะ🇰​ะะ🇷​ะ ะ🇲​ะะ🇸​ะะ🇬​ะ ะ🇩​ะะ🇪​ะะ🇱​ะะ🇪​ะะ🇹​ะะ🇪​ะ, ะ🇴​ะะ🇮​ะ ะ🇸​ะะ🇺​ะะ🇦​ะะ🇷​ะ ะ🇰​ะะ🇪​ะ ะ🇱​ะะ🇦​ะะ🇩​ะะ🇰​ะะ🇪​ะ",
        "ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ ะ🇫​ะะ🇺​ะะ🇫​ะะ🇮​ะ, ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇩​ะะ🇮​ะะ🇩​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇩​ะะ🇮​ะ",
        "ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ ะ🇩​ะะ🇮​ะะ🇰​ะะ🇭​ะะ🇦​ะ, ะ🇨​ะะ🇺​ะะ🇩​ะ ะ🇦​ะะ🇧​ะ",
        "ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ, ะ🇧​ะะ🇭​ะะ🇦​ะะ🇰​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ",
        "ะ🇨​ะะ🇺​ะะ🇩​ะะ🇱​ะะ🇪​ะ ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇷​ะะ🇺​ะ, ะ🇹​ะะ🇲​ะะ🇰​ะะ🇱​ะ ะ🇨​ะะ🇺​ะะ🇩​ะะ🇱​ะะ🇪​ะ ะ🇬​ะะ🇷​ะะ🇮​ะะ🇧​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇧​ะะ🇪​ะะ🇭​ะะ🇪​ะะ🇳​ะ ะ🇻​ะะ🇪​ะะ🇸​ะะ🇮​ะะ🇾​ะะ🇦​ะะ🇦​ะ ะ🇷​ะะ🇳​ะะ🇩​ะะ🇮​ะ, ะ🇮​ะะ🇹​ะะ🇳​ะะ🇦​ะ ะ🇬​ะะ🇳​ะะ🇩​ะะ🇦​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇩​ะะ🇦​ะ ะ🇹​ะะ🇺​ะ ะ🇫​ะะ🇮​ะะ🇷​ะะ🇸​ะะ🇪​ะ ะ🇳​ะะ🇪​ะะ🇹​ะ ะ🇴​ะะ🇳​ะ ะ🇴​ะะ🇫​ะะ🇫​ะ",
        "ะ🇬​ะะ🇷​ะะ🇮​ะะ🇧​ะ ะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇪​ะะ🇹​ะะ🇪​ะ, ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇯​ะะ🇦​ะ ะ🇱​ะะ🇴​ะะ🇩​ะะ🇪​ะ ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇦​ะะ🇷​ะะ🇺​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ",
        "ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇷​ะะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะะ🇦​ะ, ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ",
        "ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ, ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇪​ะะ🇾​ะ ะ🇨​ะะ🇵​ะ",
        "ะ🇨​ะะ🇵​ะ ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇪​ะะ🇭​ะะ🇭​ะ, ะ🇨​ะะ🇵​ะ ะ🇹​ะะ🇲​ะะ🇰​ะะ🇱​ะ ะ🇲​ะะ🇪​ะะ🇭​ะ",
        "ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ, ะ🇦​ะะ🇧​ะะ🇪​ะ ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ",
        "ะ🇩​ะะ🇴​ะะ🇺​ะะ🇧​ะะ🇱​ะะ🇪​ะ ะ🇸​ะะ🇪​ะะ🇳​ะะ🇩​ะ ะ🇰​ะะ🇴​ะ ะ🇨​ะะ🇵​ะ ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ ะ🇨​ะะ🇴​ะะ🇩​ะะ🇺​ะ, ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇪​ะ ะ🇨​ะะ🇵​ะ ะ🇨​ะะ🇴​ะะ🇩​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ ะ🇦​ะะ🇦​ะะ🇯​ะ ะ🇲​ะะ🇪​ะะ🇭​ะะ🇭​ะ",
        "ะ🇭​ะะ🇹​ะ ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇩​ะะ🇦​ะะ🇱​ะะ🇦​ะะ🇱​ะ ะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇪​ะะ🇹​ะะ🇪​ะ., ะ🇷​ะะ🇳​ะะ🇩​ะะ🇾​ะ ะ🇯​ะะ🇱​ะะ🇩​ะะ🇮​ะ ะ🇯​ะะ🇱​ะะ🇩​ะะ🇮​ะ ะ🇨​ะะ🇺​ะะ🇩​ะะ🇶​ะ ะ🇹​ะะ🇷​ะะ🇾​ะะ🇲​ะะ🇦​ะ",
        "ะ🇵​ะะ🇦​ะะ🇷​ะะ🇦​ะ ะ🇱​ะะ🇮​ะะ🇰​ะะ🇭​ะะ🇪​ะะ🇬​ะะ🇦​ะ.., ะ🇹​ะะ🇷​ะะ🇦​ะ ะ🇷​ะะ🇳​ะะ🇩​ะะ🇭​ะะ🇧​ะะ🇭​ะะ🇦​ะะ🇰​ะ",
        "ะ🇱​ะะ🇦​ะะ🇬​ะะ🇩​ะะ🇮​ะ ะ🇰​ะะ🇪​ะ ะ🇱​ะะ🇦​ะะ🇩​ะะ🇨​ะะ🇪​ะ ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ, ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ ะ🇱​ะะ🇦​ะะ🇬​ะะ🇩​ะะ🇮​ะ ะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇪​ะะ🇹​ะะ🇪​ะ..",
        "ะ🇨​ะะ🇺​ะะ🇩​ะะ🇰​ะะ🇪​ะ ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ, ะ🇧​ะะ🇭​ะะ🇮​ะะ🇰​ะะ🇦​ะะ🇷​ะะ🇮​ะ ะ🇱​ะะ🇺​ะะ🇳​ะะ🇩​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ??​ะ ะ🇲​ะะ🇪​ะะ🇷​ะะ🇦​ะ.",
        "ะ🇱​ะะ🇴​ะะ🇼​ะ ะ🇱​ะะ🇪​ะะ🇻​ะะ🇪​ะะ🇱​ะ ะ🇨​ะะ🇵​ะ ะ🇨​ะะ🇷​ะ, ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ ะ🇱​ะะ🇴​ะะ🇼​ะ ะ🇱​ะะ🇪​ะะ🇻​ะะ🇪​ะะ🇱​ะ ะ🇼​ะะ🇪​ะะ🇦​ะะ🇰​ะ",
        "ะ🇲​ะะ🇪​ะะ🇷​ะะ🇪​ะ ะ🇱​ะะ🇺​ะะ🇳​ะะ🇩​ะ ะ🇵​ะะ🇪​ะ ะ🇪​ะะ🇾​ะ ะ🇹​ะะ🇺​ะ ะ🇭​ะะ🇮​ะะ🇯​ะะ🇩​ะะ🇪​ะ, ะ🇫​ะะ🇷​ะะ🇪​ะะ🇪​ะ ะ🇨​ะะ🇺​ะะ🇩​ะะ🇼​ะะ🇦​ะ ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะะ🇰​ะะ🇴​ะ",
        "ะ🇫​ะะ🇷​ะะ🇪​ะะ🇪​ะ ะ🇲​ะะ🇪​ะะ🇾​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ ะ🇹​ะะ🇺​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ, ะ🇹​ะะ🇺​ะ ะ🇧​ะะ🇭​ะะ🇮​ะ ะ🇰​ะะ🇮​ะ ะ🇰​ะะ🇾​ะะ🇦​ะ ะ🇭​ะะ🇦​ะะ🇮​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇨​ะะ🇱​ะะ🇦​ะะ🇮​ะะ🇲​ะ ะ🇨​ะะ🇷​ะะ🇼​ะะ🇦​ะ, ะ🇹​ะะ🇺​ะ ะ🇰​ะะ🇾​ะะ🇦​ะ ะ🇧​ะะ🇭​ะะ🇮​ะ ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇸​ะะ🇰​ะะ🇹​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇧​ะะ🇭​ะะ🇪​ะะ🇳​ะ ะ🇻​ะะ🇪​ะะ🇸​ะะ🇮​ะะ🇾​ะะ🇦​ะะ🇦​ะ ะ🇷​ะะ🇳​ะะ🇩​ะะ🇮​ะ, ะ??​ะะ🇺​ะ ะ🇰​ะะ🇾​ะะ🇦​ะ ะ🇨​ะะ??​ะะ🇺​ะะ🇩​ะ ะ🇯​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇩​ะะ🇮​ะะ🇩​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇩​ะะ🇮​ะ, ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ ะ🇩​ะะ🇮​ะะ🇰​ะะ🇭​ะะ🇦​ะ",
        "ะ🇨​ะะ🇺​ะะ🇩​ะ ะ🇦​ะะ🇧​ะ, ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ",
        "ะ🇧​ะะ🇭​ะะ🇦​ะะ🇰​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ, ะ🇨​ะะ🇺​ะะ🇩​ะะ🇱​ะะ🇪​ะ ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇷​ะะ🇺​ะ",
        "ะ🇹​ะะ🇲​ะะ🇰​ะะ🇱​ะ ะ🇨​ะะ🇺​ะะ🇩​ะะ🇱​ะะ🇪​ะ ะ🇬​ะะ🇷​ะะ🇮​ะะ🇧​ะ, ะ🇹​ะะ🇪​ะะ??​ะะ🇾​ะ ะ🇧​ะะ🇪​ะะ🇭​ะะ🇪​ะะ🇳​ะ ะ🇻​ะะ🇪​ะะ🇸​ะะ🇮​ะะ🇾​ะะ🇦​ะะ🇦​ะ ะ🇷​ะะ🇳​ะะ🇩​ะะ🇮​ะ",
        "ะ🇮​ะะ🇹​ะะ🇳​ะะ🇦​ะ ะ🇬​ะะ🇳​ะะ🇩​ะะ🇦​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇩​ะะ🇦​ะ ะ🇹​ะะ🇺​ะ ะ🇫​ะะ🇮​ะะ🇷​ะะ🇸​ะะ🇪​ะ ะ🇳​ะะ🇪​ะะ🇹​ะ ะ🇴​ะะ🇳​ะ ะ🇴​ะะ🇫​ะะ🇫​ะ, ะ🇬​ะะ🇷​ะะ🇮​ะะ🇧​ะ ะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇪​ะะ🇹​ะะ🇪​ะ",
        "ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇯​ะะ🇦​ะ ะ🇱​ะะ🇴​ะะ🇩​ะะ🇪​ะ ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇦​ะะ🇷​ะะ🇺​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ, ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇷​ะะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะะ🇦​ะ",
        "ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ, ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ",
        "ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇪​ะะ🇾​ะ ะ🇨​ะะ🇵​ะ, ะ🇨​ะะ🇵​ะ ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇪​ะะ🇭​ะะ🇭​ะ",
        "ะ🇨​ะะ🇵​ะ ะ🇹​ะะ🇲​ะะ🇰​ะะ🇱​ะ ะ🇲​ะะ🇪​ะะ🇭​ะ, ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ",
        "ะ??​ะะ🇧​ะะ🇪​ะ ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ, ะ🇩​ะะ🇴​ะะ🇺​ะะ🇧​ะะ🇱​ะะ🇪​ะ ะ🇸​ะะ🇪​ะะ🇳​ะะ🇩​ะ ะ🇰​ะะ🇴​ะ ะ🇨​ะะ🇵​ะ ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ ะ🇨​ะะ🇴​ะะ🇩​ะะ🇺​ะ",
        "ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇪​ะ ะ🇨​ะะ🇵​ะ ะ🇨​ะะ🇴​ะะ🇩​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ ะ🇦​ะะ🇦​ะะ🇯​ะ ะ🇲​ะะ🇪​ะะ🇭​ะะ🇭​ะ, ะ🇭​ะะ🇹​ะ ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇩​ะะ🇦​ะะ🇱​ะะ🇦​ะะ🇱​ะ ะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇪​ะะ🇹​ะะ🇪​ะ.",
        "ะ🇷​ะะ🇳​ะะ🇩​ะะ🇾​ะ ะ🇯​ะะ🇱​ะะ🇩​ะะ🇮​ะ ะ🇯​ะะ🇱​ะะ🇩​ะะ🇮​ะ ะ🇨​ะะ🇺​ะะ🇩​ะะ🇶​ะ ะ🇹​ะะ🇷​ะะ🇾​ะะ🇲​ะะ🇦​ะ, ะ🇵​ะะ🇦​ะะ🇷​ะะ🇦​ะ ะ🇱​ะะ🇮​ะะ🇰​ะะ🇭​ะะ🇪​ะะ🇬​ะะ🇦​ะ..",
        "ะ🇹​ะะ🇷​ะะ🇦​ะ ะ🇷​ะะ🇳​ะะ🇩​ะะ🇭​ะะ🇧​ะะ🇭​ะะ🇦​ะะ🇰​ะ, ะ🇱​ะะ🇦​ะะ🇬​ะะ🇩​ะะ🇮​ะ ะ🇰​ะะ🇪​ะ ะ🇱​ะะ🇦​ะะ🇩​ะะ🇨​ะะ🇪​ะ ะ??​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ",
        "ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ ะ🇱​ะะ🇦​ะะ🇬​ะะ🇩​ะะ🇮​ะ ะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇪​ะะ🇹​ะะ🇪​ะ.., ะ🇨​ะะ🇺​ะะ🇩​ะะ🇰​ะะ🇪​ะ ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ",
        "ะ🇧​ะะ🇭​ะะ🇮​ะะ🇰​ะะ🇦​ะะ🇷​ะะ🇮​ะ ะ🇱​ะะ🇺​ะะ🇳​ะะ🇩​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇸​ะ ะ🇲​ะะ🇪​ะะ🇷​ะะ🇦​ะ., ะ🇱​ะะ🇴​ะะ🇼​ะ ะ🇱​ะะ🇪​ะะ🇻​ะะ🇪​ะะ🇱​ะ ะ🇨​ะะ🇵​ะ ะ🇨​ะะ🇷​ะ",
        "ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ ะ🇱​ะะ🇴​ะะ🇼​ะ ะ🇱​ะะ🇪​ะะ🇻​ะะ🇪​ะะ🇱​ะ ะ🇼​ะะ🇪​ะะ🇦​ะะ🇰​ะ, ะ🇲​ะะ🇪​ะะ🇷​ะะ🇪​ะ ะ🇱​ะะ🇺​ะะ🇳​ะะ🇩​ะ ะ🇵​ะะ🇪​ะ ะ🇪​ะะ🇾​ะ ะ🇹​ะะ🇺​ะ ะ🇭​ะะ🇮​ะะ🇯​ะะ🇩​ะะ🇪​ะ",
        "ะ🇫​ะะ🇷​ะะ🇪​ะะ🇪​ะ ะ🇨​ะะ🇺​ะะ🇩​ะะ🇼​ะะ🇦​ะ ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะะ🇰​ะะ🇴​ะ, ะ🇫​ะะ🇷​ะะ🇪​ะะ🇪​ะ ะ🇲​ะะ🇪​ะะ🇾​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ ะ🇹​ะะ🇺​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇨​ะะ🇱​ะะ🇦​ะะ🇮​ะะ🇲​ะ ะ🇨​ะะ🇷​ะะ🇼​ะะ🇦​ะ, ะ🇹​ะะ🇺​ะ ะ🇰​ะะ🇾​ะะ🇦​ะ ะ🇧​ะะ🇭​ะะ🇮​ะ ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇸​ะะ🇰​ะะ🇹​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇧​ะะ🇭​ะะ🇪​ะะ🇳​ะ ะ🇻​ะะ🇪​ะะ🇸​ะะ🇮​ะะ🇾​ะะ🇦​ะะ🇦​ะ ะ🇷​ะะ🇳​ะะ🇩​ะะ🇮​ะ, ะ🇹​ะะ🇺​ะ ะ🇰​ะะ🇾​ะะ🇦​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇩​ะ ะ🇯​ะะ🇦​ะ"
        "ะ🇯ะะ🇦ะะ🇱ะะ🇩ะะ🇮ะ ะ🇱ะะ🇮ะะ🇰ะะ🇭ะ ะ🇷ะะ🇳ะะ🇩ะะ🇾ะะ🇰ะะ🇪ะ ะ🇧ะะ🇪ะะ🇯ะ",
        "ะ🇴ะะ🇷ะ ะ🇧ะะ🇩ะะ🇦ะ ะ🇱ะะ🇮ะะ🇰ะะ🇭ะ",
        "ะ🇴ะะ🇷ะ ะ🇧ะะ🇩ะะ🇦ะ",
        "ะ🇴ะะ🇷ะ ะ🇧ะะ🇩ะะ🇦ะ ะ🇴ะะ🇾ะะ🇪ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇰ะะ🇦ะ ะ🇧ะะ🇺ะะ🇷ะ",
        "ะ🇴ะะ🇾ะะ🇪ะ ะ🇰ะะ🇪ะะ🇩ะะ🇪ะ",
        "ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะ ะ🇰ะะ🇪ะ ะ🇱ะะ🇦ะะ🇩ะะ🇰ะะ🇪ะ",
        "ะ🇯ะะ🇦ะะ🇱ะะ🇩ะะ🇮ะ ะ🇱ะะ🇮ะะ🇰ะะ🇭ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะะ🇳ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇺ะ",
        "ะ🇲ะะ🇰ะะ🇱ะ ะ??ะะ🇹ะะ🇭ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇨ะะ🇨ะะ🇭ะะ🇪ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇳ะะ🇦ะะ🇳ะะ🇮ะ ะ🇲ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇱ะ",
        "ะ🇹ะะ🇪ะะ🇯ะ ะ🇱ะะ🇮ะะ🇰ะะ🇭ะ ะ🇷ะะ🇳ะะ🇩ะะ🇨ะะ🇪ะ",
        "ะ🇴ะะ🇾ะะ🇪ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇪ะ ะ🇱ะะ🇴ะะ🇩ะะ🇪ะ ะ🇲ะะ🇷ะะ🇪ะะ🇳ะะ🇬ะะ🇦ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇾ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇮ะะ🇾ะะ🇦ะ ะ🇰ะะ🇮ะ ะ🇬ะะ🇦ะะ🇳ะะ🇩ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇩ะะ🇦ะะ🇩ะะ🇮ะ ะ🇰ะะ🇦ะ ะ🇫ะะ🇺ะะ🇩ะะ🇩ะะ🇦ะ",
        "ะ🇲ะะ🇰ะะ🇱ะ ะ🇺ะะ🇹ะะ🇭ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะะ🇳ะะ🇨ะะ🇴ะะ🇩ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ??ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇰ะะ🇮ะ ะ🇧ะะ🇺ะะ🇷ะ ะ🇩ะะ🇪ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇰ะะ🇦ะ ะ🇫ะะ🇺ะะ🇩ะะ🇩ะะ🇦ะ ะ🇲ะะ🇪ะ ะ🇱ะะ🇦ะะ🇺ะะ🇩ะะ🇦ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇨ะะ🇭ะะ🇺ะะ🇩ะะ🇻ะะ🇦ะ",
        "ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇪ะะ🇹ะะ🇪ะ ะ🇲ะะ🇦ะะ🇷ะ ะ🇬ะะ🇦ะะ🇾ะะ🇦ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะ ะ🇲ะะ🇷ะะ🇺ะ",
        "ะ🇯ะะ🇦ะะ🇱ะะ🇮ะะ🇩ะ ะ🇰ะะ🇷ะ ะ🇸ะะ🇵ะะ🇦ะะ🇲ะ",
        "ะ🇲ะะ🇨ะ ะ🇸ะะ🇵ะะ🇦ะะ🇲ะ ะ🇷ะะ🇴ะะ🇰ะะ🇪ะะ🇳ะะ🇬ะะ🇦ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะ ะ🇸ะะ🇵ะะ🇦ะะ🇲ะ ะ🇰ะะ🇷ะ",
        "ะ🇸ะะ🇵ะะ🇦ะะ🇲ะ ะ🇰ะะ🇷ะ.ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇪ะ ะ🇱ะะ🇴ะะ🇩ะะ🇪ะ",
        "ะ🇷ะะ🇳ะะ🇮ะะ🇩ะ ะ🇰ะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇪ะ ะ🇸ะะ🇵ะะ🇦ะะ🇲ะ ะ🇰ะะ🇷ะ",
        "ะ🇸ะะ🇵ะะ🇦ะะ🇲ะ ะ🇰ะะ🇷ะ ะ🇰ะะ🇮ะะ🇩ะ",
        "ะ🇳ะะ🇴ะะ🇴ะะ🇧ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇺ะ",
        "ะ🇷ะะ🇳ะะ🇩ะะ🇮ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇪ะะ🇹ะะ🇪ะ",
        "ะ🇳ะะ🇴ะะ🇴ะะ🇧ะ ะ??ะะ🇦ะะ🇱ะะ🇩ะะ🇮ะ ะ🇱ะะ🇮ะะ🇰ะะ🇭ะ ะ🇼ะะ🇷ะะ🇳ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะ",
        "ะ🇨ะะ🇺ะะ🇩ะ ะ🇬ะะ🇦ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇳ะะ🇴ะะ🇴ะะ🇧ะ",
        "ะ🇺ะะ🇹ะะ🇭ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇾ะะ🇰ะะ🇪ะ ะ🇳ะะ🇴ะะ🇴ะะ🇧ะ",
        "ะ🇨ะะ🇭ะะ🇱ะ ะ🇨ะะ🇺ะะ🇩ะะ🇰ะะ🇪ะ ะ🇩ะะ🇮ะะ🇰ะะ🇭ะะ🇦ะ ะ🇳ะะ🇴ะะ🇴ะะ🇧ะ",
        "ะ🇯ะะ🇱ะะ🇩ะะ🇮ะ ะ🇹ะะ🇾ะะ🇵ะ ะ🇨ะะ🇷ะ ะ🇳ะะ🇴ะะ🇴ะะ🇧ะ ะ🇭ะะ🇦ะะ🇱ะะ🇰ะะ🇪ะ",
        "ะ🇨ะะ🇺ะะ🇩ะ ะ🇰ะะ🇪ะ ะ🇵ะะ🇬ะะ🇱ะ ะ🇳ะะ🇾ะ ะ🇭ะะ🇴ะ ะ🇳ะะ🇴ะะ🇴ะะ🇧ะ",
        "ะ🇨ะะ🇺ะะ🇩ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇰ะะ🇪ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะ ะ🇧ะะ🇳ะะ🇯ะะ🇦ะ ะ🇹ะะ🇺ะ ะ🇳ะะ🇴ะะ🇴ะะ🇧ะ",
        "ะ🇲ะะ🇦ะะ🇰ะะ🇮ะะ🇨ะะ🇭ะะ🇺ะะ🇹ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇳ะะ🇴ะะ🇴ะะ🇧ะ",
        "ะ🇬ะะ🇦ะะ🇳ะะ🇩ะะ🇦ะ ะ🇨ะะ🇾ะะ🇺ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇷ะะ🇭ะะ🇦ะ ะ🇹ะะ🇺ะ ?",
        "ะ🇮ะะ🇹ะะ🇳ะะ🇦ะ ะ🇬ะะ🇳ะะ🇩ะะ🇦ะ ะ🇳ะะ🇾ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇦ะะ🇨ะะ🇭ะะ🇪ะ ะ🇸ะะ🇪ะ ะ🇨ะะ🇺ะะ🇩ะ",
        "ะ🇲ะะ🇦ะะ🇦ะ⍟ ะ🇱ะะ🇪ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇬ะะ🇾ะะ🇦ะ ะ🇹ะะ🇺ะ ะ🇸ะะ🇺ะ⍟ ะ🇧ะะ🇦ะะ🇹ะ ะ🇦ะะ🇧",
        "ะ🇲ะะ🇦ะะ🇰ะะ🇦ะะ🇫ะะ🇺ะะ🇩ะะ🇩ะะ🇦ะ ะ🇫ะะ🇦ะะ🇹ะ ะ🇬ะะ🇾ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇷ะะ🇺ะะ🇰ะ",
        "ะ🇸ะะ🇭ะะ🇦ะะ🇳ะะ🇹ะ ะ🇧ะะ🇪ะะ🇹ะะ🇭ะ ะ🇲ะะ🇦ะะ🇩ะะ🇷ะะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇼ะะ🇷ะะ🇳ะะ🇦ะ ะ🇲ะะ🇦ะะ🇰ะะ🇦ะะ🇧ะะ🇴ะะ🇸ะะ🇩ะะ🇦ะ ะ🇹ะะ🇪ะะ🇪ะะ🇾ะ.",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะ..",
        "ะ🇱ะะ🇼ะะ🇩ะะ🇪ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇦ะะ🇦ะะ🇱ะะ🇱ะะ🇱ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇨ะะ🇺ะะ🇩ะะ🇰ะะ🇪ะ ะ🇵ะะ🇬ะะ🇱ะ ะ🇩ะะ🇪ะะ🇰ะะ🇭ะ.",
        "ะ🇲ะะ🇦ะะ🇨ะะ🇭ะะ🇦ะะ🇷ะ ะ🇰ะะ🇮ะ ะ🇯ะะ🇭ะะ🇦ะะ🇦ะะ🇹ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇦ะะ🇱ะะ🇱ะะ🇱ะะ🇱ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇦ะะ🇨ะะ🇭ะะ🇪ะ ะ🇸ะะ🇪ะ ะ🇾ะะ🇭ะะ🇦ะะ🇵ะะ🇪ะ ะ🇹ะะ🇺ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะ ะ🇲ะ ะ🇩ะะ🇺ะ ะ🇹ะะ🇦ะะ🇵ะะ🇦ะ ะ🇹ะะ🇦ะะ🇵ะ?",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇦ะ ะ🇧ะะ🇭ะะ🇴ะꜱะะ🇩ะะ🇦ะะ??ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇭ะะ🇳ะ ꜱะ🇧ะꜱะ🇧ะะ🇪ะ ะ🇧ะะ🇩ะะ🇮ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะ.",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇴ะꜱะꜱะะ🇪ะ ะ🇧ะะ🇦ะะ🇩ะะ🇮ะ ะ??ะะ🇦ะะ🇳ะะ🇩ะะ🇩ะะ🇩ะะ🇩ะะ🇩ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇦ะ ะ🇧ะะ🇦ะะ🇦ะะ🇵ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะะ🇧ะะ🇦ะะ🇦ะะ🇿ะ ะ🇪ะะ🇾ะ ะ🇩ะะ🇪ะะ🇰ะะ🇭ะ",
        "ะ🇰ะะ🇮ะะ🇹ะะ🇳ะะ🇮ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇺ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇦ะะ🇧ะ ะ🇴ะะ🇷..",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇩ะะ🇮ะ ะ🇭ะะ🇲ะ ะ🇳ะะ🇪ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇪ะ ꜱะ🇹ะะ🇭ะ ะ🇷ะะ🇪ะะ🇪ะะ🇱ะꜱะ ะ🇧ะะ🇳ะะ🇪ะะ🇬ะะ🇦ะ ะ🇷ะะ🇴ะะ🇦ะะ🇩ะ ะ🇵ะะ🇪ะะ🇪ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะ ะ🇪ะะ🇰ะ ะ🇩ะะ🇦ะะ🇲ะ ะ🇹ะะ🇴ะะ🇵ะ ꜱะ🇪ะxะ🇾ะ",
        "ะ🇲ะะ🇦ะะ🇱ะะ🇺ะ🇲ะ ะ🇳ะะ🇦ะ ะ🇵ะะ🇭ะ🇷ะ ะ🇰ะะ🇪ꜱะะ🇪ะ ะ🇱ะะ🇪ะะ🇹ะะ🇦ะ ะ🇭ะะ🇺ะ ะ🇲ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะ ะ🇹ะะ🇦ะะ🇵ะะ🇦ะ ะ🇹ะะ🇦ะะ🇵ะะ🇵ะะ🇵ะะ🇵ะะ🇵ะ",
        "ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇰ะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇪ะ ะ🇹ะะ🇺ะ ะ🇰ะะ🇪ะะ🇷ะะ🇪ะะ🇬ะะ🇦ะ ะ🇹ะะ🇾ะะ🇵ะะ🇮ะะ🇳ะะ🇬ะ ะ🇰ะะ🇷ะะ🇪ะะ🇬ะะ🇦ะ ะ🇹ะะ🇲ะะ🇰ะะ🇨ะ",
        "ꜱะ🇵ะะ🇪ะะ🇪ะะ🇩ะ ะ🇵ะะ🇰ะะ🇩ะ ะ🇱ะะ🇼ะะ🇩ะะ🇪ะะ🇪ะะ🇪ะะ🇪ะ ะ🇼ะะ🇷ะะ🇳ะะ🇦ะ ะ🇲ะะ🇪ะะ🇷ะะ🇦ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇵ะะ🇰ะะ🇩ะ",
        "ะ🇧ะะ🇦ะะ🇦ะะ🇵ะ ะ🇰ะะ🇮ะ ꜱะ🇵ะะ🇪ะะ🇪ะะ🇩ะ ะ🇲ะะ🇹ะะ🇨ะะ🇭ะ ะ🇰ะะ🇷ะะ🇷ะะ🇷ะ",
        "ะ🇱ะะ🇼ะะ🇩ะะ🇦ะ ะ🇱ะะ🇪ะ ะ🇲ะะ🇪ะะ🇷ะะ🇦ะ ะ🇯ะะ🇦ะะ🇱ะะ🇩ะะ🇮ะ ะ🇸ะะ🇪ะ ะ🇹ะะ🇺ะ",
        "ะ🇵ะะ🇦ะะ🇵ะะ🇦ะ ะ🇰ะะ🇮ะ ꜱะ🇵ะะ🇪ะะ🇪ะะ🇩ะ ะ🇲ะะ🇹ะะ🇨ะะ🇭ะ ะ🇳ะะ🇭ะะ🇮ะ ะ🇭ะะ🇴ะ ะ🇷ะะ🇭ะะ🇮ะ ะ🇰ะะ🇾ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇪ะะ🇸ะะ🇪ะ",
        "ะ🇦ะะ🇱ะะ🇪ะ ะ🇦ะะ🇱ะะ🇪ะ ะ🇲ะะ🇪ะะ🇱ะะ🇦ะ ะ🇧ะะ🇨ะะ🇭ะะ🇦ะะ🇦ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇲ะะ🇦ะะ🇰ะะ🇦ะ ะ🇧ะะ🇴ะะ🇸ะะ🇩ะะ🇦ะ ะ🇸ะะ🇺ะะ🇳ะ",
        "ะ🇨ะะ🇭ะะ🇺ะะ🇩ะ ะ🇬ะะ🇾ะะ🇦ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะะ🇧ะะ🇦ะะ🇦ะะ🇿ะ ะ🇵ะะ🇦ะะ🇵ะะ🇦ะ ꜱะ🇪ะะ🇪ะะ🇪ะ ะ🇹ะะ🇺ะ",
        "ะ🇲ะะ🇪ะะ🇳ะะ🇺ะ ะ🇰ะะ🇮ะ ะ🇵ะะ🇹ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇲ะะ🇦ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇬ะะ🇦ะะ🇮ะ",
        "ะ🇰ะะ🇴ะะ🇮ะ ะ🇧ะะ🇦ะะ🇦ะะ🇹ะ ะ🇳ะะ🇾ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇾ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ",
        "ะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇦ะะ🇦ะะ🇦ะะ🇦ะ ะ🇲ะะ🇦ะะ🇰ะะ🇦ะะ🇧ะะ🇴ะะ🇸ะะ🇩ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ",
        "ะ🇽ะะ🇭ะะ🇺ะะ🇩ะ ะ🇬ะะ🇦ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇰ะะ🇮ะะ🇩ะꜱะꜱะꜱะꜱะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇨ะะ🇭ะะ🇺ะะ🇩ะ ะ🇬ะะ🇾ะะ🇮ะ ะ🇦ะะ🇧ะ ꜰะ🇷ะะ🇦ะ🇷ะ ะ🇲ะะ🇹ะ ะ🇭ะะ🇴ะะ🇳ะะ🇦ะ",
        "ะ🇾ะะ🇪ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇱ะะ🇪ะ ะ🇲ะะ🇪ะะ🇷ะะ🇦ะ ะ🇨ะะ🇭ะะ🇱ะ ะ🇯ะะ🇦ะะ🇱ะะ🇩ะะ🇮ะ ะ🇸ะะ🇪ะ",
        "ะ🇰ะะ🇮ะะ🇩ะꜱะꜱะꜱะ ꜰะ🇷ะะ🇦ะ🇷ะ ะ🇳ะะ🇦ะ ะ🇭ะะ🇴ะ ะ🇹ะะ🇺ะ ะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇭ะะ🇭ะ",
        "ะ🇧ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇪ะ ะ🇱ะะ🇼ะะ🇩ะะ🇪ะ ꜱะ🇭ะ🇷ะ🇲ะ ะ🇰ะะ🇷ะ",
        "ะ🇰ะะ🇮ะะ🇹ะะ🇳ะะ🇮ะ ะ🇬ะะ🇱ะะ🇮ะะ🇾ะะ🇦ะ ะ🇵ะะ🇩ะะ🇼ะะ🇪ะะ🇬ะะ🇦ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇴ะ",
        "ะ🇨ะะ🇭ะะ🇺ะะ🇵ะ ะ🇳ะะ🇦ะะ🇱ะะ🇱ะะ🇮ะะ🇮ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇾ะะ🇰ะะ🇪ะ ะ🇱ะะ🇦ะะ🇩ะะ🇰ะะ🇪ะ",
        "ꜱะ🇺ะะ🇦ะ🇷ะ ะ🇰ะะ🇪ะ ะ🇵ะะ🇮ะะ🇱ะะ🇱ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ꜱะ🇦ะะ🇩ะะ🇦ะ🇰ะ ะ🇵ะ🇷ะ ะ🇱ะะ🇮ะะ🇹ะะ🇦ะะ🇰ะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ 😂😆🤤",
        "ะ🇦ะะ🇧ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇦ะ ะ🇧ะะ🇭ะะ🇴ꜱะะ🇩ะะ🇦ะ ะ🇲ะะ🇦ะะ🇩ะะ🇪ะ🇷ะะ🇨ะะ🇭ะะ🇴ะะ🇴ะะ🇩ะ ะ🇰ะ🇷ะ ะ🇵ะะ🇮ะะ🇱ะะ🇱ะะ🇪ะ ะ🇵ะะ🇦ะะ🇵ะะ🇦ะ ꜱะ🇪ะ ะ🇱ะะ🇦ะะ🇩ะะ🇪ะะ🇬ะะ🇦ะ ะ🇹ะะ🇺ะ 😼😂🤤",
        "ะ🇬ะะ🇦ะะ🇱ะะ🇮ะ ะ🇬ะะ🇦ะะ🇱ะะ🇮ะ ะ🇳ะะ🇪ะ ꜱะ🇭ะ🇴ะ🇷ะ ะ🇭ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะ ะ🇨ะะ🇭ะะ🇴ะ🇷ะ ะ🇭ะะ🇪ะ 💋💋💦",
        "ะ🇦ะะ🇧ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇺ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะะ🇰ะะ🇪ะ ะ🇵ะะ🇮ะะ🇱ะะ🇱ะะ🇪ะ ะ🇰ะะ🇺ะะ🇹ะะ🇹ะะ🇪ะ ะ🇰ะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇪ะ 😂👻🔥",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇦ะะ🇮ꜱะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇦ะ ะ🇦ะะ🇮ꜱะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇦ะ ะ🇧ะะ🇪ะะ🇩ะ ะ🇵ะะ🇪ะะ🇭ะะ🇮ะ ะ🇲ะะ🇺ะะ🇹ะะ🇭ะ ะ🇩ะะ🇮ะะ🇦ะ 💦💦💦💦",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇭ะะ🇴ꜱะะ🇩ะะ🇪ะ ะ🇲ะะ🇪ะ ะ🇦ะะ🇦ะะ🇦ะ🇬ะ ะ🇱ะะ🇦ะะ🇬ะะ🇦ะะ🇩ะะ🇮ะะ🇦ะ ะ🇲ะะ🇪ะะ🇷ะะ🇦ะ ะ🇲ะะ🇴ะะ🇹ะะ🇦ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇩ะะ🇦ะะ🇱ะะ🇰ะะ🇪ะ 🔥🔥💦😆😆",
        "ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇨ะะ🇭ะะ🇭ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇺ะ ะ🇨ะะ🇭ะะ🇦ะะ🇱ะ ะ🇳ะะ🇮ะะ🇰ะะ🇦ะะ🇱ะ",
        "ะ🇰ะะ🇮ะะ🇹ะะ🇳ะะ🇦ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇺ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะะ🇭ะ ะ🇦ะะ🇧ะะ🇧ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇴ะ ะ🇧ะะ🇭ะะ🇪ะะ🇯ะ 😆👻🤤",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇴ะะ🇹ะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇰ะะ🇪ะ ะ🇵ะะ🇺ะะ🇷ะะ🇦ะ ꜰะ🇦ะะ🇦ะะ🇩ะ ะ🇩ะะ🇮ะะ🇦ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะะ🇭ะ ะ🇦ะะ🇧ะะ🇧ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇬ะꜰะ ะ🇰ะะ🇴ะ ะ🇧ะะ🇭ะะ🇪ะะ🇯ะ 😆💦🤤",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇬ะꜰะ ะ🇰ะะ🇴ะ ะ🇪ะะ🇹ะะ🇳ะะ🇦ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇦ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇪ะ ะ🇱ะะ🇴ะะ🇩ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇬ะꜰะ ะ🇹ะะ🇴ะ ะ🇲ะะ🇪ะะ🇷ะะ🇮ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะ ะ🇧ะะ🇦ะะ🇳ะะ🇬ะะ🇦ะะ🇾ะะ🇮ะ ะ🇦ะะ🇧ะะ🇧ะ ะ🇨ะะ🇭ะะ🇦ะะ🇱ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇹ะะ🇦ะ ꜰะ🇮ะ🇷ꜱะะ🇪ะ ♥️💦😆😆😆😆",
        "ะ🇭ะะ🇦ะะ🇷ะะ🇮ะ ะ🇭ะะ🇦ะะ🇷ะะ🇮ะ ะ🇬ะะ🇭ะะ🇦ะะ🇦ꜱะ ะ🇲ะะ🇪ะ ะ🇯ะะ🇭ะะ🇴ะะ🇵ะะ🇩ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇦ะ ะ🇧ะะ🇭ะะ🇴ꜱะะ🇩ะะ🇦ะ 🤣🤣💋💦",
        "ะ🇨ะะ🇭ะะ🇦ะะ🇱ะ ะ🇹ะะ🇪ะะ🇷ะะ🇪ะ ะ🇧ะะ🇦ะะ🇦ะะ🇵ะ ะ🇰ะะ🇴ะ ะ🇧ะะ🇭ะะ🇪ะะ🇯ะ ะ🇹ะะ🇪ะะ🇷ะะ🇦ะ ะ🇧ะะ🇦ꜱะะ🇰ะะ🇦ะ ะ🇳ะะ🇭ะะ🇮ะ ะ🇭ะะ🇪ะ ะ🇵ะะ🇦ะะ🇵ะะ🇦ะ ꜱะ🇪ะ ะ🇱ะะ🇦ะะ🇩ะะ🇪ะะ🇬ะะ🇦ะ ะ🇹ะะ🇺ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะะ🇭ะ ะ🇲ะะ🇪ะ ะ🇧ะะ🇴ะะ🇲ะ🇧ะ ะ🇩ะะ🇦ะะ🇱ะะ🇰ะะ🇪ะ ะ🇺ะะ🇩ะะ🇦ะ ะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇪ะ ะ🇱ะะ🇦ะะ🇼ะะ🇩ะะ🇪ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇹ะะ🇷ะะ🇦ะะ🇮ะ🇳ะ ะ🇲ะะ🇪ะ ะ🇱ะะ🇪ะะ🇯ะะ🇦ะะ🇰ะะ🇪ะ ะ🇹ะะ🇴ะะ🇵ะ ะ🇧ะะ🇪ะะ🇩ะ ะ🇵ะะ🇪ะ ะ🇱ะะ🇮ะะ🇹ะะ🇦ะะ🇰ะะ🇪ะ ะ🇨ะะ??ะะ🇴ะะ🇩ะ ะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ꜱะ🇺ะะ🇦ะ🇷ะ ะ🇰ะะ🇪ะ ะ🇵ะะ🇮ะะ🇱ะะ🇱ะะ🇪ะ 🤣🤣💋💋",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇪ะ ะ🇳ะะ🇺ะะ🇩ะะ🇪ꜱะ ะ🇬ะะ🇴ะะ🇴ะ🇬ะ🇱ะะ🇪ะ ะ🇵ะะ🇪ะ ะ🇺ะะ🇵ะะ🇱ะะ🇴ะะ🇦ะ🇩ะ ะ🇰ะะ🇦ะ🇷ะะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇪ะ ะ🇱ะะ🇦ะะ🇪ะะ🇼ะะ🇩ะะ🇪ะ 👻🔥",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇪ะ ะ🇳ะะ🇺ะะ🇩ะะ🇪ꜱะ ะ🇬ะะ🇴ะะ🇴ะ🇬ะ🇱ะะ🇪ะ ะ🇵ะะ🇪ะ ะ🇺ะะ🇵ะะ🇱ะะ🇴ะะ🇦ะ🇩ะ ะ🇰ะะ🇦ะ🇷ะะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇪ะ ะ🇱ะะ🇦ะะ🇪ะะ🇼ะะ🇩ะะ🇪ะ 👻🔥",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇰ะะ🇪ะ ะ🇻ะะ🇮ะะ🇩ะะ🇪ะ🇴ะ ะ🇧ะะ🇦ะะ🇳ะะ🇦ะะ🇰ะะ🇪ะ ะ🇽ะ🇳🇽🇽.🇨🇴🇲 ะ🇵ะะ🇪ะ ะ🇳ะะ🇪ะะ🇪ะะ🇱ะะ🇦ะ🇲ะ ะ🇰ะะ🇦ะ🇷ะะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ะ🇰ะะ🇺ะะ🇹ะะ🇹ะะ🇪ะ ะ🇰ะะ🇪ะ ะ🇵ะะ🇮ะะ🇱ะะ🇱ะะ🇪ะ 💦💋",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇩ะะ🇦ะะ🇮ะ ะ🇰ะะ🇴ะ ะ🇵ะ🇴🇷🇳🇭🇺🇧.🇨🇴🇲 ะ🇵ะะ🇪ะ ะ🇺ะะ🇵ะะ🇱ะะ🇴ะะ🇦ะ🇩ะ ะ🇰ะะ🇦ะ🇷ะะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ꜱะ🇺ะะ🇦ะ🇷ะ ะ🇰ะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇪ะ 🤣💋💦",
        "ะ🇦ะะ🇧ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇺ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇨ะะ🇭ะะ🇭ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇪ะะ🇰ะ🇴ะ ะ🇨ะะ🇭ะะ🇦ะะ🇰ะะ🇰ะ🇴ะ ꜱะะ🇪ะ ะ🇵ะะ🇮ะะ🇱ะะ🇼ะะ🇦ะะ🇻ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇨ะะ🇭ะะ🇭ะะ🇪ะ 🤣🤣",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะะ🇭ะ ꜰะะ🇦ะะ🇦ะะ🇩ะะ🇰ะะ🇪ะ ะ🇷ะะ🇦ะะ🇰ะะ🇩ะะ🇮ะะ🇦ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇪ะ ะ🇱ะะ🇴ะะ🇩ะะ🇪ะ ะ🇯ะะ🇦ะะ🇦ะ ะ🇦ะะ🇧ะะ🇧ะ ꜱะะ🇮ะะ🇱ะะ🇼ะะ🇦ะะ🇱ะะ🇪ะ 👄👄",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะะ🇭ะ ะ🇲ะะ🇪ะ ะ🇲ะะ🇪ะะ🇷ะะ🇦ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇰ะะ🇦ะะ🇦ะะ🇱ะะ🇦ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇱ะะ🇪ะะ🇹ะะ🇮ะ ะ🇲ะะ🇪ะะ🇷ะะ🇮ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇧ะะ🇦ะะ🇩ะะ🇪ะ ะ🇲ะะ🇦ꜱะะ🇹ะะ🇮ะ ꜱะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇴ะ ะ🇲ะะ🇪ะะ🇳ะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇩ะะ🇦ะะ🇱ะะ🇦ะ ะ🇧ะะ🇴ะะ🇭ะะ🇴ะะ🇹ะ ꜱะะ🇦ꜱะะ🇹ะะ🇪ะ ꜱะะ🇪ะ",
        "ะ🇧ะะ🇪ะะ🇹ะะ🇪ะ ะ🇹ะะ🇺ะ ะ🇧ะะ🇦ะะ🇦ะะ🇵ะ ꜱะะ🇪ะ ะ🇱ะะ🇪ะะ🇬ะะ🇦ะ ะ🇵ะะ🇦ะะ🇳ะะ🇬ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇦ะ ะ🇰ะะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ะ🇰ะะ🇦ะ🇷ะะ🇰ะะ🇪ะ ะ🇳ะะ🇦ะะ🇳ะะ🇬ะะ🇦ะ 💦💋",
        "ะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇭ะ ะ🇲ะะ🇪ะะ🇷ะะ🇪ะ ะ🇧ะะ🇪ะะ🇹ะะ🇪ะ ะ🇦ะะ🇬ะะ🇱ะะ🇮ะ ะ🇧ะะ🇦ะะ🇦ะ🇷ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇱ะะ🇪ะะ🇰ะะ🇪ะ ะ🇦ะะ🇦ะะ🇾ะะ🇦ะ ะ🇲ะะ🇦ะะ🇹ะะ🇭ะ ะ🇰ะะ🇦ะะ🇹ะ ะ🇴ะ🇷ะ ะ🇲ะะ🇪ะะ🇷ะะ🇪ะ ะ🇲ะะ🇴ะะ🇹ะะ🇪ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ꜱะะ🇪ะ ะ🇨ะะ🇭ะะ🇺ะะ🇩ะะ🇼ะะ🇦ะะ🇾ะะ🇦ะ ะ🇲ะะ🇦ะะ🇹ะะ🇭ะ ะ🇰ะะ🇦ะ🇷ะ",
        "ะ🇨ะะ🇭ะะ🇦ะะ🇱ะ ะ🇧ะะ🇪ะะ🇹ะะ🇦ะ ะ🇹ะะ🇺ะะ🇯ะะ🇭ะะ🇪ะ ะ🇲ะะ🇦ะะ🇦ꜱะ🇫ะ ะ🇰ะะ🇮ะะ🇦ะ 🤣ะ🇹ะะ🇺ะ ะ🇦ะะ🇧ะะ🇧ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇲ะะ🇦ะะ🇰ะ🇴ะ ะ🇧ะะ🇭ะะ🇪ะะ🇯ะ",
        "ꜱะ🇭ะะ🇦ะะ🇷ะะ🇦ะ🇲ะ ะ🇰ะะ🇦ะ🇷ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇦ะ ะ🇧ะะ🇭ะะ🇴ꜱะะ🇩ะะ🇦ะ ะ🇰ะะ🇮ะะ🇹ะะ🇳ะะ🇦ะ ะ🇬ะะ🇦ะะ🇦ะะ🇱ะะ🇮ะะ🇦ะ ꜱะ🇺ะะ🇳ะะ🇼ะะ🇦ะะ🇾ะะ🇪ะะ🇬ะะ🇦ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇦ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇪ะ ะ🇺ะะ🇵ะะ🇪ะ🇷ะ",
        "ะ🇦ะะ🇧ะะ🇪ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇨ะะ🇭ะะ🇭ะะ🇪ะ ะ🇦ะะ🇺ะะ🇰ะะ🇦ะะ🇹ะ ะ🇳ะะ🇭ะะ🇮ะ ะ🇭ะะ🇪ะะ🇹ะ🇴ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇱ะะ🇪ะะ🇰ะะ🇪ะ ะ🇦ะะ🇦ะะ🇾ะะ🇦ะ ะ🇲ะะ🇦ะะ🇹ะะ🇭ะ ะ🇰ะะ🇦ะ??ะ ะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇭ะะ🇦ะ",
        "ะ🇰ะะ🇮ะะ🇩ะ🇿ะ ะ🇲ะะ🇦ะะ🇩ะะ🇦ะ🇷ะะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇰ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะ🇷ะ ะ🇱ะะ🇮ะะ🇾ะะ🇪ะ ะ🇧ะะ🇭ะะ🇦ะะ🇮ะ ะ🇩ะะ🇪ะะ🇩ะะ🇮ะะ🇾ะะ🇦ะ",
        "ะ🇯ะะ🇺ะะ🇳ะะ🇬ะ🇱ะะ🇪ะ ะ🇲ะะ🇪ะ ะ🇳ะะ🇦ะะ🇨ะะ🇭ะะ🇹ะะ🇦ะ ะ🇭ะะ🇪ะ ะ🇲ะะ🇴ะ🇷ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇩ะะ🇦ะะ🇮ะ ะ🇩ะะ🇪ะะ🇰ะะ🇰ะะ🇪ะ ꜱะ🇦ะ🇧ะ ะ🇧ะะ🇴ะะ🇱ะะ🇹ะะ🇪ะ ะ🇴ะะ🇳ะ🇨ะะ🇪ะ ะ🇲ะะ🇴ะ🇷ะะ🇪ะ ะ🇴ะะ🇳ะ🇨ะะ🇪ะ ะ🇲ะะ🇴ะ🇷ะะ🇪ะ 🤣🤣💦💋",
        "ะ🇬ะะ🇦ะะ🇱ะะ🇮ะ ะ🇬ะะ🇦ะะ🇱ะะ🇮ะ ะ🇲ะะ🇪ะ ะ🇷ะะ🇪ะะ🇭ะะ🇹ะะ🇦ะ ะ🇭ะะ🇪ะ ꜱะ🇦ะะ🇳ะะ🇩ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇩ะะ🇦ะะ🇱ะะ🇦ะ ะ🇴ะ🇷ะ ะ🇧ะะ🇦ะะ🇳ะะ🇦ะ ะ🇩ะะ🇮ะะ🇦ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะ 🤤🤣",
        "ꜱะ🇦ะ🇧ะ ะ🇧ะะ🇴ะะ🇱ะะ🇹ะะ🇪ะ ะ🇲ะะ🇺ะะ🇯ะะ🇭ะะ🇰ะ🇴ะ ะ🇵ะะ🇦ะะ🇵ะะ🇦ะ ะ🇨ะะ🇾ะะ🇺ะะ🇰ะะ🇮ะ ะ🇲ะะ🇪ะะ🇳ะะ🇪ะ ะ🇰ะ🇷ะะ??ะะ🇮ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇵ะ🇷ะะ🇪ะะ🇬ะะ🇳ะะ🇪ะะ🇳ะะ🇹ะ 🤣🤣",
        "ꜱะ🇺ะะ🇦ะ🇷ะ ะ🇰ะะ🇪ะ ะ🇵ะะ🇮ะะ🇱ะะ🇱ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะะ🇭ะ ะ🇲ะะ🇪ะ ꜱะ🇺ะะ🇦ะ🇷ะ ะ🇰ะะ🇦ะ ะ🇱ะะ🇴ะะ🇺ะะ🇩ะะ🇦ะ ะ🇴ะ🇷ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะะ🇭ะ ะ🇲ะะ🇪ะ ะ🇲ะะ🇪ะะ🇷ะะ🇦ะ ะ🇱ะะ🇴ะะ🇩ะะ🇦ะ",
        "ะ🇨ะะ🇭ะะ🇦ะะ🇱ะ ะ🇨ะะ🇭ะะ🇦ะะ🇱ะ ะ🇹ะะ🇺ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇨ะะ🇭ะะ🇮ะะ🇾ะะ🇦ะ ะ🇩ะะ🇮ะะ🇰ะะ🇦ะ",
        "ะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇭ะะ🇦ะ ะ🇧ะะ🇦ะะ🇨ะะ🇭ะะ🇭ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇩ะะ🇮ะะ🇦ะ ะ🇳ะะ🇦ะะ🇳ะะ🇬ะะ🇦ะ ะ🇰ะะ🇦ะ🇷ะะ🇰ะะ🇪ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇬ะꜰะ ะ🇭ะะ🇪ะ ะ🇧ะะ🇦ะะ🇩ะะ🇮ะ ꜱะ🇪xะ🇾ะ ะ🇺ꜱะะ🇰ะ??ะ ะ🇵ะะ🇮ะะ🇱ะะ🇦ะะ🇰ะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇴ะะ🇩ะะ🇪ะะ🇳ะะ🇬ะะ🇪ะ ะ🇵ะะ🇪ะะ🇵ꜱะะ🇮ะ",
        "2 ะ🇷ะะ🇺ะะ🇵ะะ🇦ะ🇾ะ ะ🇰ะะ🇮ะ ะ🇵ะะ🇪ะะ🇵ꜱะะ🇮ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇺ะะ🇲ะะ🇲ะะ🇾ะ ꜱะ🇦ะ🇧ꜱะะ🇪ะ ꜱะ🇪xะ🇾ะ 💋💦",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇨ะะ🇭ะะ🇪ะะ🇪ะ🇲ꜱะ ꜱะะ🇪ะ ะ🇨ะะ🇭ะะ🇺ะะ🇩ะะ🇼ะะ🇦ะะ🇻ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ะ🇲ะะ🇦ะะ🇩ะะ🇪ะ🇷ะะ🇨ะะ🇭ะะ🇴ะะ🇴ะะ🇩ะ ะ🇰ะะ🇪ะ ะ🇵ะะ🇮ะะ🇱ะะ🇱ะะ🇪ะ 💦🤣",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะะ🇭ะ ะ🇲ะะ🇪ะ ะ🇲ะะ🇺ะะ🇹ะะ🇭ะะ🇰ะะ🇪ะ ꜰะะ🇦ะ🇷ะะ🇦ะ🇷ะ ะ🇭ะะ🇴ะะ🇯ะะ🇦ะะ🇻ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ะ🇭ะะ🇺ะะ🇮ะ ะ🇭ะะ🇺ะะ🇮ะ ะ🇭ะะ🇺ะะ🇮ะ",
        "ꜱะ🇵ะะ🇪ะะ🇪ะะ🇩ะ ะ🇱ะะ🇦ะะ🇦ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇺ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะะ🇰ะะ🇪ะ ะ🇵ะะ🇮ะะ🇱ะะ🇱ะะ🇪ะ 💋💦🤣",
        "ะ🇦ะะ🇷ะะ🇪ะ ะ🇷ะะ🇪ะ ะ🇲ะะ🇪ะะ🇷ะะ🇪ะ ะ🇧ะะ🇪ะะ🇹ะะ🇪ะ ะ🇨ะะ🇾ะะ🇺ะ ꜱะ🇵ะะ🇪ะะ🇪ะะ🇩ะ ะ🇵ะะ🇦ะะ🇰ะะ🇦ะะ🇩ะ ะ🇳ะะ🇦ะ ะ🇵ะะ🇦ะะ🇦ะะ🇦ะ ะ🇷ะะ🇦ะะ🇭ะะ🇦ะ ะ🇦ะะ🇵ะะ🇳ะะ🇪ะ ะ🇧ะะ🇦ะะ🇦ะะ🇵ะ ะ🇰ะะ🇦ะ ะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇭ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇬ะะ🇦ะะ🇮ะ🤣🤣",
        "ꜱะ🇺ะะ🇳ะ ꜱะ🇺ะะ🇳ะ ꜱะ🇺ะะ🇦ะ🇷ะ ะ🇰ะะ🇪ะ ะ🇵ะะ🇮ะะ🇱ะะ🇱ะะ🇪ะ ะ🇯ะะ🇭ะะ🇦ะะ🇳ะะ🇹ะ🇴ะ ะ🇰ะะ🇪ะ ꜱะ🇴ะะ🇺ะะ🇩ะะ🇦ะะ🇬ะะ🇦ะ🇷ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇲ะะ🇺ะะ🇲ะะ🇲ะะ🇾ะ ะ🇰ะะ🇮ะ ะ🇳ะะ🇺ะะ🇩ะะ🇪ꜱะ ะ🇧ะะ🇭ะะ🇪ะะ🇯ะ",
        "ะ🇦ะะ🇧ะะ🇪ะ ꜱะ🇺ะะ🇳ะ ะ🇱ะะ🇴ะะ🇩ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇦ะ ะ🇧ะะ🇭ะะ🇴ꜱะะ🇩ะะ🇦ะ ꜰะะ🇦ะะ🇦ะะ🇩ะ ะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇰ะะ🇭ะะ🇺ะะ🇱ะะ🇪ะ ะ🇧ะะ🇦ะะ🇯ะะ🇦ะ🇷ะ ะ🇲ะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇩ะะ🇦ะะ🇱ะะ🇦ะ 🤣🤣💋",
        "ꜱะ🇭ะ🇷ะ🇲ะ ะ🇰ะ🇷ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇬ะะ🇦ะะ🇮ะ ะ🇾ะะ🇭ะะ🇦ะ",
        "ะ🇲ะะ🇪ะะ🇷ะะ🇪ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇦ะะ🇦ะะ🇦ะะ🇱ะะ🇱ะะ🇱ะะ🇱ะะ🇱ะ ะ🇵ะะ🇰ะะ🇩ะ ะ🇯ะะ🇦ะะ🇱ะะ🇩ะะ🇮ะ ะ🇸ะะ🇪ะ",
        "ะ🇹ะะ🇺ะ ะ🇪ะะ🇰ะ ะ🇰ะะ🇦ะะ🇦ะ🇲ะ ะ🇰ะ🇷ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇧ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇴ะ ะ🇨ะะ🇺ะะ🇩ะะ🇼ะะ🇦ะ ะ🇱ะะ🇪ะ ะ🇲ะะ🇪ะะ🇷ะะ🇪ะ ะ🇸ะะ🇹ะะ🇭ะ",
        "ะ🇷ะะ🇳ะะ🇩ะะ🇮ะ ะ🇰ะะ🇪ะ ะ🇱ะะ🇩ะะ🇰ะะ🇪ะะ🇪ะะ🇪ะะ🇪ะะ🇪ะะ🇪ะะ🇪ะะ🇪ะ ะ🇨ะะ🇭ะะ🇺ะะ🇵ะ ะ🇴ะ🇷ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇾ะะ🇭ะะ🇦ะ",
        "ะ🇨ะะ🇭ะะ🇺ะะ🇵ะ ะ🇹ะะ🇲ะะ🇰ะะ🇨ะ ะ🇰ะะ🇮ะะ🇩ꜱะꜱะꜱะꜱะꜱะꜱะꜱะꜱะꜱะꜱะꜱะꜱะ",
        "ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇬ะะ🇦ะะ🇦ะะ🇳ะะ🇩ะ ะ🇲ะะ🇪ะะ??ะ🇳ะ ะ🇲ะะ🇺ะะ🇹ะะ🇭ะะ🇮ะ ะ🇩ะะ🇦ะะ🇦ะะ🇱ะ",
        "ะ🇲ะะ🇪ะะ🇷ะะ🇦ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇨ะะ🇭ะะ🇴ะะ🇴ꜱะ ะ🇯ะะ🇦ะะ🇱ะะ🇩ะะ🇮ะ ะ🇸ะะ🇪ะ",
        "ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇴ะ ะ🇨ะะ🇺ꜱะะ🇼ะะ🇦ะ ะ🇲ะะ🇪ะะ🇷ะะ🇦ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ",
        "ะ🇧ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇪ะ ะ🇱ะะ🇦ะะ🇺ะะ🇩ะะ🇪ะ ะ🇹ะะ🇲ะะ🇨ะ",
        "ะ🇧ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇪ะ ะ🇹ะะ🇦ะะ🇰ะะ🇰ะะ🇪ะ ะ🇹ะะ🇲ะะ🇱ะ",
        "ะ🇦ะะ🇧ะะ🇱ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇦ะ ะ🇰ะะ🇭ะะ🇦ะ🇳ะ ะ🇩ะะ🇦ะ🇳ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇳ะะ🇪ะ ะ🇰ะะ🇮ะ ะ🇧ะะ🇦ะ🇷ะะ🇮ะะ🇮ะ",
        "ะ🇧ะะ🇪ะะ🇹ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ꜱะ🇧ꜱะะ🇪ะ ะ🇧ะะ🇩ะะ🇮ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะ",
        "ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇦ะะ🇦ะะ🇱ะ ะ🇯ะะ🇭ะะ🇦ะะ🇹ะ ะ??ะะ🇪ะ ะ🇵ะะ🇮ꜱะꜱะꜱะ🇺ะะ🇺ะะ🇺ะะ🇺ะะ🇺ะะ🇺ะะ🇺ะ ะ🇹ะะ🇲ะะ🇰ะะ🇨ะ",
        "ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇵ะะ🇪ะ ะ🇱ะะ🇹ะะ🇰ะะ🇮ะะ🇹ะ ะ🇲ะะ🇦ะะ🇦ะะ🇦ะะ🇱ะะ🇱ะะ🇱ะะ🇱ะ ะ🇰ะะ🇮ะ ะ🇧ะะ🇴ะะ🇳ะะ🇩ะ ะ🇭ะ ะ🇹ะะ🇺ะะ🇺ะะ🇺ะ",
        "ะ🇰ะะ🇦ꜱะะ🇭ะ ะ🇴ꜱะ ะ🇩ะะ🇮ะ🇳ะ ะ🇲ะะ🇺ะะ🇹ะะ🇭ะ ะ🇲ะ🇷ะะ🇰ะะ🇪ะ ꜱะ🇴ะะ🇯ะะ🇹ะะ🇦ะ ะ🇲ะ ะ🇹ะะ🇺ะ ะ🇵ะะ🇦ะะ🇮ะะ🇩ะะ🇦ะ ะ🇳ะะ🇦ะ ะ🇭ะะ🇴ะะ🇹ะะ🇦ะะ🇦ะ",
        "ะ🇬ะะ🇱ะะ🇹ะะ🇮ะ ะ🇰ะ🇷ะะ🇩ะะ🇮ะ ะ🇹ะะ🇺ะะ🇯ะะ🇼ะ ะ🇵ะะ🇦ะะ🇮ะะ🇩ะะ🇦ะ ะ🇰ะ🇷ะะ🇰ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇲ะะ🇦ะ ะ🇳ะะ🇪ะ ะ🇦ะะ🇧ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇹ะะ🇺ะ ะ🇾ะะ🇭ะะ🇦ะ",
        "ꜱะ🇵ะะ🇪ะะ🇪ะะ🇩ะ ะ🇵ะะ🇰ะะ🇩ะะ🇩ะะ??ะ",
        "ะ🇬ะะ🇦ะะ🇦ะะ🇳ะะ🇩ะ ะ🇲ะะ🇦ะะ🇮ะ🇳ะ ะ🇱ะะ🇼ะะ🇩ะะ🇦ะ ะ🇩ะะ🇦ะะ🇱ะ ะ🇱ะะ🇪ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇲ะะ🇪ะะ🇷ะะ🇦ะะ🇦ะะ🇦ะ",
        "ะ🇬ะะ🇦ะะ🇦ะะ🇳ะะ🇩ะ ะ🇲ะะ🇪ะะ🇮ะ🇳ะ ะ🇧ะะ🇦ะะ🇲ะะ🇧ะ🇺ะ ะ🇩ะะ🇪ะะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะะ🇦ะะ🇦ะะ🇦ะะ🇦ะะ🇦ะ",
        "ะ🇬ะะ🇦ะะ🇳ะะ🇩ะ ꜰะะ🇹ะะ🇮ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇱ะะ🇰ะะ🇰ะะ🇰ะ ะ🇹ะะ🇺ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇾ะะ🇭ะะ🇦ะ",
        "ะ🇬ะะ🇴ะะ🇹ะะ🇪ะ ะ🇰ะะ🇮ะะ🇹ะะ🇳ะะ🇪ะ ะ🇧ะะ🇭ะะ🇮ะ ะ🇧ะะ🇦ะะ🇩ะะ🇪ะ ะ🇭ะะ🇴ะ, ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇰ะะ🇪ะ ะ🇳ะะ🇮ะะ🇨ะะ🇭ะะ🇪ะ ะ🇭ะะ🇮ะ ะ🇷ะะ🇪ะะ🇭ะะ🇹ะะ🇪ะ ะ🇭ะะ🇦ะ",
        "ะ🇭ะะ🇦ะะ🇿ะะ🇦ะะ🇦ะ🇷ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇬ะะ🇦ะะ🇦ะะ🇳ะะ🇩ะ ะ🇲ะะ🇦ะะ🇮ะ🇳ะ",
        "ะ🇯ะะ🇭ะะ🇦ะะ🇦ะะ🇳ะะ🇹ะ ะ🇰ะะ🇪ะ ะ🇵ะะ🇮ꜱะꜱะ🇺ะ ะ🇹ะะ🇲ะะ🇰ะะ🇨ะ ะ🇸ะะ🇺ะะ🇳ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇮ะ ะ🇰ะะ🇦ะะ🇱ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะ",
        "ะ🇰ะะ🇭ะะ🇴ะะ🇹ะะ🇪ะ🇾ะ ะ🇰ะะ🇮ะ ะ🇦ะะ🇺ะะ🇱ะะ🇩ะะ🇦ะ ะ🇪ะะ🇾ะ ะ🇹ะะ🇺ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇾ะะ🇰ะะ🇪ะ",
        "ะ🇰ะะ🇺ะะ🇹ะะ🇹ะะ🇪ะ ะ🇰ะะ🇦ะ ะ🇦ะะ🇼ะะ🇱ะะ🇦ะะ🇹ะ ะ🇯ะะ🇦ะะ🇮ะꜱะะ🇦ะ ะ🇱ะะ🇬ะ ะ🇷ะะ🇭ะะ🇦ะ ะ🇹ะะ🇺ะ",
        "ะ🇰ะะ🇺ะะ🇹ะะ🇹ะะ🇪ะ ะ🇰ะะ🇮ะ ะ🇯ะะ🇦ะะ🇹ะ ะ🇯ะะ🇦ะะ🇮ꜱะะ🇦ะ ะ🇪ะะ🇾ะ ะ🇹ะะ🇺ะ ",
        "ะ🇰ะะ🇺ะะ🇹ะะ🇹ะะ🇪ะ ะ🇰ะะ🇪ะ ะ🇹ะะ🇦ะะ🇹ะะ🇹ะะ🇦ะ ะ🇪ะะ🇾ะ ะ🇹ะะ🇺ะ",
        "ะ🇹ะะ🇪ะะ🇹ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇮ะ.ะ🇨ะะ🇭ะะ🇺ะะ🇹ะ , ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇷ะะ🇳ะะ🇩ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะ",
        "ะ🇱ะะ🇦ะะ🇻ะะ🇩ะะ🇪ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇱ะ ะ🇵ะะ🇰ะะ🇩ะ ะ🇱ะะ🇪ะ ะ🇲ะะ🇪ะะ🇷ะะ🇪ะ",
        "ะ🇲ะะ🇺ะะ🇭ะ ะ🇲ะะ🇪ะะ🇮ะ ะ🇱ะะ🇪ะะ🇱ะะ🇪ะ ะ🇲ะะ🇪ะะ🇷ะะ🇦ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ",
        "ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇰ะะ🇪ะ ะ🇵ะะ🇦ꜱะะ🇮ะะ🇳ะะ🇪ะ ะ🇨ะะ🇭ะะ🇺ะะ🇵ะ ะ🇧ะะ🇪ะะ🇹ะะ🇭ะ ะ🇴ะ🇷ะ ะ🇨ะะ🇺ะะ🇩ะ",
        "ะ🇲ะะ🇪ะะ🇷ะะ🇪ะ ะ🇱ะะ🇼ะะ🇩ะะ🇪ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇦ะะ🇦ะะ🇦ะะ🇱ะะ🇱ะะ🇱ะ",
        "ะ🇭​ะะ🇦​ะะ🇭​ะะ🇦​ะะ🇭​ะะ🇦​ะะ🇦​ะะ🇦​ะะ🇦​ะะ🇦​ะะ🇦​ะ ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ ะ🇬​ะะ🇦​ะะ🇮​ะ",
        "ะ🇹​ะะ🇺​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇩​ะ ะ🇬​ะะ🇾​ะะ🇦​ะะ🇦​ะะ🇦​ะะ🇦​ะ",
        "ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะ ะ🇰​ะะ🇭​ะะ🇦​ะะ🇳​ะะ🇪​ะ ะ🇰​ะะ🇮​ะ ะ🇺​ะะ🇱​ะะ🇦​ะะ🇩​ะะ🇩​ะะ🇩​ะ",
        "ꜱ​ะ🇦​ะะ🇩​ะะ🇮​ะ ะ🇭​ะะ🇺​ะะ🇮​ะ ะ🇬​ะะ🇦​ะะ🇦​ะะ🇳​ะะ🇩​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇬​ะะ🇦​ะะ🇦​ะะ🇳​ะะ🇩​ะ ะ🇲​ะะ🇦​ะะ🇮​ะ🇳​ะ ะ🇰​ะะ🇺​ะะ🇹​ะะ🇪​ะ ะ🇰​ะะ🇦​ะ ะ🇱​ะะ🇺​ะะ🇳​ะะ🇩​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇦​ะ ะ🇧​ะะ🇭​ะะ🇴​ꜱ​ะะ🇩​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇪​ะ ะ🇬​ะะ🇦​ะะ🇦​ะะ🇳​ะะ🇩​ะ ะ🇲​ะะ🇪​ะะ🇮​ะ🇳​ะ ะ🇰​ะะ🇪​ะะ🇪​ะะ🇩​ะะ🇪​ะ ะ🇵​ะะ🇦​ะะ🇩​ะะ🇦​ะ🇾​ะ",
        "ะ🇳​ะะ🇾​ะ ะ🇳​ะะ🇾​ะ ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะ",
        "ꜱ​ะ🇺​ะะ🇳​ะะ🇳​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇪​ะ🇷​ะะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะ ะ🇹​ะะ🇲​ะะ🇱​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇦​ะ ะ🇧​ะะ🇭​ะะ🇴​ꜱ​ะะ🇩​ะะ🇦​ะ",
        "ะ🇧​ะะ🇪​ะะ🇭​ะะ🇪​ะ🇳​ะ ะ🇰​ะ ะ🇱​ะะ🇺​ะะ🇳​ะะ🇩​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇵​ะะ🇨​ะะ🇭​ะะ🇦​ะะ🇵​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ ะ🇾​ะะ🇭​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇦​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇹​ะะ🇳​ะะ🇮​ะะ🇮​ะะ🇮​ะ",
        "ะ🇲​ะะ🇪​ะะ🇷​ะะ🇦​ะ ะ🇱​ะะ🇦​ะะ🇼​ะะ🇩​ะะ🇦​ะ ะ🇱​ะะ🇪​ะะ🇱​ะะ🇪​ะ ะ🇹​ะะ🇺​ะ ะ🇦​ะะ🇬​ะะ🇦​ะ🇷​ะ ะ🇨​ะะ🇭​ะะ🇦​ะะ🇮​ะะ🇾​ะะ🇪​ะ ะ🇹​ะะ🇴​ะะ🇭​ะ",
        "ะ🇨​ะะ🇭​ะะ🇺​ะะ🇵​ะ ะ🇬​ะะ🇦​ะะ🇦​ะะ🇳​ะะ🇩​ะ🇺​ะ",
        "ะ🇨​ะะ🇭​ะะ🇺​ะะ🇵​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะะ🇮​ะะ🇾​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇵​ะะ🇪​ะ ะ🇯​ะ🇨​ะ🇧​ะ ะ🇨​ะะ🇭​ะะ🇦​ะะ🇩​ะะ🇭​ะะ🇦​ะะ🇦​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ",
        "ꜱ​ะ🇦​ะะ🇲​ะะ🇯​ะะ🇭​ะะ🇦​ะะ🇦​ะ ะ🇱​ะะ🇦​ะะ🇼​ะะ🇩​ะะ🇪​ะ",
        "ะ🇾​ะะ🇦​ะ ะ🇩​ะะ🇺​ะ ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇬​ะะ🇦​ะะ🇦​ะะ🇳​ะะ🇩​ะ ะ🇲​ะะ🇪​ะ ะ🇹​ะะ🇦​ะะ🇵​ะะ🇦​ะะ🇦​ะ ะ🇹​ะะ🇦​ะะ🇵​",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇧​ะะ🇪​ะะ🇭​ะะ🇪​ะ🇳​ะ ะ🇲​ะะ🇪​ะะ🇷​ะะ🇦​ะ ะ🇷​ะะ🇴​ะะ🇿​ะ ะ🇱​ะะ🇪​ะะ🇹​ะะ🇮​ะ ะ🇭​ะะ🇦​ะะ🇮​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇪​ะ ꜱ​ะะ🇦​ะะ🇦​ะะ🇹​ะะ🇭​ะ ะ🇲​ะ🇲​ꜱ​ะ ะ🇧​ะะ🇦​ะะ🇳​ะะ🇦​ะะ🇦​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇰​ะะ🇦​ะ ะ🇭​ะะ🇺​",
        "ะ🇹​ะะ🇺​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะะ🇮​ะะ🇾​ะะ🇦​ะ ะ🇹​ะะ🇪​ะะ🇷​ะะ🇦​ะ ะ🇰​ะะ🇭​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇦​ะะ🇦​ะ🇳​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะะ🇮​ะะ🇾​ะะ🇦​ะ",
        "ะ🇦​ะะ🇺​ะ🇷​ะ ะ🇰​ะะ🇮​ะะ🇹​ะะ🇳​ะะ🇦​ะ ะ🇧​ะะ🇴​ะะ🇱​ะะ🇺​ะ ะ🇧​ะะ🇪​ะ🇾​ะ ะ🇲​ะะ🇦​ะะ🇳​ะะ🇳​ะ ะ🇧​ะะ🇭​ะะ🇦​ะ🇷​ะ ะ🇬​ะะ🇦​ะะ🇾​ะะ🇦​ะ ะ🇲​ะะ🇪​ะะ🇷​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะะ🇮​ะะ🇮​ะะ🇮​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะะ🇹​ะะ🇹​ะ ะ🇲​ะะ🇪​ะ ะ🇦​ะะ🇧​ะ🇨​ะ🇩​ะ ะ🇱​ะะ🇮​ะะ🇰​ะะ🇭​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇪​ะ ะ🇱​ะะ🇴​ะะ🇩​ะะ🇪​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇴​ะ ะ🇱​ะะ🇪​ะะ🇰​ะะ🇦​ะ🇷​ะ ะ🇲​ะะ🇦​ะะ🇮​ะ ꜰ​ะะ🇦​ะ🇷​ะะ🇦​ะ🇷​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇮​ะะ🇩​ะะ🇮​ะะ🇮​ะ",
        "ะ🇨​ะะ🇭​ะะ🇺​ะะ🇵​ะ ะ🇧​ะะ🇦​ะะ🇨​ะะ🇭​ะะ🇪​ะะ🇪​ะ ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะะ??​ะ🇴​ะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะะ🇺​ะ",
        "ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ",
        "ะ🇹​ะะ🇺​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะ ะ🇰​ะะ🇪​ะ ะ🇵​ะะ🇮​ะะ🇱​ะะ🇱​ะะ🇦​ะ ะ🇪​ะะ🇾​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะะ🇮​ะะ🇮​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇴​ะ ะ🇧​ะะ🇭​ะะ🇪​ะะ🇯​ะะ🇯​ะะ🇯​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇦​ะะ🇦​ะ ะ🇧​ะะ🇦​ะะ🇦​ะะ🇦​ะะ🇵​ะ ะ🇭​ะะ🇺​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇲​ะะ🇪​ะ ะ🇭​ะะ🇦​ะะ🇦​ะะ🇹​ะ ะ🇩​ะะ🇦​ะะ🇦​ะะ🇱​ะะ🇱​ะะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇭​ะะ🇦​ะะ🇦​ะ🇬​ะ ะ🇯​ะะ🇦​ะะ🇦​ะะ🇳​ะะ🇺​ะะ🇬​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇴​ะ ꜱ​ะะ🇦​ะ🇷​ะะ🇦​ะะ🇰​ะ ะ🇵​ะะ🇪​ะ ะ🇱​ะะ🇪​ะะ🇹​ะะ🇦​ะะ🇦​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇴​ ะ🇬​ะ🇧​ะ ะ🇷​ะ🇴​ะ🇦​ะ🇩​ะ ะ🇵​ะะ🇪​ะ ะ🇱​ะะ🇪​ะะ🇯​ะะ🇦​ะะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇪​ะ🇨​ะ🇭​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇲​É​ะ ะ🇰​ะะ🇦​ะะ🇦​ะะ🇱​ะะ🇮​ะ ะ🇲​ะะ🇮​ะะ🇹​ะ🇨​ะ🇭​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ꜱ​ะะ🇦​ꜱ​ะะ🇹​ะะ🇮​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะ ะ🇭​ะะ🇦​ะะ🇮​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇲​ะะ🇪​ะ ะ🇰​ะะ🇦​ะะ🇧​ะะ🇺​ะะ🇹​ะะ🇦​ะ🇷​ะ ะ??​ะะ🇦​ะะ🇦​ะะ🇱​ะ ะ🇰​ะะ🇪​ะ ꜱ​ะ🇴​ะะ🇺​ะะ🇵​ะ ะ🇧​ะะ🇦​ะะ🇳​ะะ🇦​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇦​ะ🇷​ะะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะะ🇦​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะ ะ🇭​ะะ🇦​ะะ🇮​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇲​ะะ🇪​ะ ะ🇩​ะะ🇪​ะะ🇹​ะ🇴​ะ🇱​ะ ะ🇩​ะะ??​ะะ🇦​ะะ🇱​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇦​ะ🇷​ะะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇦​ะะ🇦​ะ ะ🇧​ะะ🇭​ะะ🇴​ꜱ​ะะ🇩​ะะ🇦​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇲​ะะ🇪​ะ ะ🇱​ะะ🇦​ะะ🇵​ะะ🇹​ะ🇴​ะ🇵​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะ ะ🇭​ะะ🇦​ะะ🇮​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇴​ ะ🇧​ะะ🇮​ꜱ​ะะ🇹​ะะ🇦​ะ🇷​ะ ะ🇵​ะะ🇪​ะ ะ🇱​ะะ🇪​ะะ🇹​ะะ🇦​ะะ🇦​ะะ🇰​ะะ🇪​ะ ะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ??​ะะ🇴​ ะ🇦​ะะ🇲​ะะ🇪​ะ🇷​ะะ🇮​ะ🇨​ะะ🇦​ะ ะ🇬​ะะ🇭​ะะ🇺​ะะ🇲​ะะ🇦​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇦​ะ🇷​ะะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇲​ะะ🇪​ะ ะ🇳​ะะ🇦​ะะ🇦​ะ🇷​ะะ🇮​ะะ🇾​ะะ🇦​ะ🇱​ะ ะ🇵​ะะ🇭​ะ🇴​ะ🇷​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇪​ะ ะ🇬​ะะ🇦​ะะ🇳​ะะ🇩​ะ ะ🇲​ะะ🇪​ะ ะ🇩​ะะ🇪​ะะ🇹​ะ🇴​ะ🇱​ะ ะ🇩​ะะ🇦​ะะ🇦​ะะ🇱​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇴​ ะ🇭​ะ🇴​🇷​🇱​🇮​🇨​🇰​ꜱ​ะ ะ🇵​ะะ🇮​ะะ🇱​ะะ🇦​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇦​ะ🇷​ะะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇴​ ꜱ​ะะ🇦​ะ🇷​ะะ🇦​ะะ🇰​ะ ะ🇵​ะะ🇪​ะ ะ🇱​ะะ🇪​ะะ🇹​ะะ🇦​ะะ🇦​ะะ🇦​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะะ🇦​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇦​ะะ🇦​ะ ะ🇧​ะะ🇭​ะะ🇴​ꜱ​ะะ🇩​ะะ🇦​ะ",
        "ะ🇲​ะะ🇪​ะะ🇷​ะะ🇦​ะะ🇦​ะ ะ🇱​ะะ🇺​ะะ🇳​ะะ🇩​ะ ะ🇵​ะะ🇦​ะะ🇰​ะะ🇦​ะะ🇩​ะ ะ🇱​ะะ🇪​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇦​ะ🇷​ะะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะ",
        "ะ🇨​ะะ🇭​ะะ🇺​ะะ🇵​ะ ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇦​ะะ🇰​ะะ🇦​ะะ🇦​ะ ะ🇧​ะะ🇭​ะะ🇴​ꜱ​ะะ🇩​ะะ🇦​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇨​ะะ🇭​ะะ🇺​ꜱ​ะ ะ🇬​ะะ🇪​ะะ🇾​ะะ🇮​ะ ะ🇰​ะะ🇾​ะะ🇦​ะะ🇦​ะ ะ🇱​ะะ🇦​ะะ🇼​ะะ🇩​ะะ🇪​ะะ🇪​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇦​ะะ🇦​ะ ะ🇧​ะะ🇯​ꜱ​ะะ🇴​ะะ🇩​ะะ🇦​ะะ🇦​ะ",
        "ะ🇲​ะะ🇦​ะะ🇩​ะะ🇦​ะ🇷​ะ🇽​ะะ🇭​ะะ🇴​ะะ🇩​ะะ🇩​ะะ🇩​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะะ🇺​ะะ🇺​ะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇦​ะะ🇦​ะ ะ🇧​ะะ🇭​ꜱ​ะะ🇴​ะะ🇩​ะะ🇦​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะะ🇮​ะะ🇮​ะะ🇮​ะะ🇮​ะ ะ🇧​ะะ🇪​ะะ🇭​ะะ🇪​ะ🇳​ะะ🇳​ะะ🇳​ะ ะ🇰​ะะ🇴​ะ ะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะะ🇩​ะะ🇩​ะะ🇺​ะะ🇺​ะะ🇺​ะะ🇺​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇦​ะ🇷​ะ🇽​ะะ🇭​ะะ🇴​ะะ🇩​ะะ🇩​ะะ🇩​ะะ🇩​ะ",
        "ะ🇹​ะะ🇺​ะ ะ🇳​ะะ🇮​ะะ🇰​ะะ🇦​ะะ🇱​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇦​ะ🇷​ะะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะ",
        "ะ🇨​ะะ🇭​ะะ🇺​ะะ🇵​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะ ะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇦​ะะ🇨​ะะ🇭​ะะ🇪​ะ",
        "ะ??​ะะ🇪​ะะ🇷​ะะ🇦​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇲​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇯​ะะ🇦​ะะ🇦​ะ🇳​ะ ะ🇪​ะะ🇾​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ꜱ​ะ🇪​x​ะ🇾​ะ ะ🇧​ะะ🇦​ะะ🇭​ะะ🇪​ะ🇳​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇴​ะะ🇵​ะ",
        "⚡🇧⚡🇦⚡🇦⚡🇵 ⚡🇧⚡🇭⚡?? ⚡🇧⚡🇳⚡🇦⚡🇱⚡🇪 ⚡🇲⚡🇺⚡🇯⚡🇪 ⚡🇷⚡🇳⚡🇩⚡🇮⚡🇰⚡🇪",
        "⚡🇹⚡🇪⚡🇷⚡🇦 ⚡🇧⚡🇦⚡🇦⚡🇵 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮⚡🇧⚡🇦⚡🇦⚡🇿 ⚡🇪⚡🇾 ⚡🇾⚡🇦⚡🇦⚡🇩 ⚡🇪⚡🇾 ⚡🇹⚡🇺⚡🇯⚡🇭⚡🇪",
        "⚡🇹⚡🇺 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇦 ⚡🇳⚡🇦 ⚡🇹⚡🇾⚡🇲⚡🇵⚡🇦⚡🇸⚡🇸",
        "⚡🇴⚡🇾⚡🇪 ⚡🇺⚡🇳⚡🇫⚡🇺⚡🇳⚡🇳⚡🇾 ⚡🇸⚡🇼⚡🇮⚡🇵⚡🇪 ⚡🇲⚡🇹⚡🇹 ⚡🇰⚡🇷",
        "⚡🇴⚡🇭 ⚡🇭⚡🇪⚡🇱⚡🇱⚡🇴 ⚡🇧⚡🇮⚡🇭⚡🇦⚡🇷⚡🇮 ⚡🇹⚡🇪⚡??⚡🇦 ⚡🇧⚡🇦⚡🇦⚡🇵 ⚡🇧⚡🇮⚡🇭⚡🇦⚡🇷⚡🇮 ⚡🇴⚡🇷 ⚡🇹⚡🇺 ⚡🇻 ⚡🇧⚡🇮⚡🇭⚡🇦⚡🇷⚡🇮 ⚡🇦⚡🇺⚡🇰⚡🇦⚡🇹 ⚡🇲⚡🇪 ⚡🇷⚡🇭⚡🇦 ⚡🇰⚡🇷.",
        "⚡🇴⚡🇾⚡🇾 ⚡🇰⚡🇮⚡🇳⚡🇳⚡🇪⚡🇷 ⚡🇹⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇬⚡🇨 ⚡🇲⚡🇪 ⚡🇦⚡🇦⚡🇳⚡🇪 ⚡🇰⚡🇮 ⚡🇵⚡🇪⚡🇷⚡🇲⚡🇮⚡🇸⚡🇸⚡🇮⚡🇴⚡🇳 ⚡🇰⚡🇮⚡🇸⚡🇳⚡🇪 ⚡🇩⚡🇮.",
        "⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇭⚡🇦",
        "⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇭⚡🇦 ⚡🇪⚡🇰 ⚡🇧⚡🇦⚡🇦⚡🇷.",
        "⚡🇸⚡🇺⚡🇳 ⚡🇸⚡🇺⚡🇳 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇦.",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇨⚡🇦 ⚡🇧⚡🇭⚡🇴⚡🇸⚡🇩⚡🇦.",
        "⚡🇴⚡🇾⚡🇪 ⚡🇨⚡🇭⚡🇴⚡🇹⚡🇮 ⚡🇯⚡🇦⚡🇹⚡🇮 ⚡🇰⚡🇪 ⚡🇹⚡🇲⚡🇷.",
        "⚡🇰⚡🇾? ⚡🇯⚡🇱⚡🇩⚡🇮 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇰⚡🇮⚡🇩⚡🇩⚡🇪.",
        "⚡🇧⚡🇮⚡🇭⚡🇦⚡🇷⚡🇮 ⚡🇨⚡🇴⚡🇲 ⚡🇬⚡🇦⚡🇳⚡🇬 ⚡🇰⚡🇪 ⚡🇧⚡🇦⚡🇦⚡🇵 ⚡🇰⚡🇴 ⚡🇹⚡🇦⚡🇬 ⚡🇨⚡🇷⚡🇪⚡🇬⚡🇦 ⚡🇹⚡🇺",
        "⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇨⚡🇾⚡🇦 ⚡🇹⚡🇺 ⚡🇧⚡🇮⚡🇭⚡🇦⚡🇷⚡🇮 ⚡🇪⚡🇾 ⚡🇹⚡🇲⚡🇰⚡🇨 ⚡🇧⚡🇸",
        "⚡🇯⚡🇦⚡🇱⚡🇩⚡🇮 ⚡🇸⚡🇪 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮⚡🇧⚡🇦⚡🇦⚡🇿 ⚡🇵⚡🇦⚡🇵⚡🇦 ⚡🇧⚡🇴⚡🇱",
        "⚡🇸⚡🇮⚡🇩⚡🇪 ⚡🇭⚡🇴⚡🇯⚡🇦 ⚡🇧⚡🇮⚡🇭⚡🇦⚡🇷⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇦⚡🇧",
        "⚡🇭⚡🇾⚡🇪 ⚡🇵⚡🇬⚡🇱 ⚡🇧⚡🇭⚡🇬 ⚡🇲⚡🇦⚡🇹 ⚡🇦⚡🇨⚡🇭⚡🇪 ⚡🇸⚡🇪 ⚡🇨⚡🇺⚡🇩",
        "⚡🇧⚡🇭⚡🇬 ⚡🇳⚡🇾 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇹⚡🇺 ⚡🇦⚡🇯⚡🇯",
        "⚡🇭⚡🇾⚡🇪 ⚡🇵⚡🇬⚡🇱 ⚡🇰⚡🇪 ⚡🇧⚡🇨⚡🇭⚡🇪 ⚡🇧⚡🇭⚡🇦⚡🇬 ⚡🇲⚡🇦⚡🇹",
        "⚡🇭⚡🇾⚡🇪 ⚡🇩⚡🇺⚡🇷 ⚡🇭⚡🇦⚡🇹⚡🇹 ⚡🇲⚡🇦⚡🇩⚡🇭⚡🇦⚡🇷⚡🇨⚡🇭⚡🇴⚡🇩 ⚡🇰⚡🇪 ⚡🇧⚡🇦⚡🇨⚡🇭⚡🇪",
        "⚡🇰⚡🇴⚡🇮 ⚡🇧⚡🇦⚡🇹 ⚡🇳⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾 ⚡🇪⚡🇸⚡🇱⚡🇮⚡🇾⚡🇪 ⚡🇲⚡🇦⚡🇫 ⚡🇨⚡🇷 ⚡🇷⚡🇭⚡🇦 ⚡🇭⚡🇺 ⚡🇹⚡🇺⚡🇯⚡🇭⚡🇪",
        "⚡🇰⚡🇴⚡🇮 ⚡🇧⚡🇦⚡🇦⚡🇹 ⚡🇳⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇹⚡🇺 ⚡🇲⚡🇦⚡🇫⚡🇮 ⚡🇩⚡🇪 ⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦",
        "⚡🇦⚡🇨⚡🇭⚡🇪 ⚡🇸⚡🇪 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇹⚡🇺 ⚡🇲⚡🇦⚡🇫⚡🇮 ⚡🇲⚡🇮⚡🇱 ⚡🇯⚡🇦⚡🇾⚡🇪⚡🇬⚡🇮 ⚡🇹⚡🇺⚡🇯⚡🇭⚡🇪",
        "⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦 ⚡🇲⚡🇦⚡🇹 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇦 ⚡🇲⚡🇺⚡🇯⚡🇪 ⚡🇸⚡🇼⚡🇮⚡🇵⚡🇪 ⚡🇨⚡🇷⚡🇰⚡🇪",
        "⚡🇦⚡🇨⚡🇭⚡🇪 ⚡🇸⚡🇪 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇹⚡🇺 ⚡🇸⚡🇼⚡🇮⚡🇵⚡🇪 ⚡🇨⚡🇷⚡🇰⚡🇪",
        "⚡🇫⚡🇷 ⚡🇧⚡🇴⚡🇱⚡🇳⚡🇦 ⚡🇳⚡🇦 ⚡🇰⚡🇮 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇱⚡🇪 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦 ⚡🇸⚡🇼⚡🇮⚡🇵⚡🇪 ⚡🇨⚡🇷⚡🇰⚡🇪",
        "⚡🇨⚡🇾⚡🇦 ⚡🇭⚡🇺⚡🇦 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇵⚡🇷 ⚡🇰⚡🇪⚡🇸⚡🇪 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦",
        "⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇵⚡🇹⚡🇦 ⚡🇹⚡🇭⚡🇦 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇲⚡🇪⚡🇾 ⚡🇳⚡🇾 ⚡🇲⚡🇦⚡🇳⚡🇹⚡🇦 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇾",
        "⚡🇱⚡🇴⚡🇩⚡🇪 ⚡🇸⚡🇪 ⚡🇺⚡🇹⚡🇷 ⚡🇲⚡🇨",
        "⚡🇱⚡🇺⚡🇳 ⚡🇲⚡🇹 ⚡🇨⚡🇭⚡🇺⚡🇸 ⚡🇲⚡🇪⚡🇷⚡🇦",
        "⚡🇳⚡🇮⚡🇰⚡🇦⚡🇱 ⚡🇲⚡🇦⚡🇩⚡🇦⚡🇷⚡🇨⚡🇭⚡🇩",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇴⚡🇾⚡🇪 ⚡🇬⚡🇦⚡🇸⚡🇭⚡🇹⚡🇮 ⚡🇰 ⚡🇧⚡🇦⚡🇨⚡🇭⚡🇪",
        "⚡🇲⚡🇦⚡🇰⚡🇮⚡🇨⚡🇭⚡🇺⚡🇹 ⚡🇹⚡🇪⚡🇷⚡🇮",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇷⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪",
        "⚡🇲⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇮",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦 ⚡🇰 ⚡🇭⚡🇦⚡🇹⚡🇭 ⚡🇹⚡🇴⚡🇩⚡🇭 ⚡🇰 ⚡🇹⚡🇪⚡🇷⚡🇪 ⚡🇧⚡🇦⚡🇦⚡🇵 ⚡🇰 ⚡🇲⚡🇺⚡🇭 ⚡🇲⚡🇪 ⚡🇫⚡🇦⚡🇸⚡🇦⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪",
        "⚡🇱⚡🇪⚡🇦⚡🇻⚡🇪 ⚡🇱⚡🇪 ⚡🇹⚡🇺 ⚡🇷⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇵⚡🇦⚡🇸⚡🇦⚡🇳⚡🇩 ⚡🇳⚡🇦⚡🇮 ⚡🇦⚡🇾⚡🇦 ⚡🇲⚡🇪⚡🇰⚡🇴",
        "⚡🇱⚡🇪⚡🇦⚡🇻⚡🇪 ⚡🇱⚡🇪 ⚡🇹⚡🇺 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇮⚡🇩⚡🇪⚡🇷 ⚡🇸⚡🇪",
        "⚡🇱⚡🇪⚡🇦⚡🇻⚡🇪 ⚡🇱⚡🇪 ⚡🇯⚡🇱⚡🇩⚡🇮 ⚡🇸⚡🇪 ⚡🇼⚡🇷⚡🇳⚡🇦 ⚡🇲⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇱⚡🇪⚡🇦⚡🇻⚡🇪 ⚡🇳⚡🇾 ⚡🇱⚡🇪⚡🇬⚡🇦 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇸⚡🇲⚡🇯⚡🇭 ⚡🇧⚡🇦⚡🇹 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇱⚡🇪⚡🇦⚡🇻⚡🇪 ⚡🇱⚡🇪",
        "⚡🇫⚡🇦⚡🇸⚡🇹 ⚡🇱⚡🇪⚡🇦⚡🇻⚡🇪 ⚡🇱⚡🇪 ⚡🇰⚡🇦⚡🇲⚡🇯⚡🇴⚡🇷 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪",
        "⚡🇹⚡🇺⚡🇹⚡🇴 ⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇷⚡🇳⚡🇩⚡🇾⚡🇰",
        "⚡🇴⚡🇾 ⚡🇭⚡🇮⚡🇯⚡🇩⚡🇪 ⚡🇰⚡🇭⚡??⚡🇳⚡🇦 ⚡🇰⚡🇭⚡🇦 ⚡🇰⚡🇪 ⚡🇦⚡🇦 ⚡🇰⚡🇦⚡🇲⚡🇿⚡🇴⚡🇷",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇰⚡🇴 ⚡🇮⚡🇱⚡🇾 ⚡🇷⚡🇪⚡🇾 🌚😂",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇨⚡🇭⚡🇦⚡🇵 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇹⚡🇲⚡🇰⚡🇨",
        "⚡🇨⚡🇭⚡🇺⚡🇵⚡🇨⚡🇭⚡🇦⚡🇵 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇹⚡🇺",
        "⚡🇸⚡🇭⚡🇮 ⚡🇸⚡🇪 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡??⚡🇺 ⚡🇨⚡🇭⚡🇺⚡🇵⚡🇨⚡🇭⚡🇦⚡🇵",
        "⚡🇫⚡🇷 ⚡🇸⚡🇪 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇹⚡🇺 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇵⚡🇨⚡🇭⚡🇦⚡🇵",
        "⚡🇸⚡🇭⚡🇮 ⚡🇸⚡🇪 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇼⚡🇷⚡🇳⚡🇦 ⚡🇲⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡??⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇲⚡🇦 ⚡🇨⚡🇾⚡🇺 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇨⚡🇭⚡🇺⚡🇵⚡🇨⚡🇭⚡🇦⚡🇵",
        "⚡🇵⚡🇷⚡🇴⚡🇴⚡🇫 ⚡🇨⚡🇷 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇵⚡🇷⚡🇴⚡🇴⚡🇫 ⚡🇪⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾",
        "⚡🇵⚡🇷⚡🇴⚡🇴⚡🇫 ⚡🇭⚡🇴 ⚡🇨⚡🇭⚡🇺⚡🇰⚡🇦 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇨⚡🇭⚡🇮⚡🇱⚡🇱⚡🇦⚡🇷",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇲⚡🇦⚡🇦 ⚡🇰 ⚡🇧⚡🇴⚡🇸⚡🇩⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇴⚡🇾 ⚡🇭⚡🇮⚡🇯⚡🇩⚡🇪 ⚡🇰⚡🇭⚡🇦⚡🇳⚡🇦 ⚡🇰⚡🇭⚡🇦 ⚡🇰⚡🇪 ⚡🇦⚡🇦 ⚡🇰⚡🇦⚡🇲⚡🇿⚡🇴⚡🇷",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇲⚡🇦⚡🇩⚡🇷⚡🇨⚡🇭⚡🇴⚡🇩 ?",
        "⚡🇦⚡🇧 ⚡🇹⚡🇰 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮 ⚡🇭⚡🇴⚡🇬⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ?",
        "⚡🇳⚡🇾 ⚡🇳⚡🇾 ⚡🇲⚡🇪 ⚡🇰⚡🇺⚡🇨⚡🇭 ⚡🇳⚡🇾 ⚡🇯⚡🇦⚡🇳⚡🇹⚡🇦 ⚡🇧⚡🇸 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾",
        "⚡🇸⚡🇧⚡🇸⚡🇪 ⚡🇵⚡🇭⚡🇪⚡🇱⚡🇪 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇰⚡🇴 ⚡🇧⚡🇴⚡🇱 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇳⚡🇦 ⚡🇰⚡🇦⚡🇲 ⚡🇰⚡🇷⚡🇪",
        "⚡🇾⚡🇦⚡🇭⚡🇦 ⚡🇧⚡🇭⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇦 ⚡🇹⚡🇺 ⚡🇷⚡🇳⚡🇩⚡🇾⚡🇨⚡🇪 ⚡🇵⚡🇮⚡🇱⚡🇱⚡🇪",
        "⚡🇹⚡🇪⚡🇷⚡🇮⚡🇲⚡🇦⚡🇰⚡🇦⚡🇧⚡🇴⚡🇸⚡🇩⚡🇦",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇹⚡🇴 ⚡🇧⚡🇭⚡🇪⚡🇳 ⚡🇨⚡🇺⚡🇩⚡🇪⚡🇬⚡🇮",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇷⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇹⚡🇴⚡🇲⚡🇲⚡🇾",
        "⚡🇳⚡🇮⚡🇰⚡🇦⚡🇱 ⚡🇲⚡🇦⚡🇩⚡🇦⚡🇷⚡🇨⚡🇭⚡🇩 ⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇾⚡🇭⚡🇦 ⚡🇸⚡🇪",
        "⚡🇨⚡🇴⚡🇿 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦 ⚡🇦⚡🇳⚡🇩⚡🇭⚡🇮 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮 ⚡🇭⚡🇪",
        "⚡🇳⚡🇾⚡🇹⚡🇴 ⚡🇧⚡🇦⚡🇦⚡🇵 ⚡🇧⚡🇴⚡🇱 ⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪",
        "⚡🇳⚡🇾⚡🇳⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇭⚡🇴⚡🇬⚡🇮 ⚡🇷⚡🇳⚡🇩⚡🇮 ⚡🇯⚡🇴 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦⚡🇹⚡🇮 ⚡🇯⚡🇴⚡🇬⚡🇮",
        "⚡🇹⚡🇷⚡🇾 ⚡🇦⚡🇲⚡🇲⚡🇮 ⚡🇨⚡🇪 ⚡🇧⚡🇭⚡🇴⚡🇸⚡🇩⚡🇪 ⚡🇲⚡🇪 ⚡🇪⚡🇲⚡🇴⚡🇯⚡🇮 ⚡🇩⚡🇦⚡🇱 ⚡🇲⚡🇨",
        "⚡🇨⚡🇾⚡🇦 ? ⚡🇨⚡🇭⚡🇲⚡🇷 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇦 ⚡🇨⚡🇾⚡🇦 ?",
        "⚡🇹⚡🇲 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇷⚡🇮 ⚡🇭⚡🇴⚡🇬⚡🇮 ⚡🇫⚡🇷⚡🇷⚡🇹⚡🇴",
        "⚡🇨⚡🇾⚡🇦 ? ⚡🇰⚡🇧 ? ⚡🇵⚡🇬⚡🇱 ⚡🇪⚡🇾 ⚡🇨⚡🇾⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇰⚡🇪⚡🇰",
        "⚡🇨⚡🇾⚡🇦 ⚡🇸⚡🇨⚡🇭 ⚡🇲⚡🇪⚡🇾 ⚡🇵⚡🇬⚡🇱 ⚡🇪⚡🇾 ⚡🇨⚡🇾⚡🇦 ⚡🇹⚡🇺 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇨⚡🇺⚡🇩⚡🇼⚡?? ⚡🇱⚡🇮 ⚡🇹⚡🇺⚡🇳⚡🇪 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦",
        "⚡🇮⚡🇹⚡🇳⚡🇦 ⚡🇸⚡🇨⚡🇭 ⚡🇳⚡🇾 ⚡🇧⚡🇴⚡🇱 ⚡🇲⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇸⚡🇨⚡🇭 ⚡🇲⚡🇪⚡🇾 ⚡🇵⚡🇬⚡🇱 ⚡🇪⚡🇾 ⚡🇹⚡🇺 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇱⚡🇮⚡🇦 ⚡🇲⚡🇪⚡🇷⚡🇪 ⚡🇸⚡🇹⚡🇭",
        "⚡🇲⚡🇹⚡🇱⚡🇧 ⚡🇹⚡🇲⚡🇷",
        "⚡🇳⚡🇾⚡🇹⚡🇴",
        "⚡🇵⚡🇺⚡🇷⚡🇦 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇲⚡🇨",
        "⚡🇹⚡🇲⚡🇷 ⚡🇫⚡🇷⚡🇷⚡🇹⚡🇴",
        "⚡🇴⚡🇭 ⚡🇴⚡🇰 ⚡🇨⚡🇺⚡🇩⚡🇱⚡🇪 ⚡🇫⚡🇮⚡🇷",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇰⚡🇦 ⚡🇩⚡🇦⚡🇲⚡🇦⚡🇩",
        "⚡🇨⚡🇾⚡🇦 ? ⚡🇦⚡🇨⚡🇭⚡🇪 ⚡🇸⚡🇪 ⚡🇱⚡🇮⚡🇰⚡🇭⚡🇪 ⚡🇵⚡🇪⚡🇭⚡🇱⚡🇪 ⚡🇷⚡🇳⚡🇩⚡🇮⚡🇰⚡🇪⚡🇧⚡🇦⚡🇨⚡🇭⚡🇪",
        "⚡🇳⚡🇾⚡🇹⚡🇴 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇳⚡🇪 ⚡🇲⚡🇪 ⚡🇻⚡🇾⚡🇦⚡🇸⚡🇹 ⚡🇭⚡🇺",
        "⚡🇳⚡🇾⚡🇹⚡🇴 ⚡🇵⚡🇬⚡🇱 ⚡🇪⚡🇾 ⚡🇨⚡🇾⚡🇦 ⚡🇰⚡🇺⚡🇨⚡🇭 ⚡🇧⚡🇮",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇨⚡🇾⚡🇦 ? ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇦 ?",
        "⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇲⚡🇹 ⚡🇭⚡🇸⚡🇸",
        "⚡🇾⚡🇺⚡🇷 ⚡🇷⚡🇳⚡🇩⚡🇮 ⚡🇲⚡🇴⚡🇲",
        "⚡🇦⚡🇷⚡🇪 ⚡🇸⚡🇧⚡🇰⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇮 ⚡🇴⚡🇷 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇧⚡🇮",
        "⚡🇦⚡🇷⚡🇪 ⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇨⚡🇺⚡🇩⚡🇱⚡🇪 ⚡🇪⚡🇰 ⚡🇧⚡🇦⚡🇦⚡🇷",
        "⚡🇹⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇮 ⚡🇹⚡🇷⚡🇭",
        "⚡🇪⚡🇰 ⚡🇱⚡🇮⚡🇳⚡🇪 ⚡🇲⚡🇪 ⚡🇹⚡🇲⚡🇷",
        "⚡🇶",
        "⚡🇴⚡🇨⚡🇾 ⚡🇦⚡🇧 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇱⚡🇪",
        "⚡🇵⚡🇪⚡🇭⚡🇪⚡🇱⚡🇪 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇺",
        "⚡🇳⚡🇾⚡🇹⚡🇴",
        "⚡?? ?",
        "⚡🇭⚡🇾⚡🇾⚡🇾 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇦 ⚡🇪⚡🇰 ⚡🇧⚡🇦⚡🇦⚡🇷",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇸⚡🇺⚡🇳 ⚡🇩⚡🇴⚡🇸⚡🇹 ⚡🇹⚡🇲⚡🇷",
        "⚡🇧⚡🇭⚡🇦⚡🇬 ⚡🇯⚡🇦 ⚡🇷⚡🇦⚡🇦⚡🇳⚡🇩 ⚡🇲⚡🇦⚡🇦⚡🇫 ⚡🇨⚡🇷⚡🇷 ⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇵⚡🇬⚡🇱 ⚡🇷⚡🇳⚡🇩⚡🇮 ⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇦⚡🇦",
        "⚡🇨⚡🇾⚡🇦 ⚡🇹⚡🇲⚡🇷 ⚡🇫⚡🇷⚡🇷⚡🇹⚡🇴",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇦⚡🇦⚡🇰⚡🇪 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇱⚡🇪 ⚡🇨⚡🇭⚡🇲⚡🇷",
        "⚡🇳⚡🇾⚡🇹⚡🇴 ⚡🇦⚡🇪⚡🇸⚡🇪 ⚡🇭⚡🇮 ⚡🇨⚡🇺⚡🇩",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇭⚡🇾⚡🇾 ⚡🇦⚡🇮⚡🇸⚡🇪 ⚡🇭⚡🇮 ⚡🇨⚡🇺⚡🇩 ⚡🇱⚡🇪⚡🇳⚡🇦",
        "⚡🇴⚡🇷 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇱⚡🇪",
        "⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇦 ⚡🇴⚡🇷",
        "⚡🇭⚡🇾⚡🇾 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇴 ⚡🇳⚡🇦",
        "⚡🇨⚡🇭⚡🇺⚡🇩⚡🇴 ⚡🇲⚡🇹 ⚡🇧⚡🇭⚡🇦⚡🇬 ⚡🇯⚡🇦⚡🇴",
        "⚡🇧⚡🇾⚡🇾⚡🇪⚡🇪 ⚡🇭⚡🇾⚡🇾 ⚡🇨⚡🇾⚡🇦 ?",
        "⚡🇶⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇶 ⚡🇷⚡🇭⚡🇪 ⚡🇭⚡🇴 ?",
        "⚡🇵⚡🇬⚡🇱 ⚡🇪⚡🇾 ⚡🇨⚡🇾⚡🇦 ⚡🇲⚡🇨",
        "⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇲⚡🇹",
        "⚡🇨⚡🇾⚡🇦 ⚡🇵⚡🇬⚡🇱 ⚡🇷⚡🇳⚡🇩⚡🇮 ⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇦⚡🇦",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇦⚡🇲⚡🇲⚡🇮 ⚡🇨⚡🇪 ⚡🇧⚡🇭⚡🇴⚡🇸⚡🇩⚡🇪 ⚡🇲⚡🇪 ⚡🇨⚡🇭⚡🇦⚡🇵⚡🇵⚡🇦⚡🇱",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇦⚡🇦 ⚡🇲⚡🇨",
        "⚡🇰⚡🇲⚡🇿⚡🇷⚡🇴⚡🇷 ⚡🇪⚡🇾 ⚡🇨⚡??⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇮⚡🇪⚡🇰",
        "⚡🇨⚡🇾⚡🇦 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇷⚡🇭⚡🇦 ?",
        "⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇹⚡🇭⚡🇦 ⚡🇨⚡🇾⚡🇦 ?",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇸⚡🇱⚡🇮⚡🇩⚡🇪 ⚡🇱⚡🇪⚡🇰⚡🇪 ⚡🇧⚡🇦⚡🇦⚡🇹 ⚡🇨⚡🇷⚡🇲⚡🇨",
        "⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇺",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇨⚡🇵 ⚡🇲⚡🇹 ⚡🇨⚡🇷⚡🇷 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇱⚡🇪",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇭⚡🇾⚡🇾 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇦",
        "⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇦⚡🇦 ⚡🇹⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇸⚡🇨⚡🇭⚡🇴⚡🇫⚡🇺 ⚡🇰⚡🇭⚡🇦⚡🇨⚡🇭⚡🇦⚡🇷 ⚡🇰⚡🇭⚡🇦⚡🇨⚡🇭⚡🇦⚡🇷",
        "⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇦⚡🇦 ⚡🇯⚡🇦 ⚡🇲⚡🇨",
        "⚡🇭⚡🇾⚡🇾 ⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇦⚡🇦⚡🇰⚡🇪 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇱⚡🇪",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇰⚡🇲⚡🇿⚡🇴⚡🇷 ⚡🇲⚡🇨 ⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇦⚡🇦",
        "⚡🇾⚡🇪 ⚡🇨⚡🇾⚡🇦 ⚡🇹⚡🇲⚡🇷",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇳⚡🇾 ⚡🇨⚡🇵 ⚡🇳⚡🇾 ⚡🇨⚡🇷⚡🇷",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇵⚡🇬⚡🇱 ⚡🇲⚡🇹 ⚡🇨⚡🇷⚡🇷",
        "⚡🇨⚡🇺⚡🇩⚡🇱⚡🇪 ⚡🇦⚡🇷⚡🇦⚡🇲 ⚡🇸⚡🇪 ⚡🇲⚡🇨",
        "⚡🇵⚡🇬⚡🇱 ⚡🇪⚡🇾 ⚡🇨⚡🇾⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇮⚡🇪⚡🇰",
        "⚡🇨⚡🇵 ⚡🇨⚡🇷⚡🇨⚡🇪 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇪⚡🇬⚡🇦 !",
        "⚡🇧⚡🇦⚡🇦⚡🇵 ? ⚡🇲⚡🇨 ⚡🇲⚡🇪⚡🇷⚡🇦 ⚡🇨⚡🇴⚡🇮 ⚡🇲⚡🇦 ⚡🇧⚡🇦⚡🇦⚡🇵 ⚡🇳⚡🇾 ⚡🇪⚡🇾 ⚡🇲⚡🇦⚡🇮 ⚡🇺⚡🇵⚡🇦⚡🇷 ⚡🇸⚡🇪 ⚡🇷⚡🇴⚡🇨⚡🇰⚡🇪⚡🇹 ⚡🇵⚡🇪 ⚡🇧⚡🇪⚡🇹⚡🇭 ⚡🇨⚡🇪 ⚡🇧⚡🇸⚡🇸 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇳⚡🇪 ⚡🇦⚡🇾⚡🇦 ⚡🇭⚡🇺",
        "⚡🇨⚡🇭⚡🇴⚡🇹⚡🇦 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇷⚡🇳⚡🇩⚡🇮 ⚡🇰 ⚡🇧⚡🇦⚡🇨⚡🇭⚡🇪",
        "⚡🇨⚡🇭⚡🇴⚡🇹⚡🇦 ⚡🇱⚡🇮⚡🇰⚡🇭⚡🇦 ⚡🇼⚡🇷⚡🇳⚡🇦 ⚡🇹⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇾",
        "⚡🇹⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇧⚡🇦⚡🇰⚡🇦 ⚡🇨⚡🇴⚡🇩⚡🇪⚡🇬⚡🇦",
        "⚡🇹⚡🇲⚡🇰⚡🇨 ⚡🇲⚡🇦⚡🇮⚡🇳 ⚡🇧⚡🇺⚡🇷⚡🇫",
        "⚡🇧⚡🇭⚡🇮⚡🇰⚡🇦⚡🇷⚡🇮 ⚡🇰⚡🇮 ⚡🇯⚡🇭⚡🇦⚡🇹 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇦 ⚡🇱⚡🇪",
        "⚡🇨⚡🇭⚡🇴⚡🇩⚡🇰⚡🇪 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇲⚡🇦⚡🇷⚡🇯⚡🇦⚡🇾⚡🇪⚡🇬⚡🇮",
        "⚡🇹⚡🇲⚡🇰⚡🇨 ⚡🇲⚡🇦⚡🇮⚡🇳 ⚡🇲⚡🇴⚡🇺⚡🇳⚡🇹 ⚡🇪⚡🇻⚡🇪⚡🇷⚡🇪⚡🇸⚡🇹",
        "⚡🇲⚡🇺⚡🇭 ⚡🇲⚡🇪⚡🇾 ⚡🇱⚡🇪⚡🇬⚡🇦 ⚡🇱⚡🇺⚡🇳⚡🇩 ⚡🇲⚡🇪⚡🇷⚡🇦",
        "⚡🇭⚡🇮⚡🇯⚡🇩⚡🇪 ⚡🇰⚡🇮 ⚡🇯⚡🇭⚡🇦⚡🇹 ⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇼⚡🇷⚡🇳⚡🇦 ⚡🇹⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇮",
        "⚡🇲⚡🇪⚡🇳⚡🇺 ⚡🇳⚡🇾 ⚡🇵⚡🇹⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾",
        "⚡🇲⚡🇪⚡🇳⚡🇺 ⚡🇰⚡🇮 ⚡🇵⚡🇹⚡🇦 ⚡🇲⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇲⚡🇪⚡🇳⚡🇺 ⚡🇵⚡🇹⚡🇦 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇲⚡🇪⚡🇳⚡🇺 ⚡🇸⚡🇧 ⚡🇵⚡🇹⚡🇦 ⚡🇲⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇲⚡🇪⚡🇳⚡🇺 ⚡🇵⚡🇷 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾",
        "⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇪⚡🇳⚡🇺 ⚡🇵⚡🇹⚡🇦",
        "⚡🇹⚡🇪⚡🇳⚡🇺 ⚡🇴⚡🇷 ⚡🇲⚡🇪⚡🇳⚡🇺 ⚡🇵⚡🇹⚡🇦 ⚡🇪⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇧⚡🇸 ⚡🇧⚡🇸 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇦⚡🇵⚡🇳⚡🇮",
        "⚡🇧⚡🇸 ⚡🇧⚡🇸 ⚡🇲⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇹⚡🇭⚡🇳⚡🇰⚡🇸⚡🇸",
        "⚡🇧⚡🇸 ⚡??⚡🇸 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇱⚡🇮⚡🇦 ⚡🇹⚡🇺 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦⚡🇦",
        "⚡🇧⚡🇸 ⚡🇧⚡🇸 ⚡🇰⚡🇦⚡🇲⚡🇯⚡🇴⚡🇷 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇸⚡🇲⚡🇯⚡🇭 ⚡🇬⚡🇾⚡🇦 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇱⚡🇪 ⚡🇦⚡🇧",
        "⚡🇸⚡🇲⚡🇯⚡🇭 ⚡🇬⚡🇾⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾",
        "⚡🇸⚡🇲⚡🇯⚡🇭 ⚡🇬⚡🇾⚡🇦 ⚡🇹⚡🇺 ⚡🇸⚡🇦⚡🇧⚡🇮⚡🇹 ⚡🇰⚡🇷 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇨⚡🇾⚡🇦 ⚡🇭⚡🇺⚡🇦 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇹⚡🇺 ⚡🇦⚡🇵⚡🇳⚡🇮",
        "⚡🇪⚡🇦⚡🇸⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇱⚡🇪 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇹⚡🇺",
        "⚡🇪⚡🇦⚡🇸⚡🇾 ⚡🇼8 ⚡🇲⚡?? ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇱⚡🇪 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇦⚡🇧",
        "⚡🇸⚡🇦⚡🇳⚡🇸 ⚡🇦⚡🇷⚡🇮 ⚡🇭⚡🇦 ⚡🇰⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇬⚡🇮 ⚡🇦⚡🇯⚡🇯",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇰⚡🇴 ⚡🇧⚡🇮⚡🇳⚡🇦 ⚡🇸⚡🇦⚡🇳⚡🇸⚡🇸 ⚡🇱⚡🇪⚡🇹⚡🇪 ⚡🇭⚡🇺⚡🇪 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮⚡🇰⚡🇪 ⚡🇰⚡🇦⚡🇲⚡🇯⚡🇴⚡🇷",
        "⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦 ⚡🇳⚡🇴⚡🇷⚡🇲⚡🇮⚡🇪 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇱⚡🇪 ⚡🇹⚡🇺",
        "⚡🇫⚡🇷 ⚡🇨⚡🇾⚡🇦 ⚡🇳⚡🇴⚡🇷⚡🇲⚡🇮⚡🇪 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇧⚡🇦⚡🇸 ⚡🇹⚡🇭⚡🇪⚡🇰 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾",
        "⚡🇧⚡🇦⚡🇸 ⚡🇹⚡🇭⚡🇪⚡🇰 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮",
        "⚡🇰⚡🇦⚡🇲⚡🇯⚡🇴⚡🇷 ⚡🇹⚡🇭⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇪⚡🇸⚡🇱⚡🇮⚡🇾⚡🇪 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮",
        "⚡🇲⚡🇦⚡🇮 ⚡🇸⚡🇧 ⚡🇯⚡🇦⚡🇳⚡🇹⚡🇦 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇨⚡🇭⚡🇱 ⚡🇨⚡🇭⚡🇱 ⚡🇭⚡🇹 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮",
        "⚡🇫⚡🇷 ⚡🇰⚡🇦⚡🇮⚡🇸⚡🇪 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇲⚡🇦⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾",
        "⚡🇧⚡🇦⚡🇸 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾",
        "⚡🇫⚡🇷 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇲⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇪⚡🇾",
        "⚡🇰⚡🇦⚡🇲⚡🇯⚡🇴⚡🇷 ⚡🇲⚡🇦 ⚡🇰⚡🇦 ⚡🇧⚡🇨⚡🇭⚡🇦 ⚡🇹⚡🇺 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪",
        "⚡🇧⚡🇭⚡🇴⚡🇹 ⚡🇬⚡🇳⚡🇩⚡🇮 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇵⚡🇷 ⚡🇰⚡🇦⚡🇮⚡🇸⚡🇪 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇮⚡🇹⚡🇳⚡🇦 ⚡🇬⚡🇳⚡🇩⚡🇦",
        "⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇨⚡🇾⚡🇦 ⚡🇧⚡🇹⚡🇦 ⚡🇷⚡🇭⚡🇦 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇨⚡🇾⚡🇦 ⚡🇵⚡🇹⚡🇦 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇫⚡🇮⚡🇷 ⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇳⚡🇾 ⚡🇵⚡🇹⚡🇦 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇵⚡🇹⚡🇦 ⚡🇳⚡🇾 ⚡🇰⚡🇴⚡🇳 ⚡🇨⚡🇴⚡🇩 ⚡🇩⚡🇮⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇰⚡🇴",
        "⚡🇷⚡🇺⚡🇰 ⚡🇦⚡🇦⚡🇾⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇴⚡🇩⚡🇰⚡🇪",
        "⚡🇼⚡🇦⚡🇮⚡🇹 ⚡🇨⚡🇷 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇴⚡🇩 ⚡🇷⚡🇭⚡🇦 ⚡🇭⚡🇺",
        "⚡🇼⚡🇦⚡🇮⚡🇹 ⚡🇨⚡🇷 ⚡🇷⚡🇦⚡🇧⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇷⚡🇭⚡🇮 ⚡🇪⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇼⚡🇦⚡🇮⚡🇹 ⚡🇰⚡🇷 ⚡🇸⚡🇲⚡🇯⚡🇭 ⚡🇷⚡🇭⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇴⚡🇩⚡🇰⚡🇪",
        "⚡🇼⚡🇦⚡🇮⚡🇹 ⚡🇱⚡🇪 ⚡🇹⚡🇭⚡🇴⚡🇩⚡🇦 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇳⚡🇪 ⚡🇩⚡🇪 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇴",
        "⚡🇷⚡🇺⚡🇰 ⚡🇯⚡🇦 ⚡🇦⚡🇦⚡🇳⚡🇩 ⚡🇷⚡🇰⚡🇭 ⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇪 ⚡🇱⚡🇮⚡🇾⚡🇪",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇫⚡🇦⚡🇲⚡🇴⚡🇺⚡🇸 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾",
        "⚡🇲⚡🇦⚡🇦⚡🇳 ⚡🇱⚡🇮⚡🇦 ⚡🇲⚡🇪⚡🇳⚡🇪 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇸⚡🇦⚡🇱⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇲⚡🇦⚡🇦⚡🇳 ⚡🇱⚡🇮⚡🇦 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇸⚡🇭⚡🇦⚡🇳⚡🇹 ⚡🇧⚡🇪⚡🇹⚡🇭 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇹⚡🇺 ⚡🇦⚡🇵⚡🇳⚡🇮",
        "⚡🇸⚡🇭⚡🇦⚡🇳⚡🇹 ⚡🇧⚡🇪⚡🇹⚡🇭⚡🇰⚡🇪 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇱⚡🇪 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦⚡🇰⚡🇴 ⚡🇹⚡🇺",
        "⚡🇫⚡🇷 ⚡🇸⚡🇪 ⚡🇸⚡🇭⚡🇦⚡🇳⚡🇹 ⚡🇧⚡🇪⚡🇹⚡🇭 ⚡🇹⚡🇺 ⚡🇨⚡🇺⚡🇩 ⚡🇦⚡🇧 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇾⚡🇭⚡🇦",
        "⚡🇲⚡🇪⚡🇷⚡🇪 ⚡🇸⚡🇲⚡🇯⚡🇭 ⚡🇳⚡🇾 ⚡🇦⚡🇾⚡🇦 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇱⚡🇪 ⚡🇰⚡🇪⚡🇱⚡🇦 ⚡🇰⚡🇭⚡🇦 ⚡🇹⚡🇺 ⚡🇲⚡🇦⚡🇩⚡🇷⚡🇨⚡🇭⚡🇴⚡🇩",
        "⚡🇭⚡🇾⚡🇪 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮 ⚡🇨⚡🇾⚡🇦",
        "⚡🇭⚡🇾⚡🇪 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇲⚡🇦⚡🇷 ⚡🇬⚡🇦⚡🇮 ⚡🇨⚡🇾⚡🇦",
        "⚡🇭⚡🇾⚡🇪 ⚡🇸⚡🇨⚡🇭 ⚡🇧⚡🇹⚡🇦 ⚡🇨⚡🇴⚡🇲 ⚡🇨⚡??⚡🇩 ⚡🇩⚡🇮⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇴",
        "⚡🇨⚡🇭⚡🇱 ⚡🇨⚡🇭⚡🇴⚡🇩 ⚡🇩⚡🇮⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇰⚡🇴 ⚡🇸⚡🇲⚡🇯⚡🇭⚡🇱⚡🇪",
        "⚡🇧⚡🇦⚡🇰⚡🇮 ⚡🇰⚡🇴⚡🇮 ⚡🇩⚡🇮⚡🇰⚡🇰⚡🇦⚡🇹 ⚡🇳⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾",
        "⚡🇧⚡🇦⚡🇰⚡🇮 ⚡🇸⚡🇧 ⚡🇯⚡🇦⚡🇳⚡🇹⚡🇪 ⚡🇪⚡🇾 ⚡🇰⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇩⚡🇰⚡🇦⚡🇩 ⚡🇪⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇨⚡🇾⚡🇦 ⚡🇵⚡🇹⚡🇦 ⚡🇹⚡🇭⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇳⚡🇪 ⚡🇼⚡🇱⚡🇮 ⚡🇪⚡🇾",
        "⚡🇵⚡🇷 ⚡🇲⚡🇪⚡🇮 ⚡🇰⚡🇦⚡🇮⚡🇸⚡🇪 ⚡🇯⚡🇳⚡🇹⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇰⚡🇴 ⚡🇰⚡🇴⚡🇮 ⚡🇨⚡🇭⚡🇴⚡🇩 ⚡🇩⚡🇮⚡🇦",
        "⚡🇵⚡🇷 ⚡🇲⚡🇪⚡🇷⚡🇦 ⚡🇻⚡🇮 ⚡🇲⚡🇦⚡🇳⚡🇳⚡🇦 ⚡🇸⚡🇭⚡🇮 ⚡🇹⚡🇭⚡🇦 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇵⚡🇷 ⚡🇼⚡🇴 ⚡🇬⚡🇱⚡🇹 ⚡🇳⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾",
        "⚡🇵⚡🇷 ⚡🇼⚡🇴 ⚡🇸⚡🇭⚡🇮 ⚡🇪⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇩⚡🇰⚡🇦⚡🇩 ⚡🇪⚡🇾",
        "⚡🇵⚡🇷 ⚡🇰⚡🇦⚡🇮⚡🇸⚡🇪 ⚡🇰⚡🇮⚡🇦 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇴⚡🇲⚡🇫⚡🇴⚡🇴",
        "⚡🇧⚡🇺⚡🇷 ⚡🇨⚡🇭⚡🇪⚡🇪⚡🇷 ⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦 ⚡🇹⚡🇷⚡🇮 ⚡🇲⚡🇦 ⚡🇰⚡🇦",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦 ⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇱 ⚡🇲⚡🇪 ⚡🇱⚡🇴⚡🇩⚡🇦 ⚡🇲⚡🇦⚡🇷⚡🇰⚡🇪 ⚡🇺⚡🇸⚡🇰⚡🇮 ⚡🇩⚡🇭⚡🇦⚡🇩⚡🇰⚡🇦⚡🇳 ⚡🇷⚡🇴⚡🇰 ⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦",
        "⚡🇱⚡🇺⚡🇱⚡🇱⚡🇪 ⚡🇰⚡🇭⚡🇦 ⚡🇹⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇰⚡🇦⚡🇧⚡🇭⚡🇴⚡🇸⚡🇩⚡🇦",
        "⚡🇹⚡🇷⚡🇮 ⚡🇧⚡🇭⚡🇳 ⚡🇰⚡🇮 ⚡🇧⚡🇭⚡🇴⚡🇸⚡🇩⚡🇮 ⚡🇧⚡🇪⚡🇹⚡🇦",
        "⚡🇹⚡🇷⚡🇮 ⚡🇲⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇮 ⚡🇧⚡🇦⚡🇦⚡🇹 ⚡🇰⚡🇭⚡🇹⚡🇲",
        "⚡🇸⚡🇺⚡🇳 ⚡🇪⚡🇰 ⚡🇲⚡🇦⚡🇿⚡🇪 ⚡🇰⚡🇮 ⚡🇧⚡🇦⚡🇦⚡🇹 ⚡🇧⚡🇦⚡🇹⚡🇦⚡🇴 ⚡🇰⚡🇾⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇭⚡🇦⚡🇮",
        "⚡🇨⚡🇴⚡🇩⚡🇺 ⚡🇨⚡🇴⚡🇩⚡🇺 ⚡🇲⚡🇦⚡🇰⚡🇴 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇦⚡🇯 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇴⚡🇾⚡🇪",
        "⚡🇸⚡🇺⚡🇳 ⚡🇸⚡🇺⚡🇳 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇪 ⚡🇧⚡🇦⚡🇨⚡🇭⚡🇪 ⚡🇹⚡🇺",
        "⚡🇰⚡🇮⚡🇱⚡🇦⚡🇸 ⚡🇳⚡🇾 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪",
        "⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇨⚡🇾⚡🇦 ⚡🇵⚡🇹⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇧⚡🇭⚡🇪⚡🇳 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮",
        "⚡🇵⚡?? ⚡🇵⚡🇷 ⚡🇨⚡🇾⚡🇦 ⚡🇭⚡🇴⚡🇹⚡🇪 ⚡🇪⚡🇾 ⚡🇹⚡🇲⚡🇰⚡🇨",
        "⚡🇹⚡🇲⚡🇨⚡🇱 ⚡🇸⚡🇺⚡🇳⚡🇱⚡🇪",
        "⚡🇲⚡🇴⚡🇴⚡🇹 ⚡🇩⚡🇺 ⚡🇹⚡🇪⚡🇷⚡?? ⚡🇲⚡🇦⚡🇰⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇹 ⚡🇲⚡🇪⚡🇾",
        "⚡🇧⚡🇭⚡🇬⚡🇳⚡🇾 ⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇭⚡🇦 ⚡🇫⚡🇷",
        "⚡🇫⚡🇷 ⚡🇸⚡🇪 ⚡🇨⚡🇺⚡🇩⚡🇱⚡🇪 ⚡🇹⚡🇺",
        "⚡🇾⚡🇪 ⚡🇻⚡🇮 ⚡🇸⚡🇭⚡🇮 ⚡🇪⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇰⚡🇸 ⚡🇧⚡🇸",
        "⚡🇦⚡🇯 ⚡🇰⚡🇺⚡🇨⚡🇭 ⚡🇳⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇹⚡🇺 ⚡🇦⚡🇵⚡🇳⚡🇮",
        "⚡🇹⚡🇷⚡🇾 ⚡🇰⚡🇷 ⚡🇲⚡🇪⚡🇷⚡🇦 ⚡🇱⚡🇺⚡🇳⚡🇩 ⚡🇨⚡🇭⚡🇺⚡🇸⚡🇰⚡🇪",
        "⚡🇹⚡🇴⚡🇷⚡🇲⚡🇦⚡🇰⚡🇮⚡🇧⚡🇺⚡🇷 ⚡🇸⚡🇺⚡🇳",
        "⚡🇹⚡🇴⚡🇷 ⚡🇲⚡🇦⚡🇰⚡🇮 ⚡🇫⚡🇺⚡🇩⚡🇩⚡🇮 ⚡🇴⚡🇾⚡🇪",
        "⚡🇭⚡🇦⚡🇾⚡🇪 ⚡🇭⚡🇦⚡🇾⚡🇪 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮",
        "⚡🇴⚡🇾⚡🇪 ⚡🇱⚡🇺⚡🇳⚡🇩⚡🇰⚡🇪 ⚡🇵⚡🇦⚡🇸⚡🇮⚡🇳⚡🇪..",
        "⚡🇰⚡🇺⚡🇹⚡🇹⚡🇪 ⚡🇰⚡🇪 ⚡🇹⚡🇦⚡🇹⚡🇹⚡🇪 ⚡🇸⚡🇺⚡🇳",
        "⚡🇰⚡🇺⚡🇹⚡🇹⚡🇦 ⚡🇯⚡🇦⚡🇮⚡🇸⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇷⚡🇭⚡🇦 ⚡🇹⚡🇺",
        "⚡🇲⚡🇺⚡🇭 ⚡🇲⚡🇪⚡🇮 ⚡🇱⚡🇪 ⚡🇲⚡🇪⚡🇷⚡🇦..",
        "⚡🇯⚡🇭⚡🇦⚡🇹 ⚡🇰⚡🇪 ⚡🇵⚡🇮⚡🇸⚡🇸⚡🇺 ⚡🇸⚡🇺⚡🇳 ⚡🇹⚡🇲⚡🇰⚡🇨",
        "⚡🇭⚡🇦⚡🇭⚡🇦⚡🇭⚡🇭⚡🇦 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇼⚡🇪⚡🇦⚡🇰 ⚡🇹⚡🇦⚡🇹⚡🇹⚡🇪 ⚡🇺⚡🇹⚡🇭",
        "⚡🇼⚡🇪⚡🇦⚡🇰 ⚡🇪⚡🇾 ⚡🇹⚡🇺 ⚡🇨⚡🇺⚡🇩 ⚡🇷⚡🇭⚡🇦",
        "⚡🇼⚡🇪⚡🇦⚡🇰 ⚡🇦⚡🇨⚡🇭⚡🇪 ⚡🇸⚡🇪 ⚡🇨⚡🇺⚡🇩 ⚡🇹⚡🇺",
        "⚡🇼⚡🇪⚡🇦⚡🇰 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇷⚡🇭⚡🇮 ⚡🇩⚡🇪⚡🇰⚡🇭",
        "⚡🇼⚡🇪⚡🇪⚡🇰 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇦⚡🇧",
        "⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇳⚡🇾 ⚡🇷⚡🇴⚡🇰 ⚡🇹⚡🇺 ⚡🇼⚡🇪⚡🇦⚡🇰 ⚡🇪⚡🇾",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇭⚡🇮⚡🇿⚡🇩⚡🇪",
        "⚡🇴⚡🇰⚡🇦⚡🇹 ⚡🇳⚡🇾 ⚡🇲⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇹⚡🇺 ⚡🇦⚡🇵⚡🇳⚡🇮",
        "⚡🇱⚡🇺⚡🇳 ⚡🇱⚡🇪⚡🇬⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇮 ⚡🇬⚡🇦⚡🇳⚡🇩 ⚡🇲⚡🇪⚡🇮 ?",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇮 ⚡🇧⚡🇦⚡🇨⚡🇭⚡🇮 ⚡🇨⚡🇴⚡🇩⚡🇺..",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇧⚡🇭⚡🇪⚡🇳 ⚡🇰⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇹 ⚡🇦⚡🇯 ⚡🇫⚡🇦⚡🇩 ⚡🇩⚡🇺",
        "⚡🇸⚡🇵⚡🇪⚡🇪⚡🇩 ⚡🇱⚡🇪⚡🇰⚡🇷 ⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇭⚡🇦",
        "⚡🇸⚡🇵⚡🇪⚡🇪⚡🇩 ⚡🇳⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇪 ⚡🇦⚡🇳⚡🇩⚡🇷 ⚡🇼⚡🇪⚡🇦⚡🇰 ⚡🇵⚡🇷⚡🇴⚡🇸⚡🇳",
        "⚡🇺⚡🇬⚡🇱⚡🇾 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇨⚡🇭⚡🇺⚡🇵",
        "⚡🇲⚡🇦⚡🇰⚡🇦⚡🇫⚡🇺⚡🇩⚡🇩⚡🇦⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇹⚡🇪⚡🇷⚡🇦 ⚡🇧⚡🇦⚡🇦⚡🇵 ⚡🇰⚡🇴 ⚡🇹⚡🇦⚡🇬 ⚡🇰⚡🇷..?",
        "⚡🇦⚡🇨⚡🇭⚡🇪 ⚡🇸⚡🇪 ⚡🇹⚡🇦⚡🇬 ⚡🇰⚡🇷 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮⚡🇧⚡🇦⚡🇦⚡🇿 ⚡🇧⚡🇭⚡🇦⚡🇬⚡🇼⚡🇳 ⚡🇰⚡🇴..",
        "⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇵⚡🇬⚡🇱 ⚡🇳⚡🇾 ⚡🇭⚡🇴 ⚡🇹⚡🇺",
        "⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇵⚡🇬⚡🇱 ⚡🇭⚡🇴 ⚡🇷⚡🇭⚡🇦 ⚡🇹⚡🇺 ⚡🇰⚡🇮⚡🇩",
        "⚡🇲⚡🇦 ⚡🇹⚡🇴 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇭⚡🇦⚡🇼⚡🇦⚡🇧⚡🇿⚡🇮 ⚡🇨⚡🇷..",
        "⚡🇧⚡🇸 ⚡🇲⚡🇦 ⚡🇨⚡🇴⚡🇩⚡🇳⚡🇮 ⚡🇪⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇹⚡🇴⚡🇼⚡🇳 ⚡🇲⚡🇪⚡🇮 ⚡🇨⚡🇺⚡🇩 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇴 ⚡🇱⚡🇪⚡🇰⚡🇷",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇸⚡🇪⚡🇽⚡🇾 ⚡🇰⚡🇴 ⚡🇧⚡🇪⚡🇯 - ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮⚡🇧⚡🇦⚡🇦⚡🇿 ⚡🇧⚡🇭⚡🇬⚡🇼⚡🇳 ⚡🇵⚡🇪",
        "⚡🇸⚡🇵⚡🇪⚡🇪⚡🇩 ⚡🇵⚡🇰⚡🇩 ⚡🇨⚡🇵 ⚡🇳⚡🇾 ⚡🇰⚡🇷",
        "⚡🇹⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇷⚡🇪⚡🇳⚡🇩⚡🇾",
        "⚡🇧⚡🇭⚡🇰⚡🇰 ⚡🇨⚡🇺⚡🇩",
        "⚡🇹⚡🇪⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇮",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇧⚡🇪⚡🇭⚡🇪⚡🇳 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮",
        "⚡🇨⚡🇺⚡🇩 ⚡🇯⚡🇦",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇩⚡🇮⚡🇩⚡🇮 ⚡🇷⚡🇳⚡🇩⚡🇮",
        "⚡🇸⚡🇱⚡🇴⚡🇼",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇮⚡🇾⚡🇦 ⚡🇨⚡🇮⚡🇴⚡🇩⚡🇺",
        "⚡🇧⚡🇭⚡🇦⚡🇬?",
        "⚡🇧⚡🇭⚡🇦⚡🇰 ⚡🇨⚡🇺⚡🇩",
        "⚡🇹⚡🇲⚡🇦 ⚡🇨⚡🇴⚡🇩⚡🇺",
        "⚡🇸⚡🇱⚡🇴⚡🇼",
        "⚡🇸⚡🇱⚡🇴⚡🇼 ⚡🇫⚡🇮⚡🇷⚡🇸⚡🇪",
        "⚡🇨⚡🇺⚡🇩⚡🇬⚡🇷⚡🇮⚡🇧",
        "⚡🇹⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇩⚡🇴⚡🇺",
        "⚡🇹⚡🇧⚡🇰⚡🇨 ⚡🇨⚡🇴⚡🇩⚡🇺",
        "⚡🇳⚡🇪⚡🇹 ⚡🇴⚡🇳 ⚡🇴⚡🇫⚡🇫 ⚡🇼⚡🇦⚡🇱⚡🇮 ⚡🇷⚡🇳⚡🇩⚡🇾",
        "⚡🇴⚡🇾⚡🇪 ⚡🇹⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇴⚡🇩⚡🇺",
        "⚡🇮⚡🇩⚡🇭⚡🇦⚡🇷 ⚡🇦⚡🇦⚡🇰⚡🇪 ⚡🇨⚡🇺⚡🇩 ⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇨⚡🇭⚡🇦⚡🇦⚡🇵",
        "⚡🇹⚡🇧⚡🇰⚡🇨 ⚡🇲⚡🇷⚡🇩⚡🇺",
        "⚡🇴⚡🇮 ⚡🇲⚡🇦⚡🇦⚡🇰⚡🇪 ⚡🇱⚡🇴⚡🇩⚡🇪⚡🇪",
        "⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇧⚡🇪⚡🇪⚡🇯",
        "⚡🇹⚡🇲⚡🇰⚡🇨 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇺",
        "⚡🇸⚡🇺⚡🇦⚡🇷 ⚡🇰⚡🇪 ⚡🇧⚡🇪⚡🇪⚡🇯",
        "⚡🇳⚡🇪⚡🇹 ⚡🇴⚡🇫⚡🇫 ⚡🇴⚡🇳 ⚡🇰⚡🇷 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇱⚡🇦⚡🇩⚡🇰⚡🇪",
        "⚡🇹⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇮 ⚡🇰⚡🇪⚡🇸⚡🇪",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇸⚡🇱⚡🇴⚡🇼 ⚡🇲⚡🇦⚡🇩⚡🇭⚡🇦⚡🇷⚡🇨⚡🇴⚡🇩",
        "⚡🇹⚡??⚡🇰⚡🇨 ⚡🇨⚡🇴⚡🇩⚡🇺 ⚡🇰⚡🇷 ⚡🇲⚡🇸⚡🇬 ⚡🇩⚡🇪⚡🇱⚡🇪⚡🇹⚡🇪",
        "⚡🇴⚡🇮 ⚡🇸⚡🇺⚡🇦⚡🇷 ⚡🇰⚡🇪 ⚡🇱⚡🇦⚡🇩⚡🇰⚡🇪",
        "⚡🇹⚡??⚡🇰⚡🇨 ⚡🇫⚡🇺⚡🇫⚡🇮",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇩⚡🇮⚡🇩⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇮",
        "⚡🇹⚡🇲⚡🇰⚡🇨 ⚡🇩⚡🇮⚡🇰⚡🇭⚡🇦",
        "⚡🇨⚡🇺⚡🇩 ⚡🇦⚡🇧",
        "⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇨⚡🇺⚡🇩",
        "⚡🇧⚡🇭⚡🇦⚡🇰 ⚡🇨⚡🇺⚡🇩",
        "⚡🇨⚡🇺⚡🇩⚡🇱⚡🇪 ⚡🇹⚡🇧⚡🇰⚡🇨 ⚡🇲⚡🇷⚡🇺",
        "⚡🇹⚡🇲⚡🇰⚡🇱 ⚡🇨⚡🇺⚡🇩⚡🇱⚡🇪 ⚡🇬⚡🇷⚡🇮⚡🇧",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇧⚡🇪⚡🇭⚡🇪⚡🇳 ⚡🇻⚡🇪⚡🇸⚡🇮⚡🇾⚡🇦⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇮",
        "⚡🇮⚡🇹⚡🇳⚡🇦 ⚡🇬⚡🇳⚡🇩⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇦 ⚡🇹⚡🇺 ⚡🇫⚡🇮⚡🇷⚡🇸⚡🇪 ⚡🇳⚡🇪⚡🇹 ⚡🇴⚡🇳 ⚡🇴⚡🇫⚡🇫",
        "⚡🇬⚡🇷⚡🇮⚡🇧 ⚡🇰⚡🇪 ⚡🇧⚡🇪⚡🇹⚡🇪",
        "⚡🇧⚡🇭⚡🇦⚡🇬 ⚡🇯⚡🇦 ⚡🇱⚡🇴⚡🇩⚡🇪 ⚡🇹⚡🇲⚡🇰⚡🇨 ⚡🇲⚡🇦⚡🇷⚡🇺 ⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦",
        "⚡🇹⚡🇧⚡🇰⚡🇨 ⚡🇲⚡🇷⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦⚡🇦",
        "⚡🇧⚡🇭⚡🇦⚡🇬 ⚡🇹⚡🇲⚡🇰⚡🇨",
        "⚡🇧⚡🇭⚡🇦⚡🇬 ⚡🇹⚡🇧⚡🇰⚡🇨",
        "⚡🇹⚡🇧⚡🇰⚡🇨 ⚡🇲⚡🇪⚡🇾 ⚡🇨⚡🇵",
        "⚡🇨⚡🇵 ⚡🇹⚡🇧⚡🇰⚡🇨 ⚡🇲⚡🇪⚡🇭⚡🇭",
        "⚡🇨⚡🇵 ⚡🇹⚡🇲⚡🇰⚡🇱 ⚡🇲⚡🇪⚡🇭",
        "⚡🇨⚡🇵 ⚡🇧⚡🇴⚡🇱 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪",
        "⚡🇦⚡🇧⚡🇪 ⚡🇨⚡🇵 ⚡🇧⚡🇴⚡🇱 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪",
        "⚡🇩⚡🇴⚡🇺⚡🇧⚡🇱⚡🇪 ⚡🇸⚡🇪⚡🇳⚡🇩 ⚡🇰⚡🇴 ⚡🇨⚡🇵 ⚡🇹⚡🇲⚡🇰⚡🇨 ⚡🇨⚡🇴⚡🇩⚡🇺",
        "⚡🇹⚡🇧⚡🇰⚡🇨 ⚡🇲⚡🇪 ⚡🇨⚡🇵 ⚡🇨⚡🇴⚡🇩 ⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦 ⚡🇦⚡🇦⚡🇯 ⚡🇲⚡🇪⚡🇭⚡🇭",
        "⚡🇭⚡🇹 ⚡🇹⚡🇧⚡🇰⚡🇨 ⚡🇩⚡🇦⚡🇱⚡🇦⚡🇱 ⚡🇰⚡🇪 ⚡🇧⚡🇪⚡🇹⚡🇪.",
        "⚡🇷⚡🇳⚡🇩⚡🇾 ⚡🇯⚡🇱⚡🇩⚡🇮 ⚡🇯⚡🇱⚡🇩⚡🇮 ⚡🇨⚡🇺⚡🇩⚡🇶 ⚡🇹⚡🇷⚡🇾⚡🇲⚡🇦",
        "⚡🇵⚡🇦⚡🇷⚡🇦 ⚡🇱⚡🇮⚡🇰⚡🇭⚡🇪⚡🇬⚡🇦..",
        "⚡🇹⚡🇷⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇭⚡🇧⚡🇭⚡🇦⚡🇰",
        "⚡🇱⚡🇦⚡🇬⚡🇩⚡🇮 ⚡🇰⚡🇪 ⚡🇱⚡🇦⚡🇩⚡🇨⚡🇪 ⚡🇨⚡🇵 ⚡🇧⚡🇴⚡🇱",
        "⚡🇨⚡🇵 ⚡🇧⚡🇴⚡🇱 ⚡🇱⚡🇦⚡🇬⚡🇩⚡🇮 ⚡🇰⚡🇪 ⚡🇧⚡🇪⚡🇹⚡🇪..",
        "⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇨⚡🇵 ⚡🇧⚡🇴⚡🇱",
        "⚡🇧⚡🇭⚡🇮⚡🇰⚡🇦⚡🇷⚡🇮 ⚡🇱⚡🇺⚡🇳⚡🇩 ⚡🇨⚡🇭⚡🇺⚡🇸 ⚡🇲⚡🇪⚡🇷⚡??.",
        "⚡🇱⚡🇴⚡🇼 ⚡🇱⚡🇪⚡🇻⚡🇪⚡🇱 ⚡🇨⚡🇵 ⚡🇨⚡🇷",
        "⚡🇨⚡🇵 ⚡🇧⚡🇴⚡🇱 ⚡🇱⚡🇴⚡🇼 ⚡🇱⚡🇪⚡🇻⚡🇪⚡🇱 ⚡🇼⚡🇪⚡🇦⚡🇰",
        "⚡🇲⚡🇪⚡🇷⚡🇪 ⚡🇱⚡🇺⚡🇳⚡🇩 ⚡🇵⚡🇪 ⚡🇪⚡🇾 ⚡🇹⚡🇺 ⚡🇭⚡🇮⚡🇯⚡🇩⚡🇪",
        "⚡🇫⚡🇷⚡🇪⚡🇪 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇴",
        "⚡🇫⚡🇷⚡🇪⚡🇪 ⚡🇲⚡🇪⚡🇾 ⚡🇨⚡🇺⚡🇩 ⚡🇹⚡🇺 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪"
        "⚡🇸⚡🇵⚡🇪⚡🇪⚡🇩 ⚡🇳⚡🇾 ⚡🇼⚡🇪⚡🇦⚡🇰 ⚡🇹⚡🇦⚡🇹⚡🇹⚡🇪 ⚡🇹⚡🇪⚡🇷⚡🇲⚡🇪",
        "⚡??⚡🇮⚡🇹⚡🇳⚡🇮 ⚡🇧⚡🇷 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦⚡🇾⚡🇪⚡🇬⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾⚡🇲⚡🇦⚡🇰⚡🇴",
        "⚡🇱⚡🇺⚡🇳⚡🇩 ⚡🇱⚡🇪 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮⚡🇧⚡🇦⚡🇦⚡🇿 ⚡🇧⚡🇦⚡🇵⚡🇰⚡🇦",
        "⚡🇱⚡🇺⚡🇳 ⚡🇨⚡🇺⚡🇸 ⚡🇯⚡🇦⚡🇱⚡🇩⚡🇮 ⚡🇸⚡🇪 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮⚡🇧⚡🇦⚡🇦⚡🇿 ⚡🇧⚡🇦⚡🇵⚡🇰⚡🇦",
        "⚡🇰⚡🇴⚡🇮 ⚡🇳⚡🇾 ⚡🇩⚡🇪⚡🇰⚡🇭 ⚡🇷⚡🇭⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇱⚡🇪 ⚡🇹⚡🇺",
        "⚡🇨⚡🇺⚡🇩⚡🇱⚡🇪 ⚡🇧⚡🇪⚡🇹⚡🇮⚡🇨⚡🇭⚡🇴⚡🇩 ⚡🇦⚡🇨⚡🇭⚡🇪 ⚡🇸⚡🇪",
        "⚡🇲⚡🇦⚡🇰⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇹 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇧⚡🇸 ⚡🇾⚡🇪⚡🇭⚡🇮 ⚡🇯⚡🇦⚡🇳⚡🇹⚡🇦 ⚡🇲⚡🇪⚡🇾",
        "⚡🇨⚡🇵 ⚡🇧⚡🇴⚡🇱⚡🇪⚡🇬⚡🇦 ⚡🇹⚡🇴 ⚡🇹⚡🇲⚡🇰⚡🇨",
        "⚡🇼⚡🇷⚡🇳⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇯⚡🇦⚡🇾⚡🇪⚡🇬⚡🇮",
        "⚡🇸⚡🇱⚡🇴⚡🇼 ⚡🇪⚡🇾 ⚡🇹⚡🇺 ⚡🇰⚡🇮⚡🇩",
        "⚡🇯⚡🇱⚡🇩⚡🇮 ⚡🇱⚡🇮⚡🇰⚡🇭..",
        "⚡🇯⚡🇱⚡🇩⚡🇮 ⚡🇱⚡🇮⚡🇰⚡🇭..",
        "⚡🇹⚡🇾⚡🇲 ⚡🇸⚡🇪 ⚡🇵⚡🇭⚡🇱⚡🇪 ⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇭⚡🇦",
        "⚡🇹⚡🇾⚡🇲 ⚡🇭⚡🇴⚡🇬⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦",
        "⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇹⚡🇾⚡🇲 ⚡🇸⚡🇪 ⚡🇵⚡🇭⚡🇱⚡🇪",
        "⚡🇺⚡🇹⚡🇭 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇨⚡🇪 ⚡🇰⚡🇪 ⚡🇱⚡🇩⚡🇰⚡🇪",
        "⚡🇲⚡🇦⚡🇨⚡🇦⚡🇧⚡🇴⚡🇸⚡🇩⚡🇦⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇨⚡🇴⚡🇳 ⚡🇰⚡🇧 ⚡🇨⚡🇴⚡🇩 ⚡🇩⚡🇮⚡🇦 ⚡🇲⚡🇦⚡🇰⚡🇴 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇰⚡🇴⚡🇮 ⚡🇭⚡🇴⚡🇬⚡🇦 ⚡🇹⚡🇲⚡🇱",
        "⚡🇲⚡🇦⚡🇨⚡🇭⚡🇦⚡🇷 ⚡🇨⚡🇺⚡🇩⚡🇱⚡🇪 ⚡🇹⚡🇺",
        "⚡🇲⚡🇪⚡🇳⚡🇺 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇴 ⚡🇨⚡🇴⚡🇩⚡🇳⚡🇦 ⚡🇸⚡🇪",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇴 ⚡🇧⚡🇴⚡🇱 ⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇨⚡🇴⚡🇩 ⚡🇩⚡🇪",
        "⚡🇧⚡🇸 ⚡🇲⚡🇪⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇸⚡🇪 ⚡🇨⚡🇺⚡🇩⚡🇳⚡🇦 ⚡🇨⚡🇭⚡🇹⚡🇦 ⚡🇭⚡🇺",
        "⚡🇪⚡🇼⚡🇼 ⚡🇲⚡🇦⚡🇰⚡🇦 ⚡🇱⚡🇴⚡🇩⚡🇪 ⚡🇺⚡🇹⚡🇭",
        "⚡🇲⚡🇪⚡🇴⚡🇼 ⚡🇨⚡🇷 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇴 ⚡🇨⚡🇴⚡🇩⚡🇺",
        "⚡🇱⚡🇺⚡🇳⚡🇩 ⚡🇷⚡🇰⚡🇭 ⚡🇩⚡🇮⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇪 ⚡🇫⚡🇺⚡🇩⚡🇪 ⚡🇵⚡🇪",
        "⚡🇲⚡🇪⚡🇷⚡🇦 ⚡🇱⚡🇺⚡🇳⚡🇩 ⚡🇰⚡🇪 ⚡🇧⚡🇦⚡🇱 ⚡🇺⚡🇹⚡🇭",
        "⚡🇰⚡🇮⚡🇩⚡🇪⚡🇪 ⚡🇿⚡🇮⚡🇳⚡🇩⚡🇦 ⚡🇭⚡🇴",
        "⚡🇲⚡🇦⚡🇷 ⚡🇳⚡🇾 ⚡🇰⚡🇮⚡🇩⚡🇩⚡🇪 ⚡🇹⚡🇾⚡🇵⚡🇪 ⚡🇰⚡🇷",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇧⚡🇰⚡🇱",
        "⚡🇧⚡🇨 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇹",
        "⚡🇲⚡🇨 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇫⚡🇦⚡🇸⚡🇹",
        "⚡🇫⚡🇦⚡🇸⚡🇹 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪",
        "⚡🇫⚡🇦⚡🇸⚡🇹 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇰⚡🇦⚡🇲⚡🇿⚡🇴⚡🇷"
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇹 ⚡🇨⚡🇱⚡🇦⚡🇮⚡🇲 ⚡🇨⚡🇷⚡🇼⚡🇦",
        "⚡🇦⚡🇼⚡🇿 ⚡🇳⚡🇮⚡🇨⚡🇭⚡🇪 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇨⚡🇪 ⚡🇰⚡🇪 ⚡🇧⚡🇨⚡🇭⚡🇪",
        "⚡🇸⚡🇦⚡🇼⚡🇦⚡🇱 ⚡🇳⚡🇾 ⚡🇵⚡🇺⚡🇨⚡🇭 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇦⚡🇧⚡🇴⚡🇸⚡🇩⚡🇦",
        "⚡🇫⚡🇾⚡🇹⚡🇪⚡🇷 ⚡🇧⚡🇳⚡🇪⚡🇬⚡🇦 ⚡🇱⚡🇦⚡🇬⚡🇩⚡🇪 ⚡🇲⚡🇦⚡🇩⚡🇷⚡🇨⚡🇭⚡🇴⚡🇩",
        "⚡🇴⚡🇾⚡🇪 ⚡🇰⚡🇦⚡🇦⚡🇱⚡🇪 ⚡🇷⚡🇴 ⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇭⚡🇦",
        "⚡🇴⚡🇾⚡🇪 ⚡🇰⚡🇦⚡🇦⚡🇱⚡🇪 ⚡🇷⚡🇴⚡🇴 ⚡🇳⚡🇾",
        "⚡🇸⚡🇭⚡🇴⚡🇷⚡🇹 ⚡🇳⚡🇾 ⚡🇨⚡🇺⚡🇩 ⚡🇹⚡🇺 ⚡🇧⚡🇮⚡🇳⚡🇦 ⚡🇷⚡🇺⚡🇰⚡🇪",
        "⚡🇸⚡🇭⚡🇴⚡🇷⚡🇹 ⚡🇳⚡🇾 ⚡🇨⚡🇺⚡🇩 ⚡🇹⚡🇺 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦⚡🇰⚡🇴 ⚡🇱⚡🇪⚡🇰⚡🇷",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇪 ⚡🇸⚡🇹⚡🇭 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇧⚡🇭⚡🇪⚡🇳 ⚡🇻⚡🇮 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇱⚡🇪",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇪 ⚡🇸⚡🇹⚡🇭 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇩⚡🇮⚡🇩⚡🇮 ⚡🇻⚡🇮 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮",
        "⚡🇨⚡🇭⚡🇦⚡🇹 ⚡🇫⚡🇾⚡🇹⚡🇪⚡🇷 ⚡🇧⚡🇳⚡🇪⚡🇬⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇨⚡🇪 ⚡🇨⚡🇴⚡🇩⚡🇺 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇴",
        "⚡🇧⚡🇴⚡🇱 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮⚡🇧⚡🇦⚡🇦⚡🇿 ⚡🇩⚡🇦⚡🇩⚡🇩⚡🇾 ⚡🇪⚡🇾",
        "⚡🇧⚡🇺⚡🇱⚡🇱⚡🇾🇽 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇺⚡🇹⚡🇭",
        "⚡🇲⚡🇦⚡🇷 ⚡🇲⚡🇦⚡🇷⚡🇰⚡🇪 ⚡🇨⚡🇺⚡🇩 ⚡🇷⚡🇭⚡🇦 ⚡🇹⚡🇺",
        "⚡🇴⚡🇷 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇲⚡🇦⚡🇷⚡🇰⚡🇪 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮"
        "⚡🇯⚡🇦⚡🇱⚡🇩⚡🇮 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇷⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇧⚡🇪⚡🇯",
        "⚡🇴⚡🇷 ⚡🇧⚡🇩⚡🇦 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇹⚡🇲⚡🇨",
        "⚡🇴⚡🇷 ⚡🇧⚡🇩⚡🇦 2 ⚡🇱⚡🇮⚡🇳⚡🇪 ⚡🇼⚡🇱⚡🇦 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇹⚡🇲⚡🇰⚡🇨",
        "⚡🇴⚡🇷 ⚡🇧⚡??⚡🇦 ⚡🇴⚡🇾⚡🇪 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇹⚡🇲⚡🇱",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇰⚡🇦 ⚡🇧⚡🇺⚡🇷",
        "⚡🇴⚡🇾⚡🇪 ⚡🇰⚡🇪⚡🇪⚡🇩⚡🇪",
        "⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮 ⚡🇰⚡🇪 ⚡🇱⚡🇦⚡🇩⚡🇰⚡🇪",
        "⚡🇯⚡🇦⚡🇱⚡🇩⚡🇮 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇧⚡🇪⚡🇭⚡🇪⚡🇳 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇺",
        "⚡🇲⚡🇰⚡🇱 ⚡🇺⚡🇹⚡🇭 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮 ⚡🇰⚡🇪 ⚡🇧⚡🇦⚡🇨⚡🇨⚡🇭⚡🇪",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇳⚡🇦⚡🇳⚡🇮 ⚡🇲⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦⚡🇱",
        "⚡🇹⚡🇪⚡🇯 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇨⚡🇪",
        "⚡🇴⚡🇾⚡🇪 ⚡🇲⚡🇦⚡🇦⚡🇰⚡🇪 ⚡🇱⚡🇴⚡🇩⚡🇪 ⚡🇲⚡🇷⚡🇪⚡🇳⚡🇬⚡🇦",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇾",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇮⚡🇾⚡🇦 ⚡🇰⚡🇮 ⚡🇬⚡🇦⚡🇳⚡🇩",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇩⚡🇦⚡🇩⚡🇮 ⚡🇰⚡🇦 ⚡🇫⚡🇺⚡🇩⚡🇩⚡🇦",
        "⚡🇲⚡🇰⚡🇱 ⚡🇺⚡🇹⚡🇭 ⚡🇧⚡🇪⚡🇭⚡🇪⚡🇳⚡🇨⚡🇴⚡🇩",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇰⚡🇮 ⚡🇧⚡🇺⚡🇷 ⚡🇩⚡🇪",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇰⚡🇦 ⚡🇫⚡🇺⚡🇩⚡🇩⚡🇦 ⚡🇲⚡🇪 ⚡🇱⚡🇦⚡🇺⚡🇩⚡🇦",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇻⚡🇦",
        "⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮 ⚡🇰⚡🇪 ⚡🇧⚡🇪⚡🇹⚡🇪 ⚡🇲⚡🇦⚡🇷 ⚡🇬⚡🇦⚡🇾⚡🇦",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇰⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇹 ⚡🇲⚡🇷⚡🇺",
        "⚡🇯⚡🇦⚡🇱⚡🇮⚡🇩 ⚡🇰⚡🇷 ⚡🇸⚡🇵⚡🇦⚡🇲",
        "⚡🇲⚡🇨 ⚡🇸⚡🇵⚡🇦⚡🇲 ⚡🇷⚡🇴⚡🇰⚡🇪⚡🇳⚡🇬⚡🇦",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦⚡🇰⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇹 ⚡🇸⚡🇵⚡🇦⚡🇲 ⚡🇰⚡🇷",
        "⚡🇸⚡🇵⚡🇦⚡🇲 ⚡🇰⚡🇷.⚡🇲⚡🇦⚡🇦⚡🇰⚡🇪 ⚡🇱⚡🇴⚡🇩⚡🇪",
        "⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇪 ⚡🇸⚡🇵⚡🇦⚡🇲 ⚡🇰⚡🇷 ⚡🇼⚡🇷⚡🇳⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇹⚡🇺",
        "⚡🇸⚡🇵⚡🇦⚡🇲 ⚡🇰⚡🇷 ⚡🇰⚡🇮⚡🇩",
        "⚡🇳⚡🇴⚡🇴⚡🇧 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇺",
        "⚡🇷⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇧⚡🇪⚡🇹⚡🇪 ⚡🇲⚡🇦⚡🇷 ⚡🇲⚡🇦⚡🇹 ⚡🇹⚡🇺",
        "⚡🇳⚡🇴⚡🇴⚡🇧 ⚡🇯⚡🇦⚡🇱⚡🇩⚡🇮 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇼⚡🇷⚡🇳⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩",
        "⚡🇨⚡🇺⚡?? ⚡🇬⚡🇦⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇳⚡🇴⚡🇴⚡🇧",
        "⚡🇺⚡🇹⚡🇭 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇳⚡🇴⚡🇴⚡🇧",
        "⚡🇨⚡🇭⚡🇱 ⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇭⚡🇦 ⚡🇳⚡🇴⚡🇴⚡🇧",
        "⚡🇯⚡🇱⚡🇩⚡🇮 ⚡🇹⚡🇾⚡🇵 ⚡🇨⚡🇷 ⚡🇳⚡🇴⚡🇴⚡🇧 ⚡🇭⚡🇦⚡🇱⚡🇰⚡🇪",
        "⚡🇨⚡🇺⚡🇩 ⚡🇰⚡🇪 ⚡🇵⚡🇬⚡🇱 ⚡🇳⚡🇾 ⚡🇭⚡🇴 ⚡🇳⚡🇴⚡🇴⚡🇧",
        "⚡🇨⚡🇺⚡🇩 ⚡🇨⚡🇺⚡🇩 ⚡🇰⚡🇪 ⚡🇷⚡🇦⚡🇳⚡🇩 ⚡🇧⚡🇳⚡🇯⚡🇦 ⚡🇹⚡🇺 ⚡🇳⚡🇴⚡🇴⚡🇧",
        "⚡🇲⚡🇦⚡🇰⚡🇮⚡🇨⚡🇭⚡🇺⚡🇹 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇳⚡🇴⚡🇴⚡🇧",
        "⚡🇬⚡🇦⚡🇳⚡🇩⚡🇦 ⚡🇨⚡🇾⚡🇺 ⚡🇨⚡🇺⚡🇩 ⚡🇷⚡🇭⚡🇦 ⚡🇹⚡🇺 ?",    "⚡🇮⚡🇹⚡🇳⚡🇦 ⚡🇬⚡🇳⚡🇩⚡🇦 ⚡🇳⚡🇾 ⚡🇨⚡🇺⚡🇩 ⚡🇦⚡🇨⚡🇭⚡🇪 ⚡🇸⚡🇪 ⚡🇨⚡🇺⚡🇩",
        "⚡🇲⚡🇦⚡🇦⚡🇳 ⚡🇱⚡🇪 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇦 ⚡🇹⚡🇺 ⚡🇸⚡🇺⚡🇳 ⚡🇧⚡🇦⚡🇹 ⚡🇦⚡🇧",
        "⚡🇲⚡🇦⚡🇰⚡🇦⚡🇫⚡🇺⚡🇩⚡🇩⚡🇦 ⚡🇫⚡🇦⚡🇹 ⚡🇬⚡🇾⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇷⚡🇺⚡🇰",
        ]

        bar_texts = [
        "★🆂★🅷★🅰★🅽★🆃 ★🅱★🅴★🆃★🅷 ★🅼★🅰★🅳★🆁★🅲★🅷★🅾★🅳 ★🆆★🆁★🅽★🅰 ★🅼★🅰★🅺★🅰★🅱★🅾★🆂★🅳★🅰 ★🆃★🅴★🅴★🆈.",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃..",
        "★🅻★🆆★🅳★🅴 ★🅺★🅴 ★🅱★🅰★🅰★🅰★🅻★🅻★🅻 ★🆃★🅴★🆁★🆈 ★🅼★🅰★🅰 ★🅲★🆄★🅳★🅺★🅴 ★🅿★🅶★🅻 ★🅳★🅴★🅺★🅷.",
        "★🅼★🅰★🅲★🅷★🅰★🆁 ★🅺★🅸 ★🅹★🅷★🅰★🅰★🆃 ★🅺★🅴 ★🅱★🅰★🅰★🅰★🅻★🅻★🅻★🅻 ★🅲★🆄★🅳 ★🅰★🅲★🅷★🅴 ★🆂★🅴 ★🆈★🅷★🅰★🅿★🅴 ★🆃★🅤",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅼 ★🅳★🆄 ★🆃★🅰★🅿★🅰 ★🆃★🅰★🅿?",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅺★🅰 ★🅱★🅷★🅾★🅱★🅴★🅰★🅰",
        "★🆃★🅴★🆁★🅸 ★🅱★🅷★🅽 ★🅰★🅱★🅰★🅱★🅴 ★🅱★🅳★🅸 ★🆁★🅰★🅽★🅳★🅸.",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅾★🅰★🅰★🅴 ★🅱★🅰★🅳★🅸 ★🆁★🅰★🅽★🅳★🅳★🅳★🅳★🅳",
        "★🆃★🅴★🆁★🅰 ★🅱★🅰★🅰★🅿 ★🆁★🅰★🅽★🅳★🅸★🅱★🅰★🅰★🅾 ★🅴★🅈 ★🅳★🅴★🅺★🅷",
        "★🅺★🅸★🆃★🅽★🅸 ★🅲★🅷★🅾★🅳★🆄 ★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅰★🅱 ★🅾★🆁..",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅲★🅷★🅾★🅳 ★🅳★🅸 ★🅷★🅼 ★🅽★🅴",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅺★🅴 ★🅱★🅴★🅴★🅻★🅰 ★🅱★🅽★🅴★🅶★🅰 ★🆁★🅾★🅰★🅳 ★🅿★🅴★🅴",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅴★🅺 ★🅳★🅰★🅼 ★🆃★🅾★🅿 ★🅱★🅴★🆇★🆈",
        "★🅼★🅰★🅻★🆄★🅼 ★🅽★🅰 ★🅿★🅷★🆁 ★🅺★🅴★🅰★🅴 ★🅻★🅴★🆃★🅰 ★🅷★🆄 ★🅼 ★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🆃★🅰★🅿★🅰 ★🆃★🅰★🅿★🅿★🅿★🅿★🅿",
        "★🅻★🆄★🅽★🅳 ★🅺★🅴 ★🅲★🅷★🅾★🅳★🅴 ★🆃★🅤 ★??★🅴★🆁★🅴★🅶★🅰 ★🆃★🆈★🅿★🅸★🅽★🅶 ★🅺★🆁★🅴★🅶★🅰 ★🆃★🅼★🅺★🅲",
        "★🅱★🅴★🅱★🅳 ★🅿★🅺★🅳 ★🅻★🆆★🅳★🅴★🅴★🅴★🅴 ★🆆★🆁★🅽★🅰 ★🅼★🅴★🆁★🅰 ★🅻★🆄★🅽★🅳 ★🅿★🅺★🅳",
        "★🅱★🅰★🅰★🅿 ★🅺★🅸 ★🅱★🅴★🅱★🅳 ★🅼★🆃★🅲★🅷 ★🅺★🆁★🆁★🆁",
        "★🅻★🆆★🅳★🅰 ★🅻★🅴 ★🅼★🅴★🆁★🅰 ★🅹★🅰★🅻★🅳★🅸 ★🆂★🅴 ★🆃★🅤",
        "★🅿★🅰★🅿★🅰 ★🅺★🅸 ★🅱★🅴★🅱★🅳 ★🅼★🆃★🅲★🅷 ★🅽★🅷★🅸 ★🅷★🅾 ★🆁★🅷★🅸 ★🅺★🆈★🅰 ★🆃★??★🆁★🅴★🆂★🅴",
        "★🅰★🅻★🅴 ★🅰★🅻★🅴 ★🅼★🅴★🅻★🅰 ★🅱★🅲★🅷★🅰★🅰★🅰 ★🆃★🅴★🆁★🆈 ★🅼★🅰★🅺★🅰 ★🅱★🅾★🅂★🅳★🅰 ★🆂★🆄★🅽",
        "★🅲★🅷★🆄★🅳 ★🅶★🆈★🅰 ★🆁★🅰★🅽★🅳★🅸★🅱★🅰★🅰★🅾 ★🅿★🅰★🅿★🅰 ★🅱★🅴★🅴★🅴 ★🆃★🅤",
        "★🅼★🅴★🅽★🆄 ★🅺★🅸 ★🅿★🆃★🅰 ★🆃★🅴★🆁★🆈 ★🅼★🅰 ★🅲★🆄★🅳 ★🅶★🅰★🅸",
        "★🅺★🅾★🅸 ★🅱★🅰★🅰★🆃 ★🅽★🅈 ★🅼★🅰★🅰 ★🆁★🅰★🅽★🅳★🆈 ★🆃★🅴★🆁★🆈",
        "★🅷★🅰★🅷★🅰★🅷★🅰★🅰★🅰★🅰★🅰 ★🅼★🅰★🅺★🅰★🅱★🅾★🅂★🅳★🅰 ★🆃★🅴★🆁★🆈",
        "★🆇★🅷★🆄★🅳 ★🅶★🅰★🅸 ★🅼★🅰★🅰 ★🆃★🅴★🆁★🆈 ★🅺★🅸★🅳★🅰★🅰★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅲★🅷★🆄★🅳 ★🅶★🆈★🅸 ★🅰★🅱 ★🅱★🅰★🆁 ★🅼★🆃 ★🅷★🅾★🅽★🅰",
        "★🆈★🅴 ★🅻★🆄★🅽★🅳 ★🅻★🅴 ★🅼★🅴★🆁★🅰 ★🅲★🅷★🅻 ★🅹★🅰★🅻★🅳★🅸 ★🆂★🅴",
        "★🅺★🅸★🅳★🅰★🅰★🅰 ★🅱★🅰★🆁 ★🅽★🅰 ★🅷★🅾 ★🆃★🅤 ★🅷★🅰★🅷★🅰★🅷★🅷",
        "★🅱★🅷★🅴★🅽 ★🅺★🅴 ★🅻★🆆★🅳★🅴 ★🅱★🅷★🆁★🅼 ★🅺★🆁",
        "★🅺★🅸★🆃★🅽★🅸 ★🅶★🅻★🅸★🅈★🅰 ★🅿★🅳★🆆★🅴★🅶★🅰 ★🅰★🅿★🅽★🅸 ★🅼★🅰 ★🅺★🅾",
        "★🅲★🅷★🆄★🅿 ★🅽★🅰★🅻★🅻★🅸★🅸 ★🆁★🅰★🅽★🅳★🆈★🅺★🅴 ★🅻★🅰★🅳★🅺★🅴",
        "★🅱★🅰★🅰★🆁 ★🅺★🅴 ★🅿★🅸★🅻★🅻★🅴 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅱★🅰★🅳★🅰★🅺 ★🅿★🅁 ★🅻★🅸★🆃★🅰★🅺★🅴 ★🅲★🅷★🅾★🅳 ★🅳★🆄★🅽★🅶★🅰 😂😆🤤",
        "★🅰★🅱★🅴 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅰 ★🅱★🅷★🅾★🅱★🅴★🅰 ★🅼★🅰★🅳★🅴★🆁★🅲★🅷★🅾★🅾★🅳 ★🅺★🆁 ★🅿★🅸★🅻★🅻★🅴 ★🅿★🅰★🅿★🅰 ★🅱★🅴★🅴 ★🅻★🅰★🅳★🅴★🅶★🅰 ★🆃★🅤 😼😂🤤",
        "★🅶★🅰★🅻★🅸 ★🅶★🅰★🅻★🅸 ★🅽★🅴 ★🅱★🅷★🅾★🆁 ★🅷★🅴 ★🆃★🅴★??★🅸 ★🅼★🅰★🅰 ★🆁★🅰★🅽★🅳★🅸 ★🅲★🅷★🅾★🆁 ★🅷★🅴 💋💋💦",
        "★🅰★🅱★🅴 ★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅾 ★🅲★🅷★🅾★🅳★🆄 ★🆁★🅰★🅽★🅳★🅸★🅺★🅴 ★🅿★🅸★🅻★🅻★🅴 ★🅺★🆄★🆃★🆃★🅴 ★🅺★🅴 ★🅲★🅷★🅾★🅳★🅴 😂👻🔥",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅰★🅸★🅱★🅴 ★🅲★🅷★🅾★🅳★🅰 ★🅰★🅸★🅱★🅴 ★🅲★🅷★🅾★🅳★🅰 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅰 ★🅱★🅴★🅳 ★🅿★🅴★🅷★🅸 ★🅼★🆄★🆃★🅷 ★🅳★🅸★🅰 💦💦💦💦",
        "★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅴 ★🅱★🅷★🅾★🅱★🅴★🅳★🅴 ★🅼★🅴 ★🅰★??★🅰★🅶 ★🅻★🅰★🅶★🅰★🅳★🅸★🅰 ★🅼★🅴★🆁★🅰 ★🅼★🅾★🆃★🅰 ★🅻★🆄★🅽★🅳 ★🅳★🅰★🅻★🅺★🅴 🔥🔥💦😆😆",
        "★🆁★🅰★🅽★🅳★🅸★🅺★🅴 ★🅱★🅰★🅲★🅷★🅷★🅴 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅲★🅷★🅾★🅳★🆄 ★🅲★🅷★🅰★🅻 ★🅽★🅸★🅺★🅰★🅻",
        "★🅺★🅸★🆃★🅽★🅰 ★🅲★🅷★🅾★🅳★🆄 ★🆃★🅴★🆁★🅸 ★🆁★🅰★🅽★🅳★🅸 ★🅼★🅰★🅰★🅺★🅸 ★🅲★🅷★🆄★🆃★🅷 ★🅰★🅱★🅱 ★🅰★🅿★🅽★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅾 ★🅱★🅷★🅴★🅹 😆👻🤤",
        "★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅾★🆃★🅾 ★🅲★🅷★🅾★🅳 ★🅲★🅷★🅾★🅳★🅺★🅴 ★🅿★🆄★🆁★🅰 ★🅱★🅰★🅰★🅳 ★🅳★🅸★🅰 ★🅲★🅷★🆄★🆃★🅷 ★🅰★🅱★🅱 ★??★🅴★🆁★🅸 ★🅶★🅱 ★🅺★🅾 ★🅱★🅷★🅴★🅹 😆💦🤤",
        "★🆃★🅴★🆁★🅸 ★🅶★🅱 ★🅺★🅾 ★🅴★🆃★🅽★🅰 ★🅲★🅷★🅾★🅳★🅰 ★🅱★🅴★🅷★🅴★🅽 ★??★🅴 ★🅻★🅾★🅳★🅴 ★🆃★🅴★🆁★🅸 ★🅶★🅱 ★🆃★🅾 ★🅼★🅴★🆁★🅸 ★🆁★🅰★🅽★🅳★🅸 ★🅱★🅰★🅽★🅶★🅰★🆈★🅸 ★🅰★🅱★🅱 ★🅲★🅷★🅰★🅻 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅲★🅷★🅾★🅳★🆃★🅰 ★🅱★🅸★🆁★🅱★🅴 ♥️💦😆😆😆😆",
        "★🅷★🅰★🆁★🅸 ★🅷★🅰★🆁★🅸 ★🅶★🅷★🅰★🅰★🅱 ★🅼★🅴 ★🅹★🅷★🅾★🅿★🅳★🅰 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅰 ★🅱★🅷★🅾★🅱★🅴★🅰 🤣🤣💋💦",
        "★🅲★🅷★🅰★🅻 ★🆃★🅴★🆁★🅴 ★🅱★🅰★🅰★🅿 ★🅺★🅾 ★🅱★🅷★🅴★🅹 ★🆃★🅴★🆁★🅰 ★🅱★🅰★🅱★🅺★🅰 ★🅽★🅷★🅸 ★🅷★🅴 ★🅿★🅰★🅿★🅰 ★🅱★🅴★🅴 ★🅻★🅰★🅳★🅴★🅶★🅰 ★🆃★🅤",
        "★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅸 ★🅲★🅷★🆄★🆃★🅷 ★🅼★🅴 ★🅱★🅾★🅼★🅱 ★🅳★🅰★🅻★🅺★🅴 ★🆄★🅳★🅰 ★🅳★🆄★🅽★🅶★🅰 ★🅼★🅰★🅰★🅺★🅴 ★🅻★🅰★🆆★🅳★🅴",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🆃★🆁★🅰★🅸★🅽 ★🅼★🅴 ★🅻★🅴★🅹★🅰★🅺★🅴 ★🆃★🅾★🅿 ★🅱★🅴★🅳 ★🅿★🅴 ★🅻★🅸★🆃★🅰★🅺★🅴 ★🅲★🅷★🅾★🅳 ★🅳★🆄★🅽★🅶★🅰 ★🅱★🅰★🅰★🆁 ★🅺★🅴 ★🅿★🅸★🅻★🅻★🅴 🤣🤣💋💋",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅴 ★🅽★🆄★🅳★🅴★🅰 ★🅶★🅾★🅾★🅶★🅻★🅴 ★🅿★🅴 ★🆄★🅿★🅻★🅾★🅰★🅳 ★🅺★🅰★🆁★🅳★🆄★🅽★🅶★🅰 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅴 ★🅻★🅰★🅴★🆆★🅳★🅴 👻🔥",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅴 ★🅽★🆄★🅳★🅴★🅰 ★🅶★🅾★🅾★🅶★🅻★🅴 ★🅿★🅴 ★🆄★🅿★🅻★🅾★🅰★🅳 ★🅺★🅰★🆁★🅳★🆄★🅽★🅶★🅰 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅴 ★🅻★🅰★🅴★🆆★🅳★🅴 👻🔥",
        "★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅾 ★🅲★🅷★🅾★🅳 ★??★🅷★🅾★🅳★🅺★🅴 ★🅱★🅰★🅽★🅰★🅺★🅴 ★🅱★🅸★🅳★🅴★🅾 ★🅱★🅰★🅽★🅰★🅺★🅴 ★🆇★🅽★🆇★🆇.★🅲★🅾★🅼 ★🅿★🅴 ★🅽★🅴★🅴★🅻★🅰★🅼 ★🅺★🅰★🆁★🅳★🆄★🅽★🅶★🅰 ★🅺★🆄★🆃★🆃★🅴 ★🅺★🅴 ★🅿★🅸★🅻★🅻★🅴 💦💋",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅸 ★🅲★🅷★🆄★🅳★🅰★🅸 ★🅺★🅾 ★🅿★🅾★🆁★🅽★🅷★🆄★🅱.★🅲★🅾★🅼 ★🅿★🅴 ★🆄★🅿★🅻★🅾★🅰★🅳 ★🅺★🅰★🆁★🅳★🆄★🅽★🅶★🅰 ★🅱★🅰★🅰★🆁 ★🅺★🅴 ★🅲★🅷★🅾★🅳★🅴 🤣💋💦",
        "★🅰★🅱★🅴 ★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅾 ★🅲★🅷★🅾★🅳★🆄 ★🆁★🅰★🅽★🅳★🅸★🅺★🅴 ★🅱★🅰★🅲★🅷★🅷★🅴 ★🆃★🅴★🆁★🅴★🅺★🅾 ★🅲★🅷★🅰★🅺★🅺★🅾 ★🅱★🅴★🅴 ★🅿★🅸★🅻★🆆★🅰★🆅★🆄★🅽★🅶★🅰 ★🆁★🅰★🅽★🅳★🅸★🅺★🅴 ★🅱★🅰★🅲★🅷★🅷★🅴 🤣🤣",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅸 ★🅲★🅷★🆄★🆃★🅷 ★🅱★🅰★🅰★🅳★🅺★🅴 ★🆁★🅰★🅺★🅳★🅸★🅰 ★🅼★🅰★🅰★🅺★🅴 ★🅻★🅾★🅳★🅴 ★🅹★🅰★🅰 ★🅰★🅱★🅱 ★🅱★🅸★🅻★🆆★🅰★🅻★🅴 👄👄",
        "★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅸 ★🅲★🅷★🆄★🆃★🅷 ★🅼★🅴 ★🅼★🅴★🆁★🅰 ★🅻★🆄★🅽★🅳 ★🅺★🅰★🅰★🅻★🅰",
        "★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅻★🅴★🆃★🅸 ★🅼★🅴★🆁★🅸 ★🅻★🆄★🅽★🅳 ★🅱★🅰★🅳★🅴 ★🅼★🅰★🅱★🅰★🅱★🅸 ★🅱★🅴★🅴 ★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅾 ★🅼★🅴★🅽★🅴 ★🅲★🅷★🅾★🅳 ★🅳★🅰★🅻★🅰 ★🅱★🅾★🅷★🅾★🆃 ★🅱★🅰★🅱★🆃★🅴 ★🅱★🅴★🅴",
        "★🅱★🅴★🆃★🅴 ★🆃★🅤 ★🅱★🅰★🅰★🅿 ★🅱★🅴★🅴 ★🅻★🅴★🅶★🅰 ★🅿★🅰★🅽★🅶★🅰 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅰 ★🅺★🅾 ★🅲★🅷★🅾★🅳 ★🅳★🆄★🅽★🅶★🅰 ★🅺★🅰★🆁★🅺★🅴 ★🅽★🅰★🅽★🅶★🅰 💦💋",
        "★🅷★🅰★🅷★🅰★🅷★🅰★🅷 ★🅼★🅴★🆁★🅴 ★🅱★🅴★🆃★🅴 ★🅰★🅶★🅻★🅸 ★🅱★🅰★🅰★🆁 ★🅰★🅿★🅽★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅻★🅴★🅺★🅴 ★🅰★🅰★🆈★🅰 ★🅼★🅰★🆃★🅷 ★🅺★🅰★🆃 ★🅾★🆁 ★🅼★🅴★🆁★🅴 ★🅼★🅾★🆃★🅴 ★🅻★🆄★🅽★🅳 ★🅱★🅴★🅴 ★🅲★🅷★🆄★🅳★🆆★🅰★🆈★🅰 ★🅼★🅰★🆃★🅷 ★🅺★🅰★🆁",
        "★🅲★🅷★🅰★🅻 ★🅱★🅴★🆃★🅰 ★🆃★🆄★🅹★🅷★🅴 ★🅼★🅰★🅰★🅱 ★🅺★🅸★🅰 🤣★🆃★🅤 ★🅰★🅱★🅱 ★🅰★🅿★🅽★🅸 ★🅼★🅰★🅺★🅾 ★🅱★🅷★🅴★🅹",
        "★🅱★🅷★🅰★🆁★🅰★🅼 ★🅺★🅰★🆁 ★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅰 ★🅱★🅷★🅾★🅱★🅴★🅳★🅰 ★🅺★🅸★🆃★🅽★🅰 ★🅶★🅰★🅰★??★🅸★🅰 ★🅱★🆄★🅽★🆆★🅰★🆈★🅴★🅶★🅰 ★🅰★🅿★🅽★🅸 ★🅼★🅰★🅰★🅰 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅴 ★🆄★🅿★🅴★🆁",
        "★🅰★🅱★🅴 ★🆁★🅰★🅽★🅳★🅸★🅺★🅴 ★🅱★🅰★🅲★🅷★🅷★🅴 ★🅰★🆄★🅺★🅰★🆃 ★🅽★🅷★🅸 ★🅷★🅴★🆃★🅾 ★🅰★🅿★🅽★🅸 ★🆁★🅰★🅽★🅳★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅻★🅴★🅺★🅴 ★🅰★🅰★🆈★🅰 ★🅼★🅰★🆃★🅷 ★🅺★🅰★🆁 ★🅷★🅰★🅷★🅰★🅷★🅰★🅷★🅰",
        "★🅺★🅸★🅳★🅾 ★🅼★🅰★🅳★🅰★🆁★🅲★🅷★🅾★🅳 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅲★🅷★🅾★?? ★🅲★🅷★🅾★🅳★🅺★🅴 ★🆃★🅴★🆁★🆁 ★🅻★🅸★🆈★🅴 ★🅱★🅷★🅰★🅸 ★🅳★🅴★🅳★🅸★🆈★🅰",
        "★🅹★🆄★🅽★🅶★🅻★🅴 ★🅼★🅴 ★🅽★🅰★🅲★🅷★🆃★🅰 ★🅷★🅴 ★🅼★🅾★🆁★🅴 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅸 ★🅲★🅷★🆄★🅳★🅰★🅸 ★🅳★🅴★🅺★🅺★🅴 ★🅱★🅰★🅱 ★🅱★🅾★🅻★🆃★🅴 ★🅾★🅽★🅲★🅴 ★🅼★🅾★🆁★🅴 ★🅾★🅽★🅲★🅴 ★🅼★🅾★🆁★🅴 🤣🤣💦💋",
        "★🅶★🅰★??★🅸 ★🅶★🅰★🅻★🅸 ★🅼★🅴 ★🆁★🅴★🅷★🆃★🅰 ★🅷★🅴 ★🅱★🅰★🅽★🅳 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅲★🅷★🅾★🅳 ★🅳★🅰★🅻★🅰 ★🅾★🆁 ★🅱★🅰★🅽★🅰 ★🅳★🅸★🅰 ★🆁★🅰★🅽★🅳 🤤🤣",
        "★🅱★🅰★🅱 ★🅱★🅾★🅻★🆃★🅴 ★🅼★🆄★🅹★🅷★🅺★🅾 ★🅿★🅰★🅿★🅰 ★🅲★🆈★🆄★🅺★🅸 ★🅼★🅴★🅽★🅴 ★🅺★🆁★🅳★🅸★🅰 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅿★🆁★🅴★🅶★🅽★🅴★🅽★🆃 🤣🤣",
        "★🅱★🅰★🅰★🆁 ★🅺★🅴 ★🅿★🅸★🅻★🅻★🅴 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅸 ★🅲★🅷★🆄★🆃★🅷 ★🅼★🅴 ★🅱★🅰★🅰★🆁 ★🅺★🅰 ★🅻★🅾★🆄★🅳★🅰 ★🅾★🆁 ★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅸 ★🅲★🅷★🆄★🆃★🅷 ★🅼★🅴 ★🅼★🅴★🆁★🅰 ★🅻★🅾★🅳★🅰",
        "★🅲★🅷★🅰★🅻 ★🅲★🅷★🅰★🅻 ★🆃★🅤 ★🅰★🅿★🅽★🅸 ★🅼★🅰★🅰★🅺★🅸 ★🅲★🅷★🆄★🅲★🅷★🅸★🆈★🅰 ★🅳★🅸★🅺★🅰",
        "★🅷★🅰★🅷★🅰★🅷★🅰★🅷★🅰 ★🅱★🅰★🅲★🅷★🅷★🅴 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅰★🅺★🅾 ★🅲★🅷★🅾★🅳 ★🅳★🅸★🅰 ★🅽★🅰★🅽★🅶★🅰 ★🅺★🅰★🆁★🅺★🅴",
        "★🆃★🅴★🆁★🅸 ★🅶★🅱 ★🅷★🅴 ★🅱★🅰★🅳★🅸 ★🅱★🅴★🆇★🆈 ★🆄★🅱★🅺★🅾 ★🅿★🅸★🅻★🅰★🅺★🅴 ★🅲★🅷★🅾★🅾★🅳★🅴★🅽★🅶★🅴 ★🅿★🅴★🅿★🅱★🅸",
        "2 ★🆁★🆄★🅿★🅰★🆈 ★🅺★🅸 ★🅿★🅴★🅿★🅱★🅸 ★🆃★🅴★🆁★🅸 ★🅼★🆄★🅼★🅼★🆈 ★🅱★??★🅱★🅱★🅴 ★🅱★🅴★🆇★🆈 💋💦",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅲★🅷★🅴★🅴★🅼★🅱 ★🅱★🅴★🅴 ★🅲★🅷★🆄★🅳★🆆★🅰★🆅★🆄★🅽★🅶★🅰 ★🅼★🅰★🅳★🅴★🆁★🅲★🅷★🅾★🅾★🅳 ★🅺★🅴 ★🅿★🅸★🅻★🅻★🅴 💦🤣",
        "★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅸 ★🅲★🅷★🆄★🆃★🅷 ★🅼★🅴 ★🅼★🆄★🆃★🅷★🅺★🅴 ★🅱★🅰★🆁★🅰★🆁 ★🅷★🅾★🅹★🅰★🆅★🆄★🅽★🅶★🅰 ★🅷★🆄★🅸 ★🅷★🆄★🅸 ★🅷★🆄★🅸",
        "★🅱★🅴★🅱★🅳 ★🅻★🅰★🅰★🅰 ★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅲★🅷★🅾★🅳★🆄 ★🆁★🅰★🅽★🅳★🅸★🅺★🅴 ★🅿★🅸★🅻★🅻★🅴 💋💦🤣",
        "★🅰★🆁★🅴 ★🆁★🅴 ★🅼★🅴★🆁★🅴 ★🅱★🅴★🆃★🅴 ★🅲★🆈★🆄 ★🅱★🅴★🅱★🅳 ★🅿★🅰★🅺★🅰★🅳 ★🅽★🅰 ★🅿★🅰★🅰★🅰 ★🆁★🅰★🅷★🅰 ★🅰★🅿★🅽★🅴 ★🅱★🅰★🅰★🅿 ★🅺★🅰 ★🅷★🅰★🅷★🅰★🅷★🅰 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅲★🆄★🅳 ★🅶★🅰★🅸🤣🤣",
        "★🅱★🆄★🅽 ★🅱★🆄★🅽 ★🅱★🅰★🅰★🆁 ★🅺★🅴 ★🅿★🅸★🅻★🅻★🅴 ★🅹★🅷★🅰★🅽★🆃★🅾 ★🅺★🅴 ★🅱★🅾★🆄★🅳★🅰★🅶★🅰★🆁 ★🅰★🅿★🅽★🅸 ★🅼★🆄★🅼★🅼★🆈 ★🅺★🅸 ★🅽★🆄★🅳★🅴★🅱 ★🅱★🅷★🅴★🅹",
        "★🅰★🅱★🅴 ★🅱★🆄★🅽 ★🅻★🅾★🅳★🅴 ★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅰 ★🅱★🅷★🅾★🅱★🅴★🅳★🅰 ★🅱★🅰★🅰★🅳 ★🅳★🆄★🅽★🅶★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅺★🅷★🆄★🅻★🅴 ★🅱★🅰★🅹★🅰★🆁 ★🅼★🅴 ★🅲★🅷★🅾★🅳 ★🅳★🅰★🅻★🅰 🤣🤣💋",
        "★🅱★🅷★🆁★🅼 ★🅺★🆁 ★🆃★🅴★🆁★🆈 ★🅼★🅰★🅰 ★🅲★🆄★🅳 ★🅶★🅰★🅸 ★🆈★🅷★🅰",
        "★🅼★🅴★🆁★🅴 ★🅻★🆄★🅽★🅳 ★🅺★🅴 ★🅱★🅰★🅰★🅰★🅰★🅻★🅻★🅻★🅻★🅻 ★🅿★🅺★🅳 ★🅹★🅰★🅻★🅳★🅸 ★🅱★🅴★🅴",
        "★🆃★🅤 ★🅴★🅺 ★🅺★🅰★🅰★🅼 ★🅺★🆁 ★🅰★🅿★🅽★🅸 ★🅼★🅰 ★🅱★🅷★🅴★🅽 ★🅺★🅾 ★🅲★🆄★🅳★🆆★🅰 ★🅻★🅴 ★🅼★🅴★🆁★🅴 ★🅱★🆃★🅷",
        "★🆁★🅽★🅳★🅸 ★🅺★🅴 ★🅻★🅳★🅺★🅴★🅴★🅴★🅴★🅴★🅴★🅴★🅴 ★🅲★🅷★🆄★🅿 ★🅾★🆁 ★🅲★🆄★🅳 ★🆈★🅷★🅰",
        "★🅲★🅷★🆄★🅿 ★🆃★🅼★🅺★🅲 ★🅺★🅸★🅳★🅰★🅰★🅰★🅰★🅰★🅰★🅰★🅰★🅰★🅰★🅰★🅰★🅰",
        "★🅰★🅿★🅽★🅸 ★🅶★🅰★🅰★🅽★🅳 ★🅼★🅴★🅸★🅽 ★🅼★🆄★🆃★🅷★🅸 ★🅳★🅰★🅰★🅻",
        "★🅼★🅴★🆁★🅰 ★🅻★🆄★🅽★🅳 ★🅲★🅷★🅾★🅾★🅱 ★🅹★🅰★🅻★🅳★🅸 ★🅱★🅴★🅴",
        "★🅰★🅿★🅽★🅸 ★🅼★🅰 ★🅺★🅾 ★🅲★🆄★🅱★🆆★🅰 ★🅼★🅴★🆁★🅰 ★🅻★🆄★🅽★🅳",
        "★🅱★🅷★🅴★🅽 ★🅺★🅴 ★🅻★🅰★🆄★🅳★🅴 ★🆃★🅼★🅲",
        "★🅱★🅷★🅴★🅽 ★🅺★🅴 ★🆃★🅰★🅺★🅺★🅴 ★🆃★🅼★🅻",
        "★🅰★🅱★🅻★🅰 ★🆃★🅴★🆁★🅰 ★🅺★🅷★🅰★🅽 ★🅳★🅰★🅽 ★🅲★🅷★🅾★🅳★🅽★🅴 ★🅺★🅸 ★🅱★🅰★🆁★🅸★🅸",
        "★🅱★🅴★🆃★🅴 ★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅱★🅰★🅱★🅱★🅴 ★🅱★🅳★🅸 ★🆁★🅰★🅽★🅳",
        "★🅻★🆄★🅽★🅳 ★🅺★🅴 ★🅱★🅰★🅰★🅰★🅻 ★🅹★🅷★🅰★🆃 ★🅺★🅴 ★🅿★🅸★🅱★🅱★🅱★🆄★🆄★🆄★🆄★🆄★🆄 ★🆃★🅼★🅺★🅲",
        "★🅻★🆄★🅽★🅳 ★🅿★🅴 ★🅻★🆃★🅺★🅸★🆃 ★🅼★🅰★🅰★🅻★🅻★🅻★🅻 ★🅺★🅸 ★🅱★🅾★🅽★🅳 ★🅷 ★🆃★🆄★??★🆄",
        "★🅺★🅰★🅱★🅷 ★🅾★🅱 ★🅳★🅸★🅽 ★🅼★🆄★🆃★🅷 ★🅼★🆁★🅺★🅴 ★🅱★🅾★🅹★🆃★🅰 ★🅼 ★🆃★🅤 ★🅿★🅰★🅸★🅳★🅰 ★🅽★🅰 ★🅷★🅾★🆃★🅰★🅰",
        "★🅶★🅻★🆃★🅸 ★🅺★🆁★🅳★🅸 ★🆃★🆄★🅹★🆆 ★🅿★🅰★🅸★🅳★🅰 ★🅺★🆁★🅺★🅴 ★🆃★🅴★🆁★🆈 ★🅼★🅰 ★🅽★🅴 ★🅰★🅱 ★🅲★🆄★🅳 ★🆃★🅤 ★🆈★🅷★🅰",
        "★🅱★🅴★🅱★🅳 ★🅿★🅺★🅳★🅳★🅳",
        "★🅶★🅰★🅰★🅽★🅳 ★🅼★🅰★🅸★🅽 ★🅻★🆆★🅳★🅰 ★🅳★🅰★🅻 ★🅻★🅴 ★🅰★🅿★🅽★🅸 ★🅼★🅴★🆁★🅰★🅰★🅰",
        "★🅶★🅰★🅰★🅽★🅳 ★🅼★🅴★🅸★🅽 ★🅱★🅰★🅼★🅱★🆄 ★🅳★🅴★🅳★🆄★🅽★🅶★🅰★🅰★🅰★🅰★🅰",
        "★🅶★🅰★🅽★🅳 ★🅱★🆃★🅸 ★🅺★🅴 ★🅱★🅰★🅻★🅺★🅺★🅺 ★🆃★🅤 ★🅲★🆄★🅳 ★🆈★🅷★🅰",
        "★🅶★🅾★🆃★🅴 ★🅺★🅸★🆃★🅽★🅴 ★🅱★🅷★🅸 ★🅱★🅰★🅳★🅴 ★🅷★🅾, ★🅻★🆄★🅽★🅳 ★🅺★🅴 ★🅽★🅸★🅲★🅷★🅴 ★🅷★🅸 ★🆁★🅴★🅷★🆃★🅴 ★🅷★🅰",
        "★🅷★🅰★🅾★??★🅰★🆁 ★🅻★🆄★🅽★🅳 ★🆃★🅴★🆁★🅸 ★🅶★🅰★🅰★🅽★🅳 ★🅼★🅰★🅸★🅽",
        "★🅹★🅷★🅰★🅰★🅽★🆃 ★🅺★🅴 ★🅿★🅸★🅱★🅱★🆄 ★🆃★🅼★🅺★🅲 ★🅱★🆄★🅽",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅺★🅸 ★🅺★🅰★🅻★🅸 ★🅲★🅷★🆄★🆃",
        "★🅺★🅷★🅾★🆃★🅴★🆈 ★🅺★🅸 ★🅰★🆄★??★🅳★🅰 ★🅴★🆈 ★🆃★🅤 ★🆁★🅰★🅽★🅳★🆈★🅺★🅴",
        "★🅺★🆄★🆃★🆃★🅴 ★🅺★🅰 ★🅰★🆆★🅻★🅰★🆃 ★🅹★🅰★🅸★🅱★🅰 ★🅻★🅶 ★🆁★🅷★🅰 ★🆃★🅤",
        "★🅺★🆄★🆃★🆃★🅴 ★🅺★🅸 ★🅹★🅰★🆃 ★🅹★🅰★🅸★🅱★🅰 ★🅴★🆈 ★🆃★🅤 ",
        "★🅺★🆄★🆃★🆃★🅴 ★🅺★🅴 ★🆃★🅰★🆃★🆃★🅰 ★🅴★🆈 ★🆃★🅤",
        "★🆃★🅴★🆃★🅸 ★🅼★🅰 ★🅺★🅸.★🅲★🅷★🆄★🆃 , ★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🆁★🅽★🅳★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸",
        "★🅻★🅰★🆅★🅳★🅴 ★🅺★🅴 ★🅱★🅰★🅻 ★🅿★🅺★🅳 ★🅻★🅴 ★🅼★🅴★🆁★🅴",
        "★🅼★🆄★🅷 ★🅼★🅴★🅸 ★🅻★🅴★🅻★🅴 ★🅼★🅴★🆁★🅰 ★🅻★🆄★🅽★🅳",
        "★🅻★🆄★🅽★🅳 ★🅺★🅴 ★🅿★🅰★🅱★🅸★🅽★🅴 ★🅲★🅷★🆄★🅿 ★🅱★🅴★🆃★🅷 ★🅾★🆁 ★🅲★🆄★🅳",
        "★🅼★🅴★🆁★🅴 ★🅻★🆆★🅳★🅴 ★🅺★🅴 ★🅱★🅰★🅰★🅰★🅰★🅻★🅻★🅻",
        "★🅷★🅰★🅷★🅰★🅷★🅰★🅰★🅰★🅰★🅰★🅰 ★🆃★🅴★🆁★🆈 ★🅼★🅰★🅰 ★🅲★🆄★🅳 ★🅶★🅰★🅸",
        "★🆃★🅤 ★🅲★🅷★🆄★🅳 ★🅶★🆈★🅰★🅰★🅰★🅰",
        "★🆁★🅰★🅽★🅳★🅸 ★🅺★🅷★🅰★🅽★🅴 ★🅺★🅸 ★🆄★🅻★🅰★🅳★🅳★🅳",
        "★🅱★🅰★🅳★🅸 ★🅷★🆄★🅸 ★🅶★🅰★🅰★🅽★🅳",
        "★🆃★🅴★🆁★🅸 ★🅶★🅰★🅰★🅽★🅳 ★🅼★🅰★🅸★🅽 ★🅺★🆄★🆃★🅴 ★🅺★🅰 ★🅻★🆄★🅽★🅳",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅰 ★🅱★🅷★🅾★🅱★🅴★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃",
        "★🆃★🅴★🆁★🅴 ★🅶★🅰★🅰★🅽★🅳 ★🅼★🅴★🅸★🅽 ★🅺★🅴★🅴★🅳★🅴 ★🅿★🅰★🅳★🅰★🆈",
        "★🅽★🆈 ★🅽★🆈 ★🆃★🅴★🆁★🆈 ★🅼★🅰★🅰 ★🆁★🅰★🅽★🅳★🅸",
        "★🅱★🆄★🅽★🅽 ★🅼★🅰★🅳★🅴★🆁★🅲★🅷★🅾★🅳 ★🆃★🅼★🅻",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅰 ★🅱★🅷★🅾★🅱★🅴★🅰",
        "★🅱★🅴★🅷★🅴★🅽 ★🅺 ★🅻★🆄★🅽★🅳 ★🅲★🅷★🆄★🅿★🅲★🅷★🅰★🅿 ★🅲★🆄★🅳 ★🆈★🅷★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅰 ★🅲★🅷★🆄★🆃 ★🅺★🅸 ★🅲★🅷★🆃★🅽★🅸★🅸★🅸",
        "★🅼★🅴★🆁★🅰 ★🅻★🅰★🆆★🅳★🅰 ★🅻★🅴★🅻★🅴 ★🆃★🅤 ★🅰★🅶★🅰★🆁 ★🅲★🅷★🅰★🅸★🆈★🅴 ★🆃★🅾★🅷",
        "★🅲★🅷★🆄★🅿 ★🅶★🅰★🅰★🅽★🅳★🆄",
        "★🅲★🅷★🆄★🅿 ★🅲★🅷★🆄★🆃★🅸★🆈★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅿★🅴 ★🅹★🅲★🅱 ★🅲★🅷★🅰★🅳★🅷★🅰★🅰 ★🅳★🆄★🅽★🅶★🅰",
        "★🅱★🅰★🅼★🅹★🅷★🅰★🅰 ★🅻★🅰★🆆★🅳★🅴",
        "★🆈★🅰 ★🅳★🆄 ★🆃★🅴★🆁★🅸 ★🅶★🅰★🅰★🅽★🅳 ★🅼★🅴 ★🆃★🅰★🅿★🅰★🅰 ★🆃★🅰★🅿",
        "★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅼★🅴★🆁★🅰 ★🆁★🅾★🅾 ★🅻★🅴★🆃★🅸 ★🅷★🅰★🅸",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅴 ★🅱★🅰★🅰★🆃★🅷 ★🅼★🅼★🅱 ★🅱★🅰★🅽★🅰★🅰 ★🅲★🅷★🆄★🅺★🅰 ★🅷★🆄",
        "★🆃★🅤 ★🅲★🅷★🆄★🆃★🅸★🆈★🅰 ★🆃★🅴★🆁★🅰 ★🅺★🅷★🅰★🅽★🅳★🅰★🅰★🅽 ★🅲★🅷★🆄★🆃★🅸★🆈★🅰",
        "★🅰★🆄★🆁 ★🅺★🅸★🆃★🅽★🅰 ★🅱★🅾★🅻★🆄 ★🅱★🅴★🆈 ★🅼★🅰★🅽★🅽 ★🅱★🅷★🅰★🆁 ★🅶★🅰★🆈★🅰 ★🅼★🅴★🆁★🅰",
        "★🆃★🅴★🆁★🅸★🅸★🅸★🅸★🅸 ★🅼★🅰★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃★🆃★🆃 ★🅼★🅴 ★🅰★🅱★🅲★🅳 ★🅻★🅸★🅺★🅷 ★🅳★🆄★🅽★🅶★🅰 ★🅼★🅰★🅰 ★🅺★🅴 ★🅻★🅾★🅳★🅴",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅾 ★🅻★🅴★🅺★🅰★🆁 ★🅼★🅰★🅸 ★🅱★🅰★🆁★🅰★🆁",
        "★🆃★🅴★🆁★🆈 ★🅼★🅰★🅰 ★🆁★🅰★🅽★🅸★🅳★🅸★🅸",
        "★🅲★🅷★🆄★🅿 ★🅱★🅰★🅲★🅷★🅴★🅴 ★🆃★🅼★🅺★🅲",
        "★🆃★🅴★🆁★🆈 ★🅼★🅰★🅺★🅾★🅲★🅷★🅾★🅳★🆄",
        "★🆁★🅰★🅽★🅳★🅸 ★🅼★🅰★🅰 ★🆃★🅴★🆁★🆈",
        "★🆃★🅤 ★🆁★🅰★🅽★🅳★🅸 ★🅺★🅴 ★🅿★🅸★🅻★🅻★🅰 ★🅴★🆈",
        "★🆃★🅴★🆁★🅸★🅸★🅸★🅸 ★🅼★🅰★🅰★🅰 ★🅺★🅾 ★🅱★🅷★🅴★🅹★🅹★🅹",
        "★🆃★🅴★🆁★🅰★🅰 ★🅱★🅰★🅰★🅰★🅿 ★🅷★🆄",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅼★🅴 ★🅷★🅰★🅰★🆃 ★🅳★🅰★🅰★🅻★🅻★🅺★🅴 ★🅱★🅷★🅰★🅰★🅶 ★🅹★🅰★🅰★🅽★🆄★🅶★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅾 ★🅱★🅰★🆁★🅰★🅺 ★🅿★🅴 ★🅻★🅴★??★🅰★🅰 ★🅳★🆄★🅽★🅶★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅾 ★🅶★🅱 ★🆁★🅾★🅰★🅳 ★🅿★🅴 ★🅻★🅴★🅹★🅰★🅺★🅴 ★🅱★🅴★🅲★🅷 ★🅳★🆄★🅽★🅶★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅼★🅴★🅰 ★🅺★🅰★🅰★🅻★🅸 ★🅼★🅸★🆃★🅲★🅷",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅱★🅰★🅱★🆃★🅸 ★🆁★🅰★🅽★🅳★🅸 ★🅷★🅰★🅸",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅼★🅴 ★🅺★🅰★🅱★🆄★🆃★🅰★🆁 ★🅳★🅰★🅰★🅻 ★🅺★🅴 ★🅱★🅾★🆄★🅿 ★🅱★🅰★🅽★🅰★🆄★🅽★🅶★🅰 ★🅼★🅰★??★🅰★🆁★🅲★🅷★🅾★🅳",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅰 ★🆁★🅰★🅽★🅳★🅸 ★🅷★🅰★🅸",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅼★🅴 ★🅳★🅴★🆃★🅾★🅻 ★🅳★🅰★🅰★🅻 ★🅳★🆄★🅽★🅶★🅰 ★🅼★🅰★🅳★🅰★🆁★🅲★🅷★🅾★🅳",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅰★🅰 ★🅱★🅷★🅾★🅱★🅴★🅰★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅼★🅴 ★🅻★🅰★🅿★🆃★🅾★🅿",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🆁★🅰★🅽★🅳★🅸 ★🅷★🅰★🅸",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅾 ★🅱★🅸★🅱★🆃★🅰★🆁 ★🅿★🅴 ★🅻★🅴★🆃★🅰★🅰★🅺★🅴 ★🅲★🅷★🅾★🅳★🆄★🅽★🅶★??",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅾 ★🅰★🅼★🅴★🆁★🅸★🅲★🅰 ★🅶★🅷★🆄★🅼★🅰★🆄★🅽★🅶★🅰 ★🅼★🅰★🅳★🅰★🆁★🅲★🅷★🅾★🅳",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅼★🅴 ★🅽★🅰★🅰★🆁★🅸★🆈★🅰★🅻 ★🅿★🅷★🅾★🆁 ★🅳★🆄★🅽★🅶★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅴 ★🅶★🅰★🅽★🅳 ★🅼★🅴 ★🅳★🅴★🆃★🅾★🅻 ★🅳★🅰★🅰★🅻 ★🅳★🆄★🅽★🅶★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅰 ★🅺★🅾 ★🅷★🅾★🆁★🅻★🅸★🅲★🅺★🅱 ★🅿★🅸★🅻★🅰★🆄★🅽★🅶★🅰 ★🅼★🅰★🅳★🅰★🆁★🅲★🅷★🅾★🅳",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅾 ★🅱★🅰★🆁★🅰★🅺 ★🅿★🅴 ★🅻★🅴★🆃★🅰★🅰★🅰 ★🅳★🆄★🅽★🅶★🅰★🅰★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅰★🅰 ★🅱★🅷★🅾★🅱★🅴★🅰",
        "★🅼★🅴★🆁★🅰★🅰 ★🅻★🆄★🅽★🅳 ★🅿★🅰★🅺★🅰★🅳 ★🅻★🅴 ★🅼★🅰★🅳★🅰★🆁★🅲★🅷★🅾★🅳",
        "★🅲★🅷★🆄★🅿 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅰★🅺★🅰★🅰 ★🅱★🅷★🅾★🅱★🅴★🅰★🅰",
        "★🆃★🅴★🆁★🅸★🅸 ★🅼★🅰★🅰 ★🅲★🅷★🆄★🅱 ★🅶★🅴★🆈★🅸 ★🅺★🆈★🅰★🅰 ★🅻★🅰★🆆★🅳★🅴★🅴★🅴",
        "★🆃★🅴★🆁★🅸★🅸 ★🅼★🅰★🅰 ★🅺★🅰★🅰 ★🅱★🅹★🅱★🅾★🅳★🅰★🅰",
        "★🅼★🅰★🅳★🅰★🆁★🅇★🅷★🅾★🅳★🅳★🅳",
        "★🆃★🅴★🆁★🅸★🆄★🆄★🅸 ★🅼★🅰★🅰★🅰 ★🅺★🅰★🅰 ★🅱★🅷★🅱★🅾★🅳★🅰★🅰",
        "★🆃★🅴★🆁★🅸★🅸★🅸★🅸★🅸 ★🅱★🅴★🅷★🅴★🅽★🅽★🅽 ★🅺★🅾 ★🅲★🅷★🅾★🅳★🅳★🅳★🆄★🆄★🆄★🆄 ★🅼★🅰★🅳★🅰★🆁★🅇★🅷★🅾★🅳★🅳★🅳★🅳",
        "★🆃★🅤 ★🅽★🅸★🅺★🅰★🅻 ★🅼★🅰★🅳★🅰★🆁★🅲★🅷★🅾★🅳",
        "★🅲★🅷★🆄★🅿 ★🆁★🅰★🅽★🅳★🅸 ★🅺★🅴 ★🅱★🅰★🅲★🅷★🅴",
        "★🆃★🅴★🆁★🅰 ★🅼★🅰★🅰 ★🅼★🅴★🆁★🅸 ★🅹★🅰★🅰★🅽 ★🅴★🆈",
        "★🆃★🅴★🆁★🅸 ★🅱★🅰★🅱★🅴★🅽 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅾★🅿",
        "★🅹★🅰★🅻★🅳★🅸 ★🅻★🅸★🅺★🅷 ★🆁★🅽★🅳★🆈★🅺★🅴 ★🅱★🅴★🅹",
        "★🅾★🆁 ★🅱★🅳★🅰 ★🅻★🅸★🅺★🅷",
        "★🅾★🆁 ★🅱★🅳★🅰",
        "★🅾★🆁 ★🅱★🅳★🅰 ★🅾★🆈★🅴",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅰 ★🅱★🆄★🆁",
        "★🅾★🆈★🅴 ★🅺★🅴★🅴★🅳★🅴",
        "★🆁★🅰★🅽★🅳★🅸 ★🅺★🅴 ★🅻★🅰★🅳★🅺★🅴",
        "★🅹★🅰★🅻★🅳★🅸 ★🅻★🅸★🅺★🅷 ★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅲★🅷★🅾★🅳★🆄",
        "★🅼★🅺★🅻 ★🆄★🆃★🅷 ★🆁★🅰★🅽★🅳★🅸 ★🅺★🅴 ★🅱★🅰★🅲★🅲★🅷★🅴",
        "★🆃★🅴★🆁★🅸 ★🅽★🅰★🅽★🅸 ★🅼★🅴★🆁★🅸 ★🅼★🅰★🅰★🅻",
        "★🆃★🅴★🅹 ★🅻★🅸★🅺★🅷 ★🆁★🅰★🅽★🅳★🅲★🅴",
        "★🅾★🆈★🅴 ★🅼★🅰★🅰★🅺★🅴 ★🅻★🅾★🅳★🅴 ★🅼★🆁★🅴★🅽★🅶★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅲★🅷★🅾★🅳★🆈",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅸★🆈★🅰 ★🅺★🅸 ★🅶★🅰★🅽★🅳",
        "★🆃★🅴★🆁★🆈 ★🅳★🅰★🅳★🅸 ★🅺★🅰 ★🅵★🆄★🅳★🅳★🅰",
        "★🅼★🅺★🅻 ★🆄★🆃★🅷 ★🅱★🅴★🅷★🅴★🅽★🅲★🅾★🅳",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅸 ★🅱★🆄★🆁 ★🅳★🅴",
        "★🆃★🅴★🆁★🆈 ★🅼★🅰★🅰 ★🅺★🅰 ★🅵★🆄★🅳★🅳★🅰 ★🅼★🅴 ★🅻★🅰★🆄★🅳★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅲★🅷★🆄★🅳★🆅★🅰",
        "★🆁★🅰★🅽★🅳★🅸 ★🅺★🅴 ★🅱★🅴★🆃★🅴 ★🅼★🅰★🆁 ★🅶★🅰★🆈★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅼★🆁★🆄",
        "★🅹★🅰★🅻★🅸★🅳 ★🅺★🆁 ★🆂★🅿★🅰★🅼",
        "★🅼★🅲 ★🆂★🅿★🅰★🅼 ★🆁★🅾★🅺★🅴★🅽★🅶★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🆂★🅿★🅰★🅼 ★🅺★🆁",
        "★🆂★🅿★🅰★🅼 ★🅺★🆁.★🅼★🅰★🅰★🅺★🅴 ★🅻★🅾★🅳★🅴",
        "★🆁★🅽★🅸★🅳 ★🅺★🅴 ★🅲★🅷★🅾★🅳★🅴 ★🆂★🅿★🅰★🅼 ★🅺★🆁",
        "★🆂★🅿★🅰★🅼 ★🅺★🆁 ★🅺★🅸★🅳",
        "★🅽★🅾★🅾★🅱 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅲★🅷★🅾★🅳★🆄",
        "★🆁★🅽★🅳★🅸 ★🅺★🅴 ★🅱★🅴★🆃★🅴",
        "★🅽★🅾★🅾★🅱 ★🅹★🅰★🅻★🅳★🅸 ★🅻★🅸★🅺★🅷 ★🆆★🆁★🅽★🅰 ★🆃★🅴★🆁★🆈 ★🅼★🅰★🅰 ★🆁★🅰★🅽★🅳",
        "★🅲★🆄★🅳 ★🅶★🅰★🅸 ★🅼★🅰★🅰 ★🆃★🅴★🆁★🆈 ★🅽★🅾★🅾★🅱",
        "★🆄★🆃★🅷 ★🆁★??★🅽★🅳★🆈★🅺★🅴 ★🅽★🅾★🅾★🅱",
        "★🅲★🅷★🅻 ★🅲★🆄★🅳★🅺★🅴 ★🅳★🅸★🅺★🅷★🅰 ★🅽★🅾★🅾★🅱",
        "★🅹★🅻★🅳★🅸 ★🆃★🆈★🅿 ★🅲★🆁 ★🅽★🅾★🅾★🅱 ★🅷★🅰★🅻★🅺★🅴",
        "★🅲★🆄★🅳 ★🅺★🅴 ★🅿★🅶★🅻 ★🅽★🆈 ★🅷★🅾 ★🅽★🅾★🅾★🅱",
        "★🅲★🆄★🅳 ★🅲★🆄★🅳 ★🅺★🅴 ★🆁★🅰★🅽★🅳 ★🅱★🅽★🅹★🅰 ★🆃★🅤 ★🅽★🅾★🅾★🅱",
        "★🅼★🅰★🅺★🅸★🅲★🅷★🆄★🆃 ★🆃★🅴★🆁★🆈 ★🅽★🅾★🅾★🅱",
        "★🅶★🅰★🅽★🅳★🅰 ★🅲★🆈★🆄 ★🅲★🆄★🅳 ★🆁★🅷★🅰 ★🆃★🆄 ?",
        "★🅸★??★🅽★🅰 ★🅶★🅽★🅳★🅰 ★🅽★🆈 ★🅲★🆄★🅳 ★🅰★🅲★🅷★🅴 ★🆂★🅴 ★🅲★🆄★🅳",
        "★🅼★🅰★🅰★🅽 ★🅻★🅴 ★🅲★🆄★🅳 ★🅶★🆈★🅰 ★🆃★🅤 ★🆂★🆄★🅽 ★🅱★🅰★🆃 ★🅰★🅱",
        "★🅼★🅰★🅺★🅰★🅵★🆄★🅳★🅳★🅰 ★🅵★🅰★🆃 ★🅶★🆈★🅰 ★🆃★🅴★🆁★🆈 ★🆁★🆄★🅺",
        
        ]
        gr_texts = [
        """~~~~~ ~~~~~ ~~~~~ ~~~~~
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Pᴀɴɪ Kɪ Tᴀʀᴀʜ Cʜᴏᴅᴀ
        ~~~~~ ~~~~~ ~~~~~ ~~~~~""",
        """████████████████████████████
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴅᴀɪ Kɪ
        ████████████████████████████
        ✦ (🩷) ✦ (❤️) ✦ (🧡) ✦""",
        """☠️☠️☠️☠️☠️☠️☠️☠️☠️☠️☠️☠️
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Zʜᴇʀ Dᴀʟᴀ
        ☠️☠️☠️☠️☠️☠️☠️☠️☠️☠️☠️☠️""",
        """✦━━━━━━━━━━━━━━━━━━━━━━━✦
        🥇 ZA Nᴇ 🥇
        Tᴇʀɪ Mᴀᴀ Kᴏ Gᴏʟᴅ Cʜᴜᴅᴀɪ Dɪ
        ✦━━━━━━━━━━━━━━━━━━━━━━━✦""",
        """🗑️━━━━━━━━━━━━━━━━━🗑️
        ║  ZA Nᴇ  ║
        ║  Tᴇʀɪ Mᴀᴀ Kᴏ Kᴀᴄʀᴀ Bɴᴀʏᴀ ║
        🗑️━━━━━━━━━━━━━━━━━🗑️""",
        """☢️☢️☢️☢️☢️☢️☢️☢️☢️☢️
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴀ Bᴏsᴅᴀ Kʜᴏʟ Dɪʏᴀ
        ☢️☢️☢️☢️☢️☢️☢️☢️☢️☢️""",
        """🚀 Sᴘᴀᴄᴇ Mɪssɪᴏɴ: ZA
        👨‍🚀 Cᴏᴍᴍᴀɴᴅᴇʀ: ZA
        🌍 Tᴀʀɢᴇᴛ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        🌟 Mɪssɪᴏɴ: Cʜᴏᴅ ᴀɴᴅ Dᴇsᴛʀᴏʏ""",
        """⏰ Tɪᴍᴇ: 3:00 AM
        📍 Lᴏᴄᴀᴛɪᴏɴ: Tᴇʀɪ Mᴀᴀ Kᴇ Bʜᴏsᴅᴇ Mᴇ
        👨 ZA Iɴ Aᴄᴛɪᴏɴ
        🎬 Lɪᴠᴇ Sᴛʀᴇᴀᴍɪɴɢ...""",
        """🌧️ Mᴀᴜsᴀᴍ: Bᴀʀɪsʜ
        🌊 Lᴇᴠᴇʟ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Bᴀᴅʜ
        ⚡ ZA Nᴇ Bᴀɴᴅʜ Tᴏᴅᴀ""",
        """📰 Bʀᴇᴀᴋɪɴɢ Nᴇᴡs!
        🗞️ ZA Nᴇ Cʜᴏᴅᴀ
        👑 Tʀᴇɴᴅɪɴɢ #1 Oɴ Tᴇʟᴇɢʀᴀᴍ
        ⭐ ZA""",
        """🎬 Mᴏᴠɪᴇ: ZA
        🎭 Sᴛᴀʀʀɪɴɢ: ZA
        🎟️ Rᴀᴛɪɴɢ: ⭐⭐⭐⭐⭐
        🍿 Bᴏx Oғғɪᴄᴇ: Tᴇʀɪ Mᴀᴀ""",
        """🎮 Gᴀᴍᴇ: ZA
        👾 Pʟᴀʏᴇʀ: ZA
        🏆 Lᴇᴠᴇʟ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        💀 Sᴄᴏʀᴇ: Iɴғɪɴɪᴛʏ""",
        """📋 Mᴇɴᴜ Cᴀʀᴅ:
        🍽️ Mᴀɪɴ Cᴏᴜʀsᴇ: Tᴇʀɪ Mᴀᴀ
        🍜 Sɪᴅᴇ Dɪsʜ: Tᴇʀɪ Bʜᴇɴ
        🍰 Dᴇssᴇʀᴛ: ZA Kᴀ Lᴜɴᴅ
        💵 Pʀɪᴄᴇ: Fʀᴇᴇ Cʜᴜᴅᴀɪ""",
        """🗺️ Nᴀᴠɪɢᴀᴛɪᴏɴ:
        Sᴛᴀʀᴛ: ZA
        Dᴇsᴛɪɴᴀᴛɪᴏɴ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        Dɪsᴛᴀɴᴄᴇ: 0 Mᴇᴛᴇʀs
        ETA: Aʙʜɪ Cʜᴏᴅ Rʜᴀ Hᴜ""",
        """🎵 Nᴏᴡ Pʟᴀʏɪɴɢ:
        🎶 Tʀᴀᴄᴋ: ZA
        🎤 Aʀᴛɪsᴛ: ZA
        💿 Aʟʙᴜᴍ: ZA Sᴇʀɪᴇs
        🔥 Vɪᴇᴡs: 69M""",
        """🏏 Mᴀᴛᴄʜ: ZA Vs Tᴇʀɪ Mᴀᴀ
        🏆 Wɪɴɴᴇʀ: ZA
        📊 Sᴄᴏʀᴇ: Cʜᴏᴅ ᴏᴜᴛ
        🔥 Mᴀɴ ᴏғ ᴛʜᴇ Mᴀᴛᴄʜ: Lᴜɴᴅ""",
        """🏥 Rᴇᴘᴏʀᴛ:
        Dᴏᴄᴛᴏʀ: ZA
        Pᴀᴛɪᴇɴᴛ: Tᴇʀɪ Mᴀᴀ
        Dɪᴀɢɴᴏsɪs: Cʜᴜᴛ Mᴇ Lᴜɴᴅ
        Tʀᴇᴀᴛᴍᴇɴᴛ: Cʜᴏᴅɴᴀ""",
        """🏫 Sᴄʜᴏᴏʟ: ZA Aᴄᴀᴅᴇᴍʏ
        📚 Sᴜʙᴊᴇᴄᴛ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴅᴀɪ 101
        👨‍🏫 Tᴇᴀᴄʜᴇʀ: ZA
        ✅ Cʟᴀss: Iɴ Sᴇssɪᴏɴ""",
        """🛒 Sʜᴏᴘᴘɪɴɢ Cᴀʀᴛ:
        🛍️ Iᴛᴇᴍ: Tᴇʀɪ Mᴀᴀ
        💰 Pʀɪᴄᴇ: Fʀᴇᴇ
        🛒 Bᴏᴜɢʜᴛ Bʏ: ZA
        📦 Sᴛᴀᴛᴜs: Cʜᴏᴅ Dɪʏᴀ""",
        """🏨 Hᴏᴛᴇʟ: ZA Pᴀʟᴀᴄᴇ
        🛏️ Rᴏᴏᴍ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        👤 Gᴜᴇsᴛ: ZA
        ⭐ Rᴀᴛɪɴɢ: 5 Sᴛᴀʀs""",
        """✈️ Fʟɪɢʜᴛ: ZA 101
        🛫 Dᴇᴘᴀʀᴛᴜʀᴇ: ZA
        🛬 Aʀʀɪᴠᴀʟ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        ⏰ Tɪᴍᴇ: Nᴏᴡ""",
        """🚂 Tʀᴀɪɴ: ZA Exᴘʀᴇss
        🚉 Sᴛᴀᴛɪᴏɴ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        👨‍✈️ Dʀɪᴠᴇʀ: ZA
        🕒 Tɪᴍɪɴɢ: 24x7""",
        """🍕 Rᴇsᴛᴀᴜʀᴀɴᴛ: ZA Bᴀᴢᴀᴀʀ
        🍽️ Sᴘᴇᴄɪᴀʟ: Tᴇʀɪ Mᴀᴀ
        👨‍🍳 Cʜᴇғ: ZA
        🍴 Oʀᴅᴇʀ: Cʜᴏᴅ ᴀɴᴅ Gᴏ""",
        """💪 Gʏᴍ: ZA Fɪᴛɴᴇss
        🏋️ Tʀᴀɪɴᴇʀ: ZA
        🎯 Tᴀʀɢᴇᴛ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        ✅ Rᴇsᴜʟᴛ: Pʜᴏᴏʟ Cʜᴏᴅ""",
        """🎉 Pᴀʀᴛʏ: ZA Nɪɢʜᴛ
        🕺 Hᴏsᴛ: ZA
        💃 Gᴜᴇsᴛ: Tᴇʀɪ Mᴀᴀ
        🎵 Sᴏɴɢ: Cʜᴏᴅ Tʜᴇ Fʟᴏᴏʀ""",
        """🏛️ Mᴜsᴇᴜᴍ: ZA Hɪsᴛᴏʀʏ
        🖼️ Exʜɪʙɪᴛ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        🎨 Aʀᴛɪsᴛ: ZA
        📅 Dᴀᴛᴇ: Hᴀʀ Rᴏᴢ""",
        """🦁 Zᴏᴏ: ZA Wᴏʀʟᴅ
        🐯 Mᴀɪɴ Aᴛᴛʀᴀᴄᴛɪᴏɴ: Tᴇʀɪ Mᴀᴀ
        🐺 Kᴇᴇᴘᴇʀ: ZA
        🔥 Sʜᴏᴡ: Cʜᴏᴅᴜɴɢᴀ""",
        """🎪 Cɪʀᴄᴜs: ZA Mᴀsᴛɪ
        🤡 Cʟᴏᴡɴ: ZA
        🎪 Sʜᴏᴡ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴅᴀɪ
        🎟️ Tɪᴄᴋᴇᴛ: Fʀᴇᴇ""",
        """📚 Lɪʙʀᴀʀʏ: ZA Bᴏᴏᴋs
        📖 Bᴏᴏᴋ: ZA
        ✍️ Aᴜᴛʜᴏʀ: ZA
        📕 Cʜᴀᴘᴛᴇʀ: Cʜᴏᴅɴᴀ""",
        """🌸 Gᴀʀᴅᴇɴ: ZA Fʟᴏᴡᴇʀs
        🌹 Mᴀɪɴ Fʟᴏᴡᴇʀ: Tᴇʀɪ Mᴀᴀ
        🌻 Gᴀʀᴅᴇɴᴇʀ: ZA
        💧 Wᴀᴛᴇʀ: Lᴜɴᴅ Kᴀ Pᴀɴɪ""",
        """🏖️ Bᴇᴀᴄʜ: ZA Sʜᴏʀᴇ
        🌊 Wᴀᴠᴇs: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        🏄 Sᴜʀғᴇʀ: ZA
        🌅 Tɪᴍᴇ: Sᴜɴsᴇᴛ Cʜᴏᴅ""",
        """☕ Cᴏғғᴇᴇ Sʜᴏᴘ: ZA Cᴀғᴇ
        🍵 Sᴘᴇᴄɪᴀʟ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        👨‍🍳 Bᴀʀɪsᴛᴀ: ZA
        💦 Aᴅᴅɪᴛɪᴏɴ: Lᴜɴᴅ Kᴀ Cʀᴇᴀᴍ""",
        """🎰 Cᴀsɪɴᴏ: ZA Pᴀʟᴀᴄᴇ
        🃏 Gᴀᴍᴇ: Cʜᴏᴅ Tʜᴇ ZA
        🎲 Bᴇᴛ: Tᴇʀɪ Mᴀᴀ
        💰 Wɪɴɴᴇʀ: ZA""",
        """🌙 Nɪɢʜᴛ Sʜᴏᴡ:
        🌚 Mᴀɪɴ Aᴛᴛʀᴀᴄᴛɪᴏɴ: Tᴇʀɪ Mᴀᴀ
        🌟 Hᴏsᴛ: ZA
        💫 Pᴇʀғᴏʀᴍᴀɴᴄᴇ: Cʜᴏᴅɴᴀ""",
        """🌋🌋🌋🌋🌋🌋🌋🌋
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Jᴡᴀʟᴀ Pʜᴏᴅɪ
        🌋🌋🌋🌋🌋🌋🌋🌋""",
        """🌊🌊🌊🌊🌊🌊🌊🌊
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Tᴏᴏғᴀɴ Lᴀʏᴀ
        🌊🌊🌊🌊🌊🌊🌊🌊""",
        """🌀🌀🌀🌀🌀🌀🌀🌀
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Bʜᴜᴄʜᴀʟ Lᴀʏɪ
        🌀🌀🌀🌀🌀🌀🌀🌀""",
        """💻💻💻💻💻💻💻💻
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Cʏʙᴇʀ Cʜᴏᴅᴀ
        💻💻💻💻💻💻💻💻""",
        """🤖🤖🤖🤖🤖🤖🤖🤖
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Rᴏʙᴏᴛ Sᴛʏʟᴇ Mᴇ Cʜᴏᴅᴀ
        🤖🤖🤖🤖🤖🤖🤖🤖""",
        """👽👽👽👽👽👽👽👽
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Aʟɪᴇɴ Gʜᴜsᴀʏᴀ
        👽👽👽👽👽👽👽👽""",
        """🐉🔥🐉🔥🐉🔥🐉🔥
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Dʀᴀɢᴏɴ Sᴛʏʟᴇ Mᴇ Cʜᴏᴅᴀ
        🐉🔥🐉🔥🐉🔥🐉🔥""",
        """⚡🔨⚡🔨⚡🔨⚡🔨
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Tʜᴏʀ Kᴀ Hᴀᴍᴍᴇʀ Mᴀʀᴀ
        ⚡🔨⚡🔨⚡🔨⚡🔨""",
        """🦾💥🦾💥🦾💥🦾💥
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Iʀᴏɴ Mᴀɴ Sᴛʏʟᴇ Mᴇ Cʜᴏᴅᴀ
        🦾💥🦾💥🦾💥🦾💥""",
        """💚💢💚💢💚💢💚💢
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Hᴜʟᴋ Sᴛʏʟᴇ Mᴇ Sᴍᴀsʜ Kɪʏᴀ
        💚💢💚💢💚💢💚💢""",
        """🕷️🕸️🕷️🕸️🕷️🕸️🕷️🕸️
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Sᴘɪᴅᴇʀ Wᴇʙ Bɴᴀʏᴀ
        🕷️🕸️🕷️🕸️🕷️🕸️🕷️🕸️""",
        """🦇🌙🦇🌙🦇🌙🦇🌙
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Bᴀᴛᴍᴀɴ Sᴛʏʟᴇ Mᴇ Cʜᴏᴅᴀ
        🦇🌙🦇🌙🦇🌙🦇🌙""",
        """🦸💫🦸💫🦸💫🦸💫
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Sᴜᴘᴇʀᴍᴀɴ Sᴛʏʟᴇ Mᴇ Uᴅᴀʏᴀ
        🦸💫🦸💫🦸💫🦸💫""",
        """🗡️💢🗡️💢🗡️💢🗡️💢
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Wᴏʟᴠᴇʀɪɴᴇ Cʟᴀᴡs Mᴀʀᴇ
        🗡️💢🗡️💢🗡️💢🗡️💢""",
        """🔥💀🔥💀🔥💀🔥💀
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Gʜᴏsᴛ Rɪᴅᴇʀ Gʜᴜsᴀʏᴀ
        🔥💀🔥💀🔥💀🔥💀""",
        """💀🔫💀🔫💀🔫💀🔫
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Pᴜɴɪsʜᴇʀ Dᴀʟᴀ
        💀🔫💀🔫💀🔫💀🔫""",
        """🦸🔫🦸🔫🦸🔫🦸🔫
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Dᴇᴀᴅᴘᴏᴏʟ Sᴛʏʟᴇ Mᴇ Cʜᴏᴅᴀ
        🦸🔫🦸🔫🦸🔫🦸🔫""",
        """🖤👅🖤👅🖤👅🖤👅
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Vᴇɴᴏᴍ Gʜᴜsᴀʏᴀ
        🖤👅🖤👅🖤👅🖤👅""",
        """🃏💚🃏💚🃏💚🃏💚
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Jᴏᴋᴇʀ Kʜᴇʟᴀ
        🃏💚🃏💚🃏💚🃏💚""",
        """💕🔨💕🔨💕🔨💕🔨
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Hᴀʀʟᴇʏ Sᴛʏʟᴇ Mᴇ Cʜᴏᴅᴀ
        💕🔨💕🔨💕🔨💕🔨""",
        """⚡💨⚡💨⚡💨⚡💨
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Fʟᴀsʜ Sᴘᴇᴇᴅ Dɪ
        ⚡💨⚡💨⚡💨⚡💨""",
        """🌊🔱🌊🔱🌊🔱🌊🔱
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Aǫᴜᴀᴍᴀɴ Gʜᴜsᴀʏᴀ
        🌊🔱🌊🔱🌊🔱🌊🔱""",
        """👁️💥👁️💥👁️💥👁️💥
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Cʏᴄʟᴏᴘs Bᴇᴀᴍ Mᴀʀᴀ
        👁️💥👁️💥👁️💥👁️💥""",
        """🧲💢🧲💢🧲💢🧲💢
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Mᴀɢɴᴇᴛᴏ Gʜᴜsᴀʏᴀ
        🧲💢🧲💢🧲💢🧲💢""",
        """🌩️⚡🌩️⚡🌩️⚡🌩️⚡
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Sᴛᴏʀᴍ Lᴀʏᴀ
        🌩️⚡🌩️⚡🌩️⚡🌩️⚡""",
        """💋💢💋💢💋💢💋💢
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Rᴏɢᴜᴇ Kɪss Dɪ
        💋💢💋💢💋💢💋💢""",
        """🃏🔥🃏🔥🃏🔥🃏🔥
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Gᴀᴍʙɪᴛ Cᴀʀᴅs Dᴀʟᴇ
        🃏🔥🃏🔥🃏🔥🃏🔥""",
        """💨🌀💨🌀💨🌀💨🌀
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Nɪɢʜᴛᴄʀᴀᴡʟᴇʀ Gʜᴜsᴀʏᴀ
        💨🌀💨🌀💨🌀💨🌀""",
        """💙🌀💙🌀💙🌀💙🌀
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Mʏsᴛɪǫᴜᴇ Gʜᴜsᴀʏᴀ
        💙🌀💙🌀💙🌀💙🌀""",
        """🐾💢🐾💢🐾💢🐾💢
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Bᴇᴀsᴛ Gʜᴜsᴀʏᴀ
        🐾💢🐾💢🐾💢🐾💢""",
        """❄️🧊❄️🧊❄️🧊❄️🧊
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Iᴄᴇᴍᴀɴ Gʜᴜsᴀʏᴀ
        ❄️🧊❄️🧊❄️🧊❄️🧊""",
        """🔥💥🔥💥🔥💥🔥💥
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Pʏʀᴏ Gʜᴜsᴀʏᴀ
        🔥💥🔥💥🔥💥🔥💥""",
        """🌑🌀🌑🌀🌑🌀🌑🌀
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Sʜᴀᴅᴏᴡ Gʜᴜsᴀʏᴀ
        🌑🌀🌑🌀🌑🌀🌑🌀""",
        """🔥🦅🔥🦅🔥🦅🔥🦅
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Pʜᴏᴇɴɪx Fɪʀᴇ Dᴀʟɪ
        🔥🦅🔥🦅🔥🦅🔥🦅""",
        """🍔🍔🍔🍔🍔🍔🍔🍔🍔
        ??   😋   🍔
        🍔  🧀   🍔
        🍔  🥩   🍔
        🍔🍔🍔🍔🍔🍔🍔🍔🍔
        
        Tᴇʀɪ Mᴀᴀ Kᴏ Bᴜʀɢᴇʀ Bɴᴀᴋᴇ Kʜᴀʏᴀ""",
        """🍕🍕🍕🍕🍕🍕🍕🍕
        🍕  🍅  🍕
        🍕  🧀  🍕
        🍕  🍕  🍕
        🍕🍕🍕🍕🍕🍕🍕🍕
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Pɪᴢᴢᴀ Dᴀʟᴀ""",
        """🌮🌮🌮🌮🌮🌮🌮🌮
        🌮  😋  🌮
        🌮  🥩  🌮
        🌮  🌮  🌮
        🌮🌮🌮🌮🌮🌮🌮🌮
        
        Tᴇʀɪ Mᴀᴀ Kᴏ Tᴀᴄᴏ Sᴛʏʟᴇ Mᴇ Cʜᴏᴅᴀ""",
        """🍩🍩🍩🍩🍩🍩🍩🍩
        🍩  😋  🍩
        🍩  🍩  🍩
        🍩  🍩  🍩
        🍩🍩🍩🍩🍩🍩🍩🍩
        
        Tᴇʀɪ Mᴀᴀ Kᴏ Dᴏɴᴜᴛ Bɴᴀᴋᴇ Cʜᴏᴅᴀ""",
        """☕☕☕☕☕☕☕☕
        ☕  😋  ☕
        ☕  ☕  ☕
        ☕  ☕  ☕
        ☕☕☕☕☕☕☕☕
        
        Tᴇʀɪ Mᴀᴀ Kᴏ Cᴏғғᴇᴇ Sᴛʏʟᴇ Mᴇ Cʜᴏᴅᴀ""",
        """👑👑👑👑👑👑👑👑
        👑  😎  👑
        👑  👑  👑
        👑  👑  👑
        👑👑👑👑👑👑👑👑
        
        ZA Nᴇ Tᴇʀɪ Mᴀᴀ Kᴏ Cʜᴏᴅᴀ""",
        """💖💖💖💖💖💖💖💖
        💖  😍  💖
        💖  💖  💖
        💖  💖  💖
        💖💖💖💖💖💖💖💖
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Pʏᴀʀ""",
        """💀💀💀💀💀💀💀💀
        💀  😈  💀
        💀  💀  💀
        💀  💀  💀
        💀💀💀💀💀💀💀💀
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴀʀ Gᴀʏɪ""",
        """🔥🔥🔥🔥🔥🔥🔥🔥
        🔥  😈  🔥
        🔥  🔥  🔥
        🔥  🔥  🔥
        🔥🔥🔥🔥🔥🔥🔥🔥
        
        ZA Nᴇ Aᴀɢ Lɢᴀʏɪ""",
        """👻👻👻👻👻👻👻👻
        👻  😱  👻
        👻  👻  👻
        👻  👻  👻
        👻👻👻👻👻👻👻👻
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Gʜᴏsᴛ""",
        """🌈🌈🌈🌈🌈🌈🌈🌈
        🌈  😋  🌈
        🌈  🌈  🌈
        🌈  🌈  🌈
        🌈🌈🌈🌈🌈🌈🌈🌈
        
        Tᴇʀɪ Mᴀᴀ Kᴏ Rᴀɪɴʙᴏᴡ Sᴛʏʟᴇ Mᴇ Cʜᴏᴅᴀ""",
        """💣➖💣➖➖💣➖💣
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🔥             ✨
        /    \\
        💥    💥 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Bᴏᴍʙ Pʜᴏᴅᴜɴɢᴀ""",
        """☢️➖☢️➖➖☢️➖☢️
        🌟        \\         /          🌟
        ⭐️          \\☠️/            ⭐️
        ✨           💀             ✨
        /    \\
        🦴    🦴 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Nᴜᴄʟᴇᴀʀ Aᴛᴛᴀᴄᴋ""",
        """🐉➖🐉➖➖🐉➖🐉
        🌟        \\         /          🌟
        ⭐️          \\🔥/            ⭐️
        ✨           🐲             ✨
        /    \\
        🔥    🔥 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Dʀᴀɢᴏɴ Gʜᴜsᴀʏᴀ""",
        """👿➖👿➖➖👿➖👿
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           👹             ✨
        /    \\
        🔱    🔱 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Dᴇᴍᴏɴ Gʜᴜsᴀʏᴀ""",
        """💀➖💀➖➖💀➖💀
        🌟        \\         /          🌟
        ⭐️          \\☠️/            ⭐️
        ✨           💀             ✨
        /    \\
        🦴    🦴 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴀʀ Gᴀʏɪ""",
        """🔫➖🔫➖➖🔫➖🔫
        🌟        \\         /          🌟
        ⭐️          \\😎/            ⭐️
        ✨           🎯             ✨
        /    \\
        💥    💥 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Tᴀɴᴋ Gʜᴜsᴀʏᴀ""",
        """⚔️➖⚔️➖➖⚔️➖⚔️
        🌟        \\         /          🌟
        ⭐️          \\🗡️/            ⭐️
        ✨           ⚔️             ✨
        /    \\
        🩸    🩸 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Sᴡᴏʀᴅ Gʜᴜsᴀʏᴀ""",
        """🐍➖🐍➖➖🐍➖🐍
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🐍             ✨
        /    \\
        ☠️    ☠️ 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Vɪᴘᴇʀ Gʜᴜsᴀʏᴀ""",
        """🦂➖🦂➖➖🦂➖🦂
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🦂             ✨
        /    \\
        ☠️    ☠️ 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Sᴄᴏʀᴘɪᴏɴ Gʜᴜsᴀʏᴀ""",
        """🐦‍⬛➖🐦‍⬛➖➖🐦‍⬛➖🐦‍⬛
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🖤             ✨
        /    \\
        🪶    🪶 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Rᴀᴠᴇɴ Gʜᴜsᴀʏᴀ""",
        """🐺➖🐺➖➖🐺➖🐺
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🐺             ✨
        /    \\
        🩸    🩸 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Wᴏʟғ Gʜᴜsᴀʏᴀ""",
        """🔥➖🔥➖➖🔥➖🔥
        🌟        \\         /          🌟
        ⭐️          \\🦅/            ⭐️
        ✨           🔥             ✨
        /    \\
        💫    💫 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Pʜᴏᴇɴɪx Gʜᴜsᴀʏᴀ""",
        """🦁➖🦁➖➖🦁➖🦁
        🌟        \\         /          🌟
        ⭐️          \\👑/            ⭐️
        ✨           🦁             ✨
        /    \\
        🩸    🩸 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Lɪᴏɴ Gʜᴜsᴀʏᴀ""",
        """🐯➖🐯➖➖🐯➖🐯
        🌟        \\         /          🌟
        ⭐️          \\🐅/            ⭐️
        ✨           🐯             ✨
        /    \\
        🩸    🩸 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Tɪɢᴇʀ Gʜᴜsᴀʏᴀ""",
        """🦈➖🦈➖➖🦈➖🦈
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🦈             ✨
        /    \\
        🩸    🩸 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Sʜᴀʀᴋ Gʜᴜsᴀʏᴀ""",
        """🦅➖🦅➖➖🦅➖🦅
        🌟        \\         /          🌟
        ⭐️          \\🦅/            ⭐️
        ✨           🦅             ✨
        /    \\
        🪶    🪶 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Eᴀɢʟᴇ Gʜᴜsᴀʏᴀ""",
        """🐂➖🐂➖➖🐂➖🐂
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🐂             ✨
        /    \\
        💥    💥 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Bᴜʟʟ Gʜᴜsᴀʏᴀ""",
        """🦏➖🦏➖➖🦏➖🦏
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🦏             ✨
        /    \\
        💥    💥 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Rʜɪɴᴏ Gʜᴜsᴀʏᴀ""",
        """🐘➖🐘➖➖🐘➖🐘
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🐘             ✨
        /    \\
        💥    💥 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Eʟᴇᴘʜᴀɴᴛ Gʜᴜsᴀʏᴀ""",
        """🦛➖🦛➖➖🦛➖🦛
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🦛             ✨
        /    \\
        💥    💥 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Hɪᴘᴘᴏ Gʜᴜsᴀʏᴀ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  💣  💣  █  █  █
        █  █  █  💣  💣  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Bᴏᴍʙ Pʜᴏᴅᴜɴɢᴀ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  💀  💀  █  █  █
        █  █  █  💀  💀  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴀʀ Gᴀʏɪ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  ☢️  ☢️  █  █  █
        █  █  █  ☢️  ☢️  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Nᴜᴄʟᴇᴀʀ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  🐉  🐉  █  █  █
        █  █  █  🐉  🐉  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Dʀᴀɢᴏɴ Gʜᴜsᴀʏᴀ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  🔫  🔫  █  █  █
        █  █  █  🔫  🔫  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Tᴀɴᴋ Gʜᴜsᴀʏᴀ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  🐍  🐍  █  █  █
        █  █  █  🐍  🐍  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Sᴀᴀᴘ Gʜᴜsᴀʏᴀ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  👿  👿  █  █  █
        █  █  █  👿  👿  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Dᴇᴍᴏɴ Gʜᴜsᴀʏᴀ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  🦈  🦈  █  █  █
        █  █  █  🦈  🦈  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Sʜᴀʀᴋ Gʜᴜsᴀʏᴀ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  🦂  🦂  █  █  █
        █  █  █  🦂  🦂  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Bɪᴄʜʜᴜ Gʜᴜsᴀʏᴀ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  👻  👻  █  █  █
        █  █  █  👻  👻  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Bʜᴏᴏᴛ Gʜᴜsᴀʏᴀ""",
        ]

        # ─── PREMIUM SPAM TEXT LISTS ──────────────────────────────────────────
        ms_texts = [
        "TTTTTTT🍷EEEEEE💊RRRRR🔘OOOOO🎲BBBBB🤍EEEEEE💊GGGGGG🖤EEEEEE💊JJJJJJ👅 CCCCCC⚔️OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 CCCCCC⚔️OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE💊OOOOO🎲 AAAAAA👿AAAAAA👿AAAAAA👿MMMMM🚀MMMMM🚀AAAAAA👿 CCCCCC⚔️OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘OOOOO🎲 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 LLLLLL🔨AAAAAA👿 BBBBB🤍UUUUU💣RRRRR🔘",
        "OOOOOO👅YYYYYYEEEEEE💊 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 KKKKKK💜EEEEEE💊 BBBBB🤍AAAAAA👿CCCCCC⚔️CCCCCC⚔️EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜 BBBBB🤍JJJJJJ👅OOOOO🎲SSSSS⚒️RRRRR🔘WWWWW🥰",
        "TTTTTTT🍷EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜 FFFFFF🔥AAAAAA👿NNNNNN🤣RRRRR🔘",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀UUUUU💣MMMMM🚀MMMMM🚀YYYYYY",
        "RRRRRR⚔️AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷RRRRR🔘",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿KKKKKK💜IIIIII🍷 GGGGGG🖤EEEEEE💊TTTTT🚭IIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜EEEEEE💊 MMMMM🚀UUUUU💣HHHHH🖤",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜OOOOO🎲 GGGGGG🖤AAAAAA👿NNNNNN🤣DDDDD👿",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 CCCCCC⚔️HHHHH🖤IIIIII🍷NNNNNN🤣AAAAAA👿LLLLLL🔨",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 MMMMM🚀AAAAAA👿RRRRR🔘 GGGGGG🖤AAAAAA👿YYYYYYIIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀UUUUU💣TTTTT🚭IIIIII🍷 RRRRR🔘AAAAAA👿DDDDD👿IIIIII🍷 KKKKKK💜IIIIII🍷 HHHHH🖤EEEEEE💊TTTTT🚭",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 CCCCCC⚔️OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿IIIIII🍷YYYYYYAAAAAA👿 CCCCCC⚔️IIIIII🍷OOOOO🎲DDDDD👿AAAAAA👿 AAAAAA👿AAAAAA👿AAAAAA👿AAAAAA👿KKKKKK💜 MMMMM🚀",
        "OOOOOO👅YYYYYYEEEEEE💊 KKKKKK💜IIIIII🍷NNNNNN🤣NNNNNN🤣AAAAAA👿RRRRR🔘 KKKKKK💜EEEEEE💊 BBBBB🤍AAAAAA??CCCCCC⚔️CCCCCC⚔️GGGGGG🖤EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII?? MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜AAAAAA👿 BBBBB🤍IIIIII🍷OOOOO🎲AAAAAA👿RRRRR🔘SSSSS⚒️",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜OOOOO🎲 GGGGGG🖤AAAAAA👿NNNNNN🤣DDDDD👿 MMMMM🚀AAAAAA👿RRRRR🔘AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿OOOOO🎲UUUUU💣AAAAAA👿 JJJJJJ👅AAAAAA👿AAAAAA👿NNNNNN🤣 CCCCCC⚔️JJJJJJ👅OOOOO🎲DDDDD👿YYYYYYAAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜EEEEEE💊 BBBBB🤍HHHHH🖤OOOOO🎲AAAAAA👿DDDDD👿AAAAAA👿 CCCCCC⚔️OOOOO🎲DDDDD👿AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜OOOOO🎲 CCCCCC⚔️HHHHH🖤UUUUU💣TTTTT??EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿.    KKKKKK📌AAAAAA👿AAAAAA👿 BBBBB🤍HHHHH🖤OOOOO🎲SSSSS⚒️DDDDD👿AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍RRRRR🔘HHHHH🖤EEEEEE💊NNNNNN🤣 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀UUUUU💣MMMMM🚀MMMMM🚀YYYYYY KKKKKK💜UUUUU💣TTTTT🚭IIIIII🍷YYYYYYAAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍AAAAAA👿HHHHH🖤IIIIII🍷 KKKKKK💜AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜AAAAAA👿 BBBBB🤍UUUUU💣RRRRR🔘",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 CCCCCC⚔️GGGGGG🖤OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿IIIIII🍷YYYYYYAAAAAA👿 CCCCCC⚔️GGGGGG🖤OOOOO🎲DDDDD👿UUUUU💣",
        "OOOOOO??YYYYYYEEEEEE💊 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 KKKKKK💜EEEEEE💊 BBBBB🤍AAAAAA👿CCCCCC⚔️CCCCCC⚔️HHHHH🖤EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜IIIIII🍷 CCCCCC⚔️HHHHH🖤UUUUU💣CCCCCC⚔️HHHHH🖤OOOOO🎲 KKKKKK💜AAAAAA👿TTTTT🚭YYYYYY",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍AAAAAA👿HHHHH🖤IIIIII🍷 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿IIIIII🍷YYYYYYAAAAAA👿 CCCCCC⚔️GGGGGG🖤OOOOO🎲DDDDD👿YYYYYY",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀UUUUU💣MMMMM🚀MMMMM🚀YYYYYY RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀UUUUU💣MMMMM🚀YYYYYY CCCCCC⚔️HHHHH🖤OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍AAAAAA👿JJJJJJ👅IIIIII🍷 CCCCCC⚔️HHHHH🖤OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 KKKKKK💜IIIIII🍷 LLLLLL🔨AAAAAA👿DDDDD👿KKKKKK💜IIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿IIIIII🍷YYYYYYAAAAAA👿 JJJJJJ👅AAAAAA👿AAAAAA👿NNNNNN🤣 CCCCCC⚔️HHHHH🖤OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE??RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜AAAAAA👿 BBBBB🤍UUUUU💣RRRRR🔘 FFFFFF🔥AAAAAA👿DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 BBBBB🤍AAAAAA👿NNNNNN🤣AAAAAA👿 DDDDD👿UUUUU💣NNNNNN🤣GGGGGG🖤AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 CCCCCC⚔️HHHHH🖤OOOOO🎲DDDDD👿KKKKKK💜EEEEEE💊 FFFFFF🔥EEEEEE💊KKKKKK💜UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜EEEEEE💊 MMMMM🚀UUUUU💣HHHHH🖤 MMMMM🚀EEEEEE💊IIIIII🍷 PPPPPP📌AAAAAA👿KKKKKK💜IIIIII🍷SSSSS⚒️TTTTT🚭AAAAAA👿NNNNNN🤣IIIIII🍷 LLLLLL🔨AAAAAA👿VVVVDDDDD👿AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 PPPPPP📌KKKKKK💜AAAAAA👿OOOOO🎲SSSSS⚒️TTTTT🚭AAAAAA👿NNNNNN🤣IIIIII🍷 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷",
        "RRRRRR⚔️AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 KKKKKK💜EEEEEE💊 BBBBB🤍EEEEEE💊TTTTT🚭",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘UUUUU💣 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜AAAAAA👿 BBBBB🤍UUUUU💣TTTTT🚭",
        "OOOOOO👅YYYYYYEEEEEE💊 TTTTT🚭AAAAAA👿TTTTT🚭TTTTT🚭TTTTT🚭EEEEEE💊 UUUUU💣TTTTT🚭HHHHH🖤",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 CCCCCC⚔️HHHHH🖤UUUUU💣DDDDD👿VVVVAAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀UUUUU💣MMMMM🚀MMMMM🚀YYYYYY CCCCCC⚔️HHHHH🖤UUUUU💣DDDDD👿VVVVAAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 CCCCCC⚔️UUUUU💣UUUUU💣DDDDD👿VVVVAAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿IIIIII🍷YYYYYYAAAAAA👿 KKKKKK💜AAAAAA👿 BBBBB🤍HHHHH🖤OOOOO🎲SSSSS⚒️DDDDD👿AAAAAA👿 DDDDD👿EEEEEE💊DDDDD👿EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘OOOOO🎲 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 KKKKKK💜OOOOO🎲 GGGGGG🖤AAAAAA👿NNNNNN🤣DDDDD👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 KKKKKK💜EEEEEE💊 BBBBB🤍HHHHH🖤OOOOO🎲SSSSS⚒️DDDDD👿EEEEEE💊 PPPPPP📌EEEEEE💊 LLLLLL🔨OOOOO🎲LLLLLL🔨LLLLLL🔨AAAAAA👿",
        "LLLLLLL🎲OOOOO🎲LLLLLL🔨LLLLLL🔨EEEEEE💊 HHHHH🖤OOOOO🎲 LLLLLL🔨OOOOO🎲LLLLLL🔨LLLLLL🔨EEEEEE💊 TTTTT🚭EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜OOOOO🎲 GGGGGG🖤AAAAAA👿NNNNNN🤣DDDDD👿 PPPPPP📌EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 DDDDD👿EEEEEE💊 MMMMM🚀UUUUU💣JJJJJJ👅GGGGGG🖤EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀UUUUU💣MMMMM🚀YYYYYY CCCCCC⚔️HHHHH🖤UUUUU💣DDDDD👿AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜 BBBBB🤍UUUUU💣RRRRR🔘 CCCCCC⚔️HHHHH🖤UUUUU💣DDDDD👿VVVVAAAAAA👿",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 VVVVEEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 CCCCCC⚔️HHHHH🖤UUUUU💣DDDDD👿VVVVAAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 AAAAAA👿MMMMM🚀MMMMM🚀AAAAAA👿 CCCCCC⚔️HHHHH🖤UUUUU💣DDDDD👿VVVVAAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜IIIIII🍷 FFFFFF🔥AAAAAA👿BBBBB🤍DDDDD👿 MMMMM🚀AAAAAA👿RRRRR🔘VVVVAAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜AAAAAA👿 BBBBB🤍UUUUU💣RRRRR🔘  MMMMM🚀AAAAAA👿RRRRR🔘VVVVAAAAAA👿",
        "IIIIIIII⚒️DDDDD👿GGGGGG🖤AAAAAA👿RRRRR🔘 AAAAAA👿JJJJJJ👅AAAAAA👿AAAAAA👿 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 KKKKKK💜AAAAAA👿 LLLLLL🔨AAAAAA👿DDDDD👿KKKKKK💜AAAAAA👿",
        "IIIIIIII⚒️DDDDD👿HHHHH🖤AAAAAA👿 TTTTT🚭EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜AAAAAA👿 BBBBB🤍HHHHH🖤OOOOO🎲SSSSS⚒️DDDDD👿AAAAAA👿 DDDDD👿EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜IIIIII🍷 GGGGGG🖤AAAAAA👿NNNNNN🤣DDDDD👿 DDDDD👿EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊NNNNNN🤣 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 HHHHH🖤AAAAAA👿IIIIII🍷",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜YYYYYYTTTTT🚭TTTTT🚭OOOOO🎲 HHHHH🖤AAAAAA👿IIIIII🍷",
        "YYYYYY🤍EEEEEE💊 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 KKKKKK💜EEEEEE💊 BBBBB🤍AAAAAA👿CCCCCC⚔️CCCCCC⚔️HHHHH🖤EEEEEE💊",
        "MMMMM💥AAAAAA👿RRRRR🔘 GGGGGG🖤AAAAAA👿YYYYYYAAAAAA👿 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 KKKKKK💜EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜AAAAAA👿 BBBBB🤍HHHHH🖤OOOOO🎲SSSSS⚒️DDDDD👿 AAAAAA👿 DDDDD👿EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊. KKKKKK📌 PPPPPP📌EEEEEE💊LLLLLL🔨UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 KKKKKK💜OOOOO🎲 LLLLLL🔨EEEEEE💊UUUUU💣 LLLLLL🔨UUUUU💣NNNNNN🤣DDDDD👿 PPPPPP📌EEEEEE💊 AAAAAA👿PPPPPP📌NNNNNN🤣EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜IIIIII🍷 GGGGGG🖤AAAAAA👿NNNNNN🤣DDDDD👿 MMMMM🚀AAAAAA👿RRRRR🔘AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿 KKKKKK💜AAAAAA👿 BBBBB🤍HHHHH🖤OOOOO🎲SSSSS⚒️DDDDD👿AAAAAA👿 MMMMM🚀AAAAAA👿RRRRR🔘AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍AAAAAA👿JJJJJJ👅IIIIII🍷 CCCCCC⚔️HHHHH🖤OOOOO🎲DDDDD👿AAAAAA👿",
        "OOOOOO👅YYYYYYEEEEEE💊 TTTTT🚭AAAAAA👿TTTTT🚭TTTTT🚭EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 AAAAAA👿CCCCCC⚔️UUUUU💣DDDDD👿AAAAAA👿. AAAAAA👿BBBBB🤍",
        "MMMMM💥AAAAAA👿RRRRR🔘NNNNNN??AAAAAA👿 MMMMM🚀AAAAAA👿NNNNNN🤣AAAAAA👿 HHHHH🖤AAAAAA👿IIIIII🍷 RRRRR🔘AAAAAA👿 DDDDD👿IIIIII🍷 KKKKKK💜EEEEEE💊",
        "MMMMM💥AAAAAA👿RRRRR🔘 MMMMM🚀AAAAAA👿RRRRR🔘 KKKKKK💜EEEEEE💊 LLLLLL🔨IIIIII🍷MMMMM🚀HHHHH🖤EEEEEE💊AAAAAA👿 TTTTT🚭EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 CCCCCC⚔️HHHHH🖤OOOOO🎲DDDDD👿HHHHH🖤",
        "OOOOOO👅YYYYYYEEEEEE💊 KKKKKK💜IIIIII🍷NNNNNN🤣AAAAAA👿AAAAAA👿RRRRR🔘 KKKKKK💜EEEEEE💊 BBBBB🤍AAAAAA??CCCCCC⚔️CCCCCC⚔️HHHHH🖤EEEEEE💊 UUUUU💣TTTTT🚭HHHHH🖤",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿 CCCCCC⚔️HHHHH🖤UUUUU💣DDDDD👿VVVVAAAAAA👿 OOOOO🎲YYYYYYEEEEEE💊 TTTTT🚭AAAAAA👿TTTTT🚭TTTTT🚭EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 BBBBB🤍EEEEEE💊HHHHH🖤EEEEEE💊 CCCCCC⚔️BBBBB🤍UUUUU💣DDDDD👿VVVVAAAAAA👿 LLLLLL🔨EEEEEE💊",
        "GGGGGG🌿EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜IIIIII🍷 FFFFFF🔥AAAAAA👿NNNNNN🤣DDDDD👿 OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 BBBBB🤍AAAAAA👿JJJJJJ👅IIIIII🍷 KKKKKK💜AAAAAA👿AAAAAA👿AAAAAA👿 BBBBB🤍UUUUU💣RRRRR🔘 TTTTT🚭OOOOO🎲DDDDD👿UUUUU💣",
        "TTTTTTT🍷AAAAAA👿TTTTT🚭TTTTT🚭TTTTT🚭EEEEEE💊 TTTTT🚭EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜EEEEEE💊 MMMMM🚀UUUUU💣HHHHH🖤 PPPPPP📌EEEEEE💊 LLLLLL🔨OOOOO🎲DDDDD👿AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜IIIIII🍷 GGGGGG🖤AAAAAA👿NNNNNN🤣DDDDD👿 PPPPPP📌EEEEEE💊 LLLLLL🔨OOOOO🎲DDDDD👿AAAAAA👿",
        "OOOOOO👅YYYYYYEEEEEE💊 RRRRR🔘AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 SSSSS⚒️AAAAAA👿MMMMM🚀JJJJJJ👿 WWWWW??AAAAAA👿LLLLLL🔨EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 KKKKKK💜IIIIII🍷.GGGGGG🖤AAAAAA👿 DDDDD👿 SSSSS⚒️AAAAAA👿MMMMM🚀BBBBB🤍HHHHH🖤AAAAAA👿LLLLLL🔨AAAAAA👿 KKKKKK💜EEEEEE💊 CCCCCC⚔️HHHHH🖤OOOOO🎲DDDDD👿UUUUU💣",
        "RRRRRR⚔️AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 IIIIII🍷EEEEEE💊 BBBBB🤍EEEEEE💊YYYYYY",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 GGGGGG🖤AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 CCCCCC⚔️HHHHH🖤UUUUU💣TTTTT🚭EEEEEE💊 WWWWW🥰AAAAAA👿LLLLLL🔨IIIIII🍷 RRRRR🔘AAAAAA👿 DDDDD👿IIIIII🍷",
        "MMMMM💥AAAAAA👿AAAAAA👿AAAAAA👿AAAAAA👿AAAAAA👿AAAAAA👿",
        "KKKKKK📌WWWWW🥰EEEEEE💊EEEEEE💊EEEEEE💊 BBBBB🤍HHHHH🖤OOOOO🎲SSSSS⚒️DDDDD👿EEEEEE💊 DDDDD👿EEEEEE💊",
        "OOOOOO👅YYYYYYEEEEEE💊 BBBBB🤍HHHHH🖤AAAAAA👿NNNNNN🤣GGGGGG🖤IIIIII🍷 TTTTT🚭AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 KKKKKK💜EEEEEE💊",
        "RRRRRR⚔️AAAAAA👿NNNNNN🤣DDDDD👿IIIIII🍷 KKKKKK💜EEEEEE💊 BBBBB🤍AAAAAA👿CCCCCC⚔️CCCCCC⚔️HHHHH🖤EEEEEE💊",
        "KKKKKK📌IIIIII🍷NNNNNN🤣NNNNNN🤣AAAAAA👿RRRRR🔘 KKKKKK💜EEEEEE💊 BBBBB🤍AAAAAA👿CCCCCC⚔️CCCCCC⚔️HHHHH🖤EEEEEE💊",
        "TTTTTTT🍷EEEEEE💊RRRRR🔘IIIIII🍷 MMMMM🚀AAAAAA👿AAAAAA👿AAAAAA👿 NNNNNN🤣AAAAAA👿 CCCCCC⚔️HHHHH🖤UUUUU💣DDDDD👿BBBBB🤍YYYYYYEEEEEE💊GGGGGG🖤AAAAAA👿",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 BBBBB🤍AAAAAA👿JJJJJJ👅IIIIII🍷 KKKKKK💜AAAAAA👿AAAAAA👿AAAAAA👿 BBBBB🤍HHHHH🖤OOOOO🎲SSSSS⚒️DDDDD👿SSSSS⚒️ DDDDD👿EEEEEE💊DDDDD👿EEEEEE💊",
        "AAAAAA👿BBBBB🤍 CCCCCC⚔️HHHHH🖤AAAAAA??LLLLLL🔨 LLLLLL🔨UUUUU💣NNNNNN🤣DDDDD👿 KKKKKK💜EEEEEE💊 CCCCCC⚔️HHHHH🖤UUUUU💣PPPPPP📌PPPPPP📌EEEEEE💊 KKKKKK💜AAAAAA👿RRRRR🔘",
        "TTTTTTT🍷EEEEEE💊EEEEEE💊IIIIII🍷 BBBBB🤍AAAAAA👿JJJJJJ👅IIIIII🍷 CCCCCC⚔️HHHHH🖤OOOOO🎲DDDDD👿UUUUU💣 OOOOO🎲YYYYYYEEEEEE💊"
        ]
            
        ms2_texts = [
        "B⃠a⃠a⃠p⃠ b⃠h⃠i⃠ b⃠n⃠a⃠l⃠e⃠ m⃠u⃠j⃠e⃠ r⃠n⃠d⃠i⃠k⃠e⃠",
        "T⃠e⃠r⃠a⃠ b⃠a⃠a⃠p⃠ r⃠a⃠n⃠d⃠i⃠b⃠a⃠a⃠z⃠ e⃠y⃠ y⃠a⃠a⃠d⃠ e⃠y⃠ t⃠u⃠j⃠h⃠e⃠",
        "T⃠u⃠ a⃠p⃠n⃠i⃠ M⃠a⃠a⃠ c⃠u⃠d⃠a⃠ n⃠a⃠ t⃠y⃠m⃠p⃠a⃠s⃠s⃠",
        "O⃠y⃠e⃠ u⃠n⃠f⃠u⃠n⃠n⃠y⃠ s⃠w⃠i⃠p⃠e⃠ m⃠t⃠t⃠ k⃠r⃠",
        "O⃠h⃠ h⃠e⃠l⃠l⃠o⃠ b⃠i⃠h⃠a⃠r⃠i⃠ t⃠e⃠r⃠a⃠ b⃠a⃠a⃠p⃠ b⃠i⃠h⃠a⃠r⃠i⃠ o⃠r⃠ t⃠u⃠ v⃠ b⃠i⃠h⃠a⃠r⃠i⃠ a⃠a⃠u⃠k⃠a⃠t⃠ m⃠e⃠ r⃠h⃠a⃠ k⃠r⃠.",
        "O⃠y⃠y⃠ k⃠i⃠n⃠n⃠e⃠r⃠ t⃠u⃠j⃠h⃠e⃠ g⃠c⃠ m⃠e⃠ a⃠a⃠n⃠e⃠ k⃠i⃠ p⃠e⃠r⃠m⃠i⃠s⃠s⃠i⃠o⃠n⃠ k⃠i⃠s⃠n⃠e⃠ d⃠i⃠.",
        "C⃠u⃠d⃠k⃠e⃠ d⃠i⃠k⃠h⃠a⃠",
        "C⃠u⃠d⃠k⃠e⃠ d⃠i⃠k⃠h⃠a⃠ e⃠k⃠ b⃠a⃠a⃠r⃠.",
        "S⃠u⃠n⃠ s⃠u⃠n⃠ m⃠a⃠ c⃠u⃠d⃠a⃠.",
        "T⃠e⃠r⃠i⃠ m⃠a⃠c⃠a⃠ b⃠h⃠o⃠s⃠d⃠a⃠.",
        "O⃠y⃠e⃠ c⃠h⃠o⃠t⃠i⃠ j⃠a⃠t⃠i⃠ k⃠e⃠ t⃠m⃠r⃠.",
        "K⃠y⃠? j⃠l⃠d⃠i⃠ l⃠i⃠k⃠h⃠ k⃠i⃠d⃠d⃠e⃠.",
        "B⃠i⃠h⃠a⃠r⃠i⃠ c⃠o⃠m⃠ g⃠a⃠n⃠g⃠ k⃠e⃠ b⃠a⃠a⃠p⃠ k⃠o⃠ t⃠a⃠g⃠ c⃠r⃠e⃠g⃠a⃠ t⃠u⃠",
        "M⃠u⃠j⃠h⃠e⃠ c⃠y⃠a⃠ t⃠u⃠ b⃠i⃠h⃠a⃠r⃠i⃠ e⃠y⃠ t⃠m⃠k⃠c⃠ b⃠s⃠",
        "J⃠a⃠l⃠d⃠i⃠ s⃠e⃠ r⃠a⃠n⃠d⃠i⃠b⃠a⃠a⃠z⃠ p⃠a⃠p⃠a⃠ b⃠o⃠l⃠",
        "S⃠i⃠d⃠e⃠ h⃠o⃠j⃠a⃠ b⃠i⃠h⃠a⃠r⃠i⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ a⃠b⃠",
        "H⃠y⃠e⃠ p⃠g⃠l⃠ b⃠h⃠g⃠ m⃠a⃠t⃠ a⃠c⃠h⃠e⃠ s⃠e⃠ c⃠u⃠d⃠",
        "b⃠h⃠g⃠ n⃠y⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ t⃠u⃠ a⃠j⃠j⃠",
        "H⃠y⃠e⃠ p⃠g⃠l⃠ k⃠e⃠ b⃠c⃠h⃠e⃠ b⃠h⃠a⃠g⃠ m⃠a⃠t⃠",
        "H⃠y⃠e⃠ d⃠u⃠r⃠ h⃠a⃠t⃠t⃠ m⃠a⃠d⃠h⃠c⃠h⃠o⃠d⃠ k⃠e⃠ b⃠a⃠c⃠h⃠e⃠",
        "k⃠o⃠i⃠ b⃠a⃠t⃠ n⃠y⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠ e⃠s⃠l⃠i⃠y⃠e⃠ m⃠a⃠f⃠ c⃠r⃠ r⃠h⃠a⃠ h⃠u⃠ t⃠u⃠j⃠h⃠e⃠",
        "k⃠o⃠i⃠ b⃠a⃠a⃠t⃠ n⃠y⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠w⃠a⃠ a⃠p⃠n⃠i⃠ t⃠u⃠ m⃠a⃠f⃠i⃠ d⃠e⃠ d⃠u⃠n⃠g⃠a⃠",
        "A⃠c⃠h⃠e⃠ s⃠e⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠w⃠a⃠ a⃠p⃠n⃠i⃠ t⃠u⃠ m⃠a⃠f⃠i⃠ m⃠i⃠l⃠ j⃠a⃠y⃠e⃠g⃠i⃠ t⃠u⃠j⃠h⃠e⃠",
        "a⃠p⃠n⃠i⃠ m⃠a⃠ m⃠a⃠t⃠ c⃠h⃠u⃠d⃠a⃠ m⃠u⃠j⃠e⃠ s⃠w⃠i⃠p⃠e⃠ c⃠r⃠k⃠e⃠",
        "A⃠c⃠h⃠e⃠ s⃠e⃠ a⃠p⃠n⃠i⃠ m⃠a⃠ c⃠u⃠d⃠w⃠a⃠ t⃠u⃠ s⃠w⃠i⃠p⃠e⃠ c⃠r⃠k⃠e⃠",
        "F⃠r⃠ b⃠o⃠l⃠n⃠a⃠ n⃠a⃠ k⃠i⃠ c⃠u⃠d⃠w⃠a⃠ l⃠e⃠ a⃠p⃠n⃠i⃠ m⃠a⃠ s⃠w⃠i⃠p⃠e⃠ c⃠r⃠k⃠e⃠",
        "C⃠y⃠a⃠ h⃠u⃠a⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠y⃠i⃠ t⃠e⃠r⃠y⃠",
        "p⃠r⃠ k⃠e⃠s⃠e⃠ c⃠u⃠d⃠ g⃠y⃠i⃠ t⃠e⃠r⃠y⃠ m⃠a⃠",
        "m⃠u⃠j⃠h⃠e⃠ p⃠t⃠a⃠ t⃠h⃠a⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "m⃠e⃠y⃠ n⃠y⃠ m⃠a⃠n⃠t⃠a⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠y⃠i⃠ t⃠e⃠r⃠y⃠",
        "t⃠e⃠r⃠i⃠ m⃠a⃠ r⃠n⃠d⃠y⃠",
        "l⃠o⃠d⃠e⃠ s⃠e⃠ u⃠t⃠r⃠ m⃠c⃠",
        "l⃠u⃠n⃠ m⃠t⃠ c⃠h⃠u⃠s⃠ m⃠e⃠r⃠a⃠",
        "n⃠i⃠k⃠a⃠l⃠ m⃠a⃠d⃠a⃠r⃠c⃠h⃠d⃠",
        "c⃠h⃠u⃠p⃠ o⃠y⃠e⃠ g⃠a⃠s⃠h⃠t⃠i⃠ k⃠ b⃠a⃠c⃠h⃠e⃠",
        "m⃠a⃠k⃠i⃠c⃠h⃠u⃠t⃠ t⃠e⃠r⃠i⃠",
        "c⃠h⃠u⃠p⃠ r⃠n⃠d⃠y⃠k⃠e⃠",
        "m⃠a⃠ r⃠n⃠d⃠y⃠ t⃠e⃠r⃠i⃠",
        "t⃠e⃠r⃠i⃠ m⃠a⃠ k⃠ h⃠a⃠t⃠h⃠ t⃠o⃠d⃠h⃠ k⃠ t⃠e⃠r⃠e⃠ b⃠a⃠a⃠p⃠ k⃠ m⃠u⃠h⃠ m⃠e⃠ f⃠a⃠s⃠a⃠d⃠u⃠n⃠g⃠a⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠",
        "l⃠e⃠a⃠v⃠e⃠ l⃠e⃠ t⃠u⃠ r⃠n⃠d⃠y⃠k⃠e⃠ p⃠a⃠s⃠a⃠n⃠d⃠ n⃠a⃠i⃠ a⃠y⃠a⃠ m⃠e⃠k⃠o⃠",
        "l⃠e⃠a⃠v⃠e⃠ l⃠e⃠ t⃠u⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ i⃠d⃠e⃠r⃠ s⃠e⃠",
        "L⃠e⃠a⃠v⃠e⃠ l⃠e⃠ j⃠l⃠d⃠i⃠ s⃠e⃠ w⃠r⃠n⃠a⃠ m⃠a⃠ c⃠h⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "L⃠e⃠a⃠v⃠e⃠ n⃠y⃠ l⃠e⃠g⃠a⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ t⃠e⃠r⃠y⃠",
        "S⃠m⃠j⃠h⃠ b⃠a⃠t⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠ t⃠e⃠r⃠y⃠ l⃠e⃠a⃠v⃠e⃠ l⃠e⃠",
        "f⃠a⃠s⃠t⃠ l⃠e⃠a⃠v⃠e⃠ l⃠e⃠ k⃠a⃠m⃠j⃠o⃠r⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠",
        "t⃠u⃠t⃠o⃠ c⃠h⃠u⃠p⃠ r⃠n⃠d⃠y⃠k⃠",
        "o⃠y⃠ h⃠i⃠j⃠d⃠e⃠ k⃠h⃠a⃠n⃠a⃠ k⃠h⃠a⃠ k⃠e⃠ a⃠a⃠ k⃠a⃠m⃠z⃠o⃠r⃠",
        "t⃠e⃠r⃠i⃠ m⃠a⃠k⃠o⃠ i⃠l⃠y⃠ r⃠e⃠y⃠🌚😂",
        "c⃠h⃠u⃠p⃠ c⃠h⃠a⃠p⃠ c⃠h⃠u⃠d⃠ t⃠m⃠k⃠c⃠",
        "c⃠h⃠u⃠p⃠c⃠h⃠a⃠p⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠w⃠a⃠ a⃠p⃠n⃠i⃠ t⃠u⃠",
        "s⃠h⃠i⃠ s⃠e⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠w⃠a⃠ a⃠p⃠n⃠i⃠ t⃠u⃠ c⃠h⃠u⃠p⃠c⃠h⃠a⃠p⃠",
        "f⃠r⃠ s⃠e⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠w⃠a⃠ t⃠u⃠ a⃠p⃠n⃠i⃠ c⃠h⃠u⃠p⃠c⃠h⃠a⃠p⃠",
        "s⃠h⃠i⃠ s⃠e⃠ l⃠i⃠k⃠h⃠ w⃠r⃠n⃠a⃠ m⃠a⃠ c⃠h⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "m⃠a⃠ c⃠y⃠u⃠ c⃠h⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠ c⃠h⃠u⃠p⃠c⃠h⃠a⃠p⃠",
        "p⃠r⃠o⃠o⃠f⃠ c⃠r⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠ g⃠y⃠i⃠ t⃠e⃠r⃠y⃠",
        "p⃠r⃠o⃠o⃠f⃠ e⃠y⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠",
        "p⃠r⃠o⃠o⃠f⃠ h⃠o⃠ c⃠h⃠u⃠k⃠a⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ t⃠e⃠r⃠y⃠",
        "C⃠h⃠u⃠p⃠ c⃠h⃠i⃠l⃠l⃠a⃠r⃠",
        "c⃠h⃠u⃠p⃠ c⃠h⃠u⃠p⃠ m⃠a⃠a⃠ k⃠ b⃠o⃠s⃠d⃠a⃠ t⃠e⃠r⃠y⃠",
        "o⃠y⃠ h⃠i⃠j⃠d⃠e⃠ k⃠h⃠a⃠n⃠a⃠ k⃠h⃠a⃠ k⃠e⃠ a⃠a⃠ k⃠a⃠m⃠z⃠o⃠r⃠",
        "c⃠h⃠u⃠p⃠ m⃠a⃠d⃠a⃠r⃠c⃠h⃠o⃠d⃠ ?",
        "A⃠b⃠ t⃠k⃠ c⃠u⃠d⃠ g⃠y⃠i⃠ h⃠o⃠g⃠i⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ ?",
        "n⃠y⃠ n⃠y⃠ m⃠e⃠ k⃠u⃠c⃠h⃠ n⃠y⃠ j⃠a⃠n⃠t⃠a⃠ b⃠s⃠ t⃠e⃠r⃠i⃠ m⃠a⃠ r⃠n⃠d⃠y⃠ e⃠y⃠",
        "S⃠b⃠s⃠e⃠ p⃠h⃠e⃠l⃠e⃠ a⃠p⃠n⃠i⃠ m⃠a⃠a⃠ k⃠o⃠ b⃠o⃠l⃠ c⃠h⃠u⃠d⃠n⃠a⃠ k⃠a⃠a⃠m⃠ k⃠r⃠e⃠",
        "Y⃠a⃠h⃠a⃠ b⃠h⃠i⃠ c⃠h⃠u⃠d⃠a⃠ t⃠u⃠ r⃠n⃠d⃠y⃠c⃠e⃠ p⃠i⃠l⃠l⃠e⃠",
        "t⃠e⃠r⃠i⃠m⃠a⃠k⃠a⃠b⃠o⃠s⃠d⃠a⃠",
        "t⃠e⃠r⃠i⃠ t⃠o⃠ b⃠h⃠e⃠n⃠ c⃠u⃠d⃠e⃠g⃠i⃠",
        "c⃠h⃠u⃠p⃠ r⃠n⃠d⃠y⃠k⃠e⃠ t⃠o⃠m⃠m⃠y⃠",
        "n⃠i⃠k⃠a⃠l⃠ m⃠a⃠d⃠a⃠r⃠c⃠h⃠d⃠ c⃠u⃠d⃠k⃠e⃠ y⃠h⃠a⃠ s⃠e⃠",
        "c⃠o⃠z⃠ t⃠e⃠r⃠i⃠ m⃠a⃠ a⃠n⃠d⃠h⃠i⃠ r⃠a⃠n⃠d⃠i⃠ h⃠e⃠",
        "n⃠y⃠t⃠o⃠ b⃠a⃠a⃠p⃠ b⃠o⃠l⃠ m⃠u⃠j⃠h⃠e⃠",
        "n⃠y⃠n⃠y⃠ t⃠e⃠r⃠i⃠ m⃠a⃠a⃠ h⃠o⃠g⃠i⃠ r⃠n⃠d⃠i⃠i⃠ j⃠o⃠ c⃠h⃠u⃠d⃠w⃠a⃠t⃠i⃠ j⃠o⃠g⃠i⃠",
        "t⃠r⃠y⃠ a⃠m⃠m⃠i⃠ c⃠e⃠ b⃠h⃠o⃠s⃠d⃠e⃠ m⃠e⃠ e⃠m⃠o⃠j⃠i⃠ d⃠a⃠l⃠ m⃠c⃠",
        "c⃠y⃠a⃠ ? c⃠h⃠m⃠r⃠ c⃠h⃠u⃠d⃠ g⃠y⃠a⃠ c⃠y⃠a⃠ ?",
        "t⃠m⃠ c⃠h⃠u⃠d⃠r⃠i⃠ h⃠o⃠g⃠i⃠ f⃠r⃠r⃠t⃠o⃠",
        "c⃠y⃠a⃠ ? k⃠b⃠ ? p⃠g⃠l⃠ e⃠y⃠ c⃠y⃠a⃠ r⃠n⃠d⃠k⃠e⃠k⃠",
        "c⃠y⃠a⃠ s⃠c⃠h⃠ m⃠e⃠y⃠ p⃠g⃠l⃠ e⃠y⃠ c⃠y⃠a⃠ t⃠u⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ c⃠u⃠d⃠w⃠a⃠ l⃠i⃠ t⃠u⃠n⃠e⃠ a⃠p⃠n⃠i⃠ m⃠a⃠",
        "i⃠t⃠n⃠a⃠ s⃠c⃠h⃠ n⃠y⃠ b⃠o⃠l⃠ m⃠a⃠ c⃠h⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "s⃠c⃠h⃠ m⃠e⃠y⃠ p⃠g⃠l⃠ e⃠y⃠ t⃠u⃠ a⃠p⃠n⃠i⃠ m⃠a⃠ c⃠u⃠d⃠w⃠a⃠ l⃠i⃠a⃠ m⃠e⃠r⃠e⃠ s⃠t⃠h⃠",
        "m⃠t⃠l⃠b⃠ t⃠m⃠r⃠",
        "n⃠y⃠t⃠o⃠",
        "p⃠u⃠r⃠a⃠ l⃠i⃠k⃠h⃠ m⃠c⃠",
        "t⃠m⃠r⃠ f⃠r⃠r⃠t⃠o⃠",
        "o⃠h⃠ o⃠k⃠ c⃠u⃠d⃠l⃠e⃠ f⃠i⃠r⃠",
        "t⃠e⃠r⃠i⃠ m⃠a⃠a⃠ k⃠a⃠ d⃠a⃠m⃠a⃠d⃠",
        "c⃠y⃠a⃠ ? a⃠c⃠h⃠e⃠ s⃠e⃠ l⃠i⃠k⃠h⃠e⃠ p⃠e⃠h⃠l⃠e⃠ r⃠n⃠d⃠i⃠k⃠e⃠b⃠a⃠c⃠h⃠e⃠",
        "n⃠y⃠t⃠o⃠ t⃠e⃠r⃠i⃠ m⃠a⃠a⃠ c⃠h⃠o⃠d⃠n⃠e⃠ m⃠e⃠ v⃠y⃠a⃠s⃠t⃠ h⃠u⃠",
        "n⃠y⃠t⃠o⃠ p⃠g⃠l⃠ e⃠y⃠ c⃠y⃠a⃠ k⃠u⃠c⃠h⃠ b⃠i⃠",
        "o⃠y⃠e⃠e⃠ c⃠y⃠a⃠ ? c⃠h⃠u⃠d⃠ g⃠y⃠a⃠ ?",
        "c⃠h⃠u⃠d⃠ m⃠t⃠ h⃠s⃠s⃠",
        "y⃠u⃠r⃠ r⃠n⃠d⃠i⃠i⃠ m⃠o⃠m⃠",
        "a⃠r⃠e⃠ s⃠b⃠k⃠i⃠ m⃠a⃠a⃠ r⃠n⃠d⃠i⃠i⃠ o⃠r⃠ t⃠e⃠r⃠i⃠ b⃠i⃠",
        "a⃠r⃠e⃠ i⃠d⃠a⃠r⃠ c⃠u⃠d⃠l⃠e⃠ e⃠k⃠ b⃠a⃠a⃠r⃠",
        "t⃠r⃠i⃠ m⃠a⃠a⃠ c⃠i⃠ t⃠r⃠h⃠",
        "e⃠k⃠ l⃠i⃠n⃠e⃠ m⃠e⃠ t⃠m⃠r⃠",
        "Q⃠",
        "o⃠c⃠y⃠ a⃠b⃠ c⃠h⃠u⃠d⃠l⃠e⃠",
        "p⃠e⃠h⃠e⃠l⃠e⃠ t⃠e⃠r⃠i⃠ m⃠a⃠a⃠ c⃠h⃠o⃠d⃠u⃠",
        "n⃠y⃠t⃠o⃠",
        "q⃠ ?",
        "h⃠y⃠y⃠y⃠ c⃠h⃠u⃠d⃠ k⃠e⃠ d⃠i⃠k⃠a⃠ e⃠k⃠ b⃠a⃠a⃠r⃠",
        "o⃠y⃠e⃠e⃠ s⃠u⃠n⃠ d⃠o⃠s⃠t⃠ t⃠m⃠r⃠",
        "b⃠h⃠a⃠g⃠ j⃠a⃠ r⃠a⃠a⃠n⃠d⃠ m⃠a⃠a⃠f⃠ c⃠r⃠r⃠ d⃠u⃠n⃠g⃠a⃠",
        "o⃠y⃠e⃠e⃠ p⃠g⃠l⃠ r⃠n⃠d⃠i⃠i⃠ i⃠d⃠a⃠r⃠ a⃠a⃠",
        "c⃠y⃠a⃠ t⃠m⃠r⃠ f⃠r⃠r⃠t⃠o⃠",
        "o⃠y⃠e⃠e⃠ i⃠d⃠a⃠r⃠ a⃠a⃠k⃠e⃠ c⃠h⃠u⃠d⃠ l⃠e⃠ c⃠h⃠m⃠r⃠",
        "n⃠y⃠t⃠o⃠ a⃠e⃠s⃠e⃠ h⃠i⃠ c⃠u⃠d⃠",
        "o⃠y⃠e⃠e⃠ h⃠y⃠y⃠ a⃠i⃠s⃠e⃠ h⃠i⃠ c⃠u⃠d⃠ l⃠e⃠n⃠a⃠",
        "o⃠r⃠ c⃠h⃠u⃠d⃠ l⃠e⃠",
        "c⃠h⃠u⃠d⃠ k⃠e⃠ d⃠i⃠k⃠a⃠ o⃠r⃠",
        "h⃠y⃠y⃠ c⃠h⃠u⃠d⃠o⃠ n⃠a⃠",
        "c⃠h⃠u⃠d⃠o⃠ m⃠t⃠ b⃠h⃠a⃠g⃠ j⃠a⃠o⃠",
        "b⃠y⃠y⃠e⃠e⃠ h⃠y⃠y⃠ c⃠y⃠a⃠ ?",
        "Q⃠c⃠h⃠u⃠d⃠ q⃠ r⃠h⃠e⃠ h⃠o⃠ ?",
        "p⃠g⃠l⃠ e⃠y⃠ c⃠y⃠a⃠ m⃠c⃠",
        "c⃠h⃠u⃠d⃠ m⃠t⃠",
        "c⃠y⃠a⃠ p⃠g⃠l⃠ r⃠n⃠d⃠i⃠i⃠ i⃠d⃠a⃠r⃠ a⃠a⃠",
        "t⃠e⃠r⃠i⃠ a⃠m⃠m⃠i⃠ c⃠e⃠ b⃠h⃠o⃠s⃠d⃠e⃠ m⃠e⃠ c⃠h⃠a⃠p⃠p⃠a⃠l⃠",
        "o⃠y⃠e⃠e⃠ i⃠d⃠a⃠r⃠ a⃠a⃠ m⃠c⃠",
        "k⃠m⃠z⃠r⃠o⃠r⃠ e⃠y⃠ c⃠y⃠a⃠ r⃠n⃠d⃠i⃠e⃠k⃠",
        "c⃠y⃠a⃠ l⃠i⃠k⃠h⃠ r⃠h⃠a⃠ ?",
        "c⃠h⃠u⃠d⃠ t⃠h⃠a⃠ c⃠y⃠a⃠ ?",
        "o⃠y⃠e⃠e⃠ s⃠l⃠i⃠d⃠e⃠ l⃠e⃠k⃠e⃠ b⃠a⃠a⃠t⃠ c⃠r⃠m⃠c⃠",
        "i⃠d⃠a⃠r⃠ a⃠ t⃠e⃠r⃠i⃠ m⃠a⃠a⃠ c⃠h⃠o⃠d⃠u⃠",
        "o⃠y⃠e⃠e⃠ c⃠p⃠ m⃠t⃠ c⃠r⃠r⃠ c⃠h⃠u⃠d⃠l⃠e⃠",
        "o⃠y⃠e⃠e⃠ h⃠y⃠y⃠ c⃠h⃠u⃠d⃠ k⃠e⃠ d⃠i⃠k⃠a⃠",
        "i⃠d⃠a⃠r⃠ a⃠a⃠ t⃠r⃠y⃠ m⃠a⃠ s⃠c⃠h⃠o⃠f⃠u⃠ k⃠h⃠a⃠c⃠h⃠a⃠r⃠ k⃠h⃠a⃠c⃠h⃠a⃠r⃠",
        "i⃠d⃠a⃠r⃠ a⃠a⃠ j⃠a⃠ m⃠c⃠",
        "h⃠y⃠y⃠ i⃠d⃠a⃠r⃠ a⃠a⃠k⃠e⃠ c⃠h⃠u⃠d⃠l⃠e⃠",
        "o⃠y⃠e⃠e⃠ k⃠m⃠z⃠o⃠r⃠ m⃠c⃠ i⃠d⃠a⃠r⃠ a⃠a⃠",
        "y⃠e⃠ c⃠y⃠a⃠ t⃠m⃠r⃠",
        "o⃠y⃠e⃠e⃠ n⃠y⃠ c⃠p⃠ n⃠y⃠ c⃠r⃠r⃠",
        "o⃠y⃠e⃠e⃠ p⃠g⃠l⃠ m⃠t⃠ c⃠r⃠r⃠",
        "c⃠u⃠d⃠l⃠e⃠ a⃠r⃠a⃠m⃠ s⃠e⃠ m⃠c⃠",
        "p⃠g⃠l⃠ e⃠y⃠ c⃠y⃠a⃠ r⃠n⃠d⃠i⃠e⃠k⃠",
        "c⃠p⃠ c⃠r⃠c⃠e⃠ c⃠h⃠u⃠d⃠e⃠g⃠a⃠ !",
        "b⃠a⃠a⃠p⃠ ? m⃠c⃠ m⃠e⃠r⃠a⃠ c⃠o⃠i⃠ m⃠a⃠ b⃠a⃠a⃠p⃠ n⃠y⃠ e⃠y⃠ m⃠a⃠i⃠ u⃠p⃠a⃠r⃠ s⃠e⃠ r⃠o⃠c⃠k⃠e⃠t⃠ p⃠e⃠ b⃠e⃠t⃠h⃠ c⃠e⃠ b⃠s⃠s⃠ t⃠e⃠r⃠i⃠ m⃠a⃠ c⃠h⃠o⃠d⃠n⃠e⃠ a⃠y⃠a⃠ h⃠u⃠",
        "C⃠h⃠o⃠t⃠a⃠ l⃠i⃠k⃠h⃠ r⃠n⃠d⃠i⃠ k⃠ b⃠a⃠c⃠h⃠e⃠",
        "C⃠h⃠o⃠t⃠a⃠ l⃠i⃠k⃠h⃠a⃠ w⃠r⃠n⃠a⃠ t⃠r⃠y⃠ m⃠a⃠ r⃠n⃠d⃠y⃠",
        "T⃠r⃠y⃠ m⃠a⃠ b⃠a⃠k⃠a⃠ c⃠o⃠d⃠e⃠g⃠a⃠",
        "T⃠m⃠k⃠c⃠ m⃠a⃠i⃠n⃠ b⃠u⃠r⃠f⃠",
        "B⃠h⃠i⃠k⃠a⃠r⃠i⃠ k⃠i⃠ j⃠h⃠a⃠t⃠ m⃠a⃠ c⃠u⃠d⃠a⃠ l⃠e⃠",
        "C⃠h⃠o⃠d⃠k⃠e⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ m⃠a⃠r⃠j⃠a⃠y⃠e⃠g⃠i⃠",
        "T⃠m⃠k⃠c⃠ m⃠a⃠i⃠n⃠ M⃠o⃠u⃠n⃠t⃠ E⃠v⃠e⃠r⃠e⃠s⃠t⃠",
        "M⃠u⃠h⃠ m⃠e⃠y⃠ l⃠e⃠g⃠a⃠ l⃠u⃠n⃠d⃠ m⃠e⃠r⃠a⃠",
        "H⃠i⃠j⃠d⃠e⃠ k⃠i⃠ j⃠h⃠a⃠t⃠ c⃠h⃠u⃠p⃠ w⃠r⃠n⃠a⃠ t⃠r⃠y⃠ m⃠a⃠ r⃠n⃠d⃠i⃠",
        "M⃠e⃠n⃠u⃠ n⃠y⃠ p⃠t⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ r⃠a⃠n⃠d⃠y⃠",
        "M⃠e⃠n⃠u⃠ k⃠i⃠ p⃠t⃠a⃠ m⃠a⃠ r⃠a⃠n⃠d⃠y⃠ t⃠e⃠r⃠y⃠",
        "M⃠e⃠n⃠u⃠ p⃠t⃠a⃠ m⃠a⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "M⃠e⃠n⃠u⃠ s⃠b⃠ p⃠t⃠a⃠ m⃠a⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠ t⃠e⃠r⃠y⃠",
        "M⃠e⃠n⃠u⃠ p⃠r⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ r⃠a⃠n⃠d⃠y⃠",
        "R⃠a⃠n⃠d⃠y⃠ m⃠a⃠a⃠ t⃠e⃠r⃠y⃠ m⃠e⃠n⃠u⃠ p⃠t⃠a⃠",
        "T⃠e⃠n⃠u⃠ o⃠r⃠ m⃠e⃠n⃠u⃠ p⃠t⃠a⃠ e⃠y⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ t⃠e⃠r⃠y⃠",
        "B⃠s⃠ b⃠s⃠ m⃠a⃠a⃠ c⃠u⃠d⃠w⃠a⃠ a⃠p⃠n⃠i⃠",
        "B⃠s⃠ b⃠s⃠ m⃠a⃠ r⃠a⃠n⃠d⃠y⃠ t⃠e⃠r⃠y⃠ t⃠h⃠n⃠k⃠s⃠s⃠",
        "B⃠s⃠ b⃠s⃠ c⃠h⃠u⃠d⃠w⃠a⃠ l⃠i⃠a⃠ t⃠u⃠ a⃠p⃠n⃠i⃠ m⃠a⃠a⃠",
        "B⃠s⃠ b⃠s⃠ k⃠a⃠m⃠j⃠o⃠r⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ t⃠e⃠r⃠y⃠",
        "S⃠m⃠j⃠h⃠ g⃠y⃠a⃠ a⃠p⃠n⃠i⃠ m⃠a⃠ c⃠u⃠d⃠w⃠a⃠ l⃠e⃠ a⃠b⃠",
        "s⃠m⃠j⃠h⃠ g⃠y⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠",
        "s⃠m⃠j⃠h⃠ g⃠y⃠a⃠ t⃠u⃠ s⃠a⃠b⃠i⃠t⃠ k⃠r⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ t⃠e⃠r⃠y⃠",
        "C⃠y⃠a⃠ h⃠u⃠a⃠ m⃠a⃠ c⃠u⃠d⃠w⃠a⃠ t⃠u⃠ a⃠p⃠n⃠i⃠",
        "E⃠a⃠s⃠y⃠ m⃠a⃠a⃠ c⃠u⃠d⃠w⃠a⃠ l⃠e⃠ a⃠p⃠n⃠i⃠ t⃠u⃠",
        "E⃠a⃠s⃠y⃠ w⃠8⃠ m⃠a⃠ c⃠h⃠u⃠d⃠w⃠a⃠ l⃠e⃠ a⃠p⃠n⃠i⃠ a⃠b⃠",
        "S⃠a⃠n⃠s⃠ a⃠r⃠i⃠ h⃠a⃠ k⃠y⃠ t⃠e⃠r⃠i⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠g⃠i⃠ a⃠j⃠j⃠",
        "T⃠e⃠r⃠i⃠ m⃠a⃠a⃠ k⃠o⃠ b⃠i⃠n⃠a⃠ s⃠a⃠n⃠s⃠s⃠ l⃠e⃠t⃠e⃠ h⃠u⃠e⃠ c⃠h⃠o⃠d⃠u⃠n⃠g⃠a⃠",
        "c⃠h⃠u⃠p⃠ r⃠a⃠n⃠d⃠i⃠k⃠e⃠ k⃠a⃠m⃠j⃠o⃠r⃠",
        "a⃠p⃠n⃠i⃠ m⃠a⃠ n⃠o⃠r⃠m⃠i⃠e⃠ c⃠u⃠d⃠w⃠a⃠ l⃠e⃠ t⃠u⃠",
        "f⃠r⃠ c⃠y⃠a⃠ n⃠o⃠r⃠m⃠i⃠e⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "b⃠a⃠s⃠ t⃠h⃠e⃠k⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ r⃠a⃠n⃠d⃠y⃠",
        "b⃠a⃠s⃠ t⃠h⃠e⃠k⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ c⃠u⃠d⃠ g⃠y⃠i⃠",
        "k⃠a⃠m⃠j⃠o⃠r⃠ t⃠h⃠i⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ e⃠s⃠l⃠i⃠y⃠e⃠ c⃠u⃠d⃠ g⃠a⃠i⃠",
        "M⃠a⃠i⃠ s⃠b⃠ j⃠a⃠n⃠t⃠a⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "c⃠h⃠l⃠ c⃠h⃠l⃠ h⃠t⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ c⃠u⃠d⃠ g⃠y⃠i⃠",
        "f⃠r⃠ k⃠a⃠i⃠s⃠e⃠ c⃠u⃠d⃠ g⃠y⃠i⃠ m⃠a⃠a⃠ t⃠e⃠r⃠y⃠",
        "m⃠a⃠a⃠ t⃠e⃠r⃠y⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠",
        "b⃠a⃠s⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠",
        "f⃠r⃠ r⃠a⃠n⃠d⃠y⃠ m⃠a⃠ t⃠e⃠r⃠y⃠ e⃠y⃠",
        "K⃠a⃠m⃠j⃠o⃠r⃠ m⃠a⃠ k⃠a⃠ b⃠c⃠h⃠a⃠ t⃠u⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠",
        "b⃠h⃠o⃠t⃠ g⃠n⃠d⃠i⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ m⃠a⃠a⃠ t⃠e⃠r⃠y⃠",
        "p⃠r⃠ k⃠a⃠i⃠s⃠e⃠ m⃠a⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠ i⃠t⃠n⃠a⃠ g⃠n⃠d⃠a⃠",
        "m⃠u⃠j⃠h⃠e⃠ c⃠y⃠a⃠ b⃠t⃠a⃠ r⃠h⃠a⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ t⃠e⃠r⃠y⃠",
        "m⃠u⃠j⃠h⃠e⃠ c⃠y⃠a⃠ p⃠t⃠a⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠y⃠i⃠ t⃠e⃠r⃠y⃠",
        "f⃠i⃠r⃠ m⃠u⃠j⃠h⃠e⃠ n⃠y⃠ p⃠t⃠a⃠ m⃠a⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "p⃠t⃠a⃠ n⃠y⃠ k⃠o⃠n⃠ c⃠o⃠d⃠ d⃠i⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ k⃠o⃠",
        "r⃠u⃠k⃠ a⃠a⃠y⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ c⃠o⃠d⃠k⃠e⃠",
        "w⃠a⃠i⃠t⃠ c⃠r⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ c⃠o⃠d⃠ r⃠h⃠a⃠ h⃠u⃠",
        "w⃠a⃠i⃠t⃠ c⃠r⃠ r⃠a⃠b⃠d⃠y⃠k⃠e⃠ m⃠a⃠a⃠ c⃠u⃠d⃠ r⃠h⃠i⃠ e⃠y⃠ t⃠e⃠r⃠y⃠",
        "w⃠a⃠i⃠t⃠ k⃠r⃠ s⃠m⃠j⃠h⃠ r⃠h⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ c⃠o⃠d⃠k⃠e⃠",
        "w⃠a⃠i⃠t⃠ l⃠e⃠ t⃠h⃠o⃠d⃠a⃠ c⃠h⃠o⃠d⃠n⃠e⃠ d⃠e⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠o⃠",
        "r⃠u⃠k⃠ j⃠a⃠ a⃠a⃠n⃠d⃠ r⃠k⃠h⃠ d⃠u⃠n⃠g⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠e⃠ l⃠i⃠y⃠e⃠",
        "t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ f⃠a⃠m⃠o⃠u⃠s⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠",
        "m⃠a⃠a⃠n⃠ l⃠i⃠a⃠ m⃠e⃠n⃠e⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ s⃠a⃠l⃠i⃠ t⃠e⃠r⃠y⃠",
        "m⃠a⃠a⃠n⃠ l⃠i⃠a⃠ m⃠a⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "s⃠h⃠a⃠n⃠t⃠ b⃠e⃠t⃠h⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠w⃠a⃠ t⃠u⃠ a⃠p⃠n⃠i⃠",
        "s⃠h⃠a⃠n⃠t⃠ b⃠e⃠t⃠h⃠k⃠e⃠ c⃠h⃠u⃠d⃠w⃠a⃠ l⃠e⃠ a⃠p⃠n⃠i⃠ m⃠a⃠k⃠o⃠ t⃠u⃠",
        "f⃠r⃠ s⃠e⃠ s⃠h⃠a⃠n⃠t⃠ B⃠e⃠t⃠h⃠ t⃠u⃠ c⃠u⃠d⃠ a⃠b⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ y⃠h⃠a⃠",
        "m⃠e⃠r⃠e⃠ s⃠m⃠j⃠h⃠ n⃠y⃠ a⃠y⃠a⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ t⃠e⃠r⃠y⃠",
        "L⃠e⃠ k⃠e⃠l⃠a⃠ K⃠h⃠a⃠ t⃠u⃠ m⃠a⃠d⃠a⃠r⃠c⃠h⃠o⃠d⃠",
        "H⃠y⃠e⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠y⃠i⃠ c⃠y⃠a⃠",
        "h⃠y⃠e⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ m⃠a⃠r⃠ g⃠a⃠i⃠ c⃠y⃠a⃠",
        "H⃠y⃠e⃠ s⃠c⃠h⃠ b⃠t⃠a⃠ c⃠o⃠m⃠ c⃠o⃠d⃠ d⃠i⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠o⃠",
        "C⃠h⃠l⃠ c⃠h⃠o⃠d⃠ d⃠i⃠a⃠ t⃠e⃠r⃠i⃠ m⃠a⃠a⃠ k⃠o⃠ s⃠m⃠j⃠h⃠l⃠e⃠",
        "B⃠a⃠k⃠i⃠ k⃠o⃠i⃠ d⃠i⃠k⃠k⃠a⃠t⃠ n⃠y⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠",
        "b⃠a⃠k⃠i⃠ s⃠b⃠ j⃠a⃠n⃠t⃠e⃠ e⃠y⃠ k⃠i⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠d⃠k⃠a⃠d⃠ e⃠y⃠ t⃠e⃠r⃠y⃠",
        "m⃠u⃠j⃠h⃠e⃠ c⃠y⃠a⃠ p⃠t⃠a⃠ t⃠h⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ c⃠u⃠d⃠n⃠e⃠ w⃠l⃠i⃠ e⃠y⃠",
        "p⃠r⃠ m⃠e⃠i⃠ k⃠a⃠i⃠s⃠e⃠ j⃠n⃠t⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ k⃠o⃠ k⃠o⃠i⃠ c⃠h⃠o⃠d⃠ d⃠i⃠a⃠",
        "p⃠r⃠ m⃠e⃠r⃠a⃠ v⃠i⃠ m⃠a⃠n⃠n⃠a⃠ s⃠h⃠i⃠ t⃠h⃠a⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "p⃠r⃠ w⃠o⃠ g⃠l⃠t⃠ n⃠y⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠",
        "p⃠r⃠ w⃠o⃠ s⃠h⃠i⃠ e⃠y⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠d⃠k⃠a⃠d⃠ e⃠y⃠",
        "p⃠r⃠ k⃠a⃠i⃠s⃠e⃠ k⃠i⃠a⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠ o⃠m⃠f⃠o⃠o⃠",
        "b⃠u⃠r⃠ c⃠h⃠e⃠e⃠r⃠ d⃠u⃠n⃠g⃠a⃠ t⃠r⃠i⃠ m⃠a⃠ k⃠a⃠",
        "t⃠e⃠r⃠i⃠ m⃠a⃠ k⃠e⃠ d⃠i⃠l⃠ m⃠e⃠ l⃠o⃠d⃠a⃠ m⃠a⃠r⃠k⃠e⃠ u⃠s⃠k⃠i⃠ d⃠h⃠a⃠d⃠k⃠a⃠n⃠ r⃠o⃠k⃠ d⃠u⃠n⃠g⃠a⃠",
        "l⃠u⃠l⃠l⃠e⃠ k⃠h⃠a⃠ t⃠r⃠i⃠ m⃠a⃠k⃠a⃠b⃠h⃠o⃠s⃠d⃠a⃠",
        "t⃠r⃠i⃠ b⃠h⃠n⃠ k⃠i⃠ b⃠h⃠o⃠s⃠d⃠i⃠ b⃠e⃠t⃠a⃠",
        "t⃠r⃠i⃠ m⃠a⃠ r⃠n⃠d⃠i⃠ b⃠a⃠a⃠t⃠ k⃠h⃠t⃠m⃠",
        "S⃠u⃠n⃠ e⃠k⃠ m⃠a⃠z⃠e⃠ k⃠i⃠ b⃠a⃠a⃠t⃠ b⃠a⃠t⃠a⃠o⃠ k⃠y⃠a⃠ t⃠e⃠r⃠i⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠y⃠ e⃠y⃠"
        "c⃠o⃠d⃠u⃠ c⃠o⃠d⃠u⃠ m⃠a⃠k⃠o⃠ t⃠e⃠r⃠y⃠",
        "a⃠j⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ o⃠y⃠e⃠",
        "s⃠u⃠n⃠ s⃠u⃠n⃠ r⃠a⃠n⃠d⃠y⃠ m⃠a⃠k⃠e⃠ b⃠a⃠c⃠h⃠e⃠ t⃠u⃠",
        "k⃠i⃠l⃠a⃠s⃠ n⃠y⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠",
        "m⃠u⃠j⃠h⃠e⃠ c⃠y⃠a⃠ p⃠t⃠a⃠ t⃠e⃠r⃠y⃠ b⃠h⃠e⃠n⃠ c⃠u⃠d⃠ g⃠a⃠i⃠",
        "p⃠r⃠ p⃠r⃠ c⃠y⃠a⃠ h⃠o⃠t⃠e⃠ e⃠y⃠ t⃠m⃠k⃠c⃠",
        "t⃠m⃠c⃠l⃠ s⃠u⃠n⃠l⃠e⃠",
        "m⃠o⃠o⃠t⃠ d⃠u⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠i⃠ c⃠h⃠u⃠t⃠ m⃠e⃠y⃠",
        "b⃠h⃠g⃠n⃠y⃠ c⃠u⃠d⃠k⃠e⃠ d⃠i⃠k⃠h⃠a⃠ f⃠r⃠",
        "f⃠r⃠ s⃠e⃠ c⃠u⃠d⃠l⃠e⃠ t⃠u⃠",
        "y⃠e⃠ v⃠i⃠ s⃠h⃠i⃠ e⃠y⃠ t⃠e⃠r⃠y⃠ m⃠k⃠c⃠ b⃠s⃠",
        "a⃠j⃠ k⃠u⃠c⃠h⃠ n⃠y⃠ m⃠a⃠ c⃠u⃠d⃠w⃠a⃠ t⃠u⃠ a⃠p⃠n⃠i⃠",
        "t⃠r⃠y⃠ k⃠r⃠ m⃠e⃠r⃠a⃠ l⃠u⃠n⃠d⃠ c⃠h⃠u⃠s⃠k⃠e⃠",
        "t⃠o⃠r⃠m⃠a⃠k⃠i⃠b⃠u⃠r⃠ s⃠u⃠n⃠",
        "t⃠o⃠r⃠ m⃠a⃠k⃠i⃠ f⃠u⃠d⃠d⃠i⃠ o⃠y⃠e⃠",
        "H⃠a⃠y⃠e⃠ H⃠a⃠y⃠e⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠",
        "o⃠y⃠e⃠ l⃠u⃠n⃠d⃠k⃠e⃠ p⃠a⃠s⃠i⃠n⃠e⃠..",
        "k⃠u⃠t⃠t⃠e⃠ k⃠e⃠ t⃠a⃠t⃠t⃠e⃠ s⃠u⃠n⃠",
        "k⃠u⃠t⃠t⃠a⃠ j⃠a⃠i⃠s⃠a⃠ c⃠u⃠d⃠ r⃠h⃠a⃠ t⃠u⃠",
        "M⃠u⃠h⃠ m⃠e⃠i⃠ l⃠e⃠ m⃠e⃠r⃠a⃠..",
        "j⃠h⃠a⃠a⃠t⃠ k⃠e⃠ p⃠i⃠s⃠s⃠u⃠ s⃠u⃠n⃠ t⃠m⃠k⃠c⃠",
        "H⃠a⃠h⃠a⃠h⃠h⃠a⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠",
        "w⃠e⃠a⃠k⃠ t⃠a⃠t⃠t⃠e⃠ u⃠t⃠h⃠",
        "w⃠e⃠a⃠k⃠ e⃠y⃠ t⃠u⃠ c⃠u⃠d⃠ r⃠h⃠a⃠",
        "w⃠e⃠a⃠k⃠ a⃠c⃠h⃠e⃠ s⃠e⃠ c⃠u⃠d⃠ t⃠u⃠",
        "w⃠e⃠a⃠k⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ c⃠u⃠d⃠ r⃠h⃠i⃠ d⃠e⃠k⃠h⃠",
        "w⃠e⃠e⃠k⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ a⃠b⃠",
        "m⃠u⃠j⃠h⃠e⃠ n⃠y⃠ r⃠o⃠k⃠ t⃠u⃠ w⃠e⃠a⃠k⃠ e⃠y⃠",
        "c⃠h⃠u⃠p⃠ h⃠i⃠z⃠d⃠e⃠",
        "o⃠k⃠a⃠t⃠ n⃠y⃠ m⃠e⃠r⃠i⃠ m⃠a⃠ c⃠u⃠d⃠w⃠a⃠ t⃠u⃠ a⃠p⃠n⃠i⃠",
        "l⃠u⃠n⃠ l⃠e⃠g⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠i⃠ g⃠a⃠n⃠d⃠ m⃠e⃠i⃠ ?",
        "t⃠e⃠r⃠y⃠ m⃠a⃠k⃠i⃠ b⃠a⃠c⃠h⃠i⃠ c⃠o⃠d⃠u⃠..",
        "t⃠e⃠r⃠y⃠ b⃠h⃠e⃠n⃠ k⃠i⃠ c⃠h⃠u⃠t⃠ a⃠j⃠ f⃠a⃠d⃠ d⃠u⃠",
        "s⃠p⃠e⃠e⃠d⃠ l⃠e⃠k⃠r⃠ a⃠a⃠ c⃠u⃠d⃠k⃠e⃠ d⃠i⃠k⃠h⃠a⃠",
        "s⃠p⃠e⃠e⃠d⃠ n⃠y⃠ t⃠e⃠r⃠e⃠ a⃠n⃠d⃠r⃠ w⃠e⃠a⃠k⃠ p⃠r⃠o⃠s⃠n⃠",
        "u⃠g⃠l⃠y⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ c⃠h⃠u⃠p⃠",
        "m⃠a⃠k⃠a⃠f⃠u⃠d⃠d⃠a⃠t⃠e⃠r⃠y⃠",
        "t⃠e⃠r⃠a⃠ b⃠a⃠a⃠p⃠ k⃠o⃠ t⃠a⃠g⃠ k⃠r⃠..?",
        "a⃠c⃠h⃠e⃠ s⃠e⃠ t⃠a⃠g⃠ k⃠r⃠ r⃠a⃠n⃠d⃠i⃠b⃠a⃠a⃠z⃠ b⃠h⃠a⃠g⃠w⃠n⃠ k⃠o⃠..",
        "c⃠u⃠d⃠k⃠e⃠ p⃠g⃠l⃠ n⃠y⃠ h⃠o⃠ t⃠u⃠",
        "c⃠u⃠d⃠k⃠e⃠ p⃠g⃠l⃠ h⃠o⃠ r⃠h⃠a⃠ t⃠u⃠ k⃠i⃠d⃠",
        "m⃠a⃠ t⃠o⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠ h⃠a⃠w⃠a⃠b⃠z⃠i⃠ c⃠r⃠..",
        "b⃠s⃠ m⃠a⃠ c⃠o⃠d⃠n⃠i⃠ e⃠y⃠ t⃠e⃠r⃠y⃠",
        "t⃠o⃠w⃠n⃠ m⃠e⃠i⃠ c⃠u⃠d⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠o⃠ l⃠e⃠k⃠r⃠",
        "t⃠e⃠r⃠y⃠ m⃠a⃠ s⃠e⃠x⃠y⃠ k⃠o⃠ b⃠e⃠j⃠ - r⃠a⃠n⃠d⃠i⃠b⃠a⃠a⃠z⃠ b⃠h⃠g⃠w⃠n⃠ p⃠e⃠",
        "s⃠p⃠e⃠e⃠d⃠ p⃠k⃠d⃠ c⃠p⃠ n⃠y⃠ k⃠r⃠",
        "T⃠r⃠y⃠ m⃠a⃠ r⃠e⃠n⃠d⃠y⃠",
        "B⃠h⃠k⃠k⃠ c⃠u⃠d⃠",
        "t⃠e⃠y⃠ m⃠a⃠a⃠ r⃠n⃠d⃠i⃠",
        "t⃠e⃠r⃠y⃠ b⃠e⃠h⃠e⃠n⃠ r⃠a⃠n⃠d⃠i⃠",
        "C⃠u⃠d⃠ j⃠a⃠",
        "t⃠e⃠r⃠y⃠ d⃠i⃠d⃠i⃠ r⃠n⃠d⃠i⃠",
        "S⃠l⃠o⃠w⃠",
        "t⃠e⃠r⃠i⃠ M⃠a⃠i⃠y⃠a⃠ c⃠i⃠o⃠d⃠u⃠",
        "B⃠h⃠a⃠g⃠?",
        "B⃠h⃠a⃠k⃠ c⃠u⃠d⃠",
        "T⃠m⃠a⃠ c⃠o⃠d⃠u⃠",
        "S⃠l⃠o⃠w⃠",
        "S⃠l⃠o⃠w⃠ f⃠i⃠r⃠s⃠e⃠",
        "C⃠u⃠d⃠g⃠r⃠i⃠b⃠",
        "T⃠r⃠y⃠ m⃠a⃠ d⃠o⃠u⃠",
        "t⃠b⃠k⃠c⃠ c⃠o⃠d⃠u⃠",
        "N⃠e⃠t⃠ o⃠n⃠ o⃠f⃠f⃠ w⃠a⃠l⃠i⃠ r⃠n⃠d⃠y⃠",
        "O⃠y⃠e⃠ t⃠r⃠y⃠ m⃠a⃠ c⃠o⃠d⃠u⃠",
        "I⃠d⃠h⃠a⃠r⃠ a⃠a⃠k⃠e⃠ c⃠u⃠d⃠ c⃠h⃠u⃠p⃠ c⃠h⃠a⃠a⃠p⃠",
        "t⃠b⃠k⃠c⃠ m⃠r⃠d⃠u⃠",
        "o⃠i⃠ m⃠a⃠a⃠k⃠e⃠ l⃠o⃠d⃠e⃠e⃠",
        "r⃠a⃠n⃠d⃠y⃠k⃠e⃠ b⃠e⃠e⃠j⃠",
        "t⃠m⃠k⃠c⃠ c⃠h⃠o⃠d⃠u⃠",
        "s⃠u⃠a⃠r⃠ k⃠e⃠ b⃠e⃠e⃠j⃠",
        "n⃠e⃠t⃠ o⃠f⃠f⃠ o⃠n⃠ k⃠r⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ l⃠a⃠d⃠k⃠e⃠",
        "T⃠r⃠y⃠ m⃠a⃠ c⃠u⃠d⃠i⃠ k⃠e⃠s⃠e⃠",
        "C⃠h⃠u⃠p⃠ s⃠l⃠o⃠w⃠ m⃠a⃠d⃠h⃠a⃠r⃠c⃠o⃠d⃠",
        "t⃠b⃠k⃠c⃠ c⃠o⃠d⃠u⃠ k⃠r⃠ m⃠s⃠g⃠ d⃠e⃠l⃠e⃠t⃠e⃠",
        "o⃠i⃠ s⃠u⃠a⃠r⃠ k⃠e⃠ l⃠a⃠d⃠k⃠e⃠",
        "t⃠m⃠k⃠c⃠ f⃠u⃠f⃠i⃠",
        "t⃠e⃠r⃠y⃠ d⃠i⃠d⃠i⃠ c⃠h⃠u⃠d⃠i⃠",
        "t⃠m⃠k⃠c⃠ d⃠i⃠k⃠h⃠a⃠",
        "C⃠u⃠d⃠ a⃠b⃠",
        "r⃠a⃠n⃠d⃠y⃠k⃠e⃠ c⃠u⃠d⃠",
        "B⃠h⃠a⃠k⃠ c⃠u⃠d⃠",
        "c⃠u⃠d⃠l⃠e⃠ t⃠b⃠k⃠c⃠ m⃠r⃠u⃠",
        "t⃠m⃠k⃠l⃠ c⃠u⃠d⃠l⃠e⃠ g⃠r⃠i⃠b⃠",
        "t⃠e⃠r⃠y⃠ b⃠e⃠h⃠e⃠n⃠ v⃠e⃠s⃠i⃠y⃠a⃠a⃠ r⃠n⃠d⃠i⃠",
        "I⃠t⃠n⃠a⃠ g⃠n⃠d⃠a⃠ c⃠h⃠u⃠d⃠a⃠ t⃠u⃠ f⃠i⃠r⃠s⃠e⃠ n⃠e⃠t⃠ o⃠n⃠ o⃠f⃠f⃠",
        "g⃠r⃠i⃠b⃠ k⃠e⃠ b⃠e⃠t⃠e⃠",
        "B⃠h⃠a⃠g⃠ j⃠a⃠ l⃠o⃠d⃠e⃠ t⃠m⃠k⃠c⃠ m⃠a⃠r⃠u⃠ d⃠u⃠n⃠g⃠a⃠",
        "t⃠b⃠k⃠c⃠ m⃠r⃠d⃠u⃠n⃠g⃠a⃠a⃠",
        "b⃠h⃠a⃠g⃠ t⃠m⃠k⃠c⃠",
        "b⃠h⃠a⃠g⃠ t⃠b⃠k⃠c⃠",
        "t⃠b⃠k⃠c⃠ m⃠e⃠y⃠ c⃠p⃠",
        "c⃠p⃠ t⃠b⃠k⃠c⃠ m⃠e⃠h⃠h⃠",
        "c⃠p⃠ t⃠m⃠k⃠l⃠ m⃠e⃠h⃠",
        "c⃠p⃠ b⃠o⃠l⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠",
        "A⃠b⃠e⃠ c⃠p⃠ b⃠o⃠l⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠",
        "d⃠o⃠u⃠b⃠l⃠e⃠ s⃠e⃠n⃠d⃠ k⃠o⃠ c⃠p⃠ t⃠m⃠k⃠c⃠ c⃠o⃠d⃠u⃠",
        "t⃠b⃠k⃠c⃠ m⃠e⃠ c⃠p⃠ c⃠o⃠d⃠ d⃠u⃠n⃠g⃠a⃠ A⃠a⃠j⃠ m⃠e⃠h⃠h⃠",
        "h⃠t⃠ t⃠b⃠k⃠c⃠ d⃠a⃠l⃠a⃠l⃠ k⃠e⃠ b⃠e⃠t⃠e⃠.",
        "R⃠n⃠d⃠y⃠ j⃠l⃠d⃠i⃠ j⃠l⃠d⃠i⃠ c⃠u⃠d⃠q⃠ t⃠r⃠y⃠m⃠a⃠",
        "P⃠a⃠r⃠a⃠ l⃠i⃠k⃠h⃠e⃠g⃠a⃠..",
        "T⃠r⃠a⃠ r⃠n⃠d⃠h⃠b⃠h⃠a⃠k⃠",
        "L⃠a⃠g⃠d⃠i⃠ k⃠e⃠ l⃠a⃠d⃠c⃠e⃠ c⃠p⃠ b⃠o⃠l⃠",
        "c⃠p⃠ b⃠o⃠l⃠ l⃠a⃠g⃠d⃠i⃠ k⃠e⃠ b⃠e⃠t⃠e⃠..",
        "c⃠u⃠d⃠k⃠e⃠ c⃠p⃠ b⃠o⃠l⃠",
        "b⃠h⃠i⃠k⃠a⃠r⃠i⃠ l⃠u⃠n⃠d⃠ c⃠h⃠u⃠s⃠ m⃠e⃠r⃠a⃠.",
        "L⃠o⃠w⃠ l⃠e⃠v⃠e⃠l⃠ c⃠p⃠ c⃠r⃠",
        "c⃠p⃠ b⃠o⃠l⃠ l⃠o⃠w⃠ l⃠e⃠v⃠e⃠l⃠ w⃠e⃠a⃠k⃠",
        "m⃠e⃠r⃠e⃠ l⃠u⃠n⃠d⃠ p⃠e⃠ e⃠y⃠ t⃠u⃠ h⃠i⃠j⃠d⃠e⃠",
        "f⃠r⃠e⃠e⃠ c⃠u⃠d⃠w⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠o⃠",
        "F⃠r⃠e⃠e⃠ m⃠e⃠y⃠ c⃠u⃠d⃠ t⃠u⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠"
        "s⃠p⃠e⃠e⃠d⃠ n⃠y⃠ w⃠e⃠a⃠k⃠ t⃠a⃠t⃠t⃠e⃠ t⃠e⃠r⃠m⃠e⃠",
        "k⃠i⃠t⃠n⃠i⃠ b⃠r⃠ c⃠u⃠d⃠w⃠a⃠y⃠e⃠g⃠a⃠ t⃠e⃠r⃠y⃠m⃠a⃠k⃠o⃠",
        "l⃠u⃠n⃠d⃠ l⃠e⃠ r⃠a⃠n⃠d⃠i⃠b⃠a⃠a⃠z⃠ b⃠a⃠p⃠k⃠a⃠",
        "l⃠u⃠n⃠ c⃠u⃠s⃠ j⃠a⃠l⃠d⃠i⃠ s⃠e⃠ r⃠a⃠n⃠d⃠i⃠b⃠a⃠a⃠z⃠ b⃠a⃠p⃠k⃠a⃠",
        "k⃠o⃠i⃠ n⃠y⃠ d⃠e⃠k⃠h⃠ r⃠h⃠a⃠ c⃠u⃠d⃠l⃠e⃠ t⃠u⃠",
        "c⃠u⃠d⃠l⃠e⃠ b⃠e⃠t⃠i⃠c⃠h⃠o⃠d⃠ a⃠c⃠h⃠e⃠ s⃠e⃠",
        "m⃠a⃠k⃠i⃠ c⃠h⃠u⃠t⃠ t⃠e⃠r⃠y⃠ b⃠s⃠ y⃠e⃠h⃠i⃠ j⃠a⃠n⃠t⃠a⃠ m⃠e⃠y⃠",
        "c⃠p⃠ b⃠o⃠l⃠e⃠g⃠a⃠ t⃠o⃠ t⃠m⃠k⃠c⃠",
        "w⃠r⃠n⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ c⃠u⃠d⃠ j⃠a⃠y⃠e⃠g⃠i⃠",
        "s⃠l⃠o⃠w⃠ e⃠y⃠ t⃠u⃠ k⃠i⃠d⃠",
        "j⃠l⃠d⃠i⃠ l⃠i⃠k⃠h⃠..t⃠m⃠k⃠c⃠",
        "j⃠l⃠d⃠i⃠ l⃠i⃠k⃠h⃠..r⃠a⃠n⃠d⃠c⃠e⃠ t⃠u⃠",
        "t⃠y⃠m⃠ s⃠e⃠ p⃠h⃠l⃠e⃠ c⃠u⃠d⃠k⃠e⃠ d⃠i⃠k⃠h⃠a⃠",
        "t⃠y⃠m⃠ h⃠o⃠g⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ c⃠u⃠d⃠w⃠a⃠",
        "m⃠a⃠ c⃠u⃠d⃠ g⃠a⃠i⃠ t⃠e⃠r⃠y⃠ t⃠y⃠m⃠ s⃠e⃠ p⃠h⃠l⃠e⃠",
        "u⃠t⃠h⃠ r⃠a⃠n⃠d⃠c⃠e⃠ k⃠e⃠ l⃠d⃠k⃠e⃠",
        "m⃠a⃠c⃠a⃠b⃠o⃠s⃠d⃠a⃠t⃠e⃠r⃠y⃠",
        "c⃠o⃠n⃠ k⃠b⃠ c⃠o⃠d⃠ d⃠i⃠a⃠ m⃠a⃠k⃠o⃠ t⃠e⃠r⃠y⃠",
        "k⃠o⃠i⃠ h⃠o⃠g⃠a⃠ t⃠m⃠l⃠",
        "m⃠a⃠c⃠h⃠a⃠r⃠ c⃠u⃠d⃠l⃠e⃠ t⃠u⃠",
        "m⃠e⃠n⃠u⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠o⃠ c⃠o⃠d⃠n⃠a⃠ s⃠e⃠",
        "t⃠e⃠r⃠y⃠ m⃠a⃠k⃠o⃠ b⃠o⃠l⃠ m⃠u⃠j⃠h⃠e⃠ c⃠o⃠d⃠ d⃠e⃠",
        "b⃠s⃠ m⃠e⃠y⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ s⃠e⃠ c⃠u⃠d⃠n⃠a⃠ c⃠h⃠t⃠a⃠ h⃠u⃠",
        "E⃠w⃠w⃠ m⃠a⃠k⃠a⃠ l⃠o⃠d⃠e⃠ u⃠t⃠h⃠",
        "M⃠e⃠o⃠w⃠ c⃠r⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠o⃠ c⃠o⃠d⃠u⃠",
        "l⃠u⃠n⃠d⃠ r⃠k⃠h⃠ d⃠i⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠e⃠ f⃠u⃠d⃠e⃠ p⃠e⃠",
        "m⃠e⃠r⃠a⃠ l⃠u⃠n⃠d⃠ k⃠e⃠ b⃠a⃠l⃠ u⃠t⃠h⃠",
        "k⃠i⃠d⃠e⃠e⃠ Z⃠i⃠n⃠d⃠a⃠ h⃠o⃠",
        "m⃠a⃠r⃠ n⃠y⃠ k⃠i⃠d⃠d⃠e⃠ t⃠y⃠p⃠e⃠ k⃠r⃠",
        "c⃠h⃠u⃠p⃠ b⃠k⃠l⃠",
        "b⃠c⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠i⃠ c⃠h⃠u⃠t⃠",
        "m⃠c⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ l⃠i⃠k⃠h⃠ f⃠a⃠s⃠t⃠",
        "f⃠a⃠s⃠t⃠ l⃠i⃠k⃠h⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠",
        "f⃠a⃠s⃠t⃠ l⃠i⃠k⃠h⃠ k⃠a⃠m⃠z⃠o⃠r⃠"
        "t⃠e⃠r⃠y⃠ m⃠a⃠k⃠i⃠ c⃠h⃠u⃠t⃠ c⃠l⃠a⃠i⃠m⃠ c⃠r⃠w⃠a⃠",
        "a⃠w⃠z⃠ n⃠i⃠c⃠h⃠e⃠ r⃠a⃠n⃠d⃠c⃠e⃠ k⃠e⃠ b⃠c⃠h⃠e⃠",
        "s⃠a⃠w⃠a⃠l⃠ n⃠y⃠ p⃠u⃠c⃠h⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠a⃠b⃠o⃠s⃠d⃠a⃠",
        "f⃠y⃠t⃠e⃠r⃠ b⃠n⃠e⃠g⃠a⃠ l⃠a⃠g⃠d⃠e⃠ m⃠a⃠d⃠r⃠c⃠h⃠o⃠d⃠",
        "o⃠y⃠e⃠ k⃠a⃠a⃠l⃠e⃠ r⃠o⃠ k⃠e⃠ d⃠i⃠k⃠h⃠a⃠",
        "o⃠y⃠e⃠ k⃠a⃠a⃠l⃠e⃠ r⃠o⃠o⃠ n⃠y⃠",
        "s⃠h⃠o⃠r⃠t⃠ n⃠y⃠ c⃠u⃠d⃠ t⃠u⃠ b⃠i⃠n⃠a⃠ r⃠u⃠k⃠e⃠",
        "s⃠h⃠o⃠r⃠t⃠ n⃠y⃠ c⃠u⃠d⃠ t⃠u⃠ a⃠p⃠n⃠i⃠ m⃠a⃠k⃠o⃠ l⃠e⃠k⃠r⃠",
        "t⃠e⃠r⃠y⃠ m⃠a⃠k⃠e⃠ s⃠t⃠h⃠ t⃠e⃠r⃠y⃠ b⃠h⃠e⃠n⃠ v⃠i⃠ c⃠u⃠d⃠w⃠a⃠ l⃠e⃠",
        "t⃠e⃠r⃠y⃠ m⃠a⃠k⃠e⃠ s⃠t⃠h⃠ t⃠e⃠r⃠y⃠ d⃠i⃠d⃠i⃠ v⃠i⃠ c⃠u⃠d⃠ g⃠a⃠i⃠",
        "C⃠h⃠a⃠t⃠ f⃠y⃠t⃠e⃠r⃠ b⃠n⃠e⃠g⃠a⃠ r⃠a⃠n⃠d⃠c⃠e⃠ c⃠o⃠d⃠u⃠ t⃠e⃠r⃠y⃠ m⃠a⃠k⃠o⃠",
        "b⃠o⃠l⃠ r⃠a⃠n⃠d⃠i⃠b⃠a⃠a⃠z⃠ d⃠a⃠d⃠d⃠y⃠ e⃠y⃠",
        "b⃠u⃠l⃠l⃠y⃠x⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ u⃠t⃠h⃠",
        "m⃠a⃠r⃠ m⃠a⃠r⃠k⃠e⃠ c⃠u⃠d⃠ r⃠h⃠a⃠ t⃠u⃠",
        "o⃠r⃠ t⃠e⃠r⃠y⃠ m⃠a⃠ m⃠a⃠r⃠k⃠e⃠ c⃠u⃠d⃠ g⃠a⃠i⃠"
        "J⃠a⃠l⃠d⃠i⃠ l⃠i⃠k⃠h⃠ r⃠n⃠d⃠y⃠k⃠e⃠ b⃠e⃠j⃠",
        "O⃠r⃠ b⃠d⃠a⃠ l⃠i⃠k⃠h⃠ t⃠m⃠c⃠",
        "O⃠r⃠ b⃠d⃠a⃠ 2⃠ l⃠i⃠n⃠e⃠ w⃠l⃠a⃠ l⃠i⃠k⃠h⃠ t⃠m⃠k⃠c⃠",
        "O⃠r⃠ b⃠d⃠a⃠ o⃠y⃠e⃠ l⃠i⃠k⃠h⃠ t⃠m⃠l⃠",
        "T⃠e⃠r⃠i⃠ m⃠a⃠a⃠ k⃠a⃠ b⃠u⃠r⃠",
        "O⃠y⃠e⃠ k⃠e⃠e⃠d⃠e⃠",
        "R⃠a⃠n⃠d⃠i⃠ k⃠e⃠ l⃠a⃠d⃠k⃠e⃠",
        "J⃠a⃠l⃠d⃠i⃠ l⃠i⃠k⃠h⃠ t⃠e⃠r⃠i⃠ b⃠e⃠h⃠e⃠n⃠ c⃠h⃠o⃠d⃠u⃠",
        "M⃠k⃠l⃠ u⃠t⃠h⃠ r⃠a⃠n⃠d⃠i⃠ k⃠e⃠ b⃠a⃠c⃠c⃠h⃠e⃠",
        "T⃠e⃠r⃠i⃠ n⃠a⃠n⃠i⃠ m⃠e⃠r⃠i⃠ m⃠a⃠a⃠l⃠",
        "T⃠e⃠j⃠ l⃠i⃠k⃠h⃠ r⃠a⃠n⃠d⃠c⃠e⃠",
        "O⃠y⃠e⃠ m⃠a⃠a⃠k⃠e⃠ l⃠o⃠d⃠e⃠ m⃠r⃠e⃠n⃠g⃠a⃠",
        "T⃠e⃠r⃠i⃠ m⃠a⃠a⃠ c⃠h⃠o⃠d⃠y⃠",
        "T⃠e⃠r⃠i⃠ M⃠a⃠i⃠y⃠a⃠ k⃠i⃠ g⃠a⃠n⃠d⃠",
        "T⃠e⃠r⃠y⃠ d⃠a⃠d⃠i⃠ k⃠a⃠ f⃠u⃠d⃠d⃠a⃠",
        "M⃠k⃠l⃠ u⃠t⃠h⃠ b⃠e⃠h⃠e⃠n⃠c⃠o⃠d⃠",
        "T⃠e⃠r⃠i⃠ m⃠a⃠a⃠ k⃠i⃠ b⃠u⃠r⃠ d⃠e⃠",
        "T⃠e⃠r⃠y⃠ m⃠a⃠a⃠ k⃠a⃠ f⃠u⃠d⃠d⃠a⃠ m⃠e⃠ l⃠a⃠u⃠d⃠a⃠",
        "T⃠e⃠r⃠i⃠ m⃠a⃠a⃠ c⃠h⃠u⃠d⃠v⃠a⃠",
        "R⃠a⃠n⃠d⃠i⃠ k⃠e⃠ b⃠e⃠t⃠e⃠ m⃠a⃠r⃠ g⃠a⃠y⃠a⃠",
        "T⃠e⃠r⃠i⃠ m⃠a⃠a⃠ k⃠i⃠ c⃠h⃠u⃠t⃠ m⃠r⃠u⃠",
        "J⃠a⃠l⃠i⃠d⃠ k⃠r⃠ s⃠p⃠a⃠m⃠",
        "M⃠c⃠ s⃠p⃠a⃠m⃠ r⃠o⃠k⃠e⃠n⃠g⃠a⃠",
        "T⃠e⃠r⃠i⃠ m⃠a⃠a⃠k⃠i⃠ c⃠h⃠u⃠t⃠ s⃠p⃠a⃠m⃠ k⃠r⃠",
        "s⃠p⃠a⃠m⃠ k⃠r⃠.⃠m⃠a⃠a⃠k⃠e⃠ l⃠o⃠d⃠e⃠",
        "R⃠a⃠n⃠d⃠y⃠k⃠e⃠ c⃠h⃠o⃠d⃠e⃠ s⃠p⃠a⃠m⃠ k⃠r⃠ w⃠r⃠n⃠a⃠ c⃠u⃠d⃠ t⃠u⃠",
        "S⃠p⃠a⃠m⃠ k⃠r⃠ k⃠i⃠d⃠",
        "N⃠o⃠o⃠b⃠ t⃠e⃠r⃠i⃠ m⃠a⃠a⃠ c⃠h⃠o⃠d⃠u⃠",
        "R⃠n⃠d⃠y⃠k⃠e⃠ b⃠e⃠t⃠e⃠ m⃠a⃠r⃠ m⃠a⃠t⃠ t⃠u⃠",
        "N⃠o⃠o⃠b⃠ j⃠a⃠l⃠d⃠i⃠ l⃠i⃠k⃠h⃠ w⃠r⃠n⃠a⃠ t⃠e⃠r⃠y⃠ m⃠a⃠a⃠ r⃠a⃠n⃠d⃠",
        "c⃠u⃠d⃠ g⃠a⃠i⃠ m⃠a⃠a⃠ t⃠e⃠r⃠y⃠ n⃠o⃠o⃠b⃠",
        "u⃠t⃠h⃠ r⃠a⃠n⃠d⃠y⃠k⃠e⃠ n⃠o⃠o⃠b⃠",
        "c⃠h⃠l⃠ c⃠u⃠d⃠k⃠e⃠ d⃠i⃠k⃠h⃠a⃠ n⃠o⃠o⃠b⃠",
        "j⃠l⃠d⃠i⃠ t⃠y⃠p⃠ c⃠r⃠ n⃠o⃠o⃠b⃠ h⃠a⃠l⃠k⃠e⃠",
        "c⃠u⃠d⃠ k⃠e⃠ p⃠g⃠l⃠ n⃠y⃠ h⃠o⃠ n⃠o⃠o⃠b⃠",
        "c⃠u⃠d⃠ c⃠u⃠d⃠ k⃠e⃠ r⃠a⃠n⃠d⃠ b⃠n⃠j⃠a⃠ t⃠u⃠ n⃠o⃠o⃠b⃠",
        "m⃠a⃠k⃠i⃠c⃠h⃠u⃠t⃠ t⃠e⃠r⃠y⃠ n⃠o⃠o⃠b⃠",
        "g⃠a⃠n⃠d⃠a⃠ c⃠y⃠u⃠ c⃠u⃠d⃠ r⃠h⃠a⃠ t⃠u⃠ ?",
        "i⃠t⃠n⃠a⃠ g⃠n⃠d⃠a⃠ n⃠y⃠ c⃠u⃠d⃠ a⃠c⃠h⃠e⃠ s⃠e⃠ c⃠u⃠d⃠",
        "M⃠a⃠a⃠n⃠ l⃠e⃠ c⃠u⃠d⃠ g⃠y⃠a⃠ t⃠u⃠ s⃠u⃠n⃠ b⃠a⃠t⃠ a⃠b⃠",
        "m⃠a⃠k⃠a⃠f⃠u⃠d⃠d⃠a⃠ f⃠a⃠t⃠ g⃠y⃠a⃠ t⃠e⃠r⃠y⃠ r⃠u⃠k⃠",
        ]
        bs_texts = [
        "ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓅ᕗ ᕙ𝒷ᕗᕙ𝒽ᕗᕙ𝒾ᕗ ᕙ𝒷ᕗᕙ𝓃ᕗᕙ𝒶ᕗᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝓂ᕗᕙ𝓊ᕗᕙ𝒿ᕗᕙ𝑒ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝑒ᕗ",
        "ᕙ𝒯ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒶ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓅ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓏ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝓎ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝒹ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗᕙ𝒿ᕗᕙ𝒽ᕗᕙ𝑒ᕗ",
        "ᕙ𝒯ᕗᕙ𝓊ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙℳᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝒶ᕗ ᕙ𝓃ᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝓎ᕗᕙ𝓂ᕗᕙ𝓅ᕗᕙ𝒶ᕗᕙ𝓈ᕗᕙ𝓈ᕗ",
        "ᕙ𝒪ᕗᕙ𝓎ᕗᕙ𝑒ᕗ ᕙ𝓊ᕗᕙ𝓃ᕗᕙ𝒻ᕗᕙ𝓊ᕗᕙ𝓃ᕗᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝓈ᕗᕙ𝓌ᕗᕙ𝒾ᕗᕙ𝓅ᕗᕙ𝑒ᕗ ᕙ𝓂ᕗᕙ𝓉ᕗᕙ𝓉ᕗ ᕙ𝓀ᕗᕙ𝓇ᕗ",
        "ᕙ𝒪ᕗᕙ𝒽ᕗ ᕙ𝒽ᕗᕙ𝑒ᕗᕙ𝓁ᕗᕙ𝓁ᕗᕙ𝑜ᕗ ᕙ𝒷ᕗᕙ𝒾ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒶ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓅ᕗ ᕙ𝒷ᕗᕙ𝒾ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝑜ᕗᕙ𝓇ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝓋ᕗ ᕙ𝒷ᕗᕙ𝒾ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝒶ᕗᕙ𝓊ᕗᕙ𝓀ᕗᕙ𝒶ᕗᕙ𝓉ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗ ᕙ𝓇ᕗᕙ𝒽ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝓇ᕗ.",
        "ᕙ𝒪ᕗᕙ𝓎ᕗᕙ𝓎ᕗ ᕙ𝓀ᕗᕙ𝒾ᕗᕙ𝓃ᕗᕙ𝓃ᕗᕙ𝑒ᕗᕙ𝓇ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗᕙ𝒿ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙℊᕗᕙ𝒸ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗ ᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝑒ᕗ ᕙ𝓀ᕗᕙ𝒾ᕗ ᕙ𝓅ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓂ᕗᕙ𝒾ᕗᕙ𝓈ᕗᕙ𝓈ᕗᕙ𝒾ᕗᕙ𝑜ᕗᕙ𝓃ᕗ ᕙ𝓀ᕗᕙ𝒾ᕗᕙ𝓈ᕗᕙ𝓃ᕗᕙ𝑒ᕗ ᕙ𝒹ᕗᕙ𝒾ᕗ.",
        "ᕙ𝒞ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒽ᕗᕙ𝒶ᕗ",
        "ᕙ𝒞ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒽ᕗᕙ𝒶ᕗ ᕙ𝑒ᕗᕙ𝓀ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓇ᕗ.",
        "ᕙ𝒮ᕗᕙ𝓊ᕗᕙ𝓃ᕗ ᕙ𝒮ᕗᕙ𝓊ᕗᕙ𝓃ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝒶ᕗ.",
        "ᕙ𝒯ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒸ᕗᕙ𝒶ᕗ ᕙ𝒷ᕗᕙ𝒽ᕗᕙ𝑜ᕗᕙ𝓈ᕗᕙ𝒹ᕗᕙ𝒶ᕗ.",
        "ᕙ𝒪ᕗᕙ𝓎ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑜ᕗᕙ𝓉ᕗᕙ𝒾ᕗ ᕙ𝒿ᕗᕙ𝒶ᕗᕙ𝓉ᕗᕙ𝒾ᕗ ᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝓉ᕗᕙ𝓂ᕗᕙ𝓇ᕗ.",
        "ᕙ𝒦ᕗᕙ𝓎ᕗ? ᕙ𝒿ᕗᕙ𝓁ᕗᕙ𝒹ᕗᕙ𝒾ᕗ ᕙ𝓁ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒽ᕗ ᕙ𝓀ᕗᕙ𝒾ᕗᕙ𝒹ᕗᕙ𝒹ᕗᕙ𝑒ᕗ.",
        "ᕙℬᕗᕙ𝒾ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝒸ᕗᕙ𝑜ᕗᕙ𝓂ᕗ ᕙℊᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙℊᕗ ᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓅ᕗ ᕙ𝓀ᕗᕙ𝑜ᕗ ᕙ𝓉ᕗᕙ𝒶ᕗᕙℊᕗ ᕙ𝒸ᕗᕙ𝓇ᕗᕙ𝑒ᕗᕙℊᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ",
        "ᕙℳᕗᕙ𝓊ᕗᕙ𝒿ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝒷ᕗᕙ𝒾ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝓂ᕗᕙ𝓀ᕗᕙ𝒸ᕗ ᕙ𝒷ᕗᕙ𝓈ᕗ",
        "ᕙ𝒥ᕗᕙ𝒶ᕗᕙ𝓁ᕗᕙ𝒹ᕗᕙ𝒾ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓏ᕗ ᕙ𝓅ᕗᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝒶ᕗ ᕙ𝒷ᕗᕙ𝑜ᕗᕙ𝓁ᕗ",
        "ᕙ𝒮ᕗᕙ𝒾ᕗᕙ𝒹ᕗᕙ𝑒ᕗ ᕙ𝒽ᕗᕙ𝑜ᕗᕙ𝒿ᕗᕙ𝒶ᕗ ᕙ𝒷ᕗᕙ𝒾ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝒶ᕗᕙ𝒾ᕗ ᕙ𝒶ᕗᕙ𝒷ᕗ",
        "ᕙℋᕗᕙ𝓎ᕗᕙ𝑒ᕗ ᕙ𝓅ᕗᕙℊᕗᕙ𝓁ᕗ ᕙ𝒷ᕗᕙ𝒽ᕗᕙℊᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝓉ᕗ ᕙ𝒶ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗ",
        "ᕙ𝒷ᕗᕙ𝒽ᕗᕙℊᕗ ᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝒶ᕗᕙ𝒿ᕗᕙ𝒿ᕗ",
        "ᕙℋᕗᕙ𝓎ᕗᕙ𝑒ᕗ ᕙ𝓅ᕗᕙℊᕗᕙ𝓁ᕗ ᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒷ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙ𝒷ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙℊᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝓉ᕗ",
        "ᕙℋᕗᕙ𝓎ᕗᕙ𝑒ᕗ ᕙ𝒹ᕗᕙ𝓊ᕗᕙ𝓇ᕗ ᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓉ᕗᕙ𝓉ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒹ᕗᕙ𝒽ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑜ᕗᕙ𝒹ᕗ ᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑒ᕗ",
        "ᕙ𝓀ᕗᕙ𝑜ᕗᕙ𝒾ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝓉ᕗ ᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝑒ᕗᕙ𝓈ᕗᕙ𝓁ᕗᕙ𝒾ᕗᕙ𝓎ᕗᕙ𝑒ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒻ᕗ ᕙ𝒸ᕗᕙ𝓇ᕗ ᕙ𝓇ᕗᕙ𝒽ᕗᕙ𝒶ᕗ ᕙ𝒽ᕗᕙ𝓊ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗᕙ𝒿ᕗᕙ𝒽ᕗᕙ𝑒ᕗ",
        "ᕙ𝓀ᕗᕙ𝑜ᕗᕙ𝒾ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓉ᕗ ᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ𝒶ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒻ᕗᕙ𝒾ᕗ ᕙ𝒹ᕗᕙ𝑒ᕗ ᕙ𝒹ᕗᕙ𝓊ᕗᕙ𝓃ᕗᕙℊᕗᕙ𝒶ᕗ",
        "ᕙ𝒜ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ??ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒻ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒾ᕗᕙ𝓁ᕗ ᕙ𝒿ᕗᕙ𝒶ᕗᕙ𝓎ᕗᕙ𝑒ᕗᕙℊᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗᕙ𝒿ᕗᕙ𝒽ᕗᕙ𝑒ᕗ",
        "ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝓉ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝓊ᕗᕙ𝒿ᕗᕙ𝑒ᕗ ᕙ𝓈ᕗᕙ𝓌ᕗᕙ𝒾ᕗᕙ𝓅ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝓇ᕗᕙ𝓀ᕗᕙ𝑒ᕗ",
        "ᕙ𝒜ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝓈ᕗᕙ𝓌ᕗᕙ𝒾ᕗᕙ𝓅ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝓇ᕗᕙ𝓀ᕗᕙ𝑒ᕗ",
        "ᕙℱᕗᕙ𝓇ᕗ ᕙ𝒷ᕗᕙ𝑜ᕗᕙ𝓁ᕗᕙ𝓃ᕗᕙ𝒶ᕗ ᕙ𝓃ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝒾ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ𝒶ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝓈ᕗᕙ𝓌ᕗᕙ𝒾ᕗᕙ𝓅ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝓇ᕗᕙ𝓀ᕗᕙ𝑒ᕗ",
        "ᕙ𝒞ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝓎ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ𝓅ᕗᕙ𝓇ᕗ ᕙ𝓀ᕗᕙ𝑒ᕗᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝓎ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ",
        "ᕙ𝓂ᕗᕙ𝓊ᕗᕙ𝒿ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙ𝓅ᕗᕙ𝓉ᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝒽ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝒶ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ𝓂ᕗᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝓉ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝓎ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗ",
        "ᕙ𝓁ᕗᕙ𝑜ᕗᕙ𝒹ᕗᕙ𝑒ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝓊ᕗᕙ𝓉ᕗᕙ𝓇ᕗ ᕙ𝓂ᕗᕙ𝒸ᕗ",
        "ᕙ𝓁ᕗᕙ𝓊ᕗᕙ𝓃ᕗ ᕙ𝓂ᕗᕙ𝓉ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓈ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒶ᕗ",
        "ᕙ𝓃ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒶ᕗᕙ𝓁ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒹ᕗᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝒹ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗ ᕙ𝑜ᕗᕙ𝓎ᕗᕙ𝑒ᕗ ᕙℊᕗᕙ𝒶ᕗᕙ𝓈ᕗᕙ𝒽ᕗᕙ𝓉ᕗᕙ𝒾ᕗ ᕙ𝓀ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑒ᕗ",
        "ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝓀ᕗᕙ𝒾ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓉ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝓀ᕗᕙ𝑒ᕗ",
        "ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ",
        "ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗ ᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓉ᕗᕙ𝒽ᕗ ᕙ𝓉ᕗᕙ𝑜ᕗᕙ𝒹ᕗᕙ𝒽ᕗ ᕙ𝓀ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝑒ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓅ᕗ ᕙ𝓀ᕗ ᕙ𝓂ᕗᕙ𝓊ᕗᕙ𝒽ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗ ᕙ𝒻ᕗᕙ𝒶ᕗᕙ𝓈ᕗᕙ𝒶ᕗᕙ𝒹ᕗᕙ𝓊ᕗᕙ𝓃ᕗᕙℊᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝓀ᕗᕙ𝑒ᕗ",
        "ᕙ𝓁ᕗᕙ𝑒ᕗᕙ𝒶ᕗᕙ𝓋ᕗᕙ𝑒ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝓅ᕗᕙ𝒶ᕗᕙ𝓈ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗ ᕙ𝓃ᕗᕙ𝒶ᕗᕙ𝒾ᕗ ᕙ𝒶ᕗᕙ??ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗᕙ𝓀ᕗᕙ𝑜ᕗ",
        "ᕙ𝓁ᕗᕙ𝑒ᕗᕙ𝒶ᕗᕙ𝓋ᕗᕙ𝑒ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒾ᕗᕙ𝒹ᕗᕙ𝑒ᕗᕙ𝓇ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ",
        "ᕙ𝓁ᕗᕙ𝑒ᕗᕙ𝒶ᕗᕙ𝓋ᕗᕙ𝑒ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝒿ᕗᕙ𝓁ᕗᕙ𝒹ᕗᕙ𝒾ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝓌ᕗᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝒶ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ𝓁ᕗᕙ𝑒ᕗᕙ𝒶ᕗᕙ𝓋ᕗᕙ𝑒ᕗ ᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗᕙℊᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ𝒮ᕗᕙ𝓂ᕗᕙ𝒿ᕗᕙ𝒽ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝓉ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗᕙ𝒶ᕗᕙ𝓋ᕗᕙ𝑒ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗ",
        "ᕙ𝒻ᕗᕙ𝒶ᕗᕙ𝓈ᕗᕙ𝓉ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗᕙ𝒶ᕗᕙ𝓋ᕗᕙ𝑒ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝓀ᕗᕙ𝒶ᕗᕙ𝓂ᕗᕙ𝒿ᕗᕙ𝑜ᕗᕙ𝓇ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝓀ᕗᕙ𝑒ᕗ",
        "ᕙ𝓉ᕗᕙ𝓊ᕗᕙ𝓉ᕗᕙ𝑜ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝓀ᕗ",
        "ᕙ𝑜ᕗᕙ𝓎ᕗ ᕙ𝒽ᕗᕙ𝒾ᕗᕙ𝒿ᕗᕙ𝒹ᕗᕙ𝑒ᕗ ᕙ𝓀ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝒽ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝒶ᕗᕙ𝓂ᕗᕙ𝓏ᕗᕙ𝑜ᕗᕙ𝓇ᕗ",
        "ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝓀ᕗᕙ𝑜ᕗ ᕙ𝒾ᕗᕙ𝓁ᕗᕙ𝓎ᕗ ᕙ𝓇ᕗᕙ𝑒ᕗᕙ𝓎ᕗ 🌚😂",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓅ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙ𝓉ᕗᕙ𝓂ᕗᕙ𝓀ᕗᕙ𝒸ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓅ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ𝒶ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ",
        "ᕙ𝓈ᕗᕙ𝒽ᕗᕙ𝒾ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ𝒶ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓅ᕗ",
        "ᕙ𝒻ᕗᕙ𝓇ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ??ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓅ᕗ",
        "ᕙ𝓈ᕗᕙ𝒽ᕗᕙ𝒾ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝓁ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒽ᕗ ᕙ𝓌ᕗᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝒶ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝓊ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝒶ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓅ᕗ",
        "ᕙ𝓅ᕗᕙ𝓇ᕗᕙ𝑜ᕗᕙ𝑜ᕗᕙ𝒻ᕗ ᕙ𝒸ᕗᕙ𝓇ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝓎ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ𝓅ᕗᕙ𝓇ᕗᕙ𝑜ᕗᕙ𝑜ᕗᕙ𝒻ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ",
        "ᕙ𝓅ᕗᕙ𝓇ᕗᕙ𝑜ᕗᕙ𝑜ᕗᕙ𝒻ᕗ ᕙ𝒽ᕗᕙ𝑜ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓀ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝒾ᕗᕙ𝓁ᕗᕙ𝓁ᕗᕙ𝒶ᕗᕙ𝓇ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗ ᕙ𝒷ᕗᕙ𝑜ᕗᕙ𝓈ᕗᕙ𝒹ᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ??ᕗᕙ𝓎ᕗ ᕙ𝒽ᕗᕙ𝒾ᕗᕙ𝒿ᕗᕙ𝒹ᕗᕙ𝑒ᕗ ᕙ𝓀ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝒽ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝒶ᕗᕙ𝓂ᕗᕙ𝓏ᕗᕙ𝑜ᕗᕙ𝓇ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒹ᕗᕙ𝓇ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑜ᕗᕙ𝒹ᕗ ?",
        "ᕙ𝒶ᕗᕙ𝒷ᕗ ᕙ𝓉ᕗᕙ𝓀ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝓎ᕗᕙ𝒾ᕗ ᕙ𝒽ᕗᕙ𝑜ᕗᕙℊᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ?",
        "ᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗ ᕙ𝓀ᕗᕙ𝓊ᕗᕙ𝒸ᕗᕙ𝒽ᕗ ᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝒿ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝓉ᕗᕙ𝒶ᕗ ᕙ𝒷ᕗᕙ𝓈ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ",
        "ᕙ𝒮ᕗᕙ𝒷ᕗᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝓅ᕗᕙ𝒽ᕗᕙ𝑒ᕗᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝑜ᕗ ᕙ𝒷ᕗᕙ𝑜ᕗᕙ𝓁ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓃ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝒶ᕗᕙ𝓂ᕗ ᕙ𝓀ᕗᕙ𝓇ᕗᕙ𝑒ᕗ",
        "ᕙ𝓎ᕗᕙ𝒶ᕗᕙ𝒽ᕗᕙ𝒶ᕗ ᕙ𝒷ᕗᕙ𝒽ᕗᕙ𝒾ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝒸ᕗᕙ𝑒ᕗ ᕙ𝓅ᕗᕙ𝒾ᕗᕙ𝓁ᕗᕙ𝓁ᕗᕙ𝑒ᕗ",
        "ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝓀ᕗᕙ𝒶ᕗᕙ𝒷ᕗᕙ𝑜ᕗᕙ𝓈ᕗᕙ𝒹ᕗᕙ𝒶ᕗ",
        "ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑜ᕗ ᕙ𝒷ᕗᕙ𝒽ᕗᕙ𝑒ᕗᕙ𝓃ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝑒ᕗᕙℊᕗᕙ𝒾ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝓅ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝓉ᕗᕙ𝑜ᕗᕙ𝓂ᕗᕙ𝓂ᕗᕙ𝓎ᕗ",
        "ᕙ𝓃ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒶ᕗᕙ𝓁ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒹ᕗᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝒹ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝓎ᕗᕙ𝒽ᕗᕙ𝒶ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ",
        "ᕙ𝒸ᕗᕙ𝑜ᕗᕙ𝓏ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒽ᕗᕙ𝒾ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒾ᕗ ᕙ𝒽ᕗᕙ𝑒ᕗ",
        "ᕙ𝓃ᕗᕙ𝓎ᕗᕙ𝓉ᕗᕙ𝑜ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓅ᕗ ᕙ𝒷ᕗᕙ𝑜ᕗᕙ𝓁ᕗ ᕙ𝓂ᕗᕙ𝓊ᕗᕙ𝒿ᕗᕙ𝒽ᕗᕙ𝑒ᕗ",
        "ᕙ𝓃ᕗᕙ𝓎ᕗᕙ𝓃ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒽ᕗᕙ𝑜ᕗᕙℊᕗᕙ𝒾ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝒾ᕗ ᕙ𝒿ᕗᕙ𝑜ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ𝒶ᕗᕙ𝓉ᕗᕙ𝒾ᕗ ᕙ𝒿ᕗᕙ𝑜ᕗᕙℊᕗᕙ𝒾ᕗ",
        "ᕙ𝓉ᕗᕙ𝓇ᕗᕙ𝓎ᕗ ᕙ𝒶ᕗᕙ𝓂ᕗᕙ𝓂ᕗᕙ𝒾ᕗ ᕙ𝒸ᕗᕙ𝑒ᕗ ᕙ𝒷ᕗᕙ𝒽ᕗᕙ𝑜ᕗᕙ𝓈ᕗᕙ𝒹ᕗᕙ𝑒ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗ ᕙ𝑒ᕗᕙ𝓂ᕗᕙ𝑜ᕗᕙ𝒿ᕗᕙ𝒾ᕗ ᕙ𝒹ᕗᕙ𝒶ᕗᕙ𝓁ᕗ ᕙ𝓂ᕗᕙ𝒸ᕗ",
        "ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ? ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓂ᕗᕙ𝓇ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝓎ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ?",
        "ᕙ𝓉ᕗᕙ𝓂ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝒽ᕗᕙ𝑜ᕗᕙℊᕗᕙ𝒾ᕗ ᕙ𝒻ᕗᕙ𝓇ᕗᕙ𝓇ᕗᕙ𝓉ᕗᕙ𝑜ᕗ",
        "ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ? ᕙ𝓀ᕗᕙ𝒷ᕗ ? ᕙ𝓅ᕗᕙℊᕗᕙ𝓁ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓀ᕗᕙ𝑒ᕗᕙ𝓀ᕗ",
        "ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ᕙ𝓈ᕗᕙ𝒸ᕗᕙ𝒽ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝓅ᕗᕙℊᕗᕙ𝓁ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝓎ᕗᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ𝒶ᕗ ᕙ𝓁ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗᕙ𝓃ᕗᕙ𝑒ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ",
        "ᕙ𝒾ᕗᕙ𝓉ᕗᕙ𝓃ᕗᕙ𝒶ᕗ ᕙ𝓈ᕗᕙ𝒸ᕗᕙ𝒽ᕗ ᕙ𝓃ᕗᕙ??ᕗ ᕙ𝒷ᕗᕙ𝑜ᕗᕙ𝓁ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝒶ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝓎ᕗ",
        "ᕙ𝓈ᕗᕙ𝒸ᕗᕙ𝒽ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝓅ᕗᕙℊᕗᕙ𝓁ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝓉ᕗᕙ𝓊ᕗ ᕙ𝒶ᕗᕙ𝓅ᕗᕙ𝓃ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓌ᕗᕙ𝒶ᕗ ᕙ𝓁ᕗᕙ𝒾ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝑒ᕗ ᕙ𝓈ᕗᕙ𝓉ᕗᕙ𝒽ᕗ",
        "ᕙ𝓂ᕗᕙ𝓉ᕗᕙ𝓁ᕗᕙ𝒷ᕗ ᕙ𝓉ᕗᕙ𝓂ᕗᕙ𝓇ᕗ",
        "ᕙ𝓃ᕗᕙ𝓎ᕗᕙ𝓉ᕗᕙ𝑜ᕗ",
        "ᕙ𝓅ᕗᕙ𝓊ᕗᕙ𝓇ᕗᕙ𝒶ᕗ ᕙ𝓁ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒽ᕗ ᕙ𝓂ᕗᕙ𝒸ᕗ",
        "ᕙ𝓉ᕗᕙ𝓂ᕗᕙ𝓇ᕗ ᕙ𝒻ᕗᕙ𝓇ᕗᕙ𝓇ᕗᕙ𝓉ᕗᕙ𝑜ᕗ",
        "ᕙ𝑜ᕗᕙ𝒽ᕗ ᕙ𝑜ᕗᕙ𝓀ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝒻ᕗᕙ𝒾ᕗᕙ𝓇ᕗ",
        "ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝒶ᕗ ᕙ𝒹ᕗᕙ𝒶ᕗᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒹ᕗ",
        "ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ? ᕙ𝒶ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝓁ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙ𝓅ᕗᕙ𝑒ᕗᕙ𝒽ᕗᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝑒ᕗᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑒ᕗ",
        "ᕙ𝓃ᕗᕙ𝓎ᕗᕙ𝓉ᕗᕙ𝑜ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑜ᕗᕙ𝒹ᕗᕙ𝓃ᕗᕙ𝑒ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗ ᕙ𝓋ᕗᕙ𝓎ᕗᕙ𝒶ᕗᕙ𝓈ᕗᕙ𝓉ᕗ ᕙ𝒽ᕗᕙ𝓊ᕗ",
        "ᕙ𝓃ᕗᕙ𝓎ᕗᕙ𝓉ᕗᕙ𝑜ᕗ ᕙ𝓅ᕗᕙℊᕗᕙ𝓁ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ᕙ𝓀ᕗᕙ𝓊ᕗᕙ𝒸ᕗᕙ𝒽ᕗ ᕙ𝒷ᕗᕙ𝒾ᕗ",
        "ᕙ𝑜ᕗᕙ𝓎ᕗᕙ𝑒ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ? ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙℊᕗᕙ𝓎ᕗᕙ𝒶ᕗ ?",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙ𝓂ᕗᕙ𝓉ᕗ ᕙ𝒽ᕗᕙ𝓈ᕗᕙ𝓈ᕗ",
        "ᕙ𝓎ᕗᕙ𝓊ᕗᕙ𝓇ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝑜ᕗᕙ𝓂ᕗ",
        "ᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝑒ᕗ ᕙ𝓈ᕗᕙ𝒷ᕗᕙ𝓀ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝒾ᕗ ᕙ𝑜ᕗᕙ𝓇ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝒷ᕗᕙ𝒾ᕗ",
        "ᕙ𝒶ᕗᕙ𝓇ᕗᕙ𝑒ᕗ ᕙ𝒾ᕗᕙ𝒹ᕗᕙ𝒶ᕗᕙ𝓇ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝑒ᕗᕙ𝓀ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓇ᕗ",
        "ᕙ𝓉ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒾ᕗ ᕙ𝓉ᕗᕙ𝓇ᕗᕙ𝒽ᕗ",
        "ᕙ𝑒ᕗᕙ𝓀ᕗ ᕙ𝓁ᕗᕙ𝒾ᕗᕙ𝓃ᕗᕙ𝑒ᕗ ᕙ𝓂ᕗᕙ𝑒ᕗ ᕙ𝓉ᕗᕙ𝓂ᕗᕙ𝓇ᕗ",
        "ᕙ𝒬ᕗ",
        "ᕙ𝑜ᕗᕙ𝒸ᕗᕙ𝓎ᕗ ᕙ𝒶ᕗᕙ𝒷ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝓁ᕗᕙ𝑒ᕗ",
        "ᕙ𝓅ᕗᕙ𝑒ᕗᕙ𝒽ᕗᕙ𝑒ᕗᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝓉ᕗᕙ𝑒ᕗᕙ𝓇ᕗᕙ𝒾ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝑜ᕗᕙ𝒹ᕗᕙ𝓊ᕗ",
        "ᕙ𝓃ᕗᕙ𝓎ᕗᕙ𝓉ᕗᕙ𝑜ᕗ",
        "ᕙ𝓆ᕗ ?",
        "ᕙ𝒽ᕗᕙ𝓎ᕗᕙ𝓎ᕗᕙ𝓎ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒶ᕗ ᕙ𝑒ᕗᕙ𝓀ᕗ ᕙ𝒷ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓇ᕗ",
        "ᕙ𝑜ᕗᕙ𝓎ᕗᕙ𝑒ᕗᕙ𝑒ᕗ ᕙ𝓈ᕗᕙ𝓊ᕗᕙ𝓃ᕗ ᕙ𝒹ᕗᕙ𝑜ᕗᕙ𝓈ᕗᕙ𝓉ᕗ ᕙ𝓉ᕗᕙ𝓂ᕗᕙ𝓇ᕗ",
        "ᕙ𝒷ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙℊᕗ ᕙ𝒿ᕗᕙ𝒶ᕗ ᕙ𝓇ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓃ᕗᕙ𝒹ᕗ ᕙ𝓂ᕗᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝒻ᕗ ᕙ𝒸ᕗᕙ𝓇ᕗᕙ𝓇ᕗ ᕙ𝒹ᕗᕙ𝓊ᕗᕙ𝓃ᕗᕙℊᕗᕙ𝒶ᕗ",
        "ᕙ𝑜ᕗᕙ𝓎ᕗᕙ𝑒ᕗᕙ𝑒ᕗ ᕙ𝓅ᕗᕙℊᕗᕙ𝓁ᕗ ᕙ𝓇ᕗᕙ𝓃ᕗᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝒾ᕗ ᕙ𝒾ᕗᕙ𝒹ᕗᕙ𝒶ᕗᕙ𝓇ᕗ ᕙ𝒶ᕗᕙ𝒶ᕗ",
        "ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ᕙ𝓉ᕗᕙ𝓂ᕗᕙ𝓇ᕗ ᕙ𝒻ᕗᕙ𝓇ᕗᕙ𝓇ᕗᕙ𝓉ᕗᕙ𝑜ᕗ",
        "ᕙ𝑜ᕗᕙ𝓎ᕗᕙ𝑒ᕗᕙ𝑒ᕗ ᕙ𝒾ᕗᕙ𝒹ᕗᕙ𝒶ᕗᕙ𝓇ᕗ ᕙ𝒶ᕗᕙ𝒶ᕗᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓂ᕗᕙ𝓇ᕗ",
        "ᕙ𝓃ᕗᕙ𝓎ᕗᕙ𝓉ᕗᕙ𝑜ᕗ ᕙ𝒶ᕗᕙ𝑒ᕗᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝒽ᕗᕙ𝒾ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗ",
        "ᕙ𝑜ᕗᕙ𝓎ᕗᕙ𝑒ᕗᕙ𝑒ᕗ ᕙ𝒽ᕗᕙ𝓎ᕗᕙ𝓎ᕗ ᕙ𝒶ᕗᕙ𝒾ᕗᕙ𝓈ᕗᕙ𝑒ᕗ ᕙ𝒽ᕗᕙ𝒾ᕗ ᕙ𝒸ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗᕙ𝓃ᕗᕙ𝒶ᕗ",
        "ᕙ𝑜ᕗᕙ𝓇ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙ𝓁ᕗᕙ𝑒ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙ𝓀ᕗᕙ𝑒ᕗ ᕙ𝒹ᕗᕙ𝒾ᕗᕙ𝓀ᕗᕙ𝒶ᕗ ᕙ𝑜ᕗᕙ𝓇ᕗ",
        "ᕙ𝒽ᕗᕙ𝓎ᕗᕙ𝓎ᕗ ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝑜ᕗ ᕙ𝓃ᕗᕙ𝒶ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗᕙ𝑜ᕗ ᕙ𝓂ᕗᕙ𝓉ᕗ ᕙ𝒷ᕗᕙ𝒽ᕗᕙ𝒶ᕗᕙℊᕗ ᕙ𝒿ᕗᕙ𝒶ᕗᕙ𝑜ᕗ",
        "ᕙ𝒷ᕗᕙ𝓎ᕗᕙ𝓎ᕗᕙ𝑒ᕗᕙ𝑒ᕗ ᕙ𝒽ᕗᕙ𝓎ᕗᕙ𝓎ᕗ ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ?",
        "ᕙ𝒬ᕗᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙ𝒬ᕗ ᕙ𝓇ᕗᕙ𝒽ᕗᕙ𝑒ᕗ ᕙ𝒽ᕗᕙ𝑜ᕗ ?",
        "ᕙ𝓅ᕗᕙℊᕗᕙ𝓁ᕗ ᕙ𝑒ᕗᕙ𝓎ᕗ ᕙ𝒸ᕗᕙ𝓎ᕗᕙ𝒶ᕗ ᕙ𝓂ᕗᕙ𝒸ᕗ",
        "ᕙ𝒸ᕗᕙ𝒽ᕗᕙ𝓊ᕗᕙ𝒹ᕗ ᕙ𝓂ᕗᕙ𝓉ᕗ",
        ]
        bs2_texts = [
        "⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇮​⋰⋰🇮​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇰​⋰⋰🇦​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇸​⋰⋰🇪​⋰⋰🇼​⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇮​⋰⋰🇰​⋰⋰🇪​⋰⋰🇧​⋰⋰🇦​⋰⋰🇨​⋰⋰🇭​⋰⋰🇪​⋰, ⋰🇹​⋰⋰🇺​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇮​⋰ ⋰🇰​⋰⋰🇮​⋰⋰🇸​⋰⋰🇸​⋰⋰🇦​⋰⋰🇬​⋰⋰🇦​⋰",
        "⋰🇦​⋰⋰🇦​⋰⋰🇯​⋰ ⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇮​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇰​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇹​⋰, ⋰🇹​⋰⋰🇺​⋰ ⋰🇰​⋰⋰🇾​⋰⋰🇦​⋰ ⋰🇭​⋰⋰🇦​⋰⋰🇮​⋰",
        "⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇩​⋰⋰🇷​⋰⋰🇨​⋰⋰🇭​⋰⋰🇴​⋰⋰🇩​⋰, ⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇮​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇰​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇹​⋰",
        "⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇮​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇪​⋰⋰🇳​⋰ ⋰🇰​⋰⋰🇮​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇹​⋰, ⋰🇹​⋰⋰🇺​⋰ ⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇮​⋰",
        "⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇩​⋰ ⋰🇯​⋰⋰🇦​⋰, ⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇮​⋰ ⋰🇩​⋰⋰🇮​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇮​⋰",
        "⋰🇸​⋰⋰🇱​⋰⋰🇴​⋰⋰🇼​⋰, ⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇮​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇮​⋰⋰🇾​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇮​⋰⋰🇴​⋰⋰🇩​⋰⋰🇺​⋰",
        "⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰, ⋰🇹​⋰⋰🇺​⋰ ⋰🇰​⋰⋰🇾​⋰⋰🇦​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇸​⋰⋰🇰​⋰⋰🇹​⋰⋰🇦​⋰",
        "⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇰​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰, ⋰🇹​⋰⋰🇲​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇴​⋰⋰🇩​⋰⋰🇺​⋰",
        "⋰🇸​⋰⋰🇱​⋰⋰🇴​⋰⋰🇼​⋰ ⋰🇫​⋰⋰🇮​⋰⋰🇷​⋰⋰🇸​⋰⋰🇪​⋰, ⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇮​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇰​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇹​⋰",
        "⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇬​⋰⋰🇷​⋰⋰🇮​⋰⋰🇧​⋰, ⋰🇹​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇲​⋰⋰🇦​⋰ ⋰🇩​⋰⋰🇴​⋰⋰🇺​⋰",
        "⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇨​⋰⋰🇴​⋰⋰🇩​⋰⋰🇺​⋰, ⋰🇳​⋰⋰🇪​⋰⋰🇹​⋰ ⋰🇴​⋰⋰🇳​⋰ ⋰🇴​⋰⋰🇫​⋰⋰🇫​⋰ ⋰🇼​⋰⋰🇦​⋰⋰🇱​⋰⋰🇮​⋰ ⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰",
        "⋰🇴​⋰⋰🇾​⋰⋰🇪​⋰ ⋰🇹​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇲​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇴​⋰⋰🇩​⋰⋰🇺​⋰, ⋰🇮​⋰⋰🇩​⋰⋰🇭​⋰⋰🇦​⋰⋰🇷​⋰ ⋰🇦​⋰⋰🇦​⋰⋰🇰​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰",
        "⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇷​⋰⋰🇩​⋰⋰🇺​⋰, ⋰🇴​⋰⋰🇮​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇦​⋰⋰🇰​⋰⋰🇪​⋰ ⋰🇱​⋰⋰🇴​⋰⋰🇩​⋰⋰🇪​⋰⋰🇪​⋰",
        "⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇪​⋰⋰🇯​⋰, ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇴​⋰⋰🇩​⋰⋰🇺​⋰",
        "⋰🇸​⋰⋰🇺​⋰⋰🇦​⋰⋰🇷​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇪​⋰⋰🇯​⋰, ⋰🇳​⋰⋰🇪​⋰⋰🇹​⋰ ⋰🇴​⋰⋰🇫​⋰⋰🇫​⋰ ⋰🇴​⋰⋰🇳​⋰ ⋰🇰​⋰⋰🇷​⋰ ⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰ ⋰🇱​⋰⋰🇦​⋰⋰🇩​⋰⋰🇰​⋰⋰🇪​⋰",
        "⋰🇹​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇲​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇰​⋰⋰🇪​⋰⋰🇸​⋰⋰🇪​⋰, ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇵​⋰ ⋰🇸​⋰⋰🇱​⋰⋰🇴​⋰⋰🇼​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇩​⋰⋰🇭​⋰⋰🇦​⋰⋰🇷​⋰⋰🇨​⋰⋰🇴​⋰⋰🇩​⋰",
        "⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇨​⋰⋰🇴​⋰⋰🇩​⋰⋰🇺​⋰ ⋰🇰​⋰⋰🇷​⋰ ⋰🇲​⋰⋰🇸​⋰⋰🇬​⋰ ⋰🇩​⋰⋰🇪​⋰⋰🇱​⋰⋰🇪​⋰⋰🇹​⋰⋰🇪​⋰, ⋰🇴​⋰⋰🇮​⋰ ⋰🇸​⋰⋰🇺​⋰⋰🇦​⋰⋰🇷​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇱​⋰⋰🇦​⋰⋰🇩​⋰⋰🇰​⋰⋰🇪​⋰",
        "⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇫​⋰⋰🇺​⋰⋰🇫​⋰⋰🇮​⋰, ⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇩​⋰⋰🇮​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇩​⋰⋰🇮​⋰",
        "⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇩​⋰⋰🇮​⋰⋰🇰​⋰⋰🇭​⋰⋰🇦​⋰, ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰ ⋰🇦​⋰⋰🇧​⋰",
        "⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰, ⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇰​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰",
        "⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇱​⋰⋰🇪​⋰ ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇷​⋰⋰🇺​⋰, ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇱​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇱​⋰⋰🇪​⋰ ⋰🇬​⋰⋰🇷​⋰⋰🇮​⋰⋰🇧​⋰",
        "⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇭​⋰⋰🇪​⋰⋰🇳​⋰ ⋰🇻​⋰⋰🇪​⋰⋰🇸​⋰⋰🇮​⋰⋰🇾​⋰⋰🇦​⋰⋰🇦​⋰ ⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇮​⋰, ⋰🇮​⋰⋰🇹​⋰⋰🇳​⋰⋰🇦​⋰ ⋰🇬​⋰⋰🇳​⋰⋰🇩​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇩​⋰⋰🇦​⋰ ⋰🇹​⋰⋰🇺​⋰ ⋰🇫​⋰⋰🇮​⋰⋰🇷​⋰⋰🇸​⋰⋰🇪​⋰ ⋰🇳​⋰⋰🇪​⋰⋰🇹​⋰ ⋰🇴​⋰⋰🇳​⋰ ⋰🇴​⋰⋰🇫​⋰⋰🇫​⋰",
        "⋰🇬​⋰⋰🇷​⋰⋰🇮​⋰⋰🇧​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇹​⋰⋰🇪​⋰, ⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇯​⋰⋰🇦​⋰ ⋰🇱​⋰⋰🇴​⋰⋰🇩​⋰⋰🇪​⋰ ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇷​⋰⋰🇺​⋰ ⋰🇩​⋰⋰🇺​⋰⋰??​⋰⋰🇬​⋰⋰🇦​⋰",
        "⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇷​⋰⋰🇩​⋰⋰🇺​⋰⋰🇳​⋰⋰🇬​⋰⋰🇦​⋰⋰🇦​⋰, ⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰",
        "⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰, ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇾​⋰ ⋰🇨​⋰⋰🇵​⋰",
        "⋰🇨​⋰⋰🇵​⋰ ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇭​⋰⋰🇭​⋰, ⋰🇨​⋰⋰🇵​⋰ ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇱​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇭​⋰",
        "⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰ ⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰, ⋰🇦​⋰⋰🇧​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰ ⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰",
        "⋰🇩​⋰⋰🇴​⋰⋰🇺​⋰⋰🇧​⋰⋰🇱​⋰⋰🇪​⋰ ⋰🇸​⋰⋰🇪​⋰⋰🇳​⋰⋰🇩​⋰ ⋰🇰​⋰⋰🇴​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇨​⋰⋰🇴​⋰⋰🇩​⋰⋰🇺​⋰, ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇨​⋰⋰🇴​⋰⋰🇩​⋰ ⋰🇩​⋰⋰🇺​⋰⋰🇳​⋰⋰🇬​⋰⋰🇦​⋰ ⋰🇦​⋰⋰🇦​⋰⋰🇯​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇭​⋰⋰🇭​⋰",
        "⋰🇭​⋰⋰🇹​⋰ ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇩​⋰⋰🇦​⋰⋰🇱​⋰⋰🇦​⋰⋰🇱​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇹​⋰⋰🇪​⋰., ⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰ ⋰🇯​⋰⋰🇱​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇯​⋰⋰🇱​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇶​⋰ ⋰🇹​⋰⋰??​⋰⋰🇾​⋰⋰🇲​⋰⋰🇦​⋰",
        "⋰🇵​⋰⋰🇦​⋰⋰🇷​⋰⋰🇦​⋰ ⋰🇱​⋰⋰🇮​⋰⋰🇰​⋰⋰🇭​⋰⋰🇪​⋰⋰🇬​⋰⋰🇦​⋰.., ⋰🇹​⋰⋰🇷​⋰⋰🇦​⋰ ⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇭​⋰⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇰​⋰",
        "⋰🇱​⋰⋰🇦​⋰⋰🇬​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇱​⋰⋰🇦​⋰⋰🇩​⋰⋰🇨​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰, ⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰ ⋰🇱​⋰⋰🇦​⋰⋰🇬​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇹​⋰⋰🇪​⋰..",
        "⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇰​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰, ⋰🇧​⋰⋰🇭​⋰⋰🇮​⋰⋰🇰​⋰⋰🇦​⋰⋰🇷​⋰⋰🇮​⋰ ⋰🇱​⋰⋰🇺​⋰⋰🇳​⋰⋰🇩​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇸​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇷​⋰⋰🇦​⋰.",
        "⋰🇱​⋰⋰🇴​⋰⋰🇼​⋰ ⋰🇱​⋰⋰🇪​⋰⋰🇻​⋰⋰🇪​⋰⋰🇱​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇨​⋰⋰🇷​⋰, ⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰ ⋰🇱​⋰⋰🇴​⋰⋰🇼​⋰ ⋰🇱​⋰⋰🇪​⋰⋰🇻​⋰⋰🇪​⋰⋰🇱​⋰ ⋰🇼​⋰⋰🇪​⋰⋰🇦​⋰⋰🇰​⋰",
        "⋰🇲​⋰⋰🇪​⋰⋰🇷​⋰⋰🇪​⋰ ⋰🇱​⋰⋰🇺​⋰⋰🇳​⋰⋰🇩​⋰ ⋰🇵​⋰⋰🇪​⋰ ⋰🇪​⋰⋰🇾​⋰ ⋰🇹​⋰⋰🇺​⋰ ⋰🇭​⋰⋰🇮​⋰⋰🇯​⋰⋰🇩​⋰⋰🇪​⋰, ⋰🇫​⋰⋰🇷​⋰⋰🇪​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇼​⋰⋰🇦​⋰ ⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇰​⋰⋰🇴​⋰",
        "⋰🇫​⋰⋰🇷​⋰⋰🇪​⋰⋰🇪​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇾​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰ ⋰🇹​⋰⋰🇺​⋰ ⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰, ⋰🇹​⋰⋰🇺​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇮​⋰ ⋰🇰​⋰⋰🇮​⋰ ⋰🇰​⋰⋰🇾​⋰⋰🇦​⋰ ⋰🇭​⋰⋰🇦​⋰⋰🇮​⋰",
        "⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇰​⋰⋰🇮​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇹​⋰ ⋰🇨​⋰⋰🇱​⋰⋰🇦​⋰⋰🇮​⋰⋰🇲​⋰ ⋰🇨​⋰⋰🇷​⋰⋰🇼​⋰⋰🇦​⋰, ⋰🇹​⋰⋰🇺​⋰ ⋰🇰​⋰⋰🇾​⋰⋰🇦​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇮​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇸​⋰⋰🇰​⋰⋰🇹​⋰⋰🇦​⋰",
        "⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇪​⋰⋰🇳​⋰ ⋰🇻​⋰⋰🇪​⋰⋰🇸​⋰⋰🇮​⋰⋰🇾​⋰⋰🇦​⋰⋰🇦​⋰ ⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇮​⋰, ⋰🇹​⋰⋰🇺​⋰ ⋰🇰​⋰⋰🇾​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇩​⋰ ⋰🇯​⋰⋰🇦​⋰",
        "⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇩​⋰⋰🇮​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇩​⋰⋰🇮​⋰, ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇩​⋰⋰🇮​⋰⋰🇰​⋰⋰🇭​⋰⋰🇦​⋰",
        "⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰ ⋰🇦​⋰⋰🇧​⋰, ⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰",
        "⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇰​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰, ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇱​⋰⋰🇪​⋰ ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇷​⋰⋰🇺​⋰",
        "⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇱​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇱​⋰⋰🇪​⋰ ⋰🇬​⋰⋰🇷​⋰⋰??​⋰⋰🇧​⋰, ⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇭​⋰⋰🇪​⋰⋰🇳​⋰ ⋰🇻​⋰⋰🇪​⋰⋰🇸​⋰⋰🇮​⋰⋰🇾​⋰⋰🇦​⋰⋰🇦​⋰ ⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇮​⋰",
        "⋰🇮​⋰⋰🇹​⋰⋰🇳​⋰⋰🇦​⋰ ⋰🇬​⋰⋰🇳​⋰⋰🇩​⋰⋰??​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇩​⋰⋰🇦​⋰ ⋰🇹​⋰⋰🇺​⋰ ⋰🇫​⋰⋰🇮​⋰⋰🇷​⋰⋰🇸​⋰⋰🇪​⋰ ⋰🇳​⋰⋰🇪​⋰⋰🇹​⋰ ⋰🇴​⋰⋰🇳​⋰ ⋰🇴​⋰⋰🇫​⋰⋰🇫​⋰, ⋰🇬​⋰⋰🇷​⋰⋰🇮​⋰⋰🇧​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇹​⋰⋰🇪​⋰",
        "⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇯​⋰⋰🇦​⋰ ⋰🇱​⋰⋰🇴​⋰⋰🇩​⋰⋰🇪​⋰ ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇷​⋰⋰🇺​⋰ ⋰🇩​⋰⋰🇺​⋰⋰🇳​⋰⋰🇬​⋰⋰🇦​⋰, ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇷​⋰⋰🇩​⋰⋰🇺​⋰⋰🇳​⋰⋰🇬​⋰⋰🇦​⋰⋰🇦​⋰",
        "⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰, ⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰",
        "⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇾​⋰ ⋰🇨​⋰⋰🇵​⋰, ⋰🇨​⋰⋰🇵​⋰ ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇭​⋰⋰🇭​⋰",
        "⋰🇨​⋰⋰🇵​⋰ ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇱​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇭​⋰, ⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰ ⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰",
        "⋰🇦​⋰⋰🇧​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰ ⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰, ⋰🇩​⋰⋰🇴​⋰⋰🇺​⋰⋰🇧​⋰⋰🇱​⋰⋰🇪​⋰ ⋰🇸​⋰⋰🇪​⋰⋰🇳​⋰⋰🇩​⋰ ⋰🇰​⋰⋰🇴​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇹​⋰⋰🇲​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇨​⋰⋰🇴​⋰⋰🇩​⋰⋰🇺​⋰",
        "⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇲​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇨​⋰⋰🇴​⋰⋰🇩​⋰ ⋰🇩​⋰⋰🇺​⋰⋰🇳​⋰⋰🇬​⋰⋰🇦​⋰ ⋰🇦​⋰⋰🇦​⋰⋰🇯​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇭​⋰⋰🇭​⋰, ⋰🇭​⋰⋰🇹​⋰ ⋰🇹​⋰⋰🇧​⋰⋰🇰​⋰⋰🇨​⋰ ⋰🇩​⋰⋰🇦​⋰⋰🇱​⋰⋰🇦​⋰⋰🇱​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇹​⋰⋰🇪​⋰.",
        "⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰ ⋰🇯​⋰⋰🇱​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇯​⋰⋰🇱​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇶​⋰ ⋰🇹​⋰⋰🇷​⋰⋰🇾​⋰⋰🇲​⋰⋰🇦​⋰, ⋰🇵​⋰⋰🇦​⋰⋰🇷​⋰⋰🇦​⋰ ⋰🇱​⋰⋰🇮​⋰⋰🇰​⋰⋰🇭​⋰⋰🇪​⋰⋰🇬​⋰⋰🇦​⋰..",
        "⋰🇹​⋰⋰🇷​⋰⋰🇦​⋰ ⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇭​⋰⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇰​⋰, ⋰🇱​⋰⋰🇦​⋰⋰🇬​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇱​⋰⋰🇦​⋰⋰🇩​⋰⋰🇨​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰",
        "⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰ ⋰🇱​⋰⋰🇦​⋰⋰🇬​⋰⋰🇩​⋰⋰🇮​⋰ ⋰🇰​⋰⋰🇪​⋰ ⋰🇧​⋰⋰🇪​⋰⋰🇹​⋰⋰🇪​⋰.., ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇰​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰",
        "⋰🇧​⋰⋰🇭​⋰⋰🇮​⋰⋰🇰​⋰⋰🇦​⋰⋰🇷​⋰⋰🇮​⋰ ⋰🇱​⋰⋰🇺​⋰⋰🇳​⋰⋰🇩​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇸​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇷​⋰⋰🇦​⋰., ⋰🇱​⋰⋰🇴​⋰⋰🇼​⋰ ⋰🇱​⋰⋰🇪​⋰⋰🇻​⋰⋰🇪​⋰⋰🇱​⋰ ⋰🇨​⋰⋰🇵​⋰ ⋰🇨​⋰⋰🇷​⋰",
        "⋰🇨​⋰⋰🇵​⋰ ⋰🇧​⋰⋰🇴​⋰⋰🇱​⋰ ⋰🇱​⋰⋰🇴​⋰⋰🇼​⋰ ⋰🇱​⋰⋰🇪​⋰⋰🇻​⋰⋰🇪​⋰⋰🇱​⋰ ⋰🇼​⋰⋰🇪​⋰⋰🇦​⋰⋰🇰​⋰, ⋰🇲​⋰⋰🇪​⋰⋰🇷​⋰⋰🇪​⋰ ⋰🇱​⋰⋰🇺​⋰⋰🇳​⋰⋰🇩​⋰ ⋰🇵​⋰⋰🇪​⋰ ⋰🇪​⋰⋰🇾​⋰ ⋰🇹​⋰⋰🇺​⋰ ⋰🇭​⋰⋰🇮​⋰⋰🇯​⋰⋰🇩​⋰⋰🇪​⋰",
        "⋰🇫​⋰⋰🇷​⋰⋰🇪​⋰⋰🇪​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰⋰🇼​⋰⋰🇦​⋰ ⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰??​⋰⋰🇦​⋰⋰🇰​⋰⋰🇴​⋰, ⋰🇫​⋰⋰🇷​⋰⋰🇪​⋰⋰🇪​⋰ ⋰🇲​⋰⋰🇪​⋰⋰🇾​⋰ ⋰🇨​⋰⋰🇺​⋰⋰🇩​⋰ ⋰🇹​⋰⋰🇺​⋰ ⋰🇷​⋰⋰🇦​⋰⋰🇳​⋰⋰🇩​⋰⋰🇾​⋰⋰🇰​⋰⋰🇪​⋰",
        "⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇰​⋰⋰🇮​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇹​⋰ ⋰🇨​⋰⋰🇱​⋰⋰🇦​⋰⋰🇮​⋰⋰🇲​⋰ ⋰🇨​⋰⋰🇷​⋰⋰🇼​⋰⋰🇦​⋰, ⋰🇹​⋰⋰🇺​⋰ ⋰🇰​⋰⋰🇾​⋰⋰🇦​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇮​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇦​⋰⋰🇬​⋰ ⋰🇸​⋰⋰🇰​⋰⋰🇹​⋰⋰🇦​⋰",
        "⋰🇹​⋰⋰🇪​⋰⋰🇷​⋰⋰🇾​⋰ ⋰🇧​⋰⋰🇭​⋰⋰🇪​⋰⋰🇳​⋰ ⋰🇻​⋰⋰🇪​⋰⋰🇸​⋰⋰🇮​⋰⋰🇾​⋰⋰🇦​⋰⋰🇦​⋰ ⋰🇷​⋰⋰🇳​⋰⋰🇩​⋰⋰🇮​⋰, ⋰🇹​⋰⋰🇺​⋰ ⋰🇰​⋰⋰🇾​⋰⋰🇦​⋰ ⋰🇨​⋰⋰🇭​⋰⋰🇺​⋰⋰🇩​⋰ ⋰🇯​⋰⋰🇦​⋰"
        "⋰🇧⋰⋰🇭⋰⋰🇴⋰⋰🇸⋰⋰🇩⋰⋰🇮⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇫⋰⋰🇦⋰⋰🇹⋰⋰🇮⋰ ⋰🇭⋰⋰🇦⋰⋰🇮⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇭⋰⋰🇴⋰⋰🇯⋰⋰🇦⋰",
        "⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰ ⋰🇯⋰⋰🇦⋰⋰🇾⋰⋰🇪⋰⋰🇬⋰⋰🇮⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇧⋰⋰🇭⋰⋰🇮⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇭⋰⋰🇦⋰⋰🇮⋰",
        "⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇴⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇫⋰⋰🇮⋰⋰🇷⋰⋰🇸⋰⋰🇪⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇬⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰ ⋰🇫⋰⋰🇦⋰⋰🇩⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇳⋰⋰🇦⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇲⋰⋰🇦⋰⋰🇷⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰??⋰⋰🇪⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇨⋰⋰🇭⋰⋰🇦⋰⋰🇵⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰ ⋰🇩⋰⋰🇮⋰⋰🇩⋰⋰🇮⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇫⋰⋰🇦⋰⋰🇩⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇧⋰⋰🇭⋰⋰🇮⋰⋰🇰⋰⋰🇦⋰⋰🇷⋰⋰🇮⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇱⋰⋰🇦⋰⋰🇩⋰⋰🇰⋰⋰🇪⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰",
        "⋰🇳⋰⋰🇪⋰⋰🇹⋰ ⋰🇴⋰⋰🇫⋰⋰🇫⋰ ⋰🇰⋰⋰🇷⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰, ⋰🇹⋰⋰🇧⋰⋰🇰⋰⋰🇨⋰ ⋰🇨⋰⋰🇴⋰⋰🇩⋰⋰🇺⋰ ⋰🇰⋰⋰🇷⋰ ⋰🇲⋰⋰🇸⋰⋰🇬⋰ ⋰🇩⋰⋰🇪⋰⋰🇱⋰⋰🇪⋰⋰🇹⋰⋰🇪⋰",
        "⋰🇴⋰⋰🇾⋰⋰🇪⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⋰🇰⋰⋰🇪⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇴⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰",
        "⋰🇹⋰⋰??⋰⋰🇰⋰⋰🇨⋰ ⋰🇲⋰⋰🇦⋰⋰🇷⋰⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇫⋰⋰🇦⋰⋰🇹⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰",
        "⋰🇸⋰⋰🇱⋰⋰🇴⋰⋰🇼⋰ ⋰🇫⋰⋰🇮⋰⋰🇷⋰⋰🇸⋰⋰🇪⋰ ⋰🇧⋰⋰🇭⋰⋰🇮⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰ ⋰🇯⋰⋰🇦⋰⋰🇾⋰⋰🇪⋰⋰🇬⋰⋰🇮⋰",
        "⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇬⋰⋰🇷⋰⋰🇮⋰⋰🇧⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰, ⋰🇹⋰⋰🇷⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇩⋰⋰🇴⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇳⋰⋰🇦⋰",
        "⋰🇹⋰⋰🇧⋰⋰🇰⋰⋰🇨⋰ ⋰🇨⋰⋰🇴⋰⋰🇩⋰⋰🇺⋰ ⋰🇵⋰⋰🇺⋰⋰🇷⋰⋰🇦⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇧⋰⋰🇪⋰⋰🇨⋰⋰🇭⋰ ⋰🇩⋰⋰🇴⋰",
        "⋰🇴⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇪⋰ ⋰🇱⋰⋰🇴⋰⋰🇩⋰⋰🇪⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰",
        "⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰ ⋰🇧⋰⋰🇪⋰⋰🇪⋰⋰🇯⋰, ⋰🇹⋰⋰🇲⋰⋰🇰⋰⋰🇨⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰⋰🇺⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇰⋰⋰🇴⋰",
        "⋰🇸⋰⋰🇺⋰⋰🇦⋰⋰🇷⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇧⋰⋰🇪⋰⋰🇪⋰⋰🇯⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇧⋰⋰🇦⋰⋰🇩⋰⋰🇮⋰ ⋰🇭⋰⋰🇦⋰⋰🇮⋰",
        "⋰🇹⋰⋰🇷⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇮⋰ ⋰🇰⋰⋰🇪⋰⋰🇸⋰⋰🇪⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇴⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇫⋰⋰🇮⋰⋰🇷⋰⋰🇸⋰⋰🇪⋰",
        "⋰🇹⋰⋰🇧⋰⋰🇰⋰⋰🇨⋰ ⋰🇨⋰⋰🇴⋰⋰🇩⋰⋰🇺⋰ ⋰🇰⋰⋰🇷⋰ ⋰🇲⋰⋰🇸⋰⋰🇬⋰ ⋰🇩⋰⋰🇪⋰⋰🇱⋰⋰🇪⋰⋰🇹⋰⋰🇪⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰",
        "⋰🇴⋰⋰🇮⋰ ⋰🇸⋰⋰🇺⋰⋰🇦⋰⋰🇷⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇱⋰⋰🇦⋰⋰🇩⋰⋰🇰⋰⋰🇪⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰",
        "⋰🇹⋰⋰🇺⋰ ⋰🇧⋰⋰🇭⋰⋰🇮⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇭⋰⋰🇦⋰⋰🇮⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇯⋰⋰🇦⋰⋰🇾⋰⋰🇪⋰⋰🇬⋰⋰🇮⋰",
        "⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇯⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇱⋰⋰🇪⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇬⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰ ⋰🇫⋰⋰🇦⋰⋰🇩⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇸⋰⋰🇱⋰⋰🇴⋰⋰🇼⋰ ⋰🇹⋰⋰🇾⋰⋰🇵⋰⋰🇪⋰⋰🇷⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰??⋰ ⋰🇧⋰⋰🇭⋰⋰🇴⋰⋰🇸⋰⋰🇩⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇦⋰⋰🇦⋰⋰🇯⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇬⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰ ⋰🇲⋰⋰🇪⋰⋰🇮⋰⋰🇳⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇸⋰⋰🇰⋰⋰🇹⋰⋰🇦⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇲⋰⋰🇦⋰⋰🇩⋰⋰🇷⋰⋰🇨⋰⋰🇴⋰⋰🇩⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇩⋰⋰🇮⋰⋰🇩⋰⋰🇮⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇫⋰⋰🇦⋰⋰🇩⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇧⋰⋰🇭⋰⋰🇮⋰⋰🇰⋰⋰🇦⋰⋰🇷⋰⋰🇮⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇱⋰⋰🇦⋰⋰🇩⋰⋰🇰⋰⋰🇪⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰",
        "⋰🇳⋰⋰🇪⋰⋰🇹⋰ ⋰🇴⋰⋰🇫⋰⋰🇫⋰ ⋰🇰⋰⋰🇷⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰, ⋰🇹⋰⋰🇧⋰⋰🇰⋰⋰🇨⋰ ⋰🇨⋰⋰🇴⋰⋰🇩⋰⋰🇺⋰ ⋰🇰⋰⋰🇷⋰ ⋰🇲⋰⋰🇸⋰⋰🇬⋰ ⋰🇩⋰⋰🇪⋰⋰🇱⋰⋰🇪⋰⋰🇹⋰⋰🇪⋰",
        "⋰🇴⋰⋰🇾⋰⋰🇪⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⋰🇰⋰⋰🇪⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇴⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰",
        "⋰🇹⋰⋰🇲⋰⋰🇰⋰⋰🇨⋰ ⋰🇲⋰⋰🇦⋰⋰🇷⋰⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇫⋰⋰🇦⋰⋰🇹⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰",
        "⋰🇸⋰⋰🇱⋰⋰🇴⋰⋰🇼⋰ ⋰??⋰⋰🇮⋰⋰🇷⋰⋰🇸⋰⋰🇪⋰ ⋰🇧⋰⋰🇭⋰⋰🇮⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰ ⋰🇯⋰⋰🇦⋰⋰🇾⋰⋰🇪⋰⋰🇬⋰⋰🇮⋰",
        "⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇬⋰⋰🇷⋰⋰🇮⋰⋰🇧⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰, ⋰🇹⋰⋰🇷⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇩⋰⋰🇴⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇳⋰⋰🇦⋰",
        "⋰🇹⋰⋰🇧⋰⋰🇰⋰⋰🇨⋰ ⋰🇨⋰⋰🇴⋰⋰🇩⋰⋰🇺⋰ ⋰🇵⋰⋰🇺⋰⋰🇷⋰⋰🇦⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇧⋰⋰🇪⋰⋰🇨⋰⋰🇭⋰ ⋰🇩⋰⋰🇴⋰",
        "⋰🇴⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇪⋰ ⋰🇱⋰⋰🇴⋰⋰🇩⋰⋰🇪⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰",
        "⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰ ⋰🇧⋰⋰🇪⋰⋰🇪⋰⋰🇯⋰, ⋰🇹⋰⋰🇲⋰⋰🇰⋰⋰🇨⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰⋰🇺⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇰⋰⋰🇴⋰",
        "⋰🇸⋰⋰🇺⋰⋰🇦⋰⋰🇷⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇧⋰⋰🇪⋰⋰🇪⋰⋰🇯⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇧⋰⋰🇦⋰⋰🇩⋰⋰🇮⋰ ⋰🇭⋰⋰🇦⋰⋰🇮⋰",
        "⋰🇹⋰⋰🇷⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇮⋰ ⋰🇰⋰⋰🇪⋰⋰🇸⋰⋰🇪⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇴⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇫⋰⋰🇮⋰⋰🇷⋰⋰🇸⋰⋰🇪⋰",
        "⋰🇹⋰⋰🇧⋰⋰🇰⋰⋰🇨⋰ ⋰🇨⋰⋰🇴⋰⋰🇩⋰⋰🇺⋰ ⋰🇰⋰⋰🇷⋰ ⋰🇲⋰⋰🇸⋰⋰🇬⋰ ⋰🇩⋰⋰🇪⋰⋰🇱⋰⋰🇪⋰⋰🇹⋰⋰🇪⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰",
        "⋰🇴⋰⋰🇮⋰ ⋰🇸⋰⋰🇺⋰⋰🇦⋰⋰🇷⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇱⋰⋰🇦⋰⋰🇩⋰⋰🇰⋰⋰🇪⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰",
        "⋰🇹⋰⋰🇺⋰ ⋰🇧⋰⋰🇭⋰⋰🇮⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇭⋰⋰🇦⋰⋰🇮⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇯⋰⋰🇦⋰⋰🇾⋰⋰🇪⋰⋰🇬⋰⋰🇮⋰",
        "⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇯⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇱⋰⋰🇪⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇬⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰ ⋰🇫⋰⋰🇦⋰⋰🇩⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇸⋰⋰🇱⋰⋰🇴⋰⋰🇼⋰ ⋰🇹⋰⋰🇾⋰⋰🇵⋰⋰🇪⋰⋰🇷⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇧⋰⋰🇭⋰⋰🇴⋰⋰🇸⋰⋰🇩⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇦⋰⋰🇦⋰⋰🇯⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇰⋰⋰??⋰ ⋰🇬⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰ ⋰🇲⋰⋰🇪⋰⋰🇮⋰⋰🇳⋰, ⋰🇹⋰⋰🇺⋰ ⋰🇰⋰⋰🇾⋰⋰🇦⋰ ⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇸⋰⋰🇰⋰⋰🇹⋰⋰🇦⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇲⋰⋰🇦⋰⋰🇩⋰⋰🇷⋰⋰🇨⋰⋰🇴⋰⋰🇩⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇩⋰⋰🇮⋰⋰🇩⋰⋰🇮⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇫⋰⋰🇦⋰⋰🇩⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇧⋰⋰🇭⋰⋰🇮⋰⋰🇰⋰⋰🇦⋰⋰🇷⋰⋰🇮⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇱⋰⋰🇦⋰⋰🇩⋰⋰🇰⋰⋰🇪⋰, ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰"
        "⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇵⋰ ⋰🇧⋰⋰🇭⋰⋰🇮⋰ ⋰🇧⋰⋰🇳⋰⋰🇦⋰⋰🇱⋰⋰🇪⋰ ⋰🇲⋰⋰🇺⋰⋰🇯⋰⋰🇪⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⋰🇰⋰⋰🇪⋰",
        "⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇦⋰ ⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇵⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇿⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇾⋰⋰🇦⋰⋰🇦⋰⋰🇩⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇹⋰⋰🇺⋰⋰🇯⋰⋰🇭⋰⋰🇪⋰",
        "⋰🇹⋰⋰🇺⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇦⋰ ⋰🇳⋰⋰🇦⋰ ⋰🇹⋰⋰🇾⋰⋰🇲⋰⋰🇵⋰⋰🇦⋰⋰🇸⋰⋰🇸⋰",
        "⋰🇴⋰⋰🇾⋰⋰🇪⋰ ⋰🇺⋰⋰🇳⋰⋰🇫⋰⋰🇺⋰⋰🇳⋰⋰🇳⋰⋰🇾⋰ ⋰🇸⋰⋰🇼⋰⋰🇮⋰⋰🇵⋰⋰🇪⋰ ⋰🇲⋰⋰🇹⋰⋰🇹⋰ ⋰🇰⋰⋰🇷⋰",
        "⋰🇴⋰⋰🇭⋰ ⋰🇭⋰⋰🇪⋰⋰🇱⋰⋰🇱⋰⋰🇴⋰ ⋰🇧⋰⋰🇮⋰⋰🇭⋰⋰🇦⋰⋰🇷⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇦⋰ ⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇵⋰ ⋰🇧⋰⋰🇮⋰⋰🇭⋰⋰🇦⋰⋰🇷⋰⋰🇮⋰ ⋰🇴⋰⋰🇷⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇻⋰ ⋰🇧⋰⋰🇮⋰⋰🇭⋰⋰🇦⋰⋰🇷⋰⋰🇮⋰ ⋰🇦⋰⋰🇺⋰⋰🇰⋰⋰🇦⋰⋰🇹⋰ ⋰🇲⋰⋰🇪⋰ ⋰🇷⋰⋰🇭⋰⋰🇦⋰ ⋰🇰⋰⋰🇷⋰.",
        "⋰🇴⋰⋰🇾⋰⋰🇾⋰ ⋰🇰⋰⋰🇮⋰⋰🇳⋰⋰🇳⋰⋰🇪⋰⋰🇷⋰ ⋰🇹⋰⋰🇺⋰⋰🇯⋰⋰🇭⋰⋰🇪⋰ ⋰🇬⋰⋰🇨⋰ ⋰🇲⋰⋰🇪⋰ ⋰🇦⋰⋰🇦⋰⋰🇳⋰⋰🇪⋰ ⋰🇰⋰⋰🇮⋰ ⋰🇵⋰⋰🇪⋰⋰🇷⋰⋰🇲⋰⋰🇮⋰⋰🇸⋰⋰🇸⋰⋰🇮⋰⋰🇴⋰⋰🇳⋰ ⋰🇰⋰⋰🇮⋰⋰🇸⋰⋰🇳⋰⋰🇪⋰ ⋰🇩⋰⋰🇮⋰.",
        "⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇰⋰⋰🇪⋰ ⋰🇩⋰⋰🇮⋰⋰🇰⋰⋰🇭⋰⋰🇦⋰",
        "⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇰⋰⋰🇪⋰ ⋰🇩⋰⋰🇮⋰⋰🇰⋰⋰🇭⋰⋰🇦⋰ ⋰🇪⋰⋰🇰⋰ ⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇷⋰.",
        "⋰🇸⋰⋰🇺⋰⋰🇳⋰ ⋰🇸⋰⋰🇺⋰⋰🇳⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇦⋰.",
        "⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰??⋰ ⋰🇲⋰⋰🇦⋰⋰🇨⋰⋰🇦⋰ ⋰🇧⋰⋰🇭⋰⋰🇴⋰⋰🇸⋰⋰🇩⋰⋰🇦⋰.",
        "⋰🇴⋰⋰🇾⋰⋰🇪⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇹⋰⋰🇮⋰ ⋰🇯⋰⋰🇦⋰⋰🇹⋰⋰🇮⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇹⋰⋰🇲⋰⋰🇷⋰.",
        "⋰🇰⋰⋰🇾⋰? ⋰🇯⋰⋰🇱⋰⋰🇩⋰⋰🇮⋰ ⋰🇱⋰⋰🇮⋰⋰🇰⋰⋰🇭⋰ ⋰🇰⋰⋰🇮⋰⋰🇩⋰⋰🇩⋰⋰🇪⋰.",
        "⋰🇧⋰⋰🇮⋰⋰🇭⋰⋰🇦⋰⋰🇷⋰⋰🇮⋰ ⋰🇨⋰⋰🇴⋰⋰🇲⋰ ⋰🇬⋰⋰🇦⋰⋰🇳⋰⋰🇬⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇵⋰ ⋰🇰⋰⋰🇴⋰ ⋰🇹⋰⋰🇦⋰⋰🇬⋰ ⋰🇨⋰⋰🇷⋰⋰🇪⋰⋰🇬⋰⋰🇦⋰ ⋰🇹⋰⋰🇺⋰",
        "⋰🇲⋰⋰🇺⋰⋰🇯⋰⋰🇭⋰⋰🇪⋰ ⋰🇨⋰⋰🇾⋰⋰🇦⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇧⋰⋰🇮⋰⋰🇭⋰⋰🇦⋰⋰🇷⋰⋰🇮⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇹⋰⋰🇲⋰⋰🇰⋰⋰🇨⋰ ⋰🇧⋰⋰🇸⋰",
        "⋰🇯⋰⋰🇦⋰⋰🇱⋰⋰🇩⋰⋰🇮⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇿⋰ ⋰🇵⋰⋰🇦⋰⋰🇵⋰⋰🇦⋰ ⋰🇧⋰⋰🇴⋰⋰🇱⋰",
        "⋰🇸⋰⋰🇮⋰⋰🇩⋰⋰🇪⋰ ⋰🇭⋰⋰🇴⋰⋰🇯⋰⋰🇦⋰ ⋰🇧⋰⋰🇮⋰⋰🇭⋰⋰🇦⋰⋰🇷⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇦⋰⋰🇮⋰ ⋰🇦⋰⋰🇧⋰",
        "⋰🇭⋰⋰🇾⋰⋰🇪⋰ ⋰🇵⋰⋰🇬⋰⋰🇱⋰ ⋰🇧⋰⋰🇭⋰⋰🇬⋰ ⋰🇲⋰⋰🇦⋰⋰🇹⋰ ⋰🇦⋰⋰🇨⋰⋰🇭⋰⋰🇪⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰",
        "⋰🇧⋰⋰🇭⋰⋰🇬⋰ ⋰🇳⋰⋰🇾⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇦⋰⋰🇯⋰⋰🇯⋰",
        "⋰🇭⋰⋰🇾⋰⋰🇪⋰ ⋰🇵⋰⋰🇬⋰⋰🇱⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇧⋰⋰🇨⋰⋰🇭⋰⋰🇪⋰ ⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇲⋰⋰🇦⋰⋰🇹⋰",
        "⋰🇭⋰⋰🇾⋰⋰🇪⋰ ⋰🇩⋰⋰🇺⋰⋰🇷⋰ ⋰🇭⋰⋰🇦⋰⋰🇹⋰⋰🇹⋰ ⋰🇲⋰⋰🇦⋰⋰🇩⋰⋰🇭⋰⋰🇦⋰⋰🇷⋰⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇧⋰⋰🇦⋰⋰🇨⋰⋰🇭⋰⋰🇪⋰",
        "⋰🇰⋰⋰🇴⋰⋰🇮⋰ ⋰🇧⋰⋰🇦⋰⋰🇹⋰ ⋰🇳⋰⋰🇾⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇪⋰⋰🇸⋰⋰🇱⋰⋰🇮⋰⋰🇾⋰⋰🇪⋰ ⋰🇲⋰⋰🇦⋰⋰🇫⋰ ⋰🇨⋰⋰🇷⋰ ⋰🇷⋰⋰🇭⋰⋰🇦⋰ ⋰🇭⋰⋰🇺⋰ ⋰🇹⋰⋰🇺⋰⋰🇯⋰⋰🇭⋰⋰🇪⋰",
        "⋰🇰⋰⋰🇴⋰⋰🇮⋰ ⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇹⋰ ⋰🇳⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇲⋰⋰🇦⋰⋰🇫⋰⋰🇮⋰ ⋰🇩⋰⋰🇪⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇦⋰⋰🇨⋰⋰🇭⋰⋰🇪⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇲⋰⋰🇦⋰⋰🇫⋰⋰🇮⋰ ⋰🇲⋰⋰🇮⋰⋰🇱⋰ ⋰🇯⋰⋰🇦⋰⋰🇾⋰⋰🇪⋰⋰🇬⋰⋰🇮⋰ ⋰🇹⋰⋰🇺⋰⋰🇯⋰⋰🇭⋰⋰🇪⋰",
        "⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇲⋰⋰🇦⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇦⋰ ⋰🇲⋰⋰🇺⋰⋰🇯⋰⋰🇪⋰ ⋰🇸⋰⋰🇼⋰⋰🇮⋰⋰🇵⋰⋰🇪⋰ ⋰🇨⋰⋰🇷⋰⋰🇰⋰⋰🇪⋰",
        "⋰🇦⋰⋰🇨⋰⋰🇭⋰⋰🇪⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇸⋰⋰🇼⋰⋰🇮⋰⋰🇵⋰⋰🇪⋰ ⋰🇨⋰⋰🇷⋰⋰🇰⋰⋰🇪⋰",
        "⋰🇫⋰⋰🇷⋰ ⋰🇧⋰⋰🇴⋰⋰🇱⋰⋰🇳⋰⋰🇦⋰ ⋰🇳⋰⋰🇦⋰ ⋰??⋰⋰🇮⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇱⋰⋰🇪⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇸⋰⋰🇼⋰⋰🇮⋰⋰🇵⋰⋰🇪⋰ ⋰🇨⋰⋰🇷⋰⋰🇰⋰⋰🇪⋰",
        "⋰🇨⋰⋰🇾⋰⋰🇦⋰ ⋰🇭⋰⋰🇺⋰⋰🇦⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰",
        "⋰🇵⋰⋰🇷⋰ ⋰🇰⋰⋰🇪⋰⋰🇸⋰⋰🇪⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰",
        "⋰🇲⋰⋰🇺⋰⋰🇯⋰⋰🇭⋰⋰🇪⋰ ⋰🇵⋰⋰🇹⋰⋰🇦⋰ ⋰🇹⋰⋰🇭⋰⋰🇦⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇦⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰",
        "⋰🇲⋰⋰🇪⋰⋰🇾⋰ ⋰🇳⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰⋰🇳⋰⋰🇹⋰⋰🇦⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰",
        "⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰",
        "⋰🇱⋰⋰🇴⋰⋰🇩⋰⋰🇪⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇺⋰⋰🇹⋰⋰🇷⋰ ⋰🇲⋰⋰??⋰",
        "⋰🇱⋰⋰🇺⋰⋰🇳⋰ ⋰🇲⋰⋰🇹⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇸⋰ ⋰🇲⋰⋰🇪⋰⋰🇷⋰⋰🇦⋰",
        "⋰🇳⋰⋰🇮⋰⋰🇰⋰⋰🇦⋰⋰🇱⋰ ⋰🇲⋰⋰🇦⋰⋰🇩⋰⋰🇦⋰⋰🇷⋰⋰🇨⋰⋰🇭⋰⋰🇩⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇴⋰⋰🇾⋰⋰🇪⋰ ⋰🇬⋰⋰🇦⋰⋰🇸⋰⋰🇭⋰⋰🇹⋰⋰🇮⋰ ⋰🇰⋰ ⋰🇧⋰⋰🇦⋰⋰🇨⋰⋰🇭⋰⋰🇪⋰",
        "⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇮⋰⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇹⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰",
        "⋰🇲⋰⋰🇦⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰",
        "⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇰⋰ ⋰🇭⋰⋰🇦⋰⋰🇹⋰⋰🇭⋰ ⋰🇹⋰⋰🇴⋰⋰🇩⋰⋰🇭⋰ ⋰🇰⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇪⋰ ⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇵⋰ ⋰🇰⋰ ⋰🇲⋰⋰🇺⋰⋰🇭⋰ ⋰🇲⋰⋰🇪⋰ ⋰🇫⋰⋰🇦⋰⋰🇸⋰⋰🇦⋰⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰",
        "⋰🇱⋰⋰🇪⋰⋰🇦⋰⋰??⋰⋰🇪⋰ ⋰🇱⋰⋰🇪⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰ ⋰🇵⋰⋰🇦⋰⋰🇸⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰ ⋰🇳⋰⋰🇦⋰⋰🇮⋰ ⋰🇦⋰⋰🇾⋰⋰🇦⋰ ⋰🇲⋰⋰🇪⋰⋰🇰⋰⋰🇴⋰",
        "⋰🇱⋰⋰🇪⋰⋰🇦⋰⋰🇻⋰⋰🇪⋰ ⋰🇱⋰⋰🇪⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰ ⋰🇮⋰⋰🇩⋰⋰🇪⋰⋰🇷⋰ ⋰🇸⋰⋰🇪⋰",
        "⋰🇱⋰⋰🇪⋰⋰🇦⋰⋰🇻⋰⋰🇪⋰ ⋰🇱⋰⋰🇪⋰ ⋰🇯⋰⋰🇱⋰⋰🇩⋰⋰🇮⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇼⋰⋰🇷⋰⋰🇳⋰⋰🇦⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇦⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰",
        "⋰🇱⋰⋰🇪⋰⋰🇦⋰⋰🇻⋰⋰🇪⋰ ⋰🇳⋰⋰🇾⋰ ⋰🇱⋰⋰🇪⋰⋰🇬⋰⋰🇦⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰",
        "⋰🇸⋰⋰🇲⋰⋰🇯⋰⋰🇭⋰ ⋰🇧⋰⋰🇦⋰⋰🇹⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰ ⋰🇱⋰⋰🇪⋰⋰🇦⋰⋰🇻⋰⋰🇪⋰ ⋰🇱⋰⋰🇪⋰",
        "⋰🇫⋰⋰🇦⋰⋰🇸⋰⋰🇹⋰ ⋰🇱⋰⋰🇪⋰⋰🇦⋰⋰🇻⋰⋰🇪⋰ ⋰🇱⋰⋰🇪⋰ ⋰🇰⋰⋰🇦⋰⋰🇲⋰⋰🇯⋰⋰🇴⋰⋰🇷⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰",
        "⋰🇹⋰⋰🇺⋰⋰🇹⋰⋰🇴⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰",
        "⋰🇴⋰⋰🇾⋰ ⋰🇭⋰⋰🇮⋰⋰🇯⋰⋰🇩⋰⋰🇪⋰ ⋰🇰⋰⋰🇭⋰⋰🇦⋰⋰🇳⋰⋰🇦⋰ ⋰🇰⋰⋰🇭⋰⋰🇦⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇦⋰⋰🇦⋰ ⋰🇰⋰⋰🇦⋰⋰🇲⋰⋰🇿⋰⋰🇴⋰⋰🇷⋰",
        "⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇴⋰ ⋰🇮⋰⋰🇱⋰⋰🇾⋰ ⋰🇷⋰⋰🇪⋰⋰🇾",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇨⋰⋰🇭⋰⋰🇦⋰⋰🇵⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇹⋰⋰🇲⋰⋰🇰⋰⋰🇨⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰⋰🇨⋰⋰🇭⋰⋰🇦⋰⋰🇵⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇹⋰⋰🇺⋰",
        "⋰🇸⋰⋰🇭⋰⋰🇮⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰⋰🇨⋰⋰🇭⋰⋰🇦⋰⋰🇵⋰",
        "⋰🇫⋰⋰🇷⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰??⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰⋰🇨⋰⋰🇭⋰⋰🇦⋰⋰🇵⋰",
        "⋰🇸⋰⋰🇭⋰⋰🇮⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇱⋰⋰🇮⋰⋰🇰⋰⋰🇭⋰ ⋰🇼⋰⋰🇷⋰⋰🇳⋰⋰🇦⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇦⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰",
        "⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇾⋰⋰🇺⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇦⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰⋰🇨⋰⋰🇭⋰⋰🇦⋰⋰🇵⋰",
        "⋰🇵⋰⋰🇷⋰⋰🇴⋰⋰🇴⋰⋰🇫⋰ ⋰🇨⋰⋰🇷⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰",
        "⋰🇵⋰⋰🇷⋰⋰🇴⋰⋰🇴⋰⋰🇫⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰ ⋰🇪⋰⋰🇾⋰",
        "⋰🇵⋰⋰🇷⋰⋰🇴⋰⋰🇴⋰⋰🇫⋰ ⋰🇭⋰⋰🇴⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇰⋰⋰🇦⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇨⋰⋰🇭⋰⋰🇮⋰⋰🇱⋰⋰🇱⋰⋰🇦⋰⋰🇷⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇰⋰ ⋰🇧⋰⋰🇴⋰⋰🇸⋰⋰🇩⋰⋰🇦⋰ ⋰🇹⋰⋰🇪⋰⋰??⋰⋰🇾⋰",
        "⋰🇴⋰⋰🇾⋰ ⋰🇭⋰⋰🇮⋰⋰🇯⋰⋰🇩⋰⋰🇪⋰ ⋰🇰⋰⋰🇭⋰⋰🇦⋰⋰🇳⋰⋰🇦⋰ ⋰🇰⋰⋰🇭⋰⋰🇦⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇦⋰⋰🇦⋰ ⋰🇰⋰⋰🇦⋰⋰🇲⋰⋰🇿⋰⋰🇴⋰⋰🇷⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇲​⋰⋰🇦​⋰⋰🇩​⋰⋰🇷​⋰⋰🇨​⋰⋰🇭​⋰⋰🇴​⋰⋰🇩​⋰ ?",
        "⋰🇦⋰⋰🇧⋰ ⋰🇹⋰⋰🇰⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇮⋰ ⋰🇭⋰⋰🇴⋰⋰🇬⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ?",
        "⋰🇳⋰⋰🇾⋰ ⋰🇳⋰⋰🇾⋰ ⋰🇲⋰⋰🇪⋰ ⋰🇰⋰⋰🇺⋰⋰🇨⋰⋰🇭⋰ ⋰🇳⋰⋰🇾⋰ ⋰🇯⋰⋰🇦⋰⋰🇳⋰⋰🇹⋰⋰🇦⋰ ⋰🇧⋰⋰🇸⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰ ⋰🇪⋰⋰🇾⋰",
        "⋰🇸⋰⋰🇧⋰⋰🇸⋰⋰🇪⋰ ⋰🇵⋰⋰🇭⋰⋰🇪⋰⋰🇱⋰⋰🇪⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇰⋰⋰🇴⋰ ⋰🇧⋰⋰🇴⋰⋰🇱⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇳⋰⋰🇦⋰ ⋰🇰⋰⋰🇦⋰⋰🇲⋰ ⋰🇰⋰⋰🇷⋰⋰🇪⋰",
        "⋰🇾⋰⋰🇦⋰⋰🇭⋰⋰🇦⋰ ⋰🇧⋰⋰🇭⋰⋰🇮⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇦⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇨⋰⋰🇪⋰ ⋰🇵⋰⋰🇮⋰⋰🇱⋰⋰🇱⋰⋰🇪⋰",
        "⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰⋰🇲⋰⋰🇦⋰⋰🇰⋰⋰🇦⋰⋰🇧⋰⋰🇴⋰⋰🇸⋰⋰🇩⋰⋰🇦⋰",
        "⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇹⋰⋰🇴⋰ ⋰🇧⋰⋰🇭⋰⋰🇪⋰⋰🇳⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇪⋰⋰🇬⋰⋰🇮⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇵⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰ ⋰🇹⋰⋰🇴⋰⋰🇲⋰⋰🇲⋰⋰🇾⋰",
        "⋰🇳⋰⋰🇮⋰⋰🇰⋰⋰🇦⋰⋰🇱⋰ ⋰🇲⋰⋰🇦⋰⋰🇩⋰⋰🇦⋰⋰🇷⋰⋰🇨⋰⋰🇭⋰⋰🇩⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇰⋰⋰🇪⋰ ⋰🇾⋰⋰🇭⋰⋰🇦⋰ ⋰🇸⋰⋰🇪⋰",
        "⋰🇨⋰⋰🇴⋰⋰🇿⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇭⋰⋰🇮⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰ ⋰🇭⋰⋰🇪⋰",
        "⋰🇳⋰⋰🇾⋰⋰🇹⋰⋰🇴⋰ ⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇵⋰ ⋰🇧⋰⋰🇴⋰⋰🇱⋰ ⋰🇲⋰⋰🇺⋰⋰🇯⋰⋰🇭⋰⋰🇪⋰",
        "⋰🇳⋰⋰🇾⋰⋰🇳⋰⋰🇾⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇭⋰⋰🇴⋰⋰🇬⋰⋰🇮⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⊶⊶🇮⋰ ⋰🇯⋰⋰🇴⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰⋰🇹⋰⋰🇮⋰ ⋰🇯⋰⋰🇴⋰⋰🇬⋰⋰🇮⋰",
        "⋰🇹⋰⋰🇷⋰⋰🇾⋰ ⋰🇦⋰⋰🇲⋰⋰🇲⋰⋰🇮⋰ ⋰🇨⋰⋰🇪⋰ ⋰🇧⋰⋰🇭⋰⋰🇴⋰⋰🇸⋰⋰🇩⋰⋰🇪⋰ ⋰🇲⋰⋰🇪⋰ ⋰🇪⋰⋰🇲⋰⋰🇴⋰⋰🇯⋰⋰🇮⋰ ⋰🇩⋰⋰🇦⋰⋰🇱⋰ ⋰🇲⋰⋰🇨⋰",
        "⋰🇨⋰⋰🇾⋰⋰🇦⋰ ? ⋰🇨⋰⋰🇭⋰⋰🇲⋰⋰🇷⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇦⋰ ⋰🇨⋰⋰🇾⋰⋰🇦⋰ ?",
        "⋰🇹⋰⋰🇲⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇷⋰⋰🇮⋰ ⋰🇭⋰⋰🇴⋰⋰🇬⋰⋰🇮⋰ ⋰🇫⋰⋰🇷⋰⋰🇷⋰⋰🇹⋰⋰🇴⋰",
        "⋰🇨⋰⋰🇾⋰⋰🇦⋰ ? ⋰🇰⋰⋰🇧⋰ ? ⋰🇵⋰⋰🇬⋰⋰🇱⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇨⋰⋰🇾⋰⋰🇦⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇰⋰⋰🇪⋰⋰🇰⋰",
        "⋰🇨⋰⋰🇾⋰⋰🇦⋰ ⋰🇸⋰⋰🇨⋰⋰🇭⋰ ⋰🇲⋰⋰🇪⋰⋰🇾⋰ ⋰🇵⋰⋰🇬⋰⋰🇱⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇨⋰⋰🇾⋰⋰🇦⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇷⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰⋰🇾⋰⋰🇰⋰⋰🇪⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇱⋰⋰🇮⋰ ⋰🇹⋰⋰🇺⋰⋰🇳⋰⋰🇪⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰",
        "⋰🇮⋰⋰🇹⋰⋰🇳⋰⋰🇦⋰ ⋰🇸⋰⋰🇨⋰⋰🇭⋰ ⋰🇳⋰⋰🇾⋰ ⋰🇧⋰⋰🇴⋰⋰🇱⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇦⋰⋰🇮⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇾⋰",
        "⋰🇸⋰⋰🇨⋰⋰🇭⋰ ⋰🇲⋰⋰🇪⋰⋰🇾⋰ ⋰🇵⋰⋰🇬⋰⋰🇱⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇹⋰⋰🇺⋰ ⋰🇦⋰⋰🇵⋰⋰🇳⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇼⋰⋰🇦⋰ ⋰🇱⋰⋰🇮⋰⋰🇦⋰ ⋰🇲⋰⋰🇪⋰⋰🇷⋰⋰🇪⋰ ⋰🇸⋰⋰🇹⋰⋰🇭⋰",
        "⋰🇲⋰⋰🇹⋰⋰🇱⋰⋰🇧⋰ ⋰🇹⋰⋰🇲⋰⋰🇷⋰",
        "⋰🇳⋰⋰🇾⋰⋰🇹⋰⋰🇴⋰",
        "⋰🇵⋰⋰🇺⋰⋰🇷⋰⋰🇦⋰ ⋰🇱⋰⋰🇮⋰⋰🇰⋰⋰🇭⋰ ⋰🇲⋰⋰🇨⋰",
        "⋰🇹⋰⋰🇲⋰⋰🇷⋰ ⋰🇫⋰⋰🇷⋰⋰🇷⋰⋰🇹⋰⋰🇴⋰",
        "⋰🇴⋰⋰🇭⋰ ⋰🇴⋰⋰🇰⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇱⋰⋰🇪⋰ ⋰🇫⋰⋰🇮⋰⋰🇷⋰",
        "⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇰⋰⋰🇦⋰ ⋰🇩⋰⋰🇦⋰⋰🇲⋰⋰🇦⋰⋰🇩⋰",
        "⋰🇨⋰⋰🇾⋰⋰🇦⋰ ? ⋰🇦⋰⋰🇨⋰⋰🇭⋰⋰🇪⋰ ⋰🇸⋰⋰🇪⋰ ⋰🇱⋰⋰🇮⋰⋰🇰⋰⋰🇭⋰⋰🇪⋰ ⋰🇵⋰⋰🇪⋰⋰🇭⋰⋰🇱⋰⋰🇪⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⋰🇰⋰⋰🇪⋰⋰🇧⋰⋰🇦⋰⋰🇨⋰⋰🇭⋰⋰🇪⋰",
        "⋰🇳⋰⋰🇾⋰⋰🇹⋰⋰🇴⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰⋰🇳⋰⋰🇪⋰ ⋰🇲⋰⋰🇪⋰ ⋰🇻⋰⋰🇾⋰⋰🇦⋰⋰🇸⋰⋰🇹⋰ ⋰🇭⋰⋰🇺⋰",
        "⋰🇳⋰⋰🇾⋰⋰🇹⋰⋰🇴⋰ ⋰🇵⋰⋰🇬⋰⋰🇱⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇨⋰⋰🇾⋰⋰🇦⋰ ⋰🇰⋰⋰🇺⋰⋰🇨⋰⋰🇭⋰ ⋰🇧⋰⋰🇮⋰",
        "⋰🇴⋰⋰🇾⋰⋰🇪⋰⋰🇪⋰ ⋰🇨⋰⋰🇾⋰⋰🇦⋰ ? ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇬⋰⋰🇾⋰⋰🇦⋰ ?",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇲⋰⋰🇹⋰ ⋰🇭⋰⋰🇸⋰⋰🇸⋰",
        "⋰🇾⋰⋰🇺⋰⋰🇷⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⊶⊶🇮⋰ ⋰🇲⋰⋰🇴⋰⋰🇲⋰",
        "⋰🇦⋰⋰🇷⋰⋰🇪⋰ ⋰🇸⋰⋰🇧⋰⋰🇰⋰⋰🇮⋰ ⋰🇲⋰⋰??⋰⋰🇦⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⊶⊶🇮⋰ ⋰🇴⋰⋰🇷⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇧⋰⋰🇮⋰",
        "⋰🇦⋰⋰🇷⋰⋰🇪⋰ ⋰🇮⋰⋰🇩⋰⋰🇦⋰⋰🇷⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰⋰🇱⋰⋰🇪⋰ ⋰🇪⋰⋰🇰⋰ ⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇷⋰",
        "⋰🇹⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇮⋰ ⋰🇹⋰⋰🇷⋰⋰🇭⋰",
        "⋰🇪⋰⋰🇰⋰ ⋰🇱⋰⋰🇮⋰⋰🇳⋰⋰🇪⋰ ⋰🇲⋰⋰🇪⋰ ⋰🇹⋰⋰🇲⋰⋰🇷⋰",
        "⋰🇶⋰",
        "⋰🇴⋰⋰🇨⋰⋰🇾⋰ ⋰🇦⋰⋰🇧⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇱⋰⋰🇪⋰",
        "⋰🇵⋰⋰🇪⋰⋰🇭⋰⋰🇪⋰⋰🇱⋰⋰🇪⋰ ⋰🇹⋰⋰🇪⋰⋰🇷⋰⋰🇮⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰ ⋰🇨⋰⋰🇭⋰⋰🇴⋰⋰🇩⋰⋰🇺⋰",
        "⋰🇳⋰⋰🇾⋰⋰🇹⋰⋰🇴⋰",
        "⋰🇶⋰ ?",
        "⋰??⋰⋰🇾⋰⋰🇾⋰⋰🇾⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇩⋰⋰🇮⋰⋰🇰⋰⋰🇦⋰ ⋰🇪⋰⋰🇰⋰ ⋰🇧⋰⋰🇦⋰⋰🇦⋰⋰🇷⋰",
        "⋰🇴⋰⋰🇾⋰⋰🇪⋰⋰🇪⋰ ⋰🇸⋰⋰🇺⋰⋰🇳⋰ ⋰🇩⋰⋰🇴⋰⋰🇸⋰⋰🇹⋰ ⋰🇹⋰⋰🇲⋰⋰🇷⋰",
        "⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇯⋰⋰🇦⋰ ⋰🇷⋰⋰🇦⋰⋰🇦⋰⋰🇳⋰⋰🇩⋰ ⋰🇲⋰⋰🇦⋰⋰🇦⋰⋰🇫⋰ ⋰🇨⋰⋰🇷⋰⋰🇷⋰ ⋰🇩⋰⋰🇺⋰⋰🇳⋰⋰🇬⋰⋰🇦⋰",
        "⋰🇴⋰⋰🇾⋰⋰🇪⋰⋰🇪⋰ ⋰🇵⋰⋰🇬⋰⋰🇱⋰ ⋰🇷⋰⋰🇳⋰⋰🇩⋰⋰🇮⋰⊶⊶🇮⋰ ⋰🇮⋰⋰🇩⋰⋰🇦⋰⋰🇷⋰ ⋰🇦⋰⋰🇦⋰",
        "⋰🇨⋰⋰🇾⋰⋰🇦⋰ ⋰🇹⋰⋰🇲⋰⋰🇷⋰ ⋰🇫⋰⋰🇷⋰⋰🇷⋰⋰🇹⋰⋰🇴⋰",
        "⋰🇴⋰⋰🇾⋰⋰🇪⋰⋰🇪⋰ ⋰🇮⋰⋰🇩⋰⋰🇦⋰⋰🇷⋰ ⋰🇦⋰⋰🇦⋰⋰🇰⋰⋰🇪⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇱⋰⋰🇪⋰ ⋰🇨⋰⋰🇭⋰⋰🇲⋰⋰🇷⋰",
        "⋰🇳⋰⋰🇾⋰⋰🇹⋰⋰🇴⋰ ⋰🇦⋰⋰🇪⋰⋰🇸⋰⋰🇪⋰ ⋰🇭⋰⋰🇮⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰",
        "⋰🇴⋰⋰🇾⋰⋰🇪⋰⋰🇪⋰ ⋰🇭⋰⋰🇾⋰⋰🇾⋰ ⋰🇦⋰⋰🇮⋰⋰🇸⋰⋰🇪⋰ ⋰🇭⋰⋰🇮⋰ ⋰🇨⋰⋰🇺⋰⋰🇩⋰ ⋰🇱⋰⋰🇪⋰⋰🇳⋰⋰🇦⋰",
        "⋰🇴⋰⋰🇷⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇱⋰⋰🇪⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇰⋰⋰🇪⋰ ⋰🇩⋰⋰🇮⋰⋰🇰⋰⋰🇦⋰ ⋰🇴⋰⋰🇷⋰",
        "⋰🇭⋰⋰🇾⋰⋰🇾⋰ ⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇴⋰ ⋰??⋰⋰🇦⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰⋰🇴⋰ ⋰🇲⋰⋰🇹⋰ ⋰🇧⋰⋰🇭⋰⋰🇦⋰⋰🇬⋰ ⋰🇯⋰⋰🇦⋰⋰🇴⋰",
        "⋰🇧⋰⋰🇾⋰⋰🇾⋰⋰🇪⋰⋰🇪⋰ ⋰🇭⋰⋰🇾⋰⋰🇾⋰ ⋰🇨⋰⋰🇾⋰⋰🇦⋰ ?",
        "⋰🇶⋰⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇶⋰ ⋰🇷⋰⋰🇭⋰⋰🇪⋰ ⋰🇭⋰⋰🇴⋰ ?",
        "⋰🇵⋰⋰🇬⋰⋰🇱⋰ ⋰🇪⋰⋰🇾⋰ ⋰🇨⋰⋰🇾⋰⋰🇦⋰ ⋰🇲⋰⋰🇨⋰",
        "⋰🇨⋰⋰🇭⋰⋰🇺⋰⋰🇩⋰ ⋰🇲⋰⋰🇹⋰",
        ]

            
        bs3_texts = [
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰ ⋰🄱⋰⋰🄾⋰⋰🄻⋰ ⋰🅃⋰⋰🄾⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄳⋰⋰??⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄴⋰ ⋰🄼⋰⋰🅄⋰⋰🄷⋰ ⋰🄼⋰⋰🄴⋰ ⋰🅁⋰⋰🄰⋰⋰🄶⋰⋰🄰⋰⋰🄳⋰ ⋰🄳⋰⋰🅄⋰",
        "⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰ ⋰??⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄼⋰⋰🄴⋰ ⋰🄻⋰⋰🄾⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🄰⋰⋰🄰⋰⋰🄻⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄼⋰⋰🄰⋰⋰🅂⋰⋰🄰⋰⋰🄻⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰",
        "⋰🄵⋰⋰🄰⋰⋰🄼⋰⋰🄴⋰ ⋰🄻⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄿⋰⋰🄴⋰ ⋰🅃⋰⋰🄷⋰⋰🄰⋰⋰🄿⋰⋰🄿⋰⋰🄰⋰⋰🄳⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🅄⋰",
        "⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄼⋰⋰🄴⋰ ⋰🄻⋰⋰🄾⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🄰⋰⋰🄰⋰⋰🄻⋰⋰🅄⋰",
        "⋰🅇⋰⋰🄷⋰⋰🄰⋰⋰🄻⋰ ⋰🅄⋰⋰🅃⋰⋰🄷⋰ ⋰🄼⋰⋰🄰⋰⋰🄳⋰⋰🄷⋰⋰🄴⋰⋰🅁⋰⋰🄲⋰⋰🄷⋰⋰??⋰⋰🄳⋰",
        "⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🄽⋰⋰🄰⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄻⋰⋰🄰⋰⋰🄳⋰⋰🄺⋰⋰🄴⋰",
        "⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄱⋰⋰🅄⋰⋰🄳⋰⋰🄷⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄻⋰⋰🄰⋰⋰🄳⋰⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄸⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄳⋰⋰🄷⋰⋰🄴⋰⋰🅁⋰⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰ ⋰🄲⋰⋰🄷⋰⋰🄰⋰⋰🄻⋰ ⋰🅄⋰⋰🅃⋰⋰🄷⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄰⋰⋰🄺⋰⋰🄴⋰⋰🄻⋰⋰🄰⋰ ⋰🄿⋰⋰🄰⋰⋰🄽⋰ ⋰🄼⋰⋰🄸⋰⋰🅃⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰ ⋰🄱⋰⋰🄸⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰⋰🄸⋰ ⋰🅇⋰⋰🄷⋰⋰🄰⋰⋰🄻⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄷⋰⋰🄾⋰ ⋰🄹⋰⋰🄰⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰⋰🄽⋰ ⋰🄺⋰⋰🄸⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰⋰🅃⋰⋰🅃⋰ ⋰🄿⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰ ⋰🄲⋰⋰🄷⋰⋰🄰⋰⋰🄿⋰⋰🄿⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰⋰🄻⋰⋰🄻⋰⋰🄻⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄽⋰⋰🄰⋰⋰🄽⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄺⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄱⋰⋰🄾⋰⋰🄾⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄴⋰⋰🅁⋰⋰🅁⋰ ⋰🄵⋰⋰🄰⋰⋰🄰⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰⋰🅃⋰⋰🅃⋰ ⋰🅂⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰⋰🅁⋰⋰🅁⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰⋰🄻⋰⋰🄻⋰⋰🄻⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰⋰🄹⋰⋰🄹⋰ ⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄱⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄵⋰⋰🄰⋰⋰🄰⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰ ⋰🅁⋰⋰🄴⋰⋰🄿⋰⋰??⋰⋰🅈⋰⋰🅈⋰⋰🅈⋰ ⋰🄺⋰⋰🅁⋰⋰🅁⋰⋰🅁⋰⋰🅁⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄱⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄽⋰⋰🄸⋰⋰🄻⋰⋰🄰⋰⋰🄰⋰⋰🄼⋰⋰🄼⋰⋰🄼⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰⋰🄽⋰⋰🄽⋰ ⋰🄺⋰⋰🄾⋰⋰🄾⋰⋰🄾⋰ ⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰⋰🄺⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰ ⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰⋰🄰⋰⋰🄰⋰ ⋰🅂⋰⋰🄴⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰⋰🅁⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰⋰🄶⋰⋰🄶⋰⋰🄶⋰ ⋰🄹⋰⋰🄰⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🅁⋰⋰🄴⋰⋰🄿⋰⋰🄻⋰⋰🅈⋰⋰🅈⋰⋰🅈⋰ ⋰🄳⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄺⋰⋰🄰⋰⋰🄰⋰⋰🄻⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄺⋰⋰🄰⋰⋰🄰⋰⋰🄻⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰⋰🅃⋰⋰🅃⋰ ⋰🄼⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰ ⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰⋰🄽⋰⋰🄽⋰ ⋰🄺⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰⋰🅃⋰ ⋰🄼⋰⋰🄴⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰⋰🄽⋰ ⋰🄷⋰⋰🄰⋰⋰🅃⋰⋰🄷⋰⋰🄷⋰⋰🄷⋰ ⋰🄳⋰⋰🄰⋰⋰🄰⋰⋰🄻⋰⋰🄻⋰⋰🄻⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰⋰🄹⋰⋰🄹⋰⋰🄹⋰ ⋰??⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰⋰🄽⋰⋰🄽⋰",
        "⋰🅂⋰⋰🄿⋰⋰🄴⋰⋰🄴⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🄿⋰⋰🄰⋰⋰🄺⋰⋰🄰⋰⋰🄰⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰⋰🄴⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰",
        "⋰🅂⋰⋰🄿⋰⋰🄴⋰⋰🄴⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🄻⋰⋰🄴⋰⋰🄺⋰⋰🄺⋰⋰🄰⋰⋰🅁⋰⋰🅁⋰⋰🅁⋰ ⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🄳⋰⋰🄰⋰⋰🅁⋰⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🅂⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰",
        "⋰🅁⋰⋰🄴⋰⋰🄿⋰⋰🄻⋰⋰🅈⋰⋰🅈⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄺⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰ ⋰🄽⋰⋰🄰⋰⋰🄽⋰⋰🄸⋰ ⋰🄺⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰⋰🅃⋰ ⋰🄺⋰⋰🄰⋰⋰🄰⋰ ⋰🄱⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄱⋰⋰🄰⋰⋰🄽⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄺⋰⋰🄰⋰⋰🅃⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄰⋰⋰🅄⋰⋰🄻⋰⋰🄰⋰⋰🄳⋰ ⋰🄷⋰⋰🄰⋰⋰🄸⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄺⋰⋰🄰⋰⋰🅃⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄰⋰⋰🅄⋰⋰🄻⋰⋰🄰⋰⋰🄳⋰ ⋰🄷⋰⋰🄰⋰⋰🄸⋰ ⋰🅃⋰⋰🅄⋰ ⋰🄼⋰⋰🄰⋰⋰🄳⋰⋰🄰⋰⋰🅁⋰⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰⋰🄳⋰ ⋰🄺⋰⋰🄸⋰⋰🄳⋰⋰🄳⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🅂⋰⋰🄰⋰⋰🅃⋰⋰🄷⋰ ⋰🅂⋰⋰🄾⋰ ⋰🄹⋰⋰🄰⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🅅⋰⋰🄾⋰⋰🄸⋰⋰🄲⋰⋰🄴⋰ ⋰🄷⋰⋰🄾⋰ ⋰🄹⋰⋰🄰⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰ ⋰🅂⋰⋰🄴⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🅄⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰ ⋰🅂⋰⋰🄰⋰⋰🄺⋰⋰🅃⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄻⋰⋰🄰⋰⋰🅄⋰⋰🄳⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄱⋰⋰🄰⋰⋰🄰⋰⋰🄿⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄸⋰⋰🄶⋰⋰🄽⋰⋰🄾⋰⋰🅁⋰⋰🄴⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄺⋰⋰🄰⋰⋰🅃⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰ ⋰🄹⋰⋰🄰⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🅄⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🄸⋰⋰🄶⋰⋰🄽⋰⋰🄾⋰⋰🅁⋰⋰🄴⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🅁⋰⋰🄰⋰ ⋰🄷⋰⋰🄰⋰⋰🄸⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰ ⋰??⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄵⋰⋰🄰⋰⋰🅃⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄰⋰ ⋰🄻⋰⋰🄾⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🄰⋰⋰🄻⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄰⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄾⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄰⋰⋰🄰⋰⋰🄿⋰ ⋰🄲⋰⋰🄿⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄺⋰⋰🄰⋰⋰🄻⋰⋰🄸⋰ ⋰🄹⋰⋰🅄⋰⋰🄱⋰⋰🄰⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰⋰🅃⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄵⋰⋰🄴⋰⋰🄽⋰⋰🄺⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰??⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄽⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰ ⋰🄹⋰⋰🄰⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄼⋰⋰🄰⋰⋰🄸⋰ ⋰🄺⋰⋰🄰⋰⋰🄱⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰⋰🄰⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰ ⋰🅂⋰⋰🄴⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰ ⋰🄺⋰⋰🄴⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄵⋰⋰🄰⋰⋰🅃⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄴⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰ ⋰🄹⋰⋰🄰⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄻⋰⋰🄸⋰⋰🄺⋰⋰🄷⋰ ⋰🄰⋰⋰🄱⋰ ⋰🅃⋰⋰🅄⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄳⋰⋰🄰⋰⋰🄵⋰⋰🄰⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄴⋰ ⋰🄻⋰⋰🄰⋰⋰🅄⋰⋰🄳⋰⋰🄴⋰ ⋰🄿⋰⋰🄴⋰⋰🅁⋰ ⋰🄶⋰⋰??⋰⋰🅄⋰⋰🄼⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄺⋰⋰🄷⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🄺⋰⋰🄷⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🄻⋰⋰🄴⋰⋰🄺⋰⋰🄸⋰⋰🄽⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄹⋰⋰🄷⋰⋰🅄⋰⋰🄺⋰⋰🄽⋰⋰🄴⋰ ⋰🄽⋰⋰🄰⋰⋰🄸⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰ ⋰🄱⋰⋰🄰⋰⋰🄽⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄰⋰ ⋰🅁⋰⋰🄴⋰⋰🄿⋰⋰🄻⋰⋰🅈⋰ ⋰🄷⋰⋰🄾⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄳⋰⋰🄸⋰⋰🄺⋰⋰🄷⋰⋰🄰⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰ ⋰🄹⋰⋰🄰⋰⋰🅈⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰⋰🄽⋰⋰🄰⋰ ⋰🄲⋰⋰🄷⋰⋰🄰⋰⋰🄻⋰⋰🅄⋰ ⋰🄺⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🅃⋰⋰🄾⋰ ⋰🄲⋰⋰🄿⋰ ⋰🄱⋰⋰🄾⋰⋰🄻⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🅄⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄰⋰⋰🅃⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰ ⋰🄷⋰⋰🄾⋰⋰🄹⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🅄⋰⋰🅃⋰⋰🄷⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄵⋰⋰🄴⋰⋰🄽⋰⋰🄺⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🄿⋰ ⋰🄼⋰⋰🄰⋰⋰🄳⋰⋰🅁⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄺⋰⋰🄾⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰??⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰ ⋰🄹⋰⋰🄰⋰⋰🅈⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄴⋰ ⋰🄻⋰⋰🄰⋰⋰🅄⋰⋰🄳⋰⋰🄴⋰ ⋰🄿⋰⋰🄴⋰",
        "⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄳⋰⋰🄸⋰⋰🄺⋰⋰🄷⋰⋰🄰⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄳⋰⋰🄰⋰⋰🄵⋰⋰🄰⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰⋰🄾⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🄼⋰⋰🄴⋰⋰🄴⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🅂⋰⋰🄰⋰⋰🅃⋰⋰🄷⋰ ⋰🅃⋰⋰🅄⋰ ⋰🄱⋰⋰🄷⋰⋰🄸⋰ ⋰🄳⋰⋰🄰⋰⋰🄵⋰⋰🄰⋰⋰🄽⋰ ⋰🄷⋰⋰🄾⋰ ⋰🄹⋰⋰🄰⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄰⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄷⋰⋰🄰⋰⋰🄸⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰??⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🅂⋰⋰🄴⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰",
        "⋰🄶⋰⋰🄰⋰⋰🄸⋰⋰🅁⋰⋰🄱⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄰⋰⋰🅄⋰⋰🄻⋰⋰🄰⋰⋰🄳⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄱⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰⋰🄿⋰ ⋰🄺⋰⋰🄸⋰ ⋰🅂⋰⋰🄿⋰⋰🄴⋰⋰🄴⋰⋰🄳⋰ ⋰🄼⋰⋰🄰⋰⋰🅃⋰⋰🄲⋰⋰🄷⋰ ⋰🄺⋰⋰🅁⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰ ⋰🄶⋰⋰🄰⋰⋰🅁⋰⋰🄸⋰⋰🄱⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄲⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅃⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄵⋰⋰🄴⋰⋰🄺⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄴⋰⋰🄴⋰⋰🄹⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰??⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄲⋰⋰🄿⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰ ⋰🅃⋰⋰🅄⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄴⋰ ⋰🄺⋰⋰🄾⋰ ⋰🅃⋰⋰🄰⋰⋰🄶⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄺⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰⋰🅁⋰ ⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄵⋰⋰🄰⋰⋰🅃⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄴⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰ ⋰🄹⋰⋰🄰⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄻⋰⋰🄸⋰⋰🄺⋰⋰🄷⋰ ⋰🄰⋰⋰🄱⋰ ⋰🅃⋰⋰🅄⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄳⋰⋰🄰⋰⋰🄵⋰⋰🄰⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄴⋰ ⋰🄻⋰⋰🄰⋰⋰🅄⋰⋰🄳⋰⋰🄴⋰ ⋰🄿⋰⋰🄴⋰⋰🅁⋰ ⋰🄶⋰⋰🄷⋰⋰🅄⋰⋰🄼⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄺⋰⋰🄷⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🄺⋰⋰🄷⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🄻⋰⋰🄴⋰⋰🄺⋰⋰🄸⋰⋰🄽⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄹⋰⋰🄷⋰⋰🅄⋰⋰🄺⋰⋰🄽⋰⋰🄴⋰ ⋰🄽⋰⋰🄰⋰⋰🄸⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰ ⋰🄱⋰⋰🄰⋰⋰🄽⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄰⋰ ⋰🅁⋰⋰🄴⋰⋰🄿⋰⋰🄻⋰⋰🅈⋰ ⋰🄷⋰⋰🄾⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄳⋰⋰🄸⋰⋰🄺⋰⋰🄷⋰⋰🄰⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰??⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰??⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰ ⋰🄹⋰⋰🄰⋰⋰🅈⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰⋰🄽⋰⋰🄰⋰ ⋰🄲⋰⋰🄷⋰⋰🄰⋰⋰🄻⋰⋰🅄⋰ ⋰🄺⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🅃⋰⋰🄾⋰ ⋰🄲⋰⋰🄿⋰ ⋰🄱⋰⋰🄾⋰⋰🄻⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🅄⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄰⋰⋰🅃⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰??⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰ ⋰🄷⋰⋰🄾⋰⋰🄹⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🅄⋰⋰🅃⋰⋰🄷⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄵⋰⋰🄴⋰⋰🄽⋰⋰🄺⋰ ⋰🄳⋰⋰🅄⋰⋰??⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🄿⋰ ⋰🄼⋰⋰🄰⋰⋰🄳⋰⋰🅁⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄺⋰⋰🄾⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰ ⋰🄹⋰⋰🄰⋰⋰🅈⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄴⋰ ⋰🄻⋰⋰🄰⋰⋰🅄⋰⋰🄳⋰⋰🄴⋰ ⋰🄿⋰⋰🄴⋰",
        "⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄳⋰⋰🄸⋰⋰🄺⋰⋰🄷⋰⋰🄰⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄳⋰⋰🄰⋰⋰🄵⋰⋰🄰⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰⋰🄾⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🄼⋰⋰🄴⋰⋰🄴⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🅂⋰⋰🄰⋰⋰🅃⋰⋰🄷⋰ ⋰🅃⋰⋰🅄⋰ ⋰🄱⋰⋰🄷⋰⋰🄸⋰ ⋰🄳⋰⋰🄰⋰⋰🄵⋰⋰🄰⋰⋰🄽⋰ ⋰🄷⋰⋰🄾⋰ ⋰🄹⋰⋰🄰⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄰⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄷⋰⋰🄰⋰⋰🄸⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🅂⋰⋰🄴⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰",
        "⋰🄶⋰⋰🄰⋰⋰🄸⋰⋰🅁⋰⋰🄱⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄰⋰⋰🅄⋰⋰🄻⋰⋰🄰⋰⋰🄳⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄱⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰⋰🄿⋰ ⋰🄺⋰⋰🄸⋰ ⋰🅂⋰⋰🄿⋰⋰🄴⋰⋰🄴⋰⋰🄳⋰ ⋰🄼⋰⋰🄰⋰⋰🅃⋰⋰🄲⋰⋰🄷⋰ ⋰🄺⋰⋰🅁⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰ ⋰🄶⋰⋰🄰⋰⋰🅁⋰⋰🄸⋰⋰🄱⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄲⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅃⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄵⋰⋰🄴⋰⋰🄺⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄴⋰⋰🄴⋰⋰🄹⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄲⋰⋰🄿⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰ ⋰🅃⋰⋰🅄⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄴⋰ ⋰🄺⋰⋰🄾⋰ ⋰🅃⋰⋰🄰⋰⋰🄶⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄺⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰⋰🅁⋰ ⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰"
        ]

            
        sqs_texts = [
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰ ⋰🄱⋰⋰🄾⋰⋰🄻⋰ ⋰🅃⋰⋰🄾⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄳⋰⋰??⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄴⋰ ⋰🄼⋰⋰🅄⋰⋰🄷⋰ ⋰🄼⋰⋰🄴⋰ ⋰🅁⋰⋰🄰⋰⋰🄶⋰⋰🄰⋰⋰🄳⋰ ⋰🄳⋰⋰🅄⋰",
        "⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰ ⋰??⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄼⋰⋰🄴⋰ ⋰🄻⋰⋰🄾⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🄰⋰⋰🄰⋰⋰🄻⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄼⋰⋰🄰⋰⋰🅂⋰⋰🄰⋰⋰🄻⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰",
        "⋰🄵⋰⋰🄰⋰⋰🄼⋰⋰🄴⋰ ⋰🄻⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄿⋰⋰🄴⋰ ⋰🅃⋰⋰🄷⋰⋰🄰⋰⋰🄿⋰⋰🄿⋰⋰🄰⋰⋰🄳⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🅄⋰",
        "⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄼⋰⋰🄴⋰ ⋰🄻⋰⋰🄾⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🄰⋰⋰🄰⋰⋰🄻⋰⋰🅄⋰",
        "⋰🅇⋰⋰🄷⋰⋰🄰⋰⋰🄻⋰ ⋰🅄⋰⋰🅃⋰⋰🄷⋰ ⋰🄼⋰⋰🄰⋰⋰🄳⋰⋰🄷⋰⋰🄴⋰⋰🅁⋰⋰🄲⋰⋰🄷⋰⋰??⋰⋰🄳⋰",
        "⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🄽⋰⋰🄰⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄻⋰⋰🄰⋰⋰🄳⋰⋰🄺⋰⋰🄴⋰",
        "⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄱⋰⋰🅄⋰⋰🄳⋰⋰🄷⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄻⋰⋰🄰⋰⋰🄳⋰⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄸⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄳⋰⋰🄷⋰⋰🄴⋰⋰🅁⋰⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰ ⋰🄲⋰⋰🄷⋰⋰🄰⋰⋰🄻⋰ ⋰🅄⋰⋰🅃⋰⋰🄷⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄰⋰⋰🄺⋰⋰🄴⋰⋰🄻⋰⋰🄰⋰ ⋰🄿⋰⋰🄰⋰⋰🄽⋰ ⋰🄼⋰⋰🄸⋰⋰🅃⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰ ⋰🄱⋰⋰🄸⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰⋰🄸⋰ ⋰🅇⋰⋰🄷⋰⋰🄰⋰⋰🄻⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄷⋰⋰🄾⋰ ⋰🄹⋰⋰🄰⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰⋰🄽⋰ ⋰🄺⋰⋰🄸⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰⋰🅃⋰⋰🅃⋰ ⋰🄿⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰ ⋰🄲⋰⋰🄷⋰⋰🄰⋰⋰🄿⋰⋰🄿⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰⋰🄻⋰⋰🄻⋰⋰🄻⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄽⋰⋰🄰⋰⋰🄽⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄺⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄱⋰⋰🄾⋰⋰🄾⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄴⋰⋰🅁⋰⋰🅁⋰ ⋰🄵⋰⋰🄰⋰⋰🄰⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰⋰🅃⋰⋰🅃⋰ ⋰🅂⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰⋰🅁⋰⋰🅁⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰⋰🄻⋰⋰🄻⋰⋰🄻⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰⋰🄹⋰⋰🄹⋰ ⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄱⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄵⋰⋰🄰⋰⋰🄰⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰ ⋰🅁⋰⋰🄴⋰⋰🄿⋰⋰??⋰⋰🅈⋰⋰🅈⋰⋰🅈⋰ ⋰🄺⋰⋰🅁⋰⋰🅁⋰⋰🅁⋰⋰🅁⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄱⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄽⋰⋰🄸⋰⋰🄻⋰⋰🄰⋰⋰🄰⋰⋰🄼⋰⋰🄼⋰⋰🄼⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰⋰🄽⋰⋰🄽⋰ ⋰🄺⋰⋰🄾⋰⋰🄾⋰⋰🄾⋰ ⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰⋰🄺⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰ ⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰⋰🄰⋰⋰🄰⋰ ⋰🅂⋰⋰🄴⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰⋰🅁⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰⋰🄶⋰⋰🄶⋰⋰🄶⋰ ⋰🄹⋰⋰🄰⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🅁⋰⋰🄴⋰⋰🄿⋰⋰🄻⋰⋰🅈⋰⋰🅈⋰⋰🅈⋰ ⋰🄳⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄺⋰⋰🄰⋰⋰🄰⋰⋰🄻⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄺⋰⋰🄰⋰⋰🄰⋰⋰🄻⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰⋰🅃⋰⋰🅃⋰ ⋰🄼⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰ ⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰⋰🄽⋰⋰🄽⋰ ⋰🄺⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰⋰🅃⋰ ⋰🄼⋰⋰🄴⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰⋰🄽⋰ ⋰🄷⋰⋰🄰⋰⋰🅃⋰⋰🄷⋰⋰🄷⋰⋰🄷⋰ ⋰🄳⋰⋰🄰⋰⋰🄰⋰⋰🄻⋰⋰🄻⋰⋰🄻⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰⋰🄹⋰⋰🄹⋰⋰🄹⋰ ⋰??⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰⋰🄽⋰⋰🄽⋰",
        "⋰🅂⋰⋰🄿⋰⋰🄴⋰⋰🄴⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🄿⋰⋰🄰⋰⋰🄺⋰⋰🄰⋰⋰🄰⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰⋰🄴⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰",
        "⋰🅂⋰⋰🄿⋰⋰🄴⋰⋰🄴⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🄻⋰⋰🄴⋰⋰🄺⋰⋰🄺⋰⋰🄰⋰⋰🅁⋰⋰🅁⋰⋰🅁⋰ ⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🄳⋰⋰🄰⋰⋰🅁⋰⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰⋰🄳⋰⋰🄳⋰ ⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🅂⋰⋰🄴⋰⋰🄴⋰⋰🄴⋰",
        "⋰🅁⋰⋰🄴⋰⋰🄿⋰⋰🄻⋰⋰🅈⋰⋰🅈⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄺⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰ ⋰🄽⋰⋰🄰⋰⋰🄽⋰⋰🄸⋰ ⋰🄺⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰⋰🅃⋰ ⋰🄺⋰⋰🄰⋰⋰🄰⋰ ⋰🄱⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄱⋰⋰🄰⋰⋰🄽⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄺⋰⋰🄰⋰⋰🅃⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄰⋰⋰🅄⋰⋰🄻⋰⋰🄰⋰⋰🄳⋰ ⋰🄷⋰⋰🄰⋰⋰🄸⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄴⋰⋰🄽⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄺⋰⋰🄰⋰⋰🅃⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄰⋰⋰🅄⋰⋰🄻⋰⋰🄰⋰⋰🄳⋰ ⋰🄷⋰⋰🄰⋰⋰🄸⋰ ⋰🅃⋰⋰🅄⋰ ⋰🄼⋰⋰🄰⋰⋰🄳⋰⋰🄰⋰⋰🅁⋰⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰⋰🄳⋰ ⋰🄺⋰⋰🄸⋰⋰🄳⋰⋰🄳⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🅂⋰⋰🄰⋰⋰🅃⋰⋰🄷⋰ ⋰🅂⋰⋰🄾⋰ ⋰🄹⋰⋰🄰⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🅅⋰⋰🄾⋰⋰🄸⋰⋰🄲⋰⋰🄴⋰ ⋰🄷⋰⋰🄾⋰ ⋰🄹⋰⋰🄰⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰ ⋰🅂⋰⋰🄴⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🅄⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰ ⋰🅂⋰⋰🄰⋰⋰🄺⋰⋰🅃⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄻⋰⋰🄰⋰⋰🅄⋰⋰🄳⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄱⋰⋰🄰⋰⋰🄰⋰⋰🄿⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄸⋰⋰🄶⋰⋰🄽⋰⋰🄾⋰⋰🅁⋰⋰🄴⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄺⋰⋰🄰⋰⋰🅃⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰ ⋰🄹⋰⋰🄰⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🅄⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🄸⋰⋰🄶⋰⋰🄽⋰⋰🄾⋰⋰🅁⋰⋰🄴⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🅁⋰⋰🄰⋰ ⋰🄷⋰⋰🄰⋰⋰🄸⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰⋰🄸⋰ ⋰??⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄵⋰⋰🄰⋰⋰🅃⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄰⋰ ⋰🄻⋰⋰🄾⋰⋰🄳⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🄰⋰⋰🄻⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄰⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄾⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄰⋰⋰🄰⋰⋰🄿⋰ ⋰🄲⋰⋰🄿⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄺⋰⋰🄰⋰⋰🄻⋰⋰🄸⋰ ⋰🄹⋰⋰🅄⋰⋰🄱⋰⋰🄰⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰⋰🅃⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄵⋰⋰🄴⋰⋰🄽⋰⋰🄺⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰??⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄽⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰ ⋰🄹⋰⋰🄰⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄼⋰⋰🄰⋰⋰🄸⋰ ⋰🄺⋰⋰🄰⋰⋰🄱⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰⋰🄰⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰ ⋰🅂⋰⋰🄴⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰ ⋰🄺⋰⋰🄴⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄵⋰⋰🄰⋰⋰🅃⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄴⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰ ⋰🄹⋰⋰🄰⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄻⋰⋰🄸⋰⋰🄺⋰⋰🄷⋰ ⋰🄰⋰⋰🄱⋰ ⋰🅃⋰⋰🅄⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄳⋰⋰🄰⋰⋰🄵⋰⋰🄰⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄴⋰ ⋰🄻⋰⋰🄰⋰⋰🅄⋰⋰🄳⋰⋰🄴⋰ ⋰🄿⋰⋰🄴⋰⋰🅁⋰ ⋰🄶⋰⋰??⋰⋰🅄⋰⋰🄼⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄺⋰⋰🄷⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🄺⋰⋰🄷⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🄻⋰⋰🄴⋰⋰🄺⋰⋰🄸⋰⋰🄽⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄹⋰⋰🄷⋰⋰🅄⋰⋰🄺⋰⋰🄽⋰⋰🄴⋰ ⋰🄽⋰⋰🄰⋰⋰🄸⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰ ⋰🄱⋰⋰🄰⋰⋰🄽⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄰⋰ ⋰🅁⋰⋰🄴⋰⋰🄿⋰⋰🄻⋰⋰🅈⋰ ⋰🄷⋰⋰🄾⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄳⋰⋰🄸⋰⋰🄺⋰⋰🄷⋰⋰🄰⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰ ⋰🄹⋰⋰🄰⋰⋰🅈⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰⋰🄽⋰⋰🄰⋰ ⋰🄲⋰⋰🄷⋰⋰🄰⋰⋰🄻⋰⋰🅄⋰ ⋰🄺⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🅃⋰⋰🄾⋰ ⋰🄲⋰⋰🄿⋰ ⋰🄱⋰⋰🄾⋰⋰🄻⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🅄⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄰⋰⋰🅃⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰ ⋰🄷⋰⋰🄾⋰⋰🄹⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🅄⋰⋰🅃⋰⋰🄷⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄵⋰⋰🄴⋰⋰🄽⋰⋰🄺⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🄿⋰ ⋰🄼⋰⋰🄰⋰⋰🄳⋰⋰🅁⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄺⋰⋰🄾⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰??⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰ ⋰🄹⋰⋰🄰⋰⋰🅈⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄴⋰ ⋰🄻⋰⋰🄰⋰⋰🅄⋰⋰🄳⋰⋰🄴⋰ ⋰🄿⋰⋰🄴⋰",
        "⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄳⋰⋰🄸⋰⋰🄺⋰⋰🄷⋰⋰🄰⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄳⋰⋰🄰⋰⋰🄵⋰⋰🄰⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰⋰🄾⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🄼⋰⋰🄴⋰⋰🄴⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🅂⋰⋰🄰⋰⋰🅃⋰⋰🄷⋰ ⋰🅃⋰⋰🅄⋰ ⋰🄱⋰⋰🄷⋰⋰🄸⋰ ⋰🄳⋰⋰🄰⋰⋰🄵⋰⋰🄰⋰⋰🄽⋰ ⋰🄷⋰⋰🄾⋰ ⋰🄹⋰⋰🄰⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄰⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄷⋰⋰🄰⋰⋰🄸⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰??⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🅂⋰⋰🄴⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰",
        "⋰🄶⋰⋰🄰⋰⋰🄸⋰⋰🅁⋰⋰🄱⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄰⋰⋰🅄⋰⋰🄻⋰⋰🄰⋰⋰🄳⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄱⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰⋰🄿⋰ ⋰🄺⋰⋰🄸⋰ ⋰🅂⋰⋰🄿⋰⋰🄴⋰⋰🄴⋰⋰🄳⋰ ⋰🄼⋰⋰🄰⋰⋰🅃⋰⋰🄲⋰⋰🄷⋰ ⋰🄺⋰⋰🅁⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰ ⋰🄶⋰⋰🄰⋰⋰🅁⋰⋰🄸⋰⋰🄱⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄲⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅃⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄵⋰⋰🄴⋰⋰🄺⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄴⋰⋰🄴⋰⋰🄹⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰??⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄲⋰⋰🄿⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰ ⋰🅃⋰⋰🅄⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄴⋰ ⋰🄺⋰⋰🄾⋰ ⋰🅃⋰⋰🄰⋰⋰🄶⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄺⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰⋰🅁⋰ ⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄵⋰⋰🄰⋰⋰🅃⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄴⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰ ⋰🄹⋰⋰🄰⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄻⋰⋰🄸⋰⋰🄺⋰⋰🄷⋰ ⋰🄰⋰⋰🄱⋰ ⋰🅃⋰⋰🅄⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄳⋰⋰🄰⋰⋰🄵⋰⋰🄰⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄴⋰ ⋰🄻⋰⋰🄰⋰⋰🅄⋰⋰🄳⋰⋰🄴⋰ ⋰🄿⋰⋰🄴⋰⋰🅁⋰ ⋰🄶⋰⋰🄷⋰⋰🅄⋰⋰🄼⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄺⋰⋰🄷⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🄺⋰⋰🄷⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🄻⋰⋰🄴⋰⋰🄺⋰⋰🄸⋰⋰🄽⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄹⋰⋰🄷⋰⋰🅄⋰⋰🄺⋰⋰🄽⋰⋰🄴⋰ ⋰🄽⋰⋰🄰⋰⋰🄸⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰ ⋰🄱⋰⋰🄰⋰⋰🄽⋰⋰🄰⋰⋰🄰⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄰⋰ ⋰🅁⋰⋰🄴⋰⋰🄿⋰⋰🄻⋰⋰🅈⋰ ⋰🄷⋰⋰🄾⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄳⋰⋰🄸⋰⋰🄺⋰⋰🄷⋰⋰🄰⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰??⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰??⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰ ⋰🄹⋰⋰🄰⋰⋰🅈⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰⋰🄽⋰⋰🄰⋰ ⋰🄲⋰⋰🄷⋰⋰🄰⋰⋰🄻⋰⋰🅄⋰ ⋰🄺⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🅃⋰⋰🄾⋰ ⋰🄲⋰⋰🄿⋰ ⋰🄱⋰⋰🄾⋰⋰🄻⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🅄⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄰⋰⋰🅃⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🅁⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰??⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰ ⋰🄷⋰⋰🄾⋰⋰🄹⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🅄⋰⋰🅃⋰⋰🄷⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄵⋰⋰🄴⋰⋰🄽⋰⋰🄺⋰ ⋰🄳⋰⋰🅄⋰⋰??⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🄿⋰ ⋰🄼⋰⋰🄰⋰⋰🄳⋰⋰🅁⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄾⋰⋰🄳⋰",
        "⋰🄹⋰⋰🄰⋰⋰🄻⋰⋰🄳⋰⋰🄸⋰ ⋰🄹⋰⋰🄸⋰⋰🄽⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄺⋰⋰🄾⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰ ⋰🄹⋰⋰🄰⋰⋰🅈⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄴⋰ ⋰🄻⋰⋰🄰⋰⋰🅄⋰⋰🄳⋰⋰🄴⋰ ⋰🄿⋰⋰🄴⋰",
        "⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰ ⋰🄰⋰⋰🄿⋰⋰🄽⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄳⋰⋰🄸⋰⋰🄺⋰⋰🄷⋰⋰🄰⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄲⋰⋰🄷⋰⋰🅄⋰⋰🅃⋰ ⋰🄺⋰⋰🄾⋰ ⋰🄳⋰⋰🄰⋰⋰🄵⋰⋰🄰⋰⋰🄽⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰⋰🄾⋰ ⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🄼⋰⋰🄴⋰⋰🄴⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🅂⋰⋰🄰⋰⋰🅃⋰⋰🄷⋰ ⋰🅃⋰⋰🅄⋰ ⋰🄱⋰⋰🄷⋰⋰🄸⋰ ⋰🄳⋰⋰🄰⋰⋰🄵⋰⋰🄰⋰⋰🄽⋰ ⋰🄷⋰⋰🄾⋰ ⋰🄹⋰⋰🄰⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🄱⋰⋰🄷⋰⋰🄰⋰⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄰⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄷⋰⋰🄰⋰⋰🄸⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🅂⋰⋰🄴⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰",
        "⋰🄶⋰⋰🄰⋰⋰🄸⋰⋰🅁⋰⋰🄱⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄰⋰⋰🅄⋰⋰🄻⋰⋰🄰⋰⋰🄳⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄼⋰⋰🄰⋰⋰🅁⋰⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰",
        "⋰🄱⋰⋰🄰⋰⋰🄰⋰⋰🄰⋰⋰🄿⋰ ⋰🄺⋰⋰🄸⋰ ⋰🅂⋰⋰🄿⋰⋰🄴⋰⋰🄴⋰⋰🄳⋰ ⋰🄼⋰⋰🄰⋰⋰🅃⋰⋰🄲⋰⋰🄷⋰ ⋰🄺⋰⋰🅁⋰⋰🄴⋰⋰🄶⋰⋰🄰⋰ ⋰🄶⋰⋰🄰⋰⋰🅁⋰⋰🄸⋰⋰🄱⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄲⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰ ⋰🄺⋰⋰🄰⋰⋰🅃⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄵⋰⋰🄴⋰⋰🄺⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄴⋰⋰🄴⋰⋰🄹⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄴⋰ ⋰🄱⋰⋰🄷⋰⋰🄾⋰⋰🅂⋰⋰🄳⋰⋰🄰⋰⋰🄳⋰⋰🄴⋰ ⋰🄼⋰⋰🄴⋰⋰🄸⋰⋰🄽⋰ ⋰🄲⋰⋰🄿⋰ ⋰🄺⋰⋰🄰⋰⋰🅁⋰ ⋰🄳⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰ ⋰🄽⋰⋰🄸⋰⋰🄺⋰⋰🄰⋰⋰🄻⋰",
        "⋰🄰⋰⋰🄰⋰⋰🄹⋰ ⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🅁⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄽⋰⋰🄰⋰⋰🄷⋰⋰🄸⋰ ⋰🄱⋰⋰🄰⋰⋰🄲⋰⋰🄷⋰⋰🄴⋰⋰🄶⋰⋰🄸⋰ ⋰🅃⋰⋰🅄⋰ ⋰🄼⋰⋰🄴⋰⋰🅁⋰⋰🄴⋰ ⋰🄺⋰⋰🄾⋰ ⋰🅃⋰⋰🄰⋰⋰🄶⋰ ⋰🄺⋰⋰🄰⋰⋰🄸⋰⋰🅂⋰⋰🄴⋰ ⋰🄺⋰⋰🄸⋰⋰🅈⋰⋰🄰⋰",
        "⋰🅃⋰⋰🄴⋰⋰🅁⋰⋰🄸⋰ ⋰🄼⋰⋰🅄⋰⋰🄼⋰⋰🄼⋰⋰🅈⋰ ⋰🄺⋰⋰🄸⋰ ⋰🄶⋰⋰🄰⋰⋰🄽⋰⋰🄳⋰ ⋰🄼⋰⋰🄰⋰⋰🄰⋰⋰🅁⋰ ⋰🄻⋰⋰🅄⋰⋰🄽⋰⋰🄶⋰⋰🄰⋰"
        ]

        sqr_texts = [
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓐ ⊶Ⓑ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ, ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓒ⊶Ⓐ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ",
        "⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓟ ⊶Ⓑ⊶Ⓗ⊶Ⓘ ⊶Ⓑ⊶Ⓝ⊶Ⓐ⊶Ⓛ⊶Ⓔ ⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓔ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓐ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓟ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓩ ⊶Ⓔ⊶Ⓨ ⊶Ⓨ⊶Ⓐ⊶Ⓐ⊶Ⓓ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓤ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓐ ⊶Ⓝ⊶Ⓐ ⊶Ⓣ⊶Ⓨ⊶Ⓜ⊶Ⓟ⊶Ⓐ⊶Ⓢ⊶Ⓢ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ ⊶Ⓤ⊶Ⓝ⊶Ⓕ⊶Ⓤ⊶Ⓝ⊶Ⓝ⊶Ⓨ ⊶Ⓢ⊶Ⓦ⊶Ⓘ⊶Ⓟ⊶Ⓔ ⊶Ⓜ⊶Ⓣ⊶Ⓣ ⊶Ⓚ⊶Ⓡ",
        "⊶Ⓞ⊶Ⓗ ⊶Ⓗ⊶Ⓔ⊶Ⓛ⊶Ⓛ⊶Ⓞ ⊶Ⓑ⊶Ⓘ⊶Ⓗ⊶Ⓐ⊶Ⓡ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓐ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓟ ⊶Ⓑ⊶Ⓘ⊶Ⓗ⊶Ⓐ⊶Ⓡ⊶Ⓘ ⊶Ⓞ⊶Ⓡ ⊶Ⓣ⊶Ⓤ ⊶Ⓥ ⊶Ⓑ⊶Ⓘ⊶Ⓗ⊶Ⓐ⊶Ⓡ⊶Ⓘ ⊶Ⓐ⊶Ⓤ⊶Ⓚ⊶Ⓐ⊶Ⓣ ⊶Ⓜ⊶Ⓔ ⊶Ⓡ⊶Ⓗ⊶Ⓐ ⊶Ⓚ⊶Ⓡ.",
        "⊶Ⓞ⊶Ⓨ⊶Ⓨ ⊶Ⓚ⊶Ⓘ⊶Ⓝ⊶Ⓝ⊶Ⓔ⊶Ⓡ ⊶Ⓣ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ ⊶Ⓖ⊶Ⓒ ⊶Ⓜ⊶Ⓔ ⊶Ⓐ⊶Ⓐ⊶Ⓝ⊶Ⓔ ⊶Ⓚ⊶Ⓘ ⊶Ⓟ⊶Ⓔ⊶Ⓡ⊶Ⓜ⊶Ⓘ⊶Ⓢ⊶Ⓢ⊶Ⓘ⊶Ⓞ⊶Ⓝ ⊶Ⓚ⊶Ⓘ⊶Ⓢ⊶Ⓝ⊶Ⓔ ⊶Ⓓ⊶Ⓘ.",
        "⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓚ⊶Ⓔ ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓗ⊶Ⓐ",
        "⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓚ⊶Ⓔ ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓗ⊶Ⓐ ⊶Ⓔ⊶Ⓚ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓡ.",
        "⊶Ⓢ⊶Ⓤ⊶Ⓝ ⊶Ⓢ⊶Ⓤ⊶Ⓝ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓐ.",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓒ⊶Ⓐ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ.",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓣ⊶Ⓘ ⊶Ⓙ⊶Ⓐ⊶Ⓣ⊶Ⓘ ⊶Ⓚ⊶Ⓔ ⊶Ⓣ⊶Ⓜ⊶Ⓡ.",
        "⊶Ⓚ⊶Ⓨ? ⊶Ⓙ⊶Ⓛ⊶Ⓓ⊶Ⓘ ⊶Ⓛ⊶Ⓘ⊶Ⓚ⊶Ⓗ ⊶Ⓚ⊶Ⓘ⊶Ⓓ⊶Ⓓ⊶Ⓔ.",
        "⊶Ⓑ⊶Ⓘ⊶Ⓗ⊶Ⓐ⊶Ⓡ⊶Ⓘ ⊶Ⓒ⊶Ⓞ⊶Ⓜ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓖ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓟ ⊶Ⓚ⊶Ⓞ ⊶Ⓣ⊶Ⓐ⊶Ⓖ ⊶Ⓒ⊶Ⓡ⊶Ⓔ⊶Ⓖ⊶Ⓐ ⊶Ⓣ⊶Ⓤ",
        "⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓑ⊶Ⓘ⊶Ⓗ⊶Ⓐ⊶Ⓡ⊶Ⓘ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓜ⊶Ⓚ⊶Ⓒ ⊶Ⓑ⊶Ⓢ",
        "⊶Ⓙ⊶Ⓐ⊶Ⓛ⊶Ⓓ⊶Ⓘ ⊶Ⓢ⊶Ⓔ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓩ ⊶Ⓟ⊶Ⓐ⊶Ⓟ⊶Ⓐ ⊶Ⓑ⊶Ⓞ⊶Ⓛ",
        "⊶Ⓢ⊶Ⓘ⊶Ⓓ⊶Ⓔ ⊶Ⓗ⊶Ⓞ⊶Ⓙ⊶Ⓐ ⊶Ⓑ⊶Ⓘ⊶Ⓗ⊶Ⓐ⊶Ⓡ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓐ⊶Ⓑ",
        "⊶Ⓗ⊶Ⓨ⊶Ⓔ ⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓑ⊶Ⓗ⊶Ⓖ ⊶Ⓜ⊶Ⓐ⊶Ⓣ ⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓒ⊶Ⓤ⊶Ⓓ",
        "⊶Ⓑ⊶Ⓗ⊶Ⓖ ⊶Ⓝ⊶Ⓨ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ ⊶Ⓣ⊶Ⓤ ⊶Ⓐ⊶Ⓙ⊶Ⓙ",
        "⊶Ⓗ⊶Ⓨ⊶Ⓔ ⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓒ⊶Ⓗ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓐ⊶Ⓖ ⊶Ⓜ⊶Ⓐ⊶Ⓣ",
        "⊶Ⓗ⊶Ⓨ⊶Ⓔ ⊶Ⓓ⊶Ⓤ⊶Ⓡ ⊶Ⓗ⊶Ⓐ⊶Ⓣ⊶Ⓣ ⊶Ⓜ⊶Ⓐ⊶Ⓓ⊶Ⓗ⊶Ⓐ⊶Ⓡ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓔ",
        "⊶Ⓚ⊶Ⓞ⊶Ⓘ ⊶Ⓑ⊶Ⓐ⊶Ⓣ ⊶Ⓝ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ ⊶Ⓔ⊶Ⓢ⊶Ⓛ⊶Ⓘ⊶Ⓨ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓕ ⊶Ⓒ⊶Ⓡ ⊶Ⓡ⊶Ⓗ⊶Ⓐ ⊶Ⓗ⊶Ⓤ ⊶Ⓣ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ",
        "⊶Ⓚ⊶Ⓞ⊶Ⓘ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓣ ⊶Ⓝ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓣ⊶Ⓤ ⊶Ⓜ⊶Ⓐ⊶Ⓕ⊶Ⓘ ⊶Ⓓ⊶Ⓔ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓣ⊶Ⓤ ⊶Ⓜ⊶Ⓐ⊶Ⓕ⊶Ⓘ ⊶Ⓜ⊶Ⓘ⊶Ⓛ ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓖ⊶Ⓘ ⊶Ⓣ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ",
        "⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓣ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓐ ⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓔ ⊶Ⓢ⊶Ⓦ⊶Ⓘ⊶Ⓟ⊶Ⓔ ⊶Ⓒ⊶Ⓡ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓢ⊶Ⓦ⊶Ⓘ⊶Ⓟ⊶Ⓔ ⊶Ⓒ⊶Ⓡ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓕ⊶Ⓡ ⊶Ⓑ⊶Ⓞ⊶Ⓛ⊶Ⓝ⊶Ⓐ ⊶Ⓝ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓛ⊶Ⓔ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓢ⊶Ⓦ⊶Ⓘ⊶Ⓟ⊶Ⓔ ⊶Ⓒ⊶Ⓡ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓗ⊶Ⓤ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓟ⊶Ⓡ ⊶Ⓚ⊶Ⓔ⊶Ⓢ⊶Ⓔ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ",
        "⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓣ⊶Ⓗ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓔ⊶Ⓨ ⊶Ⓝ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓝ⊶Ⓣ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓨ",
        "⊶Ⓛ⊶Ⓞ⊶Ⓓ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓤ⊶Ⓣ⊶Ⓡ ⊶Ⓜ⊶Ⓒ",
        "⊶Ⓛ⊶Ⓤ⊶Ⓝ ⊶Ⓜ⊶Ⓣ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓢ ⊶Ⓜ⊶Ⓔ⊶Ⓡ⊶Ⓐ",
        "⊶Ⓝ⊶Ⓘ⊶Ⓚ⊶Ⓐ⊶Ⓛ ⊶Ⓜ⊶Ⓐ⊶Ⓓ⊶Ⓐ⊶Ⓡ⊶Ⓒ⊶Ⓗ⊶Ⓓ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓞ⊶Ⓨ⊶Ⓔ ⊶Ⓖ⊶Ⓐ⊶Ⓢ⊶Ⓗ⊶Ⓣ⊶Ⓘ ⊶Ⓚ ⊶Ⓑ⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓔ",
        "⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓘ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓚ ⊶Ⓗ⊶Ⓐ⊶Ⓣ⊶Ⓗ ⊶Ⓣ⊶Ⓞ⊶Ⓓ⊶Ⓗ ⊶Ⓚ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓟ ⊶Ⓚ ⊶Ⓜ⊶Ⓤ⊶Ⓗ ⊶Ⓜ⊶Ⓔ ⊶Ⓕ⊶Ⓐ⊶Ⓢ⊶Ⓐ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓛ⊶Ⓔ⊶Ⓐ⊶Ⓥ⊶Ⓔ ⊶Ⓛ⊶Ⓔ ⊶Ⓣ⊶Ⓤ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ ⊶Ⓟ⊶Ⓐ⊶Ⓢ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓝ⊶Ⓐ⊶Ⓘ ⊶Ⓐ⊶Ⓨ⊶Ⓐ ⊶Ⓜ⊶Ⓔ⊶Ⓚ⊶Ⓞ",
        "⊶Ⓛ⊶Ⓔ⊶Ⓐ⊶Ⓥ⊶Ⓔ ⊶Ⓛ⊶Ⓔ ⊶Ⓣ⊶Ⓤ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ ⊶Ⓘ⊶Ⓓ⊶Ⓔ⊶Ⓡ ⊶Ⓢ⊶Ⓔ",
        "⊶Ⓛ⊶Ⓔ⊶Ⓐ⊶Ⓥ⊶Ⓔ ⊶Ⓛ⊶Ⓔ ⊶Ⓙ⊶Ⓛ⊶Ⓓ⊶Ⓘ ⊶Ⓢ⊶Ⓔ ⊶Ⓦ⊶Ⓡ⊶Ⓝ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓛ⊶Ⓔ⊶Ⓐ⊶Ⓥ⊶Ⓔ ⊶Ⓝ⊶Ⓨ ⊶Ⓛ⊶Ⓔ⊶Ⓖ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓢ⊶Ⓜ⊶Ⓙ⊶Ⓗ ⊶Ⓑ⊶Ⓐ⊶Ⓣ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓛ⊶Ⓔ⊶Ⓐ⊶Ⓥ⊶Ⓔ ⊶Ⓛ⊶Ⓔ",
        "⊶Ⓕ⊶Ⓐ⊶Ⓢ⊶Ⓣ ⊶Ⓛ⊶Ⓔ⊶Ⓐ⊶Ⓥ⊶Ⓔ ⊶Ⓛ⊶Ⓔ ⊶Ⓚ⊶Ⓐ⊶Ⓜ⊶Ⓙ⊶Ⓞ⊶Ⓡ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓤ⊶Ⓣ⊶Ⓞ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ",
        "⊶Ⓞ⊶Ⓨ ⊶Ⓗ⊶Ⓘ⊶Ⓙ⊶Ⓓ⊶Ⓔ ⊶Ⓚ⊶Ⓗ⊶Ⓐ⊶Ⓝ⊶Ⓐ ⊶Ⓚ⊶Ⓗ⊶Ⓐ ⊶Ⓚ⊶Ⓔ ⊶Ⓐ⊶Ⓐ ⊶Ⓚ⊶Ⓐ⊶Ⓜ⊶Ⓩ⊶Ⓞ⊶Ⓡ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓞ ⊶Ⓘ⊶Ⓛ⊶Ⓨ ⊶Ⓡ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓣ⊶Ⓜ⊶Ⓚ⊶Ⓒ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓣ⊶Ⓤ",
        "⊶Ⓢ⊶Ⓗ⊶Ⓘ ⊶Ⓢ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓣ⊶Ⓤ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ",
        "⊶Ⓕ⊶Ⓡ ⊶Ⓢ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ",
        "⊶Ⓢ⊶Ⓗ⊶Ⓘ ⊶Ⓢ⊶Ⓔ ⊶Ⓛ⊶Ⓘ⊶Ⓚ⊶Ⓗ ⊶Ⓦ⊶Ⓡ⊶Ⓝ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓨ⊶Ⓤ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ⊶ⓒ⊶ⓤ⊶ⓓ⊶ⓦ⊶ⓐ",
        "⊶Ⓟ⊶Ⓡ⊶Ⓞ⊶Ⓞ⊶Ⓕ ⊶Ⓒ⊶Ⓡ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓟ⊶Ⓡ⊶Ⓞ⊶Ⓞ⊶Ⓕ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓟ⊶Ⓡ⊶Ⓞ⊶Ⓞ⊶Ⓕ ⊶Ⓗ⊶Ⓞ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓚ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓒ⊶Ⓗ⊶Ⓘ⊶Ⓛ⊶Ⓛ⊶Ⓐ⊶Ⓡ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓚ ⊶Ⓑ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓞ⊶Ⓨ ⊶Ⓗ⊶Ⓘ⊶Ⓙ⊶Ⓓ⊶Ⓔ ⊶Ⓚ⊶Ⓗ⊶Ⓐ⊶Ⓝ⊶Ⓐ ⊶Ⓚ⊶Ⓗ⊶Ⓐ ⊶Ⓚ⊶Ⓔ ⊶Ⓐ⊶Ⓐ ⊶Ⓚ⊶Ⓐ⊶Ⓜ⊶Ⓩ⊶Ⓞ⊶Ⓡ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶ⓜ⊶ⓐ⊶ⓓ⊶ⓡ⊶ⓒ⊶ⓗ⊶ⓞ⊶ⓓ?",
        "⊶Ⓐ⊶Ⓑ ⊶Ⓣ⊶Ⓚ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ ⊶Ⓗ⊶Ⓞ⊶Ⓖ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ?",
        "⊶Ⓝ⊶Ⓨ ⊶Ⓝ⊶Ⓨ ⊶Ⓜ⊶Ⓔ ⊶Ⓚ⊶Ⓤ⊶Ⓒ⊶Ⓗ ⊶Ⓝ⊶Ⓨ ⊶Ⓙ⊶Ⓐ⊶Ⓝ⊶Ⓣ⊶Ⓐ ⊶Ⓑ⊶Ⓢ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓢ⊶Ⓑ⊶Ⓢ⊶Ⓔ ⊶Ⓟ⊶Ⓗ⊶Ⓔ⊶Ⓛ⊶Ⓔ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓚ⊶Ⓞ ⊶Ⓑ⊶Ⓞ⊶Ⓛ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓝ⊶Ⓐ ⊶Ⓚ⊶Ⓐ⊶Ⓜ ⊶Ⓚ⊶Ⓡ⊶Ⓔ",
        "⊶Ⓨ⊶Ⓐ⊶Ⓗ⊶Ⓐ ⊶Ⓑ⊶Ⓗ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓒ⊶Ⓔ ⊶Ⓟ⊶Ⓘ⊶Ⓛ⊶Ⓛ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓐ⊶Ⓑ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓣ⊶Ⓞ ⊶Ⓑ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓔ⊶Ⓖ⊶Ⓘ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ ⊶Ⓣ⊶Ⓞ⊶Ⓜ⊶Ⓜ⊶Ⓨ",
        "⊶Ⓝ⊶Ⓘ⊶Ⓚ⊶Ⓐ⊶Ⓛ ⊶Ⓜ⊶Ⓐ⊶Ⓓ⊶Ⓐ⊶Ⓡ⊶Ⓒ⊶Ⓗ⊶Ⓓ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓚ⊶Ⓔ ⊶Ⓨ⊶Ⓗ⊶Ⓐ ⊶Ⓢ⊶Ⓔ",
        "⊶Ⓒ⊶Ⓞ⊶Ⓩ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓗ⊶Ⓘ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓘ ⊶Ⓗ⊶Ⓔ",
        "⊶Ⓝ⊶Ⓨ⊶Ⓣ⊶Ⓞ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓟ ⊶Ⓑ⊶Ⓞ⊶Ⓛ ⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ",
        "⊶Ⓝ⊶Ⓨ⊶Ⓝ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓗ⊶Ⓞ⊶Ⓖ⊶Ⓘ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶⊶Ⓘ ⊶Ⓙ⊶Ⓞ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ⊶Ⓣ⊶Ⓘ ⊶Ⓙ⊶Ⓞ⊶Ⓖ⊶Ⓘ",
        "⊶Ⓣ⊶Ⓡ⊶Ⓨ ⊶Ⓐ⊶Ⓜ⊶Ⓜ⊶Ⓘ ⊶Ⓒ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓔ⊶Ⓜ⊶Ⓞ⊶Ⓙ⊶Ⓘ ⊶Ⓓ⊶Ⓐ⊶Ⓛ ⊶Ⓜ⊶Ⓒ",
        "⊶Ⓒ⊶Ⓨ⊶Ⓐ ? ⊶Ⓒ⊶Ⓗ⊶Ⓜ⊶Ⓡ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓐ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ?",
        "⊶Ⓣ⊶Ⓜ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓡ⊶Ⓘ ⊶Ⓗ⊶Ⓞ⊶Ⓖ⊶Ⓘ ⊶Ⓕ⊶Ⓡ⊶Ⓡ⊶Ⓣ⊶Ⓞ",
        "⊶Ⓒ⊶Ⓨ⊶Ⓐ ? ⊶Ⓚ⊶Ⓑ ? ⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓔ⊶Ⓨ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓚ⊶Ⓔ⊶Ⓚ",
        "⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓢ⊶Ⓒ⊶Ⓗ ⊶Ⓜ⊶Ⓔ⊶Ⓨ ⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓔ⊶Ⓨ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓛ⊶Ⓘ ⊶Ⓣ⊶Ⓤ⊶Ⓝ⊶Ⓔ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ",
        "⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓐ ⊶Ⓢ⊶Ⓒ⊶Ⓗ ⊶Ⓝ⊶Ⓨ ⊶Ⓑ⊶Ⓞ⊶Ⓛ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓢ⊶Ⓒ⊶Ⓗ ⊶Ⓜ⊶Ⓔ⊶Ⓨ ⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓤ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓛ⊶Ⓘ⊶Ⓐ ⊶Ⓜ⊶Ⓔ⊶Ⓡ⊶Ⓔ ⊶Ⓢ⊶Ⓣ⊶Ⓗ",
        "⊶Ⓜ⊶Ⓣ⊶Ⓛ⊶Ⓑ ⊶Ⓣ⊶Ⓜ⊶Ⓡ",
        "⊶Ⓝ⊶Ⓨ⊶Ⓣ⊶Ⓞ",
        "⊶Ⓟ⊶Ⓤ⊶Ⓡ⊶Ⓐ ⊶Ⓛ⊶Ⓘ⊶Ⓚ⊶Ⓗ ⊶Ⓜ⊶Ⓒ",
        "⊶Ⓣ⊶Ⓜ⊶Ⓡ ⊶Ⓕ⊶Ⓡ⊶Ⓡ⊶Ⓣ⊶Ⓞ",
        "⊶Ⓞ⊶Ⓗ ⊶Ⓞ⊶Ⓚ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓛ⊶Ⓔ ⊶Ⓕ⊶Ⓘ⊶Ⓡ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓚ⊶Ⓐ ⊶Ⓓ⊶Ⓐ⊶Ⓜ⊶Ⓐ⊶Ⓓ",
        "⊶Ⓒ⊶Ⓨ⊶Ⓐ ? ⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓛ⊶Ⓘ⊶Ⓚ⊶Ⓗ⊶Ⓔ ⊶Ⓟ⊶Ⓔ⊶Ⓗ⊶Ⓛ⊶Ⓔ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓔ⊶Ⓑ⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓔ",
        "⊶Ⓝ⊶Ⓨ⊶Ⓣ⊶Ⓞ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ⊶Ⓝ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓥ⊶Ⓨ⊶Ⓐ⊶Ⓢ⊶Ⓣ ⊶Ⓗ⊶Ⓤ",
        "⊶Ⓝ⊶Ⓨ⊶Ⓣ⊶Ⓞ ⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓔ⊶Ⓨ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓚ⊶Ⓤ⊶Ⓒ⊶Ⓗ ⊶Ⓑ⊶Ⓘ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ? ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓐ ?",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓜ⊶Ⓣ ⊶Ⓗ⊶Ⓢ⊶Ⓢ",
        "⊶Ⓨ⊶Ⓤ⊶Ⓡ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶⊶Ⓘ ⊶Ⓜ⊶Ⓞ⊶Ⓜ",
        "⊶Ⓐ⊶Ⓡ⊶Ⓔ ⊶Ⓢ⊶Ⓑ⊶Ⓚ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶⊶Ⓘ ⊶Ⓞ⊶Ⓡ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓘ",
        "⊶Ⓐ⊶Ⓡ⊶Ⓔ ⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓛ⊶Ⓔ ⊶Ⓔ⊶Ⓚ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓡ",
        "⊶Ⓣ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓘ ⊶Ⓣ⊶Ⓡ⊶Ⓗ",
        "⊶Ⓔ⊶Ⓚ ⊶Ⓛ⊶Ⓘ⊶Ⓝ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓣ⊶Ⓜ⊶Ⓡ",
        "⊶Ⓠ",
        "⊶Ⓞ⊶Ⓒ⊶Ⓨ ⊶Ⓐ⊶Ⓑ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓛ⊶Ⓔ",
        "⊶Ⓟ⊶Ⓔ⊶Ⓗ⊶Ⓔ⊶Ⓛ⊶Ⓔ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ⊶Ⓤ",
        "⊶Ⓝ⊶Ⓨ⊶Ⓣ⊶Ⓞ",
        "⊶Ⓠ ?",
        "⊶Ⓗ⊶Ⓨ⊶Ⓨ⊶Ⓨ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓚ⊶Ⓔ ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓐ ⊶Ⓔ⊶Ⓚ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓡ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓢ⊶Ⓤ⊶Ⓝ ⊶Ⓓ⊶Ⓞ⊶Ⓢ⊶Ⓣ ⊶Ⓣ⊶Ⓜ⊶Ⓡ",
        "⊶Ⓑ⊶Ⓗ⊶Ⓐ⊶Ⓖ ⊶Ⓙ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓕ ⊶Ⓒ⊶Ⓡ⊶Ⓡ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶⊶Ⓘ ⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓐ⊶Ⓐ",
        "⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓣ⊶Ⓜ⊶Ⓡ ⊶Ⓕ⊶Ⓡ⊶Ⓡ⊶Ⓣ⊶Ⓞ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓛ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓜ⊶Ⓡ",
        "⊶Ⓝ⊶Ⓨ⊶Ⓣ⊶Ⓞ ⊶Ⓐ⊶Ⓔ⊶Ⓢ⊶Ⓔ ⊶Ⓗ⊶Ⓘ ⊶Ⓒ⊶Ⓤ⊶Ⓓ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓗ⊶Ⓨ⊶Ⓨ ⊶Ⓐ⊶Ⓘ⊶Ⓢ⊶Ⓔ ⊶Ⓗ⊶Ⓘ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓛ⊶Ⓔ⊶Ⓝ⊶Ⓐ",
        "⊶Ⓞ⊶Ⓡ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓛ⊶Ⓔ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓚ⊶Ⓔ ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓐ ⊶Ⓞ⊶Ⓡ",
        "⊶Ⓗ⊶Ⓨ⊶Ⓨ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓞ ⊶Ⓝ⊶Ⓐ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓞ ⊶Ⓜ⊶Ⓣ ⊶Ⓑ⊶Ⓗ⊶Ⓐ⊶Ⓖ ⊶Ⓙ⊶Ⓐ⊶Ⓞ",
        "⊶Ⓑ⊶Ⓨ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓗ⊶Ⓨ⊶Ⓨ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ?",
        "⊶Ⓠ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓠ ⊶Ⓡ⊶Ⓗ⊶Ⓔ ⊶Ⓗ⊶Ⓞ ?",
        "⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓔ⊶Ⓨ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓜ⊶Ⓒ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓜ⊶Ⓣ",
        "⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶⊶Ⓘ ⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓐ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓐ⊶Ⓜ⊶Ⓜ⊶Ⓘ ⊶Ⓒ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ⊶Ⓟ⊶Ⓐ⊶Ⓛ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓐ⊶Ⓐ ⊶Ⓜ⊶Ⓒ",
        "⊶Ⓚ⊶Ⓜ⊶Ⓩ⊶Ⓡ⊶Ⓞ⊶Ⓡ ⊶Ⓔ⊶Ⓨ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶Ⓔ⊶Ⓚ",
        "⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓛ⊶Ⓘ⊶Ⓚ⊶Ⓗ ⊶Ⓡ⊶Ⓗ⊶Ⓐ ?",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓣ⊶Ⓗ⊶Ⓐ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ?",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓢ⊶Ⓛ⊶Ⓘ⊶Ⓓ⊶Ⓔ ⊶Ⓛ⊶Ⓔ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶ⒶⓉ ⊶Ⓒ⊶Ⓡ⊶Ⓜ⊶Ⓒ",
        "⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ⊶Ⓤ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓒ⊶Ⓟ ⊶Ⓜ⊶Ⓣ ⊶Ⓒ⊶Ⓡ⊶Ⓡ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓛ⊶Ⓔ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓗ⊶Ⓨ⊶Ⓨ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓚ⊶Ⓔ ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓐ",
        "⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓐ⊶Ⓐ ⊶Ⓣ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓢ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓕ⊶Ⓤ ⊶Ⓚ⊶Ⓗ⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓡ ⊶Ⓚ⊶Ⓗ⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓡ",
        "⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓐ⊶Ⓐ ⊶Ⓙ⊶Ⓐ ⊶Ⓜ⊶Ⓒ",
        "⊶Ⓗ⊶Ⓨ⊶Ⓨ ⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓛ⊶Ⓔ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓚ⊶Ⓜ⊶Ⓩ⊶Ⓞ⊶Ⓡ ⊶Ⓜ⊶Ⓒ ⊶Ⓘ⊶Ⓓ⊶Ⓐ⊶Ⓡ ⊶Ⓐ⊶Ⓐ",
        "⊶Ⓨ⊶Ⓔ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓣ⊶Ⓜ⊶Ⓡ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓝ⊶Ⓨ ⊶Ⓒ⊶Ⓟ ⊶Ⓝ⊶Ⓨ ⊶Ⓒ⊶Ⓡ⊶Ⓡ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ⊶Ⓔ ⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓜ⊶Ⓣ ⊶Ⓒ⊶Ⓡ⊶Ⓡ",
        "⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓛ⊶Ⓔ ⊶Ⓐ⊶Ⓡ⊶ⒶⓂ ⊶Ⓢ⊶Ⓔ ⊶Ⓜ⊶Ⓒ",
        "⊶Ⓟ⊶Ⓖ⊶Ⓛ ⊶Ⓔ⊶Ⓨ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶Ⓔ⊶Ⓚ",
        "⊶Ⓒ⊶Ⓟ ⊶Ⓒ⊶Ⓡ⊶Ⓒ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓔ⊶Ⓖ⊶Ⓐ !",
        "⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓟ ? ⊶Ⓜ⊶Ⓒ ⊶Ⓜ⊶Ⓔ⊶Ⓡ⊶Ⓐ ⊶Ⓒ⊶Ⓞ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓑ⊶Ⓐ⊶Ⓐ⊶Ⓟ ⊶Ⓝ⊶Ⓨ ⊶Ⓔ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓘ ⊶Ⓤ⊶Ⓟ⊶Ⓐ⊶Ⓡ ⊶Ⓢ⊶Ⓔ ⊶Ⓡ⊶Ⓞ⊶Ⓒ⊶Ⓚ⊶Ⓔ⊶Ⓣ ⊶Ⓟ⊶Ⓔ ⊶Ⓑ⊶Ⓔ⊶Ⓣ⊶Ⓗ ⊶Ⓒ⊶Ⓔ ⊶ⒷⓈⓈ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ⊶Ⓝ⊶Ⓔ ⊶Ⓐ⊶Ⓨ⊶Ⓐ ⊶Ⓗ⊶Ⓤ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓣ⊶Ⓐ ⊶Ⓛ⊶Ⓘ⊶Ⓚ⊶Ⓗ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ ⊶Ⓚ ⊶Ⓑ⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓔ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓣ⊶Ⓐ ⊶Ⓛ⊶Ⓘ⊶Ⓚ⊶Ⓗ⊶Ⓐ ⊶Ⓦ⊶Ⓡ⊶Ⓝ⊶Ⓐ ⊶ⓉⓇ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓨ",
        "⊶Ⓣ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓑ⊶Ⓐ⊶Ⓚ⊶Ⓐ ⊶Ⓒ⊶Ⓞ⊶Ⓓ⊶Ⓔ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓜ⊶Ⓚ⊶Ⓒ ⊶Ⓜ⊶Ⓐ⊶Ⓘ⊶Ⓝ ⊶Ⓑ⊶Ⓤ⊶Ⓡ⊶Ⓕ",
        "⊶Ⓑ⊶Ⓗ⊶Ⓘ⊶Ⓚ⊶Ⓐ⊶Ⓡ⊶Ⓘ ⊶Ⓚ⊶Ⓘ ⊶Ⓙ⊶Ⓗ⊶Ⓐ⊶Ⓣ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓐ ⊶Ⓛ⊶Ⓔ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ⊶Ⓚ⊶Ⓔ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓖ⊶Ⓘ",
        "⊶Ⓣ⊶Ⓜ⊶Ⓚ⊶Ⓒ ⊶Ⓜ⊶Ⓐ⊶Ⓘ⊶Ⓝ ⊶Ⓜ⊶Ⓞ⊶Ⓤ⊶Ⓝ⊶Ⓣ ⊶Ⓔ⊶Ⓥ⊶Ⓔ⊶Ⓡ⊶Ⓔ⊶Ⓢ⊶Ⓣ",
        "⊶Ⓜ⊶Ⓤ⊶Ⓗ ⊶Ⓜ⊶Ⓔ⊶Ⓨ ⊶Ⓛ⊶Ⓔ⊶Ⓖ⊶Ⓐ ⊶Ⓛ⊶Ⓤ⊶Ⓝ⊶Ⓓ ⊶Ⓜ⊶Ⓔ⊶Ⓡ⊶Ⓐ",
        "⊶Ⓗ⊶Ⓘ⊶Ⓙ⊶Ⓓ⊶Ⓔ ⊶Ⓚ⊶Ⓘ ⊶Ⓙ⊶Ⓗ⊶Ⓐ⊶Ⓣ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓦ⊶Ⓡ⊶Ⓝ⊶Ⓐ ⊶ⓉⓇ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ",
        "⊶Ⓜ⊶Ⓔ⊶Ⓝ⊶Ⓤ ⊶Ⓝ⊶Ⓨ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓔ⊶Ⓝ⊶Ⓤ ⊶Ⓚ⊶Ⓘ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓔ⊶Ⓝ⊶Ⓤ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓔ⊶Ⓝ⊶Ⓤ ⊶Ⓢ⊶Ⓑ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓔ⊶Ⓝ⊶Ⓤ ⊶Ⓟ⊶Ⓡ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ",
        "⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓔ⊶Ⓝ⊶Ⓤ ⊶Ⓟ⊶Ⓣ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓝ⊶Ⓤ ⊶Ⓞ⊶Ⓡ ⊶Ⓜ⊶Ⓔ⊶Ⓝ⊶Ⓤ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓔ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓑ⊶Ⓢ ⊶Ⓑ⊶Ⓢ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ",
        "⊶Ⓑ⊶Ⓢ ⊶Ⓑ⊶Ⓢ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓣ⊶Ⓗ⊶Ⓝ⊶Ⓚ⊶Ⓢ⊶Ⓢ",
        "⊶Ⓑ⊶Ⓢ ⊶Ⓑ⊶Ⓢ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓛ⊶Ⓘ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ",
        "⊶Ⓑ⊶Ⓢ ⊶Ⓑ⊶Ⓢ ⊶Ⓚ⊶Ⓐ⊶Ⓜ⊶Ⓙ⊶Ⓞ⊶Ⓡ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓢ⊶Ⓜ⊶Ⓙ⊶Ⓗ ⊶Ⓖ⊶Ⓨ⊶Ⓐ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓛ⊶Ⓔ ⊶Ⓐ⊶Ⓑ",
        "⊶Ⓢ⊶Ⓜ⊶Ⓙ⊶Ⓗ ⊶Ⓖ⊶Ⓨ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓢ⊶Ⓜ⊶Ⓙ⊶Ⓗ ⊶Ⓖ⊶Ⓨ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓢ⊶Ⓐ⊶Ⓑ⊶Ⓘ⊶Ⓣ ⊶Ⓚ⊶Ⓡ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓗ⊶Ⓤ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ",
        "⊶Ⓔ⊶Ⓐ⊶Ⓢ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓛ⊶Ⓔ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓣ⊶Ⓤ",
        "⊶Ⓔ⊶Ⓐ⊶Ⓢ⊶Ⓨ ⊶Ⓦ⊶8 ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓛ⊶Ⓔ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓐ⊶Ⓑ",
        "⊶Ⓢ⊶Ⓐ⊶Ⓝ⊶Ⓢ ⊶Ⓐ⊶Ⓡ⊶Ⓘ ⊶Ⓗ⊶Ⓐ ⊶Ⓚ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓖ⊶Ⓘ ⊶Ⓐ⊶Ⓙ⊶Ⓙ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓚ⊶Ⓞ ⊶Ⓑ⊶Ⓘ⊶Ⓝ⊶Ⓐ ⊶Ⓢ⊶Ⓐ⊶Ⓝ⊶Ⓢ⊶Ⓢ ⊶Ⓛ⊶Ⓔ⊶Ⓣ⊶Ⓔ ⊶Ⓗ⊶Ⓤ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓟ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓔ ⊶Ⓚ⊶Ⓐ⊶Ⓜ⊶Ⓙ⊶Ⓞ⊶Ⓡ",
        "⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓝ⊶Ⓞ⊶Ⓡ⊶Ⓜ⊶Ⓘ⊶Ⓔ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓛ⊶Ⓔ ⊶Ⓣ⊶Ⓤ",
        "⊶Ⓕ⊶Ⓡ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓝ⊶Ⓞ⊶Ⓡ⊶Ⓜ⊶Ⓘ⊶Ⓔ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓑ⊶Ⓐ⊶Ⓢ ⊶Ⓣ⊶Ⓗ⊶Ⓔ⊶Ⓚ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ",
        "⊶Ⓑ⊶Ⓐ⊶Ⓢ ⊶Ⓣ⊶Ⓗ⊶Ⓔ⊶Ⓚ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ",
        "⊶Ⓚ⊶Ⓐ⊶Ⓜ⊶Ⓙ⊶Ⓞ⊶Ⓡ ⊶Ⓣ⊶Ⓗ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓔ⊶Ⓢ⊶Ⓛ⊶Ⓘ⊶Ⓨ⊶Ⓔ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ",
        "⊶Ⓜ⊶Ⓐ⊶Ⓘ ⊶Ⓢ⊶Ⓑ ⊶Ⓙ⊶Ⓐ⊶Ⓝ⊶Ⓣ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓛ ⊶Ⓒ⊶Ⓗ⊶Ⓛ ⊶Ⓗ⊶Ⓣ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ",
        "⊶Ⓕ⊶Ⓡ ⊶Ⓚ⊶Ⓐ⊶Ⓘ⊶Ⓢ⊶Ⓔ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓑ⊶Ⓐ⊶Ⓢ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓕ⊶Ⓡ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓚ⊶Ⓐ⊶Ⓜ⊶Ⓙ⊶Ⓞ⊶Ⓡ ⊶Ⓜ⊶Ⓐ ⊶Ⓚ⊶Ⓐ ⊶Ⓑ⊶Ⓒ⊶Ⓗ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓣ ⊶Ⓖ⊶Ⓝ⊶Ⓓ⊶Ⓘ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓟ⊶Ⓡ ⊶Ⓚ⊶Ⓐ⊶Ⓘ⊶Ⓢ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓐ ⊶Ⓖ⊶Ⓝ⊶Ⓓ⊶Ⓐ",
        "⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓑ⊶Ⓣ⊶Ⓐ ⊶Ⓡ⊶Ⓗ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓕ⊶Ⓘ⊶Ⓡ ⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ ⊶Ⓝ⊶Ⓨ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓝ⊶Ⓨ ⊶Ⓚ⊶Ⓞ⊶Ⓝ ⊶Ⓒ⊶Ⓞ⊶Ⓓ ⊶Ⓓ⊶Ⓘ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓚ⊶Ⓞ",
        "⊶Ⓡ⊶Ⓤ⊶Ⓚ ⊶Ⓐ⊶Ⓐ⊶Ⓨ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓞ⊶Ⓓ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓦ⊶Ⓐ⊶Ⓘ⊶Ⓣ ⊶Ⓒ⊶Ⓡ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓞ⊶Ⓓ ⊶Ⓡ⊶Ⓗ⊶Ⓐ ⊶Ⓗ⊶Ⓤ",
        "⊶Ⓦ⊶Ⓐ⊶Ⓘ⊶Ⓣ ⊶Ⓒ⊶Ⓡ ⊶Ⓡ⊶Ⓐ⊶Ⓑ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓡ⊶Ⓗ⊶Ⓘ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓦ⊶Ⓐ⊶Ⓘ⊶Ⓣ ⊶Ⓚ⊶Ⓡ ⊶Ⓢ⊶Ⓜ⊶Ⓙ⊶Ⓗ ⊶Ⓡ⊶Ⓗ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓞ⊶Ⓓ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓦ⊶Ⓐ⊶Ⓘ⊶Ⓣ ⊶Ⓛ⊶Ⓔ ⊶Ⓣ⊶Ⓗ⊶Ⓞ⊶Ⓓ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ⊶Ⓝ⊶Ⓔ ⊶Ⓓ⊶Ⓔ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓞ",
        "⊶Ⓡ⊶Ⓤ⊶Ⓚ ⊶Ⓙ⊶Ⓐ ⊶Ⓐ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓡ⊶Ⓚ⊶Ⓗ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓛ⊶Ⓘ⊶Ⓨ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓕ⊶Ⓐ⊶Ⓜ⊶Ⓞ⊶Ⓤ⊶Ⓢ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓐ⊶ⒶⓃ ⊶Ⓛ⊶Ⓘ⊶Ⓐ ⊶Ⓜ⊶Ⓔ⊶Ⓝ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓢ⊶Ⓐ⊶Ⓛ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓐ⊶ⒶⓃ ⊶Ⓛ⊶Ⓘ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓢ⊶Ⓗ⊶Ⓐ⊶Ⓝ⊶Ⓣ ⊶Ⓑ⊶Ⓔ⊶Ⓣ⊶Ⓗ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ",
        "⊶Ⓢ⊶Ⓗ⊶Ⓐ⊶Ⓝ⊶Ⓣ ⊶Ⓑ⊶Ⓔ⊶Ⓣ⊶Ⓗ⊶Ⓚ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓛ⊶Ⓔ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓞ ⊶Ⓣ⊶Ⓤ",
        "⊶Ⓕ⊶Ⓡ ⊶Ⓢ⊶Ⓔ ⊶Ⓢ⊶Ⓗ⊶Ⓐ⊶Ⓝ⊶Ⓣ ⊶Ⓑ⊶Ⓔ⊶Ⓣ⊶Ⓗ ⊶Ⓣ⊶Ⓤ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓐ⊶Ⓑ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ ⊶Ⓨ⊶Ⓗ⊶Ⓐ",
        "⊶Ⓜ⊶Ⓔ⊶Ⓡ⊶Ⓔ ⊶Ⓢ⊶Ⓜ⊶Ⓙ⊶Ⓗ ⊶Ⓝ⊶Ⓨ ⊶Ⓐ⊶Ⓨ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓛ⊶Ⓔ ⊶ⓛ⊶ⓤ⊶ⓝ⊶ⓓ ⊶Ⓚ⊶Ⓗ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓜ⊶Ⓐ⊶Ⓓ⊶Ⓐ⊶Ⓡ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ",
        "⊶Ⓗ⊶Ⓨ⊶Ⓔ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓨ⊶Ⓘ ⊶Ⓒ⊶Ⓨ⊶Ⓐ",
        "⊶Ⓗ⊶Ⓨ⊶Ⓔ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓡ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓒ⊶Ⓨ⊶Ⓐ",
        "⊶Ⓗ⊶Ⓨ⊶Ⓔ ⊶Ⓢ⊶Ⓒ⊶Ⓗ ⊶Ⓑ⊶Ⓣ⊶Ⓐ ⊶Ⓒ⊶Ⓞ⊶Ⓜ ⊶Ⓒ⊶Ⓞ⊶Ⓓ ⊶Ⓓ⊶Ⓘ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓞ",
        "⊶Ⓒ⊶Ⓗ⊶Ⓛ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓓ⊶Ⓘ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓚ⊶Ⓞ ⊶Ⓢ⊶Ⓜ⊶Ⓙ⊶Ⓗ⊶Ⓛ⊶Ⓔ",
        "⊶Ⓑ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓚ⊶Ⓞ⊶Ⓘ ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓚ⊶Ⓐ⊶Ⓣ ⊶Ⓝ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓑ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓢ⊶Ⓑ ⊶Ⓙ⊶Ⓐ⊶Ⓝ⊶Ⓣ⊶Ⓔ ⊶Ⓔ⊶Ⓨ ⊶Ⓚ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓓ⊶Ⓚ⊶Ⓐ⊶Ⓓ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓣ⊶Ⓗ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓝ⊶Ⓔ ⊶Ⓦ⊶Ⓛ⊶Ⓘ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓟ⊶Ⓡ ⊶Ⓜ⊶Ⓔ⊶Ⓘ ⊶Ⓚ⊶Ⓐ⊶Ⓘ⊶Ⓢ⊶Ⓔ ⊶Ⓙ⊶Ⓝ⊶Ⓣ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓚ⊶Ⓞ ⊶Ⓚ⊶Ⓞ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓓ⊶Ⓘ⊶Ⓐ",
        "⊶Ⓟ⊶Ⓡ ⊶Ⓜ⊶Ⓔ⊶Ⓡ⊶Ⓐ ⊶Ⓥ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓝ⊶Ⓝ⊶Ⓐ ⊶Ⓢ⊶Ⓗ⊶Ⓘ ⊶Ⓣ⊶Ⓗ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓟ⊶Ⓡ ⊶Ⓦ⊶Ⓞ ⊶Ⓖ⊶Ⓛ⊶Ⓣ ⊶Ⓝ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓟ⊶Ⓡ ⊶Ⓦ⊶Ⓞ ⊶Ⓢ⊶Ⓗ⊶Ⓘ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓓ⊶Ⓚ⊶Ⓐ⊶Ⓓ ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓟ⊶Ⓡ ⊶Ⓚ⊶Ⓐ⊶Ⓘ⊶Ⓢ⊶Ⓔ ⊶Ⓚ⊶Ⓘ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓞ⊶Ⓜ⊶Ⓕ⊶Ⓞ⊶Ⓞ",
        "⊶Ⓑ⊶Ⓤ⊶Ⓡ ⊶Ⓒ⊶Ⓗ⊶Ⓔ⊶Ⓔ⊶Ⓡ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓣ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓚ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓚ⊶Ⓔ ⊶Ⓓ⊶Ⓘ⊶Ⓛ ⊶Ⓜ⊶Ⓔ ⊶Ⓛ⊶Ⓞ⊶Ⓓ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓚ⊶Ⓔ ⊶Ⓤ⊶Ⓢ⊶Ⓚ⊶Ⓘ ⊶Ⓓ⊶Ⓗ⊶Ⓐ⊶Ⓓ⊶Ⓚ⊶Ⓐ⊶Ⓝ ⊶Ⓡ⊶Ⓞ⊶Ⓚ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓛ⊶Ⓤ⊶Ⓛ⊶Ⓛ⊶Ⓔ ⊶Ⓚ⊶Ⓗ⊶Ⓐ ⊶Ⓣ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓐ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓗ⊶Ⓝ ⊶Ⓚ⊶Ⓘ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓘ ⊶Ⓑ⊶Ⓔ⊶Ⓣ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ ⊶Ⓡ⊶Ⓝ⊶Ⓓ⊶Ⓘ ⊶Ⓑ⊶Ⓐ⊶ⒶⓉ ⊶Ⓚ⊶Ⓗ⊶ⓉⓂ",
        "⊶Ⓢ⊶Ⓤ⊶Ⓝ ⊶Ⓔ⊶Ⓚ ⊶Ⓜ⊶Ⓐ⊶Ⓩ⊶Ⓔ ⊶Ⓚ⊶Ⓘ ⊶Ⓑ⊶Ⓐ⊶ⒶⓉ ⊶Ⓑ⊶Ⓐ⊶Ⓣ⊶Ⓐ⊶Ⓞ ⊶Ⓚ⊶Ⓨ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶रैं⊶डी ⊶Ⓗ⊶Ⓐ⊶Ⓘ",
        "⊶Ⓒ⊶Ⓞ⊶Ⓓ⊶Ⓤ ⊶Ⓒ⊶Ⓞ⊶Ⓓ⊶Ⓤ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓞ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ",
        "⊶Ⓐ⊶Ⓙ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓞ⊶Ⓨ⊶Ⓔ",
        "⊶Ⓢ⊶Ⓤ⊶Ⓝ ⊶Ⓢ⊶Ⓤ⊶Ⓝ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓒ⊶Ⓗ⊶Ⓔ ⊶Ⓣ⊶Ⓤ",
        "⊶Ⓚ⊶Ⓘ⊶Ⓛ⊶Ⓐ⊶Ⓢ ⊶Ⓝ⊶Ⓨ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓨ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓜ⊶Ⓤ⊶Ⓙ⊶Ⓗ⊶Ⓔ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓟ⊶Ⓣ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓑ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ",
        "⊶Ⓟ⊶Ⓡ ⊶Ⓟ⊶Ⓡ ⊶Ⓒ⊶Ⓨ⊶Ⓐ ⊶Ⓗ⊶Ⓞ⊶Ⓣ⊶Ⓔ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓜ⊶Ⓚ⊶Ⓒ",
        "⊶Ⓣ⊶Ⓜ⊶Ⓒ⊶Ⓛ ⊶Ⓢ⊶Ⓤ⊶Ⓝ⊶Ⓛ⊶Ⓔ",
        "⊶Ⓜ⊶Ⓞ⊶Ⓞ⊶Ⓣ ⊶Ⓓ⊶Ⓤ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓜ⊶Ⓔ⊶Ⓨ",
        "⊶Ⓑ⊶Ⓗ⊶Ⓖ⊶Ⓝ⊶Ⓨ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓚ⊶Ⓔ ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓗ⊶Ⓐ ⊶Ⓕ⊶Ⓡ",
        "⊶Ⓕ⊶Ⓡ ⊶Ⓢ⊶Ⓔ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓛ⊶Ⓔ ⊶Ⓣ⊶Ⓤ",
        "⊶Ⓨ⊶Ⓔ ⊶Ⓥ⊶Ⓘ ⊶Ⓢ⊶Ⓗ⊶Ⓘ ⊶Ⓔ⊶Ⓨ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓚ⊶Ⓒ ⊶Ⓑ⊶Ⓢ",
        "⊶Ⓐ⊶Ⓙ ⊶Ⓚ⊶Ⓤ⊶Ⓒ⊶Ⓗ ⊶Ⓝ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓣ⊶Ⓤ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ",
        "⊶Ⓣ⊶Ⓡ⊶Ⓨ ⊶Ⓚ⊶Ⓡ ⊶Ⓜ⊶Ⓔ⊶Ⓡ⊶Ⓐ ⊶Ⓛ⊶Ⓤ⊶Ⓝ⊶Ⓓ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓢ⊶Ⓚ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓞ⊶Ⓡ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓘ⊶Ⓑ⊶Ⓤ⊶Ⓡ ⊶Ⓢ⊶Ⓤ⊶Ⓝ",
        "⊶Ⓣ⊶Ⓞ⊶Ⓡ ⊶Ⓜ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓕ⊶Ⓤ⊶Ⓓ⊶Ⓓ⊶Ⓘ ⊶Ⓞ⊶Ⓨ⊶Ⓔ",
        "⊶Ⓗ⊶Ⓐ⊶Ⓨ⊶Ⓔ ⊶Ⓗ⊶Ⓐ⊶Ⓨ⊶Ⓔ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓨ ⊶Ⓜ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓖ⊶Ⓐ⊶Ⓘ",
        "⊶Ⓞ⊶Ⓨ⊶Ⓔ ⊶Ⓛ⊶Ⓤ⊶Ⓝ⊶Ⓓ⊶Ⓚ⊶Ⓔ ⊶Ⓟ⊶Ⓐ⊶Ⓢ⊶Ⓘ⊶Ⓝ⊶Ⓔ..",
        "⊶Ⓚ⊶Ⓤ⊶Ⓣ⊶Ⓣ⊶Ⓔ ⊶Ⓚ⊶Ⓔ ⊶Ⓣ⊶Ⓐ⊶Ⓣ⊶Ⓣ⊶Ⓔ ⊶Ⓢ⊶Ⓤ⊶Ⓝ",
        "⊶Ⓚ⊶Ⓤ⊶Ⓣ⊶Ⓣ⊶Ⓐ ⊶Ⓙ⊶Ⓐ⊶Ⓘ⊶Ⓢ⊶Ⓐ ⊶Ⓒ⊶Ⓤ⊶Ⓓ ⊶Ⓡ⊶Ⓗ⊶Ⓐ ⊶Ⓣ⊶Ⓤ",
        "⊶Ⓜ⊶Ⓤ⊶Ⓗ ⊶Ⓜ⊶Ⓔ⊶Ⓘ ⊶Ⓛ⊶Ⓔ ⊶Ⓜ⊶Ⓔ⊶Ⓡ⊶Ⓐ..",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ⊶Ⓘ⊶Ⓨ⊶Ⓐ ⊶Ⓚ⊶Ⓐ⊶Ⓣ ⊶Ⓚ⊶Ⓔ ⊶Ⓕ⊶Ⓔ⊶Ⓝ⊶Ⓚ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓝ⊶Ⓞ⊶Ⓝ ⊶Ⓢ⊶Ⓣ⊶Ⓞ⊶Ⓟ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓕ⊶Ⓐ⊶ⒶⓉ ⊶Ⓖ⊶Ⓐ⊶Ⓨ⊶Ⓘ ⊶Ⓐ⊶Ⓙ⊶Ⓣ⊶Ⓞ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓗ⊶Ⓐ⊶Ⓝ ⊶Ⓚ⊶Ⓐ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ ⊶Ⓜ⊶Ⓔ ⊶Ⓚ⊶Ⓤ⊶Ⓣ⊶Ⓣ⊶Ⓐ ⊶Ⓚ⊶Ⓐ ⊶Ⓛ⊶Ⓤ⊶Ⓝ⊶Ⓓ ⊶Ⓒ⊶Ⓗ⊶Ⓘ⊶Ⓟ⊶Ⓚ⊶Ⓐ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓝ⊶Ⓞ⊶Ⓝ ⊶Ⓢ⊶Ⓣ⊶Ⓞ⊶Ⓟ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓖ⊶Ⓞ⊶Ⓛ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶ⒶⓇ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓤ⊶Ⓢ⊶Ⓢ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶100 ⊶Ⓒ⊶Ⓗ⊶Ⓔ⊶Ⓓ⊶Ⓓ ⊶Ⓚ⊶Ⓐ⊶Ⓡ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓓ⊶Ⓘ⊶Ⓓ⊶Ⓘ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ⊶Ⓟ⊶Ⓐ⊶Ⓛ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓓ⊶Ⓘ⊶Ⓓ⊶Ⓘ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓦ⊶Ⓐ⊶Ⓢ⊶Ⓘ⊶Ⓡ ⊶Ⓗ⊶Ⓞ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓜ⊶Ⓔ⊶Ⓡ⊶Ⓔ ⊶Ⓛ⊶Ⓐ⊶Ⓥ⊶Ⓓ⊶Ⓔ ⊶Ⓟ⊶Ⓐ⊶Ⓡ ⊶Ⓤ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓛ ⊶Ⓤ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓛ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓣ⊶Ⓘ ⊶Ⓗ⊶Ⓐ⊶Ⓘ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓔ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓚ⊶Ⓘ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓜ⊶Ⓔ ⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ⊶Ⓟ⊶Ⓐ⊶Ⓛ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓔ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓚ⊶Ⓘ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓣ⊶Ⓐ⊶Ⓜ⊶Ⓐ⊶Ⓣ⊶Ⓐ⊶Ⓡ ⊶Ⓚ⊶Ⓔ ⊶Ⓣ⊶Ⓐ⊶Ⓡ⊶Ⓐ⊶Ⓗ ⊶Ⓛ⊶Ⓐ⊶ⒶⓁ ⊶Ⓗ⊶Ⓞ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓓ⊶Ⓘ⊶Ⓓ⊶Ⓘ ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓕ⊶Ⓐ⊶ⒶⓅ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓑ⊶Ⓘ⊶Ⓒ⊶Ⓗ ⊶Ⓑ⊶Ⓐ⊶Ⓙ⊶Ⓐ⊶Ⓡ ⊶Ⓜ⊶Ⓔ ⊶Ⓝ⊶Ⓘ⊶Ⓛ⊶Ⓐ⊶Ⓜ ⊶Ⓚ⊶Ⓐ⊶Ⓡ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓑ⊶Ⓔ⊶Ⓣ⊶Ⓘ⊶Ⓨ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓚ⊶Ⓐ⊶Ⓕ⊶Ⓕ⊶Ⓐ⊶Ⓝ ⊶Ⓜ⊶Ⓔ ⊶Ⓓ⊶Ⓐ⊶Ⓕ⊶Ⓐ⊶Ⓝ ⊶Ⓚ⊶Ⓐ⊶Ⓡ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓙ⊶Ⓐ⊶Ⓓ⊶Ⓐ ⊶Ⓝ⊶Ⓐ ⊶Ⓤ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓛ ⊶Ⓦ⊶Ⓐ⊶Ⓡ⊶Ⓝ⊶Ⓐ⊶Ⓐ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓓ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓔ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓔ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓢ⊶Ⓐ⊶Ⓢ⊶Ⓣ⊶Ⓐ ⊶Ⓚ⊶Ⓔ⊶Ⓨ⊶Ⓑ⊶Ⓞ⊶Ⓐ⊶Ⓡ⊶Ⓓ ⊶Ⓛ⊶Ⓐ⊶Ⓖ⊶Ⓐ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓐ⊶Ⓖ⊶Ⓐ⊶Ⓡ ⊶Ⓣ⊶Ⓤ ⊶Ⓒ⊶Ⓟ ⊶Ⓑ⊶Ⓞ⊶Ⓛ⊶Ⓔ⊶Ⓖ⊶Ⓐ ⊶Ⓣ⊶Ⓞ ⊶Ⓜ⊶Ⓔ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓖ⊶Ⓐ⊶Ⓡ⊶Ⓐ⊶Ⓜ ⊶Ⓜ⊶Ⓤ⊶Ⓣ⊶Ⓣ⊶Ⓗ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓤ⊶Ⓡ ⊶Ⓜ⊶Ⓔ ⊶Ⓗ⊶Ⓐ⊶Ⓣ⊶Ⓗ⊶Ⓞ⊶Ⓡ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓚ⊶Ⓘ⊶Ⓛ⊶Ⓛ⊶Ⓘ ⊶Ⓣ⊶Ⓗ⊶Ⓞ⊶Ⓚ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓔ ⊶Ⓣ⊶Ⓔ⊶Ⓙ⊶Ⓙ⊶Ⓘ ⊶Ⓢ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ⊶Ⓟ⊶Ⓐ⊶Ⓛ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ ⊶Ⓕ⊶Ⓐ⊶ⒶⓉ ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓐ⊶Ⓜ⊶Ⓜ⊶Ⓐ ⊶Ⓙ⊶Ⓐ⊶ⒶⓃ ⊶Ⓚ⊶Ⓔ ⊶Ⓒ⊶Ⓐ⊶Ⓝ⊶Ⓒ⊶Ⓔ⊶Ⓡ ⊶Ⓦ⊶Ⓐ⊶Ⓛ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓜ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ⊶Ⓟ⊶Ⓐ⊶Ⓛ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓝ⊶Ⓞ⊶Ⓝ ⊶Ⓢ⊶Ⓣ⊶Ⓞ⊶Ⓟ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓐ⊶Ⓜ⊶Ⓜ⊶Ⓐ ⊶Ⓙ⊶Ⓐ⊶ⒶⓃ ⊶Ⓚ⊶Ⓔ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓜ⊶Ⓔ ⊶Ⓖ⊶Ⓛ⊶Ⓘ⊶Ⓣ⊶Ⓒ⊶Ⓗ ⊶Ⓣ⊶Ⓨ⊶Ⓟ⊶Ⓘ⊶Ⓝ⊶Ⓖ ⊶Ⓚ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓥ⊶Ⓐ⊶Ⓢ⊶Ⓘ⊶Ⓨ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓗ⊶Ⓐ⊶Ⓘ ⊶Ⓢ⊶Ⓐ⊶Ⓑ⊶Ⓚ⊶Ⓐ ⊶Ⓜ⊶Ⓤ⊶Ⓗ ⊶Ⓜ⊶Ⓔ⊶Ⓗ ⊶Ⓛ⊶Ⓤ⊶Ⓝ⊶Ⓓ ⊶Ⓛ⊶Ⓔ⊶Ⓚ⊶Ⓡ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓐ ⊶Ⓚ⊶Ⓗ⊶Ⓐ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓐ⊶Ⓝ ⊶Ⓚ⊶Ⓞ ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓛ⊶Ⓐ⊶Ⓣ⊶Ⓘ ⊶Ⓗ⊶Ⓐ⊶Ⓘ",
        "⊶Ⓣ⊶Ⓤ ⊶Ⓞ⊶Ⓡ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓐ ⊶Ⓚ⊶Ⓗ⊶Ⓐ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓐ⊶Ⓝ ⊶Ⓚ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓑ⊶Ⓘ⊶Ⓒ⊶Ⓗ ⊶Ⓑ⊶Ⓐ⊶Ⓙ⊶Ⓐ⊶Ⓡ ⊶Ⓜ⊶Ⓔ ⊶Ⓜ⊶Ⓞ⊶Ⓙ⊶Ⓡ⊶Ⓐ ⊶Ⓚ⊶Ⓐ⊶Ⓡ⊶Ⓦ⊶Ⓐ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓔ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓚ⊶Ⓔ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓜ⊶Ⓔ ⊶Ⓖ⊶Ⓞ⊶Ⓛ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶ⒶⓇ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓓ⊶Ⓤ⊶Ⓢ⊶Ⓡ⊶Ⓐ ⊶Ⓑ⊶Ⓛ⊶Ⓐ⊶Ⓒ⊶Ⓚ ⊶Ⓗ⊶Ⓞ⊶Ⓛ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓝ⊶Ⓐ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓜ⊶Ⓜ⊶Ⓐ ⊶Ⓛ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓔ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓚ⊶Ⓐ⊶Ⓕ⊶Ⓕ⊶Ⓐ⊶Ⓝ ⊶Ⓜ⊶Ⓔ ⊶Ⓓ⊶Ⓐ⊶Ⓕ⊶Ⓐ⊶Ⓝ ⊶Ⓚ⊶Ⓐ⊶Ⓡ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓑ⊶Ⓔ⊶Ⓣ⊶Ⓘ⊶ⓨ⊶Ⓞ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓖ⊶Ⓞ⊶Ⓓ⊶Ⓩ⊶Ⓘ⊶Ⓛ⊶Ⓛ⊶Ⓐ ⊶Ⓚ⊶Ⓐ ⊶Ⓛ⊶Ⓤ⊶Ⓝ⊶Ⓓ ⊶Ⓓ⊶Ⓐ⊶Ⓛ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓖ⊶Ⓞ⊶Ⓓ⊶Ⓩ⊶Ⓘ⊶Ⓛ⊶Ⓛ⊶Ⓐ ⊶Ⓚ⊶Ⓐ ⊶Ⓛ⊶Ⓤ⊶Ⓝ⊶Ⓓ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓕ⊶Ⓐ⊶ⒶⓇ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓢ⊶Ⓔ ⊶Ⓝ⊶Ⓘ⊶Ⓚ⊶Ⓐ⊶Ⓛ ⊶Ⓓ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓨ⊶Ⓐ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓕ⊶Ⓛ⊶Ⓨ ⊶Ⓚ⊶Ⓘ⊶Ⓢ⊶Ⓢ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓟ⊶Ⓐ⊶Ⓐ⊶Ⓝ⊶Ⓘ ⊶Ⓝ⊶Ⓘ⊶Ⓚ⊶Ⓐ⊶Ⓛ ⊶Ⓓ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓘ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓤ⊶Ⓜ⊶Ⓜ⊶Ⓨ ⊶Ⓚ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓒ⊶Ⓗ⊶Ⓘ⊶ⓨ⊶Ⓞ ⊶Ⓚ⊶Ⓞ ⊶Ⓚ⊶Ⓐ⊶Ⓣ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓟ⊶Ⓐ⊶Ⓚ⊶Ⓚ⊶Ⓐ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓔ ⊶Ⓙ⊶Ⓤ⊶Ⓣ⊶Ⓣ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓚ⊶Ⓗ⊶Ⓤ⊶Ⓝ⊶Ⓝ ⊶Ⓝ⊶Ⓘ⊶Ⓚ⊶Ⓐ⊶Ⓛ ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓤ⊶Ⓢ⊶Ⓢ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓟ⊶Ⓐ⊶Ⓐ⊶Ⓝ⊶Ⓘ ⊶Ⓝ⊶Ⓘ⊶Ⓚ⊶Ⓐ⊶Ⓛ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓓ⊶Ⓞ⊶Ⓝ⊶Ⓐ⊶Ⓣ⊶Ⓔ ⊶Ⓚ⊶Ⓐ⊶Ⓡ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓟ⊶Ⓟ⊶Ⓐ⊶Ⓛ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓢ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓒ⊶Ⓒ⊶Ⓗ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓗ⊶Ⓐ⊶Ⓡ ⊶Ⓝ⊶Ⓘ⊶Ⓚ⊶Ⓐ⊶Ⓛ ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓓ⊶Ⓘ⊶Ⓓ⊶Ⓘ ⊶Ⓚ⊶Ⓔ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓜ⊶Ⓔ ⊶Ⓨ⊶Ⓞ⊶Ⓖ⊶Ⓘ ⊶Ⓙ⊶Ⓘ ⊶Ⓚ⊶Ⓐ ⊶Ⓑ⊶Ⓤ⊶Ⓛ⊶Ⓛ⊶Ⓓ⊶Ⓞ⊶Ⓩ⊶Ⓔ⊶Ⓡ ⊶Ⓒ⊶Ⓗ⊶Ⓐ⊶Ⓛ⊶Ⓐ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓓ⊶Ⓘ⊶Ⓓ⊶Ⓘ ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓕ⊶Ⓛ⊶Ⓐ⊶Ⓣ ⊶Ⓗ⊶Ⓞ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓘ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓑ⊶Ⓔ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓔ ⊶Ⓙ⊶Ⓤ⊶Ⓣ⊶Ⓣ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓑ⊶Ⓔ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓚ⊶Ⓐ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ ⊶Ⓕ⊶Ⓐ⊶ⒶⓉ ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓓ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓐ⊶Ⓚ⊶49 ⊶Ⓢ⊶Ⓔ ⊶Ⓖ⊶Ⓞ⊶Ⓛ⊶Ⓘ⊶Ⓨ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓔ ⊶Ⓖ⊶Ⓞ⊶Ⓛ⊶Ⓘ⊶Ⓨ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶9 ⊶Ⓤ⊶Ⓝ⊶Ⓘ⊶Ⓥ⊶Ⓔ⊶Ⓡ⊶Ⓢ ⊶Ⓐ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓐ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓐ ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓗ⊶Ⓐ ⊶Ⓓ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓜ⊶Ⓔ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓘ⊶ⓨ⊶Ⓞ ⊶Ⓚ⊶Ⓐ ⊶Ⓚ⊶Ⓞ⊶Ⓣ⊶Ⓗ⊶Ⓐ ⊶Ⓑ⊶Ⓐ⊶Ⓝ⊶Ⓐ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓑ⊶Ⓔ⊶Ⓗ⊶Ⓔ⊶Ⓝ ⊶Ⓚ⊶Ⓞ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ⊶Ⓝ⊶Ⓔ ⊶Ⓚ⊶Ⓞ ⊶Ⓑ⊶Ⓐ⊶Ⓘ⊶Ⓣ⊶Ⓗ⊶Ⓐ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓚ⊶Ⓞ⊶Ⓣ⊶Ⓗ⊶Ⓔ ⊶Ⓟ⊶Ⓐ⊶Ⓡ⊶Ⓡ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓚ⊶Ⓞ ⊶Ⓑ⊶Ⓐ⊶Ⓒ⊶Ⓒ⊶Ⓗ⊶Ⓐ ⊶Ⓡ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓘ ⊶Ⓑ⊶Ⓐ⊶Ⓗ⊶Ⓐ⊶Ⓝ⊶Ⓔ ⊶Ⓑ⊶Ⓐ⊶Ⓙ⊶Ⓘ⊶Ⓨ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓔ⊶Ⓖ⊶Ⓐ ⊶Ⓣ⊶Ⓞ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓐ⊶Ⓝ⊶Ⓒ⊶Ⓔ⊶Ⓡ ⊶Ⓦ⊶Ⓐ⊶Ⓛ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓜ⊶Ⓔ ⊶Ⓚ⊶Ⓞ ⊶Ⓣ⊶Ⓘ⊶Ⓚ⊶Ⓣ⊶Ⓞ⊶Ⓚ ⊶Ⓚ⊶Ⓔ ⊶Ⓣ⊶Ⓐ⊶Ⓡ⊶Ⓐ⊶Ⓗ ⊶Ⓑ⊶Ⓐ⊶Ⓝ ⊶Ⓚ⊶Ⓐ⊶Ⓡ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓘ⊶Ⓢ⊶Ⓢ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓘ⊶Ⓨ⊶Ⓐ ⊶Ⓢ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓚ⊶Ⓐ ⊶Ⓟ⊶Ⓞ⊶Ⓦ⊶Ⓔ⊶Ⓡ ⊶Ⓓ⊶Ⓘ⊶Ⓚ⊶Ⓗ⊶Ⓐ",
        "⊶Ⓐ⊶Ⓘ⊶Ⓢ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓐ⊶Ⓖ⊶Ⓔ⊶Ⓖ⊶Ⓐ ⊶Ⓣ⊶Ⓞ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓣ⊶Ⓞ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓘ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓣ ⊶Ⓜ⊶Ⓔ ⊶Ⓜ⊶Ⓤ⊶Ⓣ⊶Ⓣ⊶Ⓗ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶ⒶⓇ ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓟ⊶Ⓞ⊶Ⓛ⊶Ⓘ⊶Ⓒ⊶Ⓔ ⊶Ⓚ⊶Ⓐ ⊶Ⓓ⊶Ⓐ⊶Ⓝ⊶Ⓓ⊶Ⓐ ⊶Ⓜ⊶Ⓐ⊶Ⓡ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ ⊶Ⓤ⊶Ⓢ⊶Ⓢ⊶Ⓔ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓚ⊶Ⓐ ⊶Ⓦ⊶Ⓞ⊶Ⓡ⊶Ⓚ⊶Ⓞ⊶Ⓤ⊶Ⓣ ⊶Ⓗ⊶Ⓞ⊶Ⓙ⊶Ⓐ⊶Ⓨ⊶Ⓔ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓐ⊶Ⓜ⊶Ⓜ⊶Ⓐ ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ ⊶Ⓘ⊶Ⓣ⊶Ⓝ⊶Ⓐ ⊶Ⓔ⊶Ⓝ⊶Ⓔ⊶Ⓡ⊶Ⓖ⊶Ⓨ ⊶Ⓗ⊶Ⓐ⊶Ⓘ ⊶Ⓚ⊶Ⓘ ⊶Ⓔ⊶Ⓚ ⊶Ⓑ⊶Ⓐ⊶ⒶⓇ ⊶Ⓜ⊶Ⓔ ⊶10 ⊶Ⓛ⊶Ⓞ⊶Ⓖ⊶Ⓞ ⊶Ⓚ⊶Ⓐ ⊶Ⓛ⊶Ⓤ⊶Ⓝ⊶Ⓓ⊶Ⓐ ⊶Ⓛ⊶Ⓔ⊶Ⓛ⊶Ⓔ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓜ⊶Ⓔ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓐ⊶Ⓜ⊶Ⓜ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓑ⊶Ⓐ⊶Ⓒ⊶Ⓒ⊶Ⓗ⊶Ⓐ ⊶Ⓐ⊶Ⓘ⊶Ⓢ⊶Ⓔ ⊶Ⓐ⊶Ⓟ⊶Ⓝ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓨ⊶Ⓐ ⊶Ⓒ⊶Ⓗ⊶Ⓤ⊶Ⓓ⊶Ⓦ⊶Ⓐ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓑ⊶Ⓗ⊶Ⓐ⊶Ⓖ⊶Ⓔ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓜ⊶Ⓐ⊶Ⓐ⊶Ⓚ⊶Ⓔ ⊶Ⓑ⊶Ⓗ⊶Ⓞ⊶Ⓢ⊶Ⓓ⊶Ⓔ ⊶Ⓚ⊶Ⓞ ⊶Ⓤ⊶Ⓛ⊶Ⓣ⊶Ⓐ ⊶Ⓛ⊶Ⓐ⊶Ⓣ⊶Ⓚ⊶Ⓐ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓒ⊶Ⓗ⊶Ⓞ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ",
        "⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓐ⊶Ⓜ⊶Ⓜ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓜ⊶Ⓔ ⊶Ⓗ⊶Ⓞ⊶Ⓛ⊶Ⓛ⊶Ⓞ⊶Ⓦ ⊶Ⓟ⊶Ⓤ⊶Ⓡ⊶Ⓟ⊶Ⓛ⊶Ⓔ ⊶Ⓜ⊶Ⓐ⊶ⒶⓇ ⊶Ⓚ⊶Ⓐ⊶Ⓡ ⊶Ⓣ⊶Ⓔ⊶Ⓡ⊶Ⓘ ⊶Ⓐ⊶Ⓜ⊶Ⓜ⊶Ⓐ ⊶Ⓚ⊶Ⓘ ⊶Ⓖ⊶Ⓐ⊶Ⓝ⊶Ⓓ ⊶Ⓜ⊶Ⓔ ⊶Ⓒ⊶Ⓗ⊶Ⓔ⊶Ⓓ⊶Ⓓ ⊶Ⓚ⊶Ⓐ⊶Ⓡ⊶Ⓓ⊶Ⓤ⊶Ⓝ⊶Ⓖ⊶Ⓐ"
        ]
        sqs2_texts = [
        "⋰Ⓑ⋰⋰⒪⋰⋰⒧⋰ ⋰⒯⋰⋰⒪⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰Ⓓ⋰⋰⒤⋰⋰Ⓓ⋰⋰⒤⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒠⋰ ⋰⒨⋰⋰⒰⋰⋰⒣⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒭⋰⋰⒜⋰⋰⒢⋰⋰⒜⋰⋰⒟⋰ ⋰⒟⋰⋰⒰⋰",
        "⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒧⋰⋰⒪⋰⋰⒟⋰⋰⒜⋰⋰⒜⋰ ⋰⒟⋰⋰⒜⋰⋰⒜⋰⋰⒧⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒨⋰⋰⒜⋰⋰⒮⋰⋰⒜⋰⋰⒧⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰",
        "⋰⒡⋰⋰⒜⋰⋰⒨⋰⋰⒠⋰ ⋰⒧⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒫⋰⋰⒠⋰ ⋰⒯⋰⋰⒣⋰⋰⒜⋰⋰⒫⋰⋰⒫⋰⋰⒜⋰⋰⒟⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰⋰⒰⋰",
        "⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒧⋰⋰⒪⋰⋰⒟⋰⋰⒜⋰⋰⒜⋰ ⋰⒟⋰⋰⒜⋰⋰⒜⋰⋰⒧⋰⋰⒰⋰",
        "⋰⒳⋰⋰⒣⋰⋰⒜⋰⋰⒧⋰ ⋰⒰⋰⋰⒯⋰⋰⒣⋰ ⋰⒨⋰⋰⒜⋰⋰⒟⋰⋰⒣⋰⋰⒠⋰⋰⒭⋰⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰",
        "⋰⒨⋰⋰⒜⋰⋰⒭⋰⋰⒩⋰⋰⒜⋰ ⋰⒩⋰⋰⒜⋰⋰⒣⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒧⋰⋰⒜⋰⋰⒟⋰⋰⒦⋰⋰⒠⋰",
        "⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒝⋰⋰⒰⋰⋰⒟⋰⋰⒣⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒧⋰⋰⒜⋰⋰⒟⋰⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒤⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒟⋰⋰⒣⋰⋰⒠⋰⋰⒭⋰⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰ ⋰⒞⋰⋰⒣⋰⋰⒜⋰⋰⒧⋰ ⋰⒰⋰⋰⒯⋰⋰⒣⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒜⋰⋰⒦⋰⋰⒠⋰⋰⒧⋰⋰⒜⋰ ⋰⒫⋰⋰⒜⋰⋰⒩⋰ ⋰⒨⋰⋰⒤⋰⋰⒯⋰⋰⒜⋰⋰⒜⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰ ⋰⒝⋰⋰⒤⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒤⋰ ⋰⒳⋰⋰⒣⋰⋰⒜⋰⋰⒧⋰ ⋰⒥⋰⋰⒤⋰⋰⒩⋰⋰⒟⋰⋰⒜⋰⋰⒜⋰ ⋰⒣⋰⋰⒪⋰ ⋰⒥⋰⋰⒜⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰⋰⒩⋰ ⋰⒦⋰⋰⒤⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰⋰⒯⋰⋰⒯⋰ ⋰⒫⋰⋰⒠⋰⋰⒠⋰⋰⒠⋰ ⋰⒞⋰⋰⒣⋰⋰⒜⋰⋰⒫⋰⋰⒫⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰⋰⒧⋰⋰⒧⋰⋰⒧⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒩⋰⋰⒜⋰⋰⒩⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒦⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰ ⋰⒝⋰⋰⒪⋰⋰⒪⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒠⋰⋰⒠⋰⋰⒭⋰⋰⒭⋰ ⋰⒡⋰⋰⒜⋰⋰⒜⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰⋰⒯⋰⋰⒯⋰ ⋰⒮⋰⋰⒠⋰⋰⒠⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒭⋰⋰⒭⋰ ⋰⒩⋰⋰⒤⋰⋰⒦⋰⋰⒜⋰⋰⒧⋰⋰⒧⋰⋰⒧⋰⋰⒧⋰ ⋰⒜⋰⋰⒜⋰⋰⒥⋰⋰⒥⋰⋰⒥⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒝⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒡⋰⋰⒜⋰⋰⒜⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰⋰⒭⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰ ⋰⒭⋰⋰⒠⋰⋰⒫⋰⋰⒧⋰⋰⒴⋰⋰⒴⋰⋰⒴⋰ ⋰⒦⋰⋰⒭⋰⋰⒭⋰⋰⒭⋰⋰⒭⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰⋰⒩⋰ ⋰⒦⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰ ⋰⒝⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰⋰⒜⋰ ⋰⒩⋰⋰⒤⋰⋰⒧⋰⋰⒜⋰⋰⒜⋰⋰⒨⋰⋰⒨⋰⋰⒨⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰⋰⒭⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰⋰⒠⋰⋰⒠⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰⋰⒠⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰⋰⒩⋰⋰⒩⋰ ⋰⒦⋰⋰⒪⋰⋰⒪⋰⋰⒪⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒦⋰⋰⒠⋰⋰⒠⋰⋰⒠⋰ ⋰⒤⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒜⋰⋰⒜⋰ ⋰⒮⋰⋰⒠⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒭⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰⋰⒢⋰⋰⒢⋰⋰⒢⋰ ⋰⒥⋰⋰⒜⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰ ⋰⒭⋰⋰⒠⋰⋰⒫⋰⋰⒧⋰⋰⒴⋰⋰⒴⋰⋰⒴⋰ ⋰⒟⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒦⋰⋰⒜⋰⋰⒜⋰⋰⒧⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒦⋰⋰⒜⋰⋰⒜⋰⋰⒧⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰⋰⒯⋰⋰⒯⋰ ⋰⒨⋰⋰⒠⋰⋰⒠⋰⋰⒠⋰ ⋰⒧⋰⋰⒰⋰⋰⒩⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰ ⋰⒜⋰⋰⒜⋰⋰⒥⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰⋰⒩⋰⋰⒩⋰ ⋰⒦⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰⋰⒯⋰ ⋰⒨⋰⋰⒠⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰⋰⒩⋰ ⋰⒣⋰⋰⒜⋰⋰⒯⋰⋰⒣⋰⋰⒣⋰⋰⒣⋰ ⋰⒟⋰⋰⒜⋰⋰⒜⋰⋰⒧⋰⋰⒧⋰⋰⒧⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰ ⋰⒜⋰⋰⒜⋰⋰⒥⋰⋰⒥⋰⋰⒥⋰⋰⒥⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰⋰⒩⋰⋰⒩⋰",
        "⋰⒮⋰⋰⒫⋰⋰⒠⋰⋰⒠⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰ ⋰⒫⋰⋰⒜⋰⋰⒦⋰⋰⒜⋰⋰⒜⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰⋰⒠⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰⋰⒠⋰⋰⒠⋰",
        "⋰⒮⋰⋰⒫⋰⋰⒠⋰⋰⒠⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰ ⋰⒧⋰⋰⒠⋰⋰⒦⋰⋰⒦⋰⋰⒜⋰⋰⒭⋰⋰⒭⋰⋰⒭⋰ ⋰⒜⋰⋰⒜⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰⋰⒟⋰⋰⒜⋰⋰⒭⋰⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒟⋰⋰⒟⋰ ⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒮⋰⋰⒠⋰⋰⒠⋰⋰⒠⋰",
        "⋰⒭⋰⋰⒠⋰⋰⒫⋰⋰⒧⋰⋰⒴⋰⋰⒴⋰⋰⒴⋰ ⋰⒦⋰⋰⒜⋰⋰⒤⋰⋰⒮⋰⋰⒠⋰ ⋰⒦⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰ ⋰⒩⋰⋰⒜⋰⋰⒩⋰⋰⒤⋰ ⋰⒦⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰⋰⒯⋰ ⋰⒦⋰⋰⒜⋰⋰⒜⋰ ⋰⒝⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰⋰⒜⋰ ⋰⒝⋰⋰⒜⋰⋰⒩⋰⋰⒜⋰⋰⒜⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰⋰⒜⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰⋰⒴⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒦⋰⋰⒜⋰⋰⒯⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒜⋰⋰⒰⋰⋰⒧⋰⋰⒜⋰⋰⒟⋰ ⋰⒣⋰⋰⒜⋰⋰⒤⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒦⋰⋰⒜⋰⋰⒯⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒜⋰⋰⒰⋰⋰⒧⋰⋰⒜⋰⋰⒟⋰ ⋰⒣⋰⋰⒜⋰⋰⒤⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒨⋰⋰⒜⋰⋰⒟⋰⋰⒜⋰⋰⒭⋰⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒟⋰ ⋰⒦⋰⋰⒤⋰⋰⒟⋰⋰⒟⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒮⋰⋰⒜⋰⋰⒯⋰⋰⒣⋰ ⋰⒮⋰⋰⒪⋰ ⋰⒥⋰⋰⒜⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰ ⋰⒱⋰⋰⒪⋰⋰⒤⋰⋰⒞⋰⋰⒠⋰ ⋰⒣⋰⋰⒪⋰ ⋰⒥⋰⋰⒜⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒤⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒩⋰⋰⒤⋰⋰⒦⋰⋰⒜⋰⋰⒧⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒩⋰⋰⒜⋰⋰⒣⋰⋰⒤⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰ ⋰⒮⋰⋰⒜⋰⋰⒦⋰⋰⒯⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰ ⋰⒧⋰⋰⒜⋰⋰⒰⋰⋰⒟⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰⋰⒭⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒫⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒤⋰⋰⒢⋰⋰⒩⋰⋰⒪⋰⋰⒭⋰⋰⒠⋰ ⋰⒦⋰⋰⒜⋰⋰⒤⋰⋰⒮⋰⋰⒠⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒝⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰ ⋰⒜⋰⋰⒜⋰⋰⒥⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒦⋰⋰⒜⋰⋰⒯⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰ ⋰⒥⋰⋰⒜⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒰⋰ ⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒤⋰⋰⒢⋰⋰⒩⋰⋰⒪⋰⋰⒭⋰⋰⒠⋰ ⋰⒦⋰⋰⒜⋰⋰⒤⋰⋰⒮⋰⋰⒠⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰ ⋰⒭⋰⋰⒜⋰ ⋰⒣⋰⋰⒜⋰⋰⒤⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒡⋰⋰⒜⋰⋰⒯⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰ ⋰⒨⋰⋰⒠⋰⋰⒭⋰⋰⒜⋰ ⋰⒧⋰⋰⒪⋰⋰⒟⋰⋰⒜⋰⋰⒜⋰ ⋰⒟⋰⋰⒜⋰⋰⒧⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒜⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒪⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰ ⋰⒜⋰⋰⒜⋰⋰⒫⋰ ⋰⒞⋰⋰⒫⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒦⋰⋰⒜⋰⋰⒧⋰⋰⒤⋰ ⋰⒥⋰⋰⒰⋰⋰⒝⋰⋰⒜⋰⋰⒩⋰ ⋰⒦⋰⋰⒜⋰⋰⒯⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒡⋰⋰⒠⋰⋰⒩⋰⋰⒦⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒩⋰⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰ ⋰⒥⋰⋰⒜⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒨⋰⋰⒜⋰⋰⒤⋰ ⋰⒦⋰⋰⒜⋰⋰⒝⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰⋰⒜⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒤⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒩⋰⋰⒤⋰⋰⒦⋰⋰⒜⋰⋰⒧⋰ ⋰⒦⋰⋰⒠⋰",
        "⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒥⋰⋰⒤⋰⋰⒩⋰⋰⒟⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒡⋰⋰⒜⋰⋰⒯⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒠⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰ ⋰⒥⋰⋰⒜⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰ ⋰⒜⋰⋰⒝⋰ ⋰⒯⋰⋰⒰⋰",
        "⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰ ⋰⒟⋰⋰⒜⋰⋰⒡⋰⋰⒜⋰⋰⒩⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰??⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒠⋰ ⋰⒧⋰⋰⒜⋰⋰⒰⋰⋰⒟⋰⋰⒠⋰ ⋰⒫⋰⋰⒠⋰⋰⒭⋰ ⋰⒢⋰⋰??⋰⋰⒰⋰⋰⒨⋰⋰⒜⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒦⋰⋰⒣⋰⋰⒜⋰⋰⒟⋰⋰⒠⋰ ⋰⒦⋰⋰⒣⋰⋰⒜⋰⋰⒟⋰⋰⒠⋰ ⋰⒧⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰ ⋰⒧⋰⋰⒠⋰⋰⒦⋰⋰⒤⋰⋰⒩⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒥⋰⋰⒣⋰⋰⒰⋰⋰⒦⋰⋰⒩⋰⋰⒠⋰ ⋰⒩⋰⋰⒜⋰⋰⒤⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰ ⋰⒝⋰⋰⒜⋰⋰⒩⋰⋰⒜⋰⋰⒜⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰ ⋰⒨⋰⋰⒠⋰⋰⒭⋰⋰⒜⋰ ⋰⒭⋰⋰⒠⋰⋰⒫⋰⋰⒧⋰⋰⒴⋰ ⋰⒣⋰⋰⒪⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰⋰⒜⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰ ⋰⒥⋰⋰⒜⋰⋰⒴⋰⋰⒠⋰⋰⒢⋰⋰⒤⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒩⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒜⋰⋰⒧⋰⋰⒰⋰ ⋰⒦⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒯⋰⋰⒪⋰ ⋰⒞⋰⋰⒫⋰ ⋰⒝⋰⋰⒪⋰⋰⒧⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰⋰⒰⋰⋰⒢⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒜⋰⋰⒯⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒥⋰⋰⒤⋰⋰⒩⋰⋰⒟⋰⋰⒜⋰ ⋰⒣⋰⋰⒪⋰⋰⒥⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒰⋰⋰⒯⋰⋰⒣⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰ ⋰⒡⋰⋰⒠⋰⋰⒩⋰⋰⒦⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒨⋰⋰⒜⋰⋰⒟⋰⋰⒭⋰⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰",
        "⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒥⋰⋰⒤⋰⋰⒩⋰⋰⒟⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒦⋰⋰⒪⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰ ⋰⒥⋰⋰⒜⋰⋰⒴⋰⋰⒠⋰⋰⒢⋰⋰⒤⋰ ⋰⒨⋰⋰⒠⋰⋰⒭⋰⋰⒠⋰ ⋰⒧⋰⋰⒜⋰⋰⒰⋰⋰⒟⋰⋰⒠⋰ ⋰⒫⋰⋰⒠⋰",
        "⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒤⋰⋰⒮⋰⋰⒠⋰ ⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰⋰⒜⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒟⋰⋰⒜⋰⋰⒡⋰⋰⒜⋰⋰⒩⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰⋰⒪⋰ ⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒨⋰⋰⒠⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒮⋰⋰⒜⋰⋰⒯⋰⋰⒣⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒝⋰⋰⒣⋰⋰⒤⋰ ⋰⒟⋰⋰⒜⋰⋰⒡⋰⋰⒜⋰⋰⒩⋰ ⋰⒣⋰⋰⒪⋰ ⋰⒥⋰⋰⒜⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒜⋰ ⋰⒩⋰⋰⒜⋰⋰⒣⋰⋰⒤⋰ ⋰⒣⋰⋰⒜⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰⋰⒟⋰⋰⒠⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒩⋰⋰⒤⋰⋰⒦⋰⋰⒜⋰⋰⒧⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰",
        "⋰⒢⋰⋰⒜⋰⋰⒤⋰⋰⒭⋰⋰⒝⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒜⋰⋰⒰⋰⋰⒧⋰⋰⒜⋰⋰⒟⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰⋰⒧⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒜⋰⋰⒫⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒮⋰⋰⒫⋰⋰⒠⋰⋰⒠⋰⋰⒟⋰ ⋰⒨⋰⋰⒜⋰⋰⒯⋰⋰⒞⋰⋰⒣⋰ ⋰⒦⋰⋰⒭⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰ ⋰⒢⋰⋰⒜⋰⋰⒭⋰⋰⒤⋰⋰⒝⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒞⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒯⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒡⋰⋰⒠⋰⋰⒦⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒠⋰⋰⒠⋰⋰⒥⋰",
        "⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒩⋰⋰⒜⋰⋰⒣⋰⋰⒤⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰⋰⒢⋰⋰⒤⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰⋰⒟⋰⋰⒠⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰ ⋰⒞⋰⋰⒫⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰ ⋰⒩⋰⋰⒤⋰⋰⒦⋰⋰⒜⋰⋰⒧⋰",
        "⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒩⋰⋰⒜⋰⋰⒣⋰⋰⒤⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰⋰⒢⋰⋰⒤⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒨⋰⋰⒠⋰⋰⒭⋰⋰⒠⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒯⋰⋰⒜⋰⋰⒢⋰ ⋰⒦⋰⋰⒜⋰⋰⒤⋰⋰⒮⋰⋰⒠⋰ ⋰⒦⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰⋰⒭⋰ ⋰⒧⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒥⋰⋰⒤⋰⋰⒩⋰⋰⒟⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒡⋰⋰⒜⋰⋰⒯⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒠⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰ ⋰⒥⋰⋰⒜⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰ ⋰⒜⋰⋰⒝⋰ ⋰⒯⋰⋰⒰⋰",
        "⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰ ⋰⒟⋰⋰⒜⋰⋰⒡⋰⋰⒜⋰⋰⒩⋰ ⋰⒦⋰⋰⒜⋰⋰⒭⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒠⋰ ⋰⒧⋰⋰⒜⋰⋰⒰⋰⋰⒟⋰⋰⒠⋰ ⋰⒫⋰⋰⒠⋰⋰⒭⋰ ⋰⒢⋰⋰⒣⋰⋰⒰⋰⋰⒨⋰⋰⒜⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒦⋰⋰⒣⋰⋰⒜⋰⋰⒟⋰⋰⒠⋰ ⋰⒦⋰⋰⒣⋰⋰⒜⋰⋰⒟⋰⋰⒠⋰ ⋰⒧⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰ ⋰⒧⋰⋰⒠⋰⋰⒦⋰⋰⒤⋰⋰⒩⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒥⋰⋰⒣⋰⋰⒰⋰⋰⒦⋰⋰⒩⋰⋰⒠⋰ ⋰⒩⋰⋰⒜⋰⋰⒤⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰ ⋰⒝⋰⋰⒜⋰⋰⒩⋰⋰⒜⋰⋰⒜⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒠⋰⋰⒤⋰⋰⒩⋰ ⋰⒨⋰⋰⒠⋰⋰⒭⋰⋰⒜⋰ ⋰⒭⋰⋰⒠⋰⋰⒫⋰⋰⒧⋰⋰⒴⋰ ⋰⒣⋰⋰⒪⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰⋰⒜⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒜⋰⋰⒜⋰⋰⒥⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰ ⋰⒥⋰⋰⒜⋰⋰⒴⋰⋰⒠⋰⋰⒢⋰⋰⒤⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒨⋰⋰⒰⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒩⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒜⋰⋰⒧⋰⋰⒰⋰ ⋰⒦⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒯⋰⋰⒪⋰ ⋰⒞⋰⋰⒫⋰ ⋰⒝⋰⋰⒪⋰⋰",
        "⋰Ⓑ⋰⋰⒜⋰⋰⒜⋰⋰⒫⋰ ⋰Ⓑ⋰⋰⒣⋰⋰⒤⋰ ⋰Ⓑ⋰⋰⒩⋰⋰⒜⋰⋰⒧⋰⋰⒠⋰ ⋰⒨⋰⋰⒰⋰⋰⒥⋰⋰⒠⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒜⋰ ⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒫⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒵⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒴⋰⋰⒜⋰⋰⒜⋰⋰⒟⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒯⋰⋰⒰⋰⋰⒥⋰⋰⒣⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒰⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒜⋰ ⋰⒩⋰⋰⒜⋰ ⋰⒯⋰⋰⒴⋰⋰⒨⋰⋰⒫⋰⋰⒜⋰⋰⒮⋰⋰⒮⋰",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰ ⋰⒰⋰⋰⒩⋰⋰⒡⋰⋰⒰⋰⋰⒩⋰⋰⒩⋰⋰⒴⋰ ⋰⒮⋰⋰⒲⋰⋰⒤⋰⋰⒫⋰⋰⒠⋰ ⋰⒨⋰⋰⒯⋰⋰⒯⋰ ⋰⒦⋰⋰⒭⋰",
        "⋰⒪⋰⋰⒣⋰ ⋰⒣⋰⋰⒠⋰⋰⒧⋰⋰⒧⋰⋰⒪⋰ ⋰⒝⋰⋰⒤⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒜⋰ ⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒫⋰ ⋰⒝⋰⋰⒤⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒤⋰ ⋰⒪⋰⋰⒭⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒱⋰ ⋰⒝⋰⋰⒤⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒤⋰ ⋰⒜⋰⋰⒜⋰⋰⒰⋰⋰⒦⋰⋰⒜⋰⋰⒯⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒭⋰⋰⒣⋰⋰⒜⋰ ⋰⒦⋰⋰⒭⋰.",
        "⋰⒪⋰⋰⒴⋰⋰⒴⋰ ⋰⒦⋰⋰⒤⋰⋰⒩⋰⋰⒩⋰⋰⒠⋰⋰⒭⋰ ⋰⒯⋰⋰⒰⋰⋰⒥⋰⋰⒣⋰⋰⒠⋰ ⋰⒢⋰⋰⒞⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒜⋰⋰⒜⋰⋰⒩⋰⋰⒠⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒫⋰⋰⒠⋰⋰⒭⋰⋰⒨⋰⋰⒤⋰⋰⒮⋰⋰⒮⋰⋰⒤⋰⋰⒪⋰⋰⒩⋰ ⋰⒦⋰⋰⒤⋰⋰⒮⋰⋰⒩⋰⋰⒠⋰ ⋰⒟⋰⋰⒤⋰.",
        "⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒦⋰⋰⒠⋰ ⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰⋰⒜⋰",
        "⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒦⋰⋰⒠⋰ ⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰⋰⒜⋰ ⋰⒠⋰⋰⒦⋰ ⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒭⋰.",
        "⋰⒮⋰⋰⒰⋰⋰⒩⋰ ⋰⒮⋰⋰⒰⋰⋰⒩⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒜⋰.",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒞⋰⋰⒜⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰.",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒯⋰⋰⒤⋰ ⋰⒥⋰⋰⒜⋰⋰⒯⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒯⋰⋰⒨⋰⋰⒭⋰.",
        "⋰⒦⋰⋰⒴⋰? ⋰⒥⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰ ⋰⒦⋰⋰⒤⋰⋰⒟⋰⋰⒟⋰⋰⒠⋰.",
        "⋰⒝⋰⋰⒤⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒤⋰ ⋰⒞⋰⋰⒪⋰⋰⒨⋰ ⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒢⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒫⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒯⋰⋰⒜⋰⋰⒢⋰ ⋰⒞⋰⋰⒭⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰ ⋰⒯⋰⋰⒰⋰",
        "⋰⒨⋰⋰⒰⋰⋰⒥⋰⋰⒣⋰⋰⒠⋰ ⋰⒞⋰⋰⒴⋰⋰⒜⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒝⋰⋰⒤⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒤⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒯⋰⋰⒨⋰⋰⒦⋰⋰⒞⋰ ⋰⒝⋰⋰⒮⋰",
        "⋰⒥⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒵⋰ ⋰⒫⋰⋰⒜⋰⋰⒫⋰⋰⒜⋰ ⋰⒝⋰⋰⒪⋰⋰⒧⋰",
        "⋰⒮⋰⋰⒤⋰⋰⒟⋰⋰⒠⋰ ⋰⒣⋰⋰⒪⋰⋰⒥⋰⋰⒜⋰ ⋰⒝⋰⋰⒤⋰⋰⒣⋰⋰⒜⋰⋰⒭⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒜⋰⋰⒤⋰ ⋰⒜⋰⋰⒝⋰",
        "⋰⒣⋰⋰⒴⋰⋰⒠⋰ ⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒝⋰⋰⒣⋰⋰⒢⋰ ⋰⒨⋰⋰⒜⋰⋰⒯⋰ ⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰",
        "⋰⒝⋰⋰⒣⋰⋰⒢⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒜⋰⋰⒥⋰⋰⒥⋰",
        "⋰⒣⋰⋰⒴⋰⋰⒠⋰ ⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰ ⋰⒨⋰⋰⒜⋰⋰⒯⋰",
        "⋰⒣⋰⋰⒴⋰⋰⒠⋰ ⋰⒟⋰⋰⒰⋰⋰⒭⋰ ⋰⒣⋰⋰⒜⋰⋰⒯⋰⋰⒯⋰ ⋰⒨⋰⋰⒜⋰⋰⒟⋰⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰",
        "⋰⒦⋰⋰⒪⋰⋰⒤⋰ ⋰⒝⋰⋰⒜⋰⋰⒯⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒠⋰⋰⒮⋰⋰⒧⋰⋰⒤⋰⋰⒴⋰⋰⒠⋰ ⋰⒨⋰⋰⒜⋰⋰⒡⋰ ⋰⒞⋰⋰⒭⋰ ⋰⒭⋰⋰⒣⋰⋰⒜⋰ ⋰⒣⋰⋰⒰⋰ ⋰⒯⋰⋰⒰⋰⋰⒥⋰⋰⒣⋰⋰⒠⋰",
        "⋰⒦⋰⋰⒪⋰⋰⒤⋰ ⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒯⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒨⋰⋰⒜⋰⋰⒡⋰⋰⒤⋰ ⋰⒟⋰⋰⒠⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒨⋰⋰⒜⋰⋰⒡⋰⋰⒤⋰ ⋰⒨⋰⋰⒤⋰⋰⒧⋰ ⋰⒥⋰⋰⒜⋰⋰⒴⋰⋰⒠⋰⋰⒢⋰⋰⒤⋰ ⋰⒯⋰⋰⒰⋰⋰⒥⋰⋰⒣⋰⋰⒠⋰",
        "⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰⋰⒯⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒜⋰ ⋰⒨⋰⋰⒰⋰⋰⒥⋰⋰⒠⋰ ⋰⒮⋰⋰⒲⋰⋰⒤⋰⋰⒫⋰⋰⒠⋰ ⋰⒞⋰⋰⒭⋰⋰⒦⋰⋰⒠⋰",
        "⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒮⋰⋰⒲⋰⋰⒤⋰⋰⒫⋰⋰⒠⋰ ⋰⒞⋰⋰⒭⋰⋰⒦⋰⋰⒠⋰",
        "⋰⒡⋰⋰⒭⋰ ⋰⒝⋰⋰⒪⋰⋰⒧⋰⋰⒩⋰⋰⒜⋰ ⋰⒩⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰ ⋰⒧⋰⋰⒠⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒮⋰⋰⒲⋰⋰⒤⋰⋰⒫⋰⋰⒠⋰ ⋰⒞⋰⋰⒭⋰⋰⒦⋰⋰⒠⋰",
        "⋰⒞⋰⋰⒴⋰⋰⒜⋰ ⋰⒣⋰⋰⒰⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒴⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒫⋰⋰⒭⋰ ⋰⒦⋰⋰⒠⋰⋰⒮⋰⋰⒠⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒴⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰",
        "⋰⒨⋰⋰⒰⋰⋰⒥⋰⋰⒣⋰⋰⒠⋰ ⋰⒫⋰⋰⒯⋰⋰⒜⋰ ⋰⒯⋰⋰⒣⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒜⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒨⋰⋰⒠⋰⋰⒴⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒩⋰⋰⒯⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒴⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰",
        "⋰⒧⋰⋰⒪⋰⋰⒟⋰⋰⒠⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒰⋰⋰⒯⋰⋰⒭⋰ ⋰⒨⋰⋰⒞⋰",
        "⋰⒧⋰⋰⒰⋰⋰⒩⋰ ⋰⒨⋰⋰⒯⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒮⋰ ⋰⒨⋰⋰⒠⋰⋰⒭⋰⋰⒜⋰",
        "⋰⒩⋰⋰⒤⋰⋰⒦⋰⋰⒜⋰⋰⒧⋰ ⋰⒨⋰⋰⒜⋰⋰⒟⋰⋰⒜⋰⋰⒭⋰⋰⒞⋰⋰⒣⋰⋰⒟⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒪⋰⋰⒴⋰⋰⒠⋰ ⋰⒢⋰⋰⒜⋰⋰⒮⋰⋰⒣⋰⋰⒯⋰⋰⒤⋰ ⋰⒦⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰",
        "⋰⒨⋰⋰⒜⋰⋰⒦⋰⋰⒤⋰⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰",
        "⋰⒨⋰⋰⒜⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒦⋰ ⋰⒣⋰⋰⒜⋰⋰⒯⋰⋰⒣⋰ ⋰⒯⋰⋰⒪⋰⋰⒟⋰⋰⒣⋰ ⋰⒦⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒠⋰ ⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒫⋰ ⋰⒦⋰ ⋰⒨⋰⋰⒰⋰⋰⒣⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒡⋰⋰⒜⋰⋰⒮⋰⋰⒜⋰⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰",
        "⋰⒧⋰⋰⒠⋰⋰⒜⋰⋰⒱⋰⋰⒠⋰ ⋰⒧⋰⋰⒠⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰ ⋰⒫⋰⋰⒜⋰⋰⒮⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒩⋰⋰⒜⋰⋰⒤⋰ ⋰⒜⋰⋰⒴⋰⋰⒜⋰ ⋰⒨⋰⋰⒠⋰⋰⒦⋰⋰⒪⋰",
        "⋰⒧⋰⋰⒠⋰⋰⒜⋰⋰⒱⋰⋰⒠⋰ ⋰⒧⋰⋰⒠⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰ ⋰⒤⋰⋰⒟⋰⋰⒠⋰⋰⒭⋰ ⋰⒮⋰⋰⒠⋰",
        "⋰⒧⋰⋰⒠⋰⋰⒜⋰⋰⒱⋰⋰⒠⋰ ⋰⒧⋰⋰⒠⋰ ⋰⒥⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒲⋰⋰⒭⋰⋰⒩⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒜⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒧⋰⋰⒠⋰⋰⒜⋰⋰⒱⋰⋰⒠⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒧⋰⋰⒠⋰⋰⒢⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒮⋰⋰⒨⋰⋰⒥⋰⋰⒣⋰ ⋰⒝⋰⋰⒜⋰⋰⒯⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒧⋰⋰⒠⋰⋰⒜⋰⋰⒱⋰⋰⒠⋰ ⋰⒧⋰⋰⒠⋰",
        "⋰⒡⋰⋰⒜⋰⋰⒮⋰⋰⒯⋰ ⋰⒧⋰⋰⒠⋰⋰⒜⋰⋰⒱⋰⋰⒠⋰ ⋰⒧⋰⋰⒠⋰ ⋰⒦⋰⋰⒜⋰⋰⒨⋰⋰⒥⋰⋰⒪⋰⋰⒭⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒰⋰⋰⒯⋰⋰⒪⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰",
        "⋰⒪⋰⋰⒴⋰ ⋰⒣⋰⋰⒤⋰⋰⒥⋰⋰⒟⋰⋰⒠⋰ ⋰⒦⋰⋰⒣⋰⋰⒜⋰⋰⒩⋰⋰⒜⋰ ⋰⒦⋰⋰⒣⋰⋰⒜⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒨⋰⋰⒵⋰⋰⒪⋰⋰⒭⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒦⋰⋰⒪⋰ ⋰⒤⋰⋰⒧⋰⋰⒴⋰ ⋰⒭⋰⋰⒠⋰⋰⒴⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒞⋰⋰⒣⋰⋰⒜⋰⋰⒫⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒯⋰⋰⒨⋰⋰⒦⋰⋰⒞⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰⋰⒞⋰⋰⒣⋰⋰⒜⋰⋰⒫⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒯⋰⋰⒰⋰",
        "⋰⒮⋰⋰⒣⋰⋰⒤⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰⋰⒞⋰⋰⒣⋰⋰⒜⋰⋰⒫⋰",
        "⋰⒡⋰⋰⒭⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰⋰⒞⋰⋰⒣⋰⋰⒜⋰⋰⒫⋰",
        "⋰⒮⋰⋰⒣⋰⋰⒤⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰ ⋰⒲⋰⋰⒭⋰⋰⒩⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒜⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒴⋰⋰⒰⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒜⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰⋰⒞⋰⋰⒣⋰⋰⒜⋰⋰⒫⋰",
        "⋰⒫⋰⋰⒭⋰⋰⒪⋰⋰⒪⋰⋰⒡⋰ ⋰⒞⋰⋰⒭⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒴⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒫⋰⋰⒭⋰⋰⒪⋰⋰⒪⋰⋰⒡⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰ ⋰⒠⋰⋰⒴⋰",
        "⋰⒫⋰⋰⒭⋰⋰⒪⋰⋰⒪⋰⋰⒡⋰ ⋰⒣⋰⋰⒪⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒦⋰⋰⒜⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒞⋰⋰⒣⋰⋰⒤⋰⋰⒧⋰⋰⒧⋰⋰⒜⋰⋰⒭⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰ ⋰⒝⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒪⋰⋰⒴⋰ ⋰⒣⋰⋰⒤⋰⋰⒥⋰⋰⒟⋰⋰⒠⋰ ⋰⒦⋰⋰⒣⋰⋰⒜⋰⋰⒩⋰⋰⒜⋰ ⋰⒦⋰⋰⒣⋰⋰⒜⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒨⋰⋰⒵⋰⋰⒪⋰⋰⒭⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒨⋰⋰⒜⋰⋰⒟⋰⋰⒭⋰⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰ ?",
        "⋰⒜⋰⋰⒝⋰ ⋰⒯⋰⋰⒦⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒴⋰⋰⒤⋰ ⋰⒣⋰⋰⒪⋰⋰⒢⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ?",
        "⋰⒩⋰⋰⒴⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒦⋰⋰⒰⋰⋰⒞⋰⋰⒣⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒥⋰⋰⒜⋰⋰⒩⋰⋰⒯⋰⋰⒜⋰ ⋰⒝⋰⋰⒮⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰ ⋰⒠⋰⋰⒴⋰",
        "⋰⒮⋰⋰⒝⋰⋰⒮⋰⋰⒠⋰ ⋰⒫⋰⋰⒣⋰⋰⒠⋰⋰⒧⋰⋰⒠⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒪⋰ ⋰⒝⋰⋰⒪⋰⋰⒧⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒩⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰⋰⒨⋰ ⋰⒦⋰⋰⒭⋰⋰⒠⋰",
        "⋰⒴⋰⋰⒜⋰⋰⒣⋰⋰⒜⋰ ⋰⒝⋰⋰⒣⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒜⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒞⋰⋰⒠⋰ ⋰⒫⋰⋰⒤⋰⋰⒧⋰⋰⒧⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰⋰⒨⋰⋰⒜⋰⋰⒦⋰⋰⒜⋰⋰⒝⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒯⋰⋰⒪⋰ ⋰⒝⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒠⋰⋰⒢⋰⋰⒤⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒫⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰ ⋰⒯⋰⋰⒪⋰⋰⒨⋰⋰⒨⋰⋰⒴⋰",
        "⋰⒩⋰⋰⒤⋰⋰⒦⋰⋰⒜⋰⋰⒧⋰ ⋰⒨⋰⋰⒜⋰⋰⒟⋰⋰⒜⋰⋰⒭⋰⋰⒞⋰⋰⒣⋰⋰⒟⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒦⋰⋰⒠⋰ ⋰⒴⋰⋰⒣⋰⋰⒜⋰ ⋰⒮⋰⋰⒠⋰",
        "⋰⒞⋰⋰⒪⋰⋰⒵⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒣⋰⋰⒤⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒣⋰⋰⒠⋰",
        "⋰⒩⋰⋰⒴⋰⋰⒯⋰⋰⒪⋰ ⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒫⋰ ⋰⒝⋰⋰⒪⋰⋰⒧⋰ ⋰⒨⋰⋰⒰⋰⋰⒥⋰⋰⒣⋰⋰⒠⋰",
        "⋰⒩⋰⋰⒴⋰⋰⒩⋰⋰⒴⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒣⋰⋰⒪⋰⋰⒢⋰⋰⒤⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒤⋰ ⋰⒥⋰⋰⒪⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰⋰⒯⋰⋰⒤⋰ ⋰⒥⋰⋰⒪⋰⋰⒢⋰⋰⒤⋰",
        "⋰⒯⋰⋰⒭⋰⋰⒴⋰ ⋰⒜⋰⋰⒨⋰⋰⒨⋰⋰⒤⋰ ⋰⒞⋰⋰⒠⋰ ⋰⒝⋰⋰⒣⋰⋰⒪⋰⋰⒮⋰⋰⒟⋰⋰⒠⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒠⋰⋰⒨⋰⋰⒪⋰⋰⒥⋰⋰⒤⋰ ⋰⒟⋰⋰⒜⋰⋰⒧⋰ ⋰⒨⋰⋰⒞⋰",
        "⋰⒞⋰⋰⒴⋰⋰⒜⋰ ? ⋰⒞⋰⋰⒣⋰⋰⒨⋰⋰⒭⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒴⋰⋰⒜⋰ ⋰⒞⋰⋰⒴⋰⋰⒜⋰ ?",
        "⋰⒯⋰⋰⒨⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒭⋰⋰⒤⋰ ⋰⒣⋰⋰⒪⋰⋰⒢⋰⋰⒤⋰ ⋰⒡⋰⋰⒭⋰⋰⒭⋰⋰⒯⋰⋰⒪⋰",
        "⋰⒞⋰⋰⒴⋰⋰⒜⋰ ? ⋰⒦⋰⋰⒝⋰ ? ⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒞⋰⋰⒴⋰⋰⒜⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒦⋰⋰⒠⋰⋰⒦⋰",
        "⋰⒞⋰⋰⒴⋰⋰⒜⋰ ⋰⒮⋰⋰⒞⋰⋰⒣⋰ ⋰⒨⋰⋰⒠⋰⋰⒴⋰ ⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒞⋰⋰⒴⋰⋰⒜⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰ ⋰⒧⋰⋰⒤⋰ ⋰⒯⋰⋰⒰⋰⋰⒩⋰⋰⒠⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰",
        "⋰⒤⋰⋰⒯⋰⋰⒩⋰⋰⒜⋰ ⋰⒮⋰⋰⒞⋰⋰⒣⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒝⋰⋰⒪⋰⋰⒧⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒜⋰⋰⒤⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰",
        "⋰⒮⋰⋰⒞⋰⋰⒣⋰ ⋰⒨⋰⋰⒠⋰⋰⒴⋰ ⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒜⋰⋰⒫⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒲⋰⋰⒜⋰ ⋰⒧⋰⋰⒤⋰⋰⒜⋰ ⋰⒨⋰⋰⒠⋰⋰⒭⋰⋰⒠⋰ ⋰⒮⋰⋰⒯⋰⋰⒣⋰",
        "⋰⒨⋰⋰⒯⋰⋰⒧⋰⋰⒝⋰ ⋰⒯⋰⋰⒨⋰⋰⒭⋰",
        "⋰⒩⋰⋰⒴⋰⋰⒯⋰⋰⒪⋰",
        "⋰⒫⋰⋰⒰⋰⋰⒭⋰⋰⒜⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰ ⋰⒨⋰⋰⒞⋰",
        "⋰⒯⋰⋰⒨⋰⋰⒭⋰ ⋰⒡⋰⋰⒭⋰⋰⒭⋰⋰⒯⋰⋰⒪⋰",
        "⋰⒪⋰⋰⒣⋰ ⋰⒪⋰⋰⒦⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒧⋰⋰⒠⋰ ⋰⒡⋰⋰⒤⋰⋰⒭⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒟⋰⋰⒜⋰⋰⒨⋰⋰⒜⋰⋰⒟⋰",
        "⋰⒞⋰⋰⒴⋰⋰⒜⋰ ? ⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰ ⋰⒮⋰⋰⒠⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰⋰⒠⋰ ⋰⒫⋰⋰⒠⋰⋰⒣⋰⋰⒧⋰⋰⒠⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒠⋰⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰",
        "⋰⒩⋰⋰⒴⋰⋰⒯⋰⋰⒪⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒩⋰⋰⒠⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒱⋰⋰⒴⋰⋰⒜⋰⋰⒮⋰⋰⒯⋰ ⋰⒣⋰⋰⒰⋰",
        "⋰⒩⋰⋰⒴⋰⋰⒯⋰⋰⒪⋰ ⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒞⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒰⋰⋰⒞⋰⋰⒣⋰ ⋰⒝⋰⋰⒤⋰",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰⋰⒠⋰ ⋰⒞⋰⋰⒴⋰⋰⒜⋰ ? ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒴⋰⋰⒜⋰ ?",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒨⋰⋰⒯⋰ ⋰⒣⋰⋰⒮⋰⋰⒮⋰",
        "⋰⒴⋰⋰⒰⋰⋰⒭⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒤⋰ ⋰⒨⋰⋰⒪⋰⋰⒨⋰",
        "⋰⒜⋰⋰⒭⋰⋰⒠⋰ ⋰⒮⋰⋰⒝⋰⋰⒦⋰⋰⒤⋰ ⋰⒨⋰⋰??⋰⋰⒜⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒤⋰ ⋰⒪⋰⋰⒭⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒝⋰⋰⒤⋰",
        "⋰⒜⋰⋰⒭⋰⋰⒠⋰ ⋰⒤⋰⋰⒟⋰⋰⒜⋰⋰⒭⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰⋰⒧⋰⋰⒠⋰ ⋰⒠⋰⋰⒦⋰ ⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒭⋰",
        "⋰⒯⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒤⋰ ⋰⒯⋰⋰⒭⋰⋰⒣⋰",
        "⋰⒠⋰⋰⒦⋰ ⋰⒧⋰⋰⒤⋰⋰⒩⋰⋰⒠⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒯⋰⋰⒨⋰⋰⒭⋰",
        "⋰⒬⋰",
        "⋰⒪⋰⋰⒞⋰⋰⒴⋰ ⋰⒜⋰⋰⒝⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒧⋰⋰⒠⋰",
        "⋰⒫⋰⋰⒠⋰⋰⒣⋰⋰⒠⋰⋰⒧⋰⋰⒠⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒰⋰",
        "⋰⒩⋰⋰⒴⋰⋰⒯⋰⋰⒪⋰",
        "⋰⒬⋰ ?",
        "⋰⒣⋰⋰⒴⋰⋰⒴⋰⋰⒴⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒜⋰ ⋰⒠⋰⋰⒦⋰ ⋰⒝⋰⋰⒜⋰⋰⒜⋰⋰⒭⋰",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰⋰⒠⋰ ⋰⒮⋰⋰⒰⋰⋰⒩⋰ ⋰⒟⋰⋰⒪⋰⋰⒮⋰⋰⒯⋰ ⋰⒯⋰⋰⒨⋰⋰⒭⋰",
        "⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰ ⋰⒥⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰⋰⒡⋰ ⋰⒞⋰⋰⒭⋰⋰⒭⋰ ⋰⒟⋰⋰⒰⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰⋰⒠⋰ ⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒤⋰ ⋰⒤⋰⋰⒟⋰⋰⒜⋰⋰⒭⋰ ⋰⒜⋰⋰⒜⋰",
        "⋰⒞⋰⋰⒴⋰⋰⒜⋰ ⋰⒯⋰⋰⒨⋰⋰⒭⋰ ⋰⒡⋰⋰⒭⋰⋰⒭⋰⋰⒯⋰⋰⒪⋰",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰⋰⒠⋰ ⋰⒤⋰⋰⒟⋰⋰⒜⋰⋰⒭⋰ ⋰⒜⋰⋰⒜⋰⋰⒦⋰⋰⒠⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒧⋰⋰⒠⋰ ⋰⒞⋰⋰⒣⋰⋰⒨⋰⋰⒭⋰",
        "⋰⒩⋰⋰⒴⋰⋰⒯⋰⋰⒪⋰ ⋰⒜⋰⋰⒠⋰⋰⒮⋰⋰⒠⋰ ⋰⒣⋰⋰⒤⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰⋰⒠⋰ ⋰⒣⋰⋰⒴⋰⋰⒴⋰ ⋰⒜⋰⋰⒤⋰⋰⒮⋰⋰⒠⋰ ⋰⒣⋰⋰⒤⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒧⋰⋰⒠⋰⋰⒩⋰⋰⒜⋰",
        "⋰⒪⋰⋰⒭⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒧⋰⋰⒠⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒜⋰ ⋰⒪⋰⋰⒭⋰",
        "⋰⒣⋰⋰⒴⋰⋰⒴⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒪⋰ ⋰⒩⋰⋰⒜⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒪⋰ ⋰⒨⋰⋰⒯⋰ ⋰⒝⋰⋰⒣⋰⋰⒜⋰⋰⒢⋰ ⋰⒥⋰⋰⒜⋰⋰⒪⋰",
        "⋰⒝⋰⋰⒴⋰⋰⒴⋰⋰⒠⋰⋰⒠⋰ ⋰⒣⋰⋰⒴⋰⋰⒴⋰ ⋰⒞⋰⋰⒴⋰⋰⒜⋰ ?",
        "⋰⒬⋰⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒬⋰ ⋰⒭⋰⋰⒣⋰⋰⒠⋰ ⋰⒣⋰⋰⒪⋰ ?",
        "⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒠⋰⋰⒴⋰ ⋰⒞⋰⋰⒴⋰⋰⒜⋰ ⋰⒨⋰⋰⒞⋰",
        "⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰ ⋰⒨⋰⋰⒯⋰",
        "⋰Ⓙ⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒠⋰⋰⒥⋰",
        "⋰⒪⋰⋰⒭⋰ ⋰⒝⋰⋰⒟⋰⋰⒜⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰",
        "⋰⒪⋰⋰⒭⋰ ⋰⒝⋰⋰⒟⋰⋰⒜⋰",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰ ⋰⒦⋰⋰⒤⋰⋰⒟⋰⋰⒟⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒝⋰⋰⒰⋰⋰⒭⋰",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰ ⋰⒦⋰⋰⒠⋰⋰⒠⋰⋰⒟⋰⋰⒠⋰",
        "⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒧⋰⋰⒜⋰⋰⒟⋰⋰⒦⋰⋰⒠⋰",
        "⋰Ⓙ⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒝⋰⋰⒠⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒰⋰",
        "⋰⒨⋰⋰⒦⋰⋰⒧⋰ ⋰⒰⋰⋰⒯⋰⋰⒣⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒜⋰⋰⒞⋰⋰⒞⋰⋰⒣⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒩⋰⋰⒜⋰⋰⒩⋰⋰⒤⋰ ⋰⒨⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰⋰⒧⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒥⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰ ⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒞⋰⋰⒠⋰",
        "⋰⒪⋰⋰⒴⋰⋰⒠⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰⋰⒦⋰⋰⒠⋰ ⋰⒧⋰⋰⒪⋰⋰⒟⋰⋰⒠⋰ ⋰⒨⋰⋰⒭⋰⋰⒠⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒴⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒤⋰⋰⒴⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒢⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒟⋰⋰⒜⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒡⋰⋰⒰⋰⋰⒟⋰⋰⒟⋰⋰⒜⋰",
        "⋰⒨⋰⋰⒦⋰⋰⒧⋰ ⋰⒰⋰⋰⒯⋰⋰⒣⋰ ⋰⒝⋰⋰⒠⋰⋰⒣⋰⋰⒠⋰⋰⒩⋰⋰⒞⋰⋰⒪⋰⋰⒟⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒤⋰ ⋰⒝⋰⋰⒰⋰⋰⒭⋰ ⋰⒟⋰⋰⒠⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒦⋰⋰⒜⋰ ⋰⒡⋰⋰⒰⋰⋰⒟⋰⋰⒟⋰⋰⒜⋰ ⋰⒨⋰⋰⒠⋰ ⋰⒧⋰⋰⒪⋰⋰⒟⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰⋰⒱⋰⋰⒜⋰",
        "⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒠⋰⋰⒯⋰⋰⒠⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰ ⋰⒢⋰⋰⒜⋰⋰⒴⋰⋰⒜⋰",
        "⋰Ⓙ⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒭⋰ ⋰⒮⋰⋰⒫⋰⋰⒜⋰⋰⒨⋰",
        "⋰⒨⋰⋰⒞⋰ ⋰⒮⋰⋰⒫⋰⋰⒜⋰⋰⒨⋰ ⋰⒭⋰⋰⒪⋰⋰⒦⋰⋰⒠⋰⋰⒩⋰⋰⒢⋰⋰⒜⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰⋰⒦⋰⋰⒤⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒮⋰⋰⒫⋰⋰⒜⋰⋰⒨⋰ ⋰⒦⋰⋰⒭⋰",
        "⋰⒮⋰⋰⒫⋰⋰⒜⋰⋰⒨⋰ ⋰⒦⋰⋰⒭⋰.⋰⒨⋰⋰⒜⋰⋰⒜⋰⋰⒦⋰⋰⒠⋰ ⋰⒧⋰⋰⒪⋰⋰⒟⋰⋰⒠⋰",
        "⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒠⋰ ⋰⒮⋰⋰⒫⋰⋰⒜⋰⋰⒨⋰ ⋰⒦⋰⋰⒭⋰",
        "⋰⒮⋰⋰⒫⋰⋰⒜⋰⋰⒨⋰ ⋰⒦⋰⋰⒭⋰ ⋰⒦⋰⋰⒤⋰⋰⒟⋰",
        "⋰⒩⋰⋰⒪⋰⋰⒪⋰⋰⒝⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒰⋰",
        "⋰⒭⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒠⋰⋰⒯⋰⋰⒠⋰",
        "⋰⒩⋰⋰⒪⋰⋰⒪⋰⋰⒝⋰ ⋰Ⓙ⋰⋰⒜⋰⋰⒧⋰⋰⒟⋰⋰⒤⋰ ⋰⒧⋰⋰⒤⋰⋰⒦⋰⋰⒣⋰ ⋰⒲⋰⋰⒭⋰⋰⒩⋰⋰⒜⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰",
        "⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒢⋰⋰⒜⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒩⋰⋰⒪⋰⋰⒪⋰⋰⒝⋰",
        "⋰⒰⋰⋰⒯⋰⋰⒣⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒴⋰⋰⒦⋰⋰⒠⋰ ⋰⒩⋰⋰⒪⋰⋰⒪⋰⋰⒝⋰",
        "⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒣⋰⋰⒪⋰ ⋰⒩⋰⋰⒪⋰⋰⒪⋰⋰⒝⋰",
        "⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰ ⋰⒝⋰⋰⒩⋰⋰⒥⋰⋰⒜⋰ ⋰⒯⋰⋰⒰⋰ ⋰⒩⋰⋰⒪⋰⋰⒪⋰⋰⒝⋰",
        "⋰⒨⋰⋰⒜⋰⋰⒦⋰⋰⒤⋰⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒩⋰⋰⒪⋰⋰⒪⋰⋰⒝⋰",
        "⋰⒣⋰⋰⒜⋰⋰⒧⋰⋰⒦⋰⋰⒠⋰",
        "⋰⒞⋰⋰⒰⋰⋰⒟⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒫⋰⋰⒢⋰⋰⒧⋰ ⋰⒩⋰⋰⒴⋰ ⋰⒣⋰⋰⒪⋰ ⋰⒩⋰⋰⒪⋰⋰⒪⋰⋰⒝⋰",
        "⋰⒨⋰⋰⒜⋰⋰⒦⋰⋰⒤⋰⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒴⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰",
        "⋰⒨⋰⋰⒜⋰⋰⒦⋰⋰⒤⋰⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒯⋰ ⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒰⋰⋰⒟⋰",
        "⋰⒯⋰⋰⒠⋰⋰⒭⋰⋰⒤⋰ ⋰⒨⋰⋰⒜⋰⋰⒜⋰ ⋰⒞⋰⋰⒣⋰⋰⒪⋰⋰⒟⋰⋰⒱⋰⋰⒜⋰",
        "⋰⒭⋰⋰⒜⋰⋰⒩⋰⋰⒟⋰⋰⒤⋰ ⋰⒦⋰⋰⒠⋰ ⋰⒝⋰⋰⒠⋰⋰⒯⋰⋰⒠⋰ ⋰⒨⋰⋰⒜⋰⋰⒭⋰ ⋰⒢⋰⋰⒜⋰⋰⒴⋰⋰⒜⋰",
        "⋰Ⓓ⋰⋰⒪⋰⋰⒮⋰⋰⒯⋰",
        ]
            
        cs_texts = [
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇰​ะะ🇦​ะ ะ🇧​ะะ🇴​ะะ🇸​ะะ🇪​ะะ🇼​ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะะ🇰​ะะ🇪​ะะ🇧​ะะ🇦​ะะ🇨​ะะ🇭​ะะ🇪​ะ, ะ🇹​ะะ🇺​ะ ะ🇧​ะะ🇭​ะะ🇮​ะ ะ🇰​ะะ🇮​ะะ🇸​ะะ🇸​ะะ🇦​ะะ🇬​ะะ🇦​ะ",
        "ะ🇦​ะะ🇦​ะะ🇯​ะ ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇰​ะะ🇦​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ, ะ🇹​ะะ🇺​ะ ะ🇰​ะะ🇾​ะะ🇦​ะ ะ🇭​ะะ🇦​ะะ🇮​ะ",
        "ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇷​ะะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะ, ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇰​ะะ🇦​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇧​ะะ🇭​ะะ🇪​ะะ🇳​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ, ะ🇹​ะะ🇺​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะ",
        "ะ🇨​ะะ🇭​ะะ🇺​ะะ🇩​ะ ะ🇯​ะะ🇦​ะ, ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇩​ะะ🇮​ะะ🇩​ะะ🇮​ะ ะ🇷​ะะ🇳​ะะ🇩​ะะ🇮​ะ",
        "ะ🇸​ะะ🇱​ะะ🇴​ะะ🇼​ะ, ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇮​ะะ🇾​ะะ🇦​ะ ะ🇨​ะะ🇮​ะะ🇴​ะะ🇩​ะะ🇺​ะ",
        "ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ, ะ🇹​ะะ🇺​ะ ะ🇰​ะะ🇾​ะะ🇦​ะ ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇸​ะะ🇰​ะะ🇹​ะะ🇦​ะ",
        "ะ🇧​ะะ🇭​ะะ🇦​ะะ🇰​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ, ะ🇹​ะะ🇲​ะะ🇦​ะ ะ🇨​ะะ🇴​ะะ🇩​ะะ🇺​ะ",
        "ะ🇸​ะะ🇱​ะะ🇴​ะะ🇼​ะ ะ🇫​ะะ🇮​ะะ🇷​ะะ🇸​ะะ🇪​ะ, ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇰​ะะ🇦​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ",
        "ะ🇨​ะะ🇺​ะะ🇩​ะะ🇬​ะะ🇷​ะะ🇮​ะะ🇧​ะ, ะ🇹​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะ ะ🇩​ะะ🇴​ะะ🇺​ะ",
        "ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇨​ะะ🇴​ะะ🇩​ะะ🇺​ะ, ะ🇳​ะะ🇪​ะะ🇹​ะ ะ🇴​ะะ🇳​ะ ะ🇴​ะะ🇫​ะะ🇫​ะ ะ🇼​ะะ🇦​ะะ🇱​ะะ??​ะ ะ🇷​ะะ🇳​ะะ🇩​ะะ??​ะ",
        "ะ🇴​ะะ🇾​ะะ🇪​ะ ะ🇹​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะ ะ🇨​ะะ🇴​ะะ🇩​ะะ🇺​ะ, ะ🇮​ะะ🇩​ะะ🇭​ะะ🇦​ะะ🇷​ะ ะ🇦​ะะ🇦​ะะ🇰​ะะ🇪​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ",
        "ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇷​ะะ🇩​ะะ🇺​ะ, ะ🇴​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะะ🇰​ะะ🇪​ะ ะ🇱​ะะ🇴​ะะ🇩​ะะ🇪​ะะ🇪​ะ",
        "ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇪​ะะ🇪​ะะ🇯​ะ, ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ ะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะะ🇺​ะ",
        "ะ🇸​ะะ🇺​ะะ🇦​ะะ🇷​ะ ะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇪​ะะ🇪​ะะ🇯​ะ, ะ🇳​ะะ🇪​ะะ🇹​ะ ะ🇴​ะะ🇫​ะะ🇫​ะ ะ🇴​ะะ🇳​ะ ะ🇰​ะะ🇷​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ ะ🇱​ะะ🇦​ะะ🇩​ะะ🇰​ะะ🇪​ะ",
        "ะ🇹​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะ ะ🇨​ะะ🇺​ะะ🇩​ะะ🇮​ะ ะ🇰​ะะ🇪​ะะ🇸​ะะ🇪​ะ, ะ🇨​ะะ🇭​ะะ🇺​ะะ🇵​ะ ะ🇸​ะะ🇱​ะะ🇴​ะะ🇼​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇭​ะะ🇦​ะะ🇷​ะะ🇨​ะะ🇴​ะะ🇩​ะ",
        "ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇨​ะะ🇴​ะะ🇩​ะะ🇺​ะ ะ🇰​ะะ🇷​ะ ะ🇲​ะะ🇸​ะะ🇬​ะ ะ🇩​ะะ🇪​ะะ🇱​ะะ🇪​ะะ🇹​ะะ🇪​ะ, ะ🇴​ะะ🇮​ะ ะ🇸​ะะ🇺​ะะ🇦​ะะ🇷​ะ ะ🇰​ะะ🇪​ะ ะ🇱​ะะ🇦​ะะ🇩​ะะ🇰​ะะ🇪​ะ",
        "ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ ะ🇫​ะะ🇺​ะะ🇫​ะะ🇮​ะ, ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇩​ะะ🇮​ะะ🇩​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇩​ะะ🇮​ะ",
        "ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ ะ🇩​ะะ🇮​ะะ🇰​ะะ🇭​ะะ🇦​ะ, ะ🇨​ะะ🇺​ะะ🇩​ะ ะ🇦​ะะ🇧​ะ",
        "ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ, ะ🇧​ะะ🇭​ะะ🇦​ะะ🇰​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ",
        "ะ🇨​ะะ🇺​ะะ🇩​ะะ🇱​ะะ🇪​ะ ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇷​ะะ🇺​ะ, ะ🇹​ะะ🇲​ะะ🇰​ะะ🇱​ะ ะ🇨​ะะ🇺​ะะ🇩​ะะ🇱​ะะ🇪​ะ ะ🇬​ะะ🇷​ะะ🇮​ะะ🇧​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇧​ะะ🇪​ะะ🇭​ะะ🇪​ะะ🇳​ะ ะ🇻​ะะ🇪​ะะ🇸​ะะ🇮​ะะ🇾​ะะ🇦​ะะ🇦​ะ ะ🇷​ะะ🇳​ะะ🇩​ะะ🇮​ะ, ะ🇮​ะะ🇹​ะะ🇳​ะะ🇦​ะ ะ🇬​ะะ🇳​ะะ🇩​ะะ🇦​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇩​ะะ🇦​ะ ะ🇹​ะะ🇺​ะ ะ🇫​ะะ🇮​ะะ🇷​ะะ🇸​ะะ🇪​ะ ะ🇳​ะะ🇪​ะะ🇹​ะ ะ🇴​ะะ🇳​ะ ะ🇴​ะะ🇫​ะะ🇫​ะ",
        "ะ🇬​ะะ🇷​ะะ🇮​ะะ🇧​ะ ะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇪​ะะ🇹​ะะ🇪​ะ, ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇯​ะะ🇦​ะ ะ🇱​ะะ🇴​ะะ🇩​ะะ🇪​ะ ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇦​ะะ🇷​ะะ🇺​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ",
        "ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇷​ะะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะะ🇦​ะ, ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ",
        "ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ, ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇪​ะะ🇾​ะ ะ🇨​ะะ🇵​ะ",
        "ะ🇨​ะะ🇵​ะ ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇪​ะะ🇭​ะะ🇭​ะ, ะ🇨​ะะ🇵​ะ ะ🇹​ะะ🇲​ะะ🇰​ะะ🇱​ะ ะ🇲​ะะ🇪​ะะ🇭​ะ",
        "ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ, ะ🇦​ะะ🇧​ะะ🇪​ะ ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ",
        "ะ🇩​ะะ🇴​ะะ🇺​ะะ🇧​ะะ🇱​ะะ🇪​ะ ะ🇸​ะะ🇪​ะะ🇳​ะะ🇩​ะ ะ🇰​ะะ🇴​ะ ะ🇨​ะะ🇵​ะ ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ ะ🇨​ะะ🇴​ะะ🇩​ะะ🇺​ะ, ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇪​ะ ะ🇨​ะะ🇵​ะ ะ🇨​ะะ🇴​ะะ🇩​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ ะ🇦​ะะ🇦​ะะ🇯​ะ ะ🇲​ะะ🇪​ะะ🇭​ะะ🇭​ะ",
        "ะ🇭​ะะ🇹​ะ ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇩​ะะ🇦​ะะ🇱​ะะ🇦​ะะ🇱​ะ ะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇪​ะะ🇹​ะะ🇪​ะ., ะ🇷​ะะ🇳​ะะ🇩​ะะ🇾​ะ ะ🇯​ะะ🇱​ะะ🇩​ะะ🇮​ะ ะ🇯​ะะ🇱​ะะ🇩​ะะ🇮​ะ ะ🇨​ะะ🇺​ะะ🇩​ะะ🇶​ะ ะ🇹​ะะ🇷​ะะ🇾​ะะ🇲​ะะ🇦​ะ",
        "ะ🇵​ะะ🇦​ะะ🇷​ะะ🇦​ะ ะ🇱​ะะ🇮​ะะ🇰​ะะ🇭​ะะ🇪​ะะ🇬​ะะ🇦​ะ.., ะ🇹​ะะ🇷​ะะ🇦​ะ ะ🇷​ะะ🇳​ะะ🇩​ะะ🇭​ะะ🇧​ะะ🇭​ะะ🇦​ะะ🇰​ะ",
        "ะ🇱​ะะ🇦​ะะ🇬​ะะ🇩​ะะ🇮​ะ ะ🇰​ะะ🇪​ะ ะ🇱​ะะ🇦​ะะ🇩​ะะ🇨​ะะ🇪​ะ ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ, ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ ะ🇱​ะะ🇦​ะะ🇬​ะะ🇩​ะะ🇮​ะ ะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇪​ะะ🇹​ะะ🇪​ะ..",
        "ะ🇨​ะะ🇺​ะะ🇩​ะะ🇰​ะะ🇪​ะ ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ, ะ🇧​ะะ🇭​ะะ🇮​ะะ🇰​ะะ🇦​ะะ🇷​ะะ🇮​ะ ะ🇱​ะะ🇺​ะะ🇳​ะะ🇩​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ??​ะ ะ🇲​ะะ🇪​ะะ🇷​ะะ🇦​ะ.",
        "ะ🇱​ะะ🇴​ะะ🇼​ะ ะ🇱​ะะ🇪​ะะ🇻​ะะ🇪​ะะ🇱​ะ ะ🇨​ะะ🇵​ะ ะ🇨​ะะ🇷​ะ, ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ ะ🇱​ะะ🇴​ะะ🇼​ะ ะ🇱​ะะ🇪​ะะ🇻​ะะ🇪​ะะ🇱​ะ ะ🇼​ะะ🇪​ะะ🇦​ะะ🇰​ะ",
        "ะ🇲​ะะ🇪​ะะ🇷​ะะ🇪​ะ ะ🇱​ะะ🇺​ะะ🇳​ะะ🇩​ะ ะ🇵​ะะ🇪​ะ ะ🇪​ะะ🇾​ะ ะ🇹​ะะ🇺​ะ ะ🇭​ะะ🇮​ะะ🇯​ะะ🇩​ะะ🇪​ะ, ะ🇫​ะะ🇷​ะะ🇪​ะะ🇪​ะ ะ🇨​ะะ🇺​ะะ🇩​ะะ🇼​ะะ🇦​ะ ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะะ🇰​ะะ🇴​ะ",
        "ะ🇫​ะะ🇷​ะะ🇪​ะะ🇪​ะ ะ🇲​ะะ🇪​ะะ🇾​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ ะ🇹​ะะ🇺​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ, ะ🇹​ะะ🇺​ะ ะ🇧​ะะ🇭​ะะ🇮​ะ ะ🇰​ะะ🇮​ะ ะ🇰​ะะ🇾​ะะ🇦​ะ ะ🇭​ะะ🇦​ะะ🇮​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇨​ะะ🇱​ะะ🇦​ะะ🇮​ะะ🇲​ะ ะ🇨​ะะ🇷​ะะ🇼​ะะ🇦​ะ, ะ🇹​ะะ🇺​ะ ะ🇰​ะะ🇾​ะะ🇦​ะ ะ🇧​ะะ🇭​ะะ🇮​ะ ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇸​ะะ🇰​ะะ🇹​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇧​ะะ🇭​ะะ🇪​ะะ🇳​ะ ะ🇻​ะะ🇪​ะะ🇸​ะะ🇮​ะะ🇾​ะะ🇦​ะะ🇦​ะ ะ🇷​ะะ🇳​ะะ🇩​ะะ🇮​ะ, ะ??​ะะ🇺​ะ ะ🇰​ะะ🇾​ะะ🇦​ะ ะ🇨​ะะ??​ะะ🇺​ะะ🇩​ะ ะ🇯​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇩​ะะ🇮​ะะ🇩​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇩​ะะ🇮​ะ, ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ ะ🇩​ะะ🇮​ะะ🇰​ะะ🇭​ะะ🇦​ะ",
        "ะ🇨​ะะ🇺​ะะ🇩​ะ ะ🇦​ะะ🇧​ะ, ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ",
        "ะ🇧​ะะ🇭​ะะ🇦​ะะ🇰​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ, ะ🇨​ะะ🇺​ะะ🇩​ะะ🇱​ะะ🇪​ะ ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇷​ะะ🇺​ะ",
        "ะ🇹​ะะ🇲​ะะ🇰​ะะ🇱​ะ ะ🇨​ะะ🇺​ะะ🇩​ะะ🇱​ะะ🇪​ะ ะ🇬​ะะ🇷​ะะ🇮​ะะ🇧​ะ, ะ🇹​ะะ🇪​ะะ??​ะะ🇾​ะ ะ🇧​ะะ🇪​ะะ🇭​ะะ🇪​ะะ🇳​ะ ะ🇻​ะะ🇪​ะะ🇸​ะะ🇮​ะะ🇾​ะะ🇦​ะะ🇦​ะ ะ🇷​ะะ🇳​ะะ🇩​ะะ🇮​ะ",
        "ะ🇮​ะะ🇹​ะะ🇳​ะะ🇦​ะ ะ🇬​ะะ🇳​ะะ🇩​ะะ🇦​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇩​ะะ🇦​ะ ะ🇹​ะะ🇺​ะ ะ🇫​ะะ🇮​ะะ🇷​ะะ🇸​ะะ🇪​ะ ะ🇳​ะะ🇪​ะะ🇹​ะ ะ🇴​ะะ🇳​ะ ะ🇴​ะะ🇫​ะะ🇫​ะ, ะ🇬​ะะ🇷​ะะ🇮​ะะ🇧​ะ ะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇪​ะะ🇹​ะะ🇪​ะ",
        "ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇯​ะะ🇦​ะ ะ🇱​ะะ🇴​ะะ🇩​ะะ🇪​ะ ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇦​ะะ🇷​ะะ🇺​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ, ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇷​ะะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะะ🇦​ะ",
        "ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ, ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ",
        "ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇪​ะะ🇾​ะ ะ🇨​ะะ🇵​ะ, ะ🇨​ะะ🇵​ะ ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇪​ะะ🇭​ะะ🇭​ะ",
        "ะ🇨​ะะ🇵​ะ ะ🇹​ะะ🇲​ะะ🇰​ะะ🇱​ะ ะ🇲​ะะ🇪​ะะ🇭​ะ, ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ",
        "ะ??​ะะ🇧​ะะ🇪​ะ ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ, ะ🇩​ะะ🇴​ะะ🇺​ะะ🇧​ะะ🇱​ะะ🇪​ะ ะ🇸​ะะ🇪​ะะ🇳​ะะ🇩​ะ ะ🇰​ะะ🇴​ะ ะ🇨​ะะ🇵​ะ ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ ะ🇨​ะะ🇴​ะะ🇩​ะะ🇺​ะ",
        "ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇲​ะะ🇪​ะ ะ🇨​ะะ🇵​ะ ะ🇨​ะะ🇴​ะะ🇩​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ ะ🇦​ะะ🇦​ะะ🇯​ะ ะ🇲​ะะ🇪​ะะ🇭​ะะ🇭​ะ, ะ🇭​ะะ🇹​ะ ะ🇹​ะะ🇧​ะะ🇰​ะะ🇨​ะ ะ🇩​ะะ🇦​ะะ🇱​ะะ🇦​ะะ🇱​ะ ะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇪​ะะ🇹​ะะ🇪​ะ.",
        "ะ🇷​ะะ🇳​ะะ🇩​ะะ🇾​ะ ะ🇯​ะะ🇱​ะะ🇩​ะะ🇮​ะ ะ🇯​ะะ🇱​ะะ🇩​ะะ🇮​ะ ะ🇨​ะะ🇺​ะะ🇩​ะะ🇶​ะ ะ🇹​ะะ🇷​ะะ🇾​ะะ🇲​ะะ🇦​ะ, ะ🇵​ะะ🇦​ะะ🇷​ะะ🇦​ะ ะ🇱​ะะ🇮​ะะ🇰​ะะ🇭​ะะ🇪​ะะ🇬​ะะ🇦​ะ..",
        "ะ🇹​ะะ🇷​ะะ🇦​ะ ะ🇷​ะะ🇳​ะะ🇩​ะะ🇭​ะะ🇧​ะะ🇭​ะะ🇦​ะะ🇰​ะ, ะ🇱​ะะ🇦​ะะ🇬​ะะ🇩​ะะ🇮​ะ ะ🇰​ะะ🇪​ะ ะ🇱​ะะ🇦​ะะ🇩​ะะ🇨​ะะ🇪​ะ ะ??​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ",
        "ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ ะ🇱​ะะ🇦​ะะ🇬​ะะ🇩​ะะ🇮​ะ ะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇪​ะะ🇹​ะะ🇪​ะ.., ะ🇨​ะะ🇺​ะะ🇩​ะะ🇰​ะะ🇪​ะ ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ",
        "ะ🇧​ะะ🇭​ะะ🇮​ะะ🇰​ะะ🇦​ะะ🇷​ะะ🇮​ะ ะ🇱​ะะ🇺​ะะ🇳​ะะ🇩​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇸​ะ ะ🇲​ะะ🇪​ะะ🇷​ะะ🇦​ะ., ะ🇱​ะะ🇴​ะะ🇼​ะ ะ🇱​ะะ🇪​ะะ🇻​ะะ🇪​ะะ🇱​ะ ะ🇨​ะะ🇵​ะ ะ🇨​ะะ🇷​ะ",
        "ะ🇨​ะะ🇵​ะ ะ🇧​ะะ🇴​ะะ🇱​ะ ะ🇱​ะะ🇴​ะะ🇼​ะ ะ🇱​ะะ🇪​ะะ🇻​ะะ🇪​ะะ🇱​ะ ะ🇼​ะะ🇪​ะะ🇦​ะะ🇰​ะ, ะ🇲​ะะ🇪​ะะ🇷​ะะ🇪​ะ ะ🇱​ะะ🇺​ะะ🇳​ะะ🇩​ะ ะ🇵​ะะ🇪​ะ ะ🇪​ะะ🇾​ะ ะ🇹​ะะ🇺​ะ ะ🇭​ะะ🇮​ะะ🇯​ะะ🇩​ะะ🇪​ะ",
        "ะ🇫​ะะ🇷​ะะ🇪​ะะ🇪​ะ ะ🇨​ะะ🇺​ะะ🇩​ะะ🇼​ะะ🇦​ะ ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะะ🇰​ะะ🇴​ะ, ะ🇫​ะะ🇷​ะะ🇪​ะะ🇪​ะ ะ🇲​ะะ🇪​ะะ🇾​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ ะ🇹​ะะ🇺​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇾​ะะ🇰​ะะ🇪​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇨​ะะ🇱​ะะ🇦​ะะ🇮​ะะ🇲​ะ ะ🇨​ะะ🇷​ะะ🇼​ะะ🇦​ะ, ะ🇹​ะะ🇺​ะ ะ🇰​ะะ🇾​ะะ🇦​ะ ะ🇧​ะะ🇭​ะะ🇮​ะ ะ🇧​ะะ🇭​ะะ🇦​ะะ🇬​ะ ะ🇸​ะะ🇰​ะะ🇹​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇧​ะะ🇭​ะะ🇪​ะะ🇳​ะ ะ🇻​ะะ🇪​ะะ🇸​ะะ🇮​ะะ🇾​ะะ🇦​ะะ🇦​ะ ะ🇷​ะะ🇳​ะะ🇩​ะะ🇮​ะ, ะ🇹​ะะ🇺​ะ ะ🇰​ะะ🇾​ะะ🇦​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇩​ะ ะ🇯​ะะ🇦​ะ"
        "ะ🇯ะะ🇦ะะ🇱ะะ🇩ะะ🇮ะ ะ🇱ะะ🇮ะะ🇰ะะ🇭ะ ะ🇷ะะ🇳ะะ🇩ะะ🇾ะะ🇰ะะ🇪ะ ะ🇧ะะ🇪ะะ🇯ะ",
        "ะ🇴ะะ🇷ะ ะ🇧ะะ🇩ะะ🇦ะ ะ🇱ะะ🇮ะะ🇰ะะ🇭ะ",
        "ะ🇴ะะ🇷ะ ะ🇧ะะ🇩ะะ🇦ะ",
        "ะ🇴ะะ🇷ะ ะ🇧ะะ🇩ะะ🇦ะ ะ🇴ะะ🇾ะะ🇪ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇰ะะ🇦ะ ะ🇧ะะ🇺ะะ🇷ะ",
        "ะ🇴ะะ🇾ะะ🇪ะ ะ🇰ะะ🇪ะะ🇩ะะ🇪ะ",
        "ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะ ะ🇰ะะ🇪ะ ะ🇱ะะ🇦ะะ🇩ะะ🇰ะะ🇪ะ",
        "ะ🇯ะะ🇦ะะ🇱ะะ🇩ะะ🇮ะ ะ🇱ะะ🇮ะะ🇰ะะ🇭ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะะ🇳ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇺ะ",
        "ะ🇲ะะ🇰ะะ🇱ะ ะ??ะะ🇹ะะ🇭ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇨ะะ🇨ะะ🇭ะะ🇪ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇳ะะ🇦ะะ🇳ะะ🇮ะ ะ🇲ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇱ะ",
        "ะ🇹ะะ🇪ะะ🇯ะ ะ🇱ะะ🇮ะะ🇰ะะ🇭ะ ะ🇷ะะ🇳ะะ🇩ะะ🇨ะะ🇪ะ",
        "ะ🇴ะะ🇾ะะ🇪ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇪ะ ะ🇱ะะ🇴ะะ🇩ะะ🇪ะ ะ🇲ะะ🇷ะะ🇪ะะ🇳ะะ🇬ะะ🇦ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇾ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇮ะะ🇾ะะ🇦ะ ะ🇰ะะ🇮ะ ะ🇬ะะ🇦ะะ🇳ะะ🇩ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇩ะะ🇦ะะ🇩ะะ🇮ะ ะ🇰ะะ🇦ะ ะ🇫ะะ🇺ะะ🇩ะะ🇩ะะ🇦ะ",
        "ะ🇲ะะ🇰ะะ🇱ะ ะ🇺ะะ🇹ะะ🇭ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะะ🇳ะะ🇨ะะ🇴ะะ🇩ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ??ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇰ะะ🇮ะ ะ🇧ะะ🇺ะะ🇷ะ ะ🇩ะะ🇪ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇰ะะ🇦ะ ะ🇫ะะ🇺ะะ🇩ะะ🇩ะะ🇦ะ ะ🇲ะะ🇪ะ ะ🇱ะะ🇦ะะ🇺ะะ🇩ะะ🇦ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇨ะะ🇭ะะ🇺ะะ🇩ะะ🇻ะะ🇦ะ",
        "ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇪ะะ🇹ะะ🇪ะ ะ🇲ะะ🇦ะะ🇷ะ ะ🇬ะะ🇦ะะ🇾ะะ🇦ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะ ะ🇲ะะ🇷ะะ🇺ะ",
        "ะ🇯ะะ🇦ะะ🇱ะะ🇮ะะ🇩ะ ะ🇰ะะ🇷ะ ะ🇸ะะ🇵ะะ🇦ะะ🇲ะ",
        "ะ🇲ะะ🇨ะ ะ🇸ะะ🇵ะะ🇦ะะ🇲ะ ะ🇷ะะ🇴ะะ🇰ะะ🇪ะะ🇳ะะ🇬ะะ🇦ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะ ะ🇸ะะ🇵ะะ🇦ะะ🇲ะ ะ🇰ะะ🇷ะ",
        "ะ🇸ะะ🇵ะะ🇦ะะ🇲ะ ะ🇰ะะ🇷ะ.ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇪ะ ะ🇱ะะ🇴ะะ🇩ะะ🇪ะ",
        "ะ🇷ะะ🇳ะะ🇮ะะ🇩ะ ะ🇰ะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇪ะ ะ🇸ะะ🇵ะะ🇦ะะ🇲ะ ะ🇰ะะ🇷ะ",
        "ะ🇸ะะ🇵ะะ🇦ะะ🇲ะ ะ🇰ะะ🇷ะ ะ🇰ะะ🇮ะะ🇩ะ",
        "ะ🇳ะะ🇴ะะ🇴ะะ🇧ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇺ะ",
        "ะ🇷ะะ🇳ะะ🇩ะะ🇮ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇪ะะ🇹ะะ🇪ะ",
        "ะ🇳ะะ🇴ะะ🇴ะะ🇧ะ ะ??ะะ🇦ะะ🇱ะะ🇩ะะ🇮ะ ะ🇱ะะ🇮ะะ🇰ะะ🇭ะ ะ🇼ะะ🇷ะะ🇳ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะ",
        "ะ🇨ะะ🇺ะะ🇩ะ ะ🇬ะะ🇦ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇳ะะ🇴ะะ🇴ะะ🇧ะ",
        "ะ🇺ะะ🇹ะะ🇭ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇾ะะ🇰ะะ🇪ะ ะ🇳ะะ🇴ะะ🇴ะะ🇧ะ",
        "ะ🇨ะะ🇭ะะ🇱ะ ะ🇨ะะ🇺ะะ🇩ะะ🇰ะะ🇪ะ ะ🇩ะะ🇮ะะ🇰ะะ🇭ะะ🇦ะ ะ🇳ะะ🇴ะะ🇴ะะ🇧ะ",
        "ะ🇯ะะ🇱ะะ🇩ะะ🇮ะ ะ🇹ะะ🇾ะะ🇵ะ ะ🇨ะะ🇷ะ ะ🇳ะะ🇴ะะ🇴ะะ🇧ะ ะ🇭ะะ🇦ะะ🇱ะะ🇰ะะ🇪ะ",
        "ะ🇨ะะ🇺ะะ🇩ะ ะ🇰ะะ🇪ะ ะ🇵ะะ🇬ะะ🇱ะ ะ🇳ะะ🇾ะ ะ🇭ะะ🇴ะ ะ🇳ะะ🇴ะะ🇴ะะ🇧ะ",
        "ะ🇨ะะ🇺ะะ🇩ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇰ะะ🇪ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะ ะ🇧ะะ🇳ะะ🇯ะะ🇦ะ ะ🇹ะะ🇺ะ ะ🇳ะะ🇴ะะ🇴ะะ🇧ะ",
        "ะ🇲ะะ🇦ะะ🇰ะะ🇮ะะ🇨ะะ🇭ะะ🇺ะะ🇹ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇳ะะ🇴ะะ🇴ะะ🇧ะ",
        "ะ🇬ะะ🇦ะะ🇳ะะ🇩ะะ🇦ะ ะ🇨ะะ🇾ะะ🇺ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇷ะะ🇭ะะ🇦ะ ะ🇹ะะ🇺ะ ?",
        "ะ🇮ะะ🇹ะะ🇳ะะ🇦ะ ะ🇬ะะ🇳ะะ🇩ะะ🇦ะ ะ🇳ะะ🇾ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇦ะะ🇨ะะ🇭ะะ🇪ะ ะ🇸ะะ🇪ะ ะ🇨ะะ🇺ะะ🇩ะ",
        "ะ🇲ะะ🇦ะะ🇦ะ⍟ ะ🇱ะะ🇪ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇬ะะ🇾ะะ🇦ะ ะ🇹ะะ🇺ะ ะ🇸ะะ🇺ะ⍟ ะ🇧ะะ🇦ะะ🇹ะ ะ🇦ะะ🇧",
        "ะ🇲ะะ🇦ะะ🇰ะะ🇦ะะ🇫ะะ🇺ะะ🇩ะะ🇩ะะ🇦ะ ะ🇫ะะ🇦ะะ🇹ะ ะ🇬ะะ🇾ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇷ะะ🇺ะะ🇰ะ",
        "ะ🇸ะะ🇭ะะ🇦ะะ🇳ะะ🇹ะ ะ🇧ะะ🇪ะะ🇹ะะ🇭ะ ะ🇲ะะ🇦ะะ🇩ะะ🇷ะะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇼ะะ🇷ะะ🇳ะะ🇦ะ ะ🇲ะะ🇦ะะ🇰ะะ🇦ะะ🇧ะะ🇴ะะ🇸ะะ🇩ะะ🇦ะ ะ🇹ะะ🇪ะะ🇪ะะ🇾ะ.",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะ..",
        "ะ🇱ะะ🇼ะะ🇩ะะ🇪ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇦ะะ🇦ะะ🇱ะะ🇱ะะ🇱ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇨ะะ🇺ะะ🇩ะะ🇰ะะ🇪ะ ะ🇵ะะ🇬ะะ🇱ะ ะ🇩ะะ🇪ะะ🇰ะะ🇭ะ.",
        "ะ🇲ะะ🇦ะะ🇨ะะ🇭ะะ🇦ะะ🇷ะ ะ🇰ะะ🇮ะ ะ🇯ะะ🇭ะะ🇦ะะ🇦ะะ🇹ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇦ะะ🇱ะะ🇱ะะ🇱ะะ🇱ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇦ะะ🇨ะะ🇭ะะ🇪ะ ะ🇸ะะ🇪ะ ะ🇾ะะ🇭ะะ🇦ะะ🇵ะะ🇪ะ ะ🇹ะะ🇺ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะ ะ🇲ะ ะ🇩ะะ🇺ะ ะ🇹ะะ🇦ะะ🇵ะะ🇦ะ ะ🇹ะะ🇦ะะ🇵ะ?",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇦ะ ะ🇧ะะ🇭ะะ🇴ะꜱะะ🇩ะะ🇦ะะ??ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇭ะะ🇳ะ ꜱะ🇧ะꜱะ🇧ะะ🇪ะ ะ🇧ะะ🇩ะะ🇮ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะ.",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇴ะꜱะꜱะะ🇪ะ ะ🇧ะะ🇦ะะ🇩ะะ🇮ะ ะ??ะะ🇦ะะ🇳ะะ🇩ะะ🇩ะะ🇩ะะ🇩ะะ🇩ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇦ะ ะ🇧ะะ🇦ะะ🇦ะะ🇵ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะะ🇧ะะ🇦ะะ🇦ะะ🇿ะ ะ🇪ะะ🇾ะ ะ🇩ะะ🇪ะะ🇰ะะ🇭ะ",
        "ะ🇰ะะ🇮ะะ🇹ะะ🇳ะะ🇮ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇺ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇦ะะ🇧ะ ะ🇴ะะ🇷..",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇩ะะ🇮ะ ะ🇭ะะ🇲ะ ะ🇳ะะ🇪ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇪ะ ꜱะ🇹ะะ🇭ะ ะ🇷ะะ🇪ะะ🇪ะะ🇱ะꜱะ ะ🇧ะะ🇳ะะ🇪ะะ🇬ะะ🇦ะ ะ🇷ะะ🇴ะะ🇦ะะ🇩ะ ะ🇵ะะ🇪ะะ🇪ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะ ะ🇪ะะ🇰ะ ะ🇩ะะ🇦ะะ🇲ะ ะ🇹ะะ🇴ะะ🇵ะ ꜱะ🇪ะxะ🇾ะ",
        "ะ🇲ะะ🇦ะะ🇱ะะ🇺ะ🇲ะ ะ🇳ะะ🇦ะ ะ🇵ะะ🇭ะ🇷ะ ะ🇰ะะ🇪ꜱะะ🇪ะ ะ🇱ะะ🇪ะะ🇹ะะ🇦ะ ะ🇭ะะ🇺ะ ะ🇲ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะ ะ🇹ะะ🇦ะะ🇵ะะ🇦ะ ะ🇹ะะ🇦ะะ🇵ะะ🇵ะะ🇵ะะ🇵ะะ🇵ะ",
        "ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇰ะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇪ะ ะ🇹ะะ🇺ะ ะ🇰ะะ🇪ะะ🇷ะะ🇪ะะ🇬ะะ🇦ะ ะ🇹ะะ🇾ะะ🇵ะะ🇮ะะ🇳ะะ🇬ะ ะ🇰ะะ🇷ะะ🇪ะะ🇬ะะ🇦ะ ะ🇹ะะ🇲ะะ🇰ะะ🇨ะ",
        "ꜱะ🇵ะะ🇪ะะ🇪ะะ🇩ะ ะ🇵ะะ🇰ะะ🇩ะ ะ🇱ะะ🇼ะะ🇩ะะ🇪ะะ🇪ะะ🇪ะะ🇪ะ ะ🇼ะะ🇷ะะ🇳ะะ🇦ะ ะ🇲ะะ🇪ะะ🇷ะะ🇦ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇵ะะ🇰ะะ🇩ะ",
        "ะ🇧ะะ🇦ะะ🇦ะะ🇵ะ ะ🇰ะะ🇮ะ ꜱะ🇵ะะ🇪ะะ🇪ะะ🇩ะ ะ🇲ะะ🇹ะะ🇨ะะ🇭ะ ะ🇰ะะ🇷ะะ🇷ะะ🇷ะ",
        "ะ🇱ะะ🇼ะะ🇩ะะ🇦ะ ะ🇱ะะ🇪ะ ะ🇲ะะ🇪ะะ🇷ะะ🇦ะ ะ🇯ะะ🇦ะะ🇱ะะ🇩ะะ🇮ะ ะ🇸ะะ🇪ะ ะ🇹ะะ🇺ะ",
        "ะ🇵ะะ🇦ะะ🇵ะะ🇦ะ ะ🇰ะะ🇮ะ ꜱะ🇵ะะ🇪ะะ🇪ะะ🇩ะ ะ🇲ะะ🇹ะะ🇨ะะ🇭ะ ะ🇳ะะ🇭ะะ🇮ะ ะ🇭ะะ🇴ะ ะ🇷ะะ🇭ะะ🇮ะ ะ🇰ะะ🇾ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇪ะะ🇸ะะ🇪ะ",
        "ะ🇦ะะ🇱ะะ🇪ะ ะ🇦ะะ🇱ะะ🇪ะ ะ🇲ะะ🇪ะะ🇱ะะ🇦ะ ะ🇧ะะ🇨ะะ🇭ะะ🇦ะะ🇦ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇲ะะ🇦ะะ🇰ะะ🇦ะ ะ🇧ะะ🇴ะะ🇸ะะ🇩ะะ🇦ะ ะ🇸ะะ🇺ะะ🇳ะ",
        "ะ🇨ะะ🇭ะะ🇺ะะ🇩ะ ะ🇬ะะ🇾ะะ🇦ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะะ🇧ะะ🇦ะะ🇦ะะ🇿ะ ะ🇵ะะ🇦ะะ🇵ะะ🇦ะ ꜱะ🇪ะะ🇪ะะ🇪ะ ะ🇹ะะ🇺ะ",
        "ะ🇲ะะ🇪ะะ🇳ะะ🇺ะ ะ🇰ะะ🇮ะ ะ🇵ะะ🇹ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇲ะะ🇦ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇬ะะ🇦ะะ🇮ะ",
        "ะ🇰ะะ🇴ะะ🇮ะ ะ🇧ะะ🇦ะะ🇦ะะ🇹ะ ะ🇳ะะ🇾ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇾ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ",
        "ะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇦ะะ🇦ะะ🇦ะะ🇦ะ ะ🇲ะะ🇦ะะ🇰ะะ🇦ะะ🇧ะะ🇴ะะ🇸ะะ🇩ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ",
        "ะ🇽ะะ🇭ะะ🇺ะะ🇩ะ ะ🇬ะะ🇦ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇰ะะ🇮ะะ🇩ะꜱะꜱะꜱะꜱะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇨ะะ🇭ะะ🇺ะะ🇩ะ ะ🇬ะะ🇾ะะ🇮ะ ะ🇦ะะ🇧ะ ꜰะ🇷ะะ🇦ะ🇷ะ ะ🇲ะะ🇹ะ ะ🇭ะะ🇴ะะ🇳ะะ🇦ะ",
        "ะ🇾ะะ🇪ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇱ะะ🇪ะ ะ🇲ะะ🇪ะะ🇷ะะ🇦ะ ะ🇨ะะ🇭ะะ🇱ะ ะ🇯ะะ🇦ะะ🇱ะะ🇩ะะ🇮ะ ะ🇸ะะ🇪ะ",
        "ะ🇰ะะ🇮ะะ🇩ะꜱะꜱะꜱะ ꜰะ🇷ะะ🇦ะ🇷ะ ะ🇳ะะ🇦ะ ะ🇭ะะ🇴ะ ะ🇹ะะ🇺ะ ะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇭ะะ🇭ะ",
        "ะ🇧ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇪ะ ะ🇱ะะ🇼ะะ🇩ะะ🇪ะ ꜱะ🇭ะ🇷ะ🇲ะ ะ🇰ะะ🇷ะ",
        "ะ🇰ะะ🇮ะะ🇹ะะ🇳ะะ🇮ะ ะ🇬ะะ🇱ะะ🇮ะะ🇾ะะ🇦ะ ะ🇵ะะ🇩ะะ🇼ะะ🇪ะะ🇬ะะ🇦ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇴ะ",
        "ะ🇨ะะ🇭ะะ🇺ะะ🇵ะ ะ🇳ะะ🇦ะะ🇱ะะ🇱ะะ🇮ะะ🇮ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇾ะะ🇰ะะ🇪ะ ะ🇱ะะ🇦ะะ🇩ะะ🇰ะะ🇪ะ",
        "ꜱะ🇺ะะ🇦ะ🇷ะ ะ🇰ะะ🇪ะ ะ🇵ะะ🇮ะะ🇱ะะ🇱ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ꜱะ🇦ะะ🇩ะะ🇦ะ🇰ะ ะ🇵ะ🇷ะ ะ🇱ะะ🇮ะะ🇹ะะ🇦ะะ🇰ะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ 😂😆🤤",
        "ะ🇦ะะ🇧ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇦ะ ะ🇧ะะ🇭ะะ🇴ꜱะะ🇩ะะ🇦ะ ะ🇲ะะ🇦ะะ🇩ะะ🇪ะ🇷ะะ🇨ะะ🇭ะะ🇴ะะ🇴ะะ🇩ะ ะ🇰ะ🇷ะ ะ🇵ะะ🇮ะะ🇱ะะ🇱ะะ🇪ะ ะ🇵ะะ🇦ะะ🇵ะะ🇦ะ ꜱะ🇪ะ ะ🇱ะะ🇦ะะ🇩ะะ🇪ะะ🇬ะะ🇦ะ ะ🇹ะะ🇺ะ 😼😂🤤",
        "ะ🇬ะะ🇦ะะ🇱ะะ🇮ะ ะ🇬ะะ🇦ะะ🇱ะะ🇮ะ ะ🇳ะะ🇪ะ ꜱะ🇭ะ🇴ะ🇷ะ ะ🇭ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะ ะ🇨ะะ🇭ะะ🇴ะ🇷ะ ะ🇭ะะ🇪ะ 💋💋💦",
        "ะ🇦ะะ🇧ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇺ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะะ🇰ะะ🇪ะ ะ🇵ะะ🇮ะะ🇱ะะ🇱ะะ🇪ะ ะ🇰ะะ🇺ะะ🇹ะะ🇹ะะ🇪ะ ะ🇰ะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇪ะ 😂👻🔥",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇦ะะ🇮ꜱะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇦ะ ะ🇦ะะ🇮ꜱะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇦ะ ะ🇧ะะ🇪ะะ🇩ะ ะ🇵ะะ🇪ะะ🇭ะะ🇮ะ ะ🇲ะะ🇺ะะ🇹ะะ🇭ะ ะ🇩ะะ🇮ะะ🇦ะ 💦💦💦💦",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇭ะะ🇴ꜱะะ🇩ะะ🇪ะ ะ🇲ะะ🇪ะ ะ🇦ะะ🇦ะะ🇦ะ🇬ะ ะ🇱ะะ🇦ะะ🇬ะะ🇦ะะ🇩ะะ🇮ะะ🇦ะ ะ🇲ะะ🇪ะะ🇷ะะ🇦ะ ะ🇲ะะ🇴ะะ🇹ะะ🇦ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇩ะะ🇦ะะ🇱ะะ🇰ะะ🇪ะ 🔥🔥💦😆😆",
        "ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇨ะะ🇭ะะ🇭ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇺ะ ะ🇨ะะ🇭ะะ🇦ะะ🇱ะ ะ🇳ะะ🇮ะะ🇰ะะ🇦ะะ🇱ะ",
        "ะ🇰ะะ🇮ะะ🇹ะะ🇳ะะ🇦ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇺ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะะ🇭ะ ะ🇦ะะ🇧ะะ🇧ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇴ะ ะ🇧ะะ🇭ะะ🇪ะะ🇯ะ 😆👻🤤",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇴ะะ🇹ะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇰ะะ🇪ะ ะ🇵ะะ🇺ะะ🇷ะะ🇦ะ ꜰะ🇦ะะ🇦ะะ🇩ะ ะ🇩ะะ🇮ะะ🇦ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะะ🇭ะ ะ🇦ะะ🇧ะะ🇧ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇬ะꜰะ ะ🇰ะะ🇴ะ ะ🇧ะะ🇭ะะ🇪ะะ🇯ะ 😆💦🤤",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇬ะꜰะ ะ🇰ะะ🇴ะ ะ🇪ะะ🇹ะะ🇳ะะ🇦ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇦ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇪ะ ะ🇱ะะ🇴ะะ🇩ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇬ะꜰะ ะ🇹ะะ🇴ะ ะ🇲ะะ🇪ะะ🇷ะะ🇮ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะ ะ🇧ะะ🇦ะะ🇳ะะ🇬ะะ🇦ะะ🇾ะะ🇮ะ ะ🇦ะะ🇧ะะ🇧ะ ะ🇨ะะ🇭ะะ🇦ะะ🇱ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇹ะะ🇦ะ ꜰะ🇮ะ🇷ꜱะะ🇪ะ ♥️💦😆😆😆😆",
        "ะ🇭ะะ🇦ะะ🇷ะะ🇮ะ ะ🇭ะะ🇦ะะ🇷ะะ🇮ะ ะ🇬ะะ🇭ะะ🇦ะะ🇦ꜱะ ะ🇲ะะ🇪ะ ะ🇯ะะ🇭ะะ🇴ะะ🇵ะะ🇩ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇦ะ ะ🇧ะะ🇭ะะ🇴ꜱะะ🇩ะะ🇦ะ 🤣🤣💋💦",
        "ะ🇨ะะ🇭ะะ🇦ะะ🇱ะ ะ🇹ะะ🇪ะะ🇷ะะ🇪ะ ะ🇧ะะ🇦ะะ🇦ะะ🇵ะ ะ🇰ะะ🇴ะ ะ🇧ะะ🇭ะะ🇪ะะ🇯ะ ะ🇹ะะ🇪ะะ🇷ะะ🇦ะ ะ🇧ะะ🇦ꜱะะ🇰ะะ🇦ะ ะ🇳ะะ🇭ะะ🇮ะ ะ🇭ะะ🇪ะ ะ🇵ะะ🇦ะะ🇵ะะ🇦ะ ꜱะ🇪ะ ะ🇱ะะ🇦ะะ🇩ะะ🇪ะะ🇬ะะ🇦ะ ะ🇹ะะ🇺ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะะ🇭ะ ะ🇲ะะ🇪ะ ะ🇧ะะ🇴ะะ🇲ะ🇧ะ ะ🇩ะะ🇦ะะ🇱ะะ🇰ะะ🇪ะ ะ🇺ะะ🇩ะะ🇦ะ ะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇪ะ ะ🇱ะะ🇦ะะ🇼ะะ🇩ะะ🇪ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇹ะะ🇷ะะ🇦ะะ🇮ะ🇳ะ ะ🇲ะะ🇪ะ ะ🇱ะะ🇪ะะ🇯ะะ🇦ะะ🇰ะะ🇪ะ ะ🇹ะะ🇴ะะ🇵ะ ะ🇧ะะ🇪ะะ🇩ะ ะ🇵ะะ🇪ะ ะ🇱ะะ🇮ะะ🇹ะะ🇦ะะ🇰ะะ🇪ะ ะ🇨ะะ??ะะ🇴ะะ🇩ะ ะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ꜱะ🇺ะะ🇦ะ🇷ะ ะ🇰ะะ🇪ะ ะ🇵ะะ🇮ะะ🇱ะะ🇱ะะ🇪ะ 🤣🤣💋💋",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇪ะ ะ🇳ะะ🇺ะะ🇩ะะ🇪ꜱะ ะ🇬ะะ🇴ะะ🇴ะ🇬ะ🇱ะะ🇪ะ ะ🇵ะะ🇪ะ ะ🇺ะะ🇵ะะ🇱ะะ🇴ะะ🇦ะ🇩ะ ะ🇰ะะ🇦ะ🇷ะะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇪ะ ะ🇱ะะ🇦ะะ🇪ะะ🇼ะะ🇩ะะ🇪ะ 👻🔥",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇪ะ ะ🇳ะะ🇺ะะ🇩ะะ🇪ꜱะ ะ🇬ะะ🇴ะะ🇴ะ🇬ะ🇱ะะ🇪ะ ะ🇵ะะ🇪ะ ะ🇺ะะ🇵ะะ🇱ะะ🇴ะะ🇦ะ🇩ะ ะ🇰ะะ🇦ะ🇷ะะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇪ะ ะ🇱ะะ🇦ะะ🇪ะะ🇼ะะ🇩ะะ🇪ะ 👻🔥",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇰ะะ🇪ะ ะ🇻ะะ🇮ะะ🇩ะะ🇪ะ🇴ะ ะ🇧ะะ🇦ะะ🇳ะะ🇦ะะ🇰ะะ🇪ะ ะ🇽ะ🇳🇽🇽.🇨🇴🇲 ะ🇵ะะ🇪ะ ะ🇳ะะ🇪ะะ🇪ะะ🇱ะะ🇦ะ🇲ะ ะ🇰ะะ🇦ะ🇷ะะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ะ🇰ะะ🇺ะะ🇹ะะ🇹ะะ🇪ะ ะ🇰ะะ🇪ะ ะ🇵ะะ🇮ะะ🇱ะะ🇱ะะ🇪ะ 💦💋",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇩ะะ🇦ะะ🇮ะ ะ🇰ะะ🇴ะ ะ🇵ะ🇴🇷🇳🇭🇺🇧.🇨🇴🇲 ะ🇵ะะ🇪ะ ะ🇺ะะ🇵ะะ🇱ะะ🇴ะะ🇦ะ🇩ะ ะ🇰ะะ🇦ะ🇷ะะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ꜱะ🇺ะะ🇦ะ🇷ะ ะ🇰ะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇪ะ 🤣💋💦",
        "ะ🇦ะะ🇧ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇺ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇨ะะ🇭ะะ🇭ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇪ะะ🇰ะ🇴ะ ะ🇨ะะ🇭ะะ🇦ะะ🇰ะะ🇰ะ🇴ะ ꜱะะ🇪ะ ะ🇵ะะ🇮ะะ🇱ะะ🇼ะะ🇦ะะ🇻ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇨ะะ🇭ะะ🇭ะะ🇪ะ 🤣🤣",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะะ🇭ะ ꜰะะ🇦ะะ🇦ะะ🇩ะะ🇰ะะ🇪ะ ะ🇷ะะ🇦ะะ🇰ะะ🇩ะะ🇮ะะ🇦ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇪ะ ะ🇱ะะ🇴ะะ🇩ะะ🇪ะ ะ🇯ะะ🇦ะะ🇦ะ ะ🇦ะะ🇧ะะ🇧ะ ꜱะะ🇮ะะ🇱ะะ🇼ะะ🇦ะะ🇱ะะ🇪ะ 👄👄",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะะ🇭ะ ะ🇲ะะ🇪ะ ะ🇲ะะ🇪ะะ🇷ะะ🇦ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇰ะะ🇦ะะ🇦ะะ🇱ะะ🇦ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇱ะะ🇪ะะ🇹ะะ🇮ะ ะ🇲ะะ🇪ะะ🇷ะะ🇮ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇧ะะ🇦ะะ🇩ะะ🇪ะ ะ🇲ะะ🇦ꜱะะ🇹ะะ🇮ะ ꜱะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇴ะ ะ🇲ะะ🇪ะะ🇳ะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇩ะะ🇦ะะ🇱ะะ🇦ะ ะ🇧ะะ🇴ะะ🇭ะะ🇴ะะ🇹ะ ꜱะะ🇦ꜱะะ🇹ะะ🇪ะ ꜱะะ🇪ะ",
        "ะ🇧ะะ🇪ะะ🇹ะะ🇪ะ ะ🇹ะะ🇺ะ ะ🇧ะะ🇦ะะ🇦ะะ🇵ะ ꜱะะ🇪ะ ะ🇱ะะ🇪ะะ🇬ะะ🇦ะ ะ🇵ะะ🇦ะะ🇳ะะ🇬ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇦ะ ะ🇰ะะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ะ🇰ะะ🇦ะ🇷ะะ🇰ะะ🇪ะ ะ🇳ะะ🇦ะะ🇳ะะ🇬ะะ🇦ะ 💦💋",
        "ะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇭ะ ะ🇲ะะ🇪ะะ🇷ะะ🇪ะ ะ🇧ะะ🇪ะะ🇹ะะ🇪ะ ะ🇦ะะ🇬ะะ🇱ะะ🇮ะ ะ🇧ะะ🇦ะะ🇦ะ🇷ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇱ะะ🇪ะะ🇰ะะ🇪ะ ะ🇦ะะ🇦ะะ🇾ะะ🇦ะ ะ🇲ะะ🇦ะะ🇹ะะ🇭ะ ะ🇰ะะ🇦ะะ🇹ะ ะ🇴ะ🇷ะ ะ🇲ะะ🇪ะะ🇷ะะ🇪ะ ะ🇲ะะ🇴ะะ🇹ะะ🇪ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ꜱะะ🇪ะ ะ🇨ะะ🇭ะะ🇺ะะ🇩ะะ🇼ะะ🇦ะะ🇾ะะ🇦ะ ะ🇲ะะ🇦ะะ🇹ะะ🇭ะ ะ🇰ะะ🇦ะ🇷ะ",
        "ะ🇨ะะ🇭ะะ🇦ะะ🇱ะ ะ🇧ะะ🇪ะะ🇹ะะ🇦ะ ะ🇹ะะ🇺ะะ🇯ะะ🇭ะะ🇪ะ ะ🇲ะะ🇦ะะ🇦ꜱะ🇫ะ ะ🇰ะะ🇮ะะ🇦ะ 🤣ะ🇹ะะ🇺ะ ะ🇦ะะ🇧ะะ🇧ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇲ะะ🇦ะะ🇰ะ🇴ะ ะ🇧ะะ🇭ะะ🇪ะะ🇯ะ",
        "ꜱะ🇭ะะ🇦ะะ🇷ะะ🇦ะ🇲ะ ะ🇰ะะ🇦ะ🇷ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇦ะ ะ🇧ะะ🇭ะะ🇴ꜱะะ🇩ะะ🇦ะ ะ🇰ะะ🇮ะะ🇹ะะ🇳ะะ🇦ะ ะ🇬ะะ🇦ะะ🇦ะะ🇱ะะ🇮ะะ🇦ะ ꜱะ🇺ะะ🇳ะะ🇼ะะ🇦ะะ🇾ะะ🇪ะะ🇬ะะ🇦ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇦ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇪ะ ะ🇺ะะ🇵ะะ🇪ะ🇷ะ",
        "ะ🇦ะะ🇧ะะ🇪ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇨ะะ🇭ะะ🇭ะะ🇪ะ ะ🇦ะะ🇺ะะ🇰ะะ🇦ะะ🇹ะ ะ🇳ะะ🇭ะะ🇮ะ ะ🇭ะะ🇪ะะ🇹ะ🇴ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇱ะะ🇪ะะ🇰ะะ🇪ะ ะ🇦ะะ🇦ะะ🇾ะะ🇦ะ ะ🇲ะะ🇦ะะ🇹ะะ🇭ะ ะ🇰ะะ🇦ะ??ะ ะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇭ะะ🇦ะ",
        "ะ🇰ะะ🇮ะะ🇩ะ🇿ะ ะ🇲ะะ🇦ะะ🇩ะะ🇦ะ🇷ะะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇰ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะ🇷ะ ะ🇱ะะ🇮ะะ🇾ะะ🇪ะ ะ🇧ะะ🇭ะะ🇦ะะ🇮ะ ะ🇩ะะ🇪ะะ🇩ะะ🇮ะะ🇾ะะ🇦ะ",
        "ะ🇯ะะ🇺ะะ🇳ะะ🇬ะ🇱ะะ🇪ะ ะ🇲ะะ🇪ะ ะ🇳ะะ🇦ะะ🇨ะะ🇭ะะ🇹ะะ🇦ะ ะ🇭ะะ🇪ะ ะ🇲ะะ🇴ะ🇷ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇩ะะ🇦ะะ🇮ะ ะ🇩ะะ🇪ะะ🇰ะะ🇰ะะ🇪ะ ꜱะ🇦ะ🇧ะ ะ🇧ะะ🇴ะะ🇱ะะ🇹ะะ🇪ะ ะ🇴ะะ🇳ะ🇨ะะ🇪ะ ะ🇲ะะ🇴ะ🇷ะะ🇪ะ ะ🇴ะะ🇳ะ🇨ะะ🇪ะ ะ🇲ะะ🇴ะ🇷ะะ🇪ะ 🤣🤣💦💋",
        "ะ🇬ะะ🇦ะะ🇱ะะ🇮ะ ะ🇬ะะ🇦ะะ🇱ะะ🇮ะ ะ🇲ะะ🇪ะ ะ🇷ะะ🇪ะะ🇭ะะ🇹ะะ🇦ะ ะ🇭ะะ🇪ะ ꜱะ🇦ะะ🇳ะะ🇩ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇩ะะ🇦ะะ🇱ะะ🇦ะ ะ🇴ะ🇷ะ ะ🇧ะะ🇦ะะ🇳ะะ🇦ะ ะ🇩ะะ🇮ะะ🇦ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะ 🤤🤣",
        "ꜱะ🇦ะ🇧ะ ะ🇧ะะ🇴ะะ🇱ะะ🇹ะะ🇪ะ ะ🇲ะะ🇺ะะ🇯ะะ🇭ะะ🇰ะ🇴ะ ะ🇵ะะ🇦ะะ🇵ะะ🇦ะ ะ🇨ะะ🇾ะะ🇺ะะ🇰ะะ🇮ะ ะ🇲ะะ🇪ะะ🇳ะะ🇪ะ ะ🇰ะ🇷ะะ??ะะ🇮ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇵ะ🇷ะะ🇪ะะ🇬ะะ🇳ะะ🇪ะะ🇳ะะ🇹ะ 🤣🤣",
        "ꜱะ🇺ะะ🇦ะ🇷ะ ะ🇰ะะ🇪ะ ะ🇵ะะ🇮ะะ🇱ะะ🇱ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะะ🇭ะ ะ🇲ะะ🇪ะ ꜱะ🇺ะะ🇦ะ🇷ะ ะ🇰ะะ🇦ะ ะ🇱ะะ🇴ะะ🇺ะะ🇩ะะ🇦ะ ะ🇴ะ🇷ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะะ🇭ะ ะ🇲ะะ🇪ะ ะ🇲ะะ🇪ะะ🇷ะะ🇦ะ ะ🇱ะะ🇴ะะ🇩ะะ🇦ะ",
        "ะ🇨ะะ🇭ะะ🇦ะะ🇱ะ ะ🇨ะะ🇭ะะ🇦ะะ🇱ะ ะ🇹ะะ🇺ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇨ะะ🇭ะะ🇮ะะ🇾ะะ🇦ะ ะ🇩ะะ🇮ะะ🇰ะะ🇦ะ",
        "ะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇭ะะ🇦ะ ะ🇧ะะ🇦ะะ🇨ะะ🇭ะะ🇭ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇩ะะ🇮ะะ🇦ะ ะ🇳ะะ🇦ะะ🇳ะะ🇬ะะ🇦ะ ะ🇰ะะ🇦ะ🇷ะะ🇰ะะ🇪ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇬ะꜰะ ะ🇭ะะ🇪ะ ะ🇧ะะ🇦ะะ🇩ะะ🇮ะ ꜱะ🇪xะ🇾ะ ะ🇺ꜱะะ🇰ะ??ะ ะ🇵ะะ🇮ะะ🇱ะะ🇦ะะ🇰ะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇴ะะ🇩ะะ🇪ะะ🇳ะะ🇬ะะ🇪ะ ะ🇵ะะ🇪ะะ🇵ꜱะะ🇮ะ",
        "2 ะ🇷ะะ🇺ะะ🇵ะะ🇦ะ🇾ะ ะ🇰ะะ🇮ะ ะ🇵ะะ🇪ะะ🇵ꜱะะ🇮ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇺ะะ🇲ะะ🇲ะะ🇾ะ ꜱะ🇦ะ🇧ꜱะะ🇪ะ ꜱะ🇪xะ🇾ะ 💋💦",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇨ะะ🇭ะะ🇪ะะ🇪ะ🇲ꜱะ ꜱะะ🇪ะ ะ🇨ะะ🇭ะะ🇺ะะ🇩ะะ🇼ะะ🇦ะะ🇻ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ะ🇲ะะ🇦ะะ🇩ะะ🇪ะ🇷ะะ🇨ะะ🇭ะะ🇴ะะ🇴ะะ🇩ะ ะ🇰ะะ🇪ะ ะ🇵ะะ🇮ะะ🇱ะะ🇱ะะ🇪ะ 💦🤣",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะะ🇭ะ ะ🇲ะะ🇪ะ ะ🇲ะะ🇺ะะ🇹ะะ🇭ะะ🇰ะะ🇪ะ ꜰะะ🇦ะ🇷ะะ🇦ะ🇷ะ ะ🇭ะะ🇴ะะ🇯ะะ🇦ะะ🇻ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ ะ🇭ะะ🇺ะะ🇮ะ ะ🇭ะะ🇺ะะ🇮ะ ะ🇭ะะ🇺ะะ🇮ะ",
        "ꜱะ🇵ะะ🇪ะะ🇪ะะ🇩ะ ะ🇱ะะ🇦ะะ🇦ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇺ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇮ะะ🇰ะะ🇪ะ ะ🇵ะะ🇮ะะ🇱ะะ🇱ะะ🇪ะ 💋💦🤣",
        "ะ🇦ะะ🇷ะะ🇪ะ ะ🇷ะะ🇪ะ ะ🇲ะะ🇪ะะ🇷ะะ🇪ะ ะ🇧ะะ🇪ะะ🇹ะะ🇪ะ ะ🇨ะะ🇾ะะ🇺ะ ꜱะ🇵ะะ🇪ะะ🇪ะะ🇩ะ ะ🇵ะะ🇦ะะ🇰ะะ🇦ะะ🇩ะ ะ🇳ะะ🇦ะ ะ🇵ะะ🇦ะะ🇦ะะ🇦ะ ะ🇷ะะ🇦ะะ🇭ะะ🇦ะ ะ🇦ะะ🇵ะะ🇳ะะ🇪ะ ะ🇧ะะ🇦ะะ🇦ะะ🇵ะ ะ🇰ะะ🇦ะ ะ🇭ะะ🇦ะะ🇭ะะ🇦ะะ🇭ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇬ะะ🇦ะะ🇮ะ🤣🤣",
        "ꜱะ🇺ะะ🇳ะ ꜱะ🇺ะะ🇳ะ ꜱะ🇺ะะ🇦ะ🇷ะ ะ🇰ะะ🇪ะ ะ🇵ะะ🇮ะะ🇱ะะ🇱ะะ🇪ะ ะ🇯ะะ🇭ะะ🇦ะะ🇳ะะ🇹ะ🇴ะ ะ🇰ะะ🇪ะ ꜱะ🇴ะะ🇺ะะ🇩ะะ🇦ะะ🇬ะะ🇦ะ🇷ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇲ะะ🇺ะะ🇲ะะ🇲ะะ🇾ะ ะ🇰ะะ🇮ะ ะ🇳ะะ🇺ะะ🇩ะะ🇪ꜱะ ะ🇧ะะ🇭ะะ🇪ะะ🇯ะ",
        "ะ🇦ะะ🇧ะะ🇪ะ ꜱะ🇺ะะ🇳ะ ะ🇱ะะ🇴ะะ🇩ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇧ะะ🇪ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇦ะ ะ🇧ะะ🇭ะะ🇴ꜱะะ🇩ะะ🇦ะ ꜰะะ🇦ะะ🇦ะะ🇩ะ ะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะะ🇦ะะ🇰ะ🇴ะ ะ🇰ะะ🇭ะะ🇺ะะ🇱ะะ🇪ะ ะ🇧ะะ🇦ะะ🇯ะะ🇦ะ🇷ะ ะ🇲ะะ🇪ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะ ะ🇩ะะ🇦ะะ🇱ะะ🇦ะ 🤣🤣💋",
        "ꜱะ🇭ะ🇷ะ🇲ะ ะ🇰ะ🇷ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇲ะะ🇦ะะ🇦ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇬ะะ🇦ะะ🇮ะ ะ🇾ะะ🇭ะะ🇦ะ",
        "ะ🇲ะะ🇪ะะ🇷ะะ🇪ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇦ะะ🇦ะะ🇦ะะ🇱ะะ🇱ะะ🇱ะะ🇱ะะ🇱ะ ะ🇵ะะ🇰ะะ🇩ะ ะ🇯ะะ🇦ะะ🇱ะะ🇩ะะ🇮ะ ะ🇸ะะ🇪ะ",
        "ะ🇹ะะ🇺ะ ะ🇪ะะ🇰ะ ะ🇰ะะ🇦ะะ🇦ะ🇲ะ ะ🇰ะ🇷ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇧ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇴ะ ะ🇨ะะ🇺ะะ🇩ะะ🇼ะะ🇦ะ ะ🇱ะะ🇪ะ ะ🇲ะะ🇪ะะ🇷ะะ🇪ะ ะ🇸ะะ🇹ะะ🇭ะ",
        "ะ🇷ะะ🇳ะะ🇩ะะ🇮ะ ะ🇰ะะ🇪ะ ะ🇱ะะ🇩ะะ🇰ะะ🇪ะะ🇪ะะ🇪ะะ🇪ะะ🇪ะะ🇪ะะ🇪ะะ🇪ะ ะ🇨ะะ🇭ะะ🇺ะะ🇵ะ ะ🇴ะ🇷ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇾ะะ🇭ะะ🇦ะ",
        "ะ🇨ะะ🇭ะะ🇺ะะ🇵ะ ะ🇹ะะ🇲ะะ🇰ะะ🇨ะ ะ🇰ะะ🇮ะะ🇩ꜱะꜱะꜱะꜱะꜱะꜱะꜱะꜱะꜱะꜱะꜱะꜱะ",
        "ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇬ะะ🇦ะะ🇦ะะ🇳ะะ🇩ะ ะ🇲ะะ🇪ะะ??ะ🇳ะ ะ🇲ะะ🇺ะะ🇹ะะ🇭ะะ🇮ะ ะ🇩ะะ🇦ะะ🇦ะะ🇱ะ",
        "ะ🇲ะะ🇪ะะ🇷ะะ🇦ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇨ะะ🇭ะะ🇴ะะ🇴ꜱะ ะ🇯ะะ🇦ะะ🇱ะะ🇩ะะ🇮ะ ะ🇸ะะ🇪ะ",
        "ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇴ะ ะ🇨ะะ🇺ꜱะะ🇼ะะ🇦ะ ะ🇲ะะ🇪ะะ🇷ะะ🇦ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ",
        "ะ🇧ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇪ะ ะ🇱ะะ🇦ะะ🇺ะะ🇩ะะ🇪ะ ะ🇹ะะ🇲ะะ🇨ะ",
        "ะ🇧ะะ🇭ะะ🇪ะ🇳ะ ะ🇰ะะ🇪ะ ะ🇹ะะ🇦ะะ🇰ะะ🇰ะะ🇪ะ ะ🇹ะะ🇲ะะ🇱ะ",
        "ะ🇦ะะ🇧ะะ🇱ะะ🇦ะ ะ🇹ะะ🇪ะะ🇷ะะ🇦ะ ะ🇰ะะ🇭ะะ🇦ะ🇳ะ ะ🇩ะะ🇦ะ🇳ะ ะ🇨ะะ🇭ะะ🇴ะะ🇩ะะ🇳ะะ🇪ะ ะ🇰ะะ🇮ะ ะ🇧ะะ🇦ะ🇷ะะ🇮ะะ🇮ะ",
        "ะ🇧ะะ🇪ะะ🇹ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ꜱะ🇧ꜱะะ🇪ะ ะ🇧ะะ🇩ะะ🇮ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะ",
        "ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇦ะะ🇦ะะ🇱ะ ะ🇯ะะ🇭ะะ🇦ะะ🇹ะ ะ??ะะ🇪ะ ะ🇵ะะ🇮ꜱะꜱะꜱะ🇺ะะ🇺ะะ🇺ะะ🇺ะะ🇺ะะ🇺ะะ🇺ะ ะ🇹ะะ🇲ะะ🇰ะะ🇨ะ",
        "ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇵ะะ🇪ะ ะ🇱ะะ🇹ะะ🇰ะะ🇮ะะ🇹ะ ะ🇲ะะ🇦ะะ🇦ะะ🇦ะะ🇱ะะ🇱ะะ🇱ะะ🇱ะ ะ🇰ะะ🇮ะ ะ🇧ะะ🇴ะะ🇳ะะ🇩ะ ะ🇭ะ ะ🇹ะะ🇺ะะ🇺ะะ🇺ะ",
        "ะ🇰ะะ🇦ꜱะะ🇭ะ ะ🇴ꜱะ ะ🇩ะะ🇮ะ🇳ะ ะ🇲ะะ🇺ะะ🇹ะะ🇭ะ ะ🇲ะ🇷ะะ🇰ะะ🇪ะ ꜱะ🇴ะะ🇯ะะ🇹ะะ🇦ะ ะ🇲ะ ะ🇹ะะ🇺ะ ะ🇵ะะ🇦ะะ🇮ะะ🇩ะะ🇦ะ ะ🇳ะะ🇦ะ ะ🇭ะะ🇴ะะ🇹ะะ🇦ะะ🇦ะ",
        "ะ🇬ะะ🇱ะะ🇹ะะ🇮ะ ะ🇰ะ🇷ะะ🇩ะะ🇮ะ ะ🇹ะะ🇺ะะ🇯ะะ🇼ะ ะ🇵ะะ🇦ะะ🇮ะะ🇩ะะ🇦ะ ะ🇰ะ🇷ะะ🇰ะะ🇪ะ ะ🇹ะะ🇪ะะ🇷ะะ🇾ะ ะ🇲ะะ🇦ะ ะ🇳ะะ🇪ะ ะ🇦ะะ🇧ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇹ะะ🇺ะ ะ🇾ะะ🇭ะะ🇦ะ",
        "ꜱะ🇵ะะ🇪ะะ🇪ะะ🇩ะ ะ🇵ะะ🇰ะะ🇩ะะ🇩ะะ??ะ",
        "ะ🇬ะะ🇦ะะ🇦ะะ🇳ะะ🇩ะ ะ🇲ะะ🇦ะะ🇮ะ🇳ะ ะ🇱ะะ🇼ะะ🇩ะะ🇦ะ ะ🇩ะะ🇦ะะ🇱ะ ะ🇱ะะ🇪ะ ะ🇦ะะ🇵ะะ🇳ะะ🇮ะ ะ🇲ะะ🇪ะะ🇷ะะ🇦ะะ🇦ะะ🇦ะ",
        "ะ🇬ะะ🇦ะะ🇦ะะ🇳ะะ🇩ะ ะ🇲ะะ🇪ะะ🇮ะ🇳ะ ะ🇧ะะ🇦ะะ🇲ะะ🇧ะ🇺ะ ะ🇩ะะ🇪ะะ🇩ะะ🇺ะะ🇳ะะ🇬ะะ🇦ะะ🇦ะะ🇦ะะ🇦ะะ🇦ะะ🇦ะ",
        "ะ🇬ะะ🇦ะะ🇳ะะ🇩ะ ꜰะะ🇹ะะ🇮ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇱ะะ🇰ะะ🇰ะะ🇰ะ ะ🇹ะะ🇺ะ ะ🇨ะะ🇺ะะ🇩ะ ะ🇾ะะ🇭ะะ🇦ะ",
        "ะ🇬ะะ🇴ะะ🇹ะะ🇪ะ ะ🇰ะะ🇮ะะ🇹ะะ🇳ะะ🇪ะ ะ🇧ะะ🇭ะะ🇮ะ ะ🇧ะะ🇦ะะ🇩ะะ🇪ะ ะ🇭ะะ🇴ะ, ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇰ะะ🇪ะ ะ🇳ะะ🇮ะะ🇨ะะ🇭ะะ🇪ะ ะ🇭ะะ🇮ะ ะ🇷ะะ🇪ะะ🇭ะะ🇹ะะ🇪ะ ะ🇭ะะ🇦ะ",
        "ะ🇭ะะ🇦ะะ🇿ะะ🇦ะะ🇦ะ🇷ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇬ะะ🇦ะะ🇦ะะ🇳ะะ🇩ะ ะ🇲ะะ🇦ะะ🇮ะ🇳ะ",
        "ะ🇯ะะ🇭ะะ🇦ะะ🇦ะะ🇳ะะ🇹ะ ะ🇰ะะ🇪ะ ะ🇵ะะ🇮ꜱะꜱะ🇺ะ ะ🇹ะะ🇲ะะ🇰ะะ🇨ะ ะ🇸ะะ🇺ะะ🇳ะ",
        "ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇮ะ ะ🇰ะะ🇦ะะ🇱ะะ🇮ะ ะ🇨ะะ🇭ะะ🇺ะะ🇹ะ",
        "ะ🇰ะะ🇭ะะ🇴ะะ🇹ะะ🇪ะ🇾ะ ะ🇰ะะ🇮ะ ะ🇦ะะ🇺ะะ🇱ะะ🇩ะะ🇦ะ ะ🇪ะะ🇾ะ ะ🇹ะะ🇺ะ ะ🇷ะะ🇦ะะ🇳ะะ🇩ะะ🇾ะะ🇰ะะ🇪ะ",
        "ะ🇰ะะ🇺ะะ🇹ะะ🇹ะะ🇪ะ ะ🇰ะะ🇦ะ ะ🇦ะะ🇼ะะ🇱ะะ🇦ะะ🇹ะ ะ🇯ะะ🇦ะะ🇮ะꜱะะ🇦ะ ะ🇱ะะ🇬ะ ะ🇷ะะ🇭ะะ🇦ะ ะ🇹ะะ🇺ะ",
        "ะ🇰ะะ🇺ะะ🇹ะะ🇹ะะ🇪ะ ะ🇰ะะ🇮ะ ะ🇯ะะ🇦ะะ🇹ะ ะ🇯ะะ🇦ะะ🇮ꜱะะ🇦ะ ะ🇪ะะ🇾ะ ะ🇹ะะ🇺ะ ",
        "ะ🇰ะะ🇺ะะ🇹ะะ🇹ะะ🇪ะ ะ🇰ะะ🇪ะ ะ🇹ะะ🇦ะะ🇹ะะ🇹ะะ🇦ะ ะ🇪ะะ🇾ะ ะ🇹ะะ🇺ะ",
        "ะ🇹ะะ🇪ะะ🇹ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇰ะะ🇮ะ.ะ🇨ะะ🇭ะะ🇺ะะ🇹ะ , ะ🇹ะะ🇪ะะ🇷ะะ🇮ะ ะ🇲ะะ🇦ะ ะ🇷ะะ🇳ะะ🇩ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะะ🇮ะ",
        "ะ🇱ะะ🇦ะะ🇻ะะ🇩ะะ🇪ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇱ะ ะ🇵ะะ🇰ะะ🇩ะ ะ🇱ะะ🇪ะ ะ🇲ะะ🇪ะะ🇷ะะ🇪ะ",
        "ะ🇲ะะ🇺ะะ🇭ะ ะ🇲ะะ🇪ะะ🇮ะ ะ🇱ะะ🇪ะะ🇱ะะ🇪ะ ะ🇲ะะ🇪ะะ🇷ะะ🇦ะ ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ",
        "ะ🇱ะะ🇺ะะ🇳ะะ🇩ะ ะ🇰ะะ🇪ะ ะ🇵ะะ🇦ꜱะะ🇮ะะ🇳ะะ🇪ะ ะ🇨ะะ🇭ะะ🇺ะะ🇵ะ ะ🇧ะะ🇪ะะ🇹ะะ🇭ะ ะ🇴ะ🇷ะ ะ🇨ะะ🇺ะะ🇩ะ",
        "ะ🇲ะะ🇪ะะ🇷ะะ🇪ะ ะ🇱ะะ🇼ะะ🇩ะะ🇪ะ ะ🇰ะะ🇪ะ ะ🇧ะะ🇦ะะ🇦ะะ🇦ะะ🇦ะะ🇱ะะ🇱ะะ🇱ะ",
        "ะ🇭​ะะ🇦​ะะ🇭​ะะ🇦​ะะ🇭​ะะ🇦​ะะ🇦​ะะ🇦​ะะ🇦​ะะ🇦​ะะ🇦​ะ ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ ะ🇬​ะะ🇦​ะะ🇮​ะ",
        "ะ🇹​ะะ🇺​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇩​ะ ะ🇬​ะะ🇾​ะะ🇦​ะะ🇦​ะะ🇦​ะะ🇦​ะ",
        "ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะ ะ🇰​ะะ🇭​ะะ🇦​ะะ🇳​ะะ🇪​ะ ะ🇰​ะะ🇮​ะ ะ🇺​ะะ🇱​ะะ🇦​ะะ🇩​ะะ🇩​ะะ🇩​ะ",
        "ꜱ​ะ🇦​ะะ🇩​ะะ🇮​ะ ะ🇭​ะะ🇺​ะะ🇮​ะ ะ🇬​ะะ🇦​ะะ🇦​ะะ🇳​ะะ🇩​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇬​ะะ🇦​ะะ🇦​ะะ🇳​ะะ🇩​ะ ะ🇲​ะะ🇦​ะะ🇮​ะ🇳​ะ ะ🇰​ะะ🇺​ะะ🇹​ะะ🇪​ะ ะ🇰​ะะ🇦​ะ ะ🇱​ะะ🇺​ะะ🇳​ะะ🇩​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇦​ะ ะ🇧​ะะ🇭​ะะ🇴​ꜱ​ะะ🇩​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇪​ะ ะ🇬​ะะ🇦​ะะ🇦​ะะ🇳​ะะ🇩​ะ ะ🇲​ะะ🇪​ะะ🇮​ะ🇳​ะ ะ🇰​ะะ🇪​ะะ🇪​ะะ🇩​ะะ🇪​ะ ะ🇵​ะะ🇦​ะะ🇩​ะะ🇦​ะ🇾​ะ",
        "ะ🇳​ะะ🇾​ะ ะ🇳​ะะ🇾​ะ ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะ",
        "ꜱ​ะ🇺​ะะ🇳​ะะ🇳​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇪​ะ🇷​ะะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะ ะ🇹​ะะ🇲​ะะ🇱​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇦​ะ ะ🇧​ะะ🇭​ะะ🇴​ꜱ​ะะ🇩​ะะ🇦​ะ",
        "ะ🇧​ะะ🇪​ะะ🇭​ะะ🇪​ะ🇳​ะ ะ🇰​ะ ะ🇱​ะะ🇺​ะะ🇳​ะะ🇩​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇵​ะะ🇨​ะะ🇭​ะะ🇦​ะะ🇵​ะ ะ🇨​ะะ🇺​ะะ🇩​ะ ะ🇾​ะะ🇭​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇦​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇹​ะะ🇳​ะะ🇮​ะะ🇮​ะะ🇮​ะ",
        "ะ🇲​ะะ🇪​ะะ🇷​ะะ🇦​ะ ะ🇱​ะะ🇦​ะะ🇼​ะะ🇩​ะะ🇦​ะ ะ🇱​ะะ🇪​ะะ🇱​ะะ🇪​ะ ะ🇹​ะะ🇺​ะ ะ🇦​ะะ🇬​ะะ🇦​ะ🇷​ะ ะ🇨​ะะ🇭​ะะ🇦​ะะ🇮​ะะ🇾​ะะ🇪​ะ ะ🇹​ะะ🇴​ะะ🇭​ะ",
        "ะ🇨​ะะ🇭​ะะ🇺​ะะ🇵​ะ ะ🇬​ะะ🇦​ะะ🇦​ะะ🇳​ะะ🇩​ะ🇺​ะ",
        "ะ🇨​ะะ🇭​ะะ🇺​ะะ🇵​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะะ🇮​ะะ🇾​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇵​ะะ🇪​ะ ะ🇯​ะ🇨​ะ🇧​ะ ะ🇨​ะะ🇭​ะะ🇦​ะะ🇩​ะะ🇭​ะะ🇦​ะะ🇦​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ",
        "ꜱ​ะ🇦​ะะ🇲​ะะ🇯​ะะ🇭​ะะ🇦​ะะ🇦​ะ ะ🇱​ะะ🇦​ะะ🇼​ะะ🇩​ะะ🇪​ะ",
        "ะ🇾​ะะ🇦​ะ ะ🇩​ะะ🇺​ะ ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇬​ะะ🇦​ะะ🇦​ะะ🇳​ะะ🇩​ะ ะ🇲​ะะ🇪​ะ ะ🇹​ะะ🇦​ะะ🇵​ะะ🇦​ะะ🇦​ะ ะ🇹​ะะ🇦​ะะ🇵​",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇧​ะะ🇪​ะะ🇭​ะะ🇪​ะ🇳​ะ ะ🇲​ะะ🇪​ะะ🇷​ะะ🇦​ะ ะ🇷​ะะ🇴​ะะ🇿​ะ ะ🇱​ะะ🇪​ะะ🇹​ะะ🇮​ะ ะ🇭​ะะ🇦​ะะ🇮​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇪​ะ ꜱ​ะะ🇦​ะะ🇦​ะะ🇹​ะะ🇭​ะ ะ🇲​ะ🇲​ꜱ​ะ ะ🇧​ะะ🇦​ะะ🇳​ะะ🇦​ะะ🇦​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇰​ะะ🇦​ะ ะ🇭​ะะ🇺​",
        "ะ🇹​ะะ🇺​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะะ🇮​ะะ🇾​ะะ🇦​ะ ะ🇹​ะะ🇪​ะะ🇷​ะะ🇦​ะ ะ🇰​ะะ🇭​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇦​ะะ🇦​ะ🇳​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะะ🇮​ะะ🇾​ะะ🇦​ะ",
        "ะ🇦​ะะ🇺​ะ🇷​ะ ะ🇰​ะะ🇮​ะะ🇹​ะะ🇳​ะะ🇦​ะ ะ🇧​ะะ🇴​ะะ🇱​ะะ🇺​ะ ะ🇧​ะะ🇪​ะ🇾​ะ ะ🇲​ะะ🇦​ะะ🇳​ะะ🇳​ะ ะ🇧​ะะ🇭​ะะ🇦​ะ🇷​ะ ะ🇬​ะะ🇦​ะะ🇾​ะะ🇦​ะ ะ🇲​ะะ🇪​ะะ🇷​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะะ🇮​ะะ🇮​ะะ🇮​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะะ🇹​ะะ🇹​ะ ะ🇲​ะะ🇪​ะ ะ🇦​ะะ🇧​ะ🇨​ะ🇩​ะ ะ🇱​ะะ🇮​ะะ🇰​ะะ🇭​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇪​ะ ะ🇱​ะะ🇴​ะะ🇩​ะะ🇪​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇴​ะ ะ🇱​ะะ🇪​ะะ🇰​ะะ🇦​ะ🇷​ะ ะ🇲​ะะ🇦​ะะ🇮​ะ ꜰ​ะะ🇦​ะ🇷​ะะ🇦​ะ🇷​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇮​ะะ🇩​ะะ🇮​ะะ🇮​ะ",
        "ะ🇨​ะะ🇭​ะะ🇺​ะะ🇵​ะ ะ🇧​ะะ🇦​ะะ🇨​ะะ🇭​ะะ🇪​ะะ🇪​ะ ะ🇹​ะะ🇲​ะะ🇰​ะะ🇨​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ ะ🇲​ะะ🇦​ะะ??​ะ🇴​ะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะะ🇺​ะ",
        "ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇹​ะะ🇪​ะะ🇷​ะะ🇾​ะ",
        "ะ🇹​ะะ🇺​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะ ะ🇰​ะะ🇪​ะ ะ🇵​ะะ🇮​ะะ🇱​ะะ🇱​ะะ🇦​ะ ะ🇪​ะะ🇾​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะะ🇮​ะะ🇮​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇴​ะ ะ🇧​ะะ🇭​ะะ🇪​ะะ🇯​ะะ🇯​ะะ🇯​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇦​ะะ🇦​ะ ะ🇧​ะะ🇦​ะะ🇦​ะะ🇦​ะะ🇵​ะ ะ🇭​ะะ🇺​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇲​ะะ🇪​ะ ะ🇭​ะะ🇦​ะะ🇦​ะะ🇹​ะ ะ🇩​ะะ🇦​ะะ🇦​ะะ🇱​ะะ🇱​ะะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇭​ะะ🇦​ะะ🇦​ะ🇬​ะ ะ🇯​ะะ🇦​ะะ🇦​ะะ🇳​ะะ🇺​ะะ🇬​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇴​ะ ꜱ​ะะ🇦​ะ🇷​ะะ🇦​ะะ🇰​ะ ะ🇵​ะะ🇪​ะ ะ🇱​ะะ🇪​ะะ🇹​ะะ🇦​ะะ🇦​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇴​ ะ🇬​ะ🇧​ะ ะ🇷​ะ🇴​ะ🇦​ะ🇩​ะ ะ🇵​ะะ🇪​ะ ะ🇱​ะะ🇪​ะะ🇯​ะะ🇦​ะะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇪​ะ🇨​ะ🇭​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇲​É​ะ ะ🇰​ะะ🇦​ะะ🇦​ะะ🇱​ะะ🇮​ะ ะ🇲​ะะ🇮​ะะ🇹​ะ🇨​ะ🇭​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ꜱ​ะะ🇦​ꜱ​ะะ🇹​ะะ🇮​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะ ะ🇭​ะะ🇦​ะะ🇮​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇲​ะะ🇪​ะ ะ🇰​ะะ🇦​ะะ🇧​ะะ🇺​ะะ🇹​ะะ🇦​ะ🇷​ะ ะ??​ะะ🇦​ะะ🇦​ะะ🇱​ะ ะ🇰​ะะ🇪​ะ ꜱ​ะ🇴​ะะ🇺​ะะ🇵​ะ ะ🇧​ะะ🇦​ะะ🇳​ะะ🇦​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇦​ะ🇷​ะะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะะ🇦​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะ ะ🇭​ะะ🇦​ะะ🇮​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇲​ะะ🇪​ะ ะ🇩​ะะ🇪​ะะ🇹​ะ🇴​ะ🇱​ะ ะ🇩​ะะ??​ะะ🇦​ะะ🇱​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇦​ะ🇷​ะะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇦​ะะ🇦​ะ ะ🇧​ะะ🇭​ะะ🇴​ꜱ​ะะ🇩​ะะ🇦​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇲​ะะ🇪​ะ ะ🇱​ะะ🇦​ะะ🇵​ะะ🇹​ะ🇴​ะ🇵​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะ ะ🇭​ะะ🇦​ะะ🇮​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇴​ ะ🇧​ะะ🇮​ꜱ​ะะ🇹​ะะ🇦​ะ🇷​ะ ะ🇵​ะะ🇪​ะ ะ🇱​ะะ🇪​ะะ🇹​ะะ🇦​ะะ🇦​ะะ🇰​ะะ🇪​ะ ะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ??​ะะ🇴​ ะ🇦​ะะ🇲​ะะ🇪​ะ🇷​ะะ🇮​ะ🇨​ะะ🇦​ะ ะ🇬​ะะ🇭​ะะ🇺​ะะ🇲​ะะ🇦​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇦​ะ🇷​ะะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇲​ะะ🇪​ะ ะ🇳​ะะ🇦​ะะ🇦​ะ🇷​ะะ🇮​ะะ🇾​ะะ🇦​ะ🇱​ะ ะ🇵​ะะ🇭​ะ🇴​ะ🇷​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇪​ะ ะ🇬​ะะ🇦​ะะ🇳​ะะ🇩​ะ ะ🇲​ะะ🇪​ะ ะ🇩​ะะ🇪​ะะ🇹​ะ🇴​ะ🇱​ะ ะ🇩​ะะ🇦​ะะ🇦​ะะ🇱​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇴​ ะ🇭​ะ🇴​🇷​🇱​🇮​🇨​🇰​ꜱ​ะ ะ🇵​ะะ🇮​ะะ🇱​ะะ🇦​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇦​ะ🇷​ะะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇴​ ꜱ​ะะ🇦​ะ🇷​ะะ🇦​ะะ🇰​ะ ะ🇵​ะะ🇪​ะ ะ🇱​ะะ🇪​ะะ🇹​ะะ🇦​ะะ🇦​ะะ🇦​ะ ะ🇩​ะะ🇺​ะะ🇳​ะะ🇬​ะะ🇦​ะะ🇦​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇦​ะะ🇦​ะ ะ🇧​ะะ🇭​ะะ🇴​ꜱ​ะะ🇩​ะะ🇦​ะ",
        "ะ🇲​ะะ🇪​ะะ🇷​ะะ🇦​ะะ🇦​ะ ะ🇱​ะะ🇺​ะะ🇳​ะะ🇩​ะ ะ🇵​ะะ🇦​ะะ🇰​ะะ🇦​ะะ🇩​ะ ะ🇱​ะะ🇪​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇦​ะ🇷​ะะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะ",
        "ะ🇨​ะะ🇭​ะะ🇺​ะะ🇵​ะ ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇦​ะะ🇰​ะะ🇦​ะะ🇦​ะ ะ🇧​ะะ🇭​ะะ🇴​ꜱ​ะะ🇩​ะะ🇦​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇨​ะะ🇭​ะะ🇺​ꜱ​ะ ะ🇬​ะะ🇪​ะะ🇾​ะะ🇮​ะ ะ🇰​ะะ🇾​ะะ🇦​ะะ🇦​ะ ะ🇱​ะะ🇦​ะะ🇼​ะะ🇩​ะะ🇪​ะะ🇪​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇦​ะะ🇦​ะ ะ🇧​ะะ🇯​ꜱ​ะะ🇴​ะะ🇩​ะะ🇦​ะะ🇦​ะ",
        "ะ🇲​ะะ🇦​ะะ🇩​ะะ🇦​ะ🇷​ะ🇽​ะะ🇭​ะะ🇴​ะะ🇩​ะะ🇩​ะะ🇩​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะะ🇺​ะะ🇺​ะ🇮​ะ ะ🇲​ะะ🇦​ะะ🇦​ะะ🇦​ะ ะ🇰​ะะ🇦​ะะ🇦​ะ ะ🇧​ะะ🇭​ꜱ​ะะ🇴​ะะ🇩​ะะ🇦​ะะ🇦​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะะ🇮​ะะ🇮​ะะ🇮​ะะ🇮​ะ ะ🇧​ะะ🇪​ะะ🇭​ะะ🇪​ะ🇳​ะะ🇳​ะะ🇳​ะ ะ🇰​ะะ🇴​ะ ะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะะ🇩​ะะ🇩​ะะ🇺​ะะ🇺​ะะ🇺​ะะ🇺​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇦​ะ🇷​ะ🇽​ะะ🇭​ะะ🇴​ะะ🇩​ะะ🇩​ะะ🇩​ะะ🇩​ะ",
        "ะ🇹​ะะ🇺​ะ ะ🇳​ะะ🇮​ะะ🇰​ะะ🇦​ะะ🇱​ะ ะ🇲​ะะ🇦​ะะ🇩​ะะ🇦​ะ🇷​ะะ🇨​ะะ🇭​ะะ🇴​ะะ🇩​ะ",
        "ะ🇨​ะะ🇭​ะะ🇺​ะะ🇵​ะ ะ🇷​ะะ🇦​ะะ🇳​ะะ🇩​ะะ🇮​ะ ะ🇰​ะะ🇪​ะ ะ🇧​ะะ🇦​ะะ🇨​ะะ🇭​ะะ🇪​ะ",
        "ะ??​ะะ🇪​ะะ🇷​ะะ🇦​ะ ะ🇲​ะะ🇦​ะะ🇦​ะ ะ🇲​ะะ🇪​ะะ🇷​ะะ🇮​ะ ะ🇯​ะะ🇦​ะะ🇦​ะ🇳​ะ ะ🇪​ะะ🇾​ะ",
        "ะ🇹​ะะ🇪​ะะ🇷​ะะ🇮​ะ ꜱ​ะ🇪​x​ะ🇾​ะ ะ🇧​ะะ🇦​ะะ🇭​ะะ🇪​ะ🇳​ะ ะ🇰​ะะ🇮​ะ ะ🇨​ะะ🇭​ะะ🇺​ะะ🇹​ะ ะ🇴​ะะ🇵​ะ",
        "⚡🇧⚡🇦⚡🇦⚡🇵 ⚡🇧⚡🇭⚡?? ⚡🇧⚡🇳⚡🇦⚡🇱⚡🇪 ⚡🇲⚡🇺⚡🇯⚡🇪 ⚡🇷⚡🇳⚡🇩⚡🇮⚡🇰⚡🇪",
        "⚡🇹⚡🇪⚡🇷⚡🇦 ⚡🇧⚡🇦⚡🇦⚡🇵 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮⚡🇧⚡🇦⚡🇦⚡🇿 ⚡🇪⚡🇾 ⚡🇾⚡🇦⚡🇦⚡🇩 ⚡🇪⚡🇾 ⚡🇹⚡🇺⚡🇯⚡🇭⚡🇪",
        "⚡🇹⚡🇺 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇦 ⚡🇳⚡🇦 ⚡🇹⚡🇾⚡🇲⚡🇵⚡🇦⚡🇸⚡🇸",
        "⚡🇴⚡🇾⚡🇪 ⚡🇺⚡🇳⚡🇫⚡🇺⚡🇳⚡🇳⚡🇾 ⚡🇸⚡🇼⚡🇮⚡🇵⚡🇪 ⚡🇲⚡🇹⚡🇹 ⚡🇰⚡🇷",
        "⚡🇴⚡🇭 ⚡🇭⚡🇪⚡🇱⚡🇱⚡🇴 ⚡🇧⚡🇮⚡🇭⚡🇦⚡🇷⚡🇮 ⚡🇹⚡🇪⚡??⚡🇦 ⚡🇧⚡🇦⚡🇦⚡🇵 ⚡🇧⚡🇮⚡🇭⚡🇦⚡🇷⚡🇮 ⚡🇴⚡🇷 ⚡🇹⚡🇺 ⚡🇻 ⚡🇧⚡🇮⚡🇭⚡🇦⚡🇷⚡🇮 ⚡🇦⚡🇺⚡🇰⚡🇦⚡🇹 ⚡🇲⚡🇪 ⚡🇷⚡🇭⚡🇦 ⚡🇰⚡🇷.",
        "⚡🇴⚡🇾⚡🇾 ⚡🇰⚡🇮⚡🇳⚡🇳⚡🇪⚡🇷 ⚡🇹⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇬⚡🇨 ⚡🇲⚡🇪 ⚡🇦⚡🇦⚡🇳⚡🇪 ⚡🇰⚡🇮 ⚡🇵⚡🇪⚡🇷⚡🇲⚡🇮⚡🇸⚡🇸⚡🇮⚡🇴⚡🇳 ⚡🇰⚡🇮⚡🇸⚡🇳⚡🇪 ⚡🇩⚡🇮.",
        "⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇭⚡🇦",
        "⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇭⚡🇦 ⚡🇪⚡🇰 ⚡🇧⚡🇦⚡🇦⚡🇷.",
        "⚡🇸⚡🇺⚡🇳 ⚡🇸⚡🇺⚡🇳 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇦.",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇨⚡🇦 ⚡🇧⚡🇭⚡🇴⚡🇸⚡🇩⚡🇦.",
        "⚡🇴⚡🇾⚡🇪 ⚡🇨⚡🇭⚡🇴⚡🇹⚡🇮 ⚡🇯⚡🇦⚡🇹⚡🇮 ⚡🇰⚡🇪 ⚡🇹⚡🇲⚡🇷.",
        "⚡🇰⚡🇾? ⚡🇯⚡🇱⚡🇩⚡🇮 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇰⚡🇮⚡🇩⚡🇩⚡🇪.",
        "⚡🇧⚡🇮⚡🇭⚡🇦⚡🇷⚡🇮 ⚡🇨⚡🇴⚡🇲 ⚡🇬⚡🇦⚡🇳⚡🇬 ⚡🇰⚡🇪 ⚡🇧⚡🇦⚡🇦⚡🇵 ⚡🇰⚡🇴 ⚡🇹⚡🇦⚡🇬 ⚡🇨⚡🇷⚡🇪⚡🇬⚡🇦 ⚡🇹⚡🇺",
        "⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇨⚡🇾⚡🇦 ⚡🇹⚡🇺 ⚡🇧⚡🇮⚡🇭⚡🇦⚡🇷⚡🇮 ⚡🇪⚡🇾 ⚡🇹⚡🇲⚡🇰⚡🇨 ⚡🇧⚡🇸",
        "⚡🇯⚡🇦⚡🇱⚡🇩⚡🇮 ⚡🇸⚡🇪 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮⚡🇧⚡🇦⚡🇦⚡🇿 ⚡🇵⚡🇦⚡🇵⚡🇦 ⚡🇧⚡🇴⚡🇱",
        "⚡🇸⚡🇮⚡🇩⚡🇪 ⚡🇭⚡🇴⚡🇯⚡🇦 ⚡🇧⚡🇮⚡🇭⚡🇦⚡🇷⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇦⚡🇧",
        "⚡🇭⚡🇾⚡🇪 ⚡🇵⚡🇬⚡🇱 ⚡🇧⚡🇭⚡🇬 ⚡🇲⚡🇦⚡🇹 ⚡🇦⚡🇨⚡🇭⚡🇪 ⚡🇸⚡🇪 ⚡🇨⚡🇺⚡🇩",
        "⚡🇧⚡🇭⚡🇬 ⚡🇳⚡🇾 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇹⚡🇺 ⚡🇦⚡🇯⚡🇯",
        "⚡🇭⚡🇾⚡🇪 ⚡🇵⚡🇬⚡🇱 ⚡🇰⚡🇪 ⚡🇧⚡🇨⚡🇭⚡🇪 ⚡🇧⚡🇭⚡🇦⚡🇬 ⚡🇲⚡🇦⚡🇹",
        "⚡🇭⚡🇾⚡🇪 ⚡🇩⚡🇺⚡🇷 ⚡🇭⚡🇦⚡🇹⚡🇹 ⚡🇲⚡🇦⚡🇩⚡🇭⚡🇦⚡🇷⚡🇨⚡🇭⚡🇴⚡🇩 ⚡🇰⚡🇪 ⚡🇧⚡🇦⚡🇨⚡🇭⚡🇪",
        "⚡🇰⚡🇴⚡🇮 ⚡🇧⚡🇦⚡🇹 ⚡🇳⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾 ⚡🇪⚡🇸⚡🇱⚡🇮⚡🇾⚡🇪 ⚡🇲⚡🇦⚡🇫 ⚡🇨⚡🇷 ⚡🇷⚡🇭⚡🇦 ⚡🇭⚡🇺 ⚡🇹⚡🇺⚡🇯⚡🇭⚡🇪",
        "⚡🇰⚡🇴⚡🇮 ⚡🇧⚡🇦⚡🇦⚡🇹 ⚡🇳⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇹⚡🇺 ⚡🇲⚡🇦⚡🇫⚡🇮 ⚡🇩⚡🇪 ⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦",
        "⚡🇦⚡🇨⚡🇭⚡🇪 ⚡🇸⚡🇪 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇹⚡🇺 ⚡🇲⚡🇦⚡🇫⚡🇮 ⚡🇲⚡🇮⚡🇱 ⚡🇯⚡🇦⚡🇾⚡🇪⚡🇬⚡🇮 ⚡🇹⚡🇺⚡🇯⚡🇭⚡🇪",
        "⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦 ⚡🇲⚡🇦⚡🇹 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇦 ⚡🇲⚡🇺⚡🇯⚡🇪 ⚡🇸⚡🇼⚡🇮⚡🇵⚡🇪 ⚡🇨⚡🇷⚡🇰⚡🇪",
        "⚡🇦⚡🇨⚡🇭⚡🇪 ⚡🇸⚡🇪 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇹⚡🇺 ⚡🇸⚡🇼⚡🇮⚡🇵⚡🇪 ⚡🇨⚡🇷⚡🇰⚡🇪",
        "⚡🇫⚡🇷 ⚡🇧⚡🇴⚡🇱⚡🇳⚡🇦 ⚡🇳⚡🇦 ⚡🇰⚡🇮 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇱⚡🇪 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦 ⚡🇸⚡🇼⚡🇮⚡🇵⚡🇪 ⚡🇨⚡🇷⚡🇰⚡🇪",
        "⚡🇨⚡🇾⚡🇦 ⚡🇭⚡🇺⚡🇦 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇵⚡🇷 ⚡🇰⚡🇪⚡🇸⚡🇪 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦",
        "⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇵⚡🇹⚡🇦 ⚡🇹⚡🇭⚡🇦 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇲⚡🇪⚡🇾 ⚡🇳⚡🇾 ⚡🇲⚡🇦⚡🇳⚡🇹⚡🇦 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇾",
        "⚡🇱⚡🇴⚡🇩⚡🇪 ⚡🇸⚡🇪 ⚡🇺⚡🇹⚡🇷 ⚡🇲⚡🇨",
        "⚡🇱⚡🇺⚡🇳 ⚡🇲⚡🇹 ⚡🇨⚡🇭⚡🇺⚡🇸 ⚡🇲⚡🇪⚡🇷⚡🇦",
        "⚡🇳⚡🇮⚡🇰⚡🇦⚡🇱 ⚡🇲⚡🇦⚡🇩⚡🇦⚡🇷⚡🇨⚡🇭⚡🇩",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇴⚡🇾⚡🇪 ⚡🇬⚡🇦⚡🇸⚡🇭⚡🇹⚡🇮 ⚡🇰 ⚡🇧⚡🇦⚡🇨⚡🇭⚡🇪",
        "⚡🇲⚡🇦⚡🇰⚡🇮⚡🇨⚡🇭⚡🇺⚡🇹 ⚡🇹⚡🇪⚡🇷⚡🇮",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇷⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪",
        "⚡🇲⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇮",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦 ⚡🇰 ⚡🇭⚡🇦⚡🇹⚡🇭 ⚡🇹⚡🇴⚡🇩⚡🇭 ⚡🇰 ⚡🇹⚡🇪⚡🇷⚡🇪 ⚡🇧⚡🇦⚡🇦⚡🇵 ⚡🇰 ⚡🇲⚡🇺⚡🇭 ⚡🇲⚡🇪 ⚡🇫⚡🇦⚡🇸⚡🇦⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪",
        "⚡🇱⚡🇪⚡🇦⚡🇻⚡🇪 ⚡🇱⚡🇪 ⚡🇹⚡🇺 ⚡🇷⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇵⚡🇦⚡🇸⚡🇦⚡🇳⚡🇩 ⚡🇳⚡🇦⚡🇮 ⚡🇦⚡🇾⚡🇦 ⚡🇲⚡🇪⚡🇰⚡🇴",
        "⚡🇱⚡🇪⚡🇦⚡🇻⚡🇪 ⚡🇱⚡🇪 ⚡🇹⚡🇺 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇮⚡🇩⚡🇪⚡🇷 ⚡🇸⚡🇪",
        "⚡🇱⚡🇪⚡🇦⚡🇻⚡🇪 ⚡🇱⚡🇪 ⚡🇯⚡🇱⚡🇩⚡🇮 ⚡🇸⚡🇪 ⚡🇼⚡🇷⚡🇳⚡🇦 ⚡🇲⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇱⚡🇪⚡🇦⚡🇻⚡🇪 ⚡🇳⚡🇾 ⚡🇱⚡🇪⚡🇬⚡🇦 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇸⚡🇲⚡🇯⚡🇭 ⚡🇧⚡🇦⚡🇹 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇱⚡🇪⚡🇦⚡🇻⚡🇪 ⚡🇱⚡🇪",
        "⚡🇫⚡🇦⚡🇸⚡🇹 ⚡🇱⚡🇪⚡🇦⚡🇻⚡🇪 ⚡🇱⚡🇪 ⚡🇰⚡🇦⚡🇲⚡🇯⚡🇴⚡🇷 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪",
        "⚡🇹⚡🇺⚡🇹⚡🇴 ⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇷⚡🇳⚡🇩⚡🇾⚡🇰",
        "⚡🇴⚡🇾 ⚡🇭⚡🇮⚡🇯⚡🇩⚡🇪 ⚡🇰⚡🇭⚡??⚡🇳⚡🇦 ⚡🇰⚡🇭⚡🇦 ⚡🇰⚡🇪 ⚡🇦⚡🇦 ⚡🇰⚡🇦⚡🇲⚡🇿⚡🇴⚡🇷",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇰⚡🇴 ⚡🇮⚡🇱⚡🇾 ⚡🇷⚡🇪⚡🇾 🌚😂",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇨⚡🇭⚡🇦⚡🇵 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇹⚡🇲⚡🇰⚡🇨",
        "⚡🇨⚡🇭⚡🇺⚡🇵⚡🇨⚡🇭⚡🇦⚡🇵 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇹⚡🇺",
        "⚡🇸⚡🇭⚡🇮 ⚡🇸⚡🇪 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡??⚡🇺 ⚡🇨⚡🇭⚡🇺⚡🇵⚡🇨⚡🇭⚡🇦⚡🇵",
        "⚡🇫⚡🇷 ⚡🇸⚡🇪 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇹⚡🇺 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇵⚡🇨⚡🇭⚡🇦⚡🇵",
        "⚡🇸⚡🇭⚡🇮 ⚡🇸⚡🇪 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇼⚡🇷⚡🇳⚡🇦 ⚡🇲⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡??⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇲⚡🇦 ⚡🇨⚡🇾⚡🇺 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇨⚡🇭⚡🇺⚡🇵⚡🇨⚡🇭⚡🇦⚡🇵",
        "⚡🇵⚡🇷⚡🇴⚡🇴⚡🇫 ⚡🇨⚡🇷 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇵⚡🇷⚡🇴⚡🇴⚡🇫 ⚡🇪⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾",
        "⚡🇵⚡🇷⚡🇴⚡🇴⚡🇫 ⚡🇭⚡🇴 ⚡🇨⚡🇭⚡🇺⚡🇰⚡🇦 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇨⚡🇭⚡🇮⚡🇱⚡🇱⚡🇦⚡🇷",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇲⚡🇦⚡🇦 ⚡🇰 ⚡🇧⚡🇴⚡🇸⚡🇩⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇴⚡🇾 ⚡🇭⚡🇮⚡🇯⚡🇩⚡🇪 ⚡🇰⚡🇭⚡🇦⚡🇳⚡🇦 ⚡🇰⚡🇭⚡🇦 ⚡🇰⚡🇪 ⚡🇦⚡🇦 ⚡🇰⚡🇦⚡🇲⚡🇿⚡🇴⚡🇷",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇲⚡🇦⚡🇩⚡🇷⚡🇨⚡🇭⚡🇴⚡🇩 ?",
        "⚡🇦⚡🇧 ⚡🇹⚡🇰 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮 ⚡🇭⚡🇴⚡🇬⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ?",
        "⚡🇳⚡🇾 ⚡🇳⚡🇾 ⚡🇲⚡🇪 ⚡🇰⚡🇺⚡🇨⚡🇭 ⚡🇳⚡🇾 ⚡🇯⚡🇦⚡🇳⚡🇹⚡🇦 ⚡🇧⚡🇸 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾",
        "⚡🇸⚡🇧⚡🇸⚡🇪 ⚡🇵⚡🇭⚡🇪⚡🇱⚡🇪 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇰⚡🇴 ⚡🇧⚡🇴⚡🇱 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇳⚡🇦 ⚡🇰⚡🇦⚡🇲 ⚡🇰⚡🇷⚡🇪",
        "⚡🇾⚡🇦⚡🇭⚡🇦 ⚡🇧⚡🇭⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇦 ⚡🇹⚡🇺 ⚡🇷⚡🇳⚡🇩⚡🇾⚡🇨⚡🇪 ⚡🇵⚡🇮⚡🇱⚡🇱⚡🇪",
        "⚡🇹⚡🇪⚡🇷⚡🇮⚡🇲⚡🇦⚡🇰⚡🇦⚡🇧⚡🇴⚡🇸⚡🇩⚡🇦",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇹⚡🇴 ⚡🇧⚡🇭⚡🇪⚡🇳 ⚡🇨⚡🇺⚡🇩⚡🇪⚡🇬⚡🇮",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇷⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇹⚡🇴⚡🇲⚡🇲⚡🇾",
        "⚡🇳⚡🇮⚡🇰⚡🇦⚡🇱 ⚡🇲⚡🇦⚡🇩⚡🇦⚡🇷⚡🇨⚡🇭⚡🇩 ⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇾⚡🇭⚡🇦 ⚡🇸⚡🇪",
        "⚡🇨⚡🇴⚡🇿 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦 ⚡🇦⚡🇳⚡🇩⚡🇭⚡🇮 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮 ⚡🇭⚡🇪",
        "⚡🇳⚡🇾⚡🇹⚡🇴 ⚡🇧⚡🇦⚡🇦⚡🇵 ⚡🇧⚡🇴⚡🇱 ⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪",
        "⚡🇳⚡🇾⚡🇳⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇭⚡🇴⚡🇬⚡🇮 ⚡🇷⚡🇳⚡🇩⚡🇮 ⚡🇯⚡🇴 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦⚡🇹⚡🇮 ⚡🇯⚡🇴⚡🇬⚡🇮",
        "⚡🇹⚡🇷⚡🇾 ⚡🇦⚡🇲⚡🇲⚡🇮 ⚡🇨⚡🇪 ⚡🇧⚡🇭⚡🇴⚡🇸⚡🇩⚡🇪 ⚡🇲⚡🇪 ⚡🇪⚡🇲⚡🇴⚡🇯⚡🇮 ⚡🇩⚡🇦⚡🇱 ⚡🇲⚡🇨",
        "⚡🇨⚡🇾⚡🇦 ? ⚡🇨⚡🇭⚡🇲⚡🇷 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇦 ⚡🇨⚡🇾⚡🇦 ?",
        "⚡🇹⚡🇲 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇷⚡🇮 ⚡🇭⚡🇴⚡🇬⚡🇮 ⚡🇫⚡🇷⚡🇷⚡🇹⚡🇴",
        "⚡🇨⚡🇾⚡🇦 ? ⚡🇰⚡🇧 ? ⚡🇵⚡🇬⚡🇱 ⚡🇪⚡🇾 ⚡🇨⚡🇾⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇰⚡🇪⚡🇰",
        "⚡🇨⚡🇾⚡🇦 ⚡🇸⚡🇨⚡🇭 ⚡🇲⚡🇪⚡🇾 ⚡🇵⚡🇬⚡🇱 ⚡🇪⚡🇾 ⚡🇨⚡🇾⚡🇦 ⚡🇹⚡🇺 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇨⚡🇺⚡🇩⚡🇼⚡?? ⚡🇱⚡🇮 ⚡🇹⚡🇺⚡🇳⚡🇪 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦",
        "⚡🇮⚡🇹⚡🇳⚡🇦 ⚡🇸⚡🇨⚡🇭 ⚡🇳⚡🇾 ⚡🇧⚡🇴⚡🇱 ⚡🇲⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇸⚡🇨⚡🇭 ⚡🇲⚡🇪⚡🇾 ⚡🇵⚡🇬⚡🇱 ⚡🇪⚡🇾 ⚡🇹⚡🇺 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇱⚡🇮⚡🇦 ⚡🇲⚡🇪⚡🇷⚡🇪 ⚡🇸⚡🇹⚡🇭",
        "⚡🇲⚡🇹⚡🇱⚡🇧 ⚡🇹⚡🇲⚡🇷",
        "⚡🇳⚡🇾⚡🇹⚡🇴",
        "⚡🇵⚡🇺⚡🇷⚡🇦 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇲⚡🇨",
        "⚡🇹⚡🇲⚡🇷 ⚡🇫⚡🇷⚡🇷⚡🇹⚡🇴",
        "⚡🇴⚡🇭 ⚡🇴⚡🇰 ⚡🇨⚡🇺⚡🇩⚡🇱⚡🇪 ⚡🇫⚡🇮⚡🇷",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇰⚡🇦 ⚡🇩⚡🇦⚡🇲⚡🇦⚡🇩",
        "⚡🇨⚡🇾⚡🇦 ? ⚡🇦⚡🇨⚡🇭⚡🇪 ⚡🇸⚡🇪 ⚡🇱⚡🇮⚡🇰⚡🇭⚡🇪 ⚡🇵⚡🇪⚡🇭⚡🇱⚡🇪 ⚡🇷⚡🇳⚡🇩⚡🇮⚡🇰⚡🇪⚡🇧⚡🇦⚡🇨⚡🇭⚡🇪",
        "⚡🇳⚡🇾⚡🇹⚡🇴 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇳⚡🇪 ⚡🇲⚡🇪 ⚡🇻⚡🇾⚡🇦⚡🇸⚡🇹 ⚡🇭⚡🇺",
        "⚡🇳⚡🇾⚡🇹⚡🇴 ⚡🇵⚡🇬⚡🇱 ⚡🇪⚡🇾 ⚡🇨⚡🇾⚡🇦 ⚡🇰⚡🇺⚡🇨⚡🇭 ⚡🇧⚡🇮",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇨⚡🇾⚡🇦 ? ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇦 ?",
        "⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇲⚡🇹 ⚡🇭⚡🇸⚡🇸",
        "⚡🇾⚡🇺⚡🇷 ⚡🇷⚡🇳⚡🇩⚡🇮 ⚡🇲⚡🇴⚡🇲",
        "⚡🇦⚡🇷⚡🇪 ⚡🇸⚡🇧⚡🇰⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇮 ⚡🇴⚡🇷 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇧⚡🇮",
        "⚡🇦⚡🇷⚡🇪 ⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇨⚡🇺⚡🇩⚡🇱⚡🇪 ⚡🇪⚡🇰 ⚡🇧⚡🇦⚡🇦⚡🇷",
        "⚡🇹⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇮 ⚡🇹⚡🇷⚡🇭",
        "⚡🇪⚡🇰 ⚡🇱⚡🇮⚡🇳⚡🇪 ⚡🇲⚡🇪 ⚡🇹⚡🇲⚡🇷",
        "⚡🇶",
        "⚡🇴⚡🇨⚡🇾 ⚡🇦⚡🇧 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇱⚡🇪",
        "⚡🇵⚡🇪⚡🇭⚡🇪⚡🇱⚡🇪 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇺",
        "⚡🇳⚡🇾⚡🇹⚡🇴",
        "⚡?? ?",
        "⚡🇭⚡🇾⚡🇾⚡🇾 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇦 ⚡🇪⚡🇰 ⚡🇧⚡🇦⚡🇦⚡🇷",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇸⚡🇺⚡🇳 ⚡🇩⚡🇴⚡🇸⚡🇹 ⚡🇹⚡🇲⚡🇷",
        "⚡🇧⚡🇭⚡🇦⚡🇬 ⚡🇯⚡🇦 ⚡🇷⚡🇦⚡🇦⚡🇳⚡🇩 ⚡🇲⚡🇦⚡🇦⚡🇫 ⚡🇨⚡🇷⚡🇷 ⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇵⚡🇬⚡🇱 ⚡🇷⚡🇳⚡🇩⚡🇮 ⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇦⚡🇦",
        "⚡🇨⚡🇾⚡🇦 ⚡🇹⚡🇲⚡🇷 ⚡🇫⚡🇷⚡🇷⚡🇹⚡🇴",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇦⚡🇦⚡🇰⚡🇪 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇱⚡🇪 ⚡🇨⚡🇭⚡🇲⚡🇷",
        "⚡🇳⚡🇾⚡🇹⚡🇴 ⚡🇦⚡🇪⚡🇸⚡🇪 ⚡🇭⚡🇮 ⚡🇨⚡🇺⚡🇩",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇭⚡🇾⚡🇾 ⚡🇦⚡🇮⚡🇸⚡🇪 ⚡🇭⚡🇮 ⚡🇨⚡🇺⚡🇩 ⚡🇱⚡🇪⚡🇳⚡🇦",
        "⚡🇴⚡🇷 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇱⚡🇪",
        "⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇦 ⚡🇴⚡🇷",
        "⚡🇭⚡🇾⚡🇾 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇴 ⚡🇳⚡🇦",
        "⚡🇨⚡🇭⚡🇺⚡🇩⚡🇴 ⚡🇲⚡🇹 ⚡🇧⚡🇭⚡🇦⚡🇬 ⚡🇯⚡🇦⚡🇴",
        "⚡🇧⚡🇾⚡🇾⚡🇪⚡🇪 ⚡🇭⚡🇾⚡🇾 ⚡🇨⚡🇾⚡🇦 ?",
        "⚡🇶⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇶 ⚡🇷⚡🇭⚡🇪 ⚡🇭⚡🇴 ?",
        "⚡🇵⚡🇬⚡🇱 ⚡🇪⚡🇾 ⚡🇨⚡🇾⚡🇦 ⚡🇲⚡🇨",
        "⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇲⚡🇹",
        "⚡🇨⚡🇾⚡🇦 ⚡🇵⚡🇬⚡🇱 ⚡🇷⚡🇳⚡🇩⚡🇮 ⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇦⚡🇦",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇦⚡🇲⚡🇲⚡🇮 ⚡🇨⚡🇪 ⚡🇧⚡🇭⚡🇴⚡🇸⚡🇩⚡🇪 ⚡🇲⚡🇪 ⚡🇨⚡🇭⚡🇦⚡🇵⚡🇵⚡🇦⚡🇱",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇦⚡🇦 ⚡🇲⚡🇨",
        "⚡🇰⚡🇲⚡🇿⚡🇷⚡🇴⚡🇷 ⚡🇪⚡🇾 ⚡🇨⚡??⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇮⚡🇪⚡🇰",
        "⚡🇨⚡🇾⚡🇦 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇷⚡🇭⚡🇦 ?",
        "⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇹⚡🇭⚡🇦 ⚡🇨⚡🇾⚡🇦 ?",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇸⚡🇱⚡🇮⚡🇩⚡🇪 ⚡🇱⚡🇪⚡🇰⚡🇪 ⚡🇧⚡🇦⚡🇦⚡🇹 ⚡🇨⚡🇷⚡🇲⚡🇨",
        "⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇺",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇨⚡🇵 ⚡🇲⚡🇹 ⚡🇨⚡🇷⚡🇷 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇱⚡🇪",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇭⚡🇾⚡🇾 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇦",
        "⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇦⚡🇦 ⚡🇹⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇸⚡🇨⚡🇭⚡🇴⚡🇫⚡🇺 ⚡🇰⚡🇭⚡🇦⚡🇨⚡🇭⚡🇦⚡🇷 ⚡🇰⚡🇭⚡🇦⚡🇨⚡🇭⚡🇦⚡🇷",
        "⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇦⚡🇦 ⚡🇯⚡🇦 ⚡🇲⚡🇨",
        "⚡🇭⚡🇾⚡🇾 ⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇦⚡🇦⚡🇰⚡🇪 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇱⚡🇪",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇰⚡🇲⚡🇿⚡🇴⚡🇷 ⚡🇲⚡🇨 ⚡🇮⚡🇩⚡🇦⚡🇷 ⚡🇦⚡🇦",
        "⚡🇾⚡🇪 ⚡🇨⚡🇾⚡🇦 ⚡🇹⚡🇲⚡🇷",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇳⚡🇾 ⚡🇨⚡🇵 ⚡🇳⚡🇾 ⚡🇨⚡🇷⚡🇷",
        "⚡🇴⚡🇾⚡🇪⚡🇪 ⚡🇵⚡🇬⚡🇱 ⚡🇲⚡🇹 ⚡🇨⚡🇷⚡🇷",
        "⚡🇨⚡🇺⚡🇩⚡🇱⚡🇪 ⚡🇦⚡🇷⚡🇦⚡🇲 ⚡🇸⚡🇪 ⚡🇲⚡🇨",
        "⚡🇵⚡🇬⚡🇱 ⚡🇪⚡🇾 ⚡🇨⚡🇾⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇮⚡🇪⚡🇰",
        "⚡🇨⚡🇵 ⚡🇨⚡🇷⚡🇨⚡🇪 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇪⚡🇬⚡🇦 !",
        "⚡🇧⚡🇦⚡🇦⚡🇵 ? ⚡🇲⚡🇨 ⚡🇲⚡🇪⚡🇷⚡🇦 ⚡🇨⚡🇴⚡🇮 ⚡🇲⚡🇦 ⚡🇧⚡🇦⚡🇦⚡🇵 ⚡🇳⚡🇾 ⚡🇪⚡🇾 ⚡🇲⚡🇦⚡🇮 ⚡🇺⚡🇵⚡🇦⚡🇷 ⚡🇸⚡🇪 ⚡🇷⚡🇴⚡🇨⚡🇰⚡🇪⚡🇹 ⚡🇵⚡🇪 ⚡🇧⚡🇪⚡🇹⚡🇭 ⚡🇨⚡🇪 ⚡🇧⚡🇸⚡🇸 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇳⚡🇪 ⚡🇦⚡🇾⚡🇦 ⚡🇭⚡🇺",
        "⚡🇨⚡🇭⚡🇴⚡🇹⚡🇦 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇷⚡🇳⚡🇩⚡🇮 ⚡🇰 ⚡🇧⚡🇦⚡🇨⚡🇭⚡🇪",
        "⚡🇨⚡🇭⚡🇴⚡🇹⚡🇦 ⚡🇱⚡🇮⚡🇰⚡🇭⚡🇦 ⚡🇼⚡🇷⚡🇳⚡🇦 ⚡🇹⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇾",
        "⚡🇹⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇧⚡🇦⚡🇰⚡🇦 ⚡🇨⚡🇴⚡🇩⚡🇪⚡🇬⚡🇦",
        "⚡🇹⚡🇲⚡🇰⚡🇨 ⚡🇲⚡🇦⚡🇮⚡🇳 ⚡🇧⚡🇺⚡🇷⚡🇫",
        "⚡🇧⚡🇭⚡🇮⚡🇰⚡🇦⚡🇷⚡🇮 ⚡🇰⚡🇮 ⚡🇯⚡🇭⚡🇦⚡🇹 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇦 ⚡🇱⚡🇪",
        "⚡🇨⚡🇭⚡🇴⚡🇩⚡🇰⚡🇪 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇲⚡🇦⚡🇷⚡🇯⚡🇦⚡🇾⚡🇪⚡🇬⚡🇮",
        "⚡🇹⚡🇲⚡🇰⚡🇨 ⚡🇲⚡🇦⚡🇮⚡🇳 ⚡🇲⚡🇴⚡🇺⚡🇳⚡🇹 ⚡🇪⚡🇻⚡🇪⚡🇷⚡🇪⚡🇸⚡🇹",
        "⚡🇲⚡🇺⚡🇭 ⚡🇲⚡🇪⚡🇾 ⚡🇱⚡🇪⚡🇬⚡🇦 ⚡🇱⚡🇺⚡🇳⚡🇩 ⚡🇲⚡🇪⚡🇷⚡🇦",
        "⚡🇭⚡🇮⚡🇯⚡🇩⚡🇪 ⚡🇰⚡🇮 ⚡🇯⚡🇭⚡🇦⚡🇹 ⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇼⚡🇷⚡🇳⚡🇦 ⚡🇹⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇮",
        "⚡🇲⚡🇪⚡🇳⚡🇺 ⚡🇳⚡🇾 ⚡🇵⚡🇹⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾",
        "⚡🇲⚡🇪⚡🇳⚡🇺 ⚡🇰⚡🇮 ⚡🇵⚡🇹⚡🇦 ⚡🇲⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇲⚡🇪⚡🇳⚡🇺 ⚡🇵⚡🇹⚡🇦 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇲⚡🇪⚡🇳⚡🇺 ⚡🇸⚡🇧 ⚡🇵⚡🇹⚡🇦 ⚡🇲⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇲⚡🇪⚡🇳⚡🇺 ⚡🇵⚡🇷 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾",
        "⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇪⚡🇳⚡🇺 ⚡🇵⚡🇹⚡🇦",
        "⚡🇹⚡🇪⚡🇳⚡🇺 ⚡🇴⚡🇷 ⚡🇲⚡🇪⚡🇳⚡🇺 ⚡🇵⚡🇹⚡🇦 ⚡🇪⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇧⚡🇸 ⚡🇧⚡🇸 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇦⚡🇵⚡🇳⚡🇮",
        "⚡🇧⚡🇸 ⚡🇧⚡🇸 ⚡🇲⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇹⚡🇭⚡🇳⚡🇰⚡🇸⚡🇸",
        "⚡🇧⚡🇸 ⚡??⚡🇸 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇱⚡🇮⚡🇦 ⚡🇹⚡🇺 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦⚡🇦",
        "⚡🇧⚡🇸 ⚡🇧⚡🇸 ⚡🇰⚡🇦⚡🇲⚡🇯⚡🇴⚡🇷 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇸⚡🇲⚡🇯⚡🇭 ⚡🇬⚡🇾⚡🇦 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇱⚡🇪 ⚡🇦⚡🇧",
        "⚡🇸⚡🇲⚡🇯⚡🇭 ⚡🇬⚡🇾⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾",
        "⚡🇸⚡🇲⚡🇯⚡🇭 ⚡🇬⚡🇾⚡🇦 ⚡🇹⚡🇺 ⚡🇸⚡🇦⚡🇧⚡🇮⚡🇹 ⚡🇰⚡🇷 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇨⚡🇾⚡🇦 ⚡🇭⚡🇺⚡🇦 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇹⚡🇺 ⚡🇦⚡🇵⚡🇳⚡🇮",
        "⚡🇪⚡🇦⚡🇸⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇱⚡🇪 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇹⚡🇺",
        "⚡🇪⚡🇦⚡🇸⚡🇾 ⚡🇼8 ⚡🇲⚡?? ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇱⚡🇪 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇦⚡🇧",
        "⚡🇸⚡🇦⚡🇳⚡🇸 ⚡🇦⚡🇷⚡🇮 ⚡🇭⚡🇦 ⚡🇰⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇬⚡🇮 ⚡🇦⚡🇯⚡🇯",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇰⚡🇴 ⚡🇧⚡🇮⚡🇳⚡🇦 ⚡🇸⚡🇦⚡🇳⚡🇸⚡🇸 ⚡🇱⚡🇪⚡🇹⚡🇪 ⚡🇭⚡🇺⚡🇪 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮⚡🇰⚡🇪 ⚡🇰⚡🇦⚡🇲⚡🇯⚡🇴⚡🇷",
        "⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦 ⚡🇳⚡🇴⚡🇷⚡🇲⚡🇮⚡🇪 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇱⚡🇪 ⚡🇹⚡🇺",
        "⚡🇫⚡🇷 ⚡🇨⚡🇾⚡🇦 ⚡🇳⚡🇴⚡🇷⚡🇲⚡🇮⚡🇪 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇧⚡🇦⚡🇸 ⚡🇹⚡🇭⚡🇪⚡🇰 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾",
        "⚡🇧⚡🇦⚡🇸 ⚡🇹⚡🇭⚡🇪⚡🇰 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮",
        "⚡🇰⚡🇦⚡🇲⚡🇯⚡🇴⚡🇷 ⚡🇹⚡🇭⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇪⚡🇸⚡🇱⚡🇮⚡🇾⚡🇪 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮",
        "⚡🇲⚡🇦⚡🇮 ⚡🇸⚡🇧 ⚡🇯⚡🇦⚡🇳⚡🇹⚡🇦 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇨⚡🇭⚡🇱 ⚡🇨⚡🇭⚡🇱 ⚡🇭⚡🇹 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮",
        "⚡🇫⚡🇷 ⚡🇰⚡🇦⚡🇮⚡🇸⚡🇪 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇲⚡🇦⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾",
        "⚡🇧⚡🇦⚡🇸 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾",
        "⚡🇫⚡🇷 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇲⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇪⚡🇾",
        "⚡🇰⚡🇦⚡🇲⚡🇯⚡🇴⚡🇷 ⚡🇲⚡🇦 ⚡🇰⚡🇦 ⚡🇧⚡🇨⚡🇭⚡🇦 ⚡🇹⚡🇺 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪",
        "⚡🇧⚡🇭⚡🇴⚡🇹 ⚡🇬⚡🇳⚡🇩⚡🇮 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇵⚡🇷 ⚡🇰⚡🇦⚡🇮⚡🇸⚡🇪 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇮⚡🇹⚡🇳⚡🇦 ⚡🇬⚡🇳⚡🇩⚡🇦",
        "⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇨⚡🇾⚡🇦 ⚡🇧⚡🇹⚡🇦 ⚡🇷⚡🇭⚡🇦 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇨⚡🇾⚡🇦 ⚡🇵⚡🇹⚡🇦 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇫⚡🇮⚡🇷 ⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇳⚡🇾 ⚡🇵⚡🇹⚡🇦 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇵⚡🇹⚡🇦 ⚡🇳⚡🇾 ⚡🇰⚡🇴⚡🇳 ⚡🇨⚡🇴⚡🇩 ⚡🇩⚡🇮⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇰⚡🇴",
        "⚡🇷⚡🇺⚡🇰 ⚡🇦⚡🇦⚡🇾⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇴⚡🇩⚡🇰⚡🇪",
        "⚡🇼⚡🇦⚡🇮⚡🇹 ⚡🇨⚡🇷 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇴⚡🇩 ⚡🇷⚡🇭⚡🇦 ⚡🇭⚡🇺",
        "⚡🇼⚡🇦⚡🇮⚡🇹 ⚡🇨⚡🇷 ⚡🇷⚡🇦⚡🇧⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇷⚡🇭⚡🇮 ⚡🇪⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇼⚡🇦⚡🇮⚡🇹 ⚡🇰⚡🇷 ⚡🇸⚡🇲⚡🇯⚡🇭 ⚡🇷⚡🇭⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇴⚡🇩⚡🇰⚡🇪",
        "⚡🇼⚡🇦⚡🇮⚡🇹 ⚡🇱⚡🇪 ⚡🇹⚡🇭⚡🇴⚡🇩⚡🇦 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇳⚡🇪 ⚡🇩⚡🇪 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇴",
        "⚡🇷⚡🇺⚡🇰 ⚡🇯⚡🇦 ⚡🇦⚡🇦⚡🇳⚡🇩 ⚡🇷⚡🇰⚡🇭 ⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇪 ⚡🇱⚡🇮⚡🇾⚡🇪",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇫⚡🇦⚡🇲⚡🇴⚡🇺⚡🇸 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾",
        "⚡🇲⚡🇦⚡🇦⚡🇳 ⚡🇱⚡🇮⚡🇦 ⚡🇲⚡🇪⚡🇳⚡🇪 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇸⚡🇦⚡🇱⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇲⚡🇦⚡🇦⚡🇳 ⚡🇱⚡🇮⚡🇦 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇸⚡🇭⚡🇦⚡🇳⚡🇹 ⚡🇧⚡🇪⚡🇹⚡🇭 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇹⚡🇺 ⚡🇦⚡🇵⚡🇳⚡🇮",
        "⚡🇸⚡🇭⚡🇦⚡🇳⚡🇹 ⚡🇧⚡🇪⚡🇹⚡🇭⚡🇰⚡🇪 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇱⚡🇪 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦⚡🇰⚡🇴 ⚡🇹⚡🇺",
        "⚡🇫⚡🇷 ⚡🇸⚡🇪 ⚡🇸⚡🇭⚡🇦⚡🇳⚡🇹 ⚡🇧⚡🇪⚡🇹⚡🇭 ⚡🇹⚡🇺 ⚡🇨⚡🇺⚡🇩 ⚡🇦⚡🇧 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇾⚡🇭⚡🇦",
        "⚡🇲⚡🇪⚡🇷⚡🇪 ⚡🇸⚡🇲⚡🇯⚡🇭 ⚡🇳⚡🇾 ⚡🇦⚡🇾⚡🇦 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇱⚡🇪 ⚡🇰⚡🇪⚡🇱⚡🇦 ⚡🇰⚡🇭⚡🇦 ⚡🇹⚡🇺 ⚡🇲⚡🇦⚡🇩⚡🇷⚡🇨⚡🇭⚡🇴⚡🇩",
        "⚡🇭⚡🇾⚡🇪 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇮 ⚡🇨⚡🇾⚡🇦",
        "⚡🇭⚡🇾⚡🇪 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇲⚡🇦⚡🇷 ⚡🇬⚡🇦⚡🇮 ⚡🇨⚡🇾⚡🇦",
        "⚡🇭⚡🇾⚡🇪 ⚡🇸⚡🇨⚡🇭 ⚡🇧⚡🇹⚡🇦 ⚡🇨⚡🇴⚡🇲 ⚡🇨⚡??⚡🇩 ⚡🇩⚡🇮⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇴",
        "⚡🇨⚡🇭⚡🇱 ⚡🇨⚡🇭⚡🇴⚡🇩 ⚡🇩⚡🇮⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇰⚡🇴 ⚡🇸⚡🇲⚡🇯⚡🇭⚡🇱⚡🇪",
        "⚡🇧⚡🇦⚡🇰⚡🇮 ⚡🇰⚡🇴⚡🇮 ⚡🇩⚡🇮⚡🇰⚡🇰⚡🇦⚡🇹 ⚡🇳⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾",
        "⚡🇧⚡🇦⚡🇰⚡🇮 ⚡🇸⚡🇧 ⚡🇯⚡🇦⚡🇳⚡🇹⚡🇪 ⚡🇪⚡🇾 ⚡🇰⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇩⚡🇰⚡🇦⚡🇩 ⚡🇪⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇨⚡🇾⚡🇦 ⚡🇵⚡🇹⚡🇦 ⚡🇹⚡🇭⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇳⚡🇪 ⚡🇼⚡🇱⚡🇮 ⚡🇪⚡🇾",
        "⚡🇵⚡🇷 ⚡🇲⚡🇪⚡🇮 ⚡🇰⚡🇦⚡🇮⚡🇸⚡🇪 ⚡🇯⚡🇳⚡🇹⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇰⚡🇴 ⚡🇰⚡🇴⚡🇮 ⚡🇨⚡🇭⚡🇴⚡🇩 ⚡🇩⚡🇮⚡🇦",
        "⚡🇵⚡🇷 ⚡🇲⚡🇪⚡🇷⚡🇦 ⚡🇻⚡🇮 ⚡🇲⚡🇦⚡🇳⚡🇳⚡🇦 ⚡🇸⚡🇭⚡🇮 ⚡🇹⚡🇭⚡🇦 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇵⚡🇷 ⚡🇼⚡🇴 ⚡🇬⚡🇱⚡🇹 ⚡🇳⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇪⚡🇾",
        "⚡🇵⚡🇷 ⚡🇼⚡🇴 ⚡🇸⚡🇭⚡🇮 ⚡🇪⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇩⚡🇰⚡🇦⚡🇩 ⚡🇪⚡🇾",
        "⚡🇵⚡🇷 ⚡🇰⚡🇦⚡🇮⚡🇸⚡🇪 ⚡🇰⚡🇮⚡🇦 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇴⚡🇲⚡🇫⚡🇴⚡🇴",
        "⚡🇧⚡🇺⚡🇷 ⚡🇨⚡🇭⚡🇪⚡🇪⚡🇷 ⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦 ⚡🇹⚡🇷⚡🇮 ⚡🇲⚡🇦 ⚡🇰⚡🇦",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦 ⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇱 ⚡🇲⚡🇪 ⚡🇱⚡🇴⚡🇩⚡🇦 ⚡🇲⚡🇦⚡🇷⚡🇰⚡🇪 ⚡🇺⚡🇸⚡🇰⚡🇮 ⚡🇩⚡🇭⚡🇦⚡🇩⚡🇰⚡🇦⚡🇳 ⚡🇷⚡🇴⚡🇰 ⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦",
        "⚡🇱⚡🇺⚡🇱⚡🇱⚡🇪 ⚡🇰⚡🇭⚡🇦 ⚡🇹⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇰⚡🇦⚡🇧⚡🇭⚡🇴⚡🇸⚡🇩⚡🇦",
        "⚡🇹⚡🇷⚡🇮 ⚡🇧⚡🇭⚡🇳 ⚡🇰⚡🇮 ⚡🇧⚡🇭⚡🇴⚡🇸⚡🇩⚡🇮 ⚡🇧⚡🇪⚡🇹⚡🇦",
        "⚡🇹⚡🇷⚡🇮 ⚡🇲⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇮 ⚡🇧⚡🇦⚡🇦⚡🇹 ⚡🇰⚡🇭⚡🇹⚡🇲",
        "⚡🇸⚡🇺⚡🇳 ⚡🇪⚡🇰 ⚡🇲⚡🇦⚡🇿⚡🇪 ⚡🇰⚡🇮 ⚡🇧⚡🇦⚡🇦⚡🇹 ⚡🇧⚡🇦⚡🇹⚡🇦⚡🇴 ⚡🇰⚡🇾⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇭⚡🇦⚡🇮",
        "⚡🇨⚡🇴⚡🇩⚡🇺 ⚡🇨⚡🇴⚡🇩⚡🇺 ⚡🇲⚡🇦⚡🇰⚡🇴 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇦⚡🇯 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇴⚡🇾⚡🇪",
        "⚡🇸⚡🇺⚡🇳 ⚡🇸⚡🇺⚡🇳 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇪 ⚡🇧⚡🇦⚡🇨⚡🇭⚡🇪 ⚡🇹⚡🇺",
        "⚡🇰⚡🇮⚡🇱⚡🇦⚡🇸 ⚡🇳⚡🇾 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪",
        "⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇨⚡🇾⚡🇦 ⚡🇵⚡🇹⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇧⚡🇭⚡🇪⚡🇳 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮",
        "⚡🇵⚡?? ⚡🇵⚡🇷 ⚡🇨⚡🇾⚡🇦 ⚡🇭⚡🇴⚡🇹⚡🇪 ⚡🇪⚡🇾 ⚡🇹⚡🇲⚡🇰⚡🇨",
        "⚡🇹⚡🇲⚡🇨⚡🇱 ⚡🇸⚡🇺⚡🇳⚡🇱⚡🇪",
        "⚡🇲⚡🇴⚡🇴⚡🇹 ⚡🇩⚡🇺 ⚡🇹⚡🇪⚡🇷⚡?? ⚡🇲⚡🇦⚡🇰⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇹 ⚡🇲⚡🇪⚡🇾",
        "⚡🇧⚡🇭⚡🇬⚡🇳⚡🇾 ⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇭⚡🇦 ⚡🇫⚡🇷",
        "⚡🇫⚡🇷 ⚡🇸⚡🇪 ⚡🇨⚡🇺⚡🇩⚡🇱⚡🇪 ⚡🇹⚡🇺",
        "⚡🇾⚡🇪 ⚡🇻⚡🇮 ⚡🇸⚡🇭⚡🇮 ⚡🇪⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇰⚡🇸 ⚡🇧⚡🇸",
        "⚡🇦⚡🇯 ⚡🇰⚡🇺⚡🇨⚡🇭 ⚡🇳⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇹⚡🇺 ⚡🇦⚡🇵⚡🇳⚡🇮",
        "⚡🇹⚡🇷⚡🇾 ⚡🇰⚡🇷 ⚡🇲⚡🇪⚡🇷⚡🇦 ⚡🇱⚡🇺⚡🇳⚡🇩 ⚡🇨⚡🇭⚡🇺⚡🇸⚡🇰⚡🇪",
        "⚡🇹⚡🇴⚡🇷⚡🇲⚡🇦⚡🇰⚡🇮⚡🇧⚡🇺⚡🇷 ⚡🇸⚡🇺⚡🇳",
        "⚡🇹⚡🇴⚡🇷 ⚡🇲⚡🇦⚡🇰⚡🇮 ⚡🇫⚡🇺⚡🇩⚡🇩⚡🇮 ⚡🇴⚡🇾⚡🇪",
        "⚡🇭⚡🇦⚡🇾⚡🇪 ⚡🇭⚡🇦⚡🇾⚡🇪 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮",
        "⚡🇴⚡🇾⚡🇪 ⚡🇱⚡🇺⚡🇳⚡🇩⚡🇰⚡🇪 ⚡🇵⚡🇦⚡🇸⚡🇮⚡🇳⚡🇪..",
        "⚡🇰⚡🇺⚡🇹⚡🇹⚡🇪 ⚡🇰⚡🇪 ⚡🇹⚡🇦⚡🇹⚡🇹⚡🇪 ⚡🇸⚡🇺⚡🇳",
        "⚡🇰⚡🇺⚡🇹⚡🇹⚡🇦 ⚡🇯⚡🇦⚡🇮⚡🇸⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇷⚡🇭⚡🇦 ⚡🇹⚡🇺",
        "⚡🇲⚡🇺⚡🇭 ⚡🇲⚡🇪⚡🇮 ⚡🇱⚡🇪 ⚡🇲⚡🇪⚡🇷⚡🇦..",
        "⚡🇯⚡🇭⚡🇦⚡🇹 ⚡🇰⚡🇪 ⚡🇵⚡🇮⚡🇸⚡🇸⚡🇺 ⚡🇸⚡🇺⚡🇳 ⚡🇹⚡🇲⚡🇰⚡🇨",
        "⚡🇭⚡🇦⚡🇭⚡🇦⚡🇭⚡🇭⚡🇦 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇼⚡🇪⚡🇦⚡🇰 ⚡🇹⚡🇦⚡🇹⚡🇹⚡🇪 ⚡🇺⚡🇹⚡🇭",
        "⚡🇼⚡🇪⚡🇦⚡🇰 ⚡🇪⚡🇾 ⚡🇹⚡🇺 ⚡🇨⚡🇺⚡🇩 ⚡🇷⚡🇭⚡🇦",
        "⚡🇼⚡🇪⚡🇦⚡🇰 ⚡🇦⚡🇨⚡🇭⚡🇪 ⚡🇸⚡🇪 ⚡🇨⚡🇺⚡🇩 ⚡🇹⚡🇺",
        "⚡🇼⚡🇪⚡🇦⚡🇰 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇷⚡🇭⚡🇮 ⚡🇩⚡🇪⚡🇰⚡🇭",
        "⚡🇼⚡🇪⚡🇪⚡🇰 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇦⚡🇧",
        "⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇳⚡🇾 ⚡🇷⚡🇴⚡🇰 ⚡🇹⚡🇺 ⚡🇼⚡🇪⚡🇦⚡🇰 ⚡🇪⚡🇾",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇭⚡🇮⚡🇿⚡🇩⚡🇪",
        "⚡🇴⚡🇰⚡🇦⚡🇹 ⚡🇳⚡🇾 ⚡🇲⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇹⚡🇺 ⚡🇦⚡🇵⚡🇳⚡🇮",
        "⚡🇱⚡🇺⚡🇳 ⚡🇱⚡🇪⚡🇬⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇮 ⚡🇬⚡🇦⚡🇳⚡🇩 ⚡🇲⚡🇪⚡🇮 ?",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇮 ⚡🇧⚡🇦⚡🇨⚡🇭⚡🇮 ⚡🇨⚡🇴⚡🇩⚡🇺..",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇧⚡🇭⚡🇪⚡🇳 ⚡🇰⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇹 ⚡🇦⚡🇯 ⚡🇫⚡🇦⚡🇩 ⚡🇩⚡🇺",
        "⚡🇸⚡🇵⚡🇪⚡🇪⚡🇩 ⚡🇱⚡🇪⚡🇰⚡🇷 ⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇭⚡🇦",
        "⚡🇸⚡🇵⚡🇪⚡🇪⚡🇩 ⚡🇳⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇪 ⚡🇦⚡🇳⚡🇩⚡🇷 ⚡🇼⚡🇪⚡🇦⚡🇰 ⚡🇵⚡🇷⚡🇴⚡🇸⚡🇳",
        "⚡🇺⚡🇬⚡🇱⚡🇾 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇨⚡🇭⚡🇺⚡🇵",
        "⚡🇲⚡🇦⚡🇰⚡🇦⚡🇫⚡🇺⚡🇩⚡🇩⚡🇦⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇹⚡🇪⚡🇷⚡🇦 ⚡🇧⚡🇦⚡🇦⚡🇵 ⚡🇰⚡🇴 ⚡🇹⚡🇦⚡🇬 ⚡🇰⚡🇷..?",
        "⚡🇦⚡🇨⚡🇭⚡🇪 ⚡🇸⚡🇪 ⚡🇹⚡🇦⚡🇬 ⚡🇰⚡🇷 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮⚡🇧⚡🇦⚡🇦⚡🇿 ⚡🇧⚡🇭⚡🇦⚡🇬⚡🇼⚡🇳 ⚡🇰⚡🇴..",
        "⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇵⚡🇬⚡🇱 ⚡🇳⚡🇾 ⚡🇭⚡🇴 ⚡🇹⚡🇺",
        "⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇵⚡🇬⚡🇱 ⚡🇭⚡🇴 ⚡🇷⚡🇭⚡🇦 ⚡🇹⚡🇺 ⚡🇰⚡🇮⚡🇩",
        "⚡🇲⚡🇦 ⚡🇹⚡🇴 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇭⚡🇦⚡🇼⚡🇦⚡🇧⚡🇿⚡🇮 ⚡🇨⚡🇷..",
        "⚡🇧⚡🇸 ⚡🇲⚡🇦 ⚡🇨⚡🇴⚡🇩⚡🇳⚡🇮 ⚡🇪⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇹⚡🇴⚡🇼⚡🇳 ⚡🇲⚡🇪⚡🇮 ⚡🇨⚡🇺⚡🇩 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇴 ⚡🇱⚡🇪⚡🇰⚡🇷",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇸⚡🇪⚡🇽⚡🇾 ⚡🇰⚡🇴 ⚡🇧⚡🇪⚡🇯 - ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮⚡🇧⚡🇦⚡🇦⚡🇿 ⚡🇧⚡🇭⚡🇬⚡🇼⚡🇳 ⚡🇵⚡🇪",
        "⚡🇸⚡🇵⚡🇪⚡🇪⚡🇩 ⚡🇵⚡🇰⚡🇩 ⚡🇨⚡🇵 ⚡🇳⚡🇾 ⚡🇰⚡🇷",
        "⚡🇹⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇷⚡🇪⚡🇳⚡🇩⚡🇾",
        "⚡🇧⚡🇭⚡🇰⚡🇰 ⚡🇨⚡🇺⚡🇩",
        "⚡🇹⚡🇪⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇮",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇧⚡🇪⚡🇭⚡🇪⚡🇳 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮",
        "⚡🇨⚡🇺⚡🇩 ⚡🇯⚡🇦",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇩⚡🇮⚡🇩⚡🇮 ⚡🇷⚡🇳⚡🇩⚡🇮",
        "⚡🇸⚡🇱⚡🇴⚡🇼",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇮⚡🇾⚡🇦 ⚡🇨⚡🇮⚡🇴⚡🇩⚡🇺",
        "⚡🇧⚡🇭⚡🇦⚡🇬?",
        "⚡🇧⚡🇭⚡🇦⚡🇰 ⚡🇨⚡🇺⚡🇩",
        "⚡🇹⚡🇲⚡🇦 ⚡🇨⚡🇴⚡🇩⚡🇺",
        "⚡🇸⚡🇱⚡🇴⚡🇼",
        "⚡🇸⚡🇱⚡🇴⚡🇼 ⚡🇫⚡🇮⚡🇷⚡🇸⚡🇪",
        "⚡🇨⚡🇺⚡🇩⚡🇬⚡🇷⚡🇮⚡🇧",
        "⚡🇹⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇩⚡🇴⚡🇺",
        "⚡🇹⚡🇧⚡🇰⚡🇨 ⚡🇨⚡🇴⚡🇩⚡🇺",
        "⚡🇳⚡🇪⚡🇹 ⚡🇴⚡🇳 ⚡🇴⚡🇫⚡🇫 ⚡🇼⚡🇦⚡🇱⚡🇮 ⚡🇷⚡🇳⚡🇩⚡🇾",
        "⚡🇴⚡🇾⚡🇪 ⚡🇹⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇴⚡🇩⚡🇺",
        "⚡🇮⚡🇩⚡🇭⚡🇦⚡🇷 ⚡🇦⚡🇦⚡🇰⚡🇪 ⚡🇨⚡🇺⚡🇩 ⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇨⚡🇭⚡🇦⚡🇦⚡🇵",
        "⚡🇹⚡🇧⚡🇰⚡🇨 ⚡🇲⚡🇷⚡🇩⚡🇺",
        "⚡🇴⚡🇮 ⚡🇲⚡🇦⚡🇦⚡🇰⚡🇪 ⚡🇱⚡🇴⚡🇩⚡🇪⚡🇪",
        "⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇧⚡🇪⚡🇪⚡🇯",
        "⚡🇹⚡🇲⚡🇰⚡🇨 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇺",
        "⚡🇸⚡🇺⚡🇦⚡🇷 ⚡🇰⚡🇪 ⚡🇧⚡🇪⚡🇪⚡🇯",
        "⚡🇳⚡🇪⚡🇹 ⚡🇴⚡🇫⚡🇫 ⚡🇴⚡🇳 ⚡🇰⚡🇷 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇱⚡🇦⚡🇩⚡🇰⚡🇪",
        "⚡🇹⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇮 ⚡🇰⚡🇪⚡🇸⚡🇪",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇸⚡🇱⚡🇴⚡🇼 ⚡🇲⚡🇦⚡🇩⚡🇭⚡🇦⚡🇷⚡🇨⚡🇴⚡🇩",
        "⚡🇹⚡??⚡🇰⚡🇨 ⚡🇨⚡🇴⚡🇩⚡🇺 ⚡🇰⚡🇷 ⚡🇲⚡🇸⚡🇬 ⚡🇩⚡🇪⚡🇱⚡🇪⚡🇹⚡🇪",
        "⚡🇴⚡🇮 ⚡🇸⚡🇺⚡🇦⚡🇷 ⚡🇰⚡🇪 ⚡🇱⚡🇦⚡🇩⚡🇰⚡🇪",
        "⚡🇹⚡??⚡🇰⚡🇨 ⚡🇫⚡🇺⚡🇫⚡🇮",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇩⚡🇮⚡🇩⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇮",
        "⚡🇹⚡🇲⚡🇰⚡🇨 ⚡🇩⚡🇮⚡🇰⚡🇭⚡🇦",
        "⚡🇨⚡🇺⚡🇩 ⚡🇦⚡🇧",
        "⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇨⚡🇺⚡🇩",
        "⚡🇧⚡🇭⚡🇦⚡🇰 ⚡🇨⚡🇺⚡🇩",
        "⚡🇨⚡🇺⚡🇩⚡🇱⚡🇪 ⚡🇹⚡🇧⚡🇰⚡🇨 ⚡🇲⚡🇷⚡🇺",
        "⚡🇹⚡🇲⚡🇰⚡🇱 ⚡🇨⚡🇺⚡🇩⚡🇱⚡🇪 ⚡🇬⚡🇷⚡🇮⚡🇧",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇧⚡🇪⚡🇭⚡🇪⚡🇳 ⚡🇻⚡🇪⚡🇸⚡🇮⚡🇾⚡🇦⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇮",
        "⚡🇮⚡🇹⚡🇳⚡🇦 ⚡🇬⚡🇳⚡🇩⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇦 ⚡🇹⚡🇺 ⚡🇫⚡🇮⚡🇷⚡🇸⚡🇪 ⚡🇳⚡🇪⚡🇹 ⚡🇴⚡🇳 ⚡🇴⚡🇫⚡🇫",
        "⚡🇬⚡🇷⚡🇮⚡🇧 ⚡🇰⚡🇪 ⚡🇧⚡🇪⚡🇹⚡🇪",
        "⚡🇧⚡🇭⚡🇦⚡🇬 ⚡🇯⚡🇦 ⚡🇱⚡🇴⚡🇩⚡🇪 ⚡🇹⚡🇲⚡🇰⚡🇨 ⚡🇲⚡🇦⚡🇷⚡🇺 ⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦",
        "⚡🇹⚡🇧⚡🇰⚡🇨 ⚡🇲⚡🇷⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦⚡🇦",
        "⚡🇧⚡🇭⚡🇦⚡🇬 ⚡🇹⚡🇲⚡🇰⚡🇨",
        "⚡🇧⚡🇭⚡🇦⚡🇬 ⚡🇹⚡🇧⚡🇰⚡🇨",
        "⚡🇹⚡🇧⚡🇰⚡🇨 ⚡🇲⚡🇪⚡🇾 ⚡🇨⚡🇵",
        "⚡🇨⚡🇵 ⚡🇹⚡🇧⚡🇰⚡🇨 ⚡🇲⚡🇪⚡🇭⚡🇭",
        "⚡🇨⚡🇵 ⚡🇹⚡🇲⚡🇰⚡🇱 ⚡🇲⚡🇪⚡🇭",
        "⚡🇨⚡🇵 ⚡🇧⚡🇴⚡🇱 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪",
        "⚡🇦⚡🇧⚡🇪 ⚡🇨⚡🇵 ⚡🇧⚡🇴⚡🇱 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪",
        "⚡🇩⚡🇴⚡🇺⚡🇧⚡🇱⚡🇪 ⚡🇸⚡🇪⚡🇳⚡🇩 ⚡🇰⚡🇴 ⚡🇨⚡🇵 ⚡🇹⚡🇲⚡🇰⚡🇨 ⚡🇨⚡🇴⚡🇩⚡🇺",
        "⚡🇹⚡🇧⚡🇰⚡🇨 ⚡🇲⚡🇪 ⚡🇨⚡🇵 ⚡🇨⚡🇴⚡🇩 ⚡🇩⚡🇺⚡🇳⚡🇬⚡🇦 ⚡🇦⚡🇦⚡🇯 ⚡🇲⚡🇪⚡🇭⚡🇭",
        "⚡🇭⚡🇹 ⚡🇹⚡🇧⚡🇰⚡🇨 ⚡🇩⚡🇦⚡🇱⚡🇦⚡🇱 ⚡🇰⚡🇪 ⚡🇧⚡🇪⚡🇹⚡🇪.",
        "⚡🇷⚡🇳⚡🇩⚡🇾 ⚡🇯⚡🇱⚡🇩⚡🇮 ⚡🇯⚡🇱⚡🇩⚡🇮 ⚡🇨⚡🇺⚡🇩⚡🇶 ⚡🇹⚡🇷⚡🇾⚡🇲⚡🇦",
        "⚡🇵⚡🇦⚡🇷⚡🇦 ⚡🇱⚡🇮⚡🇰⚡🇭⚡🇪⚡🇬⚡🇦..",
        "⚡🇹⚡🇷⚡🇦 ⚡🇷⚡🇳⚡🇩⚡🇭⚡🇧⚡🇭⚡🇦⚡🇰",
        "⚡🇱⚡🇦⚡🇬⚡🇩⚡🇮 ⚡🇰⚡🇪 ⚡🇱⚡🇦⚡🇩⚡🇨⚡🇪 ⚡🇨⚡🇵 ⚡🇧⚡🇴⚡🇱",
        "⚡🇨⚡🇵 ⚡🇧⚡🇴⚡🇱 ⚡🇱⚡🇦⚡🇬⚡🇩⚡🇮 ⚡🇰⚡🇪 ⚡🇧⚡🇪⚡🇹⚡🇪..",
        "⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇨⚡🇵 ⚡🇧⚡🇴⚡🇱",
        "⚡🇧⚡🇭⚡🇮⚡🇰⚡🇦⚡🇷⚡🇮 ⚡🇱⚡🇺⚡🇳⚡🇩 ⚡🇨⚡🇭⚡🇺⚡🇸 ⚡🇲⚡🇪⚡🇷⚡??.",
        "⚡🇱⚡🇴⚡🇼 ⚡🇱⚡🇪⚡🇻⚡🇪⚡🇱 ⚡🇨⚡🇵 ⚡🇨⚡🇷",
        "⚡🇨⚡🇵 ⚡🇧⚡🇴⚡🇱 ⚡🇱⚡🇴⚡🇼 ⚡🇱⚡🇪⚡🇻⚡🇪⚡🇱 ⚡🇼⚡🇪⚡🇦⚡🇰",
        "⚡🇲⚡🇪⚡🇷⚡🇪 ⚡🇱⚡🇺⚡🇳⚡🇩 ⚡🇵⚡🇪 ⚡🇪⚡🇾 ⚡🇹⚡🇺 ⚡🇭⚡🇮⚡🇯⚡🇩⚡🇪",
        "⚡🇫⚡🇷⚡🇪⚡🇪 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇴",
        "⚡🇫⚡🇷⚡🇪⚡🇪 ⚡🇲⚡🇪⚡🇾 ⚡🇨⚡🇺⚡🇩 ⚡🇹⚡🇺 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪"
        "⚡🇸⚡🇵⚡🇪⚡🇪⚡🇩 ⚡🇳⚡🇾 ⚡🇼⚡🇪⚡🇦⚡🇰 ⚡🇹⚡🇦⚡🇹⚡🇹⚡🇪 ⚡🇹⚡🇪⚡🇷⚡🇲⚡🇪",
        "⚡??⚡🇮⚡🇹⚡🇳⚡🇮 ⚡🇧⚡🇷 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦⚡🇾⚡🇪⚡🇬⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾⚡🇲⚡🇦⚡🇰⚡🇴",
        "⚡🇱⚡🇺⚡🇳⚡🇩 ⚡🇱⚡🇪 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮⚡🇧⚡🇦⚡🇦⚡🇿 ⚡🇧⚡🇦⚡🇵⚡🇰⚡🇦",
        "⚡🇱⚡🇺⚡🇳 ⚡🇨⚡🇺⚡🇸 ⚡🇯⚡🇦⚡🇱⚡🇩⚡🇮 ⚡🇸⚡🇪 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮⚡🇧⚡🇦⚡🇦⚡🇿 ⚡🇧⚡🇦⚡🇵⚡🇰⚡🇦",
        "⚡🇰⚡🇴⚡🇮 ⚡🇳⚡🇾 ⚡🇩⚡🇪⚡🇰⚡🇭 ⚡🇷⚡🇭⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇱⚡🇪 ⚡🇹⚡🇺",
        "⚡🇨⚡🇺⚡🇩⚡🇱⚡🇪 ⚡🇧⚡🇪⚡🇹⚡🇮⚡🇨⚡🇭⚡🇴⚡🇩 ⚡🇦⚡🇨⚡🇭⚡🇪 ⚡🇸⚡🇪",
        "⚡🇲⚡🇦⚡🇰⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇹 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇧⚡🇸 ⚡🇾⚡🇪⚡🇭⚡🇮 ⚡🇯⚡🇦⚡🇳⚡🇹⚡🇦 ⚡🇲⚡🇪⚡🇾",
        "⚡🇨⚡🇵 ⚡🇧⚡🇴⚡🇱⚡🇪⚡🇬⚡🇦 ⚡🇹⚡🇴 ⚡🇹⚡🇲⚡🇰⚡🇨",
        "⚡🇼⚡🇷⚡🇳⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇯⚡🇦⚡🇾⚡🇪⚡🇬⚡🇮",
        "⚡🇸⚡🇱⚡🇴⚡🇼 ⚡🇪⚡🇾 ⚡🇹⚡🇺 ⚡🇰⚡🇮⚡🇩",
        "⚡🇯⚡🇱⚡🇩⚡🇮 ⚡🇱⚡🇮⚡🇰⚡🇭..",
        "⚡🇯⚡🇱⚡🇩⚡🇮 ⚡🇱⚡🇮⚡🇰⚡🇭..",
        "⚡🇹⚡🇾⚡🇲 ⚡🇸⚡🇪 ⚡🇵⚡🇭⚡🇱⚡🇪 ⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇭⚡🇦",
        "⚡🇹⚡🇾⚡🇲 ⚡🇭⚡🇴⚡🇬⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦",
        "⚡🇲⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇹⚡🇾⚡🇲 ⚡🇸⚡🇪 ⚡🇵⚡🇭⚡🇱⚡🇪",
        "⚡🇺⚡🇹⚡🇭 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇨⚡🇪 ⚡🇰⚡🇪 ⚡🇱⚡🇩⚡🇰⚡🇪",
        "⚡🇲⚡🇦⚡🇨⚡🇦⚡🇧⚡🇴⚡🇸⚡🇩⚡🇦⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇨⚡🇴⚡🇳 ⚡🇰⚡🇧 ⚡🇨⚡🇴⚡🇩 ⚡🇩⚡🇮⚡🇦 ⚡🇲⚡🇦⚡🇰⚡🇴 ⚡🇹⚡🇪⚡🇷⚡🇾",
        "⚡🇰⚡🇴⚡🇮 ⚡🇭⚡🇴⚡🇬⚡🇦 ⚡🇹⚡🇲⚡🇱",
        "⚡🇲⚡🇦⚡🇨⚡🇭⚡🇦⚡🇷 ⚡🇨⚡🇺⚡🇩⚡🇱⚡🇪 ⚡🇹⚡🇺",
        "⚡🇲⚡🇪⚡🇳⚡🇺 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇴 ⚡🇨⚡🇴⚡🇩⚡🇳⚡🇦 ⚡🇸⚡🇪",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇴 ⚡🇧⚡🇴⚡🇱 ⚡🇲⚡🇺⚡🇯⚡🇭⚡🇪 ⚡🇨⚡🇴⚡🇩 ⚡🇩⚡🇪",
        "⚡🇧⚡🇸 ⚡🇲⚡🇪⚡🇾 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇸⚡🇪 ⚡🇨⚡🇺⚡🇩⚡🇳⚡🇦 ⚡🇨⚡🇭⚡🇹⚡🇦 ⚡🇭⚡🇺",
        "⚡🇪⚡🇼⚡🇼 ⚡🇲⚡🇦⚡🇰⚡🇦 ⚡🇱⚡🇴⚡🇩⚡🇪 ⚡🇺⚡🇹⚡🇭",
        "⚡🇲⚡🇪⚡🇴⚡🇼 ⚡🇨⚡🇷 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇴 ⚡🇨⚡🇴⚡🇩⚡🇺",
        "⚡🇱⚡🇺⚡🇳⚡🇩 ⚡🇷⚡🇰⚡🇭 ⚡🇩⚡🇮⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇪 ⚡🇫⚡🇺⚡🇩⚡🇪 ⚡🇵⚡🇪",
        "⚡🇲⚡🇪⚡🇷⚡🇦 ⚡🇱⚡🇺⚡🇳⚡🇩 ⚡🇰⚡🇪 ⚡🇧⚡🇦⚡🇱 ⚡🇺⚡🇹⚡🇭",
        "⚡🇰⚡🇮⚡🇩⚡🇪⚡🇪 ⚡🇿⚡🇮⚡🇳⚡🇩⚡🇦 ⚡🇭⚡🇴",
        "⚡🇲⚡🇦⚡🇷 ⚡🇳⚡🇾 ⚡🇰⚡🇮⚡🇩⚡🇩⚡🇪 ⚡🇹⚡🇾⚡🇵⚡🇪 ⚡🇰⚡🇷",
        "⚡🇨⚡🇭⚡🇺⚡🇵 ⚡🇧⚡🇰⚡🇱",
        "⚡🇧⚡🇨 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇹",
        "⚡🇲⚡🇨 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇫⚡🇦⚡🇸⚡🇹",
        "⚡🇫⚡🇦⚡🇸⚡🇹 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪",
        "⚡🇫⚡🇦⚡🇸⚡🇹 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇰⚡🇦⚡🇲⚡🇿⚡🇴⚡🇷"
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇹 ⚡🇨⚡🇱⚡🇦⚡🇮⚡🇲 ⚡🇨⚡🇷⚡🇼⚡🇦",
        "⚡🇦⚡🇼⚡🇿 ⚡🇳⚡🇮⚡🇨⚡🇭⚡🇪 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇨⚡🇪 ⚡🇰⚡🇪 ⚡🇧⚡🇨⚡🇭⚡🇪",
        "⚡🇸⚡🇦⚡🇼⚡🇦⚡🇱 ⚡🇳⚡🇾 ⚡🇵⚡🇺⚡🇨⚡🇭 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇦⚡🇧⚡🇴⚡🇸⚡🇩⚡🇦",
        "⚡🇫⚡🇾⚡🇹⚡🇪⚡🇷 ⚡🇧⚡🇳⚡🇪⚡🇬⚡🇦 ⚡🇱⚡🇦⚡🇬⚡🇩⚡🇪 ⚡🇲⚡🇦⚡🇩⚡🇷⚡🇨⚡🇭⚡🇴⚡🇩",
        "⚡🇴⚡🇾⚡🇪 ⚡🇰⚡🇦⚡🇦⚡🇱⚡🇪 ⚡🇷⚡🇴 ⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇭⚡🇦",
        "⚡🇴⚡🇾⚡🇪 ⚡🇰⚡🇦⚡🇦⚡🇱⚡🇪 ⚡🇷⚡🇴⚡🇴 ⚡🇳⚡🇾",
        "⚡🇸⚡🇭⚡🇴⚡🇷⚡🇹 ⚡🇳⚡🇾 ⚡🇨⚡🇺⚡🇩 ⚡🇹⚡🇺 ⚡🇧⚡🇮⚡🇳⚡🇦 ⚡🇷⚡🇺⚡🇰⚡🇪",
        "⚡🇸⚡🇭⚡🇴⚡🇷⚡🇹 ⚡🇳⚡🇾 ⚡🇨⚡🇺⚡🇩 ⚡🇹⚡🇺 ⚡🇦⚡🇵⚡🇳⚡🇮 ⚡🇲⚡🇦⚡🇰⚡🇴 ⚡🇱⚡🇪⚡🇰⚡🇷",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇪 ⚡🇸⚡🇹⚡🇭 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇧⚡🇭⚡🇪⚡🇳 ⚡🇻⚡🇮 ⚡🇨⚡🇺⚡🇩⚡🇼⚡🇦 ⚡🇱⚡🇪",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇪 ⚡🇸⚡🇹⚡🇭 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇩⚡🇮⚡🇩⚡🇮 ⚡🇻⚡🇮 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮",
        "⚡🇨⚡🇭⚡🇦⚡🇹 ⚡🇫⚡🇾⚡🇹⚡🇪⚡🇷 ⚡🇧⚡🇳⚡🇪⚡🇬⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇨⚡🇪 ⚡🇨⚡🇴⚡🇩⚡🇺 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇰⚡🇴",
        "⚡🇧⚡🇴⚡🇱 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮⚡🇧⚡🇦⚡🇦⚡🇿 ⚡🇩⚡🇦⚡🇩⚡🇩⚡🇾 ⚡🇪⚡🇾",
        "⚡🇧⚡🇺⚡🇱⚡🇱⚡🇾🇽 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇺⚡🇹⚡🇭",
        "⚡🇲⚡🇦⚡🇷 ⚡🇲⚡🇦⚡🇷⚡🇰⚡🇪 ⚡🇨⚡🇺⚡🇩 ⚡🇷⚡🇭⚡🇦 ⚡🇹⚡🇺",
        "⚡🇴⚡🇷 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦 ⚡🇲⚡🇦⚡🇷⚡🇰⚡🇪 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇦⚡🇮"
        "⚡🇯⚡🇦⚡🇱⚡🇩⚡🇮 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇷⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇧⚡🇪⚡🇯",
        "⚡🇴⚡🇷 ⚡🇧⚡🇩⚡🇦 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇹⚡🇲⚡🇨",
        "⚡🇴⚡🇷 ⚡🇧⚡🇩⚡🇦 2 ⚡🇱⚡🇮⚡🇳⚡🇪 ⚡🇼⚡🇱⚡🇦 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇹⚡🇲⚡🇰⚡🇨",
        "⚡🇴⚡🇷 ⚡🇧⚡??⚡🇦 ⚡🇴⚡🇾⚡🇪 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇹⚡🇲⚡🇱",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇰⚡🇦 ⚡🇧⚡🇺⚡🇷",
        "⚡🇴⚡🇾⚡🇪 ⚡🇰⚡🇪⚡🇪⚡🇩⚡🇪",
        "⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮 ⚡🇰⚡🇪 ⚡🇱⚡🇦⚡🇩⚡🇰⚡🇪",
        "⚡🇯⚡🇦⚡🇱⚡🇩⚡🇮 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇧⚡🇪⚡🇭⚡🇪⚡🇳 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇺",
        "⚡🇲⚡🇰⚡🇱 ⚡🇺⚡🇹⚡🇭 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮 ⚡🇰⚡🇪 ⚡🇧⚡🇦⚡🇨⚡🇨⚡🇭⚡🇪",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇳⚡🇦⚡🇳⚡🇮 ⚡🇲⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦⚡🇱",
        "⚡🇹⚡🇪⚡🇯 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇨⚡🇪",
        "⚡🇴⚡🇾⚡🇪 ⚡🇲⚡🇦⚡🇦⚡🇰⚡🇪 ⚡🇱⚡🇴⚡🇩⚡🇪 ⚡🇲⚡🇷⚡🇪⚡🇳⚡🇬⚡🇦",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇾",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇮⚡🇾⚡🇦 ⚡🇰⚡🇮 ⚡🇬⚡🇦⚡🇳⚡🇩",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇩⚡🇦⚡🇩⚡🇮 ⚡🇰⚡🇦 ⚡🇫⚡🇺⚡🇩⚡🇩⚡🇦",
        "⚡🇲⚡🇰⚡🇱 ⚡🇺⚡🇹⚡🇭 ⚡🇧⚡🇪⚡🇭⚡🇪⚡🇳⚡🇨⚡🇴⚡🇩",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇰⚡🇮 ⚡🇧⚡🇺⚡🇷 ⚡🇩⚡🇪",
        "⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇰⚡🇦 ⚡🇫⚡🇺⚡🇩⚡🇩⚡🇦 ⚡🇲⚡🇪 ⚡🇱⚡🇦⚡🇺⚡🇩⚡🇦",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇺⚡🇩⚡🇻⚡🇦",
        "⚡🇷⚡🇦⚡🇳⚡🇩⚡🇮 ⚡🇰⚡🇪 ⚡🇧⚡🇪⚡🇹⚡🇪 ⚡🇲⚡🇦⚡🇷 ⚡🇬⚡🇦⚡🇾⚡🇦",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇰⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇹 ⚡🇲⚡🇷⚡🇺",
        "⚡🇯⚡🇦⚡🇱⚡🇮⚡🇩 ⚡🇰⚡🇷 ⚡🇸⚡🇵⚡🇦⚡🇲",
        "⚡🇲⚡🇨 ⚡🇸⚡🇵⚡🇦⚡🇲 ⚡🇷⚡🇴⚡🇰⚡🇪⚡🇳⚡🇬⚡🇦",
        "⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦⚡🇰⚡🇮 ⚡🇨⚡🇭⚡🇺⚡🇹 ⚡🇸⚡🇵⚡🇦⚡🇲 ⚡🇰⚡🇷",
        "⚡🇸⚡🇵⚡🇦⚡🇲 ⚡🇰⚡🇷.⚡🇲⚡🇦⚡🇦⚡🇰⚡🇪 ⚡🇱⚡🇴⚡🇩⚡🇪",
        "⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇪 ⚡🇸⚡🇵⚡🇦⚡🇲 ⚡🇰⚡🇷 ⚡🇼⚡🇷⚡🇳⚡🇦 ⚡🇨⚡🇺⚡🇩 ⚡🇹⚡🇺",
        "⚡🇸⚡🇵⚡🇦⚡🇲 ⚡🇰⚡🇷 ⚡🇰⚡🇮⚡🇩",
        "⚡🇳⚡🇴⚡🇴⚡🇧 ⚡🇹⚡🇪⚡🇷⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇨⚡🇭⚡🇴⚡🇩⚡🇺",
        "⚡🇷⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇧⚡🇪⚡🇹⚡🇪 ⚡🇲⚡🇦⚡🇷 ⚡🇲⚡🇦⚡🇹 ⚡🇹⚡🇺",
        "⚡🇳⚡🇴⚡🇴⚡🇧 ⚡🇯⚡🇦⚡🇱⚡🇩⚡🇮 ⚡🇱⚡🇮⚡🇰⚡🇭 ⚡🇼⚡🇷⚡🇳⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇲⚡🇦⚡🇦 ⚡🇷⚡🇦⚡🇳⚡🇩",
        "⚡🇨⚡🇺⚡?? ⚡🇬⚡🇦⚡🇮 ⚡🇲⚡🇦⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇳⚡🇴⚡🇴⚡🇧",
        "⚡🇺⚡🇹⚡🇭 ⚡🇷⚡🇦⚡🇳⚡🇩⚡🇾⚡🇰⚡🇪 ⚡🇳⚡🇴⚡🇴⚡🇧",
        "⚡🇨⚡🇭⚡🇱 ⚡🇨⚡🇺⚡🇩⚡🇰⚡🇪 ⚡🇩⚡🇮⚡🇰⚡🇭⚡🇦 ⚡🇳⚡🇴⚡🇴⚡🇧",
        "⚡🇯⚡🇱⚡🇩⚡🇮 ⚡🇹⚡🇾⚡🇵 ⚡🇨⚡🇷 ⚡🇳⚡🇴⚡🇴⚡🇧 ⚡🇭⚡🇦⚡🇱⚡🇰⚡🇪",
        "⚡🇨⚡🇺⚡🇩 ⚡🇰⚡🇪 ⚡🇵⚡🇬⚡🇱 ⚡🇳⚡🇾 ⚡🇭⚡🇴 ⚡🇳⚡🇴⚡🇴⚡🇧",
        "⚡🇨⚡🇺⚡🇩 ⚡🇨⚡🇺⚡🇩 ⚡🇰⚡🇪 ⚡🇷⚡🇦⚡🇳⚡🇩 ⚡🇧⚡🇳⚡🇯⚡🇦 ⚡🇹⚡🇺 ⚡🇳⚡🇴⚡🇴⚡🇧",
        "⚡🇲⚡🇦⚡🇰⚡🇮⚡🇨⚡🇭⚡🇺⚡🇹 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇳⚡🇴⚡🇴⚡🇧",
        "⚡🇬⚡🇦⚡🇳⚡🇩⚡🇦 ⚡🇨⚡🇾⚡🇺 ⚡🇨⚡🇺⚡🇩 ⚡🇷⚡🇭⚡🇦 ⚡🇹⚡🇺 ?",    "⚡🇮⚡🇹⚡🇳⚡🇦 ⚡🇬⚡🇳⚡🇩⚡🇦 ⚡🇳⚡🇾 ⚡🇨⚡🇺⚡🇩 ⚡🇦⚡🇨⚡🇭⚡🇪 ⚡🇸⚡🇪 ⚡🇨⚡🇺⚡🇩",
        "⚡🇲⚡🇦⚡🇦⚡🇳 ⚡🇱⚡🇪 ⚡🇨⚡🇺⚡🇩 ⚡🇬⚡🇾⚡🇦 ⚡🇹⚡🇺 ⚡🇸⚡🇺⚡🇳 ⚡🇧⚡🇦⚡🇹 ⚡🇦⚡🇧",
        "⚡🇲⚡🇦⚡🇰⚡🇦⚡🇫⚡🇺⚡🇩⚡🇩⚡🇦 ⚡🇫⚡🇦⚡🇹 ⚡🇬⚡🇾⚡🇦 ⚡🇹⚡🇪⚡🇷⚡🇾 ⚡🇷⚡🇺⚡🇰",
        ]
        bas_texts = [
        "★🆂★🅷★🅰★🅽★🆃 ★🅱★🅴★🆃★🅷 ★🅼★🅰★🅳★🆁★🅲★🅷★🅾★🅳 ★🆆★🆁★🅽★🅰 ★🅼★🅰★🅺★🅰★🅱★🅾★🆂★🅳★🅰 ★🆃★🅴★🅴★🆈.",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃..",
        "★🅻★🆆★🅳★🅴 ★🅺★🅴 ★🅱★🅰★🅰★🅰★🅻★🅻★🅻 ★🆃★🅴★🆁★🆈 ★🅼★🅰★🅰 ★🅲★🆄★🅳★🅺★🅴 ★🅿★🅶★🅻 ★🅳★🅴★🅺★🅷.",
        "★🅼★🅰★🅲★🅷★🅰★🆁 ★🅺★🅸 ★🅹★🅷★🅰★🅰★🆃 ★🅺★🅴 ★🅱★🅰★🅰★🅰★🅻★🅻★🅻★🅻 ★🅲★🆄★🅳 ★🅰★🅲★🅷★🅴 ★🆂★🅴 ★🆈★🅷★🅰★🅿★🅴 ★🆃★🅤",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅼 ★🅳★🆄 ★🆃★🅰★🅿★🅰 ★🆃★🅰★🅿?",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅺★🅰 ★🅱★🅷★🅾★🅱★🅴★🅰★🅰",
        "★🆃★🅴★🆁★🅸 ★🅱★🅷★🅽 ★🅰★🅱★🅰★🅱★🅴 ★🅱★🅳★🅸 ★🆁★🅰★🅽★🅳★🅸.",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅾★🅰★🅰★🅴 ★🅱★🅰★🅳★🅸 ★🆁★🅰★🅽★🅳★🅳★🅳★🅳★🅳",
        "★🆃★🅴★🆁★🅰 ★🅱★🅰★🅰★🅿 ★🆁★🅰★🅽★🅳★🅸★🅱★🅰★🅰★🅾 ★🅴★🅈 ★🅳★🅴★🅺★🅷",
        "★🅺★🅸★🆃★🅽★🅸 ★🅲★🅷★🅾★🅳★🆄 ★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅰★🅱 ★🅾★🆁..",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅲★🅷★🅾★🅳 ★🅳★🅸 ★🅷★🅼 ★🅽★🅴",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅺★🅴 ★🅱★🅴★🅴★🅻★🅰 ★🅱★🅽★🅴★🅶★🅰 ★🆁★🅾★🅰★🅳 ★🅿★🅴★🅴",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅴★🅺 ★🅳★🅰★🅼 ★🆃★🅾★🅿 ★🅱★🅴★🆇★🆈",
        "★🅼★🅰★🅻★🆄★🅼 ★🅽★🅰 ★🅿★🅷★🆁 ★🅺★🅴★🅰★🅴 ★🅻★🅴★🆃★🅰 ★🅷★🆄 ★🅼 ★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🆃★🅰★🅿★🅰 ★🆃★🅰★🅿★🅿★🅿★🅿★🅿",
        "★🅻★🆄★🅽★🅳 ★🅺★🅴 ★🅲★🅷★🅾★🅳★🅴 ★🆃★🅤 ★??★🅴★🆁★🅴★🅶★🅰 ★🆃★🆈★🅿★🅸★🅽★🅶 ★🅺★🆁★🅴★🅶★🅰 ★🆃★🅼★🅺★🅲",
        "★🅱★🅴★🅱★🅳 ★🅿★🅺★🅳 ★🅻★🆆★🅳★🅴★🅴★🅴★🅴 ★🆆★🆁★🅽★🅰 ★🅼★🅴★🆁★🅰 ★🅻★🆄★🅽★🅳 ★🅿★🅺★🅳",
        "★🅱★🅰★🅰★🅿 ★🅺★🅸 ★🅱★🅴★🅱★🅳 ★🅼★🆃★🅲★🅷 ★🅺★🆁★🆁★🆁",
        "★🅻★🆆★🅳★🅰 ★🅻★🅴 ★🅼★🅴★🆁★🅰 ★🅹★🅰★🅻★🅳★🅸 ★🆂★🅴 ★🆃★🅤",
        "★🅿★🅰★🅿★🅰 ★🅺★🅸 ★🅱★🅴★🅱★🅳 ★🅼★🆃★🅲★🅷 ★🅽★🅷★🅸 ★🅷★🅾 ★🆁★🅷★🅸 ★🅺★🆈★🅰 ★🆃★??★🆁★🅴★🆂★🅴",
        "★🅰★🅻★🅴 ★🅰★🅻★🅴 ★🅼★🅴★🅻★🅰 ★🅱★🅲★🅷★🅰★🅰★🅰 ★🆃★🅴★🆁★🆈 ★🅼★🅰★🅺★🅰 ★🅱★🅾★🅂★🅳★🅰 ★🆂★🆄★🅽",
        "★🅲★🅷★🆄★🅳 ★🅶★🆈★🅰 ★🆁★🅰★🅽★🅳★🅸★🅱★🅰★🅰★🅾 ★🅿★🅰★🅿★🅰 ★🅱★🅴★🅴★🅴 ★🆃★🅤",
        "★🅼★🅴★🅽★🆄 ★🅺★🅸 ★🅿★🆃★🅰 ★🆃★🅴★🆁★🆈 ★🅼★🅰 ★🅲★🆄★🅳 ★🅶★🅰★🅸",
        "★🅺★🅾★🅸 ★🅱★🅰★🅰★🆃 ★🅽★🅈 ★🅼★🅰★🅰 ★🆁★🅰★🅽★🅳★🆈 ★🆃★🅴★🆁★🆈",
        "★🅷★🅰★🅷★🅰★🅷★🅰★🅰★🅰★🅰★🅰 ★🅼★🅰★🅺★🅰★🅱★🅾★🅂★🅳★🅰 ★🆃★🅴★🆁★🆈",
        "★🆇★🅷★🆄★🅳 ★🅶★🅰★🅸 ★🅼★🅰★🅰 ★🆃★🅴★🆁★🆈 ★🅺★🅸★🅳★🅰★🅰★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅲★🅷★🆄★🅳 ★🅶★🆈★🅸 ★🅰★🅱 ★🅱★🅰★🆁 ★🅼★🆃 ★🅷★🅾★🅽★🅰",
        "★🆈★🅴 ★🅻★🆄★🅽★🅳 ★🅻★🅴 ★🅼★🅴★🆁★🅰 ★🅲★🅷★🅻 ★🅹★🅰★🅻★🅳★🅸 ★🆂★🅴",
        "★🅺★🅸★🅳★🅰★🅰★🅰 ★🅱★🅰★🆁 ★🅽★🅰 ★🅷★🅾 ★🆃★🅤 ★🅷★🅰★🅷★🅰★🅷★🅷",
        "★🅱★🅷★🅴★🅽 ★🅺★🅴 ★🅻★🆆★🅳★🅴 ★🅱★🅷★🆁★🅼 ★🅺★🆁",
        "★🅺★🅸★🆃★🅽★🅸 ★🅶★🅻★🅸★🅈★🅰 ★🅿★🅳★🆆★🅴★🅶★🅰 ★🅰★🅿★🅽★🅸 ★🅼★🅰 ★🅺★🅾",
        "★🅲★🅷★🆄★🅿 ★🅽★🅰★🅻★🅻★🅸★🅸 ★🆁★🅰★🅽★🅳★🆈★🅺★🅴 ★🅻★🅰★🅳★🅺★🅴",
        "★🅱★🅰★🅰★🆁 ★🅺★🅴 ★🅿★🅸★🅻★🅻★🅴 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅱★🅰★🅳★🅰★🅺 ★🅿★🅁 ★🅻★🅸★🆃★🅰★🅺★🅴 ★🅲★🅷★🅾★🅳 ★🅳★🆄★🅽★🅶★🅰 😂😆🤤",
        "★🅰★🅱★🅴 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅰 ★🅱★🅷★🅾★🅱★🅴★🅰 ★🅼★🅰★🅳★🅴★🆁★🅲★🅷★🅾★🅾★🅳 ★🅺★🆁 ★🅿★🅸★🅻★🅻★🅴 ★🅿★🅰★🅿★🅰 ★🅱★🅴★🅴 ★🅻★🅰★🅳★🅴★🅶★🅰 ★🆃★🅤 😼😂🤤",
        "★🅶★🅰★🅻★🅸 ★🅶★🅰★🅻★🅸 ★🅽★🅴 ★🅱★🅷★🅾★🆁 ★🅷★🅴 ★🆃★🅴★??★🅸 ★🅼★🅰★🅰 ★🆁★🅰★🅽★🅳★🅸 ★🅲★🅷★🅾★🆁 ★🅷★🅴 💋💋💦",
        "★🅰★🅱★🅴 ★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅾 ★🅲★🅷★🅾★🅳★🆄 ★🆁★🅰★🅽★🅳★🅸★🅺★🅴 ★🅿★🅸★🅻★🅻★🅴 ★🅺★🆄★🆃★🆃★🅴 ★🅺★🅴 ★🅲★🅷★🅾★🅳★🅴 😂👻🔥",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅰★🅸★🅱★🅴 ★🅲★🅷★🅾★🅳★🅰 ★🅰★🅸★🅱★🅴 ★🅲★🅷★🅾★🅳★🅰 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅰 ★🅱★🅴★🅳 ★🅿★🅴★🅷★🅸 ★🅼★🆄★🆃★🅷 ★🅳★🅸★🅰 💦💦💦💦",
        "★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅴 ★🅱★🅷★🅾★🅱★🅴★🅳★🅴 ★🅼★🅴 ★🅰★??★🅰★🅶 ★🅻★🅰★🅶★🅰★🅳★🅸★🅰 ★🅼★🅴★🆁★🅰 ★🅼★🅾★🆃★🅰 ★🅻★🆄★🅽★🅳 ★🅳★🅰★🅻★🅺★🅴 🔥🔥💦😆😆",
        "★🆁★🅰★🅽★🅳★🅸★🅺★🅴 ★🅱★🅰★🅲★🅷★🅷★🅴 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅲★🅷★🅾★🅳★🆄 ★🅲★🅷★🅰★🅻 ★🅽★🅸★🅺★🅰★🅻",
        "★🅺★🅸★🆃★🅽★🅰 ★🅲★🅷★🅾★🅳★🆄 ★🆃★🅴★🆁★🅸 ★🆁★🅰★🅽★🅳★🅸 ★🅼★🅰★🅰★🅺★🅸 ★🅲★🅷★🆄★🆃★🅷 ★🅰★🅱★🅱 ★🅰★🅿★🅽★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅾 ★🅱★🅷★🅴★🅹 😆👻🤤",
        "★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅾★🆃★🅾 ★🅲★🅷★🅾★🅳 ★🅲★🅷★🅾★🅳★🅺★🅴 ★🅿★🆄★🆁★🅰 ★🅱★🅰★🅰★🅳 ★🅳★🅸★🅰 ★🅲★🅷★🆄★🆃★🅷 ★🅰★🅱★🅱 ★??★🅴★🆁★🅸 ★🅶★🅱 ★🅺★🅾 ★🅱★🅷★🅴★🅹 😆💦🤤",
        "★🆃★🅴★🆁★🅸 ★🅶★🅱 ★🅺★🅾 ★🅴★🆃★🅽★🅰 ★🅲★🅷★🅾★🅳★🅰 ★🅱★🅴★🅷★🅴★🅽 ★??★🅴 ★🅻★🅾★🅳★🅴 ★🆃★🅴★🆁★🅸 ★🅶★🅱 ★🆃★🅾 ★🅼★🅴★🆁★🅸 ★🆁★🅰★🅽★🅳★🅸 ★🅱★🅰★🅽★🅶★🅰★🆈★🅸 ★🅰★🅱★🅱 ★🅲★🅷★🅰★🅻 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅲★🅷★🅾★🅳★🆃★🅰 ★🅱★🅸★🆁★🅱★🅴 ♥️💦😆😆😆😆",
        "★🅷★🅰★🆁★🅸 ★🅷★🅰★🆁★🅸 ★🅶★🅷★🅰★🅰★🅱 ★🅼★🅴 ★🅹★🅷★🅾★🅿★🅳★🅰 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅰 ★🅱★🅷★🅾★🅱★🅴★🅰 🤣🤣💋💦",
        "★🅲★🅷★🅰★🅻 ★🆃★🅴★🆁★🅴 ★🅱★🅰★🅰★🅿 ★🅺★🅾 ★🅱★🅷★🅴★🅹 ★🆃★🅴★🆁★🅰 ★🅱★🅰★🅱★🅺★🅰 ★🅽★🅷★🅸 ★🅷★🅴 ★🅿★🅰★🅿★🅰 ★🅱★🅴★🅴 ★🅻★🅰★🅳★🅴★🅶★🅰 ★🆃★🅤",
        "★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅸 ★🅲★🅷★🆄★🆃★🅷 ★🅼★🅴 ★🅱★🅾★🅼★🅱 ★🅳★🅰★🅻★🅺★🅴 ★🆄★🅳★🅰 ★🅳★🆄★🅽★🅶★🅰 ★🅼★🅰★🅰★🅺★🅴 ★🅻★🅰★🆆★🅳★🅴",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🆃★🆁★🅰★🅸★🅽 ★🅼★🅴 ★🅻★🅴★🅹★🅰★🅺★🅴 ★🆃★🅾★🅿 ★🅱★🅴★🅳 ★🅿★🅴 ★🅻★🅸★🆃★🅰★🅺★🅴 ★🅲★🅷★🅾★🅳 ★🅳★🆄★🅽★🅶★🅰 ★🅱★🅰★🅰★🆁 ★🅺★🅴 ★🅿★🅸★🅻★🅻★🅴 🤣🤣💋💋",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅴 ★🅽★🆄★🅳★🅴★🅰 ★🅶★🅾★🅾★🅶★🅻★🅴 ★🅿★🅴 ★🆄★🅿★🅻★🅾★🅰★🅳 ★🅺★🅰★🆁★🅳★🆄★🅽★🅶★🅰 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅴 ★🅻★🅰★🅴★🆆★🅳★🅴 👻🔥",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅴 ★🅽★🆄★🅳★🅴★🅰 ★🅶★🅾★🅾★🅶★🅻★🅴 ★🅿★🅴 ★🆄★🅿★🅻★🅾★🅰★🅳 ★🅺★🅰★🆁★🅳★🆄★🅽★🅶★🅰 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅴 ★🅻★🅰★🅴★🆆★🅳★🅴 👻🔥",
        "★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅾 ★🅲★🅷★🅾★🅳 ★??★🅷★🅾★🅳★🅺★🅴 ★🅱★🅰★🅽★🅰★🅺★🅴 ★🅱★🅸★🅳★🅴★🅾 ★🅱★🅰★🅽★🅰★🅺★🅴 ★🆇★🅽★🆇★🆇.★🅲★🅾★🅼 ★🅿★🅴 ★🅽★🅴★🅴★🅻★🅰★🅼 ★🅺★🅰★🆁★🅳★🆄★🅽★🅶★🅰 ★🅺★🆄★🆃★🆃★🅴 ★🅺★🅴 ★🅿★🅸★🅻★🅻★🅴 💦💋",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅸 ★🅲★🅷★🆄★🅳★🅰★🅸 ★🅺★🅾 ★🅿★🅾★🆁★🅽★🅷★🆄★🅱.★🅲★🅾★🅼 ★🅿★🅴 ★🆄★🅿★🅻★🅾★🅰★🅳 ★🅺★🅰★🆁★🅳★🆄★🅽★🅶★🅰 ★🅱★🅰★🅰★🆁 ★🅺★🅴 ★🅲★🅷★🅾★🅳★🅴 🤣💋💦",
        "★🅰★🅱★🅴 ★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅾 ★🅲★🅷★🅾★🅳★🆄 ★🆁★🅰★🅽★🅳★🅸★🅺★🅴 ★🅱★🅰★🅲★🅷★🅷★🅴 ★🆃★🅴★🆁★🅴★🅺★🅾 ★🅲★🅷★🅰★🅺★🅺★🅾 ★🅱★🅴★🅴 ★🅿★🅸★🅻★🆆★🅰★🆅★🆄★🅽★🅶★🅰 ★🆁★🅰★🅽★🅳★🅸★🅺★🅴 ★🅱★🅰★🅲★🅷★🅷★🅴 🤣🤣",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅸 ★🅲★🅷★🆄★🆃★🅷 ★🅱★🅰★🅰★🅳★🅺★🅴 ★🆁★🅰★🅺★🅳★🅸★🅰 ★🅼★🅰★🅰★🅺★🅴 ★🅻★🅾★🅳★🅴 ★🅹★🅰★🅰 ★🅰★🅱★🅱 ★🅱★🅸★🅻★🆆★🅰★🅻★🅴 👄👄",
        "★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅸 ★🅲★🅷★🆄★🆃★🅷 ★🅼★🅴 ★🅼★🅴★🆁★🅰 ★🅻★🆄★🅽★🅳 ★🅺★🅰★🅰★🅻★🅰",
        "★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅻★🅴★🆃★🅸 ★🅼★🅴★🆁★🅸 ★🅻★🆄★🅽★🅳 ★🅱★🅰★🅳★🅴 ★🅼★🅰★🅱★🅰★🅱★🅸 ★🅱★🅴★🅴 ★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅾 ★🅼★🅴★🅽★🅴 ★🅲★🅷★🅾★🅳 ★🅳★🅰★🅻★🅰 ★🅱★🅾★🅷★🅾★🆃 ★🅱★🅰★🅱★🆃★🅴 ★🅱★🅴★🅴",
        "★🅱★🅴★🆃★🅴 ★🆃★🅤 ★🅱★🅰★🅰★🅿 ★🅱★🅴★🅴 ★🅻★🅴★🅶★🅰 ★🅿★🅰★🅽★🅶★🅰 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅰 ★🅺★🅾 ★🅲★🅷★🅾★🅳 ★🅳★🆄★🅽★🅶★🅰 ★🅺★🅰★🆁★🅺★🅴 ★🅽★🅰★🅽★🅶★🅰 💦💋",
        "★🅷★🅰★🅷★🅰★🅷★🅰★🅷 ★🅼★🅴★🆁★🅴 ★🅱★🅴★🆃★🅴 ★🅰★🅶★🅻★🅸 ★🅱★🅰★🅰★🆁 ★🅰★🅿★🅽★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅻★🅴★🅺★🅴 ★🅰★🅰★🆈★🅰 ★🅼★🅰★🆃★🅷 ★🅺★🅰★🆃 ★🅾★🆁 ★🅼★🅴★🆁★🅴 ★🅼★🅾★🆃★🅴 ★🅻★🆄★🅽★🅳 ★🅱★🅴★🅴 ★🅲★🅷★🆄★🅳★🆆★🅰★🆈★🅰 ★🅼★🅰★🆃★🅷 ★🅺★🅰★🆁",
        "★🅲★🅷★🅰★🅻 ★🅱★🅴★🆃★🅰 ★🆃★🆄★🅹★🅷★🅴 ★🅼★🅰★🅰★🅱 ★🅺★🅸★🅰 🤣★🆃★🅤 ★🅰★🅱★🅱 ★🅰★🅿★🅽★🅸 ★🅼★🅰★🅺★🅾 ★🅱★🅷★🅴★🅹",
        "★🅱★🅷★🅰★🆁★🅰★🅼 ★🅺★🅰★🆁 ★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅰 ★🅱★🅷★🅾★🅱★🅴★🅳★🅰 ★🅺★🅸★🆃★🅽★🅰 ★🅶★🅰★🅰★??★🅸★🅰 ★🅱★🆄★🅽★🆆★🅰★🆈★🅴★🅶★🅰 ★🅰★🅿★🅽★🅸 ★🅼★🅰★🅰★🅰 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅴 ★🆄★🅿★🅴★🆁",
        "★🅰★🅱★🅴 ★🆁★🅰★🅽★🅳★🅸★🅺★🅴 ★🅱★🅰★🅲★🅷★🅷★🅴 ★🅰★🆄★🅺★🅰★🆃 ★🅽★🅷★🅸 ★🅷★🅴★🆃★🅾 ★🅰★🅿★🅽★🅸 ★🆁★🅰★🅽★🅳★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅻★🅴★🅺★🅴 ★🅰★🅰★🆈★🅰 ★🅼★🅰★🆃★🅷 ★🅺★🅰★🆁 ★🅷★🅰★🅷★🅰★🅷★🅰★🅷★🅰",
        "★🅺★🅸★🅳★🅾 ★🅼★🅰★🅳★🅰★🆁★🅲★🅷★🅾★🅳 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅲★🅷★🅾★?? ★🅲★🅷★🅾★🅳★🅺★🅴 ★🆃★🅴★🆁★🆁 ★🅻★🅸★🆈★🅴 ★🅱★🅷★🅰★🅸 ★🅳★🅴★🅳★🅸★🆈★🅰",
        "★🅹★🆄★🅽★🅶★🅻★🅴 ★🅼★🅴 ★🅽★🅰★🅲★🅷★🆃★🅰 ★🅷★🅴 ★🅼★🅾★🆁★🅴 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅸 ★🅲★🅷★🆄★🅳★🅰★🅸 ★🅳★🅴★🅺★🅺★🅴 ★🅱★🅰★🅱 ★🅱★🅾★🅻★🆃★🅴 ★🅾★🅽★🅲★🅴 ★🅼★🅾★🆁★🅴 ★🅾★🅽★🅲★🅴 ★🅼★🅾★🆁★🅴 🤣🤣💦💋",
        "★🅶★🅰★??★🅸 ★🅶★🅰★🅻★🅸 ★🅼★🅴 ★🆁★🅴★🅷★🆃★🅰 ★🅷★🅴 ★🅱★🅰★🅽★🅳 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅲★🅷★🅾★🅳 ★🅳★🅰★🅻★🅰 ★🅾★🆁 ★🅱★🅰★🅽★🅰 ★🅳★🅸★🅰 ★🆁★🅰★🅽★🅳 🤤🤣",
        "★🅱★🅰★🅱 ★🅱★🅾★🅻★🆃★🅴 ★🅼★🆄★🅹★🅷★🅺★🅾 ★🅿★🅰★🅿★🅰 ★🅲★🆈★🆄★🅺★🅸 ★🅼★🅴★🅽★🅴 ★🅺★🆁★🅳★🅸★🅰 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅿★🆁★🅴★🅶★🅽★🅴★🅽★🆃 🤣🤣",
        "★🅱★🅰★🅰★🆁 ★🅺★🅴 ★🅿★🅸★🅻★🅻★🅴 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅸 ★🅲★🅷★🆄★🆃★🅷 ★🅼★🅴 ★🅱★🅰★🅰★🆁 ★🅺★🅰 ★🅻★🅾★🆄★🅳★🅰 ★🅾★🆁 ★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅸 ★🅲★🅷★🆄★🆃★🅷 ★🅼★🅴 ★🅼★🅴★🆁★🅰 ★🅻★🅾★🅳★🅰",
        "★🅲★🅷★🅰★🅻 ★🅲★🅷★🅰★🅻 ★🆃★🅤 ★🅰★🅿★🅽★🅸 ★🅼★🅰★🅰★🅺★🅸 ★🅲★🅷★🆄★🅲★🅷★🅸★🆈★🅰 ★🅳★🅸★🅺★🅰",
        "★🅷★🅰★🅷★🅰★🅷★🅰★🅷★🅰 ★🅱★🅰★🅲★🅷★🅷★🅴 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅰★🅺★🅾 ★🅲★🅷★🅾★🅳 ★🅳★🅸★🅰 ★🅽★🅰★🅽★🅶★🅰 ★🅺★🅰★🆁★🅺★🅴",
        "★🆃★🅴★🆁★🅸 ★🅶★🅱 ★🅷★🅴 ★🅱★🅰★🅳★🅸 ★🅱★🅴★🆇★🆈 ★🆄★🅱★🅺★🅾 ★🅿★🅸★🅻★🅰★🅺★🅴 ★🅲★🅷★🅾★🅾★🅳★🅴★🅽★🅶★🅴 ★🅿★🅴★🅿★🅱★🅸",
        "2 ★🆁★🆄★🅿★🅰★🆈 ★🅺★🅸 ★🅿★🅴★🅿★🅱★🅸 ★🆃★🅴★🆁★🅸 ★🅼★🆄★🅼★🅼★🆈 ★🅱★??★🅱★🅱★🅴 ★🅱★🅴★🆇★🆈 💋💦",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅲★🅷★🅴★🅴★🅼★🅱 ★🅱★🅴★🅴 ★🅲★🅷★🆄★🅳★🆆★🅰★🆅★🆄★🅽★🅶★🅰 ★🅼★🅰★🅳★🅴★🆁★🅲★🅷★🅾★🅾★🅳 ★🅺★🅴 ★🅿★🅸★🅻★🅻★🅴 💦🤣",
        "★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅸 ★🅲★🅷★🆄★🆃★🅷 ★🅼★🅴 ★🅼★🆄★🆃★🅷★🅺★🅴 ★🅱★🅰★🆁★🅰★🆁 ★🅷★🅾★🅹★🅰★🆅★🆄★🅽★🅶★🅰 ★🅷★🆄★🅸 ★🅷★🆄★🅸 ★🅷★🆄★🅸",
        "★🅱★🅴★🅱★🅳 ★🅻★🅰★🅰★🅰 ★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅲★🅷★🅾★🅳★🆄 ★🆁★🅰★🅽★🅳★🅸★🅺★🅴 ★🅿★🅸★🅻★🅻★🅴 💋💦🤣",
        "★🅰★🆁★🅴 ★🆁★🅴 ★🅼★🅴★🆁★🅴 ★🅱★🅴★🆃★🅴 ★🅲★🆈★🆄 ★🅱★🅴★🅱★🅳 ★🅿★🅰★🅺★🅰★🅳 ★🅽★🅰 ★🅿★🅰★🅰★🅰 ★🆁★🅰★🅷★🅰 ★🅰★🅿★🅽★🅴 ★🅱★🅰★🅰★🅿 ★🅺★🅰 ★🅷★🅰★🅷★🅰★🅷★🅰 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅲★🆄★🅳 ★🅶★🅰★🅸🤣🤣",
        "★🅱★🆄★🅽 ★🅱★🆄★🅽 ★🅱★🅰★🅰★🆁 ★🅺★🅴 ★🅿★🅸★🅻★🅻★🅴 ★🅹★🅷★🅰★🅽★🆃★🅾 ★🅺★🅴 ★🅱★🅾★🆄★🅳★🅰★🅶★🅰★🆁 ★🅰★🅿★🅽★🅸 ★🅼★🆄★🅼★🅼★🆈 ★🅺★🅸 ★🅽★🆄★🅳★🅴★🅱 ★🅱★🅷★🅴★🅹",
        "★🅰★🅱★🅴 ★🅱★🆄★🅽 ★🅻★🅾★🅳★🅴 ★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅺★🅰 ★🅱★🅷★🅾★🅱★🅴★🅳★🅰 ★🅱★🅰★🅰★🅳 ★🅳★🆄★🅽★🅶★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅾 ★🅺★🅷★🆄★🅻★🅴 ★🅱★🅰★🅹★🅰★🆁 ★🅼★🅴 ★🅲★🅷★🅾★🅳 ★🅳★🅰★🅻★🅰 🤣🤣💋",
        "★🅱★🅷★🆁★🅼 ★🅺★🆁 ★🆃★🅴★🆁★🆈 ★🅼★🅰★🅰 ★🅲★🆄★🅳 ★🅶★🅰★🅸 ★🆈★🅷★🅰",
        "★🅼★🅴★🆁★🅴 ★🅻★🆄★🅽★🅳 ★🅺★🅴 ★🅱★🅰★🅰★🅰★🅰★🅻★🅻★🅻★🅻★🅻 ★🅿★🅺★🅳 ★🅹★🅰★🅻★🅳★🅸 ★🅱★🅴★🅴",
        "★🆃★🅤 ★🅴★🅺 ★🅺★🅰★🅰★🅼 ★🅺★🆁 ★🅰★🅿★🅽★🅸 ★🅼★🅰 ★🅱★🅷★🅴★🅽 ★🅺★🅾 ★🅲★🆄★🅳★🆆★🅰 ★🅻★🅴 ★🅼★🅴★🆁★🅴 ★🅱★🆃★🅷",
        "★🆁★🅽★🅳★🅸 ★🅺★🅴 ★🅻★🅳★🅺★🅴★🅴★🅴★🅴★🅴★🅴★🅴★🅴 ★🅲★🅷★🆄★🅿 ★🅾★🆁 ★🅲★🆄★🅳 ★🆈★🅷★🅰",
        "★🅲★🅷★🆄★🅿 ★🆃★🅼★🅺★🅲 ★🅺★🅸★🅳★🅰★🅰★🅰★🅰★🅰★🅰★🅰★🅰★🅰★🅰★🅰★🅰★🅰",
        "★🅰★🅿★🅽★🅸 ★🅶★🅰★🅰★🅽★🅳 ★🅼★🅴★🅸★🅽 ★🅼★🆄★🆃★🅷★🅸 ★🅳★🅰★🅰★🅻",
        "★🅼★🅴★🆁★🅰 ★🅻★🆄★🅽★🅳 ★🅲★🅷★🅾★🅾★🅱 ★🅹★🅰★🅻★🅳★🅸 ★🅱★🅴★🅴",
        "★🅰★🅿★🅽★🅸 ★🅼★🅰 ★🅺★🅾 ★🅲★🆄★🅱★🆆★🅰 ★🅼★🅴★🆁★🅰 ★🅻★🆄★🅽★🅳",
        "★🅱★🅷★🅴★🅽 ★🅺★🅴 ★🅻★🅰★🆄★🅳★🅴 ★🆃★🅼★🅲",
        "★🅱★🅷★🅴★🅽 ★🅺★🅴 ★🆃★🅰★🅺★🅺★🅴 ★🆃★🅼★🅻",
        "★🅰★🅱★🅻★🅰 ★🆃★🅴★🆁★🅰 ★🅺★🅷★🅰★🅽 ★🅳★🅰★🅽 ★🅲★🅷★🅾★🅳★🅽★🅴 ★🅺★🅸 ★🅱★🅰★🆁★🅸★🅸",
        "★🅱★🅴★🆃★🅴 ★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅱★🅰★🅱★🅱★🅴 ★🅱★🅳★🅸 ★🆁★🅰★🅽★🅳",
        "★🅻★🆄★🅽★🅳 ★🅺★🅴 ★🅱★🅰★🅰★🅰★🅻 ★🅹★🅷★🅰★🆃 ★🅺★🅴 ★🅿★🅸★🅱★🅱★🅱★🆄★🆄★🆄★🆄★🆄★🆄 ★🆃★🅼★🅺★🅲",
        "★🅻★🆄★🅽★🅳 ★🅿★🅴 ★🅻★🆃★🅺★🅸★🆃 ★🅼★🅰★🅰★🅻★🅻★🅻★🅻 ★🅺★🅸 ★🅱★🅾★🅽★🅳 ★🅷 ★🆃★🆄★??★🆄",
        "★🅺★🅰★🅱★🅷 ★🅾★🅱 ★🅳★🅸★🅽 ★🅼★🆄★🆃★🅷 ★🅼★🆁★🅺★🅴 ★🅱★🅾★🅹★🆃★🅰 ★🅼 ★🆃★🅤 ★🅿★🅰★🅸★🅳★🅰 ★🅽★🅰 ★🅷★🅾★🆃★🅰★🅰",
        "★🅶★🅻★🆃★🅸 ★🅺★🆁★🅳★🅸 ★🆃★🆄★🅹★🆆 ★🅿★🅰★🅸★🅳★🅰 ★🅺★🆁★🅺★🅴 ★🆃★🅴★🆁★🆈 ★🅼★🅰 ★🅽★🅴 ★🅰★🅱 ★🅲★🆄★🅳 ★🆃★🅤 ★🆈★🅷★🅰",
        "★🅱★🅴★🅱★🅳 ★🅿★🅺★🅳★🅳★🅳",
        "★🅶★🅰★🅰★🅽★🅳 ★🅼★🅰★🅸★🅽 ★🅻★🆆★🅳★🅰 ★🅳★🅰★🅻 ★🅻★🅴 ★🅰★🅿★🅽★🅸 ★🅼★🅴★🆁★🅰★🅰★🅰",
        "★🅶★🅰★🅰★🅽★🅳 ★🅼★🅴★🅸★🅽 ★🅱★🅰★🅼★🅱★🆄 ★🅳★🅴★🅳★🆄★🅽★🅶★🅰★🅰★🅰★🅰★🅰",
        "★🅶★🅰★🅽★🅳 ★🅱★🆃★🅸 ★🅺★🅴 ★🅱★🅰★🅻★🅺★🅺★🅺 ★🆃★🅤 ★🅲★🆄★🅳 ★🆈★🅷★🅰",
        "★🅶★🅾★🆃★🅴 ★🅺★🅸★🆃★🅽★🅴 ★🅱★🅷★🅸 ★🅱★🅰★🅳★🅴 ★🅷★🅾, ★🅻★🆄★🅽★🅳 ★🅺★🅴 ★🅽★🅸★🅲★🅷★🅴 ★🅷★🅸 ★🆁★🅴★🅷★🆃★🅴 ★🅷★🅰",
        "★🅷★🅰★🅾★??★🅰★🆁 ★🅻★🆄★🅽★🅳 ★🆃★🅴★🆁★🅸 ★🅶★🅰★🅰★🅽★🅳 ★🅼★🅰★🅸★🅽",
        "★🅹★🅷★🅰★🅰★🅽★🆃 ★🅺★🅴 ★🅿★🅸★🅱★🅱★🆄 ★🆃★🅼★🅺★🅲 ★🅱★🆄★🅽",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🅺★🅸 ★🅺★🅰★🅻★🅸 ★🅲★🅷★🆄★🆃",
        "★🅺★🅷★🅾★🆃★🅴★🆈 ★🅺★🅸 ★🅰★🆄★??★🅳★🅰 ★🅴★🆈 ★🆃★🅤 ★🆁★🅰★🅽★🅳★🆈★🅺★🅴",
        "★🅺★🆄★🆃★🆃★🅴 ★🅺★🅰 ★🅰★🆆★🅻★🅰★🆃 ★🅹★🅰★🅸★🅱★🅰 ★🅻★🅶 ★🆁★🅷★🅰 ★🆃★🅤",
        "★🅺★🆄★🆃★🆃★🅴 ★🅺★🅸 ★🅹★🅰★🆃 ★🅹★🅰★🅸★🅱★🅰 ★🅴★🆈 ★🆃★🅤 ",
        "★🅺★🆄★🆃★🆃★🅴 ★🅺★🅴 ★🆃★🅰★🆃★🆃★🅰 ★🅴★🆈 ★🆃★🅤",
        "★🆃★🅴★🆃★🅸 ★🅼★🅰 ★🅺★🅸.★🅲★🅷★🆄★🆃 , ★🆃★🅴★🆁★🅸 ★🅼★🅰 ★🆁★🅽★🅳★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸★🅸",
        "★🅻★🅰★🆅★🅳★🅴 ★🅺★🅴 ★🅱★🅰★🅻 ★🅿★🅺★🅳 ★🅻★🅴 ★🅼★🅴★🆁★🅴",
        "★🅼★🆄★🅷 ★🅼★🅴★🅸 ★🅻★🅴★🅻★🅴 ★🅼★🅴★🆁★🅰 ★🅻★🆄★🅽★🅳",
        "★🅻★🆄★🅽★🅳 ★🅺★🅴 ★🅿★🅰★🅱★🅸★🅽★🅴 ★🅲★🅷★🆄★🅿 ★🅱★🅴★🆃★🅷 ★🅾★🆁 ★🅲★🆄★🅳",
        "★🅼★🅴★🆁★🅴 ★🅻★🆆★🅳★🅴 ★🅺★🅴 ★🅱★🅰★🅰★🅰★🅰★🅻★🅻★🅻",
        "★🅷★🅰★🅷★🅰★🅷★🅰★🅰★🅰★🅰★🅰★🅰 ★🆃★🅴★🆁★🆈 ★🅼★🅰★🅰 ★🅲★🆄★🅳 ★🅶★🅰★🅸",
        "★🆃★🅤 ★🅲★🅷★🆄★🅳 ★🅶★🆈★🅰★🅰★🅰★🅰",
        "★🆁★🅰★🅽★🅳★🅸 ★🅺★🅷★🅰★🅽★🅴 ★🅺★🅸 ★🆄★🅻★🅰★🅳★🅳★🅳",
        "★🅱★🅰★🅳★🅸 ★🅷★🆄★🅸 ★🅶★🅰★🅰★🅽★🅳",
        "★🆃★🅴★🆁★🅸 ★🅶★🅰★🅰★🅽★🅳 ★🅼★🅰★🅸★🅽 ★🅺★🆄★🆃★🅴 ★🅺★🅰 ★🅻★🆄★🅽★🅳",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅰 ★🅱★🅷★🅾★🅱★🅴★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃",
        "★🆃★🅴★🆁★🅴 ★🅶★🅰★🅰★🅽★🅳 ★🅼★🅴★🅸★🅽 ★🅺★🅴★🅴★🅳★🅴 ★🅿★🅰★🅳★🅰★🆈",
        "★🅽★🆈 ★🅽★🆈 ★🆃★🅴★🆁★🆈 ★🅼★🅰★🅰 ★🆁★🅰★🅽★🅳★🅸",
        "★🅱★🆄★🅽★🅽 ★🅼★🅰★🅳★🅴★🆁★🅲★🅷★🅾★🅳 ★🆃★🅼★🅻",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅰 ★🅱★🅷★🅾★🅱★🅴★🅰",
        "★🅱★🅴★🅷★🅴★🅽 ★🅺 ★🅻★🆄★🅽★🅳 ★🅲★🅷★🆄★🅿★🅲★🅷★🅰★🅿 ★🅲★🆄★🅳 ★🆈★🅷★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅰 ★🅲★🅷★🆄★🆃 ★🅺★🅸 ★🅲★🅷★🆃★🅽★🅸★🅸★🅸",
        "★🅼★🅴★🆁★🅰 ★🅻★🅰★🆆★🅳★🅰 ★🅻★🅴★🅻★🅴 ★🆃★🅤 ★🅰★🅶★🅰★🆁 ★🅲★🅷★🅰★🅸★🆈★🅴 ★🆃★🅾★🅷",
        "★🅲★🅷★🆄★🅿 ★🅶★🅰★🅰★🅽★🅳★🆄",
        "★🅲★🅷★🆄★🅿 ★🅲★🅷★🆄★🆃★🅸★🆈★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅿★🅴 ★🅹★🅲★🅱 ★🅲★🅷★🅰★🅳★🅷★🅰★🅰 ★🅳★🆄★🅽★🅶★🅰",
        "★🅱★🅰★🅼★🅹★🅷★🅰★🅰 ★🅻★🅰★🆆★🅳★🅴",
        "★🆈★🅰 ★🅳★🆄 ★🆃★🅴★🆁★🅸 ★🅶★🅰★🅰★🅽★🅳 ★🅼★🅴 ★🆃★🅰★🅿★🅰★🅰 ★🆃★🅰★🅿",
        "★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅼★🅴★🆁★🅰 ★🆁★🅾★🅾 ★🅻★🅴★🆃★🅸 ★🅷★🅰★🅸",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅴 ★🅱★🅰★🅰★🆃★🅷 ★🅼★🅼★🅱 ★🅱★🅰★🅽★🅰★🅰 ★🅲★🅷★🆄★🅺★🅰 ★🅷★🆄",
        "★🆃★🅤 ★🅲★🅷★🆄★🆃★🅸★🆈★🅰 ★🆃★🅴★🆁★🅰 ★🅺★🅷★🅰★🅽★🅳★🅰★🅰★🅽 ★🅲★🅷★🆄★🆃★🅸★🆈★🅰",
        "★🅰★🆄★🆁 ★🅺★🅸★🆃★🅽★🅰 ★🅱★🅾★🅻★🆄 ★🅱★🅴★🆈 ★🅼★🅰★🅽★🅽 ★🅱★🅷★🅰★🆁 ★🅶★🅰★🆈★🅰 ★🅼★🅴★🆁★🅰",
        "★🆃★🅴★🆁★🅸★🅸★🅸★🅸★🅸 ★🅼★🅰★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃★🆃★🆃 ★🅼★🅴 ★🅰★🅱★🅲★🅳 ★🅻★🅸★🅺★🅷 ★🅳★🆄★🅽★🅶★🅰 ★🅼★🅰★🅰 ★🅺★🅴 ★🅻★🅾★🅳★🅴",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅾 ★🅻★🅴★🅺★🅰★🆁 ★🅼★🅰★🅸 ★🅱★🅰★🆁★🅰★🆁",
        "★🆃★🅴★🆁★🆈 ★🅼★🅰★🅰 ★🆁★🅰★🅽★🅸★🅳★🅸★🅸",
        "★🅲★🅷★🆄★🅿 ★🅱★🅰★🅲★🅷★🅴★🅴 ★🆃★🅼★🅺★🅲",
        "★🆃★🅴★🆁★🆈 ★🅼★🅰★🅺★🅾★🅲★🅷★🅾★🅳★🆄",
        "★🆁★🅰★🅽★🅳★🅸 ★🅼★🅰★🅰 ★🆃★🅴★🆁★🆈",
        "★🆃★🅤 ★🆁★🅰★🅽★🅳★🅸 ★🅺★🅴 ★🅿★🅸★🅻★🅻★🅰 ★🅴★🆈",
        "★🆃★🅴★🆁★🅸★🅸★🅸★🅸 ★🅼★🅰★🅰★🅰 ★🅺★🅾 ★🅱★🅷★🅴★🅹★🅹★🅹",
        "★🆃★🅴★🆁★🅰★🅰 ★🅱★🅰★🅰★🅰★🅿 ★🅷★🆄",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅼★🅴 ★🅷★🅰★🅰★🆃 ★🅳★🅰★🅰★🅻★🅻★🅺★🅴 ★🅱★🅷★🅰★🅰★🅶 ★🅹★🅰★🅰★🅽★🆄★🅶★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅾 ★🅱★🅰★🆁★🅰★🅺 ★🅿★🅴 ★🅻★🅴★??★🅰★🅰 ★🅳★🆄★🅽★🅶★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅾 ★🅶★🅱 ★🆁★🅾★🅰★🅳 ★🅿★🅴 ★🅻★🅴★🅹★🅰★🅺★🅴 ★🅱★🅴★🅲★🅷 ★🅳★🆄★🅽★🅶★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅼★🅴★🅰 ★🅺★🅰★🅰★🅻★🅸 ★🅼★🅸★🆃★🅲★🅷",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅱★🅰★🅱★🆃★🅸 ★🆁★🅰★🅽★🅳★🅸 ★🅷★🅰★🅸",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅼★🅴 ★🅺★🅰★🅱★🆄★🆃★🅰★🆁 ★🅳★🅰★🅰★🅻 ★🅺★🅴 ★🅱★🅾★🆄★🅿 ★🅱★🅰★🅽★🅰★🆄★🅽★🅶★🅰 ★🅼★🅰★??★🅰★🆁★🅲★🅷★🅾★🅳",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅰 ★🆁★🅰★🅽★🅳★🅸 ★🅷★🅰★🅸",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅼★🅴 ★🅳★🅴★🆃★🅾★🅻 ★🅳★🅰★🅰★🅻 ★🅳★🆄★🅽★🅶★🅰 ★🅼★🅰★🅳★🅰★🆁★🅲★🅷★🅾★🅳",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅰★🅰 ★🅱★🅷★🅾★🅱★🅴★🅰★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅼★🅴 ★🅻★🅰★🅿★🆃★🅾★🅿",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🆁★🅰★🅽★🅳★🅸 ★🅷★🅰★🅸",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅾 ★🅱★🅸★🅱★🆃★🅰★🆁 ★🅿★🅴 ★🅻★🅴★🆃★🅰★🅰★🅺★🅴 ★🅲★🅷★🅾★🅳★🆄★🅽★🅶★??",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅾 ★🅰★🅼★🅴★🆁★🅸★🅲★🅰 ★🅶★🅷★🆄★🅼★🅰★🆄★🅽★🅶★🅰 ★🅼★🅰★🅳★🅰★🆁★🅲★🅷★🅾★🅳",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅼★🅴 ★🅽★🅰★🅰★🆁★🅸★🆈★🅰★🅻 ★🅿★🅷★🅾★🆁 ★🅳★🆄★🅽★🅶★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅴 ★🅶★🅰★🅽★🅳 ★🅼★🅴 ★🅳★🅴★🆃★🅾★🅻 ★🅳★🅰★🅰★🅻 ★🅳★🆄★🅽★🅶★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅰 ★🅺★🅾 ★🅷★🅾★🆁★🅻★🅸★🅲★🅺★🅱 ★🅿★🅸★🅻★🅰★🆄★🅽★🅶★🅰 ★🅼★🅰★🅳★🅰★🆁★🅲★🅷★🅾★🅳",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅾 ★🅱★🅰★🆁★🅰★🅺 ★🅿★🅴 ★🅻★🅴★🆃★🅰★🅰★🅰 ★🅳★🆄★🅽★🅶★🅰★🅰★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅰★🅰 ★🅱★🅷★🅾★🅱★🅴★🅰",
        "★🅼★🅴★🆁★🅰★🅰 ★🅻★🆄★🅽★🅳 ★🅿★🅰★🅺★🅰★🅳 ★🅻★🅴 ★🅼★🅰★🅳★🅰★🆁★🅲★🅷★🅾★🅳",
        "★🅲★🅷★🆄★🅿 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅰★🅺★🅰★🅰 ★🅱★🅷★🅾★🅱★🅴★🅰★🅰",
        "★🆃★🅴★🆁★🅸★🅸 ★🅼★🅰★🅰 ★🅲★🅷★🆄★🅱 ★🅶★🅴★🆈★🅸 ★🅺★🆈★🅰★🅰 ★🅻★🅰★🆆★🅳★🅴★🅴★🅴",
        "★🆃★🅴★🆁★🅸★🅸 ★🅼★🅰★🅰 ★🅺★🅰★🅰 ★🅱★🅹★🅱★🅾★🅳★🅰★🅰",
        "★🅼★🅰★🅳★🅰★🆁★🅇★🅷★🅾★🅳★🅳★🅳",
        "★🆃★🅴★🆁★🅸★🆄★🆄★🅸 ★🅼★🅰★🅰★🅰 ★🅺★🅰★🅰 ★🅱★🅷★🅱★🅾★🅳★🅰★🅰",
        "★🆃★🅴★🆁★🅸★🅸★🅸★🅸★🅸 ★🅱★🅴★🅷★🅴★🅽★🅽★🅽 ★🅺★🅾 ★🅲★🅷★🅾★🅳★🅳★🅳★🆄★🆄★🆄★🆄 ★🅼★🅰★🅳★🅰★🆁★🅇★🅷★🅾★🅳★🅳★🅳★🅳",
        "★🆃★🅤 ★🅽★🅸★🅺★🅰★🅻 ★🅼★🅰★🅳★🅰★🆁★🅲★🅷★🅾★🅳",
        "★🅲★🅷★🆄★🅿 ★🆁★🅰★🅽★🅳★🅸 ★🅺★🅴 ★🅱★🅰★🅲★🅷★🅴",
        "★🆃★🅴★🆁★🅰 ★🅼★🅰★🅰 ★🅼★🅴★🆁★🅸 ★🅹★🅰★🅰★🅽 ★🅴★🆈",
        "★🆃★🅴★🆁★🅸 ★🅱★🅰★🅱★🅴★🅽 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅾★🅿",
        "★🅹★🅰★🅻★🅳★🅸 ★🅻★🅸★🅺★🅷 ★🆁★🅽★🅳★🆈★🅺★🅴 ★🅱★🅴★🅹",
        "★🅾★🆁 ★🅱★🅳★🅰 ★🅻★🅸★🅺★🅷",
        "★🅾★🆁 ★🅱★🅳★🅰",
        "★🅾★🆁 ★🅱★🅳★🅰 ★🅾★🆈★🅴",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅰 ★🅱★🆄★🆁",
        "★🅾★🆈★🅴 ★🅺★🅴★🅴★🅳★🅴",
        "★🆁★🅰★🅽★🅳★🅸 ★🅺★🅴 ★🅻★🅰★🅳★🅺★🅴",
        "★🅹★🅰★🅻★🅳★🅸 ★🅻★🅸★🅺★🅷 ★🆃★🅴★🆁★🅸 ★🅱★🅴★🅷★🅴★🅽 ★🅲★🅷★🅾★🅳★🆄",
        "★🅼★🅺★🅻 ★🆄★🆃★🅷 ★🆁★🅰★🅽★🅳★🅸 ★🅺★🅴 ★🅱★🅰★🅲★🅲★🅷★🅴",
        "★🆃★🅴★🆁★🅸 ★🅽★🅰★🅽★🅸 ★🅼★🅴★🆁★🅸 ★🅼★🅰★🅰★🅻",
        "★🆃★🅴★🅹 ★🅻★🅸★🅺★🅷 ★🆁★🅰★🅽★🅳★🅲★🅴",
        "★🅾★🆈★🅴 ★🅼★🅰★🅰★🅺★🅴 ★🅻★🅾★🅳★🅴 ★🅼★🆁★🅴★🅽★🅶★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅲★🅷★🅾★🅳★🆈",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅸★🆈★🅰 ★🅺★🅸 ★🅶★🅰★🅽★🅳",
        "★🆃★🅴★🆁★🆈 ★🅳★🅰★🅳★🅸 ★🅺★🅰 ★🅵★🆄★🅳★🅳★🅰",
        "★🅼★🅺★🅻 ★🆄★🆃★🅷 ★🅱★🅴★🅷★🅴★🅽★🅲★🅾★🅳",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅸 ★🅱★🆄★🆁 ★🅳★🅴",
        "★🆃★🅴★🆁★🆈 ★🅼★🅰★🅰 ★🅺★🅰 ★🅵★🆄★🅳★🅳★🅰 ★🅼★🅴 ★🅻★🅰★🆄★🅳★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅲★🅷★🆄★🅳★🆅★🅰",
        "★🆁★🅰★🅽★🅳★🅸 ★🅺★🅴 ★🅱★🅴★🆃★🅴 ★🅼★🅰★🆁 ★🅶★🅰★🆈★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🅼★🆁★🆄",
        "★🅹★🅰★🅻★🅸★🅳 ★🅺★🆁 ★🆂★🅿★🅰★🅼",
        "★🅼★🅲 ★🆂★🅿★🅰★🅼 ★🆁★🅾★🅺★🅴★🅽★🅶★🅰",
        "★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰★🅺★🅸 ★🅲★🅷★🆄★🆃 ★🆂★🅿★🅰★🅼 ★🅺★🆁",
        "★🆂★🅿★🅰★🅼 ★🅺★🆁.★🅼★🅰★🅰★🅺★🅴 ★🅻★🅾★🅳★🅴",
        "★🆁★🅽★🅸★🅳 ★🅺★🅴 ★🅲★🅷★🅾★🅳★🅴 ★🆂★🅿★🅰★🅼 ★🅺★🆁",
        "★🆂★🅿★🅰★🅼 ★🅺★🆁 ★🅺★🅸★🅳",
        "★🅽★🅾★🅾★🅱 ★🆃★🅴★🆁★🅸 ★🅼★🅰★🅰 ★🅲★🅷★🅾★🅳★🆄",
        "★🆁★🅽★🅳★🅸 ★🅺★🅴 ★🅱★🅴★🆃★🅴",
        "★🅽★🅾★🅾★🅱 ★🅹★🅰★🅻★🅳★🅸 ★🅻★🅸★🅺★🅷 ★🆆★🆁★🅽★🅰 ★🆃★🅴★🆁★🆈 ★🅼★🅰★🅰 ★🆁★🅰★🅽★🅳",
        "★🅲★🆄★🅳 ★🅶★🅰★🅸 ★🅼★🅰★🅰 ★🆃★🅴★🆁★🆈 ★🅽★🅾★🅾★🅱",
        "★🆄★🆃★🅷 ★🆁★??★🅽★🅳★🆈★🅺★🅴 ★🅽★🅾★🅾★🅱",
        "★🅲★🅷★🅻 ★🅲★🆄★🅳★🅺★🅴 ★🅳★🅸★🅺★🅷★🅰 ★🅽★🅾★🅾★🅱",
        "★🅹★🅻★🅳★🅸 ★🆃★🆈★🅿 ★🅲★🆁 ★🅽★🅾★🅾★🅱 ★🅷★🅰★🅻★🅺★🅴",
        "★🅲★🆄★🅳 ★🅺★🅴 ★🅿★🅶★🅻 ★🅽★🆈 ★🅷★🅾 ★🅽★🅾★🅾★🅱",
        "★🅲★🆄★🅳 ★🅲★🆄★🅳 ★🅺★🅴 ★🆁★🅰★🅽★🅳 ★🅱★🅽★🅹★🅰 ★🆃★🅤 ★🅽★🅾★🅾★🅱",
        "★🅼★🅰★🅺★🅸★🅲★🅷★🆄★🆃 ★🆃★🅴★🆁★🆈 ★🅽★🅾★🅾★🅱",
        "★🅶★🅰★🅽★🅳★🅰 ★🅲★🆈★🆄 ★🅲★🆄★🅳 ★🆁★🅷★🅰 ★🆃★🆄 ?",
        "★🅸★??★🅽★🅰 ★🅶★🅽★🅳★🅰 ★🅽★🆈 ★🅲★🆄★🅳 ★🅰★🅲★🅷★🅴 ★🆂★🅴 ★🅲★🆄★🅳",
        "★🅼★🅰★🅰★🅽 ★🅻★🅴 ★🅲★🆄★🅳 ★🅶★🆈★🅰 ★🆃★🅤 ★🆂★🆄★🅽 ★🅱★🅰★🆃 ★🅰★🅱",
        "★🅼★🅰★🅺★🅰★🅵★🆄★🅳★🅳★🅰 ★🅵★🅰★🆃 ★🅶★🆈★🅰 ★🆃★🅴★🆁★🆈 ★🆁★🆄★🅺",
        
        ]
            
        gs_texts = [
        """~~~~~ ~~~~~ ~~~~~ ~~~~~
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Pᴀɴɪ Kɪ Tᴀʀᴀʜ Cʜᴏᴅᴀ
        ~~~~~ ~~~~~ ~~~~~ ~~~~~""",
        """████████████████████████████
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴅᴀɪ Kɪ
        ████████████████████████████
        ✦ (🩷) ✦ (❤️) ✦ (🧡) ✦""",
        """☠️☠️☠️☠️☠️☠️☠️☠️☠️☠️☠️☠️
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Zʜᴇʀ Dᴀʟᴀ
        ☠️☠️☠️☠️☠️☠️☠️☠️☠️☠️☠️☠️""",
        """✦━━━━━━━━━━━━━━━━━━━━━━━✦
        🥇 ZA Nᴇ 🥇
        Tᴇʀɪ Mᴀᴀ Kᴏ Gᴏʟᴅ Cʜᴜᴅᴀɪ Dɪ
        ✦━━━━━━━━━━━━━━━━━━━━━━━✦""",
        """🗑️━━━━━━━━━━━━━━━━━🗑️
        ║  ZA Nᴇ  ║
        ║  Tᴇʀɪ Mᴀᴀ Kᴏ Kᴀᴄʀᴀ Bɴᴀʏᴀ ║
        🗑️━━━━━━━━━━━━━━━━━🗑️""",
        """☢️☢️☢️☢️☢️☢️☢️☢️☢️☢️
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴀ Bᴏsᴅᴀ Kʜᴏʟ Dɪʏᴀ
        ☢️☢️☢️☢️☢️☢️☢️☢️☢️☢️""",
        """🚀 Sᴘᴀᴄᴇ Mɪssɪᴏɴ: ZA
        👨‍🚀 Cᴏᴍᴍᴀɴᴅᴇʀ: ZA
        🌍 Tᴀʀɢᴇᴛ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        🌟 Mɪssɪᴏɴ: Cʜᴏᴅ ᴀɴᴅ Dᴇsᴛʀᴏʏ""",
        """⏰ Tɪᴍᴇ: 3:00 AM
        📍 Lᴏᴄᴀᴛɪᴏɴ: Tᴇʀɪ Mᴀᴀ Kᴇ Bʜᴏsᴅᴇ Mᴇ
        👨 ZA Iɴ Aᴄᴛɪᴏɴ
        🎬 Lɪᴠᴇ Sᴛʀᴇᴀᴍɪɴɢ...""",
        """🌧️ Mᴀᴜsᴀᴍ: Bᴀʀɪsʜ
        🌊 Lᴇᴠᴇʟ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Bᴀᴅʜ
        ⚡ ZA Nᴇ Bᴀɴᴅʜ Tᴏᴅᴀ""",
        """📰 Bʀᴇᴀᴋɪɴɢ Nᴇᴡs!
        🗞️ ZA Nᴇ Cʜᴏᴅᴀ
        👑 Tʀᴇɴᴅɪɴɢ #1 Oɴ Tᴇʟᴇɢʀᴀᴍ
        ⭐ ZA""",
        """🎬 Mᴏᴠɪᴇ: ZA
        🎭 Sᴛᴀʀʀɪɴɢ: ZA
        🎟️ Rᴀᴛɪɴɢ: ⭐⭐⭐⭐⭐
        🍿 Bᴏx Oғғɪᴄᴇ: Tᴇʀɪ Mᴀᴀ""",
        """🎮 Gᴀᴍᴇ: ZA
        👾 Pʟᴀʏᴇʀ: ZA
        🏆 Lᴇᴠᴇʟ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        💀 Sᴄᴏʀᴇ: Iɴғɪɴɪᴛʏ""",
        """📋 Mᴇɴᴜ Cᴀʀᴅ:
        🍽️ Mᴀɪɴ Cᴏᴜʀsᴇ: Tᴇʀɪ Mᴀᴀ
        🍜 Sɪᴅᴇ Dɪsʜ: Tᴇʀɪ Bʜᴇɴ
        🍰 Dᴇssᴇʀᴛ: ZA Kᴀ Lᴜɴᴅ
        💵 Pʀɪᴄᴇ: Fʀᴇᴇ Cʜᴜᴅᴀɪ""",
        """🗺️ Nᴀᴠɪɢᴀᴛɪᴏɴ:
        Sᴛᴀʀᴛ: ZA
        Dᴇsᴛɪɴᴀᴛɪᴏɴ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        Dɪsᴛᴀɴᴄᴇ: 0 Mᴇᴛᴇʀs
        ETA: Aʙʜɪ Cʜᴏᴅ Rʜᴀ Hᴜ""",
        """🎵 Nᴏᴡ Pʟᴀʏɪɴɢ:
        🎶 Tʀᴀᴄᴋ: ZA
        🎤 Aʀᴛɪsᴛ: ZA
        💿 Aʟʙᴜᴍ: ZA Sᴇʀɪᴇs
        🔥 Vɪᴇᴡs: 69M""",
        """🏏 Mᴀᴛᴄʜ: ZA Vs Tᴇʀɪ Mᴀᴀ
        🏆 Wɪɴɴᴇʀ: ZA
        📊 Sᴄᴏʀᴇ: Cʜᴏᴅ ᴏᴜᴛ
        🔥 Mᴀɴ ᴏғ ᴛʜᴇ Mᴀᴛᴄʜ: Lᴜɴᴅ""",
        """🏥 Rᴇᴘᴏʀᴛ:
        Dᴏᴄᴛᴏʀ: ZA
        Pᴀᴛɪᴇɴᴛ: Tᴇʀɪ Mᴀᴀ
        Dɪᴀɢɴᴏsɪs: Cʜᴜᴛ Mᴇ Lᴜɴᴅ
        Tʀᴇᴀᴛᴍᴇɴᴛ: Cʜᴏᴅɴᴀ""",
        """🏫 Sᴄʜᴏᴏʟ: ZA Aᴄᴀᴅᴇᴍʏ
        📚 Sᴜʙᴊᴇᴄᴛ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴅᴀɪ 101
        👨‍🏫 Tᴇᴀᴄʜᴇʀ: ZA
        ✅ Cʟᴀss: Iɴ Sᴇssɪᴏɴ""",
        """🛒 Sʜᴏᴘᴘɪɴɢ Cᴀʀᴛ:
        🛍️ Iᴛᴇᴍ: Tᴇʀɪ Mᴀᴀ
        💰 Pʀɪᴄᴇ: Fʀᴇᴇ
        🛒 Bᴏᴜɢʜᴛ Bʏ: ZA
        📦 Sᴛᴀᴛᴜs: Cʜᴏᴅ Dɪʏᴀ""",
        """🏨 Hᴏᴛᴇʟ: ZA Pᴀʟᴀᴄᴇ
        🛏️ Rᴏᴏᴍ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        👤 Gᴜᴇsᴛ: ZA
        ⭐ Rᴀᴛɪɴɢ: 5 Sᴛᴀʀs""",
        """✈️ Fʟɪɢʜᴛ: ZA 101
        🛫 Dᴇᴘᴀʀᴛᴜʀᴇ: ZA
        🛬 Aʀʀɪᴠᴀʟ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        ⏰ Tɪᴍᴇ: Nᴏᴡ""",
        """🚂 Tʀᴀɪɴ: ZA Exᴘʀᴇss
        🚉 Sᴛᴀᴛɪᴏɴ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        👨‍✈️ Dʀɪᴠᴇʀ: ZA
        🕒 Tɪᴍɪɴɢ: 24x7""",
        """🍕 Rᴇsᴛᴀᴜʀᴀɴᴛ: ZA Bᴀᴢᴀᴀʀ
        🍽️ Sᴘᴇᴄɪᴀʟ: Tᴇʀɪ Mᴀᴀ
        👨‍🍳 Cʜᴇғ: ZA
        🍴 Oʀᴅᴇʀ: Cʜᴏᴅ ᴀɴᴅ Gᴏ""",
        """💪 Gʏᴍ: ZA Fɪᴛɴᴇss
        🏋️ Tʀᴀɪɴᴇʀ: ZA
        🎯 Tᴀʀɢᴇᴛ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        ✅ Rᴇsᴜʟᴛ: Pʜᴏᴏʟ Cʜᴏᴅ""",
        """🎉 Pᴀʀᴛʏ: ZA Nɪɢʜᴛ
        🕺 Hᴏsᴛ: ZA
        💃 Gᴜᴇsᴛ: Tᴇʀɪ Mᴀᴀ
        🎵 Sᴏɴɢ: Cʜᴏᴅ Tʜᴇ Fʟᴏᴏʀ""",
        """🏛️ Mᴜsᴇᴜᴍ: ZA Hɪsᴛᴏʀʏ
        🖼️ Exʜɪʙɪᴛ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        🎨 Aʀᴛɪsᴛ: ZA
        📅 Dᴀᴛᴇ: Hᴀʀ Rᴏᴢ""",
        """🦁 Zᴏᴏ: ZA Wᴏʀʟᴅ
        🐯 Mᴀɪɴ Aᴛᴛʀᴀᴄᴛɪᴏɴ: Tᴇʀɪ Mᴀᴀ
        🐺 Kᴇᴇᴘᴇʀ: ZA
        🔥 Sʜᴏᴡ: Cʜᴏᴅᴜɴɢᴀ""",
        """🎪 Cɪʀᴄᴜs: ZA Mᴀsᴛɪ
        🤡 Cʟᴏᴡɴ: ZA
        🎪 Sʜᴏᴡ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴅᴀɪ
        🎟️ Tɪᴄᴋᴇᴛ: Fʀᴇᴇ""",
        """📚 Lɪʙʀᴀʀʏ: ZA Bᴏᴏᴋs
        📖 Bᴏᴏᴋ: ZA
        ✍️ Aᴜᴛʜᴏʀ: ZA
        📕 Cʜᴀᴘᴛᴇʀ: Cʜᴏᴅɴᴀ""",
        """🌸 Gᴀʀᴅᴇɴ: ZA Fʟᴏᴡᴇʀs
        🌹 Mᴀɪɴ Fʟᴏᴡᴇʀ: Tᴇʀɪ Mᴀᴀ
        🌻 Gᴀʀᴅᴇɴᴇʀ: ZA
        💧 Wᴀᴛᴇʀ: Lᴜɴᴅ Kᴀ Pᴀɴɪ""",
        """🏖️ Bᴇᴀᴄʜ: ZA Sʜᴏʀᴇ
        🌊 Wᴀᴠᴇs: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        🏄 Sᴜʀғᴇʀ: ZA
        🌅 Tɪᴍᴇ: Sᴜɴsᴇᴛ Cʜᴏᴅ""",
        """☕ Cᴏғғᴇᴇ Sʜᴏᴘ: ZA Cᴀғᴇ
        🍵 Sᴘᴇᴄɪᴀʟ: Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ
        👨‍🍳 Bᴀʀɪsᴛᴀ: ZA
        💦 Aᴅᴅɪᴛɪᴏɴ: Lᴜɴᴅ Kᴀ Cʀᴇᴀᴍ""",
        """🎰 Cᴀsɪɴᴏ: ZA Pᴀʟᴀᴄᴇ
        🃏 Gᴀᴍᴇ: Cʜᴏᴅ Tʜᴇ ZA
        🎲 Bᴇᴛ: Tᴇʀɪ Mᴀᴀ
        💰 Wɪɴɴᴇʀ: ZA""",
        """🌙 Nɪɢʜᴛ Sʜᴏᴡ:
        🌚 Mᴀɪɴ Aᴛᴛʀᴀᴄᴛɪᴏɴ: Tᴇʀɪ Mᴀᴀ
        🌟 Hᴏsᴛ: ZA
        💫 Pᴇʀғᴏʀᴍᴀɴᴄᴇ: Cʜᴏᴅɴᴀ""",
        """🌋🌋🌋🌋🌋🌋🌋🌋
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Jᴡᴀʟᴀ Pʜᴏᴅɪ
        🌋🌋🌋🌋🌋🌋🌋🌋""",
        """🌊🌊🌊🌊🌊🌊🌊🌊
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Tᴏᴏғᴀɴ Lᴀʏᴀ
        🌊🌊🌊🌊🌊🌊🌊🌊""",
        """🌀🌀🌀🌀🌀🌀🌀🌀
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Bʜᴜᴄʜᴀʟ Lᴀʏɪ
        🌀🌀🌀🌀🌀🌀🌀🌀""",
        """💻💻💻💻💻💻💻💻
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Cʏʙᴇʀ Cʜᴏᴅᴀ
        💻💻💻💻💻💻💻💻""",
        """🤖🤖🤖🤖🤖🤖🤖🤖
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Rᴏʙᴏᴛ Sᴛʏʟᴇ Mᴇ Cʜᴏᴅᴀ
        🤖🤖🤖🤖🤖🤖🤖🤖""",
        """👽👽👽👽👽👽👽👽
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Aʟɪᴇɴ Gʜᴜsᴀʏᴀ
        👽👽👽👽👽👽👽👽""",
        """🐉🔥🐉🔥🐉🔥🐉🔥
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Dʀᴀɢᴏɴ Sᴛʏʟᴇ Mᴇ Cʜᴏᴅᴀ
        🐉🔥🐉🔥🐉🔥🐉🔥""",
        """⚡🔨⚡🔨⚡🔨⚡🔨
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Tʜᴏʀ Kᴀ Hᴀᴍᴍᴇʀ Mᴀʀᴀ
        ⚡🔨⚡🔨⚡🔨⚡🔨""",
        """🦾💥🦾💥🦾💥🦾💥
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Iʀᴏɴ Mᴀɴ Sᴛʏʟᴇ Mᴇ Cʜᴏᴅᴀ
        🦾💥🦾💥🦾💥🦾💥""",
        """💚💢💚💢💚💢💚💢
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Hᴜʟᴋ Sᴛʏʟᴇ Mᴇ Sᴍᴀsʜ Kɪʏᴀ
        💚💢💚💢💚💢💚💢""",
        """🕷️🕸️🕷️🕸️🕷️🕸️🕷️🕸️
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Sᴘɪᴅᴇʀ Wᴇʙ Bɴᴀʏᴀ
        🕷️🕸️🕷️🕸️🕷️🕸️🕷️🕸️""",
        """🦇🌙🦇🌙🦇🌙🦇🌙
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Bᴀᴛᴍᴀɴ Sᴛʏʟᴇ Mᴇ Cʜᴏᴅᴀ
        🦇🌙🦇🌙🦇🌙🦇🌙""",
        """🦸💫🦸💫🦸💫🦸💫
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Sᴜᴘᴇʀᴍᴀɴ Sᴛʏʟᴇ Mᴇ Uᴅᴀʏᴀ
        🦸💫🦸💫🦸💫🦸💫""",
        """🗡️💢🗡️💢🗡️💢🗡️💢
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Wᴏʟᴠᴇʀɪɴᴇ Cʟᴀᴡs Mᴀʀᴇ
        🗡️💢🗡️💢🗡️💢🗡️💢""",
        """🔥💀🔥💀🔥💀🔥💀
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Gʜᴏsᴛ Rɪᴅᴇʀ Gʜᴜsᴀʏᴀ
        🔥💀🔥💀🔥💀🔥💀""",
        """💀🔫💀🔫💀🔫💀🔫
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Pᴜɴɪsʜᴇʀ Dᴀʟᴀ
        💀🔫💀🔫💀🔫💀🔫""",
        """🦸🔫🦸🔫🦸🔫🦸🔫
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Dᴇᴀᴅᴘᴏᴏʟ Sᴛʏʟᴇ Mᴇ Cʜᴏᴅᴀ
        🦸🔫🦸🔫🦸🔫🦸🔫""",
        """🖤👅🖤👅🖤👅🖤👅
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Vᴇɴᴏᴍ Gʜᴜsᴀʏᴀ
        🖤👅🖤👅🖤👅🖤👅""",
        """🃏💚🃏💚🃏💚🃏💚
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Jᴏᴋᴇʀ Kʜᴇʟᴀ
        🃏💚🃏💚🃏💚🃏💚""",
        """💕🔨💕🔨💕🔨💕🔨
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kᴏ Hᴀʀʟᴇʏ Sᴛʏʟᴇ Mᴇ Cʜᴏᴅᴀ
        💕🔨💕🔨💕🔨💕🔨""",
        """⚡💨⚡💨⚡💨⚡💨
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Fʟᴀsʜ Sᴘᴇᴇᴅ Dɪ
        ⚡💨⚡💨⚡💨⚡💨""",
        """🌊🔱🌊🔱🌊🔱🌊🔱
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Aǫᴜᴀᴍᴀɴ Gʜᴜsᴀʏᴀ
        🌊🔱🌊🔱🌊🔱🌊🔱""",
        """👁️💥👁️💥👁️💥👁️💥
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Cʏᴄʟᴏᴘs Bᴇᴀᴍ Mᴀʀᴀ
        👁️💥👁️💥👁️💥👁️💥""",
        """🧲💢🧲💢🧲💢🧲💢
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Mᴀɢɴᴇᴛᴏ Gʜᴜsᴀʏᴀ
        🧲💢🧲💢🧲💢🧲💢""",
        """🌩️⚡🌩️⚡🌩️⚡🌩️⚡
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Sᴛᴏʀᴍ Lᴀʏᴀ
        🌩️⚡🌩️⚡🌩️⚡🌩️⚡""",
        """💋💢💋💢💋💢💋💢
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Rᴏɢᴜᴇ Kɪss Dɪ
        💋💢💋💢💋💢💋💢""",
        """🃏🔥🃏🔥🃏🔥🃏🔥
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Gᴀᴍʙɪᴛ Cᴀʀᴅs Dᴀʟᴇ
        🃏🔥🃏🔥🃏🔥🃏🔥""",
        """💨🌀💨🌀💨🌀💨🌀
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Nɪɢʜᴛᴄʀᴀᴡʟᴇʀ Gʜᴜsᴀʏᴀ
        💨🌀💨🌀💨🌀💨🌀""",
        """💙🌀💙🌀💙🌀💙🌀
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Mʏsᴛɪǫᴜᴇ Gʜᴜsᴀʏᴀ
        💙🌀💙🌀💙🌀💙🌀""",
        """🐾💢🐾💢🐾💢🐾💢
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Bᴇᴀsᴛ Gʜᴜsᴀʏᴀ
        🐾💢🐾💢🐾💢🐾💢""",
        """❄️🧊❄️🧊❄️🧊❄️🧊
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Iᴄᴇᴍᴀɴ Gʜᴜsᴀʏᴀ
        ❄️🧊❄️🧊❄️🧊❄️🧊""",
        """🔥💥🔥💥🔥💥🔥💥
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Pʏʀᴏ Gʜᴜsᴀʏᴀ
        🔥💥🔥💥🔥💥🔥💥""",
        """🌑🌀🌑🌀🌑🌀🌑🌀
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Sʜᴀᴅᴏᴡ Gʜᴜsᴀʏᴀ
        🌑🌀🌑🌀🌑🌀🌑🌀""",
        """🔥🦅🔥🦅🔥🦅🔥🦅
        ZA Nᴇ
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Pʜᴏᴇɴɪx Fɪʀᴇ Dᴀʟɪ
        🔥🦅🔥🦅🔥🦅🔥🦅""",
        """🍔🍔🍔🍔🍔🍔🍔🍔🍔
        ??   😋   🍔
        🍔  🧀   🍔
        🍔  🥩   🍔
        🍔🍔🍔🍔🍔🍔🍔🍔🍔
        
        Tᴇʀɪ Mᴀᴀ Kᴏ Bᴜʀɢᴇʀ Bɴᴀᴋᴇ Kʜᴀʏᴀ""",
        """🍕🍕🍕🍕🍕🍕🍕🍕
        🍕  🍅  🍕
        🍕  🧀  🍕
        🍕  🍕  🍕
        🍕🍕🍕🍕🍕🍕🍕🍕
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Pɪᴢᴢᴀ Dᴀʟᴀ""",
        """🌮🌮🌮🌮🌮🌮🌮🌮
        🌮  😋  🌮
        🌮  🥩  🌮
        🌮  🌮  🌮
        🌮🌮🌮🌮🌮🌮🌮🌮
        
        Tᴇʀɪ Mᴀᴀ Kᴏ Tᴀᴄᴏ Sᴛʏʟᴇ Mᴇ Cʜᴏᴅᴀ""",
        """🍩🍩🍩🍩🍩🍩🍩🍩
        🍩  😋  🍩
        🍩  🍩  🍩
        🍩  🍩  🍩
        🍩🍩🍩🍩🍩🍩🍩🍩
        
        Tᴇʀɪ Mᴀᴀ Kᴏ Dᴏɴᴜᴛ Bɴᴀᴋᴇ Cʜᴏᴅᴀ""",
        """☕☕☕☕☕☕☕☕
        ☕  😋  ☕
        ☕  ☕  ☕
        ☕  ☕  ☕
        ☕☕☕☕☕☕☕☕
        
        Tᴇʀɪ Mᴀᴀ Kᴏ Cᴏғғᴇᴇ Sᴛʏʟᴇ Mᴇ Cʜᴏᴅᴀ""",
        """👑👑👑👑👑👑👑👑
        👑  😎  👑
        👑  👑  👑
        👑  👑  👑
        👑👑👑👑👑👑👑👑
        
        ZA Nᴇ Tᴇʀɪ Mᴀᴀ Kᴏ Cʜᴏᴅᴀ""",
        """💖💖💖💖💖💖💖💖
        💖  😍  💖
        💖  💖  💖
        💖  💖  💖
        💖💖💖💖💖💖💖💖
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Pʏᴀʀ""",
        """💀💀💀💀💀💀💀💀
        💀  😈  💀
        💀  💀  💀
        💀  💀  💀
        💀💀💀💀💀💀💀💀
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴀʀ Gᴀʏɪ""",
        """🔥🔥🔥🔥🔥🔥🔥🔥
        🔥  😈  🔥
        🔥  🔥  🔥
        🔥  🔥  🔥
        🔥🔥🔥🔥🔥🔥🔥🔥
        
        ZA Nᴇ Aᴀɢ Lɢᴀʏɪ""",
        """👻👻👻👻👻👻👻👻
        👻  😱  👻
        👻  👻  👻
        👻  👻  👻
        👻👻👻👻👻👻👻👻
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Gʜᴏsᴛ""",
        """🌈🌈🌈🌈🌈🌈🌈🌈
        🌈  😋  🌈
        🌈  🌈  🌈
        🌈  🌈  🌈
        🌈🌈🌈🌈🌈🌈🌈🌈
        
        Tᴇʀɪ Mᴀᴀ Kᴏ Rᴀɪɴʙᴏᴡ Sᴛʏʟᴇ Mᴇ Cʜᴏᴅᴀ""",
        """💣➖💣➖➖💣➖💣
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🔥             ✨
        /    \\
        💥    💥 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Bᴏᴍʙ Pʜᴏᴅᴜɴɢᴀ""",
        """☢️➖☢️➖➖☢️➖☢️
        🌟        \\         /          🌟
        ⭐️          \\☠️/            ⭐️
        ✨           💀             ✨
        /    \\
        🦴    🦴 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Nᴜᴄʟᴇᴀʀ Aᴛᴛᴀᴄᴋ""",
        """🐉➖🐉➖➖🐉➖🐉
        🌟        \\         /          🌟
        ⭐️          \\🔥/            ⭐️
        ✨           🐲             ✨
        /    \\
        🔥    🔥 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Dʀᴀɢᴏɴ Gʜᴜsᴀʏᴀ""",
        """👿➖👿➖➖👿➖👿
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           👹             ✨
        /    \\
        🔱    🔱 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Dᴇᴍᴏɴ Gʜᴜsᴀʏᴀ""",
        """💀➖💀➖➖💀➖💀
        🌟        \\         /          🌟
        ⭐️          \\☠️/            ⭐️
        ✨           💀             ✨
        /    \\
        🦴    🦴 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴀʀ Gᴀʏɪ""",
        """🔫➖🔫➖➖🔫➖🔫
        🌟        \\         /          🌟
        ⭐️          \\😎/            ⭐️
        ✨           🎯             ✨
        /    \\
        💥    💥 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Tᴀɴᴋ Gʜᴜsᴀʏᴀ""",
        """⚔️➖⚔️➖➖⚔️➖⚔️
        🌟        \\         /          🌟
        ⭐️          \\🗡️/            ⭐️
        ✨           ⚔️             ✨
        /    \\
        🩸    🩸 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Sᴡᴏʀᴅ Gʜᴜsᴀʏᴀ""",
        """🐍➖🐍➖➖🐍➖🐍
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🐍             ✨
        /    \\
        ☠️    ☠️ 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Vɪᴘᴇʀ Gʜᴜsᴀʏᴀ""",
        """🦂➖🦂➖➖🦂➖🦂
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🦂             ✨
        /    \\
        ☠️    ☠️ 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Sᴄᴏʀᴘɪᴏɴ Gʜᴜsᴀʏᴀ""",
        """🐦‍⬛➖🐦‍⬛➖➖🐦‍⬛➖🐦‍⬛
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🖤             ✨
        /    \\
        🪶    🪶 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Rᴀᴠᴇɴ Gʜᴜsᴀʏᴀ""",
        """🐺➖🐺➖➖🐺➖🐺
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🐺             ✨
        /    \\
        🩸    🩸 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Wᴏʟғ Gʜᴜsᴀʏᴀ""",
        """🔥➖🔥➖➖🔥➖🔥
        🌟        \\         /          🌟
        ⭐️          \\🦅/            ⭐️
        ✨           🔥             ✨
        /    \\
        💫    💫 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Pʜᴏᴇɴɪx Gʜᴜsᴀʏᴀ""",
        """🦁➖🦁➖➖🦁➖🦁
        🌟        \\         /          🌟
        ⭐️          \\👑/            ⭐️
        ✨           🦁             ✨
        /    \\
        🩸    🩸 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Lɪᴏɴ Gʜᴜsᴀʏᴀ""",
        """🐯➖🐯➖➖🐯➖🐯
        🌟        \\         /          🌟
        ⭐️          \\🐅/            ⭐️
        ✨           🐯             ✨
        /    \\
        🩸    🩸 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Tɪɢᴇʀ Gʜᴜsᴀʏᴀ""",
        """🦈➖🦈➖➖🦈➖🦈
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🦈             ✨
        /    \\
        🩸    🩸 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Sʜᴀʀᴋ Gʜᴜsᴀʏᴀ""",
        """🦅➖🦅➖➖🦅➖🦅
        🌟        \\         /          🌟
        ⭐️          \\🦅/            ⭐️
        ✨           🦅             ✨
        /    \\
        🪶    🪶 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Eᴀɢʟᴇ Gʜᴜsᴀʏᴀ""",
        """🐂➖🐂➖➖🐂➖🐂
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🐂             ✨
        /    \\
        💥    💥 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Bᴜʟʟ Gʜᴜsᴀʏᴀ""",
        """🦏➖🦏➖➖🦏➖🦏
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🦏             ✨
        /    \\
        💥    💥 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Rʜɪɴᴏ Gʜᴜsᴀʏᴀ""",
        """🐘➖🐘➖➖🐘➖🐘
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🐘             ✨
        /    \\
        💥    💥 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Eʟᴇᴘʜᴀɴᴛ Gʜᴜsᴀʏᴀ""",
        """🦛➖🦛➖➖🦛➖🦛
        🌟        \\         /          🌟
        ⭐️          \\😈/            ⭐️
        ✨           🦛             ✨
        /    \\
        💥    💥 

        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Hɪᴘᴘᴏ Gʜᴜsᴀʏᴀ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  💣  💣  █  █  █
        █  █  █  💣  💣  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Bᴏᴍʙ Pʜᴏᴅᴜɴɢᴀ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  💀  💀  █  █  █
        █  █  █  💀  💀  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴀʀ Gᴀʏɪ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  ☢️  ☢️  █  █  █
        █  █  █  ☢️  ☢️  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Nᴜᴄʟᴇᴀʀ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  🐉  🐉  █  █  █
        █  █  █  🐉  🐉  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Dʀᴀɢᴏɴ Gʜᴜsᴀʏᴀ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  🔫  🔫  █  █  █
        █  █  █  🔫  🔫  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Tᴀɴᴋ Gʜᴜsᴀʏᴀ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  🐍  🐍  █  █  █
        █  █  █  🐍  🐍  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Sᴀᴀᴘ Gʜᴜsᴀʏᴀ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  👿  👿  █  █  █
        █  █  █  👿  👿  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Dᴇᴍᴏɴ Gʜᴜsᴀʏᴀ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  🦈  🦈  █  █  █
        █  █  █  🦈  🦈  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Sʜᴀʀᴋ Gʜᴜsᴀʏᴀ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  🦂  🦂  █  █  █
        █  █  █  🦂  🦂  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Bɪᴄʜʜᴜ Gʜᴜsᴀʏᴀ""",
        """
        ███████████████████████████
        █  ░███████████████████░  █
        █  █  █████████████  █  █
        █  █  █  👻  👻  █  █  █
        █  █  █  👻  👻  █  █  █
        █  █  █████████████  █  █
        █  ░███████████████████░  █
        ███████████████████████████
        
        Tᴇʀɪ Mᴀᴀ Kɪ Cʜᴜᴛ Mᴇ Bʜᴏᴏᴛ Gʜᴜsᴀʏᴀ""",
        ]
            

        # Store all premium raid and spam texts in dicts for easy lookup
        premium_raid_texts = {
        "mr": mr_texts, "mr2": mr2_texts, "br": br_texts, "br2": br2_texts, "br3": br3_texts,
        "sqr": sqr_texts, "sq2": sq2_texts, "cr": cr_texts, "bar": bar_texts, "gr": gr_texts
        }
        premium_spam_texts = {
        "ms": ms_texts, "ms2": ms2_texts, "bs": bs_texts, "bs2": bs2_texts, "bs3": bs3_texts,
        "sqs": sqs_texts, "sqs2": sqs2_texts, "cs": cs_texts, "bas": bas_texts, "gs": gs_texts
        }

        # ─── EXISTING TEXT LISTS (as in original) ──────────────────────────
        reply_list = [
        "⋆｡ﾟ☁︎｡𝐂ʏᴜ 𝐑ᴇ मदरचोद  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के सामने 𝐅ʏᴛᴇʀ 𝐁ᴀɴᴇɢᴀ ⋆𓂃 ོ☼𓂃 😂🔥",
        "नहीं नहीं तेरी मां को 𝐒ɪʀғ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप चोद सकता है ִֶָ𓂃 ࣪ ִֶָ👑་༘࿐ sᴀᴍᴊʜᴀ ʀᴀɴᴅɪᴋᴇ ???",
        "तेरी मां का 𝐒ᴛʏʟɪsʜ भोसड़ा 😱",
        "𝑻𝒆𝒓𝒚 𝒎𝒂𝒂 𝒓𝒂𝒏𝒅𝒂𝒍 𝒉 𝒃𝒂𝒔 𝒃𝒂𝒂𝒕 𝒌𝒉𝒂𝒕𝒂𝒎 😡🔥",
        "सोच तेरी बहन को  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप का गुलाम चोद रहा 😎🔥",
        "Hello hello?? SAAS aarahi है? रण्डी पुत्र 🧘🏻",
        "Shut up रंडीके वरना दुनिया यही बोलेगी तेरी बहन  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  /\\~ 👑 बाप से सही chudi 🥵🔥",
        "ᴛᴜ ᴏʀ ᴛᴇʀɪ ᴍᴀᴀ ᴅᴏɴᴏ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के ʟɴᴅ sᴇ ᴋᴀʙʜɪ ᴜᴛʜ ɴʜɪ ᴘᴀʏᴇ 😂🔥",
        "🇮🇳𝐵𝐻𝐴𝑅𝐴𝑇 𝐻𝐴𝑀𝐴𝑅𝐴 𝐷𝐸𝑆𝐻 𝐻 𝐴𝑈𝑅 𝑈𝑆 𝐷𝐸𝑆𝐻 𝑀𝐸 तेरी मां घर घर जाके SHAMBHOG करती है ! 🛐",
        "⋆｡ﾟ☁︎｡𝐂ʏᴜ 𝐑ᴇ मदरचोद  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के सामने 𝐅ʏᴛᴇʀ 𝐁ᴀɴᴇɢᴀ ⋆𓂃 ོ☼𓂃 😂🔥",
        "नहीं नहीं तेरी मां को 𝐒ɪʀғ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप चोद सकता है ִֶָ𓂃 ࣪ ִֶָ👑་༘࿐ sᴀᴍᴊʜᴀ ʀᴀɴᴅɪᴋᴇ ???",
        "तेरी मां का 𝐒ᴛʏʟɪsʜ भोसड़ा 😱",
        "𝑻𝒆𝒓𝒚 𝒎𝒂𝒂 𝒓𝒂𝒏𝒅𝒂𝒍 𝒉 𝒃𝒂𝒔 𝒃𝒂𝒂𝒕 𝒌𝒉𝒂𝒕𝒂𝒎 😡🔥",
        "सोच तेरी बहन को  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप का गुलाम चोद रहा 😎🔥",
        "Hello hello?? saas aarahi है? रण्डी पुत्र 🧘🏻",
        "Shut up रंडीके वरना दुनिया यही बोलेगी तेरी बहन  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  /\\~ 👑 बाप से सही chudi 🥵🔥",
        "ᴛᴜ ᴏʀ ᴛᴇʀɪ ᴍᴀᴀ ᴅᴏɴᴏ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के ʟɴᴅ sᴇ ᴋᴀʙʜɪ ᴜᴛʜ ɴʜɪ ᴘᴀʏᴇ 😂🔥",
        "🇮🇳𝐵𝐻𝐴𝑅𝐴𝑇 𝐻𝐴𝑀𝐴𝑅𝐴 𝐷𝐸𝑆𝐻 𝐻 𝐴𝑈𝑅 𝑈𝑆 𝐷𝐸𝑆𝐻 𝑀𝐸 तेरी मां घर घर जाके SAMBHOG करती है ! 🛐",
        "⋆｡ﾟ☁︎｡𝐂ʏᴜ 𝐑ᴇ मदरचोद  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के सामने 𝐅ʏᴛᴇʀ 𝐁ᴀɴᴇɢᴀ ⋆𓂃 ོ☼𓂃 😂🔥",
        "नहीं नहीं तेरी मां को 𝐒ɪʀғ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप चोद सकता है ִֶָ𓂃 ࣪ ִֶָ👑་༘࿐ sᴀᴍᴊʜᴀ ʀᴀɴᴅɪᴋᴇ ???",
        "तेरी मां का 𝐒ᴛʏʟɪsʜ भोसड़ा 😱",
        "𝑻𝒆𝒓𝒚 𝒎𝒂𝒂 𝒓𝒂𝒏𝒅𝒂𝒍 𝒉 𝒃𝒂𝒔 𝒃𝒂𝒂𝒕 𝒌𝒉𝒂𝒕𝒂𝒎 😡🔥",
        "सोच तेरी बहन को  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप का गुलाम चोद रहा 😎🔥",
        "Hello hello?? SAAS aarahi है? रण्डी पुत्र 🧘🏻",
        "Shut up रंडीके वरना दुनिया यही बोलेगी तेरी बहन  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  /\\~ 👑 बाप से सही chudi 🥵🔥",
        "ᴛᴜ ᴏʀ ᴛᴇʀɪ ᴍᴀᴀ ᴅᴏɴᴏ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के ʟɴᴅ sᴇ ᴋᴀʙʜɪ ᴜᴛʜ ɴʜɪ ᴘᴀʏᴇ 😂🔥",
        "🇮🇳𝐵𝐻𝐴𝑅𝐴𝑇 𝐻𝐴𝑀𝐴𝑅𝐴 𝐷𝐸𝑆𝐻 𝐻 𝐴𝑈𝑅 𝑈𝑆 𝐷𝐸𝑆𝐻 𝑀𝐸 तेरी मां घर घर जाके SAMBHOG करती है ! 🛐",
        "⋆｡ﾟ☁︎｡𝐂ʏᴜ 𝐑ᴇ मदरचोद  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के सामने 𝐅ʏᴛᴇʀ 𝐁ᴀɴᴇɢᴀ ⋆𓂃 ོ☼𓂃 😂🔥",
        "नहीं नहीं तेरी मां को 𝐒ɪʀғ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप चोद सकता है ִֶָ𓂃 ࣪ ִֶָ👑་༘࿐ sᴀᴍᴊʜᴀ ʀᴀɴᴅɪᴋᴇ ???",
        "तेरी मां का 𝐒ᴛʏʟɪsʜ भोसड़ा 😱",
        "𝑻𝒆𝒓𝒚 𝒎𝒂𝒂 𝒓𝒂𝒏𝒅𝒂𝒍 𝒉 𝒃𝒂𝒔 𝒃𝒂𝒂𝒕 𝒌𝒉𝒂𝒕𝒂𝒎 😡🔥",
        "सोच तेरी बहन को  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप का गुलाम चोद रहा 😎🔥",
        "Hello hello?? SAAS aarahi है? रण्डी पुत्र 🧘🏻",
        "Shut up रंडीके वरना दुनिया यही बोलेगी तेरी बहन  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  /\\~ 👑 बाप से सही chudi 🥵🔥",
        "ᴛᴜ ᴏʀ ᴛᴇʀɪ ᴍᴀᴀ ᴅᴏɴᴏ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के ʟɴᴅ sᴇ ᴋᴀʙʜɪ ᴜᴛʜ ɴʜɪ ᴘᴀʏᴇ 😂🔥",
        "𝙃𝙀𝙔 𝙂𝙊𝙊𝙂𝙇𝙀 𝙁𝙐𝘾𝙆 𝙃𝙄𝙎 𝙈𝙊𝙈 𝙋𝙍𝙊𝙋𝙀𝙍𝙇𝙔",
        "𝙃𝙀𝙔 𝙂𝙊𝙊𝙂𝙇𝙀 𝘼𝙎𝙆 𝙃𝙄𝙈 𝙏𝙊 𝘾𝙊𝙑𝙀𝙍 𝙃𝙄𝙎 𝙈𝙊𝙈'𝙎 𝘼𝙎𝙎",
        "𝙃𝙀𝙔 𝙂𝙊𝙊𝙂𝙇𝙀 𝙁𝙄𝙓 𝙈𝙔 𝘼‌𝙋𝙋𝙊𝙄𝙉𝙏𝙈𝙀𝙉𝙏 𝙒𝙄𝙏𝙃 𝙃𝙄𝙎 𝙎𝙄𝙎",
        "𝙃𝙀𝙔 𝙂𝙊𝙊𝙂𝙇𝙀 𝙁𝙐𝘾𝙆 𝘼𝙉𝘿 𝙏𝙃𝙍𝙊𝙒 𝙏𝙃𝙄𝙎 𝙂𝘼𝙍𝙀𝙀𝘽 𝙎𝙊𝙉",
        "𝙃𝙀𝙔 𝙂𝙊𝙊𝙂𝙇𝙀 𝘿𝙊 𝙉𝙊𝙏 𝙎𝙏𝙊𝙋 𝙁𝙐𝘾𝙆𝙄𝙉𝙂 𝙈𝙔 𝙂𝙐𝙇𝘼‌𝙈",
        "𝙂𝙀𝙈𝙄𝙉𝙄 𝙎𝘼𝙄𝘿  𝙄𝙎 𝙍𝙉𝘿𝙔 𝙋𝙐𝙏𝙍𝘼",
        "𝙋𝙀𝙍𝙋𝙇𝙀𝙓𝙄𝙏𝙔 𝙎𝘼𝙄𝘿 This 𝙄𝙎 𝙂𝙐𝙇𝘼𝙈",
        "𝙂𝙍𝙊𝙆 𝘼𝙄 𝙎𝘼𝙄𝘿 𝙄𝙎 𝙂𝘼𝙍𝙀𝙀𝘽",
        "𝘽𝙊𝙏 𝙎𝘼‌𝙄𝘿  𝙄𝙎 𝘾𝙃𝙐𝘿𝘼𝙆𝘼𝘿",
        "𝙈𝙊𝘿𝙄 𝙎𝘼‌𝙄𝘿  𝙄𝙎 𝙋𝙊𝙇𝙀 𝘿𝘼𝙉𝘾𝙀𝙍",
        "𝙏𝙍𝙐𝙈𝙋 𝙎𝘼𝙄𝘿 THis 𝙄𝙎 𝘽𝙇𝙊𝙊𝘿Y 𝙈𝙊𝙏𝙃𝙀𝙍𝙁*\"𝘾𝙆𝙀𝙍",
        "𝗧𝗢𝗛𝗔𝗥 𝗠𝗨𝗠𝗠𝗬 𝗞𝗜 𝗖𝗛𝗨𝗨‌𝗧 𝗠𝗘𝗜 𝗣𝗨𝗥𝗜 𝗞𝗜 𝗣𝗨𝗥𝗜 𝗞𝗜𝗡𝗚𝗙𝗜𝗦𝗛𝗘𝗥 𝗞𝗜 𝗕𝗢𝗧𝗧𝗟𝗘 𝗗𝗔𝗟 𝗞𝗘 𝗧𝗢𝗗 𝗗𝗨𝗡𝗚𝗔 𝗔𝗡𝗗𝗘𝗥 𝗛𝗜 😱😂🤩",
        "𝐓𝐄𝐑𝐈 𝐌𝐀𝐀 𝐊𝐈 𝐂𝐇𝐔𝐓 𝐌𝐄 ✋ 𝐇𝐀𝐓𝐓𝐇 𝐃𝐀𝐋𝐊𝐄 👶 𝐁𝐀𝐂𝐂𝐇𝐄 𝐍𝐈𝐊𝐀𝐋 𝐃𝐔𝐍𝐆𝐀 😍",
        "𝐓𝐄𝐑𝐀 𝐏𝐄𝐇𝐋𝐀 𝐁𝐀𝐀𝐏 𝐇𝐔 𝐌𝐀𝐃𝐀𝐑𝐂𝐇𝐎𝐃",
        "𝗧𝗘𝗥𝗜 𝗠𝗨𝗠𝗠𝗬 𝗞𝗘 𝗦𝗔𝗔𝗧𝗛 𝗟𝗨𝗗𝗼 𝗞𝗛𝗘𝗟𝗧𝗘 𝗞𝗛𝗘𝗟𝗧𝗘 𝗨𝗦𝗞𝗘 𝗠𝗨𝗛 𝗠𝗘 𝗔𝗣𝗡𝗔 𝗟𝗢𝗗𝗔 𝗗𝗘 𝗗𝗨𝗡𝗚𝗔☝🏻☝🏻😬",
        "𝗧𝗘𝗥𝗜 𝗠𝗔‌𝗔‌ 𝗞𝗜 𝗖𝗛𝗨𝗨‌𝗧 𝗠𝗘 𝗦𝗨𝗧𝗟𝗜 𝗕𝗢𝗠𝗕 𝗙𝗢𝗗 𝗗𝗨𝗡𝗚𝗔 𝗧𝗘𝗥𝗜 𝗠𝗔‌𝗔‌ 𝗞𝗜 𝗝𝗛𝗔𝗔𝗧𝗘 𝗝𝗔𝗟 𝗞𝗘 𝗞𝗛𝗔𝗔𝗞 𝗛𝗢 𝗝𝗔𝗬𝗘𝗚𝗜💣🔥",
        "𝐓𝐄𝐑𝐈 𝐕𝐀𝐇𝐄𝐈𝐍 𝐊𝐎 𝐀𝐏𝐍𝐄 𝐋𝐔𝐍𝐃 𝐏𝐑 𝐈𝐓𝐍𝐀 𝐉𝐇𝐔𝐋𝐀𝐀𝐔𝐍𝐆𝐀 𝐊𝐈 𝐉𝐇𝐔𝐋𝐓𝐄 𝐉𝐇𝐔𝐋𝐓𝐄 𝐇𝐈 𝐁𝐀𝐂𝐇𝐀 𝐏𝐀𝐈𝐃𝐀 𝐊𝐑 𝐃𝐄𝐆𝐈 💦💋",
        "𝐆𝐀𝐋𝐈 𝐆𝐀𝐋𝐈 𝐌𝐄 𝐑𝐄𝐇𝐓𝐀 𝐇𝐄 𝐒𝐀𝐍𝐃 𝐓𝐄𝐑𝐈 𝐌𝐀𝐀𝐊𝐎 𝐂𝐇𝐎𝐃 𝐃𝐀𝐋𝐀 𝐎𝐑 𝐁𝐀𝐍𝐀 𝐃𝐈𝐀 𝐑𝐀𝐍𝐃 🤤🤣",
        "𝐒𝐀𝐁 𝐁𝐎𝐋𝐓𝐄 𝐌𝐔𝐉𝐇𝐊𝐎 𝐏𝐀𝐏𝐀 𝐊𝐘𝐎𝐔𝐍𝐊𝐈 𝐌𝐄𝐍𝐄 𝐁𝐀𝐍𝐀𝐃𝐈𝐀 𝐓𝐄𝐑𝐈 𝐌𝐀𝐀𝐊𝐎 𝐏𝐑𝐄𝐆𝐍𝐄𝐍𝐓 🤣🤣",
        "𝙏𝙀𝙍𝙄 𝘽𝙀𝙃𝙀𝙉 𝙇𝙀𝙏𝙄 𝙈𝙀𝙍𝙄 𝙇𝙐𝙉𝘿 𝘽𝘼𝘿𝙀 𝙈𝘼𝙎𝙏𝙄 𝙎𝙀 𝙏𝙀𝙍𝙄 𝘽𝙀𝙃𝙀𝙉 𝙆𝙊 𝙈𝙀𝙉𝙀 𝘾𝙃𝙊𝘿 𝘿𝘼𝙇𝘼 𝘽𝙊𝙃𝙊𝙏 𝙎𝘼𝙎𝙏𝙀 𝙎𝙀",
        "𝗧𝗘𝗥𝗜 𝗠𝗔‌𝗔‌ 𝗞𝗜 𝗖𝗛𝗨𝗨‌𝗧 𝗠𝗘 𝗖𝗛𝗔𝗡𝗚𝗘𝗦 𝗖𝗢𝗠𝗠𝗜𝗧 𝗞𝗥𝗨𝗚𝗔 𝗙𝗜𝗥 𝗧𝗘𝗥𝗜 𝗕𝗛𝗘𝗘𝗡 𝗞𝗜 𝗖𝗛𝗨𝗨‌𝗧 𝗔𝗨𝗧𝗢𝗠𝗔𝗧𝗜𝗖𝗔𝗟𝗟𝗬 𝗨𝗣𝗗𝗔𝗧𝗘 𝗛𝗢𝗝𝗔𝗔𝗬𝗘𝗚𝗜🤖🙏🤔",
        "𝐓𝐄𝐑𝐈 𝐌𝐀𝐀𝐀𝐊𝐈 𝐂𝐇𝐔𝐃𝐀𝐈 𝐊𝐎 𝐏𝐎𝐑𝐍𝐇𝐔𝐁.𝐂𝐎𝐌 𝐏𝐄 𝐔𝐏𝐋𝐎𝐀𝐃 𝐊𝐀𝐑𝐃𝐔𝐍𝐆𝐀 𝐒𝐔𝐀𝐑 𝐊𝐄 𝐂𝐇𝐎𝐃𝐄 🤣💋💦",
        "𝐓𝐄𝐑𝐈 𝐁𝐀𝐇𝐄𝐍 𝐊𝐈 𝐆𝐀𝐀𝐍𝐃 𝐌𝐄𝐈 𝐎𝐍𝐄𝐏𝐋𝐔𝐒 𝐊𝐀 𝐖𝐑𝐀𝐏 𝐂𝐇𝐀𝐑𝐆𝐄𝐑 𝟑𝟎𝐖 𝐇𝐈𝐆𝐇 𝐏𝐎𝐖𝐄𝐑 💥😂😎",
        "𝐓𝐔𝐉𝐇𝐄 𝐀𝐁 𝐓𝐀𝐊 𝐍𝐀𝐇𝐈 𝐒𝐌𝐉𝐇 𝐀𝐘𝐀 𝐊𝐈 𝐌𝐀𝐈 𝐇𝐈 𝐇𝐔 𝐓𝐔𝐉𝐇𝐄 𝐏𝐀𝐈𝐃𝐀 𝐊𝐀𝐑𝐍𝐄 𝐖𝐀𝐋𝐀 𝐁𝐇𝐎𝐒𝐃𝐈𝐊𝐄𝐄 𝐀𝐏𝐍𝐈 𝐌𝐀𝐀 𝐒𝐄 𝐏𝐔𝐂𝐇 𝐑𝐀𝐍𝐃𝐈 𝐊𝐄 𝐁𝐀𝐂𝐇𝐄𝐄𝐄𝐄 🤩👊👤😍",
        "𝐓𝐄𝐑𝐈 𝐁𝐀𝐇𝐄𝐍 𝐊𝐈 𝐂𝐇𝐔𝐓 𝐌𝐄𝐈 𝐀𝐏𝐏𝐋𝐄 𝐊𝐀 𝟏𝟖𝐖 𝐖𝐀𝐋𝐀 𝐂𝐇𝐀𝐑𝐆𝐄𝐑 🔥🤩",
        "𝗧𝗘𝗥𝗜 𝗠𝗔‌𝗔‌ 𝗞𝗢 𝗜𝗧𝗡𝗔 𝗖𝗛𝗢𝗗𝗨𝗡𝗚𝗔 𝗞𝗜 𝗦𝗔𝗣𝗡𝗘 𝗠𝗘𝗜 𝗕𝗛𝗜 𝗠𝗘𝗥𝗜 𝗖𝗛𝗨𝗗𝗔𝗜 𝗬𝗔𝗔𝗗 𝗞𝗔𝗥𝗘𝗚𝗜 𝗥Æ𝗡𝗗𝗜 🥳😍👊💥",
        "𝙋𝘼𝙋𝘼 𝙆𝙄 𝙎𝙋𝙀𝙀𝘿 𝙈𝙏𝘾𝙃 𝙉𝙃𝙄 𝙃𝙊 𝙍𝙃𝙄 𝙆𝙔𝘼",
        "𝙆𝙄𝙏𝙉𝙄 𝘾𝙃𝙊𝘿𝙐 𝙏𝙀𝙍𝙄 𝙈𝘼 𝘼𝘽 𝙊𝙍..",
        "𝗧𝗘𝗥𝗜 𝗠𝗔𝗨𝗦𝗜 𝗞𝗘 𝗕𝗛𝗢𝗦𝗗𝗘 𝗠𝗘𝗜 𝗜𝗡𝗗𝗜𝗔𝗡 𝗥𝗔𝗜𝗟𝗪𝗔𝗬 🚂💥😂",
        "𝙆𝙄𝙏𝙉𝙄 𝙂𝙇𝙄𝙔𝘼 𝙋𝘿𝙒𝙀𝙂𝘼 𝘼𝙋𝙉𝙄 𝙈𝘼 𝙆𝙊",
        "𝗧𝗘𝗥𝗜 𝗜𝗧𝗘𝗠 𝗞𝗜 𝗚𝗔𝗔𝗡𝗗 𝗠𝗘 𝗟𝗨𝗡𝗗 𝗗𝗔𝗔𝗟𝗞𝗘,𝗧𝗘𝗥𝗘 𝗝𝗔𝗜𝗦𝗔 𝗘𝗞 𝗢𝗥 𝗡𝗜𝗞𝗔𝗔𝗟 𝗗𝗨𝗡𝗚𝗔 𝗠𝗔‌𝗔‌𝗗𝗔𝗥𝗖𝗛Ø𝗗🤘🏻🙌🏻☠️",
        "2 𝙍𝙐𝙋𝘼𝙔 𝙆𝙄 𝙋𝙀𝙋𝙎𝙄 𝙏𝙀𝙍𝙄 𝙈𝙐𝙈𝙈𝙔 𝙎𝘼𝘽𝙎𝙀 𝙎𝙀𝙓𝙔 💋💦",
        "🇮🇳𝐵𝐻𝐴𝑅𝐴𝑇 𝐻𝐴𝑀𝐴𝑅𝐴 𝐷𝐸𝑆𝐻 𝐻 𝐴𝑈𝑅 𝑈𝑆 𝐷𝐸𝑆𝐻 𝑀𝐸 तेरी मां घर घर जाके SAMBHOG करती है ! 🛐"
        "Baap bhi bnale muje rndike",
        "Tera baap randibaaz ey yaad ey tujhe",
        "Tu apni Maa cuda na tympass",
        "Oye unfunny swipe mtt kr",
        "Oh hello bihari tera baap bihari or tu v bihari aaukat me rha kr.",
        "Oyy kinner tujhe gc me aane ki permission kisne di.",
        "Cudke dikha",
        "Cudke dikha ek baar.",
        "Sun sun ma cuda.",
        "Teri maca bhosda.",
        "Oye choti jati ke tmr.",
        "Ky? jldi likh kidde.",
        "Bihari com gang ke baap ko tag crega tu",
        "Mujhe cya tu bihari ey tmkc bs",
        "Jaldi se randibaaz papa bol",
        "Side hoja bihari tery maa cud gai ab",
        "Hye pgl bhg mat ache se cud",
        "bhg ny randyke tu ajj",
        "Hye pgl ke bche bhag mat",
        "Hye dur hatt madchod ke bache",
        "koi bat ny tery maa randy ey esliye maf cr rha hu tujhe",
        "koi baat ny maa chudwa apni tu mafi de dunga",
        "Ache se maa chudwa apni tu mafi mil jayegi tujhe",
        "apni ma mat chuda muje swipe crke",
        "Ache se apni ma cudwa tu swipe crke",
        "Fr bolna na ki cudwa le apni ma swipe crke",
        "Cya hua ma cud gyi tery",
        "pr kese cud gyi tery ma",
        "mujhe pta tha ma cud gai tery",
        "mey ny manta ma cud gyi tery",
        "teri ma rndy",
        "lode se utr mc",
        "lun mt chus mera",
        "nikal madarchd",
        "chup oye gashti k bache",
        "makichut teri",
        "chup rndyke",
        "ma rndy teri",
        "teri ma k hath todh k tere baap k muh me fasadunga randyke",
        "leave le tu rndyke pasand nai aya meko",
        "leave le tu randyke ider se",
        "Leave le jldi se wrna ma chud gai tery",
        "Leave ny lega maa randy tery",
        "Smjh bat maa randy ey tery leave le",
        "fast leave le kamjor randyke",
        "tuto chup rndyk",
        "oy hijde khana kha ke aa kamzor",
        "teri mako ily rey🌚😂",
        "chup chap chud tmkc",
        "chupchap maa chudwa apni tu",
        "shi se maa chudwa apni tu chupchap",
        "fr se maa chudwa tu apni chupchap",
        "shi se likh wrna ma chud gai tery",
        "ma cyu chud gai tery chupchap",
        "proof cr maa chud gyi tery",
        "proof ey tery maa randy ey",
        "proof ho chuka maa randy tery",
        "Chup chillar",
        "chup chup maa k bosda tery",
        "oy hijde khana kha ke aa kamzor",
        "chup madarchod ?",
        "Ab tk cud gyi hogi tery maa ?",
        "ny ny me kuch ny janta bs teri ma rndy ey",
        "Sbse phele apni maa ko bol chudna kaam kre",
        "Yaha bhi chuda tu rndyce pille",
        "terimakabosda",
        "teri to bhen cudegi",
        "chup rndyke tommy",
        "nikal madarchd cudke yha se",
        "coz teri ma andhi randi he",
        "nyto baap bol mujhe",
        "nyny teri maa hogi rndii jo chudwati jogi",
        "try ammi ce bhosde me emoji dal mc",
        "cya ? chmr chud gya cya ?",
        "tm chudri hogi frrto",
        "cya ? kb ? pgl ey cya rndkek",
        "cya sch mey pgl ey cya tu randyke cudwa li tune apni ma",
        "itna sch ny bol ma chud gai tery",
        "sch mey pgl ey tu apni ma cudwa lia mere sth",
        "mtlb tmr",
        "nyto",
        "pura likh mc",
        "tmr frrto",
        "oh ok cudle fir",
        "teri maa ka damad",
        "cya ? ache se likhe pehle rndikebache",
        "nyto teri maa chodne me vyast hu",
        "nyto pgl ey cya kuch bi",
        "oyee cya ? chud gya ?",
        "chud mt hss",
        "yur rndii mom",
        "are sbki maa rndii or teri bi",
        "are idar cudle ek baar",
        "tri maa ci trh",
        "ek line me tmr",
        "Q",
        "ocy ab chudle",
        "pehele teri maa chodu",
        "nyto",
        "q ?",
        "hyyy chud ke dika ek baar",
        "oyee sun dost tmr",
        "bhag ja raand maaf crr dunga",
        "oyee pgl rndii idar aa",
        "cya tmr frrto",
        "oyee idar aake chud le chmr",
        "nyto aese hi cud",
        "oyee hyy aise hi cud lena",
        "or chud le",
        "chud ke dika or",
        "hyy chudo na",
        "chudo mt bhag jao",
        "byyee hyy cya ?",
        "Qchud q rhe ho ?",
        "pgl ey cya mc",
        "chud mt",
        "cya pgl rndii idar aa",
        "teri ammi ce bhosde me chappal",
        "oyee idar aa mc",
        "kmzror ey cya rndiek",
        "cya likh rha ?",
        "chud tha cya ?",
        "oyee slide leke baat crmc",
        "idar a teri maa chodu",
        "oyee cp mt crr chudle",
        "oyee hyy chud ke dika",
        "idar aa try ma schofu khachar khachar",
        "idar aa ja mc",
        "hyy idar aake chudle",
        "oyee kmzor mc idar aa",
        "ye cya tmr",
        "oyee ny cp ny crr",
        "oyee pgl mt crr",
        "cudle aram se mc",
        "pgl ey cya rndiek",
        "cp crce chudega !",
        "baap ? mc mera coi ma baap ny ey mai upar se rocket pe beth ce bss teri ma chodne aya hu",
        "Chota likh rndi k bache",
        "Chota likha wrna try ma rndy",
        "Try ma baka codega",
        "Tmkc main burf",
        "Bhikari ki jhat ma cuda le",
        "Chodke tery ma marjayegi",
        "Tmkc main Mount Everest",
        "Muh mey lega lund mera",
        "Hijde ki jhat chup wrna try ma rndi",
        "Menu ny pta tery ma randy",
        "Menu ki pta ma randy tery",
        "Menu pta maa cud gai tery",
        "Menu sb pta ma randy ey tery",
        "Menu pr tery ma randy",
        "Randy maa tery menu pta",
        "Tenu or menu pta ey maa randy tery",
        "Bs bs maa cudwa apni",
        "Bs bs ma randy tery thnkss",
        "Bs bs chudwa lia tu apni maa",
        "Bs bs kamjor maa randy tery",
        "Smjh gya apni ma cudwa le ab",
        "smjh gya tery maa randy ey",
        "smjh gya tu sabit kr maa randy tery",
        "Cya hua ma cudwa tu apni",
        "Easy maa cudwa le apni tu",
        "Easy w8 ma chudwa le apni ab",
        "Sans ari ha ky teri maa chudgi ajj",
        "Teri maa ko bina sanss lete hue chodunga",
        "chup randike kamjor",
        "apni ma normie cudwa le tu",
        "fr cya normie ma cud gai tery",
        "bas thek tery ma randy",
        "bas thek tery maa cud gyi",
        "kamjor thi tery ma esliye cud gai",
        "Mai sb janta ma cud gai tery",
        "chl chl ht tery maa cud gyi",
        "fr kaise cud gyi maa tery",
        "maa tery randy ey",
        "bas tery maa randy ey",
        "fr randy ma tery ey",
        "Kamjor ma ka bcha tu randyke",
        "bhot gndi cud gai maa tery",
        "pr kaise maa cud gai tery itna gnda",
        "mujhe cya bta rha maa randy tery",
        "mujhe cya pta ma cud gyi tery",
        "fir mujhe ny pta maa cud gai tery",
        "pta ny kon cod dia tery maa ko",
        "ruk aaya tery ma codke",
        "wait cr tery maa cod rha hu",
        "wait cr rabdyke maa cud rhi ey tery",
        "wait kr smjh rha tery ma codke",
        "wait le thoda chodne de tery mako",
        "ruk ja aand rkh dunga tery make liye",
        "tery maa famous randy ey",
        "maan lia mene maa randy sali tery",
        "maan lia maa cud gai tery",
        "shant beth randyke maa chudwa tu apni",
        "shant bethke chudwa le apni mako tu",
        "fr se shant Beth tu cud ab randyke yha",
        "mere smjh ny aya maa randy tery",
        "Le केला Kha tu madarchod",
        "Hye tery ma cud gyi cya",
        "hye tery maa mar gai cya",
        "Hye sch bta com cod dia tery mako",
        "Chl chod dia teri maa ko smjhle",
        "Baki koi dikkat ny tery maa randy ey",
        "baki sb jante ey ki maa chuddkad ey tery",
        "mujhe cya pta tha tery maa cudne wli ey",
        "pr mei kaise jnta tery ma ko koi chod dia",
        "pr mera vi manna shi tha maa chud gai tery",
        "pr wo glt ny tery maa randy ey",
        "pr wo shi ey tery maa chuddkad ey",
        "pr kaise kia maa chud gai tery omfoo",
        "bur cheer dunga tri ma ka",
        "teri ma ke dil me loda marke uski dhadkan rok dunga",
        "lulle kha tri makabhosda",
        "tri bhn ki bhosdi beta",
        "tri ma rndi baat khtm",
        "Sun ek maze ki baat batao kya teri maa randy ey"
        "codu codu mako tery",
        "aj cud gai tery maa oye",
        "sun sun randy make bache tu",
        "kilas ny randyke",
        "mujhe cya pta tery bhen cud gai",
        "pr pr cya hote ey tmkc",
        "tmcl sunle",
        "moot du tery maki chut mey",
        "bhgny cudke dikha fr",
        "fr se cudle tu",
        "ye vi shi ey tery mkc bs",
        "aj kuch ny ma cudwa tu apni",
        "try kr mera lund chuske",
        "tormakibur sun",
        "tor maki fuddi oye",
        "Haye Haye tery ma cud gai",
        "oye lundke pasine..",
        "kutte ke tatte sun",
        "kutta jaisa cud rha tu",
        "Muh mei le mera..",
        "jhaat ke pissu sun tmkc",
        "Hahahha ma cud gai tery",
        "weak tatte uth",
        "weak ey tu cud rha",
        "weak ache se cud tu",
        "weak tery ma cud rhi dekh",
        "week tery ma cud gai ab",
        "mujhe ny rok tu weak ey",
        "chup hizde",
        "okat ny meri ma cudwa tu apni",
        "lun lega tery maki gand mei ?",
        "tery maki bachi codu..",
        "tery bhen ki chut aj fad du",
        "speed lekr aa cudke dikha",
        "speed ny tere andr weak prosn",
        "ugly randyke chup",
        "makafuddatery",
        "tera baap ko tag kr..?",
        "ache se tag kr randibaaz bhagwn ko..",
        "cudke pgl ny ho tu",
        "cudke pgl ho rha tu kid",
        "ma to cud gai tery hawabzi cr..",
        "bs ma codni ey tery",
        "town mei cud tery mako lekr",
        "tery ma sexy ko bej - randibaaz bhgwn pe",
        "speed pkd cp ny kr",
        "Try ma rendy",
        "Bhkk cud",
        "tey maa rndi",
        "tery behen randi",
        "Cud ja",
        "tery didi rndi",
        "Slow",
        "teri Maiya ciodu",
        "Bhag?",
        "Bhak cud",
        "Tma codu",
        "Slow",
        "Slow firse",
        "Cudgrib",
        "Try ma dou",
        "tbkc codu",
        "Net on off wali rndy",
        "Oye try ma codu",
        "Idhar aake cud chup chaap",
        "tbkc mrdu",
        "oi maake lodee",
        "randyke beej",
        "tmkc chodu",
        "suar ke beej",
        "net off on kr randyke ladke",
        "Try ma cudi kese",
        "Chup slow madharcod",
        "tbkc codu kr msg delete",
        "oi suar ke ladke",
        "tmkc fufi",
        "tery didi chudi",
        "tmkc dikha",
        "Cud ab",
        "randyke cud",
        "Bhak cud",
        "cudle tbkc mru",
        "tmkl cudle grib",
        "tery behen vesiyaa rndi",
        "Itna gnda chuda tu firse net on off",
        "grib ke bete",
        "Bhag ja lode tmkc maru dunga",
        "tbkc mrdungaa",
        "bhag tmkc",
        "bhag tbkc",
        "tbkc mey cp",
        "cp tbkc mehh",
        "cp tmkl meh",
        "cp bol randyke",
        "Abe cp bol randyke",
        "double send ko cp tmkc codu",
        "tbkc me cp cod dunga Aaj mehh",
        "ht tbkc dalal ke bete.",
        "Rndy jldi jldi cudq tryma",
        "Para likhega..",
        "Tra rndhbhak",
        "Lagdi ke ladce cp bol",
        "cp bol lagdi ke bete..",
        "cudke cp bol",
        "bhikari lund chus mera.",
        "Low level cp cr",
        "cp bol low level weak",
        "mere lund pe ey tu hijde",
        "free cudwa tery mako",
        "Free mey cud tu randyke"
        "speed ny weak tatte terme",
        "kitni br cudwayega terymako",
        "lund le randibaaz bapka",
        "lun cus jaldi se randibaaz bapka",
        "koi ny dekh rha cudle tu",
        "cudle betichod ache se",
        "maki chut tery bs yehi janta mey",
        "cp bolega to tmkc",
        "wrna tery ma cud jayegi",
        "slow ey tu kid",
        "jldi likh..tmkc",
        "jldi likh..randce tu",
        "tym se phle cudke dikha",
        "tym hoga tery maa cudwa",
        "ma cud gai tery tym se phle",
        "uth randce ke ldke",
        "macabosdatery",
        "con kb cod dia mako tery",
        "koi hoga tml",
        "machar cudle tu",
        "menu tery mako codna se",
        "tery mako bol mujhe cod de",
        "bs mey tery ma se cudna chta hu",
        "Eww maka lode uth",
        "Meow cr tery mako codu",
        "lund rkh dia tery make fude pe",
        "mera lund ke bal uth",
        "kidee Zinda ho",
        "mar ny kidde type kr",
        "chup bkl",
        "bc tery maki chut",
        "mc randyke likh fast",
        "fast likh randyke",
        "fast likh kamzor"
        "tery maki chut claim crwa",
        "awz niche randce ke bche",
        "sawal ny puch tery makabosda",
        "fyter bnega lagde madrchod",
        "oye kaale ro ke dikha",
        "oye kaale roo ny",
        "short ny cud tu bina ruke",
        "short ny cud tu apni mako lekr",
        "tery make sth tery bhen vi cudwa le",
        "tery make sth tery didi vi cud gai",
        "Chat fyter bnega randce codu tery mako",
        "bol randibaaz daddy ey",
        "bullyx randyke uth",
        "mar marke cud rha tu",
        "or tery ma marke cud gai"
        "Jaldi likh rndyke bej",
        "Or bda likh tmc",
        "Or bda 2 line wla likh tmkc",
        "Or bda oye likh tml",
        "Teri maa ka bur",
        "Oye keede",
        "Randi ke ladke",
        "Jaldi likh teri behen chodu",
        "Mkl uth randi ke bacche",
        "Teri nani meri maal",
        "Tej likh randce",
        "Oye maake lode mrenga",
        "Teri maa chody",
        "Teri Maiya ki gand",
        "Tery dadi ka fudda",
        "Mkl uth behencod",
        "Teri maa ki bur de",
        "Tery maa ka fudda me lauda",
        "Teri maa chudva",
        "Randi ke bete mar gaya",
        "Teri maa ki chut mru",
        "Jalid kr spam",
        "Mc spam rokenga",
        "Teri maaki chut spam kr",
        "spam kr.maake lode",
        "Randyke chode spam kr wrna cud tu",
        "Spam kr kid",
        "Noob teri maa chodu",
        "Rndyke bete mar mat tu",
        "Noob jaldi likh wrna tery maa rand",
        "cud gai maa tery noob",
        "uth randyke noob",
        "chl cudke dikha noob",
        "jldi typ cr noob halke",
        "cud ke pgl ny ho noob",
        "cud cud ke rand bnja tu noob",
        "makichut tery noob",
        "ganda cyu cud rha tu ?",
        "itna gnda ny cud ache se cud",
        "Maan le cud gya tu sun bat ab",
        "makafudda fat gya tery ruk"
        "BAAP BHI BNALE MUJE RNDIKE",
        "TERA BAAP RANDIBAAZ EY YAAD EY TUJHE",
        "TU APNI MAA CUDA NA TYMPASS",
        "OYE UNFUNNY SWIPE MTT KR",
        "OH HELLO BIHARI TERA BAAP BIHARI OR TU V BIHARI AAUKAT ME RHA KR.",
        "OYY KINNER TUJHE GC ME AANE KI PERMISSION KISNE DI.",
        "CUDKE DIKHA",
        "CUDKE DIKHA EK BAAR.",
        "SUN SUN MA CUDA.",
        "TERI MACA BHOSDA.",
        "OYE CHOTI JATI KE TMR.",
        "KY? JLDI LIKH KIDDE.",
        "BIHARI COM GANG KE BAAP KO TAG CREGA TU",
        "MUJHE CYA TU BIHARI EY TMKC BS",
        "JALDI SE RANDIBAAZ PAPA BOL",
        "SIDE HOJA BIHARI TERY MAA CUD GAI AB",
        "HYE PGL BHG MAT ACHE SE CUD",
        "BHG NY RANDYKE TU AJJ",
        "HYE PGL KE BCHE BHAG MAT",
        "HYE DUR HATT MADCHOD KE BACHE",
        "KOI BAT NY TERY MAA RANDY EY ESLIYE MAF CR RHA HU TUJHE",
        "KOI BAAT NY MAA CHUDWA APNI TU MAFI DE DUNGA",
        "ACHE SE MAA CHUDWA APNI TU MAFI MIL JAYEGI TUJHE",
        "APNI MA MAT CHUDA MUJE SWIPE CRKE",
        "ACHE SE APNI MA CUDWA TU SWIPE CRKE",
        "FR BOLNA NA KI CUDWA LE APNI MA SWIPE CRKE",
        "CYA HUA MA CUD GYI TERY",
        "PR KESE CUD GYI TERY MA",
        "MUJHE PTA THA MA CUD GAI TERY",
        "MEY NY MANTA MA CUD GYI TERY",
        "TERI MA RNDY",
        "LODE SE UTR MC",
        "LUN MT CHUS MERA",
        "NIKAL MADARCHD",
        "CHUP OYE GASHTI K BACHE",
        "MAKICHUT TERI",
        "CHUP RNDYKE",
        "MA RNDY TERI",
        "TERI MA K HATH TODH K TERE BAAP K MUH ME FASADUNGA RANDYKE",
        "LEAVE LE TU RNDYKE PASAND NAI AYA MEKO",
        "LEAVE LE TU RANDYKE IDER SE",
        "LEAVE LE JLDI SE WRNA MA CHUD GAI TERY",
        "LEAVE NY LEGA MAA RANDY TERY",
        "SMJH BAT MAA RANDY EY TERY LEAVE LE",
        "FAST LEAVE LE KAMJOR RANDYKE",
        "TUTO CHUP RNDYK",
        "OY HIJDE KHANA KHA KE AA KAMZOR",
        "TERI MAKO ILY REY",
        "CHUP CHAP CHUD TMKC",
        "CHUPCHAP MAA CHUDWA APNI TU",
        "SHI SE MAA CHUDWA APNI TU CHUPCHAP",
        "FR SE MAA CHUDWA TU APNI CHUPCHAP",
        "SHI SE LIKH WRNA MA CHUD GAI TERY",
        "MA CYU CHUD GAI TERY CHUPCHAP",
        "PROOF CR MAA CHUD GYI TERY",
        "PROOF EY TERY MAA RANDY EY",
        "PROOF HO CHUKA MAA RANDY TERY",
        "CHUP CHILLAR",
        "CHUP CHUP MA K BOSDA TERY",
        "OY HIJDE KHANA KHA KE AA KAMZOR",
        "CHUP MADARCHOD ?",
        "AB TK CUD GYI HOGI TERY MAA ?",
        "NY NY ME KUCH NY JANTA BS TERI MA RNDY EY",
        "SBSE PHELE APNI MAA KO BOL CHUDNA KAAM KRE",
        "YAHA BHI CHUDA TU RNDYCE PILLE",
        "TERIMAKABOSDA",
        "TERI TO BHEN CUDEGI",
        "CHUP RNDYKE TOMMY",
        "NIKAL MADARCHD CUDKE YHA SE",
        "COZ TERI MA ANDHI RANDI HE",
        "NYTO BAAP BOL MUJHE",
        "NYNY TERI MAA HOGI RNDII JO CHUDWATI JOGI",
        "TRY AMMI CE BHOSDE ME EMOJI DAL MC",
        "CYA ? CHMR CHUD GYA CYA ?",
        "TM CHUDRI HOGI FRRTO",
        "CYA ? KB ? PGL EY CYA RNDKEK",
        "CYA SCH MEY PGL EY CYA TU RANDYKE CUDWA LI TUNE APNI MA",
        "ITNA SCH NY BOL MA CHUD GAI TERY",
        "SCH MEY PGL EY TU APNI MA CUDWA LIA MERE STH",
        "MTLB TMR",
        "NYTO",
        "PURA LIKH MC",
        "TMR FRRTO",
        "OH OK CUDLE FIR",
        "TERI MAA KA DAMAD",
        "CYA ? ACHE SE LIKHE PEHLE RNDIKEBACHE",
        "NYTO TERI MAA CHODNE ME VYAST HU",
        "NYTO PGL EY CYA KUCH BI",
        "OYEE CYA ? CHUD GYA ?",
        "CHUD MT HSS",
        "YUR RNDII MOM",
        "ARE SBKI MAA RNDII OR TERI BI",
        "ARE IDAR CUDLE EK BAAR",
        "TRI MAA CI TRH",
        "EK LINE ME TMR",
        "Q",
        "OCY AB CHUDLE",
        "PEHELE TERI MAA CHODU",
        "NYTO",
        "Q ?",
        "HYYY CHUD KE DIKA EK BAAR",
        "OYEE SUN DOST TMR",
        "BHAG JA RAAND MAAF CRR DUNGA",
        "OYEE PGL RNDII IDAR AA",
        "CYA TMR FRRTO",
        "OYEE IDAR Aake CHUD LE CHMR",
        "NYTO AESE HI CUD",
        "OYEE HYY AISE HI CUD LENA",
        "OR CHUD LE",
        "CHUD KE DIKA OR",
        "HYY CHUDO NA",
        "CHUDO MT BHAG JAO",
        "BYYEE HYY CYA ?",
        "QCHUD Q RHE HO ?",
        "PGL EY CYA MC",
        "CHUD MT",
        "CYA PGL RNDII IDAR AA",
        "TERI AMMI CE BHOSDE ME CHAPPAL",
        "OYEE IDAR AA MC",
        "KMZROR EY CYA RNDIEK",
        "CYA LIKH RHA ?",
        "CHUD THA CYA ?",
        "OYEE SLIDE LEKE BAAT CRMC",
        "IDAR A TERI MAA CHODU",
        "OYEE CP MT CRR CHUDLE",
        "OYEE HYY CHUD KE DIKA",
        "IDAR AA TRY MA SCHOFU KHACHAR KHACHAR",
        "IDAR AA JA MC",
        "HYY IDAR Aake CHUDLE",
        "OYEE KMZOR MC IDAR AA",
        "YE CYA TMR",
        "OYEE NY CP NY CRR",
        "OYEE PGL MT CRR",
        "CUDLE ARAM SE MC",
        "PGL EY CYA RNDIEK",
        "CP CRCE CHUDEGA !",
        "BAAP ? MC MERA COI MA BAAP NY EY MAI UPAR SE ROCKET PE BETH CE BSS TERI MA CHODNE AYA HU",
        "CHOTA LIKH RNDI K BACHE",
        "CHOTA LIKHA WRNA TRY MA RNDY",
        "TRY MA BAKA CODEGA",
        "TMKC MAIN BURF",
        "BHIKARI KI JHAT MA CUDA LE",
        "CHODKE TERY MA MARJAYEGI",
        "TMKC MAIN MOUNT EVEREST",
        "MUH MEY LEGA LUND MERA",
        "HIJDE KI JHAT CHUP WRNA TRY MA RNDI",
        "MENU NY PTA TERY MA RANDY",
        "MENU KI PTA MA RANDY TERY",
        "MENU PTA MAA CUD GAI TERY",
        "MENU SB PTA MA RANDY EY TERY",
        "MENU PR TERY MA RANDY",
        "RANDY MAA TERY MENU PTA",
        "TENU OR MENU PTA EY MAA RANDY TERY",
        "BS BS MAA CUDWA APNI",
        "BS BS MA RANDY TERY THNKSS",
        "BS BS CHUDWA LIA TU APNI MAA",
        "BS BS KAMJOR MAA RANDY TERY",
        "SMJH GYA APNI MA CUDWA LE AB",
        "SMJH GYA TERY MAA RANDY EY",
        "SMJH GYA TU SABIT KR MAA RANDY TERY",
        "CYA HUA MA CUDWA TU APNI",
        "EASY MAA CUDWA LE APNI TU",
        "EASY W8 MA CHUDWA LE APNI AB",
        "SANS ARI HA KY TERI MAA CHUDGI AJJ",
        "TERI MAA KO BINA SANSS LETE HUE CHODUNGA",
        "CHUP RANDIKE KAMJOR",
        "APNI MA NORMIE CUDWA LE TU",
        "FR CYA NORMIE MA CUD GAI TERY",
        "BAS THEK TERY MA RANDY",
        "BAS THEK TERY MAA CUD GYI",
        "KAMJOR THI TERY MA ESLIYE CUD GAI",
        "MAI SB JANTA MA CUD GAI TERY",
        "CHL CHL HT TERY MAA CUD GYI",
        "FR KAISE CUD GYI MAA TERY",
        "MAA TERY RANDY EY",
        "BAS TERY MAA RANDY EY",
        "FR RANDY MA TERY EY",
        "KAMJOR MA KA BCHA TU RANDYKE",
        "BHOT GNDI CUD GAI MAA TERY",
        "PR KAISE MAA CUD GAI TERY ITNA GNDA",
        "MUJHE CYA BTA RHA MAA RANDY TERY",
        "MUJHE CYA PTA MA CUD GYI TERY",
        "FIR MUJHE NY PTA MAA CUD GAI TERY",
        "PTA NY KON COD DIA TERY MAA KO",
        "RUK AAYA TERY MA CODKE",
        "WAIT CR TERY MAA COD RHA HU",
        "WAIT CR RABDYKE MAA CUD RHI EY TERY",
        "WAIT KR SMJH RHA TERY MA CODKE",
        "WAIT LE THODA CHODNE DE TERY MAKO",
        "RUK JA AAND RKH DUNGA TERY MAKE LIYE",
        "TERY MAA FAMOUS RANDY EY",
        "MAAN LIA MENE MAA RANDY SALI TERY",
        "MAAN LIA MAA CUD GAI TERY",
        "SHANT BETH RANDYKE MAA CHUDWA TU APNI",
        "SHANT BETHKE CHUDWA LE APNI MAKO TU",
        "FR SE SHANT BETH TU CUD AB RANDYKE YHA",
        "MERE SMJH NY AYA MAA RANDY TERY",
        "LE KELA KHA TU MADARCHOD",
        "HYE TERY MA CUD GYI CYA",
        "HYE TERY MAA MAR GAI CYA",
        "HYE SCH BTA COM COD DIA TERY MAKO",
        "CHL CHOD DIA TERI MAA KO SMJHLE",
        "BAKI KOI DIKKAT NY TERY MAA RANDY EY",
        "BAKI SB JANTE EY KI MAA CHUDDKAD EY TERY",
        "MUJHE CYA PTA THA TERY MAA CUDNE WLI EY",
        "PR MEI KAISE JNTA TERY MA KO KOI CHOD DIA",
        "PR MERA VI MANNA SHI THA MAA CHUD GAI TERY",
        "PR WO GLT NY TERY MAA RANDY EY",
        "PR WO SHI EY TERY MAA CHUDDKAD EY",
        "PR KAISE KIA MAA CHUD GAI TERY OMFOO",
        "BUR CHEER DUNGA TRI MA KA",
        "TERI MA KE DIL ME LODA MARKE USKI DHADKAN ROK DUNGA",
        "LULLE KHA TRI MAKABHOSDA",
        "TRI BHN KI BHOSDI BETA",
        "TRI MA RNDI BAAT KHTM",
        "SUN EK MAZE KI BAAT BATAO KYA TERI MAA RANDY EY",
        "CODU CODU MAKO TERY",
        "AJ CUD GAI TERY MAA OYE",
        "SUN SUN RANDY MAKE BACHE TU",
        "KILAS NY RANDYKE",
        "MUJHE CYA PTA TERY BHEN CUD GAI",
        "PR PR CYA HOTE EY TMKC",
        "TMCL SUNLE",
        "MOOT DU TERY MAKI CHUT MEY",
        "BHGNY CUDKE DIKHA FR",
        "FR SE CUDLE TU",
        "YE VI SHI EY TERY MKC BS",
        "AJ KUCH NY MA CUDWA TU APNI",
        "TRY KR MERA LUND CHUSKE",
        "TORMAKIBUR SUN",
        "TOR MAKI FUDDI OYE",
        "HAYE HAYE TERY MA CUD GAI",
        "OYE LUNDKE PASINE..",
        "KUTTE KE TATTE SUN",
        "KUTTA JAISA CUD RHA TU",
        "MUH MEI LE MERA..",
        "JHAAT KE PISSU SUN TMKC",
        "HAHAHHA MA CUD GAI TERY",
        "WEAK TATTE UTH",
        "WEAK EY TU CUD RHA",
        "WEAK ACHE SE CUD TU",
        "WEAK TERY MA CUD RHI DEKH",
        "WEEK TERY MA CUD GAI AB",
        "MUJHE NY ROK TU WEAK EY",
        "CHUP HIZDE",
        "OKAT NY MERI MA CUDWA TU APNI",
        "LUN LEGA TERY MAKI GAND MEI ?",
        "TERY MAKI BACHI CODU..",
        "TERY BHEN KI CHUT AJ FAD DU",
        "SPEED LEKR AA CUDKE DIKHA",
        "SPEED NY TERE ANDR WEAK PROSN",
        "UGLY RANDYKE CHUP",
        "MAKAFUDDATERY",
        "TERA BAAP KO TAG KR..?",
        "ACHE SE TAG KR RANDIBAAZ BHAGWN KO..",
        "CUDKE PGL NY HO TU",
        "CUDKE PGL HO RHA TU KID",
        "MA TO CUD GAI TERY HAWABZI CR..",
        "BS MA CODNI EY TERY",
        "TOWN MEI CUD TERY MAKO LEKR",
        "TERY MA SEXY KO BEJ - RANDIBAAZ BHGWN PE",
        "SPEED PKD CP NY KR",
        "TRY MA RENDY",
        "BHKK CUD",
        "TEY MAA RNDI",
        "TERY BEHEN RANDI",
        "CUD JA TMC",
        "TERY DIDI RNDI",
        "SLOW",
        "TERI MAIYA CIODU",
        "BHAG?TMC ",
        "BHAK CUD TML",
        "TMA CODU",
        "SLOW TMKC ",
        "SLOW FIRSE TMKC ",
        "CUDGRIB TML",
        "TRY MA DOU",
        "TBKC CODU",
        "NET ON OFF WALI RNDY",
        "OYE TRY MA CODU",
        "IDHAR AAKE CUD CHUP CHAAP",
        "TBKC MRDU",
        "OI MAAKE LODEE",
        "RANDYKE BEEJ",
        "TMKC CHODU",
        "SUAR KE BEEJ",
        "NET OFF ON KR RANDYKE LADKE",
        "TRY MA CUDI KESE",
        "CHUP SLOW MADHARCOD",
        "TBKC CODU KR MSG DELETE",
        "OI SUAR KE LADKE",
        "TMKC FUFI",
        "TERY DIDI CHUDI",
        "TMKC DIKHA",
        "CUD AB",
        "RANDYKE CUD",
        "BHAK CUD",
        "CUDLE TBKC MRU",
        "TMKL CUDLE GRIB",
        "TERY BEHEN VESITYA RNDI",
        "ITNA GNDA CHUDA TU FIRSE NET ON OFF",
        "GRIB KE BETE",
        "BHAG JA LODE TMKC MARU DUNGA",
        "TBKC MRDUNGAA",
        "BHAG TMKC",
        "BHAG TBKC",
        "TBKC MEY CP",
        "CP TBKC MEHH",
        "CP TMKL MEH",
        "CP BOL RANDYKE",
        "ABE CP BOL RANDYKE",
        "DOUBLE SEND KO CP TMKC CODU",
        "TBKC ME CP COD DUNGA AAJ MEHH",
        "HT TBKC DALAL KE BETE.",
        "RNDY JLDI JLDI CUDQ TRYMA",
        "PARA LIKHEGA..",
        "TRA RNDHBHAK",
        "LAGDI KE LADCE CP BOL",
        "CP BOL LAGDI KE BETE..",
        "CUDKE CP BOL",
        "BHIKARI LUND CHUS MERA.",
        "LOW LEVEL CP CR",
        "CP BOL LOW LEVEL WEAK",
        "MERE LUND PE EY TU HIJDE",
        "FREE CUDWA TERY MAKO",
        "FREE MEY CUD TU RANDYKE",
        "SPEED NY WEAK TATTE TERME",
        "KITNI BR CUDWAYEGA TERYMAKO",
        "LUND LE RANDIBAAZ BAPKA",
        "LUN CUS JALDI SE RANDIBAAZ BAPKA",
        "KOI NY DEKH RHA CUDLE TU",
        "CUDLE BETICHOD ACHE SE",
        "MAKI CHUT TERY BS YEHI JANTA MEY",
        "CP BOLEGA TO TMKC",
        "WRNA TERY MA CUD JAYEGI",
        "SLOW EY TU KID",
        "JLDI LIKH..TMKC",
        "JLDI LIKH..RANDCE TU",
        "TYM SE PHLE CUDKE DIKHA",
        "TYM HOGA TERY MAA CUDWA",
        "MA CUD GAI TERY TYM SE PHLE",
        "UTH RANDCE KE LDKE",
        "MACABOSDATERY",
        "CON KB COD DIA MAKO TERY",
        "KOI HOGA TML",
        "MACHAR CUDLE TU",
        "MENU TERY MAKO CODNA SE",
        "TERY MAKO BOL MUJHE COD DE",
        "BS MEY TERY MA SE CUDNA CHTA HU",
        "EWW MAKA LODE UTH",
        "MEOW CR TERY MAKO CODU",
        "LUND RKH DIA TERY MAKE FUDE PE",
        "MERA LUND KE BAL UTH",
        "KIDEE ZINDA HO",
        "MAR NY KIDDE TYPE KR",
        "CHUP BKL",
        "BC TERY MAKI CHUT",
        "MC RANDYKE LIKH FAST",
        "FAST LIKH RANDYKE",
        "FAST LIKH KAMZOR",
        "TERY MAKI CHUT CLAIM CRWA",
        "AWZ NICHE RANDCE KE BCHE",
        "SAWAL NY PUCH TERY MAKABOSDA",
        "FYTER BNEGA LAGDE MADRCHOD",
        "OYE KAALE RO KE DIKHA",
        "OYE KAALE ROO NY",
        "SHORT NY CUD TU BINA RUKE",
        "SHORT NY CUD TU APNI MAKO LEKR",
        "TERY MAKE STH TERY BHEN VI CUDWA LE",
        "TERY MAKE STH TERY DIDI VI CUD GAI",
        "CHAT FYTER BNEGA RANDCE CODU TERY MAKO",
        "BOL RANDIBAAZ DADDY EY",
        "BULLYX RANDYKE UTH",
        "MAR MARKE CUD RHA TU",
        "OR TERY MA MARKE CUD GAI",
        "JALDI LIKH RNDYKE BEJ",
        "OR BDA LIKH TMC",
        "OR BDA 2 LINE WLA LIKH TMKC",
        "OR BDA OYE LIKH TML",
        "TERI MAA KA BUR",
        "OYE KEEDE",
        "RANDI KE LADKE",
        "JALDI LIKH TERI BEHEN CHODU",
        "MKL UTH RANDI KE BACCHE",
        "TERI NANI MERI MAAL",
        "TEJ LIKH RANDCE",
        "OYE MAAKE LODE MRENGA",
        "TERI MAA CHODY",
        "TERI MAIYA KI GAND",
        "TERY DADI KA FUDDA",
        "MKL UTH BEHENCOD",
        "TERI MAA KI BUR DE",
        "TERY MAA KA FUDDA ME LAUDA",
        "TERI MAA CHUDVA",
        "RANDI KE BETE MAR GAYA",
        "TERI MAA KI CHUT MRU",
        "JALID KR SPAM",
        "MC SPAM ROKENGA",
        "TERI MAAKI CHUT SPAM KR",
        "SPAM KR.MAAKE LODE",
        "RANDYKE CHODE SPAM KR WRNA CUD TU",
        "SPAM KR KID",
        "NOOB TERI MAA CHODU",
        "RNDYKE BETE MAR MAT TU",
        "NOOB JALDI LIKH WRNA TERY MAA RAND",
        "CUD GAI MAA TERY NOOB",
        "UTH RANDYKE NOOB",
        "CHL CUDKE DIKHA NOOB",
        "JLDI TYP CR NOOB HALKE",
        "CUD KE PGL NY HO NOOB",
        "CUD CUD KE RAND BNJA TU NOOB",
        "MAKICHUT TERY NOOB",
        "GANDA CYU CUD RHA TU ?",
        "ITNA GNDA NY CUD ACHE SE CUD",
        "MAAN LE CUD GYA TU SUN BAT AB",
        "MAKAFUDDA FAT GYA TERY RUK",
        "sʜᴀɴᴛ ʙᴇᴛʜ ᴍᴀᴅʀᴄʜᴏᴅ ᴡʀɴᴀ ᴍᴀᴋᴀʙᴏsᴅᴀ ᴛᴇᴇʏ.",
        "ᴛᴇʀɪ ᴍᴀ ᴋɪ ᴄʜᴜᴛ..",
        "ʟᴡᴅᴇ ᴋᴇ ʙᴀᴀᴀʟʟʟ ᴛᴇʀʏ ᴍᴀᴀ ᴄᴜᴅᴋᴇ ᴘɢʟ ᴅᴇᴋʜ.",
        "ᴍᴀᴄʜᴀʀ ᴋɪ ᴊʜᴀᴀᴛ ᴋᴇ ʙᴀᴀᴀʟʟʟʟ ᴄᴜᴅ ᴀᴄʜᴇ sᴇ ʏʜᴀᴘᴇ ᴛᴜ",
        "ᴛᴇʀɪ ᴍᴀ ᴋɪ ᴄʜᴜᴛ ᴍ ᴅᴜ ᴛᴀᴘᴀ ᴛᴀᴘ?",
        "ᴛᴇʀɪ ᴍᴀ ᴋᴀ ʙʜᴏꜱᴅᴀᴀ",
        "ᴛᴇʀɪ ʙʜɴ ꜱʙꜱʙᴇ ʙᴅɪ ʀᴀɴᴅɪ.",
        "ᴛᴇʀɪ ᴍᴀ ᴏꜱꜱᴇ ʙᴀᴅɪ ʀᴀɴᴅᴅᴅᴅᴅ",
        "ᴛᴇʀᴀ ʙᴀᴀᴘ ʀᴀɴᴅɪʙᴀᴀᴢ ᴇʏ ᴅᴇᴋʜ",
        "ᴋɪᴛɴɪ ᴄʜᴏᴅᴜ ᴛᴇʀɪ ᴍᴀ ᴀʙ ᴏʀ..",
        "ᴛᴇʀɪ ᴍᴀ ᴄʜᴏᴅ ᴅɪ ʜᴍ ɴᴇ",
        "ᴛᴇʀɪ ᴍᴀ ᴋᴇ ꜱᴛʜ ʀᴇᴇʟꜱ ʙɴᴇɢᴀ ʀᴏᴀᴅ ᴘᴇᴇ",
        "ᴛᴇʀɪ ᴍᴀ ᴋɪ ᴄʜᴜᴛ ᴇᴋ ᴅᴀᴍ ᴛᴏᴘ ꜱᴇxʏ",
        "ᴍᴀʟᴜᴍ ɴᴀ ᴘʜʀ ᴋᴇꜱᴇ ʟᴇᴛᴀ ʜᴜ ᴍ ᴛᴇʀɪ ᴍᴀ ᴋɪ ᴄʜᴜᴛ ᴛᴀᴘᴀ ᴛᴀᴘᴘᴘᴘᴘ",
        "ʟᴜɴᴅ ᴋᴇ ᴄʜᴏᴅᴇ ᴛᴜ ᴋᴇʀᴇɢᴀ ᴛʏᴘɪɴɢ ᴋʀᴇɢᴀ ᴛᴍᴋᴄ",
        "ꜱᴘᴇᴇᴅ ᴘᴋᴅ ʟᴡᴅᴇᴇᴇᴇ ᴡʀɴᴀ ᴍᴇʀᴀ ʟᴜɴᴅ ᴘᴋᴅ",
        "ʙᴀᴀᴘ ᴋɪ ꜱᴘᴇᴇᴅ ᴍᴛᴄʜ ᴋʀʀʀ",
        "ʟᴡᴅᴀ ʟᴇ ᴍᴇʀᴀ ᴊᴀʟᴅɪ sᴇ ᴛᴜ",
        "ᴘᴀᴘᴀ ᴋɪ ꜱᴘᴇᴇᴅ ᴍᴛᴄʜ ɴʜɪ ʜᴏ ʀʜɪ ᴋʏᴀ ᴛᴇʀᴇsᴇ",
        "ᴀʟᴇ ᴀʟᴇ ᴍᴇʟᴀ ʙᴄʜᴀᴀᴀᴀ ᴛᴇʀʏ ᴍᴀᴋᴀ ʙᴏsᴅᴀ sᴜɴ",
        "ᴄʜᴜᴅ ɢʏᴀ ʀᴀɴᴅɪʙᴀᴀᴢ ᴘᴀᴘᴀ ꜱᴇᴇᴇ ᴛᴜ",
        "ᴍᴇɴᴜ ᴋɪ ᴘᴛᴀ ᴛᴇʀʏ ᴍᴀ ᴄᴜᴅ ɢᴀɪ",
        "ᴋᴏɪ ʙᴀᴀᴛ ɴʏ ᴍᴀᴀ ʀᴀɴᴅʏ ᴛᴇʀʏ",
        "ʜᴀʜᴀʜᴀᴀᴀᴀᴀ ᴍᴀᴋᴀʙᴏsᴅᴀ ᴛᴇʀʏ",
        "xʜᴜᴅ ɢᴀɪ ᴍᴀᴀ ᴛᴇʀʏ ᴋɪᴅꜱꜱꜱꜱ",
        "ᴛᴇʀɪ ᴍᴀ ᴄʜᴜᴅ ɢʏɪ ᴀʙ ꜰʀᴀʀ ᴍᴛ ʜᴏɴᴀ",
        "ʏᴇ ʟᴜɴᴅ ʟᴇ ᴍᴇʀᴀ ᴄʜʟ ᴊᴀʟᴅɪ sᴇ",
        "ᴋɪᴅꜱꜱꜱ ꜰʀᴀʀ ɴᴀ ʜᴏ ᴛᴜ ʜᴀʜᴀʜʜ",
        "ʙʜᴇɴ ᴋᴇ ʟᴡᴅᴇ ꜱʜʀᴍ ᴋʀ",
        "ᴋɪᴛɴɪ ɢʟɪʏᴀ ᴘᴅᴡᴇɢᴀ ᴀᴘɴɪ ᴍᴀ ᴋᴏ",
        "ᴄʜᴜᴘ ɴᴀʟʟɪɪ ʀᴀɴᴅʏᴋᴇ ʟᴀᴅᴋᴇ",
        "ꜱᴜᴀʀ ᴋᴇ ᴘɪʟʟᴇ ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ꜱᴀᴅᴀᴋ ᴘʀ ʟɪᴛᴀᴋᴇ ᴄʜᴏᴅ ᴅᴜɴɢᴀ 😂😆🤤",
        "ᴀʙᴇ ᴛᴇʀɪ ᴍᴀᴀᴋᴀ ʙʜᴏꜱᴅᴀ ᴍᴀᴅᴇʀᴄʜᴏᴏᴅ ᴋʀ ᴘɪʟʟᴇ ᴘᴀᴘᴀ ꜱᴇ ʟᴀᴅᴇɢᴀ ᴛᴜ 😼😂🤤",
        "ɢᴀʟɪ ɢᴀʟɪ ɴᴇ ꜱʜᴏʀ ʜᴇ ᴛᴇʀɪ ᴍᴀᴀ ʀᴀɴᴅɪ ᴄʜᴏʀ ʜᴇ 💋💋💦",
        "ᴀʙᴇ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴏ ᴄʜᴏᴅᴜ ʀᴀɴᴅɪᴋᴇ ᴘɪʟʟᴇ ᴋᴜᴛᴛᴇ ᴋᴇ ᴄʜᴏᴅᴇ 😂👻🔥",
        "ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴀɪꜱᴇ ᴄʜᴏᴅᴀ ᴀɪꜱᴇ ᴄʜᴏᴅᴀ ᴛᴇʀɪ ᴍᴀᴀᴀ ʙᴇᴅ ᴘᴇʜɪ ᴍᴜᴛʜ ᴅɪᴀ 💦💦💦💦",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴇ ʙʜᴏꜱᴅᴇ ᴍᴇ ᴀᴀᴀɢ ʟᴀɢᴀᴅɪᴀ ᴍᴇʀᴀ ᴍᴏᴛᴀ ʟᴜɴᴅ ᴅᴀʟᴋᴇ 🔥🔥💦😆😆",
        "ʀᴀɴᴅɪᴋᴇ ʙᴀᴄʜʜᴇ ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴄʜᴏᴅᴜ ᴄʜᴀʟ ɴɪᴋᴀʟ",
        "ᴋɪᴛɴᴀ ᴄʜᴏᴅᴜ ᴛᴇʀɪ ʀᴀɴᴅɪ ᴍᴀᴀᴋɪ ᴄʜᴜᴛʜ ᴀʙʙ ᴀᴘɴɪ ʙᴇʜᴇɴ ᴋᴏ ʙʜᴇᴊ 😆👻🤤",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴏᴛᴏ ᴄʜᴏᴅ ᴄʜᴏᴅᴋᴇ ᴘᴜʀᴀ ꜰᴀᴀᴅ ᴅɪᴀ ᴄʜᴜᴛʜ ᴀʙʙ ᴛᴇʀɪ ɢꜰ ᴋᴏ ʙʜᴇᴊ 😆💦🤤",
        "ᴛᴇʀɪ ɢꜰ ᴋᴏ ᴇᴛɴᴀ ᴄʜᴏᴅᴀ ʙᴇʜᴇɴ ᴋᴇ ʟᴏᴅᴇ ᴛᴇʀɪ ɢꜰ ᴛᴏ ᴍᴇʀɪ ʀᴀɴᴅɪ ʙᴀɴɢᴀʏɪ ᴀʙʙ ᴄʜᴀʟ ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴄʜᴏᴅᴛᴀ ꜰɪʀꜱᴇ ♥️💦😆😆😆😆",
        "ʜᴀʀɪ ʜᴀʀɪ ɢʜᴀᴀꜱ ᴍᴇ ᴊʜᴏᴘᴅᴀ ᴛᴇʀɪ ᴍᴀᴀᴋᴀ ʙʜᴏꜱᴅᴀ 🤣🤣💋💦",
        "ᴄʜᴀʟ ᴛᴇʀᴇ ʙᴀᴀᴘ ᴋᴏ ʙʜᴇᴊ ᴛᴇʀᴀ ʙᴀꜱᴋᴀ ɴʜɪ ʜᴇ ᴘᴀᴘᴀ ꜱᴇ ʟᴀᴅᴇɢᴀ ᴛᴜ",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋɪ ᴄʜᴜᴛʜ ᴍᴇ ʙᴏᴍʙ ᴅᴀʟᴋᴇ ᴜᴅᴀ ᴅᴜɴɢᴀ ᴍᴀᴀᴋᴇ ʟᴀᴡᴅᴇ",
        "ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴛʀᴀɪɴ ᴍᴇ ʟᴇᴊᴀᴋᴇ ᴛᴏᴘ ʙᴇᴅ ᴘᴇ ʟɪᴛᴀᴋᴇ ᴄʜᴏᴅ ᴅᴜɴɢᴀ ꜱᴜᴀʀ ᴋᴇ ᴘɪʟʟᴇ 🤣🤣💋💋",
        "ᴛᴇʀɪ ᴍᴀᴀᴀᴋᴇ ɴᴜᴅᴇꜱ ɢᴏᴏɢʟᴇ ᴘᴇ ᴜᴘʟᴏᴀᴅ ᴋᴀʀᴅᴜɴɢᴀ ʙᴇʜᴇɴ ᴋᴇ ʟᴀᴇᴡᴅᴇ 👻🔥",
        "ᴛᴇʀɪ ᴍᴀᴀᴀᴋᴇ ɴᴜᴅᴇꜱ ɢᴏᴏɢʟᴇ ᴘᴇ ᴜᴘʟᴏᴀᴅ ᴋᴀʀᴅᴜɴɢᴀ ʙᴇʜᴇɴ ᴋᴇ ʟᴀᴇᴡᴅᴇ 👻🔥",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴏ ᴄʜᴏᴅ ᴄʜᴏᴅᴋᴇ ᴠɪᴅᴇᴏ ʙᴀɴᴀᴋᴇ xɴxx ᴘᴇ ɴᴇᴇʟᴀᴍ ᴋᴀʀᴅᴜɴɢᴀ ᴋᴜᴛᴛᴇ ᴋᴇ ᴘɪʟʟᴇ 💦💋",
        "ᴛᴇʀɪ ᴍᴀᴀᴀᴋɪ ᴄʜᴜᴅᴀɪ ᴋᴏ ᴘᴏ*ʀɴʜᴜʙ ᴘᴇ ᴜᴘʟᴏᴀᴅ ᴋᴀʀᴅᴜɴɢᴀ ꜱᴜᴀʀ ᴋᴇ ᴄʜᴏᴅᴇ 🤣💋💦",
        "ᴀʙᴇ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴏ ᴄʜᴏᴅᴜ ʀᴀɴᴅɪᴋᴇ ʙᴀᴄʜʜᴇ ᴛᴇʀᴇᴋᴏ ᴄʜᴀᴋᴋᴏ ꜱᴇ ᴘɪʟᴡᴀᴠᴜɴɢᴀ ʀᴀɴᴅɪᴋᴇ ʙᴀᴄʜʜᴇ 🤣🤣",
        "ᴛᴇʀɪ ᴍᴀᴀᴋɪ ᴄʜᴜᴛʜ ꜰᴀᴀᴅᴋᴇ ʀᴀᴋᴅɪᴀ ᴍᴀᴀᴋᴇ ʟᴏᴅᴇ ᴊᴀᴀ ᴀʙʙ ꜱɪʟᴡᴀʟᴇ 👄👄",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋɪ ᴄʜᴜᴛʜ ᴍᴇ ᴍᴇʀᴀ ʟᴜɴᴅ ᴋᴀᴀʟᴀ",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ʟᴇᴛɪ ᴍᴇʀɪ ʟᴜɴᴅ ʙᴀᴅᴇ ᴍᴀꜱᴛɪ ꜱᴇ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴏ ᴍᴇɴᴇ ᴄʜᴏᴅ ᴅᴀʟᴀ ʙᴏʜᴏᴛ ꜱᴀꜱᴛᴇ ꜱᴇ",
        "ʙᴇᴛᴇ ᴛᴜ ʙᴀᴀᴘ ꜱᴇ ʟᴇɢᴀ ᴘᴀɴɢᴀ ᴛᴇʀɪ ᴍᴀᴀᴀ ᴋᴏ ᴄʜᴏᴅ ᴅᴜɴɢᴀ ᴋᴀʀᴋᴇ ɴᴀɴɢᴀ 💦💋",
        "ʜᴀʜᴀʜᴀʜ ᴍᴇʀᴇ ʙᴇᴛᴇ ᴀɢʟɪ ʙᴀᴀʀ ᴀᴘɴɪ ᴍᴀᴀᴋᴏ ʟᴇᴋᴇ ᴀᴀʏᴀ ᴍᴀᴛʜ ᴋᴀᴛ ᴏʀ ᴍᴇʀᴇ ᴍᴏᴛᴇ ʟᴜɴᴅ ꜱᴇ ᴄʜᴜᴅᴡᴀʏᴀ ᴍᴀᴛʜ ᴋᴀʀ",
        "ᴄʜᴀʟ ʙᴇᴛᴀ ᴛᴜᴊʜᴇ ᴍᴀᴀꜰ ᴋɪᴀ 🤣ᴛᴜ ᴀʙʙ ᴀᴘɴɪ ᴍᴀᴋᴏ ʙʜᴇᴊ",
        "ꜱʜᴀʀᴀᴍ ᴋᴀʀ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴀ ʙʜᴏꜱᴅᴀ ᴋɪᴛɴᴀ ɢᴀᴀʟɪᴀ ꜱᴜɴᴡᴀʏᴇɢᴀ ᴀᴘɴɪ ᴍᴀᴀᴀ ʙᴇʜᴇɴ ᴋᴇ ᴜᴘᴇʀ",
        "ᴀʙᴇ ʀᴀɴᴅɪᴋᴇ ʙᴀᴄʜʜᴇ ᴀᴜᴋᴀᴛ ɴʜɪ ʜᴇᴛᴏ ᴀᴘɴɪ ʀᴀɴᴅɪ ᴍᴀᴀᴋᴏ ʟᴇᴋᴇ ᴀᴀʏᴀ ᴍᴀᴛʜ ᴋᴀʀ ʜᴀʜᴀʜᴀʜᴀ",
        "ᴋɪᴅᴢ ᴍᴀᴅᴀʀᴄʜᴏᴅ ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴄʜᴏᴅ ᴄʜᴏᴅᴋᴇ ᴛᴇʀʀ ʟɪʏᴇ ʙʜᴀɪ ᴅᴇᴅɪʏᴀ",
        "ᴊᴜɴɢʟᴇ ᴍᴇ ɴᴀᴄʜᴛᴀ ʜᴇ ᴍᴏʀᴇ ᴛᴇʀɪ ᴍᴀᴀᴋɪ ᴄʜᴜᴅᴀɪ ᴅᴇᴋᴋᴇ ꜱᴀʙ ʙᴏʟᴛᴇ ᴏɴᴄᴇ ᴍᴏʀᴇ ᴏɴᴄᴇ ᴍᴏʀᴇ 🤣🤣💦💋",
        "ɢᴀʟɪ ɢᴀʟɪ ᴍᴇ ʀᴇʜᴛᴀ ʜᴇ ꜱᴀɴᴅ ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴄʜᴏᴅ ᴅᴀʟᴀ ᴏʀ ʙᴀɴᴀ ᴅɪᴀ ʀᴀɴᴅ 🤤🤣",
        "ꜱᴀʙ ʙᴏʟᴛᴇ ᴍᴜᴊʜᴋᴏ ᴘᴀᴘᴀ ᴄʏᴜᴋɪ ᴍᴇɴᴇ ᴋʀᴅɪᴀ ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴘʀᴇɢɴᴇɴᴛ 🤣🤣",
        "ꜱᴜᴀʀ ᴋᴇ ᴘɪʟʟᴇ ᴛᴇʀɪ ᴍᴀᴀᴋɪ ᴄʜᴜᴛʜ ᴍᴇ ꜱᴜᴀʀ ᴋᴀ ʟᴏᴜᴅᴀ ᴏʀ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋɪ ᴄʜᴜᴛʜ ᴍᴇ ᴍᴇʀᴀ ʟᴏᴅᴀ",
        "ᴄʜᴀʟ ᴄʜᴀʟ ᴛᴜ ᴀᴘɴɪ ᴍᴀᴀᴋɪ ᴄʜᴜᴄʜɪʏᴀ ᴅɪᴋᴀ",
        "ʜᴀʜᴀʜᴀʜᴀ ʙᴀᴄʜʜᴇ ᴛᴇʀɪ ᴍᴀᴀᴀᴋᴏ ᴄʜᴏᴅ ᴅɪᴀ ɴᴀɴɢᴀ ᴋᴀʀᴋᴇ",
        "ᴛᴇʀɪ ɢꜰ ʜᴇ ʙᴀᴅɪ ꜱᴇxʏ ᴜꜱᴋᴏ ᴘɪʟᴀᴋᴇ ᴄʜᴏᴏᴅᴇɴɢᴇ ᴘᴇᴘꜱɪ",
        "2 ʀᴜᴘᴀʏ ᴋɪ ᴘᴇᴘꜱɪ ᴛᴇʀɪ ᴍᴜᴍᴍʏ ꜱᴀʙꜱᴇ ꜱᴇxʏ 💋💦",
        "ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴄʜᴇᴇᴍꜱ ꜱᴇ ᴄʜᴜᴅᴡᴀᴠᴜɴɢᴀ ᴍᴀᴅᴇʀᴄʜᴏᴏᴅ ᴋᴇ ᴘɪʟʟᴇ 💦🤣",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋɪ ᴄʜᴜᴛʜ ᴍᴇ ᴍᴜᴛʜᴋᴇ ꜰᴀʀᴀʀ ʜᴏᴊᴀᴠᴜɴɢᴀ ʜᴜɪ ʜᴜɪ ʜᴜɪ",
        "ꜱᴘᴇᴇᴅ ʟᴀᴀᴀ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴄʜᴏᴅᴜ ʀᴀɴᴅɪᴋᴇ ᴘɪʟʟᴇ 💋💦🤣",
        "ᴀʀᴇ ʀᴇ ᴍᴇʀᴇ ʙᴇᴛᴇ ᴄʏᴜ ꜱᴘᴇᴇᴅ ᴘᴀᴋᴀᴅ ɴᴀ ᴘᴀᴀᴀ ʀᴀʜᴀ ᴀᴘɴᴇ ʙᴀᴀᴘ ᴋᴀ ʜᴀʜᴀʜᴀ ᴛᴇʀɪ ᴍᴀᴀ ᴄᴜᴅ ɢᴀɪ🤣🤣",
        "ꜱᴜɴ ꜱᴜɴ ꜱᴜᴀʀ ᴋᴇ ᴘɪʟʟᴇ ᴊʜᴀɴᴛᴏ ᴋᴇ ꜱᴏᴜᴅᴀɢᴀʀ ᴀᴘɴɪ ᴍᴜᴍᴍʏ ᴋɪ ɴᴜᴅᴇꜱ ʙʜᴇᴊ",
        "ᴀʙᴇ ꜱᴜɴ ʟᴏᴅᴇ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴀ ʙʜᴏꜱᴅᴀ ꜰᴀᴀᴅ ᴅᴜɴɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴋʜᴜʟᴇ ʙᴀᴊᴀʀ ᴍᴇ ᴄʜᴏᴅ ᴅᴀʟᴀ 🤣🤣💋",
        "ꜱʜʀᴍ ᴋʀ ᴛᴇʀʏ ᴍᴀᴀ ᴄᴜᴅ ɢᴀɪ ʏʜᴀ",
        "ᴍᴇʀᴇ ʟᴜɴᴅ ᴋᴇ ʙᴀᴀᴀᴀᴀʟʟʟʟʟ ᴘᴋᴅ ᴊᴀʟᴅɪ sᴇ",
        "ᴛᴜ ᴇᴋ ᴋᴀᴀᴍ ᴋʀ ᴀᴘɴɪ ᴍᴀ ʙʜᴇɴ ᴋᴏ ᴄᴜᴅᴡᴀ ʟᴇ ᴍᴇʀᴇ sᴛʜ",
        "ʀɴᴅɪ ᴋᴇ ʟᴅᴋᴇᴇᴇᴇᴇᴇᴇᴇᴇ ᴄʜᴜᴘ ᴏʀ ᴄᴜᴅ ʏʜᴀ",
        "ᴄʜᴜᴘ ᴛᴍᴋᴄ ᴋɪᴅꜱꜱꜱꜱꜱꜱꜱꜱꜱꜱꜱꜱ",
        "ᴀᴘɴɪ ɢᴀᴀɴᴅ ᴍᴇɪɴ ᴍᴜᴛʜɪ ᴅᴀᴀʟ",
        "ᴍᴇʀᴀ ʟᴜɴᴅ ᴄʜᴏᴏꜱ ᴊᴀʟᴅɪ sᴇ",
        "ᴀᴘɴɪ ᴍᴀ ᴋᴏ ᴄᴜsᴡᴀ ᴍᴇʀᴀ ʟᴜɴᴅ",
        "ʙʜᴇɴ ᴋᴇ ʟᴀᴜᴅᴇ ᴛᴍᴄ",
        "ʙʜᴇɴ ᴋᴇ ᴛᴀᴋᴋᴇ ᴛᴍʟ",
        "ᴀʙʟᴀ ᴛᴇʀᴀ ᴋʜᴀɴ ᴅᴀɴ ᴄʜᴏᴅɴᴇ ᴋɪ ʙᴀʀɪɪɪ",
        "ʙᴇᴛᴇ ᴛᴇʀɪ ᴍᴀ ꜱʙꜱᴇ ʙᴅɪ ʀᴀɴᴅ",
        "ʟᴜɴᴅ ᴋᴇ ʙᴀᴀᴀʟ ᴊʜᴀᴛ ᴋᴇ ᴘɪꜱꜱꜱᴜᴜᴜᴜᴜᴜᴜ ᴛᴍᴋᴄ",
        "ʟᴜɴᴅ ᴘᴇ ʟᴛᴋɪᴛ ᴍᴀᴀᴀʟʟʟʟ ᴋɪ ʙᴏɴᴅ ʜ ᴛᴜᴜᴜ",
        "ᴋᴀꜱʜ ᴏꜱ ᴅɪɴ ᴍᴜᴛʜ ᴍʀᴋᴇ ꜱᴏᴊᴛᴀ ᴍ ᴛᴜ ᴘᴀɪᴅᴀ ɴᴀ ʜᴏᴛᴀᴀ",
        "ɢʟᴛɪ ᴋʀᴅɪ ᴛᴜᴊᴡ ᴘᴀɪᴅᴀ ᴋʀᴋᴇ ᴛᴇʀʏ ᴍᴀ ɴᴇ ᴀʙ ᴄᴜᴅ ᴛᴜ ʏʜᴀ",
        "ꜱᴘᴇᴇᴅ ᴘᴋᴅᴅᴅ",
        "ɢᴀᴀɴᴅ ᴍᴀɪɴ ʟᴡᴅᴀ ᴅᴀʟ ʟᴇ ᴀᴘɴɪ ᴍᴇʀᴀᴀᴀ",
        "ɢᴀᴀɴᴅ ᴍᴇɪɴ ʙᴀᴍʙᴜ ᴅᴇᴅᴜɴɢᴀᴀᴀᴀᴀᴀ",
        "ɢᴀɴᴅ ꜰᴛɪ ᴋᴇ ʙᴀʟᴋᴋᴋ ᴛᴜ ᴄᴜᴅ ʏʜᴀ",
        "ɢᴏᴛᴇ ᴋɪᴛɴᴇ ʙʜɪ ʙᴀᴅᴇ ʜᴏ, ʟᴜɴᴅ ᴋᴇ ɴɪᴄʜᴇ ʜɪ ʀᴇʜᴛᴇ ʜᴀɪ",
        "ʜᴀᴢᴀᴀʀ ʟᴜɴᴅ ᴛᴇʀɪ ɢᴀᴀɴᴅ ᴍᴀɪɴ",
        "ᴊʜᴀᴀɴᴛ ᴋᴇ ᴘɪꜱꜱᴜ ᴛᴍᴋᴄ sᴜɴ",
        "ᴛᴇʀɪ ᴍᴀ ᴋɪ ᴋᴀʟɪ ᴄʜᴜᴛ",
        "ᴋʜᴏᴛᴇʏ ᴋɪ ᴀᴜʟᴅᴀ ᴇʏ ᴛᴜ ʀᴀɴᴅʏᴋᴇ",
        "ᴋᴜᴛᴛᴇ ᴋᴀ ᴀᴡʟᴀᴛ ᴊᴀɪsᴀ ʟɢ ʀʜᴀ ᴛᴜ",
        "ᴋᴜᴛᴛᴇ ᴋɪ ᴊᴀᴛ ᴊᴀɪsᴀ ᴇʏ ᴛᴜ ",
        "ᴋᴜᴛᴛᴇ ᴋᴇ ᴛᴀᴛᴛᴀ ᴇʏ ᴛᴜ",
        "ᴛᴇᴛɪ ᴍᴀ ᴋɪ.ᴄʜᴜᴛ , ᴛᴇʀɪ ᴍᴀ ʀɴᴅɪɪɪɪɪɪɪɪɪɪɪɪɪɪɪɪɪɪɪɪ",
        "ʟᴀᴠᴅᴇ ᴋᴇ ʙᴀʟ ᴘᴋᴅ ʟᴇ ᴍᴇʀᴇ",
        "ᴍᴜʜ ᴍᴇɪ ʟᴇʟᴇ ᴍᴇʀᴀ ʟᴜɴᴅ",
        "ʟᴜɴᴅ ᴋᴇ ᴘᴀꜱɪɴᴇ ᴄʜᴜᴘ ʙᴇᴛʜ ᴏʀ ᴄᴜᴅ",
        "ᴍᴇʀᴇ ʟᴡᴅᴇ ᴋᴇ ʙᴀᴀᴀᴀᴀʟʟʟ",
        "ʜᴀʜᴀʜᴀᴀᴀᴀᴀᴀ ᴛᴇʀʏ ᴍᴀᴀ ᴄᴜᴅ ɢᴀɪ",
        "ᴛᴜ ᴄʜᴜᴅ ɢʏᴀᴀᴀᴀᴀ",
        "ʀᴀɴᴅɪ ᴋʜᴀɴᴇ ᴋɪ ᴜʟᴀᴅᴅᴅ",
        "ꜱᴀᴅɪ ʜᴜɪ ɢᴀᴀɴᴅ",
        "ᴛᴇʀɪ ɢᴀᴀɴᴅ ᴍᴀɪɴ ᴋᴜᴛᴇ ᴋᴀ ʟᴜɴᴅ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴀ ʙʜᴏꜱᴅᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ",
        "ᴛᴇʀᴇ ɢᴀᴀɴᴅ ᴍᴇɪɴ ᴋᴇᴇᴅᴇ ᴘᴀᴅᴀʏ",
        "ɴʏ ɴʏ ᴛᴇʀʏ ᴍᴀᴀ ʀᴀɴᴅɪ",
        "ꜱᴜɴɴ ᴍᴀᴅᴇʀᴄʜᴏᴅ ᴛᴍʟ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴀ ʙʜᴏꜱᴅᴀ",
        "ʙᴇʜᴇɴ ᴋ ʟᴜɴᴅ ᴄʜᴜᴘᴄʜᴀᴘ ᴄᴜᴅ ʏʜᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴀ ᴄʜᴜᴛ ᴋɪ ᴄʜᴛɴɪɪɪɪ",
        "ᴍᴇʀᴀ ʟᴀᴡᴅᴀ ʟᴇʟᴇ ᴛᴜ ᴀɢᴀʀ ᴄʜᴀɪʏᴇ ᴛᴏʜ",
        "ᴄʜᴜᴘ ɢᴀᴀɴᴅᴜ",
        "ᴄʜᴜᴘ ᴄʜᴜᴛɪʏᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴘᴇ ᴊᴄʙ ᴄʜᴀᴅʜᴀᴀ ᴅᴜɴɢᴀ",
        "ꜱᴀᴍᴊʜᴀᴀ ʟᴀᴡᴅᴇ",
        "ʏᴀ ᴅᴜ ᴛᴇʀɪ ɢᴀᴀɴᴅ ᴍᴇ ᴛᴀᴘᴀᴀ ᴛᴀᴘ��",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴍᴇʀᴀ ʀᴏᴢ ʟᴇᴛɪ ʜᴀɪ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴇ ꜱᴀᴀᴛʜ ᴍᴍꜱ ʙᴀɴᴀᴀ ᴄʜᴜᴋᴀ ʜᴜ���不�不",
        "ᴛᴜ ᴄʜᴜᴛɪʏᴀ ᴛᴇʀᴀ ᴋʜᴀɴᴅᴀᴀɴ ᴄʜᴜᴛɪʏᴀ",
        "ᴀᴜʀ ᴋɪᴛɴᴀ ʙᴏʟᴜ ʙᴇʏ ᴍᴀɴɴ ʙʜᴀʀ ɢᴀʏᴀ ᴍᴇʀᴀ�不",
        "ᴛᴇʀɪɪɪɪɪɪ ᴍᴀᴀᴀᴀ ᴋɪ ᴄʜᴜᴛᴛᴛ ᴍᴇ ᴀʙᴄᴅ ʟɪᴋʜ ᴅᴜɴɢᴀ ᴍᴀᴀ ᴋᴇ ʟᴏᴅᴇ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ʟᴇᴋᴀʀ ᴍᴀɪ ꜰᴀʀᴀʀ",
        "ᴛᴇʀʏ ᴍᴀᴀ ʀᴀɴɪᴅɪɪɪ",
        "ᴄʜᴜᴘ ʙᴀᴄʜᴇᴇ ᴛᴍᴋᴄ",
        "ᴛᴇʀʏ ᴍᴀᴋᴏᴄʜᴏᴅᴜ",
        "ʀᴀɴᴅɪ ᴍᴀᴀ ᴛᴇʀʏ",
        "ᴛᴜ ʀᴀɴᴅɪ ᴋᴇ ᴘɪʟʟᴀ ᴇʏ",
        "ᴛᴇʀɪɪɪɪɪ ᴍᴀᴀᴀ ᴋᴏ ʙʜᴇᴊᴊᴊ",
        "ᴛᴇʀᴀᴀ ʙᴀᴀᴀᴀᴘ ʜᴜ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴍᴇ ʜᴀᴀᴛ ᴅᴀᴀʟʟᴋᴇ ʙʜᴀᴀɢ ᴊᴀᴀɴᴜɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ꜱᴀʀᴀᴋ ᴘᴇ ʟᴇᴛᴀᴀ ᴅᴜɴɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ɢʙ ʀᴏᴀᴅ ᴘᴇ ʟᴇᴊᴀᴋᴇ ʙᴇᴄʜ ᴅᴜɴɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴍÉ ᴋᴀᴀʟɪ ᴍɪᴛᴄʜ",
        "ᴛᴇʀɪ ᴍᴀᴀ ꜱᴀꜱᴛɪ ʀᴀɴᴅɪ ʜᴀɪ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴍᴇ ᴋᴀʙᴜᴛᴀʀ ᴅᴀᴀʟ ᴋᴇ ꜱᴏᴜᴘ ʙᴀɴᴀᴜɴɢᴀ ᴍᴀᴅᴀʀᴄʜᴏᴅ",
        "ᴛᴇʀɪ ᴍᴀᴀᴀ ʀᴀɴᴅɪ ʜᴀɪ",
        "ᴛᴇʀɪ ᴍᴀᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴍᴇ ᴅᴇᴛᴏʟ ᴅᴀᴀʟ ᴅᴜɴɢᴀ ᴍᴀᴅᴀʀᴄʜᴏᴅ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴀᴀᴀ ʙʜᴏꜱᴅᴀᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴍᴇ ʟᴀᴘᴛᴏᴘ",
        "ᴛᴇʀɪ ᴍᴀᴀ ʀᴀɴᴅɪ ʜᴀɪ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ʙɪꜱᴛᴀʀ ᴘᴇ ʟᴇᴛᴀᴀᴋᴇ ᴄʜᴏᴅᴜɴɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ᴀᴍᴇʀɪᴄᴀ ɢʜᴜᴍᴀᴀᴜɴɢᴀ ᴍᴀᴅᴀʀᴄʜᴏᴅ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴍᴇ ɴᴀᴀʀɪʏᴀʟ ᴘʜᴏʀ ᴅᴜɴɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴇ ɢᴀɴᴅ ᴍᴇ ᴅᴇᴛᴏʟ ᴅᴀᴀʟ ᴅᴜɴɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀᴀ ᴋᴏ ʜᴏʀʟɪᴄᴋꜱ ᴘɪʟᴀᴜɴɢᴀ ᴍᴀᴅᴀʀᴄʜᴏᴅ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ꜱᴀʀᴀᴋ ᴘᴇ ʟᴇᴛᴀᴀᴀ ᴅᴜɴɢᴀᴀᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴀᴀ ʙʜᴏꜱᴅᴀ",
        "ᴍᴇʀᴀᴀᴀ ʟᴜɴᴅ ᴘᴀᴋᴀᴅ ʟᴇ ᴍᴀᴅᴀʀᴄʜᴏᴅ",
        "ᴄʜᴜᴘ ᴛᴇʀɪ ᴍᴀᴀ ᴀᴋᴀᴀ ʙʜᴏꜱᴅᴀᴀ",
        "ᴛᴇʀɪɪɪ ᴍᴀᴀ ᴄʜᴜꜰ ɢᴇʏɪɪ ᴋʏᴀᴀᴀ ʟᴀᴡᴅᴇᴇᴇ",
        "ᴛᴇʀɪɪɪ ᴍᴀᴀ ᴋᴀᴀ ʙᴊꜱᴏᴅᴀᴀᴀ",
        "ᴍᴀᴅᴀʀxʜᴏᴅᴅᴅ",
        "ᴛᴇʀɪᴜᴜɪ ᴍᴀᴀᴀ ᴋᴀᴀ ʙʜꜱᴏᴅᴀᴀᴀ",
        "ᴛᴇʀɪɪɪɪɪɪ ʙᴇʜᴇɴɴɴɴ ᴋᴏ ᴄʜᴏᴅᴅᴅᴜᴜᴜᴜ ᴍᴀᴅᴀʀxʜᴏᴅᴅᴅᴅ",
        "ᴛᴜ ɴɪᴋᴀʟ ᴍᴀᴅᴀʀᴄʜᴏᴅ",
        "ᴄʜᴜᴘ ʀᴀɴᴅɪ ᴋᴇ ʙᴀᴄʜᴇ",
        "ᴛᴇʀᴀ ᴍᴀᴀ ᴍᴇʀɪ ᴊᴀᴀɴ ᴇʏ",
        "ᴛᴇʀɪ ꜱᴇxʏ ʙᴀʜᴇɴ ᴋɪ ᴄʜᴜᴛ ᴏᴘ"
        "👩🏿      👩🏻‍🦳        👵🏼         👱🏿‍♀️     \n👖      👖        👖         👖     \n\nतेरी बहन /तेरी माँ /तेरी दादि/ तेरीभुआ.\n\nसब की 𝐂hu𝐃𝐀i hogi",
        "तेरी माँ के（ ͜.人 ͜.）दबा दूंगा",
        "तेरी मा चुदी हुई थी\nचुदी हुई है\nऔर चुदी हुई रहेगी \n\n\"MARK MY WORD\" 😈",
        "𝐊ʏᴀ?\n𝐂ʏᴀ?\n𝐂ᴜᴀ?\n\n𝐌ᴛᴛ 𝐊ʀʀ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ɪ 𝐂ʜᴜᴛ 𝐏𝐞 𝐓ʜ𝐀ᴘᴘᴀᴅ 𝐌ᴀ𝐚ʀ 𝐃ᴜɴɢᴀ",
        "˚∧＿∧  　+        — ͟͞͞🥛\n(  •‿• )つ  — ͟͞͞ 🥛 \nSpecial attack tery mummy ke chuchiya ka dudu 🐱🎀",
        "Aaj Rakshabandhan Ke Avsar Pr तेरी मांँ मेरे लंड पर राखी Bandh Ke चुदेगी 😍🥰",
        "Sun दोस्त terko ye तीन चीजे कभी nahi भूलनी chaiye 😁👇🏻🤙🏿\n\n1 :- तेरी औकात\n2 :- तेरी बहन का फटा bhosda\n3 :- तेरी मां के भोसड़े में मेरा मूत",
        "Tery Maa Behen Ke Boshde Me Kya Maarun Jaldi Bata 😜🤙",
        "Tery Maa\nⓘ Verified Randy // 🦅🔥",
        "𝐒ᴀʏ 𝐑ᴀɴᴅɪʙᴀᴀᴢ 𝐃ᴀᴅᴅʏ 𓆩💗𓆪",
        "𝐖ᴏ ʙʜɪ ᴋʏᴀ ᴅɪɴ ᴛʜᴇ ᴊᴀʙ ᴛʀʏ ᴍᴀᴀ ᴍᴜᴊʜᴇ 𝐀ᴘɴᴀ 𝐂ʜᴜᴛ 𝐃ᴇᴛɪ ᴛʜɪ ʏᴀᴀʀ 💔🥀👌🏻",
        "𝐀ᴡᴀᴢ 𝐍ɪᴄʜᴇ 𝐆ᴜʟᴀᴀᴍ 🤢👇🏻",
        "𝐓ʀʏ 𝐌ᴀᴀ ɴᴇ 𝐂ʜᴜᴅɴᴇ 𝐌ᴀɪ ɢᴏʟᴅ 𝐌ᴇᴅᴀʟ 𝐉ᴇᴇᴛᴀ ᴇʏ 𝐃ᴏꜱᴛ 🤩👑",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴛ 𝐌ᴇ 𝐌ᴇʀᴀ 𝐋ᴜɴᴅ 🖕🏻😈",
        "𝐁ʜᴏꜱᴀᴅɪᴋᴇ 𝐀ᴘɴɪ 𝐁ᴇʜᴇɴ 𝐂ʜᴜᴅᴀ 🖕🏻😈",
        "𝐑ᴀɴᴅɪ ᴋᴇ 𝐁ᴀᴄᴄʜᴇ 𝐀ᴜᴋᴀᴛ 𝐌ᴇ 𝐑ᴇʜ 🖕🏻😈",
        "𝐌ᴀᴅᴀʀᴄʜᴏᴅ 𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴛ 🖕🏻😈",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋᴀ 𝐁ʜᴏꜱᴅᴀ ᴋʜᴏʟ ᴅᴜɴɢᴀ 🔓😈",
        "𝐁ʜᴇɴᴄʜᴏᴅ ??ᴘɴɪ 𝐀ᴜᴋᴀᴛ 𝐌ᴇ 𝐑ᴇʜ 🤡💩",
        "𝐓𝐌𝐊𝐂 ᴘᴇ 𝐂ʜᴀᴘᴘᴀʟ 𝐌ᴀᴀʀᴜɴɢᴀ 👟💥",
        "𝐁ʜᴏꜱᴅɪᴋᴇ 𝐓ᴇʀɪ 𝐊ʜᴀɴᴅᴀɴ ᴋɪ 𝐁𝐊𝐂 💀🖕🏻",
        "𝐑ᴀɴᴅɪ ᴋɪ 𝐀ᴜʟᴀᴅ ᴄʜᴜᴘ ʜᴏ ᴊᴀ 🔇😒",
        "𝐑ᴀɴᴅɪʙᴀᴀᴢ ka 𝐆ᴜʟᴀᴀᴍ ey ᴛᴜ ᴀʙ ᴛᴜ ʏʜᴀ ᴄᴜᴅᴋᴇ ᴅɪᴋʜᴀ ᴛᴇʀʏ ᴍᴀᴋᴏ ʟᴇᴋʀ 👑😎",
        "𝐓ᴇʀɪ 𝐁ᴇʜᴇɴ ᴋɪ 𝐂ʜᴜᴛ 𝐌ᴇ 𝐌ɪʀᴄʜɪ 🌶️🖕🏻",
        "𝐌ᴀᴅᴀʀᴄʜᴏᴅ 𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴛ 𝐌ᴇ 𝐏ᴀɪʀ 🦶🏻😈",
        "𝐁ʜᴏꜱᴀᴅɪᴋᴇ 𝐓ᴇʀɪ 𝐁ᴇʜᴇɴ ᴋᴀ 𝐁ʜᴏꜱᴅᴀ 🗑️😏",
        "𝐑ᴀɴᴅɪ ᴋᴀ 𝐏ɪʟʟᴀ ʜᴀɪ ᴛᴜ 🐕💩",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋᴏ 𝐁ᴀᴢᴀᴀʀ 𝐌ᴇ 𝐂ʜᴏᴅᴜɴɢᴀ 🌃😈",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴛ 𝐌ᴇ 𝐆ᴀʀᴀᴍ 𝐓ᴇʟ 🌡️🖕🏻",
        "𝐌ᴀᴅᴀʀᴄʜᴏᴅ 𝐓ᴇʀɪ 𝐁ᴇʜᴇɴ ᴍᴇʀɪ 𝐑ᴀɴᴅɪ 💋👿",
        "𝐑ᴀɴᴅɪ ᴋᴇ 𝐁ᴀᴄᴄʜᴇ 𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴛ 🖕🏻😈",
        "𝐓ᴇʀɪ 𝐁ᴇʜᴇɴ ᴋᴏ 𝐑ᴀᴀᴛ ʙʜᴀʀ 𝐂ʜᴏᴅᴜɴɢᴀ 🌙😈",
        "𝐑ᴀɴᴅɪ ᴋᴀ 𝐁ᴀᴄᴄʜᴀ ʜᴀɪ ᴛᴜ ꜱᴀᴀʟᴇ 🤡💀",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴛ 𝐌ᴇ 𝐌ᴇʀᴀ 𝐉ᴏᴏᴛᴀ 👞🖕🏻",
        "𝐑ᴀɴᴅɪʙᴀᴀᴢ 𝐃ᴀᴅᴅʏ ᴋᴀ 𝐆ᴜʟᴀᴀᴍ ʜᴀɪ ᴛᴜ 🥀😤",
        "ᴊɪꜱ ᴅɪɴ ᴛᴜ ᴘᴀɪᴅᴀ ʜᴜᴀ 𝐓ᴇʀɪ 𝐌ᴀᴀ ɴᴇ ꜱᴏᴄʜᴀ ᴛʜᴀ ᴋᴀꜱʜ ᴀʙᴏʀᴛ ᴋᴀʀ ᴅᴇᴛɪ 💀🥀",
        "𝐀ᴘɴɪ 𝐀ᴜᴋᴀᴛ ᴅᴇᴋʜ ᴋᴜᴛᴛᴇ 𝐓ᴇʀʏ 𝐌ᴀ 𝐂ᴜᴅ 𝐑ʜɪ🐕😂",
        "𝐓ᴇʀʏ 𝐌ᴀ 𝐂ᴜᴅ 𝐑ʜɪ 𝐆ᴀʟɪ ᴋᴀ 𝐊ᴜᴛᴛᴀ ʜᴀɪ ᴛᴜ 🐕🗑️",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ɴᴇ ᴍᴜᴊʜᴇ ᴅᴇᴋʜ ᴋᴇ ꜱᴏᴄʜᴀ ᴋᴀꜱʜ ʏᴇ ᴍᴇʀᴀ ʙᴇᴛᴀ ʜᴏᴛᴀ 🫦😏",
        "𝐂ʜᴜᴘ ᴋᴀʀ 𝐌ᴀᴅᴀʀᴄʜᴏᴅ ᴛᴇʀɪ ᴀᴜᴋᴀᴛ ɴᴀʜɪ ᴍᴇʀᴇ ꜱᴀᴀᴍɴᴇ ʙᴏʟɴᴇ ᴋɪ 🤐💀",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴅᴀɪ ᴍᴇ ᴊᴀʙ ᴍᴀɪ ᴛʜᴀ ᴛᴏ ᴛᴜ ᴘᴀɪᴅᴀ ʜᴜᴀ 💀😂",
        "𝐁ʜᴀɢ ʏᴀʜᴀɴ ꜱᴇ ᴋᴜᴛᴛᴇ ᴋᴇ ᴘɪʟʟᴇ 🐕💨",
        "𝐓ᴇʀɪ 𝐁ᴇʜᴇɴ ᴋɪ ꜱᴀᴅɪ 𝐌ᴇ ᴍᴇʀᴀ ʟᴜɴᴅ 💍😈",
        "𝐌ᴀᴅᴀʀᴄʜᴏᴅ ᴀᴘɴɪ 𝐌ᴀᴀ ᴍᴀᴛ ᴄʜᴜᴅᴀ 🖕🏻👹",
        "𝐁ʜᴇɴᴄʜᴏᴅ 𝐓ᴇʀɪ 𝐊ʜᴀɴᴅᴀɴ ᴋɪ 𝐁𝐊𝐂 💀🖕🏻",
        "tery ma cudke pgl dekh..𝐁𝐊𝐂 🦴🐕",
        "𝐊ʏᴀ 𝐑ᴇ 𝐑ᴀɴᴅɪᴋᴇ 𝐂ᴏᴏʟ 𝐁ᴀɴᴇɢᴀ 𝐓ᴜ 𝐂ʜᴀʟ 𝐀ʙ 𝐂ʜᴜᴅ 𝐀ᴘɴᴇ 𝐁ᴀᴀᴘ - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 𝐒ᴇ - 🦢💘",
        "tery 𝐌ᴀᴀ cudke 𝐌ᴀʀʀ  𝐆ᴀʏɪ 𝐘ᴀᴀʀ - 𝐉ᴀɪ - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 ! 🌙",
        "acha beta 😂🔥👊🏻 ? coi na me toh HATER codunga tery mako 😹💔🔥😆👊🏻💥",
        "chudke bhaga kaise 😂💥🤣🤘🏻",
        "ne toh - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 ka lun muh me lelia tune or tery maa ne😂🙏🏻😂🙏🏻",
        "try maa सूर्य☀ nikalte hi pel du 😹🔥💔",
        "mkl lun te vaj 😂✊🏻💦",
        "𝗧ᴍᴋ𝗕 pe - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 ka hamla 😂⚔🔥💥",
        "𝐂ʜʟ 𝐇ᴀʀᴍᴢᴀᴅ𝐈 𝐊ᴇ लड़के 💛🤍🩵",
        "oi 𝐓ᴇʀɪ 𝐌‌ᴀᴀ गुलाम ₰🖤",
        "chl rndyce chud ke dikha 😂💥🤣🔥",
        "tery 𝐌ᴀᴀ or bhen 𝐌ᴀʀʀ  𝐆ᴀʏɪ naacho 💃🏻💃🏻🕺🏻🎶😂😆💞🔥 !",
        "tera baap bass - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 ey 😂🎀",
        "try maa hagte hue paad mari -#😹🔥🥀",
        "𝐓ᴇʀɪ 𝐌ᴜᴍᴍʏ 𝐂ʜᴏᴅ 𝐃ɪ - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 𝐍ᴇ 𝐁ᴡᴀʜᴀʜᴀʜᴀ ⚜",
        "⋆｡ﾟ☁︎｡𝐂ʏᴜ 𝐑ᴇ मदरचोद - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 बाप के सामने 𝐅ʏᴛᴇʀ 𝐁ᴀɴᴇɢᴀ ⋆𓂃 ོ☼𓂃 😂🔥",
        "नहीं नहीं तेरी मां को 𝐒ɪʀғ - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 बाप चोद सकता है ִֶָ𓂃 ࣪ ִֶָ👑་༘࿐ sᴀᴍᴊʜᴀ ʀᴀɴᴅɪᴋᴇ ???",
        "तेरी मां का 𝐒ᴛʏʟɪsʜ भोसड़ा 😱",
        "𝑻𝒆𝒓?? 𝒎𝒂𝒂 𝒓𝒂𝒏𝒅𝒂𝒍 𝒉 𝒃𝒂𝒔 𝒃𝒂𝒂𝒕 𝒌𝒉𝒂𝒕𝒂𝒎 😡🔥",
        "सोच तेरी बहन को - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 बाप का गुलाम चोद रहा 😎🔥",
        "Hello hello?? Oxygen aarahi है? रण्डी पुत्र 🧘🏻",
        "Shut up रंडीके वरना दुनिया यही बोलेगी तेरी बहन - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 /~ 👑 बाप से सही chudi 🥵🔥",
        "ᴛᴜ ᴏʀ ᴛᴇʀɪ ᴍᴀᴀ ᴅᴏɴᴏ - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 बाप के ʟɴᴅ sᴇ ᴋᴀʙʜɪ ᴜᴛʜ ɴʜɪ ᴘᴀʏᴇ 😂🔥",
        "🇮🇳𝐵𝐻𝐴𝑅𝐴𝑇 𝐻𝐴𝑀𝐴𝑅𝐴 𝐷𝐸𝑆𝐻 𝐻 𝐴𝑈𝑅 𝑈𝑆 𝐷𝐸𝑆𝐻 𝑀𝐸 तेरी मां घर घर जाके MOAN करती है ! 🛐",
        "Tᴇʀɪ Mᴀᴀ Rᴀɴᴅɪ (🩷)—(❤️)—(🧡)—(💛)—(💚)—(🩵)—(💙)—(💜)—(🖤)—(🩶)—(🤍)—(🤎)—(🌸)—(✨)—(🌙)—(⭐)—(🦋)—(💎)—(👑)—(⚡)—(🔥)—(🌌)—(🎀)—(💫)—(🪽)—(🫧)—(🌸)—(💘)—(💓)—(💖)—(💕)—(💞)",
        "Teri make hath me chakku se hole karke lund daluga apna 🤢🤢",
        "Subha ho ya sham chudte rhena hai teri maaka kaam😂🔥😂🔥😂🔥",
        "𝐓ᴜ 𝐒ᴡɪᴘᴇ 𝐊ᴀʀᴛᴀ 𝐑ᴇʜ 𝐌ᴀɪ ᴄʜᴀʟᴀ 𝐓ᴇʀɪ 𝐁ᴇʜᴇɴ ᴋᴇ 𝐒ᴀᴛʜ 𝐊ʜᴇʟɴᴇ 😭😭",
        "🍑\n🟨  😂\n🟨🟥🟥🟨\n     🟥🟥🟨\n     ⬛⬛ \n     ⬛⬛\nTery ma ki bund hi okhad li.",
        "𝘗𝘺𝘢𝘴 𝘭𝘢𝘨 𝘳𝘢𝘩𝘪 𝘵𝘦𝘳𝘪 𝘮𝘢𝘢 𝘬𝘰 𝘤𝘰𝘥 𝘬𝘦 𝘱𝘺𝘢𝘴 𝘣𝘶𝘫𝘩𝘢𝘶𝘯𝘨𝘢 🖕🏿😂🔥🙏🏿",
        "▶︎ •၊၊၊|။||။‌‌‌‌‌၊|• 0:60\n𝘋𝘦𝘬𝘩 𝘵𝘦𝘳𝘪 𝘣𝘦𝘩𝘦𝘯 ??𝘪 𝘤𝘩𝘪𝘬𝘩 😂😱🔥🙏🏿",
        "      ᴹᴱ:\n👆       🤬 ᴷᴬᴴᴬ ᴮᴴᴬᴳᵀᴵ ᴴᴬᴵ ᴿᴬᴺᴰᴵ\n  🐛💤👔🤳\n            ⛽  👢\n          ⚡👟\n       🎸    🌂\n      👢       👢     ᵀᴱᴿᴵ ᴹᴬᴬ:🏃‍♀‍➡️ᴹᵁᴶᴴᴱ ᴹᴬᵀ ᶜᴴᴼᴰᴼ",
        "🙌\n😛 ᴹᴱ:\n  |      👩 ᵀᴱᴿᴵ ᴹᴬᴬ:\n  |   8_/ 👐\n / \\  / \\\n  \"Take a look how i am chodunging your Mummy in ghodi pose 🗿\"",
        "../\\_/\\\n  ( • _ •)  \n  /    >🍆 \n\nʏᴇ ᴘᴀᴋᴀᴅᴏ ᴀᴘᴋɪ ᴍᴏᴍ ᴋᴏ ᴀᴘɴᴇ ᴄʜᴜᴛ ᴍᴇ ɢʜᴜssᴀ ɴᴇ ᴍᴇ ᴋᴀᴀᴍ ᴀʏᴇɴɢᴀ 🤗",
        "ㅤㅤ😎 ᴹᴱ:\n          |\\👐\n         / \\_\n━━━━━┓ ＼＼\n┓┓┓┓┓┃ᵀᴼᴴᴬᴿ ᴿᴬᴺᴰᴵ ᴹᴬᴬ:\n┓┓┓┓┓┃ ヽ😩ノ\n┓┓┓┓┓┃ 　 /　ᴼᴿᴵᴵ ᴬᴹᴹᴬ\n┓┓┓┓┓┃  ノ)　\n┓┓┓┓┓┃\n\nLE TERI MAA KO CHOD KAR FHEK DIA 🥸",
        "😎 ᴍᴀɪ:\nく|)へ\n   〉\n￣┗┓       ヾ😫ｼ ᴛᴇʀɪ ᴍᴀᴀ:\n         ┗┓   ヘ/    \n             ┗┓ノ\n                 ┗┓       ヾ😨ｼ ᴛᴇʀᴀ ʙᴀᴀᴘ:\n                      ┗┓   ヘ/\n                          ┗┓ノ\n                               ┗┓       ヾ😩ｼ ᴛᴇʀᴀ ᴄʜᴀᴄʜᴀ:\n                                   ┗┓   ヘ/    \n                                       ┗┓ノ\nᴅᴇᴋʜ ᴀɪsᴇ ʜɪ ʟᴀᴀᴛ ᴍᴀᴀʀ ᴋᴀʀ ʙʜᴀɢᴀᴜɴɢᴀ ᴛᴇʀᴇ ᴋʜᴀᴀɴᴅᴀɴ ᴋᴏ 🤫🤣",
        "╭👇 ͡ ͡° ͜   ͡ ͡°)╭👇 \n      \\   .   .\\\n        \\        \\\n         \\╰[ ]╯\\ \n          /   U   \\\n       👟       👟\n\nᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ᴍᴇʀᴀ ʟᴜɴᴅ ᴍᴜʙᴀʀᴀᴋ ʜᴏ 😝",
        "Once a man said: \n\"You deserve all the chudayi and teri maa ki chutt dhulayi, and this text proves it! You should be proud!\" 🕊️",
        "😏 ᴍᴀɪ:\n    | 👐💵\n    |//    💵\n    |          💸 ᴛᴇʀɪ ʀᴀɴᴅʏ ᴍᴀᴀ:\n   /\\            👯👯\n👟👟\n\nDᴇᴋʜ Kᴇsᴇ Tᴇʀɪ Mᴀᴀ Kᴏ Aᴘɴᴇ Pᴀɪsᴏ Sᴇ Rᴀɴᴅɪ Nᴀᴄʜ Kᴀʀᴡᴀ Rʜᴀ Hᴜ 🤙😎",
        "Loading your maa ki chudai video 😳\n\n■■■■■■■■□\n99%",
        "Sun दोस्त terko ye तीन चीजे कभी nahi भूलनी chaiye  😁👇🏻🤙🏿\n\n1 :- तेरी औकात\n2 :- तेरी बहन का फटा bhosda\n3 :- तेरी मां के भोसड़े में मेरा मूत",
        "this message could't be display because teri maa randy ey",
                    
        ]

        reply_texts = [
        "⋆｡ﾟ☁︎｡𝐂ʏᴜ 𝐑ᴇ मदरचोद  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के सामने 𝐅ʏᴛᴇʀ 𝐁ᴀɴᴇɢᴀ ⋆𓂃 ོ☼𓂃 😂🔥",
        "नहीं नहीं तेरी मां को 𝐒ɪʀғ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप चोद सकता है ִֶָ𓂃 ࣪ ִֶָ👑་༘࿐ sᴀᴍᴊʜᴀ ʀᴀɴᴅɪᴋᴇ ???",
        "तेरी मां का 𝐒ᴛʏʟɪsʜ भोसड़ा 😱",
        "𝑻𝒆𝒓𝒚 𝒎𝒂𝒂 𝒓𝒂𝒏𝒅𝒂𝒍 𝒉 𝒃𝒂𝒔 𝒃𝒂𝒂𝒕 𝒌𝒉𝒂𝒕𝒂𝒎 😡🔥",
        "सोच तेरी बहन को  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप का गुलाम चोद रहा 😎🔥",
        "Hello hello?? SAAS aarahi है? रण्डी पुत्र 🧘🏻",
        "Shut up रंडीके वरना दुनिया यही बोलेगी तेरी बहन  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  /\\~ 👑 बाप से सही chudi 🥵🔥",
        "ᴛᴜ ᴏʀ ᴛᴇʀɪ ᴍᴀᴀ ᴅᴏɴᴏ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के ʟɴᴅ sᴇ ᴋᴀʙʜɪ ᴜᴛʜ ɴʜɪ ᴘᴀʏᴇ 😂🔥",
        "🇮🇳𝐵𝐻𝐴𝑅𝐴𝑇 𝐻𝐴𝑀𝐴𝑅𝐴 𝐷𝐸𝑆𝐻 𝐻 𝐴𝑈𝑅 𝑈𝑆 𝐷𝐸𝑆𝐻 𝑀𝐸 तेरी मां घर घर जाके SHAMBHOG करती है ! 🛐",
        "⋆｡ﾟ☁︎｡𝐂ʏᴜ 𝐑ᴇ मदरचोद  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के सामने 𝐅ʏᴛᴇʀ 𝐁ᴀɴᴇɢᴀ ⋆𓂃 ོ☼𓂃 😂🔥",
        "नहीं नहीं तेरी मां को 𝐒ɪʀғ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप चोद सकता है ִֶָ𓂃 ࣪ ִֶָ👑་༘࿐ sᴀᴍᴊʜᴀ ʀᴀɴᴅɪᴋᴇ ???",
        "तेरी मां का 𝐒ᴛʏʟɪsʜ भोसड़ा 😱",
        "𝑻𝒆𝒓𝒚 𝒎𝒂𝒂 𝒓𝒂𝒏𝒅𝒂𝒍 𝒉 𝒃𝒂𝒔 𝒃𝒂𝒂𝒕 𝒌𝒉𝒂𝒕𝒂𝒎 😡🔥",
        "सोच तेरी बहन को  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप का गुलाम चोद रहा 😎🔥",
        "Hello hello?? saas aarahi है? रण्डी पुत्र 🧘🏻",
        "Shut up रंडीके वरना दुनिया यही बोलेगी तेरी बहन  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  /\\~ 👑 बाप से सही chudi 🥵🔥",
        "ᴛᴜ ᴏʀ ᴛᴇʀɪ ᴍᴀᴀ ᴅᴏɴᴏ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के ʟɴᴅ sᴇ ᴋᴀʙʜɪ ᴜᴛʜ ɴʜɪ ᴘᴀʏᴇ 😂🔥",
        "🇮🇳𝐵𝐻𝐴𝑅𝐴𝑇 𝐻𝐴𝑀𝐴𝑅𝐴 𝐷𝐸𝑆𝐻 𝐻 𝐴𝑈𝑅 𝑈𝑆 𝐷𝐸𝑆𝐻 𝑀𝐸 तेरी मां घर घर जाके SAMBHOG करती है ! 🛐",
        "⋆｡ﾟ☁︎｡𝐂ʏᴜ 𝐑ᴇ मदरचोद  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के सामने 𝐅ʏᴛᴇʀ 𝐁ᴀɴᴇɢᴀ ⋆𓂃 ོ☼𓂃 😂🔥",
        "नहीं नहीं तेरी मां को 𝐒ɪʀғ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप चोद सकता है ִֶָ𓂃 ࣪ ִֶָ👑་༘࿐ sᴀᴍᴊʜᴀ ʀᴀɴᴅɪᴋᴇ ???",
        "तेरी मां का 𝐒ᴛʏʟɪsʜ भोसड़ा 😱",
        "𝑻𝒆𝒓𝒚 𝒎𝒂𝒂 𝒓𝒂𝒏𝒅𝒂𝒍 𝒉 𝒃𝒂𝒔 𝒃𝒂𝒂𝒕 𝒌𝒉𝒂𝒕𝒂𝒎 😡🔥",
        "सोच तेरी बहन को  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप का गुलाम चोद रहा 😎🔥",
        "Hello hello?? SAAS aarahi है? रण्डी पुत्र 🧘🏻",
        "Shut up रंडीके वरना दुनिया यही बोलेगी तेरी बहन  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  /\\~ 👑 बाप से सही chudi 🥵🔥",
        "ᴛᴜ ᴏʀ ᴛᴇʀɪ ᴍᴀᴀ ᴅᴏɴᴏ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के ʟɴᴅ sᴇ ᴋᴀʙʜɪ ᴜᴛʜ ɴʜɪ ᴘᴀʏᴇ 😂🔥",
        "🇮🇳𝐵𝐻𝐴𝑅𝐴𝑇 𝐻𝐴𝑀𝐴𝑅𝐴 𝐷𝐸𝑆𝐻 𝐻 𝐴𝑈𝑅 𝑈𝑆 𝐷𝐸𝑆𝐻 𝑀𝐸 तेरी मां घर घर जाके SAMBHOG करती है ! 🛐",
        "⋆｡ﾟ☁︎｡𝐂ʏᴜ 𝐑ᴇ मदरचोद  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के सामने 𝐅ʏᴛᴇʀ 𝐁ᴀɴᴇɢᴀ ⋆𓂃 ོ☼𓂃 😂🔥",
        "नहीं नहीं तेरी मां को 𝐒ɪʀғ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप चोद सकता है ִֶָ𓂃 ࣪ ִֶָ👑་༘࿐ sᴀᴍᴊʜᴀ ʀᴀɴᴅɪᴋᴇ ???",
        "तेरी मां का 𝐒ᴛʏʟɪsʜ भोसड़ा 😱",
        "𝑻𝒆𝒓𝒚 𝒎𝒂𝒂 𝒓𝒂𝒏𝒅𝒂𝒍 𝒉 𝒃𝒂𝒔 𝒃𝒂𝒂𝒕 𝒌𝒉𝒂𝒕𝒂𝒎 😡🔥",
        "सोच तेरी बहन को  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप का गुलाम चोद रहा 😎🔥",
        "Hello hello?? SAAS aarahi है? रण्डी पुत्र 🧘🏻",
        "Shut up रंडीके वरना दुनिया यही बोलेगी तेरी बहन  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  /\\~ 👑 बाप से सही chudi 🥵🔥",
        "ᴛᴜ ᴏʀ ᴛᴇʀɪ ᴍᴀᴀ ᴅᴏɴᴏ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के ʟɴᴅ sᴇ ᴋᴀʙʜɪ ᴜᴛʜ ɴʜɪ ᴘᴀʏᴇ 😂🔥",
        "𝙃𝙀𝙔 𝙂𝙊𝙊𝙂𝙇𝙀 𝙁𝙐𝘾𝙆 𝙃𝙄𝙎 𝙈𝙊𝙈 𝙋𝙍𝙊𝙋𝙀𝙍𝙇𝙔",
        "𝙃𝙀𝙔 𝙂𝙊𝙊𝙂𝙇𝙀 𝘼𝙎𝙆 𝙃𝙄𝙈 𝙏𝙊 𝘾𝙊𝙑𝙀𝙍 𝙃𝙄𝙎 𝙈𝙊𝙈'𝙎 𝘼𝙎𝙎",
        "𝙃𝙀𝙔 𝙂𝙊𝙊𝙂𝙇𝙀 𝙁𝙄𝙓 𝙈𝙔 𝘼‌𝙋𝙋𝙊𝙄𝙉𝙏𝙈𝙀𝙉𝙏 𝙒𝙄𝙏𝙃 𝙃𝙄𝙎 𝙎𝙄𝙎",
        "𝙃𝙀𝙔 𝙂𝙊𝙊𝙂𝙇𝙀 𝙁𝙐𝘾𝙆 𝘼𝙉𝘿 𝙏𝙃𝙍𝙊𝙒 𝙏𝙃𝙄𝙎 𝙂𝘼𝙍𝙀𝙀𝘽 𝙎𝙊𝙉",
        "𝙃𝙀𝙔 𝙂𝙊𝙊𝙂𝙇𝙀 𝘿𝙊 𝙉𝙊𝙏 𝙎𝙏𝙊𝙋 𝙁𝙐𝘾𝙆𝙄𝙉𝙂 𝙈𝙔 𝙂𝙐𝙇𝘼‌𝙈",
        "𝙂𝙀𝙈𝙄𝙉𝙄 𝙎𝘼𝙄𝘿  𝙄𝙎 𝙍𝙉𝘿𝙔 𝙋𝙐𝙏𝙍𝘼",
        "𝙋𝙀𝙍𝙋𝙇𝙀𝙓𝙄𝙏𝙔 𝙎𝘼𝙄𝘿 This 𝙄𝙎 𝙂𝙐𝙇𝘼𝙈",
        "𝙂𝙍𝙊𝙆 𝘼𝙄 𝙎𝘼𝙄𝘿 𝙄𝙎 𝙂𝘼𝙍𝙀𝙀𝘽",
        "𝘽𝙊𝙏 𝙎𝘼‌𝙄𝘿  𝙄𝙎 𝘾𝙃𝙐𝘿𝘼𝙆𝘼𝘿",
        "𝙈𝙊𝘿𝙄 𝙎𝘼‌𝙄𝘿  𝙄𝙎 𝙋𝙊𝙇𝙀 𝘿𝘼𝙉𝘾𝙀𝙍",
        "𝙏𝙍𝙐𝙈𝙋 𝙎𝘼𝙄𝘿 THis 𝙄𝙎 𝘽𝙇𝙊𝙊𝘿Y 𝙈𝙊𝙏𝙃𝙀𝙍𝙁*\"𝘾𝙆𝙀𝙍",
        "𝗧𝗢𝗛𝗔𝗥 𝗠𝗨𝗠𝗠𝗬 𝗞𝗜 𝗖𝗛𝗨𝗨‌𝗧 𝗠𝗘𝗜 𝗣𝗨𝗥𝗜 𝗞𝗜 𝗣𝗨𝗥𝗜 𝗞𝗜𝗡𝗚𝗙𝗜𝗦𝗛𝗘𝗥 𝗞𝗜 𝗕𝗢𝗧𝗧𝗟𝗘 𝗗𝗔𝗟 𝗞𝗘 𝗧𝗢𝗗 𝗗𝗨𝗡𝗚𝗔 𝗔𝗡𝗗𝗘𝗥 𝗛𝗜 😱😂🤩",
        "𝐓𝐄𝐑𝐈 𝐌𝐀𝐀 𝐊𝐈 𝐂𝐇𝐔𝐓 𝐌𝐄 ✋ 𝐇𝐀𝐓𝐓𝐇 𝐃𝐀𝐋𝐊𝐄 👶 𝐁𝐀𝐂𝐂𝐇𝐄 𝐍𝐈𝐊𝐀𝐋 𝐃𝐔𝐍𝐆𝐀 😍",
        "𝐓𝐄𝐑𝐀 𝐏𝐄𝐇𝐋𝐀 𝐁𝐀𝐀𝐏 𝐇𝐔 𝐌𝐀𝐃𝐀𝐑𝐂𝐇𝐎𝐃",
        "𝗧𝗘𝗥𝗜 𝗠𝗨𝗠𝗠𝗬 𝗞𝗘 𝗦𝗔𝗔𝗧𝗛 𝗟𝗨𝗗𝗼 𝗞𝗛𝗘𝗟𝗧𝗘 𝗞𝗛𝗘𝗟𝗧𝗘 𝗨𝗦𝗞𝗘 𝗠𝗨𝗛 𝗠𝗘 𝗔𝗣𝗡𝗔 𝗟𝗢𝗗𝗔 𝗗𝗘 𝗗𝗨𝗡𝗚𝗔☝🏻☝🏻😬",
        "𝗧𝗘𝗥𝗜 𝗠𝗔‌𝗔‌ 𝗞𝗜 𝗖𝗛𝗨𝗨‌𝗧 𝗠𝗘 𝗦𝗨𝗧𝗟𝗜 𝗕𝗢𝗠𝗕 𝗙𝗢𝗗 𝗗𝗨𝗡𝗚𝗔 𝗧𝗘𝗥𝗜 𝗠𝗔‌𝗔‌ 𝗞𝗜 𝗝𝗛𝗔𝗔𝗧𝗘 𝗝𝗔𝗟 𝗞𝗘 𝗞𝗛𝗔𝗔𝗞 𝗛𝗢 𝗝𝗔𝗬𝗘𝗚𝗜💣🔥",
        "𝐓𝐄𝐑𝐈 𝐕𝐀𝐇𝐄𝐈𝐍 𝐊𝐎 𝐀𝐏𝐍𝐄 𝐋𝐔𝐍𝐃 𝐏𝐑 𝐈𝐓𝐍𝐀 𝐉𝐇𝐔𝐋𝐀𝐀𝐔𝐍𝐆𝐀 𝐊𝐈 𝐉𝐇𝐔𝐋𝐓𝐄 𝐉𝐇𝐔𝐋𝐓𝐄 𝐇𝐈 𝐁𝐀𝐂𝐇𝐀 𝐏𝐀𝐈𝐃𝐀 𝐊𝐑 𝐃𝐄𝐆𝐈 💦💋",
        "𝐆𝐀𝐋𝐈 𝐆𝐀𝐋𝐈 𝐌𝐄 𝐑𝐄𝐇𝐓𝐀 𝐇𝐄 𝐒𝐀𝐍𝐃 𝐓𝐄𝐑𝐈 𝐌𝐀𝐀𝐊𝐎 𝐂𝐇𝐎𝐃 𝐃𝐀𝐋𝐀 𝐎𝐑 𝐁𝐀𝐍𝐀 𝐃𝐈𝐀 𝐑𝐀𝐍𝐃 🤤🤣",
        "𝐒𝐀𝐁 𝐁𝐎𝐋𝐓𝐄 𝐌𝐔𝐉𝐇𝐊𝐎 𝐏𝐀𝐏𝐀 𝐊𝐘𝐎𝐔𝐍𝐊𝐈 𝐌𝐄𝐍𝐄 𝐁𝐀𝐍𝐀𝐃𝐈𝐀 𝐓𝐄𝐑𝐈 𝐌𝐀𝐀𝐊𝐎 𝐏𝐑𝐄𝐆𝐍𝐄𝐍𝐓 🤣🤣",
        "𝙏𝙀𝙍𝙄 𝘽𝙀𝙃𝙀𝙉 𝙇𝙀𝙏𝙄 𝙈𝙀𝙍𝙄 𝙇𝙐𝙉𝘿 𝘽𝘼𝘿𝙀 𝙈𝘼𝙎𝙏𝙄 𝙎𝙀 𝙏𝙀𝙍𝙄 𝘽𝙀𝙃𝙀𝙉 𝙆𝙊 𝙈𝙀𝙉𝙀 𝘾𝙃𝙊𝘿 𝘿𝘼𝙇𝘼 𝘽𝙊𝙃𝙊𝙏 𝙎𝘼𝙎𝙏𝙀 𝙎𝙀",
        "𝗧𝗘𝗥𝗜 𝗠𝗔‌𝗔‌ 𝗞𝗜 𝗖𝗛𝗨𝗨‌𝗧 𝗠𝗘 𝗖𝗛𝗔𝗡𝗚𝗘𝗦 𝗖𝗢𝗠𝗠𝗜𝗧 𝗞𝗥𝗨𝗚𝗔 𝗙𝗜𝗥 𝗧𝗘𝗥𝗜 𝗕𝗛𝗘𝗘𝗡 𝗞𝗜 𝗖𝗛𝗨𝗨‌𝗧 𝗔𝗨𝗧𝗢𝗠𝗔𝗧𝗜𝗖𝗔𝗟𝗟𝗬 𝗨𝗣𝗗𝗔𝗧𝗘 𝗛𝗢𝗝𝗔𝗔𝗬𝗘𝗚𝗜🤖🙏🤔",
        "𝐓𝐄𝐑𝐈 𝐌𝐀𝐀𝐀𝐊𝐈 𝐂𝐇𝐔𝐃𝐀𝐈 𝐊𝐎 𝐏𝐎𝐑𝐍𝐇𝐔𝐁.𝐂𝐎𝐌 𝐏𝐄 𝐔𝐏𝐋𝐎𝐀𝐃 𝐊𝐀𝐑𝐃𝐔𝐍𝐆𝐀 𝐒𝐔𝐀𝐑 𝐊𝐄 𝐂𝐇𝐎𝐃𝐄 🤣💋💦",
        "𝐓𝐄𝐑𝐈 𝐁𝐀𝐇𝐄𝐍 𝐊𝐈 𝐆𝐀𝐀𝐍𝐃 𝐌𝐄𝐈 𝐎𝐍𝐄𝐏𝐋𝐔𝐒 𝐊𝐀 𝐖𝐑𝐀𝐏 𝐂𝐇𝐀𝐑𝐆𝐄𝐑 𝟑𝟎𝐖 𝐇𝐈𝐆𝐇 𝐏𝐎𝐖𝐄𝐑 💥😂😎",
        "𝐓𝐔𝐉𝐇𝐄 𝐀𝐁 𝐓𝐀𝐊 𝐍𝐀𝐇𝐈 𝐒𝐌𝐉𝐇 𝐀𝐘𝐀 𝐊𝐈 𝐌𝐀𝐈 𝐇𝐈 𝐇𝐔 𝐓𝐔𝐉𝐇𝐄 𝐏𝐀𝐈𝐃𝐀 𝐊𝐀𝐑𝐍𝐄 𝐖𝐀𝐋𝐀 𝐁𝐇𝐎𝐒𝐃𝐈𝐊𝐄𝐄 𝐀𝐏𝐍𝐈 𝐌𝐀𝐀 𝐒𝐄 𝐏𝐔𝐂𝐇 𝐑𝐀𝐍𝐃𝐈 𝐊𝐄 𝐁𝐀𝐂𝐇𝐄𝐄𝐄𝐄 🤩👊👤😍",
        "𝐓𝐄𝐑𝐈 𝐁𝐀𝐇𝐄𝐍 𝐊𝐈 𝐂𝐇𝐔𝐓 𝐌𝐄𝐈 𝐀𝐏𝐏𝐋𝐄 𝐊𝐀 𝟏𝟖𝐖 𝐖𝐀𝐋𝐀 𝐂𝐇𝐀𝐑𝐆𝐄𝐑 🔥🤩",
        "𝗧𝗘𝗥𝗜 𝗠𝗔‌𝗔‌ 𝗞𝗢 𝗜𝗧𝗡𝗔 𝗖𝗛𝗢𝗗𝗨𝗡𝗚𝗔 𝗞𝗜 𝗦𝗔𝗣𝗡𝗘 𝗠𝗘𝗜 𝗕𝗛𝗜 𝗠𝗘𝗥𝗜 𝗖𝗛𝗨𝗗𝗔𝗜 𝗬𝗔𝗔𝗗 𝗞𝗔𝗥𝗘𝗚𝗜 𝗥Æ𝗡𝗗𝗜 🥳😍👊💥",
        "𝙋𝘼𝙋𝘼 𝙆𝙄 𝙎𝙋𝙀𝙀𝘿 𝙈𝙏𝘾𝙃 𝙉𝙃𝙄 𝙃𝙊 𝙍𝙃𝙄 𝙆𝙔𝘼",
        "𝙆𝙄𝙏𝙉𝙄 𝘾𝙃𝙊𝘿𝙐 𝙏𝙀𝙍𝙄 𝙈𝘼 𝘼𝘽 𝙊𝙍..",
        "𝗧𝗘𝗥𝗜 𝗠𝗔𝗨𝗦𝗜 𝗞𝗘 𝗕𝗛𝗢𝗦𝗗𝗘 𝗠𝗘𝗜 𝗜𝗡𝗗𝗜𝗔𝗡 𝗥𝗔𝗜𝗟𝗪𝗔𝗬 🚂💥😂",
        "𝙆𝙄𝙏𝙉𝙄 𝙂𝙇𝙄𝙔𝘼 𝙋𝘿𝙒𝙀𝙂𝘼 𝘼𝙋𝙉𝙄 𝙈𝘼 𝙆𝙊",
        "𝗧𝗘𝗥𝗜 𝗜𝗧𝗘𝗠 𝗞𝗜 𝗚𝗔𝗔𝗡𝗗 𝗠𝗘 𝗟𝗨𝗡𝗗 𝗗𝗔𝗔𝗟𝗞𝗘,𝗧𝗘𝗥𝗘 𝗝𝗔𝗜𝗦𝗔 𝗘𝗞 𝗢𝗥 𝗡𝗜𝗞𝗔𝗔𝗟 𝗗𝗨𝗡𝗚𝗔 𝗠𝗔‌𝗔‌𝗗𝗔𝗥𝗖𝗛Ø𝗗🤘🏻🙌🏻☠️",
        "2 𝙍𝙐𝙋𝘼𝙔 𝙆𝙄 𝙋𝙀𝙋𝙎𝙄 𝙏𝙀𝙍𝙄 𝙈𝙐𝙈𝙈𝙔 𝙎𝘼𝘽𝙎𝙀 𝙎𝙀𝙓𝙔 💋💦",
        "🇮🇳𝐵𝐻𝐴𝑅𝐴𝑇 𝐻𝐴𝑀𝐴𝑅𝐴 𝐷𝐸𝑆𝐻 𝐻 𝐴𝑈𝑅 𝑈𝑆 𝐷𝐸𝑆𝐻 𝑀𝐸 तेरी मां घर घर जाके SAMBHOG करती है ! 🛐"
        "Baap bhi bnale muje rndike",
        "Tera baap randibaaz ey yaad ey tujhe",
        "Tu apni Maa cuda na tympass",
        "Oye unfunny swipe mtt kr",
        "Oh hello bihari tera baap bihari or tu v bihari aaukat me rha kr.",
        "Oyy kinner tujhe gc me aane ki permission kisne di.",
        "Cudke dikha",
        "Cudke dikha ek baar.",
        "Sun sun ma cuda.",
        "Teri maca bhosda.",
        "Oye choti jati ke tmr.",
        "Ky? jldi likh kidde.",
        "Bihari com gang ke baap ko tag crega tu",
        "Mujhe cya tu bihari ey tmkc bs",
        "Jaldi se randibaaz papa bol",
        "Side hoja bihari tery maa cud gai ab",
        "Hye pgl bhg mat ache se cud",
        "bhg ny randyke tu ajj",
        "Hye pgl ke bche bhag mat",
        "Hye dur hatt madchod ke bache",
        "koi bat ny tery maa randy ey esliye maf cr rha hu tujhe",
        "koi baat ny maa chudwa apni tu mafi de dunga",
        "Ache se maa chudwa apni tu mafi mil jayegi tujhe",
        "apni ma mat chuda muje swipe crke",
        "Ache se apni ma cudwa tu swipe crke",
        "Fr bolna na ki cudwa le apni ma swipe crke",
        "Cya hua ma cud gyi tery",
        "pr kese cud gyi tery ma",
        "mujhe pta tha ma cud gai tery",
        "mey ny manta ma cud gyi tery",
        "teri ma rndy",
        "lode se utr mc",
        "lun mt chus mera",
        "nikal madarchd",
        "chup oye gashti k bache",
        "makichut teri",
        "chup rndyke",
        "ma rndy teri",
        "teri ma k hath todh k tere baap k muh me fasadunga randyke",
        "leave le tu rndyke pasand nai aya meko",
        "leave le tu randyke ider se",
        "Leave le jldi se wrna ma chud gai tery",
        "Leave ny lega maa randy tery",
        "Smjh bat maa randy ey tery leave le",
        "fast leave le kamjor randyke",
        "tuto chup rndyk",
        "oy hijde khana kha ke aa kamzor",
        "teri mako ily rey🌚😂",
        "chup chap chud tmkc",
        "chupchap maa chudwa apni tu",
        "shi se maa chudwa apni tu chupchap",
        "fr se maa chudwa tu apni chupchap",
        "shi se likh wrna ma chud gai tery",
        "ma cyu chud gai tery chupchap",
        "proof cr maa chud gyi tery",
        "proof ey tery maa randy ey",
        "proof ho chuka maa randy tery",
        "Chup chillar",
        "chup chup maa k bosda tery",
        "oy hijde khana kha ke aa kamzor",
        "chup madarchod ?",
        "Ab tk cud gyi hogi tery maa ?",
        "ny ny me kuch ny janta bs teri ma rndy ey",
        "Sbse phele apni maa ko bol chudna kaam kre",
        "Yaha bhi chuda tu rndyce pille",
        "terimakabosda",
        "teri to bhen cudegi",
        "chup rndyke tommy",
        "nikal madarchd cudke yha se",
        "coz teri ma andhi randi he",
        "nyto baap bol mujhe",
        "nyny teri maa hogi rndii jo chudwati jogi",
        "try ammi ce bhosde me emoji dal mc",
        "cya ? chmr chud gya cya ?",
        "tm chudri hogi frrto",
        "cya ? kb ? pgl ey cya rndkek",
        "cya sch mey pgl ey cya tu randyke cudwa li tune apni ma",
        "itna sch ny bol ma chud gai tery",
        "sch mey pgl ey tu apni ma cudwa lia mere sth",
        "mtlb tmr",
        "nyto",
        "pura likh mc",
        "tmr frrto",
        "oh ok cudle fir",
        "teri maa ka damad",
        "cya ? ache se likhe pehle rndikebache",
        "nyto teri maa chodne me vyast hu",
        "nyto pgl ey cya kuch bi",
        "oyee cya ? chud gya ?",
        "chud mt hss",
        "yur rndii mom",
        "are sbki maa rndii or teri bi",
        "are idar cudle ek baar",
        "tri maa ci trh",
        "ek line me tmr",
        "Q",
        "ocy ab chudle",
        "pehele teri maa chodu",
        "nyto",
        "q ?",
        "hyyy chud ke dika ek baar",
        "oyee sun dost tmr",
        "bhag ja raand maaf crr dunga",
        "oyee pgl rndii idar aa",
        "cya tmr frrto",
        "oyee idar aake chud le chmr",
        "nyto aese hi cud",
        "oyee hyy aise hi cud lena",
        "or chud le",
        "chud ke dika or",
        "hyy chudo na",
        "chudo mt bhag jao",
        "byyee hyy cya ?",
        "Qchud q rhe ho ?",
        "pgl ey cya mc",
        "chud mt",
        "cya pgl rndii idar aa",
        "teri ammi ce bhosde me chappal",
        "oyee idar aa mc",
        "kmzror ey cya rndiek",
        "cya likh rha ?",
        "chud tha cya ?",
        "oyee slide leke baat crmc",
        "idar a teri maa chodu",
        "oyee cp mt crr chudle",
        "oyee hyy chud ke dika",
        "idar aa try ma schofu khachar khachar",
        "idar aa ja mc",
        "hyy idar aake chudle",
        "oyee kmzor mc idar aa",
        "ye cya tmr",
        "oyee ny cp ny crr",
        "oyee pgl mt crr",
        "cudle aram se mc",
        "pgl ey cya rndiek",
        "cp crce chudega !",
        "baap ? mc mera coi ma baap ny ey mai upar se rocket pe beth ce bss teri ma chodne aya hu",
        "Chota likh rndi k bache",
        "Chota likha wrna try ma rndy",
        "Try ma baka codega",
        "Tmkc main burf",
        "Bhikari ki jhat ma cuda le",
        "Chodke tery ma marjayegi",
        "Tmkc main Mount Everest",
        "Muh mey lega lund mera",
        "Hijde ki jhat chup wrna try ma rndi",
        "Menu ny pta tery ma randy",
        "Menu ki pta ma randy tery",
        "Menu pta maa cud gai tery",
        "Menu sb pta ma randy ey tery",
        "Menu pr tery ma randy",
        "Randy maa tery menu pta",
        "Tenu or menu pta ey maa randy tery",
        "Bs bs maa cudwa apni",
        "Bs bs ma randy tery thnkss",
        "Bs bs chudwa lia tu apni maa",
        "Bs bs kamjor maa randy tery",
        "Smjh gya apni ma cudwa le ab",
        "smjh gya tery maa randy ey",
        "smjh gya tu sabit kr maa randy tery",
        "Cya hua ma cudwa tu apni",
        "Easy maa cudwa le apni tu",
        "Easy w8 ma chudwa le apni ab",
        "Sans ari ha ky teri maa chudgi ajj",
        "Teri maa ko bina sanss lete hue chodunga",
        "chup randike kamjor",
        "apni ma normie cudwa le tu",
        "fr cya normie ma cud gai tery",
        "bas thek tery ma randy",
        "bas thek tery maa cud gyi",
        "kamjor thi tery ma esliye cud gai",
        "Mai sb janta ma cud gai tery",
        "chl chl ht tery maa cud gyi",
        "fr kaise cud gyi maa tery",
        "maa tery randy ey",
        "bas tery maa randy ey",
        "fr randy ma tery ey",
        "Kamjor ma ka bcha tu randyke",
        "bhot gndi cud gai maa tery",
        "pr kaise maa cud gai tery itna gnda",
        "mujhe cya bta rha maa randy tery",
        "mujhe cya pta ma cud gyi tery",
        "fir mujhe ny pta maa cud gai tery",
        "pta ny kon cod dia tery maa ko",
        "ruk aaya tery ma codke",
        "wait cr tery maa cod rha hu",
        "wait cr rabdyke maa cud rhi ey tery",
        "wait kr smjh rha tery ma codke",
        "wait le thoda chodne de tery mako",
        "ruk ja aand rkh dunga tery make liye",
        "tery maa famous randy ey",
        "maan lia mene maa randy sali tery",
        "maan lia maa cud gai tery",
        "shant beth randyke maa chudwa tu apni",
        "shant bethke chudwa le apni mako tu",
        "fr se shant Beth tu cud ab randyke yha",
        "mere smjh ny aya maa randy tery",
        "Le केला Kha tu madarchod",
        "Hye tery ma cud gyi cya",
        "hye tery maa mar gai cya",
        "Hye sch bta com cod dia tery mako",
        "Chl chod dia teri maa ko smjhle",
        "Baki koi dikkat ny tery maa randy ey",
        "baki sb jante ey ki maa chuddkad ey tery",
        "mujhe cya pta tha tery maa cudne wli ey",
        "pr mei kaise jnta tery ma ko koi chod dia",
        "pr mera vi manna shi tha maa chud gai tery",
        "pr wo glt ny tery maa randy ey",
        "pr wo shi ey tery maa chuddkad ey",
        "pr kaise kia maa chud gai tery omfoo",
        "bur cheer dunga tri ma ka",
        "teri ma ke dil me loda marke uski dhadkan rok dunga",
        "lulle kha tri makabhosda",
        "tri bhn ki bhosdi beta",
        "tri ma rndi baat khtm",
        "Sun ek maze ki baat batao kya teri maa randy ey"
        "codu codu mako tery",
        "aj cud gai tery maa oye",
        "sun sun randy make bache tu",
        "kilas ny randyke",
        "mujhe cya pta tery bhen cud gai",
        "pr pr cya hote ey tmkc",
        "tmcl sunle",
        "moot du tery maki chut mey",
        "bhgny cudke dikha fr",
        "fr se cudle tu",
        "ye vi shi ey tery mkc bs",
        "aj kuch ny ma cudwa tu apni",
        "try kr mera lund chuske",
        "tormakibur sun",
        "tor maki fuddi oye",
        "Haye Haye tery ma cud gai",
        "oye lundke pasine..",
        "kutte ke tatte sun",
        "kutta jaisa cud rha tu",
        "Muh mei le mera..",
        "jhaat ke pissu sun tmkc",
        "Hahahha ma cud gai tery",
        "weak tatte uth",
        "weak ey tu cud rha",
        "weak ache se cud tu",
        "weak tery ma cud rhi dekh",
        "week tery ma cud gai ab",
        "mujhe ny rok tu weak ey",
        "chup hizde",
        "okat ny meri ma cudwa tu apni",
        "lun lega tery maki gand mei ?",
        "tery maki bachi codu..",
        "tery bhen ki chut aj fad du",
        "speed lekr aa cudke dikha",
        "speed ny tere andr weak prosn",
        "ugly randyke chup",
        "makafuddatery",
        "tera baap ko tag kr..?",
        "ache se tag kr randibaaz bhagwn ko..",
        "cudke pgl ny ho tu",
        "cudke pgl ho rha tu kid",
        "ma to cud gai tery hawabzi cr..",
        "bs ma codni ey tery",
        "town mei cud tery mako lekr",
        "tery ma sexy ko bej - randibaaz bhgwn pe",
        "speed pkd cp ny kr",
        "Try ma rendy",
        "Bhkk cud",
        "tey maa rndi",
        "tery behen randi",
        "Cud ja",
        "tery didi rndi",
        "Slow",
        "teri Maiya ciodu",
        "Bhag?",
        "Bhak cud",
        "Tma codu",
        "Slow",
        "Slow firse",
        "Cudgrib",
        "Try ma dou",
        "tbkc codu",
        "Net on off wali rndy",
        "Oye try ma codu",
        "Idhar aake cud chup chaap",
        "tbkc mrdu",
        "oi maake lodee",
        "randyke beej",
        "tmkc chodu",
        "suar ke beej",
        "net off on kr randyke ladke",
        "Try ma cudi kese",
        "Chup slow madharcod",
        "tbkc codu kr msg delete",
        "oi suar ke ladke",
        "tmkc fufi",
        "tery didi chudi",
        "tmkc dikha",
        "Cud ab",
        "randyke cud",
        "Bhak cud",
        "cudle tbkc mru",
        "tmkl cudle grib",
        "tery behen vesiyaa rndi",
        "Itna gnda chuda tu firse net on off",
        "grib ke bete",
        "Bhag ja lode tmkc maru dunga",
        "tbkc mrdungaa",
        "bhag tmkc",
        "bhag tbkc",
        "tbkc mey cp",
        "cp tbkc mehh",
        "cp tmkl meh",
        "cp bol randyke",
        "Abe cp bol randyke",
        "double send ko cp tmkc codu",
        "tbkc me cp cod dunga Aaj mehh",
        "ht tbkc dalal ke bete.",
        "Rndy jldi jldi cudq tryma",
        "Para likhega..",
        "Tra rndhbhak",
        "Lagdi ke ladce cp bol",
        "cp bol lagdi ke bete..",
        "cudke cp bol",
        "bhikari lund chus mera.",
        "Low level cp cr",
        "cp bol low level weak",
        "mere lund pe ey tu hijde",
        "free cudwa tery mako",
        "Free mey cud tu randyke"
        "speed ny weak tatte terme",
        "kitni br cudwayega terymako",
        "lund le randibaaz bapka",
        "lun cus jaldi se randibaaz bapka",
        "koi ny dekh rha cudle tu",
        "cudle betichod ache se",
        "maki chut tery bs yehi janta mey",
        "cp bolega to tmkc",
        "wrna tery ma cud jayegi",
        "slow ey tu kid",
        "jldi likh..tmkc",
        "jldi likh..randce tu",
        "tym se phle cudke dikha",
        "tym hoga tery maa cudwa",
        "ma cud gai tery tym se phle",
        "uth randce ke ldke",
        "macabosdatery",
        "con kb cod dia mako tery",
        "koi hoga tml",
        "machar cudle tu",
        "menu tery mako codna se",
        "tery mako bol mujhe cod de",
        "bs mey tery ma se cudna chta hu",
        "Eww maka lode uth",
        "Meow cr tery mako codu",
        "lund rkh dia tery make fude pe",
        "mera lund ke bal uth",
        "kidee Zinda ho",
        "mar ny kidde type kr",
        "chup bkl",
        "bc tery maki chut",
        "mc randyke likh fast",
        "fast likh randyke",
        "fast likh kamzor"
        "tery maki chut claim crwa",
        "awz niche randce ke bche",
        "sawal ny puch tery makabosda",
        "fyter bnega lagde madrchod",
        "oye kaale ro ke dikha",
        "oye kaale roo ny",
        "short ny cud tu bina ruke",
        "short ny cud tu apni mako lekr",
        "tery make sth tery bhen vi cudwa le",
        "tery make sth tery didi vi cud gai",
        "Chat fyter bnega randce codu tery mako",
        "bol randibaaz daddy ey",
        "bullyx randyke uth",
        "mar marke cud rha tu",
        "or tery ma marke cud gai"
        "Jaldi likh rndyke bej",
        "Or bda likh tmc",
        "Or bda 2 line wla likh tmkc",
        "Or bda oye likh tml",
        "Teri maa ka bur",
        "Oye keede",
        "Randi ke ladke",
        "Jaldi likh teri behen chodu",
        "Mkl uth randi ke bacche",
        "Teri nani meri maal",
        "Tej likh randce",
        "Oye maake lode mrenga",
        "Teri maa chody",
        "Teri Maiya ki gand",
        "Tery dadi ka fudda",
        "Mkl uth behencod",
        "Teri maa ki bur de",
        "Tery maa ka fudda me lauda",
        "Teri maa chudva",
        "Randi ke bete mar gaya",
        "Teri maa ki chut mru",
        "Jalid kr spam",
        "Mc spam rokenga",
        "Teri maaki chut spam kr",
        "spam kr.maake lode",
        "Randyke chode spam kr wrna cud tu",
        "Spam kr kid",
        "Noob teri maa chodu",
        "Rndyke bete mar mat tu",
        "Noob jaldi likh wrna tery maa rand",
        "cud gai maa tery noob",
        "uth randyke noob",
        "chl cudke dikha noob",
        "jldi typ cr noob halke",
        "cud ke pgl ny ho noob",
        "cud cud ke rand bnja tu noob",
        "makichut tery noob",
        "ganda cyu cud rha tu ?",
        "itna gnda ny cud ache se cud",
        "Maan le cud gya tu sun bat ab",
        "makafudda fat gya tery ruk"
        "BAAP BHI BNALE MUJE RNDIKE",
        "TERA BAAP RANDIBAAZ EY YAAD EY TUJHE",
        "TU APNI MAA CUDA NA TYMPASS",
        "OYE UNFUNNY SWIPE MTT KR",
        "OH HELLO BIHARI TERA BAAP BIHARI OR TU V BIHARI AAUKAT ME RHA KR.",
        "OYY KINNER TUJHE GC ME AANE KI PERMISSION KISNE DI.",
        "CUDKE DIKHA",
        "CUDKE DIKHA EK BAAR.",
        "SUN SUN MA CUDA.",
        "TERI MACA BHOSDA.",
        "OYE CHOTI JATI KE TMR.",
        "KY? JLDI LIKH KIDDE.",
        "BIHARI COM GANG KE BAAP KO TAG CREGA TU",
        "MUJHE CYA TU BIHARI EY TMKC BS",
        "JALDI SE RANDIBAAZ PAPA BOL",
        "SIDE HOJA BIHARI TERY MAA CUD GAI AB",
        "HYE PGL BHG MAT ACHE SE CUD",
        "BHG NY RANDYKE TU AJJ",
        "HYE PGL KE BCHE BHAG MAT",
        "HYE DUR HATT MADCHOD KE BACHE",
        "KOI BAT NY TERY MAA RANDY EY ESLIYE MAF CR RHA HU TUJHE",
        "KOI BAAT NY MAA CHUDWA APNI TU MAFI DE DUNGA",
        "ACHE SE MAA CHUDWA APNI TU MAFI MIL JAYEGI TUJHE",
        "APNI MA MAT CHUDA MUJE SWIPE CRKE",
        "ACHE SE APNI MA CUDWA TU SWIPE CRKE",
        "FR BOLNA NA KI CUDWA LE APNI MA SWIPE CRKE",
        "CYA HUA MA CUD GYI TERY",
        "PR KESE CUD GYI TERY MA",
        "MUJHE PTA THA MA CUD GAI TERY",
        "MEY NY MANTA MA CUD GYI TERY",
        "TERI MA RNDY",
        "LODE SE UTR MC",
        "LUN MT CHUS MERA",
        "NIKAL MADARCHD",
        "CHUP OYE GASHTI K BACHE",
        "MAKICHUT TERI",
        "CHUP RNDYKE",
        "MA RNDY TERI",
        "TERI MA K HATH TODH K TERE BAAP K MUH ME FASADUNGA RANDYKE",
        "LEAVE LE TU RNDYKE PASAND NAI AYA MEKO",
        "LEAVE LE TU RANDYKE IDER SE",
        "LEAVE LE JLDI SE WRNA MA CHUD GAI TERY",
        "LEAVE NY LEGA MAA RANDY TERY",
        "SMJH BAT MAA RANDY EY TERY LEAVE LE",
        "FAST LEAVE LE KAMJOR RANDYKE",
        "TUTO CHUP RNDYK",
        "OY HIJDE KHANA KHA KE AA KAMZOR",
        "TERI MAKO ILY REY",
        "CHUP CHAP CHUD TMKC",
        "CHUPCHAP MAA CHUDWA APNI TU",
        "SHI SE MAA CHUDWA APNI TU CHUPCHAP",
        "FR SE MAA CHUDWA TU APNI CHUPCHAP",
        "SHI SE LIKH WRNA MA CHUD GAI TERY",
        "MA CYU CHUD GAI TERY CHUPCHAP",
        "PROOF CR MAA CHUD GYI TERY",
        "PROOF EY TERY MAA RANDY EY",
        "PROOF HO CHUKA MAA RANDY TERY",
        "CHUP CHILLAR",
        "CHUP CHUP MA K BOSDA TERY",
        "OY HIJDE KHANA KHA KE AA KAMZOR",
        "CHUP MADARCHOD ?",
        "AB TK CUD GYI HOGI TERY MAA ?",
        "NY NY ME KUCH NY JANTA BS TERI MA RNDY EY",
        "SBSE PHELE APNI MAA KO BOL CHUDNA KAAM KRE",
        "YAHA BHI CHUDA TU RNDYCE PILLE",
        "TERIMAKABOSDA",
        "TERI TO BHEN CUDEGI",
        "CHUP RNDYKE TOMMY",
        "NIKAL MADARCHD CUDKE YHA SE",
        "COZ TERI MA ANDHI RANDI HE",
        "NYTO BAAP BOL MUJHE",
        "NYNY TERI MAA HOGI RNDII JO CHUDWATI JOGI",
        "TRY AMMI CE BHOSDE ME EMOJI DAL MC",
        "CYA ? CHMR CHUD GYA CYA ?",
        "TM CHUDRI HOGI FRRTO",
        "CYA ? KB ? PGL EY CYA RNDKEK",
        "CYA SCH MEY PGL EY CYA TU RANDYKE CUDWA LI TUNE APNI MA",
        "ITNA SCH NY BOL MA CHUD GAI TERY",
        "SCH MEY PGL EY TU APNI MA CUDWA LIA MERE STH",
        "MTLB TMR",
        "NYTO",
        "PURA LIKH MC",
        "TMR FRRTO",
        "OH OK CUDLE FIR",
        "TERI MAA KA DAMAD",
        "CYA ? ACHE SE LIKHE PEHLE RNDIKEBACHE",
        "NYTO TERI MAA CHODNE ME VYAST HU",
        "NYTO PGL EY CYA KUCH BI",
        "OYEE CYA ? CHUD GYA ?",
        "CHUD MT HSS",
        "YUR RNDII MOM",
        "ARE SBKI MAA RNDII OR TERI BI",
        "ARE IDAR CUDLE EK BAAR",
        "TRI MAA CI TRH",
        "EK LINE ME TMR",
        "Q",
        "OCY AB CHUDLE",
        "PEHELE TERI MAA CHODU",
        "NYTO",
        "Q ?",
        "HYYY CHUD KE DIKA EK BAAR",
        "OYEE SUN DOST TMR",
        "BHAG JA RAAND MAAF CRR DUNGA",
        "OYEE PGL RNDII IDAR AA",
        "CYA TMR FRRTO",
        "OYEE IDAR Aake CHUD LE CHMR",
        "NYTO AESE HI CUD",
        "OYEE HYY AISE HI CUD LENA",
        "OR CHUD LE",
        "CHUD KE DIKA OR",
        "HYY CHUDO NA",
        "CHUDO MT BHAG JAO",
        "BYYEE HYY CYA ?",
        "QCHUD Q RHE HO ?",
        "PGL EY CYA MC",
        "CHUD MT",
        "CYA PGL RNDII IDAR AA",
        "TERI AMMI CE BHOSDE ME CHAPPAL",
        "OYEE IDAR AA MC",
        "KMZROR EY CYA RNDIEK",
        "CYA LIKH RHA ?",
        "CHUD THA CYA ?",
        "OYEE SLIDE LEKE BAAT CRMC",
        "IDAR A TERI MAA CHODU",
        "OYEE CP MT CRR CHUDLE",
        "OYEE HYY CHUD KE DIKA",
        "IDAR AA TRY MA SCHOFU KHACHAR KHACHAR",
        "IDAR AA JA MC",
        "HYY IDAR Aake CHUDLE",
        "OYEE KMZOR MC IDAR AA",
        "YE CYA TMR",
        "OYEE NY CP NY CRR",
        "OYEE PGL MT CRR",
        "CUDLE ARAM SE MC",
        "PGL EY CYA RNDIEK",
        "CP CRCE CHUDEGA !",
        "BAAP ? MC MERA COI MA BAAP NY EY MAI UPAR SE ROCKET PE BETH CE BSS TERI MA CHODNE AYA HU",
        "CHOTA LIKH RNDI K BACHE",
        "CHOTA LIKHA WRNA TRY MA RNDY",
        "TRY MA BAKA CODEGA",
        "TMKC MAIN BURF",
        "BHIKARI KI JHAT MA CUDA LE",
        "CHODKE TERY MA MARJAYEGI",
        "TMKC MAIN MOUNT EVEREST",
        "MUH MEY LEGA LUND MERA",
        "HIJDE KI JHAT CHUP WRNA TRY MA RNDI",
        "MENU NY PTA TERY MA RANDY",
        "MENU KI PTA MA RANDY TERY",
        "MENU PTA MAA CUD GAI TERY",
        "MENU SB PTA MA RANDY EY TERY",
        "MENU PR TERY MA RANDY",
        "RANDY MAA TERY MENU PTA",
        "TENU OR MENU PTA EY MAA RANDY TERY",
        "BS BS MAA CUDWA APNI",
        "BS BS MA RANDY TERY THNKSS",
        "BS BS CHUDWA LIA TU APNI MAA",
        "BS BS KAMJOR MAA RANDY TERY",
        "SMJH GYA APNI MA CUDWA LE AB",
        "SMJH GYA TERY MAA RANDY EY",
        "SMJH GYA TU SABIT KR MAA RANDY TERY",
        "CYA HUA MA CUDWA TU APNI",
        "EASY MAA CUDWA LE APNI TU",
        "EASY W8 MA CHUDWA LE APNI AB",
        "SANS ARI HA KY TERI MAA CHUDGI AJJ",
        "TERI MAA KO BINA SANSS LETE HUE CHODUNGA",
        "CHUP RANDIKE KAMJOR",
        "APNI MA NORMIE CUDWA LE TU",
        "FR CYA NORMIE MA CUD GAI TERY",
        "BAS THEK TERY MA RANDY",
        "BAS THEK TERY MAA CUD GYI",
        "KAMJOR THI TERY MA ESLIYE CUD GAI",
        "MAI SB JANTA MA CUD GAI TERY",
        "CHL CHL HT TERY MAA CUD GYI",
        "FR KAISE CUD GYI MAA TERY",
        "MAA TERY RANDY EY",
        "BAS TERY MAA RANDY EY",
        "FR RANDY MA TERY EY",
        "KAMJOR MA KA BCHA TU RANDYKE",
        "BHOT GNDI CUD GAI MAA TERY",
        "PR KAISE MAA CUD GAI TERY ITNA GNDA",
        "MUJHE CYA BTA RHA MAA RANDY TERY",
        "MUJHE CYA PTA MA CUD GYI TERY",
        "FIR MUJHE NY PTA MAA CUD GAI TERY",
        "PTA NY KON COD DIA TERY MAA KO",
        "RUK AAYA TERY MA CODKE",
        "WAIT CR TERY MAA COD RHA HU",
        "WAIT CR RABDYKE MAA CUD RHI EY TERY",
        "WAIT KR SMJH RHA TERY MA CODKE",
        "WAIT LE THODA CHODNE DE TERY MAKO",
        "RUK JA AAND RKH DUNGA TERY MAKE LIYE",
        "TERY MAA FAMOUS RANDY EY",
        "MAAN LIA MENE MAA RANDY SALI TERY",
        "MAAN LIA MAA CUD GAI TERY",
        "SHANT BETH RANDYKE MAA CHUDWA TU APNI",
        "SHANT BETHKE CHUDWA LE APNI MAKO TU",
        "FR SE SHANT BETH TU CUD AB RANDYKE YHA",
        "MERE SMJH NY AYA MAA RANDY TERY",
        "LE KELA KHA TU MADARCHOD",
        "HYE TERY MA CUD GYI CYA",
        "HYE TERY MAA MAR GAI CYA",
        "HYE SCH BTA COM COD DIA TERY MAKO",
        "CHL CHOD DIA TERI MAA KO SMJHLE",
        "BAKI KOI DIKKAT NY TERY MAA RANDY EY",
        "BAKI SB JANTE EY KI MAA CHUDDKAD EY TERY",
        "MUJHE CYA PTA THA TERY MAA CUDNE WLI EY",
        "PR MEI KAISE JNTA TERY MA KO KOI CHOD DIA",
        "PR MERA VI MANNA SHI THA MAA CHUD GAI TERY",
        "PR WO GLT NY TERY MAA RANDY EY",
        "PR WO SHI EY TERY MAA CHUDDKAD EY",
        "PR KAISE KIA MAA CHUD GAI TERY OMFOO",
        "BUR CHEER DUNGA TRI MA KA",
        "TERI MA KE DIL ME LODA MARKE USKI DHADKAN ROK DUNGA",
        "LULLE KHA TRI MAKABHOSDA",
        "TRI BHN KI BHOSDI BETA",
        "TRI MA RNDI BAAT KHTM",
        "SUN EK MAZE KI BAAT BATAO KYA TERI MAA RANDY EY",
        "CODU CODU MAKO TERY",
        "AJ CUD GAI TERY MAA OYE",
        "SUN SUN RANDY MAKE BACHE TU",
        "KILAS NY RANDYKE",
        "MUJHE CYA PTA TERY BHEN CUD GAI",
        "PR PR CYA HOTE EY TMKC",
        "TMCL SUNLE",
        "MOOT DU TERY MAKI CHUT MEY",
        "BHGNY CUDKE DIKHA FR",
        "FR SE CUDLE TU",
        "YE VI SHI EY TERY MKC BS",
        "AJ KUCH NY MA CUDWA TU APNI",
        "TRY KR MERA LUND CHUSKE",
        "TORMAKIBUR SUN",
        "TOR MAKI FUDDI OYE",
        "HAYE HAYE TERY MA CUD GAI",
        "OYE LUNDKE PASINE..",
        "KUTTE KE TATTE SUN",
        "KUTTA JAISA CUD RHA TU",
        "MUH MEI LE MERA..",
        "JHAAT KE PISSU SUN TMKC",
        "HAHAHHA MA CUD GAI TERY",
        "WEAK TATTE UTH",
        "WEAK EY TU CUD RHA",
        "WEAK ACHE SE CUD TU",
        "WEAK TERY MA CUD RHI DEKH",
        "WEEK TERY MA CUD GAI AB",
        "MUJHE NY ROK TU WEAK EY",
        "CHUP HIZDE",
        "OKAT NY MERI MA CUDWA TU APNI",
        "LUN LEGA TERY MAKI GAND MEI ?",
        "TERY MAKI BACHI CODU..",
        "TERY BHEN KI CHUT AJ FAD DU",
        "SPEED LEKR AA CUDKE DIKHA",
        "SPEED NY TERE ANDR WEAK PROSN",
        "UGLY RANDYKE CHUP",
        "MAKAFUDDATERY",
        "TERA BAAP KO TAG KR..?",
        "ACHE SE TAG KR RANDIBAAZ BHAGWN KO..",
        "CUDKE PGL NY HO TU",
        "CUDKE PGL HO RHA TU KID",
        "MA TO CUD GAI TERY HAWABZI CR..",
        "BS MA CODNI EY TERY",
        "TOWN MEI CUD TERY MAKO LEKR",
        "TERY MA SEXY KO BEJ - RANDIBAAZ BHGWN PE",
        "SPEED PKD CP NY KR",
        "TRY MA RENDY",
        "BHKK CUD",
        "TEY MAA RNDI",
        "TERY BEHEN RANDI",
        "CUD JA TMC",
        "TERY DIDI RNDI",
        "SLOW",
        "TERI MAIYA CIODU",
        "BHAG?TMC ",
        "BHAK CUD TML",
        "TMA CODU",
        "SLOW TMKC ",
        "SLOW FIRSE TMKC ",
        "CUDGRIB TML",
        "TRY MA DOU",
        "TBKC CODU",
        "NET ON OFF WALI RNDY",
        "OYE TRY MA CODU",
        "IDHAR AAKE CUD CHUP CHAAP",
        "TBKC MRDU",
        "OI MAAKE LODEE",
        "RANDYKE BEEJ",
        "TMKC CHODU",
        "SUAR KE BEEJ",
        "NET OFF ON KR RANDYKE LADKE",
        "TRY MA CUDI KESE",
        "CHUP SLOW MADHARCOD",
        "TBKC CODU KR MSG DELETE",
        "OI SUAR KE LADKE",
        "TMKC FUFI",
        "TERY DIDI CHUDI",
        "TMKC DIKHA",
        "CUD AB",
        "RANDYKE CUD",
        "BHAK CUD",
        "CUDLE TBKC MRU",
        "TMKL CUDLE GRIB",
        "TERY BEHEN VESITYA RNDI",
        "ITNA GNDA CHUDA TU FIRSE NET ON OFF",
        "GRIB KE BETE",
        "BHAG JA LODE TMKC MARU DUNGA",
        "TBKC MRDUNGAA",
        "BHAG TMKC",
        "BHAG TBKC",
        "TBKC MEY CP",
        "CP TBKC MEHH",
        "CP TMKL MEH",
        "CP BOL RANDYKE",
        "ABE CP BOL RANDYKE",
        "DOUBLE SEND KO CP TMKC CODU",
        "TBKC ME CP COD DUNGA AAJ MEHH",
        "HT TBKC DALAL KE BETE.",
        "RNDY JLDI JLDI CUDQ TRYMA",
        "PARA LIKHEGA..",
        "TRA RNDHBHAK",
        "LAGDI KE LADCE CP BOL",
        "CP BOL LAGDI KE BETE..",
        "CUDKE CP BOL",
        "BHIKARI LUND CHUS MERA.",
        "LOW LEVEL CP CR",
        "CP BOL LOW LEVEL WEAK",
        "MERE LUND PE EY TU HIJDE",
        "FREE CUDWA TERY MAKO",
        "FREE MEY CUD TU RANDYKE",
        "SPEED NY WEAK TATTE TERME",
        "KITNI BR CUDWAYEGA TERYMAKO",
        "LUND LE RANDIBAAZ BAPKA",
        "LUN CUS JALDI SE RANDIBAAZ BAPKA",
        "KOI NY DEKH RHA CUDLE TU",
        "CUDLE BETICHOD ACHE SE",
        "MAKI CHUT TERY BS YEHI JANTA MEY",
        "CP BOLEGA TO TMKC",
        "WRNA TERY MA CUD JAYEGI",
        "SLOW EY TU KID",
        "JLDI LIKH..TMKC",
        "JLDI LIKH..RANDCE TU",
        "TYM SE PHLE CUDKE DIKHA",
        "TYM HOGA TERY MAA CUDWA",
        "MA CUD GAI TERY TYM SE PHLE",
        "UTH RANDCE KE LDKE",
        "MACABOSDATERY",
        "CON KB COD DIA MAKO TERY",
        "KOI HOGA TML",
        "MACHAR CUDLE TU",
        "MENU TERY MAKO CODNA SE",
        "TERY MAKO BOL MUJHE COD DE",
        "BS MEY TERY MA SE CUDNA CHTA HU",
        "EWW MAKA LODE UTH",
        "MEOW CR TERY MAKO CODU",
        "LUND RKH DIA TERY MAKE FUDE PE",
        "MERA LUND KE BAL UTH",
        "KIDEE ZINDA HO",
        "MAR NY KIDDE TYPE KR",
        "CHUP BKL",
        "BC TERY MAKI CHUT",
        "MC RANDYKE LIKH FAST",
        "FAST LIKH RANDYKE",
        "FAST LIKH KAMZOR",
        "TERY MAKI CHUT CLAIM CRWA",
        "AWZ NICHE RANDCE KE BCHE",
        "SAWAL NY PUCH TERY MAKABOSDA",
        "FYTER BNEGA LAGDE MADRCHOD",
        "OYE KAALE RO KE DIKHA",
        "OYE KAALE ROO NY",
        "SHORT NY CUD TU BINA RUKE",
        "SHORT NY CUD TU APNI MAKO LEKR",
        "TERY MAKE STH TERY BHEN VI CUDWA LE",
        "TERY MAKE STH TERY DIDI VI CUD GAI",
        "CHAT FYTER BNEGA RANDCE CODU TERY MAKO",
        "BOL RANDIBAAZ DADDY EY",
        "BULLYX RANDYKE UTH",
        "MAR MARKE CUD RHA TU",
        "OR TERY MA MARKE CUD GAI",
        "JALDI LIKH RNDYKE BEJ",
        "OR BDA LIKH TMC",
        "OR BDA 2 LINE WLA LIKH TMKC",
        "OR BDA OYE LIKH TML",
        "TERI MAA KA BUR",
        "OYE KEEDE",
        "RANDI KE LADKE",
        "JALDI LIKH TERI BEHEN CHODU",
        "MKL UTH RANDI KE BACCHE",
        "TERI NANI MERI MAAL",
        "TEJ LIKH RANDCE",
        "OYE MAAKE LODE MRENGA",
        "TERI MAA CHODY",
        "TERI MAIYA KI GAND",
        "TERY DADI KA FUDDA",
        "MKL UTH BEHENCOD",
        "TERI MAA KI BUR DE",
        "TERY MAA KA FUDDA ME LAUDA",
        "TERI MAA CHUDVA",
        "RANDI KE BETE MAR GAYA",
        "TERI MAA KI CHUT MRU",
        "JALID KR SPAM",
        "MC SPAM ROKENGA",
        "TERI MAAKI CHUT SPAM KR",
        "SPAM KR.MAAKE LODE",
        "RANDYKE CHODE SPAM KR WRNA CUD TU",
        "SPAM KR KID",
        "NOOB TERI MAA CHODU",
        "RNDYKE BETE MAR MAT TU",
        "NOOB JALDI LIKH WRNA TERY MAA RAND",
        "CUD GAI MAA TERY NOOB",
        "UTH RANDYKE NOOB",
        "CHL CUDKE DIKHA NOOB",
        "JLDI TYP CR NOOB HALKE",
        "CUD KE PGL NY HO NOOB",
        "CUD CUD KE RAND BNJA TU NOOB",
        "MAKICHUT TERY NOOB",
        "GANDA CYU CUD RHA TU ?",
        "ITNA GNDA NY CUD ACHE SE CUD",
        "MAAN LE CUD GYA TU SUN BAT AB",
        "MAKAFUDDA FAT GYA TERY RUK",
        "sʜᴀɴᴛ ʙᴇᴛʜ ᴍᴀᴅʀᴄʜᴏᴅ ᴡʀɴᴀ ᴍᴀᴋᴀʙᴏsᴅᴀ ᴛᴇᴇʏ.",
        "ᴛᴇʀɪ ᴍᴀ ᴋɪ ᴄʜᴜᴛ..",
        "ʟᴡᴅᴇ ᴋᴇ ʙᴀᴀᴀʟʟʟ ᴛᴇʀʏ ᴍᴀᴀ ᴄᴜᴅᴋᴇ ᴘɢʟ ᴅᴇᴋʜ.",
        "ᴍᴀᴄʜᴀʀ ᴋɪ ᴊʜᴀᴀᴛ ᴋᴇ ʙᴀᴀᴀʟʟʟʟ ᴄᴜᴅ ᴀᴄʜᴇ sᴇ ʏʜᴀᴘᴇ ᴛᴜ",
        "ᴛᴇʀɪ ᴍᴀ ᴋɪ ᴄʜᴜᴛ ᴍ ᴅᴜ ᴛᴀᴘᴀ ᴛᴀᴘ?",
        "ᴛᴇʀɪ ᴍᴀ ᴋᴀ ʙʜᴏꜱᴅᴀᴀ",
        "ᴛᴇʀɪ ʙʜɴ ꜱʙꜱʙᴇ ʙᴅɪ ʀᴀɴᴅɪ.",
        "ᴛᴇʀɪ ᴍᴀ ᴏꜱꜱᴇ ʙᴀᴅɪ ʀᴀɴᴅᴅᴅᴅᴅ",
        "ᴛᴇʀᴀ ʙᴀᴀᴘ ʀᴀɴᴅɪʙᴀᴀᴢ ᴇʏ ᴅᴇᴋʜ",
        "ᴋɪᴛɴɪ ᴄʜᴏᴅᴜ ᴛᴇʀɪ ᴍᴀ ᴀʙ ᴏʀ..",
        "ᴛᴇʀɪ ᴍᴀ ᴄʜᴏᴅ ᴅɪ ʜᴍ ɴᴇ",
        "ᴛᴇʀɪ ᴍᴀ ᴋᴇ ꜱᴛʜ ʀᴇᴇʟꜱ ʙɴᴇɢᴀ ʀᴏᴀᴅ ᴘᴇᴇ",
        "ᴛᴇʀɪ ᴍᴀ ᴋɪ ᴄʜᴜᴛ ᴇᴋ ᴅᴀᴍ ᴛᴏᴘ ꜱᴇxʏ",
        "ᴍᴀʟᴜᴍ ɴᴀ ᴘʜʀ ᴋᴇꜱᴇ ʟᴇᴛᴀ ʜᴜ ᴍ ᴛᴇʀɪ ᴍᴀ ᴋɪ ᴄʜᴜᴛ ᴛᴀᴘᴀ ᴛᴀᴘᴘᴘᴘᴘ",
        "ʟᴜɴᴅ ᴋᴇ ᴄʜᴏᴅᴇ ᴛᴜ ᴋᴇʀᴇɢᴀ ᴛʏᴘɪɴɢ ᴋʀᴇɢᴀ ᴛᴍᴋᴄ",
        "ꜱᴘᴇᴇᴅ ᴘᴋᴅ ʟᴡᴅᴇᴇᴇᴇ ᴡʀɴᴀ ᴍᴇʀᴀ ʟᴜɴᴅ ᴘᴋᴅ",
        "ʙᴀᴀᴘ ᴋɪ ꜱᴘᴇᴇᴅ ᴍᴛᴄʜ ᴋʀʀʀ",
        "ʟᴡᴅᴀ ʟᴇ ᴍᴇʀᴀ ᴊᴀʟᴅɪ sᴇ ᴛᴜ",
        "ᴘᴀᴘᴀ ᴋɪ ꜱᴘᴇᴇᴅ ᴍᴛᴄʜ ɴʜɪ ʜᴏ ʀʜɪ ᴋʏᴀ ᴛᴇʀᴇsᴇ",
        "ᴀʟᴇ ᴀʟᴇ ᴍᴇʟᴀ ʙᴄʜᴀᴀᴀᴀ ᴛᴇʀʏ ᴍᴀᴋᴀ ʙᴏsᴅᴀ sᴜɴ",
        "ᴄʜᴜᴅ ɢʏᴀ ʀᴀɴᴅɪʙᴀᴀᴢ ᴘᴀᴘᴀ ꜱᴇᴇᴇ ᴛᴜ",
        "ᴍᴇɴᴜ ᴋɪ ᴘᴛᴀ ᴛᴇʀʏ ᴍᴀ ᴄᴜᴅ ɢᴀɪ",
        "ᴋᴏɪ ʙᴀᴀᴛ ɴʏ ᴍᴀᴀ ʀᴀɴᴅʏ ᴛᴇʀʏ",
        "ʜᴀʜᴀʜᴀᴀᴀᴀᴀ ᴍᴀᴋᴀʙᴏsᴅᴀ ᴛᴇʀʏ",
        "xʜᴜᴅ ɢᴀɪ ᴍᴀᴀ ᴛᴇʀʏ ᴋɪᴅꜱꜱꜱꜱ",
        "ᴛᴇʀɪ ᴍᴀ ᴄʜᴜᴅ ɢʏɪ ᴀʙ ꜰʀᴀʀ ᴍᴛ ʜᴏɴᴀ",
        "ʏᴇ ʟᴜɴᴅ ʟᴇ ᴍᴇʀᴀ ᴄʜʟ ᴊᴀʟᴅɪ sᴇ",
        "ᴋɪᴅꜱꜱꜱ ꜰʀᴀʀ ɴᴀ ʜᴏ ᴛᴜ ʜᴀʜᴀʜʜ",
        "ʙʜᴇɴ ᴋᴇ ʟᴡᴅᴇ ꜱʜʀᴍ ᴋʀ",
        "ᴋɪᴛɴɪ ɢʟɪʏᴀ ᴘᴅᴡᴇɢᴀ ᴀᴘɴɪ ᴍᴀ ᴋᴏ",
        "ᴄʜᴜᴘ ɴᴀʟʟɪɪ ʀᴀɴᴅʏᴋᴇ ʟᴀᴅᴋᴇ",
        "ꜱᴜᴀʀ ᴋᴇ ᴘɪʟʟᴇ ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ꜱᴀᴅᴀᴋ ᴘʀ ʟɪᴛᴀᴋᴇ ᴄʜᴏᴅ ᴅᴜɴɢᴀ 😂😆🤤",
        "ᴀʙᴇ ᴛᴇʀɪ ᴍᴀᴀᴋᴀ ʙʜᴏꜱᴅᴀ ᴍᴀᴅᴇʀᴄʜᴏᴏᴅ ᴋʀ ᴘɪʟʟᴇ ᴘᴀᴘᴀ ꜱᴇ ʟᴀᴅᴇɢᴀ ᴛᴜ 😼😂🤤",
        "ɢᴀʟɪ ɢᴀʟɪ ɴᴇ ꜱʜᴏʀ ʜᴇ ᴛᴇʀɪ ᴍᴀᴀ ʀᴀɴᴅɪ ᴄʜᴏʀ ʜᴇ 💋💋💦",
        "ᴀʙᴇ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴏ ᴄʜᴏᴅᴜ ʀᴀɴᴅɪᴋᴇ ᴘɪʟʟᴇ ᴋᴜᴛᴛᴇ ᴋᴇ ᴄʜᴏᴅᴇ 😂👻🔥",
        "ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴀɪꜱᴇ ᴄʜᴏᴅᴀ ᴀɪꜱᴇ ᴄʜᴏᴅᴀ ᴛᴇʀɪ ᴍᴀᴀᴀ ʙᴇᴅ ᴘᴇʜɪ ᴍᴜᴛʜ ᴅɪᴀ 💦💦💦💦",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴇ ʙʜᴏꜱᴅᴇ ᴍᴇ ᴀᴀᴀɢ ʟᴀɢᴀᴅɪᴀ ᴍᴇʀᴀ ᴍᴏᴛᴀ ʟᴜɴᴅ ᴅᴀʟᴋᴇ 🔥🔥💦😆😆",
        "ʀᴀɴᴅɪᴋᴇ ʙᴀᴄʜʜᴇ ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴄʜᴏᴅᴜ ᴄʜᴀʟ ɴɪᴋᴀʟ",
        "ᴋɪᴛɴᴀ ᴄʜᴏᴅᴜ ᴛᴇʀɪ ʀᴀɴᴅɪ ᴍᴀᴀᴋɪ ᴄʜᴜᴛʜ ᴀʙʙ ᴀᴘɴɪ ʙᴇʜᴇɴ ᴋᴏ ʙʜᴇᴊ 😆👻🤤",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴏᴛᴏ ᴄʜᴏᴅ ᴄʜᴏᴅᴋᴇ ᴘᴜʀᴀ ꜰᴀᴀᴅ ᴅɪᴀ ᴄʜᴜᴛʜ ᴀʙʙ ᴛᴇʀɪ ɢꜰ ᴋᴏ ʙʜᴇᴊ 😆💦🤤",
        "ᴛᴇʀɪ ɢꜰ ᴋᴏ ᴇᴛɴᴀ ᴄʜᴏᴅᴀ ʙᴇʜᴇɴ ᴋᴇ ʟᴏᴅᴇ ᴛᴇʀɪ ɢꜰ ᴛᴏ ᴍᴇʀɪ ʀᴀɴᴅɪ ʙᴀɴɢᴀʏɪ ᴀʙʙ ᴄʜᴀʟ ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴄʜᴏᴅᴛᴀ ꜰɪʀꜱᴇ ♥️💦😆😆😆😆",
        "ʜᴀʀɪ ʜᴀʀɪ ɢʜᴀᴀꜱ ᴍᴇ ᴊʜᴏᴘᴅᴀ ᴛᴇʀɪ ᴍᴀᴀᴋᴀ ʙʜᴏꜱᴅᴀ 🤣🤣💋💦",
        "ᴄʜᴀʟ ᴛᴇʀᴇ ʙᴀᴀᴘ ᴋᴏ ʙʜᴇᴊ ᴛᴇʀᴀ ʙᴀꜱᴋᴀ ɴʜɪ ʜᴇ ᴘᴀᴘᴀ ꜱᴇ ʟᴀᴅᴇɢᴀ ᴛᴜ",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋɪ ᴄʜᴜᴛʜ ᴍᴇ ʙᴏᴍʙ ᴅᴀʟᴋᴇ ᴜᴅᴀ ᴅᴜɴɢᴀ ᴍᴀᴀᴋᴇ ʟᴀᴡᴅᴇ",
        "ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴛʀᴀɪɴ ᴍᴇ ʟᴇᴊᴀᴋᴇ ᴛᴏᴘ ʙᴇᴅ ᴘᴇ ʟɪᴛᴀᴋᴇ ᴄʜᴏᴅ ᴅᴜɴɢᴀ ꜱᴜᴀʀ ᴋᴇ ᴘɪʟʟᴇ 🤣🤣💋💋",
        "ᴛᴇʀɪ ᴍᴀᴀᴀᴋᴇ ɴᴜᴅᴇꜱ ɢᴏᴏɢʟᴇ ᴘᴇ ᴜᴘʟᴏᴀᴅ ᴋᴀʀᴅᴜɴɢᴀ ʙᴇʜᴇɴ ᴋᴇ ʟᴀᴇᴡᴅᴇ 👻🔥",
        "ᴛᴇʀɪ ᴍᴀᴀᴀᴋᴇ ɴᴜᴅᴇꜱ ɢᴏᴏɢʟᴇ ᴘᴇ ᴜᴘʟᴏᴀᴅ ᴋᴀʀᴅᴜɴɢᴀ ʙᴇʜᴇɴ ᴋᴇ ʟᴀᴇᴡᴅᴇ 👻🔥",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴏ ᴄʜᴏᴅ ᴄʜᴏᴅᴋᴇ ᴠɪᴅᴇᴏ ʙᴀɴᴀᴋᴇ xɴxx ᴘᴇ ɴᴇᴇʟᴀᴍ ᴋᴀʀᴅᴜɴɢᴀ ᴋᴜᴛᴛᴇ ᴋᴇ ᴘɪʟʟᴇ 💦💋",
        "ᴛᴇʀɪ ᴍᴀᴀᴀᴋɪ ᴄʜᴜᴅᴀɪ ᴋᴏ ᴘᴏ*ʀɴʜᴜʙ ᴘᴇ ᴜᴘʟᴏᴀᴅ ᴋᴀʀᴅᴜɴɢᴀ ꜱᴜᴀʀ ᴋᴇ ᴄʜᴏᴅᴇ 🤣💋💦",
        "ᴀʙᴇ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴏ ᴄʜᴏᴅᴜ ʀᴀɴᴅɪᴋᴇ ʙᴀᴄʜʜᴇ ᴛᴇʀᴇᴋᴏ ᴄʜᴀᴋᴋᴏ ꜱᴇ ᴘɪʟᴡᴀᴠᴜɴɢᴀ ʀᴀɴᴅɪᴋᴇ ʙᴀᴄʜʜᴇ 🤣🤣",
        "ᴛᴇʀɪ ᴍᴀᴀᴋɪ ᴄʜᴜᴛʜ ꜰᴀᴀᴅᴋᴇ ʀᴀᴋᴅɪᴀ ᴍᴀᴀᴋᴇ ʟᴏᴅᴇ ᴊᴀᴀ ᴀʙʙ ꜱɪʟᴡᴀʟᴇ 👄👄",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋɪ ᴄʜᴜᴛʜ ᴍᴇ ᴍᴇʀᴀ ʟᴜɴᴅ ᴋᴀᴀʟᴀ",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ʟᴇᴛɪ ᴍᴇʀɪ ʟᴜɴᴅ ʙᴀᴅᴇ ᴍᴀꜱᴛɪ ꜱᴇ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴏ ᴍᴇɴᴇ ᴄʜᴏᴅ ᴅᴀʟᴀ ʙᴏʜᴏᴛ ꜱᴀꜱᴛᴇ ꜱᴇ",
        "ʙᴇᴛᴇ ᴛᴜ ʙᴀᴀᴘ ꜱᴇ ʟᴇɢᴀ ᴘᴀɴɢᴀ ᴛᴇʀɪ ᴍᴀᴀᴀ ᴋᴏ ᴄʜᴏᴅ ᴅᴜɴɢᴀ ᴋᴀʀᴋᴇ ɴᴀɴɢᴀ 💦💋",
        "ʜᴀʜᴀʜᴀʜ ᴍᴇʀᴇ ʙᴇᴛᴇ ᴀɢʟɪ ʙᴀᴀʀ ᴀᴘɴɪ ᴍᴀᴀᴋᴏ ʟᴇᴋᴇ ᴀᴀʏᴀ ᴍᴀᴛʜ ᴋᴀᴛ ᴏʀ ᴍᴇʀᴇ ᴍᴏᴛᴇ ʟᴜɴᴅ ꜱᴇ ᴄʜᴜᴅᴡᴀʏᴀ ᴍᴀᴛʜ ᴋᴀʀ",
        "ᴄʜᴀʟ ʙᴇᴛᴀ ᴛᴜᴊʜᴇ ᴍᴀᴀꜰ ᴋɪᴀ 🤣ᴛᴜ ᴀʙʙ ᴀᴘɴɪ ᴍᴀᴋᴏ ʙʜᴇᴊ",
        "ꜱʜᴀʀᴀᴍ ᴋᴀʀ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴀ ʙʜᴏꜱᴅᴀ ᴋɪᴛɴᴀ ɢᴀᴀʟɪᴀ ꜱᴜɴᴡᴀʏᴇɢᴀ ᴀᴘɴɪ ᴍᴀᴀᴀ ʙᴇʜᴇɴ ᴋᴇ ᴜᴘᴇʀ",
        "ᴀʙᴇ ʀᴀɴᴅɪᴋᴇ ʙᴀᴄʜʜᴇ ᴀᴜᴋᴀᴛ ɴʜɪ ʜᴇᴛᴏ ᴀᴘɴɪ ʀᴀɴᴅɪ ᴍᴀᴀᴋᴏ ʟᴇᴋᴇ ᴀᴀʏᴀ ᴍᴀᴛʜ ᴋᴀʀ ʜᴀʜᴀʜᴀʜᴀ",
        "ᴋɪᴅᴢ ᴍᴀᴅᴀʀᴄʜᴏᴅ ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴄʜᴏᴅ ᴄʜᴏᴅᴋᴇ ᴛᴇʀʀ ʟɪʏᴇ ʙʜᴀɪ ᴅᴇᴅɪʏᴀ",
        "ᴊᴜɴɢʟᴇ ᴍᴇ ɴᴀᴄʜᴛᴀ ʜᴇ ᴍᴏʀᴇ ᴛᴇʀɪ ᴍᴀᴀᴋɪ ᴄʜᴜᴅᴀɪ ᴅᴇᴋᴋᴇ ꜱᴀʙ ʙᴏʟᴛᴇ ᴏɴᴄᴇ ᴍᴏʀᴇ ᴏɴᴄᴇ ᴍᴏʀᴇ 🤣🤣💦💋",
        "ɢᴀʟɪ ɢᴀʟɪ ᴍᴇ ʀᴇʜᴛᴀ ʜᴇ ꜱᴀɴᴅ ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴄʜᴏᴅ ᴅᴀʟᴀ ᴏʀ ʙᴀɴᴀ ᴅɪᴀ ʀᴀɴᴅ 🤤🤣",
        "ꜱᴀʙ ʙᴏʟᴛᴇ ᴍᴜᴊʜᴋᴏ ᴘᴀᴘᴀ ᴄʏᴜᴋɪ ᴍᴇɴᴇ ᴋʀᴅɪᴀ ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴘʀᴇɢɴᴇɴᴛ 🤣🤣",
        "ꜱᴜᴀʀ ᴋᴇ ᴘɪʟʟᴇ ᴛᴇʀɪ ᴍᴀᴀᴋɪ ᴄʜᴜᴛʜ ᴍᴇ ꜱᴜᴀʀ ᴋᴀ ʟᴏᴜᴅᴀ ᴏʀ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋɪ ᴄʜᴜᴛʜ ᴍᴇ ᴍᴇʀᴀ ʟᴏᴅᴀ",
        "ᴄʜᴀʟ ᴄʜᴀʟ ᴛᴜ ᴀᴘɴɪ ᴍᴀᴀᴋɪ ᴄʜᴜᴄʜɪʏᴀ ᴅɪᴋᴀ",
        "ʜᴀʜᴀʜᴀʜᴀ ʙᴀᴄʜʜᴇ ᴛᴇʀɪ ᴍᴀᴀᴀᴋᴏ ᴄʜᴏᴅ ᴅɪᴀ ɴᴀɴɢᴀ ᴋᴀʀᴋᴇ",
        "ᴛᴇʀɪ ɢꜰ ʜᴇ ʙᴀᴅɪ ꜱᴇxʏ ᴜꜱᴋᴏ ᴘɪʟᴀᴋᴇ ᴄʜᴏᴏᴅᴇɴɢᴇ ᴘᴇᴘꜱɪ",
        "2 ʀᴜᴘᴀʏ ᴋɪ ᴘᴇᴘꜱɪ ᴛᴇʀɪ ᴍᴜᴍᴍʏ ꜱᴀʙꜱᴇ ꜱᴇxʏ 💋💦",
        "ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴄʜᴇᴇᴍꜱ ꜱᴇ ᴄʜᴜᴅᴡᴀᴠᴜɴɢᴀ ᴍᴀᴅᴇʀᴄʜᴏᴏᴅ ᴋᴇ ᴘɪʟʟᴇ 💦🤣",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋɪ ᴄʜᴜᴛʜ ᴍᴇ ᴍᴜᴛʜᴋᴇ ꜰᴀʀᴀʀ ʜᴏᴊᴀᴠᴜɴɢᴀ ʜᴜɪ ʜᴜɪ ʜᴜɪ",
        "ꜱᴘᴇᴇᴅ ʟᴀᴀᴀ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴄʜᴏᴅᴜ ʀᴀɴᴅɪᴋᴇ ᴘɪʟʟᴇ 💋💦🤣",
        "ᴀʀᴇ ʀᴇ ᴍᴇʀᴇ ʙᴇᴛᴇ ᴄʏᴜ ꜱᴘᴇᴇᴅ ᴘᴀᴋᴀᴅ ɴᴀ ᴘᴀᴀᴀ ʀᴀʜᴀ ᴀᴘɴᴇ ʙᴀᴀᴘ ᴋᴀ ʜᴀʜᴀʜᴀ ᴛᴇʀɪ ᴍᴀᴀ ᴄᴜᴅ ɢᴀɪ🤣🤣",
        "ꜱᴜɴ ꜱᴜɴ ꜱᴜᴀʀ ᴋᴇ ᴘɪʟʟᴇ ᴊʜᴀɴᴛᴏ ᴋᴇ ꜱᴏᴜᴅᴀɢᴀʀ ᴀᴘɴɪ ᴍᴜᴍᴍʏ ᴋɪ ɴᴜᴅᴇꜱ ʙʜᴇᴊ",
        "ᴀʙᴇ ꜱᴜɴ ʟᴏᴅᴇ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴀ ʙʜᴏꜱᴅᴀ ꜰᴀᴀᴅ ᴅᴜɴɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴋʜᴜʟᴇ ʙᴀᴊᴀʀ ᴍᴇ ᴄʜᴏᴅ ᴅᴀʟᴀ 🤣🤣💋",
        "ꜱʜʀᴍ ᴋʀ ᴛᴇʀʏ ᴍᴀᴀ ᴄᴜᴅ ɢᴀɪ ʏʜᴀ",
        "ᴍᴇʀᴇ ʟᴜɴᴅ ᴋᴇ ʙᴀᴀᴀᴀᴀʟʟʟʟʟ ᴘᴋᴅ ᴊᴀʟᴅɪ sᴇ",
        "ᴛᴜ ᴇᴋ ᴋᴀᴀᴍ ᴋʀ ᴀᴘɴɪ ᴍᴀ ʙʜᴇɴ ᴋᴏ ᴄᴜᴅᴡᴀ ʟᴇ ᴍᴇʀᴇ sᴛʜ",
        "ʀɴᴅɪ ᴋᴇ ʟᴅᴋᴇᴇᴇᴇᴇᴇᴇᴇᴇ ᴄʜᴜᴘ ᴏʀ ᴄᴜᴅ ʏʜᴀ",
        "ᴄʜᴜᴘ ᴛᴍᴋᴄ ᴋɪᴅꜱꜱꜱꜱꜱꜱꜱꜱꜱꜱꜱꜱ",
        "ᴀᴘɴɪ ɢᴀᴀɴᴅ ᴍᴇɪɴ ᴍᴜᴛʜɪ ᴅᴀᴀʟ",
        "ᴍᴇʀᴀ ʟᴜɴᴅ ᴄʜᴏᴏꜱ ᴊᴀʟᴅɪ sᴇ",
        "ᴀᴘɴɪ ᴍᴀ ᴋᴏ ᴄᴜsᴡᴀ ᴍᴇʀᴀ ʟᴜɴᴅ",
        "ʙʜᴇɴ ᴋᴇ ʟᴀᴜᴅᴇ ᴛᴍᴄ",
        "ʙʜᴇɴ ᴋᴇ ᴛᴀᴋᴋᴇ ᴛᴍʟ",
        "ᴀʙʟᴀ ᴛᴇʀᴀ ᴋʜᴀɴ ᴅᴀɴ ᴄʜᴏᴅɴᴇ ᴋɪ ʙᴀʀɪɪɪ",
        "ʙᴇᴛᴇ ᴛᴇʀɪ ᴍᴀ ꜱʙꜱᴇ ʙᴅɪ ʀᴀɴᴅ",
        "ʟᴜɴᴅ ᴋᴇ ʙᴀᴀᴀʟ ᴊʜᴀᴛ ᴋᴇ ᴘɪꜱꜱꜱᴜᴜᴜᴜᴜᴜᴜ ᴛᴍᴋᴄ",
        "ʟᴜɴᴅ ᴘᴇ ʟᴛᴋɪᴛ ᴍᴀᴀᴀʟʟʟʟ ᴋɪ ʙᴏɴᴅ ʜ ᴛᴜᴜᴜ",
        "ᴋᴀꜱʜ ᴏꜱ ᴅɪɴ ᴍᴜᴛʜ ᴍʀᴋᴇ ꜱᴏᴊᴛᴀ ᴍ ᴛᴜ ᴘᴀɪᴅᴀ ɴᴀ ʜᴏᴛᴀᴀ",
        "ɢʟᴛɪ ᴋʀᴅɪ ᴛᴜᴊᴡ ᴘᴀɪᴅᴀ ᴋʀᴋᴇ ᴛᴇʀʏ ᴍᴀ ɴᴇ ᴀʙ ᴄᴜᴅ ᴛᴜ ʏʜᴀ",
        "ꜱᴘᴇᴇᴅ ᴘᴋᴅᴅᴅ",
        "ɢᴀᴀɴᴅ ᴍᴀɪɴ ʟᴡᴅᴀ ᴅᴀʟ ʟᴇ ᴀᴘɴɪ ᴍᴇʀᴀᴀᴀ",
        "ɢᴀᴀɴᴅ ᴍᴇɪɴ ʙᴀᴍʙᴜ ᴅᴇᴅᴜɴɢᴀᴀᴀᴀᴀᴀ",
        "ɢᴀɴᴅ ꜰᴛɪ ᴋᴇ ʙᴀʟᴋᴋᴋ ᴛᴜ ᴄᴜᴅ ʏʜᴀ",
        "ɢᴏᴛᴇ ᴋɪᴛɴᴇ ʙʜɪ ʙᴀᴅᴇ ʜᴏ, ʟᴜɴᴅ ᴋᴇ ɴɪᴄʜᴇ ʜɪ ʀᴇʜᴛᴇ ʜᴀɪ",
        "ʜᴀᴢᴀᴀʀ ʟᴜɴᴅ ᴛᴇʀɪ ɢᴀᴀɴᴅ ᴍᴀɪɴ",
        "ᴊʜᴀᴀɴᴛ ᴋᴇ ᴘɪꜱꜱᴜ ᴛᴍᴋᴄ sᴜɴ",
        "ᴛᴇʀɪ ᴍᴀ ᴋɪ ᴋᴀʟɪ ᴄʜᴜᴛ",
        "ᴋʜᴏᴛᴇʏ ᴋɪ ᴀᴜʟᴅᴀ ᴇʏ ᴛᴜ ʀᴀɴᴅʏᴋᴇ",
        "ᴋᴜᴛᴛᴇ ᴋᴀ ᴀᴡʟᴀᴛ ᴊᴀɪsᴀ ʟɢ ʀʜᴀ ᴛᴜ",
        "ᴋᴜᴛᴛᴇ ᴋɪ ᴊᴀᴛ ᴊᴀɪsᴀ ᴇʏ ᴛᴜ ",
        "ᴋᴜᴛᴛᴇ ᴋᴇ ᴛᴀᴛᴛᴀ ᴇʏ ᴛᴜ",
        "ᴛᴇᴛɪ ᴍᴀ ᴋɪ.ᴄʜᴜᴛ , ᴛᴇʀɪ ᴍᴀ ʀɴᴅɪɪɪɪɪɪɪɪɪɪɪɪɪɪɪɪɪɪɪɪ",
        "ʟᴀᴠᴅᴇ ᴋᴇ ʙᴀʟ ᴘᴋᴅ ʟᴇ ᴍᴇʀᴇ",
        "ᴍᴜʜ ᴍᴇɪ ʟᴇʟᴇ ᴍᴇʀᴀ ʟᴜɴᴅ",
        "ʟᴜɴᴅ ᴋᴇ ᴘᴀꜱɪɴᴇ ᴄʜᴜᴘ ʙᴇᴛʜ ᴏʀ ᴄᴜᴅ",
        "ᴍᴇʀᴇ ʟᴡᴅᴇ ᴋᴇ ʙᴀᴀᴀᴀᴀʟʟʟ",
        "ʜᴀʜᴀʜᴀᴀᴀᴀᴀᴀ ᴛᴇʀʏ ᴍᴀᴀ ᴄᴜᴅ ɢᴀɪ",
        "ᴛᴜ ᴄʜᴜᴅ ɢʏᴀᴀᴀᴀᴀ",
        "ʀᴀɴᴅɪ ᴋʜᴀɴᴇ ᴋɪ ᴜʟᴀᴅᴅᴅ",
        "ꜱᴀᴅɪ ʜᴜɪ ɢᴀᴀɴᴅ",
        "ᴛᴇʀɪ ɢᴀᴀɴᴅ ᴍᴀɪɴ ᴋᴜᴛᴇ ᴋᴀ ʟᴜɴᴅ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴀ ʙʜᴏꜱᴅᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ",
        "ᴛᴇʀᴇ ɢᴀᴀɴᴅ ᴍᴇɪɴ ᴋᴇᴇᴅᴇ ᴘᴀᴅᴀʏ",
        "ɴʏ ɴʏ ᴛᴇʀʏ ᴍᴀᴀ ʀᴀɴᴅɪ",
        "ꜱᴜɴɴ ᴍᴀᴅᴇʀᴄʜᴏᴅ ᴛᴍʟ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴀ ʙʜᴏꜱᴅᴀ",
        "ʙᴇʜᴇɴ ᴋ ʟᴜɴᴅ ᴄʜᴜᴘᴄʜᴀᴘ ᴄᴜᴅ ʏʜᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴀ ᴄʜᴜᴛ ᴋɪ ᴄʜᴛɴɪɪɪɪ",
        "ᴍᴇʀᴀ ʟᴀᴡᴅᴀ ʟᴇʟᴇ ᴛᴜ ᴀɢᴀʀ ᴄʜᴀɪʏᴇ ᴛᴏʜ",
        "ᴄʜᴜᴘ ɢᴀᴀɴᴅᴜ",
        "ᴄʜᴜᴘ ᴄʜᴜᴛɪʏᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴘᴇ ᴊᴄʙ ᴄʜᴀᴅʜᴀᴀ ᴅᴜɴɢᴀ",
        "ꜱᴀᴍᴊʜᴀᴀ ʟᴀᴡᴅᴇ",
        "ʏᴀ ᴅᴜ ᴛᴇʀɪ ɢᴀᴀɴᴅ ᴍᴇ ᴛᴀᴘᴀᴀ ᴛᴀᴘ��",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴍᴇʀᴀ ʀᴏᴢ ʟᴇᴛɪ ʜᴀɪ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴇ ꜱᴀᴀᴛʜ ᴍᴍꜱ ʙᴀɴᴀᴀ ᴄʜᴜᴋᴀ ʜᴜ���不�不",
        "ᴛᴜ ᴄʜᴜᴛɪʏᴀ ᴛᴇʀᴀ ᴋʜᴀɴᴅᴀᴀɴ ᴄʜᴜᴛɪʏᴀ",
        "ᴀᴜʀ ᴋɪᴛɴᴀ ʙᴏʟᴜ ʙᴇʏ ᴍᴀɴɴ ʙʜᴀʀ ɢᴀʏᴀ ᴍᴇʀᴀ�不",
        "ᴛᴇʀɪɪɪɪɪɪ ᴍᴀᴀᴀᴀ ᴋɪ ᴄʜᴜᴛᴛᴛ ᴍᴇ ᴀʙᴄᴅ ʟɪᴋʜ ᴅᴜɴɢᴀ ᴍᴀᴀ ᴋᴇ ʟᴏᴅᴇ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ʟᴇᴋᴀʀ ᴍᴀɪ ꜰᴀʀᴀʀ",
        "ᴛᴇʀʏ ᴍᴀᴀ ʀᴀɴɪᴅɪɪɪ",
        "ᴄʜᴜᴘ ʙᴀᴄʜᴇᴇ ᴛᴍᴋᴄ",
        "ᴛᴇʀʏ ᴍᴀᴋᴏᴄʜᴏᴅᴜ",
        "ʀᴀɴᴅɪ ᴍᴀᴀ ᴛᴇʀʏ",
        "ᴛᴜ ʀᴀɴᴅɪ ᴋᴇ ᴘɪʟʟᴀ ᴇʏ",
        "ᴛᴇʀɪɪɪɪɪ ᴍᴀᴀᴀ ᴋᴏ ʙʜᴇᴊᴊᴊ",
        "ᴛᴇʀᴀᴀ ʙᴀᴀᴀᴀᴘ ʜᴜ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴍᴇ ʜᴀᴀᴛ ᴅᴀᴀʟʟᴋᴇ ʙʜᴀᴀɢ ᴊᴀᴀɴᴜɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ꜱᴀʀᴀᴋ ᴘᴇ ʟᴇᴛᴀᴀ ᴅᴜɴɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ɢʙ ʀᴏᴀᴅ ᴘᴇ ʟᴇᴊᴀᴋᴇ ʙᴇᴄʜ ᴅᴜɴɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴍÉ ᴋᴀᴀʟɪ ᴍɪᴛᴄʜ",
        "ᴛᴇʀɪ ᴍᴀᴀ ꜱᴀꜱᴛɪ ʀᴀɴᴅɪ ʜᴀɪ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴍᴇ ᴋᴀʙᴜᴛᴀʀ ᴅᴀᴀʟ ᴋᴇ ꜱᴏᴜᴘ ʙᴀɴᴀᴜɴɢᴀ ᴍᴀᴅᴀʀᴄʜᴏᴅ",
        "ᴛᴇʀɪ ᴍᴀᴀᴀ ʀᴀɴᴅɪ ʜᴀɪ",
        "ᴛᴇʀɪ ᴍᴀᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴍᴇ ᴅᴇᴛᴏʟ ᴅᴀᴀʟ ᴅᴜɴɢᴀ ᴍᴀᴅᴀʀᴄʜᴏᴅ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴀᴀᴀ ʙʜᴏꜱᴅᴀᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴍᴇ ʟᴀᴘᴛᴏᴘ",
        "ᴛᴇʀɪ ᴍᴀᴀ ʀᴀɴᴅɪ ʜᴀɪ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ʙɪꜱᴛᴀʀ ᴘᴇ ʟᴇᴛᴀᴀᴋᴇ ᴄʜᴏᴅᴜɴɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ᴀᴍᴇʀɪᴄᴀ ɢʜᴜᴍᴀᴀᴜɴɢᴀ ᴍᴀᴅᴀʀᴄʜᴏᴅ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴍᴇ ɴᴀᴀʀɪʏᴀʟ ᴘʜᴏʀ ᴅᴜɴɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴇ ɢᴀɴᴅ ᴍᴇ ᴅᴇᴛᴏʟ ᴅᴀᴀʟ ᴅᴜɴɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀᴀ ᴋᴏ ʜᴏʀʟɪᴄᴋꜱ ᴘɪʟᴀᴜɴɢᴀ ᴍᴀᴅᴀʀᴄʜᴏᴅ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ꜱᴀʀᴀᴋ ᴘᴇ ʟᴇᴛᴀᴀᴀ ᴅᴜɴɢᴀᴀᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴀᴀ ʙʜᴏꜱᴅᴀ",
        "ᴍᴇʀᴀᴀᴀ ʟᴜɴᴅ ᴘᴀᴋᴀᴅ ʟᴇ ᴍᴀᴅᴀʀᴄʜᴏᴅ",
        "ᴄʜᴜᴘ ᴛᴇʀɪ ᴍᴀᴀ ᴀᴋᴀᴀ ʙʜᴏꜱᴅᴀᴀ",
        "ᴛᴇʀɪɪɪ ᴍᴀᴀ ᴄʜᴜꜰ ɢᴇʏɪɪ ᴋʏᴀᴀᴀ ʟᴀᴡᴅᴇᴇᴇ",
        "ᴛᴇʀɪɪɪ ᴍᴀᴀ ᴋᴀᴀ ʙᴊꜱᴏᴅᴀᴀᴀ",
        "ᴍᴀᴅᴀʀxʜᴏᴅᴅᴅ",
        "ᴛᴇʀɪᴜᴜɪ ᴍᴀᴀᴀ ᴋᴀᴀ ʙʜꜱᴏᴅᴀᴀᴀ",
        "ᴛᴇʀɪɪɪɪɪɪ ʙᴇʜᴇɴɴɴɴ ᴋᴏ ᴄʜᴏᴅᴅᴅᴜᴜᴜᴜ ᴍᴀᴅᴀʀxʜᴏᴅᴅᴅᴅ",
        "ᴛᴜ ɴɪᴋᴀʟ ᴍᴀᴅᴀʀᴄʜᴏᴅ",
        "ᴄʜᴜᴘ ʀᴀɴᴅɪ ᴋᴇ ʙᴀᴄʜᴇ",
        "ᴛᴇʀᴀ ᴍᴀᴀ ᴍᴇʀɪ ᴊᴀᴀɴ ᴇʏ",
        "ᴛᴇʀɪ ꜱᴇxʏ ʙᴀʜᴇɴ ᴋɪ ᴄʜᴜᴛ ᴏᴘ"
        "👩🏿      👩🏻‍🦳        👵🏼         👱🏿‍♀️     \n👖      👖        👖         👖     \n\nतेरी बहन /तेरी माँ /तेरी दादि/ तेरीभुआ.\n\nसब की 𝐂hu𝐃𝐀i hogi",
        "तेरी माँ के（ ͜.人 ͜.）दबा दूंगा",
        "तेरी मा चुदी हुई थी\nचुदी हुई है\nऔर चुदी हुई रहेगी \n\n\"MARK MY WORD\" 😈",
        "𝐊ʏᴀ?\n𝐂ʏᴀ?\n𝐂ᴜᴀ?\n\n𝐌ᴛᴛ 𝐊ʀʀ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ɪ 𝐂ʜᴜᴛ 𝐏𝐞 𝐓ʜ𝐀ᴘᴘᴀᴅ 𝐌ᴀ𝐚ʀ 𝐃ᴜɴɢᴀ",
        "˚∧＿∧  　+        — ͟͞͞🥛\n(  •‿• )つ  — ͟͞͞ 🥛 \nSpecial attack tery mummy ke chuchiya ka dudu 🐱🎀",
        "Aaj Rakshabandhan Ke Avsar Pr तेरी मांँ मेरे लंड पर राखी Bandh Ke चुदेगी 😍🥰",
        "Sun दोस्त terko ye तीन चीजे कभी nahi भूलनी chaiye 😁👇🏻🤙🏿\n\n1 :- तेरी औकात\n2 :- तेरी बहन का फटा bhosda\n3 :- तेरी मां के भोसड़े में मेरा मूत",
        "Tery Maa Behen Ke Boshde Me Kya Maarun Jaldi Bata 😜🤙",
        "Tery Maa\nⓘ Verified Randy // 🦅🔥",
        "𝐒ᴀʏ 𝐑ᴀɴᴅɪʙᴀᴀᴢ 𝐃ᴀᴅᴅʏ 𓆩💗𓆪",
        "𝐖ᴏ ʙʜɪ ᴋʏᴀ ᴅɪɴ ᴛʜᴇ ᴊᴀʙ ᴛʀʏ ᴍᴀᴀ ᴍᴜᴊʜᴇ 𝐀ᴘɴᴀ 𝐂ʜᴜᴛ 𝐃ᴇᴛɪ ᴛʜɪ ʏᴀᴀʀ 💔🥀👌🏻",
        "𝐀ᴡᴀᴢ 𝐍ɪᴄʜᴇ 𝐆ᴜʟᴀᴀᴍ 🤢👇🏻",
        "𝐓ʀʏ 𝐌ᴀᴀ ɴᴇ 𝐂ʜᴜᴅɴᴇ 𝐌ᴀɪ ɢᴏʟᴅ 𝐌ᴇᴅᴀʟ 𝐉ᴇᴇᴛᴀ ᴇʏ 𝐃ᴏꜱᴛ 🤩👑",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴛ 𝐌ᴇ 𝐌ᴇʀᴀ 𝐋ᴜɴᴅ 🖕🏻😈",
        "𝐁ʜᴏꜱᴀᴅɪᴋᴇ 𝐀ᴘɴɪ 𝐁ᴇʜᴇɴ 𝐂ʜᴜᴅᴀ 🖕🏻😈",
        "𝐑ᴀɴᴅɪ ᴋᴇ 𝐁ᴀᴄᴄʜᴇ 𝐀ᴜᴋᴀᴛ 𝐌ᴇ 𝐑ᴇʜ 🖕🏻😈",
        "𝐌ᴀᴅᴀʀᴄʜᴏᴅ 𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴛ 🖕🏻😈",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋᴀ 𝐁ʜᴏꜱᴅᴀ ᴋʜᴏʟ ᴅᴜɴɢᴀ 🔓😈",
        "𝐁ʜᴇɴᴄʜᴏᴅ ??ᴘɴɪ 𝐀ᴜᴋᴀᴛ 𝐌ᴇ 𝐑ᴇʜ 🤡💩",
        "𝐓𝐌𝐊𝐂 ᴘᴇ 𝐂ʜᴀᴘᴘᴀʟ 𝐌ᴀᴀʀᴜɴɢᴀ 👟💥",
        "𝐁ʜᴏꜱᴅɪᴋᴇ 𝐓ᴇʀɪ 𝐊ʜᴀɴᴅᴀɴ ᴋɪ 𝐁𝐊𝐂 💀🖕🏻",
        "𝐑ᴀɴᴅɪ ᴋɪ 𝐀ᴜʟᴀᴅ ᴄʜᴜᴘ ʜᴏ ᴊᴀ 🔇😒",
        "𝐑ᴀɴᴅɪʙᴀᴀᴢ ka 𝐆ᴜʟᴀᴀᴍ ey ᴛᴜ ᴀʙ ᴛᴜ ʏʜᴀ ᴄᴜᴅᴋᴇ ᴅɪᴋʜᴀ ᴛᴇʀʏ ᴍᴀᴋᴏ ʟᴇᴋʀ 👑😎",
        "𝐓ᴇʀɪ 𝐁ᴇʜᴇɴ ᴋɪ 𝐂ʜᴜᴛ 𝐌ᴇ 𝐌ɪʀᴄʜɪ 🌶️🖕🏻",
        "𝐌ᴀᴅᴀʀᴄʜᴏᴅ 𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴛ 𝐌ᴇ 𝐏ᴀɪʀ 🦶🏻😈",
        "𝐁ʜᴏꜱᴀᴅɪᴋᴇ 𝐓ᴇʀɪ 𝐁ᴇʜᴇɴ ᴋᴀ 𝐁ʜᴏꜱᴅᴀ 🗑️😏",
        "𝐑ᴀɴᴅɪ ᴋᴀ 𝐏ɪʟʟᴀ ʜᴀɪ ᴛᴜ 🐕💩",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋᴏ 𝐁ᴀᴢᴀᴀʀ 𝐌ᴇ 𝐂ʜᴏᴅᴜɴɢᴀ 🌃😈",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴛ 𝐌ᴇ 𝐆ᴀʀᴀᴍ 𝐓ᴇʟ 🌡️🖕🏻",
        "𝐌ᴀᴅᴀʀᴄʜᴏᴅ 𝐓ᴇʀɪ 𝐁ᴇʜᴇɴ ᴍᴇʀɪ 𝐑ᴀɴᴅɪ 💋👿",
        "𝐑ᴀɴᴅɪ ᴋᴇ 𝐁ᴀᴄᴄʜᴇ 𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴛ 🖕🏻😈",
        "𝐓ᴇʀɪ 𝐁ᴇʜᴇɴ ᴋᴏ 𝐑ᴀᴀᴛ ʙʜᴀʀ 𝐂ʜᴏᴅᴜɴɢᴀ 🌙😈",
        "𝐑ᴀɴᴅɪ ᴋᴀ 𝐁ᴀᴄᴄʜᴀ ʜᴀɪ ᴛᴜ ꜱᴀᴀʟᴇ 🤡💀",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴛ 𝐌ᴇ 𝐌ᴇʀᴀ 𝐉ᴏᴏᴛᴀ 👞🖕🏻",
        "𝐑ᴀɴᴅɪʙᴀᴀᴢ 𝐃ᴀᴅᴅʏ ᴋᴀ 𝐆ᴜʟᴀᴀᴍ ʜᴀɪ ᴛᴜ 🥀😤",
        "ᴊɪꜱ ᴅɪɴ ᴛᴜ ᴘᴀɪᴅᴀ ʜᴜᴀ 𝐓ᴇʀɪ 𝐌ᴀᴀ ɴᴇ ꜱᴏᴄʜᴀ ᴛʜᴀ ᴋᴀꜱʜ ᴀʙᴏʀᴛ ᴋᴀʀ ᴅᴇᴛɪ 💀🥀",
        "𝐀ᴘɴɪ 𝐀ᴜᴋᴀᴛ ᴅᴇᴋʜ ᴋᴜᴛᴛᴇ 𝐓ᴇʀʏ 𝐌ᴀ 𝐂ᴜᴅ 𝐑ʜɪ🐕😂",
        "𝐓ᴇʀʏ 𝐌ᴀ 𝐂ᴜᴅ 𝐑ʜɪ 𝐆ᴀʟɪ ᴋᴀ 𝐊ᴜᴛᴛᴀ ʜᴀɪ ᴛᴜ 🐕🗑️",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ɴᴇ ᴍᴜᴊʜᴇ ᴅᴇᴋʜ ᴋᴇ ꜱᴏᴄʜᴀ ᴋᴀꜱʜ ʏᴇ ᴍᴇʀᴀ ʙᴇᴛᴀ ʜᴏᴛᴀ 🫦😏",
        "𝐂ʜᴜᴘ ᴋᴀʀ 𝐌ᴀᴅᴀʀᴄʜᴏᴅ ᴛᴇʀɪ ᴀᴜᴋᴀᴛ ɴᴀʜɪ ᴍᴇʀᴇ ꜱᴀᴀᴍɴᴇ ʙᴏʟɴᴇ ᴋɪ 🤐💀",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴅᴀɪ ᴍᴇ ᴊᴀʙ ᴍᴀɪ ᴛʜᴀ ᴛᴏ ᴛᴜ ᴘᴀɪᴅᴀ ʜᴜᴀ 💀😂",
        "𝐁ʜᴀɢ ʏᴀʜᴀɴ ꜱᴇ ᴋᴜᴛᴛᴇ ᴋᴇ ᴘɪʟʟᴇ 🐕💨",
        "𝐓ᴇʀɪ 𝐁ᴇʜᴇɴ ᴋɪ ꜱᴀᴅɪ 𝐌ᴇ ᴍᴇʀᴀ ʟᴜɴᴅ 💍😈",
        "𝐌ᴀᴅᴀʀᴄʜᴏᴅ ᴀᴘɴɪ 𝐌ᴀᴀ ᴍᴀᴛ ᴄʜᴜᴅᴀ 🖕🏻👹",
        "𝐁ʜᴇɴᴄʜᴏᴅ 𝐓ᴇʀɪ 𝐊ʜᴀɴᴅᴀɴ ᴋɪ 𝐁𝐊𝐂 💀🖕🏻",
        "tery ma cudke pgl dekh..𝐁𝐊𝐂 🦴🐕",
        "𝐊ʏᴀ 𝐑ᴇ 𝐑ᴀɴᴅɪᴋᴇ 𝐂ᴏᴏʟ 𝐁ᴀɴᴇɢᴀ 𝐓ᴜ 𝐂ʜᴀʟ 𝐀ʙ 𝐂ʜᴜᴅ 𝐀ᴘɴᴇ 𝐁ᴀᴀᴘ - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 𝐒ᴇ - 🦢💘",
        "tery 𝐌ᴀᴀ cudke 𝐌ᴀʀʀ  𝐆ᴀʏɪ 𝐘ᴀᴀʀ - 𝐉ᴀɪ - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 ! 🌙",
        "acha beta 😂🔥👊🏻 ? coi na me toh HATER codunga tery mako 😹💔🔥😆👊🏻💥",
        "chudke bhaga kaise 😂💥🤣🤘🏻",
        "ne toh - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 ka lun muh me lelia tune or tery maa ne😂🙏🏻😂🙏🏻",
        "try maa सूर्य☀ nikalte hi pel du 😹🔥💔",
        "mkl lun te vaj 😂✊🏻💦",
        "𝗧ᴍᴋ𝗕 pe - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 ka hamla 😂⚔🔥💥",
        "𝐂ʜʟ 𝐇ᴀʀᴍᴢᴀᴅ𝐈 𝐊ᴇ लड़के 💛🤍🩵",
        "oi 𝐓ᴇʀɪ 𝐌‌ᴀᴀ गुलाम ₰🖤",
        "chl rndyce chud ke dikha 😂💥🤣🔥",
        "tery 𝐌ᴀᴀ or bhen 𝐌ᴀʀʀ  𝐆ᴀʏɪ naacho 💃🏻💃🏻🕺🏻🎶😂😆💞🔥 !",
        "tera baap bass - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 ey 😂🎀",
        "try maa hagte hue paad mari -#😹🔥🥀",
        "𝐓ᴇʀɪ 𝐌ᴜᴍᴍʏ 𝐂ʜᴏᴅ 𝐃ɪ - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 𝐍ᴇ 𝐁ᴡᴀʜᴀʜᴀʜᴀ ⚜",
        "⋆｡ﾟ☁︎｡𝐂ʏᴜ 𝐑ᴇ मदरचोद - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 बाप के सामने 𝐅ʏᴛᴇʀ 𝐁ᴀɴᴇɢᴀ ⋆𓂃 ོ☼𓂃 😂🔥",
        "नहीं नहीं तेरी मां को 𝐒ɪʀғ - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 बाप चोद सकता है ִֶָ𓂃 ࣪ ִֶָ👑་༘࿐ sᴀᴍᴊʜᴀ ʀᴀɴᴅɪᴋᴇ ???",
        "तेरी मां का 𝐒ᴛʏʟɪsʜ भोसड़ा 😱",
        "𝑻𝒆𝒓?? 𝒎𝒂𝒂 𝒓𝒂𝒏𝒅𝒂𝒍 𝒉 𝒃𝒂𝒔 𝒃𝒂𝒂𝒕 𝒌𝒉𝒂𝒕𝒂𝒎 😡🔥",
        "सोच तेरी बहन को - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 बाप का गुलाम चोद रहा 😎🔥",
        "Hello hello?? Oxygen aarahi है? रण्डी पुत्र 🧘🏻",
        "Shut up रंडीके वरना दुनिया यही बोलेगी तेरी बहन - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 /~ 👑 बाप से सही chudi 🥵🔥",
        "ᴛᴜ ᴏʀ ᴛᴇʀɪ ᴍᴀᴀ ᴅᴏɴᴏ - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 बाप के ʟɴᴅ sᴇ ᴋᴀʙʜɪ ᴜᴛʜ ɴʜɪ ᴘᴀʏᴇ 😂🔥",
        "🇮🇳𝐵𝐻𝐴𝑅𝐴𝑇 𝐻𝐴𝑀𝐴𝑅𝐴 𝐷𝐸𝑆𝐻 𝐻 𝐴𝑈𝑅 𝑈𝑆 𝐷𝐸𝑆𝐻 𝑀𝐸 तेरी मां घर घर जाके MOAN करती है ! 🛐",
        "Tᴇʀɪ Mᴀᴀ Rᴀɴᴅɪ (🩷)—(❤️)—(🧡)—(💛)—(💚)—(🩵)—(💙)—(💜)—(🖤)—(🩶)—(🤍)—(🤎)—(🌸)—(✨)—(🌙)—(⭐)—(🦋)—(💎)—(👑)—(⚡)—(🔥)—(🌌)—(🎀)—(💫)—(🪽)—(🫧)—(🌸)—(💘)—(💓)—(💖)—(💕)—(💞)",
        "Teri make hath me chakku se hole karke lund daluga apna 🤢🤢",
        "Subha ho ya sham chudte rhena hai teri maaka kaam😂🔥😂🔥😂🔥",
        "𝐓ᴜ 𝐒ᴡɪᴘᴇ 𝐊ᴀʀᴛᴀ 𝐑ᴇʜ 𝐌ᴀɪ ᴄʜᴀʟᴀ 𝐓ᴇʀɪ 𝐁ᴇʜᴇɴ ᴋᴇ 𝐒ᴀᴛʜ 𝐊ʜᴇʟɴᴇ 😭😭",
        "🍑\n🟨  😂\n🟨🟥🟥🟨\n     🟥🟥🟨\n     ⬛⬛ \n     ⬛⬛\nTery ma ki bund hi okhad li.",
        "𝘗𝘺𝘢𝘴 𝘭𝘢𝘨 𝘳𝘢𝘩𝘪 𝘵𝘦𝘳𝘪 𝘮𝘢𝘢 𝘬𝘰 𝘤𝘰𝘥 𝘬𝘦 𝘱𝘺𝘢𝘴 𝘣𝘶𝘫𝘩𝘢𝘶𝘯𝘨𝘢 🖕🏿😂🔥🙏🏿",
        "▶︎ •၊၊၊|။||။‌‌‌‌‌၊|• 0:60\n𝘋𝘦𝘬𝘩 𝘵𝘦𝘳𝘪 𝘣𝘦𝘩𝘦𝘯 ??𝘪 𝘤𝘩𝘪𝘬𝘩 😂😱🔥🙏🏿",
        "      ᴹᴱ:\n👆       🤬 ᴷᴬᴴᴬ ᴮᴴᴬᴳᵀᴵ ᴴᴬᴵ ᴿᴬᴺᴰᴵ\n  🐛💤👔🤳\n            ⛽  👢\n          ⚡👟\n       🎸    🌂\n      👢       👢     ᵀᴱᴿᴵ ᴹᴬᴬ:🏃‍♀‍➡️ᴹᵁᴶᴴᴱ ᴹᴬᵀ ᶜᴴᴼᴰᴼ",
        "🙌\n😛 ᴹᴱ:\n  |      👩 ᵀᴱᴿᴵ ᴹᴬᴬ:\n  |   8_/ 👐\n / \\  / \\\n  \"Take a look how i am chodunging your Mummy in ghodi pose 🗿\"",
        "../\\_/\\\n  ( • _ •)  \n  /    >🍆 \n\nʏᴇ ᴘᴀᴋᴀᴅᴏ ᴀᴘᴋɪ ᴍᴏᴍ ᴋᴏ ᴀᴘɴᴇ ᴄʜᴜᴛ ᴍᴇ ɢʜᴜssᴀ ɴᴇ ᴍᴇ ᴋᴀᴀᴍ ᴀʏᴇɴɢᴀ 🤗",
        "ㅤㅤ😎 ᴹᴱ:\n          |\\👐\n         / \\_\n━━━━━┓ ＼＼\n┓┓┓┓┓┃ᵀᴼᴴᴬᴿ ᴿᴬᴺᴰᴵ ᴹᴬᴬ:\n┓┓┓┓┓┃ ヽ😩ノ\n┓┓┓┓┓┃ 　 /　ᴼᴿᴵᴵ ᴬᴹᴹᴬ\n┓┓┓┓┓┃  ノ)　\n┓┓┓┓┓┃\n\nLE TERI MAA KO CHOD KAR FHEK DIA 🥸",
        "😎 ᴍᴀɪ:\nく|)へ\n   〉\n￣┗┓       ヾ😫ｼ ᴛᴇʀɪ ᴍᴀᴀ:\n         ┗┓   ヘ/    \n             ┗┓ノ\n                 ┗┓       ヾ😨ｼ ᴛᴇʀᴀ ʙᴀᴀᴘ:\n                      ┗┓   ヘ/\n                          ┗┓ノ\n                               ┗┓       ヾ😩ｼ ᴛᴇʀᴀ ᴄʜᴀᴄʜᴀ:\n                                   ┗┓   ヘ/    \n                                       ┗┓ノ\nᴅᴇᴋʜ ᴀɪsᴇ ʜɪ ʟᴀᴀᴛ ᴍᴀᴀʀ ᴋᴀʀ ʙʜᴀɢᴀᴜɴɢᴀ ᴛᴇʀᴇ ᴋʜᴀᴀɴᴅᴀɴ ᴋᴏ 🤫🤣",
        "╭👇 ͡ ͡° ͜   ͡ ͡°)╭👇 \n      \\   .   .\\\n        \\        \\\n         \\╰[ ]╯\\ \n          /   U   \\\n       👟       👟\n\nᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ᴍᴇʀᴀ ʟᴜɴᴅ ᴍᴜʙᴀʀᴀᴋ ʜᴏ 😝",
        "Once a man said: \n\"You deserve all the chudayi and teri maa ki chutt dhulayi, and this text proves it! You should be proud!\" 🕊️",
        "😏 ᴍᴀɪ:\n    | 👐💵\n    |//    💵\n    |          💸 ᴛᴇʀɪ ʀᴀɴᴅʏ ᴍᴀᴀ:\n   /\\            👯👯\n👟👟\n\nDᴇᴋʜ Kᴇsᴇ Tᴇʀɪ Mᴀᴀ Kᴏ Aᴘɴᴇ Pᴀɪsᴏ Sᴇ Rᴀɴᴅɪ Nᴀᴄʜ Kᴀʀᴡᴀ Rʜᴀ Hᴜ 🤙😎",
        "Loading your maa ki chudai video 😳\n\n■■■■■■■■□\n99%",
        "Sun दोस्त terko ye तीन चीजे कभी nahi भूलनी chaiye  😁👇🏻🤙🏿\n\n1 :- तेरी औकात\n2 :- तेरी बहन का फटा bhosda\n3 :- तेरी मां के भोसड़े में मेरा मूत",
        "this message could't be display because teri maa randy ey",
        ]


        fun_texts = [
        "तेरे मां के दूदू के बीच मेरा lund fas gaya oops 🤪（ ͜.🍆 ͜.）",
        "𝐓ᴇʀʏ 𝐁ʜᴇ𝐍 𝐊ᴇ ( ͜. ㅅ ͜. )🥛 ʏᴜᴍᴍʏ ",
        "𓂃☁︎ 𓂃𝐒ɪᴅᴇ 𝐇ᴀᴛ 𝐆ᴜʟᴀᴍ 𝐓ᴇʀʏ 𝐌ᴀᴀ 𝐊ᴏ 𝐂ʜᴏᴅɴᴇ  मेरी रेलगाड़ी आ रही .-‘🚂-‘.ᯓᡣ𐭩______ 𓂃☁︎ 𓂃",
        "˙✧˖°📷༘ ⋆｡° 𝐓ᴇʀʏ 𝐌ᴀ  𝐊ᴀ 𝐂ʜɪʟᴅ 𝐏ᴏʀɴ 𝐑ᴇᴄᴏʀᴅ 𝐇ᴏɢʏᴀ 𝐀ʙ 𝐓ᴏ 𝐒ɪᴅʜᴀ 𝐕ɪʀᴀʟ 𝐇ᴏɢᴀ 𝐘ᴇ ˙✧˖°📷༘ ⋆｡°",
        "𓂃✍︎ 𝑵ʏ 𝑵ʏ 𝑨ʙ 𝑲ᴜᴄʜ 𝑵ʏ 𝑯ᴏ 𝑺ᴋᴛᴀ 𝑻ᴇʀɪ  𝑪ᴜᴅᴀɪ 𝑲ɪ 𝑺ᴄʀɪᴘᴛ 𝑨ʙ 𝑳ᴇᴀᴋ 𝑯ᴏᴋᴇ 𝑯ʏ 𝑴ᴀɴᴇɢɪ 𓂃✍︎",
        "⋆⭒˚.⋆🔭 𝐒ʜᴜᴛ 𝐔ᴘ 𝐑ᴀɴᴅɪᴋᴇ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ɪ 𝐂ʜᴜᴅᴀɪ 𝐄ɴᴊᴏʏ 𝐊ʀ 𝐑ᴀʜᴀ 𝐓ᴇʟᴇ𝐒ᴄᴏᴘᴇ 𝐒ᴇ⋆⭒˚.⋆🔭",
        "तेरे मां के दूदू के बीच मेरा lund fas gaya oops 🤪（ ͜.🍆 ͜.）",
        "𝐓ᴇʀʏ 𝐁ʜᴇ𝐍 𝐊ᴇ ( ͜. ㅅ ͜. )🥛 ʏᴜᴍᴍʏ ",
        "𓂃☁︎ 𓂃𝐒ɪᴅᴇ 𝐇ᴀᴛ 𝐆ᴜʟᴀᴍ 𝐓ᴇʀʏ 𝐌ᴀᴀ 𝐊ᴏ 𝐂ʜᴏᴅɴᴇ  मेरी रेलगाड़ी आ रही .-‘🚂-‘.ᯓᡣ𐭩______ 𓂃☁︎ 𓂃",
        "˙✧˖°📷༘ ⋆｡° 𝐓ᴇʀʏ 𝐌ᴀ  𝐊ᴀ 𝐂ʜɪʟᴅ 𝐏ᴏʀɴ 𝐑ᴇᴄᴏʀᴅ 𝐇ᴏɢʏᴀ 𝐀ʙ 𝐓ᴏ 𝐒ɪᴅʜᴀ 𝐕ɪʀᴀʟ 𝐇ᴏɢᴀ 𝐘ᴇ ˙✧˖°📷༘ ⋆｡°",
        "𓂃✍︎ 𝑵ʏ 𝑵ʏ 𝑨ʙ 𝑲ᴜᴄʜ 𝑵ʏ 𝑯ᴏ 𝑺ᴋᴛᴀ 𝑻ᴇʀɪ  𝑪ᴜᴅᴀɪ 𝑲ɪ 𝑺ᴄʀɪᴘᴛ 𝑨ʙ 𝑳ᴇᴀᴋ 𝑯ᴏᴋᴇ 𝑯ʏ 𝑴ᴀɴᴇɢɪ 𓂃✍︎",
        "⋆⭒˚.⋆🔭 𝐒ʜᴜᴛ 𝐔ᴘ 𝐑ᴀɴᴅɪᴋᴇ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ɪ 𝐂ʜᴜᴅᴀɪ 𝐄ɴᴊᴏʏ 𝐊ʀ 𝐑ᴀʜᴀ 𝐓ᴇʟᴇ𝐒ᴄᴏᴘᴇ 𝐒ᴇ⋆⭒˚.⋆🔭",
        "तेरे मां के दूदू के बीच मेरा lund fas gaya oops 🤪（ ͜.🍆 ͜.）",
        "𝐓ᴇʀʏ 𝐁ʜᴇ𝐍 𝐊ᴇ ( ͜. ㅅ ͜. )🥛 ʏᴜᴍᴍʏ ",
        "𓂃☁︎ 𓂃𝐒ɪᴅᴇ 𝐇ᴀᴛ 𝐆ᴜʟᴀᴍ 𝐓ᴇʀʏ 𝐌ᴀᴀ 𝐊ᴏ 𝐂ʜᴏᴅɴᴇ  मेरी रेलगाड़ी आ रही .-‘🚂-‘.ᯓᡣ𐭩______ 𓂃☁︎ 𓂃",
        "˙✧˖°📷༘ ⋆｡° 𝐓ᴇʀʏ 𝐌ᴀ  𝐊ᴀ 𝐂ʜɪʟᴅ 𝐏ᴏʀɴ 𝐑ᴇᴄᴏʀᴅ 𝐇ᴏɢʏᴀ 𝐀ʙ 𝐓ᴏ 𝐒ɪᴅʜᴀ 𝐕ɪʀᴀʟ 𝐇ᴏɢᴀ 𝐘ᴇ ˙✧˖°📷༘ ⋆｡°",
        "𓂃✍︎ 𝑵ʏ 𝑵ʏ 𝑨ʙ 𝑲ᴜᴄʜ 𝑵ʏ 𝑯ᴏ 𝑺ᴋᴛᴀ 𝑻ᴇʀɪ  𝑪ᴜᴅᴀɪ 𝑲ɪ 𝑺ᴄʀɪᴘᴛ 𝑨ʙ 𝑳ᴇᴀᴋ 𝑯ᴏᴋᴇ 𝑯ʏ 𝑴ᴀɴᴇɢɪ 𓂃✍︎",
        "⋆⭒˚.⋆🔭 𝐒ʜᴜᴛ 𝐔ᴘ 𝐑ᴀɴᴅɪᴋᴇ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ɪ 𝐂ʜᴜᴅᴀɪ 𝐄ɴᴊᴏʏ 𝐊ʀ 𝐑ᴀʜᴀ 𝐓ᴇʟᴇ𝐒ᴄᴏᴘᴇ 𝐒ᴇ⋆⭒˚.⋆🔭"
        ]

        flag_texts = [
        "🇮🇳 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐈ɴᴅɪᴀ 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇮🇳",
        "🇯🇵 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐉ᴀᴘᴀɴ 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇯🇵",
        "🇺🇸 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐔𝐒𝐀 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇺🇸",
        "🇬🇧 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐔𝐊 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇬🇧",
        "🇰🇷 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐊ᴏʀᴇᴀ 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇰🇷",
        "🇩🇪 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐆ᴇʀᴍᴀɴʏ 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇩🇪",
        "🇫🇷 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐅ʀᴀɴᴄᴇ 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇫🇷",
        "🇮🇹 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐈ᴛᴀʟʏ 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇮🇹",
        "🇧🇷 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐁ʀᴀᴢɪʟ 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇧🇷",
        "🇨🇦 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐂ᴀɴᴀᴅᴀ 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇨🇦",
        ]

        heart_replies = [
        "𓂃˖˳·˖ ִֶָ ⋆❤️͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚❤️ ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆🧡͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚🧡 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆💛͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚💛 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆💚͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚💚 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆💙͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚💙 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆💜͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚💜 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆🖤͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚🖤 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆🤍͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚🤍 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆🤎͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚🤎 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆💖͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚💖 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆💗͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚💗 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆💓͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚💓 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆💞͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚💞 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆💕͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚💕 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆💘͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚💘 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆💝͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚💝 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆💟͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚💟 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆❣️͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚❣️ ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆❤️‍🔥͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚❤️‍🔥 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆❤️‍🩹͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚❤️‍🩹 ݁˖⭑.ᐟ",
        ]

        # ─── DEATHGOD REPLIES ────────────────────────────────────────────────────
        deathgod_replies = [
        "⋆｡ﾟ☁︎｡𝐂ʏᴜ 𝐑ᴇ मदरचोद  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के सामने 𝐅ʏᴛᴇʀ 𝐁ᴀɴᴇɢᴀ ⋆𓂃 ོ☼𓂃 😂🔥",
        "नहीं नहीं तेरी मां को 𝐒ɪʀғ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप चोद सकता है ִֶָ𓂃 ࣪ ִֶָ👑་༘࿐ sᴀᴍᴊʜᴀ ʀᴀɴᴅɪᴋᴇ ???",
        "तेरी मां का 𝐒ᴛʏʟɪsʜ भोसड़ा 😱",
        "𝑻𝒆𝒓𝒚 𝒎𝒂𝒂 𝒓𝒂𝒏𝒅𝒂𝒍 𝒉 𝒃𝒂𝒔 𝒃𝒂𝒂𝒕 𝒌𝒉𝒂𝒕𝒂𝒎 😡🔥",
        "सोच तेरी बहन को  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप का गुलाम चोद रहा 😎🔥",
        "Hello hello?? SAAS aarahi है? रण्डी पुत्र 🧘🏻",
        "Shut up रंडीके वरना दुनिया यही बोलेगी तेरी बहन  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  /\\~ 👑 बाप से सही chudi 🥵🔥",
        "ᴛᴜ ᴏʀ ᴛᴇʀɪ ᴍᴀᴀ ᴅᴏɴᴏ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के ʟɴᴅ sᴇ ᴋᴀʙʜɪ ᴜᴛʜ ɴʜɪ ᴘᴀʏᴇ 😂🔥",
        "🇮🇳𝐵𝐻𝐴𝑅𝐴𝑇 𝐻𝐴𝑀𝐴𝑅𝐴 𝐷𝐸𝑆𝐻 𝐻 𝐴𝑈𝑅 𝑈𝑆 𝐷𝐸𝑆𝐻 𝑀𝐸 तेरी मां घर घर जाके SHAMBHOG करती है ! 🛐",
        "⋆｡ﾟ☁︎｡𝐂ʏᴜ 𝐑ᴇ मदरचोद  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के सामने 𝐅ʏᴛᴇʀ 𝐁ᴀɴᴇɢᴀ ⋆𓂃 ོ☼𓂃 😂🔥",
        "नहीं नहीं तेरी मां को 𝐒ɪʀғ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप चोद सकता है ִֶָ𓂃 ࣪ ִֶָ👑་༘࿐ sᴀᴍᴊʜᴀ ʀᴀɴᴅɪᴋᴇ ???",
        "तेरी मां का 𝐒ᴛʏʟɪsʜ भोसड़ा 😱",
        "𝑻𝒆𝒓𝒚 𝒎𝒂𝒂 𝒓𝒂𝒏𝒅𝒂𝒍 𝒉 𝒃𝒂𝒔 𝒃𝒂𝒂𝒕 𝒌𝒉𝒂𝒕𝒂𝒎 😡🔥",
        "सोच तेरी बहन को  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप का गुलाम चोद रहा 😎🔥",
        "Hello hello?? saas aarahi है? रण्डी पुत्र 🧘🏻",
        "Shut up रंडीके वरना दुनिया यही बोलेगी तेरी बहन  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  /\\~ 👑 बाप से सही chudi 🥵🔥",
        "ᴛᴜ ᴏʀ ᴛᴇʀɪ ᴍᴀᴀ ᴅᴏɴᴏ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के ʟɴᴅ sᴇ ᴋᴀʙʜɪ ᴜᴛʜ ɴʜɪ ᴘᴀʏᴇ 😂🔥",
        "🇮🇳𝐵𝐻𝐴𝑅𝐴𝑇 𝐻𝐴𝑀𝐴𝑅𝐴 𝐷𝐸𝑆𝐻 𝐻 𝐴𝑈𝑅 𝑈𝑆 𝐷𝐸𝑆𝐻 𝑀𝐸 तेरी मां घर घर जाके SAMBHOG करती है ! 🛐",
        "⋆｡ﾟ☁︎｡𝐂ʏᴜ 𝐑ᴇ मदरचोद  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के सामने 𝐅ʏᴛᴇʀ 𝐁ᴀɴᴇɢᴀ ⋆𓂃 ོ☼𓂃 😂🔥",
        "नहीं नहीं तेरी मां को 𝐒ɪʀғ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप चोद सकता है ִֶָ𓂃 ࣪ ִֶָ👑་༘࿐ sᴀᴍᴊʜᴀ ʀᴀɴᴅɪᴋᴇ ???",
        "तेरी मां का 𝐒ᴛʏʟɪsʜ भोसड़ा 😱",
        "𝑻𝒆𝒓𝒚 𝒎𝒂𝒂 𝒓𝒂𝒏𝒅𝒂𝒍 𝒉 𝒃𝒂𝒔 𝒃𝒂𝒂𝒕 𝒌𝒉𝒂𝒕𝒂𝒎 😡🔥",
        "सोच तेरी बहन को  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप का गुलाम चोद रहा 😎🔥",
        "Hello hello?? SAAS aarahi है? रण्डी पुत्र 🧘🏻",
        "Shut up रंडीके वरना दुनिया यही बोलेगी तेरी बहन  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  /\\~ 👑 बाप से सही chudi 🥵🔥",
        "ᴛᴜ ᴏʀ ᴛᴇʀɪ ᴍᴀᴀ ᴅᴏɴᴏ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के ʟɴᴅ sᴇ ᴋᴀʙʜɪ ᴜᴛʜ ɴʜɪ ᴘᴀʏᴇ 😂🔥",
        "🇮🇳𝐵𝐻𝐴𝑅𝐴𝑇 𝐻𝐴𝑀𝐴𝑅𝐴 𝐷𝐸𝑆𝐻 𝐻 𝐴𝑈𝑅 𝑈𝑆 𝐷𝐸𝑆𝐻 𝑀𝐸 तेरी मां घर घर जाके SAMBHOG करती है ! 🛐",
        "⋆｡ﾟ☁︎｡𝐂ʏᴜ 𝐑ᴇ मदरचोद  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के सामने 𝐅ʏᴛᴇʀ 𝐁ᴀɴᴇɢᴀ ⋆𓂃 ོ☼𓂃 😂🔥",
        "नहीं नहीं तेरी मां को 𝐒ɪʀғ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप चोद सकता है ִֶָ𓂃 ࣪ ִֶָ👑་༘࿐ sᴀᴍᴊʜᴀ ʀᴀɴᴅɪᴋᴇ ???",
        "तेरी मां का 𝐒ᴛʏʟɪsʜ भोसड़ा 😱",
        "𝑻𝒆𝒓𝒚 𝒎𝒂𝒂 𝒓𝒂𝒏𝒅𝒂𝒍 𝒉 𝒃𝒂𝒔 𝒃𝒂𝒂𝒕 𝒌𝒉𝒂𝒕𝒂𝒎 😡🔥",
        "सोच तेरी बहन को  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप का गुलाम चोद रहा 😎🔥",
        "Hello hello?? SAAS aarahi है? रण्डी पुत्र 🧘🏻",
        "Shut up रंडीके वरना दुनिया यही बोलेगी तेरी बहन  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  /\\~ 👑 बाप से सही chudi 🥵🔥",
        "ᴛᴜ ᴏʀ ᴛᴇʀɪ ᴍᴀᴀ ᴅᴏɴᴏ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  बाप के ʟɴᴅ sᴇ ᴋᴀʙʜɪ ᴜᴛʜ ɴʜɪ ᴘᴀʏᴇ 😂🔥",
        "𝙃𝙀𝙔 𝙂𝙊𝙊𝙂𝙇𝙀 𝙁𝙐𝘾𝙆 𝙃𝙄𝙎 𝙈𝙊𝙈 𝙋𝙍𝙊𝙋𝙀𝙍𝙇𝙔",
        "𝙃𝙀𝙔 𝙂𝙊𝙊𝙂𝙇𝙀 𝘼𝙎𝙆 𝙃𝙄𝙈 𝙏𝙊 𝘾𝙊𝙑𝙀𝙍 𝙃𝙄𝙎 𝙈𝙊𝙈'𝙎 𝘼𝙎𝙎",
        "𝙃𝙀𝙔 𝙂𝙊𝙊𝙂𝙇𝙀 𝙁𝙄𝙓 𝙈𝙔 𝘼‌𝙋𝙋𝙊𝙄𝙉𝙏𝙈𝙀𝙉𝙏 𝙒𝙄𝙏𝙃 𝙃𝙄𝙎 𝙎𝙄𝙎",
        "𝙃𝙀𝙔 𝙂𝙊𝙊𝙂𝙇𝙀 𝙁𝙐𝘾𝙆 𝘼𝙉𝘿 𝙏𝙃𝙍𝙊𝙒 𝙏𝙃𝙄𝙎 𝙂𝘼𝙍𝙀𝙀𝘽 𝙎𝙊𝙉",
        "𝙃𝙀𝙔 𝙂𝙊𝙊𝙂𝙇𝙀 𝘿𝙊 𝙉𝙊𝙏 𝙎𝙏𝙊𝙋 𝙁𝙐𝘾𝙆𝙄𝙉𝙂 𝙈𝙔 𝙂𝙐𝙇𝘼‌𝙈",
        "𝙂𝙀𝙈𝙄𝙉𝙄 𝙎𝘼𝙄𝘿  𝙄𝙎 𝙍𝙉𝘿𝙔 𝙋𝙐𝙏𝙍𝘼",
        "𝙋𝙀𝙍𝙋𝙇𝙀𝙓𝙄𝙏𝙔 𝙎𝘼𝙄𝘿 This 𝙄𝙎 𝙂𝙐𝙇𝘼𝙈",
        "𝙂𝙍𝙊𝙆 𝘼𝙄 𝙎𝘼𝙄𝘿 𝙄𝙎 𝙂𝘼𝙍𝙀𝙀𝘽",
        "𝘽𝙊𝙏 𝙎𝘼‌𝙄𝘿  𝙄𝙎 𝘾𝙃𝙐𝘿𝘼𝙆𝘼𝘿",
        "𝙈𝙊𝘿𝙄 𝙎𝘼‌𝙄𝘿  𝙄𝙎 𝙋𝙊𝙇𝙀 𝘿𝘼𝙉𝘾𝙀𝙍",
        "𝙏𝙍𝙐𝙈𝙋 𝙎𝘼𝙄𝘿 THis 𝙄𝙎 𝘽𝙇𝙊𝙊𝘿Y 𝙈𝙊𝙏𝙃𝙀𝙍𝙁*\"𝘾𝙆𝙀𝙍",
        "𝗧𝗢𝗛𝗔𝗥 𝗠𝗨𝗠𝗠𝗬 𝗞𝗜 𝗖𝗛𝗨𝗨‌𝗧 𝗠𝗘𝗜 𝗣𝗨𝗥𝗜 𝗞𝗜 𝗣𝗨𝗥𝗜 𝗞𝗜𝗡𝗚𝗙𝗜𝗦𝗛𝗘𝗥 𝗞𝗜 𝗕𝗢𝗧𝗧𝗟𝗘 𝗗𝗔𝗟 𝗞𝗘 𝗧𝗢𝗗 𝗗𝗨𝗡𝗚𝗔 𝗔𝗡𝗗𝗘𝗥 𝗛𝗜 😱😂🤩",
        "𝐓𝐄𝐑𝐈 𝐌𝐀𝐀 𝐊𝐈 𝐂𝐇𝐔𝐓 𝐌𝐄 ✋ 𝐇𝐀𝐓𝐓𝐇 𝐃𝐀𝐋𝐊𝐄 👶 𝐁𝐀𝐂𝐂𝐇𝐄 𝐍𝐈𝐊𝐀𝐋 𝐃𝐔𝐍𝐆𝐀 😍",
        "𝐓𝐄𝐑𝐀 𝐏𝐄𝐇𝐋𝐀 𝐁𝐀𝐀𝐏 𝐇𝐔 𝐌𝐀𝐃𝐀𝐑𝐂𝐇𝐎𝐃",
        "𝗧𝗘𝗥𝗜 𝗠𝗨𝗠𝗠𝗬 𝗞𝗘 𝗦𝗔𝗔𝗧𝗛 𝗟𝗨𝗗𝗼 𝗞𝗛𝗘𝗟𝗧𝗘 𝗞𝗛𝗘𝗟𝗧𝗘 𝗨𝗦𝗞𝗘 𝗠𝗨𝗛 𝗠𝗘 𝗔𝗣𝗡𝗔 𝗟𝗢𝗗𝗔 𝗗𝗘 𝗗𝗨𝗡𝗚𝗔☝🏻☝🏻😬",
        "𝗧𝗘𝗥𝗜 𝗠𝗔‌𝗔‌ 𝗞𝗜 𝗖𝗛𝗨𝗨‌𝗧 𝗠𝗘 𝗦𝗨𝗧𝗟𝗜 𝗕𝗢𝗠𝗕 𝗙𝗢𝗗 𝗗𝗨𝗡𝗚𝗔 𝗧𝗘𝗥𝗜 𝗠𝗔‌𝗔‌ 𝗞𝗜 𝗝𝗛𝗔𝗔𝗧𝗘 𝗝𝗔𝗟 𝗞𝗘 𝗞𝗛𝗔𝗔𝗞 𝗛𝗢 𝗝𝗔𝗬𝗘𝗚𝗜💣🔥",
        "𝐓𝐄𝐑𝐈 𝐕𝐀𝐇𝐄𝐈𝐍 𝐊𝐎 𝐀𝐏𝐍𝐄 𝐋𝐔𝐍𝐃 𝐏𝐑 𝐈𝐓𝐍𝐀 𝐉𝐇𝐔𝐋𝐀𝐀𝐔𝐍𝐆𝐀 𝐊𝐈 𝐉𝐇𝐔𝐋𝐓𝐄 𝐉𝐇𝐔𝐋𝐓𝐄 𝐇𝐈 𝐁𝐀𝐂𝐇𝐀 𝐏𝐀𝐈𝐃𝐀 𝐊𝐑 𝐃𝐄𝐆𝐈 💦💋",
        "𝐆𝐀𝐋𝐈 𝐆𝐀𝐋𝐈 𝐌𝐄 𝐑𝐄𝐇𝐓𝐀 𝐇𝐄 𝐒𝐀𝐍𝐃 𝐓𝐄𝐑𝐈 𝐌𝐀𝐀𝐊𝐎 𝐂𝐇𝐎𝐃 𝐃𝐀𝐋𝐀 𝐎𝐑 𝐁𝐀𝐍𝐀 𝐃𝐈𝐀 𝐑𝐀𝐍𝐃 🤤🤣",
        "𝐒𝐀𝐁 𝐁𝐎𝐋𝐓𝐄 𝐌𝐔𝐉𝐇𝐊𝐎 𝐏𝐀𝐏𝐀 𝐊𝐘𝐎𝐔𝐍𝐊𝐈 𝐌𝐄𝐍𝐄 𝐁𝐀𝐍𝐀𝐃𝐈𝐀 𝐓𝐄𝐑𝐈 𝐌𝐀𝐀𝐊𝐎 𝐏𝐑𝐄𝐆𝐍𝐄𝐍𝐓 🤣🤣",
        "𝙏𝙀𝙍𝙄 𝘽𝙀𝙃𝙀𝙉 𝙇𝙀𝙏𝙄 𝙈𝙀𝙍𝙄 𝙇𝙐𝙉𝘿 𝘽𝘼𝘿𝙀 𝙈𝘼𝙎𝙏𝙄 𝙎𝙀 𝙏𝙀𝙍𝙄 𝘽𝙀𝙃𝙀𝙉 𝙆𝙊 𝙈𝙀𝙉𝙀 𝘾𝙃𝙊𝘿 𝘿𝘼𝙇𝘼 𝘽𝙊𝙃𝙊𝙏 𝙎𝘼𝙎𝙏𝙀 𝙎𝙀",
        "𝗧𝗘𝗥𝗜 𝗠𝗔‌𝗔‌ 𝗞𝗜 𝗖𝗛𝗨𝗨‌𝗧 𝗠𝗘 𝗖𝗛𝗔𝗡𝗚𝗘𝗦 𝗖𝗢𝗠𝗠𝗜𝗧 𝗞𝗥𝗨𝗚𝗔 𝗙𝗜𝗥 𝗧𝗘𝗥𝗜 𝗕𝗛𝗘𝗘𝗡 𝗞𝗜 𝗖𝗛𝗨𝗨‌𝗧 𝗔𝗨𝗧𝗢𝗠𝗔𝗧𝗜𝗖𝗔𝗟𝗟𝗬 𝗨𝗣𝗗𝗔𝗧𝗘 𝗛𝗢𝗝𝗔𝗔𝗬𝗘𝗚𝗜🤖🙏🤔",
        "𝐓𝐄𝐑𝐈 𝐌𝐀𝐀𝐀𝐊𝐈 𝐂𝐇𝐔𝐃𝐀𝐈 𝐊𝐎 𝐏𝐎𝐑𝐍𝐇𝐔𝐁.𝐂𝐎𝐌 𝐏𝐄 𝐔𝐏𝐋𝐎𝐀𝐃 𝐊𝐀𝐑𝐃𝐔𝐍𝐆𝐀 𝐒𝐔𝐀𝐑 𝐊𝐄 𝐂𝐇𝐎𝐃𝐄 🤣💋💦",
        "𝐓𝐄𝐑𝐈 𝐁𝐀𝐇𝐄𝐍 𝐊𝐈 𝐆𝐀𝐀𝐍𝐃 𝐌𝐄𝐈 𝐎𝐍𝐄𝐏𝐋𝐔𝐒 𝐊𝐀 𝐖𝐑𝐀𝐏 𝐂𝐇𝐀𝐑𝐆𝐄𝐑 𝟑𝟎𝐖 𝐇𝐈𝐆𝐇 𝐏𝐎𝐖𝐄𝐑 💥😂😎",
        "𝐓𝐔𝐉𝐇𝐄 𝐀𝐁 𝐓𝐀𝐊 𝐍𝐀𝐇𝐈 𝐒𝐌𝐉𝐇 𝐀𝐘𝐀 𝐊𝐈 𝐌𝐀𝐈 𝐇𝐈 𝐇𝐔 𝐓𝐔𝐉𝐇𝐄 𝐏𝐀𝐈𝐃𝐀 𝐊𝐀𝐑𝐍𝐄 𝐖𝐀𝐋𝐀 𝐁𝐇𝐎𝐒𝐃𝐈𝐊𝐄𝐄 𝐀𝐏𝐍𝐈 𝐌𝐀𝐀 𝐒𝐄 𝐏𝐔𝐂𝐇 𝐑𝐀𝐍𝐃𝐈 𝐊𝐄 𝐁𝐀𝐂𝐇𝐄𝐄𝐄𝐄 🤩👊👤😍",
        "𝐓𝐄𝐑𝐈 𝐁𝐀𝐇𝐄𝐍 𝐊𝐈 𝐂𝐇𝐔𝐓 𝐌𝐄𝐈 𝐀𝐏𝐏𝐋𝐄 𝐊𝐀 𝟏𝟖𝐖 𝐖𝐀𝐋𝐀 𝐂𝐇𝐀𝐑𝐆𝐄𝐑 🔥🤩",
        "𝗧𝗘𝗥𝗜 𝗠𝗔‌𝗔‌ 𝗞𝗢 𝗜𝗧𝗡𝗔 𝗖𝗛𝗢𝗗𝗨𝗡𝗚𝗔 𝗞𝗜 𝗦𝗔𝗣𝗡𝗘 𝗠𝗘𝗜 𝗕𝗛𝗜 𝗠𝗘𝗥𝗜 𝗖𝗛𝗨𝗗𝗔𝗜 𝗬𝗔𝗔𝗗 𝗞𝗔𝗥𝗘𝗚𝗜 𝗥Æ𝗡𝗗𝗜 🥳😍👊💥",
        "𝙋𝘼𝙋𝘼 𝙆𝙄 𝙎𝙋𝙀𝙀𝘿 𝙈𝙏𝘾𝙃 𝙉𝙃𝙄 𝙃𝙊 𝙍𝙃𝙄 𝙆𝙔𝘼",
        "𝙆𝙄𝙏𝙉𝙄 𝘾𝙃𝙊𝘿𝙐 𝙏𝙀𝙍𝙄 𝙈𝘼 𝘼𝘽 𝙊𝙍..",
        "𝗧𝗘𝗥𝗜 𝗠𝗔𝗨𝗦𝗜 𝗞𝗘 𝗕𝗛𝗢𝗦𝗗𝗘 𝗠𝗘𝗜 𝗜𝗡𝗗𝗜𝗔𝗡 𝗥𝗔𝗜𝗟𝗪𝗔𝗬 🚂💥😂",
        "𝙆𝙄𝙏𝙉𝙄 𝙂𝙇𝙄𝙔𝘼 𝙋𝘿𝙒𝙀𝙂𝘼 𝘼𝙋𝙉𝙄 𝙈𝘼 𝙆𝙊",
        "𝗧𝗘𝗥𝗜 𝗜𝗧𝗘𝗠 𝗞𝗜 𝗚𝗔𝗔𝗡𝗗 𝗠𝗘 𝗟𝗨𝗡𝗗 𝗗𝗔𝗔𝗟𝗞𝗘,𝗧𝗘𝗥𝗘 𝗝𝗔𝗜𝗦𝗔 𝗘𝗞 𝗢𝗥 𝗡𝗜𝗞𝗔𝗔𝗟 𝗗𝗨𝗡𝗚𝗔 𝗠𝗔‌𝗔‌𝗗𝗔𝗥𝗖𝗛Ø𝗗🤘🏻🙌🏻☠️",
        "2 𝙍𝙐𝙋𝘼𝙔 𝙆𝙄 𝙋𝙀𝙋𝙎𝙄 𝙏𝙀𝙍𝙄 𝙈𝙐𝙈𝙈𝙔 𝙎𝘼𝘽𝙎𝙀 𝙎𝙀𝙓𝙔 💋💦",
        "🇮🇳𝐵𝐻𝐴𝑅𝐴𝑇 𝐻𝐴𝑀𝐴𝑅𝐴 𝐷𝐸𝑆𝐻 𝐻 𝐴𝑈𝑅 𝑈𝑆 𝐷𝐸𝑆𝐻 𝑀𝐸 तेरी मां घर घर जाके SAMBHOG करती है ! 🛐"
        "Baap bhi bnale muje rndike",
        "Tera baap randibaaz ey yaad ey tujhe",
        "Tu apni Maa cuda na tympass",
        "Oye unfunny swipe mtt kr",
        "Oh hello bihari tera baap bihari or tu v bihari aaukat me rha kr.",
        "Oyy kinner tujhe gc me aane ki permission kisne di.",
        "Cudke dikha",
        "Cudke dikha ek baar.",
        "Sun sun ma cuda.",
        "Teri maca bhosda.",
        "Oye choti jati ke tmr.",
        "Ky? jldi likh kidde.",
        "Bihari com gang ke baap ko tag crega tu",
        "Mujhe cya tu bihari ey tmkc bs",
        "Jaldi se randibaaz papa bol",
        "Side hoja bihari tery maa cud gai ab",
        "Hye pgl bhg mat ache se cud",
        "bhg ny randyke tu ajj",
        "Hye pgl ke bche bhag mat",
        "Hye dur hatt madchod ke bache",
        "koi bat ny tery maa randy ey esliye maf cr rha hu tujhe",
        "koi baat ny maa chudwa apni tu mafi de dunga",
        "Ache se maa chudwa apni tu mafi mil jayegi tujhe",
        "apni ma mat chuda muje swipe crke",
        "Ache se apni ma cudwa tu swipe crke",
        "Fr bolna na ki cudwa le apni ma swipe crke",
        "Cya hua ma cud gyi tery",
        "pr kese cud gyi tery ma",
        "mujhe pta tha ma cud gai tery",
        "mey ny manta ma cud gyi tery",
        "teri ma rndy",
        "lode se utr mc",
        "lun mt chus mera",
        "nikal madarchd",
        "chup oye gashti k bache",
        "makichut teri",
        "chup rndyke",
        "ma rndy teri",
        "teri ma k hath todh k tere baap k muh me fasadunga randyke",
        "leave le tu rndyke pasand nai aya meko",
        "leave le tu randyke ider se",
        "Leave le jldi se wrna ma chud gai tery",
        "Leave ny lega maa randy tery",
        "Smjh bat maa randy ey tery leave le",
        "fast leave le kamjor randyke",
        "tuto chup rndyk",
        "oy hijde khana kha ke aa kamzor",
        "teri mako ily rey🌚😂",
        "chup chap chud tmkc",
        "chupchap maa chudwa apni tu",
        "shi se maa chudwa apni tu chupchap",
        "fr se maa chudwa tu apni chupchap",
        "shi se likh wrna ma chud gai tery",
        "ma cyu chud gai tery chupchap",
        "proof cr maa chud gyi tery",
        "proof ey tery maa randy ey",
        "proof ho chuka maa randy tery",
        "Chup chillar",
        "chup chup maa k bosda tery",
        "oy hijde khana kha ke aa kamzor",
        "chup madarchod ?",
        "Ab tk cud gyi hogi tery maa ?",
        "ny ny me kuch ny janta bs teri ma rndy ey",
        "Sbse phele apni maa ko bol chudna kaam kre",
        "Yaha bhi chuda tu rndyce pille",
        "terimakabosda",
        "teri to bhen cudegi",
        "chup rndyke tommy",
        "nikal madarchd cudke yha se",
        "coz teri ma andhi randi he",
        "nyto baap bol mujhe",
        "nyny teri maa hogi rndii jo chudwati jogi",
        "try ammi ce bhosde me emoji dal mc",
        "cya ? chmr chud gya cya ?",
        "tm chudri hogi frrto",
        "cya ? kb ? pgl ey cya rndkek",
        "cya sch mey pgl ey cya tu randyke cudwa li tune apni ma",
        "itna sch ny bol ma chud gai tery",
        "sch mey pgl ey tu apni ma cudwa lia mere sth",
        "mtlb tmr",
        "nyto",
        "pura likh mc",
        "tmr frrto",
        "oh ok cudle fir",
        "teri maa ka damad",
        "cya ? ache se likhe pehle rndikebache",
        "nyto teri maa chodne me vyast hu",
        "nyto pgl ey cya kuch bi",
        "oyee cya ? chud gya ?",
        "chud mt hss",
        "yur rndii mom",
        "are sbki maa rndii or teri bi",
        "are idar cudle ek baar",
        "tri maa ci trh",
        "ek line me tmr",
        "Q",
        "ocy ab chudle",
        "pehele teri maa chodu",
        "nyto",
        "q ?",
        "hyyy chud ke dika ek baar",
        "oyee sun dost tmr",
        "bhag ja raand maaf crr dunga",
        "oyee pgl rndii idar aa",
        "cya tmr frrto",
        "oyee idar aake chud le chmr",
        "nyto aese hi cud",
        "oyee hyy aise hi cud lena",
        "or chud le",
        "chud ke dika or",
        "hyy chudo na",
        "chudo mt bhag jao",
        "byyee hyy cya ?",
        "Qchud q rhe ho ?",
        "pgl ey cya mc",
        "chud mt",
        "cya pgl rndii idar aa",
        "teri ammi ce bhosde me chappal",
        "oyee idar aa mc",
        "kmzror ey cya rndiek",
        "cya likh rha ?",
        "chud tha cya ?",
        "oyee slide leke baat crmc",
        "idar a teri maa chodu",
        "oyee cp mt crr chudle",
        "oyee hyy chud ke dika",
        "idar aa try ma schofu khachar khachar",
        "idar aa ja mc",
        "hyy idar aake chudle",
        "oyee kmzor mc idar aa",
        "ye cya tmr",
        "oyee ny cp ny crr",
        "oyee pgl mt crr",
        "cudle aram se mc",
        "pgl ey cya rndiek",
        "cp crce chudega !",
        "baap ? mc mera coi ma baap ny ey mai upar se rocket pe beth ce bss teri ma chodne aya hu",
        "Chota likh rndi k bache",
        "Chota likha wrna try ma rndy",
        "Try ma baka codega",
        "Tmkc main burf",
        "Bhikari ki jhat ma cuda le",
        "Chodke tery ma marjayegi",
        "Tmkc main Mount Everest",
        "Muh mey lega lund mera",
        "Hijde ki jhat chup wrna try ma rndi",
        "Menu ny pta tery ma randy",
        "Menu ki pta ma randy tery",
        "Menu pta maa cud gai tery",
        "Menu sb pta ma randy ey tery",
        "Menu pr tery ma randy",
        "Randy maa tery menu pta",
        "Tenu or menu pta ey maa randy tery",
        "Bs bs maa cudwa apni",
        "Bs bs ma randy tery thnkss",
        "Bs bs chudwa lia tu apni maa",
        "Bs bs kamjor maa randy tery",
        "Smjh gya apni ma cudwa le ab",
        "smjh gya tery maa randy ey",
        "smjh gya tu sabit kr maa randy tery",
        "Cya hua ma cudwa tu apni",
        "Easy maa cudwa le apni tu",
        "Easy w8 ma chudwa le apni ab",
        "Sans ari ha ky teri maa chudgi ajj",
        "Teri maa ko bina sanss lete hue chodunga",
        "chup randike kamjor",
        "apni ma normie cudwa le tu",
        "fr cya normie ma cud gai tery",
        "bas thek tery ma randy",
        "bas thek tery maa cud gyi",
        "kamjor thi tery ma esliye cud gai",
        "Mai sb janta ma cud gai tery",
        "chl chl ht tery maa cud gyi",
        "fr kaise cud gyi maa tery",
        "maa tery randy ey",
        "bas tery maa randy ey",
        "fr randy ma tery ey",
        "Kamjor ma ka bcha tu randyke",
        "bhot gndi cud gai maa tery",
        "pr kaise maa cud gai tery itna gnda",
        "mujhe cya bta rha maa randy tery",
        "mujhe cya pta ma cud gyi tery",
        "fir mujhe ny pta maa cud gai tery",
        "pta ny kon cod dia tery maa ko",
        "ruk aaya tery ma codke",
        "wait cr tery maa cod rha hu",
        "wait cr rabdyke maa cud rhi ey tery",
        "wait kr smjh rha tery ma codke",
        "wait le thoda chodne de tery mako",
        "ruk ja aand rkh dunga tery make liye",
        "tery maa famous randy ey",
        "maan lia mene maa randy sali tery",
        "maan lia maa cud gai tery",
        "shant beth randyke maa chudwa tu apni",
        "shant bethke chudwa le apni mako tu",
        "fr se shant Beth tu cud ab randyke yha",
        "mere smjh ny aya maa randy tery",
        "Le केला Kha tu madarchod",
        "Hye tery ma cud gyi cya",
        "hye tery maa mar gai cya",
        "Hye sch bta com cod dia tery mako",
        "Chl chod dia teri maa ko smjhle",
        "Baki koi dikkat ny tery maa randy ey",
        "baki sb jante ey ki maa chuddkad ey tery",
        "mujhe cya pta tha tery maa cudne wli ey",
        "pr mei kaise jnta tery ma ko koi chod dia",
        "pr mera vi manna shi tha maa chud gai tery",
        "pr wo glt ny tery maa randy ey",
        "pr wo shi ey tery maa chuddkad ey",
        "pr kaise kia maa chud gai tery omfoo",
        "bur cheer dunga tri ma ka",
        "teri ma ke dil me loda marke uski dhadkan rok dunga",
        "lulle kha tri makabhosda",
        "tri bhn ki bhosdi beta",
        "tri ma rndi baat khtm",
        "Sun ek maze ki baat batao kya teri maa randy ey"
        "codu codu mako tery",
        "aj cud gai tery maa oye",
        "sun sun randy make bache tu",
        "kilas ny randyke",
        "mujhe cya pta tery bhen cud gai",
        "pr pr cya hote ey tmkc",
        "tmcl sunle",
        "moot du tery maki chut mey",
        "bhgny cudke dikha fr",
        "fr se cudle tu",
        "ye vi shi ey tery mkc bs",
        "aj kuch ny ma cudwa tu apni",
        "try kr mera lund chuske",
        "tormakibur sun",
        "tor maki fuddi oye",
        "Haye Haye tery ma cud gai",
        "oye lundke pasine..",
        "kutte ke tatte sun",
        "kutta jaisa cud rha tu",
        "Muh mei le mera..",
        "jhaat ke pissu sun tmkc",
        "Hahahha ma cud gai tery",
        "weak tatte uth",
        "weak ey tu cud rha",
        "weak ache se cud tu",
        "weak tery ma cud rhi dekh",
        "week tery ma cud gai ab",
        "mujhe ny rok tu weak ey",
        "chup hizde",
        "okat ny meri ma cudwa tu apni",
        "lun lega tery maki gand mei ?",
        "tery maki bachi codu..",
        "tery bhen ki chut aj fad du",
        "speed lekr aa cudke dikha",
        "speed ny tere andr weak prosn",
        "ugly randyke chup",
        "makafuddatery",
        "tera baap ko tag kr..?",
        "ache se tag kr randibaaz bhagwn ko..",
        "cudke pgl ny ho tu",
        "cudke pgl ho rha tu kid",
        "ma to cud gai tery hawabzi cr..",
        "bs ma codni ey tery",
        "town mei cud tery mako lekr",
        "tery ma sexy ko bej - randibaaz bhgwn pe",
        "speed pkd cp ny kr",
        "Try ma rendy",
        "Bhkk cud",
        "tey maa rndi",
        "tery behen randi",
        "Cud ja",
        "tery didi rndi",
        "Slow",
        "teri Maiya ciodu",
        "Bhag?",
        "Bhak cud",
        "Tma codu",
        "Slow",
        "Slow firse",
        "Cudgrib",
        "Try ma dou",
        "tbkc codu",
        "Net on off wali rndy",
        "Oye try ma codu",
        "Idhar aake cud chup chaap",
        "tbkc mrdu",
        "oi maake lodee",
        "randyke beej",
        "tmkc chodu",
        "suar ke beej",
        "net off on kr randyke ladke",
        "Try ma cudi kese",
        "Chup slow madharcod",
        "tbkc codu kr msg delete",
        "oi suar ke ladke",
        "tmkc fufi",
        "tery didi chudi",
        "tmkc dikha",
        "Cud ab",
        "randyke cud",
        "Bhak cud",
        "cudle tbkc mru",
        "tmkl cudle grib",
        "tery behen vesiyaa rndi",
        "Itna gnda chuda tu firse net on off",
        "grib ke bete",
        "Bhag ja lode tmkc maru dunga",
        "tbkc mrdungaa",
        "bhag tmkc",
        "bhag tbkc",
        "tbkc mey cp",
        "cp tbkc mehh",
        "cp tmkl meh",
        "cp bol randyke",
        "Abe cp bol randyke",
        "double send ko cp tmkc codu",
        "tbkc me cp cod dunga Aaj mehh",
        "ht tbkc dalal ke bete.",
        "Rndy jldi jldi cudq tryma",
        "Para likhega..",
        "Tra rndhbhak",
        "Lagdi ke ladce cp bol",
        "cp bol lagdi ke bete..",
        "cudke cp bol",
        "bhikari lund chus mera.",
        "Low level cp cr",
        "cp bol low level weak",
        "mere lund pe ey tu hijde",
        "free cudwa tery mako",
        "Free mey cud tu randyke"
        "speed ny weak tatte terme",
        "kitni br cudwayega terymako",
        "lund le randibaaz bapka",
        "lun cus jaldi se randibaaz bapka",
        "koi ny dekh rha cudle tu",
        "cudle betichod ache se",
        "maki chut tery bs yehi janta mey",
        "cp bolega to tmkc",
        "wrna tery ma cud jayegi",
        "slow ey tu kid",
        "jldi likh..tmkc",
        "jldi likh..randce tu",
        "tym se phle cudke dikha",
        "tym hoga tery maa cudwa",
        "ma cud gai tery tym se phle",
        "uth randce ke ldke",
        "macabosdatery",
        "con kb cod dia mako tery",
        "koi hoga tml",
        "machar cudle tu",
        "menu tery mako codna se",
        "tery mako bol mujhe cod de",
        "bs mey tery ma se cudna chta hu",
        "Eww maka lode uth",
        "Meow cr tery mako codu",
        "lund rkh dia tery make fude pe",
        "mera lund ke bal uth",
        "kidee Zinda ho",
        "mar ny kidde type kr",
        "chup bkl",
        "bc tery maki chut",
        "mc randyke likh fast",
        "fast likh randyke",
        "fast likh kamzor"
        "tery maki chut claim crwa",
        "awz niche randce ke bche",
        "sawal ny puch tery makabosda",
        "fyter bnega lagde madrchod",
        "oye kaale ro ke dikha",
        "oye kaale roo ny",
        "short ny cud tu bina ruke",
        "short ny cud tu apni mako lekr",
        "tery make sth tery bhen vi cudwa le",
        "tery make sth tery didi vi cud gai",
        "Chat fyter bnega randce codu tery mako",
        "bol randibaaz daddy ey",
        "bullyx randyke uth",
        "mar marke cud rha tu",
        "or tery ma marke cud gai"
        "Jaldi likh rndyke bej",
        "Or bda likh tmc",
        "Or bda 2 line wla likh tmkc",
        "Or bda oye likh tml",
        "Teri maa ka bur",
        "Oye keede",
        "Randi ke ladke",
        "Jaldi likh teri behen chodu",
        "Mkl uth randi ke bacche",
        "Teri nani meri maal",
        "Tej likh randce",
        "Oye maake lode mrenga",
        "Teri maa chody",
        "Teri Maiya ki gand",
        "Tery dadi ka fudda",
        "Mkl uth behencod",
        "Teri maa ki bur de",
        "Tery maa ka fudda me lauda",
        "Teri maa chudva",
        "Randi ke bete mar gaya",
        "Teri maa ki chut mru",
        "Jalid kr spam",
        "Mc spam rokenga",
        "Teri maaki chut spam kr",
        "spam kr.maake lode",
        "Randyke chode spam kr wrna cud tu",
        "Spam kr kid",
        "Noob teri maa chodu",
        "Rndyke bete mar mat tu",
        "Noob jaldi likh wrna tery maa rand",
        "cud gai maa tery noob",
        "uth randyke noob",
        "chl cudke dikha noob",
        "jldi typ cr noob halke",
        "cud ke pgl ny ho noob",
        "cud cud ke rand bnja tu noob",
        "makichut tery noob",
        "ganda cyu cud rha tu ?",
        "itna gnda ny cud ache se cud",
        "Maan le cud gya tu sun bat ab",
        "makafudda fat gya tery ruk"
        "BAAP BHI BNALE MUJE RNDIKE",
        "TERA BAAP RANDIBAAZ EY YAAD EY TUJHE",
        "TU APNI MAA CUDA NA TYMPASS",
        "OYE UNFUNNY SWIPE MTT KR",
        "OH HELLO BIHARI TERA BAAP BIHARI OR TU V BIHARI AAUKAT ME RHA KR.",
        "OYY KINNER TUJHE GC ME AANE KI PERMISSION KISNE DI.",
        "CUDKE DIKHA",
        "CUDKE DIKHA EK BAAR.",
        "SUN SUN MA CUDA.",
        "TERI MACA BHOSDA.",
        "OYE CHOTI JATI KE TMR.",
        "KY? JLDI LIKH KIDDE.",
        "BIHARI COM GANG KE BAAP KO TAG CREGA TU",
        "MUJHE CYA TU BIHARI EY TMKC BS",
        "JALDI SE RANDIBAAZ PAPA BOL",
        "SIDE HOJA BIHARI TERY MAA CUD GAI AB",
        "HYE PGL BHG MAT ACHE SE CUD",
        "BHG NY RANDYKE TU AJJ",
        "HYE PGL KE BCHE BHAG MAT",
        "HYE DUR HATT MADCHOD KE BACHE",
        "KOI BAT NY TERY MAA RANDY EY ESLIYE MAF CR RHA HU TUJHE",
        "KOI BAAT NY MAA CHUDWA APNI TU MAFI DE DUNGA",
        "ACHE SE MAA CHUDWA APNI TU MAFI MIL JAYEGI TUJHE",
        "APNI MA MAT CHUDA MUJE SWIPE CRKE",
        "ACHE SE APNI MA CUDWA TU SWIPE CRKE",
        "FR BOLNA NA KI CUDWA LE APNI MA SWIPE CRKE",
        "CYA HUA MA CUD GYI TERY",
        "PR KESE CUD GYI TERY MA",
        "MUJHE PTA THA MA CUD GAI TERY",
        "MEY NY MANTA MA CUD GYI TERY",
        "TERI MA RNDY",
        "LODE SE UTR MC",
        "LUN MT CHUS MERA",
        "NIKAL MADARCHD",
        "CHUP OYE GASHTI K BACHE",
        "MAKICHUT TERI",
        "CHUP RNDYKE",
        "MA RNDY TERI",
        "TERI MA K HATH TODH K TERE BAAP K MUH ME FASADUNGA RANDYKE",
        "LEAVE LE TU RNDYKE PASAND NAI AYA MEKO",
        "LEAVE LE TU RANDYKE IDER SE",
        "LEAVE LE JLDI SE WRNA MA CHUD GAI TERY",
        "LEAVE NY LEGA MAA RANDY TERY",
        "SMJH BAT MAA RANDY EY TERY LEAVE LE",
        "FAST LEAVE LE KAMJOR RANDYKE",
        "TUTO CHUP RNDYK",
        "OY HIJDE KHANA KHA KE AA KAMZOR",
        "TERI MAKO ILY REY",
        "CHUP CHAP CHUD TMKC",
        "CHUPCHAP MAA CHUDWA APNI TU",
        "SHI SE MAA CHUDWA APNI TU CHUPCHAP",
        "FR SE MAA CHUDWA TU APNI CHUPCHAP",
        "SHI SE LIKH WRNA MA CHUD GAI TERY",
        "MA CYU CHUD GAI TERY CHUPCHAP",
        "PROOF CR MAA CHUD GYI TERY",
        "PROOF EY TERY MAA RANDY EY",
        "PROOF HO CHUKA MAA RANDY TERY",
        "CHUP CHILLAR",
        "CHUP CHUP MA K BOSDA TERY",
        "OY HIJDE KHANA KHA KE AA KAMZOR",
        "CHUP MADARCHOD ?",
        "AB TK CUD GYI HOGI TERY MAA ?",
        "NY NY ME KUCH NY JANTA BS TERI MA RNDY EY",
        "SBSE PHELE APNI MAA KO BOL CHUDNA KAAM KRE",
        "YAHA BHI CHUDA TU RNDYCE PILLE",
        "TERIMAKABOSDA",
        "TERI TO BHEN CUDEGI",
        "CHUP RNDYKE TOMMY",
        "NIKAL MADARCHD CUDKE YHA SE",
        "COZ TERI MA ANDHI RANDI HE",
        "NYTO BAAP BOL MUJHE",
        "NYNY TERI MAA HOGI RNDII JO CHUDWATI JOGI",
        "TRY AMMI CE BHOSDE ME EMOJI DAL MC",
        "CYA ? CHMR CHUD GYA CYA ?",
        "TM CHUDRI HOGI FRRTO",
        "CYA ? KB ? PGL EY CYA RNDKEK",
        "CYA SCH MEY PGL EY CYA TU RANDYKE CUDWA LI TUNE APNI MA",
        "ITNA SCH NY BOL MA CHUD GAI TERY",
        "SCH MEY PGL EY TU APNI MA CUDWA LIA MERE STH",
        "MTLB TMR",
        "NYTO",
        "PURA LIKH MC",
        "TMR FRRTO",
        "OH OK CUDLE FIR",
        "TERI MAA KA DAMAD",
        "CYA ? ACHE SE LIKHE PEHLE RNDIKEBACHE",
        "NYTO TERI MAA CHODNE ME VYAST HU",
        "NYTO PGL EY CYA KUCH BI",
        "OYEE CYA ? CHUD GYA ?",
        "CHUD MT HSS",
        "YUR RNDII MOM",
        "ARE SBKI MAA RNDII OR TERI BI",
        "ARE IDAR CUDLE EK BAAR",
        "TRI MAA CI TRH",
        "EK LINE ME TMR",
        "Q",
        "OCY AB CHUDLE",
        "PEHELE TERI MAA CHODU",
        "NYTO",
        "Q ?",
        "HYYY CHUD KE DIKA EK BAAR",
        "OYEE SUN DOST TMR",
        "BHAG JA RAAND MAAF CRR DUNGA",
        "OYEE PGL RNDII IDAR AA",
        "CYA TMR FRRTO",
        "OYEE IDAR Aake CHUD LE CHMR",
        "NYTO AESE HI CUD",
        "OYEE HYY AISE HI CUD LENA",
        "OR CHUD LE",
        "CHUD KE DIKA OR",
        "HYY CHUDO NA",
        "CHUDO MT BHAG JAO",
        "BYYEE HYY CYA ?",
        "QCHUD Q RHE HO ?",
        "PGL EY CYA MC",
        "CHUD MT",
        "CYA PGL RNDII IDAR AA",
        "TERI AMMI CE BHOSDE ME CHAPPAL",
        "OYEE IDAR AA MC",
        "KMZROR EY CYA RNDIEK",
        "CYA LIKH RHA ?",
        "CHUD THA CYA ?",
        "OYEE SLIDE LEKE BAAT CRMC",
        "IDAR A TERI MAA CHODU",
        "OYEE CP MT CRR CHUDLE",
        "OYEE HYY CHUD KE DIKA",
        "IDAR AA TRY MA SCHOFU KHACHAR KHACHAR",
        "IDAR AA JA MC",
        "HYY IDAR Aake CHUDLE",
        "OYEE KMZOR MC IDAR AA",
        "YE CYA TMR",
        "OYEE NY CP NY CRR",
        "OYEE PGL MT CRR",
        "CUDLE ARAM SE MC",
        "PGL EY CYA RNDIEK",
        "CP CRCE CHUDEGA !",
        "BAAP ? MC MERA COI MA BAAP NY EY MAI UPAR SE ROCKET PE BETH CE BSS TERI MA CHODNE AYA HU",
        "CHOTA LIKH RNDI K BACHE",
        "CHOTA LIKHA WRNA TRY MA RNDY",
        "TRY MA BAKA CODEGA",
        "TMKC MAIN BURF",
        "BHIKARI KI JHAT MA CUDA LE",
        "CHODKE TERY MA MARJAYEGI",
        "TMKC MAIN MOUNT EVEREST",
        "MUH MEY LEGA LUND MERA",
        "HIJDE KI JHAT CHUP WRNA TRY MA RNDI",
        "MENU NY PTA TERY MA RANDY",
        "MENU KI PTA MA RANDY TERY",
        "MENU PTA MAA CUD GAI TERY",
        "MENU SB PTA MA RANDY EY TERY",
        "MENU PR TERY MA RANDY",
        "RANDY MAA TERY MENU PTA",
        "TENU OR MENU PTA EY MAA RANDY TERY",
        "BS BS MAA CUDWA APNI",
        "BS BS MA RANDY TERY THNKSS",
        "BS BS CHUDWA LIA TU APNI MAA",
        "BS BS KAMJOR MAA RANDY TERY",
        "SMJH GYA APNI MA CUDWA LE AB",
        "SMJH GYA TERY MAA RANDY EY",
        "SMJH GYA TU SABIT KR MAA RANDY TERY",
        "CYA HUA MA CUDWA TU APNI",
        "EASY MAA CUDWA LE APNI TU",
        "EASY W8 MA CHUDWA LE APNI AB",
        "SANS ARI HA KY TERI MAA CHUDGI AJJ",
        "TERI MAA KO BINA SANSS LETE HUE CHODUNGA",
        "CHUP RANDIKE KAMJOR",
        "APNI MA NORMIE CUDWA LE TU",
        "FR CYA NORMIE MA CUD GAI TERY",
        "BAS THEK TERY MA RANDY",
        "BAS THEK TERY MAA CUD GYI",
        "KAMJOR THI TERY MA ESLIYE CUD GAI",
        "MAI SB JANTA MA CUD GAI TERY",
        "CHL CHL HT TERY MAA CUD GYI",
        "FR KAISE CUD GYI MAA TERY",
        "MAA TERY RANDY EY",
        "BAS TERY MAA RANDY EY",
        "FR RANDY MA TERY EY",
        "KAMJOR MA KA BCHA TU RANDYKE",
        "BHOT GNDI CUD GAI MAA TERY",
        "PR KAISE MAA CUD GAI TERY ITNA GNDA",
        "MUJHE CYA BTA RHA MAA RANDY TERY",
        "MUJHE CYA PTA MA CUD GYI TERY",
        "FIR MUJHE NY PTA MAA CUD GAI TERY",
        "PTA NY KON COD DIA TERY MAA KO",
        "RUK AAYA TERY MA CODKE",
        "WAIT CR TERY MAA COD RHA HU",
        "WAIT CR RABDYKE MAA CUD RHI EY TERY",
        "WAIT KR SMJH RHA TERY MA CODKE",
        "WAIT LE THODA CHODNE DE TERY MAKO",
        "RUK JA AAND RKH DUNGA TERY MAKE LIYE",
        "TERY MAA FAMOUS RANDY EY",
        "MAAN LIA MENE MAA RANDY SALI TERY",
        "MAAN LIA MAA CUD GAI TERY",
        "SHANT BETH RANDYKE MAA CHUDWA TU APNI",
        "SHANT BETHKE CHUDWA LE APNI MAKO TU",
        "FR SE SHANT BETH TU CUD AB RANDYKE YHA",
        "MERE SMJH NY AYA MAA RANDY TERY",
        "LE KELA KHA TU MADARCHOD",
        "HYE TERY MA CUD GYI CYA",
        "HYE TERY MAA MAR GAI CYA",
        "HYE SCH BTA COM COD DIA TERY MAKO",
        "CHL CHOD DIA TERI MAA KO SMJHLE",
        "BAKI KOI DIKKAT NY TERY MAA RANDY EY",
        "BAKI SB JANTE EY KI MAA CHUDDKAD EY TERY",
        "MUJHE CYA PTA THA TERY MAA CUDNE WLI EY",
        "PR MEI KAISE JNTA TERY MA KO KOI CHOD DIA",
        "PR MERA VI MANNA SHI THA MAA CHUD GAI TERY",
        "PR WO GLT NY TERY MAA RANDY EY",
        "PR WO SHI EY TERY MAA CHUDDKAD EY",
        "PR KAISE KIA MAA CHUD GAI TERY OMFOO",
        "BUR CHEER DUNGA TRI MA KA",
        "TERI MA KE DIL ME LODA MARKE USKI DHADKAN ROK DUNGA",
        "LULLE KHA TRI MAKABHOSDA",
        "TRI BHN KI BHOSDI BETA",
        "TRI MA RNDI BAAT KHTM",
        "SUN EK MAZE KI BAAT BATAO KYA TERI MAA RANDY EY",
        "CODU CODU MAKO TERY",
        "AJ CUD GAI TERY MAA OYE",
        "SUN SUN RANDY MAKE BACHE TU",
        "KILAS NY RANDYKE",
        "MUJHE CYA PTA TERY BHEN CUD GAI",
        "PR PR CYA HOTE EY TMKC",
        "TMCL SUNLE",
        "MOOT DU TERY MAKI CHUT MEY",
        "BHGNY CUDKE DIKHA FR",
        "FR SE CUDLE TU",
        "YE VI SHI EY TERY MKC BS",
        "AJ KUCH NY MA CUDWA TU APNI",
        "TRY KR MERA LUND CHUSKE",
        "TORMAKIBUR SUN",
        "TOR MAKI FUDDI OYE",
        "HAYE HAYE TERY MA CUD GAI",
        "OYE LUNDKE PASINE..",
        "KUTTE KE TATTE SUN",
        "KUTTA JAISA CUD RHA TU",
        "MUH MEI LE MERA..",
        "JHAAT KE PISSU SUN TMKC",
        "HAHAHHA MA CUD GAI TERY",
        "WEAK TATTE UTH",
        "WEAK EY TU CUD RHA",
        "WEAK ACHE SE CUD TU",
        "WEAK TERY MA CUD RHI DEKH",
        "WEEK TERY MA CUD GAI AB",
        "MUJHE NY ROK TU WEAK EY",
        "CHUP HIZDE",
        "OKAT NY MERI MA CUDWA TU APNI",
        "LUN LEGA TERY MAKI GAND MEI ?",
        "TERY MAKI BACHI CODU..",
        "TERY BHEN KI CHUT AJ FAD DU",
        "SPEED LEKR AA CUDKE DIKHA",
        "SPEED NY TERE ANDR WEAK PROSN",
        "UGLY RANDYKE CHUP",
        "MAKAFUDDATERY",
        "TERA BAAP KO TAG KR..?",
        "ACHE SE TAG KR RANDIBAAZ BHAGWN KO..",
        "CUDKE PGL NY HO TU",
        "CUDKE PGL HO RHA TU KID",
        "MA TO CUD GAI TERY HAWABZI CR..",
        "BS MA CODNI EY TERY",
        "TOWN MEI CUD TERY MAKO LEKR",
        "TERY MA SEXY KO BEJ - RANDIBAAZ BHGWN PE",
        "SPEED PKD CP NY KR",
        "TRY MA RENDY",
        "BHKK CUD",
        "TEY MAA RNDI",
        "TERY BEHEN RANDI",
        "CUD JA TMC",
        "TERY DIDI RNDI",
        "SLOW",
        "TERI MAIYA CIODU",
        "BHAG?TMC ",
        "BHAK CUD TML",
        "TMA CODU",
        "SLOW TMKC ",
        "SLOW FIRSE TMKC ",
        "CUDGRIB TML",
        "TRY MA DOU",
        "TBKC CODU",
        "NET ON OFF WALI RNDY",
        "OYE TRY MA CODU",
        "IDHAR AAKE CUD CHUP CHAAP",
        "TBKC MRDU",
        "OI MAAKE LODEE",
        "RANDYKE BEEJ",
        "TMKC CHODU",
        "SUAR KE BEEJ",
        "NET OFF ON KR RANDYKE LADKE",
        "TRY MA CUDI KESE",
        "CHUP SLOW MADHARCOD",
        "TBKC CODU KR MSG DELETE",
        "OI SUAR KE LADKE",
        "TMKC FUFI",
        "TERY DIDI CHUDI",
        "TMKC DIKHA",
        "CUD AB",
        "RANDYKE CUD",
        "BHAK CUD",
        "CUDLE TBKC MRU",
        "TMKL CUDLE GRIB",
        "TERY BEHEN VESITYA RNDI",
        "ITNA GNDA CHUDA TU FIRSE NET ON OFF",
        "GRIB KE BETE",
        "BHAG JA LODE TMKC MARU DUNGA",
        "TBKC MRDUNGAA",
        "BHAG TMKC",
        "BHAG TBKC",
        "TBKC MEY CP",
        "CP TBKC MEHH",
        "CP TMKL MEH",
        "CP BOL RANDYKE",
        "ABE CP BOL RANDYKE",
        "DOUBLE SEND KO CP TMKC CODU",
        "TBKC ME CP COD DUNGA AAJ MEHH",
        "HT TBKC DALAL KE BETE.",
        "RNDY JLDI JLDI CUDQ TRYMA",
        "PARA LIKHEGA..",
        "TRA RNDHBHAK",
        "LAGDI KE LADCE CP BOL",
        "CP BOL LAGDI KE BETE..",
        "CUDKE CP BOL",
        "BHIKARI LUND CHUS MERA.",
        "LOW LEVEL CP CR",
        "CP BOL LOW LEVEL WEAK",
        "MERE LUND PE EY TU HIJDE",
        "FREE CUDWA TERY MAKO",
        "FREE MEY CUD TU RANDYKE",
        "SPEED NY WEAK TATTE TERME",
        "KITNI BR CUDWAYEGA TERYMAKO",
        "LUND LE RANDIBAAZ BAPKA",
        "LUN CUS JALDI SE RANDIBAAZ BAPKA",
        "KOI NY DEKH RHA CUDLE TU",
        "CUDLE BETICHOD ACHE SE",
        "MAKI CHUT TERY BS YEHI JANTA MEY",
        "CP BOLEGA TO TMKC",
        "WRNA TERY MA CUD JAYEGI",
        "SLOW EY TU KID",
        "JLDI LIKH..TMKC",
        "JLDI LIKH..RANDCE TU",
        "TYM SE PHLE CUDKE DIKHA",
        "TYM HOGA TERY MAA CUDWA",
        "MA CUD GAI TERY TYM SE PHLE",
        "UTH RANDCE KE LDKE",
        "MACABOSDATERY",
        "CON KB COD DIA MAKO TERY",
        "KOI HOGA TML",
        "MACHAR CUDLE TU",
        "MENU TERY MAKO CODNA SE",
        "TERY MAKO BOL MUJHE COD DE",
        "BS MEY TERY MA SE CUDNA CHTA HU",
        "EWW MAKA LODE UTH",
        "MEOW CR TERY MAKO CODU",
        "LUND RKH DIA TERY MAKE FUDE PE",
        "MERA LUND KE BAL UTH",
        "KIDEE ZINDA HO",
        "MAR NY KIDDE TYPE KR",
        "CHUP BKL",
        "BC TERY MAKI CHUT",
        "MC RANDYKE LIKH FAST",
        "FAST LIKH RANDYKE",
        "FAST LIKH KAMZOR",
        "TERY MAKI CHUT CLAIM CRWA",
        "AWZ NICHE RANDCE KE BCHE",
        "SAWAL NY PUCH TERY MAKABOSDA",
        "FYTER BNEGA LAGDE MADRCHOD",
        "OYE KAALE RO KE DIKHA",
        "OYE KAALE ROO NY",
        "SHORT NY CUD TU BINA RUKE",
        "SHORT NY CUD TU APNI MAKO LEKR",
        "TERY MAKE STH TERY BHEN VI CUDWA LE",
        "TERY MAKE STH TERY DIDI VI CUD GAI",
        "CHAT FYTER BNEGA RANDCE CODU TERY MAKO",
        "BOL RANDIBAAZ DADDY EY",
        "BULLYX RANDYKE UTH",
        "MAR MARKE CUD RHA TU",
        "OR TERY MA MARKE CUD GAI",
        "JALDI LIKH RNDYKE BEJ",
        "OR BDA LIKH TMC",
        "OR BDA 2 LINE WLA LIKH TMKC",
        "OR BDA OYE LIKH TML",
        "TERI MAA KA BUR",
        "OYE KEEDE",
        "RANDI KE LADKE",
        "JALDI LIKH TERI BEHEN CHODU",
        "MKL UTH RANDI KE BACCHE",
        "TERI NANI MERI MAAL",
        "TEJ LIKH RANDCE",
        "OYE MAAKE LODE MRENGA",
        "TERI MAA CHODY",
        "TERI MAIYA KI GAND",
        "TERY DADI KA FUDDA",
        "MKL UTH BEHENCOD",
        "TERI MAA KI BUR DE",
        "TERY MAA KA FUDDA ME LAUDA",
        "TERI MAA CHUDVA",
        "RANDI KE BETE MAR GAYA",
        "TERI MAA KI CHUT MRU",
        "JALID KR SPAM",
        "MC SPAM ROKENGA",
        "TERI MAAKI CHUT SPAM KR",
        "SPAM KR.MAAKE LODE",
        "RANDYKE CHODE SPAM KR WRNA CUD TU",
        "SPAM KR KID",
        "NOOB TERI MAA CHODU",
        "RNDYKE BETE MAR MAT TU",
        "NOOB JALDI LIKH WRNA TERY MAA RAND",
        "CUD GAI MAA TERY NOOB",
        "UTH RANDYKE NOOB",
        "CHL CUDKE DIKHA NOOB",
        "JLDI TYP CR NOOB HALKE",
        "CUD KE PGL NY HO NOOB",
        "CUD CUD KE RAND BNJA TU NOOB",
        "MAKICHUT TERY NOOB",
        "GANDA CYU CUD RHA TU ?",
        "ITNA GNDA NY CUD ACHE SE CUD",
        "MAAN LE CUD GYA TU SUN BAT AB",
        "MAKAFUDDA FAT GYA TERY RUK",
        "sʜᴀɴᴛ ʙᴇᴛʜ ᴍᴀᴅʀᴄʜᴏᴅ ᴡʀɴᴀ ᴍᴀᴋᴀʙᴏsᴅᴀ ᴛᴇᴇʏ.",
        "ᴛᴇʀɪ ᴍᴀ ᴋɪ ᴄʜᴜᴛ..",
        "ʟᴡᴅᴇ ᴋᴇ ʙᴀᴀᴀʟʟʟ ᴛᴇʀʏ ᴍᴀᴀ ᴄᴜᴅᴋᴇ ᴘɢʟ ᴅᴇᴋʜ.",
        "ᴍᴀᴄʜᴀʀ ᴋɪ ᴊʜᴀᴀᴛ ᴋᴇ ʙᴀᴀᴀʟʟʟʟ ᴄᴜᴅ ᴀᴄʜᴇ sᴇ ʏʜᴀᴘᴇ ᴛᴜ",
        "ᴛᴇʀɪ ᴍᴀ ᴋɪ ᴄʜᴜᴛ ᴍ ᴅᴜ ᴛᴀᴘᴀ ᴛᴀᴘ?",
        "ᴛᴇʀɪ ᴍᴀ ᴋᴀ ʙʜᴏꜱᴅᴀᴀ",
        "ᴛᴇʀɪ ʙʜɴ ꜱʙꜱʙᴇ ʙᴅɪ ʀᴀɴᴅɪ.",
        "ᴛᴇʀɪ ᴍᴀ ᴏꜱꜱᴇ ʙᴀᴅɪ ʀᴀɴᴅᴅᴅᴅᴅ",
        "ᴛᴇʀᴀ ʙᴀᴀᴘ ʀᴀɴᴅɪʙᴀᴀᴢ ᴇʏ ᴅᴇᴋʜ",
        "ᴋɪᴛɴɪ ᴄʜᴏᴅᴜ ᴛᴇʀɪ ᴍᴀ ᴀʙ ᴏʀ..",
        "ᴛᴇʀɪ ᴍᴀ ᴄʜᴏᴅ ᴅɪ ʜᴍ ɴᴇ",
        "ᴛᴇʀɪ ᴍᴀ ᴋᴇ ꜱᴛʜ ʀᴇᴇʟꜱ ʙɴᴇɢᴀ ʀᴏᴀᴅ ᴘᴇᴇ",
        "ᴛᴇʀɪ ᴍᴀ ᴋɪ ᴄʜᴜᴛ ᴇᴋ ᴅᴀᴍ ᴛᴏᴘ ꜱᴇxʏ",
        "ᴍᴀʟᴜᴍ ɴᴀ ᴘʜʀ ᴋᴇꜱᴇ ʟᴇᴛᴀ ʜᴜ ᴍ ᴛᴇʀɪ ᴍᴀ ᴋɪ ᴄʜᴜᴛ ᴛᴀᴘᴀ ᴛᴀᴘᴘᴘᴘᴘ",
        "ʟᴜɴᴅ ᴋᴇ ᴄʜᴏᴅᴇ ᴛᴜ ᴋᴇʀᴇɢᴀ ᴛʏᴘɪɴɢ ᴋʀᴇɢᴀ ᴛᴍᴋᴄ",
        "ꜱᴘᴇᴇᴅ ᴘᴋᴅ ʟᴡᴅᴇᴇᴇᴇ ᴡʀɴᴀ ᴍᴇʀᴀ ʟᴜɴᴅ ᴘᴋᴅ",
        "ʙᴀᴀᴘ ᴋɪ ꜱᴘᴇᴇᴅ ᴍᴛᴄʜ ᴋʀʀʀ",
        "ʟᴡᴅᴀ ʟᴇ ᴍᴇʀᴀ ᴊᴀʟᴅɪ sᴇ ᴛᴜ",
        "ᴘᴀᴘᴀ ᴋɪ ꜱᴘᴇᴇᴅ ᴍᴛᴄʜ ɴʜɪ ʜᴏ ʀʜɪ ᴋʏᴀ ᴛᴇʀᴇsᴇ",
        "ᴀʟᴇ ᴀʟᴇ ᴍᴇʟᴀ ʙᴄʜᴀᴀᴀᴀ ᴛᴇʀʏ ᴍᴀᴋᴀ ʙᴏsᴅᴀ sᴜɴ",
        "ᴄʜᴜᴅ ɢʏᴀ ʀᴀɴᴅɪʙᴀᴀᴢ ᴘᴀᴘᴀ ꜱᴇᴇᴇ ᴛᴜ",
        "ᴍᴇɴᴜ ᴋɪ ᴘᴛᴀ ᴛᴇʀʏ ᴍᴀ ᴄᴜᴅ ɢᴀɪ",
        "ᴋᴏɪ ʙᴀᴀᴛ ɴʏ ᴍᴀᴀ ʀᴀɴᴅʏ ᴛᴇʀʏ",
        "ʜᴀʜᴀʜᴀᴀᴀᴀᴀ ᴍᴀᴋᴀʙᴏsᴅᴀ ᴛᴇʀʏ",
        "xʜᴜᴅ ɢᴀɪ ᴍᴀᴀ ᴛᴇʀʏ ᴋɪᴅꜱꜱꜱꜱ",
        "ᴛᴇʀɪ ᴍᴀ ᴄʜᴜᴅ ɢʏɪ ᴀʙ ꜰʀᴀʀ ᴍᴛ ʜᴏɴᴀ",
        "ʏᴇ ʟᴜɴᴅ ʟᴇ ᴍᴇʀᴀ ᴄʜʟ ᴊᴀʟᴅɪ sᴇ",
        "ᴋɪᴅꜱꜱꜱ ꜰʀᴀʀ ɴᴀ ʜᴏ ᴛᴜ ʜᴀʜᴀʜʜ",
        "ʙʜᴇɴ ᴋᴇ ʟᴡᴅᴇ ꜱʜʀᴍ ᴋʀ",
        "ᴋɪᴛɴɪ ɢʟɪʏᴀ ᴘᴅᴡᴇɢᴀ ᴀᴘɴɪ ᴍᴀ ᴋᴏ",
        "ᴄʜᴜᴘ ɴᴀʟʟɪɪ ʀᴀɴᴅʏᴋᴇ ʟᴀᴅᴋᴇ",
        "ꜱᴜᴀʀ ᴋᴇ ᴘɪʟʟᴇ ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ꜱᴀᴅᴀᴋ ᴘʀ ʟɪᴛᴀᴋᴇ ᴄʜᴏᴅ ᴅᴜɴɢᴀ 😂😆🤤",
        "ᴀʙᴇ ᴛᴇʀɪ ᴍᴀᴀᴋᴀ ʙʜᴏꜱᴅᴀ ᴍᴀᴅᴇʀᴄʜᴏᴏᴅ ᴋʀ ᴘɪʟʟᴇ ᴘᴀᴘᴀ ꜱᴇ ʟᴀᴅᴇɢᴀ ᴛᴜ 😼😂🤤",
        "ɢᴀʟɪ ɢᴀʟɪ ɴᴇ ꜱʜᴏʀ ʜᴇ ᴛᴇʀɪ ᴍᴀᴀ ʀᴀɴᴅɪ ᴄʜᴏʀ ʜᴇ 💋💋💦",
        "ᴀʙᴇ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴏ ᴄʜᴏᴅᴜ ʀᴀɴᴅɪᴋᴇ ᴘɪʟʟᴇ ᴋᴜᴛᴛᴇ ᴋᴇ ᴄʜᴏᴅᴇ 😂👻🔥",
        "ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴀɪꜱᴇ ᴄʜᴏᴅᴀ ᴀɪꜱᴇ ᴄʜᴏᴅᴀ ᴛᴇʀɪ ᴍᴀᴀᴀ ʙᴇᴅ ᴘᴇʜɪ ᴍᴜᴛʜ ᴅɪᴀ 💦💦💦💦",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴇ ʙʜᴏꜱᴅᴇ ᴍᴇ ᴀᴀᴀɢ ʟᴀɢᴀᴅɪᴀ ᴍᴇʀᴀ ᴍᴏᴛᴀ ʟᴜɴᴅ ᴅᴀʟᴋᴇ 🔥🔥💦😆😆",
        "ʀᴀɴᴅɪᴋᴇ ʙᴀᴄʜʜᴇ ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴄʜᴏᴅᴜ ᴄʜᴀʟ ɴɪᴋᴀʟ",
        "ᴋɪᴛɴᴀ ᴄʜᴏᴅᴜ ᴛᴇʀɪ ʀᴀɴᴅɪ ᴍᴀᴀᴋɪ ᴄʜᴜᴛʜ ᴀʙʙ ᴀᴘɴɪ ʙᴇʜᴇɴ ᴋᴏ ʙʜᴇᴊ 😆👻🤤",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴏᴛᴏ ᴄʜᴏᴅ ᴄʜᴏᴅᴋᴇ ᴘᴜʀᴀ ꜰᴀᴀᴅ ᴅɪᴀ ᴄʜᴜᴛʜ ᴀʙʙ ᴛᴇʀɪ ɢꜰ ᴋᴏ ʙʜᴇᴊ 😆💦🤤",
        "ᴛᴇʀɪ ɢꜰ ᴋᴏ ᴇᴛɴᴀ ᴄʜᴏᴅᴀ ʙᴇʜᴇɴ ᴋᴇ ʟᴏᴅᴇ ᴛᴇʀɪ ɢꜰ ᴛᴏ ᴍᴇʀɪ ʀᴀɴᴅɪ ʙᴀɴɢᴀʏɪ ᴀʙʙ ᴄʜᴀʟ ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴄʜᴏᴅᴛᴀ ꜰɪʀꜱᴇ ♥️💦😆😆😆😆",
        "ʜᴀʀɪ ʜᴀʀɪ ɢʜᴀᴀꜱ ᴍᴇ ᴊʜᴏᴘᴅᴀ ᴛᴇʀɪ ᴍᴀᴀᴋᴀ ʙʜᴏꜱᴅᴀ 🤣🤣💋💦",
        "ᴄʜᴀʟ ᴛᴇʀᴇ ʙᴀᴀᴘ ᴋᴏ ʙʜᴇᴊ ᴛᴇʀᴀ ʙᴀꜱᴋᴀ ɴʜɪ ʜᴇ ᴘᴀᴘᴀ ꜱᴇ ʟᴀᴅᴇɢᴀ ᴛᴜ",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋɪ ᴄʜᴜᴛʜ ᴍᴇ ʙᴏᴍʙ ᴅᴀʟᴋᴇ ᴜᴅᴀ ᴅᴜɴɢᴀ ᴍᴀᴀᴋᴇ ʟᴀᴡᴅᴇ",
        "ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴛʀᴀɪɴ ᴍᴇ ʟᴇᴊᴀᴋᴇ ᴛᴏᴘ ʙᴇᴅ ᴘᴇ ʟɪᴛᴀᴋᴇ ᴄʜᴏᴅ ᴅᴜɴɢᴀ ꜱᴜᴀʀ ᴋᴇ ᴘɪʟʟᴇ 🤣🤣💋💋",
        "ᴛᴇʀɪ ᴍᴀᴀᴀᴋᴇ ɴᴜᴅᴇꜱ ɢᴏᴏɢʟᴇ ᴘᴇ ᴜᴘʟᴏᴀᴅ ᴋᴀʀᴅᴜɴɢᴀ ʙᴇʜᴇɴ ᴋᴇ ʟᴀᴇᴡᴅᴇ 👻🔥",
        "ᴛᴇʀɪ ᴍᴀᴀᴀᴋᴇ ɴᴜᴅᴇꜱ ɢᴏᴏɢʟᴇ ᴘᴇ ᴜᴘʟᴏᴀᴅ ᴋᴀʀᴅᴜɴɢᴀ ʙᴇʜᴇɴ ᴋᴇ ʟᴀᴇᴡᴅᴇ 👻🔥",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴏ ᴄʜᴏᴅ ᴄʜᴏᴅᴋᴇ ᴠɪᴅᴇᴏ ʙᴀɴᴀᴋᴇ xɴxx ᴘᴇ ɴᴇᴇʟᴀᴍ ᴋᴀʀᴅᴜɴɢᴀ ᴋᴜᴛᴛᴇ ᴋᴇ ᴘɪʟʟᴇ 💦💋",
        "ᴛᴇʀɪ ᴍᴀᴀᴀᴋɪ ᴄʜᴜᴅᴀɪ ᴋᴏ ᴘᴏ*ʀɴʜᴜʙ ᴘᴇ ᴜᴘʟᴏᴀᴅ ᴋᴀʀᴅᴜɴɢᴀ ꜱᴜᴀʀ ᴋᴇ ᴄʜᴏᴅᴇ 🤣💋💦",
        "ᴀʙᴇ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴏ ᴄʜᴏᴅᴜ ʀᴀɴᴅɪᴋᴇ ʙᴀᴄʜʜᴇ ᴛᴇʀᴇᴋᴏ ᴄʜᴀᴋᴋᴏ ꜱᴇ ᴘɪʟᴡᴀᴠᴜɴɢᴀ ʀᴀɴᴅɪᴋᴇ ʙᴀᴄʜʜᴇ 🤣🤣",
        "ᴛᴇʀɪ ᴍᴀᴀᴋɪ ᴄʜᴜᴛʜ ꜰᴀᴀᴅᴋᴇ ʀᴀᴋᴅɪᴀ ᴍᴀᴀᴋᴇ ʟᴏᴅᴇ ᴊᴀᴀ ᴀʙʙ ꜱɪʟᴡᴀʟᴇ 👄👄",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋɪ ᴄʜᴜᴛʜ ᴍᴇ ᴍᴇʀᴀ ʟᴜɴᴅ ᴋᴀᴀʟᴀ",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ʟᴇᴛɪ ᴍᴇʀɪ ʟᴜɴᴅ ʙᴀᴅᴇ ᴍᴀꜱᴛɪ ꜱᴇ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴏ ᴍᴇɴᴇ ᴄʜᴏᴅ ᴅᴀʟᴀ ʙᴏʜᴏᴛ ꜱᴀꜱᴛᴇ ꜱᴇ",
        "ʙᴇᴛᴇ ᴛᴜ ʙᴀᴀᴘ ꜱᴇ ʟᴇɢᴀ ᴘᴀɴɢᴀ ᴛᴇʀɪ ᴍᴀᴀᴀ ᴋᴏ ᴄʜᴏᴅ ᴅᴜɴɢᴀ ᴋᴀʀᴋᴇ ɴᴀɴɢᴀ 💦💋",
        "ʜᴀʜᴀʜᴀʜ ᴍᴇʀᴇ ʙᴇᴛᴇ ᴀɢʟɪ ʙᴀᴀʀ ᴀᴘɴɪ ᴍᴀᴀᴋᴏ ʟᴇᴋᴇ ᴀᴀʏᴀ ᴍᴀᴛʜ ᴋᴀᴛ ᴏʀ ᴍᴇʀᴇ ᴍᴏᴛᴇ ʟᴜɴᴅ ꜱᴇ ᴄʜᴜᴅᴡᴀʏᴀ ᴍᴀᴛʜ ᴋᴀʀ",
        "ᴄʜᴀʟ ʙᴇᴛᴀ ᴛᴜᴊʜᴇ ᴍᴀᴀꜰ ᴋɪᴀ 🤣ᴛᴜ ᴀʙʙ ᴀᴘɴɪ ᴍᴀᴋᴏ ʙʜᴇᴊ",
        "ꜱʜᴀʀᴀᴍ ᴋᴀʀ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴀ ʙʜᴏꜱᴅᴀ ᴋɪᴛɴᴀ ɢᴀᴀʟɪᴀ ꜱᴜɴᴡᴀʏᴇɢᴀ ᴀᴘɴɪ ᴍᴀᴀᴀ ʙᴇʜᴇɴ ᴋᴇ ᴜᴘᴇʀ",
        "ᴀʙᴇ ʀᴀɴᴅɪᴋᴇ ʙᴀᴄʜʜᴇ ᴀᴜᴋᴀᴛ ɴʜɪ ʜᴇᴛᴏ ᴀᴘɴɪ ʀᴀɴᴅɪ ᴍᴀᴀᴋᴏ ʟᴇᴋᴇ ᴀᴀʏᴀ ᴍᴀᴛʜ ᴋᴀʀ ʜᴀʜᴀʜᴀʜᴀ",
        "ᴋɪᴅᴢ ᴍᴀᴅᴀʀᴄʜᴏᴅ ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴄʜᴏᴅ ᴄʜᴏᴅᴋᴇ ᴛᴇʀʀ ʟɪʏᴇ ʙʜᴀɪ ᴅᴇᴅɪʏᴀ",
        "ᴊᴜɴɢʟᴇ ᴍᴇ ɴᴀᴄʜᴛᴀ ʜᴇ ᴍᴏʀᴇ ᴛᴇʀɪ ᴍᴀᴀᴋɪ ᴄʜᴜᴅᴀɪ ᴅᴇᴋᴋᴇ ꜱᴀʙ ʙᴏʟᴛᴇ ᴏɴᴄᴇ ᴍᴏʀᴇ ᴏɴᴄᴇ ᴍᴏʀᴇ 🤣🤣💦💋",
        "ɢᴀʟɪ ɢᴀʟɪ ᴍᴇ ʀᴇʜᴛᴀ ʜᴇ ꜱᴀɴᴅ ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴄʜᴏᴅ ᴅᴀʟᴀ ᴏʀ ʙᴀɴᴀ ᴅɪᴀ ʀᴀɴᴅ 🤤🤣",
        "ꜱᴀʙ ʙᴏʟᴛᴇ ᴍᴜᴊʜᴋᴏ ᴘᴀᴘᴀ ᴄʏᴜᴋɪ ᴍᴇɴᴇ ᴋʀᴅɪᴀ ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴘʀᴇɢɴᴇɴᴛ 🤣🤣",
        "ꜱᴜᴀʀ ᴋᴇ ᴘɪʟʟᴇ ᴛᴇʀɪ ᴍᴀᴀᴋɪ ᴄʜᴜᴛʜ ᴍᴇ ꜱᴜᴀʀ ᴋᴀ ʟᴏᴜᴅᴀ ᴏʀ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋɪ ᴄʜᴜᴛʜ ᴍᴇ ᴍᴇʀᴀ ʟᴏᴅᴀ",
        "ᴄʜᴀʟ ᴄʜᴀʟ ᴛᴜ ᴀᴘɴɪ ᴍᴀᴀᴋɪ ᴄʜᴜᴄʜɪʏᴀ ᴅɪᴋᴀ",
        "ʜᴀʜᴀʜᴀʜᴀ ʙᴀᴄʜʜᴇ ᴛᴇʀɪ ᴍᴀᴀᴀᴋᴏ ᴄʜᴏᴅ ᴅɪᴀ ɴᴀɴɢᴀ ᴋᴀʀᴋᴇ",
        "ᴛᴇʀɪ ɢꜰ ʜᴇ ʙᴀᴅɪ ꜱᴇxʏ ᴜꜱᴋᴏ ᴘɪʟᴀᴋᴇ ᴄʜᴏᴏᴅᴇɴɢᴇ ᴘᴇᴘꜱɪ",
        "2 ʀᴜᴘᴀʏ ᴋɪ ᴘᴇᴘꜱɪ ᴛᴇʀɪ ᴍᴜᴍᴍʏ ꜱᴀʙꜱᴇ ꜱᴇxʏ 💋💦",
        "ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴄʜᴇᴇᴍꜱ ꜱᴇ ᴄʜᴜᴅᴡᴀᴠᴜɴɢᴀ ᴍᴀᴅᴇʀᴄʜᴏᴏᴅ ᴋᴇ ᴘɪʟʟᴇ 💦🤣",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋɪ ᴄʜᴜᴛʜ ᴍᴇ ᴍᴜᴛʜᴋᴇ ꜰᴀʀᴀʀ ʜᴏᴊᴀᴠᴜɴɢᴀ ʜᴜɪ ʜᴜɪ ʜᴜɪ",
        "ꜱᴘᴇᴇᴅ ʟᴀᴀᴀ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴄʜᴏᴅᴜ ʀᴀɴᴅɪᴋᴇ ᴘɪʟʟᴇ 💋💦🤣",
        "ᴀʀᴇ ʀᴇ ᴍᴇʀᴇ ʙᴇᴛᴇ ᴄʏᴜ ꜱᴘᴇᴇᴅ ᴘᴀᴋᴀᴅ ɴᴀ ᴘᴀᴀᴀ ʀᴀʜᴀ ᴀᴘɴᴇ ʙᴀᴀᴘ ᴋᴀ ʜᴀʜᴀʜᴀ ᴛᴇʀɪ ᴍᴀᴀ ᴄᴜᴅ ɢᴀɪ🤣🤣",
        "ꜱᴜɴ ꜱᴜɴ ꜱᴜᴀʀ ᴋᴇ ᴘɪʟʟᴇ ᴊʜᴀɴᴛᴏ ᴋᴇ ꜱᴏᴜᴅᴀɢᴀʀ ᴀᴘɴɪ ᴍᴜᴍᴍʏ ᴋɪ ɴᴜᴅᴇꜱ ʙʜᴇᴊ",
        "ᴀʙᴇ ꜱᴜɴ ʟᴏᴅᴇ ᴛᴇʀɪ ʙᴇʜᴇɴ ᴋᴀ ʙʜᴏꜱᴅᴀ ꜰᴀᴀᴅ ᴅᴜɴɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀᴋᴏ ᴋʜᴜʟᴇ ʙᴀᴊᴀʀ ᴍᴇ ᴄʜᴏᴅ ᴅᴀʟᴀ 🤣🤣💋",
        "ꜱʜʀᴍ ᴋʀ ᴛᴇʀʏ ᴍᴀᴀ ᴄᴜᴅ ɢᴀɪ ʏʜᴀ",
        "ᴍᴇʀᴇ ʟᴜɴᴅ ᴋᴇ ʙᴀᴀᴀᴀᴀʟʟʟʟʟ ᴘᴋᴅ ᴊᴀʟᴅɪ sᴇ",
        "ᴛᴜ ᴇᴋ ᴋᴀᴀᴍ ᴋʀ ᴀᴘɴɪ ᴍᴀ ʙʜᴇɴ ᴋᴏ ᴄᴜᴅᴡᴀ ʟᴇ ᴍᴇʀᴇ sᴛʜ",
        "ʀɴᴅɪ ᴋᴇ ʟᴅᴋᴇᴇᴇᴇᴇᴇᴇᴇᴇ ᴄʜᴜᴘ ᴏʀ ᴄᴜᴅ ʏʜᴀ",
        "ᴄʜᴜᴘ ᴛᴍᴋᴄ ᴋɪᴅꜱꜱꜱꜱꜱꜱꜱꜱꜱꜱꜱꜱ",
        "ᴀᴘɴɪ ɢᴀᴀɴᴅ ᴍᴇɪɴ ᴍᴜᴛʜɪ ᴅᴀᴀʟ",
        "ᴍᴇʀᴀ ʟᴜɴᴅ ᴄʜᴏᴏꜱ ᴊᴀʟᴅɪ sᴇ",
        "ᴀᴘɴɪ ᴍᴀ ᴋᴏ ᴄᴜsᴡᴀ ᴍᴇʀᴀ ʟᴜɴᴅ",
        "ʙʜᴇɴ ᴋᴇ ʟᴀᴜᴅᴇ ᴛᴍᴄ",
        "ʙʜᴇɴ ᴋᴇ ᴛᴀᴋᴋᴇ ᴛᴍʟ",
        "ᴀʙʟᴀ ᴛᴇʀᴀ ᴋʜᴀɴ ᴅᴀɴ ᴄʜᴏᴅɴᴇ ᴋɪ ʙᴀʀɪɪɪ",
        "ʙᴇᴛᴇ ᴛᴇʀɪ ᴍᴀ ꜱʙꜱᴇ ʙᴅɪ ʀᴀɴᴅ",
        "ʟᴜɴᴅ ᴋᴇ ʙᴀᴀᴀʟ ᴊʜᴀᴛ ᴋᴇ ᴘɪꜱꜱꜱᴜᴜᴜᴜᴜᴜᴜ ᴛᴍᴋᴄ",
        "ʟᴜɴᴅ ᴘᴇ ʟᴛᴋɪᴛ ᴍᴀᴀᴀʟʟʟʟ ᴋɪ ʙᴏɴᴅ ʜ ᴛᴜᴜᴜ",
        "ᴋᴀꜱʜ ᴏꜱ ᴅɪɴ ᴍᴜᴛʜ ᴍʀᴋᴇ ꜱᴏᴊᴛᴀ ᴍ ᴛᴜ ᴘᴀɪᴅᴀ ɴᴀ ʜᴏᴛᴀᴀ",
        "ɢʟᴛɪ ᴋʀᴅɪ ᴛᴜᴊᴡ ᴘᴀɪᴅᴀ ᴋʀᴋᴇ ᴛᴇʀʏ ᴍᴀ ɴᴇ ᴀʙ ᴄᴜᴅ ᴛᴜ ʏʜᴀ",
        "ꜱᴘᴇᴇᴅ ᴘᴋᴅᴅᴅ",
        "ɢᴀᴀɴᴅ ᴍᴀɪɴ ʟᴡᴅᴀ ᴅᴀʟ ʟᴇ ᴀᴘɴɪ ᴍᴇʀᴀᴀᴀ",
        "ɢᴀᴀɴᴅ ᴍᴇɪɴ ʙᴀᴍʙᴜ ᴅᴇᴅᴜɴɢᴀᴀᴀᴀᴀᴀ",
        "ɢᴀɴᴅ ꜰᴛɪ ᴋᴇ ʙᴀʟᴋᴋᴋ ᴛᴜ ᴄᴜᴅ ʏʜᴀ",
        "ɢᴏᴛᴇ ᴋɪᴛɴᴇ ʙʜɪ ʙᴀᴅᴇ ʜᴏ, ʟᴜɴᴅ ᴋᴇ ɴɪᴄʜᴇ ʜɪ ʀᴇʜᴛᴇ ʜᴀɪ",
        "ʜᴀᴢᴀᴀʀ ʟᴜɴᴅ ᴛᴇʀɪ ɢᴀᴀɴᴅ ᴍᴀɪɴ",
        "ᴊʜᴀᴀɴᴛ ᴋᴇ ᴘɪꜱꜱᴜ ᴛᴍᴋᴄ sᴜɴ",
        "ᴛᴇʀɪ ᴍᴀ ᴋɪ ᴋᴀʟɪ ᴄʜᴜᴛ",
        "ᴋʜᴏᴛᴇʏ ᴋɪ ᴀᴜʟᴅᴀ ᴇʏ ᴛᴜ ʀᴀɴᴅʏᴋᴇ",
        "ᴋᴜᴛᴛᴇ ᴋᴀ ᴀᴡʟᴀᴛ ᴊᴀɪsᴀ ʟɢ ʀʜᴀ ᴛᴜ",
        "ᴋᴜᴛᴛᴇ ᴋɪ ᴊᴀᴛ ᴊᴀɪsᴀ ᴇʏ ᴛᴜ ",
        "ᴋᴜᴛᴛᴇ ᴋᴇ ᴛᴀᴛᴛᴀ ᴇʏ ᴛᴜ",
        "ᴛᴇᴛɪ ᴍᴀ ᴋɪ.ᴄʜᴜᴛ , ᴛᴇʀɪ ᴍᴀ ʀɴᴅɪɪɪɪɪɪɪɪɪɪɪɪɪɪɪɪɪɪɪɪ",
        "ʟᴀᴠᴅᴇ ᴋᴇ ʙᴀʟ ᴘᴋᴅ ʟᴇ ᴍᴇʀᴇ",
        "ᴍᴜʜ ᴍᴇɪ ʟᴇʟᴇ ᴍᴇʀᴀ ʟᴜɴᴅ",
        "ʟᴜɴᴅ ᴋᴇ ᴘᴀꜱɪɴᴇ ᴄʜᴜᴘ ʙᴇᴛʜ ᴏʀ ᴄᴜᴅ",
        "ᴍᴇʀᴇ ʟᴡᴅᴇ ᴋᴇ ʙᴀᴀᴀᴀᴀʟʟʟ",
        "ʜᴀʜᴀʜᴀᴀᴀᴀᴀᴀ ᴛᴇʀʏ ᴍᴀᴀ ᴄᴜᴅ ɢᴀɪ",
        "ᴛᴜ ᴄʜᴜᴅ ɢʏᴀᴀᴀᴀᴀ",
        "ʀᴀɴᴅɪ ᴋʜᴀɴᴇ ᴋɪ ᴜʟᴀᴅᴅᴅ",
        "ꜱᴀᴅɪ ʜᴜɪ ɢᴀᴀɴᴅ",
        "ᴛᴇʀɪ ɢᴀᴀɴᴅ ᴍᴀɪɴ ᴋᴜᴛᴇ ᴋᴀ ʟᴜɴᴅ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴀ ʙʜᴏꜱᴅᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ",
        "ᴛᴇʀᴇ ɢᴀᴀɴᴅ ᴍᴇɪɴ ᴋᴇᴇᴅᴇ ᴘᴀᴅᴀʏ",
        "ɴʏ ɴʏ ᴛᴇʀʏ ᴍᴀᴀ ʀᴀɴᴅɪ",
        "ꜱᴜɴɴ ᴍᴀᴅᴇʀᴄʜᴏᴅ ᴛᴍʟ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴀ ʙʜᴏꜱᴅᴀ",
        "ʙᴇʜᴇɴ ᴋ ʟᴜɴᴅ ᴄʜᴜᴘᴄʜᴀᴘ ᴄᴜᴅ ʏʜᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴀ ᴄʜᴜᴛ ᴋɪ ᴄʜᴛɴɪɪɪɪ",
        "ᴍᴇʀᴀ ʟᴀᴡᴅᴀ ʟᴇʟᴇ ᴛᴜ ᴀɢᴀʀ ᴄʜᴀɪʏᴇ ᴛᴏʜ",
        "ᴄʜᴜᴘ ɢᴀᴀɴᴅᴜ",
        "ᴄʜᴜᴘ ᴄʜᴜᴛɪʏᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴘᴇ ᴊᴄʙ ᴄʜᴀᴅʜᴀᴀ ᴅᴜɴɢᴀ",
        "ꜱᴀᴍᴊʜᴀᴀ ʟᴀᴡᴅᴇ",
        "ʏᴀ ᴅᴜ ᴛᴇʀɪ ɢᴀᴀɴᴅ ᴍᴇ ᴛᴀᴘᴀᴀ ᴛᴀᴘ��",
        "ᴛᴇʀɪ ʙᴇʜᴇɴ ᴍᴇʀᴀ ʀᴏᴢ ʟᴇᴛɪ ʜᴀɪ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴇ ꜱᴀᴀᴛʜ ᴍᴍꜱ ʙᴀɴᴀᴀ ᴄʜᴜᴋᴀ ʜᴜ���不�不",
        "ᴛᴜ ᴄʜᴜᴛɪʏᴀ ᴛᴇʀᴀ ᴋʜᴀɴᴅᴀᴀɴ ᴄʜᴜᴛɪʏᴀ",
        "ᴀᴜʀ ᴋɪᴛɴᴀ ʙᴏʟᴜ ʙᴇʏ ᴍᴀɴɴ ʙʜᴀʀ ɢᴀʏᴀ ᴍᴇʀᴀ�不",
        "ᴛᴇʀɪɪɪɪɪɪ ᴍᴀᴀᴀᴀ ᴋɪ ᴄʜᴜᴛᴛᴛ ᴍᴇ ᴀʙᴄᴅ ʟɪᴋʜ ᴅᴜɴɢᴀ ᴍᴀᴀ ᴋᴇ ʟᴏᴅᴇ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ʟᴇᴋᴀʀ ᴍᴀɪ ꜰᴀʀᴀʀ",
        "ᴛᴇʀʏ ᴍᴀᴀ ʀᴀɴɪᴅɪɪɪ",
        "ᴄʜᴜᴘ ʙᴀᴄʜᴇᴇ ᴛᴍᴋᴄ",
        "ᴛᴇʀʏ ᴍᴀᴋᴏᴄʜᴏᴅᴜ",
        "ʀᴀɴᴅɪ ᴍᴀᴀ ᴛᴇʀʏ",
        "ᴛᴜ ʀᴀɴᴅɪ ᴋᴇ ᴘɪʟʟᴀ ᴇʏ",
        "ᴛᴇʀɪɪɪɪɪ ᴍᴀᴀᴀ ᴋᴏ ʙʜᴇᴊᴊᴊ",
        "ᴛᴇʀᴀᴀ ʙᴀᴀᴀᴀᴘ ʜᴜ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴍᴇ ʜᴀᴀᴛ ᴅᴀᴀʟʟᴋᴇ ʙʜᴀᴀɢ ᴊᴀᴀɴᴜɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ꜱᴀʀᴀᴋ ᴘᴇ ʟᴇᴛᴀᴀ ᴅᴜɴɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ɢʙ ʀᴏᴀᴅ ᴘᴇ ʟᴇᴊᴀᴋᴇ ʙᴇᴄʜ ᴅᴜɴɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴍÉ ᴋᴀᴀʟɪ ᴍɪᴛᴄʜ",
        "ᴛᴇʀɪ ᴍᴀᴀ ꜱᴀꜱᴛɪ ʀᴀɴᴅɪ ʜᴀɪ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴍᴇ ᴋᴀʙᴜᴛᴀʀ ᴅᴀᴀʟ ᴋᴇ ꜱᴏᴜᴘ ʙᴀɴᴀᴜɴɢᴀ ᴍᴀᴅᴀʀᴄʜᴏᴅ",
        "ᴛᴇʀɪ ᴍᴀᴀᴀ ʀᴀɴᴅɪ ʜᴀɪ",
        "ᴛᴇʀɪ ᴍᴀᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴍᴇ ᴅᴇᴛᴏʟ ᴅᴀᴀʟ ᴅᴜɴɢᴀ ᴍᴀᴅᴀʀᴄʜᴏᴅ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴀᴀᴀ ʙʜᴏꜱᴅᴀᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴍᴇ ʟᴀᴘᴛᴏᴘ",
        "ᴛᴇʀɪ ᴍᴀᴀ ʀᴀɴᴅɪ ʜᴀɪ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ʙɪꜱᴛᴀʀ ᴘᴇ ʟᴇᴛᴀᴀᴋᴇ ᴄʜᴏᴅᴜɴɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ᴀᴍᴇʀɪᴄᴀ ɢʜᴜᴍᴀᴀᴜɴɢᴀ ᴍᴀᴅᴀʀᴄʜᴏᴅ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋɪ ᴄʜᴜᴛ ᴍᴇ ɴᴀᴀʀɪʏᴀʟ ᴘʜᴏʀ ᴅᴜɴɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴇ ɢᴀɴᴅ ᴍᴇ ᴅᴇᴛᴏʟ ᴅᴀᴀʟ ᴅᴜɴɢᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀᴀ ᴋᴏ ʜᴏʀʟɪᴄᴋꜱ ᴘɪʟᴀᴜɴɢᴀ ᴍᴀᴅᴀʀᴄʜᴏᴅ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ꜱᴀʀᴀᴋ ᴘᴇ ʟᴇᴛᴀᴀᴀ ᴅᴜɴɢᴀᴀᴀ",
        "ᴛᴇʀɪ ᴍᴀᴀ ᴋᴀᴀ ʙʜᴏꜱᴅᴀ",
        "ᴍᴇʀᴀᴀᴀ ʟᴜɴᴅ ᴘᴀᴋᴀᴅ ʟᴇ ᴍᴀᴅᴀʀᴄʜᴏᴅ",
        "ᴄʜᴜᴘ ᴛᴇʀɪ ᴍᴀᴀ ᴀᴋᴀᴀ ʙʜᴏꜱᴅᴀᴀ",
        "ᴛᴇʀɪɪɪ ᴍᴀᴀ ᴄʜᴜꜰ ɢᴇʏɪɪ ᴋʏᴀᴀᴀ ʟᴀᴡᴅᴇᴇᴇ",
        "ᴛᴇʀɪɪɪ ᴍᴀᴀ ᴋᴀᴀ ʙᴊꜱᴏᴅᴀᴀᴀ",
        "ᴍᴀᴅᴀʀxʜᴏᴅᴅᴅ",
        "ᴛᴇʀɪᴜᴜɪ ᴍᴀᴀᴀ ᴋᴀᴀ ʙʜꜱᴏᴅᴀᴀᴀ",
        "ᴛᴇʀɪɪɪɪɪɪ ʙᴇʜᴇɴɴɴɴ ᴋᴏ ᴄʜᴏᴅᴅᴅᴜᴜᴜᴜ ᴍᴀᴅᴀʀxʜᴏᴅᴅᴅᴅ",
        "ᴛᴜ ɴɪᴋᴀʟ ᴍᴀᴅᴀʀᴄʜᴏᴅ",
        "ᴄʜᴜᴘ ʀᴀɴᴅɪ ᴋᴇ ʙᴀᴄʜᴇ",
        "ᴛᴇʀᴀ ᴍᴀᴀ ᴍᴇʀɪ ᴊᴀᴀɴ ᴇʏ",
        "ᴛᴇʀɪ ꜱᴇxʏ ʙᴀʜᴇɴ ᴋɪ ᴄʜᴜᴛ ᴏᴘ"
        "👩🏿      👩🏻‍🦳        👵🏼         👱🏿‍♀️     \n👖      👖        👖         👖     \n\nतेरी बहन /तेरी माँ /तेरी दादि/ तेरीभुआ.\n\nसब की 𝐂hu𝐃𝐀i hogi",
        "तेरी माँ के（ ͜.人 ͜.）दबा दूंगा",
        "तेरी मा चुदी हुई थी\nचुदी हुई है\nऔर चुदी हुई रहेगी \n\n\"MARK MY WORD\" 😈",
        "𝐊ʏᴀ?\n𝐂ʏᴀ?\n𝐂ᴜᴀ?\n\n𝐌ᴛᴛ 𝐊ʀʀ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ɪ 𝐂ʜᴜᴛ 𝐏𝐞 𝐓ʜ𝐀ᴘᴘᴀᴅ 𝐌ᴀ𝐚ʀ 𝐃ᴜɴɢᴀ",
        "˚∧＿∧  　+        — ͟͞͞🥛\n(  •‿• )つ  — ͟͞͞ 🥛 \nSpecial attack tery mummy ke chuchiya ka dudu 🐱🎀",
        "Aaj Rakshabandhan Ke Avsar Pr तेरी मांँ मेरे लंड पर राखी Bandh Ke चुदेगी 😍🥰",
        "Sun दोस्त terko ye तीन चीजे कभी nahi भूलनी chaiye 😁👇🏻🤙🏿\n\n1 :- तेरी औकात\n2 :- तेरी बहन का फटा bhosda\n3 :- तेरी मां के भोसड़े में मेरा मूत",
        "Tery Maa Behen Ke Boshde Me Kya Maarun Jaldi Bata 😜🤙",
        "Tery Maa\nⓘ Verified Randy // 🦅🔥",
        "𝐒ᴀʏ 𝐑ᴀɴᴅɪʙᴀᴀᴢ 𝐃ᴀᴅᴅʏ 𓆩💗𓆪",
        "𝐖ᴏ ʙʜɪ ᴋʏᴀ ᴅɪɴ ᴛʜᴇ ᴊᴀʙ ᴛʀʏ ᴍᴀᴀ ᴍᴜᴊʜᴇ 𝐀ᴘɴᴀ 𝐂ʜᴜᴛ 𝐃ᴇᴛɪ ᴛʜɪ ʏᴀᴀʀ 💔🥀👌🏻",
        "𝐀ᴡᴀᴢ 𝐍ɪᴄʜᴇ 𝐆ᴜʟᴀᴀᴍ 🤢👇🏻",
        "𝐓ʀʏ 𝐌ᴀᴀ ɴᴇ 𝐂ʜᴜᴅɴᴇ 𝐌ᴀɪ ɢᴏʟᴅ 𝐌ᴇᴅᴀʟ 𝐉ᴇᴇᴛᴀ ᴇʏ 𝐃ᴏꜱᴛ 🤩👑",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴛ 𝐌ᴇ 𝐌ᴇʀᴀ 𝐋ᴜɴᴅ 🖕🏻😈",
        "𝐁ʜᴏꜱᴀᴅɪᴋᴇ 𝐀ᴘɴɪ 𝐁ᴇʜᴇɴ 𝐂ʜᴜᴅᴀ 🖕🏻😈",
        "𝐑ᴀɴᴅɪ ᴋᴇ 𝐁ᴀᴄᴄʜᴇ 𝐀ᴜᴋᴀᴛ 𝐌ᴇ 𝐑ᴇʜ 🖕🏻😈",
        "𝐌ᴀᴅᴀʀᴄʜᴏᴅ 𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴛ 🖕🏻😈",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋᴀ 𝐁ʜᴏꜱᴅᴀ ᴋʜᴏʟ ᴅᴜɴɢᴀ 🔓😈",
        "𝐁ʜᴇɴᴄʜᴏᴅ ??ᴘɴɪ 𝐀ᴜᴋᴀᴛ 𝐌ᴇ 𝐑ᴇʜ 🤡💩",
        "𝐓𝐌𝐊𝐂 ᴘᴇ 𝐂ʜᴀᴘᴘᴀʟ 𝐌ᴀᴀʀᴜɴɢᴀ 👟💥",
        "𝐁ʜᴏꜱᴅɪᴋᴇ 𝐓ᴇʀɪ 𝐊ʜᴀɴᴅᴀɴ ᴋɪ 𝐁𝐊𝐂 💀🖕🏻",
        "𝐑ᴀɴᴅɪ ᴋɪ 𝐀ᴜʟᴀᴅ ᴄʜᴜᴘ ʜᴏ ᴊᴀ 🔇😒",
        "𝐑ᴀɴᴅɪʙᴀᴀᴢ ka 𝐆ᴜʟᴀᴀᴍ ey ᴛᴜ ᴀʙ ᴛᴜ ʏʜᴀ ᴄᴜᴅᴋᴇ ᴅɪᴋʜᴀ ᴛᴇʀʏ ᴍᴀᴋᴏ ʟᴇᴋʀ 👑😎",
        "𝐓ᴇʀɪ 𝐁ᴇʜᴇɴ ᴋɪ 𝐂ʜᴜᴛ 𝐌ᴇ 𝐌ɪʀᴄʜɪ 🌶️🖕🏻",
        "𝐌ᴀᴅᴀʀᴄʜᴏᴅ 𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴛ 𝐌ᴇ 𝐏ᴀɪʀ 🦶🏻😈",
        "𝐁ʜᴏꜱᴀᴅɪᴋᴇ 𝐓ᴇʀɪ 𝐁ᴇʜᴇɴ ᴋᴀ 𝐁ʜᴏꜱᴅᴀ 🗑️😏",
        "𝐑ᴀɴᴅɪ ᴋᴀ 𝐏ɪʟʟᴀ ʜᴀɪ ᴛᴜ 🐕💩",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋᴏ 𝐁ᴀᴢᴀᴀʀ 𝐌ᴇ 𝐂ʜᴏᴅᴜɴɢᴀ 🌃😈",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴛ 𝐌ᴇ 𝐆ᴀʀᴀᴍ 𝐓ᴇʟ 🌡️🖕🏻",
        "𝐌ᴀᴅᴀʀᴄʜᴏᴅ 𝐓ᴇʀɪ 𝐁ᴇʜᴇɴ ᴍᴇʀɪ 𝐑ᴀɴᴅɪ 💋👿",
        "𝐑ᴀɴᴅɪ ᴋᴇ 𝐁ᴀᴄᴄʜᴇ 𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴛ 🖕🏻😈",
        "𝐓ᴇʀɪ 𝐁ᴇʜᴇɴ ᴋᴏ 𝐑ᴀᴀᴛ ʙʜᴀʀ 𝐂ʜᴏᴅᴜɴɢᴀ 🌙😈",
        "𝐑ᴀɴᴅɪ ᴋᴀ 𝐁ᴀᴄᴄʜᴀ ʜᴀɪ ᴛᴜ ꜱᴀᴀʟᴇ 🤡💀",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴛ 𝐌ᴇ 𝐌ᴇʀᴀ 𝐉ᴏᴏᴛᴀ 👞🖕🏻",
        "𝐑ᴀɴᴅɪʙᴀᴀᴢ 𝐃ᴀᴅᴅʏ ᴋᴀ 𝐆ᴜʟᴀᴀᴍ ʜᴀɪ ᴛᴜ 🥀😤",
        "ᴊɪꜱ ᴅɪɴ ᴛᴜ ᴘᴀɪᴅᴀ ʜᴜᴀ 𝐓ᴇʀɪ 𝐌ᴀᴀ ɴᴇ ꜱᴏᴄʜᴀ ᴛʜᴀ ᴋᴀꜱʜ ᴀʙᴏʀᴛ ᴋᴀʀ ᴅᴇᴛɪ 💀🥀",
        "𝐀ᴘɴɪ 𝐀ᴜᴋᴀᴛ ᴅᴇᴋʜ ᴋᴜᴛᴛᴇ 𝐓ᴇʀʏ 𝐌ᴀ 𝐂ᴜᴅ 𝐑ʜɪ🐕😂",
        "𝐓ᴇʀʏ 𝐌ᴀ 𝐂ᴜᴅ 𝐑ʜɪ 𝐆ᴀʟɪ ᴋᴀ 𝐊ᴜᴛᴛᴀ ʜᴀɪ ᴛᴜ 🐕🗑️",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ɴᴇ ᴍᴜᴊʜᴇ ᴅᴇᴋʜ ᴋᴇ ꜱᴏᴄʜᴀ ᴋᴀꜱʜ ʏᴇ ᴍᴇʀᴀ ʙᴇᴛᴀ ʜᴏᴛᴀ 🫦😏",
        "𝐂ʜᴜᴘ ᴋᴀʀ 𝐌ᴀᴅᴀʀᴄʜᴏᴅ ᴛᴇʀɪ ᴀᴜᴋᴀᴛ ɴᴀʜɪ ᴍᴇʀᴇ ꜱᴀᴀᴍɴᴇ ʙᴏʟɴᴇ ᴋɪ 🤐💀",
        "𝐓ᴇʀɪ 𝐌ᴀᴀ ᴋɪ 𝐂ʜᴜᴅᴀɪ ᴍᴇ ᴊᴀʙ ᴍᴀɪ ᴛʜᴀ ᴛᴏ ᴛᴜ ᴘᴀɪᴅᴀ ʜᴜᴀ 💀😂",
        "𝐁ʜᴀɢ ʏᴀʜᴀɴ ꜱᴇ ᴋᴜᴛᴛᴇ ᴋᴇ ᴘɪʟʟᴇ 🐕💨",
        "𝐓ᴇʀɪ 𝐁ᴇʜᴇɴ ᴋɪ ꜱᴀᴅɪ 𝐌ᴇ ᴍᴇʀᴀ ʟᴜɴᴅ 💍😈",
        "𝐌ᴀᴅᴀʀᴄʜᴏᴅ ᴀᴘɴɪ 𝐌ᴀᴀ ᴍᴀᴛ ᴄʜᴜᴅᴀ 🖕🏻👹",
        "𝐁ʜᴇɴᴄʜᴏᴅ 𝐓ᴇʀɪ 𝐊ʜᴀɴᴅᴀɴ ᴋɪ 𝐁𝐊𝐂 💀🖕🏻",
        "tery ma cudke pgl dekh..𝐁𝐊𝐂 🦴🐕",
        "𝐊ʏᴀ 𝐑ᴇ 𝐑ᴀɴᴅɪᴋᴇ 𝐂ᴏᴏʟ 𝐁ᴀɴᴇɢᴀ 𝐓ᴜ 𝐂ʜᴀʟ 𝐀ʙ 𝐂ʜᴜᴅ 𝐀ᴘɴᴇ 𝐁ᴀᴀᴘ - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 𝐒ᴇ - 🦢💘",
        "tery 𝐌ᴀᴀ cudke 𝐌ᴀʀʀ  𝐆ᴀʏɪ 𝐘ᴀᴀʀ - 𝐉ᴀɪ - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 ! 🌙",
        "acha beta 😂🔥👊🏻 ? coi na me toh HATER codunga tery mako 😹💔🔥😆👊🏻💥",
        "chudke bhaga kaise 😂💥🤣🤘🏻",
        "ne toh - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 ka lun muh me lelia tune or tery maa ne😂🙏🏻😂🙏🏻",
        "try maa सूर्य☀ nikalte hi pel du 😹🔥💔",
        "mkl lun te vaj 😂✊🏻💦",
        "𝗧ᴍᴋ𝗕 pe - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 ka hamla 😂⚔🔥💥",
        "𝐂ʜʟ 𝐇ᴀʀᴍᴢᴀᴅ𝐈 𝐊ᴇ लड़के 💛🤍🩵",
        "oi 𝐓ᴇʀɪ 𝐌‌ᴀᴀ गुलाम ₰🖤",
        "chl rndyce chud ke dikha 😂💥🤣🔥",
        "tery 𝐌ᴀᴀ or bhen 𝐌ᴀʀʀ  𝐆ᴀʏɪ naacho 💃🏻💃🏻🕺🏻🎶😂😆💞🔥 !",
        "tera baap bass - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 ey 😂🎀",
        "try maa hagte hue paad mari -#😹🔥🥀",
        "𝐓ᴇʀɪ 𝐌ᴜᴍᴍʏ 𝐂ʜᴏᴅ 𝐃ɪ - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 𝐍ᴇ 𝐁ᴡᴀʜᴀʜᴀʜᴀ ⚜",
        "⋆｡ﾟ☁︎｡𝐂ʏᴜ 𝐑ᴇ मदरचोद - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 बाप के सामने 𝐅ʏᴛᴇʀ 𝐁ᴀɴᴇɢᴀ ⋆𓂃 ོ☼𓂃 😂🔥",
        "नहीं नहीं तेरी मां को 𝐒ɪʀғ - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 बाप चोद सकता है ִֶָ𓂃 ࣪ ִֶָ👑་༘࿐ sᴀᴍᴊʜᴀ ʀᴀɴᴅɪᴋᴇ ???",
        "तेरी मां का 𝐒ᴛʏʟɪsʜ भोसड़ा 😱",
        "𝑻𝒆𝒓?? 𝒎𝒂𝒂 𝒓𝒂𝒏𝒅𝒂𝒍 𝒉 𝒃𝒂𝒔 𝒃𝒂𝒂𝒕 𝒌𝒉𝒂𝒕𝒂𝒎 😡🔥",
        "सोच तेरी बहन को - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 बाप का गुलाम चोद रहा 😎🔥",
        "Hello hello?? Oxygen aarahi है? रण्डी पुत्र 🧘🏻",
        "Shut up रंडीके वरना दुनिया यही बोलेगी तेरी बहन - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 /~ 👑 बाप से सही chudi 🥵🔥",
        "ᴛᴜ ᴏʀ ᴛᴇʀɪ ᴍᴀᴀ ᴅᴏɴᴏ - 𝐑𝐀𝐍𝐃𝐈𝐁𝐀𝐀𝐙 बाप के ʟɴᴅ sᴇ ᴋᴀʙʜɪ ᴜᴛʜ ɴʜɪ ᴘᴀʏᴇ 😂🔥",
        "🇮🇳𝐵𝐻𝐴𝑅𝐴𝑇 𝐻𝐴𝑀𝐴𝑅𝐴 𝐷𝐸𝑆𝐻 𝐻 𝐴𝑈𝑅 𝑈𝑆 𝐷𝐸𝑆𝐻 𝑀𝐸 तेरी मां घर घर जाके MOAN करती है ! 🛐",
        "Tᴇʀɪ Mᴀᴀ Rᴀɴᴅɪ (🩷)—(❤️)—(🧡)—(💛)—(💚)—(🩵)—(💙)—(💜)—(🖤)—(🩶)—(🤍)—(🤎)—(🌸)—(✨)—(🌙)—(⭐)—(🦋)—(💎)—(👑)—(⚡)—(🔥)—(🌌)—(🎀)—(💫)—(🪽)—(🫧)—(🌸)—(💘)—(💓)—(💖)—(💕)—(💞)",
        "Teri make hath me chakku se hole karke lund daluga apna 🤢🤢",
        "Subha ho ya sham chudte rhena hai teri maaka kaam😂🔥😂🔥😂🔥",
        "𝐓ᴜ 𝐒ᴡɪᴘᴇ 𝐊ᴀʀᴛᴀ 𝐑ᴇʜ 𝐌ᴀɪ ᴄʜᴀʟᴀ 𝐓ᴇʀɪ 𝐁ᴇʜᴇɴ ᴋᴇ 𝐒ᴀᴛʜ 𝐊ʜᴇʟɴᴇ 😭😭",
        "🍑\n🟨  😂\n🟨🟥🟥🟨\n     🟥🟥🟨\n     ⬛⬛ \n     ⬛⬛\nTery ma ki bund hi okhad li.",
        "𝘗𝘺𝘢𝘴 𝘭𝘢𝘨 𝘳𝘢𝘩𝘪 𝘵𝘦𝘳𝘪 𝘮𝘢𝘢 𝘬𝘰 𝘤𝘰𝘥 𝘬𝘦 𝘱𝘺𝘢𝘴 𝘣𝘶𝘫𝘩𝘢𝘶𝘯𝘨𝘢 🖕🏿😂🔥🙏🏿",
        "▶︎ •၊၊၊|။||။‌‌‌‌‌၊|• 0:60\n𝘋𝘦𝘬𝘩 𝘵𝘦𝘳𝘪 𝘣𝘦𝘩𝘦𝘯 ??𝘪 𝘤𝘩𝘪𝘬𝘩 😂😱🔥🙏🏿",
        "      ᴹᴱ:\n👆       🤬 ᴷᴬᴴᴬ ᴮᴴᴬᴳᵀᴵ ᴴᴬᴵ ᴿᴬᴺᴰᴵ\n  🐛💤👔🤳\n            ⛽  👢\n          ⚡👟\n       🎸    🌂\n      👢       👢     ᵀᴱᴿᴵ ᴹᴬᴬ:🏃‍♀‍➡️ᴹᵁᴶᴴᴱ ᴹᴬᵀ ᶜᴴᴼᴰᴼ",
        "🙌\n😛 ᴹᴱ:\n  |      👩 ᵀᴱᴿᴵ ᴹᴬᴬ:\n  |   8_/ 👐\n / \\  / \\\n  \"Take a look how i am chodunging your Mummy in ghodi pose 🗿\"",
        "../\\_/\\\n  ( • _ •)  \n  /    >🍆 \n\nʏᴇ ᴘᴀᴋᴀᴅᴏ ᴀᴘᴋɪ ᴍᴏᴍ ᴋᴏ ᴀᴘɴᴇ ᴄʜᴜᴛ ᴍᴇ ɢʜᴜssᴀ ɴᴇ ᴍᴇ ᴋᴀᴀᴍ ᴀʏᴇɴɢᴀ 🤗",
        "ㅤㅤ😎 ᴹᴱ:\n          |\\👐\n         / \\_\n━━━━━┓ ＼＼\n┓┓┓┓┓┃ᵀᴼᴴᴬᴿ ᴿᴬᴺᴰᴵ ᴹᴬᴬ:\n┓┓┓┓┓┃ ヽ😩ノ\n┓┓┓┓┓┃ 　 /　ᴼᴿᴵᴵ ᴬᴹᴹᴬ\n┓┓┓┓┓┃  ノ)　\n┓┓┓┓┓┃\n\nLE TERI MAA KO CHOD KAR FHEK DIA 🥸",
        "😎 ᴍᴀɪ:\nく|)へ\n   〉\n￣┗┓       ヾ😫ｼ ᴛᴇʀɪ ᴍᴀᴀ:\n         ┗┓   ヘ/    \n             ┗┓ノ\n                 ┗┓       ヾ😨ｼ ᴛᴇʀᴀ ʙᴀᴀᴘ:\n                      ┗┓   ヘ/\n                          ┗┓ノ\n                               ┗┓       ヾ😩ｼ ᴛᴇʀᴀ ᴄʜᴀᴄʜᴀ:\n                                   ┗┓   ヘ/    \n                                       ┗┓ノ\nᴅᴇᴋʜ ᴀɪsᴇ ʜɪ ʟᴀᴀᴛ ᴍᴀᴀʀ ᴋᴀʀ ʙʜᴀɢᴀᴜɴɢᴀ ᴛᴇʀᴇ ᴋʜᴀᴀɴᴅᴀɴ ᴋᴏ 🤫🤣",
        "╭👇 ͡ ͡° ͜   ͡ ͡°)╭👇 \n      \\   .   .\\\n        \\        \\\n         \\╰[ ]╯\\ \n          /   U   \\\n       👟       👟\n\nᴛᴇʀɪ ᴍᴀᴀ ᴋᴏ ᴍᴇʀᴀ ʟᴜɴᴅ ᴍᴜʙᴀʀᴀᴋ ʜᴏ 😝",
        "Once a man said: \n\"You deserve all the chudayi and teri maa ki chutt dhulayi, and this text proves it! You should be proud!\" 🕊️",
        "😏 ᴍᴀɪ:\n    | 👐💵\n    |//    💵\n    |          💸 ᴛᴇʀɪ ʀᴀɴᴅʏ ᴍᴀᴀ:\n   /\\            👯👯\n👟👟\n\nDᴇᴋʜ Kᴇsᴇ Tᴇʀɪ Mᴀᴀ Kᴏ Aᴘɴᴇ Pᴀɪsᴏ Sᴇ Rᴀɴᴅɪ Nᴀᴄʜ Kᴀʀᴡᴀ Rʜᴀ Hᴜ 🤙😎",
        "Loading your maa ki chudai video 😳\n\n■■■■■■■■□\n99%",
        "Sun दोस्त terko ye तीन चीजे कभी nahi भूलनी chaiye  😁👇🏻🤙🏿\n\n1 :- तेरी औकात\n2 :- तेरी बहन का फटा bhosda\n3 :- तेरी मां के भोसड़े में मेरा मूत",
        "this message could't be display because teri maa randy ey",
        "𓂃☁︎ 𓂃𝐒ɪᴅᴇ 𝐇ᴀᴛ 𝐆ᴜʟᴀᴍ 𝐓ᴇʀʏ 𝐌ᴀᴀ 𝐊ᴏ 𝐂ʜᴏᴅɴᴇ  मेरी रेलगाड़ी आ रही .-‘🚂-‘.ᯓᡣ𐭩______ 𓂃☁︎ 𓂃",
        "˙✧˖°📷༘ ⋆｡° 𝐓ᴇʀʏ 𝐌ᴀ  𝐊ᴀ 𝐂ʜɪʟᴅ 𝐏ᴏʀɴ 𝐑ᴇᴄᴏʀᴅ 𝐇ᴏɢʏᴀ 𝐀ʙ 𝐓ᴏ 𝐒ɪᴅʜᴀ 𝐕ɪʀᴀʟ 𝐇ᴏɢᴀ 𝐘ᴇ ˙✧˖°📷༘ ⋆｡°",
        "𓂃✍︎ 𝑵ʏ 𝑵ʏ 𝑨ʙ 𝑲ᴜᴄʜ 𝑵ʏ 𝑯ᴏ 𝑺ᴋᴛᴀ 𝑻ᴇʀɪ  𝑪ᴜᴅᴀɪ 𝑲ɪ 𝑺ᴄʀɪᴘᴛ 𝑨ʙ 𝑳ᴇᴀᴋ 𝑯ᴏᴋᴇ 𝑯ʏ 𝑴ᴀɴᴇɢɪ 𓂃✍︎",
        "⋆⭒˚.⋆🔭 𝐒ʜᴜᴛ 𝐔ᴘ 𝐑ᴀɴᴅɪᴋᴇ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ɪ 𝐂ʜᴜᴅᴀɪ 𝐄ɴᴊᴏʏ 𝐊ʀ 𝐑ᴀʜᴀ 𝐓ᴇʟᴇ𝐒ᴄᴏᴘᴇ 𝐒ᴇ⋆⭒˚.⋆🔭",
        "तेरे मां के दूदू के बीच मेरा lund fas gaya oops 🤪（ ͜.🍆 ͜.）",
        "𝐓ᴇʀʏ 𝐁ʜᴇ𝐍 𝐊ᴇ ( ͜. ㅅ ͜. )🥛 ʏᴜᴍᴍʏ ",
        "𓂃☁︎ 𓂃𝐒ɪᴅᴇ 𝐇ᴀᴛ 𝐆ᴜʟᴀᴍ 𝐓ᴇʀʏ 𝐌ᴀᴀ 𝐊ᴏ 𝐂ʜᴏᴅɴᴇ  मेरी रेलगाड़ी आ रही .-‘🚂-‘.ᯓᡣ𐭩______ 𓂃☁︎ 𓂃",
        "˙✧˖°📷༘ ⋆｡° 𝐓ᴇʀʏ 𝐌ᴀ  𝐊ᴀ 𝐂ʜɪʟᴅ 𝐏ᴏʀɴ 𝐑ᴇᴄᴏʀᴅ 𝐇ᴏɢʏᴀ 𝐀ʙ 𝐓ᴏ 𝐒ɪᴅʜᴀ 𝐕ɪʀᴀʟ 𝐇ᴏɢᴀ 𝐘ᴇ ˙✧˖°📷༘ ⋆｡°",
        "𓂃✍︎ 𝑵ʏ 𝑵ʏ 𝑨ʙ 𝑲ᴜᴄʜ 𝑵ʏ 𝑯ᴏ 𝑺ᴋᴛᴀ 𝑻ᴇʀɪ  𝑪ᴜᴅᴀɪ 𝑲ɪ 𝑺ᴄʀɪᴘᴛ 𝑨ʙ 𝑳ᴇᴀᴋ 𝑯ᴏᴋᴇ 𝑯ʏ 𝑴ᴀɴᴇɢɪ 𓂃✍︎",
        "⋆⭒˚.⋆🔭 𝐒ʜᴜᴛ 𝐔ᴘ 𝐑ᴀɴᴅɪᴋᴇ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ɪ 𝐂ʜᴜᴅᴀɪ 𝐄ɴᴊᴏʏ 𝐊ʀ 𝐑ᴀʜᴀ 𝐓ᴇʟᴇ𝐒ᴄᴏᴘᴇ 𝐒ᴇ⋆⭒˚.⋆🔭",
        "तेरे मां के दूदू के बीच मेरा lund fas gaya oops 🤪（ ͜.🍆 ͜.）",
        "𝐓ᴇʀʏ 𝐁ʜᴇ𝐍 𝐊ᴇ ( ͜. ㅅ ͜. )🥛 ʏᴜᴍᴍʏ ",
        "𓂃☁︎ 𓂃𝐒ɪᴅᴇ 𝐇ᴀᴛ 𝐆ᴜʟᴀᴍ 𝐓ᴇʀʏ 𝐌ᴀᴀ 𝐊ᴏ 𝐂ʜᴏᴅɴᴇ  मेरी रेलगाड़ी आ रही .-‘🚂-‘.ᯓᡣ𐭩______ 𓂃☁︎ 𓂃",
        "˙✧˖°📷༘ ⋆｡° 𝐓ᴇʀʏ 𝐌ᴀ  𝐊ᴀ 𝐂ʜɪʟᴅ 𝐏ᴏʀɴ 𝐑ᴇᴄᴏʀᴅ 𝐇ᴏɢʏᴀ 𝐀ʙ 𝐓ᴏ 𝐒ɪᴅʜᴀ 𝐕ɪʀᴀʟ 𝐇ᴏɢᴀ 𝐘ᴇ ˙✧˖°📷༘ ⋆｡°",
        "𓂃✍︎ 𝑵ʏ 𝑵ʏ 𝑨ʙ 𝑲ᴜᴄʜ 𝑵ʏ 𝑯ᴏ 𝑺ᴋᴛᴀ 𝑻ᴇʀɪ  𝑪ᴜᴅᴀɪ 𝑲ɪ 𝑺ᴄʀɪᴘᴛ 𝑨ʙ 𝑳ᴇᴀᴋ 𝑯ᴏᴋᴇ 𝑯ʏ 𝑴ᴀɴᴇɢɪ 𓂃✍︎",
        "⋆⭒˚.⋆🔭 𝐒ʜᴜᴛ 𝐔ᴘ 𝐑ᴀɴᴅɪᴋᴇ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ɪ 𝐂ʜᴜᴅᴀɪ 𝐄ɴᴊᴏʏ 𝐊ʀ 𝐑ᴀʜᴀ 𝐓ᴇʟᴇ𝐒ᴄᴏᴘᴇ 𝐒ᴇ⋆⭒˚.⋆🔭",
        "🇮🇳 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐈ɴᴅɪᴀ 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇮🇳",
        "🇯🇵 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐉ᴀᴘᴀɴ 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇯🇵",
        "🇺🇸 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐔𝐒𝐀 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇺🇸",
        "🇬🇧 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐔𝐊 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇬🇧",
        "🇰🇷 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐊ᴏʀᴇᴀ 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇰🇷",
        "🇩🇪 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐆ᴇʀᴍᴀɴʏ 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇩🇪",
        "🇫🇷 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐅ʀᴀɴᴄᴇ 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇫🇷",
        "🇮🇹 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐈ᴛᴀʟʏ 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇮🇹",
        "🇧🇷 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐁ʀᴀᴢɪʟ 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇧🇷",
        "🇨🇦 ✦ 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ᴇ 𝐒ᴀᴛʜ  ⚡️ZYЯΣX ✕ ΛΣƬΉΣЯ⚡️  𝐁ᴀᴀᴘ 𝐀ᴜʀ  𝐂ᴀɴᴀᴅᴀ 𝐖ᴀʟᴇ 𝐁ʜɪ 𝐂ʜɪʟʟ 𝐊ᴀʀ 𝐑ʜᴇ ✦ 🇨🇦",
        "𓂃˖˳·˖ ִֶָ ⋆🧡͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚🧡 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆💛͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚💛 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆💚͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚💚 ݁˖⭑.ᐟ",
        "𓂃˖˳·˖ ִֶָ ⋆💙͙⋆ ִֶָ˖·˳˖𓂃 ִֶָ⁀➴༯ 𝐒𝐋𝐀𝐕𝐄 ִֶָ. ..𓂃 ࣪ ִֶָ🌈་༘࿐ 𝐓𝐌𝐊𝐂 -/- ⋆˚💙 ݁˖⭑.ᐟ",
        ]

        # ─── FUN RAIDS TEXT LISTS (Menu8) ──────────────────────────────────────

        shayari_texts = [
        "तेरी आँखों में खोया रहूँ, तू मिले तो ये जहाँ भूल जाऊँ। 💕",
        "प्यार में क्या रखा है, बस तेरे बिना लगता है जीना भी सज़ा नहीं। 💔",
        "चाँद से खूबसूरत है तेरा चेहरा, तू है तो दुनिया लगती है मेरी। 🌙",
        "तेरी यादों में खोया रहूँ, हर सांस में तू बसी है। 💭",
        "हर दिन तुझसे प्यार बढ़े, हर सांस तुझसे निभे। 💗",
        "तेरी हँसी में जान है, तेरी बातों में पहचान है। 😊",
        "तेरी बाहों में मिली राहत, तेरी आँखों में मिला सुकून। 🌹",
        "तू है तो हर ग़म भूला, तू है तो ये दिल झूला। 🎠",
        "हर रोज़ तुझसे प्यार हो, हर शाम तुझपे निसार हो। 🌅",
        "तेरी मुस्कान है जादू, जो बिखेरे हर दिन बहार। 🌺",
        "Your love is the poetry my heart always wanted to write. 📝💖",
        "In a world full of trends, I want to remain your timeless classic. 🌟",
        "You are the missing piece of my soul, the calm in my chaos. 🧩",
        "Every love story is beautiful, but ours is my favorite chapter. 📖",
        "You are the sun in my day, the moon in my night, and the stars in my dreams. 🌞🌙",
        "Meeting you was fate, becoming your friend was a choice, but falling in love with you was beyond my control. 💫",
        "I didn't choose you, my heart did. And it doesn't know how to unchoose. ❤️‍🔥",
        "You are not just my love; you are my home. 🏠",
        "Your smile is the best part of my day, and your laugh is my favorite sound. 😄🎶",
        "You are my today and all of my tomorrows. 📅❤️",
        "Teri smile dekh ke lagta hai, jaise mera wifi full signal pe aa gaya. 📶😄",
        "Pyaar kya hai? Maine tujhse jaana, tera naam sunke hi dil ho jaata hai deewana. 🫀",
        "Tu hai toh din hai, warna toh har pal hai night shift. 🌃",
        "Dil ki baat kehni thi, bas yahi socha, tujhse milke samjha, pyaar kya hai bhai! 🥰",
        "Teri ek smile pe, main de doon jaan bhi, par tu maange toh, de doon duniya bhi. 😄🌎",
        "Chand se chura ke laaya hoon, teri muskaan, rakh lo dil mein, yeh hai meri jaan. 🌙💖",
        "Tere bina dil hai veeran, tu aaja ve, dil ki yeh raah, hai bas teri hi ore. 🛤️💔",
        "Pyaar ka sabak mila, tujhse hi yaar, ab toh bas tera hi hai, yeh dil bekarar. 🫀",
        "Kya baat hai tujh mein, hai koi jaadu, dekhta hi rahu, na ho mera wajood. 👀✨",
        "Tu hi meri subah, tu hi mera sukoon, tere bina toh jaise, khaali hai yeh khwabon ka jahoon. ☁️"
        ]

        rizz_texts = [
        "क्या तुम सड़क हो? क्योंकि मैं हर दिन तुम्हें क्रॉस करना चाहता हूँ। 😏",
        "तुम्हारी हँसी सुनकर लगता है जैसे मेरा दिन बन गया। 😄",
        "तुम्हारी आँखों में खो जाऊँ तो वापस न आऊँ। 👀",
        "क्या तुम्हारे पास कोई मैप है? क्योंकि मैं तुम्हारे दिल में खो गया हूँ। 🗺️",
        "तुम बिना makeup के भी परफेक्ट हो – लेकिन मैं तो तुम्हें हर तरह से चाहता हूँ। 💋",
        "मैं तुमसे प्यार नहीं करता – मैं तो तुम्हें worship करता हूँ। 🙌",
        "तुम मेरे दिन की सबसे अच्छी notification हो। 🔔",
        "तुम मेरे सबसे पसंदीदा गाने की धुन हो। 🎶",
        "मैं तुम्हें चाँद से भी ऊपर रखता हूँ – क्योंकि तुम तो सूरज हो। ☀️",
        "तुम मेरी रूह की तसल्ली हो – बस साथ रहो। 🕊️",
        "Are you a magician? Because whenever I look at you, everyone else disappears. 🎩✨",
        "Do you have a map? I keep getting lost in your eyes. 🗺️👀",
        "Is your name Google? Because you have everything I'm searching for. 🔍💕",
        "Are you a camera? Because every time I look at you, I smile. 📸😊",
        "If beauty were a crime, you'd be serving a life sentence. ⛓️🔥",
        "Do you believe in love at first sight, or should I walk by again? 🚶‍♂️🔄",
        "Excuse me, but I think you dropped something – my jaw. 👇😮",
        "Are you Wi-Fi? Because I'm feeling a connection. 📶❤️",
        "If you were a vegetable, you'd be a cute-cumber! 🥒😉",
        "You must be a 10 because you've got me feeling like a 1 with you. 1️⃣0️⃣",
        "Tera naam kya hai? Kyunki mera plan hai tera baap banana! 😎👀",
        "Kya tum Google ho? Kyunki mujhe tum mein woh sab milta hai jo main dhundh raha tha. 🔍💕",
        "Tum toh mere WiFi jaisi ho, bina tumhare connection hi nahi aata. 📶😏",
        "Kya tum chocolate ho? Kyunki main toh din raat tumhe kha sakta hoon. 🍫😋",
        "Tumhari smile dekh ke lagta hai, mera din set aur raat forget. 🌞",
        "Main driver nahi hoon, par tumhare dil ki steering le sakta hoon? 🚗💨",
        "Kya tum Starbucks ho? Kyunki main har din tumhara naam pukaarna chahta hoon. ☕😄",
        "Meri battery low hai, kya tum mere charger ban sakte ho? 🔋❤️",
        "Kya tum doctor ho? Kyunki mera dil dekh ke toh tumne dhadkana sikha diya. 👨‍⚕️💓",
        "Tumhari height kya hai? Kyunki lagta hai tum heaven se chhidi hui ho. 📏👼"
        ]

        pickup_texts = [
        "क्या तुम्हारा नाम Google है? क्योंकि तुममें वो सब है जो मैं ढूंढ रहा हूँ। 🔍",
        "तुम्हारी आँखें तारे हैं और मैं उनमें खो जाना चाहता हूँ। ✨",
        "क्या तुम WiFi हो? क्योंकि मुझे तुमसे कनेक्शन महसूस हो रहा है। 📶",
        "तुम्हारी मुस्कान देखकर मेरा दिन बन जाता है। 😊",
        "क्या तुम चॉकलेट हो? क्योंकि मैं तुम्हें हर वक़्त खाना चाहता हूँ। 🍫",
        "तुम्हारे बिना मेरी ज़िंदगी अधूरी है। 💔",
        "तुम मेरे सपनों की रानी हो। 👑",
        "तुम्हारी बातें सुनकर दिल खुश हो जाता है। 💕",
        "क्या तुम मेरे साथ चलोगी? 🚶‍♀️",
        "तुम मेरी दुनिया हो। 🌍",
        "Are you a time traveler? Because I see you in my future. ⏳",
        "Is your name Angel? Because you fell from heaven. 👼",
        "Do you have a Band-Aid? Because I just scraped my knee falling for you. 🩹",
        "Are you a magician? Because whenever I look at you, everyone else disappears. 🎩",
        "Can I follow you home? Because my parents always told me to follow my dreams. 🏠",
        "Are you French? Because Eiffel for you. 🗼",
        "Is your name Google? Because you have everything I'm searching for. 🔍",
        "You must be a 10 because you've got me feeling like a 1 with you. 1️⃣0️⃣",
        "Roses are red, violets are blue, sugar is sweet, and so are you. 🌹",
        "I must be a snowflake because I've fallen for you. ❄️",
        "Tum toh mere WiFi jaisi ho, bina tumhare connection hi nahi aata. 📶",
        "Kya tum chocolate ho? Kyunki main toh din raat tumhe kha sakta hoon. 🍫",
        "Tumhari smile dekh ke lagta hai, mera din set aur raat forget. 🌞",
        "Meri battery low hai, kya tum mere charger ban sakte ho? 🔋",
        "Kya tum doctor ho? Kyunki mera dil dekh ke toh tumne dhadkana sikha diya. 👨‍⚕️",
        "Tumhari aankhon mein pyaar hai ya paani, maine toh dooba marne ka plan banaya. 🏊",
        "Mera DNA toh tumse match karta hai, kyunki main toh tumhara hi bana hoon. 🧬",
        "Tumse milke lagta hai jaise, sach mein pyaar hota hai. 😅",
        "Tum toh mere sapno ki rani ho. 👑",
        "Tumhari baatein sunke lagta hai, jaise koi khwab ho. 💭"
        ]

        romance_texts = [
        "तेरी आँखों की गहराई में मेरी दुनिया बसी है। 💕",
        "हर सांस में तू बसी है, तू ही मेरी हँसी है। 😊",
        "चाँद से खूबसूरत है तेरा चेहरा। 🌙",
        "तेरी यादों में खोया रहूँ। 💭",
        "प्यार का हर लम्हा तेरे साथ जीया। 🥀",
        "तेरे बिना ये दिल है बेक़रार। ❤️",
        "हर दिन तुझसे प्यार बढ़े। 💗",
        "तेरी हँसी में जान है। 😊",
        "तेरी बाहों में मिली राहत। 🌹",
        "तू है तो हर ग़म भूला। 🎠",
        "You are the poetry my heart always wanted to write. 📝",
        "In a world full of trends, I want to be your classic. 🌟",
        "You are the missing piece of my soul. 🧩",
        "Our love story is my favorite chapter. 📖",
        "You are the sun in my day, the moon in my night. 🌞🌙",
        "Falling in love with you was beyond my control. 💫",
        "I didn't choose you, my heart did. ❤️‍🔥",
        "You are not just my love; you are my home. 🏠",
        "Your smile is the best part of my day. 😄",
        "You are my today and all of my tomorrows. 📅",
        "Teri smile dekh ke lagta hai, wifi full signal pe aa gaya. 📶",
        "Pyaar kya hai? Maine tujhse jaana. 🫀",
        "Tu hai toh din hai, warna toh har pal hai night shift. 🌃",
        "Tujhse milke samjha, pyaar kya hai bhai! 🥰",
        "Teri ek smile pe, de doon jaan bhi. 😄",
        "Chand se chura ke laaya hoon, teri muskaan. 🌙",
        "Tere bina dil hai veeran. 💔",
        "Pyaar ka sabak mila, tujhse hi yaar. 🫀",
        "Kya baat hai tujh mein, hai koi jaadu. 👀",
        "Tu hi meri subah, tu hi mera sukoon. ☁️"
        ]

        troll_texts = [
        "Bhai tujhe dekh ke lagta hai troll ka mascot tu hai 😂",
        "Ter personality ek sada hua pyaz jaisi hai — khole toh aansu aaye 🧅",
        "Tu itna bura lagta hai ke teri photo dekh ke mosquito bhi bhaag jata hai 🦟",
        "Teri maa ne bhi socha hoga — yaar galti ho gayi 😹",
        "Tujhe dekh ke pata chalta hai — darr darr ke jeena kya hota hai 😂",
        "Teri iq level calculator mein error aata hai 🧮",
        "Tu chhata hua papad hai — touch karte hi toot gaya 😹",
        "Bhai teri aukat itni hai ke mirror bhi muh fer leta hai 🪞",
        "Teri personality dekh ke AI bhi depressed ho gaya 🤖",
        "Tu aisa dost hai jo aaye na aaye — fark nahi padta 😂",
        "Your life is like a bad web series — flop in season 1 📺",
        "Your personality is like a blank meme template — nothing 😂",
        "You're so boring that even sleep runs away from you 😴",
        "Your existence is proof that anyone can use the internet 📶",
        "Your thinking is 2G speed in a 5G world 📡",
        "Your life is a loading screen that never loads ⏳",
        "You're the reason 'error' exists in the dictionary 📖",
        "Your vibe check: FAILED 😂",
        "You're irrelevant — even Google doesn't know you 🔍",
        "You're a hero whose movie flopped in 3 minutes 🎬",
        "Bhai tera swag Excel mein error hai — #NAME? 📊",
        "Tu itna dheema hai ke kachhua bhi race jeet gaya 🐢",
        "Teri thinking 2G speed pe chal rahi hai 📡",
        "Beta tera ek message dekh ke aasman bhi sharma gaya ☁️",
        "Bhai teri life ek loading screen hai — jo kabhi load nahi hoti ⏳",
        "Ter maa ne tujhe chhoda nahi chhodni chahiye thi 😂",
        "Beta tera existence proof hai ke koi bhi internet use kar sakta hai 📶",
        "Bhai teri personality ek blank page hai — aur blank hi rahega 📄",
        "Tu sirf chat mein hero hai real duniya mein zero 💻",
        "Beta teri soch itni outdated hai ke floppy disk bhi reject kar de 💾",
        "🤡 Bhai tujhe dekh ke lagta hai troll ka mascot tu hai 😂🔥",
        "😹 Tu itna troll hai ke khud ko pata nahi 💀🤡",
        "🤡 Teri baatein sun ke log seriously nahi lete — aur le bhi nahi chahiye 😂😹",
        "😹 Beta tu internet ka troll #1 candidate hai 💀🤡",
        "🤡 Tujhe real life mein bhi ignore karte honge log 😂🔥",
        "😹 Bhai teri comments section mein sabne dislike diya 👎🤡",
        "🤡 Tu troll karne ki koshish karta hai — khud troll bana rehta hai 😂💀",
        "😹 Teri troll game weak hai — aur weak troll game bhi troll hai 🤡🔥",
        "🤡 Beta jo tu sochta hai funny hai woh boring hai 😂😹",
        "😹 Bhai tera troll skill level: tutorial mode pe stuck 🤡💀",
        "🤡 Tu troll hai par original nahi — copy-paste troll 😂🔥",
        "😹 Teri trolling se logon ko secondhand embarrassment hoti hai 🤡😂",
        "🤡 Beta tujhe seriously lena — woh troll hoga apne aap pe 😹💀",
        "😹 Bhai tera meme quality — delete worthy 🤡😂",
        "🤡 Tu troll karta hai online — real duniya mein kaanta nahi milta 😹🔥",
        "😹 Beta teri har post pe raat ko cry karta hai 🤡💀",
        "🤡 Tujhe dekh ke pata chalta hai — internet access free nahi honi chahiye 😂😹",
        "😹 Bhai teri troll attempt genuine cringe hai 🤡🔥",
        "🤡 Tu troll ka wannabe version hai 😂💀",
        "😹 Beta asli troll woh hota hai jise pata nahi woh troll hai — tu wahi hai 🤡😂",
        "🤡 Bhai teri comments log copy karke dusron ko dikhate hain — example ke liye kya nahi karna chahiye 😹🔥",
        "😹 Tu troll karta hai par khud hi jal jaata hai 🤡💀",
        "🤡 Beta teri troll attempts fail hoti hain kyunki tujhe original hona chahiye 😂😹",
        "😹 Bhai seriously — apni energy sahi jagah lagao 🤡🔥",
        "🤡 Teri trolling mein timing nahi content nahi creativity nahi 😂💀",
        "😹 Beta tu woh insaan hai jo khud ko troll king samjhta hai — aur paida hota hai troll ke neeche 🤡😂",
        "🤡 Bhai tera troll fail isliye hota hai — genuine nahi hai 😹🔥",
        "😹 Tu troll karta hai aur end mein rota hai — classic 🤡💀",
        "🤡 Beta tujhe sun ke logon ko stress nahi hoti — pity hoti hai 😂😹",
        "😹 Bhai teri troll quality inspect hua — returned as defective 🤡🔥",
        "🤡 Tu original troll nahi — fan-made version hai 😂💀",
        "😹 Beta teri trolling attempt mein best cheez — mujhe engage nahi karta 🤡😂",
        "🤡 Bhai teri presence troll community ke liye embarrassment hai 😹🔥",
        "😹 Tu troll karta hai aur log silent ho jaate hain — cringe se 🤡💀",
        "🤡 Beta teri troll ka response — ignore — kyunki deserve nahi karta 😂😹",
        "😹 Bhai tera troll skill tree mein sirf ek node hai — aur woh bhi locked hai 🤡🔥",
        "🤡 Tu troll ka demo version hai — full version nahi aaya 😂💀",
        "😹 Beta trolling seekh pehle phir aa — abhi tu syllabus mein nahi hai 🤡😂",
        "🤡 Bhai teri baatein sun ke log empathy feel karte hain — tere liye 😹🔥",
        "😹 Tu troll nahi — annoying hai — alag concept hai 🤡💀",
        "🤡 Beta tera troll game 0/10 — ek baar apni chat history padh 😂😹",
        "😹 Bhai tu sirf apna time barbad kar raha hai — mera nahi 🤡🔥",
        "🤡 Teri troll attempt ek baar bhi hit nahi hui — streak: 0 😂💀",
        "😹 Beta tera troll unprovoked aur uninspired tha 🤡😂",
        "🤡 Bhai tu troll ke bhi standards neeche hai 😹🔥",
        "😹 Teri trolling see aur feel karna — dono experience kharab hain 🤡💀",
        "🤡 Beta teri troll ne sirf yeh prove kiya — tujhe better kaam dhundhna chahiye 😂😹",
        "😹 Bhai troll mein skill hoti hai — teri mein nahi 🤡🔥",
        "🤡 Tu troll hai aur tera troll bhi troll hai — recursion 😂💀",
        "😹 Beta ek advice — yeh mat kar — seriously apni life mein focus kar 🤡😎",
        "Tu itna bura lagta hai ke teri photo dekh ke mosquito bhi bhaag jata hai 🦟",
        "Teri maa ne bhi socha hoga — yaar galti ho gayi 😹",
        "Tujhe dekh ke pata chalta hai — darr darr ke jeena kya hota hai 😂",
        "Teri iq level calculator mein error aata hai 🧮",
        "Tu chhata hua papad hai — touch karte hi toot gaya 😹",
        "Bhai teri aukat itni hai ke mirror bhi muh fer leta hai 🪞",
        "Teri personality dekh ke AI bhi depressed ho gaya 🤖",
        "Tu aisa dost hai jo aaye na aaye — fark nahi padta 😂",
        "Your life is like a bad web series — flop in season 1 📺",
        "Your personality is like a blank meme template — nothing 😂",
        "You're so boring that even sleep runs away from you 😴",
        "Your existence is proof that anyone can use the internet 📶",
        "Your thinking is 2G speed in a 5G world 📡",
        "Your life is a loading screen that never loads ⏳",
        "You're the reason 'error' exists in the dictionary 📖",
        "Your vibe check: FAILED 😂",
        "You're irrelevant — even Google doesn't know you 🔍",
        "You're a hero whose movie flopped in 3 minutes 🎬",
        "Bhai tera swag Excel mein error hai — #NAME? 📊",
        "Tu itna dheema hai ke kachhua bhi race jeet gaya 🐢",
        "Teri thinking 2G speed pe chal rahi hai 📡",
        "Beta tera ek message dekh ke aasman bhi sharma gaya ☁️",
        "Bhai teri life ek loading screen hai — jo kabhi load nahi hoti ⏳",
        "Ter maa ne tujhe chhoda nahi chhodni chahiye thi 😂",
        "Beta tera existence proof hai ke koi bhi internet use kar sakta hai 📶",
        "Bhai teri personality ek blank page hai — aur blank hi rahega 📄",
        "Tu sirf chat mein hero hai real duniya mein zero 💻",
        "Beta teri soch itni outdated hai ke floppy disk bhi reject kar de 💾"
        ]

        ragebait_texts = [
        "Bhai tera reaction dekh ke mujhe hasi aa rahi hai 😂",
        "Tu itna triggered ho gaya, jaise meri baat teri maa ne sun li ho 😹",
        "Rage bait pe itna emotional mat ho, beta 😂",
        "Tu toh aisa gussa ho raha hai jaise teri team world cup haar gayi 🏏",
        "Bhai shant ho ja, tera BP high ho jayega 😂",
        "Teri gaali sun ke mujhe neend aa rahi hai 😴",
        "Tu rage karta hai aur main popcorn kha raha hoon 🍿",
        "Beta tu toh aisa hai jaise bina phone ke reh gaya ho 📱",
        "Teri rage dekh ke lagta hai, teri gf ne break up kar diya 💔",
        "Tu toh aisa hai jaise internet slow ho gaya ho 😂",
        "Your rage is entertaining, please continue 😂",
        "Getting triggered over this? That's cute 🥺",
        "You're so angry, did someone steal your Wi-Fi? 📶",
        "Rage bait level: professional 😂",
        "Your anger is my daily dose of comedy 🤡",
        "Calm down, it's just a message 📩",
        "You're acting like I insulted your whole bloodline 😂",
        "The rage is real, and it's hilarious 😭",
        "You need a therapist for that anger issues 🧠",
        "I love how easy it is to get you triggered 😈",
        "Bhai tera reaction dekh ke mujhe hasi aa rahi hai 😂",
        "Tu itna triggered ho gaya, jaise maine teri game delete kar di ho 🎮",
        "Rage bait pe itna emotional mat ho, beta 😂",
        "Tu toh aisa gussa ho raha hai jaise teri team haar gayi 🏏",
        "Bhai shant ho ja, tera BP high ho jayega 😂",
        "Teri gaali sun ke mujhe neend aa rahi hai 😴",
        "Tu rage karta hai aur main popcorn kha raha hoon 🍿",
        "Beta tu toh aisa hai jaise bina phone ke reh gaya ho 📱",
        "Teri rage dekh ke lagta hai, teri gf ne break up kar diya 💔",
        "Tu toh aisa hai jaise internet slow ho gaya ho 😂"
        ]

        roast_texts = [
        "Ter life ek bakwas webseries ki tarah hai — 1 season mein flop 😂",
        "Bhai teri personality ek sada hua pyaz jaisi hai 🧅",
        "Tu itna bura lagta hai ke teri photo dekh ke mosquito bhi bhaag jata hai 🦟",
        "Teri maa ne bhi socha hoga — yaar galti ho gayi 😹",
        "Tujhe dekh ke pata chalta hai — darr darr ke jeena kya hota hai 😂",
        "Teri iq level calculator mein error aata hai 🧮",
        "Tu chhata hua papad hai — touch karte hi toot gaya 😹",
        "Bhai teri aukat itni hai ke mirror bhi muh fer leta hai 🪞",
        "Teri personality dekh ke AI bhi depressed ho gaya 🤖",
        "Tu aisa dost hai jo aaye na aaye — fark nahi padta 😂",
        "Your life is a joke, and not even a funny one 😂",
        "You're so irrelevant, even your shadow leaves you 🏃",
        "Ter life ek bakwas webseries ki tarah hai — 1 season mein flop 😂",
        "Bhai teri personality ek sada hua pyaz jaisi hai 🧅",
        "Tu itna bura lagta hai ke teri photo dekh ke mosquito bhi bhaag jata hai 🦟",
        "Teri maa ne bhi socha hoga — yaar galti ho gayi 😹",
        "Tujhe dekh ke pata chalta hai — darr darr ke jeena kya hota hai 😂",
        "Teri iq level calculator mein error aata hai 🧮",
        "Tu chhata hua papad hai — touch karte hi toot gaya 😹",
        "Bhai teri aukat itni hai ke mirror bhi muh fer leta hai 🪞",
        "Teri personality dekh ke AI bhi depressed ho gaya 🤖",
        "Tu aisa dost hai jo aaye na aaye — fark nahi padta 😂",
        "Your life is a joke, and not even a funny one 😂",
        "You're so irrelevant, even your shadow leaves you 🏃",
        "Your existence is a notification I always swipe away 📱",
        "You're like a software update — always annoying and never useful 💻",
        "Your brain is like a browser with 100 tabs open — all useless 🌐",
        "You're the human equivalent of a loading screen ⏳",
        "Your personality is like a broken pencil — pointless ✏️",
        "You're not stupid, you just have bad luck thinking 🤔",
        "You're the reason God created jokes 😂",
        "Your life is a meme, and not a good one 🗿",
        "Bhai teri zindagi ek bakwas webseries jaisi hai 📺",
        "Teri personality ek sada hua pyaz jaisi hai — khole toh aansu aaye 🧅",
        "Tu itna bura lagta hai ke teri photo dekh ke mosquito bhi bhaag jata hai 🦟",
        "Teri maa ne bhi socha hoga — yaar galti ho gayi 😹",
        "Tujhe dekh ke pata chalta hai — darr darr ke jeena kya hota hai 😂",
        "Teri iq level calculator mein error aata hai 🧮",
        "Tu chhata hua papad hai — touch karte hi toot gaya 😹",
        "Bhai teri aukat itni hai ke mirror bhi muh fer leta hai 🪞",
        "Teri personality dekh ke AI bhi depressed ho gaya 🤖",
        "Tu aisa dost hai jo aaye na aaye — fark nahi padta 😂",
        "🔥 Teri zindagi ek bakwas webseries ki tarah hai — 1 season mein flop 😂📺",
        "🤣 Bhai teri personality ek sada hua pyaz jaisi hai — khole toh aansu aaye 🧅💀",
        "😹 Tu itna bura lagta hai ke teri photo dekh ke mosquito bhi bhaag jata hai 🦟😂",
        "🔥 Teri maa ne bhi socha hoga — yaar galti ho gayi 😹👶",
        "🤣 Tujhe dekh ke pata chalta hai — darr darr ke jeena kya hota hai 😂💀",
        "😹 Beta tu Google Maps pe search kare toh bhi worthless aayega 🗺️😈",
        "🔥 Teri iq level negative hai — calculator mein error aata hai 🧮😂",
        "🤣 Tu chhata hua papad hai — touch karte hi toot gaya 😹🔥",
        "😹 Bhai teri aukat itni hai ke mirror bhi muh fer leta hai 🪞😂",
        "🔥 Teri personality dekh ke AI bhi depressed ho gaya hoga 🤖😹",
        "🤣 Tu aisa dost hai jo aaye na aaye — fark nahi padta 😂💀",
        "😹 Bhai teri soch utni hi purani hai jitna tera Nokia phone 📱😂",
        "🔥 Tera existence mere life mein irrelevant hai — bilkul sarkari kaam jaisa 📋😹",
        "🤣 Tu itna boring hai ke neend khud aa jaaye tujhe dekh ke 😴😂",
        "😹 Teri profile pic dekh ke emoji wale bhi sue kar sakte hain 😱🔥",
        "🔥 Bhai tu aisa player hai jo kabhi goal nahi kar sakta apni hi team ke khilaf 😂⚽",
        "🤣 Teri advice sunna waisa hai jaise sade kele se rasta poochna 🍌😹",
        "😹 Tu garib nahi hai — but tujhe dekh ke gareebi ko takleef hoti hai 💰😂",
        "🔥 Teri kismat itni kharab hai ke lottery ticket bhi teri traf nahi dekhti 🎫😹",
        "🤣 Bhai tera sense of humor graveyard se udhaara liya hai kya 🪦😂",
        "😹 Tu itna irrelevant hai ke khud Google bhi nahi jaanta tera naam 🔍🔥",
        "🔥 Teri body language bolta hai — main hara hua insaan hoon 😂💀",
        "🤣 Tu ek hi baar funny tha — jab tune mujhe seriously liya 😹⚡",
        "😹 Bhai teri achievements list mein sirf ek cheez hai — exist karna 😂🔥",
        "🔥 Tujhe dekh ke lagta hai — nature ne mistake ki thi 🌿😹",
        "🤣 Teri skills dekh ke Thanos bhi bola hoga — yeh toh automatically wipe ho jaayega 💀😂",
        "😹 Beta tera future itna dark hai ke sunglasses pehenne ki zaroorat nahi 🕶️🔥",
        "🔥 Teri batting dekh ke khud pitch ne sorry bola 🏏😂",
        "🤣 Bhai tu aisa idea hai jo meeting mein sab ignore karte hain 📊😹",
        "😹 Teri zubaan aur dimag mein kabhi meetup nahi hota 🧠💬😂",
        "🔥 Tu aisa hero hai jiska movie 3 minutes mein flop ho gayi 🎬😹",
        "🤣 Teri gaali sunne ke baad dushmano ne mafi maang li 😂⚔️",
        "😹 Bhai tera swag level Excel mein error hai — #NAME? 📊🔥",
        "🔥 Tu itna dheema hai ke kachhua bhi race jeet gaya 🐢😂",
        "🤣 Teri thinking 2G speed pe chal rahi hai duniya 5G mein hai 📡😹",
        "😹 Beta tera ek message dekh ke aasman bhi sharma gaya ☁️😂",
        "🔥 Bhai teri life ek loading screen hai — jo kabhi load nahi hoti ⏳😹",
        "🤣 Tu aisa mirror hai jo galat reflection dikhata hai 🪞😂",
        "😹 Teri maa ne tujhe chhoda nahi chhodni chahiye thi 😂🔥",
        "🔥 Beta tera existence proof hai ke koi bhi internet use kar sakta hai 📶😹",
        "🤣 Tujhe dekh ke lagta hai — maa baap ne education mein invest nahi kiya 📚😂",
        "😹 Teri personality ek blank page hai — aur blank hi rahega 📄🔥",
        "🔥 Tu sirf chat mein hero hai real duniya mein zero 💻😂",
        "🤣 Bhai teri jawab dene ki speed se tortoise bhi impress nahi 🐢😹",
        "😹 Teri soch itni outdated hai ke floppy disk bhi reject kar de 💾😂",
        "🔥 Tu aisa WiFi password hai jo koi yaad nahi rakhta 🔑😹",
        "🤣 Beta teri awaaz sunne ke baad mujhe silence zyada priceless laga 🤫😂",
        "😹 Bhai tera roast karna waisa hai jaise sadi hui vegetable ko season karna 🥦🔥",
        "🔥 Teri social skills dekh ke chatbot bhi impress ho ga",
        "Your existence is a notification I always swipe away 📱",
        "You're like a software update — always annoying and never useful 💻",
        "Your brain is like a browser with 100 tabs open — all useless 🌐",
        "You're the human equivalent of a loading screen ⏳",
        "Your personality is like a broken pencil — pointless ✏️",
        "You're not stupid, you just have bad luck thinking 🤔",
        "You're the reason God created jokes 😂",
        "Your life is a meme, and not a good one 🗿",
        "Bhai teri zindagi ek bakwas webseries jaisi hai 📺",
        "Teri personality ek sada hua pyaz jaisi hai — khole toh aansu aaye 🧅",
        "Tu itna bura lagta hai ke teri photo dekh ke mosquito bhi bhaag jata hai 🦟",
        "Teri maa ne bhi socha hoga — yaar galti ho gayi 😹",
        "Tujhe dekh ke pata chalta hai — darr darr ke jeena kya hota hai 😂",
        "Teri iq level calculator mein error aata hai 🧮",
        "Tu chhata hua papad hai — touch karte hi toot gaya 😹",
        "Bhai teri aukat itni hai ke mirror bhi muh fer leta hai 🪞",
        "Teri personality dekh ke AI bhi depressed ho gaya 🤖",
        "Tu aisa dost hai jo aaye na aaye — fark nahi padta 😂"
        ]

        # ─── NON-ABUSIVE RAID TEXTS (Menu9) ────────────────────────────────────

        attack_texts = [
        "🗡️ Tera baap aaya hai sunta nahi kya 👑😈",
        "⚡ Mere saamne aake dikhao himmat hai toh 😎💪",
        "🔥 Attack mode on — teri khair nahi aaj 😡⚔️",
        "💀 Tujhe itna marunga ke teri maa bhi nahi pehchanegi 😂🔥",
        "💥 Beta ye territory meri hai nikal yahan se 🏴‍☠️⚡",
        "🗡️ Aukaat hai toh saamne aa nahi toh chup baith 😈💀",
        "⚡ Tu keyboard warrior hai asli mard nahi 😂👊",
        "🔥 Teri maa ne bhi bola tera baap chahiye 😹💔",
        "💥 Chal hat yahan se chota baccha 🤣👋",
        "⚔️ Mujhe gaali de ke dekh kya hoga teri life mein 😈⚡",
        "💀 Bhai seedha bol de surrender karega ya maar khayega 😎🔥",
        "🗡️ Attack karta hoon toh block nahi hoga tera 😡⚔️",
        "⚡ Yeh game mein nahi real life mein bhi kaatenge tujhe 💪😤",
        "🔥 Tera confidence dekh ke hansi aati hai yaar 😂💥",
        "💥 Andha hai ya dikhta nahi kaun boss hai yahan 👑⚔️",
        "⚔️ Teri har gaali pe 10 gaaliyan waapis aayengi 😈🔥",
        "💀 Beta peeth nahi dikhana mujhe — coward 🏃‍♂️😂",
        "🗡️ Lad le ek baar — guarantee hai rota hoga tu 😹⚡",
        "⚡ Keyboard tod ke aa toh baat karte hain 💥👊",
        "🔥 Teri bhasha se pata chalta hai ghar mein parhe nahi 😂🤣",
        "⚔️ Main yahan hoon — tu kahan chhupta hai aaja 😎💀",
        "💀 Teri har move ka jawab taiyaar hai mere paas 🎯🔥",
        "🗡️ Tu sirf darta hai asli attack nahi kar sakta 😂⚡",
        "⚡ Baahubali nahi hai tu yahan — chal nikal 👋💥",
        "🔥 Teri aukaat utni hai jitni do takke ki 😹🗡️",
        "💥 Attack aur reaction — dono mein haar jayega tu ⚔️😎",
        "⚔️ Ek baar aake dekh kya hota hai tere saath 💀🔥",
        "💀 Sher ke saamne bakra nahi ban — phir bhi ban raha 😂⚡",
        "🗡️ Yeh teri territory nahi bhai — haath jod ke ja 🙏😈",
        "⚡ Tu attack karega aur main finish karunga 💥⚔️",
        "🔥 Teri himmat hai toh mujhse seedha baat kar 😤💀",
        "💥 Keyboard pe hero ban raha hai — asli duniya mein zero 😂🗡️",
        "⚔️ Maar kha aur phir rota mat — warning hai 😈⚡",
        "💀 Teri speed se faster hoon main — bhaag nahi sakta 🔥💥",
        "🗡️ Yaar teri life mein koi nahi kya isliye yahan ata hai 😂⚔️",
        "⚡ Hero mat ban — yahan real khiladi baithe hain 👑💀",
        "🔥 Attack kiya — ab lash uthane ki taiyaari kar 😹⚡",
        "⚔️ Teri har galti ka hisaab hoga — ruk 😈🔥",
        "💀 Bhai attack se pehle 1% dimag use kar 🧠💥",
        "🗡️ Chal hat nahi toh main khud hataunga isko 😤⚡",
        "⚡ Yeh war hai — aur tu already haar gaya 😎🔥",
        "🔥 Teri maa bhi tera lecture sunke bore ho gayi hogi 😹💥",
        "💥 Main attack mein vishwas nahi karta — main finish mein karta hoon ⚔️😈",
        "⚔️ Chal randike ek baar try kar le — rona mat baad mein 😂💀",
        "💀 Ab samjha kya hua? No? Toh phir ek aur attack 🔥⚡",
        ]

        war_texts = [
        "⚔️ War shuru ho gayi — aur tu pehle hi haar gaya 😂🔥",
        "💣 Bhai main war mein nahi aata — main war khatam karne aata hoon 😈⚡",
        "🏴‍☠️ Tera jhanda uraya — apna wala lehraya 😎💀",
        "⚔️ Tu lad raha hai mujhse — yeh teri sabse badi galti hai 🔥😂",
        "💣 Main war nahi khelta — main result deliver karta hoon 👑⚡",
        "🏴‍☠️ Battlefield pe aake to dekh — tera rank kya hai 😈⚔️",
        "⚔️ Randike war declare kiya toh surrender ka option bhi rakh 😂💣",
        "💣 Tu soldier nahi hai — tu sirf noise hai 🔊😂",
        "🏴‍☠️ War mein strategy chahiye — tu sirf emotion se ladta hai 😹⚔️",
        "⚔️ Beta yeh teri territory nahi — nikalja 👋💣",
        "💣 Tera war cry sunke mujhe neend aati hai 😴😂",
        "🏴‍☠️ Main akela kaafi hoon — teri poori army ke liye ⚔️😈",
        "⚔️ War ghoshit kiya — white flag kahan hai tera 🏳️😂",
        "💣 Bhai tu pehle khud ko toh jeet — phir mujhse lad 😎💀",
        "🏴‍☠️ Tera war tactic: bolna aur bhaagna 😹⚔️",
        "⚔️ Main chhoda nahi — tu chhoda baad mein roega 😂💣",
        "💣 Battle field pe aate waqt socha — main jeet sakta hoon? Nahi 😈🏴‍☠️",
        "⚔️ Tu ek round bhi nahi jeeta — aur war ki baat karta hai 😂💀",
        "💣 Bhai surrender kar le — dignity bachegi thodi 🙏😹",
        "🏴‍☠️ War mein aaye — aur pehli line mein fail ho gaye ⚔️😂",
        "⚔️ Tera morale zero hai — teri army teri khud ki dushman hai 😂💣",
        "💣 Main war expert hoon — tu war ka victim hai 😎🏴‍☠️",
        "🏴‍☠️ Beta teri strategy ek broken compass jaisi hai ⚔️😂",
        "⚔️ War mein seena taan ke aa — peeth dikha ke nahi 😹💣",
        "💣 Bhai teri army mein sirf tu hai — aur tu kaafi nahi 😈🏴‍☠️",
        "🏴‍☠️ Teri war cry sun ke dushman khud aa gaye — rescue karne ⚔️😂",
        "⚔️ Beta teri territory war se pehle hi haari thi 💣😹",
        "💣 Main war mein nahi — main tujhe personally destroy karne mein hoon 😈🏴‍☠️",
        "🏴‍☠️ Tera war plan sunke GPS bhi confused hai ⚔️😂",
        "⚔️ Tu war mein aaya — par weapons lana bhool gaya 💣😹",
        "💣 Bhai yeh war nahi tujhe sirf reality check tha 😂🏴‍☠️",
        "🏴‍☠️ Teri army tujhse zyada samajhdaar hai — unhone bandh kiya ⚔️😈",
        "⚔️ War mein bhi excuse karta hai — aur life mein bhi 😂💣",
        "💣 Tu jo war soch raha hai — woh meri morning routine hai 😎🏴‍☠️",
        "🏴‍☠️ Bhai teri war itni slow hai ke climate change pehle ho jaayega ⚔️😹",
        "⚔️ Main tujhse war karta hoon — aur tujhe pata bhi nahi chalta 💣😂",
        "💣 War ghoshit kar ke tu pehla tha — haar ke bhi pehla hai 😹🏴‍☠️",
        "🏴‍☠️ Teri war mein consistency hai — consistently losing ⚔️😂",
        "⚔️ Bhai war mein bhagna galat hai — tu phir bhi karta hai 💣😈",
        "💣 Tu war mein aaya — main pehle se tere base par tha 🏴‍☠️😂",
        "🏴‍☠️ Teri war strategy mein sirf ek problem hai — sab kuch ⚔️😹",
        "⚔️ Beta war ka matalab samjha nahi tujhe — sikhaunga abhi 💣😂",
        "💣 War mein hero nahi bante — survivors bante hain — aur tu nahi banega 🏴‍☠️😈",
        "🏴‍☠️ Teri war mein dum nahi — sirf dhool hai ⚔️😂",
        "⚔️ Bhai war declare karna alag baat hai — jeetan alag 💣😹",
        "💣 Tu war mein aaya sirf lose karne ke liye — congratulations 🏴‍☠️😂",
        "🏴‍☠️ Main akele teri sab pe bhaari hoon — aur tujhe pata hai ⚔️😈",
        "⚔️ Teri war ka sabse bura part — tu khud tha 💣😂",
        "💣 War mein aaye — teri team ne hi tujhe chhod diya 🏴‍☠️😹",
        "🏴‍☠️ Beta war khatam — teri taraf se surrender accepted ⚔️😎",
        ]

        savage_texts = [
        "😈 Confidence is silent, insecurity is loud! 🔥",
        "💀 You're not as important as you think! 🌪️",
        "🔥 Reality check — you're not that special! 💥",
        "😏 Your opinion is noted, but not needed! 📝",
        "💀 Let's be honest — you're overrated! 🎭",
        "🔥 The truth hurts, but it sets you free! 💪",
        "😈 You're not the main character, sorry! 📺",
        "💀 Your ego is writing checks your skills can't cash! 💰",
        "🔥 Stay humble or get humbled! ⚡",
        "😏 You're a classic example of overconfidence! 🎯",
        "💀 Let your actions speak, not your mouth! 🔥",
        "😈 Your presence is as useful as a screen door on a submarine! 🚪",
        "🔥 Let's be real — you're not that impressive! 💥",
        "💀 You're the CEO of overestimating yourself! 🏢",
        "😏 Stay in your lane, champ! 🏎️",
        "🔥 You're not as hot as you think! ❄️",
        "💀 Confidence without skill is just delusion! 🎭",
        "😈 Your reputation precedes you — and it's not good! 📉",
        "🔥 Let's keep it real — you're average at best! ⭐",
        "💀 You're a cautionary tale for others! ⚠️",
        "😈 Main savage hoon — tujhe explanation nahi deta 🔥💀",
        "💀 Teri feelings mere liye statistics hain — irrelevant 😂😈",
        "🔥 Main woh nahi hoon jo tujhe comfortable feel karaaye 😎💀",
        "😈 Beta teri baatein mujhe bore karti hain — next 😂🔥",
        "💀 Teri opinion meri life mein footnote bhi nahi hai 😈😹",
        "🔥 Main tujhe explain nahi karta — tujhse better logon ke paas time deta hoon 😎💀",
        "😈 Tera attitude dekh ke mujhe apni nails file karni chahiye 💅😂",
        "💀 Bhai tujhe reject karna meri hobby hai 🔥😈",
        "🔥 Teri presence mujhe remind karaati hai — kuch logon ko mute karna chahiye 🔇😂",
        "😈 Main bad vibes nahi leta — teri taraf bhi nahi 💀🔥",
        "💀 Tu mere standard se neeche hai — elevator laga le 🛗😂",
        "🔥 Teri baat sunna — option nahi habit nahi aur interest bhi nahi 😈💀",
        "😈 Main ghanta samjhata hoon — samajh nahi aaya toh teri problem 😂🔥",
        "💀 Teri ego itni badi hai — uske liye alag zip code chahiye 📮😂",
        "🔥 Beta mujhe tujhse jealousy feel nahi hoti — pity hoti hai 😈💀",
        "😈 Main woh insaan nahi hoon jis par tu waqt barbad kare — ya main karta hoon 😂🔥",
        "💀 Teri life choices dekh ke main grateful hoon main tujhsa nahi hoon 😹😈",
        "🔥 Bhai teri smartness ka level: WiFi password ignore karna 📶😂",
        "😈 Teri mastiyan mujhe entertain nahi karti — bore karti hain 💀🔥",
        "💀 Main savage nahi — main simply tujhse better hoon 😎😂",
        "🔥 Teri personality ek blank meme format jaisi hai — kuch nahi 😈💀",
        "😈 Beta apni journey pe focus kar — meri disturb mat kar 😂🔥",
        "💀 Teri hard work ka result tera hi face hai — kaafi bura 😹😈",
        "🔥 Main tujhe miss nahi karta — mujhe tujhse better cheezein miss hoti hain 😂💀",
        "😈 Teri baatein sun ke laga — yeh real person hai ya chatbot glitch 🤖😂",
        "💀 Bhai teri intelligence ke liye sorry feel hoti hai 🔥😈",
        "🔥 Main tujhe block isliye nahi karta — kyunki tujhe exist karna pata hai 😂💀",
        "😈 Teri struggles dekh ke mujhe motivation milti hai — teri tarah mat banna 😹🔥",
        "💀 Tu jo effort lagate ho mujhpe — woh apni growth mein lagao 😎😂",
        "🔥 Teri vibes mujhe 2G network se bhi slow lagti hain 📡😈",
        "😈 Main tujhe pehle judge nahi karta — par tujhe pehle judge hota hoon 💀😂",
        "💀 Bhai tera shadow bhi tujhse zyada interesting hai 🔥😂",
        "🔥 Teri logic sun ke Albert Einstein ne resign kar diya hoga 🧪😈",
        "😈 Tu mere jaisa ban sakta hai — agar try karta 10 saal toh bhi nahi 💀😂",
        "💀 Teri taraf se koi bhi reaction — mujhe bored karta hai 🔥😹",
        "🔥 Main respectful hoon — tere sath nahi 😈💀",
        "😈 Beta teri vibe check: FAILED 😂🔥",
        "💀 Teri har move predicted thi — boring player 😹😈",
        "🔥 Main tujhe second chance nahi deta — teri pehli impression kafi thi 😂💀",
        "😈 Teri friendship ke offer ko professionally decline karta hoon 😎😂",
        "💀 Beta tu mujhe feel nahi karaata — tu sirf annoy karta hai 🔥😈",
        "🔥 Teri dimagi capacity dekh ke solar calculator bhi sorry bol de 🔋😂",
        "😈 Main uun logon mein nahi hoon jo tere liye time waste karein 💀🔥",
        "💀 Teri life ka GPS tujhe wrong direction mein le ja raha hai 🗺️😂",
        "🔥 Bhai teri alag identity bana — copier mat ban 😈💀",
        "😈 Tu mere radar par bhi nahi aata — itna irrelevant hai 😂🔥",
        "💀 Teri maa ne bhi socha hoga — yaar isko kuch aur karna chahiye tha 😹😈",
        "🔥 Main woh hoon jo teri nightmares mein aata hai — as a reminder 😎💀",
        "😈 Beta teri bakaiti mujhe filter nahi karti — automatically skip ho jaati hai 😂🔥",
        "💀 Tu savage hone ki koshish karta hai — mujhe dekh savage ka example 😈😹",
        ]

        ultra_texts = [
        "🔥 ULTRA mode activated — time to dominate! 👑",
        "🌪️ ULTRA MODE ACTIVATED — teri poori existence question mein hai 😈🔥",
        "⚡ Ultra attack — pehle gaali sunna phir rona — sequence yaad kar 😂💀",
        "🌪️ Beta ultra level pe aake dekh — yahan teri category nahi hai 👑🔥",
        "⚡ ULTRA BLOW — teri soch se lekar attitude tak sab destroy 💥😈",
        "🌪️ Yeh ultra mode hai — blocking nahi help karega 😂⚡",
        "⚡ Ultra raid engaged — ab teri poori chat history history hai 📜😹",
        "🌪️ Beta ultra speed mein aa — par seedha home le jaata hoon 💀🔥",
        "⚡ Ultra fire — teri har defensive move kaam nahi karegi 😈🌪️",
        "🌪️ Yeh ultra level fight hai — tu still bronze mein hai 😂⚡",
        "⚡ ULTRA DAMAGE — teri reputation, teri aukaat, teri everything 💥😹",
        "🌪️ Ultra mode mein poori teri army bhi kaafi nahi 😈🔥",
        "⚡ Beta ultra attack sunne ke baad sun raha hai kya? Normal hai 😂🌪️",
        "🌪️ ULTRA RANT incoming — tune jo kiya uska hisaab hoga 💀⚡",
        "⚡ Yeh ultra version hai — tujhe pata bhi nahi kya aaya 😹🔥",
        "🌪️ Ultra mode ON — timer chal raha hai teri destruction ka 😈⚡",
        "⚡ Beta ultra strike pe tujhe sirf ek option hai — disappear 😂💀",
        "🌪️ ULTRA COMBO — reply + react + roast + raid all at once 🔥⚡",
        "⚡ Yeh ultra level rage hai — aur tujhe taste hoga 😈🌪️",
        "🌪️ Ultra activated — pehle bol sorry phir ja 😹😂",
        "⚡ Beta ULTRA message ka matlab — tu mere liye mission ban gaya 💀🔥",
        "🌪️ ULTRA STORM — har cheez destroy ho rahi hai teri side pe 😈⚡",
        "⚡ Yeh ultra nahi — tujhe sirf samjhane ki koshish thi 😂🌪️",
        "🌪️ Ultra mode finish — teri team ne tera saath chhoda 💀🔥",
        "⚡ Beta ULTRA = mera minimum effort on you 😈😂",
        "🌪️ ULTRA RAIN — tune invite kiya tha — enjoy karna tha na? 😹⚡",
        "⚡ Ultra mode mein ek hi rule — no mercy 💀🔥",
        "🌪️ Beta ULTRA sabse pehle yeh — teri galti ka hisaab 😈⚡",
        "⚡ Yeh ultra speed se aaya — aur teri samajh mein ultra slow aayega 😹🌪️",
        "🌪️ ULTRA LOCK — ab yahan se nahi jayega tu 💀🔥",
        "⚡ Beta ultra strike mein teri saari strategy fail hai 😂😈",
        "🌪️ Ultra level pe chal — toh teri duniya hi badal jaayegi 🔥⚡",
        "⚡ ULTRA — yeh word hi teri aukat se bada hai 😹💀",
        "🌪️ Beta ultra mein main hoon — tujhe pata nahi tha kya 😈🔥",
        "⚡ Yeh ultra raid hai — har message teri ek problem hai 😂🌪️",
        "🌪️ ULTRA DONE — tu done kar le pehle 💀⚡",
        "⚡ Beta ultra mein welcome — pehle bol kya karna hai 😹🔥",
        "🌪️ Ultra mode — ab seedha point pe aata hoon — tu fail hai 😂😈",
        "⚡ ULTRA BLAST — teri timeline pe aaya — nahi ruk sakta 💥🌪️",
        "🌪️ Beta ultra mein aake teri baat karo — nahi aata toh seedha ja 💀🔥",
        "⚡ Yeh ultra war hai — aur teri taraf se koi nahi 😂😈",
        "🌪️ ULTRA FINAL — bas yahi hoga — accept kar 💀⚡",
        "⚡ Beta ultra strike complete — check teri status 😹🔥",
        "🌪️ Ultra mode mein log surrender karte hain — tujhe bhi karna hoga 😈⚡",
        "⚡ Yeh ultra punishment nahi — tutorial hai teri life ka 😂💀",
        "🌪️ ULTRA JUDGEMENT — teri har move judged ho rahi hai 🔥⚡",
        "⚡ Beta ultra mein ek cheez — main hoon aur tu nahi rahe 😈🌪️",
        "🌪️ Ultra mode completed — teri side destroyed 💀😂",
        "⚡ Yeh ultra attack ka last wave hai — teri koi repair nahi 😹🔥",
        "🌪️ ULTRA END — teri war khatam teri taraf se flag gira 😈⚡",
        "⚡ Beta ultra mein aana tha — rona nahi tha — par dono kiye 😂💀",
        ]

        # ─── NEW MENU9 RAID TEXTS ───────────────────────────────────────────────

        shame_texts = [
        "😤 Sharam kar — itna gira hua kaam karte kaise hain tum log 🔥💀",
        "🙅 Bhai teri harkat dekh ke pura group sharam se doob gaya 😂😤",
        "😤 Yeh sab karke tujhe pride feel hoti hai? Really? 💀🔥",
        "🙅 Beta teri harkaten dekh ke maa baap sharmayenge 😂😤",
        "😤 Sharam nahi hai tujhe bilkul — clearly 💀😹",
        "🙅 Bhai itna gira hua kaam dekh ke log muh fer lete hain 😤🔥",
        "😤 Tu itna neeche gira — zameen bhi neeche ho gayi 💀😂",
        "🙅 Beta sharam bhi nahi aata aisa karte hue 😤😹",
        "😤 Yeh harkat dekh ke lagta hai — tujhe value kisi ne nahi sikhaya 💀🔥",
        "🙅 Bhai log tujhe dekh ke aankhein pher lete hain — soch kya kar raha hai 😤😂",
        "😤 Teri galti nahi — environment ki galti — par ab waqt hai change ka 💀😹",
        "🙅 Beta sharam isliye nahi aati kyunki sharam feel karna seekha nahi 😤🔥",
        "😤 Yeh kaam karke tujhe khushi mili? Toh mujhe tujhse zyada chinta hai 💀😂",
        "🙅 Bhai teri harkat pura record hai — aur yeh record kharab hai 😤😹",
        "😤 Tu sochta hai koi dekh nahi raha — sab dekh rahe hain 💀🔥",
        "🙅 Beta aisa behave karta hai — khud se bhi embarrassing lagta hai tu 😤😂",
        "😤 Yeh sab dekh ke lagta hai — teri parwarish kahan gayi 💀😹",
        "🙅 Bhai teri harkaton ka hisaab hoga — aaj nahi toh kal 😤🔥",
        "😤 Tu sharminda nahi hai — woh most shameful cheez hai 💀😂",
        "🙅 Beta logo ne tujhe judge kiya — kyunki tune judge hone wala kaam kiya 😤😹",
        "😤 Yeh bura kaam karke tujhe kya mila — kuch nahi — bas naam barbad 💀🔥",
        "🙅 Bhai sharam karo — itna toh haq hai tumhara 😤😂",
        "😤 Tu yahan cool lagne ki koshish mein sharminda ho gaya 💀😹",
        "🙅 Beta ghalat rasta chhod — vapas aa 😤🔥",
        "😤 Yeh sab karke teri image bani hai — worst category mein 💀😂",
        "🙅 Bhai teri harkat ka review — 0 stars — do not recommend 😤😹",
        "😤 Tu itna neeche gira — recovery mushkil lagti hai 💀🔥",
        "🙅 Beta tujhe samjhana waqt waste hai — par try kar raha hoon 😤😂",
        "😤 Yeh sab dekh ke mujhe tujhse zyada tujhpe gussa nahi — hairaani hai 💀😹",
        "🙅 Bhai sharam se doob — par us mein bhi tujhe help chahiye shayad 😤🔥",
        "😤 Teri harkat ek lesson hai — dusron ke liye kya nahi karna chahiye 💀😂",
        "🙅 Beta teri yeh sab dekh ke khud bhi tujhse door rehna chahta hoon 😤😹",
        "😤 Yeh gaaliyaan nahi — sirf reality check hai 💀🔥",
        "🙅 Bhai sharam tab aati hai jab insaan mein insaniyat hoti hai 😤😂",
        "😤 Tu ek example bana diya khud ko — negative example 💀😹",
        "🙅 Beta tujhe ek baar ruk ke soochna chahiye tha — nahi soocha 😤🔥",
        "😤 Yeh sab karke tu yahan hai — aur sochta hai main galat hoon? 💀😂",
        "🙅 Bhai itna toh bata — tujhe kaisa feel hota hai yeh sab karne ke baad 😤😹",
        "😤 Tu sharminda nahi — tujhe sharminda feel karna chahiye 💀🔥",
        "🙅 Beta yeh rasta galat hai — abhi bhi change ho sakta hai 😤😂",
        "😤 Yeh sab khud se bura nahi tha — tu tha 💀😹",
        "🙅 Bhai teri harkaton ka real world impact sun — sab tujhse dur hain 😤🔥",
        "😤 Tu soch raha hai main overreact kar raha hoon — par tujhe hisaab hoga 💀😂",
        "🙅 Beta tujhe pata hai tu kya kar raha hai — aur phir bhi kar raha hai 😤😹",
        "😤 Yeh sharm ki baat hai — aur tujhe realize karna chahiye 💀🔥",
        "🙅 Bhai tujhe mirror mein dekhna chahiye — ek baar 😤😂",
        "😤 Tu itna bura nahi hai — par yeh kaam bura tha 💀😹",
        "🙅 Beta sharam isliye nahi aati — kyunki tu sochta nahi consequences ke baare mein 😤🔥",
        "😤 Yeh moment tera lowest point hai — aur abhi bhi jaag sakta hai 💀😂",
        "🙅 Bhai aaj ek kaam kar — sharminda ho aur badal — bas itna chahiye 😤😎",
        ]

        diss_texts = [
        "🎤 Tera naam sun ke log mute kar dete hain khud ko 🔇😂",
        "💀 Tu diss kar raha hai — khud ko diss kar pehle 🪞😹",
        "🎙️ Teri rap jaisi hai — no flow no bars no future 🎵😂",
        "💥 Bhai tera verse sun ke Eminem ne retire le liya 😹🎤",
        "🔥 Teri diss itni kamzor hai ke whisper bhi zyada loud hai 🤫😂",
        "💀 Tu sirf bolne mein mard hai karne mein? Zero 😈🎙️",
        "🎤 Beta teri bars mein bar hi nahi — sirf khali string 🎸😂",
        "💥 Tera diss track sunne ke baad logon ne earbuds tod diye 🎧😹",
        "🔥 Bhai teri lyric likh ke dekha — autocorrect ne bhi reject kiya ✍️😂",
        "💀 Tu diss karta hai aur log diss ko diss karte hain 😂🎤",
        "🎙️ Teri voice aisi hai ke autotune bhi nahi bach sakta 🎶😹",
        "💥 Beta freestyle kar le — ya phir stop the embarrassment 🛑😂",
        "🔥 Tujhe sun ke DJ ne plug nikal diya 🔌😹",
        "💀 Bhai tera flow aisa hai jaise jaam mein traffic — ruka hua 🚗😂",
        "🎤 Teri soch itni slow hai ke beat ke saath nahi chalti 🥁😹",
        "💥 Tera diss mujhe sula raha hai — better than sleeping pills 😴😂",
        "🔥 Bhai asli diss toh tab hogi jab tu actually kuch achieve kare 🏆😹",
        "💀 Teri lyrics Google Translate se better hain — bas 🌐😂",
        "🎙️ Beta chal hat stage se — pehle walk-on music bana 🎵😹",
        "💥 Tera punchline itna weak hai ke paper bhi survive kar le 📄😂",
        "🔥 Bhai teri diss sun ke crowd ne baat karna shuru kar diya 🙄😹",
        "💀 Tu verse likhta hai ya grocery list — same energy 🛒😂",
        "🎤 Teri bars mein calories zyada hain — totally empty 😹🔥",
        "💥 Bhai teri rhyme sunke chhote bacche bhi sharma jaate hain 😂💀",
        "🔥 Teri diss aisi hai — sirf uski maa samjhi 😹🎙️",
        "💀 Tu diss karta hai mujhe — main khud apni diss sunta hoon for fun 😂💥",
        "🎤 Tera stage naam kya hai — Bakwas ke Raja? 👑😹",
        "💥 Bhai teri microphone bhi teri awaaz se dara hua hai 🎙️😂",
        "🔥 Tu diss mein expert hai — aur expert hone mein loser 😹💀",
        "💀 Teri har line mein cringe hai — Olympic level 🥇😂",
        "🎙️ Beta khud ki diss sun le — ek baar realise hoga 😹🔥",
        "💥 Bhai tera diss itna slow hai ke mujhe neend aa gayi 😴😂",
        "🔥 Teri creativity level: template pe naam likhna 💀😹",
        "💀 Tu diss karne ke liye paida hua tha — aur fail ho gaya 😂🎤",
        "🎙️ Tera rhyme scheme: aab aab aab — boring AF 📝😹",
        "💥 Bhai teri diss response mein Soulja Boy beat use karta hun 😂🔥",
        "🔥 Tu keyboard pe rap karta hai — phone pe nahi kaata 📱💀",
        "💀 Teri diss sun ke mic khud neeche gir gaya 🎙️😂",
        "🎤 Beta teri bars itni weak hain ke paper toh chodh kaagaz bhi nahi chhapega 📰😹",
        "💥 Bhai tera flow paani mein nahi petrol mein hai — ab blast 🔥😂",
        "🔥 Teri diss sunta hoon toh lagta hai sabne kaan band kar rakhe hain 🔇💀",
        "💀 Tu diss mein ghusaa — tu diss tha diss 😹😂",
        "🎙️ Bhai tera verse industry standard se neeche hai — ground floor bhi nahi 🏚️🔥",
        "💥 Teri awaaz mein woh baat nahi jo diss mein chahiye — talent 😂💀",
        "🔥 Beta teri diss itni pathetic hai ke pity vote mil sakta tha 🗳️😹",
        "💀 Bhai teri rap career ek Instagram story jaisi hai — 24 ghante mein khatam 📸😂",
        "🎤 Tu rapper nahi rapper ki copy ki copy ka knock-off hai 😹🔥",
        "💥 Teri diss sun ke auto-generated ho sakti thi — aur better hoti 🤖😂",
        "🔥 Bhai freestyle maar — aur phir sun khud ko — tujhe pata chalega 🎧💀",
        "💀 Teri diss ka reply nahi deta — tujhe dignify karna time waste hai 😂🎙️",
        ]

        devil_texts = [
        "😈 DEVIL MODE — yahan woh aaya hai jo tujhe deserve karta hai 🔥💀",
        "😈 Beta main devil nahi — main tera worst nightmare hoon 🔥⚡",
        "😈 Devil raid activate — teri poori timeline disturbed 💀😂",
        "😈 Bhai devil pe hath lagaya — ab bhog 🔥💥",
        "😈 DEVIL FURY — teri sab cheez ek baar mein 💀⚡",
        "😈 Beta devil ke saamne hum sab khiladi hain — tu beginner 🔥😂",
        "😈 DEVIL ATTACK — teri defense devil ke touch se fail 💀😈",
        "😈 Bhai devil mode mein koi safe nahi — tu bhi nahi 🔥⚡",
        "😈 Teri galti — devil ko challenge karna 💀😂",
        "😈 Beta devil ki bhasha — punishment aur reward — tu punishment mein hai 🔥😈",
        "😈 DEVIL LEVEL RAGE — teri poori life on line 💀⚡",
        "😈 Bhai devil se lad ke koi nahi jeeta — tu bhi nahi jeetega 🔥😂",
        "😈 Devil mode — tera sab kuch noted — sab 💀😈",
        "😈 Beta DEVIL FIRE — teri poori duniya burn 🔥⚡",
        "😈 DEVIL RAID COMPLETE — tujhe koi nahi bachayega 💀😂",
        "😈 Bhai devil teri har move pe already plan bana chuka 🔥😈",
        "😈 Devil mode — tera future bleak — teri choice thi 💀⚡",
        "😈 Beta devil ne tujhe select kiya — koi bada reason hoga 🔥😂",
        "😈 DEVIL STORM — teri poori squad disbanded 💀😈",
        "😈 Bhai devil ke game mein tera turn tha — abhi mera 🔥⚡",
        "😈 Devil raid engage — now teri responsibility 💀😂",
        "😈 Beta devil level punishment — tujhse tune karaya tha 🔥😈",
        "😈 DEVIL ZONE — nikal ja nahi toh devil ka guest ban 💀⚡",
        "😈 Bhai devil hamesha sunta hai — teri bhi sun li 🔥😂",
        "😈 Devil mode ACTIVATED — teri poori timeline hijacked 💀😈",
        "😈 Beta devil ke saamne sirf ek option — respect ya suffer 🔥⚡",
        "😈 DEVIL FINAL BLOW — teri defense completely gone 💀😂",
        "😈 Bhai devil ne decide kiya — teri loss is inevitable 🔥😈",
        "😈 Devil mein aake dekha — tu deserving nahi tha challenge ka 💀⚡",
        "😈 Beta DEVIL RAIN — teri har cheez soaked in fire 🔥😂",
        "😈 DEVIL vs YOU — spoiler: devil wins 💀😈",
        "😈 Bhai devil ke saamne teri prayers bhi kaam nahi aate 🔥⚡",
        "😈 Devil mode — teri weak spots identified — attack 💀😂",
        "😈 Beta devil ki nazar se tu nahi chhupta 🔥😈",
        "😈 DEVIL JUDGMENT — teri poori history reviewed — verdict: guilty 💀⚡",
        "😈 Bhai devil ki duniya mein tu tourist tha — time up 🔥😂",
        "😈 Devil fury — tere steps already tracked hain 💀😈",
        "😈 Beta DEVIL COUNTER — teri har move ka counter ready tha 🔥⚡",
        "😈 DEVIL FINISH — teri game over — my game continues 💀😂",
        "😈 Bhai devil mode se nikalna — tujhe option nahi 🔥😈",
        "😈 Devil attack — teri soul targeted — figuratively 💀⚡",
        "😈 Beta devil ne kaha — teri aukat nahi — aur devil galat nahi hota 🔥😂",
        "😈 DEVIL STORM OVER — teri side: scorched earth 💀😈",
        "😈 Bhai devil ke rules simple hain — tu follow nahi kiya 🔥⚡",
        "😈 Devil raid — teri position compromised — retreat 💀😂",
        "😈 Beta DEVIL mein aake rota mat — khud aaya tha 🔥😈",
        "😈 DEVIL WAVE — teri har defence erased 💀⚡",
        "😈 Bhai devil ka favorite — log jo khud ko smart samjhte hain — tu 🔥😂",
        "😈 Devil mode DONE — check teri condition 💀😈",
        "😈 Beta devil ne aaj tujhe yaadgaar bana diya — wrong reasons se 🔥⚡",
        ]

        karma_texts = [
        "☯️ Karma aaya — teri sab harkat ka hisaab ho raha hai 🔥💀",
        "☯️ Beta karma kisi ki nahi sunta — teri bhi nahi 😂⚡",
        "☯️ KARMA STRIKE — tune jo kiya woh teri taraf wapas aaya 🔥😈",
        "☯️ Bhai karma judge nahi karta — deliver karta hai 💀😂",
        "☯️ Karma mode activate — teri sab galtiyan wapas aa rahi hain 🔥⚡",
        "☯️ Beta karma tujhe bhool nahi gaya — yaad rakha tha 😂💀",
        "☯️ KARMA DELIVERY — teri harkat ka package arrive ho gaya 🔥😈",
        "☯️ Bhai karma se koi nahi bachta — tu bhi nahi bachega 💀⚡",
        "☯️ Karma tujhe dhundh raha tha — dhundh liya 🔥😂",
        "☯️ Beta karma aata hai jab expect nahi karte — sun le 😂💀",
        "☯️ KARMA HITS DIFFERENT — teri sab cheez wapas 🔥⚡",
        "☯️ Bhai karma teri priority nahi thi — karma mein tu priority hai 😂💀",
        "☯️ Karma cycle complete — tune jo kiya tune hi bhoga 🔥😈",
        "☯️ Beta karma slow hota hai par sure hota hai — yeh sure tha 💀⚡",
        "☯️ KARMA CALL — teri line pe aa gaya 🔥😂",
        "☯️ Bhai karma mein koi error nahi — teri galti recorded thi 😂💀",
        "☯️ Karma teri taraf waapis — enjoy 🔥⚡",
        "☯️ Beta karma tera address jaanta tha 😂💀",
        "☯️ KARMA FINAL — teri poori account balance zero 🔥😈",
        "☯️ Bhai karma se lad nahi sakte — tu chhupa nahi karma se 💀⚡",
        "☯️ Karma strike — tune deserve kiya — mila 🔥😂",
        "☯️ Beta karma ko excuse nahi deta — sirf result deta hai 😂💀",
        "☯️ KARMA STORM — teri sab beizzati aaj ekatha aayi 🔥⚡",
        "☯️ Bhai karma tujhse behtar account maintain karta hai 😂💀",
        "☯️ Karma mein tera account — overdraft mein hai 🔥😈",
        "☯️ Beta karma ki speed teri speed se faster hai 💀⚡",
        "☯️ KARMA BLAST — teri sab cheezon ka hisaab 🔥😂",
        "☯️ Bhai karma ko pata tha tune kya kiya — sab record mein hai 😂💀",
        "☯️ Karma kisi pe bhi nahi rulta — teri bhi nahi 🔥⚡",
        "☯️ Beta karma tera future nahi — karma tera present hai 😂💀",
        "☯️ KARMA INVOICE — teri sab galtiyon ka bill aa gaya 🔥😈",
        "☯️ Bhai karma mein koi discount nahi milta — full price pay 💀⚡",
        "☯️ Karma delivered — tune jo bheja wahi mila 🔥😂",
        "☯️ Beta karma tujhse kisi ki nahi sunta — seedha deliver karta hai 😂💀",
        "☯️ KARMA FULL CIRCLE — teri sab harkat ghumke teri hi taraf aayi 🔥⚡",
        "☯️ Bhai karma teri taraf — aur tu prepared nahi tha 😂💀",
        "☯️ Karma hit kiya — tujhe pata tha aayega — aaya 🔥😈",
        "☯️ Beta karma mein interest bhi hota hai — tera compound ho gaya 💀⚡",
        "☯️ KARMA COMPLETE — lesson mila? 🔥😂",
        "☯️ Bhai karma ne tujhe select kiya — deservingly 😂💀",
        "☯️ Karma tujhe yaad dila raha hai — tune kya kiya tha 🔥⚡",
        "☯️ Beta karma ki awaaz nahi hoti — par result loud hota hai 😂💀",
        "☯️ KARMA RESPONSE — teri har cheez ka seedha jawab 🔥😈",
        "☯️ Bhai karma ki list mein tu first position pe tha 💀⚡",
        "☯️ Karma tujhe bhool nahi gaya — teri galti note thi 🔥😂",
        "☯️ Beta karma aur tu — aaj inka meetup schedule tha 😂💀",
        "☯️ KARMA WRAP UP — teri life lesson: yeh tha 🔥⚡",
        "☯️ Bhai karma ne apna kaam kiya — efficient tha 😂💀",
        "☯️ Karma strike final — teri sab cheez balanced ho gayi — zero pe 🔥😈",
        "☯️ Beta karma yaad rakhna — abhi bhi teri account open hai ☯️😂",
        ]

        doom_texts = [
        "💀 DOOM activated — teri poori existence on countdown 🔥😈",
        "💀 Beta doom aaya — tera timer start ho gaya 😂⚡",
        "💀 DOOM STRIKE — teri poori defense wiped 🔥😈",
        "💀 Bhai doom se koi nahi bachta — teri bhi date aane wali thi 😂💀",
        "💀 Doom mode — teri sab cheez: scheduled for deletion 🔥⚡",
        "💀 Beta doom tera waqt dekh ke aaya — perfect timing 😂😈",
        "💀 DOOM RAID — teri poori squad: doomed 🔥💀",
        "💀 Bhai doom pe haath lagaya — yeh result expect karna chahiye tha 😂⚡",
        "💀 Doom finale — teri poori story: ended 🔥😈",
        "💀 Beta doom ki awaaz sunna nahi chahte log — teri aa gayi 😂💀",
        "💀 DOOM COMPLETE — teri sab cheez: finished 🔥⚡",
        "💀 Bhai doom tujhse pehle plan kar ke aaya tha 😂😈",
        "💀 Doom level CRITICAL — teri situation: hopeless 🔥💀",
        "💀 Beta doom ne tujhe select kiya — teri achievement nahi 😂⚡",
        "💀 DOOM COUNTDOWN — teri sab cheez: 3... 2... 1... done 🔥😈",
        "💀 Bhai doom mein rasta ek hi hota hai — neeche 😂💀",
        "💀 Doom activated — teri poori future: uncertain 🔥⚡",
        "💀 Beta doom ki language — teri samajh nahi aati — result aata hai 😂😈",
        "💀 DOOM FINAL — teri poori team: gone 🔥💀",
        "💀 Bhai doom aur tu — aaj ka meetup tera worst tha 😂⚡",
        "💀 Doom mode — tera har step: tracked 🔥😈",
        "💀 Beta doom ne teri position: permanent zero confirm ki 😂💀",
        "💀 DOOM RAIN — teri har cheez: destroyed 🔥⚡",
        "💀 Bhai doom mein mercy nahi hoti — teri request: denied 😂😈",
        "💀 Doom strike — teri sab galtiyan: collected 🔥💀",
        "💀 Beta doom clock — teri ticking: started 😂⚡",
        "💀 DOOM WAVE — teri poori defense: overwhelmed 🔥😈",
        "💀 Bhai doom ki speed mein teri situation resolve ho gayi — badly 😂💀",
        "💀 Doom verdict — teri case: closed — against you 🔥⚡",
        "💀 Beta doom se pehle sun: teri galti — doom aaya 😂😈",
        "💀 DOOM ARRIVAL — teri poori day ruined 🔥💀",
        "💀 Bhai doom ne tujhe apna project bana liya 😂⚡",
        "💀 Doom mode final — teri sab cheez: ash 🔥😈",
        "💀 Beta doom ki ek khasiyat — woh aata zaroor hai 😂💀",
        "💀 DOOM EXECUTION — teri poori plan: failed 🔥⚡",
        "💀 Bhai doom tera number leke aaya tha — mila 😂😈",
        "💀 Doom level MAX — teri recovery: impossible 🔥💀",
        "💀 Beta doom ki taraf se ek gift — teri haari 😂⚡",
        "💀 DOOM COMPLETE CYCLE — teri poori existence reset 🔥😈",
        "💀 Bhai doom tujhse better hai — wait nahi karta 😂💀",
        "💀 Doom mode — teri sab cheez: compromised 🔥⚡",
        "💀 Beta DOOM aur tu — tujhe jeetna tha par doom ka hi naam hai 😂😈",
        "💀 DOOM FINAL WAVE — teri sab: erased 🔥💀",
        "💀 Bhai doom ne tujhe memorable bana diya — galat reasons se 😂⚡",
        "💀 Doom activated final time — teri countdown: zero 🔥😈",
        "💀 Beta DOOM se seekhna tha — tujhe nahi tha pata ab hai 😂💀",
        "💀 DOOM OVER — teri side: collapsed — mine: standing 🔥⚡",
        "💀 Bhai doom ne tera chapter likh diya — R.I.P. chapter 😂😈",
        "💀 Doom final message — tujhe yaad rahega — sahi reasons se nahi 🔥💀",
        "💀 Beta DOOM complete — check teri condition — yahi tha 😂⚡",
        ]

        # ─── GAME TEXTS (Menu10) ──────────────────────────────────────────────

        truth_texts = [
        "Tumhara sabse bada secret kya hai jo kisi ko nahi pata? 🤫",
        "Kisi pe crush tha jo ab dost hai? 😳",
        "Kabhi kisi ki baat repeat ki thi jo confidence mein batai gayi thi? 😬",
        "Woh kaun hai jis par sabse zyada trust karte ho? ❤️",
        "Life mein sabse bada regret kya hai? 💭",
        "Kabhi class ya office se bina bataye bhaage ho? 😂",
        "Tumhari sabse embarrassing memory kya hai? 😳",
        "Kabhi kisi ko jhooth bol ke escape kiya hai? 🤥",
        "Tumhara sabse bada fear kya hai? 😨",
        "Kabhi kisi se pyaar kiya hai jo tumhe pata nahi? 💔",
        "Tumhari life ka best decision kya tha? ✅",
        "Kabhi kisi ko ghost kiya hai? 👻",
        "Tumhara sabse bada achievement kya hai? 🏆",
        "Kabhi kisi ko 'I love you' bola hai jhooth mein? 💀",
        "Tumhari sabse badi weakness kya hai? 😅",
        "Kabhi kisi ka trust todna pada hai? 💔",
        "Tumhari favourite memory kya hai? 📸",
        "Kabhi kisi ko dekh ke jealous feel kiya hai? 😤",
        "Tumhara sabse bada dream kya hai? 🌟",
        "Kabhi kisi ki feelings hurt kari hai? 😢",
        "Tumhari sabse badi strength kya hai? 💪",
        "Kabhi kisi ko forgive kiya hai jo worth nahi tha? 🙏",
        "Tumhara worst date experience kya tha? 😬",
        "Kabhi kisi ko block kiya hai without reason? 🚫",
        "Tumhari guilty pleasure kya hai? 🍫",
        "Kabhi kisi se jealous hoke galat kiya hai? 😤",
        "Tumhara favourite childhood memory kya hai? 🧸",
        "Kabhi kisi ko sacrifice kiya hai apne liye? 🥺",
        "Tumhari life ki best advice kya hai? 💡",
        "Kabhi apne best friend se jhooth bola hai? 🤥"
        ]

        dare_texts = [
        "Apni maa ko call kar ke bol — 'Main tujhse pyaar karta hoon' 📞❤️",
        "Apni sabse embarrassing photo share kar group mein 📸😹",
        "Kisi bhi friend ko abhi message kar — 'Bhai mujhe pata chal gaya' — aur reaction dekho 😈",
        "10 seconds ke liye khud se hi baat karo — loud 🗣️",
        "Abhi ek push-up kar aur photo bhejo 💪",
        "Apne crush ko 'Hi' bol — screenshot bhejo 😳",
        "Khud ki roast karo ek paragraph mein — seriously 😂",
        "Apna phone wallpaper change karo kisi funny photo mein 📱",
        "5 random logo ko 'I love you' message karo 💌",
        "Apni last seen status pe kuch funny likho 📝",
        "Kisi bhi group mein 'Main pagal hoon' bolo 🤪",
        "Apna profile pic change karo kisi meme se 🖼️",
        "Apne best friend ko call karo aur kuch funny bolo 📞",
        "Apni gallery se koi embarrassing photo share karo 📸",
        "Kisi random person ko compliment do 🌹",
        "Apne parents ko 'I love you' bolo ❤️",
        "Kisi bhi chat mein 'I am the best' bolo 😎",
        "Apna phone number kisi stranger ko do 📱",
        "Kisi ko 'You are amazing' bol kar photo bhejo 💖",
        "Apni life ka sabse embarrassing story share karo 📖",
        "Kisi ko 'Mujhe tumse pyaar hai' bol kar block karo 💀",
        "Apni bio mein kuch weird likho 📝",
        "Kisi bhi group mein 'Main aaj gussa hoon' bolo 😤",
        "Apne crush ko 'Hi' bol kar screenshot bhejo 😳",
        "Kisi ko 'You are my hero' bolo 🦸",
        "Apni last seen story mein kuch funny daalo 📱",
        "Kisi bhi chat mein 'Main bhagwan hoon' bolo 😂",
        "Apne best friend ko 'Main teri maa hoon' bolo 🤣",
        "Kisi random person ko 'You are beautiful' bolo 💕",
        "Apni life ki best memory share karo 📸"
        ]

        situation_texts = [
        "Agar tumhe 1 crore mil jaye toh kya karoge? 💰",
        "Agar tum 1 din invisible ho sakte ho toh kya karoge? 👻",
        "Agar tumhe ek wish mil jaye toh kya maangoge? ✨",
        "Agar tum president ban jao toh kya change karoge? 🏛️",
        "Agar tumhe time travel karna hai toh kahan jaoge? ⏳",
        "Agar tumhe 3 wishes mil jaye toh kya maangoge? 🌟",
        "Agar tum superpower choose kar sakte ho toh kya? 🦸",
        "Agar tumhe ek book likhni hai toh kya likhoge? 📖",
        "Agar tum famous ho jao toh kya karoge? 🌟",
        "Agar tumhe ek din kuch bhi karne ko mile toh kya karoge? 🎉",
        "Agar tumhe ek country choose karni hai toh kaunsi? 🌍",
        "Agar tumhe ek language seekhni hai toh kaunsi? 🗣️",
        "Agar tum apna naam change kar sakte ho toh kya rakhenge? 📛",
        "Agar tumhe apni life 1 word mein describe karni hai toh kya? 💬",
        "Agar tumhe ek famous personality se milna hai toh kaun? 🌟",
        "Agar tumhe 1 din life free ho toh kya karoge? 🎈",
        "Agar tumhe apni life ka best moment choose karna hai toh kya? 📸",
        "Agar tumhe ek skill seekhni hai toh kaunsi? 🎯",
        "Agar tumhe apni life ka worst moment choose karna hai toh kya? 😢",
        "Agar tumhe ek adventure karna hai toh kya? 🏔️",
        "Agar tumhe apni life change karni hai toh kya change karoge? 🔄",
        "Agar tumhe ek dream choose karna hai toh kya? 💭",
        "Agar tumhe apni life ka best decision choose karna hai toh kya? ✅",
        "Agar tumhe ek challenge choose karna hai toh kya? 🏆",
        "Agar tumhe apni life ka best friend choose karna hai toh kaun? 🤝",
        "Agar tumhe apni life ka worst decision choose karna hai toh kya? ❌",
        "Agar tumhe ek goal choose karna hai toh kya? 🎯",
        "Agar tumhe apni life ka best memory choose karna hai toh kya? 📸",
        "Agar tumhe apni life ka worst memory choose karna hai toh kya? 😢",
        "Agar tumhe apni life ka best achievement choose karna hai toh kya? 🏆"
        ]

        # ─── QUIZ TEXTS ────────────────────────────────────────────────────────

        quiz_texts = [
        {"q": "IIT JEE mein kaunsi book sabse important hai?", "a": "HC Verma"},
        {"q": "Physics mein 'g' ki value kya hai?", "a": "9.8"},
        {"q": "Formula E = mc² kisne diya?", "a": "Einstein"},
        {"q": "IIT ka full form kya hai?", "a": "Indian Institute of Technology"},
        {"q": "JEE ka full form kya hai?", "a": "Joint Entrance Examination"},
        {"q": "Physics mein SI unit of force kya hai?", "a": "Newton"},
        {"q": "Chemistry mein H2O kya hai?", "a": "Water"},
        {"q": "Maths mein 'pi' ki value kya hai?", "a": "3.14"},
        {"q": "Biology mein human body mein kitna water hai?", "a": "70%"},
        {"q": "IIT mein admission kaunsi exam se hota hai?", "a": "JEE Advanced"},
        {"q": "NEET ka full form kya hai?", "a": "National Eligibility cum Entrance Test"},
        {"q": "Human body mein kitna blood hai?", "a": "5 liters"},
        {"q": "Heart ka function kya hai?", "a": "Blood pump"},
        {"q": "Brain ka weight kitna hai?", "a": "1.4 kg"},
        {"q": "Biology mein DNA ka full form kya hai?", "a": "Deoxyribonucleic Acid"},
        {"q": "Human eye mein kitne colors dikhte hain?", "a": "10 million"},
        {"q": "Body mein kitne bones hain?", "a": "206"},
        {"q": "Blood group kaunse type ke hote hain?", "a": "A, B, AB, O"},
        {"q": "NEET mein kitne questions hote hain?", "a": "200"},
        {"q": "MBBS ka full form kya hai?", "a": "Bachelor of Medicine and Bachelor of Surgery"},
        {"q": "Earth ka sabse bada ocean kaunsa hai?", "a": "Pacific Ocean"},
        {"q": "World ka sabse lamba river kaunsa hai?", "a": "Nile River"},
        {"q": "Human body mein sabse bada organ kaunsa hai?", "a": "Skin"},
        {"q": "Universe ka sabse bada planet kaunsa hai?", "a": "Jupiter"},
        {"q": "Light ki speed kya hai?", "a": "3x10^8 m/s"},
        {"q": "Earth ka sabse ooncha mountain kaunsa hai?", "a": "Mount Everest"},
        {"q": "World mein sabse zyada population wala country kaunsa hai?", "a": "India"},
        {"q": "Computer ka brain kaunsa hai?", "a": "CPU"},
        {"q": "Mobile OS kaunse hain?", "a": "Android, iOS"},
        {"q": "World ka sabse bada desert kaunsa hai?", "a": "Sahara Desert"}
        ]

        # ─── RIDDLE TEXTS ──────────────────────────────────────────────────────

        riddle_texts = [
        {"q": "Main hoon jo andar aata hai par bahar nahi jaata. Main hoon jo har insaan ke paas hai. Main kya hoon?", "a": "Sans (Breath)"},
        {"q": "Main hoon jo duniya mein sabse bada hai, par main kisi ko dikhta nahi. Main kya hoon?", "a": "Pyaar (Love)"},
        {"q": "Main hoon jo haath mein aata hai par pakda nahi jaata. Main kya hoon?", "a": "Pani (Water)"},
        {"q": "Main hoon jo har insaan ko dikhta hai par koi dekh nahi sakta. Main kya hoon?", "a": "Andhera (Darkness)"},
        {"q": "Main hoon jo kabhi nahi rukta, kabhi nahi thakta. Main kya hoon?", "a": "Samay (Time)"},
        {"q": "Main hoon jo duniya mein sabse tez hai, par main kisi ko dikhta nahi. Main kya hoon?", "a": "Vichar (Thought)"},
        {"q": "Main hoon jo andar hota hai par bahar nahi. Main kya hoon?", "a": "Dil (Heart)"},
        {"q": "Main hoon jo har insaan ke paas hai par koi use nahi karta. Main kya hoon?", "a": "Dimag (Brain)"},
        {"q": "Main hoon jo kabhi nahi sota, kabhi nahi thakta. Main kya hoon?", "a": "Aankh (Eye)"},
        {"q": "Main hoon jo har insaan ki madad karta hai par koi use nahi dekhta. Main kya hoon?", "a": "Hawa (Air)"},
        {"q": "Main hoon jo duniya mein sabse chhota hai, par sab se bada kaam karta hoon. Main kya hoon?", "a": "Beej (Seed)"},
        {"q": "Main hoon jo kabhi nahi marta, kabhi nahi hota. Main kya hoon?", "a": "Atma (Soul)"},
        {"q": "The person who makes it doesn't need it. The person who buys it doesn't use it. The person who uses it doesn't know they're using it. What is it?", "a": "coffin"},
        ]

        # ─── FUN TEXTS (Joke, Fact, Compliment, Quotes) ──────────────────────

        joke_list = [
        "Main apni life mein itna positive hoon... ki blood group bhi B+ hai! 😂",
        "Teacher: Kal absent kyun the? Student: Sir, mujhe bukhar tha. Teacher: Proof? Student: Aaj aa gaya na! 😹",
        "Santa: Main ghar ke bahar khada hun. Banta: Andar aa jao. Santa: Andar wala bhi main hoon! 🤣",
        "Meri girlfriend ne kaha — tujhse better koi nahi. Phir chali gayi. Better koi mila hoga shayad 😂",
        "Doctor: Patient ko hawa ki zaroorat hai. Nurse: Kya karein? Doctor: Fan on karo. Nurse: Ceiling se pakad ke? 😹",
        "Ghar mein sabse zyada kaam mera — internet chalaana! 😂",
        "Padhai karo beta future bright hoga. Maine padhi — future gaya andhera mein. 😂",
        "Wo bolti hai 'I need space' — main bola ठीक है, NASA se contact karo! 😂",
        "Mera wifi itna slow hai ke circle of life bhi nahi chalta 🐢",
        "Main sochta hoon kal se gym jaunga... kal kab aata hai? 🤔",
        "Mummy ka 2 minute aur Maggi ka 2 minute kabhi same nahi hote",
        "Aaj kal log 'seen' karke itna attitude dikhate hain, jaise message nahi loan approve kar rahe ho",
        "Meri life itni private hai ki mujhe khud next update ka pata nahi hota 🤡 ",
        "Mere jokes pe sirf do log haste hain... main aur meri overconfidence 🤣",
        "Log bolte hain Be yourself... phir judge bhi wahi log karte hain",
        "Life ne itne twists diye hain ki Google Maps bhi rerouting kar de",
        ]

        fact_list = [
        "🧠 Insaan ka dimag 75% paani se bana hai!",
        "🐙 Octopus ke teen dil hote hain!",
        "🌙 Chand par mobile signal nahi hai — par WiFi aata hai ek satellite se! (Future plan 😂)",
        "🍯 Sahi tarike se rakha hua honey kabhi kharab nahi hota!",
        "⚡ Bijli ka ek bolt 5 times zyada garam hota hai sun ki surface se!",
        "🦈 Shark insaan se zyada purana hai — dinasors se bhi pehle!",
        "👁️ Insaan ki aankh 10 million rangon ko differentiate kar sakti hai!",
        "🐝 Ek machhar ek second mein 600 baar apne pankh hilata hai!",
        "🦒 Giraffe ki tongue 20 inches lambi hoti hai!",
        "🐧 Penguins ek dusre ko pehchanne ke liye unique calls use karte hain!",
        "🚀 Space mein awaaz travel nahi karti, kyunki wahan hawa nahi hoti.",
        "👅 Har insaan ki tongue print fingerprints ki tarah unique hoti hai.",
        "🦒 Giraffe apni 21-inch lambi tongue se kaan saaf kar sakta hai.",
        "⚡ Lightning ka temperature Suraj ki surface se bhi zyada hota hai",
        "🌍 Har second Earth par lagbhag 100 lightning strikes hoti hain.",
        "🐌 Snail 3 saal tak so sakta hai (kuch species mein).",
        "🧊 Garam paani kuch conditions mein thande paani se jaldi jam sakta hai (Mpemba effect).",
        "👀 Insaan ka brain ulta image dekhta hai aur use seedha process karta hai.",
        "🍌 Banana technically ek berry hai, lekin strawberry nahi.",
        "🦘 Kangaroo peeche ki taraf chal nahi sakta.",
        "🐧 Penguins propose karne ke liye apne partner ko chhota sa pathar gift karte hain (kuch species mein).",
        "💀 Human body mein itni blood vessels hoti hain ki unhe line mein jodo to lagbhag 100,000 km lambi ho jaayengi.",
        "🌌 Hum raat ko jo kuch stars dekhte hain, unki light kai saal pehle nikli hoti hai.",
        "🐝 Bees insaanon ke chehre pehchaan sakti hain.",
        ]

        compliment_list = [
        "Bhai tu bahut positive energy rakhta hai — seriously 🌟",
        "Teri thinking bahut alag hai — creative hai tu 🧠✨",
        "Tu jo bhi karta hai dil se karta hai — yeh rare hai ❤️",
        "Teri sense of humor? Top tier 😂👑",
        "Tujhse baat karna genuinely enjoyable hota hai 🗣️✨",
        "Tu ek natural leader hai — log tujhe follow karte hain 👑",
        "Teri mehnat dekh ke lagta hai, success teri waiting hai 💪",
        "Teri smile contagious hai — sabko khushi deti hai 😊",
        "Tu bahut strong insaan hai — sab handle kar leta hai 💪",
        "Teri vibe bohot positive hai — tere saath time acha lagta hai ✨",
        "You're one of a kind.",
        "Tumhari vibe alag hi level ki hai.",
        "You're effortlessly cool.",
        "Tum jahan hote ho, wahan energy aa jaati hai.",
        "You make everything look easy.",
        "Tumhari personality hi alag hai.",
        "You're genuinely impressive.",
        "Tumhare ideas hamesha unique hote hain.",
        "You're unforgettable.",
        "Tum confidence ka perfect example ho.",
        "Built different. 💯",
        "Aura speaks louder than words.",
        "You're the main character.",
        "Tumhari smile mood fix kar deti hai.",
        "You make people feel comfortable.",
        "You're naturally adorable.",
        "Tumhari laugh contagious hai.",
        "You're a walking green flag.",
        "You're sunshine in human form.",
        "Tumhare saath time ka pata hi nahi chalta.",
        "You have the kindest heart.",
        "You're effortlessly charming.",
        "You make ordinary moments special.",
        "Standards on another level.",
        "Too real to be fake.",
        "Calm outside, dangerous inside.",
        "Rare people have this kind of aura.",
        "Silent, but unforgettable.",
        "Class never chases attention.",
        "You don't follow trends, you set them.",
        "You're the flex you don't even need to show.",
        "Some people have looks, you have presence.",
        "Your aura deserves its own fan club.",
        "You're proof that being real is attractive.",
        "Not everyone shines, but you do.",
        "You don't need attention, attention finds you.",
        "Legends don't introduce themselves.",
        "Your vibe is expensive.",
        "You're the kind of person people remember.",
        "You make confidence look natural. 😎",
        ]

        quote_list = [
        "💭 Sapne woh nahi jo sote waqt aate hain, sapne woh hain jo sone nahi dete. — APJ Abdul Kalam",
        "💭 'Mehnat karo itna ki luck ko bhi mauka mile tujhe dhundhne ka.' — Unknown",
        "💭 'Duniya ka sabse bada teacher: failure hai.' — Unknown",
        "💭 'Ek accha dost aur ek accha kitaab — dono hi tujhe better banate hain.' — Unknown",
        "💭 'Zindagi ek echo hai — jo bejhoge woh wapas aayega.' — Unknown",
        "💭 'Success is not final, failure is not fatal: it is the courage to continue that counts.' — Churchill",
        "💭 'The only way to do great work is to love what you do.' — Steve Jobs",
        "💭 'In the middle of difficulty lies opportunity.' — Einstein",
        "💭 'Believe you can and you're halfway there.' — Theodore Roosevelt",
        "💭 'The best time to plant a tree was 20 years ago. The second best time is now.' — Chinese Proverb",
        "💭 People's lives don't end when they die, it ends when they lose faith. — Itachi Uchiha",
        "💭 Wake up to reality. Nothing ever goes as planned in this world. — Madara Uchiha",
        "💭 Those who break the rules are trash, but those who abandon their friends are worse than trash. — Kakashi Hatake",
        "💭 When people are protecting something truly precious, they truly become strong. — Haku",
        "💭 A lesson without pain is meaningless. — Edward Elric",
        "💭 A person grows up when they're able to overcome hardships. — Jiraiya",
        "💭 Power comes in response to a need, not a desire. — Goku",
        "💭 If you don't take risks, you can't create a future. — Monkey D. Luffy",
        "💭 The world isn't perfect, but it's there for us. — Roy Mustang",
        "💭 Fear is not evil. It tells you your weakness. — Gildarts Clive",
        "💭 The moment you think of giving up, think of the reason why you held on so long. — Natsu Dragneel",
        "💭 Hard work is worthless for those that don't believe in themselves. — Naruto Uzumaki",
        "💭 The difference between the novice and the master is that the master has failed more times than the novice has tried. — Koro-sensei",
        "💭 To know sorrow is not terrifying. What is terrifying is to know you can't go back to happiness. — Matsumoto Rangiku",
        "💭 Whatever you lose, you'll find it again. But what you throw away you'll never get back. — Kenshin Himura",
        "💭 Success is not final, failure is not fatal: it is the courage to continue that counts. — Winston Churchill",
        "💭 The only way to do great work is to love what you do. — Steve Jobs",
        "💭 Stay hungry, stay foolish. — Steve Jobs",
        "💭 Your time is limited, so don't waste it living someone else's life. — Steve Jobs",
        "💭 The future belongs to those who believe in the beauty of their dreams. — Eleanor Roosevelt",
        "💭 Be yourself; everyone else is already taken. — Oscar Wilde",
        "💭 It always seems impossible until it's done. — Nelson Mandela",
        "💭 Dream big and dare to fail. — Norman Vaughan",
        "💭 Do what you can, with what you have, where you are. — Theodore Roosevelt",
        "💭 Believe you can and you're halfway there. — Theodore Roosevelt",
        "💭 The best way to predict the future is to create it. — Peter Drucker",
        "💭 Discipline is choosing between what you want now and what you want most.",
        "💭 Don't watch the clock; do what it does. Keep going. — Sam Levenson",
        "💭 The journey of a thousand miles begins with one step. — Lao Tzu",
        "💭 Fall seven times, stand up eight. — Japanese Proverb",
        "💭 Action is the foundational key to all success. — Pablo Picasso",
        "💭 Work hard in silence, let success make the noise.",
        "💭 Great things never come from comfort zones.",
        "💭 Small steps every day lead to big results.",
        "💭 Consistency beats motivation.",
        "💭 Discipline creates freedom.",
        "💭 Your only competition is the person you were yesterday.",
        "💭 Never let success get to your head or failure get to your heart.",
        "💭 A calm mind is a powerful weapon.",
        "💭 Pressure creates diamonds.",
        ]
        # ─── PWR & OWS TEXT LISTS ─────────────────────────────────────────────
        pwr_texts = [
        "Kyun",
        "Re",
        "Mc",
        "Ka",
        "Baccha",
        "Apna",
        "Papa",
        "Sa",
        "Hawabji",
        "Karega",
        "Randi",
        "Rand",
        "Ka",
        "Beta",
        "Teri",
        "Maa",
        "Ki",
        "Kali",
        "Kali",
        "Chut",
        "Ma",
        "Lund",
        "Daal",
        "Ka",
        "Mix",
        "Kar",
        "Dunga",
        "Te",
        "RANDI",
        "Ka",
        "Beta",
        "Teri",
        "Mausi",
        "Ko",
        "Apna",
        "Lund",
        "Pa",
        "Baitha",
        "Ka",
        "Puri",
        "Duniya",
        "Ghumunga",
        "Re",
        "Chinnar",
        "Ka",
        "Beta",
        "Tere",
        "Baap",
        "Ko",
        "Apna",
        "Goto",
        "Sa",
        "Chap",
        "Ka",
        "Maar",
        "DUNGA",
        "Mc",
        "Dhanda",
        "Wali",
        "Ka",
        "Ladka",
        "Kaha",
        "Gayi",
        "Teri",
        "Speed",
        "Abb",
        "Apna",
        "Papa",
        "Sa",
        "Hawabaji",
        "Nahi",
        "KAREGA",
        "Mc",
        "Ka",
        "Pill",
        "Teri",
        "Bhen",
        "Ka",
        "Rape",
        "Kar",
        "Dunga",
        "Bc",
        "Majduri",
        "Ruko",
        "Teri",
        "Tho",
        "Mai",
        "Tera",
        "Bhen",
        "Betiyon",
        "Ka",
        "Rape",
        "Kar",
        "Ka",
        "Bhagg",
        "Jaunga",
        "Mc",
        "Teri",
        "Maa",
        "Ke"
                
        ]
        ows_texts = [
        "Kyun",
        "Re",
        "Mc",
        "Ka",
        "Baccha",
        "Apna",
        "Papa",
        "Sa",
        "Hawabji",
        "Karega",
        "Randi",
        "Rand",
        "Ka",
        "Beta",
        "Teri",
        "Maa",
        "Ki",
        "Kali",
        "Kali",
        "Chut",
        "Ma",
        "Lund",
        "Daal",
        "Ka",
        "Mix",
        "Kar",
        "Dunga",
        "Te",
        "RANDI",
        "Ka",
        "Beta",
        "Teri",
        "Mausi",
        "Ko",
        "Apna",
        "Lund",
        "Pa",
        "Baitha",
        "Ka",
        "Puri",
        "Duniya",
        "Ghumunga",
        "Re",
        "Chinnar",
        "Ka",
        "Beta",
        "Tere",
        "Baap",
        "Ko",
        "Apna",
        "Goto",
        "Sa",
        "Chap",
        "Ka",
        "Maar",
        "DUNGA",
        "Mc",
        "Dhanda",
        "Wali",
        "Ka",
        "Ladka",
        "Kaha",
        "Gayi",
        "Teri",
        "Speed",
        "Abb",
        "Apna",
        "Papa",
        "Sa",
        "Hawabaji",
        "Nahi",
        "KAREGA",
        "Mc",
        "Ka",
        "Pill",
        "Teri",
        "Bhen",
        "Ka",
        "Rape",
        "Kar",
        "Dunga",
        "Bc",
        "Majduri",
        "Ruko",
        "Teri",
        "Tho",
        "Mai",
        "Tera",
        "Bhen",
        "Betiyon",
        "Ka",
        "Rape",
        "Kar",
        "Ka",
        "Bhagg",
        "Jaunga",
        "Mc",
        "Teri",
        "Maa",
        "Ke"
        ]

        # ─── LOAD/SAVE FUNCTIONS ─────────────────────────────────────────────
        def load_admins():
            try:
                if not os.path.isfile(ADMINS_FILE):
                    return set()
                with open(ADMINS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return {int(x) for x in data} if isinstance(data, list) else set()
            except:
                return set()

        def save_admins():
            try:
                with open(ADMINS_FILE, "w", encoding="utf-8") as f:
                    json.dump(sorted(user_bot.admins), f, indent=2)
            except:
                pass

        def load_notes():
            try:
                if not os.path.isfile(NOTES_FILE):
                    return {}
                with open(NOTES_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                return {int(k): str(v) for k, v in raw.items() if isinstance(raw, dict)}
            except:
                return {}

        def save_notes():
            try:
                with open(NOTES_FILE, "w", encoding="utf-8") as f:
                    json.dump(user_bot.notes, f, ensure_ascii=False, indent=2)
            except:
                pass

        def load_banner():
            try:
                if not os.path.isfile(BANNER_FILE):
                    return None
                with open(BANNER_FILE, "r", encoding="utf-8") as f:
                    raw = f.read().strip()
                if ":" not in raw:
                    return None
                chat, msg = raw.split(":", 1)
                return (int(chat), int(msg))
            except:
                return None

        def save_banner():
            try:
                if not user_bot.menu_banner_msg:
                    if os.path.isfile(BANNER_FILE):
                        os.remove(BANNER_FILE)
                    return
                with open(BANNER_FILE, "w", encoding="utf-8") as f:
                    f.write(f"{user_bot.menu_banner_msg[0]}:{user_bot.menu_banner_msg[1]}")
            except:
                pass

        def load_common_spam():
            try:
                if not os.path.isfile(COMMON_SPAM_FILE):
                    return []
                with open(COMMON_SPAM_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return [str(x) for x in data] if isinstance(data, list) else []
            except:
                return []

        def save_common_spam():
            try:
                with open(COMMON_SPAM_FILE, "w", encoding="utf-8") as f:
                    json.dump(user_bot.spam_texts, f, ensure_ascii=False, indent=2)
            except:
                pass

        def load_filters():
            try:
                if not os.path.isfile(FILTERS_FILE):
                    return []
                with open(FILTERS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, list) else []
            except:
                return []

        def save_filters():
            try:
                with open(FILTERS_FILE, "w", encoding="utf-8") as f:
                    json.dump(user_bot.filters, f, ensure_ascii=False, indent=2)
            except:
                pass

        def load_autoreply():
            try:
                if not os.path.isfile(AUTO_REPLY_FILE):
                    return None
                with open(AUTO_REPLY_FILE, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except:
                return None

        def save_autoreply(text):
            try:
                with open(AUTO_REPLY_FILE, "w", encoding="utf-8") as f:
                    f.write(text if text else "")
            except:
                pass

        def get_sangmata_file(uid):
            return os.path.join(SANGMATA_DIR, f"{uid}.json")

        def load_sangmata(uid):
            fname = get_sangmata_file(uid)
            try:
                if not os.path.isfile(fname):
                    return []
                with open(fname, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return []

        def save_sangmata(uid, history):
            fname = get_sangmata_file(uid)
            try:
                with open(fname, "w", encoding="utf-8") as f:
                    json.dump(history, f, ensure_ascii=False, indent=2)
            except:
                pass

        user_bot.admins = load_admins()
        user_bot.notes = load_notes()
        user_bot.menu_banner_msg = load_banner()
        user_bot.spam_texts = load_common_spam()
        user_bot.filters = load_filters()
        user_bot.auto_reply = load_autoreply()
        user_bot.dm_shield_enabled = False
        user_bot.god_protection_enabled = False
        user_bot.frozen = False
        user_bot.dm_approved = set()
        user_bot.dm_blocked = set()
        user_bot.god_protection = set()
        user_bot.gp_mentions = {}
        user_bot.gp_duplicate = {}
        user_bot.gp_flood = {}

        # ─── LOAD PER-USER FILTERS FROM DATABASE ─────────────────────
        async def load_user_filters(uid: int):
            async with db_pool.acquire() as conn:
                rows = await conn.fetch("SELECT trigger_word, reply_text, reply_sticker_id, reply_type FROM user_filters WHERE user_id = $1", uid)
            filters = {}
            for row in rows:
                filters[row['trigger_word']] = {
                    'text': row['reply_text'],
                    'sticker_id': row['reply_sticker_id'],
                    'type': row['reply_type']
                }
            return filters

        user_bot.user_filters = await load_user_filters(me.id)
        user_bot.filter_reply_ids = set()

        # ─── DM SHIELD FUNCTIONS ──────────────────────────────────────
        async def get_warnings(uid: int, target_id: int) -> int:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT count FROM dm_warnings WHERE user_id = $1 AND target_id = $2",
                    uid, target_id
                )
                return row["count"] if row else 0

        async def add_warning(uid: int, target_id: int) -> int:
            async with db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO dm_warnings (user_id, target_id, count)
                    VALUES ($1, $2, 1)
                    ON CONFLICT (user_id, target_id)
                    DO UPDATE SET count = dm_warnings.count + 1
                """, uid, target_id)
                row = await conn.fetchrow(
                    "SELECT count FROM dm_warnings WHERE user_id = $1 AND target_id = $2",
                    uid, target_id
                )
                return row["count"]

        async def reset_warnings(uid: int, target_id: int):
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM dm_warnings WHERE user_id = $1 AND target_id = $2",
                    uid, target_id
                )

        async def is_blocked(uid: int, target_id: int) -> bool:
            if target_id in user_bot.dm_blocked:
                return True
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT 1 FROM dm_blocked WHERE user_id = $1 AND blocked_id = $2",
                    uid, target_id
                )
                return row is not None

        async def block_user(uid: int, target_id: int):
            # Prevent blocking yourself or the owner
            if target_id == uid or target_id in OWNER_IDS:
                return

            async with db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO dm_blocked (user_id, blocked_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    uid, target_id
                )
                await reset_warnings(uid, target_id)

            user_bot.dm_blocked.add(target_id)

            # Use low‑level API for reliable blocking
            for attempt in range(3):
                try:
                    await user_bot(BlockRequest(id=target_id))
                    break
                except FloodWaitError as e:
                    wait = e.seconds + 1
                    print(f"Block flood wait: {wait}s for {target_id}")
                    await asyncio.sleep(wait)
                except Exception as e:
                    print(f"Block error (attempt {attempt+1}): {e}")
                    # Fallback: try with entity
                    try:
                        entity = await user_bot.get_entity(target_id)
                        await user_bot(BlockRequest(id=entity))
                        break
                    except Exception:
                        continue
            else:
                print(f"❌ Failed to block {target_id} after 3 attempts")

        async def unblock_user(uid: int, target_id: int):
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM dm_blocked WHERE user_id = $1 AND blocked_id = $2",
                    uid, target_id
                )
                await reset_warnings(uid, target_id)

            user_bot.dm_blocked.discard(target_id)

            for attempt in range(3):
                try:
                    await user_bot(UnblockRequest(id=target_id))
                    break
                except FloodWaitError as e:
                    wait = e.seconds + 1
                    print(f"Unblock flood wait: {wait}s for {target_id}")
                    await asyncio.sleep(wait)
                except Exception as e:
                    print(f"Unblock error (attempt {attempt+1}): {e}")
                    try:
                        entity = await user_bot.get_entity(target_id)
                        await user_bot(UnblockRequest(id=entity))
                        break
                    except Exception:
                        continue
            else:
                print(f"❌ Failed to unblock {target_id} after 3 attempts")

        # ─── HELPER FUNCTIONS ──────────────────────────────────────────
        async def is_premium_user(uid: int) -> bool:
            prem = await check_premium_status(uid)
            return prem is not None

        async def safe_send(chat, text, reply_to=None, retries=3):
            for attempt in range(retries):
                try:
                    if isinstance(text, str):
                        return await user_bot.send_message(chat, text, reply_to=reply_to)
                    else:
                        return await user_bot.send_file(chat, text, reply_to=reply_to)
                except FloodWaitError as fw:
                    await asyncio.sleep(fw.seconds + 1)
                    continue
                except Exception:
                    await asyncio.sleep(1)
            return None

        async def safe_edit(event, text):
            try:
                return await event.edit(text)
            except FloodWaitError as fw:
                await asyncio.sleep(fw.seconds + 1)
                try:
                    return await event.edit(text)
                except:
                    try:
                        return await event.reply(text)
                    except:
                        return
            except MessageNotModifiedError:
                pass
            except Exception:
                try:
                    return await event.reply(text)
                except:
                    return

        async def get_targets(event, arg=""):
            targets = set()
            if event.is_reply:
                try:
                    r = await event.get_reply_message()
                    if r and r.sender_id:
                        targets.add(int(r.sender_id))
                except:
                    pass
            if arg:
                for part in arg.strip().split():
                    if part.isdigit():
                        targets.add(int(part))
                    else:
                        try:
                            ent = await user_bot.get_entity(part)
                            if ent and hasattr(ent, "id"):
                                targets.add(int(ent.id))
                        except:
                            pass
            try:
                me2 = await user_bot.get_me()
                targets.discard(me2.id)
            except:
                pass
            return targets

        def is_admin(uid):
            return uid in OWNER_IDS or uid in user_bot.admins

        # ─── NC LOOP ─────────────────────────────────────────────────────────
        async def nc_loop(chat_id, lang, text):
            # Patterns are empty, so do nothing
            pass

        # ─── COMMAND REGISTRY ──────────────────────────────────────────────
        commands = {}

        def register_cmd(name, needs_reply=False, group_only=False, premium=False):
            def decorator(func):
                key = name.lower().strip()
                commands[key] = {
                    "func": func,
                    "needs_reply": needs_reply,
                    "group_only": group_only,
                    "premium": premium,
                }
                return func
            return decorator

        owner_only_commands = {
            "addtext", "edittext", "deltext", "cleartext",
            "spraydelay", "addadmin", "deladmin", "giftpremium",
            "freeze", "unfreeze", "stopallspray", "stopall"
        }

        # ─── MENU REGISTRATION (FIXED) ────────────────────────────────────
        @user_bot.on(events.NewMessage(pattern=r'\.(menu\d*[a-z]*)', outgoing=True))
        async def menu_handler(event):
            cmd = event.pattern_match.group(1).strip().lower()
            text = MENU_MAP.get(cmd)
            if text is not None:
                await safe_edit(event, text or "⚠️ This menu is empty.")
            else:
                await safe_edit(event, f"❌ Menu '{cmd}' not found.")

        # ─── ADD .cmds COMMAND ─────────────────────────────────────────────
        @user_bot.on(events.NewMessage(pattern=r'\.cmds', outgoing=True))
        async def cmd_cmds(event):
            cmd_list = sorted(commands.keys())
            if not cmd_list:
                await safe_edit(event, "📭 No commands registered.")
                return
            msg = "📋 **Available Commands:**\n" + "\n".join(f"• .{c}" for c in cmd_list)
            await safe_edit(event, msg)

        # ─── STOPALL ────────────────────────────────────────────────────────
        @register_cmd("stopall")
        async def cmd_stopall(event, _):
            for chat, task in list(user_bot.spray_tasks.items()):
                try:
                    task.cancel()
                except:
                    pass
            user_bot.spray_tasks.clear()

            user_bot.reply_users.clear()
            user_bot.rr_users.clear()
            user_bot.flag_users.clear()
            user_bot.hrr_users.clear()
            user_bot.replygod_users.clear()
            user_bot.custom_raid_users.clear()
            user_bot.shayari_raid.clear()
            user_bot.rizz_raid.clear()
            user_bot.pickup_raid.clear()
            user_bot.romance_raid.clear()
            user_bot.troll_raid.clear()
            user_bot.ragebait_raid.clear()
            user_bot.roast_raid.clear()
            user_bot.pickup_users.clear()
            user_bot.romance_users.clear()
            user_bot.trollraid_users.clear()
            user_bot.ragebait_users.clear()
            user_bot.roastraid_users.clear()
            user_bot.attack_raid.clear()
            user_bot.war_raid.clear()
            user_bot.savage_raid.clear()
            user_bot.ultra_raid.clear()
            user_bot.shame_raid.clear()
            user_bot.diss_raid.clear()
            user_bot.devil_raid.clear()
            user_bot.karma_raid.clear()
            user_bot.doom_raid.clear()
            user_bot.attackraid_users.clear()
            user_bot.warraid_users.clear()
            user_bot.savageraid_users.clear()
            user_bot.ultraraid_users.clear()
            user_bot.shame_users.clear()
            user_bot.diss_users.clear()
            user_bot.devil_users.clear()
            user_bot.karma_users.clear()
            user_bot.doom_users.clear()
            user_bot.pwr_raid.clear()
            user_bot.pwr_users.clear()
            user_bot.pwr_index.clear()
            user_bot.ows_spam.clear()
            user_bot.ows_users.clear()
            user_bot.ows_index.clear()
            user_bot.premium_raid_targets.clear()
            user_bot.premium_spam_targets.clear()
            if user_bot.autotag_active:
                user_bot.autotag_active = False
                if user_bot.autotag_task:
                    user_bot.autotag_task.cancel()
                    user_bot.autotag_task = None
            if user_bot.NC_STATE.get("active"):
                user_bot.NC_STATE["active"] = False
                if user_bot.NC_STATE.get("task") and not user_bot.NC_STATE["task"].done():
                    user_bot.NC_STATE["task"].cancel()

            await safe_edit(event, "🛑 **All raids, spams, and sprays have been stopped!**")

        # ─── PROTECTION COMMANDS ──────────────────────────────────────────
        @register_cmd("protect", premium=True)
        async def cmd_protect(event, arg):
            if not arg:
                return
            cmd = arg.strip().lower()
            if cmd not in commands:
                await safe_edit(event, f"❌ Command `.{cmd}` not found.")
                return
            await add_protection(event.sender_id, cmd)
            await safe_edit(event, f"🛡️ Protected from `.{cmd}` now.")

        @register_cmd("unprotect", premium=True)
        async def cmd_unprotect(event, arg):
            if not arg:
                return
            cmd = arg.strip().lower()
            await remove_protection(event.sender_id, cmd)
            await safe_edit(event, f"🔓 Removed protection from `.{cmd}`.")

        @register_cmd("protectlist", premium=True)
        async def cmd_protectlist(event, _):
            prot = await get_protections(event.sender_id)
            if not prot:
                await safe_edit(event, "📭 You have no protected commands.")
                return
            msg = "🛡️ **Protected Commands:**\n" + "\n".join(f"• `.{c}`" for c in sorted(prot))
            await safe_edit(event, msg)

        @register_cmd("premiumstatus", premium=True)
        async def cmd_premiumstatus(event, _):
            data = await check_premium_status(event.sender_id)
            if not data:
                await safe_edit(event, "❌ You are not a premium user.")
                return
            expiry = data['expiry_date'].strftime("%Y-%m-%d %H:%M:%S")
            plan = data['plan'].upper()
            await safe_edit(event, f"💎 **Premium Status**\n━━━━━━━━━━━━━━━\n📅 Plan: {plan}\n⏳ Expires: {expiry}\n🛡️ Protected from all raids/spam/deathgod.")

        # ─── TYPING EFFECT ──────────────────────────────────────────────────
        @register_cmd("typing", premium=True)
        async def cmd_typing(event, arg):
            if not arg:
                return
            parts = arg.split(maxsplit=1)
            style = "bold"
            text = arg
            if len(parts) == 2 and parts[0].lower() in ['bold', 'italic', 'double', 'script', 'mono', 'circle', 'square', 'default']:
                style = parts[0].lower()
                text = parts[1]
            bold_map = {
                'a': '𝗮', 'b': '𝗯', 'c': '𝗰', 'd': '𝗱', 'e': '𝗲', 'f': '𝗳', 'g': '𝗴', 'h': '𝗵',
                'i': '𝗶', 'j': '𝗷', 'k': '𝗸', 'l': '𝗹', 'm': '𝗺', 'n': '𝗻', 'o': '𝗼', 'p': '𝗽',
                'q': '𝗾', 'r': '𝗿', 's': '𝘀', 't': '𝘁', 'u': '𝘂', 'v': '𝘃', 'w': '𝘄', 'x': '𝘅',
                'y': '𝘆', 'z': '𝘇',
                'A': '𝗔', 'B': '𝗕', 'C': '𝗖', 'D': '𝗗', 'E': '𝗘', 'F': '𝗙', 'G': '𝗚', 'H': '𝗛',
                'I': '𝗜', 'J': '𝗝', 'K': '𝗞', 'L': '𝗟', 'M': '𝗠', 'N': '𝗡', 'O': '𝗢', 'P': '𝗣',
                'Q': '𝗤', 'R': '𝗥', 'S': '𝗦', 'T': '𝗧', 'U': '𝗨', 'V': '𝗩', 'W': '𝗪', 'X': '𝗫',
                'Y': '𝗬', 'Z': '𝗭',
                '0': '𝟬', '1': '𝟭', '2': '𝟮', '3': '𝟯', '4': '𝟰',
                '5': '𝟱', '6': '𝟲', '7': '𝟳', '8': '𝟴', '9': '𝟵'
            }
            italic_map = {
                'a': '𝘢', 'b': '𝘣', 'c': '𝘤', 'd': '𝘥', 'e': '𝘦', 'f': '𝘧', 'g': '𝘨', 'h': '𝘩',
                'i': '𝘪', 'j': '𝘫', 'k': '𝘬', 'l': '𝘭', 'm': '𝘮', 'n': '𝘯', 'o': '𝘰', 'p': '𝘱',
                'q': '𝘲', 'r': '𝘳', 's': '𝘴', 't': '𝘵', 'u': '𝘶', 'v': '𝘷', 'w': '𝘸', 'x': '𝘹',
                'y': '𝘺', 'z': '𝘻',
                'A': '𝘈', 'B': '𝘉', 'C': '𝘊', 'D': '𝘋', 'E': '𝘌', 'F': '𝘍', 'G': '𝘎', 'H': '𝘏',
                'I': '𝘐', 'J': '𝘑', 'K': '𝘒', 'L': '𝘓', 'M': '𝘔', 'N': '𝘕', 'O': '𝘖', 'P': '𝘗',
                'Q': '𝘘', 'R': '𝘙', 'S': '𝘚', 'T': '𝘛', 'U': '𝘜', 'V': '𝘝', 'W': '𝘞', 'X': '𝘟',
                'Y': '𝘠', 'Z': '𝘡'
            }
            double_map = {
                'a': '𝕒', 'b': '𝕓', 'c': '𝕔', 'd': '𝕕', 'e': '𝕖', 'f': '𝕗', 'g': '𝕘', 'h': '𝕙',
                'i': '𝕚', 'j': '𝕛', 'k': '𝕜', 'l': '𝕝', 'm': '𝕞', 'n': '𝕟', 'o': '𝕠', 'p': '𝕡',
                'q': '𝕢', 'r': '𝕣', 's': '𝕤', 't': '𝕥', 'u': '𝕦', 'v': '𝕧', 'w': '𝕨', 'x': '𝕩',
                'y': '𝕪', 'z': '𝕫',
                'A': '𝔸', 'B': '𝔹', 'C': 'ℂ', 'D': '𝔻', 'E': '𝔼', 'F': '𝔽', 'G': '𝔾', 'H': 'ℍ',
                'I': '𝕀', 'J': '𝕁', 'K': '𝕂', 'L': '𝕃', 'M': '𝕄', 'N': 'ℕ', 'O': '𝕆', 'P': 'ℙ',
                'Q': 'ℚ', 'R': 'ℝ', 'S': '𝕊', 'T': '𝕋', 'U': '𝕌', 'V': '𝕍', 'W': '𝕎', 'X': '𝕏',
                'Y': '𝕐', 'Z': 'ℤ',
                '0': '𝟘', '1': '𝟙', '2': '𝟚', '3': '𝟛', '4': '𝟜',
                '5': '𝟝', '6': '𝟞', '7': '𝟟', '8': '𝟠', '9': '𝟡'
            }
            script_map = {
                'a': '𝓪', 'b': '𝓫', 'c': '𝓬', 'd': '𝓭', 'e': '𝓮', 'f': '𝓯', 'g': '𝓰', 'h': '𝓱',
                'i': '𝓲', 'j': '𝓳', 'k': '𝓴', 'l': '𝓵', 'm': '𝓶', 'n': '𝓷', 'o': '𝓸', 'p': '𝓹',
                'q': '𝓺', 'r': '𝓻', 's': '𝓼', 't': '𝓽', 'u': '𝓾', 'v': '𝓿', 'w': '𝔀', 'x': '𝔁',
                'y': '𝔂', 'z': '𝔃',
                'A': '𝓐', 'B': '𝓑', 'C': '𝓒', 'D': '𝓓', 'E': '𝓔', 'F': '𝓕', 'G': '𝓖', 'H': '𝓗',
                'I': '𝓘', 'J': '𝓙', 'K': '𝓚', 'L': '𝓛', 'M': '𝓜', 'N': '𝓝', 'O': '𝓞', 'P': '𝓟',
                'Q': '𝓠', 'R': '𝓡', 'S': '𝓢', 'T': '𝓣', 'U': '𝓤', 'V': '𝓥', 'W': '𝓦', 'X': '𝓧',
                'Y': '𝓨', 'Z': '𝓩'
            }
            mono_map = {
                'a': '𝚊', 'b': '𝚋', 'c': '𝚌', 'd': '𝚍', 'e': '𝚎', 'f': '𝚏', 'g': '𝚐', 'h': '𝚑',
                'i': '𝚒', 'j': '𝚓', 'k': '𝚔', 'l': '𝚕', 'm': '𝚖', 'n': '𝚗', 'o': '𝚘', 'p': '𝚙',
                'q': '𝚚', 'r': '𝚛', 's': '𝚜', 't': '𝚝', 'u': '𝚞', 'v': '𝚟', 'w': '𝚠', 'x': '𝚡',
                'y': '𝚢', 'z': '𝚣',
                'A': '𝙰', 'B': '𝙱', 'C': '𝙲', 'D': '𝙳', 'E': '𝙴', 'F': '𝙵', 'G': '𝙶', 'H': '𝙷',
                'I': '𝙸', 'J': '𝙹', 'K': '𝙺', 'L': '𝙻', 'M': '𝙼', 'N': '𝙽', 'O': '𝙾', 'P': '𝙿',
                'Q': '𝚀', 'R': '𝚁', 'S': '𝚂', 'T': '𝚃', 'U': '𝚄', 'V': '𝚅', 'W': '𝚆', 'X': '𝚇',
                'Y': '𝚈', 'Z': '𝚉'
            }
            circle_map = {
                'a': 'ⓐ', 'b': 'ⓑ', 'c': 'ⓒ', 'd': 'ⓓ', 'e': 'ⓔ', 'f': 'ⓕ', 'g': 'ⓖ', 'h': 'ⓗ',
                'i': 'ⓘ', 'j': 'ⓙ', 'k': 'ⓚ', 'l': 'ⓛ', 'm': 'ⓜ', 'n': 'ⓝ', 'o': 'ⓞ', 'p': 'ⓟ',
                'q': 'ⓠ', 'r': 'ⓡ', 's': 'ⓢ', 't': 'ⓣ', 'u': 'ⓤ', 'v': 'ⓥ', 'w': 'ⓦ', 'x': 'ⓧ',
                'y': 'ⓨ', 'z': 'ⓩ',
                'A': 'Ⓐ', 'B': 'Ⓑ', 'C': 'Ⓒ', 'D': 'Ⓓ', 'E': 'Ⓔ', 'F': 'Ⓕ', 'G': 'Ⓖ', 'H': 'Ⓗ',
                'I': 'Ⓘ', 'J': 'Ⓙ', 'K': 'Ⓚ', 'L': 'Ⓛ', 'M': 'Ⓜ', 'N': 'Ⓝ', 'O': 'Ⓞ', 'P': 'Ⓟ',
                'Q': 'Ⓠ', 'R': 'Ⓡ', 'S': 'Ⓢ', 'T': 'Ⓣ', 'U': 'Ⓤ', 'V': 'Ⓥ', 'W': 'Ⓦ', 'X': 'Ⓧ',
                'Y': 'Ⓨ', 'Z': 'Ⓩ',
                '0': '⓪', '1': '①', '2': '②', '3': '③', '4': '④',
                '5': '⑤', '6': '⑥', '7': '⑦', '8': '⑧', '9': '⑨'
            }
            square_map = {
                'a': '🅰', 'b': '🅱', 'c': '🅲', 'd': '🅳', 'e': '🅴', 'f': '🅵', 'g': '🅶', 'h': '🅷',
                'i': '🅸', 'j': '🅹', 'k': '🅺', 'l': '🅻', 'm': '🅼', 'n': '🅽', 'o': '🅾', 'p': '🅿',
                'q': '🆀', 'r': '🆁', 's': '🆂', 't': '🆃', 'u': '🆄', 'v': '🆅', 'w': '🆆', 'x': '🆇',
                'y': '🆈', 'z': '🆉',
                '0': '🅾', '1': '🆒', '2': '🆓', '3': '🆔', '4': '🆕',
                '5': '🆖', '6': '🆗', '7': '🆘', '8': '🆙', '9': '🆚'
            }
            font_maps = {
                'bold': bold_map,
                'italic': italic_map,
                'double': double_map,
                'script': script_map,
                'mono': mono_map,
                'circle': circle_map,
                'square': square_map,
                'default': {}
            }
            char_map = font_maps.get(style, bold_map)
            stylish_text = ''.join(char_map.get(c, c) for c in text) if style != 'default' else text
            try:
                await event.delete()
            except:
                pass
            msg = await user_bot.send_message(event.chat_id, "")  # No emoji
            for i in range(1, len(stylish_text) + 1):
                current_text = f"{stylish_text[:i]}"
                try:
                    await msg.edit(current_text)
                    await asyncio.sleep(random.uniform(0.02, 0.08))  # Faster
                except Exception:
                    pass
            try:
                await msg.edit(stylish_text)
            except:
                pass

        # ─── AFK ──────────────────────────────────────────────────────────────
        user_bot.afk_data = {}
        @register_cmd("afk", premium=True)
        async def cmd_afk(event, arg):
            uid = event.sender_id
            if arg and arg.lower() == "off":
                if uid in user_bot.afk_data:
                    del user_bot.afk_data[uid]
                    await safe_edit(event, "✅ AFK removed.")
                else:
                    await safe_edit(event, "❌ You were not AFK.")
                return
            reason = arg or "I'm away, will reply later."
            user_bot.afk_data[uid] = {"reason": reason, "time": time.time()}
            await safe_edit(event, f"✅ AFK set: {reason}")

        @user_bot.on(events.NewMessage)
        async def afk_handler(event):
            if event.out:
                return
            sender = event.sender_id
            if sender in user_bot.afk_data:
                # Check if mentioned or replied to
                is_mentioned = False
                if event.text and ("@" + me.username in event.text or "tg://user?id=" + str(me.id) in event.text):
                    is_mentioned = True
                if event.is_reply:
                    try:
                        reply = await event.get_reply_message()
                        if reply and reply.sender_id == me.id:
                            is_mentioned = True
                    except:
                        pass
                if is_mentioned:
                    data = user_bot.afk_data[sender]
                    await safe_send(event.chat_id, f"🤖 **AFK:** {data['reason']} (since {int(time.time() - data['time'])}s ago)", reply_to=event.id)

        # ─── TEXT FORMATTING ──────────────────────────────────────────────────
        def format_text_func(name, transform):
            @register_cmd(name, premium=True)
            async def cmd(event, arg):
                if not arg:
                    return
                result = transform(arg)
                await safe_edit(event, f"**{name.upper()}**\n━━━━━━━━━━━━━━━\n{result}")
            return cmd

        transforms = {
            "upper": str.upper,
            "lower": str.lower,
            "reverse": lambda s: s[::-1],
            "len": lambda s: str(len(s)),
            "wcount": lambda s: str(len(s.split())),
            "bold": lambda s: f"**{s}**",
            "italic": lambda s: f"__{s}__",
            "mono": lambda s: f"`{s}`",
            "camel": lambda s: ''.join(word.capitalize() if i>0 else word.lower() for i, word in enumerate(s.split())),
            "titlecase": lambda s: s.title(),
            "snake": lambda s: '_'.join(s.lower().split()),
            "shout": lambda s: s.upper() + "!",
            "mock": lambda s: ''.join(c.upper() if i%2 else c.lower() for i,c in enumerate(s)),
            "spaceit": lambda s: ' '.join(s),
            "removespaces": lambda s: ''.join(s.split()),
            "clap": lambda s: ' '.join(s.split()),
            "mirror": lambda s: s + s[::-1],
            "flip_text": lambda s: s[::-1].translate(str.maketrans("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ", "ɐqɔpǝɟɓɥıɾʞlɯuodbɹsʇnʌʍxʎz∀BƆDƎℲ⅁HIſʞLMNOԀQɹS┴∩ΛMX⅄Z")),
        }
        for name, func in transforms.items():
            format_text_func(name, func)

        @register_cmd("big", premium=True)
        async def cmd_big(event, arg):
            await safe_edit(event, f"**BIG**\n━━━━━━━━━━━━━━━\n{arg.upper()}")

        @register_cmd("small", premium=True)
        async def cmd_small(event, arg):
            await safe_edit(event, f"**SMALL**\n━━━━━━━━━━━━━━━\n{arg.lower()}")

        @register_cmd("shadow", premium=True)
        async def cmd_shadow(event, arg):
            await safe_edit(event, f"**SHADOW**\n━━━━━━━━━━━━━━━\n***{arg}***")

        @register_cmd("zalgo", premium=True)
        async def cmd_zalgo(event, arg):
            diacritics = r"̴̵̶̷̸̡̢̧̨̛̖̗̘̙̜̝̞̟̠̣̤̥̦̩̪̫̬̭̮̯̰̱̲̳̹̺̻̼͇͈͉͍͎̀́̂̃̄̅̆̇̈̉̊̋̌̍̎̏̐̑̒̓̔̽̾̿̀́͂̓̈́͆͊͋͌̕̚ͅ͏͓͔͕͖͙͚͐͑͒͗͛ͣͤͥͦͧͨͩͪͫͬͭͮͯ͘͜͟͢͝͞͠͡"
            zalgo = ''.join(c + ''.join(random.choice(diacritics) for _ in range(random.randint(1, 3))) for c in arg)
            await safe_edit(event, f"**ZALGO**\n━━━━━━━━━━━━━━━\n{zalgo}")

        @register_cmd("leet", premium=True)
        async def cmd_leet(event, arg):
            leet_map = str.maketrans("aAbBeEiIoOsStT", "4@8£3!10$7+")
            await safe_edit(event, f"**LEET**\n━━━━━━━━━━━━━━━\n{arg.translate(leet_map)}")

        # ─── UTILITY COMMANDS ──────────────────────────────────────────────────
        @register_cmd("hex", premium=True)
        async def cmd_hex(event, arg):
            hex_str = arg.encode('utf-8').hex()
            await safe_edit(event, f"**HEX**\n━━━━━━━━━━━━━━━\n{hex_str}")

        @register_cmd("octal", premium=True)
        async def cmd_octal(event, arg):
            oct_str = ' '.join(format(ord(c), 'o') for c in arg)
            await safe_edit(event, f"**OCTAL**\n━━━━━━━━━━━━━━━\n{oct_str}")

        @register_cmd("ascii", premium=True)
        async def cmd_ascii(event, arg):
            ascii_codes = ' '.join(str(ord(c)) for c in arg)
            await safe_edit(event, f"**ASCII**\n━━━━━━━━━━━━━━━\n{ascii_codes}")

        @register_cmd("nato", premium=True)
        async def cmd_nato(event, arg):
            nato = {'a':'Alpha','b':'Bravo','c':'Charlie','d':'Delta','e':'Echo','f':'Foxtrot','g':'Golf','h':'Hotel','i':'India','j':'Juliett','k':'Kilo','l':'Lima','m':'Mike','n':'November','o':'Oscar','p':'Papa','q':'Quebec','r':'Romeo','s':'Sierra','t':'Tango','u':'Uniform','v':'Victor','w':'Whiskey','x':'Xray','y':'Yankee','z':'Zulu'}
            result = ' '.join(nato.get(c.lower(), c) for c in arg)
            await safe_edit(event, f"**NATO**\n━━━━━━━━━━━━━━━\n{result}")

        @register_cmd("palindrome", premium=True)
        async def cmd_palindrome(event, arg):
            cleaned = ''.join(c.lower() for c in arg if c.isalnum())
            is_pal = cleaned == cleaned[::-1]
            await safe_edit(event, f"**PALINDROME**\n━━━━━━━━━━━━━━━\n'{arg}' is {'a palindrome' if is_pal else 'not a palindrome'}.")

        @register_cmd("vowels", premium=True)
        async def cmd_vowels(event, arg):
            count = sum(1 for c in arg.lower() if c in 'aeiou')
            await safe_edit(event, f"**VOWELS**\n━━━━━━━━━━━━━━━\nVowel count: {count}")

        @register_cmd("wordfreq", premium=True)
        async def cmd_wordfreq(event, arg):
            words = arg.split()
            freq = {}
            for w in words:
                freq[w] = freq.get(w, 0) + 1
            out = '\n'.join(f"{w}: {freq[w]}" for w in freq)
            await safe_edit(event, f"**WORD FREQUENCY**\n━━━━━━━━━━━━━━━\n{out}")

        @register_cmd("charcount", premium=True)
        async def cmd_charcount(event, arg):
            await safe_edit(event, f"**CHAR COUNT**\n━━━━━━━━━━━━━━━\n{len(arg)}")

        @register_cmd("lettercount", premium=True)
        async def cmd_lettercount(event, arg):
            letters = sum(c.isalpha() for c in arg)
            await safe_edit(event, f"**LETTER COUNT**\n━━━━━━━━━━━━━━━\n{letters}")

        @register_cmd("charinfo", premium=True)
        async def cmd_charinfo(event, arg):
            if not arg:
                return
            c = arg[0]
            info = f"Char: '{c}'\nUnicode: U+{ord(c):04X}\nIs digit: {c.isdigit()}\nIs alpha: {c.isalpha()}\nIs space: {c.isspace()}"
            await safe_edit(event, f"**CHAR INFO**\n━━━━━━━━━━━━━━━\n{info}")

        # ─── MATH COMMANDS ─────────────────────────────────────────────────────
        @register_cmd("bmi", premium=True)
        async def cmd_bmi(event, arg):
            parts = arg.split()
            if len(parts) != 2:
                return
            try:
                weight = float(parts[0])
                height = float(parts[1])
                bmi = weight / (height ** 2)
                await safe_edit(event, f"**BMI**\n━━━━━━━━━━━━━━━\nWeight: {weight} kg\nHeight: {height} m\nBMI: {bmi:.2f}")
            except:
                await safe_edit(event, "❌ Invalid input. Use .bmi <weight_kg> <height_m>")

        @register_cmd("age", premium=True)
        async def cmd_age(event, arg):
            try:
                birth = datetime.strptime(arg.strip(), "%Y-%m-%d")
                today = datetime.now()
                age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
                await safe_edit(event, f"**AGE**\n━━━━━━━━━━━━━━━\nAge: {age} years")
            except:
                await safe_edit(event, "❌ Invalid date. Use YYYY-MM-DD")

        @register_cmd("prime", premium=True)
        async def cmd_prime(event, arg):
            try:
                n = int(arg)
                if n < 2:
                    is_prime = False
                else:
                    is_prime = all(n % i != 0 for i in range(2, int(math.sqrt(n))+1))
                await safe_edit(event, f"**PRIME**\n━━━━━━━━━━━━━━━\n{n} is {'prime' if is_prime else 'not prime'}.")
            except:
                await safe_edit(event, "❌ Invalid number.")

        @register_cmd("factorial", premium=True)
        async def cmd_factorial(event, arg):
            try:
                n = int(arg)
                res = math.factorial(n)
                await safe_edit(event, f"**FACTORIAL**\n━━━━━━━━━━━━━━━\n{n}! = {res}")
            except:
                await safe_edit(event, "❌ Invalid number.")

        @register_cmd("fibonacci", premium=True)
        async def cmd_fibonacci(event, arg):
            try:
                n = int(arg)
                if n <= 0:
                    return
                fib = [0,1]
                for i in range(2,n):
                    fib.append(fib[i-1]+fib[i-2])
                await safe_edit(event, f"**FIBONACCI**\n━━━━━━━━━━━━━━━\n{', '.join(map(str, fib[:n]))}")
            except:
                await safe_edit(event, "❌ Invalid number.")

        @register_cmd("square", premium=True)
        async def cmd_square(event, arg):
            try:
                n = int(arg)
                await safe_edit(event, f"**SQUARE**\n━━━━━━━━━━━━━━━\n{n}^2 = {n*n}")
            except:
                await safe_edit(event, "❌ Invalid number.")

        @register_cmd("roman", premium=True)
        async def cmd_roman(event, arg):
            try:
                n = int(arg)
                if n < 1 or n > 3999:
                    await safe_edit(event, "Number must be between 1 and 3999")
                    return
                roman_map = [(1000,'M'),(900,'CM'),(500,'D'),(400,'CD'),(100,'C'),(90,'XC'),(50,'L'),(40,'XL'),(10,'X'),(9,'IX'),(5,'V'),(4,'IV'),(1,'I')]
                res = ''
                for val, sym in roman_map:
                    while n >= val:
                        res += sym
                        n -= val
                await safe_edit(event, f"**ROMAN**\n━━━━━━━━━━━━━━━\n{res}")
            except:
                await safe_edit(event, "❌ Invalid number.")

        @register_cmd("table", premium=True)
        async def cmd_table(event, arg):
            try:
                n = int(arg)
                lines = [f"{n} x {i} = {n*i}" for i in range(1,11)]
                await safe_edit(event, f"**TABLE**\n━━━━━━━━━━━━━━━\n" + '\n'.join(lines))
            except:
                await safe_edit(event, "❌ Invalid number.")

        @register_cmd("percentage", premium=True)
        async def cmd_percentage(event, arg):
            parts = arg.split()
            if len(parts) != 2:
                return
            try:
                val = float(parts[0])
                total = float(parts[1])
                perc = (val/total)*100
                await safe_edit(event, f"**PERCENTAGE**\n━━━━━━━━━━━━━━━\n{val}/{total} = {perc:.2f}%")
            except:
                await safe_edit(event, "❌ Invalid input. Use .percentage <part> <total>")

        @register_cmd("number", premium=True)
        async def cmd_number(event, arg):
            try:
                n = int(arg)
                await safe_edit(event, f"**NUMBER INFO**\n━━━━━━━━━━━━━━━\n{n}\nEven: {n%2==0}\nPositive: {n>0}\nPrime: {'Yes' if all(n%i!=0 for i in range(2,int(math.sqrt(n))+1)) and n>1 else 'No'}\nDigits: {len(str(n))}")
            except:
                await safe_edit(event, "❌ Invalid number.")

        @register_cmd("countdown", premium=True)
        async def cmd_countdown(event, arg):
            try:
                sec = int(arg)
                if sec <= 0:
                    return
                msg = await event.reply(f"⏳ {sec}s")
                for i in range(sec, 0, -1):
                    await asyncio.sleep(1)
                    await msg.edit(f"⏳ {i}s")
                await msg.edit("⏰ **Time's up!**")
            except:
                await safe_edit(event, "❌ Invalid seconds.")

        # ─── ENCRYPTION ──────────────────────────────────────────────────────
        @register_cmd("encrypt", premium=True)
        async def cmd_encrypt(event, arg):
            encrypted = ''.join(chr(ord(c)+3) if c.isprintable() else c for c in arg)
            await safe_edit(event, f"**ENCRYPT**\n━━━━━━━━━━━━━━━\n{encrypted}")

        @register_cmd("decrypt", premium=True)
        async def cmd_decrypt(event, arg):
            decrypted = ''.join(chr(ord(c)-3) if c.isprintable() else c for c in arg)
            await safe_edit(event, f"**DECRYPT**\n━━━━━━━━━━━━━━━\n{decrypted}")

        @register_cmd("sha1", premium=True)
        async def cmd_sha1(event, arg):
            h = hashlib.sha1(arg.encode()).hexdigest()
            await safe_edit(event, f"**SHA1**\n━━━━━━━━━━━━━━━\n{h}")

        @register_cmd("sha512", premium=True)
        async def cmd_sha512(event, arg):
            h = hashlib.sha512(arg.encode()).hexdigest()
            await safe_edit(event, f"**SHA512**\n━━━━━━━━━━━━━━━\n{h}")

        @register_cmd("typetest", premium=True)
        async def cmd_typetest(event, arg):
            await safe_edit(event, f"**TYPING TEST**\n━━━━━━━━━━━━━━━\nTyping speed: {random.randint(30,60)} WPM\nAccuracy: {random.randint(90,100)}%")

        @register_cmd("coin", premium=True)
        async def cmd_coin(event, _):
            await safe_edit(event, f"**COIN FLIP**\n━━━━━━━━━━━━━━━\n{random.choice(['Heads', 'Tails'])}")

        @register_cmd("lucky", premium=True)
        async def cmd_lucky(event, _):
            await safe_edit(event, f"**LUCKY NUMBER**\n━━━━━━━━━━━━━━━\n{random.randint(1,100)}")

        @register_cmd("roll", premium=True)
        async def cmd_roll(event, arg):
            try:
                max_val = int(arg) if arg else 6
                if max_val < 1:
                    max_val = 6
                await safe_edit(event, f"**DICE ROLL**\n━━━━━━━━━━━━━━━\n{random.randint(1, max_val)}")
            except:
                await safe_edit(event, "❌ Invalid max.")

        @register_cmd("timer", premium=True)
        async def cmd_timer(event, arg):
            try:
                sec = int(arg)
                if sec <= 0:
                    return
                msg = await event.reply(f"⏳ Timer set for {sec}s")
                await asyncio.sleep(sec)
                await msg.edit("⏰ **Timer is up!**")
            except:
                await safe_edit(event, "❌ Invalid seconds.")

        @register_cmd("repeat", premium=True)
        async def cmd_repeat(event, arg):
            parts = arg.split(maxsplit=1)
            if len(parts) != 2 or not parts[0].isdigit():
                return
            count = int(parts[0])
            if count < 1 or count > 20:
                return
            text = parts[1]
            result = (text + "\n") * count
            await safe_edit(event, f"**REPEAT**\n━━━━━━━━━━━━━━━\n{result.strip()}")

        # ─── TIC TAC TOE ──────────────────────────────────────────────────────
        ttt_games = {}

        @register_cmd("ttt")
        async def cmd_ttt(event, _):
            chat = event.chat_id
            if chat in ttt_games:
                return await safe_edit(event, "⚠️ A game is already in progress! Use `.ttt_move` to play.")
            board = [" "] * 9
            ttt_games[chat] = {"board": board, "turn": "X", "player_x": None, "player_o": None}
            ttt_games[chat]["player_x"] = event.sender_id
            board_display = "```\n" + "\n".join([" | ".join(board[i:i+3]) for i in range(0, 9, 3)]) + "\n```"
            await safe_edit(event, f"🎮 **TIC TAC TOE**\n{board_display}\n\nPlayer X (you) starts. Use `.ttt_move 1-9`")

        @register_cmd("ttt_move")
        async def cmd_ttt_move(event, arg):
            chat = event.chat_id
            if chat not in ttt_games:
                return await safe_edit(event, "❌ No game active. Start with `.ttt`")
            game = ttt_games[chat]
            sender = event.sender_id
            if game["turn"] == "X":
                if game["player_x"] is None:
                    game["player_x"] = sender
                if sender != game["player_x"]:
                    return await safe_edit(event, "❌ It's not your turn (X).")
            else:
                if game["player_o"] is None:
                    game["player_o"] = sender
                if sender != game["player_o"]:
                    return await safe_edit(event, "❌ It's not your turn (O).")
            if not arg or not arg.isdigit() or int(arg) < 1 or int(arg) > 9:
                return await safe_edit(event, "❌ Use 1-9 for position")
            pos = int(arg) - 1
            if game["board"][pos] != " ":
                return await safe_edit(event, "❌ Position already taken!")
            game["board"][pos] = game["turn"]
            board = game["board"]
            win = False
            for i in range(3):
                if board[i*3] == board[i*3+1] == board[i*3+2] != " ":
                    win = True
            for i in range(3):
                if board[i] == board[i+3] == board[i+6] != " ":
                    win = True
            if board[0] == board[4] == board[8] != " " or board[2] == board[4] == board[6] != " ":
                win = True
            if win:
                board_display = "```\n" + "\n".join([" | ".join(board[i:i+3]) for i in range(0, 9, 3)]) + "\n```"
                await safe_edit(event, f"🎮 **TIC TAC TOE**\n{board_display}\n\n🏆 **{game['turn']} Wins!** 🎉")
                del ttt_games[chat]
                return
            if " " not in board:
                board_display = "```\n" + "\n".join([" | ".join(board[i:i+3]) for i in range(0, 9, 3)]) + "\n```"
                await safe_edit(event, f"🎮 **TIC TAC TOE**\n{board_display}\n\n🤝 **Draw!**")
                del ttt_games[chat]
                return
            game["turn"] = "O" if game["turn"] == "X" else "X"
            board_display = "```\n" + "\n".join([" | ".join(board[i:i+3]) for i in range(0, 9, 3)]) + "\n```"
            await safe_edit(event, f"🎮 **TIC TAC TOE**\n{board_display}\n\n{game['turn']}'s turn")

        # ─── RPS ───────────────────────────────────────────────────────────────
        @register_cmd("rps")
        async def cmd_rps(event, arg):
            choices = {"r": "🪨 Rock", "p": "📄 Paper", "s": "✂️ Scissors"}
            wins = {"r": "s", "p": "r", "s": "p"}
            if not arg or arg.lower() not in choices:
                return await safe_edit(event, "❌ Use: `.rps r` (rock) / `.rps p` (paper) / `.rps s` (scissors)")
            user = arg.lower()
            bot = random.choice(list(choices.keys()))
            if user == bot:
                result = "🤝 Draw!"
            elif wins[user] == bot:
                result = "🏆 You Win!"
            else:
                result = "🤖 Bot Wins!"
            await safe_edit(event, f"✂️🪨📄 **RPS**\n━━━━━━━━━━━━━━━\n👤 You: {choices[user]}\n🤖 Bot: {choices[bot]}\n\n{result}")

        # ─── RIDDLE & QUIZ ──────────────────────────────────────────────────────
        @register_cmd("riddle")
        async def cmd_riddle(event, _):
            if not riddle_texts:
                await safe_edit(event, "❌ No riddles available.")
                return
            riddle = random.choice(riddle_texts)
            await safe_edit(event, f"🧩 **RIDDLE**\n━━━━━━━━━━━━━━━\n{riddle['q']}\n\n⏳ You have 60 seconds to think!\n💡 Answer will be revealed after timer...")
            await asyncio.sleep(60)
            await safe_edit(event, f"🧩 **RIDDLE ANSWER**\n━━━━━━━━━━━━━━━\n{riddle['q']}\n\n✅ **Answer:** `{riddle['a']}`")

        @register_cmd("quiz")
        async def cmd_quiz(event, _):
            if not quiz_texts:
                await safe_edit(event, "❌ No quiz questions available.")
                return
            quiz = random.choice(quiz_texts)
            await safe_edit(event, f"📚 **QUIZ**\n━━━━━━━━━━━━━━━\n{quiz['q']}\n\n⏳ You have 60 seconds to answer!\n💡 Answer will be revealed after timer...")
            await asyncio.sleep(60)
            await safe_edit(event, f"📚 **QUIZ ANSWER**\n━━━━━━━━━━━━━━━\n{quiz['q']}\n\n✅ **Answer:** `{quiz['a']}`")

        # ─── ORIGINAL REPLY & RAID COMMANDS ──────────────────────────────────
        @register_cmd("reply", needs_reply=True)
        async def cmd_reply(event, arg):
            targets = await get_targets(event, arg)
            if not targets: return
            added, already = [], []
            for uid in targets:
                if uid in user_bot.reply_users:
                    already.append(str(uid))
                else:
                    user_bot.reply_users.add(uid); added.append(str(uid))
            msg = ""
            if added: msg += f"🔥 Reply raid on: {', '.join(added)}\n"
            if already: msg += f"⚠️ Already active: {', '.join(already)}"
            if not msg: msg = "❌ No changes"
            await safe_edit(event, msg)

        @register_cmd("sreply")
        async def cmd_sreply(event, arg):
            targets = await get_targets(event, arg)
            if targets:
                removed, not_active = [], []
                for uid in targets:
                    if uid in user_bot.reply_users:
                        user_bot.reply_users.discard(uid); removed.append(str(uid))
                    else:
                        not_active.append(str(uid))
                msg = ""
                if removed: msg += f"🛑 Removed: {', '.join(removed)}\n"
                if not_active: msg += f"⚠️ Not active: {', '.join(not_active)}"
                if not msg: msg = "❌ No changes"
                await safe_edit(event, msg)
            else:
                user_bot.reply_users.clear()
                await safe_edit(event, "🛑 Reply raid stopped for all")

        @register_cmd("rr", needs_reply=True)
        async def cmd_rr(event, arg):
            targets = await get_targets(event, arg)
            if not targets: return
            added, already = [], []
            for uid in targets:
                if uid in user_bot.rr_users:
                    already.append(str(uid))
                else:
                    user_bot.rr_users.add(uid); added.append(str(uid))
            msg = ""
            if added: msg += f"🔥 RR on: {', '.join(added)}\n"
            if already: msg += f"⚠️ Already: {', '.join(already)}"
            if not msg: msg = "❌ No changes"
            await safe_edit(event, msg)

        @register_cmd("srr")
        async def cmd_srr(event, arg):
            targets = await get_targets(event, arg)
            if targets:
                removed, not_active = [], []
                for uid in targets:
                    if uid in user_bot.rr_users:
                        user_bot.rr_users.discard(uid); removed.append(str(uid))
                    else:
                        not_active.append(str(uid))
                msg = ""
                if removed: msg += f"🛑 Removed: {', '.join(removed)}\n"
                if not_active: msg += f"⚠️ Not active: {', '.join(not_active)}"
                if not msg: msg = "❌ No changes"
                await safe_edit(event, msg)
            else:
                user_bot.rr_users.clear()
                await safe_edit(event, "🛑 RR stopped for all")

        @register_cmd("flag", needs_reply=True)
        async def cmd_flag(event, arg):
            targets = await get_targets(event, arg)
            if not targets: return
            added, already = [], []
            for uid in targets:
                if uid in user_bot.flag_users:
                    already.append(str(uid))
                else:
                    user_bot.flag_users.add(uid); added.append(str(uid))
            msg = ""
            if added: msg += f"🌊 Flag on: {', '.join(added)}\n"
            if already: msg += f"⚠️ Already: {', '.join(already)}"
            if not msg: msg = "❌ No changes"
            await safe_edit(event, msg)

        @register_cmd("sflag")
        async def cmd_sflag(event, arg):
            targets = await get_targets(event, arg)
            if targets:
                removed, not_active = [], []
                for uid in targets:
                    if uid in user_bot.flag_users:
                        user_bot.flag_users.discard(uid); removed.append(str(uid))
                    else:
                        not_active.append(str(uid))
                msg = ""
                if removed: msg += f"🛑 Removed: {', '.join(removed)}\n"
                if not_active: msg += f"⚠️ Not active: {', '.join(not_active)}"
                if not msg: msg = "❌ No changes"
                await safe_edit(event, msg)
            else:
                user_bot.flag_users.clear()
                await safe_edit(event, "🛑 Flag stopped for all")

        @register_cmd("hrr", needs_reply=True)
        async def cmd_hrr(event, arg):
            targets = await get_targets(event, arg)
            if not targets: return
            added, already = [], []
            for uid in targets:
                if uid in user_bot.hrr_users:
                    already.append(str(uid))
                else:
                    user_bot.hrr_users.add(uid); added.append(str(uid))
            msg = ""
            if added: msg += f"💜 Heart on: {', '.join(added)}\n"
            if already: msg += f"⚠️ Already: {', '.join(already)}"
            if not msg: msg = "❌ No changes"
            await safe_edit(event, msg)

        @register_cmd("shrr")
        async def cmd_shrr(event, arg):
            targets = await get_targets(event, arg)
            if targets:
                removed, not_active = [], []
                for uid in targets:
                    if uid in user_bot.hrr_users:
                        user_bot.hrr_users.discard(uid); removed.append(str(uid))
                    else:
                        not_active.append(str(uid))
                msg = ""
                if removed: msg += f"🛑 Removed: {', '.join(removed)}\n"
                if not_active: msg += f"⚠️ Not active: {', '.join(not_active)}"
                if not msg: msg = "❌ No changes"
                await safe_edit(event, msg)
            else:
                user_bot.hrr_users.clear()
                await safe_edit(event, "🛑 Heart stopped for all")

        @register_cmd("replygod", needs_reply=True)
        async def cmd_replygod(event, arg):
            targets = await get_targets(event, arg)
            if not targets: return
            added, already = [], []
            for uid in targets:
                if uid in user_bot.replygod_users:
                    already.append(str(uid))
                else:
                    user_bot.replygod_users.add(uid); added.append(str(uid))
            msg = ""
            if added: msg += f"💥 God on: {', '.join(added)}\n"
            if already: msg += f"⚠️ Already: {', '.join(already)}"
            if not msg: msg = "❌ No changes"
            await safe_edit(event, msg)

        @register_cmd("sgod")
        async def cmd_sgod(event, arg):
            targets = await get_targets(event, arg)
            if targets:
                removed, not_active = [], []
                for uid in targets:
                    if uid in user_bot.replygod_users:
                        user_bot.replygod_users.discard(uid); removed.append(str(uid))
                    else:
                        not_active.append(str(uid))
                msg = ""
                if removed: msg += f"🛑 Removed: {', '.join(removed)}\n"
                if not_active: msg += f"⚠️ Not active: {', '.join(not_active)}"
                if not msg: msg = "❌ No changes"
                await safe_edit(event, msg)
            else:
                user_bot.replygod_users.clear()
                await safe_edit(event, "🛑 God stopped for all")

        @register_cmd("customraid", needs_reply=True)
        async def cmd_customraid(event, arg):
            if not arg or len(arg.split()) < 2:
                return
            text, count = arg.rsplit(" ", 1)
            try:
                count = int(count)
                if count < 1: count = 1
                if count > 100: count = 100
            except:
                return
            targets = await get_targets(event, "")
            if not targets: return
            added, overridden = [], []
            for uid in targets:
                if uid in user_bot.custom_raid_users:
                    overridden.append(str(uid))
                user_bot.custom_raid_users[uid] = {"text": text, "count": count}
                added.append(str(uid))
            msg = f"☄️ **Custom Raid started** on: {', '.join(added)} × {count} times"
            if overridden:
                msg += f"\n⚠️ Overridden: {', '.join(overridden)}"
            await safe_edit(event, msg)

        @register_cmd("stopcustomraid")
        async def cmd_stopcustomraid(event, arg):
            targets = await get_targets(event, arg)
            if targets:
                removed, not_active = [], []
                for uid in targets:
                    if uid in user_bot.custom_raid_users:
                        del user_bot.custom_raid_users[uid]
                        removed.append(str(uid))
                    else:
                        not_active.append(str(uid))
                msg = ""
                if removed: msg += f"🛑 Removed: {', '.join(removed)}\n"
                if not_active: msg += f"⚠️ Not active: {', '.join(not_active)}"
                if not msg: msg = "❌ No changes"
                await safe_edit(event, msg)
            else:
                user_bot.custom_raid_users.clear()
                await safe_edit(event, "🛑 All Custom Raids stopped")

        # ─── PWR RAID (SEQUENTIAL) ──────────────────────────────────────────
        @register_cmd("pwr", needs_reply=True)
        async def cmd_pwr(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            count = None
            if arg:
                parts = arg.strip().split()
                if parts and parts[-1].isdigit():
                    count = int(parts[-1])
                    if count < 1: count = 1
                    if count > 100: count = 100
            if not pwr_texts:
                await safe_edit(event, "⚠️ PWR list is empty. Add texts to `pwr_texts` in code.")
                return
            added = []
            for uid in targets:
                user_bot.pwr_raid[uid] = count
                user_bot.pwr_users.add(uid)
                user_bot.pwr_index[uid] = 0
                display = "∞" if count is None else f"{count} times"
                added.append(f"{uid} ({display})")
            await safe_edit(event, f"🔥 PWR raid (sequential) started for {', '.join(added)}")

        @register_cmd("spwr")
        async def cmd_spwr(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                user_bot.pwr_raid.clear()
                user_bot.pwr_users.clear()
                user_bot.pwr_index.clear()
                return await safe_edit(event, "🛑 PWR raid stopped for all")
            removed = []
            for uid in targets:
                if uid in user_bot.pwr_raid:
                    del user_bot.pwr_raid[uid]
                    user_bot.pwr_users.discard(uid)
                    user_bot.pwr_index.pop(uid, None)
                    removed.append(str(uid))
            if removed:
                await safe_edit(event, f"🛑 Removed: {', '.join(removed)}")
            else:
                await safe_edit(event, "⚠️ No active raid for these users")

        # ─── OWS SPAM ────────────────────────────────────────────────────────
        @register_cmd("ows")
        async def cmd_ows(event, arg):
            if not ows_texts:
                await safe_edit(event, "⚠️ OWS list is empty. Add texts to `ows_texts` in code.")
                return
            chat = event.chat_id
            count = None
            if arg and arg.strip().isdigit():
                count = int(arg.strip())
                if count < 1: count = 1
                if count > 1000: count = 1000
            reply_to = None
            target_user = None
            if event.is_reply:
                reply = await event.get_reply_message()
                if reply:
                    reply_to = reply.id
                    target_user = reply.sender_id
                    if target_user and await is_protected(target_user, "ows"):
                        await safe_edit(event, "🚫 This user is protected from OWS.")
                        return
            if chat in user_bot.spray_tasks and not user_bot.spray_tasks[chat].done():
                return
            await safe_edit(event, f"💬 OWS (sequential) started{' with reply' if reply_to else ''}{' (' + str(count) + ' msgs)' if count else ' (infinite)'}...")
            async def loop():
                sent = 0
                idx = 0
                try:
                    while chat in user_bot.spray_tasks:
                        if count is not None and sent >= count:
                            break
                        if target_user and sent % 10 == 0 and await is_protected(target_user, "ows"):
                            await safe_send(chat, "🛑 Target is now protected. Stopping OWS.")
                            break
                        txt = ows_texts[idx % len(ows_texts)]
                        idx += 1
                        sent += 1
                        await safe_send(chat, txt, reply_to=reply_to)
                        if sent % 30 == 0:
                            await asyncio.sleep(3)
                        await asyncio.sleep(user_bot.SPRAY_DELAY)
                except asyncio.CancelledError:
                    pass
                finally:
                    user_bot.spray_tasks.pop(chat, None)
                    if sent > 0:
                        await safe_send(chat, f"💬 OWS done: {sent} messages sent.")
            user_bot.spray_tasks[chat] = asyncio.create_task(loop())
            await safe_edit(event, f"💬 OWS started{' with reply' if reply_to else ''}{' (' + str(count) + ' msgs)' if count else ' (infinite)'}")

        @register_cmd("sows")
        async def cmd_sows(event, _):
            chat = event.chat_id
            if chat in user_bot.spray_tasks:
                try:
                    user_bot.spray_tasks[chat].cancel()
                except:
                    pass
                user_bot.spray_tasks.pop(chat, None)
                await safe_edit(event, "🛑 OWS stopped.")
            else:
                await safe_edit(event, "⚠️ No active OWS spray in this chat.")

        # ─── STOP ALL SPRAY ──────────────────────────────────────────────────
        @register_cmd("stopallspray")
        async def cmd_stopallspray(event, _):
            if not is_admin(event.sender_id):
                return
            count = 0
            for chat in list(user_bot.spray_tasks.keys()):
                try:
                    user_bot.spray_tasks[chat].cancel()
                    count += 1
                except:
                    pass
            user_bot.spray_tasks.clear()
            user_bot.pwr_raid.clear()
            user_bot.pwr_users.clear()
            user_bot.pwr_index.clear()
            user_bot.ows_spam.clear()
            user_bot.ows_users.clear()
            user_bot.ows_index.clear()
            await safe_edit(event, f"🛑 Stopped all sprays/raids in {count} chats.")

        # ─── ECHO ──────────────────────────────────────────────────────────────
        @register_cmd("echo")
        async def cmd_echo(event, arg):
            if not arg:
                return await safe_edit(event, "❌ Usage: `.echo <text>` or `.echo <count> <text>`")
            parts = arg.strip().split(maxsplit=1)
            if len(parts) >= 2 and parts[0].isdigit():
                count = int(parts[0])
                if count < 1: count = 1
                if count > 20: count = 20
                text = parts[1]
                await event.delete()
                for i in range(count):
                    await user_bot.send_message(event.chat_id, text)
                    await asyncio.sleep(0.5)
            else:
                await event.delete()
                await user_bot.send_message(event.chat_id, arg)

        # ─── SPRAY ──────────────────────────────────────────────────────────────
        @register_cmd("spray")
        async def cmd_spray(event, arg):
            if not arg: return
            count = None
            text = arg
            parts = arg.split(maxsplit=1)
            if parts and parts[0].isdigit():
                count = int(parts[0])
                if count < 1: count = 1
                if count > 1000: count = 1000
                text = parts[1] if len(parts) > 1 else ""
                if not text: return
            chat = event.chat_id
            target_user = None
            if event.is_reply:
                reply = await event.get_reply_message()
                if reply:
                    target_user = reply.sender_id
                    if target_user and await is_protected(target_user, "spray"):
                        await safe_edit(event, "🚫 This user is protected from Spray.")
                        return
            if chat in user_bot.spray_tasks and not user_bot.spray_tasks[chat].done():
                return
            await safe_edit(event, f"⚡ Spray starting{' (' + str(count) + ' msgs)' if count else ' (infinite)'}...")
            async def loop():
                sent = 0
                try:
                    while chat in user_bot.spray_tasks:
                        if count is not None and sent >= count:
                            break
                        if target_user and sent % 20 == 0 and await is_protected(target_user, "spray"):
                            await safe_send(chat, "🛑 Target is now protected. Stopping Spray.")
                            break
                        await safe_send(chat, text)
                        sent += 1
                        if sent % 30 == 0:
                            await asyncio.sleep(3)
                        await asyncio.sleep(user_bot.SPRAY_DELAY)
                except asyncio.CancelledError:
                    pass
                finally:
                    user_bot.spray_tasks.pop(chat, None)
                    if count is not None and sent > 0:
                        await safe_send(chat, f"✅ Done! Sent {sent} messages.")
            user_bot.spray_tasks[chat] = asyncio.create_task(loop())
            await safe_edit(event, f"💣 Spray started: {text[:40]}" + (f" ({count} msgs)" if count else ""))

        @register_cmd("dspray")
        async def cmd_dspray(event, _):
            chat = event.chat_id
            if chat not in user_bot.spray_tasks:
                return
            try:
                user_bot.spray_tasks[chat].cancel()
            except:
                pass
            user_bot.spray_tasks.pop(chat, None)
            await safe_edit(event, "🛑 Spray stopped")

        @register_cmd("listtexts")
        async def cmd_listtexts(event, _):
            if not user_bot.spam_texts:
                return await safe_edit(event, "📭 No texts saved.\n\nUse `.addtext <text>` (owner only) to add one.")
            msg = "📋 Saved Spam Texts (Common):\n\n"
            for i, t in enumerate(user_bot.spam_texts, 1):
                preview = t[:50].replace("`", "'")
                msg += f"**{i}.** `{preview}`{'…' if len(t) > 50 else ''}\n"
            msg += f"\n💡 `.tspray <number>` to spam that specific text."
            await safe_edit(event, msg)

        @register_cmd("addtext")
        async def cmd_addtext(event, arg):
            if event.sender_id not in OWNER_IDS:
                return
            if not arg:
                return
            user_bot.spam_texts.append(arg.strip())
            save_common_spam()
            await safe_edit(event, f"✅ Text saved at slot {len(user_bot.spam_texts)}")

        @register_cmd("edittext")
        async def cmd_edittext(event, arg):
            if event.sender_id not in OWNER_IDS:
                return
            parts = arg.split(None, 1) if arg else []
            if len(parts) < 2 or not parts[0].isdigit():
                return
            idx = int(parts[0]) - 1
            if idx < 0 or idx >= len(user_bot.spam_texts):
                return
            user_bot.spam_texts[idx] = parts[1]
            save_common_spam()
            await safe_edit(event, f"✅ Slot {idx+1} updated")

        @register_cmd("deltext")
        async def cmd_deltext(event, arg):
            if event.sender_id not in OWNER_IDS:
                return
            if not arg or not arg.isdigit():
                return
            idx = int(arg) - 1
            if idx < 0 or idx >= len(user_bot.spam_texts):
                return
            user_bot.spam_texts.pop(idx)
            save_common_spam()
            await safe_edit(event, f"🗑️ Slot {idx+1} deleted")

        @register_cmd("cleartext")
        async def cmd_cleartext(event, arg):
            if event.sender_id not in OWNER_IDS:
                return
            if arg.strip().lower() != "confirm":
                return
            user_bot.spam_texts.clear()
            save_common_spam()
            await safe_edit(event, "🗑️ All texts cleared")

        @register_cmd("tspray")
        async def cmd_tspray(event, arg):
            if not arg or not arg.isdigit():
                return await safe_edit(event, "❌ Usage: .tspray <slot_number>")
            idx = int(arg) - 1
            if idx < 0 or idx >= len(user_bot.spam_texts):
                return await safe_edit(event, f"❌ Invalid slot. Total: {len(user_bot.spam_texts)}")
            text = user_bot.spam_texts[idx]
            chat = event.chat_id
            if chat in user_bot.spray_tasks and not user_bot.spray_tasks[chat].done():
                return await safe_edit(event, "⚠️ Already spraying")
            await safe_edit(event, f"⚡ TSpray starting slot {idx+1}...")
            async def loop():
                sent = 0
                try:
                    while chat in user_bot.spray_tasks:
                        await safe_send(chat, text)
                        sent += 1
                        if sent % 30 == 0:
                            await asyncio.sleep(3)
                        await asyncio.sleep(user_bot.SPRAY_DELAY)
                except asyncio.CancelledError:
                    pass
                finally:
                    user_bot.spray_tasks.pop(chat, None)
            user_bot.spray_tasks[chat] = asyncio.create_task(loop())
            await safe_edit(event, f"💣 TSpray started for slot {idx+1}")

        @register_cmd("rspray")
        async def cmd_rspray(event, _):
            if not user_bot.spam_texts:
                return await safe_edit(event, "📭 No texts saved.")
            chat = event.chat_id
            if chat in user_bot.spray_tasks and not user_bot.spray_tasks[chat].done():
                return await safe_edit(event, "⚠️ Already spraying")
            await safe_edit(event, "🎲 RSpray starting...")
            async def loop():
                sent = 0
                try:
                    while chat in user_bot.spray_tasks:
                        txt = random.choice(user_bot.spam_texts)
                        await safe_send(chat, txt)
                        sent += 1
                        if sent % 30 == 0:
                            await asyncio.sleep(3)
                        await asyncio.sleep(user_bot.SPRAY_DELAY)
                except asyncio.CancelledError:
                    pass
                finally:
                    user_bot.spray_tasks.pop(chat, None)
            user_bot.spray_tasks[chat] = asyncio.create_task(loop())
            await safe_edit(event, f"🎲 RSpray started (pool: {len(user_bot.spam_texts)})")

        @register_cmd("multispray")
        async def cmd_multispray(event, arg):
            if not user_bot.spam_texts:
                return await safe_edit(event, "📭 No texts saved.")
            count = None
            if arg and arg.strip().isdigit():
                count = int(arg.strip())
                if count < 1: count = 1
                if count > 1000: count = 1000
            chat = event.chat_id
            target_msg_id = None
            target_user = None
            if event.is_reply:
                reply = await event.get_reply_message()
                if reply:
                    target_msg_id = reply.id
                    target_user = reply.sender_id
                    if target_user and await is_protected(target_user, "multispray"):
                        await safe_edit(event, "🚫 This user is protected from MultiSpray.")
                        return
            if chat in user_bot.spray_tasks and not user_bot.spray_tasks[chat].done():
                return await safe_edit(event, "⚠️ Already spraying")
            await safe_edit(event, f"🔄 MultiSpray starting{' with reply' if target_msg_id else ''}...{' (' + str(count) + ' msgs)' if count else ' (infinite)'}")
            async def loop():
                i = 0
                sent = 0
                try:
                    while chat in user_bot.spray_tasks:
                        if count is not None and sent >= count:
                            break
                        if target_user and sent % 20 == 0 and await is_protected(target_user, "multispray"):
                            await safe_send(chat, "🛑 Target is now protected. Stopping MultiSpray.")
                            break
                        txt = user_bot.spam_texts[i % len(user_bot.spam_texts)]
                        i += 1
                        sent += 1
                        if target_msg_id:
                            await safe_send(chat, txt, reply_to=target_msg_id)
                        else:
                            await safe_send(chat, txt)
                        if sent % 30 == 0:
                            await asyncio.sleep(3)
                        await asyncio.sleep(user_bot.SPRAY_DELAY)
                except asyncio.CancelledError:
                    pass
                finally:
                    user_bot.spray_tasks.pop(chat, None)
                    if sent > 0:
                        await safe_send(chat, f"✅ MultiSpray done: {sent} messages sent.")
            user_bot.spray_tasks[chat] = asyncio.create_task(loop())
            await safe_edit(event, f"🔄 MultiSpray started (rotating {len(user_bot.spam_texts)})" + (" with reply" if target_msg_id else ""))

        @register_cmd("countspray")
        async def cmd_countspray(event, arg):
            parts = arg.split(None, 1) if arg else []
            if len(parts) < 2 or not parts[0].isdigit():
                return await safe_edit(event, "❌ Usage: .countspray <count> <text>")
            count = int(parts[0])
            if count < 1 or count > 500:
                return await safe_edit(event, "❌ Count must be 1-500")
            text = parts[1]
            chat = event.chat_id
            target_msg_id = None
            target_user = None
            if event.is_reply:
                reply = await event.get_reply_message()
                if reply:
                    target_msg_id = reply.id
                    target_user = reply.sender_id
                    if target_user and await is_protected(target_user, "countspray"):
                        await safe_edit(event, "🚫 This user is protected from CountSpray.")
                        return
            if chat in user_bot.spray_tasks and not user_bot.spray_tasks[chat].done():
                return await safe_edit(event, "⚠️ Already spraying")
            await safe_edit(event, f"🎯 CountSpray starting ({count} messages)...")
            async def loop():
                sent = 0
                try:
                    while sent < count and chat in user_bot.spray_tasks:
                        if target_user and sent % 20 == 0 and await is_protected(target_user, "countspray"):
                            await safe_send(chat, "🛑 Target is now protected. Stopping CountSpray.")
                            break
                        await safe_send(chat, text, reply_to=target_msg_id if target_msg_id else None)
                        sent += 1
                        if sent % 30 == 0:
                            await asyncio.sleep(3)
                        await asyncio.sleep(user_bot.SPRAY_DELAY)
                except asyncio.CancelledError:
                    pass
                finally:
                    user_bot.spray_tasks.pop(chat, None)
                    if sent > 0:
                        await safe_send(chat, f"✅ Done! Sent {sent} messages.")
            user_bot.spray_tasks[chat] = asyncio.create_task(loop())
            await safe_edit(event, f"🎯 CountSpray started ({count} messages)")

        @register_cmd("spraydelay")
        async def cmd_spraydelay(event, arg):
            if event.sender_id not in OWNER_IDS:
                return
            if not arg:
                await safe_edit(event, f"Current delay: {user_bot.SPRAY_DELAY}s")
                return
            try:
                val = float(arg)
                if val < 0.1: val = 0.1
                if val > 60: val = 60
                old = user_bot.SPRAY_DELAY
                user_bot.SPRAY_DELAY = val
                await safe_edit(event, f"⚡ Delay updated: {old}s → {val}s")
            except:
                await safe_edit(event, "❌ Invalid number")

        @register_cmd("mute", needs_reply=True)
        async def cmd_mute(event, arg):
            targets = await get_targets(event, arg)
            if not targets: return
            added, already, protected = [], [], []
            for uid in targets:
                if await is_protected(uid, "mute"):
                    protected.append(str(uid))
                    continue
                if uid in user_bot.muted_users:
                    already.append(str(uid))
                else:
                    user_bot.muted_users.add(uid); added.append(str(uid))
            msg = ""
            if added: msg += f"🔇 Muted: {', '.join(added)}\n"
            if already: msg += f"⚠️ Already muted: {', '.join(already)}\n"
            if protected: msg += f"🛡️ Protected (skip): {', '.join(protected)}"
            if not msg: msg = "❌ No changes"
            await safe_edit(event, msg)

        @register_cmd("unmute", needs_reply=True)
        async def cmd_unmute(event, arg):
            targets = await get_targets(event, arg)
            if not targets: return
            removed, not_muted = [], []
            for uid in targets:
                if uid in user_bot.muted_users:
                    user_bot.muted_users.remove(uid); removed.append(str(uid))
                else:
                    not_muted.append(str(uid))
            msg = ""
            if removed: msg += f"🗣️ Unmuted: {', '.join(removed)}\n"
            if not_muted: msg += f"⚠️ Not muted: {', '.join(not_muted)}"
            if not msg: msg = "❌ No changes"
            await safe_edit(event, msg)

        @register_cmd("gmute", needs_reply=True)
        async def cmd_gmute(event, arg):
            targets = await get_targets(event, arg)
            if not targets: return
            added, already, protected = [], [], []
            for uid in targets:
                if await is_protected(uid, "gmute"):
                    protected.append(str(uid))
                    continue
                if uid in user_bot.global_muted:
                    already.append(str(uid))
                else:
                    user_bot.global_muted.add(uid); added.append(str(uid))
            msg = ""
            if added: msg += f"🔕 Gmuted: {', '.join(added)}\n"
            if already: msg += f"⚠️ Already gmuted: {', '.join(already)}\n"
            if protected: msg += f"🛡️ Protected (skip): {', '.join(protected)}"
            if not msg: msg = "❌ No changes"
            await safe_edit(event, msg)

        @register_cmd("gunmute", needs_reply=True)
        async def cmd_gunmute(event, arg):
            targets = await get_targets(event, arg)
            if not targets: return
            removed, not_muted = [], []
            for uid in targets:
                if uid in user_bot.global_muted:
                    user_bot.global_muted.remove(uid); removed.append(str(uid))
                else:
                    not_muted.append(str(uid))
            msg = ""
            if removed: msg += f"🔊 Gunmuted: {', '.join(removed)}\n"
            if not_muted: msg += f"⚠️ Not gmuted: {', '.join(not_muted)}"
            if not msg: msg = "❌ No changes"
            await safe_edit(event, msg)

        @register_cmd("mutelist")
        async def cmd_mutelist(event, _):
            text = "📋 Mute Panel\n━━━━━━━━━━━━━━━\n\n🔇 Local Muted:\n"
            if user_bot.muted_users:
                for uid in user_bot.muted_users:
                    try:
                        u = await user_bot.get_entity(uid)
                        uname = f"@{u.username}" if u.username else "NoUsername"
                        text += f"• {uid} → {uname}\n"
                    except:
                        text += f"• {uid}\n"
            else:
                text += "• None\n"
            text += "\n🌍 Global Muted:\n"
            if user_bot.global_muted:
                for uid in user_bot.global_muted:
                    try:
                        u = await user_bot.get_entity(uid)
                        uname = f"@{u.username}" if u.username else "NoUsername"
                        text += f"• {uid} → {uname}\n"
                    except:
                        text += f"• {uid}\n"
            else:
                text += "• None\n"
            text += "\n🔒 Locked Groups:\n"
            if user_bot.group_locks:
                for gid in user_bot.group_locks:
                    try:
                        chat = await user_bot.get_entity(gid)
                        title = getattr(chat, "title", None) or "PrivateChat"
                        text += f"• {gid} → {title}\n"
                    except:
                        text += f"• {gid}\n"
            else:
                text += "• None\n"
            await safe_edit(event, text)

        @register_cmd("lock", group_only=True)
        async def cmd_lock(event, _):
            chat = event.chat_id
            try:
                perms = await user_bot.get_permissions(chat, 'me')
                if not perms.is_admin:
                    return
            except:
                pass
            if chat in user_bot.group_locks:
                return
            user_bot.group_locks.add(chat)
            await safe_edit(event, "🔒 Group locked")

        @register_cmd("unlock", group_only=True)
        async def cmd_unlock(event, _):
            chat = event.chat_id
            if chat not in user_bot.group_locks:
                return
            user_bot.group_locks.discard(chat)
            await safe_edit(event, "🔓 Group unlocked")

        @register_cmd("purge")
        async def cmd_purge(event, arg):
            try:
                count = int(arg) if arg else 50
                if count < 1: count = 1
                if count > 200: count = 200
            except:
                count = 50
            msgs = []
            async for m in user_bot.iter_messages(event.chat_id, limit=count+1):
                msgs.append(m.id)
            if not msgs:
                return
            try:
                await user_bot.delete_messages(event.chat_id, msgs)
            except FloodWaitError as fw:
                await asyncio.sleep(fw.seconds)
                await user_bot.delete_messages(event.chat_id, msgs)
            await safe_edit(event, f"🧹 Purged {len(msgs)-1} messages")

        @register_cmd("throw", needs_reply=True, group_only=True)
        async def cmd_throw(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            try:
                perms = await user_bot.get_permissions(event.chat_id, 'me')
                if not perms.is_admin:
                    return
            except:
                return
            kicked, failed, skipped, protected = [], [], [], []
            me2 = await user_bot.get_me()
            for uid in targets:
                if uid == me2.id:
                    skipped.append(str(uid)); continue
                if await is_protected(uid, "throw"):
                    protected.append(str(uid))
                    continue
                try:
                    await user_bot.kick_participant(event.chat_id, uid)
                    kicked.append(str(uid))
                except:
                    failed.append(str(uid))
            msg = ""
            if kicked: msg += f"👞 Kicked: {', '.join(kicked)}\n"
            if failed: msg += f"⚠️ Failed: {', '.join(failed)}\n"
            if protected: msg += f"🛡️ Protected (skip): {', '.join(protected)}\n"
            if skipped: msg += f"👑 Self skip: {', '.join(skipped)}"
            if not msg: msg = "❌ No action"
            await safe_edit(event, msg)

        @register_cmd("addbots", group_only=True)
        async def cmd_addbots(event, arg):
            if not arg or not arg.isdigit():
                return
            limit = int(arg)
            if limit < 1: limit = 1
            if limit > len(user_bot.ADD_BOTS_LIST): limit = len(user_bot.ADD_BOTS_LIST)
            try:
                perms = await user_bot.get_permissions(event.chat_id, 'me')
                if not perms.is_admin:
                    return
            except:
                return
            chat = event.chat_id
            status = await safe_edit(event, f"🔄 Adding {limit} bots...")
            added, already, failed = 0, 0, 0
            for idx, bot_username in enumerate(user_bot.ADD_BOTS_LIST[:limit], 1):
                try:
                    await status.edit(f"🔄 {idx}/{limit} → @{bot_username}")
                    entity = await user_bot.get_entity(bot_username)
                    if isinstance(chat, types.Chat):
                        await user_bot(functions.messages.AddChatUserRequest(chat_id=chat.id, user_id=entity, fwd_limit=0))
                    else:
                        await user_bot(functions.channels.InviteToChannelRequest(channel=chat, users=[entity]))
                    added += 1
                    await asyncio.sleep(2.5)
                except FloodWaitError as fw:
                    await status.edit(f"⏳ Flood {fw.seconds}s")
                    await asyncio.sleep(fw.seconds)
                except RPCError as e:
                    if "already" in str(e).lower() or "participant" in str(e).lower():
                        already += 1
                    else:
                        failed += 1
                except:
                    failed += 1
            await status.edit(f"📊 Result\nAdded: {added}\nAlready: {already}\nFailed: {failed}")

        user_bot.autotag_active = False
        user_bot.autotag_task = None

        @register_cmd("autotag", group_only=True)
        async def cmd_autotag(event, arg):
            chat = event.chat_id
            if user_bot.autotag_active:
                return await safe_edit(event, "⚠️ Auto-tag already running! Use `.stopautotag` to stop.")
            await safe_edit(event, "⏳ Fetching members...")
            try:
                participants = []
                async for p in user_bot.iter_participants(chat, limit=5000):
                    if not p.deleted and not p.bot:
                        participants.append(p)
                if not participants:
                    return await safe_edit(event, "❌ No members found")
                user_bot.autotag_active = True
                msg = arg.strip() if arg else "Hey! 👋"
                async def autotag_loop():
                    try:
                        for idx, user in enumerate(participants):
                            if not user_bot.autotag_active:
                                break
                            try:
                                if user.username:
                                    mention = f"@{user.username}"
                                else:
                                    mention = f"[{user.first_name or 'User'}](tg://user?id={user.id})"
                                await user_bot.send_message(chat, f"{msg} {mention}")
                                await asyncio.sleep(1.5)
                            except FloodWaitError as fw:
                                await asyncio.sleep(fw.seconds)
                            except Exception as e:
                                print(f"Auto-tag error: {e}")
                            if idx % 50 == 0:
                                await safe_edit(event, f"⏳ Tagged {idx+1}/{len(participants)} members...")
                    except asyncio.CancelledError:
                        pass
                    finally:
                        user_bot.autotag_active = False
                        user_bot.autotag_task = None
                        await safe_edit(event, f"✅ Auto-tag completed! Tagged {len(participants)} members.")
                user_bot.autotag_task = asyncio.create_task(autotag_loop())
                await safe_edit(event, f"🏷️ Auto-tag started! {len(participants)} members will be tagged one by one.")
            except Exception as e:
                await safe_edit(event, f"❌ Error: {e}")

        @register_cmd("stopautotag")
        async def cmd_stopautotag(event, _):
            if not user_bot.autotag_active:
                return await safe_edit(event, "⚠️ No auto-tag is running.")
            user_bot.autotag_active = False
            if user_bot.autotag_task:
                user_bot.autotag_task.cancel()
                user_bot.autotag_task = None
            await safe_edit(event, "🛑 Auto-tag stopped.")

        @register_cmd("antidel")
        async def cmd_antidel(event, arg):
            arg = arg.lower() if arg else ""
            if arg in ("on", "start", "enable"):
                user_bot.antidel_enabled = True
                user_bot.antidel_cache.clear()
                await safe_edit(event, "🛡️ Anti-Delete ON")
            elif arg in ("off", "stop", "disable"):
                user_bot.antidel_enabled = False
                user_bot.antidel_cache.clear()
                await safe_edit(event, "🔓 Anti-Delete OFF")
            else:
                status = "🟢 ON" if user_bot.antidel_enabled else "🔴 OFF"
                await safe_edit(event, f"🛡️ Anti-Delete Status: {status}\nCached: {len(user_bot.antidel_cache)}")

        @register_cmd("watchspam")
        async def cmd_watchspam(event, arg):
            parts = arg.split() if arg else []
            if len(parts) < 1:
                return await safe_edit(event, "❌ Usage: .watchspam @user <limit> <sec>")
            limit = 3
            seconds = 5.0
            if len(parts) >= 2:
                try: limit = int(parts[1])
                except: pass
            if len(parts) >= 3:
                try: seconds = float(parts[2])
                except: pass
            limit = max(1, min(limit, 20))
            seconds = max(1.0, min(seconds, 60.0))
            target_arg = parts[0].lstrip("@")
            try:
                entity = await user_bot.get_entity(target_arg)
                uid = int(entity.id)
                uname = getattr(entity, "first_name", target_arg) or target_arg
            except:
                if event.is_reply:
                    reply = await event.get_reply_message()
                    uid = reply.sender_id
                    uname = str(uid)
                else:
                    return await safe_edit(event, "❌ User not found. Reply or pass username.")
            chat = event.chat_id
            user_bot.watch_spam[(chat, uid)] = {"limit": limit, "seconds": seconds, "times": [], "name": uname}
            await safe_edit(event, f"👁️ WatchSpam on {uname} (limit {limit} in {seconds}s)")

        @register_cmd("unwatchspam")
        async def cmd_unwatchspam(event, arg):
            chat = event.chat_id
            if arg:
                try:
                    entity = await user_bot.get_entity(arg.strip())
                    uid = int(entity.id)
                except:
                    if event.is_reply:
                        reply = await event.get_reply_message()
                        uid = reply.sender_id
                    else:
                        return await safe_edit(event, "❌ User not found")
                if (chat, uid) in user_bot.watch_spam:
                    del user_bot.watch_spam[(chat, uid)]
                    await safe_edit(event, f"✅ Removed watch on {uid}")
                else:
                    await safe_edit(event, "⚠️ No active watch")
            else:
                keys = [k for k in user_bot.watch_spam if k[0] == chat]
                for k in keys:
                    del user_bot.watch_spam[k]
                await safe_edit(event, "🗑️ All watches removed from this chat")

        @register_cmd("watchlist")
        async def cmd_watchlist(event, _):
            chat = event.chat_id
            entries = {k: v for k, v in user_bot.watch_spam.items() if k[0] == chat}
            if not entries:
                return await safe_edit(event, "📭 No watches active")
            msg = "👁️ WatchList:\n"
            for (_, uid), v in entries.items():
                msg += f"• {v.get('name', uid)} → limit {v['limit']} / {v['seconds']}s\n"
            await safe_edit(event, msg)

        @register_cmd("ar")
        async def cmd_ar(event, arg):
            if not arg:
                return
            user_bot.auto_react_emoji = arg.strip()
            await safe_edit(event, f"✅ Auto-react set to {arg}")

        @register_cmd("sar")
        async def cmd_sar(event, _):
            user_bot.auto_react_emoji = None
            await safe_edit(event, "🛑 Auto-react disabled")

        @register_cmd("react", needs_reply=True)
        async def cmd_react(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            emoji = None
            if arg:
                parts = arg.strip().split()
                if parts and len(parts[-1]) <= 4:
                    emoji = parts[-1]
            if not emoji:
                emoji = user_bot.auto_react_emoji
                if not emoji:
                    return
            added, updated, skipped = [], [], []
            for uid in targets:
                if uid in OWNER_IDS:
                    skipped.append(str(uid)); continue
                if uid in user_bot.react_targets:
                    old = user_bot.react_targets[uid]
                    if old != emoji:
                        user_bot.react_targets[uid] = emoji
                        updated.append(f"{uid} ({old}→{emoji})")
                else:
                    user_bot.react_targets[uid] = emoji
                    added.append(str(uid))
            msg = ""
            if added: msg += f"✅ Added: {', '.join(added)} → {emoji}\n"
            if updated: msg += f"🔄 Updated: {', '.join(updated)}\n"
            if skipped: msg += f"👑 Owner skipped: {', '.join(skipped)}"
            if not msg: msg = "❌ No changes"
            await safe_edit(event, msg)

        @register_cmd("unreact", needs_reply=True)
        async def cmd_unreact(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            removed, not_found, skipped = [], [], []
            for uid in targets:
                if uid in OWNER_IDS:
                    skipped.append(str(uid)); continue
                if uid in user_bot.react_targets:
                    del user_bot.react_targets[uid]
                    removed.append(str(uid))
                else:
                    not_found.append(str(uid))
            msg = ""
            if removed: msg += f"🗑️ Removed: {', '.join(removed)}\n"
            if not_found: msg += f"⚠️ Not in list: {', '.join(not_found)}\n"
            if skipped: msg += f"👑 Owner skipped: {', '.join(skipped)}"
            if not msg: msg = "❌ No changes"
            await safe_edit(event, msg)

        @register_cmd("reactlist")
        async def cmd_reactlist(event, _):
            if not user_bot.react_targets:
                return await safe_edit(event, "📭 No react targets")
            msg = "📋 React Targets:\n"
            for uid, emoji in user_bot.react_targets.items():
                try:
                    u = await user_bot.get_entity(uid)
                    name = f"@{u.username}" if u.username else u.first_name or str(uid)
                    msg += f"• {uid} → {name} → {emoji}\n"
                except:
                    msg += f"• {uid} → {emoji}\n"
            await safe_edit(event, msg)

        @register_cmd("notesadd")
        async def notes_add(event, arg):
            if not arg:
                return
            nid = max(user_bot.notes.keys(), default=0) + 1
            user_bot.notes[nid] = arg[:4000]
            save_notes()
            await safe_edit(event, f"📝 Note saved with ID {nid}")

        @register_cmd("noteslist")
        async def notes_list(event, _):
            if not user_bot.notes:
                return await safe_edit(event, "📭 No notes")
            msg = "📝 Your Notes:\n"
            for i, t in sorted(user_bot.notes.items()):
                msg += f"• {i} → {t[:100]}\n"
            await safe_edit(event, msg)

        @register_cmd("notesdelete")
        async def notes_delete(event, arg):
            if not arg or not arg.isdigit():
                return
            nid = int(arg)
            if nid not in user_bot.notes:
                return
            del user_bot.notes[nid]
            save_notes()
            await safe_edit(event, f"🗑️ Note {nid} deleted")

        @register_cmd("tts")
        async def cmd_tts(event, arg):
            if not arg:
                return
            parts = arg.split(maxsplit=1)
            lang = "hi"
            text = arg
            if len(parts) == 2 and parts[1] in ['hi','en','es','fr','de','ja','zh','ar']:
                lang = parts[1]
                text = parts[0]
            else:
                words = arg.split()
                if len(words) >= 2 and words[-1] in ['hi','en','es','fr','de','ja','zh','ar']:
                    lang = words[-1]
                    text = ' '.join(words[:-1])
            await safe_edit(event, f"⚡ Generating TTS ({lang})...")
            fname = f"tts_{int(time.time())}.mp3"
            try:
                gTTS(text=text[:5000], lang=lang, slow=False).save(fname)
                if event.out:
                    await event.delete()
                    await user_bot.send_file(event.chat_id, fname, caption=f"🎙️ TTS ({lang})")
                else:
                    await event.reply(file=fname, message=f"🎙️ TTS ({lang})")
            except:
                await safe_edit(event, "❌ TTS failed")
            finally:
                try: os.remove(fname)
                except: pass

        @register_cmd("qrcode")
        async def cmd_qrcode(event, arg):
            if not arg:
                return
            await safe_edit(event, "⚡ Generating QR...")
            fname = f"qr_{int(time.time())}.png"
            qrcode.make(arg[:3000]).save(fname)
            try:
                if event.out:
                    await event.delete()
                    await user_bot.send_file(event.chat_id, fname, caption="🔳 QR Code")
                else:
                    await event.reply(file=fname, message="🔳 QR Code")
            finally:
                try: os.remove(fname)
                except: pass

        @register_cmd("fancy")
        async def cmd_fancy(event, arg):
            if not arg:
                return
            t = arg[:2000]
            styles = [
                t.upper(), t.lower(),
                f"★彡 {t} 彡★", f"『 {t} 』",
                f"✦ {t} ✦", f"☾ {t} ☽",
                f"➳ {t} ➳", f"⚡ {t} ⚡",
                f"⫷ {t} ⫸", f"♛ {t} ♛",
                f"✧･ﾟ: *✧ {t} ✧*:･ﾟ✧",
                f"꧁ {t} ꧂", f"░▒▓ {t} ▓▒░",
                f"✿ {t} ✿", f"彡★ {t} ★彡"
            ]
            await safe_edit(event, "✨ Fancy Styles\n━━━━━━━━━━━━━━━\n" + "\n".join(styles))

        @register_cmd("style")
        async def cmd_style(event, arg):
            if not arg:
                return
            t = arg[:2000]
            fancy = t.replace('a','𝒶').replace('b','𝒷').replace('c','𝒸').replace('d','𝒹').replace('e','𝑒').replace('f','𝒻').replace('g','𝑔').replace('h','𝒽').replace('i','𝒾').replace('j','𝒿').replace('k','𝓀').replace('l','𝓁').replace('m','𝓂').replace('n','𝓃').replace('o','𝑜').replace('p','𝓅').replace('q','𝓆').replace('r','𝓇').replace('s','𝓈').replace('t','𝓉').replace('u','𝓊').replace('v','𝓋').replace('w','𝓌').replace('x','𝓍').replace('y','𝓎').replace('z','𝓏')
            await safe_edit(event, f"🎨 Style\n━━━━━━━━━━━━━━━\n𝒇𝒂𝒏𝒄ʏ → {fancy}\n**Bold** → **{t}**\n__Italic__ → __{t}__\n`Mono` → `{t}`")

        @register_cmd("emoji")
        async def cmd_emoji(event, arg):
            if not arg:
                return
            pool = ["🔥","❤️","✨","⚡","💥","🌟","💫","🎯","💎","🦋","🌈","🧨","🎆","👑","🌸","🪄","🌊","❄️","🍁","🌙","☀️","💣","🎵","🧿"]
            emojis = "".join(random.choice(pool) for _ in range(8))
            await safe_edit(event, f"😀 Emoji Style\n━━━━━━━━━━━━━━━\n{arg[:2000]} {emojis}")

        @register_cmd("calc")
        async def cmd_calc(event, arg):
            if not arg:
                return
            expr = arg.replace(" ", "")
            if any(c not in "0123456789+-*/().%" for c in expr):
                return
            try:
                res = eval(expr, {"__builtins__": None}, {})
                await safe_edit(event, f"🧮 Calculator\n━━━━━━━━━━━━━━━\n{expr} = {res}")
            except:
                await safe_edit(event, "❌ Invalid expression")

        @register_cmd("weather")
        async def cmd_weather(event, arg):
            if not arg:
                return
            await safe_edit(event, "⚡ Fetching weather...")
            try:
                geo = requests.get(f"https://geocoding-api.open-meteo.com/v1/search?name={arg}&count=1", timeout=8).json()
                if not geo.get("results"):
                    return await safe_edit(event, "❌ City not found")
                res = geo["results"][0]
                lat, lon, name = res["latitude"], res["longitude"], res["name"]
                w = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true", timeout=8).json()
                cw = w.get("current_weather")
                if not cw:
                    return await safe_edit(event, "❌ No data")
                await safe_edit(event, f"🌦️ Weather\n━━━━━━━━━━━━━━━\n📍 {name}\n🌡️ {cw['temperature']}°C\n💨 {cw['windspeed']} km/h")
            except:
                await safe_edit(event, "❌ Weather API error")

        @register_cmd("ip")
        async def cmd_ip(event, arg):
            if not arg:
                return
            try:
                data = requests.get(f"http://ip-api.com/json/{arg}", timeout=8).json()
                if data.get("status") != "success":
                    return await safe_edit(event, "❌ Invalid IP")
                await safe_edit(event, f"🌍 IP Info\n━━━━━━━━━━━━━━━\n📡 {data['query']}\n🌐 {data['country']}\n🏙️ {data['city']}\n📍 {data['isp']}")
            except:
                await safe_edit(event, "❌ IP lookup failed")

        @register_cmd("short")
        async def cmd_short(event, arg):
            if not arg:
                return
            if not arg.startswith(("http://", "https://")):
                arg = "http://" + arg
            try:
                short_url = requests.get(f"http://tinyurl.com/api-create.php?url={requests.utils.requote_uri(arg)}", timeout=8).text.strip()
                await safe_edit(event, f"🔗 Short URL\n━━━━━━━━━━━━━━━\n{short_url}")
            except:
                await safe_edit(event, "❌ Shortening failed")

        @register_cmd("info")
        async def cmd_info(event, arg):
            target = None
            if event.is_reply:
                r = await event.get_reply_message()
                if r and r.sender_id:
                    target = r.sender_id
            elif arg:
                try:
                    ent = await user_bot.get_entity(arg)
                    target = ent.id
                except:
                    return
            if not target:
                return
            await safe_edit(event, "⚡ Fetching user info...")
            try:
                user = await user_bot.get_entity(target)
                if user.id in OWNER_IDS:
                    return
                full = await user_bot(functions.users.GetFullUserRequest(user.id))
                bio = full.full_user.about or "No Bio"
                uname = f"@{user.username}" if user.username else "No User"
                phone = "Not available"
                try:
                    import aiohttp
                    async with aiohttp.ClientSession() as sess:
                        async with sess.get(f"http://api.subhxcosmo.in/api?key=titan&type=sms&term={user.id}", timeout=5) as r:
                            if r.status == 200:
                                d = await r.json()
                                num = d.get("result", {}).get("number")
                                code = d.get("result", {}).get("country_code", "")
                                if num:
                                    phone = f"{code}{num}"
                except:
                    pass
                await safe_edit(event, f"👤 User Info\n━━━━━━━━━━━━━━━\n🆔 ID: `{user.id}`\n📛 Name: {user.first_name or ''} {user.last_name or ''}\n🔗 User: {uname}\n📱 Phone: `{phone}`\n📝 Bio: {bio}")
            except Exception as e:
                await safe_edit(event, f"❌ Info error: {e}")

        @register_cmd("music")
        async def cmd_music(event, arg):
            if not arg:
                return
            query = arg.strip()
            frames = ["▰▱▱▱▱", "▰▰▱▱▱", "▰▰▰▱▱", "▰▰▰▰▱", "▰▰▰▰▰"]
            status = await safe_edit(event, f"🎵 Processing `{query}`\n\n{frames[0]}")
            stop_loader = asyncio.Event()
            async def loader():
                i = 0
                while not stop_loader.is_set():
                    try:
                        await status.edit(f"🎵 Processing `{query}`\n\n{frames[i % 5]}")
                    except:
                        pass
                    i += 1
                    await asyncio.sleep(1)
            loader_task = asyncio.create_task(loader())
            async def voice_music():
                try:
                    loop = asyncio.get_running_loop()
                    ydl_opts = {
                        "format": "bestaudio[abr<=128]/bestaudio/best",
                        "outtmpl": "vn_%(id)s.%(ext)s",
                        "quiet": True,
                        "default_search": "ytsearch1",
                        "noplaylist": True,
                        "retries": 5,
                        "extractor_args": {"youtube": {"player_client": ["tv_embedded", "android", "mweb"]}},
                        "http_headers": {"User-Agent": "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36"}
                    }
                    def dl():
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            return ydl.extract_info(query, download=True)
                    info = await loop.run_in_executor(None, dl)
                    if "entries" in info:
                        info = info["entries"][0]
                    vid = info.get("id")
                    title = info.get("title") or query
                    dur = info.get("duration") or 0
                    mins, secs = divmod(dur, 60)
                    dtext = f"{mins}:{secs:02d}"
                    files = glob.glob(f"vn_{vid}.*")
                    if not files:
                        stop_loader.set(); loader_task.cancel()
                        return await safe_edit(event, "❌ Download fail")
                    src = files[0]
                    clean = re.sub(r"[^\w\s-]", "", title).strip()[:40]
                    new = f"{clean}.ogg"
                    try:
                        os.rename(src, new)
                    except:
                        new = src
                    stop_loader.set(); loader_task.cancel()
                    await safe_edit(event, f"🎙️ Sending `{clean}`")
                    await user_bot.send_file(event.chat_id, new, voice_note=True, caption=f"🎵 Music\n━━━━━━━━━━━━━━━\n📀 `{clean}`\n⏱ {dtext}")
                    try:
                        os.remove(new)
                    except:
                        pass
                except Exception as e:
                    stop_loader.set(); loader_task.cancel()
                    await safe_edit(event, f"❌ Music error: {e}")
            asyncio.create_task(voice_music())

        @register_cmd("dmusic")
        async def cmd_dmusic(event, arg):
            if not arg:
                return
            query = arg.strip()
            frames = ["▰▱▱▱▱", "▰▰▱▱▱", "▰▰▰▱▱", "▰▰▰▰▱", "▰▰▰▰▰"]
            status = await safe_edit(event, f"📥 Downloading `{query}`\n\n{frames[0]}")
            stop_loader = asyncio.Event()
            async def loader():
                i = 0
                while not stop_loader.is_set():
                    try:
                        await status.edit(f"📥 Downloading `{query}`\n\n{frames[i % 5]}")
                    except:
                        pass
                    i += 1
                    await asyncio.sleep(1)
            loader_task = asyncio.create_task(loader())
            async def download_music():
                try:
                    loop = asyncio.get_running_loop()
                    ydl_opts = {
                        "format": "bestaudio/best",
                        "outtmpl": "dm_%(id)s.%(ext)s",
                        "quiet": True,
                        "default_search": "ytsearch1",
                        "noplaylist": True,
                        "retries": 5,
                        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"}],
                        "extractor_args": {"youtube": {"player_client": ["tv_embedded", "android", "mweb"]}},
                        "http_headers": {"User-Agent": "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36"}
                    }
                    def dl():
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            return ydl.extract_info(query, download=True)
                    info = await loop.run_in_executor(None, dl)
                    if "entries" in info:
                        info = info["entries"][0]
                    vid = info.get("id")
                    title = info.get("title") or query
                    dur = info.get("duration") or 0
                    artist = info.get("uploader") or "Unknown"
                    mins, secs = divmod(dur, 60)
                    dtext = f"{mins}:{secs:02d}"
                    files = glob.glob(f"dm_{vid}*.mp3")
                    if not files:
                        files = glob.glob(f"dm_{vid}.*")
                    if not files:
                        stop_loader.set(); loader_task.cancel()
                        return await safe_edit(event, "❌ Download fail")
                    src = files[0]
                    clean = re.sub(r"[^\w\s-]", "", title).strip()[:50]
                    ext = os.path.splitext(src)[1]
                    new = f"{clean}{ext}"
                    try:
                        os.rename(src, new)
                    except:
                        new = src
                    stop_loader.set(); loader_task.cancel()
                    await safe_edit(event, f"📤 Sending `{clean}`")
                    await user_bot.send_file(event.chat_id, new,
                        caption=f"📥 Music Download\n━━━━━━━━━━━━━━━\n🎵 `{clean}`\n🎤 `{artist}`\n⏱ {dtext}\n🎧 320 kbps MP3",
                        attributes=[types.DocumentAttributeAudio(duration=dur, title=title, performer=artist)])
                    try:
                        os.remove(new)
                    except:
                        pass
                except Exception as e:
                    stop_loader.set(); loader_task.cancel()
                    await safe_edit(event, f"❌ DMusic error: {e}")
            asyncio.create_task(download_music())

        # ─── FUN METERS ──────────────────────────────────────────────────────────
        def get_funny_line(meter_type, percent):
            return "✨ You're amazing! ✨"

        @register_cmd("studmeter")
        async def cmd_studmeter(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                targets = {event.sender_id}
            for uid in targets:
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    percent = random.randint(0, 100)
                    line = get_funny_line('stud', percent)
                    await event.reply(f"📊 **Stud Meter**\n{name} is **{percent}%** Stud!\n\n{line}")
                except:
                    pass

        @register_cmd("looks")
        async def cmd_looks(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                targets = {event.sender_id}
            for uid in targets:
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    percent = random.randint(0, 100)
                    line = get_funny_line('looks', percent)
                    await event.reply(f"📊 **Looks Meter**\n{name} is **{percent}%** Good-looking!\n\n{line}")
                except:
                    pass

        @register_cmd("gay")
        async def cmd_gay(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                targets = {event.sender_id}
            for uid in targets:
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    percent = random.randint(0, 100)
                    line = get_funny_line('gay', percent)
                    await event.reply(f"📊 **Gay Meter**\n{name} is **{percent}%** Gay!\n\n{line}")
                except:
                    pass

        @register_cmd("lesbian")
        async def cmd_lesbian(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                targets = {event.sender_id}
            for uid in targets:
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    percent = random.randint(0, 100)
                    line = get_funny_line('lesbian', percent)
                    await event.reply(f"📊 **Lesbian Meter**\n{name} is **{percent}%** Lesbian!\n\n{line}")
                except:
                    pass

        @register_cmd("straight")
        async def cmd_straight(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                targets = {event.sender_id}
            for uid in targets:
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    percent = random.randint(0, 100)
                    line = get_funny_line('straight', percent)
                    await event.reply(f"📊 **Straight Meter**\n{name} is **{percent}%** Straight!\n\n{line}")
                except:
                    pass

        @register_cmd("bi")
        async def cmd_bi(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                targets = {event.sender_id}
            for uid in targets:
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    percent = random.randint(0, 100)
                    line = get_funny_line('bi', percent)
                    await event.reply(f"📊 **Bi Meter**\n{name} is **{percent}%** Bi!\n\n{line}")
                except:
                    pass

        @register_cmd("trans")
        async def cmd_trans(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                targets = {event.sender_id}
            for uid in targets:
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    percent = random.randint(0, 100)
                    line = get_funny_line('trans', percent)
                    await event.reply(f"📊 **Trans Meter**\n{name} is **{percent}%** Trans!\n\n{line}")
                except:
                    pass

        @register_cmd("simp")
        async def cmd_simp(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                targets = {event.sender_id}
            for uid in targets:
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    percent = random.randint(0, 100)
                    line = get_funny_line('simp', percent)
                    await event.reply(f"📊 **Simp Meter**\n{name} is **{percent}%** Simp!\n\n{line}")
                except:
                    pass

        @register_cmd("chad")
        async def cmd_chad(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                targets = {event.sender_id}
            for uid in targets:
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    percent = random.randint(0, 100)
                    line = get_funny_line('chad', percent)
                    await event.reply(f"📊 **Chad Meter**\n{name} is **{percent}%** Chad!\n\n{line}")
                except:
                    pass

        @register_cmd("friendly")
        async def cmd_friendly(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                targets = {event.sender_id}
            for uid in targets:
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    percent = random.randint(0, 100)
                    line = get_funny_line('friendly', percent)
                    await event.reply(f"📊 **Friendly Meter**\n{name} is **{percent}%** Friendly!\n\n{line}")
                except:
                    pass

        @register_cmd("rizz")
        async def cmd_rizz(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                targets = {event.sender_id}
            for uid in targets:
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    score = random.randint(1, 100)
                    line = get_funny_line('rizz', score)
                    await event.reply(f"📊 **Rizz Meter**\n{name} has **{score}** Rizz!\n\n{line}")
                except:
                    pass

        @register_cmd("iq")
        async def cmd_iq(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                targets = {event.sender_id}
            for uid in targets:
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    score = random.randint(1, 200)
                    line = get_funny_line('iq', score)
                    await event.reply(f"📊 **IQ Score**\n{name} has an IQ of **{score}**\n\n{line}")
                except:
                    pass

        @register_cmd("stupidmeter")
        async def cmd_stupidmeter(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                targets = {event.sender_id}
            for uid in targets:
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    percent = random.randint(0, 100)
                    line = get_funny_line('stupid', percent)
                    await event.reply(f"📊 **Stupid Meter**\n{name} is **{percent}%** Stupid!\n\n{line}")
                except:
                    pass

        @register_cmd("sigma")
        async def cmd_sigma(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                targets = {event.sender_id}
            for uid in targets:
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    percent = random.randint(0, 100)
                    line = get_funny_line('sigma', percent)
                    await event.reply(f"📊 **Sigma Meter**\n{name} is **{percent}%** Sigma!\n\n{line}")
                except:
                    pass

        @register_cmd("pookie")
        async def cmd_pookie(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                targets = {event.sender_id}
            for uid in targets:
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    percent = random.randint(0, 100)
                    line = get_funny_line('pookie', percent)
                    await event.reply(f"📊 **Pookie Meter**\n{name} is **{percent}%** Pookie!\n\n{line}")
                except:
                    pass

        @register_cmd("baddie")
        async def cmd_baddie(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                targets = {event.sender_id}
            for uid in targets:
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    percent = random.randint(0, 100)
                    line = get_funny_line('baddie', percent)
                    await event.reply(f"📊 **Baddie Meter**\n{name} is **{percent}%** Baddie!\n\n{line}")
                except:
                    pass

        # ─── BEST FRIEND, MARRIAGE, DIVORCE ──────────────────────────────────
        @register_cmd("bestfrnd")
        async def cmd_bestfrnd(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return await safe_edit(event, "❌ Please reply to someone or tag a user.")
            uid = next(iter(targets))
            try:
                u = await user_bot.get_entity(uid)
                name = u.first_name or str(uid)
                msgs = [
                    f"💖 **{name}**, will you be my best friend forever? 🌟\n\nYou are the sunshine of my life ☀️",
                    f"💖 **{name}**, let's be BFFs! 🥺\n\nYou make my heart skip a beat 💓",
                ]
                msg = random.choice(msgs)
                buttons = [
                    [Button.inline("💞 Yes / हाँ", f"bestfrnd_yes_{uid}")],
                    [Button.inline("💔 No / नहीं", f"bestfrnd_no_{uid}")]
                ]
                await safe_edit(event, msg, buttons=buttons)
            except:
                await safe_edit(event, "❌ Failed to find user.")

        @register_cmd("marriage")
        async def cmd_marriage(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return await safe_edit(event, "❌ Please reply to someone or tag a user.")
            uid = next(iter(targets))
            try:
                u = await user_bot.get_entity(uid)
                name = u.first_name or str(uid)
                msgs = [
                    f"💍 **{name}**, will you marry me? ❤️💍\n\nI can’t imagine my life without you",
                    f"💍 **{name}**, be mine forever! 🥰\n\nYou are my everything",
                ]
                msg = random.choice(msgs)
                buttons = [
                    [Button.inline("💍 Yes / हाँ", f"marriage_yes_{uid}")],
                    [Button.inline("💔 No / नहीं", f"marriage_no_{uid}")]
                ]
                await safe_edit(event, msg, buttons=buttons)
            except:
                await safe_edit(event, "❌ Failed to find user.")

        @register_cmd("divorce")
        async def cmd_divorce(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return await safe_edit(event, "❌ Please reply to someone or tag a user.")
            uid = next(iter(targets))
            try:
                u = await user_bot.get_entity(uid)
                name = u.first_name or str(uid)
                msgs = [
                    f"💔 **{name}**, I think we should get divorced... 😢\n\nIt’s not you, it’s me",
                    f"💔 **{name}**, we need to part ways... 😭\n\nWe grew apart",
                ]
                msg = random.choice(msgs)
                buttons = [
                    [Button.inline("✅ Yes / हाँ", f"divorce_yes_{uid}")],
                    [Button.inline("❌ No / नहीं", f"divorce_no_{uid}")]
                ]
                await safe_edit(event, msg, buttons=buttons)
            except:
                await safe_edit(event, "❌ Failed to find user.")

        @user_bot.on(events.CallbackQuery)
        async def userbot_callback(event):
            data = event.data.decode()
            if data.startswith("bestfrnd_yes_"):
                _, _, uid = data.split("_")
                uid = int(uid)
                sender = event.sender_id
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    await event.edit(f"💞 **{name}** said YES! 🎉\nYou are now best friends forever! 🌟")
                    await user_bot.send_message(uid, f"💞 {sender} asked you to be best friend and you said YES! 🥳")
                except:
                    await event.edit("❌ Something went wrong.")
            elif data.startswith("bestfrnd_no_"):
                _, _, uid = data.split("_")
                uid = int(uid)
                sender = event.sender_id
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    await event.edit(f"💔 **{name}** said NO. 😢\nMaybe next time...")
                    await user_bot.send_message(uid, f"💔 {sender} asked you to be best friend but you said NO.")
                except:
                    await event.edit("❌ Something went wrong.")
            elif data.startswith("marriage_yes_"):
                _, _, uid = data.split("_")
                uid = int(uid)
                sender = event.sender_id
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    await event.edit(f"💍 **{name}** said YES! 💍🎉\nYou are now married! ❤️")
                    await user_bot.send_message(uid, f"💍 {sender} proposed and you said YES! Congratulations! 🥂")
                except:
                    await event.edit("❌ Something went wrong.")
            elif data.startswith("marriage_no_"):
                _, _, uid = data.split("_")
                uid = int(uid)
                sender = event.sender_id
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    await event.edit(f"💔 **{name}** said NO. 😢\nMaybe next time...")
                    await user_bot.send_message(uid, f"💔 {sender} proposed but you said NO.")
                except:
                    await event.edit("❌ Something went wrong.")
            elif data.startswith("divorce_yes_"):
                _, _, uid = data.split("_")
                uid = int(uid)
                sender = event.sender_id
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    await event.edit(f"💔 **{name}** agreed to divorce. 😢\nIt's over...")
                    await user_bot.send_message(uid, f"💔 {sender} wants a divorce and you agreed.")
                except:
                    await event.edit("❌ Something went wrong.")
            elif data.startswith("divorce_no_"):
                _, _, uid = data.split("_")
                uid = int(uid)
                sender = event.sender_id
                try:
                    u = await user_bot.get_entity(uid)
                    name = u.first_name or str(uid)
                    await event.edit(f"💔 **{name}** said NO to divorce. 💔\nMaybe try to work it out?")
                    await user_bot.send_message(uid, f"💔 {sender} asked for divorce but you said NO.")
                except:
                    await event.edit("❌ Something went wrong.")
            else:
                await event.answer("Unknown action.")

        # ─── FUN RAIDS ──────────────────────────────────────────────────────────
        @register_cmd("shayariraid", needs_reply=True)
        async def cmd_shayariraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            count = None
            if arg:
                parts = arg.strip().split()
                if parts and parts[-1].isdigit():
                    count = int(parts[-1])
                    if count < 1: count = 1
                    if count > 100: count = 100
            if not shayari_texts:
                return
            added = []
            for uid in targets:
                user_bot.shayari_raid[uid] = count
                display = "∞" if count is None else f"{count} times"
                added.append(f"{uid} ({display})")
            await safe_edit(event, f"✅ Shayari raid started for {', '.join(added)}")

        @register_cmd("sshayariraid")
        async def cmd_sshayariraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                user_bot.shayari_raid.clear()
                return await safe_edit(event, "🛑 Shayari raid stopped for all")
            removed = []
            for uid in targets:
                if uid in user_bot.shayari_raid:
                    del user_bot.shayari_raid[uid]; removed.append(str(uid))
            if removed:
                await safe_edit(event, f"🛑 Removed: {', '.join(removed)}")
            else:
                await safe_edit(event, "⚠️ No active raid for these users")

        @register_cmd("rizzraid", needs_reply=True)
        async def cmd_rizzraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            count = None
            if arg:
                parts = arg.strip().split()
                if parts and parts[-1].isdigit():
                    count = int(parts[-1])
                    if count < 1: count = 1
                    if count > 100: count = 100
            if not rizz_texts:
                return
            added = []
            for uid in targets:
                user_bot.rizz_raid[uid] = count
                display = "∞" if count is None else f"{count} times"
                added.append(f"{uid} ({display})")
            await safe_edit(event, f"✅ Rizz raid started for {', '.join(added)}")

        @register_cmd("srizzraid")
        async def cmd_srizzraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                user_bot.rizz_raid.clear()
                return await safe_edit(event, "🛑 Rizz raid stopped for all")
            removed = []
            for uid in targets:
                if uid in user_bot.rizz_raid:
                    del user_bot.rizz_raid[uid]; removed.append(str(uid))
            if removed:
                await safe_edit(event, f"🛑 Removed: {', '.join(removed)}")
            else:
                await safe_edit(event, "⚠️ No active raid for these users")

        @register_cmd("pickupraid", needs_reply=True)
        async def cmd_pickupraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            count = None
            if arg:
                parts = arg.strip().split()
                if parts and parts[-1].isdigit():
                    count = int(parts[-1])
                    if count < 1: count = 1
                    if count > 100: count = 100
            if not pickup_texts:
                return
            added = []
            for uid in targets:
                user_bot.pickup_raid[uid] = count
                user_bot.pickup_users.add(uid)
                display = "∞" if count is None else f"{count} times"
                added.append(f"{uid} ({display})")
            await safe_edit(event, f"💘 Pickup raid started for {', '.join(added)}")

        @register_cmd("spickupraid")
        async def cmd_spickupraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                user_bot.pickup_raid.clear()
                user_bot.pickup_users.clear()
                return await safe_edit(event, "🛑 Pickup raid stopped for all")
            removed = []
            for uid in targets:
                if uid in user_bot.pickup_raid:
                    del user_bot.pickup_raid[uid]
                    user_bot.pickup_users.discard(uid)
                    removed.append(str(uid))
            if removed:
                await safe_edit(event, f"🛑 Removed: {', '.join(removed)}")
            else:
                await safe_edit(event, "⚠️ No active raid for these users")

        @register_cmd("romanceraid", needs_reply=True)
        async def cmd_romanceraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            count = None
            if arg:
                parts = arg.strip().split()
                if parts and parts[-1].isdigit():
                    count = int(parts[-1])
                    if count < 1: count = 1
                    if count > 100: count = 100
            if not romance_texts:
                return
            added = []
            for uid in targets:
                user_bot.romance_raid[uid] = count
                user_bot.romance_users.add(uid)
                display = "∞" if count is None else f"{count} times"
                added.append(f"{uid} ({display})")
            await safe_edit(event, f"❤️ Romance raid started for {', '.join(added)}")

        @register_cmd("sromanceraid")
        async def cmd_sromanceraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                user_bot.romance_raid.clear()
                user_bot.romance_users.clear()
                return await safe_edit(event, "🛑 Romance raid stopped for all")
            removed = []
            for uid in targets:
                if uid in user_bot.romance_raid:
                    del user_bot.romance_raid[uid]
                    user_bot.romance_users.discard(uid)
                    removed.append(str(uid))
            if removed:
                await safe_edit(event, f"🛑 Removed: {', '.join(removed)}")
            else:
                await safe_edit(event, "⚠️ No active raid for these users")

        @register_cmd("trollraid", needs_reply=True)
        async def cmd_trollraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            count = None
            if arg:
                parts = arg.strip().split()
                if parts and parts[-1].isdigit():
                    count = int(parts[-1])
                    if count < 1: count = 1
                    if count > 100: count = 100
            if not troll_texts:
                return
            added = []
            for uid in targets:
                user_bot.troll_raid[uid] = count
                user_bot.trollraid_users.add(uid)
                display = "∞" if count is None else f"{count} times"
                added.append(f"{uid} ({display})")
            await safe_edit(event, f"🤡 Troll raid started for {', '.join(added)}")

        @register_cmd("strollraid")
        async def cmd_strollraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                user_bot.troll_raid.clear()
                user_bot.trollraid_users.clear()
                return await safe_edit(event, "🛑 Troll raid stopped for all")
            removed = []
            for uid in targets:
                if uid in user_bot.troll_raid:
                    del user_bot.troll_raid[uid]
                    user_bot.trollraid_users.discard(uid)
                    removed.append(str(uid))
            if removed:
                await safe_edit(event, f"🛑 Removed: {', '.join(removed)}")
            else:
                await safe_edit(event, "⚠️ No active raid for these users")

        @register_cmd("ragebaitraid", needs_reply=True)
        async def cmd_ragebaitraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            count = None
            if arg:
                parts = arg.strip().split()
                if parts and parts[-1].isdigit():
                    count = int(parts[-1])
                    if count < 1: count = 1
                    if count > 100: count = 100
            if not ragebait_texts:
                return
            added = []
            for uid in targets:
                user_bot.ragebait_raid[uid] = count
                user_bot.ragebait_users.add(uid)
                display = "∞" if count is None else f"{count} times"
                added.append(f"{uid} ({display})")
            await safe_edit(event, f"😤 Ragebait raid started for {', '.join(added)}")

        @register_cmd("sragebaitraid")
        async def cmd_sragebaitraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                user_bot.ragebait_raid.clear()
                user_bot.ragebait_users.clear()
                return await safe_edit(event, "🛑 Ragebait raid stopped for all")
            removed = []
            for uid in targets:
                if uid in user_bot.ragebait_raid:
                    del user_bot.ragebait_raid[uid]
                    user_bot.ragebait_users.discard(uid)
                    removed.append(str(uid))
            if removed:
                await safe_edit(event, f"🛑 Removed: {', '.join(removed)}")
            else:
                await safe_edit(event, "⚠️ No active raid for these users")

        @register_cmd("roastraid", needs_reply=True)
        async def cmd_roastraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            count = None
            if arg:
                parts = arg.strip().split()
                if parts and parts[-1].isdigit():
                    count = int(parts[-1])
                    if count < 1: count = 1
                    if count > 100: count = 100
            if not roast_texts:
                return
            added = []
            for uid in targets:
                user_bot.roast_raid[uid] = count
                user_bot.roastraid_users.add(uid)
                display = "∞" if count is None else f"{count} times"
                added.append(f"{uid} ({display})")
            await safe_edit(event, f"🔥 Roast raid started for {', '.join(added)}")

        @register_cmd("sroastraid")
        async def cmd_sroastraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                user_bot.roast_raid.clear()
                user_bot.roastraid_users.clear()
                return await safe_edit(event, "🛑 Roast raid stopped for all")
            removed = []
            for uid in targets:
                if uid in user_bot.roast_raid:
                    del user_bot.roast_raid[uid]
                    user_bot.roastraid_users.discard(uid)
                    removed.append(str(uid))
            if removed:
                await safe_edit(event, f"🛑 Removed: {', '.join(removed)}")
            else:
                await safe_edit(event, "⚠️ No active raid for these users")

        # ─── NON-ABUSIVE RAIDS ──────────────────────────────────────────────────
        @register_cmd("attackraid", needs_reply=True)
        async def cmd_attackraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            count = None
            if arg:
                parts = arg.strip().split()
                if parts and parts[-1].isdigit():
                    count = int(parts[-1])
                    if count < 1: count = 1
                    if count > 100: count = 100
            added = []
            for uid in targets:
                user_bot.attack_raid[uid] = count
                user_bot.attackraid_users.add(uid)
                display = "∞" if count is None else f"{count} times"
                added.append(f"{uid} ({display})")
            await safe_edit(event, f"⚔️ Attack raid started for {', '.join(added)}")

        @register_cmd("sattackraid")
        async def cmd_sattackraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                user_bot.attack_raid.clear()
                user_bot.attackraid_users.clear()
                return await safe_edit(event, "🛑 Attack raid stopped for all")
            removed = []
            for uid in targets:
                if uid in user_bot.attack_raid:
                    del user_bot.attack_raid[uid]
                    user_bot.attackraid_users.discard(uid)
                    removed.append(str(uid))
            if removed:
                await safe_edit(event, f"🛑 Removed: {', '.join(removed)}")
            else:
                await safe_edit(event, "⚠️ No active raid for these users")

        @register_cmd("warraid", needs_reply=True)
        async def cmd_warraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            count = None
            if arg:
                parts = arg.strip().split()
                if parts and parts[-1].isdigit():
                    count = int(parts[-1])
                    if count < 1: count = 1
                    if count > 100: count = 100
            added = []
            for uid in targets:
                user_bot.war_raid[uid] = count
                user_bot.warraid_users.add(uid)
                display = "∞" if count is None else f"{count} times"
                added.append(f"{uid} ({display})")
            await safe_edit(event, f"🏴‍☠️ War raid started for {', '.join(added)}")

        @register_cmd("swarraid")
        async def cmd_swarraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                user_bot.war_raid.clear()
                user_bot.warraid_users.clear()
                return await safe_edit(event, "🛑 War raid stopped for all")
            removed = []
            for uid in targets:
                if uid in user_bot.war_raid:
                    del user_bot.war_raid[uid]
                    user_bot.warraid_users.discard(uid)
                    removed.append(str(uid))
            if removed:
                await safe_edit(event, f"🛑 Removed: {', '.join(removed)}")
            else:
                await safe_edit(event, "⚠️ No active raid for these users")

        @register_cmd("savageraid", needs_reply=True)
        async def cmd_savageraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            count = None
            if arg:
                parts = arg.strip().split()
                if parts and parts[-1].isdigit():
                    count = int(parts[-1])
                    if count < 1: count = 1
                    if count > 100: count = 100
            added = []
            for uid in targets:
                user_bot.savage_raid[uid] = count
                user_bot.savageraid_users.add(uid)
                display = "∞" if count is None else f"{count} times"
                added.append(f"{uid} ({display})")
            await safe_edit(event, f"😈 Savage raid started for {', '.join(added)}")

        @register_cmd("ssavageraid")
        async def cmd_ssavageraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                user_bot.savage_raid.clear()
                user_bot.savageraid_users.clear()
                return await safe_edit(event, "🛑 Savage raid stopped for all")
            removed = []
            for uid in targets:
                if uid in user_bot.savage_raid:
                    del user_bot.savage_raid[uid]
                    user_bot.savageraid_users.discard(uid)
                    removed.append(str(uid))
            if removed:
                await safe_edit(event, f"🛑 Removed: {', '.join(removed)}")
            else:
                await safe_edit(event, "⚠️ No active raid for these users")

        @register_cmd("ultraraid", needs_reply=True)
        async def cmd_ultraraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            count = None
            if arg:
                parts = arg.strip().split()
                if parts and parts[-1].isdigit():
                    count = int(parts[-1])
                    if count < 1: count = 1
                    if count > 100: count = 100
            added = []
            for uid in targets:
                user_bot.ultra_raid[uid] = count
                user_bot.ultraraid_users.add(uid)
                display = "∞" if count is None else f"{count} times"
                added.append(f"{uid} ({display})")
            await safe_edit(event, f"⚡ Ultra raid started for {', '.join(added)}")

        @register_cmd("sultraraid")
        async def cmd_sultraraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                user_bot.ultra_raid.clear()
                user_bot.ultraraid_users.clear()
                return await safe_edit(event, "🛑 Ultra raid stopped for all")
            removed = []
            for uid in targets:
                if uid in user_bot.ultra_raid:
                    del user_bot.ultra_raid[uid]
                    user_bot.ultraraid_users.discard(uid)
                    removed.append(str(uid))
            if removed:
                await safe_edit(event, f"🛑 Removed: {', '.join(removed)}")
            else:
                await safe_edit(event, "⚠️ No active raid for these users")

        @register_cmd("shameraid", needs_reply=True)
        async def cmd_shameraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            count = None
            if arg:
                parts = arg.strip().split()
                if parts and parts[-1].isdigit():
                    count = int(parts[-1])
                    if count < 1: count = 1
                    if count > 100: count = 100
            added = []
            for uid in targets:
                user_bot.shame_raid[uid] = count
                user_bot.shame_users.add(uid)
                display = "∞" if count is None else f"{count} times"
                added.append(f"{uid} ({display})")
            await safe_edit(event, f"😤 Shame raid started for {', '.join(added)}")

        @register_cmd("sshameraid")
        async def cmd_sshameraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                user_bot.shame_raid.clear()
                user_bot.shame_users.clear()
                return await safe_edit(event, "🛑 Shame raid stopped for all")
            removed = []
            for uid in targets:
                if uid in user_bot.shame_raid:
                    del user_bot.shame_raid[uid]
                    user_bot.shame_users.discard(uid)
                    removed.append(str(uid))
            if removed:
                await safe_edit(event, f"🛑 Removed: {', '.join(removed)}")
            else:
                await safe_edit(event, "⚠️ No active raid for these users")

        @register_cmd("dissraid", needs_reply=True)
        async def cmd_dissraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            count = None
            if arg:
                parts = arg.strip().split()
                if parts and parts[-1].isdigit():
                    count = int(parts[-1])
                    if count < 1: count = 1
                    if count > 100: count = 100
            added = []
            for uid in targets:
                user_bot.diss_raid[uid] = count
                user_bot.diss_users.add(uid)
                display = "∞" if count is None else f"{count} times"
                added.append(f"{uid} ({display})")
            await safe_edit(event, f"🎤 Diss raid started for {', '.join(added)}")

        @register_cmd("sdissraid")
        async def cmd_sdissraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                user_bot.diss_raid.clear()
                user_bot.diss_users.clear()
                return await safe_edit(event, "🛑 Diss raid stopped for all")
            removed = []
            for uid in targets:
                if uid in user_bot.diss_raid:
                    del user_bot.diss_raid[uid]
                    user_bot.diss_users.discard(uid)
                    removed.append(str(uid))
            if removed:
                await safe_edit(event, f"🛑 Removed: {', '.join(removed)}")
            else:
                await safe_edit(event, "⚠️ No active raid for these users")

        @register_cmd("devilraid", needs_reply=True)
        async def cmd_devilraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            count = None
            if arg:
                parts = arg.strip().split()
                if parts and parts[-1].isdigit():
                    count = int(parts[-1])
                    if count < 1: count = 1
                    if count > 100: count = 100
            added = []
            for uid in targets:
                user_bot.devil_raid[uid] = count
                user_bot.devil_users.add(uid)
                display = "∞" if count is None else f"{count} times"
                added.append(f"{uid} ({display})")
            await safe_edit(event, f"😈 Devil raid started for {', '.join(added)}")

        @register_cmd("sdevilraid")
        async def cmd_sdevilraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                user_bot.devil_raid.clear()
                user_bot.devil_users.clear()
                return await safe_edit(event, "🛑 Devil raid stopped for all")
            removed = []
            for uid in targets:
                if uid in user_bot.devil_raid:
                    del user_bot.devil_raid[uid]
                    user_bot.devil_users.discard(uid)
                    removed.append(str(uid))
            if removed:
                await safe_edit(event, f"🛑 Removed: {', '.join(removed)}")
            else:
                await safe_edit(event, "⚠️ No active raid for these users")

        @register_cmd("karmaraid", needs_reply=True)
        async def cmd_karmaraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            count = None
            if arg:
                parts = arg.strip().split()
                if parts and parts[-1].isdigit():
                    count = int(parts[-1])
                    if count < 1: count = 1
                    if count > 100: count = 100
            added = []
            for uid in targets:
                user_bot.karma_raid[uid] = count
                user_bot.karma_users.add(uid)
                display = "∞" if count is None else f"{count} times"
                added.append(f"{uid} ({display})")
            await safe_edit(event, f"☯️ Karma raid started for {', '.join(added)}")

        @register_cmd("skarmaraid")
        async def cmd_skarmaraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                user_bot.karma_raid.clear()
                user_bot.karma_users.clear()
                return await safe_edit(event, "🛑 Karma raid stopped for all")
            removed = []
            for uid in targets:
                if uid in user_bot.karma_raid:
                    del user_bot.karma_raid[uid]
                    user_bot.karma_users.discard(uid)
                    removed.append(str(uid))
            if removed:
                await safe_edit(event, f"🛑 Removed: {', '.join(removed)}")
            else:
                await safe_edit(event, "⚠️ No active raid for these users")

        @register_cmd("doomraid", needs_reply=True)
        async def cmd_doomraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                return
            count = None
            if arg:
                parts = arg.strip().split()
                if parts and parts[-1].isdigit():
                    count = int(parts[-1])
                    if count < 1: count = 1
                    if count > 100: count = 100
            added = []
            for uid in targets:
                user_bot.doom_raid[uid] = count
                user_bot.doom_users.add(uid)
                display = "∞" if count is None else f"{count} times"
                added.append(f"{uid} ({display})")
            await safe_edit(event, f"💀 Doom raid started for {', '.join(added)}")

        @register_cmd("sdoomraid")
        async def cmd_sdoomraid(event, arg):
            targets = await get_targets(event, arg)
            if not targets:
                user_bot.doom_raid.clear()
                user_bot.doom_users.clear()
                return await safe_edit(event, "🛑 Doom raid stopped for all")
            removed = []
            for uid in targets:
                if uid in user_bot.doom_raid:
                    del user_bot.doom_raid[uid]
                    user_bot.doom_users.discard(uid)
                    removed.append(str(uid))
            if removed:
                await safe_edit(event, f"🛑 Removed: {', '.join(removed)}")
            else:
                await safe_edit(event, "⚠️ No active raid for these users")

        # ─── PREMIUM RAID START/STOP ──────────────────────────────────
        premium_raid_tasks = {}
        premium_spam_tasks = {}

        for start_cmd, stop_cmd in [
            ("mr", "smr"), ("mr2", "smr2"), ("br", "sbr"), ("br2", "sbr2"),
            ("br3", "sbr3"), ("sqr", "ssqr"), ("sq2", "ssq2"), ("cr", "scr"),
            ("bar", "sbar"), ("gr", "sgr")
        ]:
            @register_cmd(start_cmd, needs_reply=True, premium=True)
            async def start_premium_raid(event, arg, cmd=start_cmd):
                targets = await get_targets(event, arg)
                if not targets:
                    return
                count = None
                if arg:
                    parts = arg.strip().split()
                    if parts and parts[-1].isdigit():
                        count = int(parts[-1])
                        if count < 1: count = 1
                        if count > 100: count = 100
                text_list = premium_raid_texts.get(cmd, [])
                if not text_list:
                    await safe_edit(event, f"⚠️ No texts for `{cmd}`. Using default.")
                    text_list = [f"🔥 Premium Raid {cmd}!"]
                chat = event.chat_id
                target_user = None
                reply_to = None
                if event.is_reply:
                    reply = await event.get_reply_message()
                    if reply:
                        reply_to = reply.id
                        target_user = reply.sender_id
                        if target_user and await is_protected(target_user, cmd):
                            await safe_edit(event, f"🚫 Target is protected from `{cmd}`.")
                            return
                if chat in user_bot.spray_tasks:
                    await safe_edit(event, "⚠️ Already a spray running in this chat.")
                    return
                key = f"{chat}_{cmd}"
                await safe_edit(event, f"⚔️ Premium Raid `{cmd}` started on target{' with reply' if reply_to else ''}{' (' + str(count) + ' msgs)' if count else ' (infinite)'}...")
                async def loop():
                    sent = 0
                    idx = 0
                    try:
                        while key in user_bot.spray_tasks:
                            if count is not None and sent >= count:
                                break
                            if target_user and sent % 10 == 0 and await is_protected(target_user, cmd):
                                await safe_send(chat, f"🛑 Target is now protected from `{cmd}`. Stopping.")
                                break
                            txt = text_list[idx % len(text_list)]
                            idx += 1
                            sent += 1
                            await safe_send(chat, txt, reply_to=reply_to)
                            if sent % 30 == 0:
                                await asyncio.sleep(3)
                            await asyncio.sleep(user_bot.SPRAY_DELAY)
                    except asyncio.CancelledError:
                        pass
                    finally:
                        user_bot.spray_tasks.pop(key, None)
                        if sent > 0:
                            await safe_send(chat, f"✅ Premium Raid `{cmd}` done: {sent} messages sent.")
                user_bot.spray_tasks[key] = asyncio.create_task(loop())
                await safe_edit(event, f"⚔️ Premium Raid `{cmd}` started.")

            @register_cmd(stop_cmd, premium=True)
            async def stop_premium_raid(event, arg, cmd=start_cmd):
                chat = event.chat_id
                key = f"{chat}_{cmd}"
                if key in user_bot.spray_tasks:
                    try:
                        user_bot.spray_tasks[key].cancel()
                    except:
                        pass
                    user_bot.spray_tasks.pop(key, None)
                    await safe_edit(event, f"🛑 Premium Raid `{cmd}` stopped.")
                else:
                    await safe_edit(event, f"⚠️ No active `{cmd}` raid in this chat.")

        for start_cmd, stop_cmd in [
            ("ms", "sms"), ("ms2", "sms2"), ("bs", "sbs"), ("bs2", "sbs2"),
            ("bs3", "sbs3"), ("sqs", "ssqs"), ("sqs2", "ssqs2"), ("cs", "scs"),
            ("bas", "sbas"), ("gs", "sgs")
        ]:
            @register_cmd(start_cmd, needs_reply=True, premium=True)
            async def start_premium_spam(event, arg, cmd=start_cmd):
                targets = await get_targets(event, arg)
                if not targets:
                    return
                count = None
                if arg:
                    parts = arg.strip().split()
                    if parts and parts[-1].isdigit():
                        count = int(parts[-1])
                        if count < 1: count = 1
                        if count > 100: count = 100
                text_list = premium_spam_texts.get(cmd, [])
                if not text_list:
                    await safe_edit(event, f"⚠️ No texts for `{cmd}`. Using default.")
                    text_list = [f"💣 Premium Spam {cmd}!"]
                chat = event.chat_id
                target_user = None
                reply_to = None
                if event.is_reply:
                    reply = await event.get_reply_message()
                    if reply:
                        reply_to = reply.id
                        target_user = reply.sender_id
                        if target_user and await is_protected(target_user, cmd):
                            await safe_edit(event, f"🚫 Target is protected from `{cmd}`.")
                            return
                key = f"{chat}_{cmd}"
                if key in user_bot.spray_tasks:
                    await safe_edit(event, "⚠️ Already a spam running in this chat.")
                    return
                await safe_edit(event, f"💣 Premium Spam `{cmd}` started on target{' with reply' if reply_to else ''}{' (' + str(count) + ' msgs)' if count else ' (infinite)'}...")
                async def loop():
                    sent = 0
                    idx = 0
                    try:
                        while key in user_bot.spray_tasks:
                            if count is not None and sent >= count:
                                break
                            if target_user and sent % 10 == 0 and await is_protected(target_user, cmd):
                                await safe_send(chat, f"🛑 Target is now protected from `{cmd}`. Stopping.")
                                break
                            txt = text_list[idx % len(text_list)]
                            idx += 1
                            sent += 1
                            await safe_send(chat, txt, reply_to=reply_to)
                            if sent % 30 == 0:
                                await asyncio.sleep(3)
                            await asyncio.sleep(user_bot.SPRAY_DELAY)
                    except asyncio.CancelledError:
                        pass
                    finally:
                        user_bot.spray_tasks.pop(key, None)
                        if sent > 0:
                            await safe_send(chat, f"✅ Premium Spam `{cmd}` done: {sent} messages sent.")
                user_bot.spray_tasks[key] = asyncio.create_task(loop())
                await safe_edit(event, f"💣 Premium Spam `{cmd}` started.")

            @register_cmd(stop_cmd, premium=True)
            async def stop_premium_spam(event, arg, cmd=start_cmd):
                chat = event.chat_id
                key = f"{chat}_{cmd}"
                if key in user_bot.spray_tasks:
                    try:
                        user_bot.spray_tasks[key].cancel()
                    except:
                        pass
                    user_bot.spray_tasks.pop(key, None)
                    await safe_edit(event, f"🛑 Premium Spam `{cmd}` stopped.")
                else:
                    await safe_edit(event, f"⚠️ No active `{cmd}` spam in this chat.")

        @register_cmd("addadmin", needs_reply=True)
        async def cmd_addadmin(event, arg):
            if event.sender_id not in OWNER_IDS:
                return
            targets = await get_targets(event, arg)
            if not targets:
                return
            added, already, skipped = [], [], []
            for uid in targets:
                if uid in OWNER_IDS:
                    skipped.append(str(uid)); continue
                if uid in user_bot.admins:
                    already.append(str(uid))
                else:
                    user_bot.admins.add(uid); added.append(str(uid))
            save_admins()
            msg = ""
            if added: msg += f"✅ Added: {', '.join(added)}\n"
            if already: msg += f"⚠️ Already: {', '.join(already)}\n"
            if skipped: msg += f"👑 Owner skipped: {', '.join(skipped)}"
            if not msg: msg = "❌ No changes"
            await safe_edit(event, msg)

        @register_cmd("deladmin", needs_reply=True)
        async def cmd_deladmin(event, arg):
            if event.sender_id not in OWNER_IDS:
                return
            targets = await get_targets(event, arg)
            if not targets:
                return
            removed, not_admin, skipped = [], [], []
            for uid in targets:
                if uid in OWNER_IDS:
                    skipped.append(str(uid)); continue
                if uid in user_bot.admins:
                    user_bot.admins.remove(uid); removed.append(str(uid))
                else:
                    not_admin.append(str(uid))
            save_admins()
            msg = ""
            if removed: msg += f"🗑️ Removed: {', '.join(removed)}\n"
            if not_admin: msg += f"⚠️ Not admin: {', '.join(not_admin)}\n"
            if skipped: msg += f"👑 Owner skipped: {', '.join(skipped)}"
            if not msg: msg = "❌ No changes"
            await safe_edit(event, msg)

        @register_cmd("admins")
        async def cmd_admins(event, _):
            admin_list = "\n".join(f"• `{a}`" for a in sorted(user_bot.admins)) if user_bot.admins else "⚠️ No extra admins"
            owner_list = "\n".join(f"👑 `{o}`" for o in sorted(OWNER_IDS))
            await safe_edit(event, f"👑 Owners:\n{owner_list}\n\n━━━━━━━━━━━━━━━\n👥 Admins:\n{admin_list}\n\nTotal Admins: {len(user_bot.admins)}")

        @register_cmd("ping")
        async def cmd_ping(event, _):
            t0 = time.perf_counter()
            try:
                if event.out:
                    msg = await event.edit("🏓 Pong...")
                else:
                    msg = await event.reply("🏓 Pong...")
            except:
                msg = None
            t1 = time.perf_counter()
            ms = round((t1 - t0) * 1000)
            try:
                if msg:
                    await msg.edit(f"🏓 Pong → `{ms} ms`")
                else:
                    await event.reply(f"🏓 Pong → `{ms} ms`")
            except:
                pass

        @register_cmd("status")
        async def cmd_status(event, _):
            uptime = int(time.time() - user_bot.START_TIME) if user_bot.START_TIME else 0
            await safe_edit(event, f"✅ Userbot Status\n━━━━━━━━━━━━━━━\n⏱️ Uptime: {uptime}s\n👑 Admins: {len(user_bot.admins)}\n⚙️ Mode: Operational")

        @register_cmd("dice")
        async def cmd_dice(event, _):
            await safe_edit(event, f"🎲 Dice Roll\n━━━━━━━━━━━━━━━\n👉 {random.randint(1, 6)}")

        @register_cmd("flip")
        async def cmd_flip(event, _):
            await safe_edit(event, f"🪙 Coin Flip\n━━━━━━━━━━━━━━━\n👉 {random.choice(['Heads', 'Tails'])}")

        @register_cmd("truth")
        async def cmd_truth(event, _):
            if not truth_texts:
                await safe_edit(event, "❌ No truths available.")
                return
            await safe_edit(event, f"🤥 **TRUTH**\n━━━━━━━━━━━━━━━\n{random.choice(truth_texts)}")

        @register_cmd("dare")
        async def cmd_dare(event, _):
            if not dare_texts:
                await safe_edit(event, "❌ No dares available.")
                return
            await safe_edit(event, f"😈 **DARE**\n━━━━━━━━━━━━━━━\n{random.choice(dare_texts)}")

        @register_cmd("situation")
        async def cmd_situation(event, _):
            if not situation_texts:
                await safe_edit(event, "❌ No situations available.")
                return
            await safe_edit(event, f"🧐 **SITUATION**\n━━━━━━━━━━━━━━━\n{random.choice(situation_texts)}")

        @register_cmd("joke")
        async def cmd_joke(event, _):
            if not joke_list:
                await safe_edit(event, "❌ No jokes available.")
                return
            await safe_edit(event, f"😂 **JOKE**\n━━━━━━━━━━━━━━━\n{random.choice(joke_list)}")

        @register_cmd("fact")
        async def cmd_fact(event, _):
            if not fact_list:
                await safe_edit(event, "❌ No facts available.")
                return
            await safe_edit(event, f"🧠 **FACT**\n━━━━━━━━━━━━━━━\n{random.choice(fact_list)}")

        @register_cmd("compliment")
        async def cmd_compliment(event, _):
            if not compliment_list:
                await safe_edit(event, "❌ No compliments available.")
                return
            await safe_edit(event, f"🌟 **COMPLIMENT**\n━━━━━━━━━━━━━━━\n{random.choice(compliment_list)}")

        @register_cmd("quote")
        async def cmd_quote(event, _):
            if not quote_list:
                await safe_edit(event, "❌ No quotes available.")
                return
            await safe_edit(event, f"💭 **QUOTE**\n━━━━━━━━━━━━━━━\n{random.choice(quote_list)}")

        # ─── SEND & TAG ──────────────────────────────────────────────────────────
        @register_cmd("send")
        async def cmd_send(event, arg):
            if not is_admin(event.sender_id):
                return
            if not arg:
                return
            parts = arg.split(maxsplit=1)
            if len(parts) < 2:
                return
            target_part = parts[0]
            msg = parts[1]
            try:
                entity = await user_bot.get_entity(target_part)
                await safe_send(entity, msg)
                await safe_edit(event, f"✅ Message sent to {target_part}")
            except Exception as e:
                await safe_edit(event, f"❌ Failed: {e}")

        @register_cmd("tag")
        async def cmd_tag(event, arg):
            if not is_admin(event.sender_id):
                return
            if not arg:
                return
            import re
            tokens = arg.split()
            pairs = []
            current_target = None
            current_msg_parts = []
            for token in tokens:
                if token.startswith('@') or token.isdigit():
                    if current_target is not None:
                        if current_msg_parts:
                            pairs.append((current_target, ' '.join(current_msg_parts)))
                    current_target = token
                    current_msg_parts = []
                else:
                    current_msg_parts.append(token)
            if current_target is not None and current_msg_parts:
                pairs.append((current_target, ' '.join(current_msg_parts)))
            if not pairs:
                return
            sent = 0
            failed = []
            for target_str, message in pairs:
                try:
                    entity = await user_bot.get_entity(target_str)
                    await safe_send(event.chat_id, f"[{target_str}](tg://user?id={entity.id}) {message}")
                    await asyncio.sleep(0.5)
                    sent += 1
                except Exception as e:
                    failed.append(f"{target_str}: {e}")
            response = f"✅ Tagged {sent} users."
            if failed:
                response += f"\n❌ Failed: {', '.join(failed)}"
            await safe_edit(event, response)

        @register_cmd("copy")
        async def cmd_copy(event, args):
            if not is_admin(event.sender_id):
                return
            reply = await event.get_reply_message()
            target = None
            if reply:
                try:
                    if reply.sender_id:
                        target = await user_bot.get_entity(reply.sender_id)
                except:
                    pass
                if not target and getattr(reply, "fwd_from", None):
                    try:
                        fid = reply.fwd_from.from_id
                        if fid:
                            target = await user_bot.get_entity(fid)
                    except:
                        pass
            if not target and args:
                try:
                    target = await user_bot.get_entity(args.strip())
                except:
                    pass
            if not target:
                return
            me2 = await user_bot.get_me()
            if target.id == me2.id:
                return
            if user_bot.CLONE_ACTIVE and user_bot.LAST_CLONE_ID == target.id:
                return
            await safe_edit(event, "⚡ Clone Init...")
            if not user_bot.CLONE_ACTIVE:
                try:
                    full = await user_bot(functions.users.GetFullUserRequest(me2.id))
                    user_bot.CLONE_DATA["name"] = me2.first_name
                    user_bot.CLONE_DATA["last"] = me2.last_name
                    user_bot.CLONE_DATA["bio"] = full.full_user.about
                    user_bot.CLONE_DATA["username"] = me2.username
                    dp = await user_bot.download_profile_photo("me", file=bytes, download_big=True)
                    if dp:
                        bio = BytesIO(dp)
                        bio.name = "orig.jpg"
                        user_bot.CLONE_DATA["photo_bytes"] = bio
                    user_bot.CLONE_ACTIVE = True
                except:
                    pass
            try:
                await safe_edit(event, "⚡ Cloning Name...")
                await user_bot(functions.account.UpdateProfileRequest(first_name=target.first_name or "", last_name=target.last_name or ""))
                await safe_edit(event, "⚡ Cloning Bio...")
                tfull = await user_bot(functions.users.GetFullUserRequest(target.id))
                bio_text = (tfull.full_user.about or "")[:70]
                await user_bot(functions.account.UpdateProfileRequest(about=""))
                await asyncio.sleep(0.7)
                await user_bot(functions.account.UpdateProfileRequest(about=bio_text))
                await safe_edit(event, "⚡ Cloning PFP...")
                file = await user_bot.download_profile_photo(target, file=bytes, download_big=True)
                if file:
                    bio = BytesIO(file)
                    bio.name = "clone.jpg"
                    up = await user_bot.upload_file(bio)
                    cur = await user_bot.get_profile_photos("me", limit=1)
                    if cur:
                        await user_bot(functions.photos.DeletePhotosRequest(id=[cur[0]]))
                    await user_bot(functions.photos.UploadProfilePhotoRequest(file=up))
                user_bot.LAST_CLONE_ID = target.id
                await safe_edit(event, "✅ Clone Complete")
            except Exception as e:
                await safe_edit(event, f"❌ Clone error: {e}")

        @register_cmd("normal")
        async def cmd_normal(event, _):
            if not is_admin(event.sender_id):
                return
            if not user_bot.CLONE_ACTIVE:
                return
            try:
                await safe_edit(event, "⚡ Restoring...")
                await user_bot(functions.account.UpdateProfileRequest(first_name=user_bot.CLONE_DATA.get("name") or "", last_name=user_bot.CLONE_DATA.get("last") or ""))
                await user_bot(functions.account.UpdateProfileRequest(about=""))
                await asyncio.sleep(0.7)
                await user_bot(functions.account.UpdateProfileRequest(about=user_bot.CLONE_DATA.get("bio") or ""))
                cur = await user_bot.get_profile_photos("me", limit=1)
                if cur:
                    await user_bot(functions.photos.DeletePhotosRequest(id=[cur[0]]))
                if user_bot.CLONE_DATA.get("photo_bytes"):
                    bio = user_bot.CLONE_DATA["photo_bytes"]
                    bio.name = "restore.jpg"
                    up = await user_bot.upload_file(bio)
                    await user_bot(functions.photos.UploadProfilePhotoRequest(file=up))
                user_bot.CLONE_ACTIVE = False
                user_bot.LAST_CLONE_ID = None
                user_bot.CLONE_DATA.clear()
                await safe_edit(event, "✅ Original restored")
            except Exception as e:
                await safe_edit(event, f"❌ Restore error: {e}")

        @register_cmd("banner", needs_reply=True)
        async def cmd_banner(event, _):
            if not is_admin(event.sender_id):
                return
            reply = await event.get_reply_message()
            if not reply or not reply.media:
                return
            await safe_edit(event, "⚡ Processing banner...")
            try:
                try:
                    saved = await reply.forward_to("me")
                except:
                    file = await reply.download_media(file=bytes)
                    if not file:
                        return
                    bio = BytesIO(file)
                    bio.name = "banner"
                    saved = await user_bot.send_file("me", bio)
                user_bot.menu_banner_msg = (saved.chat_id, saved.id)
                save_banner()
                await safe_edit(event, f"🖼️ Banner set (ID: {saved.id})")
            except Exception as e:
                await safe_edit(event, f"❌ Error: {e}")

        @register_cmd("rembanner")
        async def cmd_rembanner(event, _):
            if not is_admin(event.sender_id):
                return
            if not user_bot.menu_banner_msg:
                return
            try:
                chat_id2, msg_id = user_bot.menu_banner_msg
                try:
                    await user_bot.delete_messages(chat_id2, [msg_id])
                except:
                    pass
                user_bot.menu_banner_msg = None
                save_banner()
                await safe_edit(event, "🗑️ Banner removed")
            except Exception as e:
                await safe_edit(event, f"❌ Error: {e}")

        @register_cmd("nc")
        async def cmd_nc(event, arg):
            if not is_admin(event.sender_id):
                return
            if not arg:
                return
            parts = arg.strip().split(maxsplit=2)
            if len(parts) < 2:
                return
            action = parts[0].lower()
            if action == "stop":
                user_bot.NC_STATE["active"] = False
                if user_bot.NC_STATE.get("task") and not user_bot.NC_STATE["task"].done():
                    user_bot.NC_STATE["task"].cancel()
                    try:
                        await user_bot.NC_STATE["task"]
                    except asyncio.CancelledError:
                        pass
                user_bot.NC_STATE["task"] = None
                await safe_edit(event, "🛑 Name Changer stopped.")
                return
            elif action == "set":
                if len(parts) < 3:
                    return
                lang = parts[1].lower()
                text = parts[2]
                allowed = {"hindi","urdu","bengali","bihari","english","emoji"}
                if lang not in allowed:
                    return
                if user_bot.NC_STATE.get("task") and not user_bot.NC_STATE["task"].done():
                    user_bot.NC_STATE["task"].cancel()
                    try:
                        await user_bot.NC_STATE["task"]
                    except asyncio.CancelledError:
                        pass
                user_bot.NC_STATE["active"] = True
                user_bot.NC_STATE["lang"] = lang
                user_bot.NC_STATE["text"] = text
                user_bot.NC_STATE["chat_id"] = event.chat_id
                task = asyncio.create_task(nc_loop(event.chat_id, lang, text))
                user_bot.NC_STATE["task"] = task
                await safe_edit(event, f"✅ Name Changer started with language `{lang}` and text `{text}`.")
            else:
                await safe_edit(event, "❌ Invalid action. Use `set` or `stop`.")

        @register_cmd("deathgod")
        async def cmd_deathgod(event, arg):
            chat = event.chat_id
            count = None
            if arg and arg.strip().isdigit():
                count = int(arg.strip())
                if count < 1: count = 1
                if count > 1000: count = 1000
            reply_to = None
            target_user = None
            if event.is_reply:
                reply = await event.get_reply_message()
                if reply:
                    reply_to = reply.id
                    target_user = reply.sender_id
                    if target_user and await is_protected(target_user, "deathgod"):
                        await safe_edit(event, "🚫 This user is protected from Deathgod.")
                        return
            if chat in user_bot.spray_tasks and not user_bot.spray_tasks[chat].done():
                return
            await safe_edit(event, f"☠️ Deathgod started{' with reply' if reply_to else ''}{' (' + str(count) + ' msgs)' if count else ' (infinite)'}...")
            async def loop():
                sent = 0
                try:
                    while chat in user_bot.spray_tasks:
                        if count is not None and sent >= count:
                            break
                        if target_user and sent % 10 == 0 and await is_protected(target_user, "deathgod"):
                            await safe_send(chat, "🛑 Target is now protected. Stopping Deathgod.")
                            break
                        txt = random.choice(deathgod_replies) if deathgod_replies else "☠️ Deathgod!"
                        sent += 1
                        await safe_send(chat, txt, reply_to=reply_to)
                        if sent % 30 == 0:
                            await asyncio.sleep(3)
                        await asyncio.sleep(user_bot.SPRAY_DELAY)
                except asyncio.CancelledError:
                    pass
                finally:
                    user_bot.spray_tasks.pop(chat, None)
                    if sent > 0:
                        await safe_send(chat, f"☠️ Deathgod done: {sent} messages sent.")
            user_bot.spray_tasks[chat] = asyncio.create_task(loop())
            await safe_edit(event, f"☠️ Deathgod started{' with reply' if reply_to else ''}{' (' + str(count) + ' msgs)' if count else ' (infinite)'}")

        @register_cmd("sdeathgod")
        async def cmd_sdeathgod(event, _):
            chat = event.chat_id
            if chat in user_bot.spray_tasks:
                try:
                    user_bot.spray_tasks[chat].cancel()
                except:
                    pass
                user_bot.spray_tasks.pop(chat, None)
                await safe_edit(event, "🛑 Deathgod stopped.")
            else:
                await safe_edit(event, "⚠️ No active Deathgod spray in this chat.")

        # ─── DM SHIELD COMMANDS (premium) ─────────────────────────────────────
        @register_cmd("dmshield", premium=True)
        async def cmd_dmshield(event, arg):
            if not is_admin(event.sender_id):
                return
            arg = arg.strip().lower()
            if not arg:
                status = "🟢 ON" if user_bot.dm_shield_enabled else "🔴 OFF"
                await safe_edit(event, f"🛡️ DM Shield Status: {status}")
                return
            if arg in ("on", "off"):
                user_bot.dm_shield_enabled = (arg == "on")
                await safe_edit(event, f"✅ DM Shield {'enabled' if user_bot.dm_shield_enabled else 'disabled'}")
            else:
                await safe_edit(event, "❌ Usage: .dmshield on/off")

        @register_cmd("approve", premium=True)
        async def cmd_approve(event, arg):
            if not is_admin(event.sender_id):
                return
            targets = await get_targets(event, arg)
            if not targets:
                return
            added = []
            for uid in targets:
                user_bot.dm_approved.add(uid)
                added.append(str(uid))
            await safe_edit(event, f"✅ Approved: {', '.join(added)}")

        @register_cmd("unapprove", premium=True)
        async def cmd_unapprove(event, arg):
            if not is_admin(event.sender_id):
                return
            targets = await get_targets(event, arg)
            if not targets:
                return
            removed = []
            for uid in targets:
                if uid in user_bot.dm_approved:
                    user_bot.dm_approved.discard(uid)
                    removed.append(str(uid))
            await safe_edit(event, f"🛑 Removed approval: {', '.join(removed)}")

        @register_cmd("block", premium=True, needs_reply=True)
        async def cmd_block(event, arg):
            if not is_admin(event.sender_id):
                return
            targets = await get_targets(event, arg)
            if not targets:
                return
            for uid in targets:
                await block_user(me.id, uid)
            await safe_edit(event, f"✅ Blocked: {', '.join(str(uid) for uid in targets)}")

        @register_cmd("unblock", premium=True, needs_reply=True)
        async def cmd_unblock(event, arg):
            if not is_admin(event.sender_id):
                return
            targets = await get_targets(event, arg)
            if not targets:
                return
            for uid in targets:
                await unblock_user(me.id, uid)
            await safe_edit(event, f"✅ Unblocked: {', '.join(str(uid) for uid in targets)}")

        @register_cmd("blockedlist", premium=True)
        async def cmd_blockedlist(event, _):
            if not is_admin(event.sender_id):
                return
            if not user_bot.dm_blocked:
                await safe_edit(event, "📭 No blocked users.")
                return
            msg = "🚫 Blocked Users:\n"
            for uid in user_bot.dm_blocked:
                try:
                    u = await user_bot.get_entity(uid)
                    name = f"@{u.username}" if u.username else u.first_name or str(uid)
                    msg += f"• {uid} → {name}\n"
                except:
                    msg += f"• {uid}\n"
            await safe_edit(event, msg)

        # ─── AUTO-REPLY (works for all incoming private messages) ──────────
        @user_bot.on(events.NewMessage(incoming=True))
        async def auto_reply_handler(event):
            if event.out:
                return
            if not event.is_private:
                return
            if event.sender_id in OWNER_IDS:
                return
            if not user_bot.auto_reply:
                return
            await safe_send(event.chat_id, user_bot.auto_reply, reply_to=event.id)

        # ─── FILTERS ──────────────────────────────────────────────────────────
        @register_cmd("addfilter")
        async def cmd_addfilter(event, arg):
            if not is_admin(event.sender_id):
                return
            if not arg:
                return
            word = arg.strip().lower()
            if word in user_bot.filters:
                await safe_edit(event, f"⚠️ Filter '{word}' already exists.")
                return
            user_bot.filters.append(word)
            save_filters()
            await safe_edit(event, f"✅ Filter added: `{word}`")

        @register_cmd("delfilter")
        async def cmd_delfilter(event, arg):
            if not is_admin(event.sender_id):
                return
            if not arg:
                return
            word = arg.strip().lower()
            if word not in user_bot.filters:
                await safe_edit(event, f"⚠️ Filter '{word}' not found.")
                return
            user_bot.filters.remove(word)
            save_filters()
            await safe_edit(event, f"🗑️ Filter removed: `{word}`")

        @register_cmd("listfilters")
        async def cmd_listfilters(event, _):
            if not is_admin(event.sender_id):
                return
            if not user_bot.filters:
                await safe_edit(event, "📭 No filters set.")
                return
            msg = "📋 Filters:\n" + "\n".join(f"• `{w}`" for w in user_bot.filters)
            await safe_edit(event, msg)

        @register_cmd("setautoreply")
        async def cmd_setautoreply(event, arg):
            if not is_admin(event.sender_id):
                return
            if not arg:
                return
            user_bot.auto_reply = arg.strip()
            save_autoreply(user_bot.auto_reply)
            await safe_edit(event, f"✅ Auto-reply set:\n{user_bot.auto_reply}")

        @register_cmd("delautoreply")
        async def cmd_delautoreply(event, _):
            if not is_admin(event.sender_id):
                return
            user_bot.auto_reply = None
            save_autoreply("")
            await safe_edit(event, "🗑️ Auto-reply removed.")

        # ─── GODPROTECTION ──────────────────────────────────────────────────────
        @register_cmd("godprotection")
        async def cmd_godprotection(event, arg):
            if not is_admin(event.sender_id):
                return
            arg = arg.strip().lower()
            cid = event.chat_id
            uid = me.id
            if not arg:
                try:
                    async with db_pool.acquire() as conn:
                        row = await conn.fetchrow("SELECT * FROM god_protection WHERE uid = $1 AND chat_id = $2", uid, cid)
                    if row:
                        status = "✅ ON" if row["enabled"] else "❌ OFF"
                        await safe_edit(event,
                            f"🛡️ **God Protection**\nChat: `{cid}`\nStatus: {status}\n"
                            f"Action: `{row['action']}`\nAuto-mute: `{row['auto_mute']}` ({row['mute_min']}m)\n"
                            f"Threshold: {row['threshold_mentions']} mentions in {row['threshold_sec']}s\n"
                            f"`.godprotection on/off` to toggle")
                    else:
                        await safe_edit(event, "🛡️ **God Protection** — No config yet.\n`.godprotection on` to enable.")
                except Exception as e:
                    await safe_edit(event, f"❌ DB error: {e}")
                return
            if arg == "on":
                try:
                    async with db_pool.acquire() as conn:
                        await conn.execute(
                            """INSERT INTO god_protection (uid, chat_id, action, auto_mute, mute_min, threshold_mentions, threshold_sec, enabled)
                               VALUES ($1, $2, 'delete', TRUE, 5, 5, 10, TRUE)
                               ON CONFLICT (uid, chat_id) DO UPDATE SET enabled = TRUE""",
                            uid, cid)
                    user_bot.god_protection.add(cid)
                    await safe_edit(event, "🛡️ **God Protection: ENABLED** ✅")
                except Exception as e:
                    await safe_edit(event, f"❌ Error: {e}")
            elif arg == "off":
                try:
                    async with db_pool.acquire() as conn:
                        await conn.execute("UPDATE god_protection SET enabled = FALSE WHERE uid = $1 AND chat_id = $2", uid, cid)
                    user_bot.god_protection.discard(cid)
                    await safe_edit(event, "🛡️ **God Protection: DISABLED** ❌")
                except Exception as e:
                    await safe_edit(event, f"❌ Error: {e}")
            else:
                await safe_edit(event, "❌ Usage: `.godprotection on/off`")

        @register_cmd("setgp")
        async def cmd_setgp(event, arg):
            parts = arg.strip().split()
            if not parts:
                await safe_edit(event, "❌ Usage: `.setgp action delete/mute/ban/kick` | `.setgp automute on/off` | `.setgp threshold <mentions> <sec>`")
                return
            cid = event.chat_id
            uid = me.id
            sub = parts[0].lower()
            try:
                async with db_pool.acquire() as conn:
                    if sub == "action" and len(parts) >= 2 and parts[1].lower() in ("delete","mute","ban","kick"):
                        await conn.execute("UPDATE god_protection SET action = $1 WHERE uid = $2 AND chat_id = $3", parts[1].lower(), uid, cid)
                        await safe_edit(event, f"✅ GP action set to `{parts[1].lower()}`")
                    elif sub == "automute" and len(parts) >= 2:
                        val = parts[1].lower() == "on"
                        await conn.execute("UPDATE god_protection SET auto_mute = $1 WHERE uid = $2 AND chat_id = $3", val, uid, cid)
                        await safe_edit(event, f"✅ GP auto-mute set to `{val}`")
                    elif sub == "threshold" and len(parts) >= 3:
                        try:
                            mentions, seconds = int(parts[1]), int(parts[2])
                            await conn.execute("UPDATE god_protection SET threshold_mentions = $1, threshold_sec = $2 WHERE uid = $3 AND chat_id = $4", mentions, seconds, uid, cid)
                            await safe_edit(event, f"✅ GP threshold: {mentions} mentions / {seconds}s")
                        except ValueError:
                            await safe_edit(event, "❌ Provide numbers: `.setgp threshold 5 10`")
                    elif sub == "mutemin" and len(parts) >= 2:
                        try:
                            mins = int(parts[1])
                            await conn.execute("UPDATE god_protection SET mute_min = $1 WHERE uid = $2 AND chat_id = $3", mins, uid, cid)
                            await safe_edit(event, f"✅ GP mute duration set to {mins} min")
                        except ValueError:
                            await safe_edit(event, "❌ Provide number: `.setgp mutemin 5`")
                    else:
                        await safe_edit(event, "❌ Invalid sub-command.")
            except Exception as e:
                await safe_edit(event, f"❌ DB error: {e}")

        # ─── GOD PROTECTION AUTO HANDLER ─────────────────────────────
        async def _gp_take_action(cid, uid, action, auto_mute=False, mute_min=5):
            try:
                if action == "delete":
                    pass
                elif action == "mute" or (auto_mute and action == "delete"):
                    until = datetime.now() + timedelta(minutes=mute_min) if mute_min > 0 else None
                    rights = ChatBannedRights(until_date=until, send_messages=True, send_media=True,
                        send_stickers=True, send_gifs=True, send_games=True, send_inline=True, send_polls=True)
                    await user_bot(EditBannedRequest(cid, uid, rights))
                elif action == "kick":
                    rights = ChatBannedRights(until_date=datetime.now() + timedelta(seconds=30), view_messages=True)
                    await user_bot(EditBannedRequest(cid, uid, rights))
                    await asyncio.sleep(1)
                    rights2 = ChatBannedRights(until_date=None, view_messages=False)
                    await user_bot(EditBannedRequest(cid, uid, rights2))
                elif action == "ban":
                    rights = ChatBannedRights(until_date=None, view_messages=True, send_messages=True,
                        send_media=True, send_stickers=True, send_gifs=True, send_games=True, send_inline=True, send_polls=True)
                    await user_bot(EditBannedRequest(cid, uid, rights))
            except Exception as e:
                print(f"GP action error on {uid} in {cid}: {e}")

        @user_bot.on(events.NewMessage(incoming=True))
        async def god_protection_auto_handler(event):
            if not event.is_group:
                return
            cid = event.chat_id
            if cid not in user_bot.god_protection:
                return
            if event.sender_id in (me.id, 777000):
                return
            if not event.text:
                return
            uid = me.id
            try:
                async with db_pool.acquire() as conn:
                    row = await conn.fetchrow("SELECT * FROM god_protection WHERE uid = $1 AND chat_id = $2 AND enabled = TRUE", uid, cid)
                if not row:
                    user_bot.god_protection.discard(cid)
                    return
            except:
                return
            action = row["action"]
            auto_mute = row["auto_mute"]
            mute_min = row["mute_min"]
            thresh_mentions = row["threshold_mentions"]
            thresh_sec = row["threshold_sec"]
            sid = event.sender_id
            now = time.time()

            ABUSIVE_WORDS = set()  # empty

            mentions = re.findall(r'@\w+|@\d+', event.text)
            if mentions:
                if sid not in user_bot.gp_mentions:
                    user_bot.gp_mentions[sid] = []
                user_bot.gp_mentions[sid].append(now)
                user_bot.gp_mentions[sid] = [t for t in user_bot.gp_mentions[sid] if now - t < thresh_sec]
                if len(user_bot.gp_mentions[sid]) >= thresh_mentions:
                    try:
                        await event.delete()
                    except:
                        pass
                    await _gp_take_action(cid, sid, action, auto_mute, mute_min)
                    await safe_send(cid, f"🛡️ **GP:** Mass mention detected. Action taken on `{sid}`.")
                    user_bot.gp_mentions[sid] = []

            if sid not in user_bot.gp_duplicate:
                user_bot.gp_duplicate[sid] = []
            user_bot.gp_duplicate[sid].append((event.text.lower().strip(), now))
            user_bot.gp_duplicate[sid] = [(t, ts) for t, ts in user_bot.gp_duplicate[sid] if now - ts < 30]
            texts_in_window = [t for t,_ in user_bot.gp_duplicate[sid]]
            if len(texts_in_window) >= 3 and len(set(texts_in_window)) <= 1:
                try:
                    await event.delete()
                except:
                    pass
                await _gp_take_action(cid, sid, "delete" if action != "delete" else action, auto_mute, mute_min)
                user_bot.gp_duplicate[sid] = []

            if sid not in user_bot.gp_flood:
                user_bot.gp_flood[sid] = []
            user_bot.gp_flood[sid].append(now)
            user_bot.gp_flood[sid] = [t for t in user_bot.gp_flood[sid] if now - t < 5]
            if len(user_bot.gp_flood[sid]) >= 5:
                try:
                    await event.delete()
                except:
                    pass
                await _gp_take_action(cid, sid, "mute" if action == "delete" else action, auto_mute, mute_min)
                await safe_send(cid, f"🛡️ **GP:** Flood detected. Muted `{sid}`.")
                user_bot.gp_flood[sid] = []

        # ─── DM SHIELD INCOMING HANDLER ──────────────────────────────────────
        @user_bot.on(events.NewMessage(incoming=True))
        async def dm_shield_handler(event):
            if event.out or not event.is_private:
                return
            if not user_bot.dm_shield_enabled:
                return
            sender = event.sender_id
            if sender == me.id or sender in OWNER_IDS:
                return
            if sender in user_bot.dm_approved:
                return
            if await is_blocked(me.id, sender):
                return
            warns = await get_warnings(me.id, sender)
            if warns >= 3:
                await block_user(me.id, sender)
                await safe_send(sender, "🚫 You have been blocked due to excessive messages.")
                return
            new_warns = await add_warning(me.id, sender)
            left = 3 - new_warns
            if left <= 0:
                await block_user(me.id, sender)
                await safe_send(sender, "🚫 You have been blocked.")
            else:
                await safe_send(sender, f"⚠️ **Warning {new_warns}/3**\nYou are not approved to DM this user. Please request approval.\nYou have {left} warning(s) left before being blocked.")

        # ─── ID ──────────────────────────────────────────────────────────────────
        @register_cmd("id")
        async def cmd_id(event, arg):
            chat = event.chat_id
            sender = event.sender_id
            reply_user = None
            if event.is_reply:
                reply = await event.get_reply_message()
                if reply and reply.sender_id:
                    reply_user = reply.sender_id
            msg = f"🆔 **Your ID:** `{sender}`\n"
            msg += f"💬 **Chat ID:** `{chat}`\n"
            if reply_user:
                msg += f"↩️ **Replied User ID:** `{reply_user}`\n"
            await safe_edit(event, msg)

        # ─── CLEARME ────────────────────────────────────────────────────────────
        @register_cmd("clearme")
        async def cmd_clearme(event, arg):
            cid = event.chat_id
            deleted = 0
            try:
                async for msg in user_bot.iter_messages(cid, from_user="me"):
                    try:
                        await user_bot.delete_messages(cid, msg.id, revoke=True)
                        deleted += 1
                        await asyncio.sleep(0.05)
                    except:
                        pass
                await safe_edit(event, f"✅ Deleted {deleted} of your messages.")
            except Exception as e:
                await safe_edit(event, f"❌ Error: {e}")

        # ─── DLTALL ─────────────────────────────────────────────────────────────
        @register_cmd("dltall")
        async def cmd_dltall(event, arg):
            if not event.is_reply:
                await safe_edit(event, "❌ Reply to a message to delete all from there onwards.")
                return
            try:
                r = await event.get_reply_message()
                cid = event.chat_id
                deleted = 0
                async for msg in user_bot.iter_messages(cid, offset_id=r.id, reverse=True):
                    try:
                        await user_bot.delete_messages(cid, msg.id, revoke=True)
                        deleted += 1
                        await asyncio.sleep(0.05)
                    except:
                        pass
                await safe_edit(event, f"✅ Deleted {deleted} messages from that point.")
            except Exception as e:
                await safe_edit(event, f"❌ Error: {e}")

        # ─── SANGMATA ─────────────────────────────────────────────────────────
        @register_cmd("sangmata")
        async def cmd_sangmata(event, arg):
            target = None
            if event.is_reply:
                r = await event.get_reply_message()
                if r and r.sender_id:
                    target = r.sender_id
            elif arg:
                try:
                    ent = await user_bot.get_entity(arg)
                    target = ent.id
                except:
                    pass
            if not target:
                return await safe_edit(event, "❌ Please reply to a user or mention one.")
            history = load_sangmata(target)
            if history:
                try:
                    u = await user_bot.get_entity(target)
                    name = u.first_name or "User"
                except:
                    name = str(target)
                msg = (
                    "<pre>"
                    "❀═══⟦ HISTORY TRACKER ⟧═══❀\n"
                    f"✧➤ Target: {name}\n"
                    f"✧➤ User ID: {target}\n"
                    f"✧➤ Type: Name & Username History\n"
                    "❀═════════════════════════❀\n\n"
                )
                for entry in history[-20:]:
                    time_str = entry.get('time', 'Unknown')
                    old_name = entry.get('old_name', 'N/A')
                    new_name = entry.get('new_name', 'N/A')
                    old_username = entry.get('old_username', 'N/A')
                    new_username = entry.get('new_username', 'N/A')
                    msg += f"🕒 {time_str}\n"
                    msg += f"📛 {old_name} → {new_name}\n"
                    msg += f"🔗 {old_username} → {new_username}\n\n"
                msg += "</pre>"
                await safe_edit(event, msg)
                return
            status_msg = await safe_edit(event, "<pre>❀ Fetching History From SangMata... ❀</pre>")
            bot_username = "SangMata_beta_bot"
            try:
                await user_bot.send_message(bot_username, str(target))
            except Exception as e:
                await status_msg.edit(f"<pre>❀ ERROR: {str(e)} ❀</pre>")
                return
            combined_response = ""
            for _ in range(12):
                await asyncio.sleep(0.9)
                async for msg in user_bot.iter_messages(bot_username, limit=3):
                    if msg.text and str(target) not in msg.text:
                        text_lower = msg.text.lower()
                        if "history" in text_lower or "no records" in text_lower or "name" in text_lower or "username" in text_lower:
                            combined_response = msg.text
                            break
                if combined_response:
                    break
            await user_bot.read_chat_history(bot_username)
            if not combined_response:
                await status_msg.edit("<pre>❀ ERROR: SangMata responded but code missed it! Try again. ❀</pre>")
                return
            if "No records found" in combined_response or "doesn't have any record" in combined_response:
                await status_msg.edit("<pre>❀ INFO: No history records found for this user! ❀</pre>")
                return
            try:
                u = await user_bot.get_entity(target)
                name = u.first_name or "User"
            except:
                name = str(target)
            output_box = (
                "<pre>"
                "❀═══⟦ HISTORY TRACKER ⟧═══❀\n"
                f"✧➤ Target: {name}\n"
                f"✧➤ User ID: {target}\n"
                f"✧➤ Type: Name History\n"
                "❀═════════════════════════❀\n\n"
                f"{combined_response}"
                "</pre>"
            )
            await status_msg.edit(text=output_box)

        # ─── DISPATCHER ──────────────────────────────────────────────────────
        @user_bot.on(events.NewMessage)
        async def dispatcher(event):
            if await get_freeze(chat_id):
                return
            text = event.raw_text
            if not text:
                return
            if text.startswith("."):
                prefix = "."
                body = text[1:].strip()
            elif text.startswith("!") and event.sender_id in OWNER_IDS:
                prefix = "!"
                body = text[1:].strip()
            else:
                return
            if not body:
                return
            parts = body.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""
            cmd_data = commands.get(cmd)
            if not cmd_data:
                return
            sender = event.sender_id
            if not sender:
                return
            if prefix == "!":
                if sender not in OWNER_IDS:
                    return
            else:
                if sender not in OWNER_IDS and sender not in user_bot.admins:
                    return
                if cmd in owner_only_commands and sender not in OWNER_IDS:
                    return
            if cmd_data.get("premium", False):
                if not await is_premium_user(sender):
                    await safe_edit(event, "❌ This command is premium only. Buy premium with `/buy` in main bot.")
                    return
            if cmd_data.get("needs_reply") and not event.is_reply and not arg:
                return
            if cmd_data.get("group_only"):
                try:
                    if not event.is_group:
                        return
                except:
                    return
            try:
                await cmd_data["func"](event, arg)
            except FloodWaitError as fw:
                await asyncio.sleep(fw.seconds + 1)
            except Exception:
                pass

        # ─── AUTO HANDLER ──────────────────────────────────────────────────
        @user_bot.on(events.NewMessage)
        async def auto_handler(event):
            if await get_freeze(chat_id):   # chat_id comes from outer scope (the user's ID)
                return
            msg_id = event.id
            if msg_id in user_bot.filter_reply_ids:
                user_bot.filter_reply_ids.discard(msg_id)
                return

            sender = event.sender_id
            chat = event.chat_id
            now = time.time()   # <-- ADD THIS LINE

            if not sender or sender in OWNER_IDS:
                pass

            if user_bot.user_filters and event.text:
                msg_text = event.raw_text or ""
                for trigger, reply_data in user_bot.user_filters.items():
                    if trigger.lower() in msg_text.lower():
                        try:
                            if reply_data['type'] == 'sticker' and reply_data['sticker_id']:
                                sent = await safe_send(chat, file=reply_data['sticker_id'], reply_to=event.id)
                            elif reply_data['type'] == 'text' and reply_data['text']:
                                sent = await safe_send(chat, reply_data['text'], reply_to=event.id)
                            else:
                                continue
                            if sent:
                                user_bot.filter_reply_ids.add(sent.id)
                                if len(user_bot.filter_reply_ids) > 100:
                                    user_bot.filter_reply_ids.clear()
                        except Exception as e:
                            print(f"Filter reply error: {e}")
                        break

            if event.out:
                return
            if not sender or sender in OWNER_IDS:
                return

            if sender in user_bot.muted_users or sender in user_bot.global_muted:
                try:
                    await event.delete()
                except:
                    pass
                return

            ws_key = (chat, sender)
            if ws_key in user_bot.watch_spam:
                now = time.time()
                entry = user_bot.watch_spam[ws_key]
                entry["times"] = [t for t in entry["times"] if now - t < entry["seconds"]]
                entry["times"].append(now)
                if len(entry["times"]) > entry["limit"]:
                    try:
                        await event.delete()
                    except:
                        pass
                    return

            if chat in user_bot.group_locks:
                if not is_admin(sender):
                    try:
                        await event.delete()
                    except:
                        pass
                    return

            if sender in user_bot.reply_users:
                if await is_protected(sender, "reply"):
                    await safe_send(chat, "🚫 This user has protected themselves from reply raid.", reply_to=event.id)
                    return
                await safe_send(chat, random.choice(reply_list) if reply_list else "🔥 Reply Raid!", reply_to=event.id)
                user_bot.reply_cooldowns[sender] = now
                return

            if sender in user_bot.replygod_users:
                if await is_protected(sender, "replygod"):
                    await safe_send(chat, "🚫 This user has protected themselves from God raid.", reply_to=event.id)
                    return
                for _ in range(4):
                    await safe_send(chat, random.choice(reply_texts) if reply_texts else "💥 God Raid!", reply_to=event.id)
                    await asyncio.sleep(0.3)
                user_bot.reply_cooldowns[sender] = now
                return

            if sender in user_bot.flag_users:
                if await is_protected(sender, "flag"):
                    await safe_send(chat, "🚫 This user has protected themselves from flag raid.", reply_to=event.id)
                    return
                await safe_send(chat, random.choice(flag_texts) if flag_texts else "🚩 Flag Raid!", reply_to=event.id)
                user_bot.reply_cooldowns[sender] = now
                return

            if sender in user_bot.hrr_users:
                if await is_protected(sender, "hrr"):
                    await safe_send(chat, "🚫 This user has protected themselves from heart raid.", reply_to=event.id)
                    return
                await safe_send(chat, random.choice(heart_replies) if heart_replies else "💜 Heart Raid!", reply_to=event.id)
                user_bot.reply_cooldowns[sender] = now
                return

            if sender in user_bot.rr_users:
                if await is_protected(sender, "rr"):
                    await safe_send(chat, "🚫 This user has protected themselves from RR raid.", reply_to=event.id)
                    return
                bot_msg = await safe_send(chat, random.choice(fun_texts) if fun_texts else "🤣 RR Raid!", reply_to=event.id)
                if bot_msg:
                    try:
                        await user_bot(functions.messages.SendReactionRequest(
                            peer=chat, msg_id=bot_msg.id,
                            reaction=[types.ReactionEmoji(emoticon="🤣")]
                        ))
                    except:
                        pass
                user_bot.reply_cooldowns[sender] = now
                return

            if sender in user_bot.custom_raid_users:
                if await is_protected(sender, "customraid"):
                    await safe_send(chat, "🚫 This user has protected themselves from custom raid.", reply_to=event.id)
                    return
                data = user_bot.custom_raid_users.get(sender)
                if data and data.get("count", 0) > 0:
                    await safe_send(chat, data.get("text", ""), reply_to=event.id)
                    data["count"] = data["count"] - 1
                    if data["count"] <= 0:
                        del user_bot.custom_raid_users[sender]
                    user_bot.reply_cooldowns[sender] = now
                    return

            if sender in user_bot.pwr_users:
                if await is_protected(sender, "pwr"):
                    await safe_send(chat, "🚫 This user has protected themselves from PWR raid.", reply_to=event.id)
                    return
                remaining = user_bot.pwr_raid.get(sender)
                if remaining is not None:
                    if isinstance(remaining, int) and remaining <= 0:
                        del user_bot.pwr_raid[sender]
                        user_bot.pwr_users.discard(sender)
                        user_bot.pwr_index.pop(sender, None)
                        return
                    if isinstance(remaining, int):
                        user_bot.pwr_raid[sender] = remaining - 1

                idx = user_bot.pwr_index.get(sender, 0)
                if pwr_texts:
                    text_to_send = pwr_texts[idx % len(pwr_texts)]
                    user_bot.pwr_index[sender] = (idx + 1) % len(pwr_texts)
                else:
                    text_to_send = "🔥 PWR! (list empty)"
                await safe_send(chat, text_to_send, reply_to=event.id)
                user_bot.reply_cooldowns[sender] = time.time()
                return

            if sender in user_bot.ows_users:
                if await is_protected(sender, "ows"):
                    await safe_send(chat, "🚫 This user has protected themselves from OWS spam.", reply_to=event.id)
                    return
                remaining = user_bot.ows_spam.get(sender)
                if remaining is not None:
                    if remaining <= 0:
                        del user_bot.ows_spam[sender]
                        user_bot.ows_users.discard(sender)
                        user_bot.ows_index.pop(sender, None)
                        return
                    user_bot.ows_spam[sender] = remaining - 1

                idx = user_bot.ows_index.get(sender, 0)
                if ows_texts:
                    text_to_send = ows_texts[idx % len(ows_texts)]
                    user_bot.ows_index[sender] = (idx + 1) % len(ows_texts)
                else:
                    text_to_send = "💬 OWS! (list empty)"
                await safe_send(chat, text_to_send, reply_to=event.id)
                user_bot.reply_cooldowns[sender] = time.time()
                return

            if sender in user_bot.shayari_raid:
                if await is_protected(sender, "shayariraid"):
                    await safe_send(chat, "🚫 This user has protected themselves from Shayari raid.", reply_to=event.id)
                    return
                remaining = user_bot.shayari_raid[sender]
                if remaining is not None and remaining <= 0:
                    del user_bot.shayari_raid[sender]
                    return
                await safe_send(chat, random.choice(shayari_texts) if shayari_texts else "📜 Shayari!", reply_to=event.id)
                user_bot.reply_cooldowns[sender] = now
                if remaining is not None:
                    user_bot.shayari_raid[sender] = remaining - 1
                return

            if sender in user_bot.rizz_raid:
                if await is_protected(sender, "rizzraid"):
                    await safe_send(chat, "🚫 This user has protected themselves from Rizz raid.", reply_to=event.id)
                    return
                remaining = user_bot.rizz_raid[sender]
                if remaining is not None and remaining <= 0:
                    del user_bot.rizz_raid[sender]
                    return
                await safe_send(chat, random.choice(rizz_texts) if rizz_texts else "💋 Rizz!", reply_to=event.id)
                user_bot.reply_cooldowns[sender] = now
                if remaining is not None:
                    user_bot.rizz_raid[sender] = remaining - 1
                return

            if sender in user_bot.pickup_users:
                if await is_protected(sender, "pickupraid"):
                    await safe_send(chat, "🚫 This user has protected themselves from pickup raid.", reply_to=event.id)
                    return
                remaining = user_bot.pickup_raid.get(sender)
                if remaining is not None and remaining <= 0:
                    del user_bot.pickup_raid[sender]
                    user_bot.pickup_users.discard(sender)
                    return
                if isinstance(remaining, int):
                    user_bot.pickup_raid[sender] = remaining - 1
                await safe_send(chat, random.choice(pickup_texts) if pickup_texts else "💘 Pickup!", reply_to=event.id)
                user_bot.reply_cooldowns[sender] = now
                return

            if sender in user_bot.romance_users:
                if await is_protected(sender, "romanceraid"):
                    await safe_send(chat, "🚫 This user has protected themselves from romance raid.", reply_to=event.id)
                    return
                remaining = user_bot.romance_raid.get(sender)
                if remaining is not None and remaining <= 0:
                    del user_bot.romance_raid[sender]
                    user_bot.romance_users.discard(sender)
                    return
                if isinstance(remaining, int):
                    user_bot.romance_raid[sender] = remaining - 1
                await safe_send(chat, random.choice(romance_texts) if romance_texts else "❤️ Romance!", reply_to=event.id)
                user_bot.reply_cooldowns[sender] = now
                return

            if sender in user_bot.trollraid_users:
                if await is_protected(sender, "trollraid"):
                    await safe_send(chat, "🚫 This user has protected themselves from troll raid.", reply_to=event.id)
                    return
                remaining = user_bot.troll_raid.get(sender)
                if remaining is not None and remaining <= 0:
                    del user_bot.troll_raid[sender]
                    user_bot.trollraid_users.discard(sender)
                    return
                if isinstance(remaining, int):
                    user_bot.troll_raid[sender] = remaining - 1
                await safe_send(chat, random.choice(troll_texts) if troll_texts else "🤡 Troll!", reply_to=event.id)
                user_bot.reply_cooldowns[sender] = now
                return

            if sender in user_bot.ragebait_users:
                if await is_protected(sender, "ragebaitraid"):
                    await safe_send(chat, "🚫 This user has protected themselves from ragebait raid.", reply_to=event.id)
                    return
                remaining = user_bot.ragebait_raid.get(sender)
                if remaining is not None and remaining <= 0:
                    del user_bot.ragebait_raid[sender]
                    user_bot.ragebait_users.discard(sender)
                    return
                if isinstance(remaining, int):
                    user_bot.ragebait_raid[sender] = remaining - 1
                await safe_send(chat, random.choice(ragebait_texts) if ragebait_texts else "😤 Ragebait!", reply_to=event.id)
                user_bot.reply_cooldowns[sender] = now
                return

            if sender in user_bot.roastraid_users:
                if await is_protected(sender, "roastraid"):
                    await safe_send(chat, "🚫 This user has protected themselves from roast raid.", reply_to=event.id)
                    return
                remaining = user_bot.roast_raid.get(sender)
                if remaining is not None and remaining <= 0:
                    del user_bot.roast_raid[sender]
                    user_bot.roastraid_users.discard(sender)
                    return
                if isinstance(remaining, int):
                    user_bot.roast_raid[sender] = remaining - 1
                await safe_send(chat, random.choice(roast_texts) if roast_texts else "🔥 Roast!", reply_to=event.id)
                user_bot.reply_cooldowns[sender] = now
                return

            if sender in user_bot.attackraid_users:
                if await is_protected(sender, "attackraid"):
                    await safe_send(chat, "🚫 This user has protected themselves from attack raid.", reply_to=event.id)
                    return
                remaining = user_bot.attack_raid.get(sender)
                if remaining is not None and remaining <= 0:
                    del user_bot.attack_raid[sender]
                    user_bot.attackraid_users.discard(sender)
                    return
                if isinstance(remaining, int):
                    user_bot.attack_raid[sender] = remaining - 1
                await safe_send(chat, random.choice(attack_texts) if attack_texts else "⚔️ Attack!", reply_to=event.id)
                user_bot.reply_cooldowns[sender] = now
                return

            if sender in user_bot.warraid_users:
                if await is_protected(sender, "warraid"):
                    await safe_send(chat, "🚫 This user has protected themselves from war raid.", reply_to=event.id)
                    return
                remaining = user_bot.war_raid.get(sender)
                if remaining is not None and remaining <= 0:
                    del user_bot.war_raid[sender]
                    user_bot.warraid_users.discard(sender)
                    return
                if isinstance(remaining, int):
                    user_bot.war_raid[sender] = remaining - 1
                await safe_send(chat, random.choice(war_texts) if war_texts else "🏴‍☠️ War!", reply_to=event.id)
                user_bot.reply_cooldowns[sender] = now
                return

            if sender in user_bot.savageraid_users:
                if await is_protected(sender, "savageraid"):
                    await safe_send(chat, "🚫 This user has protected themselves from savage raid.", reply_to=event.id)
                    return
                remaining = user_bot.savage_raid.get(sender)
                if remaining is not None and remaining <= 0:
                    del user_bot.savage_raid[sender]
                    user_bot.savageraid_users.discard(sender)
                    return
                if isinstance(remaining, int):
                    user_bot.savage_raid[sender] = remaining - 1
                await safe_send(chat, random.choice(savage_texts) if savage_texts else "😈 Savage!", reply_to=event.id)
                user_bot.reply_cooldowns[sender] = now
                return

            if sender in user_bot.ultraraid_users:
                if await is_protected(sender, "ultraraid"):
                    await safe_send(chat, "🚫 This user has protected themselves from ultra raid.", reply_to=event.id)
                    return
                remaining = user_bot.ultra_raid.get(sender)
                if remaining is not None and remaining <= 0:
                    del user_bot.ultra_raid[sender]
                    user_bot.ultraraid_users.discard(sender)
                    return
                if isinstance(remaining, int):
                    user_bot.ultra_raid[sender] = remaining - 1
                await safe_send(chat, random.choice(ultra_texts) if ultra_texts else "⚡ Ultra!", reply_to=event.id)
                user_bot.reply_cooldowns[sender] = now
                return

            if sender in user_bot.shame_users:
                if await is_protected(sender, "shameraid"):
                    await safe_send(chat, "🚫 This user has protected themselves from shame raid.", reply_to=event.id)
                    return
                remaining = user_bot.shame_raid.get(sender)
                if remaining is not None and remaining <= 0:
                    del user_bot.shame_raid[sender]
                    user_bot.shame_users.discard(sender)
                    return
                if isinstance(remaining, int):
                    user_bot.shame_raid[sender] = remaining - 1
                await safe_send(chat, random.choice(shame_texts) if shame_texts else "😤 Shame!", reply_to=event.id)
                user_bot.reply_cooldowns[sender] = now
                return

            if sender in user_bot.diss_users:
                if await is_protected(sender, "dissraid"):
                    await safe_send(chat, "🚫 This user has protected themselves from diss raid.", reply_to=event.id)
                    return
                remaining = user_bot.diss_raid.get(sender)
                if remaining is not None and remaining <= 0:
                    del user_bot.diss_raid[sender]
                    user_bot.diss_users.discard(sender)
                    return
                if isinstance(remaining, int):
                    user_bot.diss_raid[sender] = remaining - 1
                await safe_send(chat, random.choice(diss_texts) if diss_texts else "🎤 Diss!", reply_to=event.id)
                user_bot.reply_cooldowns[sender] = now
                return

            if sender in user_bot.devil_users:
                if await is_protected(sender, "devilraid"):
                    await safe_send(chat, "🚫 This user has protected themselves from devil raid.", reply_to=event.id)
                    return
                remaining = user_bot.devil_raid.get(sender)
                if remaining is not None and remaining <= 0:
                    del user_bot.devil_raid[sender]
                    user_bot.devil_users.discard(sender)
                    return
                if isinstance(remaining, int):
                    user_bot.devil_raid[sender] = remaining - 1
                await safe_send(chat, random.choice(devil_texts) if devil_texts else "😈 Devil!", reply_to=event.id)
                user_bot.reply_cooldowns[sender] = now
                return

            if sender in user_bot.karma_users:
                if await is_protected(sender, "karmaraid"):
                    await safe_send(chat, "🚫 This user has protected themselves from karma raid.", reply_to=event.id)
                    return
                remaining = user_bot.karma_raid.get(sender)
                if remaining is not None and remaining <= 0:
                    del user_bot.karma_raid[sender]
                    user_bot.karma_users.discard(sender)
                    return
                if isinstance(remaining, int):
                    user_bot.karma_raid[sender] = remaining - 1
                await safe_send(chat, random.choice(karma_texts) if karma_texts else "☯️ Karma!", reply_to=event.id)
                user_bot.reply_cooldowns[sender] = now
                return

            if sender in user_bot.doom_users:
                if await is_protected(sender, "doomraid"):
                    await safe_send(chat, "🚫 This user has protected themselves from doom raid.", reply_to=event.id)
                    return
                remaining = user_bot.doom_raid.get(sender)
                if remaining is not None and remaining <= 0:
                    del user_bot.doom_raid[sender]
                    user_bot.doom_users.discard(sender)
                    return
                if isinstance(remaining, int):
                    user_bot.doom_raid[sender] = remaining - 1
                await safe_send(chat, random.choice(doom_texts) if doom_texts else "💀 Doom!", reply_to=event.id)
                user_bot.reply_cooldowns[sender] = now
                return

        # ─── CACHE & ANTI-DELETE ──────────────────────────────────────────────
        @user_bot.on(events.NewMessage(outgoing=True))
        async def cache_own(event):
            if not user_bot.antidel_enabled:
                return
            try:
                msg_id = event.id
                chat = event.chat_id
                if msg_id and chat:
                    user_bot.antidel_cache[msg_id] = {"chat_id": chat, "text": event.raw_text or "", "time": time.time()}
                    if len(user_bot.antidel_cache) > 300:
                        oldest = sorted(user_bot.antidel_cache, key=lambda k: user_bot.antidel_cache[k]["time"])
                        for k in oldest[:50]:
                            user_bot.antidel_cache.pop(k, None)
            except:
                pass

        @user_bot.on(events.MessageDeleted)
        async def on_delete(event):
            if not user_bot.antidel_enabled:
                return
            try:
                for msg_id in (event.deleted_ids or []):
                    entry = user_bot.antidel_cache.pop(msg_id, None)
                    if entry:
                        chat_id = entry.get("chat_id")
                        text = entry.get("text")
                        if chat_id and text:
                            await safe_send(chat_id, f"♻️ **[Anti-Delete]**\n{text}")
            except:
                pass

        @user_bot.on(events.NewMessage)
        async def auto_react(event):
            sender = event.sender_id
            if not sender:
                return
            if event.out:
                emoji = user_bot.auto_react_emoji
                if not emoji:
                    return
                try:
                    await user_bot(functions.messages.SendReactionRequest(
                        peer=event.chat_id,
                        msg_id=event.id,
                        reaction=[types.ReactionEmoji(emoticon=emoji)]
                    ))
                except:
                    pass
                return
            if sender in user_bot.react_targets:
                emoji = user_bot.react_targets[sender]
                if not emoji:
                    return
                try:
                    await user_bot(functions.messages.SendReactionRequest(
                        peer=event.chat_id,
                        msg_id=event.id,
                        reaction=[types.ReactionEmoji(emoticon=emoji)]
                    ))
                except:
                    pass

        @user_bot.on(events.NewMessage)
        async def track_name_changes(event):
            if event.out:
                return
            sender = event.sender_id
            if not sender:
                return
            try:
                user = await user_bot.get_entity(sender)
                if user.deleted or user.bot:
                    return
                current_name = user.first_name or ""
                current_username = user.username or ""
                history = load_sangmata(sender)
                last_entry = history[-1] if history else None
                if last_entry:
                    last_name = last_entry.get('new_name', '')
                    last_username = last_entry.get('new_username', '')
                    if last_name == current_name and last_username == current_username:
                        return
                entry = {
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "old_name": last_entry.get('new_name', '') if last_entry else '',
                    "old_username": last_entry.get('new_username', '') if last_entry else '',
                    "new_name": current_name,
                    "new_username": current_username
                }
                history.append(entry)
                save_sangmata(sender, history)
            except:
                pass

        # ─── START USERBOT ──────────────────────────────────────────────────
        await MAIN_BOT_CLIENT.send_message(chat_id, f"🔥 **Your Userbot is now Active!**\n👤 {me.first_name}\n💡 Use `.menu` to get started.")
        await user_bot.run_until_disconnected()

    except (UnauthorizedError, ValueError, RPCError) as e:
        error_msg = str(e)
        if "SESSION_INVALID" in error_msg or "invalid" in error_msg.lower():
            try:
                await MAIN_BOT_CLIENT.send_message(chat_id, "⚠️ **Your userbot session is invalid. Please login again with /login.**")
            except:
                pass
        raise

    except asyncio.CancelledError:
        print(f"Userbot task cancelled for {chat_id}")
        raise

    except Exception as e:
        print(f"Userbot crashed: {e}")
        try:
            await MAIN_BOT_CLIENT.send_message(chat_id, f"⚠️ **Userbot crashed:** {str(e)[:100]}\nRestarting...")
        except:
            pass
        raise

    finally:
        active_userbots.pop(chat_id, None)
        if user_bot:
            try:
                tasks_to_cancel = []
                for task in asyncio.all_tasks():
                    if task.get_name() in [f"userbot_{chat_id}", f"userbot_restart_{chat_id}"]:
                        tasks_to_cancel.append(task)
                for task in tasks_to_cancel:
                    if not task.done():
                        task.cancel()
                        try:
                            await asyncio.shield(task)
                        except:
                            pass
                await user_bot.disconnect()
            except Exception:
                pass

# ─── WEB SERVER ──────────────────────────────────────────────────────
app = Flask(__name__)

@app.route('/')
@app.route('/health')
def home():
    return "✅ Userbot is running 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 5000))
    serve(app, host="0.0.0.0", port=port)

# ─── MAIN ────────────────────────────────────────────────────────────
async def main():
    print("🚀 Main bot starting with Web Server (Waitress)...")
    await init_db()
    await init_cipher()
    sessions = await load_sessions()
    for uid, sess_str in sessions.items():
        try:
            task = asyncio.create_task(run_user_bot_with_restart(sess_str, uid))
            task.set_name(f"userbot_restart_{uid}")
            running_tasks.add(task)
            task.add_done_callback(running_tasks.discard)
            print(f"✅ Restored session for user {uid}")
        except Exception as e:
            print(f"❌ Failed to restore {uid}: {e}")
            await delete_session(uid)
    threading.Thread(target=run_web, daemon=True).start()
    await MAIN_BOT_CLIENT.start(bot_token=BOT_TOKEN)
    print("✅ Bot is running. Press Ctrl+C to stop.")
    try:
        await MAIN_BOT_CLIENT.run_until_disconnected()
    finally:
        for task in list(running_tasks):
            if not task.done():
                task.cancel()
        await MAIN_BOT_CLIENT.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
