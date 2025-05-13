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
SPREADSHEET_URL  = os.getenv("SPREADSHEET_URL")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "Sheet1")
BASE_TOKEN       = os.getenv("TELEGRAM_TOKEN")
PORT             = int(os.getenv("PORT", 5000))

# ─── Flask 앱 (헬스체크) ────────────────────────────────────────────────────────
app = Flask(__name__)

@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

# ─── 시간대 설정 ───────────────────────────────────────────────────────────────
KST = pytz.timezone("Asia/Seoul")

# ─── 캐시 변수 ─────────────────────────────────────────────────────────────────
last_sheet_hash = None
welcome_list    = []  # 입장 시 환영 메시지
schedule_list   = []  # 요일·시간 스케줄

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

        # 지정된 URL, 이름의 탭(sheet) 읽어오기
        spreadsheet = client.open_by_url(SPREADSHEET_URL)
        sheet       = spreadsheet.worksheet(SPREADSHEET_NAME)

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
            try:
                tid = int(row.get("토픽 ID", 0))
            except:
                tid = 0
            msg = row["보낼 메세지"]
            t   = row.get("보낼 시간", "").strip()

            if wd == "on_join":
                welcome_list.append({
                    "chat_id": cid,
                    "topic_id": tid,
                    "message": msg
                })
            else:
                schedule_list.append({
                    "weekday": wd,
                    "time": t,
                    "chat_id": cid,
                    "topic_id": tid,
                    "message": msg
                })

    except APIError as e:
        print(f"[Warning] Google Sheets APIError: {e}. Will retry next cycle.")
    except Exception as e:
        print(f"[Error] load_configs failed: {e}")

# ─── TeleBot 생성 & 환영 핸들러 등록 ───────────────────────────────────────────
bot = telebot.TeleBot(BASE_TOKEN, threaded=False)

@bot.message_handler(content_types=['new_chat_members'])
def handle_new_members(message):
    for cfg in welcome_list:
        if message.chat.id == cfg["chat_id"]:
            # 메시지에 사용자 이름 적용
            try:
                personalized = cfg["message"].format(new_user=new_user)
            except Exception as e:
                print(f"[Format Error] {e}")
                personalized = cfg["message"]  # 실패 시 원본 메시지
                
            kwargs = {
                "chat_id": cfg["chat_id"],
                "text": cfg["message"]
            }
            # topic_id가 2 이상일 때만 스레드 파라미터 추가
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
    # 1) Flask 헬스체크 서버
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=PORT), daemon=True).start()

    # 2) 스케줄러 데몬 스레드
    threading.Thread(target=scheduler_loop, daemon=True).start()

    # 3) Telegram Polling (메인 스레드에서 단일 인스턴스)
    bot.delete_webhook(drop_pending_updates=True)
    bot.infinity_polling()
