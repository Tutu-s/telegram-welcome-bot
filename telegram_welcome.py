import telebot
import os
import schedule
import time
import threading
from dotenv import load_dotenv
from flask import Flask, request
from datetime import datetime
import pytz

# .env 환경변수 불러오기
load_dotenv()

# 텔레그램 봇 초기화
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # 그룹 채팅 ID
TOPIC1_ID = int(os.getenv("TOPIC1_ID"))  # 인사용 토픽 ID
TOPIC2_ID = int(os.getenv("TOPIC2_ID"))  # 취합용 토픽 ID
bot = telebot.TeleBot(TOKEN)

# Flask 앱 생성
app = Flask(__name__)

# 슬립 방지를 위한 ping 엔드포인트
@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

# 1. 새 멤버 인사 메시지
@bot.message_handler(content_types=['new_chat_members'])
def greet_new_member(message):
    for user in message.new_chat_members:
        text = (
            f"👋 {user.first_name}님, 반갑습니다❣️\n"
            f"비즈LIKE 동아리에 오신걸 환영합니다🎉\n"
            f"모임 참석 전 상단에 고정돼있는 동아리 소개글을 필독해주세요🙏🙏"
        )
        bot.send_message(chat_id=CHAT_ID, text=text, message_thread_id=TOPIC1_ID)

# 테스트 코드
@bot.message_handler(func=lambda message: True)
def debug_topic_id(message):
    print(f"[디버그] 토픽 ID: {message.message_thread_id}")

                         
# 2. 매주 월요일 09:00에 공지 메시지 전송
def weekly_announcement():
    now = datetime.now().strftime("%Y-%m-%d")
    message = (
        f"☘️비즈LIKE 모임 취합☘️\n"
        f"\n"
        f"참석자/재료준비(개인or공구)/사진첨부/재료비 입금\n"
        f"예)임정민/공구/0/0\n"
        f"\n"
        f"1/\n"
        f"2/\n"
        f"3/\n"
        f"4/\n"
    )
    bot.send_message(chat_id=CHAT_ID, text=message, message_thread_id=TOPIC2_ID)

schedule.every().monday.at("09:00").do(weekly_announcement)

# ▶️ 한국 시간 기준으로 월요일 9시에 공지를 보내는 스케줄러
KST = pytz.timezone("Asia/Seoul")
def run_scheduler():
    while True:
        now = datetime.now(KST)
        if now.weekday() == 0 and now.hour == 9 and now.minute == 0:
            weekly_announcement()
            time.sleep(60)  # 1분 대기 (중복 방지)
        time.sleep(30)  # 체크 간격

# Flask 서버와 봇 polling을 동시에 실행하기 위한 스레딩

def run_bot():
    bot.remove_webhook()  # 충돌 방지를 위해 웹훅 제거
    bot.infinity_polling()

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    threading.Thread(target=run_scheduler).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))


