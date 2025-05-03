import telebot
import os
import threading
from dotenv import load_dotenv
from flask import Flask, request
from datetime import datetime
import time
import pytz

# .env 환경변수 불러오기
load_dotenv()

# 텔레그램 봇 초기화
TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TOKEN)
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))  # 그룹 채팅 ID
TOPIC1_ID = int(os.getenv("TOPIC1_ID"))  # 인사용 토픽 ID
TOPIC2_ID = int(os.getenv("TOPIC2_ID"))  # 공지용 토픽 ID

# Flask 앱 생성
app = Flask(__name__)

# 슬립 방지를 위한 ping 엔드포인트
@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

# 새 멤버 인사 메시지
@bot.message_handler(content_types=['new_chat_members'])
def greet_new_member(message):
    for new_user in message.new_chat_members:
        welcome_message = (
            f"👋 {new_user.first_name}님, 반갑습니다❣️\n"
            f"비즈LIKE 동아리에 오신걸 환영합니다🎉\n"
            f"모임 참석 전 상단에 고정돼있는 동아리 소개글을 필독해주세요🙏🙏"
        )
        bot.send_message(message.chat.id, welcome_message)

# 매주 월요일 오전 9시 (한국 시간) 공지 전송 함수
def weekly_announcement():
    now = datetime.now(KST).strftime("%Y-%m-%d")
    message = (
         f"오늘 드디어 모임 날입니다!!\n"
         f"늦지 않도록 와주시고 식사도 챙겨드셔요!\n"
         f"\n"
         f"‼️수다방 고정 메세지 필수 확인‼️\n"
    )
    bot.send_message(chat_id=CHAT_ID, text=message, message_thread_id=TOPIC2_ID)  # 공지 전용 토픽

# 한국 시간 기준으로 월요일 9시에 공지를 보내는 스케줄러
KST = pytz.timezone("Asia/Seoul")
def run_scheduler():
    while True:
        now = datetime.now(KST)
        if now.weekday() == 6 and now.hour == 10 and now.minute == 0:
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
