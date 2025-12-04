#!/bin/bash
# Botni screen sessiyasida ishga tushirish uchun skript

# Agar 'bot_screen' nomli sessiya allaqachon mavjud bo'lsa, uni yopamiz
screen -S bot_screen -X quit

# Yangi 'bot_screen' sessiyasini ochamiz va bot.py ni ishga tushiramiz
screen -dmS bot_screen python3 bot.py

echo "Telegram bot 'bot_screen' nomli screen sessiyasida ishga tushirildi."
echo "Holatni tekshirish uchun: screen -r bot_screen"