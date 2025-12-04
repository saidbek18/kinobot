import telebot
from telebot import types
import sqlite3
import logging
import time

# ----------------- 1. BOT SOZLAMALARI VA DB SETUP -----------------
API_TOKEN = '7966505221:AAHEUj82be8yTNnmfKhbpTz9CqiSR75SAx4' # O'zingizning haqiqiy TOKENINGIZNI KIRITING
DB_NAME = 'bot.db'

# --- ADMINLAR VA KANALLAR ---
ADMINS = [8165064673] # Bosh admin ID'si (Bu joyga o'z ID'ingizni kiriting)
CHANNELS = [
    '@tarjimakinolar_bizda',  # Haqiqiy kanal username'laringizni yozing!
    # '@kanal_username_2'
]

# Logging sozlamalari
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Bot obyektini yaratish
bot = telebot.TeleBot(API_TOKEN)

# Holatlar (FSM o'rniga) va ma'lumotlarni saqlash uchun lug'atlar
user_states = {} # {chat_id: 'state_name'}
user_data = {}   # {chat_id: {'code': '101', 'caption': 'matn', 'media_file_id': '...'}}

# ----------------- 2. MA'LUMOTLAR BAZASI FUNKSIYALARI (SQLite) -----------------

class Database:
    """SQLite bilan ishlash uchun sinf"""
    def __init__(self, db_file):
        self.conn = sqlite3.connect(db_file, check_same_thread=False) 
        self.cursor = self.conn.cursor()
        self.setup()

    def setup(self):
        # Adminlar jadvali
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)
        """)
        
        # Kinolar jadvali
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS films (
                code TEXT PRIMARY KEY,
                file_id TEXT NOT NULL,
                caption TEXT
            )
        """)
        
        # Foydalanuvchilar jadvali (Statistika va Reklama uchun)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                is_blocked BOOLEAN DEFAULT 0,
                last_active DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()
        
        for admin_id in ADMINS:
            self.add_admin(admin_id)

    # --- USER AMALLARI ---
    def add_user(self, user_id):
        """Foydalanuvchini bazaga qo'shish yoki faolligini yangilash"""
        self.cursor.execute("INSERT OR IGNORE INTO users (user_id, is_blocked) VALUES (?, 0)", (user_id,))
        self.cursor.execute("UPDATE users SET is_blocked = 0, last_active = DATETIME('now', 'localtime') WHERE user_id = ?", (user_id,))
        self.conn.commit()

    def set_user_blocked(self, user_id, is_blocked):
        """Foydalanuvchining bloklanganlik holatini o'rnatish"""
        self.cursor.execute("UPDATE users SET is_blocked = ? WHERE user_id = ?", (is_blocked, user_id))
        self.conn.commit()

    def get_all_users_for_broadcast(self):
        """Reklama uchun bloklamagan barcha userlar ID'sini qaytaradi"""
        self.cursor.execute("SELECT user_id FROM users WHERE is_blocked = 0")
        return [row[0] for row in self.cursor.fetchall()]

    # --- STATISTIKA AMALLARI ---
    def count_total_users(self):
        self.cursor.execute("SELECT COUNT(user_id) FROM users")
        return self.cursor.fetchone()[0]

    def count_blocked_users(self):
        self.cursor.execute("SELECT COUNT(user_id) FROM users WHERE is_blocked = 1")
        return self.cursor.fetchone()[0]

    def count_active_users(self):
        """Oxirgi 24 soatda faol bo'lganlarni hisoblash"""
        self.cursor.execute("""
            SELECT COUNT(user_id) FROM users 
            WHERE last_active >= DATETIME('now', '-1 day', 'localtime')
        """)
        return self.cursor.fetchone()[0]

    # --- FILM AMALLARI ---
    def add_film(self, code, file_id, caption):
        self.cursor.execute("INSERT OR REPLACE INTO films (code, file_id, caption) VALUES (?, ?, ?)",
                            (code, file_id, caption))
        self.conn.commit()

    def get_film(self, code):
        self.cursor.execute("SELECT file_id, caption FROM films WHERE code = ?", (code,))
        row = self.cursor.fetchone()
        if row:
            return {'file_id': row[0], 'caption': row[1]}
        return None
        
    def delete_film(self, code):
        self.cursor.execute("DELETE FROM films WHERE code = ?", (code,))
        self.conn.commit()
        return self.cursor.rowcount > 0

    def search_films(self, query):
        """Kino kodiga yoki sarlavhasiga qarab kinolarni qidiradi."""
        query = f"%{query}%"
        self.cursor.execute("SELECT code, caption FROM films WHERE code LIKE ? OR caption LIKE ? LIMIT 10", (query, query))
        rows = self.cursor.fetchall()
        return [{'code': row[0], 'caption': row[1]} for row in rows]

    # --- ADMIN AMALLARI ---
    def add_admin(self, user_id):
        try:
            self.cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def remove_admin(self, user_id):
        self.cursor.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        self.conn.commit()
        return self.cursor.rowcount > 0

    def is_admin(self, user_id):
        self.cursor.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone() is not None

db = Database(DB_NAME)

# ----------------- 3. YORDAMCHI FUNKSIYALAR VA KLAVIATURALAR -----------------

def get_main_keyboard():
    return types.ReplyKeyboardRemove()

def get_super_admin_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(types.KeyboardButton("🎬 Kino Qo'shish"), types.KeyboardButton("🗑️ Kino O'chirish"),
                 types.KeyboardButton("➕ Admin Qo'shish"), types.KeyboardButton("➖ Admin O'chirish"),
                 types.KeyboardButton("📊 Statistika"), types.KeyboardButton("📢 Reklama"),
                 types.KeyboardButton("❌ Bekor Qilish"))
    return keyboard

def get_regular_admin_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(types.KeyboardButton("🎬 Kino Qo'shish"), types.KeyboardButton("🗑️ Kino O'chirish"),
                 types.KeyboardButton("📊 Statistika"), types.KeyboardButton("📢 Reklama"),
                 types.KeyboardButton("❌ Bekor Qilish"))
    return keyboard

def get_cancel_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True).add(types.KeyboardButton("❌ Bekor Qilish"))
    return keyboard

def check_subscription(user_id, channel_id):
    try:
        member = bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        return member.status not in ['left', 'kicked']
    except Exception as e:
        logging.error(f"Obunani tekshirishda xatolik yuz berdi ({channel_id}): {e}")
        return False

def send_main_menu(chat_id):
    bot.send_message(
        chat_id,
        "🎬 Botimizga xush kelibsiz! Kino kodini yuboring. \n\nMasalan: 101",
        reply_markup=get_main_keyboard()
    )

def get_current_keyboard(user_id):
    if db.is_admin(user_id):
        return get_super_admin_keyboard() if user_id == ADMINS[0] else get_regular_admin_keyboard()
    return get_main_keyboard()

# ----------------- 4. ASOSIY HANDLERLAR (/start, Obuna) -----------------

@bot.message_handler(commands=['start', 'admin'])
def send_welcome(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # YANGI: Foydalanuvchini DBga qo'shish/faolligini yangilash
    db.add_user(user_id) 
    
    # Holatni tozalash
    user_states.pop(chat_id, None)
    user_data.pop(chat_id, None)
    
    # Obunani tekshirish
    not_subscribed_channels = [ch for ch in CHANNELS if not check_subscription(user_id, ch)]

    if not_subscribed_channels:
        # --- Obuna shartlari bajarilmagan ---
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        for channel_username in not_subscribed_channels:
            channel_link = f"https://t.me/{channel_username.strip('@')}"
            keyboard.add(types.InlineKeyboardButton(text=f"➕ {channel_username}", url=channel_link))
        keyboard.add(types.InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_subs"))
        bot.send_message(
            chat_id,
            "Botdan foydalanish uchun quyidagi kanallarga obuna bo'lishingiz shart:",
            reply_markup=keyboard
        )
    else:
        # --- Obuna shartlari bajarilgan ---
        if db.is_admin(user_id):
            keyboard = get_current_keyboard(user_id)
            bot.send_message(chat_id, "🛠️ Admin Panelga xush kelibsiz! Marhamat, kerakli amalni tanlang:", reply_markup=keyboard)
        else:
            send_main_menu(chat_id)

@bot.callback_query_handler(func=lambda call: call.data == "check_subs")
def check_subscription_callback(call):
    user_id = call.from_user.id
    not_subscribed_channels = [ch for ch in CHANNELS if not check_subscription(user_id, ch)]
            
    bot.answer_callback_query(call.id, "Obuna tekshirilmoqda...")

    if not_subscribed_channels:
        # ... (Qayta obuna tugmalari) ...
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        for channel_username in not_subscribed_channels:
            channel_link = f"https://t.me/{channel_username.strip('@')}"
            keyboard.add(types.InlineKeyboardButton(text=f"➕ {channel_username}", url=channel_link))
        keyboard.add(types.InlineKeyboardButton(text="✅ Obunani qayta tekshirish", callback_data="check_subs"))

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Iltimos, avval barcha kanallarga obuna bo'ling:",
            reply_markup=keyboard
        )
    else:
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
        if db.is_admin(user_id):
            keyboard = get_current_keyboard(user_id)
            bot.send_message(call.message.chat.id, "✅ Obunangiz tekshirildi. Admin panelga xush kelibsiz!", reply_markup=keyboard)
        else:
            send_main_menu(call.message.chat.id)

# ----------------- 5. ADMIN PANEL HANDLERLARI (Reklama va Statistika qo'shildi) -----------------

@bot.message_handler(func=lambda message: message.text == "❌ Bekor Qilish" and db.is_admin(message.from_user.id))
def cancel_handler(message):
    chat_id = message.chat.id
    
    user_states.pop(chat_id, None)
    user_data.pop(chat_id, None)
        
    keyboard = get_current_keyboard(message.from_user.id)
    bot.reply_to(message, "✅ Amal bekor qilindi.", reply_markup=keyboard)

# --- STATISTIKA AMALIYOTI ---

@bot.message_handler(func=lambda message: message.text == "📊 Statistika" and db.is_admin(message.from_user.id))
def send_statistics(message):
    chat_id = message.chat.id
    
    # DBdan ma'lumotlarni olish
    total = db.count_total_users()
    blocked = db.count_blocked_users()
    active_24h = db.count_active_users()

    msg = (f"📊 **Bot Statistikasi**\n\n"
           f"👤 Jami Foydalanuvchilar: **{total}** kishi\n"
           f"🚫 Botni bloklaganlar: **{blocked}** kishi\n"
           f"🟢 Oxirgi 24 soatda faol: **{active_24h}** kishi\n")
           
    bot.send_message(chat_id, msg)

# --- REKLAMA AMALIYOTI ---

@bot.message_handler(func=lambda message: message.text == "📢 Reklama" and db.is_admin(message.from_user.id))
def broadcast_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'broadcast_waiting_for_media'
    user_data[chat_id] = {'media_file_id': None, 'media_type': None}
    
    msg = ("🖼️ **Reklama uchun rasm yoki videoni yuboring.**\n\n"
           "Agar rasm/video kerak bo'lmasa, shunchaki **skip** deb yozing.")
    
    bot.send_message(chat_id, msg, reply_markup=get_cancel_keyboard())

# 1-bosqich: Rasm/Video/Skip qabul qilish
@bot.message_handler(content_types=['text', 'photo', 'video'], func=lambda message: user_states.get(message.chat.id) == 'broadcast_waiting_for_media')
def broadcast_get_media(message):
    chat_id = message.chat.id
    
    if message.text and message.text.lower() == 'skip':
        user_data[chat_id]['media_file_id'] = None
        user_data[chat_id]['media_type'] = None
    elif message.photo:
        user_data[chat_id]['media_file_id'] = message.photo[-1].file_id
        user_data[chat_id]['media_type'] = 'photo'
    elif message.video:
        user_data[chat_id]['media_file_id'] = message.video.file_id
        user_data[chat_id]['media_type'] = 'video'
    else:
        bot.send_message(chat_id, "❌ Iltimos, faqat rasm, video yoki 'skip' yuboring.")
        return
    
    # Keyingi bosqich
    user_states[chat_id] = 'broadcast_waiting_for_caption'
    bot.send_message(chat_id, "📝 **Endi reklama matnini (caption) yuboring.**", reply_markup=get_cancel_keyboard())

# 2-bosqich: Matnni qabul qilish va yuborishni boshlash
@bot.message_handler(content_types=['text'], func=lambda message: user_states.get(message.chat.id) == 'broadcast_waiting_for_caption')
def broadcast_get_caption_and_send(message):
    chat_id = message.chat.id
    caption = message.text
    data = user_data.get(chat_id)
    
    media_file_id = data.get('media_file_id')
    media_type = data.get('media_type')
    
    # Holatlarni tozalash
    user_states.pop(chat_id, None)
    user_data.pop(chat_id, None)
    
    # Foydalanuvchilarni olish va yuborish
    target_users = db.get_all_users_for_broadcast()
    sent_count = 0
    blocked_count = 0
    
    # Yuborish haqida xabar
    bot.send_message(chat_id, f"📡 Reklama {len(target_users)} ta foydalanuvchiga yuborish boshlandi...", reply_markup=get_current_keyboard(message.from_user.id))

    for user in target_users:
        try:
            if media_type == 'photo':
                bot.send_photo(user, media_file_id, caption=caption)
            elif media_type == 'video':
                bot.send_video(user, media_file_id, caption=caption)
            else:
                bot.send_message(user, caption)
            sent_count += 1
            time.sleep(0.05) # Flood oldini olish uchun
        except Exception as e:
            if 'bot was blocked by the user' in str(e):
                db.set_user_blocked(user, 1)
                blocked_count += 1
            logging.error(f"Reklama yuborishda xato ({user}): {e}")
    
    final_msg = (f"✅ **Reklama yakunlandi!**\n\n"
                 f"➡️ Yuborildi: **{sent_count}** ta foydalanuvchiga.\n"
                 f"❌ Bloklangan: **{blocked_count}** ta foydalanuvchi.")
                 
    bot.send_message(chat_id, final_msg)

# --- KINO QO'SHISH, O'CHIRISH, ADMIN QO'SHISH, O'CHIRISH HANDLERLARI (Avvalgi kabi ishlaydi) ---

@bot.message_handler(func=lambda message: message.text == "🎬 Kino Qo'shish" and db.is_admin(message.from_user.id))
def film_add_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'waiting_for_code'
    user_data[chat_id] = {}
    bot.send_message(chat_id, "🎥 Kino uchun noyob **kodni** yuboring (Masalan: 101, B25).", reply_markup=get_cancel_keyboard())

# ... (film_add_code, film_add_caption, film_add_video, film_add_video_invalid funksiyalari avvalgi koddagi kabi kiritiladi) ...
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'waiting_for_code')
def film_add_code(message):
    chat_id = message.chat.id
    film_code = message.text.strip()
    
    if db.get_film(film_code):
        bot.send_message(chat_id, "❌ Uzr, bu **kod** allaqachon mavjud. Boshqa kod kiriting.")
        return
        
    user_data[chat_id]['code'] = film_code
    user_states[chat_id] = 'waiting_for_caption' # Keyingi bosqich
    bot.send_message(chat_id, f"📝 **{film_code}** kodiga tegishli kino uchun **matn (caption)** yuboring.", reply_markup=get_cancel_keyboard())

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'waiting_for_caption')
def film_add_caption(message):
    chat_id = message.chat.id
    
    user_data[chat_id]['caption'] = message.text
    user_states[chat_id] = 'waiting_for_video' # Keyingi bosqich
    bot.send_message(chat_id, "🎬 Endi shu kino uchun **videoni** yuboring.", reply_markup=get_cancel_keyboard())

@bot.message_handler(content_types=['video'], func=lambda message: user_states.get(message.chat.id) == 'waiting_for_video')
def film_add_video(message):
    chat_id = message.chat.id
    data = user_data.get(chat_id, {})
    
    film_code = data.get('code')
    film_caption = data.get('caption')
    file_id = message.video.file_id
    
    if film_code and film_caption:
        db.add_film(film_code, file_id, film_caption)
        
        keyboard = get_current_keyboard(message.from_user.id)
        bot.send_message(chat_id, f"✅ Kino muvaffaqiyatli qo'shildi!\nKod: **{film_code}**", reply_markup=keyboard)
    else:
        bot.send_message(chat_id, "❌ Xatolik yuz berdi. Qo'shish jarayoni bekor qilindi.", reply_markup=get_current_keyboard(message.from_user.id))

    user_states.pop(chat_id, None)
    user_data.pop(chat_id, None)
    
@bot.message_handler(content_types=['text', 'photo', 'document', 'audio', 'voice'], func=lambda message: user_states.get(message.chat.id) == 'waiting_for_video')
def film_add_video_invalid(message):
    bot.send_message(message.chat.id, "❌ Iltimos, **faqat video faylini** yuboring.")
    
@bot.message_handler(func=lambda message: message.text == "🗑️ Kino O'chirish" and db.is_admin(message.from_user.id))
def film_delete_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'delete_waiting_for_code'
    bot.send_message(chat_id, "🗑️ O'chirmoqchi bo'lgan kinoning **kodini** yuboring.", reply_markup=get_cancel_keyboard())

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'delete_waiting_for_code')
def film_delete_code(message):
    chat_id = message.chat.id
    film_code = message.text.strip()
    
    if db.delete_film(film_code):
        msg = f"✅ **{film_code}** kodli kino ma'lumotlar bazasidan o'chirildi."
    else:
        msg = f"❌ Uzr, **{film_code}** kodli kino topilmadi."

    keyboard = get_current_keyboard(message.from_user.id)
    bot.send_message(chat_id, msg, reply_markup=keyboard)
    user_states.pop(chat_id, None)

@bot.message_handler(func=lambda message: message.text == "➕ Admin Qo'shish" and message.from_user.id == ADMINS[0])
def admin_add_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = 'admin_add_waiting_for_id'
    bot.send_message(chat_id, "➕ Admin qilmoqchi bo'lgan foydalanuvchining **Telegram ID'sini** yuboring.", reply_markup=get_cancel_keyboard())

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'admin_add_waiting_for_id')
def admin_add_id(message):
    chat_id = message.chat.id
    try:
        user_id = int(message.text.strip())
    except ValueError:
        bot.send_message(chat_id, "❌ ID faqat raqamlardan iborat bo'lishi kerak. Qayta urinib ko'ring.")
        return
        
    if db.add_admin(user_id):
        bot.send_message(chat_id, f"✅ **{user_id}** ID muvaffaqiyatli adminlikka qo'shildi.", reply_markup=get_current_keyboard(message.from_user.id))
    else:
        bot.send_message(chat_id, f"❌ **{user_id}** ID allaqachon adminlar ro'yxatida mavjud.")

    user_states.pop(chat_id, None)

@bot.message_handler(func=lambda message: message.text == "➖ Admin O'chirish" and message.from_user.id == ADMINS[0])
def admin_remove_start(message):
    chat_id = message.chat.id
    admin_list = "\n".join([str(uid) for uid in db.get_all_admins() if uid != ADMINS[0]])
    
    user_states[chat_id] = 'admin_remove_waiting_for_id'
    bot.send_message(chat_id, f"➖ Adminlikdan chiqarmoqchi bo'lgan foydalanuvchining **Telegram ID'sini** yuboring.\n\n"
                        f"**Hozirgi Adminlar ID'lari:**\n{admin_list}", reply_markup=get_cancel_keyboard())

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == 'admin_remove_waiting_for_id')
def admin_remove_id(message):
    chat_id = message.chat.id
    try:
        user_id = int(message.text.strip())
    except ValueError:
        bot.send_message(chat_id, "❌ ID faqat raqamlardan iborat bo'lishi kerak. Qayta urinib ko'ring.")
        return
        
    if user_id == ADMINS[0]:
        bot.send_message(chat_id, "❌ Siz **bosh adminni** o'chira olmaysiz.", reply_markup=get_current_keyboard(message.from_user.id))
    elif db.remove_admin(user_id):
        bot.send_message(chat_id, f"✅ **{user_id}** ID adminlikdan chiqarildi.", reply_markup=get_current_keyboard(message.from_user.id))
    else:
        bot.send_message(chat_id, f"❌ **{user_id}** ID adminlar ro'yxatida mavjud emas.")

    user_states.pop(chat_id, None)


# ----------------- 6. UMUMIY MATN HANDLERI (Kod yuborish) -----------------

@bot.message_handler(func=lambda message: 
    message.text and 
    message.text not in ["🎬 Kino Qo'shish", "🗑️ Kino O'chirish", "➕ Admin Qo'shish", "➖ Admin O'chirish", "❌ Bekor Qilish", "📊 Statistika", "📢 Reklama"] and
    message.chat.id not in user_states 
)
def process_film_code(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # YANGI: Faollikni yangilash
    db.add_user(user_id) 
    
    # Obunani tekshirish
    if not all(check_subscription(user_id, ch) for ch in CHANNELS):
        send_welcome(message)
        return

    # Kodni qabul qilish
    film_code = message.text.strip()
    film_data = db.get_film(film_code)
    
    if film_data:
        file_id = film_data['file_id']
        caption = film_data['caption']
        
        try:
            bot.send_video(chat_id, video=file_id, caption=caption, reply_to_message_id=message.message_id)
        except Exception as e:
            bot.send_message(chat_id, "😔 Afsuski, bu kod bo'yicha kino fayli topilmadi yoki xatolik yuz berdi.")
            logging.error(f"Kino yuborishda xatolik: {e}")
            
    else:
        bot.send_message(chat_id, "❌ Uzr, siz kiritgan kod bo'yicha kino topilmadi. Iltimos, kodni tekshiring.")

# ----------------- 7. INLINE QUERY HANDLER (Qidiruv) -----------------

@bot.inline_handler(func=lambda query: True)
def inline_query_handler(inline_query):
    query = inline_query.query.strip()
    articles = []
    
    if not query or len(query) < 2:
        item = types.InlineQueryResultArticle(
            id='0',
            title="🔍 Kino kodini yoki nomini yozing",
            description="Qidiruv kamida 2ta harfdan iborat bo'lishi kerak.",
            input_message_content=types.InputTextMessageContent(message_text="Kino kodini yuboring. Masalan: 101") 
        )
        bot.answer_inline_query(inline_query.id, [item], cache_time=1)
        return

    search_results = db.search_films(query)

    if search_results:
        for i, film in enumerate(search_results):
            input_content = types.InputTextMessageContent(
                message_text=film['code'] 
            )
            
            keyboard = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton(text="▶️ Bu kinoni menga yubor", url=f"https://t.me/{bot.get_me().username}?start={film['code']}")
            )

            article = types.InlineQueryResultArticle(
                id=str(i + 1),
                title=f"🎬 Kod: {film['code']} - {film['caption'][:30]}...",
                description=film['caption'],
                input_message_content=input_content,
                reply_markup=keyboard 
            )
            articles.append(article)
    else:
        articles.append(
            types.InlineQueryResultArticle(
                id='-1',
                title="❌ Hech narsa topilmadi",
                description=f"'{query}' so'zi bo'yicha hech qanday kino topilmadi.",
                input_message_content=types.InputTextMessageContent(message_text=f"Uzr, '{query}' bo'yicha kino topilmadi.")
            )
        )
        
    bot.answer_inline_query(inline_query.id, articles, cache_time=300)


# --- BOTNI ISHGA TUSHIRISH ---

if __name__ == '__main__':
    logging.info("Bot ishga tushirildi...")
    bot.infinity_polling(skip_pending=True)