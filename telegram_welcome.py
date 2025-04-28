import telebot
import os
from dotenv import load_dotenv
from flask import Flask, request

# .env 환경변수 불러오기
load_dotenv()

# 텔레그램 봇 초기화
TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TOKEN)
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # 그룹 채팅 ID
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
        bot.send_message(CHAT_ID, welcome_message, TOPIC1_ID)

# Flask 서버와 봇 polling을 동시에 실행하기 위한 스레딩
import threading

def run_bot():
    bot.remove_webhook()  # 충돌 방지를 위해 웹훅 제거
    bot.infinity_polling()

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
