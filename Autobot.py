import os
import hashlib
import threading
import time
from datetime import datetime

import pytz
import gspread
from flask import Flask
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
import telebot
from gspread.exceptions import APIError

# ─── 환경 변수 로드 ────────────────────────────────────────────────────────────
load_dotenv()
SPREADSHEET_URL = os.getenv("SPREADSHEET_URL")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME")
BASE_TOKEN      = os.getenv("TELEGRAM_TOKEN")
PORT            = int(os.getenv("PORT", 5000))

# ─── Flask 앱 (헬스체크) ────────────────────────────────────────────────────────
app = Flask(__name__)
@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

# ─── 시간대 설정 ───────────────────────────────────────────────────────────────
KST = pytz.timezone("Asia/Seoul")

# ─── 캐시 변수 ─────────────────────────────────────────────────────────────────
last_sheet_hash = None
welcome_list   = []  # 입장 시 환영 메시지
schedule_list  = []  # 요일·시간 스케줄

# ─── 헬퍼 함수 ─────────────────────────────────────────────────────────────────
def get_sheet_hash(values):
    flat = "".join("".join(row) for row in values)
    return hashlib.md5(flat.encode()).hexdigest()

def convert_weekday_kor_to_eng(kor):
    m = {
        "월요일":"monday","화요일":"tuesday","수요일":"wednesday",
        "목요일":"thursday","금요일":"friday","토요일":"saturday",
        "일요일":"sunday","입장시":"on_join"
    }
    return m.get(kor.strip(), "").lower()

# ─── 시트 데이터 로드 & 캐싱 (예외 처리 포함) ─────────────────────────────────
def load_configs():
    global last_sheet_hash, welcome_list, schedule_list

    try:
        scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name('google_credentials.json', scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_url(SPREADSHEET_URL).worksheet(SPREADSHEET_NAME)

        values = sheet.get_all_values()
        h = get_sheet_hash(values)
        if h == last_sheet_hash:
            return
        last_sheet_hash = h

        print("[Sheet Updated] Reloading configs…")
        data = sheet.get_all_records()
        welcome_list.clear()
        schedule_list.clear()

        for row in data:
            wd  = convert_weekday_kor_to_eng(row["보낼 요일"])
            cid = int("-100" + str(row["그룹방 ID"]))
            # 유효하지 않은 토픽 ID는 0 처리
            try:
                tid = int(row.get("토픽 ID", 0))
            except:
                tid = 0
            msg = row["보낼 메세지"]
            t   = row.get("보낼 시간", "").strip()

            if wd == "on_join":
                welcome_list.append({"chat_id": cid, "topic_id": tid, "message": msg})
            else:
                schedule_list.append({
                    "weekday": wd, "time": t,
                    "chat_id": cid, "topic_id": tid, "message": msg
                })

    except APIError as e:
        # 일시적 구글 API 오류: 로그만 남기고 바로 리턴
        print(f"[Warning] Google Sheets APIError: {e}. Will retry next cycle.")
    except Exception as e:
        # 다른 예외도 캐치
        print(f"[Error] load_configs failed: {e}")

# ─── TeleBot 생성 & 환영 핸들러 등록 ───────────────────────────────────────────
bot = telebot.TeleBot(BASE_TOKEN, threaded=False)

@bot.message_handler(content_types=['new_chat_members'])
def handle_new_members(message):
    for cfg in welcome_list:
        if message.chat.id == cfg["chat_id"]:
            kwargs = {
                "chat_id": cfg["chat_id"],
                "text": cfg["message"]
            }
            if cfg["topic_id"] not in (0, 1):
                kwargs["message_thread_id"] = cfg["topic_id"]
            bot.send_message(**kwargs)
            print(f"[Welcome] sent to chat {cfg['chat_id']}")

# ─── 스케줄러 헬퍼 & 루프 ───────────────────────────────────────────────────────
def sleep_until_next_minute():
    now = datetime.now()
    time.sleep(60 - now.second)

def scheduler_loop():
    while True:
        now = datetime.now(KST)
        wd  = now.strftime("%A").lower()
        tm  = now.strftime("%H:%M")

        # configs 로드 (API 오류 시 스킵되어도 다음 루프에 재시도)
        load_configs()

        for cfg in schedule_list:
            if cfg["weekday"] == wd and cfg["time"] == tm:
                try:
                    kwargs = {
                        "chat_id": cfg["chat_id"],
                        "text": cfg["message"]
                    }
                    if cfg["topic_id"] not in (0, 1):
                        kwargs["message_thread_id"] = cfg["topic_id"]
                    bot.send_message(**kwargs)
                    print(f"[Scheduled] {wd} {tm} → {cfg['message']}")
                except Exception as e:
                    print(f"[Error] failed to send scheduled message: {e}")

        sleep_until_next_minute()

# ─── 앱 실행 ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 1) 스케줄러 스레드 (데몬으로 백그라운드)
    threading.Thread(target=scheduler_loop, daemon=True).start()
    # 2) Polling
    bot.remove_webhook()
    bot.infinity_polling()
    # (Optional) Flask 헬스체크는 필요에 따라 별도 프로세스로 실행하세요.
